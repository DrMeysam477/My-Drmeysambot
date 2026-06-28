import os
import asyncio
import threading
import pandas as pd
import ccxt
from flask import Flask
from telegram.ext import ApplicationBuilder, ContextTypes

# تنظیمات
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET = os.getenv("OKX_SECRET")
OKX_PASSWORD = os.getenv("OKX_PASSWORD")
PORT = int(os.getenv("PORT", "10000"))

# اتصال OKX
exchange = ccxt.okx({
    "apiKey": OKX_API_KEY,
    "secret": OKX_SECRET,
    "password": OKX_PASSWORD,
    "enableRateLimit": True,
    "options": {"defaultType": "swap"}
})

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is Alive ✅"

# تابعی که به محض روشن شدن ربات، به شما پیام می‌دهد
async def post_init(application):
    print("--- مرحله ۱: تست اتصال شروع شد ---")
    try:
        # تست گرفتن قیمت از OKX
        ticker = await asyncio.to_thread(exchange.fetch_ticker, "BTC/USDT:USDT")
        price = ticker.get("last")
        
        msg = (
            "✅ ربات با موفقیت در رندر بالا آمد!\n"
            "✅ اتصال به OKX برقرار است.\n"
            f"💰 قیمت فعلی بیت‌کوین: {price}\n"
            "------------------\n"
            "من هر ۳۰ دقیقه بازار را برای سیگنال چک می‌کنم."
        )
        await application.bot.send_message(chat_id=CHAT_ID, text=msg)
        print("--- پیام تایید به تلگرام فرستاده شد ---")
    except Exception as e:
        error_msg = f"❌ خطا در استارت ربات:\n{e}"
        print(error_msg)
        await application.bot.send_message(chat_id=CHAT_ID, text=error_msg)

# تابع اسکن بازار
async def scan_markets(context: ContextTypes.DEFAULT_TYPE):
    print("--- در حال اسکن بازار ---")
    try:
        ohlcv = await asyncio.to_thread(exchange.fetch_ohlcv, "BTC/USDT:USDT", "1h", limit=50)
        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "vol"])
        df["ema20"] = df["close"].ewm(span=20).mean()
        
        last_price = df.iloc[-1]["close"]
        ema20 = df.iloc[-1]["ema20"]
        
        if last_price > ema20:
            await context.bot.send_message(chat_id=CHAT_ID, text=f"📢 سیگنال BTC: روند صعودی (بالای EMA20)\nقیمت: {last_price}")
    except Exception as e:
        print(f"Error in scan: {e}")

def main():
    # اجرای Flask در یک Thread جداگانه که مانع اجرای تلگرام نشود
    print("Starting Flask...")
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, use_reloader=False)).start()

    # تنظیمات تلگرام
    print("Starting Telegram Bot...")
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # تنظیم زمان‌بندی (هر ۳۰ دقیقه)
    application.job_queue.run_repeating(scan_markets, interval=1800, first=10)

    # اجرای دائمی تلگرام
    application.run_polling()

if __name__ == "__main__":
    main()
