import telebot

TOKEN = '8979791105:AAFE_r734rshqOUfkaEDPSidXptpGxXIYHs'

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "سلام! من در سرور رندر بیدار هستم.")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, message.text)

bot.infinity_polling()
