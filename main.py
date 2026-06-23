import os
import time
import math
import json
import sqlite3
import asyncio
import threading
from datetime import datetime, timezone, timedelta

import aiohttp
import numpy as np
import pandas as pd

from flask import Flask

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)


# =========================
# ENV CONFIG
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()
TELEGRAM_SEND = os.getenv("TELEGRAM_SEND", "0").strip() == "1"
PORT = int(os.getenv("PORT", "10000"))

# =========================
# STRATEGY CONFIG
# =========================

OKX_BASE_URL = "https://www.okx.com"

MARKET_TYPE = "SWAP"
QUOTE = "USDT"

TOP_MARKETS_LIMIT = 100
SCAN_INTERVAL_SECONDS = 15 * 60

COOLDOWN_HOURS = 6

MIN_SCORE_FOR_SIGNAL = 70
MIN_SCORE_RANGE_MARKET = 78

MAX_SIGNALS_PER_SCAN = 5

CANDLE_LIMIT = 180

TIMEFRAMES = {
    "15m": "15m",
    "1H": "1H",
    "4H": "4H",
    "1D": "1D",
}

DB_PATH = "signals.db"


# =========================
# FLASK HEALTH SERVER
# =========================

app = Flask(__name__)


@app.route("/")
def home():
    return "OKX Telegram Scanner is running ✅"


@app.route("/health")
def health():
    return "healthy"


def run_flask():
    app.run(host="0.0.0.0", port=PORT)


# =========================
# DATABASE
# =========================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sent_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inst_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            created_at TEXT NOT NULL,
            score REAL NOT NULL,
            entry REAL,
            tp1 REAL,
            tp2 REAL,
            sl REAL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS scan_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            scanned INTEGER,
            signals INTEGER,
            message TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def save_scan_log(scanned: int, signals: int, message: str = ""):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO scan_logs (created_at, scanned, signals, message)
            VALUES (?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                scanned,
                signals,
                message,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"save_scan_log error: {e}")


