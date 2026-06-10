@bot.message_handler(commands=['signal'])
def get_signal(message):
    try:
        text = message.text.split()
        if len(text) < 2:
            bot.reply_to(message, "⚠️ لطفا نماد را وارد کنید.\nمثال: /signal BTCUSDT")
            return
        
        symbol = text[1].upper()
        # حذف IRT و جایگزینی با USDT برای هماهنگی با بای‌بیت
        if "IRT" in symbol:
            symbol = symbol.replace("IRT", "USDT")
            
        sent_msg = bot.reply_to(message, f"⌛ در حال استعلام {symbol} از بای‌بیت...")
        
        url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}"
        response = requests.get(url, timeout=10)
        
        # بررسی اینکه آیا پاسخ وب‌سایت واقعاً JSON معتبر است
        try:
            data = response.json()
        except:
            bot.edit_message_text("❌ خطا در دریافت پاسخ از صرافی.", chat_id=message.chat.id, message_id=sent_msg.message_id)
            return

        if data.get('retCode') == 0 and data.get('result') and len(data['result']['list']) > 0:
            ticker = data['result']['list'][0]
            price = float(ticker['lastPrice'])
            
            msg = (f"✅ قیمت لحظه‌ای {symbol}:\n\n"
                   f"💰 قیمت: {price:,.2f} USDT\n"
                   f"📈 تغییر ۲۴ ساعته: {float(ticker['price24hPcnt'])*100:.2f}%\n"
                   f"🔝 سقف: {float(ticker['highPrice24h']):,.2f}\n"
                   f"🔙 کف: {float(ticker['lowPrice24h']):,.2f}")
            bot.edit_message_text(msg, chat_id=message.chat.id, message_id=sent_msg.message_id)
        else:
            bot.edit_message_text(f"❌ نماد {symbol} در بای‌بیت یافت نشد.\nنکته: از USDT استفاده کنید.", chat_id=message.chat.id, message_id=sent_msg.message_id)

    except Exception as e:
        bot.reply_to(message, f"❌ خطای غیرمنتظره: {str(e)}")
