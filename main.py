import requests
import statistics
import jdatetime
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- تنظیمات اصلی ---
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
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("data"):
            return list(reversed(data["data"]))
    except:
        return None
    return None

def calculate_atr(candles, period=14):
    trs = []
    for i in range(1, len(candles)):
        high, low, prev_close = float(candles[i][2]), float(candles[i][3]), float(candles[i-1][4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return statistics.mean(trs[-period:])

def get_tehran_time():
    now = datetime.now(TEHRAN_TZ)
    jalali = jdatetime.datetime.fromgregorian(datetime=now)
    return jalali.strftime("%H:%M | %Y-%m-%d")

def analyze_signal(symbol, candles):
    close = float(candles[-1][4])
    prev_close = float(candles[-2][4])
    volume = float(candles[-1][5])
    avg_volume = statistics.mean([float(c[5]) for c in candles[-20:]])
    
    atr = calculate_atr(candles)
    direction = "LONG" if close > prev_close else "SHORT"
    
    whale_act = "تأیید شد ✅" if volume > avg_volume * 1.5 else "عادی"
    
    if direction == "LONG":
        entry = close
        tp1, tp2, tp3, tp4 = entry + atr, entry + atr*1.5, entry + atr*2.2, entry + atr*3
        sl = entry - atr * 1.2
    else:
        entry = close
        tp1, tp2, tp3, tp4 = entry - atr, entry - atr*1.5, entry - atr*2.2, entry - atr*3
        sl = entry + atr * 1.2

    rr = abs(tp2 - entry) / abs(entry - sl)
    score = min(int(rr * 35), 100)
    confidence = min(int(rr * 30), 98)

    if score < 65: return None
    
    if sent_signals.get(symbol) == direction: return None
    sent_signals[symbol] = direction

    time_str = get_tehran_time()
    dir_fa = "لانگ / LONG" if direction == "LONG" else "شورت / SHORT"
    
    template = f"""
📊 نماد: {symbol.replace("-USDT", "")}
🕒 زمان سیگنال: {time_str}
⏱ تایم‌فریم: 15m

🟢 قدرت سیگنال: قوی | ✅ ورود مناسب
🐳 فعالیت نهنگ‌ها: ورود نقدینگی {whale_act}

📌 نوع معامله: {dir_fa}
💵 قیمت حدودی ورود: {entry:,.4f}$

🎯 تارگت اول: {tp1:,.4f}$
🎯 تارگت دوم: {tp2:,.4f}$
🎯 تارگت سوم: {tp3:,.4f}$
🎯 تارگت چهارم: {tp4:,.4f}$

🛑 حد ضرر معقول: {sl:,.4f}$

✅ %درستی تقریبی پیش‌بینی: {confidence}
⭐ امتیاز سیگنال: {score}/100
"""
    return template

async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    for symbol in SYMBOLS:
        candles = get_candles(symbol)
        if not candles: continue
        signal = analyze_signal(symbol, candles)
        if signal:
            await context.bot.send_message(chat_id=CHAT_ID, text=signal)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 ربات اسکنر حرفه‌ای فعال شد!")

async def force_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 در حال اسکن... لطفاً صبر کنید.")
    for symbol in SYMBOLS:
        candles = get_candles(symbol)
        if not candles: continue
        signal = analyze_signal(symbol, candles)
        if signal: await update.message.reply_text(signal)

# --- اصلاح بخش اصلی برای رفع خطای Event Loop ---
def main():
    # ساخت اپلیکیشن
    app = Application.builder().token(TOKEN).build()
    
    # افزودن دستورات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", force_scan))
    
    # تنظیم زمان‌بندی
    job_queue = app.job_queue
    job_queue.run_repeating(scan_market, interval=900, first=10)
    
    print("Bot is starting...")
    
    # اجرای ربات (این متد در نسخه‌های جدید پایدارتر است)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
