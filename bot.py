import os
import time
import sqlite3
import threading
import logging
import traceback
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- 1. Render Environment Variables ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
raw_admins = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = []
for item in raw_admins.split(","):
    clean_item = item.strip()
    if clean_item.isdigit():
        ADMIN_IDS.append(int(clean_item))

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

# --- 3. SQLite Database (बैलेंस सेव रखने के लिए) ---
conn = sqlite3.connect("ludo_bot.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT, balance REAL)")
conn.commit()

def get_user_balance(user_id):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    if row is not None:
        for val in row:
            return float(val)
    return 0.0

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
        if update.message:
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
    idx = 1
    for uid, name, bal in users:
        lines.append(f"{idx}. {clickable_name(uid, name)} -- <b>₹{bal:.2f}</b>")
        idx += 1
        
    lines.append(f"\n👥 <b>Total Members: {len(users)}</b>")
    text = "\n".join(lines)
    
    keyboard = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton("💰 CHECK YOUR BALANCE", callback_data="check_bal")
    )
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
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
    amount = None
    for arg in context.args:
        try:
            amount = float(arg)
            break
        except ValueError:
            continue
    if amount is None:
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
    amount = None
    for arg in context.args:
        try:
            amount = float(arg)
            break
        except ValueError:
            continue
    if amount is None:
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

    mentioned_users = []
    if update.message.entities:
        for ent in update.message.entities:
            if ent.type == "text_mention" and ent.user:
                mentioned_users.append(ent.user)
                
    if len(mentioned_users) < 2 or not context.args:
        return

    p1 = None
    p2 = None
    for u in mentioned_users:
        if p1 is None:
            p1 = u
        elif p2 is None:
            p2 = u
            break

    amount = None
    for arg in reversed(context.args):
        try:
            amount = float(arg)
            break
        except ValueError:
            continue
    if amount is None:
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

    row1 = (InlineKeyboardButton("#win 🏆", callback_data=f"win_{t_id}_1"), InlineKeyboardButton("#win 🏆", callback_data=f"win_{t_id}_2"))
    row2 = (InlineKeyboardButton("Cancel this table ❌", callback_data=f"cancel_{t_id}"),)
    keyboard = InlineKeyboardMarkup((row1, row2))

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=table_text,
        reply_markup=keyboard,
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
    action = ""
    t_id = 0
    winner_num = 0
    step = 0
    for part in parts:
        if step == 0:
            action = part
        elif step == 1:
            t_id = int(part)
        elif step == 2:
            winner_num = int(part)
        step += 1

    table = tables.get(t_id)

    if not table or table["status"] != "active":
        await query.answer("⚠️ यह टेबल पहले ही अपडेट हो चुकी है।", show_alert=True)
        return

    p1_link = clickable_name(table["p1_id"], table["p1_name"])
    p2_link = clickable_name(table["p2_id"], table["p2_name"])
    amt = table["amount"]

    if action == "win":
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
