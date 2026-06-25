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
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)

# جلوگیری از اجرای چندباره ترد ربات
bot_thread_started = False


# --- مسیر تست Render ---
@app.route('/')
def home():
    return "Bot is Running...", 200


@app.route('/health')
def health():
    return "OK", 200


# --- توابع دریافت داده و تحلیل ---
def get_klines(symbol):
    url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=1H&limit=200"

    try:
        r = requests.get(url, timeout=10)
        data = r.json().get("data", [])

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df = df.iloc[::-1]  # از قدیم به جدید

        # OKX columns:
        # 0=time, 1=open, 2=high, 3=low, 4=close, 5=volume...
        df["close"] = df[4].astype(float)

        return df

    except Exception as e:
        print(f"Error fetching klines for {symbol}: {e}")
        return pd.DataFrame()


def get_live_price(symbol):
    """
    گرفتن قیمت آنلاین از OKX
    مثال:
    BTC -> BTC-USDT
    ETH-USDT -> ETH-USDT
    """
    symbol = symbol.upper().replace("/", "-")

    if not symbol.endswith("-USDT"):
        symbol = symbol + "-USDT"

    url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}"

    try:
        r = requests.get(url, timeout=10)
        data = r.json().get("data", [])

        if not data:
            return None, symbol

        price = float(data[0]["last"])
        return price, symbol

    except Exception as e:
        print(f"Error getting live price for {symbol}: {e}")
        return None, symbol


def ema(series, period):
    return series.ewm(span=period).mean()


def rsi(series, period=14):
    delta = series.diff()

    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()

    rs = gain / loss
    return 100 - (100 / (1 + rs))


def analyze(symbol):
    df = get_klines(symbol)

    if df.empty or len(df) < 50:
        return None

    df["ema20"] = ema(df["close"], 20)
    df["ema50"] = ema(df["close"], 50)
    df["rsi"] = rsi(df["close"])

    last = df.iloc[-1]

    if pd.isna(last["rsi"]):
        return None

    if last["ema20"] > last["ema50"] and last["rsi"] < 45:
        p = float(last["close"])
        score = int(95 - (float(last["rsi"]) / 2))

        if score > 99:
            score = 99

        return {
            "symbol": symbol,
            "price": p,
            "entry_low": round(p * 0.999, 4),
            "entry_high": round(p * 1.001, 4),
            "tp1": round(p * 1.012, 4),
            "tp2": round(p * 1.025, 4),
            "tp3": round(p * 1.04, 4),
            "tp4": round(p * 1.06, 4),
            "sl": round(p * 0.975, 4),
            "score": score
        }

    return None


def build_message(sig):
    now = datetime.utcnow().strftime("%H:%M | %d-%m-%Y")
    sym = sig["symbol"].replace("-USDT", "")

    return f"""
📊 نماد : #{sym}
🕘 زمان سیگنال : {now}
⏱ تایم‌فریم : 1H

🟢 قدرت سیگنال : قوی ✅

📌 نوع معامله : BUY / LONG
💵 محدوده ورود : {sig['entry_low']} - {sig['entry_high']}

🎯 تارگت اول : {sig['tp1']}
🎯 تارگت دوم : {sig['tp2']}
🎯 تارگت سوم : {sig['tp3']}
🎯 تارگت چهارم : {sig['tp4']}

🛑 حد ضرر : {sig['sl']}

⭐ امتیاز تحلیل : {sig['score']}/100
"""


# فعلاً برای تست کم گذاشتم. بعد که جواب داد، لیست کاملت را جایگزین کن.
COINS = [
    "BTC-USDT",
    "ETH-USDT",
    "SOL-USDT",
    "XRP-USDT",
    "DOGE-USDT",
    "ADA-USDT",
    "AVAX-USDT",
    "DOT-USDT",
    "MATIC-USDT",
    "LINK-USDT"
]


# --- دستورات تلگرام ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 اسکنر آنلاین شد و در حال تحلیل بازار است...\n\n"
        "برای گرفتن قیمت آنلاین بزن:\n"
        "/price BTC\n"
        "/price ETH\n"
        "/price SOL"
    )


async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "لطفاً نماد ارز را وارد کن.\n\n"
            "مثال:\n"
            "/price BTC\n"
            "/price ETH\n"
            "/price SOL"
        )
        return

    coin = context.args[0]

    # مهم: درخواست اینترنتی در ترد جدا اجرا شود تا ربات هنگ نکند
    price, symbol = await asyncio.to_thread(get_live_price, coin)

    if price is None:
        await update.message.reply_text(f"❌ قیمت برای {symbol} پیدا نشد.")
        return

    await update.message.reply_text(
        f"💰 قیمت آنلاین {symbol}\n\n"
        f"قیمت فعلی: {price} USDT"
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ ربات روشن است.\n"
        "✅ اتصال تلگرام فعال است.\n"
        "✅ اسکنر در پس‌زمینه اجرا می‌شود."
    )


# --- حلقه اسکن ---
async def scanner_task(bot: Bot):
    print("Scanner loop started...")

    while True:
        for coin in COINS:
            try:
                # خیلی مهم:
                # analyze شامل requests است، پس باید داخل to_thread اجرا شود
                # تا Event Loop تلگرام قفل نشود.
                sig = await asyncio.to_thread(analyze, coin)

                if sig and sig["score"] >= 75:
                    if CHAT_ID:
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=build_message(sig)
                        )
                        await asyncio.sleep(2)
                    else:
                        print("WARNING: CHAT_ID is missing. Signal not sent.")

            except Exception as e:
                print(f"Error in scan for {coin}: {e}")

            # فشار کمتر به OKX و آزاد ماندن ربات
            await asyncio.sleep(0.3)

        print("Scan cycle finished. Sleeping 15m...")
        await asyncio.sleep(900)


# --- اجرای ربات تلگرام ---
async def run_telegram_bot():
    if not TOKEN:
        print("ERROR: BOT_TOKEN is missing!")
        return

    if not CHAT_ID:
        print("WARNING: CHAT_ID is missing. Auto signals will not be sent.")

    print("Building Telegram application...")

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("price", price_cmd))
    application.add_handler(CommandHandler("status", status_cmd))

    await application.initialize()

    # خیلی مهم برای polling:
    # اگر قبلاً webhook ست شده باشد، polling جواب نمی‌دهد.
    await application.bot.delete_webhook(drop_pending_updates=True)

    await application.start()

    # اجرای اسکنر در پس‌زمینه
    asyncio.create_task(scanner_task(application.bot))

    print("Telegram bot polling started...")

    await application.updater.start_polling()

    # زنده نگه داشتن loop
    await asyncio.Event().wait()


def run_bot_in_thread():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_telegram_bot())
    except Exception as e:
        print(f"Fatal error in Telegram bot thread: {e}")


def start_bot_once():
    global bot_thread_started

    if bot_thread_started:
        return

    bot_thread_started = True

    print("Starting Telegram bot thread...")
    t = threading.Thread(target=run_bot_in_thread, daemon=True)
    t.start()


# --- ترفند اصلی برای Render/Gunicorn ---
# وقتی gunicorn main:app می‌زند، if __name__ اجرا نمی‌شود.
# پس باید اینجا ترد ربات را روشن کنیم.
start_bot_once()


if __name__ == "__main__":
    print(f"Starting Flask on port {PORT}...")
    app.run(host="0.0.0.0", port=PORT)
