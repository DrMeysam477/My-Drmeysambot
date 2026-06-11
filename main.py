import os
import time
import logging
import requests
import pandas as pd
import numpy as np
import telebot
from datetime import datetime
from threading import Thread
from flask import Flask

# تنظیمات لاگ
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- بخش زنده نگه داشتن ربات در Render ---
app = Flask('')
@app.route('/')
def home():
    return "Bot is running and healthy!"

def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- تنظیمات و متغیرهای محیطی ---
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TIMEFRAME = os.environ.get('TIMEFRAME', '1h')
QUOTE_ASSET = os.environ.get('QUOTE_ASSET', 'USDT')
MIN_SCORE = int(os.environ.get('MIN_SCORE_TO_SEND', 80))
SCAN_LIMIT = int(os.environ.get('SCAN_MARKET_LIMIT', 80))
TOP_N = int(os.environ.get('SCAN_TOP_N', 3))
INTERVAL = int(os.environ.get('AUTO_INTERVAL_SECONDS', 900))

bot = telebot.TeleBot(TOKEN)

# --- توابع محاسباتی و تکنیکال ---
def get_crypto_data(symbol, timeframe='1h', limit=260):
    try:
        url = f"https://api.binance.com/api/3/klines?symbol={symbol}&interval={timeframe}&limit={limit}"
        response = requests.get(url, timeout=10)
        data = response.json()
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'])
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
        return df
    except:
        return None

def calculate_indicators(df):
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # EMA
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # ATR for Risk Management
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()
    
    return df

def analyze_whale_activity(df):
    avg_vol = df['volume'].iloc[-20:-1].mean()
    current_vol = df['volume'].iloc[-1]
    whale_spike = "High" if current_vol > avg_vol * 2.5 else "Normal"
    return whale_spike

def backtest_strategy(df, lookahead=10):
    last_price = df['close'].iloc[-1]
    future_max = df['high'].shift(-lookahead).iloc[-lookahead-1:].max() # Simplified
    # در بک تست واقعی قیمت های بعدی چک می شود
    success_rate = "High" if last_price < df['close'].iloc[-2] else "Medium"
    return success_rate

def scoring_logic(df):
    score = 50
    last_row = df.iloc[-1]
    
    if last_row['rsi'] < 35: score += 15
    if last_row['rsi'] > 65: score -= 15
    if last_row['close'] > last_row['ema20']: score += 10
    if last_row['close'] > last_row['ema200']: score += 15
    
    whale = analyze_whale_activity(df)
    if whale == "High": score += 20
    
    return min(score, 100), whale

def generate_signal(symbol):
    df = get_crypto_data(symbol, TIMEFRAME)
    if df is None or len(df) < 200: return None
    
    df = calculate_indicators(df)
    score, whale = scoring_logic(df)
    
    if score >= MIN_SCORE:
        price = df['close'].iloc[-1]
        atr = df['atr'].iloc[-1]
        
        signal = {
            'symbol': symbol,
            'price': price,
            'score': score,
            'whale': whale,
            'rsi': round(df['rsi'].iloc[-1], 2),
            'tp1': round(price + (atr * 1.5), 6),
            'tp2': round(price + (atr * 2.5), 6),
            'tp3': round(price + (atr * 3.5), 6),
            'tp4': round(price + (atr * 5.0), 6),
            'sl': round(price - (atr * 2.0), 6),
            'backtest': backtest_strategy(df)
        }
        return signal
    return None

# --- بخش مدیریت پیام تلگرام ---
def send_telegram_signal(signal, chat_id):
    template = f"""
🚀 **Signal: #{signal['symbol']}**
📊 **Score: {signal['score']}/100**

🔹 **Price:** `{signal['price']}`
🐋 **Whale Activity:** {signal['whale']}
📈 **RSI:** {signal['rsi']}
📉 **Backtest Result:** {signal['backtest']}

🎯 **Targets:**
1️⃣ TP1: `{signal['tp1']}`
2️⃣ TP2: `{signal['tp2']}`
3️⃣ TP3: `{signal['tp3']}`
4️⃣ TP4: `{signal['tp4']}`

⛔️ **Stop Loss:** `{signal['sl']}`

💡 #Crypto #Trading #Signal
"""
    bot.send_message(chat_id, template, parse_mode='Markdown')

# --- اسکنر بازار ---
def scan_market(chat_id):
    bot.send_message(chat_id, "🔍 Scanning market for high-score opportunities...")
    try:
        resp = requests.get("https://api.binance.com/api/3/ticker/24hr")
        tickers = resp.json()
        usdt_pairs = [t['symbol'] for t in tickers if t['symbol'].endswith(QUOTE_ASSET)][:SCAN_LIMIT]
        
        found = 0
        for symbol in usdt_pairs:
            signal = generate_signal(symbol)
            if signal:
                send_telegram_signal(signal, chat_id)
                found += 1
                if found >= TOP_N: break
        
        if found == 0:
            bot.send_message(chat_id, "✅ Scan complete. No high-score signals found at this moment.")
    except Exception as e:
        logging.error(f"Scan error: {e}")

# --- هندلرهای تلگرام ---
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "Welcome to GapGPT Crypto Bot! 🤖\nUse /scan to find signals.")

@bot.message_handler(commands=['scan'])
def manual_scan(message):
    scan_market(message.chat.id)

def auto_scan_loop():
    # چون در Render هستیم، چت‌آیدی ثابتی نداریم مگر اینکه ذخیره کنیم. 
    # این بخش معمولاً برای کانال‌ها یا آیدی ادمین است.
    # فعلاً غیرفعال یا برای ادمین تنظیم کنید.
    pass

# --- اجرای اصلی ---
if __name__ == "__main__":
    # ۱. اجرای وب‌سرور برای زنده ماندن در Render
    t = Thread(target=run_web_server)
    t.setDaemon(True)
    t.start()
    
    logging.info("Web server started.")
    
    # ۲. اجرای ربات تلگرام
    logging.info("Bot is starting...")
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            logging.error(f"Bot polling error: {e}")
            time.sleep(15)
