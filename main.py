import os
import time
import logging
import requests
import pandas as pd
import numpy as np
import telebot
from datetime import datetime
from threading import Thread, Lock
from flask import Flask

# =========================================================
# Logging
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# =========================================================
# Flask Web Server for Render
# =========================================================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running and healthy!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# =========================================================
# Environment Variables
# =========================================================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID")

TIMEFRAME = os.environ.get("TIMEFRAME", "1h")
QUOTE_ASSET = os.environ.get("QUOTE_ASSET", "USDT")

MIN_SCORE = int(os.environ.get("MIN_SCORE_TO_SEND", 80))

# اگر 0 باشد یعنی کل بازار اسکن شود
SCAN_LIMIT = int(os.environ.get("SCAN_MARKET_LIMIT", 0))

TOP_N = int(os.environ.get("SCAN_TOP_N", 3))

# با همان متغیری که در Render گذاشتی سازگار شد
INTERVAL = int(os.environ.get("SCAN_INTERVAL", os.environ.get("AUTO_INTERVAL_SECONDS", 300)))

AUTO_SCAN = os.environ.get("AUTO_SCAN", "False").lower() in ["true", "1", "yes", "on"]

BINANCE_BASE_URL = "https://api.binance.com"

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set.")

bot = telebot.TeleBot(TOKEN)

# =========================================================
# Global State
# =========================================================
auto_scan_enabled = AUTO_SCAN
last_auto_scan_time = None
scan_lock = Lock()

# اگر ADMIN_ID ست شده باشد اتواسکن برای همان آیدی پیام می‌فرستد
admin_chat_id = int(ADMIN_ID) if ADMIN_ID and ADMIN_ID.isdigit() else None

# =========================================================
# Binance Helpers
# =========================================================
def safe_get_json(url, params=None, timeout=15):
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Request error: {url} | {e}")
        return None


def get_exchange_symbols():
    """
    دریافت همه نمادهای فعال Spot از بایننس.
    فقط نمادهایی که quoteAsset برابر USDT دارند و در حال معامله هستند.
    """
    url = f"{BINANCE_BASE_URL}/api/v3/exchangeInfo"
    data = safe_get_json(url)

    if not data or "symbols" not in data:
        return []

    symbols = []

    for item in data["symbols"]:
        try:
            if (
                item.get("status") == "TRADING"
                and item.get("quoteAsset") == QUOTE_ASSET
                and item.get("isSpotTradingAllowed") is True
            ):
                symbol = item.get("symbol")

                # حذف برخی جفت‌های اهرمی یا نامناسب
                blocked_words = [
                    "UP", "DOWN", "BULL", "BEAR"
                ]

                # این فیلتر خیلی سختگیرانه نیست، فقط توکن‌های لوریج‌دار قدیمی را حذف می‌کند
                if any(word in symbol.replace(QUOTE_ASSET, "") for word in blocked_words):
                    continue

                symbols.append(symbol)
        except Exception:
            continue

    return symbols


def get_24h_tickers():
    url = f"{BINANCE_BASE_URL}/api/v3/ticker/24hr"
    data = safe_get_json(url)
    if not isinstance(data, list):
        return []
    return data


def get_market_symbols():
    """
    نمادهای قابل اسکن را می‌گیرد و بر اساس حجم دلاری ۲۴ ساعته مرتب می‌کند.
    اگر SCAN_LIMIT = 0 باشد، کل نمادها را می‌دهد.
    """
    exchange_symbols = set(get_exchange_symbols())
    tickers = get_24h_tickers()

    rows = []

    for t in tickers:
        symbol = t.get("symbol")

        if symbol not in exchange_symbols:
            continue

        try:
            quote_volume = float(t.get("quoteVolume", 0))
        except Exception:
            quote_volume = 0

        rows.append({
            "symbol": symbol,
            "quoteVolume": quote_volume
        })

    rows = sorted(rows, key=lambda x: x["quoteVolume"], reverse=True)

    symbols = [r["symbol"] for r in rows]

    if SCAN_LIMIT > 0:
        symbols = symbols[:SCAN_LIMIT]

    return symbols


