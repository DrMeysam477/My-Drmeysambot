import os
import time
import math
import threading
import asyncio
import requests
from datetime import datetime

from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")  # برای ارسال خودکار سیگنال
PORT = int(os.environ.get("PORT", 10000))

# اگر شورت می‌خواهی، بهتر است SWAP باشد
DEFAULT_MARKET_TYPE = os.environ.get("MARKET_TYPE", "SWAP").upper()  # SPOT یا SWAP

# روشن/خاموش کردن اسکن خودکار
AUTO_SCAN = os.environ.get("AUTO_SCAN", "false").lower() == "true"

# هر چند دقیقه یک بار بازار اسکن شود
SCAN_INTERVAL_SECONDS = int(os.environ.get("SCAN_INTERVAL_SECONDS", 900))  # 15 دقیقه

# جلوگیری از سیگنال تکراری برای هر نماد/جهت
SIGNAL_COOLDOWN_SECONDS = int(os.environ.get("SIGNAL_COOLDOWN_SECONDS", 6 * 60 * 60))  # 6 ساعت

# لیست نمادها برای اسکن خودکار
WATCHLIST = os.environ.get(
    "WATCHLIST",
    "BTC,ETH,SOL,BNB,XRP,DOGE,ADA,AVAX,LINK,TON,TRX,DOT,NEAR,APT,ARB,OP,INJ,FIL,LTC,BCH"
).split(",")

# امتیازها
BASE_THRESHOLD = 82
NEUTRAL_THRESHOLD = 90
COUNTER_TREND_THRESHOLD = 93
BEARISH_LONG_THRESHOLD = 94

# حداقل RR
MIN_RR = 1.5

# OKX
OKX_BASE = "https://www.okx.com"


# =========================================================
# Flask for Render
# =========================================================

flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is running", 200

def run_flask():
    flask_app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )


# =========================================================
# Utilities
# =========================================================

def now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def safe_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default

def normalize_symbol(user_symbol: str, market_type=None):
    """
    BTC -> BTC-USDT-SWAP در حالت SWAP
    BTC -> BTC-USDT در حالت SPOT
    """
    if not market_type:
        market_type = DEFAULT_MARKET_TYPE

    s = user_symbol.strip().upper()

    if "-USDT-SWAP" in s:
        return s

    if "-USDT" in s:
        if market_type == "SWAP" and not s.endswith("-SWAP"):
            return s + "-SWAP"
        return s

    if market_type == "SWAP":
        return f"{s}-USDT-SWAP"

    return f"{s}-USDT"


def interval_to_okx_bar(interval):
    mapping = {
        "15m": "15m",
        "1H": "1H",
        "4H": "4H",
    }
    return mapping.get(interval, interval)


# =========================================================
# OKX DATA
# =========================================================

def okx_get(path, params=None, timeout=10):
    url = OKX_BASE + path
    try:
        r = requests.get(url, params=params, timeout=timeout)
        data = r.json()
        if data.get("code") == "0":
            return data.get("data", [])
        print(f"OKX error: {data}", flush=True)
        return []
    except Exception as e:
        print(f"OKX request error: {e}", flush=True)
        return []


def get_price(symbol="BTC-USDT"):
    data = okx_get("/api/v5/market/ticker", {"instId": symbol})
    if data:
        return data[0].get("last")
    return None


def get_candles(symbol, bar="1H", limit=200):
    """
    خروجی OKX از جدید به قدیم است؛ ما برعکس می‌کنیم تا قدیمی به جدید شود.
    candle:
    [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
    """
    data = okx_get(
        "/api/v5/market/candles",
        {
            "instId": symbol,
            "bar": interval_to_okx_bar(bar),
            "limit": str(limit)
        }
    )

    candles = []
    for item in reversed(data):
        try:
            candles.append({
                "ts": int(item[0]),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
            })
        except Exception:
            continue

    return candles


