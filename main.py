import os
from flask import Flask
import threading
from telegram.ext import ApplicationBuilder

# ۱. ساخت یک سرور وب کوچک برای راضی نگه داشتن Render
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    # Render پورت را در Variable ای به نام PORT قرار می‌دهد
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ۲. کد اصلی ربات شما
def main():
    # توکن خودت را اینجا بگذار
    TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
    
    application = ApplicationBuilder().token(TOKEN).build()
    
    # تنظیمات ربات (Handlers) را اینجا اضافه کن...
    
    print("Bot started...")
    application.run_polling()

if __name__ == '__main__':
    # اجرای سرور وب در یک ترد جداگانه
    threading.Thread(target=run_flask).start()
    
    # اجرای ربات
    main()
