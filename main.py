import os
import threading
import asyncio
import requests
import pandas as pd
from datetime import datetime
from flask import Flask
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler

# تنظیمات
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running", 200

# --- توابع تحلیل ---
def get_klines(symbol):
    url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=1H&limit=200"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()["data"]
        df = pd.DataFrame(data)
        df = df.iloc[::-1]
        df["close"] = df[1].astype(float) # ایندکس کندل OKX
        return df
    except:
        return pd.DataFrame()

def ema(series, period):
    return series.ewm(span=period).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def analyze(symbol):
    df = get_klines(symbol)
    if df.empty: return None
    df["ema20"] = ema(df["close"], 20)
    df["ema50"] = ema(df["close"], 50)
    df["rsi"] = rsi(df["close"])
    last = df.iloc[-1]
    
    # شرط سیگنال
    if last["ema20"] > last["ema50"] and last["rsi"] < 40:
        price = last["close"]
        return {
            "symbol": symbol, "price": price,
            "entry": round(price, 2),
            "tp1": round(price * 1.01, 2), "sl": round(price * 0.97, 2),
            "score": int(85) # امتیاز ثابت برای سیگنال‌های واجد شرایط
        }
    return None

# --- ربات ---
async def scanner_loop(bot):
    coins = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "ADA-USDT"] # لیست کوتاه برای تست
    while True:
        for coin in coins:
            try:
                signal = analyze(coin)
                if signal:
                    msg = f"🔥 سیگنال {signal['symbol']}\n ورود: {signal['entry']}\n تارگت: {signal['tp1']}\n حد ضرر: {signal['sl']}"
                    await bot.send_message(chat_id=CHAT_ID, text=msg)
            except:
                pass
        await asyncio.sleep(900) # 15 دقیقه

async def start(update, context):
    await update.message.reply_text("✅ ربات فعال است و در حال اسکن...")

def run_bot_in_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    
    # اجرای اسکنر در پس‌زمینه
    bot = Bot(TOKEN)
    loop.create_task(scanner_loop(bot))
    
    application.run_polling()

# --- اجرا ---
if __name__ == "__main__":
    # استارت ربات در ترد مجزا
    threading.Thread(target=run_bot_in_thread, daemon=True).start()
    # استارت وب‌سرور روی ترد اصلی
    app.run(host="0.0.0.0", port=PORT)
