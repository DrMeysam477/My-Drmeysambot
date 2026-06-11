import os
import time
import threading
import traceback

import requests
import pandas as pd
import numpy as np
import telebot
from flask import Flask


# =========================
# تنظیمات اصلی
# =========================

BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN is not set in Render Environment Variables.")

bot = telebot.TeleBot(BOT_TOKEN or "NO_TOKEN")

REQUEST_TIMEOUT = 12

HEADERS = {
    "User-Agent": "Mozilla/5.0 CryptoBot/1.0",
    "Accept": "application/json",
}


# =========================
# Flask برای Render
# =========================

app = Flask(__name__)

@app.route("/")
def home():
    return "Crypto Telegram Bot is alive."

@app.route("/health")
def health():
    return "OK"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port)


# =========================
# ابزارهای عمومی
# =========================

def safe_get_json(url, params=None):
    """
    درخواست امن به APIها.
    خروجی:
    success, data_or_error
    """
    try:
        r = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )

        text = r.text[:500]

        if r.status_code != 200:
            return False, f"HTTP {r.status_code}: {text}"

        try:
            return True, r.json()
        except Exception:
            return False, f"Invalid JSON: {text}"

    except Exception as e:
        return False, str(e)


def normalize_symbol(raw):
    """
    BTC       -> BTCUSDT
    btc       -> BTCUSDT
    BTCUSDT   -> BTCUSDT
    BTC/USDT  -> BTCUSDT
    BTC-USDT  -> BTCUSDT
    """
    s = str(raw).upper().strip()
    s = s.replace("/", "").replace("-", "").replace("_", "").replace(" ", "")

    if not s:
        return ""

    if s.endswith("USDT"):
        return s

    if s.endswith("USD"):
        return s + "T"

    return s + "USDT"


def base_from_symbol(symbol):
    symbol = normalize_symbol(symbol)
    if symbol.endswith("USDT"):
        return symbol[:-4]
    return symbol


def okx_spot_symbol(symbol):
    base = base_from_symbol(symbol)
    return f"{base}-USDT"


def okx_swap_symbol(symbol):
    base = base_from_symbol(symbol)
    return f"{base}-USDT-SWAP"


def kucoin_symbol(symbol):
    base = base_from_symbol(symbol)
    return f"{base}-USDT"


def df_from_ohlcv(rows, source):
    """
    ساخت DataFrame استاندارد:
    timestamp, open, high, low, close, volume
    """
    if not rows or len(rows) < 5:
        return None

    df = pd.DataFrame(rows)

    needed = ["timestamp", "open", "high", "low", "close", "volume"]
    for col in needed:
        if col not in df.columns:
            return None

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])

    if len(df) < 20:
        return None

    df = df.sort_values("timestamp").reset_index(drop=True)
    df["source"] = source

    return df


# =========================
# دریافت قیمت از منابع مختلف
# =========================

def price_binance(symbol):
    symbol = normalize_symbol(symbol)
    url = "https://api.binance.com/api/v3/ticker/price"
    ok, data = safe_get_json(url, {"symbol": symbol})

    if not ok:
        return None, f"Binance price: {data}"

    if "price" not in data:
        return None, f"Binance price: no price field: {data}"

    return float(data["price"]), None


def price_bybit_spot(symbol):
    symbol = normalize_symbol(symbol)
    url = "https://api.bybit.com/v5/market/tickers"
    ok, data = safe_get_json(url, {
        "category": "spot",
        "symbol": symbol
    })

    if not ok:
        return None, f"Bybit spot price: {data}"

    items = data.get("result", {}).get("list", [])
    if not items:
        return None, f"Bybit spot price: empty list. retMsg={data.get('retMsg')}"

    return float(items[0]["lastPrice"]), None


def price_bybit_linear(symbol):
    symbol = normalize_symbol(symbol)
    url = "https://api.bybit.com/v5/market/tickers"
    ok, data = safe_get_json(url, {
        "category": "linear",
        "symbol": symbol
    })

    if not ok:
        return None, f"Bybit linear price: {data}"

    items = data.get("result", {}).get("list", [])
    if not items:
        return None, f"Bybit linear price: empty list. retMsg={data.get('retMsg')}"

    return float(items[0]["lastPrice"]), None


