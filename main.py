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


@web_app.get("/")
def home():
    return "Bot is running!", 200


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ربات فعاله ✅")


def get_dollar_price():
    url = "https://api.tgju.org/v1/widget/tmp?keys=price_dollar_rl"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    data = response.json()

    price = (
        data.get("response", {})
        .get("indicators", {})
        .get("price_dollar_rl", {})
        .get("p")
    )

    if not price:
        raise ValueError("Dollar price not found in API response")

    return str(price)


async def send_price(context: ContextTypes.DEFAULT_TYPE):
    try:
        if not CHAT_ID:
            print("CHAT_ID is not set")
            return

        price = get_dollar_price()
        now = jdatetime.datetime.now().strftime("%Y/%m/%d - %H:%M")

        text = f"💵 قیمت دلار:\n{price}\n🕒 {now}"
        awa context.bot.send_message(chat_id=CHAT_ID, text=text)
        print("Price sent successfully")

    except Exception as error:
        print(f"send_price error: {error}")


async def manual_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = get_dollar_price()
        now = jdatetime.datetime.now().strftime("%Y/%m/%d - %H:%M")

        text = f"💵 قیمت دلار:\n{price}\n🕒 {now}"
        await update.message.reply_text(text)

    except Exception as error:
        await update.message.reply_text(f"خطا در دریافت قیم {error}")


def run_bot():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", manual_scan))

    if app.job_queue:
        app.job_queue.run_repeating(send_price, interval=900, first=10)
    else:
        print("JobQueue is not available")

    print("Telegram bot started")
    app.run_polling(drop_pending_updates=True)


def main():
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
