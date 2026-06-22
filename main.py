import os
import threading
import requests
import jdatetime

from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not TOKEN:
    raise ValueError("BOT_TOKEN is not set")

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "Bot is running!", 200


def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)


def get_dollar_price():
    url = "https://api.tgju.org/v1/widget/tmp?keys=price_dollar_rl"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    data = response.json()

    try:
        price = data["response"]["indicators"]["price_dollar_rl"]["p"]
    except Exception:
        raise ValueError(f"Invalid API response: {data}")

    return str(price)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ربات فعاله ✅")


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = get_dollar_price()
        now = jdatetime.datetime.now().strftime("%Y/%m/%d - %H:%M")
        text = f"💵 قیمت دلار:\n{price}\n🕒 {now}"
        await update.message.reply_text(text)
    except Exception as error:
        await update.message.reply_text(f"خطا: {error}")


def run_bot():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan))

    print("Telegram bot started...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    run_bot()
