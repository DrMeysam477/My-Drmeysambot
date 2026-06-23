import os
import time
import json
import math
import sqlite3
import logging
import asyncio
import threading
from datetime import datetime, timezone

import aiohttp
import numpy as np
import pandas as pd
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
PORT = int(os.getenv("PORT", "10000"))

OKX_BASE_URL = "https://www.okx.com"
DB_PATH = os.getenv("DB_PATH", "signals.db")

SCAN_INTERVAL_SECONDS = 900
TOP_SYMBOLS_LIMIT = 100
HTTP_TIMEOUT = 15
MAX_CONCURRENT_REQUESTS = 8

TELEGRAM_SEND = os.getenv("TELEGRAM_SEND", "0") == "1"

BASE_MIN_SCORE = 78
RANGE_MARKET_MIN_SCORE = 84
COUNTER_DAILY_MIN_SCORE = 88
COOLDOWN_HOURS = 6

DEFAULT_LIMIT_15M = 220
DEFAULT_LIMIT_HIGHER = 220

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

app = Flask(__name__)


@app.route("/")
def home():
    return "OKX crypto signal bot is running."


def run_flask():
    app.run(host="0.0.0.0", port=PORT)


def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            inst_id TEXT NOT NULL,
            side TEXT NOT NULL,
            entry REAL NOT NULL,
            sl REAL NOT NULL,
            tp1 REAL NOT NULL,
            tp2 REAL NOT NULL,
            tp3 REAL NOT NULL,
            tp4 REAL NOT NULL,
            score REAL NOT NULL,
            grade TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            reasons TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            result TEXT,
            closed_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_signals_inst_side_status
        ON signals(inst_id, side, status)
        """
    )

    conn.commit()
    conn.close()


def save_signal(signal):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO signals (
            created_at, inst_id, side, entry, sl, tp1, tp2, tp3, tp4,
            score, grade, risk_level, reasons, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """,
        (
            now_utc_iso(),
            signal["inst_id"],
            signal["side"],
            signal["entry"],
            signal["sl"],
            signal["tp1"],
            signal["tp2"],
            signal["tp3"],
            signal["tp4"],
            signal["score"],
            signal["grade"],
            signal["risk_level"],
            json.dumps(signal["reasons"], ensure_ascii=False),
        ),
    )

    conn.commit()
    conn.close()


def has_recent_or_open_signal(inst_id, side):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT created_at, status
        FROM signals
        WHERE inst_id = ? AND side = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (inst_id, side),
    )

    row = cur.fetchone()
    conn.close()

    if not row:
        return False

    created_at, status = row

    if status == "OPEN":
        return True

    try:
        created_dt = datetime.fromisoformat(created_at)
        age_hours = (datetime.now(timezone.utc) - created_dt).total_seconds() / 3600
        return age_hours < COOLDOWN_HOURS
    except Exception:
        return True


def get_open_signals():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, inst_id, side, entry, sl, tp1, tp2, tp3, tp4
        FROM signals
        WHERE status = 'OPEN'
        """
    )

    rows = cur.fetchall()
    conn.close()
    return rows


def close_signal(signal_id, result):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE signals
        SET status = 'CLOSED', result = ?, closed_at = ?
        WHERE id = ?
        """,
        (result, now_utc_iso(), signal_id),
    )

    conn.commit()
    conn.close()


async def okx_get(session, endpoint, params=None):
    url = f"{OKX_BASE_URL}{endpoint}"

    try:
        async with session.get(url, params=params, timeout=HTTP_TIMEOUT) as response:
            data = await response.json()

        if data.get("code") != "0":
            logging.warning("OKX error %s params=%s data=%s", endpoint, params, data)
            return None

        return data.get("data", [])

    except Exception as exc:
        logging.warning("HTTP error %s params=%s err=%s", endpoint, params, exc)
        return None


