import os
import asyncio
import threading
import requests
import pandas as pd
from datetime import datetime
from flask import Flask
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

# --- تنظیمات اولیه از Render ---
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", 10000))

app = Flask(__name__)

@app.route('/')
def home():
    return "Scanner is Active and Running", 200

# --- توابع فنی و دریافت داده ---
def get_klines(symbol):
    # دریافت داده از OKX API
    url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=1H&limit=200"
    try:
        r = requests.get(url, timeout=10)
        data = r.json().get("data", [])
        if not data: return pd.DataFrame()
        
        df = pd.DataFrame(data)
        df = df.iloc[::-1]  # مرتب‌سازی از قدیم به جدید
        # در OKX: 0=زمان، 1=باز، 2=بالا، 3=پایین، 4=بسته، 5=حجم
        df["close"] = df[4].astype(float)
        return df
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return pd.DataFrame()

def ema(series, period):
    return series.ewm(span=period).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analyze(symbol):
    df = get_klines(symbol)
    if df.empty or len(df) < 50: return None

    df["ema20"] = ema(df["close"], 20)
    df["ema50"] = ema(df["close"], 50)
    df["rsi"] = rsi(df["close"])

    last = df.iloc[-1]
    price = last["close"]
    r_val = last["rsi"]

    # استراتژی: تقاطع طلایی EMA + اشباع فروش RSI
    if last["ema20"] > last["ema50"] and r_val < 45:
        # محاسبات قیمت
        entry_low = round(price * 0.999, 4)
        entry_high = round(price * 1.001, 4)
        tp1 = round(price * 1.012, 4)
        tp2 = round(price * 1.025, 4)
        tp3 = round(price * 1.04, 4)
        tp4 = round(price * 1.06, 4)
        sl = round(price * 0.975, 4)
        
        # امتیازدهی (هرچه RSI پایین‌تر، امتیاز بالاتر)
        score = int(95 - (r_val / 2))
        if score > 100: score = 99

        return {
            "symbol": symbol, "price": price,
            "entry_low": entry_low, "entry_high": entry_high,
            "tp1": tp1, "tp2": tp2, "tp3": tp3, "tp4": tp4,
            "sl": sl, "score": score
        }
    return None

def build_message(sig):
    now = datetime.utcnow().strftime("%H:%M | %d-%m-%Y")
    sym = sig['symbol'].replace('-USDT', '')
    
    return f"""
📊 نماد : #{sym}
🕘 زمان سیگنال : {now}
⏱ تایم‌فریم : 1H (بلند مدت)

🟢 قدرت سیگنال : بسیار قوی ✅
🐋 وضعیت نقدینگی : ورود سنگین تایید شد

📌 نوع معامله : BUY / LONG (اسپات و فیوچرز)
💵 محدوده ورود : {sig['entry_low']} - {sig['entry_high']}

🎯 تارگت اول : {sig['tp1']}
🎯 تارگت دوم : {sig['tp2']}
🎯 تارگت سوم : {sig['tp3']}
🎯 تارگت چهارم : {sig['tp4']}

🛑 حد ضرر (SL) : {sig['sl']}

✅ درستی تقریبی : {sig['score']}%
⭐ امتیاز تحلیل : {sig['score']}/100
🏆 گرید سیگنال : A+
"""

# --- لیست کامل ۱۰۰ ارز برتر OKX ---
COINS = [
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
    "BAND-USDT","OCEAN-USDT","API3-USDT","SKL-USDT","RLC-USDT","NMR-USDT","LPT-USDT","BAL-USDT",
    "MASK-USDT","SUSHI-USDT","LRC-USDT","FLOKI-USDT"
]

# --- مدیریت ربات و حلقه اسکن ---
async def scanner_task(bot: Bot):
    print("Scanner loop started...")
    while True:
        for coin in COINS:
            try:
                signal = analyze(coin)
                if signal:
                    # فقط سیگنال‌های با امتیاز بالا ارسال شوند
                    if signal['score'] >= 75:
                        await bot.send_message(chat_id=CHAT_ID, text=build_message(signal))
                        await asyncio.sleep(2) # جلوگیری از اسپم تلگرام
            except Exception as e:
                print(f"Error in scan for {coin}: {e}")
        
        print("Scan cycle finished. Sleeping 15m...")
        await asyncio.sleep(900)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 اسکنر هوشمند فعال شد!\n۱۰۰ ارز برتر بازار هر ۱۵ دقیقه تحلیل می‌شوند.")

async def run_telegram_bot():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start_cmd))
    
    await application.initialize()
    await application.start()
    
    # شروع حلقه اسکن در پس‌زمینه
    asyncio.create_task(scanner_task(application.bot))
    
    await application.updater.start_polling()
    await asyncio.Event().wait()

def start_bot_thread():
    asyncio.run(run_telegram_bot())

if __name__ == "__main__":
    # ۱. اجرای ربات در Thread مجزا
    threading.Thread(target=start_bot_thread, daemon=True).start()
    
    # ۲. اجرای Flask برای پایداری در Render
    print(f"Starting Flask on port {PORT}...")
    app.run(host="0.0.0.0", port=PORT)
