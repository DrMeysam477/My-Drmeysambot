import os
import asyncio
from telegram import Bot
from flask import Flask
from threading import Thread

# دریافت توکن و آیدی چت از Environment Variables رندر
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running!"

async def send_test_message():
    if not BOT_TOKEN or not CHAT_ID:
        print("خطا: BOT_TOKEN یا CHAT_ID تنظیم نشده است!")
        return
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=CHAT_ID, text="✅ ربات با نسخه جدید (20.7) در رندر آنلاین شد!")
        print("Message sent successfully!")
    except Exception as e:
        print(f"Error: {e}")

def run_flask():
    # رندر از پورت محیطی استفاده می‌کند
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # اجرای فلاسک در یک ترد جداگانه برای جلوگیری از بسته شدن پورت توسط رندر
    Thread(target=run_flask).start()

    # اجرای عملیات تلگرام
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_test_message())
