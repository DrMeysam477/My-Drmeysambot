import os
import telebot
import ccxt
import pandas as pd
from flask import Flask
from threading import Thread
import time

# 1. تنظیمات اولیه
API_TOKEN = '7223788755:AAH4M8Z466hWOfqN3kH3775XnS2u0fQj-bU' # توکن شما
bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

# 2. توابع تحلیلی
def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_crypto_data(symbol):
    try:
        exchange = ccxt.okx()
        bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=50)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception:
        return None

# 3. هندلرهای ربات تلگرام
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "سلام! به ربات معاملاتی خوش آمدید. ✅\nدستورات:\n/status - بررسی وضعیت\n/signal BTC-USDT-SWAP - تحلیل ارز\n/scan - اسکن بازار")

@bot.message_handler(commands=['status'])
def send_status(message):
    bot.reply_to(message, "Bot is running on Render ✅\nEverything is stable!")

@bot.message_handler(commands
