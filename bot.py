import os
import sys
# Add vendored packages for Wasmer Edge deployment
if os.path.exists('packages'):
    sys.path.insert(0, os.path.abspath('packages'))

import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, InlineQueryResultArticle, InputTextMessageContent
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, InlineQueryHandler
from urllib.parse import urlparse
from datetime import datetime
from uuid import uuid4

import storage
from extractor import get_new_articles
from translator import translate_text
from summarizer import extractive_summary
from categorizer import CATEGORIES, categorize_article, analyze_article_metadata
import time
_bot_start_time = time.time()

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

async def on_startup(app: Application):
    """Initializes the database and sets the Telegram Bot Command Menu."""
    await storage.init_db()
    
    try:
        from telegram import BotCommand
        commands = [
            BotCommand("start", "ចាប់ផ្តើមទទួលព័ត៌មាន (Start)"),
            BotCommand("categories", "ជ្រើសរើសប្រភេទព័ត៌មាន (Categories)"),
            BotCommand("latest", "អានព័ត៌មានចុងក្រោយ (Latest News)"),
            BotCommand("stats", "មើលស្ថិតិអ្នកអាន (Bot Stats)"),
            BotCommand("stop", "ឈប់ទទួលព័ត៌មាន (Stop)")
        ]
        await app.bot.set_my_commands(commands)
        from telegram import BotCommandScopeChat
        admin_commands = [
            BotCommand("admin", "📊 Analytics Dashboard"),
            BotCommand("broadcast", "📢 Broadcast to all users"),
            BotCommand("addurl", "➕ Add news source URL"),
            BotCommand("removeurl", "🗑 Remove news source URL"),
            BotCommand("listurls", "🌐 List tracked URLs"),
        ]
        if ADMIN_CHAT_ID:
            try:
                await app.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=int(ADMIN_CHAT_ID)))
            except Exception:
                pass
        logger.info("Successfully registered bot command menu!")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Subscribe the user and prompt categories."""
    chat_id = update.effective_chat.id
    user_name = update.effective_user.first_name
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await storage.add_subscriber(chat_id)
    
    welcome_text = (
        f"🌟 <b>សួស្តី {user_name}!</b> 🌟\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🇰🇭 សូមស្វាគមន៍មកកាន់ <b>Web Article Narrator</b>\n"
        f"ប្រព័ន្ធព័ត៌មានឆ្លាតវៃបំផុតសម្រាប់ប្រជាជនខ្មែរ!\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <b>លក្ខណៈពិសេស (Features):</b>\n\n"
        f"  📡 <b>ព័ត៌មានផ្ទាល់ (Real-Time News)</b>\n"
        f"  ↳ ទទួលបានព័ត៌មានថ្មីរៀងរាល់ ៥ នាទី\n\n"
        f"  🚨 <b>ព័ត៌មានបន្ទាន់ (Breaking News)</b>\n"
        f"  ↳ ជូនដំណឹងភ្លាមៗពេលមានហេតុការណ៍សំខាន់\n\n"
        f"  🧠 <b>បញ្ញាសិប្បនិម្មិត (Smart AI)</b>\n"
        f"  ↳ ចាត់ថ្នាក់ & បកប្រែព័ត៌មានដោយស្វ័យប្រវត្តិ\n\n"
        f"  🗂 <b>ជ្រើសរើសប្រភេទ (Custom Categories)</b>\n"
        f"  ↳ ទទួលតែព័ត៌មានដែលអ្នកចង់អាន\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>ពាក្យបញ្ជា (Commands):</b>\n"
        f"  /latest — ព័ត៌មានថ្មីបំផុតឥឡូវ\n"
        f"  /categories — ជ្រើសរើសប្រភេទព័ត៌មាន\n"
        f"  /stop — ឈប់ទទួលព័ត៌មាន\n\n"
        f"👇 <b>ជំហានដំបូង:</b> សូមជ្រើសរើសប្រភេទព័ត៌មានដែលអ្នកចង់តាមដាន!"
    )

    await update.message.reply_text(welcome_text, parse_mode='HTML')
    # Automatically show category selection menu so the bot "knows" the user
    await categories_menu(update, context)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unsubscribe the user."""
    chat_id = update.effective_chat.id
    await storage.remove_subscriber(chat_id)
    await update.message.reply_text("✅ អ្នកបានឈប់ទទួលព័ត៌មានជោគជ័យ។\n\nវាយ /start ដើម្បីចាប់ផ្ដើមម្ដងទៀត។", parse_mode='HTML')

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rich Admin Analytics Dashboard."""
    chat_id = str(update.effective_chat.id)
    if chat_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Gather all stats concurrently
    subs_list, sent_count, urls, cat_stats = await asyncio.gather(
        storage.get_subscribers(),
        storage.get_sent_articles_count(),
        storage.get_base_urls(),
        storage.get_category_stats(),
    )

    # Uptime
    uptime_secs = int(time.time() - _bot_start_time)
    hours, rem = divmod(uptime_secs, 3600)
    minutes = rem // 60
    uptime_str = f"{hours}h {minutes}m"

    # Memory
    mem_str = "N/A"
    try:
        import psutil, os as _os
        proc = psutil.Process(_os.getpid())
        mem_mb = proc.memory_info().rss / 1024 / 1024
        mem_str = f"{mem_mb:.1f} MB"
    except Exception:
        pass

    # Category breakdown
    cat_lines = ""
    for cat, count in list(cat_stats.items())[:6]:
        cat_lines += f"  • {cat} — {count} users\n"
    if not cat_lines:
        cat_lines = "  មិនទាន់មានទិន្នន័យ (No data yet)\n"

    text = (
        f"💼 <b>Admin Analytics Dashboard</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Subscribers:</b> {len(subs_list)}\n"
        f"📰 <b>Articles Sent:</b> {sent_count}\n"
        f"🌐 <b>Sources Tracked:</b> {len(urls)}\n"
        f"⏱ <b>Uptime:</b> {uptime_str}\n"
        f"🧠 <b>Memory:</b> {mem_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📂 <b>Category Breakdown:</b>\n"
        f"{cat_lines}"
    )
    await update.message.reply_text(text, parse_mode='HTML')

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
        except Exception as e:
            err = str(e).lower()
            if 'blocked' in err or 'deactivated' in err or 'not found' in err:
                await storage.remove_subscriber(sub_id)
            
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
        
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    status_message = await update.message.reply_text("🔎 កំពុងស្វែងរកព័ត៌មានចុងក្រោយពីគ្រប់ប្រភព...")
    
    # 1. Concurrently scrape all base URLs for maximum responsiveness
    tasks = [get_new_articles(base) for base in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    all_articles = []
    for r in results:
        if isinstance(r, list):
            all_articles.extend(r)
            
    if not all_articles:
        await status_message.edit_text("មិនទាន់មានព័ត៌មានថ្មីនៅពេលនេះទេ។")
        return
        
    # Grab the freshest article
    article = all_articles[0]
    url = article['url']
    image_url = article.get('image_url')
    title = article.get('title', 'News Article')
    
    # 2. Summarize & Translate concurrently
    short_summary = await asyncio.to_thread(extractive_summary, article.get('text', ''))
    km_title, km_text = await asyncio.gather(
        asyncio.to_thread(translate_text, title),
        asyncio.to_thread(translate_text, short_summary)
    )
    
    domain = urlparse(url).netloc.replace('www.', '')
    date_str = datetime.now().strftime("%d/%m/%Y")
    
    # 3. Smart NLP Metadata Analysis
    url_slug = url.strip('/').split('/')[-1].replace('-', ' ')
    analysis = analyze_article_metadata(km_title=km_title, km_text=km_text, en_title=url_slug)
    
    footer = f"🔗 <b>ប្រភព:</b> {domain}\n📅 {date_str}\n\n{analysis['hashtags']}"
    
    if analysis['is_hot']:
        header = f"🚨🔥 <b>ព័ត៌មានក្តៅគគុក (BREAKING NEWS)</b> 🔥🚨\n\n📰 <b>{km_title}</b>\n\n"
    else:
        header = f"📰 <b>{km_title}</b>\n\n"
    
    # 4. Format clean bullet points
    raw_km_text = km_text
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
    
    # 5. Fetch Image with upload action indicator
    image_bytes = None
    if image_url:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        from extractor import get_scraper
        try:
            def fetch_img():
                with get_scraper() as scraper:
                    res = scraper.get(image_url, timeout=8)
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
    if str(update.effective_chat.id) != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return
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
        try:
            await update.callback_query.edit_message_text(text, parse_mode='HTML', reply_markup=reply_markup)
        except Exception as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Failed to edit message: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button clicks from the inline keyboard with instant haptic/toast feedback."""
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id
    
    if data.startswith("toggle_"):
        cat = data.split("toggle_")[1]
        added = await storage.toggle_user_category(chat_id, cat)
        toast = f"✅ បានជ្រើសរើស៖ {cat}" if added else f"❌ បានដកចេញ៖ {cat}"
        await query.answer(toast)
        # Refresh menu instantly from memory cache
        await categories_menu(update, context)
    else:
        await query.answer()

async def inline_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline queries for searching news via DuckDuckGo."""
    query = update.inline_query.query
    if not query:
        return
        
    try:
        from duckduckgo_search import DDGS
        # Search DuckDuckGo News
        results = DDGS().news(query, max_results=5)
        
        inline_results = []
        for res in results:
            title = res.get('title', '')
            url = res.get('url', '')
            body = res.get('body', '')
            source = res.get('source', '')
            
            # Translate title to Khmer
            km_title = await asyncio.to_thread(translate_text, title, 'km')
            
            message_text = f"📰 <b>{km_title}</b>\n\n<i>{body}</i>\n\n🔗 <b>ប្រភព:</b> {source}\n<a href='{url}'>អានបន្ត / Read More</a>"
            
            inline_results.append(
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=km_title,
                    description=f"{source} - {title}",
                    input_message_content=InputTextMessageContent(
                        message_text,
                        parse_mode='HTML'
                    )
                )
            )
            
        await update.inline_query.answer(inline_results, cache_time=300)
    except Exception as e:
        logger.error(f"Inline search failed: {e}")

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set. Exiting.")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    
    # Hooks for DB
    application.post_init = on_startup

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("admin", admin))
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
