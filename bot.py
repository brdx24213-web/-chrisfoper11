import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
import json, os, time, threading, re

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8783427206

if not BOT_TOKEN:
    raise ValueError("ERROR: Render ke Environment Variables mein BOT_TOKEN nahi dala gaya hai!")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
DATA_FILE = "bot_data.json"

@app.route('/')
def home():
    return "Bot is alive and running!"

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

def is_admin(uid):
    return uid == ADMIN_ID

def escape_md(text):
    if not text:
        return ""
    for ch in ['_', '*', '`', '[']:
        text = str(text).replace(ch, f'\\{ch}')
    return text

def delete_later(chat_id, msg_ids, delay=10):
    def task():
        time.sleep(delay)
        for mid in msg_ids:
            try:
                bot.delete_message(chat_id, mid)
            except Exception:
                pass
    t = threading.Thread(target=task)
    t.daemon = True
    t.start()

def ensure_user(uid, name, username=""):
    uid = str(uid)
    if uid not in db["users"]:
        db["users"][uid] = {"name": name or "Player", "username": username or "", "balance": 0}
    else:
        if name:
            db["users"][uid]["name"] = name
        if username:
            db["users"][uid]["username"] = username
    save_data(db)

def find_user(query):
    q = query.replace("@", "").strip().lower()
    if q in db["users"]:
        return q, db["users"][q]
    for uid, info in db["users"].items():
        if info.get("username", "").lower() == q:
            return uid, info
        if info.get("name", "").lower() == q:
            return uid, info
    return None, None

def get_tag(uid):
    info = db["users"].get(str(uid), {})
    uname = info.get("username", "")
    name = info.get("name", "Player")
    return f"@{escape_md(uname)}" if uname else f"[{escape_md(name)}](tg://user?id={uid})"

def send_pm(uid, text):
    if str(uid).startswith("user_"):
        return
    try:
        bot.send_message(int(uid), text, parse_mode="Markdown")
    except Exception:
        pass

def update_pinned_list(chat_id):
    cid = str(chat_id)
    lines = ["📊 *PLAYER BALANCE LIST*\n"]
    sorted_u = sorted(db["users"].items(), key=lambda x: x[1].get("balance", 0), reverse=True)
    for uid, info in sorted_u:
        bal = info.get("balance", 0)
        if bal != 0:
            icon = "🟢" if bal > 0 else "🔴"
            lines.append(f"{icon} {get_tag(uid)} : ₹{bal}")
    if len(lines) == 1:
        lines.append("अभी किसी भी प्लेयर का बैलेंस नहीं है।")
    list_text = "\n".join(lines)
    old_id = db.get("pinned_msg", {}).get(cid)
    if old_id:
        try:
            bot.edit_message_text(list_text, chat_id=chat_id, message_id=old_id, parse_mode="Markdown")
            return
        except Exception:
            pass
    try:
        sent = bot.send_message(chat_id, list_text, parse_mode="Markdown")
        db.setdefault("pinned_msg", {})[cid] = sent.message_id
        save_data(db)
        bot.pin_chat_message(chat_id, sent.message_id)
    except Exception:
        pass

@bot.message_handler(commands=['start', 'bal', 'balance'])
def check_balance(message):
    uid = str(message.from_user.id)
    name = message.from_user.first_name
    uname = message.from_user.username
    ensure_user(uid, name, uname)
    if uname:
        tid = f"user_{uname.lower()}"
        if tid in db["users"]:
            db["users"][uid]["balance"] += db["users"][tid].get("balance", 0)
            del db["users"][tid]
            save_data(db)
    bal = db["users"][uid].get("balance", 0)
    tag = f"@{escape_md(uname)}" if uname else escape_md(name)
    txt = f"👋 Hello *{tag}*!\n\n💰 आपका वर्तमान बैलेंस: *₹{bal}*"
    bot.reply_to(message, txt, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and is_admin(m.from_user.id) and re.match(r'^(@\w+\s+)?[+-]\d+$', m.text.strip()))
def admin_update_balance(message):
    text = message.text.strip()
    target_uid = None
    amount = 0
    if message.reply_to_message:
        t = message.reply_to_message.from_user
        target_uid = str(t.id)
        ensure_user(target_uid, t.first_name, t.username)
        amount = int(text)
    else:
        parts = text.split()
        if len(parts) == 2:
            amount = int(parts[1])
            f_id, _ = find_user(parts[0])
            if f_id:
                target_uid = f_id
            else:
                cu = parts[0].replace("@", "")
                target_uid = f"user_{cu.lower()}"
                ensure_user(target_uid, cu, cu)
    if not target_uid:
        return
    db["users"][target_uid]["balance"] += amount
    nb = db["users"][target_uid]["balance"]
    save_data(db)
    tag = get_tag(target_uid)
    c_msg = bot.send_message(message.chat.id, f"✅ {tag} का बैलेंस अपडेट हो गया!\n💰 नया बैलेंस: *₹{nb}*", parse_mode="Markdown")
    send_pm(target_uid, f"💳 *Balance Updated!*\n\nबदलाव: `{amount:+d}`\nनया बैलेंस: *₹{nb}*")
    if message.chat.type in ["group", "supergroup"]:
        update_pinned_list(message.chat.id)
        delete_later(message.chat.id, [message.message_id, c_msg.message_id])

