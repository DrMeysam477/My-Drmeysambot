import os
import math
import time
import asyncio
import logging
import threading
from datetime import datetime

import requests
import pandas as pd
from flask import Flask, jsonify
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing. Please set it in Render Environment Variables.")

# Primary data source
BYBIT_BASE_URL = "https://api.bybit.com"
BYBIT_CATEGORY = "spot"
BYBIT_INTERVAL = "60"

# Backup data source
OKX_BASE_URL = "https://www.okx.com"
OKX_BAR = "1H"

QUOTE_COIN = "USDT"
TIMEFRAME_LABEL = "1h"

KLINE_LIMIT = 200
REQUEST_TIMEOUT = 20

SCAN_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "TONUSDT",
    "BNBUSDT",
    "TRXUSDT",
    "DOTUSDT",
    "MATICUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "UNIUSDT",
    "ATOMUSDT",
    "NEARUSDT",
    "APTUSDT",
    "ARBUSDT",
]

TOP_SCAN_LIMIT = 20


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# FLASK APP FOR RENDER
# ============================================================

flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Crypto Telegram Bot is running."


@flask_app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "primary_data_source": "Bybit Public API",
        "backup_data_source": "OKX Public API",
        "timeframe": TIMEFRAME_LABEL,
        "port": PORT,
    })


def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Connection": "keep-alive",
})


# ============================================================
# UTILS
# ============================================================

def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def format_price(price: float) -> str:
    price = safe_float(price)

    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 1:
        return f"{price:,.4f}"
    if price >= 0.01:
        return f"{price:,.6f}"
    return f"{price:,.8f}"


def symbol_to_okx(symbol: str) -> str:
    """
    BTCUSDT -> BTC-USDT
    ETHUSDT -> ETH-USDT
    """
    symbol = symbol.upper().strip()

    if symbol.endswith("USDT"):
        base = symbol.replace("USDT", "")
        return f"{base}-USDT"

    return symbol


def now_text():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


# ============================================================
# DATA SOURCE: BYBIT
# ============================================================

def fetch_bybit_tickers():
    """
    دریافت tickerها از Bybit.
    اگر خطا بدهد، خروجی خالی می‌دهد
