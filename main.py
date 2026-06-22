import requests
import statistics
from datetime import datetime
from zoneinfo import ZoneInfo
import jdatetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "YOUR_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"

TEHRAN_TZ = ZoneInfo("Asia/Tehran")

SYMBOLS = [
"BTC-USDT","ETH-USDT","SOL-USDT","BNB-USDT","XRP-USDT","DOGE-USDT",
"ADA-USDT","AVAX-USDT","DOT-USDT","MATIC-USDT","LINK-USDT","LTC-USDT",
"TRX-USDT","ATOM-USDT","NEAR-USDT","APT-USDT","OP-USDT","ARB-USDT",
"SUI-USDT","INJ-USDT","FIL-USDT","AAVE-USDT","RUNE-USDT","GRT-USDT",
"SEI-USDT","TIA-USDT","PEPE-USDT","WLD-USDT","ORDI-USDT","JUP-USDT"
]

sent_signals = {}

def calculate_atr(candles, period=14):
    trs = []

    for i in range(1, len(candles)):
        high = float(candles[i][2])
        low = float(candles[i][3])
        prev_close = float(candles[i-1][4])

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )

        trs.append(tr)

    return statistics.mean(trs[-period:])


def get_candles(symbol):

    url=f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=15m&limit=120"

    r=requests.get(url)
    data=r.json()

    if data.get("data"):
        return list(reversed(data["data"]))

    return None


def get_tehran_jalali():

    now=datetime.now(TEHRAN_TZ)

    jalali=jdatetime.datetime.fromgregorian(datetime=now)

    return jalali.strftime("%H:%M | %Y/%m/%d")


def get_btc_trend():

    candles=get_candles("BTC-USDT")

    if not candles:
        return "NEUTRAL"

    closes=[float(c[4]) for c in candles[-50:]]

    sma20=sum(closes[-20:])/20
    sma50=sum(closes)/50

    if sma20>sma50:
        return "BULL"

    if sma20<sma50:
        return "BEAR"

    return "NEUTRAL"


def generate_signal(symbol,candles,btc_trend):

    close=float(candles[-1][4])
    prev_close=float(candles[-2][4])

    atr=calculate_atr(candles)

    direction="LONG" if close>prev_close else "SHORT"

    if btc_trend=="BULL" and direction=="SHORT":
        return None

    if btc_trend=="BEAR" and direction=="LONG":
        return None

    if direction=="LONG":

        entry=close
        stop=close-atr
        tp1=close+atr
        tp2=close+atr*2

    else:

        entry=close
        stop=close+atr
        tp1=close-atr
        tp2=close-atr*2

    rr=abs(tp2-entry)/abs(entry-stop)

    score=round(min(rr*25,100))

    if score<60:
        return None

    last=sent_signals.get(symbol)

    if last==direction:
        return None

    sent_signals[symbol]=direction

    confidence=min(round(rr*20),95)

    time_str=get_tehran_jalali()

    signal=f"""
🚨 SIGNAL ALERT 🚨

Symbol: {symbol}
Direction: {direction}

Entry: {entry:.4f}
Stop: {stop:.4f}

TP1: {tp1:.4f}
TP2: {tp2:.4f}

Score: {score}/100
Confidence: {confidence}%

Risk/Reward: {rr:.2f}

Market Trend: {btc_trend}

{time_str} Tehran
"""

    return signal


async def scan_market(context: ContextTypes.DEFAULT_TYPE):

    btc_trend=get_btc_trend()

    for symbol in SYMBOLS:

        candles=get_candles(symbol)

        if not candles:
            continue

        signal=generate_signal(symbol,candles,btc_trend)

        if signal:

            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=signal
            )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text("Pro Scanner Activated ✅")


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):

    btc_trend=get_btc_trend()

    for symbol in SYMBOLS:

        candles=get_candles(symbol)

        if not candles:
            continue

        signal=generate_signal(symbol,candles,btc_trend)

        if signal:
            await update.message.reply_text(signal)


def main():

    app=Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("scan",scan))

    job_queue=app.job_queue

    job_queue.run_repeating(scan_market,interval=900,first=10)

    print("Scanner Running...")

    app.run_polling()


if __name__=="__main__":
    main()
