import os
import telebot
from flask import Flask
from threading import Thread

# 1. تنظیمات توکن (حتماً توکن خودت را جایگزین کن)
API_TOKEN = 'YOUR_BOT_TOKEN_HERE'
bot = telebot.TeleBot(API_TOKEN)

# 2. تنظیم فلاسک برای زنده نگه داشتن سرور در Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    # Render از پورت 10000 استفاده می‌کند
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# 3. هندلرهای ربات (نمونه)
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Bot started ✅")

@bot.message_handler(commands=['status'])
def send_status(message):
    bot.reply_to(message, "Bot is running on Render ✅")

# اینجا بقیه هندلرهای /signal و /scan را که قبلاً داشتیم اضافه کن...

# 4. اجرای همزمان فلاسک و بات
if __name__ == "__main__":
    print("Starting Flask...")
    # اجرای فلاسک در یک Thread جداگانه
    t = Thread(target=run_flask)
    t.start()
    
    print("Bot started...")
    # اجرای بات در Thread اصلی به صورت بی‌پایان
    bot.infinity_polling()
