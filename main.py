import os
import threading
from flask import Flask
from telegram.ext import ApplicationBuilder

# راه اندازی سرور Flask برای رفع خطای پورت رندر
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    # رندر پورت را از محیط سیستم می‌خواند
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def main():
    # توکن خود را اینجا قرار دهید
    TOKEN = "YOUR_BOT_TOKEN_HERE"
    
    # ساخت اپلیکیشن ربات
    application = ApplicationBuilder().token(TOKEN).build()
    
    print("Bot is starting...")
    # اجرای پولینگ ربات
    application.run_polling()

if __name__ == '__main__':
    # اجرای وب‌سرور در پس‌زمینه
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # اجرای ربات در ترد اصلی
    main()
