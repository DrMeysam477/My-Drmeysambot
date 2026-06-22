import os
import asyncio
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# تنظیمات اصلی
TOKEN = os.getenv("BOT_TOKEN")
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Alive!", 200

# تابعی که در عکس داشتی (نمونه)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Scanner started ✅\nهر ۱۵ دقیقه بازار را اسکن می‌کنم.")

async def run_bot():
    # ساخت اپلیکیشن ربات
    application = Application.builder().token(TOKEN).build()
    
    # اضافه کردن دستورات
    application.add_handler(CommandHandler("start", start))
    
    # شروع به کار ربات
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # نگه داشتن ربات در حالت اجرا
    await asyncio.Event().wait()

def start_telegram():
    asyncio.run(run_bot())

if __name__ == "__main__":
    # ۱. اجرای ربات در یک Thread جداگانه
    threading.Thread(target=start_telegram, daemon=True).start()
    
    # ۲. اجرای Flask روی پورت Render (رشته اصلی)
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
