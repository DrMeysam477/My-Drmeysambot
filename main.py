import os
import threading
import requests
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---------- Flask for Render ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ---------- OKX DATA ----------
def get_price(symbol="BTC-USDT"):
    url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}"
    r = requests.get(url, timeout=10)
    data = r.json()

    if data["code"] == "0":
        price = data["data"][0]["last"]
        return price
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

    p = get_price(symbol)

    if p:
        await update.message.reply_text(f"{symbol} price: {p}")
    else:
        await update.message.reply_text("Error getting price")

# ---------- MAIN ----------

def run_bot():
    token = os.environ.get("BOT_TOKEN")

    if not token:
        raise ValueError("BOT_TOKEN not set")

    app_bot = ApplicationBuilder().token(token).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("status", status))
    app_bot.add_handler(CommandHandler("price", price))

    print("Bot started...")
    app_bot.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    run_bot()