def price_okx_spot(symbol):
    inst = okx_spot_symbol(symbol)
    url = "https://www.okx.com/api/v5/market/ticker"
    ok, data = safe_get_json(url, {"instId": inst})

    if not ok:
        return None, f"OKX spot price: {data}"

    items = data.get("data", [])
    if not items:
        return None, f"OKX spot price: empty data. msg={data.get('msg')}"

    return float(items[0]["last"]), None


def price_okx_swap(symbol):
    inst = okx_swap_symbol(symbol)
    url = "https://www.okx.com/api/v5/market/ticker"
    ok, data = safe_get_json(url, {"instId": inst})

    if not ok:
        return None, f"OKX swap price: {data}"

    items = data.get("data", [])
    if not items:
        return None, f"OKX swap price: empty data. msg={data.get('msg')}"

    return float(items[0]["last"]), None


def price_kucoin(symbol):
    inst = kucoin_symbol(symbol)
    url = "https://api.kucoin.com/api/v1/market/orderbook/level1"
    ok, data = safe_get_json(url, {"symbol": inst})

    if not ok:
        return None, f"KuCoin price: {data}"

    if data.get("code") != "200000":
        return None, f"KuCoin price: code={data.get('code')} data={data}"

    item = data.get("data", {})
    if not item or not item.get("price"):
        return None, "KuCoin price: empty price"

    return float(item["price"]), None


def price_coingecko(symbol):
    """
    بکاپ اضطراری برای ارزهای معروف.
    """
    base = base_from_symbol(symbol)

    ids = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
        "BNB": "binancecoin",
        "XRP": "ripple",
        "ADA": "cardano",
        "DOGE": "dogecoin",
        "TRX": "tron",
        "TON": "the-open-network",
        "AVAX": "avalanche-2",
        "DOT": "polkadot",
        "LINK": "chainlink",
        "LTC": "litecoin",
        "BCH": "bitcoin-cash",
        "UNI": "uniswap",
        "NEAR": "near",
        "APT": "aptos",
        "ARB": "arbitrum",
        "OP": "optimism",
        "INJ": "injective-protocol",
        "SUI": "sui",
        "PEPE": "pepe",
        "SHIB": "shiba-inu",
    }

    coin_id = ids.get(base)
    if not coin_id:
        return None, f"CoinGecko: symbol {base} not mapped"

    url = "https://api.coingecko.com/api/v3/simple/price"
    ok, data = safe_get_json(url, {
        "ids": coin_id,
        "vs_currencies": "usd"
    })

    if not ok:
        return None, f"CoinGecko price: {data}"

    price = data.get(coin_id, {}).get("usd")
    if price is None:
        return None, f"CoinGecko price: no usd field: {data}"

    return float(price), None


def get_price_any(symbol):
    """
    قیمت را از چند منبع امتحان می‌کند.
    """
    symbol = normalize_symbol(symbol)

    sources = [
        ("Binance Spot", price_binance),
        ("Bybit Spot", price_bybit_spot),
        ("Bybit Futures", price_bybit_linear),
        ("OKX Spot", price_okx_spot),
        ("OKX Swap", price_okx_swap),
        ("KuCoin Spot", price_kucoin),
        ("CoinGecko", price_coingecko),
    ]

    errors = []

    for name, func in sources:
        price, err = func(symbol)
        if price is not None:
            return price, name, errors

        errors.append(f"{name}: {err}")

    return None, None, errors


# =========================
# دریافت کندل از منابع مختلف
# =========================

def candles_binance(symbol, interval="15m", limit=120):
    symbol = normalize_symbol(symbol)
    url = "https://api.binance.com/api/v3/klines"
    ok, data = safe_get_json(url, {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    })

    if not ok:
        return None, f"Binance candles: {data}"

    if not isinstance(data, list) or len(data) < 20:
        return None, f"Binance candles: not enough rows. rows={len(data) if isinstance(data, list) else 'not-list'}"

    rows = []
    for x in data:
        rows.append({
            "timestamp": int(x[0]),
            "open": x[1],
            "high": x[2],
            "low": x[3],
            "close": x[4],
            "volume": x[5],
        })

    df = df_from_ohlcv(rows, "Binance Spot")
    if df is None:
        return None, "Binance candles: dataframe failed"

    return df, None


def candles_bybit(symbol, category="spot", interval="15", limit=120):
    symbol = normalize_symbol(symbol)
    url = "https://api.bybit.com/v5/market/kline"
    ok, data = safe_get_json(url, {
        "category": category,
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    })

    if not ok:
        return None, f"Bybit {category
