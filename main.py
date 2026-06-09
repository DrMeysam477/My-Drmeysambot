import telebot
from flask import Flask
from threading import Thread

# ۱. تنظیمات ربات
API_TOKEN = '8979791105:AAFE_r734rshq0Ufl' 
bot = telebot.TeleBot(API_TOKEN)
app = Flask('')

# ۲. بخش وب‌سایت برای رندر
@app.route('/')
def home():
    return "Bot is Running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ۳. دستورات ربات تلگرام
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "✅ ربات مدیریت با موفقیت فعال شد!")

@bot.message_handler(commands=['del'])
def delete_message(message):
    try:
        if message.reply_to_message:
            bot.delete_message(message.chat.id, message.reply_to_message.message_id)
            bot.delete_message(message.chat.id, message.message_id)
    except:
        pass

@bot.message_handler(commands=['pin'])
def pin_message(message):
    try:
        if message.reply_to_message:
            bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id)
    except:
        pass

# ۴. اجرای همزمان
if __name__ == "__main__":
    keep_alive()
    bot.infinity_polling()
