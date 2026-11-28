import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- अपनी डिटेल्स यहाँ डालें ---
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMIN_IDS = [123456789, 987654321]  # यहाँ अपनी और एडमिन की Telegram User ID डालें
COMMISSION_PERCENT = 10  # 100 पर 10% कमीशन कटेगा (यानी 100+90 मिलेगा)

# डेटाबेस (बैलेंस और टेबल स्टोर करने के लिए)
user_balances = {}
user_names = {}
tables = {}
table_counter = 0

logging.basicConfig(level=logging.INFO)

def is_admin(user_id):
    return user_id in ADMIN_IDS

# क्लिकेबल नाम बनाने का फंक्शन (क्लिक करने पर ID खुलेगी)
def clickable_name(user_id, name):
    return f'<a href="tg://user?id={user_id}">{name}</a>'

# कमांड मैसेज को तुरंत डिलीट करने का फंक्शन
async def delete_cmd(update: Update):
    try:
        await update.message.delete()
    except Exception:
        pass

# 1. /start कमांड (ताकि यूजर को पर्सनल मैसेज जा सके)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_names[user.id] = user.first_name
    if user.id not in user_balances:
        user_balances[user.id] = 0.0
    await update.message.reply_text(
        f"🙏 स्वागत है <b>{user.first_name}</b>!\nआपका अकाउंट एक्टिव है। अब आपको सभी गेम और बैलेंस अपडेट यहाँ पर्सनल में मिलेंगे।",
        parse_mode="HTML"
    )

