import os
import threading
from flask import Flask
from telegram.ext import ApplicationBuilder

app = Flask(__name__)

@app.route("/")
def home():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def main():
    TOKEN = os.environ.get("BOT_TOKEN")

    if not TOKEN:
        raise ValueError("BOT_TOKEN is not set in Render environment variables")

    application = ApplicationBuilder().token(TOKEN).build()

    print("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    main()
