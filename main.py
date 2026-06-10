import os
import telebot
import pandas as pd
import numpy as np
import requests
from flask import Flask

# تنظیمات توکن و سرور
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# لیست کلمات ممنوعه و فیلتر لینک
BAD_WORDS = ['کلمه۱', 'کلمه۲'] # می‌توانید کلمات را اینجا اضافه کنید

@bot.message_handler(func=lambda message: True)
def filter_messages(message):
    # ضد لینک
    if 't.me/' in message.text or 'http' in message.text:
        bot.delete_message(message.chat.id, message.message_id)
        bot.send_message(message.chat.id, "❌ ارسال لینک مجاز نیست.")
        return

    # ضد فحش
    if any(word in message.text for word in BAD_WORDS):
        bot.delete_message(message.chat.id, message.message_id)
        bot.send_message(message.chat.id, "⚠️ لطفا از کلمات مناسب استفاده کنید.")
        return

    # دستور استارت
    if message.text == '/start':
        bot.reply_to(message, "سلام! من ربات تحلیل‌گر نوبیتکس و مدیریت گروه هستم. برای دریافت سیگنال از /signal استفاده کنید.")

# بخش تحلیل نوبیتکس
@bot.message_handler(commands=['signal'])
def get_signal(message):
    try:
        symbol = message.text.split()[1].upper()
        # در اینجا منطق تحلیل تکنیکال که قبلاً نوشتیم قرار می‌گیرد
        bot.reply_to(message, f"📊 در حال تحلیل جفت ارز {symbol}...")
    except:
        bot.reply_to(message, "❌ لطفا نماد را درست وارد کنید. مثال: /signal BTCIRT")

# مسیر سلامت برای Render (بسیار مهم)
@app.route('/')
def health_check():
    return "Bot is Running!", 200

# اجرای ربات
if __name__ == "__main__":
    print("Bot is starting...")
    # حذف وب‌هوک قدیمی برای جلوگیری از تداخل
    bot.remove_webhook()
    # اجرای Flask در پس‌زمینه برای راضی نگه داشتن Render
    from threading import Thread
    def run_flask():
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
    
    Thread(target=run_flask).start()
    
    # اجرای اصلی ربات
    bot.infinity_polling()
