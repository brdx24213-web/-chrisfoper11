import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
import json, os, time, threading, urllib.request

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8783427206

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
DATA_FILE = "bot_data.json"

@app.route('/')
def home():
    return "Bot is running 24/7!"

def keep_alive():
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

def esc(text):
    if not text:
        return ""
    s = str(text)
    for c in ('_', '*', '`', '['):
        s = s.replace(c, '\\' + c)
    return s

def del_msg(chat_id, mids, delay=5):
    def task():
        time.sleep(delay)
        for m in mids:
            try:
                bot.delete_message(chat_id, m)
            except Exception:
                pass
    threading.Thread(target=task, daemon=True).start()

def ensure_user(uid, name, uname=""):
    uid = str(uid)
    users = db.setdefault("users", {})
    if uid not in users:
        users[uid] = {"name": name or "Player", "username": uname or "", "balance": 0, "hist": ""}
    else:
        if name:
            users[uid]["name"] = name
        if uname:
            users[uid]["username"] = uname
    save_data(db)

def find_user(q):
    q = q.replace("@", "").strip().lower()
    users = db.get("users", {})
    if q in users:
        return q
    for uid, info in users.items():
        if info.get("username", "").lower() == q or info.get("name", "").lower() == q:
            return uid
    return None

def get_tag(uid):
    info = db.get("users", {}).get(str(uid), {})
    u = info.get("username", "")
    n = info.get("name", "Player")
    return f"@{esc(u)}" if u else f"[{esc(n)}](tg://user?id={uid})"

def send_pm(uid, text):
    if str(uid).startswith("user_"):
        return
    try:
        bot.send_message(int(uid), text, parse_mode="Markdown")
    except Exception:
        pass

def update_pin(chat_id, force=False):
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
    txt = "\n".join(lines)
    old_id = db.get("pinned_msg", {}).get(cid)
    if old_id and not force:
        try:
            bot.edit_message_text(txt, chat_id=chat_id, message_id=old_id, parse_mode="Markdown")
            return
        except Exception:
            pass
    try:
        sent = bot.send_message(chat_id, txt, parse_mode="Markdown")
        db.setdefault("pinned_msg", {})[cid] = sent.message_id
        save_data(db)
        bot.pin_chat_message(chat_id, sent.message_id, disable_notification=True)
    except Exception:
        pass

@bot.message_handler(commands=['start', 'bal', 'balance'])
def cmd_bal(m):
    uid = str(m.from_user.id)
    uname = m.from_user.username
    ensure_user(uid, m.from_user.first_name, uname)
    if uname:
        tid = f"user_{uname.lower()}"
        if tid in db["users"]:
            db["users"][uid]["balance"] += db["users"][tid].get("balance", 0)
            db["users"][uid]["hist"] = db["users"][tid].get("hist", "")
            del db["users"][tid]
            save_data(db)
    bal = db["users"][uid].get("balance", 0)
    tag = get_tag(uid)
    if m.chat.type == "private":
        bot.reply_to(m, f"👋 नमस्ते {tag}!\n\n💰 आपका वर्तमान बैलेंस: *₹{bal}*", parse_mode="Markdown")
    else:
        msg = bot.send_message(m.chat.id, f"💰 {tag} का बैलेंस: *₹{bal}*", parse_mode="Markdown")
        del_msg(m.chat.id, (m.message_id, msg.message_id), 6)

@bot.message_handler(commands=['list'])
def cmd_list(m):
    if is_admin(m.from_user.id) and m.chat.type in ["group", "supergroup"]:
        update_pin(m.chat.id, True)
        del_msg(m.chat.id, (m.message_id,), 2)

@bot.message_handler(commands=['add', 'minus'])
def cmd_add_minus(m):
    if not is_admin(m.from_user.id):
        return
    parts = m.text.split()
    cmd = parts.pop(0).lower()
    is_min = "minus" in cmd
    t_uid = None
    amt = 0
    if m.reply_to_message and len(parts) >= 1:
        t = m.reply_to_message.from_user
        t_uid = str(t.id)
        ensure_user(t_uid, t.first_name, t.username)
        try:
            amt = abs(int(parts.pop(0)))
        except Exception:
            return
    elif len(parts) >= 2:
        uq = parts.pop(0)
        try:
            amt = abs(int(parts.pop(0)))
        except Exception:
            return
        fid = find_user(uq)
        if fid:
            t_uid = fid
        else:
            cu = uq.replace("@", "")
            t_uid = f"user_{cu.lower()}"
            ensure_user(t_uid, cu, cu)
    else:
        return
    if is_min:
        amt = -amt
    db["users"][t_uid]["balance"] = db["users"][t_uid].get("balance", 0) + amt
    nb = db["users"][t_uid]["balance"]
    db["users"][t_uid]["hist"] = f"{nb}" if nb != 0 else ""
    save_data(db)
    tag = get_tag(t_uid)
    st = f"+{amt}" if amt > 0 else f"{amt}"
    cm = bot.send_message(m.chat.id, f"✅ {tag} ({st}) | कुल: *₹{nb}*", parse_mode="Markdown")
    send_pm(t_uid, f"💳 *Balance Updated!*\n\nबदलाव: `{st}`\nनया बैलेंस: *₹{nb}*")
    if m.chat.type in ["group", "supergroup"]:
        update_pin(m.chat.id)
        del_msg(m.chat.id, (m.message_id, cm.message_id), 4)

