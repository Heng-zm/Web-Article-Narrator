import os
import sys
# Add vendored packages for Wasmer Edge deployment
if os.path.exists('packages'):
    sys.path.insert(0, os.path.abspath('packages'))

import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from urllib.parse import urlparse
from datetime import datetime

import storage
from extractor import get_new_articles
from translator import translate_text
from summarizer import extractive_summary
from categorizer import CATEGORIES, categorize_article

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID')
BASE_URL = os.environ.get('BASE_URL')

async def on_startup(application: Application):
    """Initialize DB on startup."""
    logger.info("Initializing database...")
    await storage.init_db()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Subscribe the user."""
    chat_id = update.effective_chat.id
    await storage.add_subscriber(chat_id)
    await update.message.reply_text(
        "Welcome! / សូមស្វាគមន៍!\n"
        "You are now subscribed to receive translated articles."
    )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unsubscribe the user."""
    chat_id = update.effective_chat.id
    await storage.remove_subscriber(chat_id)
    await update.message.reply_text("You have been unsubscribed.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin status command."""
    chat_id = str(update.effective_chat.id)
    if chat_id != ADMIN_CHAT_ID:
        await update.message.reply_text("Unauthorized.")
        return
        
    subs_list = await storage.get_subscribers()
    subs = len(subs_list)
    sent = await storage.get_sent_articles_count()
    
    status_msg = (
        f"Bot Status:\n"
        f"- Subscribers: {subs}\n"
        f"- Articles Sent: {sent}\n"
    )
    await update.message.reply_text(status_msg)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to send a message to all subscribers."""
    chat_id = str(update.effective_chat.id)
    if chat_id != ADMIN_CHAT_ID:
        await update.message.reply_text("Unauthorized.")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <your message here>")
        return
        
    message = " ".join(context.args)
    subs = await storage.get_subscribers()
    sent = 0
    for sub_id in subs:
        try:
            await context.bot.send_message(chat_id=sub_id, text=f"📢 <b>Announcement</b>\n\n{message}", parse_mode='HTML')
            sent += 1
        except Exception:
            pass
            
    await update.message.reply_text(f"Broadcast successfully sent to {sent} subscribers.")

async def addurl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to add a new base URL to scrape."""
    chat_id = str(update.effective_chat.id)
    if chat_id != ADMIN_CHAT_ID:
        await update.message.reply_text("Unauthorized.")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: /addurl <https://example.com>")
        return
        
    url = context.args[0]
    if not url.startswith('http'):
        await update.message.reply_text("URL must start with http:// or https://")
        return
        
    await storage.add_base_url(url)
    await update.message.reply_text(f"✅ Successfully added {url} to the database. The bot will now monitor it.")

async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch and send the latest article immediately."""
    chat_id = update.effective_chat.id
    
    # Check DB and fallback to .env
    urls = await storage.get_base_urls()
    if BASE_URL and BASE_URL not in urls:
        urls.append(BASE_URL)
        
    if not urls:
        await update.message.reply_text("No base URLs configured. Use /addurl first.")
        return
        
    status_message = await update.message.reply_text("🔎 Fetching the latest news from all sources...")
    
    # Try all URLs until we find articles
    all_articles = []
    for base in urls:
        arts = await get_new_articles(base)
        all_articles.extend(arts)
        
    if not all_articles:
        await status_message.edit_text("No articles found right now.")
        return
        
    # Just grab the very first one found across all sources
    article = all_articles[0]
    url = article['url']
    image_url = article.get('image_url')
    title = article.get('title', 'News Article')
    
    short_summary = await asyncio.to_thread(extractive_summary, article['text'])
    
    # Translate
    km_title, km_text = await asyncio.gather(
        asyncio.to_thread(translate_text, title),
        asyncio.to_thread(translate_text, short_summary)
    )
    
    domain = urlparse(url).netloc.replace('www.', '')
    date_str = datetime.now().strftime("%d/%m/%Y")
    
    # Generate Hashtags based on title and summary
    url_slug = url.strip('/').split('/')[-1].replace('-', ' ')
    article_cats = categorize_article(km_text, url_slug)
    if article_cats:
        hashtags = " ".join([f"#{cat.replace(' ', '_')}" for cat in article_cats])
    else:
        hashtags = "#ព័ត៌មានទូទៅ"
        
    footer = f"🔒 <b>ប្រភព:</b> {domain}\n📅 {date_str}\n\n{hashtags}"
    header = f"📰 <b>{km_title}</b>\n\n"
    
    # Format the translated summary into clean bullet points
    raw_km_text = km_text
    # Split by the strict delimiter
    lines = [line.strip() for line in raw_km_text.split('|||') if line.strip()]
    
    clean_km_text = "<b>ចំណុចសំខាន់ៗ៖</b>\n"
    current_len = 0
    max_text_len = 950 - len(header) - len(footer)
    
    for line in lines:
        line = line.lstrip('•').lstrip('-').lstrip('*').lstrip('🔹').strip()
        
        if current_len + len(line) > max_text_len:
            remaining = max_text_len - current_len
            if remaining > 15:
                clean_km_text += f"• {line[:remaining]}...\n"
            break
            
        clean_km_text += f"• {line}\n"
        current_len += len(line)
        
    summary = f"{header}{clean_km_text.strip()}\n\n{footer}"
    
    keyboard = [[InlineKeyboardButton("🔗 អានដើម (Read Original)", url=url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    image_bytes = None
    if image_url:
        from extractor import get_scraper
        try:
            def fetch_img():
                with get_scraper() as scraper:
                    res = scraper.get(image_url, timeout=10)
                    if res.status_code == 200:
                        return res.content
                    return None
            image_bytes = await asyncio.to_thread(fetch_img)
        except Exception as e:
            logger.warning(f"Failed to download image {image_url}: {e}")
    
    try:
        await status_message.delete()
        if image_bytes:
            await context.bot.send_photo(chat_id=chat_id, photo=image_bytes, caption=summary, parse_mode='HTML', reply_markup=reply_markup, read_timeout=20)
        else:
            await context.bot.send_message(chat_id=chat_id, text=summary, parse_mode='HTML', reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Failed to send latest to {chat_id}: {e}")
        await context.bot.send_message(chat_id=chat_id, text="Failed to send the article.")

async def removeurl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to remove a base URL."""
    chat_id = str(update.effective_chat.id)
    if chat_id != ADMIN_CHAT_ID:
        await update.message.reply_text("Unauthorized.")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: /removeurl <https://example.com>")
        return
        
    url = context.args[0]
    await storage.remove_base_url(url)
    await update.message.reply_text(f"🗑 Successfully removed {url} from the tracking list.")

async def listurls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all tracked URLs."""
    urls = await storage.get_base_urls()
    if BASE_URL and BASE_URL not in urls:
        urls.append(BASE_URL)
        
    if not urls:
        await update.message.reply_text("The bot is not tracking any websites right now.")
        return
        
    text = "🌐 <b>Currently Tracked Websites:</b>\n\n"
    for idx, u in enumerate(urls, 1):
        text += f"{idx}. {u}\n"
        
    await update.message.reply_text(text, parse_mode='HTML')

async def bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to show bot statistics."""
    chat_id = str(update.effective_chat.id)
    if chat_id != ADMIN_CHAT_ID:
        await update.message.reply_text("Unauthorized.")
        return
        
    stats = await storage.get_stats()
    text = f"📊 <b>Bot Statistics</b>\n\n👥 <b>Total Subscribers:</b> {stats['subscribers']}\n📰 <b>Articles Sent:</b> {stats['articles']}"
    await update.message.reply_text(text, parse_mode='HTML')

async def categories_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the interactive category selection menu."""
    if update.message:
        chat_id = update.message.chat_id
    else:
        chat_id = update.callback_query.message.chat_id
        
    user_cats = await storage.get_user_categories(chat_id)
    
    keyboard = []
    for cat in CATEGORIES:
        # Show ✅ if selected, ❌ if not
        icon = "✅" if cat in user_cats else "❌"
        button_text = f"{icon} {cat}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"toggle_{cat}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🗞️ <b>សូមជ្រើសរើសប្រភេទព័ត៌មានដែលអ្នកចង់អាន៖</b>\n(ជ្រើសរើសមួយឬច្រើន / Select your preferred categories)"
    
    if update.message:
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button clicks from the inline keyboard."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = query.message.chat_id
    
    if data.startswith("toggle_"):
        cat = data.split("toggle_")[1]
        await storage.toggle_user_category(chat_id, cat)
        # Refresh menu
        await categories_menu(update, context)

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set. Exiting.")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    
    # Hooks for DB
    application.post_init = on_startup

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("addurl", addurl))
    application.add_handler(CommandHandler("removeurl", removeurl))
    application.add_handler(CommandHandler("listurls", listurls))
    application.add_handler(CommandHandler("stats", bot_stats))
    application.add_handler(CommandHandler("latest", latest))
    application.add_handler(CommandHandler("categories", categories_menu))
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot started successfully in standalone mode.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
