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
    return {"users": {}, "tables": {}, "table_counter": 1, "pinned_msg": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

db = load_data()

def is_admin(user_id):
    return user_id == ADMIN_ID

def ensure_user(user_id, name):
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {"name": name, "balance": 0}
        save_data(db)
    else:
        db["users"][uid]["name"] = name

def find_user_by_username_or_name(query):
    query = query.replace("@", "").lower()
    for uid, info in db["users"].items():
        if info.get("username", "").lower() == query or info.get("name", "").lower() == query:
            return uid, info["name"]
    return None, query

def send_balance_update(user_id, name, text_msg, new_bal, chat_id):
    msg = f"👤 **{name}**\n{text_msg}\n💳 वर्तमान बैलेंस: **{new_bal}**"
    try:
        bot.send_message(chat_id, msg, parse_mode="Markdown")
    except Exception:
        pass
    if str(chat_id) != str(user_id):
        try:
            bot.send_message(user_id, msg, parse_mode="Markdown")
        except Exception:
            pass

def update_pinned_list(chat_id):
    cid = str(chat_id)
    active_tables = [
        f"🎲 Table #{t_id}: {t['p1_name']} vs {t['p2_name']} ({t['amount']})"
        for t_id, t in db["tables"].items() if t["status"] == "active"
    ]
    if active_tables:
        list_text = "📋 **चालू टेबल्स (Active Tables):**\n\n" + "\n".join(active_tables)
    else:
        list_text = "📋 अभी कोई टेबल चालू नहीं है।"

    old_msg_id = db.get("pinned_msg", {}).get(cid)
    if old_msg_id:
        try:
            bot.edit_message_text(list_text, chat_id, old_msg_id, parse_mode="Markdown")
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

@bot.message_handler(commands=['start', 'bal', 'balance'])
def check_balance(message):
    uid = str(message.from_user.id)
    name = message.from_user.first_name
    ensure_user(uid, name)
    if message.from_user.username:
        db["users"][uid]["username"] = message.from_user.username
        save_data(db)
    bal = db["users"][uid]["balance"]
    reply_text = f"👋 Hello **{name}**!\n💳 आपका वर्तमान बैलेंस: **{bal}**"
    bot.reply_to(message, reply_text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.reply_to_message is not None and is_admin(m.from_user.id) and re.match(r'^[+-]\d+$', m.text.strip()))
def admin_update_balance(message):
    target = message.reply_to_message.from_user
    uid = str(target.id)
    name = target.first_name
    ensure_user(uid, name)
    if target.username:
        db["users"][uid]["username"] = target.username

    change = int(message.text.strip())
    db["users"][uid]["balance"] += change
    new_bal = db["users"][uid]["balance"]
    save_data(db)

    action_str = f"✅ +{change} जोड़े गए" if change > 0 else f"❌ {change} काटे गए"
    send_balance_update(uid, name, action_str, new_bal, message.chat.id)
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

@bot.message_handler(func=lambda m: True)
def handle_all_messages(message):
    uid = str(message.from_user.id)
    name = message.from_user.first_name
    ensure_user(uid, name)
    if message.from_user.username:
        db["users"][uid]["username"] = message.from_user.username
        save_data(db)

    text = message.text.strip()
    # @mention के साथ अमाउंट होने पर टेबल बनाना (जैसे: @Anil 60 या @Queen @Anil 60)
    if "@" in text and is_admin(message.from_user.id):
        numbers = re.findall(r'\b\d+\b', text)
        if not numbers:
            return
        amount = int(numbers[-1])

        mentions = []
        if message.entities:
            for ent in message.entities:
                if ent.type == "text_mention":
                    mentions.append((str(ent.user.id), ent.user.first_name))
                elif ent.type == "mention":
                    uname = text[ent.offset:ent.offset + ent.length]
                    found_id, found_name = find_user_by_username_or_name(uname)
                    mentions.append((found_id, found_name))

        if len(mentions) >= 2:
            p1_id, p1_name = mentions[0]
            p2_id, p2_name = mentions[1]
        elif len(mentions) == 1:
            p1_id, p1_name = uid, name
            p2_id, p2_name = mentions[0]
        else:
            return

        # बैलेंस चेक और कटौती (अगर यूज़र रजिस्टर है)
        for pid, pname in [(p1_id, p1_name), (p2_id, p2_name)]:
            if pid and pid in db["users"]:
                if db["users"][pid]["balance"] < amount:
                    bot.reply_to(message, f"⚠️ **{pname}** का बैलेंस कम है! (वर्तमान बैलेंस: {db['users'][pid]['balance']})", parse_mode="Markdown")
                    return

        for pid in [p1_id, p2_id]:
            if pid and pid in db["users"]:
                db["users"][pid]["balance"] -= amount

        t_no = str(db.get("table_counter", 1))
        db["table_counter"] = int(t_no) + 1

        db["tables"][t_no] = {
            "p1_id": p1_id,
            "p1_name": p1_name,
            "p2_id": p2_id,
            "p2_name": p2_name,
            "amount": amount,
            "status": "active"
        }
        save_data(db)

        table_text = (
            f"🎲 𝑻𝒂𝒃𝒍𝒆 𝑵𝒐. {t_no}\n\n"
            f"(1). {p1_name} ✅✅\n\n"
            f"(2). {p2_name}\n\n"
            f"{amount} ✅ 𝗕𝗘𝗦𝗧 ★ 𝗢𝗙 ★𝗟𝗨𝗖𝗞 🎯🎯"
        )

        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton(f"#win 🏆 ({p1_name})", callback_data=f"win1_{t_no}"),
            InlineKeyboardButton(f"#win 🏆 ({p2_name})", callback_data=f"win2_{t_no}")
        )
        markup.row(
            InlineKeyboardButton("cancel this table ❌", callback_data=f"cancel_{t_no}")
        )

        bot.send_message(message.chat.id, table_text, reply_markup=markup)

        try:
            bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass

        if message.chat.type != "private":
            update_pinned_list(message.chat.id)

