import os
import asyncio
import threading
import pandas as pd
import numpy as np
import ccxt
from flask import Flask
from telegram import Bot
from telegram.ext import ApplicationBuilder, ContextTypes

# =========================
# تنظیمات محیطی (Render)
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
# برای این ربات فقط API Key با دسترسی Read (خواندن) کافیست
OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET = os.getenv("OKX_SECRET")
OKX_PASSWORD = os.getenv("OKX_PASSWORD")
PORT = int(os.getenv("PORT", "10000"))

# اتصال به صرافی OKX (فقط برای دریافت دیتا)
exchange = ccxt.okx({
    'apiKey': OKX_API_KEY,
    'secret': OKX_SECRET,
    'password': OKX_PASSWORD,
    'enableRateLimit': True,
})

app = Flask(__name__)

@app.route('/')
def home():
    return "Signal Bot is Running! ✅"

# =========================
# تحلیل تکنیکال و امتیازدهی
# =========================
def get_indicators(df):
    # محاسبه EMA
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # محاسبه RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # محاسبه ATR برای حد ضرر/سود
    high_low = df['high'] - df['low']
    df['atr'] = high_low.rolling(14).mean()
    return df

def run_backtest(df, direction):
    """ تست استراتژی روی ۵۰ کندل اخیر برای سنجش اعتبار """
    wins = 0
    test_count = 30
    df_test = df.suffix(test_count + 10) # بررسی محدوده‌ی اخیر
    
    for i in range(len(df)-test_count, len(df)-2):
        entry = df.iloc[i]['close']
        atr = df.iloc[i]['atr']
        if direction == "LONG":
            tp = entry + (atr * 2)
            sl = entry - (atr * 1.5)
            # چک کردن ۵ کندل بعد
            for j in range(i+1, min(i+6, len(df))):
                if df.iloc[j]['high'] >= tp: wins += 1; break
                if df.iloc[j]['low'] <= sl: break
        else:
            tp = entry - (atr * 2)
            sl = entry + (atr * 1.5)
            for j in range(i+1, min(i+6, len(df))):
                if df.iloc[j]['low'] <= tp: wins += 1; break
                if df.iloc[j]['high'] >= sl: break
                
    return round((wins / test_count) * 100, 2)

async def analyze_market(symbol):
    try:
        # دریافت داده‌های ۱ ساعته
        ohlcv = await asyncio.to_thread(exchange.fetch_ohlcv, symbol, '1h', limit=100)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        df = get_indicators(df)
        last = df.iloc[-1]
        
        score = 0
        direction = None
        
        # استراتژی: تقاطع قیمت و EMA + RSI
        if last['close'] > last['ema20'] and last['rsi'] > 55:
            direction = "LONG"
            score += 50
            if last['ema20'] > last['ema50']: score += 20
        elif last['close'] < last['ema20'] and last['rsi'] < 45:
            direction = "SHORT"
            score += 50
            if last['ema20'] < last['ema50']: score += 20
            
        if direction:
            # اجرای بک‌تست برای تایید امتیاز
            win_rate = run_backtest(df, direction)
            total_score = score + (win_rate * 0.3)
            
            if total_score > 70: # فقط سیگنال‌های قوی
                return {
                    'symbol': symbol,
                    'direction': direction,
                    'price': last['close'],
                    'score': round(total_score, 1),
                    'win_rate': win_rate,
                    'tp': last['close'] + (last['atr'] * 2) if direction == "LONG" else last['close'] - (last['atr'] * 2),
                    'sl': last['close'] - (last['atr'] * 1.5) if direction == "LONG" else last['close'] + (last['atr'] * 1.5)
                }
    except:
        return None

# =========================
# اجرای دوره‌ای و ارسال پیام
# =========================
async def scan_and_report(context: ContextTypes.DEFAULT_TYPE):
    print("شروع اسکن بازار برای سیگنال دهی...")
    try:
        markets = await asyncio.to_thread(exchange.fetch_tickers)
        # انتخاب ۵۰ بازار پرحجم تتر
        symbols = [s for s in markets.keys() if s.endswith(':USDT')]
        
        for sym in symbols[:50]:
            signal = await analyze_market(sym)
            if signal:
                msg = (f"📣 **سیگنال جدید شناسایی شد**\n\n"
                       f"🪙 نماد: `{signal['symbol']}`\n"
                       f"🧭 جهت: {'🟢 LONG' if signal['direction'] == 'LONG' else '🔴 SHORT'}\n"
                       f"⭐ امتیاز کل: `{signal['score']}/100`\n"
                       f"🧪 اعتبار بک‌تست: `{signal['win_rate']}%`\n\n"
                       f"💵 قیمت فعلی: `{signal['price']}`\n"
                       f"🎯 حد سود: `{round(signal['tp'], 5)}`\n"
                       f"🛑 حد ضرر: `{round(signal['sl'], 5)}`\n\n"
                       f"⚠️ این یک پیشنهاد مالی نیست.")
                await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
                await asyncio.sleep(2) # جلوگیری از اسپم
    except Exception as e:
        print(f"Error in scan: {e}")

def main():
    # اجرای سرور سلامت برای رندر
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=PORT), daemon=True).start()
    
    # راه‌اندازی ربات تلگرام
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # تنظیم اجرای خودکار هر ۱۵ دقیقه
    job_queue = application.job_queue
    job_queue.run_repeating(scan_and_report, interval=900, first=10)
    
    print("ربات سیگنال‌ده با موفقیت فعال شد.")
    application.run_polling()

if __name__ == "__main__":
    main()
