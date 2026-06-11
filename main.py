import os
import time
import math
import logging
import threading
from datetime import datetime

import requests
import pandas as pd
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# =========================
# Config
# =========================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

BYBIT_BASE_URL = "https://api.bybit.com"
BYBIT_CATEGORY = "spot"
TIMEFRAME_LABEL = "1h"
BYBIT_INTERVAL = "60"
QUOTE_COIN = "USDT"

TOP_N_SYMBOLS = 20
MIN_USD_TURNOVER = 500000  # برای حذف جفت‌های خیلی ضعیف
KLINE_LIMIT = 200
REQUEST_TIMEOUT = 20

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is missing from environment variables")

# =========================
# Logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# =========================
# Flask app for Render
# =========================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is running."

@flask_app.route("/health")
def health():
    return {"status": "ok", "data_source": "Bybit Public API", "timeframe": TIMEFRAME_LABEL}

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)

# =========================
# HTTP session
# =========================
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Connection": "keep-alive",
})

# =========================
# Helpers
# =========================
def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def format_price(price: float) -> str:
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 1:
        return f"{price:,.4f}"
    if price >= 0.01:
        return f"{price:,.6f}"
    return f"{price:,.8f}"

# =========================
# Bybit API
# =========================
def fetch_bybit_tickers():
    """
    دریافت لیست tickerهای spot از Bybit
    """
    url = f"{BYBIT_BASE_URL}/v5/market/tickers"
    params = {
        "category": BYBIT_CATEGORY
    }

    try:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        logger.info(f"[Bybit Tickers] HTTP status: {response.status_code}")
        preview = response.text[:500] if response.text else ""
        logger.info(f"[Bybit Tickers] Response preview: {preview}")

        if response.status_code != 200:
            logger.error(f"[Bybit Tickers] Non-200 response: {response.status_code}")
            return []

        data = response.json()
        ret_code = data.get("retCode")
        ret_msg = data.get("retMsg")
        logger.info(f"[Bybit Tickers] retCode={ret_code}, retMsg={ret_msg}")

        if ret_code != 0:
            logger.error(f"[Bybit Tickers] API error: {ret_msg}")
            return []

        result = data.get("result", {})
        ticker_list = result.get("list", [])
        if not ticker_list:
            logger.warning("[Bybit Tickers] Empty ticker list")
            return []

        return ticker_list

    except Exception as e:
        logger.exception(f"[Bybit Tickers] Exception: {e}")
        return []

def get_top_symbols():
    """
    انتخاب نمادهای برتر بازار از بین جفت‌های USDT و spot
    بر اساس turnover24h
    """
    tickers = fetch_bybit_tickers()
    if not tickers:
        return []

    filtered = []
    for item in tickers:
        symbol = item.get("symbol", "")
        if not symbol.endswith(QUOTE_COIN):
            continue

        turnover_24h = safe_float(item.get("turnover24h", 0))
        volume_24h = safe_float(item.get("volume24h", 0))
        last_price = safe_float(item.get("lastPrice", 0))

        if turnover_24h < MIN_USD_TURNOVER:
            continue
        if volume_24h <= 0 or last_price <= 0:
            continue

        filtered.append({
            "symbol": symbol,
            "turnover24h": turnover_24h,
            "volume24h": volume_24h,
            "lastPrice": last_price
        })

    filtered.sort(key=lambda x: x["turnover24h"], reverse=True)
    top_symbols = [x["symbol"] for x in filtered[:TOP_N_SYMBOLS]]

    logger.info(f"[Symbols] Selected top symbols: {top_symbols}")
    return top_symbols

