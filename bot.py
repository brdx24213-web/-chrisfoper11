import os
import sqlite3
import threading
import logging
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- 1. Render Environment Variables ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
COMMISSION_PERCENT = 10  # 100 पर 10% कमीशन (100 + 90)

logging.basicConfig(level=logging.INFO)

# --- 2. Flask Server (Render पर 24 घंटे चालू रखने के लिए) ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is alive 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# --- 3. SQLite Database (ताकि बैलेंस कभी डिलीट न हो) ---
conn = sqlite3.connect("ludo_bot.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, balance REAL)")
conn.commit()

def get_user_balance(user_id):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0.0

def update_user_db(user_id, name, new_balance):
    cursor.execute("INSERT OR REPLACE INTO users (user_id, name, balance) VALUES (?, ?, ?)", (user_id, name, new_balance))
    conn.commit()

def get_all_users():
    cursor.execute("SELECT user_id, name, balance FROM users ORDER BY balance DESC")
    return cursor.fetchall()

tables = {}
table_counter = 0

def is_admin(user_id):
    return user_id in ADMIN_IDS

def clickable_name(user_id, name):
    return f'<a href="tg://user?id={user_id}">{name}</a>'

async def delete_cmd(update: Update):
    try:
        await update.message.delete()
    except Exception:
        pass

# --- 4. Bot Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bal = get_user_balance(user.id)
    update_user_db(user.id, user.first_name, bal)
    await update.message.reply_text(
        f"🙏 स्वागत है <b>{user.first_name}</b>!\nआपका अकाउंट एक्टिव है। अब आपको सभी गेम और बैलेंस अपडेट यहाँ पर्सनल में मिलेंगे।",
        parse_mode="HTML"
    )

async def update_and_pin_list(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    users = get_all_users()
    if not users:
        return
    
    lines = ["📊 <b>LIVE BALANCE LIST</b> 📊\n"]
    for idx, (uid, name, bal) in enumerate(users, start=1):
        lines.append(f"{idx}. {clickable_name(uid, name)} -- <b>₹{bal:.2f}</b>")
        
    lines.append(f"\n👥 <b>Total Members: {len(users)}</b>")
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

async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not is_admin(update.effective_user.id) or not update.message.reply_to_message or not context.args:
        return
    
    target = update.message.reply_to_message.from_user
    try:
        amount = float(context.args[0])
    except ValueError:
        return
    
    new_bal = get_user_balance(target.id) + amount
    update_user_db(target.id, target.first_name, new_bal)
    
    try:
        await context.bot.send_message(
            chat_id=target.id,
            text=(
                f"💳 <b>BALANCE ADDED</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"1️⃣ <b>Add Amount:</b> +₹{amount:.2f}\n"
                f"2️⃣ <b>Total Balance:</b> ₹{new_bal:.2f}\n"
                f"━━━━━━━━━━━━━━━"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass
        
    await update_and_pin_list(context, update.effective_chat.id)

async def minus_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if not is_admin(update.effective_user.id) or not update.message.reply_to_message or not context.args:
        return
    
    target = update.message.reply_to_message.from_user
    try:
        amount = float(context.args[0])
    except ValueError:
        return
    
    new_bal = max(0.0, get_user_balance(target.id) - amount)
    update_user_db(target.id, target.first_name, new_bal)
    await update_and_pin_list(context, update.effective_chat.id)

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_cmd(update)
    if is_admin(update.effective_user.id):
        await update_and_pin_list(context, update.effective_chat.id)

async def create_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global table_counter
    await delete_cmd(update)
    
    if not is_admin(update.effective_user.id):
        return

    mentions = [ent for ent in update.message.entities if ent.type == "text_mention"]
    if len(mentions) < 2 or not context.args:
        return

    p1 = mentions[0].user
    p2 = mentions[1].user
    try:
        amount = float(context.args[-1])
    except ValueError:
        return

    update_user_db(p1.id, p1.first_name, get_user_balance(p1.id) - amount)
    update_user_db(p2.id, p2.first_name, get_user_balance(p2.id) - amount)

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

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if query.data == "check_bal":
        bal = get_user_balance(user_id)
        await query.answer(f"💰 आपका वर्तमान बैलेंस: ₹{bal:.2f}", show_alert=True)
        return

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

        win_profit = amt * (1 - COMMISSION_PERCENT / 100)
        total_return = amt + win_profit

        if winner_num == 1:
            win_id, win_name = table["p1_id"], table["p1_name"]
            p1_display, p2_display = f"{p1_link} ✅", p2_link
        else:
            win_id, win_name = table["p2_id"], table["p2_name"]
            p1_display, p2_display = p1_link, f"{p2_link} ✅"

        new_bal = get_user_balance(win_id) + total_return
        update_user_db(win_id, win_name, new_bal)

        new_text = (
            f"🎲 <b>𝑻𝒂𝒃𝒍𝒆 𝑵𝒐. {t_id}</b>\n\n"
            f"(1). {p1_display}\n\n"
            f"(2). {p2_display}\n\n"
            f"<b>{int(amt)}</b> ✅ 𝗕𝗘𝗦𝗧 ★ 𝗢𝗙 ★𝗟𝗨𝗖𝗞 🎯🎯"
        )
        await query.edit_message_text(text=new_text, parse_mode="HTML")

        personal_msg = (
            f"🏆 <b>CONGRATULATIONS {win_name}!</b> 🏆\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"1️⃣ <b>Table No:</b> #{t_id}\n"
            f"2️⃣ <b>Match Bet:</b> ₹{int(amt)}\n"
            f"3️⃣ <b>Win Profit:</b> ₹{int(win_profit)} (Commission Cut)\n"
            f"4️⃣ <b>Total Credited:</b> ₹{int(total_return)} ({int(amt)}+{int(win_profit)})\n"
            f"5️⃣ <b>New Balance:</b> ₹{new_bal:.2f}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        try:
            await context.bot.send_message(chat_id=win_id, text=personal_msg, parse_mode="HTML")
        except Exception:
            pass

        await update_and_pin_list(context, update.effective_chat.id)

    elif action == "cancel":
        table["status"] = "cancelled"
        update_user_db(table["p1_id"], table["p1_name"], get_user_balance(table["p1_id"]) + amt)
        update_user_db(table["p2_id"], table["p2_name"], get_user_balance(table["p2_id"]) + amt)

        cancel_text = (
            f"🎲 <b>𝑻𝒂𝒃𝒍𝒆 𝑵𝒐. {t_id}</b>\n\n"
            f"(1). {p1_link} ❌❌\n\n"
            f"(2). {p2_link} ❌❌\n\n"
            f"<b>{int(amt)}</b> ❌ 𝗧𝗔𝗕𝗟𝗘 𝗖𝗔𝗡𝗖𝗘𝗟𝗟𝗘𝗗"
        )
        await query.edit_message_text(text=cancel_text, parse_mode="HTML")

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN missing in Render Environment!")
        return

    # Flask को बैकग्राउंड में चालू करना ताकि Render बंद न हो
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_balance))
