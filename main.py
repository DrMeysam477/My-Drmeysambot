import os
import threading
import requests
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is running", 200


def get_btc_price():
    try:
        url = "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT"
        response = requests.get(url, timeout=10)
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            price = data["data"][0]["last"]
            return f"BTC-USDT price: {price}"

        return "Could not get BTC price."
    except Exception as e:
        return f"Price error: {e}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running.")


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = get_btc_price()
    await update.message.reply_text(message)


def run_bot():
    if 
