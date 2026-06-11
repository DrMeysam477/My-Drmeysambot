import os
import requests
import telebot
from flask import Flask
from threading import Thread

TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is Running"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "✅ ربات آماده است!\nمثال: /signal BTCUSDT")

@bot.message_handler(commands=['signal'])
def get_signal(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "مثال: /signal BTCUSDT")
            return
        
        symbol = parts[1].upper().strip()
        
        # هدر برای دور زدن مسدودی صرافی (شبیه‌سازی مرورگر)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        # استفاده از API جایگزین (Binance) اگر Bybit باز هم اذیت کرد
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            price = data.get("price")
            # رند کردن قیمت برای زیبایی
            formatted_price = "{:,.2f}".format(float(price))
            bot.reply_to(message, f"💰 قیمت لحظه‌ای {symbol}\n\n💵 قیمت: {formatted_price} USDT")
        elif response.status_code == 400:
            bot.reply_to(message, f"❌ نماد {symbol} اشتباه است. (مثال درست: BTCUSDT)")
        else:
            bot.reply_to(message, f"❌ صرافی پاسخ نداد (کد {response.status_code})")

    except Exception as e:
        bot.reply_to(message, f"❌ خطا: {str(e)}")

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    bot.infinity_polling()