@bot.callback_query_handler(func=lambda call: True)
def handle_table_buttons(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ सिर्फ Admin ही यह बटन दबा सकते हैं!", show_alert=True)
        return

    parts = call.data.split("_")
    action = parts[0]
    table_id = parts[1]
    table = db["tables"].get(table_id)

    if not table or table["status"] != "active":
        bot.answer_callback_query(call.id, "⚠️ यह टेबल पहले ही बंद हो चुकी है!", show_alert=True)
        return

    amount = table["amount"]
    p1_id, p1_name = table["p1_id"], table["p1_name"]
    p2_id, p2_name = table["p2_id"], table["p2_name"]

    profit = round(amount * 0.90, 2)
    total_win_payout = round(amount + profit, 2)
    if total_win_payout.is_integer():
        total_win_payout = int(total_win_payout)

    if action in ["win1", "win2"]:
        winner_id = p1_id if action == "win1" else p2_id
        winner_name = p1_name if action == "win1" else p2_name

        table["status"] = "completed"
        save_data(db)

        if winner_id and winner_id in db["users"]:
            db["users"][winner_id]["balance"] += total_win_payout
            save_data(db)
            new_bal = db["users"][winner_id]["balance"]
            send_balance_update(
                winner_id, winner_name,
                f"🏆 Table #{table_id} Won! (+{total_win_payout})",
                new_bal, call.message.chat.id
            )

        updated_text = call.message.text + f"\n\n🏆 **Winner:** {winner_name} (+{total_win_payout})"
        bot.edit_message_text(updated_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        bot.answer_callback_query(call.id, f"🏆 {winner_name} को विनर घोषित किया गया!")

    elif action == "cancel":
        table["status"] = "cancelled"
        for pid in [p1_id, p2_id]:
            if pid and pid in db["users"]:
                db["users"][pid]["balance"] += amount
        save_data(db)

        updated_text = call.message.text + "\n\n❌ **Table Cancelled (पैसे वापस कर दिए गए)**"
        bot.edit_message_text(updated_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        bot.answer_callback_query(call.id, "❌ टेबल कैंसिल कर दी गई!")

    if call.message.chat.type != "private":
        update_pinned_list(call.message.chat.id)

if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    bot.infinity_polling()
