import os
import asyncio
import threading
import requests
import pandas as pd
from datetime import datetime
from flask import Flask
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler

# --- تنظیمات ---
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)

@app.route('/')
def home(): return "Bot is Running", 200

@app.route('/health')
def health(): return "OK", 200

# --- تحلیل بازار (ساده شده) ---
def get_klines(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=1H&limit=100"
        r = requests.get(url, timeout=10)
        df = pd.DataFrame(r.json().get("data", []))
        if df.empty: return pd.DataFrame()
        df = df.iloc[::-1]
        df["close"] = df[4].astype(float)
        return df
    except: return pd.DataFrame()

def analyze(symbol):
    df = get_klines(symbol)
    if df.empty or len(df) < 50: return None
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()
    last = df.iloc[-1]
    if last["ema20"] > last["ema50"]:
        p = float(last["close"])
        return {"symbol": symbol, "price": p, "tp1": round(p*1.02, 4), "sl": round(p*0.97, 4)}
    return None

# --- دستورات تلگرام ---
async def start(update, context):
    await update.message.reply_text("🚀 اسکنر فعال شد!")

async def scanner_task(bot):
    coins = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "ADA-USDT"]
    while True:
        for coin in coins:
            sig = await asyncio.to_thread(analyze, coin)
            if sig and CHAT_ID:
                msg = f"✅ سیگنال جدید: #{sig['symbol']}\nقیمت: {sig['price']}\nتارگت: {sig['tp1']}\nاستاپ: {sig['sl']}"
                try: await bot.send_message(chat_id=CHAT_ID, text=msg)
                except: pass
            await asyncio.sleep(1)
        await asyncio.sleep(900)

# --- اجرای اصلی ---
def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # استفاده از ساختار ساده‌تر برای جلوگیری از خطای Updater
    builder = ApplicationBuilder().token(TOKEN).build()
    builder.add_handler(CommandHandler("start", start))
    
    # شروع مستقیم بدون پیچیدگی
    instance = builder
    loop.run_until_complete(instance.initialize())
    if instance.post_init:
        loop.run_until_complete(instance.post_init(instance))
    
    loop.run_until_complete(instance.bot.delete_webhook(drop_pending_updates=True))
    loop.run_until_complete(instance.updater.start_polling())
    
    # اجرای اسکنر
    asyncio.ensure_future(scanner_task(instance.bot), loop=loop)
    loop.run_forever()

# استارت در ترد جداگانه برای تداخل نداشتن با Gunicorn
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
