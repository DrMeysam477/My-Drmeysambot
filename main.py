import os, threading, requests, telebot
import pandas as pd
from flask import Flask

# تنظیمات اصلی
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
PORT = int(os.getenv("PORT", "10000"))

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

@app.route('/')
def health_check():
    return "Bot is Running", 200

def get_signal(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=50"
        data = requests.get(url, timeout=10).json()
        df = pd.DataFrame(data, columns=['t','o','h','l','c','v','ct','qv','n','tb','tg','i'])
        close = df['c'].astype(float)
        
        # محاسبه RSI ساده
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]
        
        last_price = close.iloc[-1]
        return f"✅ {symbol}: ${last_price} | RSI: {round(rsi, 1)}"
    except:
        return None

@bot.message_handler(commands=['start'])
def start(m):
    bot.reply_to(m, "سلام! ربات اسکنر روشن است.\nبرای تحلیل لیست ارزها دستور /scan را بزنید.")

@bot.message_handler(commands=['scan'])
def scan(m):
    bot.reply_to(m, "🔍 در حال اسکن ارزهای برتر...")
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT"]
    results = []
    for s in symbols:
        res = get_signal(s)
        if res: results.append(res)
    
    bot.send_message(m.chat.id, "\n".join(results) if results else "خطا در دریافت داده")

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    if not TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN is not set!")
    else:
        # ابتدا سرور فلاسک را برای تایید Render بالا می‌آوریم
        threading.Thread(target=run_flask).start()
        print("Flask server started...")
        # سپس تلگرام را استارت می‌زنیم
        print("Bot polling started...")
        bot.infinity_polling()