def get_order_book_pressure(symbol, depth=40):
    """
    نسبت فشار خرید/فروش از Order Book.
    bid_pressure > 1 یعنی سفارشات خرید قوی‌ترند.
    ask_pressure > 1 یعنی سفارشات فروش قوی‌ترند.
    """
    data = okx_get(
        "/api/v5/market/books",
        {
            "instId": symbol,
            "sz": str(depth)
        }
    )

    if not data:
        return {
            "bid_value": 0,
            "ask_value": 0,
            "ratio": 1,
            "state": "NEUTRAL"
        }

    try:
        book = data[0]
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        bid_value = sum(float(p) * float(sz) for p, sz, *_ in bids)
        ask_value = sum(float(p) * float(sz) for p, sz, *_ in asks)

        if ask_value <= 0:
            ratio = 1
        else:
            ratio = bid_value / ask_value

        if ratio >= 1.25:
            state = "BUY_PRESSURE"
        elif ratio <= 0.80:
            state = "SELL_PRESSURE"
        else:
            state = "NEUTRAL"

        return {
            "bid_value": bid_value,
            "ask_value": ask_value,
            "ratio": ratio,
            "state": state
        }

    except Exception as e:
        print(f"Order book error: {e}", flush=True)
        return {
            "bid_value": 0,
            "ask_value": 0,
            "ratio": 1,
            "state": "NEUTRAL"
        }


# =========================================================
# Indicators
# =========================================================

def closes(candles):
    return [c["close"] for c in candles]

def highs(candles):
    return [c["high"] for c in candles]

def lows(candles):
    return [c["low"] for c in candles]

def volumes(candles):
    return [c["volume"] for c in candles]


def ema(values, period):
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    ema_value = sum(values[:period]) / period

    for price in values[period:]:
        ema_value = price * k + ema_value * (1 - k)

    return ema_value


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(-period, 0):
        change = values[i] - values[i - 1]
        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(values, fast=12, slow=26, signal=9):
    if len(values) < slow + signal:
        return None

    macd_series = []

    for i in range(slow, len(values) + 1):
        sub_values = values[:i]
        fast_ema = ema(sub_values, fast)
        slow_ema = ema(sub_values, slow)

        if fast_ema is not None and slow_ema is not None:
            macd_series.append(fast_ema - slow_ema)

    if len(macd_series) < signal:
        return None

    macd_line = macd_series[-1]
    signal_line = ema(macd_series, signal)
    histogram = macd_line - signal_line

    return {
        "macd": macd_line,
        "signal": signal_line,
        "hist": histogram
    }


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        trs.append(tr)

    if len(trs) < period:
        return None

    return sum(trs[-period:]) / period


def bollinger(values, period=20, mult=2):
    if len(values) < period:
        return None

    mid = sma(values, period)
    recent = values[-period:]
    variance = sum((x - mid) ** 2 for x in recent) / period
    std = math.sqrt(variance)

    return {
        "upper": mid + mult * std,
        "middle": mid,
        "lower": mid - mult * std
    }


def vwap(candles, period=40):
    if len(candles) < period:
        return None

    recent = candles[-period:]
    pv = 0
    vol = 0

    for c in recent:
        typical = (c["high"] + c["low"] + c["close"]) / 3
        pv += typical * c["volume"]
        vol += c["volume"]

    if vol == 0:
        return None

    return pv / vol


def adx(candles, period=14):
    """
    نسخه ساده ADX برای تشخیص قدرت روند.
    """
    if len(candles) < period + 2:
        return None

    plus_dm = []
    minus_dm = []
    tr_list = []

    for i in range(1, len(candles)):
        up_move = candles[i]["high"] - candles[i - 1]["high"]
        down_move = candles[i - 1]["low"] - candles[i]["low"]

        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)

        tr = max(
            candles[i]["high"] - candles[i]["low"],
            abs(candles[i]["high"] - candles[i - 1]["close"]),
            abs(candles[i]["low"] - candles[i - 1]["close"])
        )
        tr_list.append(tr)

    if len(tr_list) < period:
        return None

    atr_val = sum(tr_list[-period:]) / period
    if atr_val == 0:
        return None

    plus_di = 100 * (sum(plus_dm[-period:]) / period) / atr_val
    minus_di = 100 * (sum(minus_dm[-period:]) / period) / atr_val

    if plus_di + minus_di == 0:
        return None

    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)

    return {
        "adx": dx,
        "plus_di": plus_di,
        "minus_di": minus_di
    }


