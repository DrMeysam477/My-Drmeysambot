import os
import asyncio
import threading
import pandas as pd
import ccxt
from flask import Flask
from telegram import Bot
from telegram.ext import ApplicationBuilder, ContextTypes

# =========================
# تنظیمات (Render Environment)
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET = os.getenv("OKX_SECRET")
OKX_PASSWORD = os.getenv("OKX_PASSWORD")
PORT = int(os.getenv("PORT", "10000"))

# اتصال فقط برای خواندن دیتا
exchange = ccxt.okx({
    'apiKey': OKX_API_KEY,
    'secret': OKX_SECRET,
    'password': OKX_PASSWORD,
    'enableRateLimit': True,
})

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is Active ✅"

# =========================
# بخش تحلیل و سیگنال
# =========================
async def get_signals(symbol):
    try:
        # دریافت دیتای قیمت
        ohlcv = await asyncio.to_thread(exchange.fetch_ohlcv, symbol, '1h', limit=50)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # اندیکاتور ساده (EMA 20 & 50)
        df['ema20'] = df['close'].ewm(span=20).mean()
        df['ema50'] = df['close'].ewm(span=50).mean()
        last = df.iloc[-1]
        
        # منطق سیگنال‌دهی (فقط نمایش)
        if last['close'] > last['ema20'] and last['ema20'] > last['ema50']:
            return "LONG 🟢"
        elif last['close'] < last['ema20'] and last['ema20'] < last['ema50']:
            return "SHORT 🔴"
    except:
        return None
    return None

async def scan_markets(context: ContextTypes.DEFAULT_TYPE):
    print("در حال بررسی بازار...")
    # لیست ارزهای پیشنهادی برای اسکن
    target_symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'DOGE/USDT:USDT']
    
    for sym in target_symbols:
        signal = await get_signals(sym)
        if signal:
            text = f"📢 **سیگنال جدید**\n\n💰 ارز: {sym}\n🧭 جهت: {signal}\n⏰ زمان: {pd.Timestamp.now()}"
            await context.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='Markdown')
            await asyncio.sleep(1)

# =========================
# اجرای اصلی
# =========================
def run_flask():
    app.run(host="0.0.0.0", port=PORT)

def main():
    # ۱. اجرای سرور فلاسک در پس‌زمینه برای رندر
    threading.Thread(target=run_flask, daemon=True).start()

    # ۲. ساخت اپلیکیشن تلگرام (نسخه جدید)
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # ۳. تنظیم زمان‌بندی (مثلاً هر ۳۰ دقیقه یکبار اسکن کند)
    job_queue = application.job_queue
    job_queue.run_repeating(scan_markets, interval=1800, first=10)
    
    print("ربات با موفقیت استارت شد...")
    application.run_polling()

if __name__ == "__main__":
    main()
