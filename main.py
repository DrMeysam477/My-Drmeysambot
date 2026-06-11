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

        # دریافت داده‌های ۷
