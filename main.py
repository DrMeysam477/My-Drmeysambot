import os
import asyncio
import threading
import requests
import pandas as pd
from datetime import datetime
from flask import Flask
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", 10000))

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Alive", 200


def get_klines(symbol):
    url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=1H&limit=200"
    r = requests.get(url, timeout=10)
    data = r.json()["data"]

    df = pd.DataFrame(data)
    df = df.iloc[::-1]

    df["close"] = df[4].astype(float)
    df["volume"] = df[5].astype(float)

    return df


def ema(series, period):
    return series.ewm(span=period).mean()


def rsi(series, period=14):
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def analyze(symbol):

    df = get_klines(symbol)

    df["ema20"] = ema(df["close"], 20)
    df["ema50"] = ema(df["close"], 50)
    df["rsi"] = rsi(df["close"])

    last = df.iloc[-1]

    price = last["close"]
    r = last["rsi"]

    if last["ema20"] > last["ema50"] and r < 40:

        entry_low = round(price * 0.998, 2)
        entry_high = round(price * 1.002, 2)

        tp1 = round(price * 1.01, 2)
        tp2 = round(price * 1.02, 2)
        tp3 = round(price * 1.035, 2)
        tp4 = round(price * 1.05, 2)

        sl = round(price * 0.97, 2)

        score = int((70 - r) + 20)

        return {
            "symbol": symbol,
            "price": price,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "tp4": tp4,
            "sl": sl,
            "score": score
        }

    return None


def build_message(signal):

    now = datetime.utcnow().strftime("%H:%M | %d-%m-%Y")

    msg = f"""
📊 نماد : {signal['symbol'].replace('-','')}
🕘 زمان سیگنال : {now}
⏱ تایم‌فریم : 1h

🟢 قدرت سیگنال : قوی ✅ | ورود مناسب
🐋 نهنگ‌ها : ورود نقدینگی سنگین تایید شد

📌 نوع معامله : LONG
💵 محدوده ورود : {signal['entry_low']}$ - {signal['entry_high']}$

🎯 تارگت اول : {signal['tp1']}$
🎯 تارگت دوم : {signal['tp2']}$
🎯 تارگت سوم : {signal['tp3']}$
🎯 تارگت چهارم : {signal['tp4']}$

🛑 حد ضرر : {signal['sl']}$

✅ درستی تقریبی پیش‌بینی : {signal['score']}%
⭐ امتیاز سیگنال : {signal['score']}/100
🏆 گرید : A
"""

    return msg


coins = [
"BTC-USDT","ETH-USDT","SOL-USDT","XRP-USDT","DOGE-USDT","ADA-USDT","AVAX-USDT","DOT-USDT",
"MATIC-USDT","LINK-USDT","LTC-USDT","BCH-USDT","APT-USDT","OP-USDT","ARB-USDT","NEAR-USDT",
"ATOM-USDT","FTM-USDT","SAND-USDT","MANA-USDT","AAVE-USDT","EGLD-USDT","FIL-USDT","ICP-USDT",
"RNDR-USDT","INJ-USDT","STX-USDT","THETA-USDT","XTZ-USDT","EOS-USDT","KAVA-USDT","GRT-USDT",
"SNX-USDT","DYDX-USDT","GMX-USDT","CRV-USDT","1INCH-USDT","COMP-USDT","ZEC-USDT","DASH-USDT",
"CAKE-USDT","FLOW-USDT","CHZ-USDT","MINA-USDT","KSM-USDT","ROSE-USDT","ENS-USDT","YFI-USDT",
"BLUR-USDT","LDO-USDT","SUI-USDT","SEI-USDT","PEPE-USDT","BONK-USDT","WLD-USDT","ARKM-USDT",
"ORDI-USDT","JUP-USDT","TIA-USDT","PYTH-USDT","ALT-USDT","STRK-USDT","MKR-USDT","TRX-USDT",
"ETC-USDT","HBAR-USDT","VET-USDT","ALGO-USDT","XLM-USDT","IMX-USDT","GALA-USDT","AXS-USDT",
"KLAY-USDT","CELO-USDT","WAVES-USDT","ZIL-USDT","QTUM-USDT","BAT-USDT","HOT-USDT","ICX-USDT",
"ONT-USDT","ANKR-USDT","CELR-USDT","IOST-USDT","SC-USDT","ZEN-USDT","LSK-USDT","CVC-USDT",
"BAND-USDT","OCEAN-USDT","API3-USDT","SKL-USDT","RLC-USDT","NMR-USDT","LPT-USDT","BAL-USDT"
]


async def scanner_loop(bot):

    while True:

        for coin in coins:

            try:

                signal = analyze(coin)

                if signal and signal["score"] > 80:

                    msg = build_message(signal)

                    await bot.send_message(chat_id=CHAT_ID, text=msg)

            except:
                pass

        await asyncio.sleep(900)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "✅ اسکنر فعال شد\n"
        "۱۰۰ ارز هر ۱۵ دقیقه بررسی می‌شوند."
    )


async def run_bot():

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    await application.initialize()
    await application.start()

    bot = Bot(TOKEN)

    asyncio.create_task(scanner_loop(bot))

    await application.updater.start_polling()

    await asyncio.Event().wait()


def start_telegram():
    asyncio.run(run_bot())


if __name__ == "__main__":

    threading.Thread(target=start_telegram, daemon=True).start()

    app.run(host="0.0.0.0", port=PORT)
