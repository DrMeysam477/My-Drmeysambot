import os, time, threading, requests
import pandas as pd
import numpy as np
import telebot
from flask import Flask

# تنظیمات
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID = os.getenv("ADMIN_ID", "")
PORT = int(os.getenv("PORT", "10000"))
TIMEFRAME = os.getenv("TIMEFRAME", "1h")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
app = Flask(__name__)

@app.route('/')
def home(): return {"status": "online"}

def get_data(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={TIMEFRAME}&limit=100"
        r = requests.get(url, timeout=10).json()
        df = pd.DataFrame(r, columns=['t','o','h','l','c','v','ct','qv','n','tb','tg','i'])
        df['c'] = df['c'].astype(float)
        df['v'] = df['v'].astype(float)
        return df
    except: return None

def analyze(symbol):
    df = get_data(symbol)
