import os
import asyncio
import threading
import requests
import pandas as pd
from flask import Flask
from telegram.ext import ApplicationBuilder, CommandHandler

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!", 200

def analyze(symbol="BTC-USDT"):
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=1H&limit=1"
        r = requests.get(url, timeout=10)
        data = r.json().get("data", [])
        if not data:
            return None
        df = pd.DataFrame(data)
        price = float(df.iloc[0, 4])
        return {"symbol": symbol, "price": price}
    except Exception as e:
        print(e)
        return None

async def start(update, context):
    await update.message.reply_text("ربات فعاله")

async def scanner_task(application):
    await asyncio.sleep(10)
    while True:
        try:
            sig = await asyncio.to_thread(analyze, "BTC-USDT")
            if sig and CHAT_ID:
                await application.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"{sig['symbol']} : {sig['price']}"
                )
        except Exception as e:
            print(e)
        await asyncio.sleep(600)

def run_bot():
    if not TOKEN:
        print("BOT_TOKEN not set")
        return

    async def bot_main():
        application = ApplicationBuilder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        asyncio.create_task(scanner_task(application))
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        await asyncio.Event().wait()

    asyncio.run(bot_main())

threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
