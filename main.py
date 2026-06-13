import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import ccxt

# تنظیمات Flask برای Health Check
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def get_crypto_price(symbol="BTC/USDT"):
    try:
        exchange = ccxt.okx()
        ticker = exchange.fetch_ticker(symbol)
        return ticker['last']
    except Exception as e:
        print(f"Error: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! ربات آنلاین شد. 🚀")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = get_crypto_price("BTC/USDT")
    if p:
        await update.message.reply_text(f"💰 قیمت بیت‌کوین: {p:,} دلار")
    else:
        await update.message.reply_text("خطا در دریافت قیمت.")

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    TOKEN = os.environ.get("BOT_TOKEN")
    if TOKEN:
        app_tg = ApplicationBuilder().token(TOKEN).build()
        app_tg.add_handler(CommandHandler("start", start))
        app_tg.add_handler(CommandHandler("price", price))
        print("Bot started...")
        app_tg.run_polling()
