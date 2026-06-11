import os
import time
import math
import json
import threading
import traceback
from datetime import datetime, timezone

import requests
import pandas as pd
import numpy as np
import telebot
from flask import Flask


# ============================================================
# Environment Variables
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()

PORT = int(os.getenv("PORT", "10000"))

TIMEFRAME = os.getenv("TIMEFRAME", "1h").strip()
QUOTE_ASSET = os.getenv("QUOTE_ASSET", "USDT").strip().upper()

MIN_SCORE_TO_SEND = float(os.getenv("MIN_SCORE_TO_SEND", "10"))
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "300"))

AUTO_SCAN = os.getenv("AUTO_SCAN", "True").strip().lower() in ["true", "1", "yes", "on"]

# اگر این مقدار وجود نداشته باشد، پیش‌فرض 80 است تا ربات سنگین نشود.
# اگر خواستی کل بازار USDT بایننس را اسکن کند، در Render بگذار:
# SCAN_MARKET_LIMIT=0
SCAN_MARKET_LIMIT = int(os.getenv("SCAN_MARKET_LIMIT", "80"))

# تعداد بهترین خروجی‌ها برای گزارش
SCAN_TOP_N = int(os.getenv("SCAN_TOP_N", "5"))

# جلوگیری از ارسال سیگنال تکراری برای یک نماد در این مدت
SIGNAL_COOLDOWN_SECONDS = int(os.getenv("SIGNAL_COOLDOWN_SECONDS", "1800"))

# تعداد کندل برای تحلیل
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "210"))

# Binance API keys فعلاً استفاده نمی‌شوند، چون دیتاهای عمومی کافی است.
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()


# ============================================================
# Basic Validation
# ============================================================

if not TELEGRAM_BOT_TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN is not set.")

if not ADMIN_ID:
    print("WARNING: ADMIN_ID is not set. Bot can still run, but admin notifications may fail.")

try:
    ADMIN_CHAT_ID = int(ADMIN_ID) if ADMIN_ID else None
except Exception:
    ADMIN_CHAT_ID = None
    print("WARNING: ADMIN_ID is not a valid integer.")


# ============================================================
# Flask App for Render
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return {
        "status": "ok",
        "service": "telegram-binance-scanner",
        "time": now_utc_string(),
        "auto_scan": AUTO_SCAN,
        "timeframe": TIMEFRAME,
        "quote_asset": QUOTE_ASSET,
        "min_score": MIN_SCORE_TO_SEND,
    }


@app.route("/health")
def health():
    return "OK", 200


# ============================================================
# Telegram Bot
# ============================================================

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode="HTML")


# ============================================================
# Global Runtime State
# ============================================================

BINANCE_BASE_URL = "https://api.binance.com"

runtime_state = {
    "started_at": time.time(),
    "last_scan_at": None,
    "last_scan_summary": None,
    "last_error": None,
    "auto_scan_enabled": AUTO_SCAN,
    "scan_running": False,
}

last_signal_sent = {}
symbols_cache = {
    "symbols": [],
    "updated_at": 0,
}


# ============================================================
# Utility Functions
# ============================================================

def now_utc_string():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def send_admin_message(text):
    """
    ارسال پیام به ادمین.
    اگر ADMIN_ID مشکل داشته باشد، فقط لاگ می‌گیرد و کرش نمی‌کند.
    """
    if not ADMIN_CHAT_ID:
        print("send_admin_message skipped: ADMIN_CHAT_ID is not set.")
        return False

    try:
        bot.send_message(ADMIN_CHAT_ID, text, disable_web_page_preview=True)
        return True
    except Exception as e:
        print(f"Telegram send error: {e}")
        runtime_state["last_error"] = f"Telegram send error: {e}"
        return False


def is_admin(message):
    """
    اگر ADMIN_ID تنظیم شده باشد، فقط ادمین اجازه دستورات مهم را دارد.
    """
    if not ADMIN_CHAT_ID:
        return True

    try:
        return int(message.chat.id) == int(ADMIN_CHAT_ID)
    except Exception:
        return False


def http_get_json(url, params=None, timeout=12, retries=3, sleep_between=1):
    """
    درخواست GET با retry ساده.
    """
    last_exception = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)

            if response.status_code == 200:
                return response.json()

            # Rate limit یا خطاهای موقت
            if response.status_code in [418, 429, 500, 502, 503, 504]:
                print(f"HTTP {response.status_code} on {url}. Attempt {attempt}/{retries}")
                time.sleep(sleep_between * attempt)
                continue

            print(f"HTTP error {response.status_code}: {response.text[:300]}")
            return None

        except Exception as e:
            last_exception = e
            print(f"Request error attempt {attempt}/{retries}: {e}")
            time.sleep(sleep_between * attempt)

    runtime_state["last_error"] = f"HTTP request failed: {last_exception}"
    return None


