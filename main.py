import os
import requests
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# فرمول ریاضی RSI برای جلوگیری از نصب پانداز
def get_rsi(prices, period=14):
    if len(prices) < period + 1: return 50
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ ربات با موفقیت در Render مستقر شد!\nبرای دریافت سیگنال /signal را بزنید.")

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # دریافت دیتا از بایننس
        res = requests.get("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=50").json()
        closes = [float(x[4]) for x in res]
        rsi_value = get_rsi(closes)
        price = closes[-1]
        
        msg = f"💰 قیمت بیت‌کوین: {price}\n📊 شاخص RSI: {rsi_value:.2f}\n\n"
        if rsi_value < 30: msg += "🟢 سیگنال: خرید (اشباع فروش)"
        elif rsi_value > 70: msg += "🔴 سیگنال: فروش (اشباع خرید)"
        else: msg += "🟡 وضعیت: خنثی"
        
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"خطا در دریافت اطلاعات: {str(e)}")

if __name__ == '__main__':
    TOKEN = os.environ.get("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal))
    
    print("Bot is running...")
    app.run_polling()
