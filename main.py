import os
import requests
import telebot
from flask import Flask
from threading import Thread

# تنظیمات توکن تلگرام از محیط رندر
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is Online"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "✅ ربات با موفقیت فعال شد!\n\nراهنما:\nارسال دستور /signal و نام ارز\nمثال: `/signal BTC` یا `/signal ETHUSDT`")

@bot.message_handler(commands=['signal'])
def get_signal(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ لطفاً نام ارز را بنویسید.\nمثال: /signal BTC")
            return
        
        # تمیز کردن نام ارز (فقط بخش اول را می‌گیرد، مثلا BTC)
        symbol = parts[1].upper().replace("USDT", "").strip()
        
        # استفاده از منبع CoinGecko (بسیار پایدار برای سرورهای ابری)
        # ابتدا آیدی ارز را پیدا می‌کنیم (مثلاً برای BTC آیدی bitcoin است)
        search_url = f"https://api.coingecko.com/api/v3/search?query={symbol}"
        search_resp = requests.get(search_url, timeout=10)
        
        if search_resp.status_code == 200:
            search_data = search_resp.json()
            if search_data.get("coins"):
                coin_id = search_data["coins"][0]["id"] # اولین نتیجه جستجو
                
                # گرفتن قیمت نهایی بر اساس آیدی
                price_url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
                price_resp = requests.get(price_url, timeout=10)
                price_data = price_resp.json()
                
                if coin_id in price_data:
                    price = price_data[coin_id]["usd"]
                    formatted_price = "{:,.2f}".format(float(price))
                    bot.reply_to(message, f"💰 قیمت لحظه‌ای {symbol}\n\n💵 قیمت: {formatted_price} دلار")
                else:
                    bot.reply_to(message, "❌ قیمت در حال حاضر در دسترس نیست.")
            else:
                bot.reply_to(message, f"❌ ارز '{symbol}' پیدا نشد.")
        else:
            bot.reply_to(message, f"❌ خطا در استعلام (کد {search_resp.status_code})")

    except Exception as e:
        bot.reply_to(message, f"❌ خطای سیستمی: {str(e)}")

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    bot.infinity_polling()
