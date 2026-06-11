import os
import pandas as pd
import requests
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# تنظیمات وب‌سرور برای زنده نگه داشتن ربات در رندر
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

# تابع ساده برای محاسبه RSI بدون نیاز به کتابخانه خارجی
def calculate_rsi(data, window=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

async def get_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = "BTCUSDT"
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=100"
    
    try:
        response = requests.get(url).json()
        df = pd.DataFrame(response, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'close_ts', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'])
        df['close'] = df['close'].astype(float)
        
        # محاسبه شاخص‌ها به صورت دستی
        rsi = calculate_rsi(df['close']).iloc[-1]
        sma = df['close'].rolling(window=20).mean().iloc[-1]
        current_price = df['close'].iloc[-1]
        
        msg = f"📊 تحلیل {symbol}:\n"
        msg += f"💰 قیمت: {current_price}\n"
        msg += f"📉 RSI: {rsi:.2f}\n"
        msg += f"📈 SMA(20): {sma:.2f}\n\n"
        
        if rsi < 30:
            msg += "✅ سیگنال: اشباع فروش (خرید)"
        elif rsi > 70:
            msg += "❌ سیگنال: اشباع خرید (فروش)"
        else:
            msg += "😐 سیگنال: خنثی"
            
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text("خطا در دریافت اطلاعات")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! برای دریافت وضعیت بازار دستور /signal را بفرستید.")

if __name__ == '__main__':
    TOKEN = os.environ.get("BOT_TOKEN")
    # اجرای وب‌سرور در پس‌زمینه
    import threading
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port)).start()
    
    # اجرای ربات تلگرام
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("signal", get_signal))
    application.run_polling()
