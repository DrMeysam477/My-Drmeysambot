import os
import time
import math
import requests
import pandas as pd
import numpy as np
import asyncio

from datetime import datetime, timezone
from flask import Flask
from threading import Thread

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


# ============================================================
# تنظیمات اصلی
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

NOBITEX_BASE_URL = "https://api.nobitex.ir"

TF_ENTRY = "5"
TF_MID = "240"
TF_HIGH = "D"

CANDLE_LIMIT_5M = 300
CANDLE_LIMIT_4H = 250
CANDLE_LIMIT_1D = 250

MIN_SCORE = 75
MIN_RR = 2.0

LIVE_TRADING = False


# ============================================================
# Flask (برای جلوگیری از Sleep در Render)
# ============================================================

web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "Nobitex Signal Bot is alive"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web, daemon=True)
    t.start()


# ============================================================
# ابزارهای کمکی
# ============================================================

def now_ts():
    return int(time.time())

def safe_float(x, default=0.0):
    try:
        return float(x)
    except:
        return default

def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()

def split_symbol(symbol: str):
    s = symbol.upper()

    if s.endswith("USDT"):
        return s.replace("USDT", "").lower(), "usdt"

    if s.endswith("IRT"):
        return s.replace("IRT", "").lower(), "rls"

    return s.lower(), "rls"


# ============================================================
# API نوبیتکس
# ============================================================

class NobitexClient:

    def __init__(self):
        self.base_url = NOBITEX_BASE_URL

    def get_orderbook(self, symbol):

        symbol = normalize_symbol(symbol)

        url = f"{self.base_url}/v2/orderbook/{symbol}"

        try:
            r = requests.get(url, timeout=10)
            return r.json()
        except:
            return {}

    def get_udf_history(self, symbol, resolution, limit):

        symbol = normalize_symbol(symbol)

        to_time = now_ts()

        if resolution == "5":
            seconds = limit * 5 * 60
        elif resolution == "240":
            seconds = limit * 4 * 60 * 60
        else:
            seconds = limit * 24 * 60 * 60

        from_time = to_time - seconds

        url = f"{self.base_url}/market/udf/history"

        params = {
            "symbol": symbol,
            "resolution": resolution,
            "from": from_time,
            "to": to_time
        }

        try:
            r = requests.get(url, params=params, timeout=15)
            data = r.json()

            if data.get("s") != "ok":
                return pd.DataFrame()

            df = pd.DataFrame({
                "time": data["t"],
                "open": data["o"],
                "high": data["h"],
                "low": data["l"],
                "close": data["c"],
                "volume": data["v"],
            })

            df["time"] = pd.to_datetime(df["time"], unit="s")

            for c in ["open","high","low","close","volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")

            df = df.dropna()

            return df

        except:
            return pd.DataFrame()


# ============================================================
# اندیکاتورها
# ============================================================

class Indicators:

    @staticmethod
    def ema(series, period):
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(series, period=14):

        delta = series.diff()

        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)

        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()

        rs = avg_gain / avg_loss.replace(0,np.nan)

        rsi = 100 - (100/(1+rs))

        return rsi.fillna(50)

    @staticmethod
    def add_all(df):

        if df.empty or len(df) < 50:
            return df

        df = df.copy()

        df["ema20"] = Indicators.ema(df["close"],20)
        df["ema50"] = Indicators.ema(df["close"],50)
        df["ema200"] = Indicators.ema(df["close"],200)

        df["rsi14"] = Indicators.rsi(df["close"],14)

        df["vol_ma20"] = df["volume"].rolling(20).mean()

        return df


# ============================================================
# استراتژی ساده امتیازدهی
# ============================================================

class SignalEngine:

    def __init__(self, client):
        self.client = client

    def analyze(self, symbol):

        df = self.client.get_udf_history(symbol, TF_ENTRY, CANDLE_LIMIT_5M)

        df = Indicators.add_all(df)

        if df.empty:
            return "دیتا دریافت نشد"

        last = df.iloc[-1]

        price = last["close"]
        rsi = last["rsi14"]

        score = 0

        if last["close"] > last["ema20"]:
            score += 30

        if last["ema20"] > last["ema50"]:
            score += 30

        if 45 < rsi < 70:
            score += 20

        if last["volume"] > last["vol_ma20"]:
            score += 20

        direction = "BUY" if score >= MIN_SCORE else "NO SIGNAL"

        msg = f"""
تحلیل نماد: {symbol}

قیمت: {price:,.0f}

RSI: {rsi:.2f}

Score: {score}/100

سیگنال: {direction}
"""

        return msg


# ============================================================
# ربات تلگرام
# ============================================================

client = NobitexClient()
engine = SignalEngine(client)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = """
ربات تحلیل نوبیتکس فعال شد ✅

دستورات:

/signal BTCIRT
تحلیل یک ارز

/scan BTCIRT ETHIRT DOGEIRT
اسکن چند ارز

/del
حذف پیام

/pin
پین پیام
"""

    await update.message.reply_text(text)


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if len(context.args) == 0:
        await update.message.reply_text("مثال:\n/signal BTCIRT")
        return

    symbol = normalize_symbol(context.args[0])

    await update.message.reply_text("در حال تحلیل...")

    msg = engine.analyze(symbol)

    await update.message.reply_text(msg)


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if len(context.args) == 0:
        await update.message.reply_text("مثال:\n/scan BTCIRT ETHIRT")
        return

    symbols = [normalize_symbol(x) for x in context.args]

    results = []

    for s in symbols:

        msg = engine.analyze(s)

        if "BUY" in msg:
            results.append(f"✅ {s}")

        else:
            results.append(f"⚪ {s}")

        await asyncio.sleep(1)

    await update.message.reply_text("\n".join(results))


async def del_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message.reply_to_message:
        await update.message.reply_to_message.delete()
        await update.message.delete()


async def pin_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message.reply_to_message:
        await update.message.reply_to_message.pin()
        await update.message.delete()


# ============================================================
# اجرای ربات
# ============================================================

def main():

    if not TELEGRAM_BOT_TOKEN:
        print("توکن تنظیم نشده")
        return

    keep_alive()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("del", del_msg))
    app.add_handler(CommandHandler("pin", pin_msg))

    print("Bot running...")

    app.run_polling()


if __name__ == "__main__":
    main()
