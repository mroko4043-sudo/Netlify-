import os
import sqlite3
import logging
import asyncio
import requests
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv()

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
NETLIFY_TOKEN = os.getenv("NETLIFY_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", ""))  # Your Telegram User ID
DEFAULT_CREDIT = 1
NETLIFY_API = "https://api.netlify.com/api/v1"

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== DATABASE ====================
def init_db():
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            credits INTEGER DEFAULT 1,
            is_premium INTEGER DEFAULT 0,
            joined_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            site_id TEXT,
            site_name TEXT,
            url TEXT,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def create_user(user_id, username):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users (user_id, username, credits, joined_at) VALUES (?, ?, ?, ?)",
        (user_id, username, DEFAULT_CREDIT, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def update_credits(user_id, amount):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def get_credits(user_id):
    user = get_user(user_id)
    return user[2] if user else 0

def deduct_credit(user_id):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits - 1 WHERE user_id = ? AND credits > 0", (user_id,))
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected > 0

def save_site(user_id, site_id, site_name, url):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO sites (user_id, site_id, site_name, url, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, site_id, site_name, url, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_user_sites(user_id):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("SELECT site_id, site_name, url, created_at FROM sites WHERE user_id = ? ORDER BY id DESC", (user_id,))
    sites = c.fetchall()
    conn.close()
    return sites

def update_site_name(site_id, new_name, new_url):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("UPDATE sites SET site_name = ?, url = ? WHERE site_id = ?", (new_name, new_url, site_id))
    conn.commit()
    conn.close()

# ==================== NETLIFY FUNCTIONS ====================
def create_netlify_site(name=None):
    headers = {
        "Authorization": f"Bearer {NETLIFY_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {}
    if name:
        data["name"] = name.lower().replace(" ", "-")

    response = requests.post(f"{NETLIFY_API}/sites", headers=headers, json=data)
    if response.status_code in [200, 201]:
        return response.json()
    else:
        logger.error(f"Create site failed: {response.text}")
        return None

def deplo
... 