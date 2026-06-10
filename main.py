import os
import requests
import telebot
from flask import Flask
from threading import Thread

# تنظیمات توکن
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is Alive"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "✅ ربات با موفقیت متصل شد.\nاستفاده: /signal BTCUSDT")

@bot.message_handler(commands=['signal'])
def get_signal(message):
    try:
        # جدا کردن نام نماد
        text_parts = message.text.split()
        if len(text_parts) < 2:
            bot.reply_to(message, "لطفاً نماد را وارد کنید. مثال: /signal BTCUSDT")
            return
        
        symbol = text_parts[1].upper().strip()
        bot.reply_to(message, f"⌛ در حال استعلام قیمت {symbol} از Bybit...")

        # دریافت قیمت از API بای‌بیت
        url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}"
        response = requests.get(url, timeout=10)
        
        # بررسی اینکه آیا پاسخ معتبر است
        if response.status_code != 200:
            bot.reply_to(message, f"❌ خطا در اتصال به صرافی (کد {response.status_code})")
            return

        data = response.json()
        
        # استخراج قیمت
        if data.get("retCode") == 0 and data["result"]["list"]:
            ticker = data["result"]["list"][0]
            last_price = ticker.get("lastPrice")
            high_24h = ticker.get("high24h")
            
            msg = (f"💰 قیمت لحظه‌ای {symbol}\n\n"
                   f"💵 قیمت: {last_price} USDT\n"
                   f"📈 سقف ۲۴ ساعته: {high_24h}")
            bot.reply_to(message, msg)
        else:
            bot.reply_to(message, f"❌ نماد {symbol} در بای‌بیت یافت نشد.")

    except Exception as e:
        bot.reply_to(message, f"❌ خطای غیرمنتظره: {str(e)}")

if __name__ == "__main__":
    # اجرای فلسک در ترد جداگانه برای زنده نگه داشتن سرویس
    Thread(target=run_flask, daemon=True).start()
    # شروع به کار ربات
    bot.infinity_polling()
