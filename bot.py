import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
import json
import os
import time
import threading
import re

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8783427206

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
DATA_FILE = "bot_data.json"

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"users": {}, "tables": {}, "pinned_msg": {}, "table_count": 0}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

db = load_data()

def is_admin(user_id):
    return user_id == ADMIN_ID

def delete_later(chat_id, message_ids, delay=3):
    def task():
        time.sleep(delay)
        for mid in message_ids:
            try:
                bot.delete_message(chat_id, mid)
            except Exception:
                pass
    threading.Thread(target=task).start()

def ensure_user(user_id, name, username=None):
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "name": name,
            "username": username or "",
            "balance": 0
        }
    else:
        if name:
            db["users"][uid]["name"] = name
        if username:
            db["users"][uid]["username"] = username
    save_data(db)

def find_user(query):
    clean_q = query.replace("@", "").strip().lower()
    for uid, info in db["users"].items():
        if info.get("username", "").lower() == clean_q and clean_q != "":
            return uid, info
        if info.get("name", "").lower() == clean_q:
            return uid, info
    return None, None

def get_display_tag(uid):
    info = db["users"].get(str(uid), {})
    uname = info.get("username", "")
    name = info.get("name", "Player")
    if uname:
        return f"@{uname}"
    return f"[{name}](tg://user?id={uid})"

def send_personal_update(user_id, text_msg):
    try:
        bot.send_message(int(user_id), text_msg, parse_mode="Markdown")
    except Exception:
        pass

def update_pinned_list(chat_id):
    cid = str(chat_id)
    lines = ["📊 **PLAYER BALANCE LIST** 📊\n"]
    has_users = False

    # Sort users by balance (highest to lowest)
    sorted_users = sorted(
        db["users"].items(),
        key=lambda x: x[1].get("balance", 0),
        reverse=True
    )

    for uid, info in sorted_users:
        bal = info.get("balance", 0)
        if bal != 0:
            has_users = True
            tag = get_display_tag(uid)
            status_emoji = "🟢" if bal > 0 else "🔴"
            lines.append(f"{status_emoji} {tag} : **{bal}**")

    if not has_users:
        lines.append("अभी किसी भी प्लेयर का बैलेंस नहीं है।")

    list_text = "\n".join(lines)
    old_msg_id = db.get("pinned_msg", {}).get(cid)

    if old_msg_id:
        try:
            bot.edit_message_text(
                list_text,
                chat_id=chat_id,
                message_id=old_msg_id,
                parse_mode="Markdown"
            )
            return
        except Exception:
            pass

    try:
        sent = bot.send_message(chat_id, list_text, parse_mode="Markdown")
        if "pinned_msg" not in db:
            db["pinned_msg"] = {}
        db["pinned_msg"][cid] = sent.message_id
        save_data(db)
        bot.pin_chat_message(chat_id, sent.message_id, disable_notification=True)
    except Exception:
        pass

# 1. Personal Bot /start & /balance Command
@bot.message_handler(commands=['start', 'balance', 'bal'])
def check_balance(message):
    uid = str(message.from_user.id)
    name = message.from_user.first_name
    username = message.from_user.username
    ensure_user(uid, name, username)

    bal = db["users"][uid].get("balance", 0)
    tag = f"@{username}" if username else name
    reply_text = (
        f"👋 Hello **{tag}**!\n\n"
        f"💰 आपका वर्तमान बैलेंस: **{bal}**\n"
        f"🎮 टेबल खेलने के लिए ग्रुप में एडमिन को बोलें।"
    )
    bot.reply_to(message, reply_text, parse_mode="Markdown")

