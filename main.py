import telebot

# توکن خودت را اینجا بین دو کوتیشن قرار بده
TOKEN = 8979791105:AAGLK5usKZ54g7R4OmsQ2YkrN2cgUCegaLc

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "سلام! ربات شما با موفقیت در سرور رندر فعال شد و ۲۴ ساعته کار می‌کند. 🚀")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, "پیام شما دریافت شد: " + message.text)

print("Bot is running...")
bot.infinity_polling()