def volume_ratio(candles, period=20):
    if len(candles) < period + 1:
        return 1

    vols = volumes(candles)
    avg_vol = sum(vols[-period-1:-1]) / period

    if avg_vol <= 0:
        return 1

    return vols[-1] / avg_vol


def candle_strength(candles):
    """
    قدرت کندل آخر.
    مثبت: صعودی
    منفی: نزولی
    """
    if not candles:
        return 0

    c = candles[-1]
    rng = c["high"] - c["low"]

    if rng <= 0:
        return 0

    body = c["close"] - c["open"]
    return body / rng


def distance_pct(a, b):
    if b == 0 or b is None or a is None:
        return 0
    return ((a - b) / b) * 100


# =========================================================
# Market State
# =========================================================

def build_indicators(symbol, tf):
    candles = get_candles(symbol, tf, 220)

    if len(candles) < 60:
        return None

    cls = closes(candles)

    indicators = {
        "symbol": symbol,
        "tf": tf,
        "candles": candles,
        "price": cls[-1],
        "ema20": ema(cls, 20),
        "ema50": ema(cls, 50),
        "ema200": ema(cls, 200),
        "rsi": rsi(cls, 14),
        "macd": macd(cls),
        "atr": atr(candles, 14),
        "bb": bollinger(cls, 20, 2),
        "vwap": vwap(candles, 40),
        "adx": adx(candles, 14),
        "volume_ratio": volume_ratio(candles, 20),
        "candle_strength": candle_strength(candles)
    }

    return indicators


def detect_trend(ind):
    if not ind:
        return "UNKNOWN"

    price = ind["price"]
    e20 = ind["ema20"]
    e50 = ind["ema50"]
    e200 = ind["ema200"]
    r = ind["rsi"]
    m = ind["macd"]
    a = ind["adx"]

    bullish_points = 0
    bearish_points = 0

    if e20 and e50 and e200:
        if e20 > e50 > e200:
            bullish_points += 3
        elif e20 < e50 < e200:
            bearish_points += 3

        if price > e50:
            bullish_points += 1
        elif price < e50:
            bearish_points += 1

    if r is not None:
        if r > 55:
            bullish_points += 1
        elif r < 45:
            bearish_points += 1

    if m:
        if m["hist"] > 0 and m["macd"] > m["signal"]:
            bullish_points += 2
        elif m["hist"] < 0 and m["macd"] < m["signal"]:
            bearish_points += 2

    if a and a["adx"] >= 18:
        if a["plus_di"] > a["minus_di"]:
            bullish_points += 1
        elif a["minus_di"] > a["plus_di"]:
            bearish_points += 1

    if bullish_points >= 5 and bullish_points > bearish_points:
        return "BULLISH"

    if bearish_points >= 5 and bearish_points > bullish_points:
        return "BEARISH"

    return "NEUTRAL"


def get_btc_trend():
    btc_symbol = "BTC-USDT-SWAP" if DEFAULT_MARKET_TYPE == "SWAP" else "BTC-USDT"
    btc_4h = build_indicators(btc_symbol, "4H")
    return detect_trend(btc_4h), btc_4h


# =========================================================
# Scoring
# =========================================================

