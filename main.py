import os
import sqlite3
import datetime
import logging
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
# 2. إعداد قاعدة البيانات (SQLite)
# ----------------------------------------------------
DB_NAME = "channel_users.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # جدول نشاط الأعضاء
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            last_active TIMESTAMP
        )
    """)
    # جدول التفاعلات مع منشورات الفصل
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS post_reactions (
            post_id INTEGER,
            user_id INTEGER,
            reaction TEXT,
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
# 3. إدارة الأعضاء ورصد الخمول (7 أيام)
# ----------------------------------------------------
async def track_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رصد أي تفاعل من العضو في القناة أو مع البوت"""
    user = update.effective_user
    if user and not user.is_bot:
        update_user_activity(user.id, user.username or user.first_name)

async def select_inactive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معاينة 5 أعضاء خاملين لم يتفاعلوا منذ أكثر من 7 أيام"""
    if update.effective_user.id != ADMIN_ID:
        return

    cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username FROM users WHERE last_active < ?", (cutoff,))
    inactive_users = cursor.fetchall()
    conn.close()

    filtered_users = []
    for uid, uname in inactive_users:
        try:
            member = await context.bot.get_chat_member(CHANNEL_ID, uid)
            # استثناء المشرفين والمالك تلقائياً
            if member.status in ['administrator', 'creator', 'left', 'kicked']:
                continue
            filtered_users.append((uid, uname))
        except Exception:
            continue

    if not filtered_users:
        await update.message.reply_text("✨ لا يوجد أعضاء خاملون حالياً (أكثر من 7 أيام)!")
        return

    sample = filtered_users[:5]
    msg = "📋 **معاينة الخاملين (أول 5 أعضاء لم يتفاعلوا منذ 7 أيام):**\n\n"
    for uid, uname in sample:
        msg += f"• ID: `{uid}` | @{uname if uname else 'بدون_معرف'}\n"
    msg += f"\n🔢 **إجمالي الخاملين المكتشفين:** {len(filtered_users)}"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def clean_inactive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنظيف وحظر الأعضاء الخاملين عبر أمر /clean"""
    if update.effective_user.id != ADMIN_ID:
        return

    cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE last_active < ?", (cutoff,))
    inactive_users = cursor.fetchall()

    banned_count = 0
    for (uid,) in inactive_users:
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
    await update.message.reply_text(f"🧹 تم تنظيف وحظر `{banned_count}` عضواً خاملاً بنجاح!")

# ----------------------------------------------------
# 4. أزرار التفاعل والنشر التفاعلي في القناة
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

    # أزرار أفقية في سطر واحد
    keyboard = [
        [
            InlineKeyboardButton(f"❤️ {c_heart}", callback_data=f"react:{post_id}:heart"),
            InlineKeyboardButton(f"💋 {c_kiss}", callback_data=f"react:{post_id}:kiss"),
            InlineKeyboardButton(f"🔥 {c_fire}", callback_data=f"react:{post_id}:fire"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع الضغط على أزرار التفاعل وتحديث العداد مباشرة"""
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name
    
    update_user_activity(user_id, username)

    _, post_id, reaction = query.data.split(":")
    post_id = int(post_id)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT reaction FROM post_reactions WHERE post_id = ? AND user_id = ?", (post_id, user_id))
    row = cursor.fetchone()

    if row and row[0] == reaction:
        cursor.execute("DELETE FROM post_reactions WHERE post_id = ? AND user_id = ?", (post_id, user_id))
        await query.answer("تم إلغاء تفاعلك.")
    else:
        cursor.execute("""
            INSERT INTO post_reactions (post_id, user_id, reaction)
            VALUES (?, ?, ?)
            ON CONFLICT(post_id, user_id) DO UPDATE SET reaction = excluded.reaction
        """, (post_id, user_id, reaction))
        await query.answer("تم تسجيل تفاعلك! ✨")

    conn.commit()
    conn.close()

    try:
        await query.edit_message_reply_markup(reply_markup=get_reaction_keyboard(post_id))
    except Exception:
        pass

async def publish_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نشر أوراق/فصول المانجا المستقبلة عبر الخاص مباشرة إلى القناة مع الأزرار"""
    if update.effective_user.id != ADMIN_ID or update.effective_chat.type != "private":
        return

    msg = update.message
    post_id = msg.message_id

    reply_markup = get_reaction_keyboard(post_id)

    if msg.photo:
        await context.bot.send_photo(CHANNEL_ID, photo=msg.photo[-1].file_id, caption=msg.caption_html, parse_mode="HTML", reply_markup=reply_markup)
    elif msg.document:
        await context.bot.send_document(CHANNEL_ID, document=msg.document.file_id, caption=msg.caption_html, parse_mode="HTML", reply_markup=reply_markup)
    elif msg.text:
        await context.bot.send_message(CHANNEL_ID, text=msg.text_html, parse_mode="HTML", reply_markup=reply_markup)

    await update.message.reply_text("✅ تم نشر الفصل/المحتوى في القناة بنجاح مع الأزرار التفاعلية!")

# ----------------------------------------------------
# 5. تشغيل البوت الرئيسي
# ----------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # الأوامر الرئيسية
    app.add_handler(CommandHandler("select", select_inactive))
    app.add_handler(CommandHandler("clean", clean_inactive))

    # التفاعل والرسائل
    app.add_handler(CallbackQueryHandler(handle_reaction, pattern="^react:"))
    app.add_handler(MessageHandler(filters.Chat(chat_id=ADMIN_ID) & filters.ChatType.PRIVATE, publish_post))
    app.add_handler(MessageHandler(filters.Chat(CHANNEL_ID), track_activity))

    print("🤖 AsterAlphabot يعمل الآن بنجاح وبشكل مستقر على جهاز الكمبيوتر...")
    app.run_polling()

if __name__ == "__main__":
    main()