# 2. Admin Add / Minus Balance (Reply to user with +100 or -100, OR type @username +100)
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and re.match(r'^(@\w+\s+)?[+-]\d+$', m.text.strip()))
def admin_update_balance(message):
    text = message.text.strip()
    target_uid = None
    target_name = None
    target_username = None

    if message.reply_to_message:
        target = message.reply_to_message.from_user
        target_uid = str(target.id)
        target_name = target.first_name
        target_username = target.username
        ensure_user(target_uid, target_name, target_username)
        amount = int(text)
    else:
        parts = text.split()
        if len(parts) == 2:
            q_user, amount_str = parts[0], parts[1]
            amount = int(amount_str)
            found_uid, info = find_user(q_user)
            if found_uid:
                target_uid = found_uid
                target_name = info["name"]
                target_username = info.get("username")
            else:
                # Create temporary entry by username if user hasn't started bot yet
                clean_u = q_user.replace("@", "")
                target_uid = f"user_{clean_u.lower()}"
                target_name = clean_u
                target_username = clean_u
                ensure_user(target_uid, target_name, target_username)

    if not target_uid:
        return

    db["users"][target_uid]["balance"] = db["users"][target_uid].get("balance", 0) + amount
    new_bal = db["users"][target_uid]["balance"]
    save_data(db)

    tag = get_display_tag(target_uid)
    action_word = "Add" if amount > 0 else "Minus"
    confirm_msg = bot.send_message(
        message.chat.id,
        f"✅ {tag} का बैलेंस **{amount:+}** ({action_word}) हुआ। नया बैलेंस: **{new_bal}**",
        parse_mode="Markdown"
    )

    # Personal Notification
    if not str(target_uid).startswith("user_"):
        send_personal_update(
            target_uid,
            f"💳 **Balance Update**\n\nबदलाव: **{amount:+}**\nनया कुल बैलेंस: **{new_bal}**"
        )

    # Update Pinned Balance List
    if message.chat.type in ["group", "supergroup"]:
        update_pinned_list(message.chat.id)
        delete_later(message.chat.id, [message.message_id, confirm_msg.message_id], delay=3)

# 3. Create Table Command (Format: @user1 @user2 100  OR reply to user1 with @user2 100)
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.chat.type in ["group", "supergroup"] and m.text and re.search(r'\d+$', m.text.strip()))
def create_table(message):
    text = message.text.strip()
    parts = text.split()

    # Ignore if it was a +100 or -100 balance command
    if re.match(r'^(@\w+\s+)?[+-]\d+$', text):
        return

    try:
        bet = int(parts[-1])
    except ValueError:
        return

    p1_uid, p2_uid = None, None

    if message.reply_to_message and len(parts) >= 2:
        u1 = message.reply_to_message.from_user
        p1_uid = str(u1.id)
        ensure_user(p1_uid, u1.first_name, u1.username)

        p2_query = parts[0]
        found_uid, _ = find_user(p2_query)
        if found_uid:
            p2_uid = found_uid
        else:
            clean_u = p2_query.replace("@", "")
            p2_uid = f"user_{clean_u.lower()}"
            ensure_user(p2_uid, clean_u, clean_u)

    elif len(parts) >= 3:
        p1_query, p2_query = parts[0], parts[1]

        found1, _ = find_user(p1_query)
        if found1:
            p1_uid = found1
        else:
            c1 = p1_query.replace("@", "")
            p1_uid = f"user_{c1.lower()}"
            ensure_user(p1_uid, c1, c1)

        found2, _ = find_user(p2_query)
        if found2:
            p2_uid = found2
        else:
            c2 = p2_query.replace("@", "")
            p2_uid = f"user_{c2.lower()}"
            ensure_user(p2_uid, c2, c2)
    else:
        return

    # Deduct bet from both players
    db["users"][p1_uid]["balance"] = db["users"][p1_uid].get("balance", 0) - bet
    db["users"][p2_uid]["balance"] = db["users"][p2_uid].get("balance", 0) - bet

    db["table_count"] = db.get("table_count", 0) + 1
    t_id = str(db["table_count"])

    p1_tag = get_display_tag(p1_uid)
    p2_tag = get_display_tag(p2_uid)

    db["tables"][t_id] = {
        "p1_uid": p1_uid,
        "p2_uid": p2_uid,
        "bet": bet,
        "status": "active"
    }
    save_data(db)

    table_text = (
        f"🎲 **Table No. {t_id}**\n\n"
        f"(1). {p1_tag}\n"
        f"(2). {p2_tag}\n\n"
        f"💰 **{bet}** ✅ **BEST ★ OF ★ LUCK**"
    )

    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("win1 🏆", callback_data=f"w1_{t_id}"),
        InlineKeyboardButton("win2 🏆", callback_data=f"w2_{t_id}")
    )
    markup.row(
        InlineKeyboardButton("cancel ❌", callback_data=f"cn_{t_id}")
    )

    bot.send_message(message.chat.id, table_text, reply_markup=markup, parse_mode="Markdown")

    # Update pinned list & delete admin's command message (Keep the table message!)
    update_pinned_list(message.chat.id)
    delete_later(message.chat.id, [message.message_id], delay=2)

# 4. Handle Table Buttons (win1, win2, cancel)
@bot.callback_query_handler(func=lambda call: call.data.startswith(("w1_", "w2_", "cn_")))
def handle_table_buttons(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ सिर्फ़ एडमिन ही बटन दबा सकता है!", show_alert=True)
        return

    action, t_id = call.data.split("_")
    table = db.get("tables", {}).get(t_id)

    if not table or table.get("status")
