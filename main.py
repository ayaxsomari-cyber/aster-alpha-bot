import os
import sqlite3
import datetime
import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ----------------------------------------------------
# 1. إعدادات البوت والبيانات الأساسية
# ----------------------------------------------------
BOT_TOKEN = "8824695458:AAESLpzfdE41hGAo-pfExdrKLgjc82m1BFc"
CHANNEL_ID = "@yaoi_kingsbl"
ADMIN_ID = 6359502690  # معرفكِ الخاص كآدمن الرئيسي

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# ----------------------------------------------------
# 2. إعداد قاعدة البيانات (المفكرة / SQLite)
# ----------------------------------------------------
DB_NAME = "channel_users.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # جدول نشاط الأعضاء العام
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            last_active TIMESTAMP
        )
    """)
    # جدول التفاعلات مع تحديد وقت التفاعل لحصر أسبوع فقط
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS post_reactions (
            post_id INTEGER,
            user_id INTEGER,
            reaction TEXT,
            interaction_time TIMESTAMP,
            PRIMARY KEY (post_id, user_id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

def update_user_activity(user_id: int, username: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.datetime.now()
    cursor.execute("""
        INSERT INTO users (user_id, username, last_active)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            last_active = excluded.last_active
    """, (user_id, username, now))
    conn.commit()
    conn.close()

# ----------------------------------------------------
# 3. رصد التفاعلات والنشاط
# ----------------------------------------------------
async def track_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رصد تفاعل الأعضاء في القناة"""
    user = update.effective_user
    if user and not user.is_bot:
        update_user_activity(user.id, user.username or user.first_name)

# ----------------------------------------------------
# 4. إدارة الخاملين والأوامر المطلوبة (/select و /inactive و /clean)
# ----------------------------------------------------
async def select_inactive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /select: يختار 5 أعضاء عشوائيين من الذين لم يتفاعلوا خلال آخر 7 أيام"""
    if update.effective_user.id != ADMIN_ID:
        return

    one_week_ago = datetime.datetime.now() - datetime.timedelta(days=7)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # جلب الأعضاء الذين تفاعلوا خلال آخر 7 أيام
    cursor.execute("SELECT DISTINCT user_id FROM post_reactions WHERE interaction_time >= ?", (one_week_ago,))
    active_user_ids = {row[0] for row in cursor.fetchall()}
    
    # جلب كل المسجلين في القاعدة
    cursor.execute("SELECT user_id, username FROM users")
    all_users = cursor.fetchall()
    conn.close()

    inactive_list = []
    for uid, uname in all_users:
        if uid in active_user_ids:
            continue
        try:
            member = await context.bot.get_chat_member(CHANNEL_ID, uid)
            if member.status in ['administrator', 'creator', 'left', 'kicked']:
                continue
            inactive_list.append((uid, uname))
        except Exception:
            continue

    if not inactive_list:
        await update.message.reply_text("✨ ممتاز! لا يوجد أعضاء خاملون (لم يتفاعلوا خلال الأسبوع الماضي).")
        return

    # اختيار 5 أعضاء عشوائياً حصرياً مع أمر select
    sample = random.sample(inactive_list, min(5, len(inactive_list)))
    
    msg = "📋 **عشوائي الخاملين (5 أعضاء لم يتفاعلوا منذ أسبوع):**\n\n"
    for uid, uname in sample:
        msg += f"• ID: `{uid}` | @{uname if uname else 'بدون_معرف'}\n"
    msg += f"\n🔢 **إجمالي غير المتفاعلين حالياً:** {len(inactive_list)}"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def show_all_inactive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /inactive: لمعرفة كل غير المتفاعلين بعد المهلة بغض النظر عن الـ 5 أعضاء"""
    if update.effective_user.id != ADMIN_ID:
        return

    one_week_ago = datetime.datetime.now() - datetime.timedelta(days=7)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT user_id FROM post_reactions WHERE interaction_time >= ?", (one_week_ago,))
    active_user_ids = {row[0] for row in cursor.fetchall()}
    
    cursor.execute("SELECT user_id, username FROM users")
    all_users = cursor.fetchall()
    conn.close()

    inactive_list = []
    for uid, uname in all_users:
        if uid in active_user_ids:
            continue
        try:
            member = await context.bot.get_chat_member(CHANNEL_ID, uid)
            if member.status in ['administrator', 'creator', 'left', 'kicked']:
                continue
            inactive_list.append((uid, uname))
        except Exception:
            continue

    if not inactive_list:
        await update.message.reply_text("✨ لا يوجد أعضاء غير متفاعلين بعد انتهاء المهلة!")
        return

    msg = f"📊 **قائمة جميع غير المتفاعلين بعد انقضاء المهلة (العدد الإجمالي: {len(inactive_list)}):**\n\n"
    for uid, uname in inactive_list[:20]:
        msg += f"• ID: `{uid}` | @{uname if uname else 'بدون_معرف'}\n"
    
    if len(inactive_list) > 20:
        msg += f"\n... و {len(inactive_list) - 20} أعضاء آخرين."

    await update.message.reply_text(msg, parse_mode="Markdown")

