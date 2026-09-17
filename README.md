# 🚀 Netlify Hosting Telegram Bot

A Telegram bot that automatically hosts static websites on Netlify when users upload a ZIP file.

## ✨ Features

- ✅ Upload ZIP file → Public hosting on Netlify
- ✅ Custom site name (rename)
- ✅ Credit system (default 1 credit)
- ✅ Premium lock (hosting blocked when credits are finished)
- ✅ Admin can add credits using Telegram UID
- ✅ Users can view their hosted sites list

## 📋 Setup Guide

### 1. Collect the required things

1. **Telegram Bot Token**
   - Open `@BotFather` on Telegram
   - Send `/newbot` and create a new bot
   - Copy the token

2. **Netlify Personal Access Token**
   - Go to [this link](https://app.netlify.com/user/applications#personal-access-tokens)
   - Click **New access token**
   - Give a name → Generate → Copy the token

3. **Your Telegram User ID**
   - Message `@userinfobot` or `@getidsbot`
   - Note down your ID (this will be the Admin ID)

### 2. Run locally

```bash
# Go to the project folder
cd netlify-host-bot

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Install packages
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Then edit the .env file and put your tokens
```

Your `.env` file should look like this:
```
BOT_TOKEN=123456:ABC-DEF...
NETLIFY_TOKEN=nfp_xxxxxxxx
ADMIN_ID=123456789
```

### 3. Start the bot

```bash
python bot.py
```

Once the bot starts, open Telegram and send `/start` to your bot.

---

## 🤖 Command List

| Command | Description |
|---------|-------------|
| `/start` | Start the bot + register |
| `/credits` | Check your credits |
| `/mysites` | View your hosted sites |
| `/rename <site_id> <new_name>` | Rename a site |
| `/help` | Help menu |
| `/addcredit <uid> <amount>` | **Admin only** - Add credits |

---

## 📦 How to Host (for users)

1. Put your website files (including `index.html`) in a folder
2. Compress the folder into a **ZIP** file
3. Send the ZIP file to the bot
4. The bot will automatically host it and give you the link
5. Optionally use `/rename` to set a custom name

---

## ☁️ How to Host the Bot 24/7

### Option 1: Railway (Easiest)

1. Create an account on [railway.app](https://railway.app)
2. New Project → Deploy from GitHub (or upload locally)
3. Add Environment Variables: `BOT_TOKEN`, `NETLIFY_TOKEN`, `ADMIN_ID`
4. Start Command: `python bot.py`

### Option 2: Render

1. Create a Web Service on [render.com](https://render.com)
2. Set Environment Variables
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `python bot.py`

### Option 3: VPS (Ubuntu)

```bash
sudo apt update
sudo apt install python3-pip python3-venv
git clone <your-repo>
cd netlify-host-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Create .env file
nohup python bot.py &
```

---

## ⚠️ Important Notes

- All sites will be created under **your Netlify account**
- Only **static sites** (HTML, CSS, JS) are supported
- Telegram file size limit ≈ 20MB
- The ZIP must contain `index.html` at the root level
- Netlify free plan has limits (creating too many sites may hit the limit)

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---------|----------|
| Deploy failed | Check if `index.html` exists inside the ZIP |
| Name already taken | Try a different name |
| Credits finished | Admin can add credits using `/addcredit` |
| Bot does not start | Check `.env` file and tokens |

---

Made with ❤️ by Grok
