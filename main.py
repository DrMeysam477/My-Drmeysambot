import os
import asyncio
import threading
import requests
import pandas as pd
from datetime import datetime
from flask import Flask
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

# --- تنظیمات اولیه ---
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

app = Flask(__name__)

# --- توابع تحلیل (بدون تغییر) ---
def get_klines(symbol):
    url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=1H&limit=200"
    try:
        r = requests.get(url, timeout=10)
        data = r.json().get("data", [])
        if not data: return pd.DataFrame()
        df = pd.DataFrame(data)
        df = df.iloc[::-1]
        df["close"] = df[4].astype(float)
        return df
    except: return pd.DataFrame()

def ema(series, period): return series.ewm(span=period).mean()
def rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    return 100 - (100 / (1 + (gain / loss)))

def analyze(symbol):
    df = get_klines(symbol)
    if df.empty or len(df) < 50: return None
    df["ema20"] = ema(df["close"], 20)
    df["ema50"] = ema(df["close"], 50)
    df["rsi"] = rsi(df["close"])
    last = df.iloc[-1]
    if last["ema20"] > last["ema50"] and last["rsi"] < 45:
        p = last["close"]
        return {
            "symbol": symbol, "price": p,
            "entry_low": round(p * 0.999, 4), "entry_high": round(p * 1.001, 4),
            "tp1": round(p * 1.012, 4), "tp2": round(p * 1.025, 4),
            "tp3": round(p * 1.04, 4), "tp4": round(p * 1.06, 4),
            "sl": round(p * 0.975, 4), "score": int(95 - (last["rsi"] / 2))
        }
    return None

def build_message(sig):
    now = datetime.utcnow().strftime("%H:%M | %d-%m-%Y")
    sym = sig['symbol'].replace('-USDT', '')
    return f"📊 نماد : #{sym}\n🕘 زمان : {now}\n🟢 قدرت : قوی ✅\n📌 ورود : {sig['entry_low']} - {sig['entry_high']}\n🎯 تارگت‌ها : {sig['tp1']}, {sig['tp2']}, {sig['tp3']}\n🛑 حد ضرر : {sig['sl']}\n⭐ امتیاز : {sig['score']}/100"

COINS = ["BTC-USDT","ETH-USDT","SOL-USDT","XRP-USDT","DOGE-USDT","ADA-USDT","AVAX-USDT","DOT-USDT","MATIC-USDT","LINK-USDT"] # برای تست تعداد را کم کردم، خودتان زیاد کنید

# --- بخش مدیریت ربات ---
async def scanner_task(bot: Bot):
    while True:
        for coin in COINS:
            try:
                sig = analyze(coin)
                if sig and sig['score'] >= 75:
                    await bot.send_message(chat_id=CHAT_ID, text=build_message(sig))
                    await asyncio.sleep(2)
            except: pass
        await asyncio.sleep(900)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 اسکنر آنلاین شد و در حال تحلیل بازار است...")

def run_bot_in_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start_cmd))
    
    loop.run_until_complete(application.initialize())
    loop.run_until_complete(application.start())
    
    # اجرای حلقه اسکن
    loop.create_task(scanner_task(application.bot))
    
    loop.run_until_complete(application.updater.start_polling())
    loop.run_forever()

# --- ترفند اصلی برای Render ---
# به محض اینکه Flask توسط Gunicorn لود شود، این ترد اجرا می‌شود
threading.Thread(target=run_bot_in_thread, daemon=True).start()

@app.route('/')
def home():
    return "Bot is Running...", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
