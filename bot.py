import os
import io
import re
import sqlite3
import asyncio
import logging
import zipfile
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
NETLIFY_TOKEN = os.getenv("NETLIFY_TOKEN")
ADMIN_ID_RAW = os.getenv("ADMIN_ID")
DEFAULT_CREDIT = 1
NETLIFY_API = "https://api.netlify.com/api/v1"
PORT = int(os.getenv("PORT", "10000"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

def validate_config():
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not NETLIFY_TOKEN:
        missing.append("NETLIFY_TOKEN")
    if not ADMIN_ID_RAW:
        missing.append("ADMIN_ID")
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))
    try:
        return int(ADMIN_ID_RAW)
    except ValueError as exc:
        raise RuntimeError("ADMIN_ID must be numeric") from exc

ADMIN_ID = validate_config()
DB_PATH = "bot_data.db"

def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = db_connect()
    try:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            credits INTEGER DEFAULT 1,
            is_premium INTEGER DEFAULT 0,
            joined_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            site_id TEXT NOT NULL UNIQUE,
            site_name TEXT,
            url TEXT,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )""")
        conn.commit()
    finally:
        conn.close()

def get_user(user_id):
    conn = db_connect()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()

def create_user(user_id, username):
    conn = db_connect()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO users
            (user_id, username, credits, joined_at)
            VALUES (?, ?, ?, ?)""",
            (user_id, username or "", DEFAULT_CREDIT,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            "UPDATE users SET username = ? WHERE user_id = ?",
            (username or "", user_id),
        )
        conn.commit()
    finally:
        conn.close()

def update_credits(user_id, amount):
    conn = db_connect()
    try:
        conn.execute(
            "UPDATE users SET credits = credits + ? WHERE user_id = ?",
            (amount, user_id),
        )
        conn.commit()
    finally:
        conn.close()

def get_credits(user_id):
    user = get_user(user_id)
    return int(user[2]) if user else 0

