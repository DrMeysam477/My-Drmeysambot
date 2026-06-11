import os
import time
import threading
import traceback
from datetime import datetime

import requests
import pandas as pd
import numpy as np

from flask import Flask
import telebot


# ============================================================
# Environment Variables
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in environment variables.")


# ============================================================
# Bot / Flask Init
# ============================================================

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

START_TIME = time.time()


# ============================================================
# Settings
# ============================================================

BYBIT_BASE_URL = "https://api.bybit.com"
BYBIT_INTERVAL = os.getenv("BYBIT_INTERVAL", "60")  # 60 یعنی تایم‌فریم 1H در Bybit
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "150"))

# نمادهایی که /scan بررسی می‌کند
SCAN_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
    "TRXUSDT",
    "MATICUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "UNIUSDT",
    "ATOMUSDT",
    "ETCUSDT",
    "FILUSDT",
    "APTUSDT",
    "ARBUSDT",
]


# ============================================================
# Flask Routes
# ============================================================

@app.route("/")
def home():
    return "Bot is running.", 200


@app.route("/health")
def health():
    return {
        "status": "ok",
        "service": "telegram-bybit-bot",
        "time": datetime.utcnow().isoformat()
    }, 200


# ============================================================
# Utility Functions
# ============================================================

def uptime_text():
    seconds = int(time.time() - START_TIME)
    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")

    return " ".join(parts) if parts else "کمتر از ۱ دقیقه"


def normalize_symbol(symbol: str) -> str:
    """
    اگر کاربر BTC بزند، تبدیل می‌شود به BTCUSDT.
    اگر BTCUSDT بزند همان می‌ماند.
    """
    symbol = symbol.upper().strip()
    symbol = symbol.replace("/", "").replace("-", "").replace("_", "")

    if not symbol.endswith("USDT"):
        symbol = symbol + "USDT"

    return symbol


def safe_float(value, default=np.nan):
    try:
        return float(value)
    except Exception:
        return default


# ============================================================
# Bybit Data Fetcher
# ============================================================

def fetch_bybit_klines(symbol, limit=KLINE_LIMIT):
    """
    دریافت کندل‌ها از Bybit Public API.
    نیازی به API Key ندارد.
    """

    try:
        symbol = normalize_symbol(symbol)

        url = f"{BYBIT_BASE_URL}/v5/market/kline"

        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": BYBIT_INTERVAL,
            "limit": str(limit),
        }

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Connection": "keep-alive",
        }

        print(f"[Bybit] Requesting klines: symbol={symbol}, interval={BYBIT_INTERVAL}, limit={limit}")

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=15
        )

        print("[Bybit] HTTP status:", response.status_code)
        print("[Bybit] Response preview:", response.text[:500])

        if response.status_code != 200:
            print(f"[Bybit] Non-200 HTTP status for {symbol}: {response.status_code}")
            return None

        data = response.json()

        ret_code = data.get("retCode")
        ret_msg = data.get("retMsg")

        if ret_code != 0:
            print(f"[Bybit] API retCode error for {symbol}: {ret_code}")
            print(f"[Bybit] API retMsg: {ret_msg}")
            return None

        rows = data.get("result", {}).get("list", [])

        if not rows:
            print(f"[Bybit] Empty kline list for {symbol}")
            return None

        df = pd.DataFrame(
            rows,
            columns=[
                "start_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "turnover",
            ],
        )

        numeric_cols = [
            "start_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
        ]

        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna()

        if df.empty:
            print(f"[Bybit] DataFrame is empty after numeric conversion: {symbol}")
            return None

        # Bybit معمولاً کندل‌ها را از جدید به قدیم می‌دهد.
        # برای محاسبه اندیکاتورها باید از قدیم به جدید مرتب شود.
        df = df.sort_values("start_time").reset_index(drop=True)

        return df