def score_long(htf, mtf, ltf, ob):
    score = 0
    reasons = []

    price = ltf["price"]

    # HTF Trend
    htf_trend = detect_trend(htf)
    if htf_trend == "BULLISH":
        score += 15
        reasons.append("4H trend bullish")
    elif htf_trend == "NEUTRAL":
        score += 5
        reasons.append("4H trend neutral")
    else:
        score -= 10
        reasons.append("4H trend bearish against long")

    # EMA alignment 1H
    if mtf["ema20"] and mtf["ema50"] and mtf["ema200"]:
        if mtf["ema20"] > mtf["ema50"] > mtf["ema200"]:
            score += 15
            reasons.append("1H EMA20 > EMA50 > EMA200")
        elif mtf["ema20"] > mtf["ema50"]:
            score += 8
            reasons.append("1H short-term EMA bullish")
        else:
            score -= 5
            reasons.append("1H EMA not bullish")

    # RSI
    r = mtf["rsi"]
    if r is not None:
        if 45 <= r <= 68:
            score += 12
            reasons.append(f"RSI healthy for long: {r:.1f}")
        elif 68 < r <= 75:
            score += 3
            reasons.append(f"RSI a bit high: {r:.1f}")
        elif r > 75:
            score -= 10
            reasons.append(f"RSI overbought: {r:.1f}")
        elif 35 <= r < 45:
            score += 4
            reasons.append(f"RSI recovering zone: {r:.1f}")
        else:
            score -= 5
            reasons.append(f"RSI weak for long: {r:.1f}")

    # MACD
    m = mtf["macd"]
    if m:
        if m["macd"] > m["signal"] and m["hist"] > 0:
            score += 12
            reasons.append("MACD bullish on 1H")
        elif m["hist"] > 0:
            score += 6
            reasons.append("MACD histogram positive")
        else:
            score -= 5
            reasons.append("MACD not bullish")

    # VWAP
    if ltf["vwap"]:
        if price > ltf["vwap"]:
            score += 8
            reasons.append("Price above VWAP")
        else:
            score -= 3
            reasons.append("Price below VWAP")

    # Bollinger breakout/reclaim
    bb = ltf["bb"]
    if bb:
        if price > bb["middle"]:
            score += 5
            reasons.append("Price above Bollinger middle")
        if price > bb["upper"]:
            score += 4
            reasons.append("Bollinger bullish breakout")

    # Volume
    vr = ltf["volume_ratio"]
    if vr >= 2.0:
        score += 10
        reasons.append(f"Strong volume spike: {vr:.2f}x")
    elif vr >= 1.3:
        score += 6
        reasons.append(f"Volume above average: {vr:.2f}x")
    elif vr < 0.8:
        score -= 4
        reasons.append(f"Weak volume: {vr:.2f}x")

    # Candle strength
    cs = ltf["candle_strength"]
    if cs >= 0.45:
        score += 6
        reasons.append("Strong bullish 15m candle")
    elif cs <= -0.45:
        score -= 6
        reasons.append("Strong bearish 15m candle against long")

    # ADX
    a = mtf["adx"]
    if a:
        if a["adx"] >= 20 and a["plus_di"] > a["minus_di"]:
            score += 8
            reasons.append(f"ADX confirms bullish trend: {a['adx']:.1f}")
        elif a["adx"] >= 20 and a["minus_di"] > a["plus_di"]:
            score -= 6
            reasons.append(f"ADX bearish pressure: {a['adx']:.1f}")

    # Order Book
    if ob["state"] == "BUY_PRESSURE":
        score += 8
        reasons.append(f"Order book buy pressure: {ob['ratio']:.2f}")
    elif ob["state"] == "SELL_PRESSURE":
        score -= 6
        reasons.append(f"Order book sell pressure: {ob['ratio']:.2f}")

    # جلوگیری از ورود دیرهنگام
    if ltf["ema20"]:
        dist = distance_pct(price, ltf["ema20"])
        if dist > 4:
            score -= 10
            reasons.append(f"Price too far above EMA20: {dist:.2f}%")

    return max(0, min(100, score)), reasons


