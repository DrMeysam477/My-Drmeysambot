import os
import requests
import telebot
from flask import Flask
from threading import Thread

TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is Running"

def run():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "ربات فعال است! از دستور /signal BTCUSDT استفاده کنید.")

@bot.message_handler(commands=['signal'])
def get_signal(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "مثال: /signal BTCUSDT")
            return
        
        symbol = parts[1].upper()
        bot.reply_to(message, f"⌛ در حال استعلام {symbol}...")
        
        url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get('retCode') == 0 and data['result']['list']:
            ticker = data['result']['list'][0]
            price = ticker['lastPrice']
            bot.reply_to(message, f"✅ قیمت {symbol}: {price} USDT")
        else:
            bot.reply_to(message, "❌ نماد پیدا نشد یا خطا در صرافی.")
    except Exception as e:
        bot.reply_to(message, f"❌ خطا: {e}")

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling()
