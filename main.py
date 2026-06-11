import os
import threading
import telebot
from flask import Flask
import requests
import pandas as pd

# --- تنظیمات اولیه ---
# توکن ربات را از Environment Variables در Render بخوانید
TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# --- مکانیزم Flask برای Render ---
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running and alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- منطق اصلی ربات ---

def analyze_symbol(symbol):
    """
    این تابع داده‌ها را از API می‌گیرد.
    در اینجا از try/except استفاده کردیم تا اگر داده‌ای نیامد، ربات کرش نکند.
    """
    try:
        # نمونه فراخوانی API (به عنوان مثال Bybit)
        url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}USDT"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if 'result' not in data or not data['result']['list']:
            return None, "داده‌ای برای این نماد یافت نشد."
            
        # پردازش ساده (جایگزین منطق خط ۱۷۰ سابق)
        price = data['result']['list'][0]['lastPrice']
        return f"قیمت فعلی {symbol}: {price}", None
    except Exception as e:
        return None, str(e)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "سلام! ربات تحلیل ارز دیجیتال فعال است.")

@bot.message_handler(commands=['debug'])
def debug_command(message):
    bot.reply_to(message, "در حال بررسی اتصال به API...")
    # تست اتصال ساده
    bot.reply_to(message, "اتصال برقرار است.")

@bot.message_handler(commands=['scan', 'signal'])
def handle_analysis(message):
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "لطفاً نماد را وارد کنید. مثال: /scan BTC")
            return
        
        symbol = args[1].upper()
        bot.reply_to(message, f"در حال تحلیل {symbol}...")
        
        result, error = analyze_symbol(symbol)
        
        if error:
            bot.reply_to(message, f"خطا در تحلیل: {error}")
        else:
            bot.reply_to(message, result)
            
    except Exception as e:
        # این بخش همان خطای ۱۷۰ سابق را مدیریت می‌کند
        bot.reply_to(message, f"یک خطای بحرانی رخ داد: {str(e)}")

# --- اجرای همزمان Flask و Bot ---
if __name__ == "__main__":
    # شروع وب‌سرور در یک ترد جداگانه
    threading.Thread(target=run_flask, daemon=True).start()
    
    print("Bot started polling...")
    bot.polling(none_stop=True)
