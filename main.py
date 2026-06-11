import os
import logging
import requests
import pandas as pd
import pandas_ta as ta
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# تنظیمات لاگ برای عیب‌یابی
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- بخش وب‌سرور برای رندر ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- بخش تحلیل تکنیکال ---
def get_crypto_data(symbol="bitcoin"):
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{symbol}/market_chart"
        params = {'vs_currency': 'usd', 'days': '30', 'interval': 'daily'}
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        prices = [x[1] for x in data['prices']]
        df = pd.DataFrame(prices, columns=['close'])
        
        # محاسبه RSI و EMA
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['ema'] = ta.ema(df['close'], length=20)
        
        last_price = df['close'].iloc[-1]
        last_rsi = df['rsi'].iloc[-1]
        last_ema = df['ema'].iloc[-1]
        
        return last_price, last_rsi, last_ema
    except Exception as e:
        logging.error(f"Error fetching data: {e}")
        return None, None, None

# --- دستورات ربات تلگرام ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! من ربات تحلیل‌گر شما هستم. برای دریافت سیگنال از دستور /signal استفاده کنید.")

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price, rsi, ema = get_crypto_data("bitcoin")
    
    if price is None:
        await update.message.reply_text("خطا در دریافت اطلاعات از بازار. لطفاً کمی بعد امتحان کنید.")
        return

    msg = f"📊 تحلیل بیت‌کوین (BTC):\n\n"
    msg += f"💰 قیمت فعلی: ${price:,.2f}\n"
    msg += f"📉 RSI (14): {rsi:.2f}\n"
    msg += f"📈 EMA (20): ${ema:,.2f}\n\n"

    if rsi < 30:
        msg += "🟢 سیگنال: اشباع فروش (احتمال صعود)"
    elif rsi > 70:
        msg += "🔴 سیگنال: اشباع خرید (احتمال اصلاح)"
    else:
        msg += "⚪ وضعیت: خنثی"

    await update.message.reply_text(msg)

# --- اجرای اصلی ---
if __name__ == '__main__':
    # ۱. اجرای وب‌سرور در یک ترد جداگانه
    Thread(target=run_web_server).start()
    
    # ۲. تنظیم و اجرای ربات تلگرام
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        logging.error("No BOT_TOKEN found in environment variables!")
    else:
        application = ApplicationBuilder().token(TOKEN).build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("signal", signal))
        
        logging.info("Starting bot...")
        application.run_polling()
