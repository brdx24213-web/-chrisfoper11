import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
import json, os, time, threading, urllib.request

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8783427206

if not BOT_TOKEN:
    print("ERROR: Render ke Environment Variables mein BOT_TOKEN nahi mila!")
    time.sleep(60)

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
DATA_FILE = "bot_data.json"

@app.route('/')
def home():
    return "Bot is alive and running 24/7!"

def keep_alive_ping():
    url = os.environ.get("RENDER_EXTERNAL_URL", "https://onrender.com")
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen(url, timeout=10)
        except Exception:
            pass

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
    s = str(text)
    for ch in ('_', '*', '`', '['):
        s = s.replace(ch, '\\' + ch)
    return s

def delete_later(chat_id, msg_ids, delay=5):
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
    users = db.get("users", {})
    if uid not in users:
        users[uid] = {"name": name or "Player", "username": username or "", "balance": 0, "hist": ""}
    else:
        if name:
            users[uid]["name"] = name
        if username:
            users[uid]["username"] = username
    db["users"] = users
    save_data(db)

def find_user(query):
    q = query.replace("@", "").strip().lower()
    users = db.get("users", {})
    if q in users:
        return q, users.get(q)
    for uid, info in users.items():
        if info.get("username", "").lower() == q:
            return uid, info
        if info.get("name", "").lower() == q:
            return uid, info
    return None, None

def get_tag(uid):
    info = db.get("users", {}).get(str(uid), {})
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

def update_pinned_list(chat_id, force_new=False):
    cid = str(chat_id)
    lines = ["📊 *PLAYER BALANCE LIST*\n"]
    sorted_u = sorted(db.get("users", {}).items(), key=lambda x: x.get("balance", 0), reverse=True)
    for uid, info in sorted_u:
        bal = info.get("balance", 0)
        hist = info.get("hist", "")
        if bal != 0:
            icon = "🟢" if bal > 0 else "🔴"
            disp = hist if hist else f"{bal}"
            lines.append(f"{icon} {get_tag(uid)} : {disp}")
    if len(lines) == 1:
        lines.append("अभी किसी भी प्लेयर का बैलेंस नहीं है।")
    list_text = "\n".join(lines)
    
    old_id = db.get("pinned_msg", {}).get(cid)
    if old_id and not force_new:
        try:
            bot.edit_message_text(list_text, chat_id=chat_id, message_id=old_id, parse_mode="Markdown")
            return
        except Exception:
            pass
    try:
        sent = bot.send_message(chat_id, list_text, parse_mode="Markdown")
        db.setdefault("pinned_msg", {})[cid] = sent.message_id
        save_data(db)
        bot.pin_chat_message(chat_id, sent.message_id, disable_notification=True)
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
            db["users"][uid]["hist"] = db["users"][tid].get("hist", "")
            del db["users"][tid]
            save_data(db)
    bal = db["users"][uid].get("balance", 0)
    tag = get_tag(uid)
    if message.chat.type == "private":
        txt = f"👋 नमस्ते {tag}!\n\n💰 आपका वर्तमान बैलेंस: *₹{bal}*\n\nअब आपको सभी गेम और बैलेंस के अपडेट यहाँ पर्सनल में मिलेंगे।"
        bot.reply_to(message, txt, parse_mode="Markdown")
    else:
        txt = f"💰 {tag} का बैलेंस: *₹{bal}*"
        msg = bot.send_message(message.chat.id, txt, parse_mode="Markdown")
        delete_later(message.chat.id, (message.message_id, msg.message_id), delay=6)

@bot.message_handler(commands=['list'])
def cmd_list(message):
    if not is_admin(message.from_user.id):
        return
    if message.chat.type in ["group", "supergroup"]:
        update_pinned_list(message.chat.id, force_new=True)
        delete_later(message.chat.id, (message.message_id,), delay=2)