def score_short(htf, mtf, ltf, ob):
    score = 0
    reasons = []

    price = ltf["price"]

    # HTF Trend
    htf_trend = detect_trend(htf)
    if htf_trend == "BEARISH":
        score += 15
        reasons.append("4H trend bearish")
    elif htf_trend == "NEUTRAL":
        score += 5
        reasons.append("4H trend neutral")
    else:
        score -= 10
        reasons.append("4H trend bullish against short")

    # EMA alignment 1H
    if mtf["ema20"] and mtf["ema50"] and mtf["ema200"]:
        if mtf["ema20"] < mtf["ema50"] < mtf["ema200"]:
            score += 15
            reasons.append("1H EMA20 < EMA50 < EMA200")
        elif mtf["ema20"] < mtf["ema50"]:
            score += 8
            reasons.append("1H short-term EMA bearish")
        else:
            score -= 5
            reasons.append("1H EMA not bearish")

    # RSI
    r = mtf["rsi"]
    if r is not None:
        if 32 <= r <= 55:
            score += 12
            reasons.append(f"RSI healthy for short: {r:.1f}")
        elif 25 <= r < 32:
            score += 3
            reasons.append(f"RSI getting oversold: {r:.1f}")
        elif r < 25:
            score -= 10
            reasons.append(f"RSI oversold, late short risk: {r:.1f}")
        elif 55 < r <= 65:
            score += 2
            reasons.append(f"RSI slightly high for short: {r:.1f}")
        else:
            score -= 5
            reasons.append(f"RSI weak for short: {r:.1f}")

    # MACD
    m = mtf["macd"]
    if m:
        if m["macd"] < m["signal"] and m["hist"] < 0:
            score += 12
            reasons.append("MACD bearish on 1H")
        elif m["hist"] < 0:
            score += 6
            reasons.append("MACD histogram negative")
        else:
            score -= 5
            reasons.append("MACD not bearish")

    # VWAP
    if ltf["vwap"]:
        if price < ltf["vwap"]:
            score += 8
            reasons.append("Price below VWAP")
        else:
            score -= 3
            reasons.append("Price above VWAP")

    # Bollinger
    bb = ltf["bb"]
    if bb:
        if price < bb["middle"]:
            score += 5
            reasons.append("Price below Bollinger middle")
        if price < bb["lower"]:
            score += 4
            reasons.append("Bollinger bearish breakdown")

    # Volume
    vr = ltf["volume_ratio"]
    if vr >= 2.0:
        score += 10
        reasons.append(f"Strong volume spike: {vr:.2f}x")
    elif vr >= 1.3:
        score += 6
        reasons.append(f"Volume above average: {vr:.2f}x")
    elif vr < 0.8:
        score -= 4
        reasons.append(f"Weak volume: {vr:.2f}x")

    # Candle strength
    cs = ltf["candle_strength"]
    if cs <= -0.45:
        score += 6
        reasons.append("Strong bearish 15m candle")
    elif cs >= 0.45:
        score -= 6
        reasons.append("Strong bullish 15m candle against short")

    # ADX
    a = mtf["adx"]
    if a:
        if a["adx"] >= 20 and a["minus_di"] > a["plus_di"]:
            score += 8
            reasons.append(f"ADX confirms bearish trend: {a['adx']:.1f}")
        elif a["adx"] >= 20 and a["plus_di"] > a["minus_di"]:
            score -= 6
            reasons.append(f"ADX bullish pressure: {a['adx']:.1f}")

    # Order Book
    if ob["state"] == "SELL_PRESSURE":
        score += 8
        reasons.append(f"Order book sell pressure: {ob['ratio']:.2f}")
    elif ob["state"] == "BUY_PRESSURE":
        score -= 6
        reasons.append(f"Order book buy pressure: {ob['ratio']:.2f}")

    # جلوگیری از شورت دیرهنگام
    if ltf["ema20"]:
        dist = distance_pct(price, ltf["ema20"])
        if dist < -4:
            score -= 10
            reasons.append(f"Price too far below EMA20: {dist:.2f}%")

    return max(0, min(100, score)), reasons


