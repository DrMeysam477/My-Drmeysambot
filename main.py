  import os
import threading
import time
import requests
import pandas as pd
import numpy as np
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
MARKET_TYPE = os.getenv("MARKET_TYPE", "SWAP")  # SPOT or SWAP
AUTO_SCAN = os.getenv("AUTO_SCAN", "false").lower() == "true"
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    app.run(host='0.0.0.0', port=10000)

# --- OKX API FUNCTIONS ---
def get_okx_candles(symbol, timeframe='4H', limit=100):
    try:
        # Normalize symbol for OKX
        inst_id = f"{symbol.upper()}-USDT-{MARKET_TYPE}"
        url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar={timeframe}&limit={limit}"
        res = requests.get(url, timeout=10).json()
        if res.get('code') == '0':
            df = pd.DataFrame(res['data'], columns=['ts', 'o', 'h', 'l', 'c', 'v', 'vol_curr', 'vol_curr_quote', 'confirm'])
            df[['o', 'h', 'l', 'c', 'v']] = df[['o', 'h', 'l', 'c', 'v']].astype(float)
            return df[::-1].reset_index(drop=True)
    except Exception as e:
        print(f"Error fetching candles for {symbol}: {e}")
    return None

# --- INDICATORS ---
def calculate_indicators(df):
    if df is None or len(df) < 50: return None
    close = df['c']
    # EMA
    df['ema20'] = close.ewm(span=20, adjust=False).mean()
    df['ema50'] = close.ewm(span=50, adjust=False).mean()
    # RSI
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("My-Drmeysambot (V2.0) is Online! 🚀\nUse /signal [Symbol] or /status")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ System Status: Stable\n📈 Mode: Long/Short\n⚡ BTC Filter: Active")

async def get_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Please provide a symbol. e.g. /signal BTC")
        return
    
    symbol = context.args[0].upper()
    await update.message.reply_text(f"🔍 Analyzing {symbol} on 4H, 1H and 15m...")
    
    df_4h = get_okx_candles(symbol, '4H', 100)
    if df_4h is None:
        await update.message.reply_text("❌ Error: Could not fetch data. Check symbol name.")
        return

    df_4h = calculate_indicators(df_4h)
    last_price = df_4h['c'].iloc[-1]
    rsi = df_4h['rsi'].iloc[-1]
    
    # Simple logic for testing (we will expand this)
    msg = f"📊 *Analysis for {symbol}*\n"
    msg += f"💰 Price: {last_price}\n"
    msg += f"📉 RSI (4H): {rsi:.2f}\n\n"
    
    if rsi < 30:
        msg += "🟢 Potential LONG (Oversold)"
    elif rsi > 70:
        msg += "🔴 Potential SHORT (Overbought)"
    else:
        msg += "⚪ Neutral - No clear signal yet."
        
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- MAIN ---
if __name__ == "__main__":
    print("Starting Flask...")
    threading.Thread(target=run_flask, daemon=True).start()

    print("Starting Telegram Bot...")
    if not TOKEN:
        print("ERROR: No BOT_TOKEN found!")
    else:
        application = ApplicationBuilder().token(TOKEN).build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("signal", get_signal))
        
        print("Bot is Polling...")
        application.run_polling()
