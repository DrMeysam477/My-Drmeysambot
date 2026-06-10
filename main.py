import telebot
import requests
from flask import Flask
from threading import Thread
import os

# تنظیمات توکن و اپلیکیشن
TOKEN = '7308703445:AAH_0N-R0N6_v7fC7zCjW0W5vW_9mY0mY8o' # توکن شما محفوظ است
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running!"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "سلام! ربات تحلیلگر فعال شد.\nبرای دریافت قیمت از دستور زیر استفاده کنید:\n/signal BTCIRT")

@bot.message_handler(commands=['signal'])
def get_signal(message):
    try:
        text = message.text.split()
        if len(text) < 2:
            bot.reply_to(message, "⚠️ لطفا نماد را وارد کنید.\nمثال: /signal BTCIRT")
            return
        
        symbol = text[1].upper()
        sent_msg = bot.reply_to(message, f"⌛ در حال استعلام قیمت {symbol} از نوبیتکس...")
        
        # استفاده از API جایگزین برای دور زدن محدودیت سرور خارجی
        url = "https://api.nobitex.ir/market/stats"
        params = {'srcCurrency': symbol.replace('IRT', '').lower(), 'dstCurrency': 'irt'}
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if data['status'] == 'ok':
            stats = data['stats'][f"{params['srcCurrency']}-irt"]
            msg = (f"✅ قیمت لحظه‌ای {symbol}:\n\n"
                   f"💰 قیمت: {float(stats['latest']):,.0f} ریال\n"
                   f"📈 تغییر ۲۴ ساعته: {stats['dayChange']}%\n"
                   f"🔝 بیشترین امروز: {float(stats['dayHigh']):,.0f}\n"
                   f"🔙 کمترین امروز: {float(stats['dayLow']):,.0f}")
            bot.edit_message_text(msg, chat_id=message.chat.id, message_id=sent_msg.message_id)
        else:
            bot.edit_message_text("❌ نماد مورد نظر یافت نشد یا در نوبیتکس لیست نیست.", chat_id=message.chat.id, message_id=sent_msg.message_id)

    except Exception as e:
        bot.reply_to(message, "❌ خطا در برقراری ارتباط با صرافی. لطفا دوباره تلاش کنید.")

if __name__ == "__main__":
    # اجرای فلسک در یک ترد جداگانه
    t = Thread(target=run_flask)
    t.start()
    # اجرای ربات
    print("Bot is starting...")
    bot.infinity_polling(non_stop=True, skip_pending=True)
