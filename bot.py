import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import json
import os
import time
import threading

# यहाँ अपना BotFather वाला टोकन और अपनी Telegram User ID (Admin) डालें
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMIN_IDS = [123456789]  # अपनी Telegram Numeric ID यहाँ लिखें

bot = telebot.TeleBot(BOT_TOKEN)
DATA_FILE = "bot_data.json"

# डेटा लोड और सेव करने के लिए
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"users": {}, "tables": {}, "table_counter": 1, "pinned_msg_id": None, "group_id": None}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

db = load_data()

def is_admin(user_id):
    return user_id in ADMIN_IDS

# फालतू कमांड मैसेज को तुरंत डिलीट करने के लिए
def delete_msg_safe(chat_id, message_id, delay=0):
    def _del():
        if delay > 0:
            time.sleep(delay)
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
    threading.Thread(target=_del).start()

# पर्सनल (DM) और ग्रुप में बैलेंस अपडेट भेजने का फंक्शन
def send_balance_update(user_id, name, change_text, new_bal, group_id=None):
    msg = (
        f"💰 <b>Balance Update</b>\n"
        f"👤 Player: {name}\n"
        f"📊 Update: {change_text}\n"
        f"💳 Current Balance: <b>{new_bal}</b>"
    )
    # पर्सनल में भेजें
    try:
        bot.send_message(user_id, msg, parse_mode="HTML")
    except Exception:
        pass
    # ग्रुप में भी अपडेट दें (और 10 सेकंड बाद डिलीट करें ताकि चैट साफ रहे)
    if group_id:
        try:
            sent = bot.send_message(group_id, msg, parse_mode="HTML")
            delete_msg_safe(group_id, sent.message_id, delay=10)
        except Exception:
            pass

# पिन की गई लिस्ट को अपडेट करने का फंक्शन
def update_pinned_list(chat_id):
    text = "📋 <b>ACTIVE PLAYERS & BALANCE LIST</b> 📋\n\n"
    if not db["users"]:
        text += "No players added yet."
    else:
        for uid, info in db["users"].items():
            text += f"• {info['name']} : <b>{info['balance']}</b>\n"
    
    try:
        if db.get("pinned_msg_id") and db.get("group_id") == chat_id:
            bot.edit_message_text(text, chat_id, db["pinned_msg_id"], parse_mode="HTML")
        else:
            sent = bot.send_message(chat_id, text, parse_mode="HTML")
            bot.pin_chat_message(chat_id, sent.message_id, disable_notification=True)
            db["pinned_msg_id"] = sent.message_id
            db["group_id"] = chat_id
            save_data(db)
    except Exception:
        pass

# /start कमांड (ताकि यूजर पर्सनल में अपना बैलेंस देख सके और बॉट से जुड़ सके)
@bot.message_handler(commands=['start', 'balance', 'bal'])
def start_cmd(message):
    uid = str(message.from_user.id)
    name = message.from_user.first_name
    if uid not in db["users"]:
        db["users"][uid] = {"name": name, "balance": 0}
        save_data(db)
    else:
        db["users"][uid]["name"] = name
        save_data(db)
    
    bal = db["users"][uid]["balance"]
    bot.send_message(
        message.chat.id,
        f"👋 Hello <b>{name}</b>!\n💳 आपका वर्तमान बैलेंस: <b>{bal}</b>\n\n<i>(नोट: पर्सनल अपडेट पाने के लिए इस बॉट को स्टार्ट रखें।)</i>",
        parse_mode="HTML"
    )
    if message.chat.type != "private":
        delete_msg_safe(message.chat.id, message.message_id, delay=2)

# /add कमांड (यूजर के मैसेज पर रिप्लाई करके या ID देकर)
@bot.message_handler(commands=['add'])
def add_balance(message):
    delete_msg_safe(message.chat.id, message.message_id)
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    target_id = None
    target_name = None
    amount = 0

    try:
        if message.reply_to_message:
            target_id = str(message.reply_to_message.from_user.id)
            target_name = message.reply_to_message.from_user.first_name
            amount = float(args[1])
        elif len(args) >= 3:
            target_id = str(args[1])
            target_name = db["users"].get(target_id, {}).get("name", f"User_{target_id}")
            amount = float(args[2])
        else:
            return
    except Exception:
        return

    if target_id not in db["users"]:
        db["users"][target_id] = {"name": target_name, "balance": 0}

    db["users"][target_id]["name"] = target_name
    db["users"][target_id]["balance"] = round(db["users"][target_id]["balance"] + amount, 2)
    save_data(db)

    send_balance_update(target_id, target_name, f"+{amount} Added ✅", db["users"][target_id]["balance"], message.chat.id)
    if message.chat.type != "private":
        update_pinned_list(message.chat.id)

