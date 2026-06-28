import os
import asyncio
import threading
import pandas as pd
import ccxt
from flask import Flask
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# =========================
# Environment Variables
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET = os.getenv("OKX_SECRET")
OKX_PASSWORD = os.getenv("OKX_PASSWORD")

PORT = int(os.getenv("PORT", "10000"))

# =========================
# Flask for Render
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is Active ✅"

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

# =========================
# OKX Connection
# =========================
exchange = ccxt.okx({
    "apiKey": OKX_API_KEY,
    "secret": OKX_SECRET,
    "password": OKX_PASSWORD,
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap"
    }
})

# =========================
# Indicators
# =========================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()

    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

# =========================
# Market Analysis
# =========================
async def analyze_symbol(symbol):
    try:
        ohlcv = await asyncio.to_thread(
            exchange.fetch_ohlcv,
            symbol,
            "1h",
            None,
            100
        )

        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["rsi"] = calculate_rsi(df["close"])

        last = df.iloc[-1]

        price = float(last["close"])
        ema20 = float(last["ema20"])
        ema50 = float(last["ema50"])
        rsi = float(last["rsi"])

        signal = None
        score = 0

        if price > ema20 > ema50:
            signal = "LONG 🟢"
            score += 50

            if 45 <= rsi <= 70:
                score += 30

            if rsi < 60:
                score += 20

        elif price < ema20 < ema50:
            signal = "SHORT 🔴"
            score += 50

            if 30 <= rsi <= 55:
                score += 30

            if rsi > 40:
                score += 20

        if signal and score >= 70:
            if signal.startswith("LONG"):
                stop_loss = price * 0.985
                take_profit = price * 1.03
            else:
                stop_loss = price * 1.015
                take_profit = price * 0.97

            return {
                "symbol": symbol,
                "signal": signal,
                "score": score,
                "price": price,
                "rsi": rsi,
                "take_profit": take_profit,
                "stop_loss": stop_loss
            }

    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")

    return None

# =========================
# Telegram Messages
# =========================
async def send_signal(context: ContextTypes.DEFAULT_TYPE, result):
    text = (
        "📢 سیگنال جدید\n\n"
        f"💰 ارز: {result['symbol']}\n"
        f"🧭 جهت: {result['signal']}\n"
        f"⭐ امتیاز: {result['score']}/100\n"
        f"📊 RSI: {result['rsi']:.2f}\n\n"
        f"🎯 ورود تقریبی: {result['price']:.4f}\n"
        f"✅ تارگت: {result['take_profit']:.4f}\n"
        f"⛔ حد ضرر: {result['stop_loss']:.4f}\n\n"
        "⚠️ این فقط سیگنال تحلیلی است، خرید و فروش خودکار انجام نمی‌شود."
    )

    await context.bot.send_message(chat_id=CHAT_ID, text=text)

async def startup_check(context: ContextTypes.DEFAULT_TYPE):
    try:
        await asyncio.to_thread(exchange.load_markets)

        ticker = await asyncio.to_thread(exchange.fetch_ticker, "BTC/USDT:USDT")
        price = ticker.get("last")

        text = (
            "✅ ربات روشن شد\n"
            "✅ اتصال به تلگرام برقرار است\n"
            "✅ اتصال به OKX برقرار است\n\n"
            f"قیمت BTC/USDT: {price}\n\n"
            "ربات فقط سیگنال می‌دهد و معامله انجام نمی‌دهد."
        )

        await context.bot.send_message(chat_id=CHAT_ID, text=text)

    except Exception as e:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=f"❌ ربات روشن شد ولی اتصال OKX خطا داد:\n{e}"
        )

async def start_command(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ ربات فعال است.\n"
        "برای تست اتصال، کمی صبر کن تا پیام بررسی OKX ارسال شود.\n"
        "این ربات فقط سیگنال می‌دهد و معامله انجام نمی‌دهد."
    )

async def scan_markets(context: ContextTypes.DEFAULT_TYPE):
    print("Scanning markets...")

    symbols = [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
        "DOGE/USDT:USDT",
        "XRP/USDT:USDT",
        "ADA/USDT:USDT",
        "BNB/USDT:USDT",
        "TON/USDT:USDT"
    ]

    found_signal = False

    for symbol in symbols:
        result = await analyze_symbol(symbol)

        if result:
            found_signal = True
            await send_signal(context, result)
            await asyncio.sleep(2)

    if not found_signal:
        print("No strong signal found.")

# =========================
# Main
# =========================
def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is missing")

    if not CHAT_ID:
        raise ValueError("CHAT_ID is missing")

    threading.Thread(target=run_flask, daemon=True).start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))

    job_queue = application.job_queue

    job_queue.run_once(startup_check, when=5)
    job_queue.run_repeating(scan_markets, interval=1800, first=15)

    print("Bot started successfully...")
    application.run_polling()

if __name__ == "__main__":
    main()
