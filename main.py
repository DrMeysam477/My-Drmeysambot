import os
import threading
import asyncio
import requests
import pandas as pd
import pandas_ta as ta
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dataclasses import dataclass
from datetime import datetime

# ---------- زیرساخت برای رندر ----------
flask_app = Flask(__name__)
@flask_app.route("/")
def home(): return "Scanner is Live", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)

# ---------- کلاس سیگنال شما ----------
@dataclass
class Signal:
    symbol: str; direction: str; timeframe: str; entry_low: float; entry_high: float
    atr: float; stop_loss: float; score: int; confidence: int; risk_reward: float
    tp1_probability: int = 81; tp2_probability: int = 70; tp3_probability: int = 55; tp4_probability: int = 40
    liquidity_ok: bool = True; spread: float = 0.1; anti_fomo_active: bool = False
    market_structure_confirmed: bool = True; whale_activity_confirmed: bool = True
    btc_filter: str = "confirmed"; market_regime: str = "aligned"

# ---------- توابع کمکی تحلیل (بر اساس فرمول شما) ----------
def should_send_signal(sig: Signal):
    if sig.score < 80 or sig.confidence < 80 or sig.risk_reward < 2: return False, "Low Score"
    return True, "Approved"

def format_telegram_message(sig: Signal):
    entry_avg = (sig.entry_low + sig.entry_high) / 2
    tp1 = entry_avg + (1.0 * sig.atr if sig.direction == "LONG" else -1.0 * sig.atr)
    now = datetime.now().strftime("%H:%M")
    return f"🕘 {now}\n📊 {sig.symbol}\nDirection: {sig.direction} {'🟢' if sig.direction=='LONG' else '🔴'}\nEntry: {sig.entry_low:.4f}\nTP1: {tp1:.4f}\nSL: {sig.stop_loss:.4f}\nScore: {sig.score}/100"

# ---------- دریافت دیتا از OKX ----------
def get_okx_data(symbol="BTC-USDT"):
    url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=15m&limit=50"
    try:
        r = requests.get(url, timeout=10).json()
        if r['code'] == '0':
            df = pd.DataFrame(r['data'], columns=['ts', 'o', 'h', 'l', 'c', 'v', 'v_vol', 'v_vol_quote', 'confirm'])
            df[['o','h','l','c','v']] = df[['o','h','l','c','v']].astype(float)
            return df
        return None
    except: return None

# ---------- عملیات اسکن ----------
async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    # لیست ارزهایی که میخواهی اسکن کنی
    symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT"]
    chat_id = context.job.chat_id

    for sym in symbols:
        df = get_okx_data(sym)
        if df is None: continue
        
        # محاسبه ATR ساده
        df['atr'] = ta.atr(df['h'], df['l'], df['c'], length=14)
        last_price = df['c'].iloc[0]
        last_atr = df['atr'].iloc[0]

        # ساخت یک سیگنال فرضی برای تست فرمول شما
        # اینجا باید استراتژی خودت را برای جهت (LONG/SHORT) بنویسی
        test_signal = Signal(
            symbol=sym, direction="LONG", timeframe="15M",
            entry_low=last_price, entry_high=last_price*1.002,
            atr=last_atr, stop_loss=last_price - (2*last_atr),
            score=85, confidence=82, risk_reward=2.5
        )

        approved, reason = should_send_signal(test_signal)
        if approved:
            msg = format_telegram_message(test_signal)
            await context.bot.send_message(chat_id=chat_id, text=f"🚀 **SIGNAL FOUND**\n\n{msg}")

# ---------- دستورات ربات ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # فعال کردن اسکن خودکار هر 15 دقیقه (900 ثانیه)
    context.job_queue.run_repeating(scan_market, interval=900, first=10, chat_id=chat_id)
    await update.message.reply_text("Scanner Started! I will scan every 15 minutes. ✅")

# ---------- اجرای اصلی ----------
def run_bot():
    token = os.environ.get("BOT_TOKEN")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    print("Scanner Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_bot()