def format_price(price):
    price = safe_float(price)
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 1:
        return f"{price:,.4f}"
    if price >= 0.01:
        return f"{price:,.6f}"
    return f"{price:,.8f}"


def format_percent(value):
    value = safe_float(value)
    return f"{value:.2f}%"


# ============================================================
# Binance Data
# ============================================================

def get_exchange_symbols(force_refresh=False):
    """
    دریافت همه نمادهای فعال Spot با quoteAsset مشخص، مثلاً USDT.
    """
    cache_age = time.time() - symbols_cache["updated_at"]

    if symbols_cache["symbols"] and not force_refresh and cache_age < 3600:
        return symbols_cache["symbols"]

    url = f"{BINANCE_BASE_URL}/api/v3/exchangeInfo"
    data = http_get_json(url, timeout=15, retries=3)

    if not data or "symbols" not in data:
        print("Failed to fetch exchangeInfo.")
        return symbols_cache["symbols"] or []

    result = []

    blocked_keywords = [
        "UP", "DOWN", "BULL", "BEAR"
    ]

    for item in data.get("symbols", []):
        try:
            symbol = item.get("symbol", "")
            status = item.get("status", "")
            quote = item.get("quoteAsset", "")
            is_spot_allowed = item.get("isSpotTradingAllowed", False)

            if status != "TRADING":
                continue

            if quote != QUOTE_ASSET:
                continue

            if not is_spot_allowed:
                continue

            # حذف توکن‌های لوریج‌دار قدیمی اگر وجود داشته باشند
            base_asset = item.get("baseAsset", "")
            if any(base_asset.endswith(k) for k in blocked_keywords):
                continue

            result.append(symbol)

        except Exception:
            continue

    result = sorted(list(set(result)))

    symbols_cache["symbols"] = result
    symbols_cache["updated_at"] = time.time()

    print(f"Loaded {len(result)} active {QUOTE_ASSET} spot symbols from Binance.")
    return result


def get_24h_tickers():
    """
    دریافت تیکرهای 24 ساعته کل بازار.
    """
    url = f"{BINANCE_BASE_URL}/api/v3/ticker/24hr"
    data = http_get_json(url, timeout=15, retries=3)

    if not isinstance(data, list):
        return {}

    result = {}
    for item in data:
        symbol = item.get("symbol")
        if symbol:
            result[symbol] = item

    return result


def select_symbols_for_scan():
    """
    انتخاب نمادها برای اسکن.
    اگر SCAN_MARKET_LIMIT=0 باشد، همه نمادهای USDT فعال اسکن می‌شوند.
    اگر عدد مثبت باشد، به ترتیب حجم 24h همان تعداد اول انتخاب می‌شود.
    """
    symbols = get_exchange_symbols()
    if not symbols:
        return []

    tickers = get_24h_tickers()

    enriched = []
    for symbol in symbols:
        ticker = tickers.get(symbol, {})
        quote_volume = safe_float(ticker.get("quoteVolume", 0))
        enriched.append((symbol, quote_volume))

    enriched.sort(key=lambda x: x[1], reverse=True)

    if SCAN_MARKET_LIMIT > 0:
        enriched = enriched[:SCAN_MARKET_LIMIT]

    return [x[0] for x in enriched]


def get_klines(symbol, interval=TIMEFRAME, limit=KLINE_LIMIT):
    """
    دریافت کندل از Binance.
    """
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    data = http_get_json(url, params=params, timeout=12, retries=2)

    if not isinstance(data, list) or len(data) < 60:
        return None

    try:
        df = pd.DataFrame(data, columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "number_of_trades",
            "taker_buy_base_asset_volume",
            "taker_buy_quote_asset_volume",
            "ignore",
        ])

        numeric_cols = [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_asset_volume",
            "number_of_trades",
            "taker_buy_base_asset_volume",
            "taker_buy_quote_asset_volume",
        ]

        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df.dropna(inplace=True)

        if len(df) < 60:
            return None

        return df

    except Exception as e:
        print(f"Error parsing klines for {symbol}: {e}")
        return None


# ============================================================
# Indicators
# ============================================================

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(close, period=14):
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    return rsi.fillna(50)


def calculate_macd(close, fast=12, slow=26, signal=9):
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def calculate_atr(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    previous_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - previous_close).abs()
    tr3 = (low - previous_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1 / period, min_periods=period
