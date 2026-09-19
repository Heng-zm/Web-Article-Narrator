# Web Article Narrator

A Telegram bot that monitors a fixed website, auto-translates new articles from English to Khmer, and delivers text + optional voice narration to subscribed Telegram users.

## Features
- **Idempotency**: Articles are saved in an SQLite DB so they are never sent twice.
- **Auto-translate**: Uses `deep-translator` (Google Translate) for EN to KM translation.
- **Voice Narration**: Uses `gTTS` and `pydub` (requires ffmpeg) to generate Khmer voice notes.
- **Smart Extraction**: Uses `trafilatura` (with `readability-lxml` fallback) and can handle both single article pages and listing pages.

## Setup

1. **Clone the repo** (if applicable) or navigate to the directory.
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Install ffmpeg**:
   - `pydub` requires `ffmpeg` to be installed on your system and available in your PATH for converting mp3 to ogg/opus.
   - Ubuntu: `sudo apt install ffmpeg`
   - Windows: Download from ffmpeg.org and add to PATH.
4. **Environment Variables**:
   - Copy `.env.example` to `.env`.
   - Fill in your `BOT_TOKEN` (from BotFather), `ADMIN_CHAT_ID`, and `BASE_URL`.

## Registering Bot Commands with BotFather
Send the following to BotFather using the `/setcommands` option for your bot:
```
start - Subscribe to translated articles
stop - Unsubscribe from articles
latest - Force check for new articles
narrate - Toggle voice narration on/off
status - (Admin) Show bot status
```

## Running

Run the bot directly:
```bash
python bot.py
```

## Deployment

For a production environment, it is recommended to run the bot as a system service.

### Using systemd (Linux)
Create `/etc/systemd/system/articlebot.service`:
```ini
[Unit]
Description=Web Article Narrator Bot
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/bot
ExecStart=/path/to/bot/venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```
Then run: `sudo systemctl enable --now articlebot`

### Using PM2
```bash
pm2 start bot.py --interpreter python3 --name "article-bot"
```