def get_crypto_data(symbol, timeframe=TIMEFRAME, limit=260):
    """
    دریافت کندل‌های قیمت از Binance.
    """
    try:
        url = f"{BINANCE_BASE_URL}/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": timeframe,
            "limit": limit
        }

        data = safe_get_json(url, params=params)

        if not data or not isinstance(data, list):
            return None

        df = pd.DataFrame(
            data,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "qav",
                "num_trades",
                "taker_base",
                "taker_quote",
                "ignore"
            ]
        )

        numeric_cols = ["open", "high", "low", "close", "volume", "qav", "num_trades", "taker_base", "taker_quote"]

        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")

        df = df.dropna()

        if len(df) < 220:
            return None

        return df

    except Exception as e:
        logging.error(f"get_crypto_data error for {symbol}: {e}")
        return None

# =========================================================
# Indicators
# =========================================================
def calculate_rsi(close, period=14):
    delta = close.diff()

    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()

    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def calculate_atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = np.abs(df["high"] - df["close"].shift())
    low_close = np.abs(df["low"] - df["close"].shift())

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()

    return atr


def calculate_indicators(df):
    df = df.copy()

    df["rsi"] = calculate_rsi(df["close"], 14)

    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

    macd_line, macd_signal, macd_hist = calculate_macd(df["close"])
    df["macd"] = macd_line
    df["macd_signal"] = macd_signal
    df["macd_hist"] = macd_hist

    df["atr"] = calculate_atr(df, 14)

    df["volume_ma20"] = df["volume"].rolling(window=20).mean()

    return df

# =========================================================
# Analysis Helpers
# =========================================================
def analyze_whale_activity(df):
    try:
        avg_vol = df["volume"].iloc[-21:-1].mean()
        current_vol = df["volume"].iloc[-1]

        if avg_vol <= 0:
            return "Normal", 1.0

        ratio = current_vol / avg_vol

        if ratio >= 3:
            return "Very High", ratio
        elif ratio >= 2:
            return "High", ratio
        elif ratio >= 1.4:
            return "Medium", ratio
        else:
            return "Normal", ratio

    except Exception:
        return "Unknown", 0


def detect_trend(last):
    if last["close"] > last["ema20"] > last["ema50"] > last["ema200"]:
        return "Strong Bullish"
    elif last["close"] > last["ema20"] and last["ema20"] > last["ema50"]:
        return "Bullish"
    elif last["close"] < last["ema20"] < last["ema50"] < last["ema200"]:
        return "Strong Bearish"
    elif last["close"] < last["ema20"] and last["ema20"] < last["ema50"]:
        return "Bearish"
    else:
        return "Neutral"


def detect_breakout(df):
    """
    بررسی شکست سقف ۲۰ کندل اخیر.
    """
    try:
        last_close = df["close"].iloc[-1]
        previous_high = df["high"].iloc[-21:-1].max()

        if last_close > previous_high:
            return True

        return False

    except Exception:
        return False


def backtest_strategy(df, lookahead=10):
    """
    بک‌تست ساده و سبک.
    چون در لحظه آینده نداریم، این فقط وضعیت گذشته نزدیک را تخمین می‌زند.
    """
    try:
        recent = df.iloc[-80:].copy()

        wins = 0
        total = 0

        for i in range(20, len(recent) - lookahead):
            row = recent.iloc[i]
            future = recent.iloc[i + 1:i + 1 + lookahead]

            if row["rsi"] < 40 and row["macd"] > row["macd_signal"] and row["close"] > row["ema20"]:
                entry = row["close"]
                future_max = future["high"].max()
                future_min = future["low"].min()

                target = entry * 1.015
                stop = entry * 0.985

                total += 1

                if future_max >= target and future_min > stop:
                    wins += 1

        if total == 0:
            return "Not enough similar setups"

        rate = round((wins / total) * 100, 1)

        if rate >= 65:
            return f"High - {rate}%"
        elif rate >= 50:
            return f"Medium - {rate}%"
        else:
            return f"Low - {rate}%"

    except Exception:
        return "Unknown"


