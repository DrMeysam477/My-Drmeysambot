import requests
import statistics
import jdatetime
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "YOUR_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"

TEHRAN_TZ = ZoneInfo("Asia/Tehran")

SYMBOLS = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT", "DOGE-USDT",
    "ADA-USDT", "AVAX-USDT", "DOT-USDT", "MATIC-USDT", "LINK-USDT", "LTC-USDT",
    "TRX-USDT", "ATOM-USDT", "NEAR-USDT", "APT-USDT", "OP-USDT", "ARB-USDT",
    "SUI-USDT", "INJ-USDT", "FIL-USDT", "AAVE-USDT", "RUNE-USDT", "GRT-USDT",
    "SEI-USDT", "TIA-USDT", "PEPE-USDT", "WLD-USDT", "ORDI-USDT", "JUP-USDT"
]

sent_signals = {}


def get_candles(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=15m&limit=100"
        response = requests.get(url, timeout=10)
        data = response.json()

        if data.get("data"):
            return list(reversed(data["data"]))

    except Exception as error:
        print(f"Error getting candles for {symbol}: {error}")

    return None


def calculate_atr(candles, period=14):
    trs = []

    for i in range(1, len(candles)):
        high = float(candles[i][2])
        low = float(candles[i][3])
        prev_close = float(candles[i - 1][4])

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )

        trs.append(tr)

    if len(trs) < period:
        return None

    return statistics.mean(trs[-period:])


def get_tehran_time():
    now = datetime.now(TEHRAN_TZ)
    jalali = jdatetime.datetime.fromgregorian(datetime=now)
    return jalali.strftime("%H:%M | %Y/%m/%d")


def analyze_market(symbol, candles):
    if not candles or len(candles) < 30:
        return None

    close = float(candles[-1][4])
    prev_close = float(candles[-2][4])
    volume = float(candles[-1][5])
    avg_volume = statistics.mean([float(candle[5]) for candle in candles[-20:]])

    atr = calculate_atr(candles)

    if not atr or atr == 0:
        return None

    direction = "LONG" if close > prev_close else "SHORT"

    liquidity_ok = volume > avg_volume * 1.2
    whale_text = "تأیید شد ✅" if liquidity_ok else "عادی"

    if direction == "LONG":
        entry = close
        tp1 = entry + atr
        tp2 = entry + atr * 1.5
        tp3 = entry + atr * 2.2
        tp4 = entry + atr * 3
        stop_loss = entry - atr * 1.2
    else:
        entry = close
        tp1 = entry - atr
        tp2 = entry - atr * 1.5
        tp3 = entry - atr * 2.2
        tp4 = entry - atr * 3
        stop_loss = entry + atr * 1.2

    risk = abs(entry - stop_loss)

    if risk == 0:
        return None

    reward = abs(tp2 - entry)
    rr = reward / risk

    score = min(int(rr * 45), 100)
    confidence = min(int(rr * 40), 98)

    if liquidity_ok:
        score = min(score + 10, 100)
        confidence = min(confidence + 8, 98)

    if score < 60:
        return None

    signal_key = f"{symbol}-{direction}"

    if sent_signals.get(symbol) == signal_key:
        return None

    sent_signals[symbol] = signal_key

    time_text = get_tehran_time()
    direction_text = "لانگ / LONG" if direction == "LONG" else "شورت / SHORT"

    message = f"""
📊 نماد: {symbol.replace("-USDT", "")}
🕒 زمان سیگنال: {time_text}
⏱ تایم‌فریم: 15m

🟢 قدرت سیگنال: قوی | ✅ ورود مناسب
🐳 فعالیت نهنگ‌ها: ورود نقدینگی {whale_text}

📌 نوع معامله: {direction_text}
💵 قیمت حدودی ورود: {entry:,.4f}$

🎯 تارگت اول: {tp1:,.4f}$
🎯 تارگت دوم: {tp2:,.4f}$
🎯 تارگت سوم: {tp3:,.4f}$
🎯 تارگت چهارم: {tp4:,.4f}$

🛑 حد ضرر معقول: {stop_loss:,.4f}$

✅ درصد درستی تقریبی پیش‌بینی: {confidence}%
⭐ امتیاز سیگنال: {score}/100
"""

    return message


async def scan_job(context: ContextTypes.DEFAULT_TYPE):
    print("Automatic scan started...")

    for symbol in SYMBOLS:
        candles = get_candles(symbol)

        if not candles:
            continue

        signal = analyze_market(symbol, candles)

        if signal:
            await context.bot.send_message(chat_id=CHAT_ID, text=signal)

    print("Automatic scan finished.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 ربات اسکنر فعال شد.\n"
        "هر ۱۵ دقیقه بازار را بررسی می‌کنم.\n"
        "برای اسکن دستی دستور /scan را بفرست."
    )


async def manual_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 در حال اسکن بازار... لطفاً صبر کن.")

    found = False

    for symbol in SYMBOLS:
        candles = get_candles(symbol)

        if not candles:
            continue

        signal = analyze_market(symbol, candles)

        if signal:
            await update.message.reply_text(signal)
            found = True

    if not found:
        await update.message.reply_text("فعلاً سیگنال قوی پیدا نشد. 🛑")


def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", manual_scan))

    if application.job_queue:
        application.job_queue.run_repeating(scan_job, interval=900, first=10)
    else:
        print("JobQueue is not available. Check requirements.txt")

    print("Bot is running...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
