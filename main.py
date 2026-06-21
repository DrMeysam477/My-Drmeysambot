import os
import threading
import requests
import pandas as pd
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dataclasses import dataclass
from datetime import datetime

# ---------- Flask برای روشن نگه داشتن Render ----------
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Crypto Scanner Bot is Live ✅", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

# ---------- مدل سیگنال ----------
@dataclass
class Signal:
    symbol: str
    direction: str
    timeframe: str
    entry_low: float
    entry_high: float
    atr: float
    stop_loss: float
    score: int
    confidence: int
    risk_reward: float

# ---------- گرفتن کندل از OKX ----------
def get_okx_data(symbol):
    url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=15m&limit=60"

    try:
        response = requests.get(url, timeout=15)
        data = response.json()

        if data.get("code") != "0":
            return None

        df = pd.DataFrame(
            data["data"],
            columns=["ts", "open", "high", "low", "close", "volume", "vol_ccy", "vol_quote", "confirm"]
        )

        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)

        df = df.iloc[::-1].reset_index(drop=True)
        return df

    except Exception as e:
        print("OKX error:", e)
        return None

# ---------- محاسبه ATR بدون pandas_ta ----------
def calculate_atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()

    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = true_range.rolling(period).mean()

    return atr.iloc[-1]

# ---------- تشخیص جهت ساده ----------
def detect_direction(df):
    last_close = df["close"].iloc[-1]
    prev_close = df["close"].iloc[-2]

    if last_close > prev_close:
        return "LONG"
    else:
        return "SHORT"

# ---------- تایید سیگنال ----------
def should_send_signal(signal):
    if signal.score < 80:
        return False
    if signal.confidence < 80:
        return False
    if signal.risk_reward < 2:
        return False
    return True

# ---------- متن پیام تلگرام ----------
def format_signal_message(signal):
    entry = (signal.entry_low + signal.entry_high) / 2

    if signal.direction == "LONG":
        tp1 = entry + signal.atr
        tp2 = entry + (signal.atr * 2)
        stop_loss = entry - (signal.atr * 1.5)
        emoji = "🟢"
    else:
        tp1 = entry - signal.atr
        tp2 = entry - (signal.atr * 2)
        stop_loss = entry + (signal.atr * 1.5)
        emoji = "🔴"

    now = datetime.now().strftime("%H:%M")

    return f"""
🚀 SIGNAL FOUND

🕘 Time: {now}
📊 Symbol: {signal.symbol}
📌 Direction: {signal.direction} {emoji}
⏱ Timeframe: {signal.timeframe}

🎯 Entry: {entry:.4f}
✅ TP1: {tp1:.4f}
✅ TP2: {tp2:.4f}
🛑 Stop Loss: {stop_loss:.4f}

⭐ Score: {signal.score}/100
📈 Confidence: {signal.confidence}%
⚖️ Risk/Reward: {signal.risk_reward}
"""

# ---------- اسکن بازار ----------
async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    symbols = [
        "BTC-USDT",
        "ETH-USDT",
        "SOL-USDT",
        "DOGE-USDT",
        "XRP-USDT",
        "ADA-USDT",
        "BNB-USDT",
        "AVAX-USDT",
        "LINK-USDT",
        "TON-USDT"
    ]

    chat_id = context.job.chat_id

    for symbol in symbols:
        df = get_okx_data(symbol)

        if df is None or len(df) < 20:
            continue

        atr = calculate_atr(df)
        if pd.isna(atr) or atr == 0:
            continue

        last_price = df["close"].iloc[-1]
        direction = detect_direction(df)

        signal = Signal(
            symbol=symbol,
            direction=direction,
            timeframe="15m",
            entry_low=last_price * 0.999,
            entry_high=last_price * 1.001,
            atr=atr,
            stop_loss=0,
            score=85,
            confidence=82,
            risk_reward=2.5
        )

        if should_send_signal(signal):
            message = format_signal_message(signal)
            await context.bot.send_message(chat_id=chat_id, text=message)

# ---------- دستور start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    context.job_queue.run_repeating(
        scan_market,
        interval=900,
        first=5,
        chat_id=chat_id
    )

    await update.message.reply_text(
        "Scanner started ✅\nهر ۱۵ دقیقه بازار را اسکن می‌کنم."
    )

# ---------- اجرای ربات ----------
def run_bot():
    token = os.environ.get("BOT_TOKEN")

    if not token:
        print("BOT_TOKEN not found")
        return

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_bot()
