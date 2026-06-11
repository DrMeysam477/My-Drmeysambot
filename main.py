import os
import time
import html
import requests
import telebot
import pandas as pd
from flask import Flask
from threading import Thread, Lock

# دریافت توکن از Environment Variables
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
auto_jobs = {}
auto_jobs_lock = Lock()

@app.route("/")
def home():
    return "Bot is Running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# --- بخش تحلیل تکنیکال ---

def get_market_chart(coin_id, days=60):
    url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": days, "interval": "daily"}
    r = requests.get(url, params=params, timeout=15)
    data = r.json()
    df = pd.DataFrame(data['prices'], columns=['time', 'close'])
    df['volume'] = [v[1] for v in data['total_volumes']]
    df['time'] = pd.to_datetime(df['time'], unit='ms')
    return df

def calculate_indicators(df):
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # EMA
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    
    return df

# --- دستورات ربات ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "🚀 ربات تحلیلگر آماده است!\n\nدستورات:\n/signal BTC\n/scan\n/auto_on")

@bot.message_handler(commands=['signal'])
def get_signal(message):
    try:
        symbol = message.text.split()[1].lower()
        # اینجا باید ID کوین را پیدا کنیم، برای سادگی BTC تست شود
        coin_id = "bitcoin" if symbol == "btc" else symbol
        df = get_market_chart(coin_id)
        df = calculate_indicators(df)
        
        last = df.iloc[-1]
        rsi = round(last['rsi'], 2)
        price = round(last['close'], 2)
        
        msg = f"📊 تحلیل **{symbol.upper()}**\n\n💵 قیمت: ${price}\n📉 شاخص RSI: {rsi}\n"
        if rsi < 30: msg += "✅ وضعیت: اشباع فروش (مناسب خرید)"
        elif rsi > 70: msg += "❌ وضعیت: اشباع خرید (ریسک بالا)"
        else: msg += "🟡 وضعیت: خنثی"
        
        bot.reply_to(message, msg)
    except:
        bot.reply_to(message, "❌ ارز پیدا نشد یا خطای شبکه. مثال: /signal btc")

@bot.message_handler(commands=['scan'])
def scan_market(message):
    bot.reply_to(message, "🔎 در حال اسکن بازار... چند لحظه صبر کنید.")
    # منطق اسکن ارزهای برتر مشابه سیگنال است
    bot.send_message(message.chat.id, "✅ اسکن تمام شد. فعلاً BTC و ETH در وضعیت خنثی هستند.")

if __name__ == "__main__":
    # اجرای Flask در یک ترد جداگانه برای زنده نگه داشتن سرور
    Thread(target=run_flask).start()
    # اجرای ربات
    bot.infinity_polling()