# /minus कमांड
@bot.message_handler(commands=['minus'])
def minus_balance(message):
    delete_msg_safe(message.chat.id, message.message_id)
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    target_id = None
    target_name = None
    amount = 0

    try:
        if message.reply_to_message:
            target_id = str(message.reply_to_message.from_user.id)
            target_name = message.reply_to_message.from_user.first_name
            amount = float(args[1])
        elif len(args) >= 3:
            target_id = str(args[1])
            target_name = db["users"].get(target_id, {}).get("name", f"User_{target_id}")
            amount = float(args[2])
        else:
            return
    except Exception:
        return

    if target_id not in db["users"]:
        db["users"][target_id] = {"name": target_name, "balance": 0}

    db["users"][target_id]["balance"] = round(db["users"][target_id]["balance"] - amount, 2)
    save_data(db)

    send_balance_update(target_id, target_name, f"-{amount} Deducted ❌", db["users"][target_id]["balance"], message.chat.id)
    if message.chat.type != "private":
        update_pinned_list(message.chat.id)

# /list और /pin कमांड
@bot.message_handler(commands=['list', 'pin'])
def list_and_pin(message):
    delete_msg_safe(message.chat.id, message.message_id)
    if not is_admin(message.from_user.id):
        return
    if message.chat.type != "private":
        db["pinned_msg_id"] = None # नया पिन बनाने के लिए रीसेट
        update_pinned_list(message.chat.id)

# टेबल लगाने का कमांड: /table <Amount> (Player 1 के मैसेज पर रिप्लाई करके, या नाम लिखकर)
# तरीका 1: किसी यूजर के मैसेज पर रिप्लाई करें: /table 100 @Anil
# तरीका 2: /table 100 Queen Anil
@bot.message_handler(commands=['table', 't'])
def create_table(message):
    delete_msg_safe(message.chat.id, message.message_id) # कमांड मैसेज डिलीट होगा, टेबल नहीं
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        return

    try:
        amount = float(args[1])
        if amount.is_integer():
            amount = int(amount)
    except ValueError:
        return

    p1_id, p1_name = None, "Player 1"
    p2_id, p2_name = None, "Player 2"

    # यदि एडमिन ने किसी प्लेयर के मैसेज पर रिप्लाई करके टेबल लगाई है
    if message.reply_to_message:
        p1_id = str(message.reply_to_message.from_user.id)
        p1_name = message.reply_to_message.from_user.first_name
        p2_name = " ".join(args[2:]) if len(args) > 2 else "Opponent"
        # नाम से दूसरे प्लेयर की ID खोजें
        for uid, info in db["users"].items():
            if info["name"].lower() in p2_name.lower().replace("@", ""):
                p2_id = uid
                p2_name = info["name"]
                break
    elif len(args) >= 4:
        p1_name = args[2].replace("@", "")
        p2_name = args[3].replace("@", "")
        for uid, info in db["users"].items():
            if info["name"].lower() == p1_name.lower():
                p1_id = uid
            if info["name"].lower() == p2_name.lower():
                p2_id = uid
    else:
        return

    # दोनों प्लेयर्स के बैलेंस से दांव की राशि काटें (Hold)
    if p1_id and p1_id in db["users"]:
        db["users"][p1_id]["balance"] = round(db["users"][p1_id]["balance"] - amount, 2)
    if p2_id and p2_id in db["users"]:
        db["users"][p2_id]["balance"] = round(db["users"][p2_id]["balance"] - amount, 2)

    t_no = db["table_counter"]
    db["table_counter"] += 1

    table_id = str(t_no)
    db["tables"][table_id] = {
        "p1_id": p1_id,
        "p1_name": p1_name,
        "p2_id": p2_id,
        "p2_name": p2_name,
        "amount": amount,
        "status": "active"
    }
    save_data(db)

    # आपके द्वारा दिया गया सटीक डिज़ाइन
    table_text = (
        f"🎲 𝑻𝒂𝒃𝒍𝒆 𝑵𝒐. {t_no}\n\n"
        f"(1). {p1_name}\n\n"
        f"(2). {p2_name} ✅✅\n\n"
        f"{amount} ✅ 𝗕𝗘𝗦𝗧 ★ 𝗢𝗙 ★𝗟𝗨𝗖𝗞 🎯🎯"
    )

    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton(f"#win 🏆 ({p1_name})", callback_data=f"win1_{table_id}"),
        InlineKeyboardButton(f"#win 🏆 ({p2_name})", callback_data=f"win2_{table_id}")
    )
    markup.row(
        InlineKeyboardButton("cancel this table ❌", callback_data=f"cancel_{table_id}")
    )

    bot.send_message(message.chat.id, table_text, reply_markup=markup)
    if message.chat.type != "private":
        update_pinned_list(message.chat.id)

# बटन क्लिक हैंडल करना (#win और cancel)
@bot.callback_query_handler(func=lambda call: True)
def handle_table_buttons(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ केवल Admin ही परिणाम घोषित कर सकते हैं!", show_alert=True)
        return

    action, table_id = call.data.split("_")
    table = db["tables"].get(table_id)

    if not table or table["status"] != "active":
        bot.answer_callback_query(call.id, "यह टेबल पहले ही बंद हो चुकी है।")
        return

    amount = table["amount"]
    p1_id, p1_name = table["p1_id"], table["p1_name"]
    p2_id, p2_name = table["p2_id"], table["p2_name"]

    # 10% कमीशन गणना: 100 पर 90 प्रॉफिट -> कुल वापसी 100 + 90 = 190
    profit = round(amount * 0.90, 2)
