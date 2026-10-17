# ABHI MUSIC ROYAL EDITION

Telegram group voice-chat music bot.

## Requirements
- Android with Termux
- Python 3, FFmpeg and Git
- Telegram API ID, API Hash and Bot Token

## Installation
```bash
pkg update
pkg install python ffmpeg git
git clone https://github.com/am4582257-commits/abhi-music-royal.git MusicWithAbhi
cd MusicWithAbhi
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Edit `.env` and enter your own API_ID, API_HASH and BOT_TOKEN.

Start the bot with:
```bash
source .venv/bin/activate
python royal_bot.py
```

## Security
Never upload `.env`, Telegram session files, bot tokens or API credentials.
Each user must configure their own credentials.
