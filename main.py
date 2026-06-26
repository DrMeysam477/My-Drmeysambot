import os
import asyncio
import threading
import requests
import pandas as pd
from flask import Flask
from telegram.ext import ApplicationBuilder, CommandHandler

# تنظیمات
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)

# وب سرور ساده برای اینکه Render فکر کند سرویس فعال است
@app.route('/')
def home(): 
    return "Bot is running perfectly!", 200

# تابع اسکن بازار (تست)
def analyze_market():
    # اینجا منطق اسکن شما قرار می‌گیرد
    return "بازار بررسی شد."

async def start(update, context):
    await update.message.reply_text("ربات فعال شد و آماده اسکن است.")

async def bot_loop():
    # ساخت اپلیکیشن
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    
    # شروع پولینگ تلگرام (بدون بستن لوپ)
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    print("Telegram bot polling started...")
    # نگه داشتن برنامه در حال اجرا
    await asyncio.Event().wait()

def run_async_code():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot_loop())

# اجرای ربات در یک ترد (Thread) جداگانه تا با وب‌سرور تداخل نکند
threading.Thread(target=run_async_code, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