async def clean_inactive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /clean: تصفية وحظر كل غير المتفاعلين خلال الأسبوع الماضي مباشرة"""
    if update.effective_user.id != ADMIN_ID:
        return

    one_week_ago = datetime.datetime.now() - datetime.timedelta(days=7)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT user_id FROM post_reactions WHERE interaction_time >= ?", (one_week_ago,))
    active_user_ids = {row[0] for row in cursor.fetchall()}
    
    cursor.execute("SELECT user_id FROM users")
    all_users = cursor.fetchall()

    banned_count = 0
    for (uid,) in all_users:
        if uid in active_user_ids:
            continue
        try:
            member = await context.bot.get_chat_member(CHANNEL_ID, uid)
            if member.status in ['administrator', 'creator', 'left', 'kicked']:
                continue
            
            await context.bot.ban_chat_member(CHANNEL_ID, uid)
            cursor.execute("DELETE FROM users WHERE user_id = ?", (uid,))
            banned_count += 1
        except Exception:
            continue

    conn.commit()
    conn.close()
    await update.message.reply_text(f"🧹 تم بنجاح تصفية وحظر `{banned_count}` عضواً خاملاً لم يتفاعلوا طوال الأسبوع الماضي!")

# ----------------------------------------------------
# 5. أزرار التفاعل (❤️, 💋, 🔥, 😭) والنشر التفاعلي
# ----------------------------------------------------
def get_reaction_keyboard(post_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT reaction, COUNT(*) FROM post_reactions WHERE post_id = ? GROUP BY reaction", (post_id,))
    counts = dict(cursor.fetchall())
    conn.close()

    c_heart = counts.get('heart', 0)
    c_kiss = counts.get('kiss', 0)
    c_fire = counts.get('fire', 0)
    c_cry = counts.get('cry', 0)

    keyboard = [
        [
            InlineKeyboardButton(f"❤️ {c_heart}", callback_data=f"react:{post_id}:heart"),
            InlineKeyboardButton(f"💋 {c_kiss}", callback_data=f"react:{post_id}:kiss"),
        ],
        [
            InlineKeyboardButton(f"🔥 {c_fire}", callback_data=f"react:{post_id}:fire"),
            InlineKeyboardButton(f"😭 {c_cry}", callback_data=f"react:{post_id}:cry"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name
    
    update_user_activity(user_id, username)

    _, post_id, reaction = query.data.split(":")
    post_id = int(post_id)
    now = datetime.datetime.now()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT reaction FROM post_reactions WHERE post_id = ? AND user_id = ?", (post_id, user_id))
    row = cursor.fetchone()

    if row and row[0] == reaction:
        cursor.execute("DELETE FROM post_reactions WHERE post_id = ? AND user_id = ?", (post_id, user_id))
        await query.answer("تم إلغاء تفاعلك.")
    else:
        cursor.execute("""
            INSERT INTO post_reactions (post_id, user_id, reaction, interaction_time)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(post_id, user_id) DO UPDATE SET reaction = excluded.reaction, interaction_time = excluded.interaction_time
        """, (post_id, user_id, reaction, now))
        await query.answer("تم تسجيل تفاعلك بنجاح! ✨")

    conn.commit()
    conn.close()

    try:
        await query.edit_message_reply_markup(reply_markup=get_reaction_keyboard(post_id))
    except Exception:
        pass

async def publish_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or update.effective_chat.type != "private":
        return

    msg = update.message
    
    initial_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❤️ 0", callback_data="react:0:heart"),
            InlineKeyboardButton("💋 0", callback_data="react:0:kiss"),
        ],
        [
            InlineKeyboardButton("🔥 0", callback_data="react:0:fire"),
            InlineKeyboardButton("😭 0", callback_data="react:0:cry"),
        ]
    ])

    sent_message = None
    if msg.photo:
        sent_message = await context.bot.send_photo(
            chat_id=CHANNEL_ID, 
            photo=msg.photo[-1].file_id, 
            caption=msg.caption_html, 
            parse_mode="HTML", 
            reply_markup=initial_markup
        )
    elif msg.document:
        sent_message = await context.bot.send_document(
            chat_id=CHANNEL_ID, 
            document=msg.document.file_id, 
            caption=msg.caption_html, 
            parse_mode="HTML", 
            reply_markup=initial_markup
        )
    elif msg.text:
        sent_message = await context.bot.send_message(
            chat_id=CHANNEL_ID, 
            text=msg.text_html, 
            parse_mode="HTML", 
            reply_markup=initial_markup
        )

    if sent_message:
        real_post_id = sent_message.message_id
        await context.bot.edit_message_reply_markup(
            chat_id=CHANNEL_ID,
            message_id=real_post_id,
            reply_markup=get_reaction_keyboard(real_post_id)
        )

    await update.message.reply_text("✅ تم نشر الفصل في القناة مع الأزرار وخانة التعليقات بنجاح!")

# ----------------------------------------------------
# 6. التشغيل الرئيسي
# ----------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("select", select_inactive))
    app.add_handler(CommandHandler("inactive", show_all_inactive))
    app.add_handler(CommandHandler("clean", clean_inactive))

    app.add_handler(CallbackQueryHandler(handle_reaction, pattern="^react:"))
    app.add_handler(MessageHandler(filters.Chat(chat_id=ADMIN_ID) & filters.ChatType.PRIVATE, publish_post))
    app.add_handler(filters.Chat(CHANNEL_ID) & ~filters.ChatType.CHANNEL, track_activity)

    print("🤖 البوت جاهز تماماً...")
    app.run_polling()

if __name__ == "__main__":
    main()