def was_signal_recently_sent(inst_id: str, direction: str) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        since = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS)

        cur.execute(
            """
            SELECT created_at FROM sent_signals
            WHERE inst_id = ? AND direction = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (inst_id, direction),
        )

        row = cur.fetchone()
        conn.close()

        if not row:
            return False

        last_time = datetime.fromisoformat(row[0])
        return last_time > since

    except Exception as e:
        print(f"was_signal_recently_sent error: {e}")
        return False


def save_signal(signal: dict):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO sent_signals
            (inst_id, direction, created_at, score, entry, tp1, tp2, sl)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.get("inst_id"),
                signal.get("direction"),
                datetime.now(timezone.utc).isoformat(),
                float(signal.get("score", 0)),
                float(signal.get("entry", 0)),
                float(signal.get("tp1", 0)),
                float(signal.get("tp2", 0)),
                float(signal.get("sl", 0)),
            ),
        )

        conn.commit()
        conn.close()

    except Exception as e:
        print(f"save_signal error: {e}")


# =========================
# OKX API
# =========================

async def okx_get(session: aiohttp.ClientSession, path: str, params: dict = None):
    url = OKX_BASE_URL + path

    try:
        async with session.get(url, params=params, timeout=15) as response:
            data = await response.json()

        if data.get("code") != "0":
            return None

        return data.get("data", [])

    except Exception as e:
        print(f"OKX GET error {path}: {e}")
        return None


async def fetch_ticker(session: aiohttp.ClientSession, inst_id: str):
    data = await okx_get(
        session,
        "/api/v5/market/ticker",
        {"instId": inst_id},
    )

    if not data:
        return None

    return data[0]


async def fetch_all_swap_tickers(session: aiohttp.ClientSession):
    data = await okx_get(
        session,
        "/api/v5/market/tickers",
        {"instType": MARKET_TYPE},
    )

    if not data:
        return []

    usdt_swaps = []

    for item in data:
        inst_id = item.get("instId", "")

        if inst_id.endswith("-USDT-SWAP"):
            try:
                vol = float(item.get("volCcy24h", 0) or 0)
                last = float(item.get("last", 0) or 0)

                if vol > 0 and last > 0:
                    item["_volume"] = vol
                    usdt_swaps.append(item)

            except Exception:
                continue

    usdt_swaps.sort(key=lambda x: x.get("_volume", 0), reverse=True)

    return usdt_swaps[:TOP_MARKETS_LIMIT]


async def fetch_candles(
    session: aiohttp.ClientSession,
    inst_id: str,
    bar: str,
    limit: int = CANDLE_LIMIT,
):
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

    for c in data:
        try:
            rows.append(
                {
                    "ts": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                    "vol_ccy": float(c[6]),
                }
            )
        except Exception:
            continue

    if len(rows) < 80:
        return None

    df = pd.DataFrame(rows)

    # OKX returns newest first. We need oldest first.
    df = df.sort_values("ts").reset_index(drop=True)

    return df


# =========================
# INDICATORS
# =========================

def ema(series: pd.Series, length: int):
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14):
    delta = series.diff()

    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.rolling(length).mean()
    avg_loss = loss.rolling(length).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    result = 100 - (100 / (1 + rs))
    return result.fillna(50)


def macd(series: pd.Series):
    fast = ema(series, 12)
    slow = ema(series, 26)

    macd_line = fast - slow
    signal_line = ema(macd_line, 9)
    hist = macd_line - signal_line

    return macd_line, signal_line, hist


def bollinger_bands(series: pd.Series, length: int = 20, mult: float = 2.0):
    mid = series.rolling(length).mean()
    std = series.rolling(length).std()

    upper = mid + mult * std
    lower = mid - mult * std

    return upper, mid, lower


def atr(df: pd.DataFrame, length: int = 14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    return true_range.rolling(length).mean()


def add_indicators(df: pd.DataFrame):
    df = df.copy()

    df["ema20"] = ema(df["close"], 20)
    df["ema50"] = ema(df["close"], 50)
    df["ema100"] = ema(df["close"], 100)

    df["rsi14"] = rsi(df["close"], 14)

    macd_line, signal_line, hist = macd(df["close"])
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"] = hist

    bb_upper, bb_mid, bb_lower = bollinger_bands(df["close"], 20, 2)
    df["bb_upper"] = bb_upper
    df["bb_mid"] = bb_mid
    df["bb_lower"] = bb_lower

    df["atr14"] = atr(df, 14)

    df["vol_ma20"] = df["volume"].rolling(20).mean()

    return df


# =========================
# MARKET ANALYSIS
# =========================

def safe_last(df: pd.DataFrame):
    if df is None or len(df) == 0:
        return None
    return df.iloc[-1]


def detect_trend(df: pd.DataFrame):
    last = safe_last(df)

    if last is None:
        return "UNKNOWN"

    close = last["close"]
    ema20_v = last["ema20"]
    ema50_v = last["ema50"]
    ema100_v = last["ema100"]

    if close > ema20_v > ema50_v > ema100_v:
        return "BULLISH"

    if close < ema20_v < ema50_v < ema100_v:
        return "BEARISH"

    return "RANGE"


def candle_power(df: pd.DataFrame):
    last = safe_last(df)

    if last is None:
        return 0

    body = abs(last["close"] - last["open"])
    full = max(last["high"] - last["low"], 1e-9)

    return body / full


def volume_power(df: pd.DataFrame):
    last = safe_last(df)

    if last is None:
        return 1

    vol = last.get("volume", 0)
    vol_ma = last.get("vol_ma20", 0)

    if not vol_ma or math.isnan(vol_ma) or vol_ma <= 0:
        return 1

    return vol / vol_ma


def is_fake_breakout_risk(df: pd.DataFrame):
    if df is None or len(df) < 30:
        return False

    last = df.iloc[-1]
    prev = df.iloc[-21:-1]

    recent_high = prev["high"].max()
    recent_low = prev["low"].min()

    close = last["close"]
    high = last["high"]
    low = last["low"]

    # wick breakout and close back inside range
    if high > recent_high and close < recent_high:
        return True

    if low < recent_low and close > recent_low:
        return True

    return False


def calculate_targets(entry: float, direction: str, atr_value: float):
    if not atr_value or math.isnan(atr_value) or atr_value <= 0:
        atr_value = entry * 0.01

    if direction == "LONG":
        sl = entry - atr_value * 1.5
        tp1 = entry + atr_value * 1.5
        tp2 = entry + atr_value * 2.5
    else:
        sl = entry + atr_value * 1.5
        tp1 = entry - atr_value * 1.5
        tp2 = entry - atr_value * 2.5

    return tp1, tp2, sl


def score_timeframe(df: pd.DataFrame):
    if df is None or len(df) < 120:
        return {
            "long": 0,
            "short": 0,
            "trend": "UNKNOWN",
            "notes": [],
        }

    df = add_indicators(df)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    trend = detect_trend(df)

    long_score = 0
    short_score = 0
    notes = []

    close = last["close"]
    ema20_v = last["ema20"]
    ema50_v = last["ema50"]
    ema100_v = last["ema100"]
    rsi_v = last["rsi14"]
    macd_hist_v = last["macd_hist"]
    macd_hist_prev = prev["macd_hist"]
    bb_upper = last["bb_upper"]
    bb_lower = last["bb_lower"]

    vol_power = volume_power(df)
    c_power = candle_power(df)

    # EMA trend
    if close > ema20_v > ema50_v:
        long_score += 18
        notes.append("قیمت بالای EMA20 و EMA50")
    elif close < ema20_v < ema50_v:
        short_score += 18
        notes.append("قیمت پایین EMA20 و EMA50")

    if ema20_v > ema50_v > ema100_v:
        long_score += 14
        notes.append("چیدمان میانگین‌ها صعودی")
    elif ema20_v < ema50_v < ema100_v:
        short_score += 14
        notes.append("چیدمان میانگین‌ها نزولی")

    # RSI
    if 50 <= rsi_v <= 68:
        long_score += 12
        notes.append("RSI مناسب برای لانگ")
    elif 32 <= rsi_v <= 50:
        short_score += 12
        notes.append("RSI مناسب برای شورت")

    if rsi_v > 75:
        long_score -= 15
        notes.append("هشدار FOMO: RSI بالا")
    if rsi_v < 25:
        short_score -= 15
        notes.append("هشدار FOMO: RSI پایین")

    # MACD
    if macd_hist_v > 0 and macd_hist_v > macd_hist_prev:
        long_score += 14
        notes.append("MACD مثبت و رو به رشد")
    elif macd_hist_v < 0 and macd_hist_v < macd_hist_prev:
        short_score += 14
        notes.append("MACD منفی و رو به ضعف")

    # Bollinger
    if close > bb_upper:
        long_score += 6
        notes.append("قدرت شکست باند بالایی")
    elif close < bb_lower:
        short_score += 6
        notes.append("قدرت شکست باند پایینی")

    # Volume
    if vol_power > 1.4:
        long_score += 8
        short_score += 8
        notes.append("حجم بالاتر از میانگین")
    elif vol_power < 0.7:
        long_score -= 5
        short_score -= 5
        notes.append("حجم ضعیف")

    # Candle power
    if c_power > 0.55:
        long_score += 5
        short_score += 5
        notes.append("کندل قدرت مناسب دارد")
    else:
        long_score -= 3
        short_score -= 3
        notes.append("کندل قدرت کافی ندارد")

    # Fake breakout
    if is_fake_breakout_risk(df):
        long_score -= 10
        short_score -= 10
        notes.append("ریسک فیک‌بریک‌اوت")

    return {
        "long": max(long_score, 0),
        "short": max(short_score, 0),
        "trend": trend,
        "notes": notes,
        "last": last,
        "df": df,
    }


def combine_analysis(inst_id: str, analyses: dict):
    score_long = 0
    score_short = 0
    notes = []

    weights = {
        "15m": 0.25,
        "1H": 0.35,
        "4H": 0.30,
        "1D": 0.10,
    }

    trends = {}

    for tf, analysis in analyses.items():
        if not analysis:
            continue

        w = weights.get(tf, 0.25)

        score_long += analysis["long"] * w
        score_short += analysis["short"] * w

        trends[tf] = analysis["trend"]

        for n in analysis.get("notes", [])[:3]:
            notes.append(f"{tf}: {n}")

    direction = None
    final_score = 0

    if score_long > score_short:
        direction = "LONG"
        final_score = score_long
    elif score_short > score_long:
        direction = "SHORT"
        final_score = score_short
    else:
        return None

    # Trend agreement bonus
    if direction == "LONG":
        if trends.get("1H") == "BULLISH":
            final_score += 8
        if trends.get("4H") == "BULLISH":
            final_score += 10
        if trends.get("1D") == "BULLISH":
            final_score += 4

    if direction == "SHORT":
        if trends.get("1H") == "BEARISH":
            final_score += 8
        if trends.get("4H") == "BEARISH":
            final_score += 10
        if trends.get("1D") == "BEARISH":
            final_score += 4

    # Penalty if higher timeframe is opposite
    if direction == "LONG" and trends.get("4H") == "BEARISH":
        final_score -= 12

    if direction == "SHORT" and trends.get("4H") == "BULLISH":
        final_score -= 12

    market_state = "TREND"

    if trends.get("1H") == "RANGE" and trends.get("4H") == "RANGE":
        market_state = "RANGE"
        final_score -= 5

    min_score = MIN_SCORE_RANGE_MARKET if market_state == "RANGE" else MIN_SCORE_FOR_SIGNAL

    tf15 = analyses.get("15m")
    tf1h = analyses.get("1H")

    if not tf15 or not tf1h:
        return None

    last = tf15["last"]

    entry = float(last["close"])
    atr_value = float(last.get("atr14", entry * 0.01))

    tp1, tp2, sl = calculate_targets(entry, direction, atr_value)

    if final_score < min_score:
        return None

    signal = {
        "inst_id": inst_id,
        "direction": direction,
        "score": round(float(final_score), 2),
        "entry": entry,
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "market_state": market_state,
        "trends": trends,
        "notes": notes[:8],
    }

    return signal


async def analyze_symbol(session: aiohttp.ClientSession, inst_id: str):
    analyses = {}

    for tf, bar in TIMEFRAMES.items():
        df = await fetch_candles(session, inst_id, bar, CANDLE_LIMIT)

        if df is None:
            return None

        analyses[tf] = score_timeframe(df)

        await asyncio.sleep(0.05)

    return combine_analysis(inst_id, analyses)


# =========================
# MESSAGE FORMAT
# =========================

def fmt_price(x):
    try:
        x = float(x)

        if x >= 100:
            return f"{x:.2f}"
        elif x >= 1:
            return f"{x:.4f}"
        else:
            return f"{x:.8f}"

    except Exception:
        return str(x)


def format_signal_message(signal: dict):
    trends = signal.get("trends", {})
    notes = signal.get("notes", [])

    notes_text = "\n".join([f"• {n}" for n in notes]) if notes else "ندارد"

    direction = signal.get("direction")

    if direction == "LONG":
        icon = "🟢"
        fa_direction = "لانگ / خرید"
    else:
        icon = "🔴"
        fa_direction = "شورت / فروش"

    text = f"""
{icon} سیگنال جدید OKX

نماد:
{signal.get("inst_id")}

جهت:
{fa_direction}

امتیاز:
{signal.get("score")}/100

وضعیت بازار:
{signal.get("market_state")}

قیمت ورود:
{fmt_price(signal.get("entry"))}

حد سود ۱:
{fmt_price(signal.get("tp1"))}

حد سود ۲:
{fmt_price(signal.get("tp2"))}

حد ضرر:
{fmt_price(signal.get("sl"))}

روند تایم‌فریم‌ها:
15m: {trends.get("15m", "-")}
1H: {trends.get("1H", "-")}
4H: {trends.get("4H", "-")}
1D: {trends.get("1D", "-")}

دلایل سیگنال:
{notes_text}

زمان:
{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

⚠️ مدیریت سرمایه فراموش نشود.
"""

    return text.strip()


def format_scan_summary(signals: list, scanned: int):
    if not signals:
        return f"""
اسکن تمام شد ✅

تعداد بازار بررسی‌شده:
{scanned}

سیگنال معتبر:
0

در این لحظه سیگنال با امتیاز کافی پیدا نشد.
""".strip()

    lines = [
        "اسکن تمام شد ✅",
        "",
        f"تعداد بازار بررسی‌شده: {scanned}",
        f"تعداد سیگنال معتبر: {len(signals)}",
        "",
        "بهترین سیگنال‌ها:",
        "",
    ]

    for i, s in enumerate(signals, start=1):
        lines.append(
            f"{i}. {s['inst_id']} | {s['direction']} | Score: {s['score']} | Entry: {fmt_price(s['entry'])}"
        )

    return "\n".join(lines)


# =========================
# TELEGRAM HELPERS
# =========================

async def send_to_chat(context: ContextTypes.DEFAULT_TYPE, text: str):
    if not TELEGRAM_SEND:
        print("TELEGRAM_SEND=0, message not sent.")
        print(text)
        return

    if not CHAT_ID:
        print("CHAT_ID not set. Cannot send message.")
        return

    try:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=text,
        )
    except Exception as e:
        print(f"send_to_chat error: {e}")


# =========================
# SCANNER
# =========================

async def run_market_scan(context: ContextTypes.DEFAULT_TYPE = None):
    print("Starting market scan...")

    signals = []
    scanned = 0

    async with aiohttp.ClientSession() as session:
        tickers = await fetch_all_swap_tickers(session)

        if not tickers:
            save_scan_log(0, 0, "No tickers from OKX")
            return {
                "signals": [],
                "scanned": 0,
                "message": "لیست بازارها از OKX دریافت نشد.",
            }

        for ticker in tickers:
            inst_id = ticker.get("instId")

            if not inst_id:
                continue

            try:
                scanned += 1

                print(f"Analyzing {scanned}/{len(tickers)}: {inst_id}")

                signal = await analyze_symbol(session, inst_id)

                if signal:
                    if was_signal_recently_sent(signal["inst_id"], signal["direction"]):
                        print(f"Cooldown active for {signal['inst_id']} {signal['direction']}")
                    else:
                        signals.append(signal)
                        save_signal(signal)

                await asyncio.sleep(0.12)

            except Exception as e:
                print(f"Analyze error for {inst_id}: {e}")
                continue

    signals.sort(key=lambda x: x.get("score", 0), reverse=True)
    signals = signals[:MAX_SIGNALS_PER_SCAN]

    save_scan_log(scanned, len(signals), "scan completed")

    if context and signals:
        for signal in signals:
            await send_to_chat(context, format_signal_message(signal))
            await asyncio.sleep(1)

    print(f"Scan finished. scanned={scanned}, signals={len(signals)}")

    return {
        "signals": signals,
        "scanned": scanned,
        "message": "scan completed",
    }


# =========================
# TELEGRAM COMMANDS
# =========================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = "فعال" if TELEGRAM_SEND else "تست / ارسال غیرفعال"

    text = f"""
✅ ربات تحلیل‌گر OKX فعال شد.

وضعیت ارسال تلگرام:
{mode}

بازار:
OKX USDT-SWAP

اسکن خودکار:
هر ۱۵ دقیقه

دستورها:

/price BTC
مشاهده قیمت بیت‌کوین از OKX

/price ETH
مشاهده قیمت اتریوم از OKX

/scan
اجرای اسکن دستی بازار

/status
نمایش وضعیت ربات

اگر /price BTC جواب بدهد یعنی اتصال OKX درست است.
"""

    await update.message.reply_text(text.strip())


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_exists = os.path.exists(DB_PATH)

    job_status = "نامشخص"
    try:
        if context.job_queue:
            jobs = context.job_queue.jobs()
            job_status = f"فعال - تعداد job: {len(jobs)}"
        else:
            job_status = "JobQueue موجود نیست"
    except Exception:
        job_status = "خطا در بررسی JobQueue"

    text = f"""
✅ وضعیت ربات

BOT_TOKEN:
{"تنظیم شده" if BOT_TOKEN else "تنظیم نشده"}

CHAT_ID:
{CHAT_ID if CHAT_ID else "تنظیم نشده"}

TELEGRAM_SEND:
{"1 - ارسال فعال" if TELEGRAM_SEND else "0 - حالت تست"}

PORT:
{PORT}

Database:
{"موجود" if db_exists else "ناموجود"}

Auto Scan:
{job_status}

تست اتصال OKX:
/price BTC

اجرای اسکن دستی:
/scan
"""

    await update.message.reply_text(text.strip())


async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text(
                "نام ارز را وارد کن.\n\nمثال:\n/price BTC"
            )
            return

        coin = context.args[0].upper()
        coin = coin.replace("USDT", "")
        coin = coin.replace("-", "")
        coin = coin.replace("/", "")

        inst_id = f"{coin}-USDT-SWAP"

        async with aiohttp.ClientSession() as session:
            ticker = await fetch_ticker(session, inst_id)

        if not ticker:
            await update.message.reply_text(
                f"❌ قیمت {coin} در OKX پیدا نشد.\n\nمثال درست:\n/price BTC"
            )
            return

        last_price = ticker.get("last", "نامشخص")
        high_24h = ticker.get("high24h", "نامشخص")
        low_24h = ticker.get("low24h", "نامشخص")
        volume_24h = ticker.get("volCcy24h", "نامشخص")

        text = f"""
✅ اتصال به OKX موفق بود

نماد:
{inst_id}

قیمت فعلی:
{last_price}

سقف ۲۴ ساعت:
{high_24h}

کف ۲۴ ساعت:
{low_24h}

حجم ۲۴ ساعت:
{volume_24h}
"""

        await update.message.reply_text(text.strip())

    except Exception as e:
        await update.message.reply_text(
            f"❌ خطا در دریافت قیمت از OKX:\n\n{e}"
        )


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "اسکن دستی شروع شد ✅\nممکن است چند دقیقه زمان ببرد..."
    )

    try:
        result = await run_market_scan(context)

        summary = format_scan_summary(
            signals=result.get("signals", []),
            scanned=result.get("scanned", 0),
        )

        await update.message.reply_text(summary)

        signals = result.get("signals", [])

        if signals:
            await update.message.reply_text("جزئیات بهترین سیگنال‌ها:")

            for signal in signals:
                await update.message.reply_text(format_signal_message(signal))
                await asyncio.sleep(0.5)

    except Exception as e:
        await update.message.reply_text(
            f"❌ خطا در اجرای اسکن:\n\n{e}"
        )


async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    print("Scheduled scan triggered.")

    try:
        result = await run_market_scan(context)

        signals = result.get("signals", [])
        scanned = result.get("scanned", 0)

        if signals:
            summary = format_scan_summary(signals, scanned)
            await send_to_chat(context, summary)
        else:
            print("Scheduled scan: no signal.")

    except Exception as e:
        print(f"scheduled_scan error: {e}")


# =========================
# MAIN
# =========================

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set. Please set BOT_TOKEN in Render environment variables.")

    print("Initializing database...")
    init_db()

    print("Starting Flask health server...")
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    print("Building Telegram application...")
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("price", price_command))
    application.add_handler(CommandHandler("scan", scan_command))

    try:
        if application.job_queue:
            application.job_queue.run_repeating(
                scheduled_scan,
                interval=SCAN_INTERVAL_SECONDS,
                first=30,
                name="scheduled_scan",
            )
            print("Auto scanner job started ✅")
        else:
            print("JobQueue is not available. Auto scan disabled.")
            print("If needed, install: python-telegram-bot[job-queue]")
    except Exception as e:
        print(f"Could not start auto scanner job: {e}")

    print("Scanner started ✅")
    print("Telegram bot polling started ✅")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
