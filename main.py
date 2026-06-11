import os
import time
import threading
import traceback
import requests
import pandas as pd
import numpy as np
import telebot
from flask import Flask

# =========================
# تنظیمات اصلی
# =========================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))

TIMEFRAME = os.getenv("TIMEFRAME", "1h").strip()
QUOTE = os.getenv("QUOTE", "USDT").strip()

# Bybit interval format:
# 1m -> 1
# 5m -> 5
# 15m -> 15
# 30m -> 30
# 1h -> 60
# 4h -> 240
# 1d -> D
TIMEFRAME_MAP = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "6h": "360",
    "12h": "720",
    "1d": "D",
    "D": "D",
}

BYBIT_INTERVAL = TIMEFRAME_MAP.get(TIMEFRAME, "60")

TOP_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "DOGEUSDT",
    "LINKUSDT",
    "DOTUSDT",
]

# =========================
# Flask برای Render
# =========================

app = Flask(__name__)

@app.route("/")
def home():
    return "Telegram Bybit Scanner Bot is running.", 200

@app.route("/health")
def health():
    return {
        "status": "ok",
        "source": "bybit",
        "timeframe": TIMEFRAME,
        "interval": BYBIT_INTERVAL,
    }, 200

# =========================
# Telegram Bot
# =========================

if not TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN is missing.")
    bot = None
else:
    bot = telebot.TeleBot(TOKEN, parse_mode="HTML")


# =========================
# ابزارهای تحلیل
# =========================

def normalize_symbol(text):
    """
    BTC -> BTCUSDT
    BTCUSDT -> BTCUSDT
    btc -> BTCUSDT
    """
    if not text:
        return "BTCUSDT"

    s = text.upper().strip()
    s = s.replace("/", "").replace("-", "").replace("_", "")

    if not s.endswith(QUOTE):
        s = s + QUOTE

    return s


def fetch_bybit_klines(symbol, limit=120):
    """
    دریافت کندل از Bybit Public API
    نیاز به API Key ندارد.
    """
    try:
        url = "https://api.bybit.com/v5/market/kline"
        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": BYBIT_INTERVAL,
            "limit": str(limit),
        }

        headers = {
            "User-Agent": "Mozilla/5.0 Render Telegram Scanner Bot"
        }

        response = requests.get(url, params=params, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"Bybit HTTP Error {response.status_code}: {response.text[:300]}")
            return None

        data = response.json()

        if data.get("retCode") != 0:
            print(f"Bybit API Error for {symbol}: {data}")
            return None

        rows = data.get("result", {}).get("list", [])

        if not rows:
            print(f"No kline data for {symbol}")
            return None

        df = pd.DataFrame(
            rows,
            columns=[
                "start_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "turnover",
            ],
        )

        df["start_time"] = pd.to_numeric(df["start_time"])
        df["open"] = pd.to_numeric(df["open"])
        df["high"] = pd.to_numeric(df["high"])
        df["low"] = pd.to_numeric(df["low"])
        df["close"] = pd.to_numeric(df["close"])
        df["volume"] = pd.to_numeric(df["volume"])

        # Bybit معمولاً کندل‌ها را از جدید به قدیم می‌دهد.
        # اینجا مرتب می‌کنیم از قدیم به جدید.
        df = df.sort_values("start_time").reset_index(drop=True)

        return df

    except Exception as e:
        print(f"fetch_bybit_klines error for {symbol}: {e}")
        traceback.print_exc()
        return None


def calculate_rsi(close, period=14):
    delta = close.diff()

    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_ema(close, period=20):
    return close.ewm(span=period, adjust=False).mean()


def analyze_symbol(symbol):
    try:
        df = fetch_bybit_klines(symbol, limit=120)

        if df is None or len(df) < 50:
            return {
                "ok": False,
                "symbol": symbol,
                "error": "داده کافی دریافت نشد.",
            }

        close = df["close"]
        volume = df["volume"]

        last_price = float(close.iloc[-1])
        prev_price = float(close.iloc[-2])

        rsi_series = calculate_rsi(close, 14)
        rsi = float(rsi_series.iloc[-1])

        ema20 = float(calculate_ema(close, 20).iloc[-1])
        ema50 = float(calculate_ema(close, 50).iloc[-1])

        vol_now = float(volume.iloc[-1])
        vol_avg = float(volume.tail(20).mean())

        change_percent = ((last_price - prev_price) / prev_price) * 100

        score = 0
        reasons = []

        # قوانین ساده ولی پایدار
        if last_price > ema20:
            score += 20
            reasons.append("قیمت بالای EMA20")

        if last_price > ema50:
            score += 20
            reasons.append("قیمت بالای EMA50")

        if 45 <= rsi <= 68:
            score += 25
            reasons.append("RSI مناسب")

        if vol_now > vol_avg * 1.1:
            score += 20
            reasons.append("حجم بهتر از میانگین")

        if change_percent > 0:
            score += 15
            reasons.append("کندل آخر مثبت")

        if rsi >= 75:
            reasons.append("هشدار: RSI بالا")

        if rsi <= 30:
            reasons.append("احتمال اشباع فروش")

        signal_type = "خنثی"

        if score >= 70:
            signal_type = "قوی"
        elif score >= 45:
            signal_type = "متوسط"

        return {
            "ok": True,
            "symbol": symbol,
            "price": last_price,
            "rsi": round(rsi, 2),
            "ema20": round(ema20, 6),
            "ema50": round(ema50, 6),
            "change_percent": round(change_percent, 2),
            "score": score,
            "signal_type": signal_type,
            "reasons": reasons,
        }

    except Exception as e:
        print(f"analyze_symbol error for {symbol}: {e}")
        traceback.print_exc()
        return {
            "ok": False,
            "symbol": symbol,
            "error": str(e),
        }


