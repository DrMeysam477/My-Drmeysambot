import os
import threading
import asyncio
import requests

from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---------- Flask for Render ----------
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is running", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )

# ---------- OKX DATA ----------
def get_price(symbol="BTC-USDT"):
    url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}"

    try:
        r = requests.get(url, timeout=10)
        data = r.json()

        if data.get("code") == "0":
            return data["data"][0]["last"]

        return None

    except Exception as e:
        print(f"Price error: {e}", flush=True)
        return None

# ---------- BOT COMMANDS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot started ✅")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running on Render ✅")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = "BTC-USDT"

    if context.args:
        symbol = context.args[0].upper()

        # اگر کاربر فقط BTC نوشت، خودش تبدیل کند به BTC-USDT
        if "-" not in symbol:
            symbol = f"{symbol}-USDT"

    p = get_price(symbol)

    if p:
        await update.message.reply_text(f"{symbol} price: {p}")
    else:
        await update.message.reply_text("Error getting price")

# ---------- BOT ----------
def run_bot():
    token = os.environ.get("BOT_TOKEN")

    if not token:
        raise ValueError("BOT_TOKEN not set")

    # Fix for Python asyncio event loop issue
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    bot_app = ApplicationBuilder().token(token).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("status", status))
    bot_app.add_handler(CommandHandler("price", price))

    print("Bot started...", flush=True)

    bot_app.run_polling(
        drop_pending_updates=True
    )

# ---------- MAIN ----------
if __name__ == "__main__":
    print("Starting Flask thread...", flush=True)
    threading.Thread(target=run_flask, daemon=True).start()

    print("Starting Telegram bot...", flush=True)
    run_bot()
