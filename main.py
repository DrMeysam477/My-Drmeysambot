import os
import requests
import telebot
from flask import Flask
from threading import Thread

# =========================
# Telegram Bot Token
# =========================
TOKEN = os.environ.get("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN is not set in Render Environment Variables")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)


# =========================
# Flask Keep Alive
# =========================
@app.route("/")
def home():
    return "Bot is Running!"


def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


# =========================
# Helpers
# =========================
def safe_float(value, default=0.0):
    try:
        return float(value)
    except:
        return default


def normalize_symbol(symbol):
    symbol = symbol.upper().strip()

    # اگر کاربر اشتباهی IRT وارد کرد، برای بازار جهانی به USDT تبدیل شود
    if symbol.endswith("IRT"):
        symbol = symbol.replace("IRT", "USDT")

    # اگر فقط BTC یا ETH نوشت، خودکار USDT اضافه شود
    common_coins = ["BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "TRX", "TON", "AVAX"]
    if symbol in common_coins:
        symbol = symbol + "USDT"

    return symbol


# =========================
# Bybit Price
# =========================
def get_bybit_price(symbol):
    try:
        url = "https://api.bybit.com/v5/market/tickers"
        params = {
            "category": "spot",
            "symbol": symbol
        }

        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        response = requests.get(url, params=params, headers=headers, timeout=10)

        # اگر جواب JSON نبود، خطای کنترل‌شده برگردان
        try:
            data = response.json()
        except Exception:
            return None, "BYBIT_NOT_JSON"

        if data.get("retCode") != 0:
            return None, data.get("retMsg", "BYBIT_ERROR")

        result = data.get("result", {})
        items = result.get("list", [])

        if not items:
            return None, "SYMBOL_NOT_FOUND"

        ticker = items[0]

        price = safe_float(ticker.get("lastPrice"))
        high = safe_float(ticker.get("highPrice24h"))
        low = safe_float(ticker.get("lowPrice24h"))
        change = safe_float(ticker.get("price24hPcnt")) * 100

        return {
            "exchange": "Bybit",
            "symbol": symbol,
            "price": price,
            "high": high,
            "low": low,
            "change": change
        }, None

    except Exception as e:
        return None, str(e)


# =========================
# Binance Fallback Price
# =========================
def get_binance_price(symbol):
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        params = {
            "symbol": symbol
        }

        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        response = requests
