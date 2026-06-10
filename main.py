import os
import telebot
import requests
from flask import Flask
from threading import Thread

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

def get_nobitex_price(symbol):
    try:
        # استفاده از API جایگزین که روی سرورهای خارجی بهتر جواب می‌دهد
        url = "https://api.nobitex.ir/market/stats"
        params = {'srcCurrency': symbol.replace('IRT', '').lower(), 'dstCurrency': 'rls'}
        
        # اگر کاربر نماد تتر خواست
        if 'USDT' in symbol.upper():
            params['srcCurrency'] = 'usdt'

        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data['status'] == 'ok':
            # نوبیتکس قیمت را به تومان (ریال حذف شده در نمایش) برمی‌گرداند
            stats = data['stats']
            # پیدا کردن کلید داینامیک (مثلاً btc-rls)
            pair_key = f"{params['srcCurrency']}-rls"
            
            if pair_key in stats:
                price = stats[pair_key]['latest']
                change = stats[pair_key]['dayChange']
                high = stats[pair_key]['dayHigh']
                low = stats[pair_key]['dayLow']
                
                return (f"✅ استعلام موفق از نوبیتکس:\n\n"
                        f"🪙 نماد: {symbol.upper()}\n"
                        f"💰 قیمت فعلی: {int(float(price)*10):,} ریال\n"
                        f"📈 بالاترین امروز: {int(float(high)*10):,}\n"
                        f"📉 پایین‌ترین امروز: {int(float(low)*10):,}\n"
                        f"📊 تغییر ۲۴ ساعته: {change}%\n"
                        f"🟢 وضعیت: آنلاین")
            else:
                return "❌ نماد یافت نشد. مثال: BTCIRT"
        else:
            return "❌ صرافی پاسخ معتبری نداد."
    except Exception as e:
        return f"❌ خطا در اتصال به نوبیتکس. (سرور خارج محدود شده است)"

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "سلام! ربات تحلیل‌گر نوبیتکس آماده است.\nمثال: /signal BTCIRT")

@bot.message_handler(commands=['signal'])
def sign_command(message):
    msg_parts = message.text.split()
    if len(msg_parts) < 2:
        bot.reply_to(message, "⚠️ لطفا نماد را وارد کنید.\nمثال: `/signal BTCIRT`", parse_mode="Markdown")
        return
    
    symbol = msg_parts[1].upper()
    bot.reply_to(message, f"⌛ در حال استعلام قیمت {symbol}...")
    result = get_nobitex_price(symbol)
    bot.send_message(message.chat.id, result)

@app.route('/')
def health(): return "OK", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))).start()
    bot.infinity_polling()