# 2. बैलेंस लिस्ट जनरेट करना और पिन करना
async def update_and_pin_list(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    if not user_balances:
        return
    
    # बैलेंस के घटते क्रम में लिस्ट बनाना
    sorted_users = sorted(user_balances.items(), key=lambda x: x[1], reverse=True)
    lines = ["📊 <b>LIVE BALANCE LIST</b> 📊\n"]
    
    for idx, (uid, bal) in enumerate(sorted_users, start=1):
        name = user_names.get(uid, f"Player {uid}")
        lines.append(f"{idx}. {clickable_name(uid, name)} -- <b>₹{bal:.2f}</b>")
        
    lines.append(f"\n👥 <b>Total Members: {len(sorted_users)}</b>")
    text = "\n".join(lines)
    
    keyboard = [[InlineKeyboardButton("💰 CHECK YOUR BALANCE", callback_data="check_bal")]]
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    try:
        await context.bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
    except Exception:
        pass

# 3. /add कमांड (उदाहरण: किसी के मैसेज पर रिप्लाई करके /add 500 लिखें)
async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not is_admin(update.effective_user.id):
        return
    
    if not update.message.reply_to_message or not context.args:
        return
    
    target = update.message.reply_to_message.from_user
    amount = float(context.args[0])
    
    user_names[target.id] = target.first_name
    user_balances[target.id] = user_balances.get(target.id, 0.0) + amount
    
    # पर्सनल में अपडेट भेजना
    try:
        await context.bot.send_message(
            chat_id=target.id,
            text=(
                f"💳 <b>BALANCE ADDED</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"1️⃣ <b>Add Amount:</b> +₹{amount:.2f}\n"
                f"2️⃣ <b>Total Balance:</b> ₹{user_balances[target.id]:.2f}\n"
                f"━━━━━━━━━━━━━━━"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass
        
    await update_and_pin_list(context, update.effective_chat.id)

# 4. /minus कमांड (रिप्लाई करके /minus 200 लिखें)
async def minus_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not is_admin(update.effective_user.id):
        return
    
    if not update.message.reply_to_message or not context.args:
        return
    
    target = update.message.reply_to_message.from_user
    amount = float(context.args[0])
    
    user_names[target.id] = target.first_name
    user_balances[target.id] = max(0.0, user_balances.get(target.id, 0.0) - amount)
    await update_and_pin_list(context, update.effective_chat.id)

# 5. /list और /pin कमांड
async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if is_admin(update.effective_user.id):
        await update_and_pin_list(context, update.effective_chat.id)

# 6. /table कमांड (उदाहरण: /table @user1 @user2 250)
async def create_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global table_counter
    await delete_cmd(update)  # टेबल लगाने वाला कमांड मैसेज डिलीट होगा, टेबल नहीं
    
    if not is_admin(update.effective_user.id):
        return

    # मेंशन किए गए दोनों यूजर निकालना
    mentions = [ent for ent in update.message.entities if ent.type == "text_mention"]
    if len(mentions) < 2 or not context.args:
        return

    p1 = mentions[0].user
    p2 = mentions[1].user
    try:
        amount = float(context.args[-1])
    except ValueError:
        return

    user_names[p1.id] = p1.first_name
    user_names[p2.id] = p2.first_name
    
    # दोनों के वॉलेट से एंट्री फीस काटना
    user_balances[p1.id] = user_balances.get(p1.id, 0.0) - amount
    user_balances[p2.id] = user_balances.get(p2.id, 0.0) - amount

    table_counter += 1
    t_id = table_counter
    tables[t_id] = {
        "p1_id": p1.id, "p1_name": p1.first_name,
        "p2_id": p2.id, "p2_name": p2.first_name,
        "amount": amount,
        "status": "active"
    }

    table_text = (
        f"🎲 <b>𝑻𝒂𝒃𝒍𝒆 𝑵𝒐. {t_id}</b>\n\n"
        f"(1). {clickable_name(p1.id, p1.first_name)}\n\n"
        f"(2). {clickable_name(p2.id, p2.first_name)}\n\n"
        f"<b>{int(amount)}</b> ✅ 𝗕𝗘𝗦𝗧 ★ 𝗢𝗙 ★𝗟𝗨𝗖𝗞 🎯🎯"
    )

    # बिना नाम वाले बटन
    keyboard = [
        [
            InlineKeyboardButton("#win 🏆", callback_data=f"win_{t_id}_1"),
            InlineKeyboardButton("#win 🏆", callback_data=f"win_{t_id}_2")
        ],
        [
            InlineKeyboardButton("Cancel this table ❌", callback_data=f"cancel_{t_id}")
        ]
    ]

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=table_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

# 7. बटन हैंडलिंग (#win और Cancel)
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    # बैलेंस चेक बटन सबके लिए
    if query.data == "check_bal":
        bal = user_balances.get(user_id, 0.0)
        await query.answer(f"💰 आपका वर्तमान बैलेंस: ₹{bal:.2f}", show_alert=True)
        return

    # बाकी बटन सिर्फ Admin दबा सकता है
    if not is_admin(user_id):
        await query.answer("❌ यह बटन सिर्फ एडमिन के लिए है!", show_alert=True)
        return

    parts = query.data.split("_")
    action = parts[0]
    t_id = int(parts[1])
    table = tables.get(t_id)

    if not table or table["status"] != "active":
        await query.answer("⚠️ यह टेबल पहले ही अपडेट हो चुकी है।", show_alert=True)
        return

    p1_link = clickable_name(table["p1_id"], table["p1_name"])
    p2_link = clickable_name(table["p2_id"], table["p2_name"])
    amt = table["amount"]

    if action == "win":
        winner_num = int(parts[2])
        table["status"] = "completed"

        win_profit = amt * (1 - COMMISSION_PERCENT / 100)  # 100 का 90 बनेगा
        total_return = amt + win_profit  # 100 + 90 = 190

        if winner_num == 1:
            win_id, win_name = table["p1_id"], table["p1_name"]
            p1_display = f"{p1_link} ✅"
            p2_display = p2_link
        else:
            win_id, win_name = table["p2_id"], table["p2_name"]
            p1_display = p1_link
            p2_display = f"{p2_link} ✅"

        user_balances[win_id] = user_balances.get(win_id, 0.0) + total_return

        # टेबल एडिट करके जीतने वाले के आगे ✅ लगाना
        new_text = (
            f"🎲 <b>𝑻𝒂𝒃𝒍𝒆 𝑵𝒐. {t_id}</b>\n\n"
            f"(1). {p1_display}\n\n"
            f"(2). {p2_display}\n\n"
            f"<b>{int(amt)}</b> ✅ 𝗕𝗘𝗦𝗧 ★ 𝗢𝗙 ★𝗟𝗨𝗖𝗞 🎯🎯"
        )
        await query.edit_message_text(text=new_text, parse_mode="HTML")

        # विजेता को पर्सनल में सुंदर डिजाइन और नंबरिंग के साथ अपडेट भेजना
        personal_msg = (
            f"🏆 <b>CONGRATULATIONS {win_name}!</b> 🏆\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"1️⃣ <b>Table No:</b> #{t_id}\n"
            f"2️⃣ <b>Match Bet:</b> ₹{int(amt)}\n"
            f"3️⃣ <b>Win Profit:</b> ₹{int(win_profit)} (Commission Cut)\n"
            f"4️⃣ <b>Total Credited:</b> ₹{int(total_return)} ({int(amt)}+{int(win_profit)})\n"
            f"5️⃣ <b>New Balance:</b> ₹{user_balances[win_id]:.2f}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        try:
            await context.bot.send_message(chat_id=win_id, text=personal_msg, parse_mode="HTML")
        except Exception:
            pass

        # ग्रुप में नई बैलेंस लिस्ट अपडेट और पिन करना
        await update_and_pin_list(context, update.effective_chat.id)

    elif action == "cancel":
        table["status"] = "cancelled"
        # दोनों खिलाड़ियों के पैसे वापस करना
        user_balances[table["p1_id"]] += amt
        user_balances[table["p2_id"]] += amt

        # कैंसिल होने पर ❌❌ इमोजी लगाना
        cancel_text = (
            f"🎲 <b>𝑻𝒂𝒃𝒍𝒆 𝑵𝒐. {t_id}</b>\n\n"
            f"(1). {p1_link} ❌❌\n\n"
            f"(2). {p2_link} ❌❌\n\n"
            f"<b>{int(amt)}</b> ❌ 𝗧𝗔𝗕𝗟𝗘 𝗖𝗔𝗡𝗖𝗘𝗟𝗟𝗘𝗗"
        )
        await query.edit_message_text(text=cancel_text, parse_mode="HTML")

# बॉट को 24 घंटे चालू रखने के लिए Main फंक्शन
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_balance))
    app.add_handler(CommandHandler("minus", minus_balance))
    app.add_handler(CommandHandler("list", list_cmd))