def scoring_logic(df):
    """
    امتیازدهی از ۰ تا ۱۰۰.
    """
    last = df.iloc[-1]
    prev = df.iloc[-2]

    score = 0
    reasons = []

    # RSI
    if 30 <= last["rsi"] <= 45:
        score += 18
        reasons.append("RSI in accumulation zone")
    elif last["rsi"] < 30:
        score += 12
        reasons.append("RSI oversold")
    elif 45 < last["rsi"] <= 60:
        score += 8
        reasons.append("RSI healthy")
    elif last["rsi"] > 75:
        score -= 10
        reasons.append("RSI overbought")

    # MACD
    if last["macd"] > last["macd_signal"]:
        score += 18
        reasons.append("MACD bullish")
    else:
        score -= 5

    if last["macd_hist"] > prev["macd_hist"]:
        score += 8
        reasons.append("MACD histogram improving")

    # EMA trend
    if last["close"] > last["ema20"]:
        score += 10
        reasons.append("Price above EMA20")

    if last["ema20"] > last["ema50"]:
        score += 10
        reasons.append("EMA20 above EMA50")

    if last["close"] > last["ema200"]:
        score += 12
        reasons.append("Price above EMA200")

    # Trend
    trend = detect_trend(last)

    if trend == "Strong Bullish":
        score += 12
        reasons.append("Strong bullish trend")
    elif trend == "Bullish":
        score += 8
        reasons.append("Bullish trend")
    elif trend == "Strong Bearish":
        score -= 15
        reasons.append("Strong bearish trend")

    # Volume / Whale
    whale, volume_ratio = analyze_whale_activity(df)

    if whale == "Very High":
        score += 15
        reasons.append("Very high volume spike")
    elif whale == "High":
        score += 10
        reasons.append("High volume spike")
    elif whale == "Medium":
        score += 5
        reasons.append("Medium volume increase")

    # Breakout
    breakout = detect_breakout(df)

    if breakout:
        score += 10
        reasons.append("Breakout above recent high")

    # کنترل نهایی
    score = max(0, min(int(score), 100))

    return score, whale, volume_ratio, trend, breakout, reasons

# =========================================================
# Signal Generator
# =========================================================
def generate_signal(symbol):
    df = get_crypto_data(symbol, TIMEFRAME, limit=260)

    if df is None or len(df) < 220:
        return None

    df = calculate_indicators(df)
    df = df.dropna()

    if len(df) < 200:
        return None

    score, whale, volume_ratio, trend, breakout, reasons = scoring_logic(df)

    if score < MIN_SCORE:
        return None

    last = df.iloc[-1]

    price = float(last["close"])
    atr = float(last["atr"])

    if atr <= 0 or np.isnan(atr):
        return None

    signal = {
        "symbol": symbol,
        "timeframe": TIMEFRAME,
        "price": round(price, 8),
        "score": score,
        "whale": whale,
        "volume_ratio": round(float(volume_ratio), 2),
        "rsi": round(float(last["rsi"]), 2),
        "macd": round(float(last["macd"]), 8),
        "macd_signal": round(float(last["macd_signal"]), 8),
        "macd_hist": round(float(last["macd_hist"]), 8),
        "ema20": round(float(last["ema20"]), 8),
        "ema50": round(float(last["ema50"]), 8),
        "ema200": round(float(last["ema200"]), 8),
        "trend": trend,
        "breakout": breakout,
        "tp1": round(price + atr * 1.5, 8),
        "tp2": round(price + atr * 2.5, 8),
        "tp3": round(price + atr * 3.5, 8),
        "tp4": round(price + atr * 5.0, 8),
        "sl": round(price - atr * 2.0, 8),
        "backtest": backtest_strategy(df),
        "reasons": reasons,
        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    }

    return signal

# =========================================================
# Telegram Message
# =========================================================
def send_telegram_signal(signal, chat_id):
    reasons_text = "\n".join([f"• {r}" for r in signal["reasons"][:6]])

    template = f"""
🚀 <b>Signal: #{signal['symbol']}</b>
⏱ <b>Timeframe:</b> {signal['timeframe']}
📊 <b>Score:</b> {signal['score']}/100

💵 <b>Price:</b> <code>{signal['price']}</code>

📈 <b>RSI:</b> {signal['rsi']}
📊 <b>MACD:</b> <code>{signal['macd']}</code>
📊 <b>MACD Signal:</b> <code>{signal['macd_signal']}</code>
📊 <b>MACD Hist:</b> <code>{signal['macd_hist']}</code>

📉 <b>EMA20:</b> <code>{signal['ema20']}</code>
📉 <b>EMA50:</b> <code>{signal['ema50']}</code>
📉 <b>EMA200:</b> <code>{signal['ema200']}</code>

🐋 <b>Whale Activity:</b> {signal['whale']} x{signal['volume_ratio']}
📌 <b>Trend:</b> {signal['trend']}
🚧 <b>Breakout:</b> {signal['breakout']}
🧪 <b>Backtest:</b> {signal['backtest']}

🎯 <b>Targets:</b>
1️⃣ TP1: <code>{signal['tp1']}</code>
2️⃣ TP2: <code>{signal['tp2']}</code>
3️⃣ TP3: <code>{signal['tp3']}</code>
4️⃣ TP4: <code>{signal['tp4']}</code>

⛔️ <b>Stop Loss:</b> <code>{signal['sl']}</code>

✅ <b>Reasons:</b>
{reasons_text}

🕒 <b>Time:</b> {signal['time']}

#Crypto #Trading #Signal
"""

    bot.send_message(chat_id, template, parse_mode="HTML")