@bot.message_handler(func=lambda m: m.text and is_admin(m.from_user.id))
def create_table(message):
    text = message.text.strip()
    if re.match(r'^(@\w+\s+)?[+-]\d+$', text):
        return
    parts = text.split()
    try:
        bet = int(parts[-1])
        if bet <= 0:
            return
    except ValueError:
        return
    p1_uid, p2_uid = None, None
    if message.reply_to_message and len(parts) == 2:
        u1 = message.reply_to_message.from_user
        p1_uid = str(u1.id)
        ensure_user(p1_uid, u1.first_name, u1.username)
        f2, _ = find_user(parts[0])
        if f2:
            p2_uid = f2
        else:
            cu = parts[0].replace("@", "")
            p2_uid = f"user_{cu.lower()}"
            ensure_user(p2_uid, cu, cu)
    elif len(parts) >= 3:
        for idx, q in enumerate([parts[0], parts[1]]):
            f_id, _ = find_user(q)
            if not f_id:
                cu = q.replace("@", "")
                f_id = f"user_{cu.lower()}"
                ensure_user(f_id, cu, cu)
            if idx == 0:
                p1_uid = f_id
            else:
                p2_uid = f_id
    else:
        return
    db["users"][p1_uid]["balance"] = db["users"][p1_uid].get("balance", 0) - bet
    db["users"][p2_uid]["balance"] = db["users"][p2_uid].get("balance", 0) - bet
    db["table_count"] = db.get("table_count", 0) + 1
    t_id = str(db["table_count"])
    db["tables"][t_id] = {"p1_uid": p1_uid, "p2_uid": p2_uid, "bet": bet, "status": "active"}
    save_data(db)
    t_text = f"🎲 *Table No. {t_id}*\n\n(1). {get_tag(p1_uid)}\n(2). {get_tag(p2_uid)}\n\n💰 Bet: *₹{bet}*"
    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton("win1 🏆", callback_data=f"w1_{t_id}"), InlineKeyboardButton("win2 🏆", callback_data=f"w2_{t_id}"))
    mk.row(InlineKeyboardButton("cancel ❌", callback_data=f"cancel_{t_id}"))
    bot.send_message(message.chat.id, t_text, reply_markup=mk, parse_mode="Markdown")
    update_pinned_list(message.chat.id)
    delete_later(message.chat.id, [message.message_id])

@bot.callback_query_handler(func=lambda call: call.data.startswith(("w1_", "w2_", "cancel_")))
def handle_table_buttons(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ सिर्फ़ एडमिन ही इसे दबा सकते हैं!", show_alert=True)
        return
    action, t_id = call.data.split("_")
    table = db.get("tables", {}).get(t_id)
    if not table or table.get("status") != "active":
        bot.answer_callback_query(call.id, "⚠️ यह टेबल पहले ही बंद हो चुकी है!", show_alert=True)
        return
    p1, p2, bet = table["p1_uid"], table["p2_uid"], table["bet"]
    profit = int(bet * 0.90)
    win_amt = bet + profit
    if action == "w1":
        db["users"][p1]["balance"] = db["users"][p1].get("balance", 0) + win_amt
        table["status"] = "win1"
        nt = f"🎲 *Table No. {t_id}*\n\n(1). {get_tag(p1)} 🏆 (Winner)\n(2). {get_tag(p2)}\n\n💰 Win Amount: *₹{win_amt}*"
        send_pm(p1, f"🏆 बधाई हो! आप Table #{t_id} जीत गए हैं।\n💰 आपको *₹{win_amt}* मिले हैं।")
    elif action == "w2":
        db["users"][p2]["balance"] = db["users"][p2].get("balance", 0) + win_amt
        table["status"] = "win2"
        nt = f"🎲 *Table No. {t_id}*\n\n(1). {get_tag(p1)}\n(2). {get_tag(p2)} 🏆 (Winner)\n\n💰 Win Amount: *₹{win_amt}*"
        send_pm(p2, f"🏆 बधाई हो! आप Table #{t_id} जीत गए हैं।\n💰 आपको *₹{win_amt}* मिले हैं।")
    else:
        db["users"][p1]["balance"] = db["users"][p1].get("balance", 0) + bet
        db["users"][p2]["balance"] = db["users"][p2].get("balance", 0) + bet
        table["status"] = "cancelled"
        nt = f"❌ *Table No. {t_id}*\n\nयह टेबल कैंसिल कर दी गई है और दोनों प्लेयर्स का बैलेंस वापस कर दिया गया है।"
    save_data(db)
    bot.edit_message_text(nt, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown")
    update_pinned_list(call.message.chat.id)
    bot.answer_callback_query(call.id, "✅ अपडेट हो गया!")

@bot.message_handler(func=lambda m: True)
def register_user(message):
    if message.from_user and not message.from_user.is_bot:
        uid = str(message.from_user.id)
        uname = message.from_user.username
        if uname and f"user_{uname.lower()}" in db["users"]:
            tid = f"user_{uname.lower()}"
            tb = db["users"][tid].get("balance", 0)
            ensure_user(uid, message.from_user.first_name, uname)
            db["users"][uid]["balance"] += tb