@bot.message_handler(commands=['add', 'minus'])
def cmd_add_minus(message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    cmd = parts.pop(0).lower()
    is_minus = "minus" in cmd
    target_uid = None
    amount = 0

    if message.reply_to_message and len(parts) >= 1:
        t = message.reply_to_message.from_user
        target_uid = str(t.id)
        ensure_user(target_uid, t.first_name, t.username)
        try:
            amount = abs(int(parts.pop(0)))
        except Exception:
            return
    elif len(parts) >= 2:
        u_query = parts.pop(0)
        try:
            amount = abs(int(parts.pop(0)))
        except Exception:
            return
        f_id, _ = find_user(u_query)
        if f_id:
            target_uid = f_id
        else:
            cu = u_query.replace("@", "")
            target_uid = f"user_{cu.lower()}"
            ensure_user(target_uid, cu, cu)
    else:
        return

    if is_minus:
        amount = -amount

    db["users"][target_uid]["balance"] = db["users"][target_uid].get("balance", 0) + amount
    nb = db["users"][target_uid]["balance"]
    db["users"][target_uid]["hist"] = f"{nb}" if nb != 0 else ""
    save_data(db)

    tag = get_tag(target_uid)
    sign_txt = f"+{amount}" if amount > 0 else f"{amount}"
    c_msg = bot.send_message(message.chat.id, f"✅ {tag} ({sign_txt}) | कुल: *₹{nb}*", parse_mode="Markdown")
    send_pm(target_uid, f"💳 *Balance Updated!*\n\nबदलाव: `{sign_txt}`\nनया बैलेंस: *₹{nb}*")

    if message.chat.type in ["group", "supergroup"]:
        update_pinned_list(message.chat.id)
        delete_later(message.chat.id, (message.message_id, c_msg.message_id), delay=4)

@bot.message_handler(func=lambda m: m.text and is_admin(m.from_user.id) and not m.text.startswith('/'))
def create_table(message):
    parts = message.text.strip().split()
    bet = 0
    before_parts = []
    after_parts = []
    found_bet = False

    for p in parts:
        if not found_bet and p.isdigit() and int(p) > 0:
            bet = int(p)
            found_bet = True
        elif not found_bet:
            before_parts.append(p)
        else:
            after_parts.append(p)

    if not found_bet or bet <= 0:
        return

    extra_msg = " ".join(after_parts)
    p1_uid, p2_uid = None, None

    if message.reply_to_message and len(before_parts) >= 1:
        u1 = message.reply_to_message.from_user
        p1_uid = str(u1.id)
        ensure_user(p1_uid, u1.first_name, u1.username)
        q2 = before_parts.pop(0)
        f2, _ = find_user(q2)
        if not f2:
            cu = q2.replace("@", "")
            f2 = f"user_{cu.lower()}"
            ensure_user(f2, cu, cu)
        p2_uid = f2
    elif len(before_parts) >= 2:
        q1 = before_parts.pop(0)
        q2 = before_parts.pop(0)
        f1, _ = find_user(q1)
        if not f1:
            cu1 = q1.replace("@", "")
            f1 = f"user_{cu1.lower()}"
            ensure_user(f1, cu1, cu1)
        p1_uid = f1

        f2, _ = find_user(q2)
        if not f2:
            cu2 = q2.replace("@", "")
            f2 = f"user_{cu2.lower()}"
            ensure_user(f2, cu2, cu2)
        p2_uid = f2
    else:
        return

    db["table_count"] = db.get("table_count", 0) + 1
    t_id = str(db["table_count"])
    db["tables"][t_id] = {
        "p1_uid": p1_uid,
        "p2_uid": p2_uid,
        "bet": bet,
        "extra": extra_msg,
        "status": "active"
    }
    save_data(db)

    extra_part = f" ({escape_md(extra_msg)})" if extra_msg else ""
    t_text = (
        f"🎲 *Table No. {t_id}*\n\n"
        f"(1). {get_tag(p1_uid)}\n"
        f"(2). {get_tag(p2_uid)}\n\n"
        f"*{bet}* ✅ *BEST ★ OF ★ LUCK* 🎯🎯{extra_part}"
    )

    mk = InlineKeyboardMarkup()
    mk.row(
        InlineKeyboardButton("#win 🏆", callback_data=f"w1_{t_id}"),
        InlineKeyboardButton("#win 🏆", callback_data=f"w2_{t_id}")
    )
    mk.row(InlineKeyboardButton("cancel this table ❌", callback_data=f"cancel_{t_id}"))

    bot.send_message(message.chat.id, t_text, reply_markup=mk, parse_mode="Markdown")
    delete_later(message.chat.id, (message.message_id,), delay=2)

@bot.callback_query_handler(func=lambda call: call.data.startswith(("w1_", "w2_", "cancel_")))
def handle_table_buttons(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ सिर्फ़ एडमिन ही इसे दबा सकते हैं!", show_alert=True)
        return

    action, t_id = call.data.split("_")
    table = db.get("tables", {}).get(t_id)
    if not table or table.get("status") != "active":
