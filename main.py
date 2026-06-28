import os
import asyncio
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# تنظیمات اصلی
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is Running!", 200

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! ربات با موفقیت فعال شد. برای دریافت قیمت دستور /price را بزنید.")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("در حال دریافت قیمت... (این یک تست است)")

def run_telegram():
    print("Starting Telegram Bot...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    
    application.run_polling(close_loop=False)

if __name__ == "__main__":
    # اجرای ربات تلگرام در یک رشته جداگانه
    threading.Thread(target=run_telegram, daemon=True).start()
    
    # اجرای وب‌سرور برای رندر
    print(f"Starting Web Server on port {PORT}...")
    app.run(host="0.0.0.0", port=PORT)
