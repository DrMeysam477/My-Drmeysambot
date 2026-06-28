import os
import threading
import requests
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# تنظیمات
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)

@app.route('/')
def health_check():
    return "OK", 200

def get_price():
    try:
        url = "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT"
        res = requests.get(url, timeout=5).json()
        return f"BTC Price: {res['data'][0]['last']} USDT"
    except:
        return "Price error."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ربات آنلاین شد! برای قیمت /price بزنید.")

async def send_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_price())

def run_bot():
    if not BOT_TOKEN:
        print("BOT_TOKEN NOT FOUND")
        return
    # ساخت اپلیکیشن نسخه ۲۰+
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("price", send_price))
    print("Starting Telegram Polling...")
    app_bot.run_polling(close_loop=False)

if __name__ == "__main__":
    # اجرای تلگرام در یک ترد مجزا
    threading.Thread(target=run_bot, daemon=True).start()
    
    # اجرای سریع فلسک برای اینکه رندر ارور پورت ندهد
    print(f"Starting Flask on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
