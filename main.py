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
    return "Bot is Active"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "✅ ربات با منبع جدید فعال شد!\nمثال: /signal BTC")

@bot.message_handler(commands=['signal'])
def get_signal(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "مثال: /signal BTC")
            return
        
        # در این منبع، فقط نماد اصلی کافی است (مثل BTC به جای BTCUSDT)
        symbol = parts[1].upper().replace("USDT", "").strip()
        
        # استفاده از منبع CryptoCompare که روی سرورها محدودیت کمتری دارد
        url = f"https://min-api.cryptocompare.com/data/price?fsym={symbol}&tsyms=USDT"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if "USDT" in data:
                price = data["USDT"]
                # فرمت‌دهی عدد
                formatted_price = "{:,.2f}".format(float(price))
                bot.reply_to(message, f"💰 قیمت لحظه‌ای {symbol}\n\n💵 قیمت: {formatted_price} USDT")
            else:
                bot.reply_to(message, f"❌ نماد {symbol} معتبر نیست.")
        else:
            bot.reply_to(message, f"❌ خطا در استعلام (کد {response.status_code})")

    except Exception as e:
        bot.reply_to(message, f"❌ خطا: {str(e)}")

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    bot.infinity_polling()