async def fetch_top_usdt_swap_symbols(session):
    data = await okx_get(
        session,
        "/api/v5/market/tickers",
        {"instType": "SWAP"},
    )

    if not data:
        return []

    symbols = []

    for item in data:
        inst_id = item.get("instId", "")
        if not inst_id.endswith("-USDT-SWAP"):
            continue

        try:
            vol_quote = float(item.get("volCcy24h", 0) or 0)
            last = float(item.get("last", 0) or 0)
        except Exception:
            continue

        if vol_quote <= 0 or last <= 0:
            continue

        symbols.append((inst_id, vol_quote))

    symbols.sort(key=lambda x: x[1], reverse=True)
    return [x[0] for x in symbols[:TOP_SYMBOLS_LIMIT]]


async def fetch_candles(session, inst_id, bar="15m", limit=200):
    data = await okx_get(
        session,
        "/api/v5/market/candles",
        {
            "instId": inst_id,
            "bar": bar,
            "limit": str(limit),
        },
    )

    if not data:
        return None

    rows = []

    for c in reversed(data):
        try:
            rows.append(
                {
                    "ts": pd.to_datetime(int(c[0]), unit="ms", utc=True),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                    "vol_ccy": float(c[6]) if len(c) > 6 else 0.0,
                    "vol_quote": float(c[7]) if len(c) > 7 else 0.0,
                }
            )
        except Exception:
            continue

    df = pd.DataFrame(rows)

    if len(df) < 80:
        return None

    return df


async def fetch_order_book(session, inst_id):
    data = await okx_get(
        session,
        "/api/v5/market/books",
        {
            "instId": inst_id,
            "sz": "50",
        },
    )

    if not data:
        return None

    try:
        book = data[0]
        bids = [(float(x[0]), float(x[1])) for x in book.get("bids", [])]
        asks = [(float(x[0]), float(x[1])) for x in book.get("asks", [])]

        if not bids or not asks:
            return None

        best_bid = bids[0][0]
        best_ask = asks[0][0]
        mid = (best_bid + best_ask) / 2
        spread_pct = ((best_ask - best_bid) / mid) * 100

        bid_depth = sum(price * size for price, size in bids[:20])
        ask_depth = sum(price * size for price, size in asks[:20])
        imbalance = bid_depth / ask_depth if ask_depth > 0 else 1

        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": spread_pct,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "imbalance": imbalance,
        }

    except Exception:
        return None


async def fetch_open_interest(session, inst_id):
    data = await okx_get(
        session,
        "/api/v5/public/open-interest",
        {
            "instType": "SWAP",
            "instId": inst_id,
        },
    )

    if not data:
        return None

    try:
        item = data[0]
        return float(item.get("oiCcy", 0) or item.get("oi", 0) or 0)
    except Exception:
        return None


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    value = 100 - (100 / (1 + rs))
    return value.fillna(50)


def atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def macd(series):
    fast = ema(series, 12)
    slow = ema(series, 26)
    line = fast - slow
    signal = ema(line, 9)
    hist = line - signal
    return line, signal, hist


def bollinger(series, period=20, std_mult=2):
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    width = ((upper - lower) / mid) * 100
    return upper, mid, lower, width


def ichimoku(df):
    high_9 = df["high"].rolling(9).max()
    low_9 = df["low"].rolling(9).min()
    tenkan = (high_9 + low_9) / 2

    high_26 = df["high"].rolling(26).max()
    low_26 = df["low"].rolling(26).min()
    kijun = (high_26 + low_26) / 2

    span_a = ((tenkan + kijun) / 2).shift(26)

    high_52 = df["high"].rolling(52).max()
    low_52 = df["low"].rolling(52).min()
    span_b = ((high_52 + low_52) / 2).shift(26)

    return tenkan, kijun, span_a, span_b


