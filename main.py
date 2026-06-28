import os
import asyncio
import threading
import pandas as pd
import ccxt
from flask import Flask
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET = os.getenv("OKX_SECRET")
OKX_PASSWORD = os.getenv("OKX_PASSWORD")
PORT = int(os.getenv("PORT", "10000"))

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is Active ✅"

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

exchange = ccxt.okx({
    "apiKey": OKX_API_KEY,
    "secret": OKX_SECRET,
    "password": OKX_PASSWORD,
    "enableRateLimit": True,
    "options": {"defaultType": "swap"}
})

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

async def startup_check(context: ContextTypes.DEFAULT_TYPE):
    print("startup_check started")
    try:
        await asyncio.to_thread(exchange.load_markets)
        ticker = await asyncio.to_thread(exchange.fetch_ticker, "BTC/USDT:USDT")
        price = ticker.get("last")

        text = (
            "✅ ربات روشن شد\n"
            "✅ اتصال به تلگرام برقرار است\n"
            "✅ اتصال به OKX برقرار است\n\n"
            f"قیمت BTC/USDT: {price}"
        )

        print("sending startup message to telegram")
        await context.bot.send_message(chat_id=CHAT_ID, text=text)
        print("startup message sent")

    except Exception as e:
        print(f"startup_check error: {e}")
        try:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=f"❌ خطا در اتصال OKX:\n{e}"
            )
        except Exception as e2:
            print(f"failed to send error message: {e2}")

async def start_command(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ ربات فعال است.")

async def scan_markets(context: ContextTypes.DEFAULT_TYPE):
    print("scan_markets running")
    try:
        ohlcv = await asyncio.to_thread(exchange.fetch_ohlcv, "BTC/USDT:USDT", "1h", None, 100)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["rsi"] = calculate_rsi(df["close"])

        last = df.iloc[-1]
        price = float(last["close"])
        ema20 = float(last["ema20"])
        ema50 = float(last["ema50"])
        rsi = float(last["rsi"])

        if price > ema20 > ema50:
            text = (
                "📢 سیگنال LONG\n\n"
                f"BTC/USDT\n"
                f"Price: {price}\n"
                f"RSI: {rsi:.2f}"
            )
            await context.bot.send_message(chat_id=CHAT_ID, text=text)

        elif price < ema20 < ema50:
            text = (
                "📢 سیگنال SHORT\n\n"
                f"BTC/USDT\n"
                f"Price: {price}\n"
                f"RSI: {rsi:.2f}"
            )
            await context.bot.send_message(chat_id=CHAT_ID, text=text)

    except Exception as e:
        print(f"scan_markets error: {e}")

def main():
    print("main started")

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is missing")
    if not CHAT_ID:
        raise ValueError("CHAT_ID is missing")

    threading.Thread(target=run_flask, daemon=True).start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))

    async def post_init(app):
        print("post_init called")
        await startup_check(app.bot)
        app.job_queue.run_repeating(scan_markets, interval=1800, first=15)

    application.post_init = post_init

    print("starting telegram polling")
    application.run_polling()

if __name__ == "__main__":
    main()
