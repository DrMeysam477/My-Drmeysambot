import os
import asyncio
import threading
import requests
import pandas as pd
from flask import Flask
from telegram import Bot
from telegram.ext import Updater, CommandHandler

# تنظیمات
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!", 200

# تابع اسکن بازار (تست)
def analyze_market():
    try:
        # یک تست ساده برای ارسال قیمت بیت کوین
        url = "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=1"
        r = requests.get(url, timeout=10)
        data = r.json().get("data", [])
        if data:
            price = float(data[0][4])
            return f"آخرین قیمت بیت کوین: {price:.2f}"
        return "خطا در دریافت قیمت بیت کوین."
    except Exception as e:
        return f"خطا در اسکن: {e}"

async def send_market_update(bot):
    while True:
        try:
            if CHAT_ID and TOKEN:
                analysis = analyze_market()
                await bot.send_message(chat_id=CHAT_ID, text=analysis)
            await asyncio.sleep(600) # هر ۱۰ دقیقه یکبار
        except Exception as e:
            print(f"Error in send_market_update: {e}")
            await asyncio.sleep(60) # تاخیر بیشتر در صورت خطا

def run_telegram_bot():
    if not TOKEN or not CHAT_ID:
        print("Error: BOT_TOKEN or CHAT_ID not set.")
        return

    bot = Bot(token=TOKEN)
    # برای سازگاری بیشتر با نسخه‌های جدید python-telegram-bot، از ApplicationBuilder استفاده نمی‌کنیم
    # و به جای آن Bot و Updater را مستقیماً مقداردهی می‌کنیم.
    updater = Updater(bot=bot, use_context=True) # یا: updater = Updater(token=TOKEN) اگر Bot را جدا نساختیم

    # دستور start
    async def start(update, context):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="ربات با موفقیت فعال شد!")

    updater.dispatcher.add_handler(CommandHandler("start", start, run_async=True))

    # اجرای حلقه اصلی تلگرام
    # در نسخه‌های جدید python-telegram-bot، نیازی به مدیریت مستقیم loop نیست
    # و start_polling به تنهایی کافیست.
    updater.start_polling()
    print("Telegram bot polling started...")
    updater.idle()

if __name__ == "__main__":
    # اطمینان از اینکه توکن وجود دارد قبل از اجرای ربات
    if TOKEN:
        # اجرای ربات تلگرام در یک ترد جداگانه
        thread = threading.Thread(target=run_telegram_bot, daemon=True)
        thread.start()
        print("Telegram bot thread started...")
    else:
        print("BOT_TOKEN environment variable not set. Telegram bot will not start.")

    # اجرای برنامه Flask
    app.run(host="0.0.0.0", port=PORT)