def direction_permission(btc_trend, long_score, short_score):
    """
    منطق دوطرفه بر اساس روند BTC.
    """
    if btc_trend == "BULLISH":
        return {
            "long_allowed": long_score >= BASE_THRESHOLD,
            "short_allowed": short_score >= COUNTER_TREND_THRESHOLD,
            "long_threshold": BASE_THRESHOLD,
            "short_threshold": COUNTER_TREND_THRESHOLD
        }

    if btc_trend == "NEUTRAL":
        return {
            "long_allowed": long_score >= NEUTRAL_THRESHOLD,
            "short_allowed": short_score >= NEUTRAL_THRESHOLD,
            "long_threshold": NEUTRAL_THRESHOLD,
            "short_threshold": NEUTRAL_THRESHOLD
        }

    if btc_trend == "BEARISH":
        return {
            "long_allowed": long_score >= BEARISH_LONG_THRESHOLD,
            "short_allowed": short_score >= BASE_THRESHOLD,
            "long_threshold": BEARISH_LONG_THRESHOLD,
            "short_threshold": BASE_THRESHOLD
        }

    return {
        "long_allowed": False,
        "short_allowed": False,
        "long_threshold": 999,
        "short_threshold": 999
    }


# =========================================================
# Risk / Targets
# =========================================================

def build_trade_plan(direction, price, atr_value):
    if atr_value is None or atr_value <= 0:
        return None

    if direction == "LONG":
        sl = price - (1.3 * atr_value)
        risk = price - sl

        tp1 = price + (1.5 * risk)
        tp2 = price + (2.2 * risk)
        tp3 = price + (3.0 * risk)
        tp4 = price + (4.0 * risk)

        rr1 = (tp1 - price) / risk if risk > 0 else 0

    else:
        sl = price + (1.3 * atr_value)
        risk = sl - price

        tp1 = price - (1.5 * risk)
        tp2 = price - (2.2 * risk)
        tp3 = price - (3.0 * risk)
        tp4 = price - (4.0 * risk)

        rr1 = (price - tp1) / risk if risk > 0 else 0

    if rr1 < MIN_RR:
        return None

    return {
        "entry": price,
        "stop_loss": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "tp4": tp4,
        "rr1": rr1
    }


def fmt_price(x):
    if x is None:
        return "N/A"

    if x >= 100:
        return f"{x:.2f}"
    elif x >= 1:
        return f"{x:.4f}"
    else:
        return f"{x:.8f}"


# =========================================================
# Main Analysis
# =========================================================

def analyze_symbol(symbol):
    symbol = normalize_symbol(symbol)

    htf = build_indicators(symbol, "4H")
    mtf = build_indicators(symbol, "1H")
    ltf = build_indicators(symbol, "15m")
    ob = get_order_book_pressure(symbol)

    if not htf or not mtf or not ltf:
        return {
            "ok": False,
            "message": f"Not enough data for {symbol}"
        }

    btc_trend, btc_ind = get_btc_trend()

    long_score, long_reasons = score_long(htf, mtf, ltf, ob)
    short_score, short_reasons = score_short(htf, mtf, ltf, ob)

    permission = direction_permission(btc_trend, long_score, short_score)

    candidates = []

    if permission["long_allowed"]:
        plan = build_trade_plan("LONG", ltf["price"], ltf["atr"])
        if plan:
            candidates.append({
                "direction": "LONG",
                "score": long_score,
                "reasons": long_reasons,
                "plan": plan,
                "threshold": permission["long_threshold"]
            })

    if permission["short_allowed"]:
        plan = build_trade_plan("SHORT", ltf["price"], ltf["atr"])
        if plan:
            candidates.append({
                "direction": "SHORT",
                "score": short_score,
                "reasons": short_reasons,
                "plan": plan,
                "threshold": permission["short_threshold"]
            })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    result = {
        "ok": True,
        "symbol": symbol,
        "btc_trend": btc_trend,
        "price": ltf["price"],
        "htf_trend": detect_trend(htf),
        "long_score": long_score,
        "short_score": short_score,
        "long_threshold": permission["long_threshold"],
        "short_threshold": permission["short_threshold"],
        "candidate": candidates[0] if candidates else None,
        "long_reasons": long_reasons,
        "short_reasons": short_reasons
    }

    return result