@bot.message_handler(func=lambda m: m.text and is_admin(m.from_user.id) and not m.text.startswith('/'))
def create_table(m):
    parts = m.text.strip().split()
    bet = 0
    bef, aft, found = [], [], False
    for p in parts:
        if not found and p.isdigit() and int(p) > 0:
            bet = int(p)
            found = True
        elif not found:
            bef.append(p)
        else:
            aft.append(p)
    if not found or bet <= 0:
        return
    extra = " ".join(aft)
    p1, p2 = None, None
    if m.reply_to_message and len(bef) >= 1:
        u1 = m.reply_to_message.from_user
        p1 = str(u1.id)
        ensure_user(p1, u1.first_name, u1.username)
        q2 = bef.pop(0)
        p2 = find_user(q2) or f"user_{q2.replace('@', '').lower()}"
        if p2.startswith("user_"):
            ensure_user(p2, q2.replace("@", ""), q2.replace("@", ""))
    elif len(bef) >= 2:
        q1, q2 = bef.pop(0), bef.pop(0)
        p1 = find_user(q1) or f"user_{q1.replace('@', '').lower()}"
        if p1.startswith("user_"):
            ensure_user(p1, q1.replace("@", ""), q1.replace("@", ""))
        p2 = find_user(q2) or f"user_{q2.replace('@', '').lower()}"
        if p2.startswith("user_"):
            ensure_user(p2, q2.replace("@", ""), q2.replace("@", ""))
    else:
        return
    db["table_count"] = db.get("table_count", 0) + 1
    tid = str(db["table_count"])
    db["tables"][tid] = {"p1": p1, "p2": p2, "bet": bet, "extra": extra, "status": "active"}
    save_data(db)
    ep = f" ({esc(extra)})" if extra else ""
    txt = f"🎲 *Table No. {tid}*\n\n(1). {get_tag(p1)}\n(2). {get_tag(p2)}\n\n*{bet}* ✅ *BEST ★ OF ★ LUCK* 🎯🎯{ep}"
    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton("#win 🏆", callback_data=f"w1_{tid}"), InlineKeyboardButton("#win 🏆", callback_data=f"w2_{tid}"))
    mk.row(InlineKeyboardButton("cancel this table ❌", callback_data=f"cancel_{tid}"))
    bot.send_message(m.chat.id, txt, reply_markup=mk, parse_mode="Markdown")
    del_msg(m.chat.id, (m.message_id,), 2)

@bot.callback_query_handler(func=lambda c: c.data.startswith(("w1_", "w2_", "cancel_")))
def handle_btn(c):
    if not is_admin(c.from_user.id):
        bot.answer_callback_query(c.id, "❌ सिर्फ़ एडमिन ही दबा सकते हैं!", show_alert=True)
        return
    act, tid = c.data.split("_")
    tb = db.get("tables", {}).get(tid)
    if not tb or tb.get("status") != "active":
        bot.answer_callback_query(c.id, "⚠️ यह टेबल बंद हो चुकी है!", show_alert=True)
        return
    p1, p2, bet = tb["p1"], tb["p2"], tb["bet"]
    ep = f" ({esc(tb.get('extra', ''))})" if tb.get("extra") else ""
    prof = int(bet * 0.90)
    if act == "w1":
        ob = db["users"][p1].get("balance", 0)
        db["users"][p1]["balance"] = ob + prof
        db["users"][p2]["balance"] = db["users"][p2].get("balance", 0) - bet
        db["users"][p1]["hist"] = f"{ob}+{prof}" if ob > 0 else f"{bet}+{prof}"
        db["users"][p2]["hist"] = f"{db['users'][p2]['balance']}"
        tb["status"] = "win1"
        nt = f"🎲 *Table No. {tid}*\n\n(1). {get_tag(p1)} ✅\n(2). {get_tag(p2)}\n\n*{bet}* ✅ *BEST ★ OF ★ LUCK* 🎯🎯{ep}"
        send_pm(p1, f"🏆 बधाई हो! आप Table No. {tid} जीत गए हैं।\n💰 हिसाब: *{bet}+{prof}* (नया बैलेंस: *₹{db['users'][p1]['balance']}*)")
        send_pm(p2, f"❌ आप Table No. {tid} हार गए हैं।\n💰 नया बैलेंस: *₹{db['users'][p2]['balance']}*")
    elif act == "w2":
        ob = db["users"][p2].get("balance", 0)
        db["users"][p2]["balance"] = ob + prof
        db["users"][p1]["balance"] = db["users"][p1].get("balance", 0) - bet
        db["users"][p2]["hist"] = f"{ob}+{prof}" if ob > 0 else f"{bet}+{prof}"
