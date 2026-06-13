import telebot
import os
from flask import Flask
from threading import Thread

# ۱. تنظیمات اولیه
BOT_TOKEN = 'توکن_ربات_خودت_را_اینجا_بگذار'
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ۲. بخشی که Render لازم دارد تا ربات را خاموش نکند
@app.route('/')
def health_check():
    return "Bot is alive! ✅", 200

def run_web_server():
    # Render پورت را به صورت خودکار به ما می‌دهد
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ۳. دستورات ربات (نمونه)
@bot.message_handler(commands=['start', 'status'])
def send_welcome(message):
    bot.reply_to(message, "ربات با موفقیت در Render فعال است! 🚀")

# ۴. اجرای همزمان وب‌سرور و ربات
if __name__ == "__main__":
    # اجرای وب‌سرور در یک رشته جداگانه
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    
    print("Starting Bot Polling...")
    # اجرای ربات
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        print(f"Error: {e}")