def fetch_bybit_klines(symbol: str, interval: str = BYBIT_INTERVAL, limit: int = KLINE_LIMIT):
    """
    دریافت کندل‌ها از Bybit
    """
    url = f"{BYBIT_BASE_URL}/v5/market/kline"
    params = {
        "category": BYBIT_CATEGORY,
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    try:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        logger.info(f"[Bybit Klines] symbol={symbol} HTTP status: {response.status_code}")
        preview = response.text[:500] if response.text else ""
        logger.info(f"[Bybit Klines] symbol={symbol} Response preview: {preview}")

        if response.status_code != 200:
            logger.error(f"[Bybit Klines] symbol={symbol} Non-200 response: {response.status_code}")
            return None

        data = response.json()
        ret_code = data.get("retCode")
        ret_msg = data.get("retMsg")
        logger.info(f"[Bybit Klines] symbol={symbol} retCode={ret_code}, retMsg={ret_msg}")

        if ret_code != 0:
            logger.error(f"[Bybit Klines] symbol={symbol} API error: {ret_msg}")
            return None

        result = data.get("result", {})
        rows = result.get("list", [])
        if not rows:
            logger.warning(f"[Bybit Klines] symbol={symbol} Empty kline list")
            return None

        # فرمت Bybit:
        # [startTime, openPrice, highPrice, lowPrice, closePrice, volume, turnover]
        df = pd.DataFrame(rows, columns=[
            "start_time", "open", "high", "low", "close", "volume", "turnover"
        ])

        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["start_time"] = pd.to_numeric(df["start_time"], errors="coerce")
        df["datetime"] = pd.to_datetime(df["start_time"], unit="ms", errors="coerce")

        # Bybit معمولاً نزولی برمی‌گرداند، برای تحلیل باید صعودی شود
        df = df.sort_values("start_time").reset_index(drop=True)

        if df["close"].isna().all():
            logger.warning(f"[Bybit Klines] symbol={symbol} all close values are NaN")
            return None

        return df

    except Exception as e:
        logger.exception(f"[Bybit Klines] symbol={symbol} Exception: {e}")
        return None

# =========================
# Indicators
# =========================
def calculate_rsi(series: pd.Series, period: int = 14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss.replace(0, math.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def calculate_ema(series: pd.Series, period: int):
    return series.ewm(span=period, adjust=False).mean()

def calculate_macd(series: pd.Series):
    ema12 = calculate_ema(series, 12)
    ema26 = calculate_ema(series, 26)
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist

def calculate_atr(df: pd.DataFrame, period: int = 14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return atr

# =========================
# Analysis
# =========================
def analyze_symbol(symbol: str):
    df = fetch_bybit_klines(symbol)
    if df is None or len(df) < 60:
        logger.warning(f"[Analyze] symbol={symbol} insufficient data")
        return None

    try:
        df["rsi"] = calculate_rsi(df["close"], 14)
        df["ema_20"] = calculate_ema(df["close"], 20)
        df["ema_50"] = calculate_ema(df["close"], 50)
        df["macd"], df["macd_signal"], df["macd_hist"] = calculate_macd(df["close"])
        df["atr"] = calculate_atr(df, 14)

        last = df.iloc[-1]
        prev = df.iloc[-2]

        close = safe_float(last["close"])
        rsi = safe_float(last["rsi"], 50)
        ema20 = safe_float(last["ema_20"])
        ema50 = safe_float(last["ema_50"])
        macd = safe_float(last["macd"])
        macd_signal = safe_float(last["macd_signal"])
        atr = safe_float(last["atr"])

        score = 0
        reasons = []

        # روند
        if close > ema20:
            score += 1
            reasons.append("قیمت بالای EMA20")
        else:
            score -= 1
            reasons.append("قیمت زیر EMA20")

        if ema20 > ema50:
            score += 1
            reasons.append("EMA20 بالای EMA50")
        else:
            score -= 1
            reasons.append("EMA20 زیر EMA50")

        # RSI
        if 45 <= rsi <= 65:
            score += 1
            reasons.append("RSI متعادل و سالم")
        elif rsi < 30:
            score += 1
            reasons.append("RSI در ناحیه اشباع فروش")
        elif rsi > 75:
            score -= 1
            reasons.append("RSI در ناحیه اشباع خرید")
        else:
            reasons.append("RSI خنثی")

        # MACD
        if macd > macd_signal:
            score += 1
            reasons.append("MACD بالای Signal")
        else:
            score -= 1
            reasons.append("MACD زیر Signal")

        # مومنتوم کوتاه‌مدت
        if safe_float(last["close"]) > safe_float(prev["close"]):
            score += 1
            reasons.append("کلوز آخر بالاتر از کلوز قبلی")
        else:
            score -= 1
            reasons.append("کلوز آخر پایین‌تر از کلوز قبلی")

        if score >= 3:
            signal_type = "🟢 BUY"
        elif score <= -2:
            signal_type = "🔴 SELL"
        else:
            signal_type = "🟡 HOLD"

        atr_pct = (atr / close * 100) if close > 0 and atr > 0 else 0

        return {
            "symbol": symbol,
            "signal": signal_type,
            "score": score,
            "price": close,
            "rsi": rsi,
            "ema20": ema20,
            "ema50": ema50,
            "macd": macd,
            "macd_signal": macd_signal,
            "atr": atr,
            "atr_pct": atr_pct,
            "reasons": reasons,
            "time": str(last["datetime"]) if pd.notna(last["datetime"]) else "N/A"
        }

    except Exception as e:
        logger.exception(f"[Analyze] symbol={symbol} Exception: {e}")
        return None

def format_analysis(result: dict) -> str:
    return (
        f"📊 {result['symbol']}\n"
        f"سیگنال: {result['signal']}\n"
        f"امتیاز: {result['score']}\n"
        f"قیمت: {format_price(result['price'])}\n"
        f"RSI: {result['rsi']:.2f}\n"
        f"EMA20: {format_price(result['ema20'])}\n"
        f"EMA50: {format_price(result['ema50'])}\n"
        f"MACD: {result['macd']:.6f}\n"
        f"Signal Line: {result['macd_signal']:.6f}\n"
        f"ATR: {result['atr']:.6f}\n"
        f"ATR%: {result['atr_pct']:.2f}%\n"
        f"تایم: {result['time']}\n"
        f"دلایل:\n- " + "\n- ".join(result["reasons"])
    )

# =========================
# Telegram Commands
# =========================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 ربات تحلیل کریپتو فعال است.\n\n"
        "دستورات:\n"
        "/status - وضعیت ربات\n"
        "/scan - اسکن ارزهای برتر Bybit\n"
        "/signal BTCUSDT - تحلیل یک نماد\n"
    )
    await update.message.reply_text(msg)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "✅ Bot Status\n"
        f"وضعیت: روشن\n"
        f"منبع دیتا: Bybit Public API\n"
        f"تایم‌فریم: {TIMEFRAME_LABEL}\n"
        f"Interval Bybit: {BYBIT_INTERVAL}\n"
        f"Quote: {QUOTE_COIN}\n"
        f"Port: {PORT}"
    )
    await update.message.reply_text(msg)

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("مثال:\n/signal BTCUSDT")
            return

        symbol = context.args[0].upper().strip()
        if not symbol.endswith(QUOTE_COIN):
            await update.message.reply_text(f"فقط نمادهای {QUOTE_COIN} پشتیبانی می‌شوند. مثال:\n/signal BTCUSDT")
            return

        await update.message.reply_text(f"⏳ در حال تحلیل {symbol} ...")

        result = analyze_symbol(symbol)
        if not result:
            await update.message.reply_text(
                f"❌ برای {symbol} داده‌ای دریافت نشد یا تحلیل ممکن نبود.\n"
                f"لاگ Render را بررسی کن."
            )
            return

        await update.message.reply_text(format_analysis(result))

    except Exception as e:
        logger.exception(f"[Command /signal] Exception: {e}")
        await update.message.reply_text(f"❌ خطا در تحلیل: {e}")

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("🔍 در حال اسکن ارزهای برتر بازار با دیتای Bybit...")

        symbols = get_top_symbols()
        if not symbols:
            await update.message.reply_text(
                "❌ لیست نمادها از Bybit دریافت نشد.\n"
                "لاگ Render را بررسی کن."
            )
            return

        results = []
        failed = []

        for symbol in symbols:
            try:
                result = analyze_symbol(symbol)
                if result:
                    results.append(result)
                else:
                    failed.append(symbol)
                time.sleep(0.2)
            except Exception as e:
                logger.exception(f"[Scan] symbol={symbol} Exception: {e}")
                failed.append(symbol)

        if not results:
            await update.message.reply_text(
                "❌ داده‌ای دریافت نشد. لاگ Render را بررسی کن."
            )
            return

        # مرتب‌سازی بر اساس score و سپس ATR%
        results.sort(key=lambda x: (x["score"], x["atr_pct"]), reverse=True)

        top_results = results[:10]

        chunks = []
        header = f"📈 نتیجه اسکن {len(results)} نماد از Bybit\n\n"
        current = header

        for r in top_results:
            line = (
                f"{r['signal']} | {r['symbol']} | "
                f"Score: {r['score']} | "
                f"Price: {format_price(r['price'])} | "
                f"RSI: {r['rsi']:.1f}\n"
            )
            if len(current) + len(line) > 3500:
                chunks.append(current)
                current = line
            else:
                current += line

        if current:
            chunks.append(current)

        for chunk in chunks:
            await update.message.reply_text(chunk)

        if failed:
            failed_preview = ", ".join(failed[:10])
            await update.message.reply_text(
                f"⚠️ بعضی نمادها تحلیل نشدند: {failed_preview}"
                + (" ..." if len(failed) > 10 else "")
            )

    except Exception as e:
        logger.exception(f"[Command /scan] Exception: {e}")
        await update.message.reply_text(f"❌ خطا در اسکن: {e}")

# =========================
# Main
# =========================
def main():
    threading.Thread(target=run_flask, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("scan", scan_command))

    logger.info("Bot started successfully with Bybit Public API.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
