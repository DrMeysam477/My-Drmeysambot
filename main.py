import os
import asyncio
import threading
from flask import Flask
from telegram.ext import ApplicationBuilder

# بخش Flask برای عبور از سد Health Check رندر
app = Flask(__name__)

@app.route('/')
def health_check():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

async def start_bot():
    # توکن خود را اینجا بگذار
    TOKEN = "YOUR_BOT_TOKEN_HERE"
    
    # ساخت اپلیکیشن با متد جدید
    application = ApplicationBuilder().token(TOKEN).build()
    
    # اگر هندلر داری اینجا اضافه کن (مثلا start_handler)
    
    print("Starting bot polling...")
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        # ایجاد یک حلقه بی‌پایان برای باز ماندن ربات
        while True:
            await asyncio.sleep(1)

if __name__ == '__main__':
    # ۱. اجرای وب‌سرور در ترد جداگانه
    threading.Thread(target=run_flask, daemon=True).start()
    
    # ۲. اجرای ربات تلگرام در حلقه اصلی
    try:
        asyncio.run(start_bot())
    except (KeyboardInterrupt, SystemExit):
        pass
