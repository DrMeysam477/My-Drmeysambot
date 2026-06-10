import telebot
import requests
from flask import Flask
from threading import Thread
import os

# خواندن امن توکن از تنظیمات Render
TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "سلام! ربات تحلیلگر به بای‌بیت متصل شد.\nبرای دریافت قیمت از این فرمت استفاده کنید:\n/signal BTCUSDT")

@bot.message_handler(commands=['signal'])
def get_signal(message):
    try:
        text = message.text.split()
        if len(text) < 2:
            bot.reply_to(message, "⚠️ لطفا نماد را با جفت ارز وارد کنید.\nمثال: /signal BTCUSDT")
            return
        
        symbol = text[1].upper()
        sent_msg = bot.reply_to(message, f"⌛ در حال استعلام {symbol} از بای‌بیت...")
        
        # اتصال به API نسخه 5 بای‌بیت
        url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}"
        response = requests.get(url, timeout=10)
        data = response.json()

        # بررسی پاسخ بای‌بیت
        if data.get('retCode') == 0 and len(data['result']['list']) > 0:
            ticker = data['result']['list'][0]
            price = ticker['lastPrice']
            high = ticker['highPrice24h']
            low = ticker['lowPrice24h']
            change = float(ticker['price24hPcnt']) * 100
            
            msg = (f"✅ قیمت لحظه‌ای {symbol}:\n\n"
                   f"💰 قیمت: {float(price):,.2f} USDT\n"
                   f"📈 تغییر ۲۴ ساعته: {change:.2f}%\n"
                   f"🔝 سقف ۲۴س: {float(high):,.2f}\n"
                   f"🔙 کف ۲۴س: {float(low):,.2f}")
            
            bot.edit_message_text(msg, chat_id=message.chat.id, message_id=sent_msg.message_id)
        else:
            bot.edit_message_text("❌ نماد یافت نشد. مطمئن شوید درست تایپ کردید (مثلاً BTCUSDT).", 
                                  chat_id=message.chat.id, message_id=sent_msg.message_id)

    except Exception as e:
        bot.reply_to(message, f"❌ خطا: {e}")

if __name__ == "__main__":
    t = Thread(target=run_flask)
    t.start()
    print("Bot is starting...")
    bot.infinity_polling()
