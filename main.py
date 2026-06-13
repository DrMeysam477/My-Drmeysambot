import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import ccxt

# تنظیمات Flask برای Health Check در Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running!"

def run_flask():
    # Render از پورت 10000 استفاده می‌کند
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# تابع گرفتن قیمت با استفاده از CCXT
def get_crypto_price(symbol="BTC/USDT"):
    try:
        exchange = ccxt.okx() # استفاده از صرافی OKX
        ticker = exchange.fetch_ticker(symbol)
        return ticker['last']
    except Exception as e:
        print(f"Error fetching price: {e}")
        return None

# دستور /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! ربات تحلیل‌گر شما آنلاین است. 🚀\nبا دستور /price قیمت لحظه‌ای را بگیرید.")

# دستور /status
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("وضعیت: ربات روی سرور Render فعال است. ✅")

# دستور /price (نسخه پیشرفته با CCXT)
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price_val = get_crypto_price("BTC/USDT")
    if price_val:
        await update.message.reply_text(f"💰 قیمت لحظه‌ای BTC-USDT: {price_val:,} دلار")
    else:
        await update.message.reply_text("خطا در دریافت قیمت. لطفا دوباره تلاش کنید.")

if __name__ == '__main__':
    # اجرای Flask در یک ترد جداگانه
    threading.Thread(target=run_flask).start()

    # تنظیمات ربات تلگرام
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        print("Error: BOT_TOKEN not found in environment variables!")
    else:
        application = ApplicationBuilder().token(TOKEN).build()
        
        # اضافه کردن دستورات به ربات
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("price", price))
        
        print("Bot started...")
        application.run_polling()