def add_indicators(df):
    df = df.copy()

    df["ema20"] = ema(df["close"], 20)
    df["ema50"] = ema(df["close"], 50)
    df["ema100"] = ema(df["close"], 100)
    df["ema200"] = ema(df["close"], 200)

    df["rsi"] = rsi(df["close"], 14)
    df["atr"] = atr(df, 14)

    df["macd"], df["macd_signal"], df["macd_hist"] = macd(df["close"])

    df["bb_upper"], df["bb_mid"], df["bb_lower"], df["bb_width"] = bollinger(df["close"])

    df["ichimoku_tenkan"], df["ichimoku_kijun"], df["ichimoku_span_a"], df["ichimoku_span_b"] = ichimoku(df)

    df["volume_ma20"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma20"].replace(0, np.nan)

    df["body"] = (df["close"] - df["open"]).abs()
    df["range"] = df["high"] - df["low"]
    df["body_ratio"] = df["body"] / df["range"].replace(0, np.nan)

    return df.dropna().reset_index(drop=True)


def detect_trend(df):
    last = df.iloc[-1]

    bullish = (
        last["close"] > last["ema20"] > last["ema50"]
        and last["ema50"] > last["ema100"]
    )

    bearish = (
        last["close"] < last["ema20"] < last["ema50"]
        and last["ema50"] < last["ema100"]
    )

    if bullish:
        return "BULLISH"

    if bearish:
        return "BEARISH"

    return "RANGE"


def detect_daily_bias(df):
    last = df.iloc[-1]

    bullish = last["close"] > last["ema50"] and last["ema50"] > last["ema100"]
    bearish = last["close"] < last["ema50"] and last["ema50"] < last["ema100"]

    if bullish:
        return "BULLISH"

    if bearish:
        return "BEARISH"

    return "NEUTRAL"


def market_structure(df):
    recent = df.tail(20)

    last_high = recent["high"].iloc[-1]
    prev_high = recent["high"].iloc[:-1].max()

    last_low = recent["low"].iloc[-1]
    prev_low = recent["low"].iloc[:-1].min()

    close = recent["close"].iloc[-1]

    if close > prev_high:
        return "BULLISH_BREAK"

    if close < prev_low:
        return "BEARISH_BREAK"

    if last_high < prev_high and last_low > prev_low:
        return "COMPRESSION"

    return "NORMAL"


def is_range_market(df):
    last = df.iloc[-1]
    atr_pct = (last["atr"] / last["close"]) * 100

    return (
        last["bb_width"] < 2.2
        or atr_pct < 0.35
        or detect_trend(df) == "RANGE"
    )


def is_extreme_volatility(df):
    last = df.iloc[-1]
    atr_pct = (last["atr"] / last["close"]) * 100
    return atr_pct > 3.5


def anti_fomo_filter(df, side):
    last = df.iloc[-1]

    distance_from_ema20 = abs(last["close"] - last["ema20"]) / last["ema20"] * 100
    atr_pct = last["atr"] / last["close"] * 100

    if distance_from_ema20 > max(2.5, atr_pct * 1.8):
        return False, "قیمت بیش از حد از EMA20 فاصله دارد"

    if side == "LONG" and last["rsi"] > 74:
        return False, "RSI برای لانگ بیش از حد بالا است"

    if side == "SHORT" and last["rsi"] < 26:
        return False, "RSI برای شورت بیش از حد پایین است"

    return True, "Anti-FOMO تایید شد"


def fake_breakout_filter(df, side):
    last = df.iloc[-1]
    previous = df.iloc[-2]
    recent = df.tail(25)

    high_level = recent["high"].iloc[:-1].max()
    low_level = recent["low"].iloc[:-1].min()

    if side == "LONG":
        broke_high = last["high"] > high_level
        closed_weak = last["close"] < high_level
        upper_wick = last["high"] - max(last["open"], last["close"])
        if broke_high and closed_weak and upper_wick > last["body"]:
            return False, "احتمال Fake Breakout صعودی"

    if side == "SHORT":
        broke_low = last["low"] < low_level
        closed_weak = last["close"] > low_level
        lower_wick = min(last["open"], last["close"]) - last["low"]
        if broke_low and closed_weak and lower_wick > last["body"]:
            return False, "احتمال Fake Breakout نزولی"

    if previous["volume"] > last["volume"] * 1.8 and last["body_ratio"] < 0.35:
        return False, "کندل شکست قدرت کافی ندارد"

    return True, "Fake Breakout رد شد"


def liquidity_filter(book):
    if not book:
        return False, "Order Book دریافت نشد"

    if book["spread_pct"] > 0.12:
        return False, f"اسپرد بالا است: {book['spread_pct']:.3f}%"

    total_depth = book["bid_depth"] + book["ask_depth"]

    if total_depth < 150_000:
        return False, "عمق نقدینگی کم است"

    return True, "نقدینگی و اسپرد مناسب است"


def order_book_filter(book, side):
    if not book:
        return False, "Order Book نامعتبر است"

    imbalance = book["imbalance"]

    if side == "LONG" and imbalance < 0.85:
        return False, "فشار فروش در Order Book بیشتر است"

    if side == "SHORT" and imbalance > 1.18:
        return False, "فشار خرید در Order Book بیشتر است"

    return True, "Order Book تایید شد"


def open_interest_filter(oi):
    if oi is None:
        return False, "Open Interest دریافت نشد"

    if oi <= 0:
        return False, "Open Interest نامعتبر است"

    return True, "Open Interest معتبر است"


def candle_power_filter(df, side):
    last = df.iloc[-1]

    if last["body_ratio"] < 0.35:
        return False, "بدنه کندل ضعیف است"

    if side == "LONG" and last["close"] <= last["open"]:
        return False, "کندل آخر صعودی نیست"

    if side == "SHORT" and last["close"] >= last["open"]:
        return False, "کندل آخر نزولی نیست"

    return True, "قدرت کندل تایید شد"


def calculate_targets(df, side):
    last = df.iloc[-1]
    entry = float(last["close"])
    current_atr = float(last["atr"])

    if side == "LONG":
        sl = entry - current_atr * 1.35
        tp1 = entry + current_atr * 1.0
        tp2 = entry + current_atr * 1.7
        tp3 = entry + current_atr * 2.4
        tp4 = entry + current_atr * 3.2
    else:
        sl = entry + current_atr * 1.35
        tp1 = entry - current_atr * 1.0
        tp2 = entry - current_atr * 1.7
        tp3 = entry - current_atr * 2.4
        tp4 = entry - current_atr * 3.2

    return {
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "tp4": tp4,
    }


def grade_from_score(score):
    if score >= 92:
        return "A+"
    if score >= 85:
        return "A"
    if score >= 78:
        return "B"
    if score >= 70:
        return "C"
    return "X"


def risk_from_score(score):
    if score >= 92:
        return "ریسک پیشنهادی: بالا اما کنترل‌شده | کیفیت A+"
    if score >= 85:
        return "ریسک پیشنهادی: متوسط رو به بالا | کیفیت A"
    if score >= 78:
        return "ریسک پیشنهادی: متوسط | کیفیت B"
    return "ریسک پیشنهادی: پایین | فقط برای بررسی"


def score_signal(
    side,
    df15,
    df1h,
    df4h,
    df1d,
    btc15,
    btc1h,
    book,
    oi,
):
    score = 0
    reasons = []
    mandatory_ok = True

    last = df15.iloc[-1]

    trend15 = detect_trend(df15)
    trend1h = detect_trend(df1h)
    trend4h = detect_trend(df4h)
    daily_bias = detect_daily_bias(df1d)

    btc_trend15 = detect_trend(btc15)
    btc_trend1h = detect_trend(btc1h)

    market_mode = "RANGE" if is_range_market(df15) else "NORMAL"

    if side == "LONG":
        if trend15 == "BULLISH":
            score += 12
            reasons.append("روند 15m صعودی")
        else:
            mandatory_ok = False

        if trend1h != "BEARISH":
            score += 10
            reasons.append("روند 1H مخالف لانگ نیست")
        else:
            mandatory_ok = False

        if trend4h != "BEARISH":
            score += 10
            reasons.append("روند 4H مخالف لانگ نیست")

        if daily_bias == "BULLISH":
            score += 8
            reasons.append("Daily صعودی است")
        elif daily_bias == "NEUTRAL":
            score += 3
            reasons.append("Daily خنثی است")
        else:
            reasons.append("Daily مخالف لانگ است")

        if btc_trend15 != "BEARISH" and btc_trend1h != "BEARISH":
            score += 8
            reasons.append("BTC مخالف لانگ نیست")
        else:
            score -= 8
            reasons.append("BTC فشار نزولی دارد")

        if last["rsi"] > 50 and last["rsi"] < 72:
            score += 7
            reasons.append("RSI مناسب لانگ")

        if last["macd_hist"] > 0 and last["macd"] > last["macd_signal"]:
            score += 8
            reasons.append("MACD صعودی")

        if last["close"] > last["bb_mid"]:
            score += 4
            reasons.append("قیمت بالای میدل باند بولینگر")

        cloud_top = max(last["ichimoku_span_a"], last["ichimoku_span_b"])
        if last["close"] > cloud_top and last["ichimoku_tenkan"] > last["ichimoku_kijun"]:
            score += 9
            reasons.append("ایچیموکو صعودی")

        if last["volume_ratio"] >= 1.15:
            score += 6
            reasons.append("حجم بالاتر از میانگین")

        structure = market_structure(df15)
        if structure in ["BULLISH_BREAK", "NORMAL"]:
            score += 5
            reasons.append("ساختار بازار مناسب لانگ")

    else:
        if trend15 == "BEARISH":
            score += 12
            reasons.append("روند 15m نزولی")
        else:
            mandatory_ok = False

        if trend1h != "BULLISH":
            score += 10
            reasons.append("روند 1H مخالف شورت نیست")
        else:
            mandatory_ok = False

        if trend4h != "BULLISH":
            score += 10
            reasons.append("روند 4H مخالف شورت نیست")

        if daily_bias == "BEARISH":
            score += 8
            reasons.append("Daily نزولی است")
        elif daily_bias == "NEUTRAL":
            score += 3
            reasons.append("Daily خنثی است")
        else:
            reasons.append("Daily مخالف شورت است")

        if btc_trend15 != "BULLISH" and btc_trend1h != "BULLISH":
            score += 8
            reasons.append("BTC مخالف شورت نیست")
        else:
            score -= 8
            reasons.append("BTC فشار صعودی دارد")

        if last["rsi"] < 50 and last["rsi"] > 28:
            score += 7
            reasons.append("RSI مناسب شورت")

        if last["macd_hist"] < 0 and last["macd"] < last["macd_signal"]:
            score += 8
            reasons.append("MACD نزولی")

        if last["close"] < last["bb_mid"]:
            score += 4
            reasons.append("قیمت پایین میدل باند بولینگر")

        cloud_bottom = min(last["ichimoku_span_a"], last["ichimoku_span_b"])
        if last["close"] < cloud_bottom and last["ichimoku_tenkan"] < last["ichimoku_kijun"]:
            score += 9
            reasons.append("ایچیموکو نزولی")

        if last["volume_ratio"] >= 1.15:
            score += 6
            reasons.append("حجم بالاتر از میانگین")

        structure = market_structure(df15)
        if structure in ["BEARISH_BREAK", "NORMAL"]:
            score += 5
            reasons.append("ساختار بازار مناسب شورت")

    ok, reason = candle_power_filter(df15, side)
    if ok:
        score += 5
        reasons.append(reason)
    else:
        score -= 6
        reasons.append(reason)

    ok, reason = anti_fomo_filter(df15, side)
    if ok:
        score += 5
        reasons.append(reason)
    else:
        score -= 10
        mandatory_ok = False
        reasons.append(reason)

    ok, reason = fake_breakout_filter(df15, side)
    if ok:
        score += 5
        reasons.append(reason)
    else:
        score -= 10
        mandatory_ok = False
        reasons.append(reason)

    ok, reason = liquidity_filter(book)
    if ok:
        score += 7
        reasons.append(reason)
    else:
        mandatory_ok = False
        reasons.append(reason)

    ok, reason = order_book_filter(book, side)
    if ok:
        score += 5
        reasons.append(reason)
    else:
        score -= 5
        reasons.append(reason)

    ok, reason = open_interest_filter(oi)
    if ok:
        score += 3
        reasons.append(reason)
    else:
        reasons.append(reason)

    if is_extreme_volatility(df15):
        score -= 10
        reasons.append("نوسان بیش از حد؛ امتیاز کاهش یافت")

    min_score = BASE_MIN_SCORE

    if market_mode == "RANGE":
        min_score = RANGE_MARKET_MIN_SCORE
        reasons.append("بازار رنج است؛ حداقل امتیاز سخت‌گیرانه‌تر شد")

    if side == "LONG" and daily_bias == "BEARISH":
        min_score = max(min_score, COUNTER_DAILY_MIN_SCORE)

    if side == "SHORT" and daily_bias == "BULLISH":
        min_score = max(min_score, COUNTER_DAILY_MIN_SCORE)

    score = max(0, min(100, score))
    grade = grade_from_score(score)

    return {
        "score": score,
        "grade": grade,
        "reasons": reasons,
        "mandatory_ok": mandatory_ok,
        "min_score": min_score,
        "market_mode": market_mode,
        "daily_bias": daily_bias,
    }


def build_signal_message(signal):
    reasons_text = "\n".join([f"• {r}" for r in signal["reasons"][:12]])

    return f"""
🚨 سیگنال جدید {signal['side']}

📌 ارز: {signal['inst_id']}
⭐ امتیاز: {signal['score']:.1f}/100
🏆 گرید: {signal['grade']}
🧠 ریسک: {signal['risk_level']}

🎯 Entry: {signal['entry']:.8f}
🛑 SL: {signal['sl']:.8f}

✅ TP1: {signal['tp1']:.8f}
✅ TP2: {signal['tp2']:.8f}
✅ TP3: {signal['tp3']:.8f}
✅ TP4: {signal['tp4']:.8f}

📊 وضعیت بازار: {signal['market_mode']}
📅 Daily Bias: {signal['daily_bias']}

📍 دلایل تایید:
{reasons_text}

⚠️ این پیام فقط سیگنال تحلیلی است، نه دستور خرید یا فروش.
""".strip()


async def analyze_symbol(session, semaphore, inst_id, btc15, btc1h):
    async with semaphore:
        try:
            df15, df1h, df4h, df1d, book, oi = await asyncio.gather(
                fetch_candles(session, inst_id, "15m", DEFAULT_LIMIT_15M),
                fetch_candles(session, inst_id, "1H", DEFAULT_LIMIT_HIGHER),
                fetch_candles(session, inst_id, "4H", DEFAULT_LIMIT_HIGHER),
                fetch_candles(session, inst_id, "1D", DEFAULT_LIMIT_HIGHER),
                fetch_order_book(session, inst_id),
                fetch_open_interest(session, inst_id),
            )

            if any(x is None for x in [df15, df1h, df4h, df1d]):
                return None

            df15 = add_indicators(df15)
            df1h = add_indicators(df1h)
            df4h = add_indicators(df4h)
            df1d = add_indicators(df1d)

            candidates = []

            for side in ["LONG", "SHORT"]:
                if has_recent_or_open_signal(inst_id, side):
                    continue

                analysis = score_signal(
                    side=side,
                    df15=df15,
                    df1h=df1h,
                    df4h=df4h,
                    df1d=df1d,
                    btc15=btc15,
                    btc1h=btc1h,
                    book=book,
                    oi=oi,
                )

                if not analysis["mandatory_ok"]:
                    continue

                if analysis["score"] < analysis["min_score"]:
                    continue

                targets = calculate_targets(df15, side)

                signal = {
                    "inst_id": inst_id,
                    "side": side,
                    **targets,
                    "score": analysis["score"],
                    "grade": analysis["grade"],
                    "risk_level": risk_from_score(analysis["score"]),
                    "reasons": analysis["reasons"],
                    "market_mode": analysis["market_mode"],
                    "daily_bias": analysis["daily_bias"],
                }

                candidates.append(signal)

            if not candidates:
                return None

            candidates.sort(key=lambda x: x["score"], reverse=True)
            return candidates[0]

        except Exception as exc:
            logging.warning("Analyze error %s: %s", inst_id, exc)
            return None


async def track_open_signals(session):
    open_signals = get_open_signals()

    if not open_signals:
        return []

    results = []

    for row in open_signals:
        signal_id, inst_id, side, entry, sl, tp1, tp2, tp3, tp4 = row
        df = await fetch_candles(session, inst_id, "15m", 10)

        if df is None or df.empty:
            continue

        recent = df.tail(5)
        high = recent["high"].max()
        low = recent["low"].min()

        result = None

        if side == "LONG":
            if low <= sl:
                result = "SL"
            elif high >= tp4:
                result = "TP4"
            elif high >= tp3:
                result = "TP3"
            elif high >= tp2:
                result = "TP2"
            elif high >= tp1:
                result = "TP1"

        if side == "SHORT":
            if high >= sl:
                result = "SL"
            elif low <= tp4:
                result = "TP4"
            elif low <= tp3:
                result = "TP3"
            elif low <= tp2:
                result = "TP2"
            elif low <= tp1:
                result = "TP1"

        if result:
            close_signal(signal_id, result)
            results.append((inst_id, side, result))

    return results


async def run_scan(bot=None, manual=False):
    started = time.time()

    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT_REQUESTS * 2)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async with aiohttp.ClientSession(connector=connector) as session:
        tracking_results = await track_open_signals(session)

        symbols = await fetch_top_usdt_swap_symbols(session)

        if not symbols:
            logging.warning("No symbols fetched")
            return {
                "sent": 0,
                "found": 0,
                "tracked": tracking_results,
                "duration": time.time() - started,
            }

        btc15_raw, btc1h_raw = await asyncio.gather(
            fetch_candles(session, "BTC-USDT-SWAP", "15m", DEFAULT_LIMIT_15M),
            fetch_candles(session, "BTC-USDT-SWAP", "1H", DEFAULT_LIMIT_HIGHER),
        )

        if btc15_raw is None or btc1h_raw is None:
            logging.warning("BTC data unavailable")
            return {
                "sent": 0,
                "found": 0,
                "tracked": tracking_results,
                "duration": time.time() - started,
            }

        btc15 = add_indicators(btc15_raw)
        btc1h = add_indicators(btc1h_raw)

        tasks = [
            analyze_symbol(session, semaphore, inst_id, btc15, btc1h)
            for inst_id in symbols
        ]

        raw_results = await asyncio.gather(*tasks)
        signals = [x for x in raw_results if x is not None]
        signals.sort(key=lambda x: x["score"], reverse=True)

        sent = 0

        for signal in signals:
            save_signal(signal)

            message = build_signal_message(signal)

            if TELEGRAM_SEND and bot and CHAT_ID:
                await bot.send_message(chat_id=CHAT_ID, text=message)
                sent += 1
                await asyncio.sleep(0.8)
            else:
                logging.info("TEST SIGNAL:\n%s", message)

        duration = time.time() - started

        logging.info(
            "Scan done | symbols=%s found=%s sent=%s duration=%.1fs tracked=%s",
            len(symbols),
            len(signals),
            sent,
            duration,
            len(tracking_results),
        )

        return {
            "sent": sent,
            "found": len(signals),
            "tracked": tracking_results,
            "duration": duration,
        }


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = "ارسال فعال" if TELEGRAM_SEND else "حالت تست؛ ارسال سیگنال غیرفعال"

    text = f"""
✅ ربات تحلیل‌گر OKX فعال است.

⏱ اسکن خودکار: هر ۱۵ دقیقه
📊 بازار: 100 ارز برتر USDT-SWAP
🧠 تایم‌فریم‌ها: 15m + 1H + 4H + 1D
📌 حالت: {mode}

دستورها:
/scan اجرای اسکن دستی
/status

async def price_command(update, context):
    try:
        if not context.args:
            await update.message.reply_text("مثال:\n/price BTC")
            return

        coin = context.args[0].upper()
        inst_id = f"{coin}-USDT-SWAP"

        url = f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                data = await response.json()

        if data.get("code") != "0" or not data.get("data"):
            await update.message.reply_text(f"قیمت {coin} از OKX پیدا نشد.")
            return

        ticker = data["data"][0]
        last_price = ticker.get("last")
        high_24h = ticker.get("high24h")
        low_24h = ticker.get("low24h")
        volume = ticker.get("volCcy24h")

        text = f"""
OKX Price ✅

Symbol: {inst_id}
Last: {last_price}
24H High: {high_24h}
24H Low: {low_24h}
24H Volume: {volume}
"""

        await update.message.reply_text(text)

    except Exception as e:
        await update.message.reply_text(f"خطا در دریافت قیمت از OKX:\n{e}")