def build_signal_message(result):
    if not result.get("ok"):
        return result.get("message", "Analysis error")

    symbol = result["symbol"]
    candidate = result.get("candidate")

    if not candidate:
        return (
            f"📊 Analysis: {symbol}\n\n"
            f"BTC Trend: {result['btc_trend']}\n"
            f"Symbol 4H Trend: {result['htf_trend']}\n"
            f"Price: {fmt_price(result['price'])}\n\n"
            f"Long Score: {result['long_score']}/100 "
            f"(Need {result['long_threshold']})\n"
            f"Short Score: {result['short_score']}/100 "
            f"(Need {result['short_threshold']})\n\n"
            f"❌ No valid signal now."
        )

    direction = candidate["direction"]
    score = candidate["score"]
    plan = candidate["plan"]
    reasons = candidate["reasons"][:8]

    emoji = "🟢" if direction == "LONG" else "🔴"

    message = (
        f"{emoji} {direction} Signal\n\n"
        f"Symbol: {symbol}\n"
        f"BTC Trend: {result['btc_trend']}\n"
        f"Symbol 4H Trend: {result['htf_trend']}\n"
        f"Score: {score}/100\n"
        f"Required Score: {candidate['threshold']}\n\n"
        f"Entry: {fmt_price(plan['entry'])}\n"
        f"Stop Loss: {fmt_price(plan['stop_loss'])}\n\n"
        f"Targets:\n"
        f"TP1: {fmt_price(plan['tp1'])}\n"
        f"TP2: {fmt_price(plan['tp2'])}\n"
        f"TP3: {fmt_price(plan['tp3'])}\n"
        f"TP4: {fmt_price(plan['tp4'])}\n\n"
        f"RR to TP1: {plan['rr1']:.2f}\n\n"
        f"Reasons:\n"
    )

    for r in reasons:
        message += f"✅ {r}\n"

    message += f"\nTime: {now_str()}"
    message += "\n\n⚠️ This is not financial advice. Use risk management."

    return message


# =========================================================
# Telegram Send
# =========================================================

def send_telegram_message(text):
    if not BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("BOT_TOKEN or TELEGRAM_CHAT_ID not set. Cannot send auto message.", flush=True)
        return False

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text
        }
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram send error: {e}", flush=True)
        return False


# =========================================================
# Auto Scanner
# =========================================================

last_signal_time = {}

def can_send_signal(symbol, direction):
    key = f"{symbol}:{direction}"
    last = last_signal_time.get(key, 0)
    return time.time() - last >= SIGNAL_COOLDOWN_SECONDS

def mark_signal_sent(symbol, direction):
    key = f"{symbol}:{direction}"
    last_signal_time[key] = time.time()


def auto_scan_loop():
    print("Auto scan loop started.", flush=True)

    while True:
        try:
            for item in WATCHLIST:
                base = item.strip().upper()
                if not base:
                    continue

                symbol = normalize_symbol(base)
                print(f"Scanning {symbol}...", flush=True)

                result = analyze_symbol(symbol)

                if result.get("ok") and result.get("candidate"):
                    candidate = result["candidate"]
                    direction = candidate["direction"]

                    if can_send_signal(symbol, direction):
                        msg = build_signal_message(result)
                        sent = send_telegram_message(msg)

                        if sent:
                            mark_signal_sent(symbol, direction)
                            print(f"Signal sent: {symbol} {direction}", flush=True)
                        else:
                            print(f"Signal found but not sent: {symbol}", flush=True)

                time.sleep(1)

        except Exception as e:
            print(f"Auto scan error: {e}", flush=True)

        print(f"Scan cycle finished. Sleeping {SCAN_INTERVAL_SECONDS}s", flush=True)
        time.sleep(SCAN_INTERVAL_SECONDS)


# =========================================================
# BOT COMMANDS
# ==============================
