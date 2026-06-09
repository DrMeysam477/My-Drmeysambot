import telebot
import os
from flask import Flask
from threading import Thread

# ۱. تنظیمات ربات
API_TOKEN = '8979791105:AAFE_r734rshqOUfkaEDPSidXptpGxXIYHs'
bot = telebot.TeleBot(API_TOKEN)

# ۲. بخش فریب دادن رندر (ساخت یک وب‌سایت فیک)
app = Flask('')

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
    bot.reply_to(message, "سلام! ربات شما در رندر با موفقیت فعال شد ✅")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, message.text)

# ۴. اجرای همزمان وب‌سایت و ربات
if __name__ == "__main__":
    keep_alive()  # این خط باعث می‌شود رندر ارور پورت ندهد
    print("Bot is starting...")
    bot.infinity_polling()

