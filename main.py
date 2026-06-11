import telebot
import requests
import pandas as pd
import numpy as np
from flask import Flask
import threading
import os
import time

# --- تنظیمات اولیه ---
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# هدر برای جلوگیری از مسدود شدن توسط CoinGecko
HEADERS = {
    "accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# نقشه تبدیل نمادها به IDهای کوین‌گکو
COIN_MAP = {
    "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin", "SOL": "solana",
    "XRP": "ripple", "ADA": "cardano", "DOGE": "dogecoin", "TRX": "tron",
    "TON": "the-open-network", "AVAX": "avalanche-2", "DOT": "polkadot",
    "LINK": "chainlink", "MATIC": "matic-network", "POL": "polygon-ecosystem-token",
    "LTC": "litecoin", "BCH": "bitcoin-cash", "UNI": "uniswap", "NEAR": "near",
    "ARB": "arbitrum", "OP": "optimism", "PEPE": "pepe", "SHIB": "shiba-inu"
}

# --- بخش Flask برای زنده نگه داشتن در Render ---
@app.route('/')
def health_check():
    return "Bot is alive and healthy!", 200

def run_flask():
    # پورت 10000 الزامی برای Render
    app.run(host='0.0.0.0', port=10000)

# --- توابع کمکی تحلیل و دریافت داده ---

def clean_symbol(symbol):
    s = symbol.upper().replace("/", "").replace("USDT", "").strip()
    return s

def get_coingecko_data(symbol):
    """دریافت قیمت و داده‌های چارت از CoinGecko"""
    s = clean_symbol(symbol)
    coin_id = COIN_MAP.get(s)
    
    if not coin_id:
        return None, None

    try:
        # دریافت قیمت لحظه‌ای و تغییرات
        price_url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
        r_price = requests.get(price_url, headers=HEADERS, timeout=15).json()
        
        current_price = r_price[coin_id]['usd']
        change_24h = r_price[coin_id]['usd_24h_change']

        # دریافت داده‌های ۷ روز اخیر برای تحلیل
        chart_url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days=7"
        r_chart = requests.get(chart_url, headers=HEADERS, timeout=15).json()
        
        prices = [p[1] for p in r_chart['prices']]
        df = pd.DataFrame(prices, columns=['close'])
        
        return df, {"price": current_price, "change": change_24h}
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None, None

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- هندلرهای تلگرام ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "👋 به ربات تحلیلگر خوش آمدید!\n\n"
        "🔍 دستورات:\n"
        "▫️ `/price BTC` : قیمت لحظه‌ای\n"
        "▫️ `/signal BTC` : تحلیل تکنیکال سریع\n"
        "▫️ `/debug` : تست وضعیت اتصال\n\n"
        "💡 نکته: این ربات از داده‌های CoinGecko استفاده می‌کند."
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['debug'])
def debug_bot(message):
    sent = bot.reply_to(message, "⏳ در حال بررسی وضعیت شبکه...")
    df, info = get_coingecko_data("BTC")
    if info:
        bot.edit_message_text(f"✅ اتصال برقرار است.\n💰 قیمت بیت‌کوین: {info['price']:,}$", chat_id=sent.chat.id, message_id=sent.message_id)
    else:
        bot.edit_message_text("❌ خطا در اتصال به CoinGecko. احتمال Rate Limit.", chat_id=sent.chat.id, message_id=sent.message_id)

@bot.message_handler(commands=['price'])
def show_price(message):
    text_parts = message.text.split()
    symbol = clean_symbol(text_parts[1]) if len(text_parts) > 1 else "BTC"
    
    df, info = get_coingecko_data(symbol)
    if info:
        emoji = "🟢" if info['change'] >= 0 else "🔴"
        msg = (f"💰 **قیمت لحظه‌ای {symbol}**\n"
               f"━━━━━━━━━━━━━━\n"
               f"💵 قیمت: `${info['price']:,.2f}`\n"
               f"{emoji} تغییرات ۲۴ساعته: `{info['change']:.2f}%`\n"
               f"📍 منبع: CoinGecko")
        bot.reply_to(message, msg, parse_mode="Markdown")
    else:
        bot.reply_to(message, f"❌ ارز `{symbol}` یافت نشد یا در لیست پشتیبانی نیست.", parse_mode="Markdown")

@bot.message_handler(commands=['signal'])
def get_signal(message):
    text_parts = message.text.split()
    symbol = clean_symbol(text_parts[1]) if len(text_parts) > 1 else "BTC"
    
    wait_msg = bot.reply_to(message, f"🔍 در حال تحلیل فنی {symbol}...")
    
    df, info = get_data(symbol)
    
    if df is not None and len(df) > 30:
        close = df['close']
        rsi = calculate_rsi(close).iloc[-1]
        ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
        current_price = info['price']
        
        status = "Neutral ⚪"
        if rsi > 70: status = "اشباع خرید (احتمال اصلاح) 🔴"
        elif rs < 30: status = "اشباع فروش (فرصت خرید) 🟢"
        
        trend = "صعودی 📈" if current_price > ema20 else "نزولی 📉"
        
        msg = (f"📊 **تحلیل تکنیکال {symbol}**\n"
               f"━━━━━━━━━━━━━━\n"
               f"💰 قیمت: `${current_price}`\n"
               f"📈 روند (EMA20): {trend}\n"
               f"📊 شاخص RSI: `{rsi:.2f}`\n"
               f"📢 وضعیت: {status}\n"
               f"━━━━━━━━━━━━━━\n"
               f"⚠️ این یک پیشنهاد مالی نیست.")
        bot.edit_message_text(msg, chat_id=wait_msg.chat.id, message_id=wait_msg.message_id, parse_mode="Markdown")
    else:
        bot.edit_message_text("❌ خطا در دریافت داده‌های تحلیل.", chat_id=wait_msg.chat.id, message_id=wait
