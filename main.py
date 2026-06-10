import os
import telebot
import requests
import pandas as pd
from flask import Flask
from threading import Thread

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

def get_nobitex_data(symbol):
    try:
        # استفاده از API عمومی نوبیتکس برای قیمت لحظه‌ای
        url = "https://api.nobitex.ir/v2/orderbook/all"
        response = requests.get(url).json()
        
        if response['status'] == 'ok':
            # پیدا کردن نماد در لیست (مثلاً BTCIRT)
            pair = symbol.upper()
            if pair in response:
                last_price = response[pair]['lastTradePrice']
                best_sell = response[pair]['asks'][0][0]
                best_buy = response[pair]['bids'][0][0]
                
                return (f"📊 وضعیت بازار نوبیتکس:\n\n"
                        f"💰 قیمت لحظه‌ای {symbol}: {int(last_price):,} ریال\n"
                        f"📈 بهترین فروش: {int(best_sell):,}\n"
                        f"📉 بهترین خرید: {int(best_buy):,}\n"
                        f"✨ وضعیت: متصل به بازار")
            else:
                return "❌ این نماد در نوبیتکس یافت نشد.\nمثال صحیح: BTCIRT یا ETHIRT"
        else:
            return "❌ خطای موقت در ارتباط با صرافی."
    except:
        return "❌ سرور صرافی در دسترس نیست. لطفا کمی بعد امتحان کنید."

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "سلام! ربات تحلیل‌گر نوبیتکس آنلاین شد.\nبرای قیمت بنویسید:\n/signal BTCIRT")

@bot.message_handler(commands=['signal'])
def sign_command(message):
    msg_parts = message.text.split()
    if len(msg_parts) < 2:
        bot.reply_to(message, "⚠️ لطفا نماد را وارد کنید.\nمثال: `/signal BTCIRT`", parse_mode="Markdown")
        return
    
    symbol = msg_parts[1].upper()
    bot.reply_to(message, "⌛ در حال استعلام قیمت از نوبیتکس...")
    result = get_nobitex_data(symbol)
    bot.send_message(message.chat.id, result)

@app.route('/')
def health(): return "OK", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))).start()
    bot.infinity_polling()
