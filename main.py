import telebot
from flask import Flask
from threading import Thread

# توکن جدید و کامل شما
API_TOKEN = '8979791105:AAFE_r734rshqOUfkaEDPSidXptpGxXIYHs'
bot = telebot.TeleBot(API_TOKEN)
app = Flask('')

@app.route('/')
def home():
    return "Bot is Running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# دستور شروع
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "✅ سلام دکتر میثم! ربات با توکن جدید و موفقیت فعال شد.\n\nمن را در گروه ادمین کنید تا دستورات مدیریت فعال شود.")

# دستور حذف پیام (در پاسخ به یک پیام فرستاده شود)
@bot.message_handler(commands=['del'])
def delete_message(message):
    try:
        if message.reply_to_message:
            bot.delete_message(message.chat.id, message.reply_to_message.message_id)
            bot.delete_message(message.chat.id, message.message_id)
        else:
            bot.reply_to(message, "⚠️ لطفا این دستور را در پاسخ (Reply) به یک پیام بفرستید.")
    except Exception as e:
        bot.reply_to(message, "❌ خطا! مطمئن شوید من در گروه ادمین هستم.")

# دستور پین کردن پیام (در پاسخ به یک پیام فرستاده شود)
@bot.message_handler(commands=['pin'])
def pin_message(message):
    try:
        if message.reply_to_message:
            bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id)
        else:
            bot.reply_to(message, "⚠️ لطفا این دستور را در پاسخ (Reply) به یک پیام بفرستید.")
    except Exception as e:
        bot.reply_to(message, "❌ خطا در پین کردن پیام.")

# تکرار پیام برای تست
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, f"شما گفتید: {message.text}")

if __name__ == "__main__":
    keep_alive()
    print("Bot is starting...")
    bot.infinity_polling()