# =========================================================
# Market Scanner
# =========================================================
def scan_market(chat_id, silent=False):
    if not scan_lock.acquire(blocking=False):
        if not silent:
            bot.send_message(chat_id, "⏳ یک اسکن دیگر در حال اجراست. لطفاً صبر کن.")
        return

    try:
        if not silent:
            bot.send_message(
                chat_id,
                f"🔍 شروع اسکن بازار...\n"
                f"⏱ تایم‌فریم: {TIMEFRAME}\n"
                f"🎯 حداقل امتیاز ارسال: {MIN_SCORE}\n"
                f"📌 محدودیت اسکن: {'کل بازار' if SCAN_LIMIT == 0 else SCAN_LIMIT}"
            )

        symbols = get_market_symbols()

        if not symbols:
            bot.send_message(chat_id, "❌ هیچ نمادی برای اسکن پیدا نشد.")
            return

        logging.info(f"Scanning {len(symbols)} symbols...")

        found = 0
        checked = 0

        for symbol in symbols:
            checked += 1

            try:
                signal = generate_signal(symbol)

                if signal:
                    send_telegram_signal(signal, chat_id)
                    found += 1

                    if found >= TOP_N:
                        break

                # جلوگیری از فشار زیاد به API
                time.sleep(0.12)

            except Exception as e:
                logging.error(f"Symbol scan error {symbol}: {e}")
                continue

        if found == 0:
            bot.send_message(
                chat_id,
                f"✅ اسکن کامل شد.\n"
                f"تعداد بررسی‌شده: {checked}\n"
                f"فعلاً سیگنال با امتیاز بالاتر از {MIN_SCORE} پیدا نشد."
            )
        else:
            bot.send_message(
                chat_id,
                f"✅ اسکن کامل شد.\n"
                f"تعداد بررسی‌شده: {checked}\n"
                f"تعداد سیگنال ارسال‌شده: {found}"
            )

    except Exception as e:
        logging.error(f"Scan error: {e}")
        bot.send_message(chat_id, f"❌ خطا در اسکن بازار:\n<code>{e}</code>", parse_mode="HTML")

    finally:
        scan_lock.release()

# =========================================================
# Auto Scan
# =========================================================
def auto_scan_loop():
    global auto_scan_enabled, last_auto_scan_time

    logging.info("Auto scan loop started.")

    while True:
        try:
            if auto_scan_enabled and admin_chat_id:
                last_auto_scan_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                logging.info("Running auto scan...")
                scan_market(admin_chat_id, silent=True)

            time.sleep(INTERVAL)

        except Exception as e:
            logging.error(f"Auto scan loop error: {e}")
            time.sleep(30)

# =========================================================
# Telegram Handlers
# =========================================================
@bot.message_handler(commands=["start"])
def welcome(message):
    global admin_chat_id

    if not admin_chat_id:
        admin_chat_id = message.chat.id

    text = f"""
🤖 ربات تحلیل‌گر کریپتو فعال است.

دستورات:

/scan
اسکن دستی بازار

/auto_on
فعال‌سازی اسکن خودکار

/auto_off
خاموش کردن اسکن خودکار

/status
نمایش وضعیت ربات

تنظیمات فعلی:
⏱ Timeframe: {TIMEFRAME}
🎯 Min Score: {MIN_SCORE}
🔁 Interval: {INTERVAL} seconds
📌 Scan Limit: {'کل بازار' if SCAN_LIMIT == 0 else SCAN_LIMIT}
"""

    bot.reply_to(message, text)


@bot.message_handler(commands=["scan"])
def manual_scan(message):
    scan_market(message.chat.id)


@bot.message_handler(commands=["auto_on):
    global auto_scan_enabled, admin_chat_id

    admin_chat_id = message.chat.id
    auto_scan_enabled = True

    bot.reply_to(
        message,
        f"✅ اسکن خودکار فعال شد.\n"
        f"هر {INTERVAL} ثانیه یک‌بار بازار اسکن می‌شود."
    )


@bot.message_handler(commands=["auto_off"])
def auto_off(message):
    global auto_scan_enabled

    auto_scan_enabled =
