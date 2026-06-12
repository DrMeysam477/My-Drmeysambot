import os
import threading
from flask import Flask
from telegram.ext import ApplicationBuilder

# بخش Flask برای Render
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# بخش ربات تلگرام
def main():
    # توکن خودت را پایین بگذار
    TOKEN = "YOUR_BOT_TOKEN_HERE"
    
    application = ApplicationBuilder().token(TOKEN).build()
    
    # هندلرهای رباتت را اگر داری اینجا اضافه کن
    
    print("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    # اجرای همزمان سرور و ربات
    threading.Thread(target=run_flask, daemon=True).start()
    main()
