import os
import telebot
import requests
import pandas as pd
from flask import Flask
from threading import Thread

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# تابع دریافت قیمت و تحلیل از نوبیتکس
def get_nobitex_analysis(symbol):
    try:
        # دریافت داده‌های بازار (شمعی)
        url = f"https://api.nobitex.ir/market/udf/history?symbol={symbol}&resolution=60&from=1670000000&to=2000000000"
        response = requests.get(url).json()
        
        if response['s'] != 'ok':
            return "❌ نماد یافت نشد. مثال: BTCIRT"

        df = pd.DataFrame({
            'close': response['c'],
            'high': response['h'],
            'low': response['l']
        })
        
        last_price = df['close'].iloc[-1]
        
        # یک محاسبه ساده RSI (نمونه)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs.iloc[-1]))
        
        status = "💎 پیشنهاد: نگهداری"
        if rsi < 30: status = "🟢 پیشنهاد: خرید (اشباع فروش)"
        elif rsi > 70: status = "🔴 پیشنهاد: فروش (اشباع خرید)"
        
        return f"📊 تحلیل نماد: {symbol}\n💰 قیمت فعلی: {last_price:,}\n📈 شاخص RSI: {rsi:.2f}\n\n{status}"
    except Exception as e:
        return "❌ خطا در دریافت اطلاعات از نوبیتکس."

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "سلام دکتر میثم! ربات تحلیلگر آماده است.\nبرای دریافت سیگنال بنویسید:\n/signal BTCIRT")

@bot.message_handler(commands=['signal'])
def sign_command(message):
    msg_parts = message.text.split()
    if len(msg_parts) < 2:
        bot.reply_to(message, "⚠️ لطفا نماد را وارد کنید.\nمثال: `/signal BTCIRT`", parse_mode="Markdown")
        return
    
    symbol = msg_parts[1].upper()
    bot.reply_to(message, "⌛ در حال تحلیل...")
    result = get_nobitex_analysis(symbol)
    bot.send_message(message.chat.id, result)

@app.route('/')
def health(): return "OK", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))).start()
    bot.infinity_polling()