def format_signal(result):
    if not result.get("ok"):
        return (
            f"❌ <b>{result.get('symbol')}</b>\n"
            f"خطا: {result.get('error', 'نامشخص')}"
        )

    reasons_text = "\n".join([f"• {r}" for r in result["reasons"]]) or "دلیل خاصی ثبت نشد."

    return f"""
🔔 <b>تحلیل {result['symbol']}</b>

💰 قیمت: <code>{result['price']}</code>
📊 RSI: <code>{result['rsi']}</code>
📈 تغییر کندل آخر: <code>{result['change_percent']}%</code>

🧮 امتیاز: <b>{result['score']}/100</b>
وضعیت: <b>{result['signal_type']}</b>

✅ دلایل:
{reasons_text}

⏱ تایم‌فریم: <code>{TIMEFRAME}</code>
📡 منبع دیتا: <b>Bybit Public API</b>
""".strip()


# =========================
# دستورات تلگرام
# =========================

if bot:

    @bot.message_handler(commands=["start", "help"])
    def start_handler(message):
        text = f"""
🚀 <b>ربات اسکنر Bybit فعال است</b>

این نسخه مستقیم از Binance دیتا نمی‌گیرد.
برای جلوگیری از خطای دریافت داده، کندل‌ها از Bybit Public API خوانده می‌شوند.

دستورات:

/scan
اسکن ارزهای مهم

/signal BTC
تحلیل یک ارز خاص

/status
وضعیت ربات

نمونه:
<code>/signal ETH</code>
<code>/signal SOL</code>
""".strip()

        bot.reply_to(message, text)


    @bot.message_handler(commands=["status"])
    def status_handler(message):
        text = f"""
✅ <b>Bot Status</b>

وضعیت: روشن
منبع دیتا: Bybit Public API
تایم‌فریم: <code>{TIMEFRAME}</code>
Interval Bybit: <code>{BYBIT_INTERVAL}</code>
Quote: <code>{QUOTE}</code>
Port: <code>{PORT}</code>
""".strip()

        bot.reply_to(message, text)


    @bot.message_handler(commands=["signal"])
    def signal_handler(message):
        try:
            parts = message.text.split(maxsplit=1)

            if len(parts) < 2:
                symbol = "BTCUSDT"
            else:
                symbol = normalize_symbol(parts[1])

            bot.reply_to(message, f"🔍 در حال تحلیل <b>{symbol}</b> ...")

            result = analyze_symbol(symbol)
            bot.send_message(message.chat.id, format_signal(result))

        except Exception as e:
            print(f"signal_handler error: {e}")
            traceback.print_exc()
            bot.reply_to(message, "❌ خطا در تحلیل این ارز.")


    @bot.message_handler(commands=["scan"])
    def scan_handler(message):
        bot.reply_to(message, "🔍 در حال اسکن ارزهای برتر بازار با دیتای Bybit...")

        def worker():
            try:
                results = []

                for symbol in TOP_SYMBOLS:
                    result = analyze_symbol(symbol)
                    if result.get("ok"):
                        results.append(result)
                    time.sleep(0.2)

                if not results:
                    bot.send_message(
                        message.chat.id,
                        "❌ داده‌ای دریافت نشد. لاگ Render را بررسی کن."
                    )
                    return

                results = sorted(results, key=lambda x: x["score"], reverse=True)

                best = results[:5]

                summary_lines = [
                    "✅ <b>نتیجه اسکن بازار</b>",
                    "",
                    f"⏱ تایم‌فریم: <code>{TIMEFRAME}</code>",
                    "📡 منبع دیتا: <b>Bybit Public API</b>",
                    "",
                ]

                for r in best:
                    emoji = "🟢" if r["score"] >= 70 else "🟡" if r["score"] >= 45 else "⚪"
                    summary_lines.append(
                        f"{emoji} <b>{r['symbol']}</b> | Score: <b>{r['score']}</b> | RSI: <code>{r['rsi']}</code> | {r['signal_type']}"
                    )

                summary_lines.append("")
                summary_lines.append("برای جزئیات:")
                summary_lines.append("<code>/signal BTC</code>")
                summary_lines.append("<code>/signal ETH</code>")
                summary_lines.append("<code>/signal SOL</code>")

                bot.send_message(message.chat.id, "\n".join(summary_lines))

            except Exception as e:
                print(f"scan worker error: {e}")
                traceback.print_exc()
                bot.send_message(
                    message.chat.id,
                    "❌ خطا در اسکن بازار. لاگ Render را بررسی کن."
                )

        threading.Thread(target=worker, daemon=True).start()


# =========================
# اجرای برنامه
# =========================

def run_flask():
    print(f"Starting Flask on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)


def run_bot():
    if not bot:
        print("Bot not started because TELEGRAM_BOT_TOKEN is missing.")
        return

    try:
        print("Removing old webhook...")
        bot.remove_webhook()
        time.sleep(1)

        print("Starting Telegram polling...")
        bot.infinity_polling(
            timeout=30,
            long_polling_timeout=30,
            skip_pending=True,
        )

    except Exception as e:
        print(f"Telegram polling crashed: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    print("===================================")
    print("Starting Telegram Bybit Scanner Bot")
    print(f"TIMEFRAME: {TIMEFRAME}")
    print(f"BYBIT_INTERVAL: {BYBIT_INTERVAL}")
    print(f"PORT: {PORT}")
    print("===================================")

    threading.Thread(target=run_flask, daemon=True).start()

    run_bot()
