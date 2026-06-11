import os
import requests
from flask import Flask
import threading
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Live!"

# محاسبه RSI بدون پانداز
def calculate_rsi_simple(prices, period=14):
    if len(prices) < period + 1:
        return 50
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

async def get_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = "BTCUSDT"
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=50"
        data = requests.get(url).json()
        
        # استخراج قیمت‌های بسته شدن
        closes = [float(x[4]) for x in data]
        current_price = closes[-1]
        rsi = calculate_rsi_simple(closes)
        
        msg = f"📊 وضعیت {symbol}:\n💰 قیمت: {current_price}\n📉 RSI: {rsi:.2f}\n\n"
        if rsi < 35: msg += "✅ سیگنال خرید"
        elif rsi > 65: msg += "❌ سیگنال فروش"
        else: msg += "😐 وضعیت خنثی"
        
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"خطا در تحلیل")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ربات فعال شد! از /signal استفاده کنید.")

if __name__ == '__main__':
    TOKEN = os.environ.get("BOT_TOKEN")
    PORT = int(os.environ.get("PORT", 10000))
    
    # اجرای Flask در ترد جداگانه
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=PORT)).start()
    
    # اجرای ربات تلگرام
    app_bot = ApplicationBuilder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("signal", get_signal))
    app_bot.run_polling()