def deduct_credit(user_id):
    conn = db_connect()
    try:
        cur = conn.execute(
            """UPDATE users SET credits = credits - 1
               WHERE user_id = ? AND credits > 0""",
            (user_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

def save_site(user_id, site_id, site_name, url):
    conn = db_connect()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO sites
               (user_id, site_id, site_name, url, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, site_id, site_name, url,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

def get_user_sites(user_id):
    conn = db_connect()
    try:
        return conn.execute(
            """SELECT site_id, site_name, url, created_at
               FROM sites WHERE user_id = ? ORDER BY id DESC""",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()

def update_site_name(site_id, new_name, new_url):
    conn = db_connect()
    try:
        conn.execute(
            "UPDATE sites SET site_name = ?, url = ? WHERE site_id = ?",
            (new_name, new_url, site_id),
        )
        conn.commit()
    finally:
        conn.close()

def netlify_json_headers():
    return {
        "Authorization": f"Bearer {NETLIFY_TOKEN}",
        "Content-Type": "application/json",
    }

def create_netlify_site(name=None):
    data = {}
    if name:
        clean = re.sub(r"[^a-z0-9-]", "-", name.lower().strip())
        clean = re.sub(r"-+", "-", clean).strip("-")[:50]
        if clean:
            data["name"] = clean
    try:
        response = requests.post(
            f"{NETLIFY_API}/sites",
            headers=netlify_json_headers(),
            json=data,
            timeout=30,
        )
    except requests.RequestException:
        logger.exception("Netlify site creation failed")
        return None
    if response.status_code in (200, 201):
        return response.json()
    logger.error("Create site failed: %s %s", response.status_code, response.text)
    return None

def deploy_zip_to_netlify(site_id, zip_bytes):
    headers = {
        "Authorization": f"Bearer {NETLIFY_TOKEN}",
        "Content-Type": "application/zip",
    }
    try:
        response = requests.post(
            f"{NETLIFY_API}/sites/{site_id}/deploys",
            headers=headers,
            data=zip_bytes,
            timeout=120,
        )
    except requests.RequestException:
        logger.exception("Netlify deployment failed")
        return None
    if response.status_code in (200, 201):
        return response.json()
    logger.error("Deploy failed: %s %s", response.status_code, response.text)
    return None

def delete_netlify_site(site_id):
    try:
        response = requests.delete(
            f"{NETLIFY_API}/sites/{site_id}",
            headers=netlify_json_headers(),
            timeout=30,
        )
        return response.status_code in (200, 204)
    except requests.RequestException:
        logger.exception("Netlify cleanup failed")
        return False

def validate_zip(zip_bytes):
    if len(zip_bytes) > 20 * 1024 * 1024:
        return False, "ZIP file is larger than 20 MB."
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = [n.replace("\\", "/") for n in zf.namelist()]
            files = [n for n in names if not n.endswith("/")]
            if not files:
                return False, "The ZIP is empty."
            if "index.html" not in files:
                return False, "index.html must be at the root of the ZIP."
            for name in names:
                if name.startswith("/") or ".." in name.split("/"):
                    return False, "ZIP contains an unsafe path."
            return True, None
    except zipfile.BadZipFile:
        return False, "The uploaded file is not a valid ZIP archive."

def valid_site_name(name):
    return bool(
        1 <= len(name.strip()) <= 50
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]*", name.strip())
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username)
    keyboard = [
        [InlineKeyboardButton("📊 Credits", callback_data="credits"),
         InlineKeyboardButton("🌐 My Sites", callback_data="mysites")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ]
    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "Send a ZIP containing a static website with index.html at the root "
        "and it will be deployed to Netlify.\n\n"
        f"💳 Credits: {get_credits(user.id)}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username)
    await update.message.reply_text(f"💳 Your credits: {get_credits(user.id)}")

async def mysites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username)
    sites = get_user_sites(user.id)
    if not sites:
        await update.message.reply_text("🌐 You have no hosted sites yet.")
        return
    lines = ["🌐 Your hosted sites:\n"]
    for site_id, site_name, url, created_at in sites[:20]:
        lines.append(f"• {site_name or site_id}\n  {url}")
    await update.message.reply_text("\n".join(lines))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Commands\n\n"
        "/start — Register and show menu\n"
        "/credits — Check credits\n"
        "/mysites — View hosted sites\n"
        "/rename <site_id> <new_name> — Rename a saved site\n"
        "/addcredit <uid> <amount> — Admin only\n\n"
        "Hosting: send a ZIP with index.html at its root."
    )

async def addcredit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /addcredit <uid> <amount>")
        return
    try:
        uid = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("UID and amount must be numbers.")
        return
    if amount == 0:
        await update.message.reply_text("Amount cannot be zero.")
        return
    if not get_user(uid):
        await update.message.reply_text("User is not registered.")
        return
    update_credits(uid, amount)
    await update.message.reply_text(
        f"✅ Added {amount} credit(s).\nCurrent balance: {get_credits(uid)}"
    )

async def rename_site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /rename <site_id> <new_name>")
        return
    site_id = context.args[0]
    new_name = " ".join(context.args[1:]).strip()
    if not valid_site_name(new_name):
        await update.message.reply_text(
            "Invalid name. Use 1–50 letters, numbers, spaces or hyphens."
        )
        return
    sites = {row[0]: row for row in get_user_sites(update.effective_user.id)}
    site = sites.get(site_id)
    if not site:
        await update.message.reply_text("❌ Site not found.")
        return
    update_site_name(site_id, new_name, site[2])
    await update.message.reply_text(f"✅ Saved site name changed to: {new_name}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    create_user(user_id, query.from_user.username)

    if query.data == "credits":
        text = f"💳 Your credits: {get_credits(user_id)}"
    elif query.data == "mysites":
        sites = get_user_sites(user_id)
        if not sites:
            text = "🌐 You have no hosted sites yet."
        else:
            text = "🌐 Your hosted sites:\n\n" + "\n".join(
                f"• {name or sid}\n  {url}" for sid, name, url, created in sites[:20]
            )
    else:
        text = (
            "📖 Send a ZIP containing index.html at the ZIP root.\n\n"
            "/credits — Check credits\n"
            "/mysites — View hosted sites\n"
            "/rename <site_id> <new_name> — Rename\n"
            "/addcredit <uid> <amount> — Admin only"
        )
    await query.edit_message_text(text)

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username)

    if get_credits(user.id) <= 0:
        await update.message.reply_text(
            "❌ You have no credits left. Ask the admin to add credits."
        )
        return

    document = update.message.document
    filename = (document.file_name or "").lower()
    if not filename.endswith(".zip"):
        await update.message.reply_text("❌ Please send a .zip file.")
        return
    if document.file_size and document.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("❌ ZIP file is larger than 20 MB.")
        return

    status = await update.message.reply_text("⏳ Downloading and checking ZIP...")
    try:
        tg_file = await document.get_file()
        buffer = io.BytesIO()
        await tg_file.download_to_memory(out=buffer)
        zip_bytes = buffer.getvalue()
    except Exception:
        logger.exception("Telegram download failed")
        await status.edit_text("❌ Could not download the ZIP.")
        return

    ok, error = validate_zip(zip_bytes)
    if not ok:
        await status.edit_text(f"❌ {error}")
        return

    if not deduct_credit(user.id):
        await status.edit_text("❌ You no longer have any credits.")
        return

    site = None
    try:
        await status.edit_text("⏳ Creating Netlify site...")
        site = await asyncio.to_thread(create_netlify_site)
        if not site:
            update_credits(user.id, 1)
            await status.edit_text("❌ Could not create the Netlify site. Credit refunded.")
            return

        site_id = site["id"]
        site_name = site.get("name") or site_id
        await status.edit_text("⏳ Uploading website to Netlify...")
        deploy = await asyncio.to_thread(
            deploy_zip_to_netlify, site_id, zip_bytes
        )

        if not deploy:
            update_credits(user.id, 1)
            await asyncio.to_thread(delete_netlify_site, site_id)
            await status.edit_text(
                "❌ Netlify deployment failed. Your credit was refunded."
            )
            return

        url = deploy.get("ssl_url") or deploy.get("url") or ""
        save_site(user.id, site_id, site_name, url)
        await status.edit_text(
            "✅ Website deployed successfully!\n\n"
            f"🌐 {url}\n"
            f"🆔 Site ID: `{site_id}`\n"
            f"💳 Remaining credits: {get_credits(user.id)}",
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Unexpected deployment error")
        update_credits(user.id, 1)
        if site and site.get("id"):
            await asyncio.to_thread(delete_netlify_site, site["id"])
        await status.edit_text(
            "❌ An unexpected error occurred. Your credit was refunded."
        )

async def error_handler(update, context):
    logger.error("Telegram update error: %s", context.error, exc_info=context.error)

async def health(request):
    return web.Response(text="OK")

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("Health server listening on port %s", PORT)
    return runner

async def main():
    init_db()
    health_runner = await start_health_server()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("credits", credits))
    application.add_handler(CommandHandler("mysites", mysites))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("addcredit", addcredit))
    application.add_handler(CommandHandler("rename", rename_site))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    application.add_error_handler(error_handler)

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("Telegram bot started successfully.")

    try:
        await asyncio.Event().wait()
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await health_runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
