import os
import threading
import requests
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# -------------------------
# Flask app for Render port
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# -------------------------
# RSI calculation
# -------------------------
def get_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# -------------------------
# Telegram handlers
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ ربات روشن شد. دستور /signal را بفرست.")

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=50"
        data = requests.get(url, timeout=15).json()

        closes = [float(x[4]) for x in data]
        price = closes[-1]
        rsi_val = get_rsi(closes)

        if rsi_val < 35:
            status = "🟢 خرید"
        elif rsi_val > 65:
            status = "🔴 فروش"
        else:
            status = "🟡 خنثی"

        msg = (
            f"💰 قیمت: {price:.2f}\n"
            f"📊 RSI: {rsi_val:.2f}\n"
            f"📌 وضعیت: {status}"
        )
        await update.message.reply_text(msg)

    except Exception as e:
        await update.message.reply_text(f"خطا در دریافت اطلاعات بازار: {e}")

# -------------------------
# Main
# -------------------------
def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN not set")

    app_bot = ApplicationBuilder().token(token).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("signal", signal))

    threading.Thread(target=run_flask, daemon=True).start()

    print("Bot is starting...")
    app_bot.run_polling()

if __name__ == "__main__":
    main()
