import os
import sys
# Add vendored packages for Wasmer Edge deployment
if os.path.exists('packages'):
    sys.path.insert(0, os.path.abspath('packages'))

import asyncio
import logging
from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from urllib.parse import urlparse
from datetime import datetime

import storage
from extractor import get_new_articles
from translator import translate_text
from summarizer import extractive_summary

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.environ.get('BOT_TOKEN')
BASE_URL = os.environ.get('BASE_URL')
CHECK_INTERVAL_MINUTES = int(os.environ.get('CHECK_INTERVAL_MINUTES', 5))

async def broadcast_to_user(bot: Bot, chat_id, summary, image_bytes, reply_markup=None):
    """Helper to send image + text to a single user."""
    try:
        # Telegram caption limit is 1024 characters.
        caption = summary[:1000] + "..." if len(summary) > 1024 else summary
        
        if image_bytes:
            try:
                await bot.send_photo(chat_id=chat_id, photo=image_bytes, caption=caption, parse_mode='HTML', reply_markup=reply_markup, read_timeout=20)
            except Exception as e:
                logger.warning(f"Failed to send photo to {chat_id}, falling back to text message: {e}")
                await bot.send_message(chat_id=chat_id, text=caption, parse_mode='HTML', reply_markup=reply_markup)
        else:
            await bot.send_message(chat_id=chat_id, text=caption, parse_mode='HTML', reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Failed to send to {chat_id}: {e}")

pipeline_lock = asyncio.Lock()

async def process_articles(bot: Bot):
    """Background job to fetch, summarize, and send articles using a Batch ETL Pipeline."""
    # Prevent concurrent execution of the pipeline (e.g. from rapid webhook triggers)
    if pipeline_lock.locked():
        logger.warning("Pipeline is already running. Skipping concurrent trigger to prevent spam.")
        return
        
    async with pipeline_lock:
        logger.info("Running scheduled article check pipeline...")
        
        # === STAGE 1: FETCH ===
        urls_to_check = await storage.get_base_urls()
        if BASE_URL and BASE_URL not in urls_to_check:
            urls_to_check.append(BASE_URL)
            
        if not urls_to_check:
            logger.warning("No base URLs configured. Add one via /addurl.")
            return
            
        all_new_articles = []
    try:
        # === STAGE 1: CONCURRENT I/O SCRAPING ===
        logger.info(f"Pipeline Stage 1: Concurrently scraping {len(urls_to_check)} websites...")
        scraping_tasks = [get_new_articles(base) for base in urls_to_check]
        results = await asyncio.gather(*scraping_tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                for article in result:
                    if not await storage.is_article_sent(article['hash']):
                        all_new_articles.append(article)
                        
        if not all_new_articles:
            logger.info("No new articles found.")
            return
            
        logger.info(f"Pipeline Stage 1: Extracted {len(all_new_articles)} new articles.")
        
        # === STAGE 2: SUMMARIZE ===
        logger.info("Pipeline Stage 2: Summarizing articles locally...")
        for article in all_new_articles:
            article['short_summary'] = await asyncio.to_thread(extractive_summary, article['text'])
            
        # === STAGE 3: TRANSLATE & VERIFY (Asynchronous Sub-Tasking) ===
        logger.info("Pipeline Stage 3: Translating & Verifying articles (Optimized Pacing)...")
        from extractor import verify_article_sources
        from telegraph_engine import get_telegraph_url
        
        for article in all_new_articles:
            url_slug = article['url'].strip('/').split('/')[-1].replace('-', ' ')
            article['en_title'] = url_slug
            
            # 1. Run Verification and Title Translation Concurrently
            km_title_task = asyncio.to_thread(translate_text, article.get('title', ''))
            verification_task = asyncio.to_thread(verify_article_sources, url_slug)
            
            article['km_title'], article['verification'] = await asyncio.gather(km_title_task, verification_task)
            await asyncio.sleep(2.0)
            
            # 2. Translate Summary
            article['km_text'] = await asyncio.to_thread(translate_text, article['short_summary'])
            await asyncio.sleep(2.0)
            
            # 3. Translate Full Text for Telegraph (Cap at 2500 chars)
            full_text = article.get('text', '')
            article['km_full_text'] = await asyncio.to_thread(translate_text, full_text[:2500])
            await asyncio.sleep(2.0)
            
            # 4. Generate Telegraph Page
            article['telegraph_url'] = await asyncio.to_thread(
                get_telegraph_url,
                article['km_title'],
                article['km_full_text'],
                article.get('image_url'),
                article['url']
            )
            
        # === STAGE 4: BROADCAST ===
        logger.info("Pipeline Stage 4: Broadcasting to users...")
        from categorizer import categorize_article, analyze_article_metadata
        
        # Massively optimize database performance by fetching all preferences in a single O(1) query
        subscribers = await storage.get_subscribers()
        all_user_prefs = await storage.get_all_user_categories()
        
        for article in all_new_articles:
            # Deep Multi-Factor NLP Analysis (weighted scoring, urgency, categories)
            analysis = analyze_article_metadata(
                km_title=article.get('km_title', ''),
                km_text=article.get('km_text', ''),
                en_title=article.get('en_title', '')
            )
            article_cats = analysis['categories']
            
            # Filter subscribers based on their category preferences in RAM instantly
            target_subscribers = []
            for sub_id in subscribers:
                user_cats = all_user_prefs.get(sub_id, [])
                # If user hasn't selected any categories, they receive everything
                if not user_cats:
                    target_subscribers.append(sub_id)
                # If article matched some categories, check for overlap
                elif any(c in user_cats for c in article_cats):
                    target_subscribers.append(sub_id)
                # If article matched NO categories, send it to everyone to be safe
                elif not article_cats:
                    target_subscribers.append(sub_id)
                    
            if not target_subscribers:
                # No one wants to read this article, mark as sent and skip
                await storage.mark_article_sent(article['hash'])
                continue
                
            url = article['url']
            domain = urlparse(url).netloc.replace('www.', '')
            date_str = datetime.now().strftime("%d/%m/%Y")
            
            verif = article.get('verification', {})
            if verif.get('verified'):
                status_badge = f"✅ បានបញ្ជាក់ដោយ {verif['sources']} ប្រភព (Verified)"
            else:
                status_badge = "⚠️ មិនមានប្រភពអន្តរជាតិ (Unverified)"
            
            hashtags = analysis['hashtags']
            footer = f"🔗 <b>ប្រភព:</b> {domain}\n🛡️ <b>បញ្ជាក់ប្រភព:</b> {status_badge}\n📅 {date_str}\n\n{hashtags}"
            
            if analysis['is_hot']:
                header = f"🚨🔥 <b>ព័ត៌មានក្តៅគគុក (BREAKING NEWS)</b> 🔥🚨\n\n📰 <b>{article['km_title']}</b>\n\n"
            else:
                header = f"📰 <b>{article['km_title']}</b>\n\n"
            
            # Format the translated summary into clean bullet points
            raw_km_text = article['km_text']
            # Split by the strict delimiter
            lines = [line.strip() for line in raw_km_text.split('|||') if line.strip()]
            
            clean_km_text = "<b>ចំណុចសំខាន់ៗ៖</b>\n"
            current_len = 0
            max_text_len = 950 - len(header) - len(footer)
            
            for line in lines:
                line = line.lstrip('•').lstrip('-').lstrip('*').lstrip('🔹').strip()
                
                # Prevent over-truncation
                if current_len + len(line) > max_text_len:
                    remaining = max_text_len - current_len
                    if remaining > 15:
                        clean_km_text += f"• {line[:remaining]}...\n"
                    break
                    
                clean_km_text += f"• {line}\n"
                current_len += len(line)
                
            summary = f"{header}{clean_km_text.strip()}\n\n{footer}"
            
            # Create interactive buttons (Stacked vertically)
            keyboard = []
            if article.get('telegraph_url'):
                keyboard.append([InlineKeyboardButton("⚡ អានអត្ថបទពេញ (Instant View)", url=article['telegraph_url'])])
            keyboard.append([InlineKeyboardButton("🔗 អានប្រភពដើម (Read Original)", url=url)])
            
            reply_markup = InlineKeyboardMarkup(keyboard)

            
            # Download image bytes
            image_bytes = None
            if article.get('image_url'):
                from extractor import get_scraper
                try:
                    def fetch_img():
                        with get_scraper() as scraper:
                            res = scraper.get(article['image_url'], timeout=10)
                            return res.content if res.status_code == 200 else None
                    image_bytes = await asyncio.to_thread(fetch_img)
                except Exception as e:
                    logger.warning(f"Failed to download image {article['image_url']}: {e}")
            
            # Ultra-fast broadcast: Upload image once and cache the file_id!
            cached_photo = image_bytes
            if image_bytes and target_subscribers:
                try:
                    first_user = target_subscribers[0]
                    msg = await bot.send_photo(chat_id=first_user, photo=image_bytes, caption=summary, parse_mode='HTML', reply_markup=reply_markup)
                    cached_photo = msg.photo[-1].file_id # Get Telegram's internal ID
                    target_subscribers = target_subscribers[1:] # Skip first user
                    logger.info(f"Successfully sent and cached photo for {first_user}")
                except Exception as e:
                    logger.warning(f"Failed to cache photo on first user {target_subscribers[0]}: {e}")

            # Broadcast to remaining subscribers concurrently in batches using the cached file_id
            batch_size = 20
            for i in range(0, len(target_subscribers), batch_size):
                batch = target_subscribers[i:i+batch_size]
                
                tasks = [
                    broadcast_to_user(bot, chat_id, summary, cached_photo, reply_markup)
                    for chat_id in batch
                ]
                await asyncio.gather(*tasks)
                
                if i + batch_size < len(target_subscribers):
                    await asyncio.sleep(1.0)
                    
            # Mark as sent only after successful broadcast
            await storage.mark_article_sent(article['hash'])
            await asyncio.sleep(1.5) # Pause between sending different articles to users
            
        logger.info("Pipeline successfully completed.")
        
    except Exception as e:
        logger.error(f"Error in process_articles job: {e}")

from aiohttp import web

# Keep strong references to background tasks so they don't get garbage collected
active_tasks = set()

async def health_check(request):
    """Health check endpoint for Render."""
    return web.Response(text="OK")

async def webhook_handler(request):
    """Handle incoming GET requests to trigger a scrape immediately."""
    logger.info("Received external webhook trigger!")
    bot = request.app['bot']
    # Trigger in background so we return HTTP 200 immediately
    task = asyncio.create_task(process_articles(bot))
    active_tasks.add(task)
    task.add_done_callback(active_tasks.discard)
    return web.Response(text="Scrape triggered successfully!")

async def send_daily_digest(bot: Bot):
    """Sends a summary of the top news of the morning to all users."""
    try:
        logger.info("Generating Morning Daily Digest...")
        # Get subscribers
        subscribers = await storage.get_subscribers()
        if not subscribers:
            return
            
        urls = await storage.get_base_urls()
        digest_text = "🌅 <b>សង្ខេបព័ត៌មានប្រចាំថ្ងៃ (Morning Daily Digest)</b>\n\n"
        
        # Scrape 3 top articles fresh from the sources
        articles_added = 0
        for url in urls[:2]:
            articles = await get_new_articles(url)
            for art in articles[:2]:
                title = await asyncio.to_thread(translate_text, art['en_title'], 'km')
                digest_text += f"🔹 <a href='{art['url']}'>{title}</a>\n"
                articles_added += 1
                
        if articles_added == 0:
            return
            
        digest_text += "\n<i>សូមជូនពរឱ្យអ្នកមានថ្ងៃដ៏ល្អ! ☀️</i>"
        
        # Broadcast to everyone
        for chat_id in subscribers:
            try:
                await bot.send_message(chat_id=chat_id, text=digest_text, parse_mode='HTML', disable_web_page_preview=True)
                await asyncio.sleep(0.5)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Failed to send digest: {e}")

async def background_scheduler(bot: Bot):
    """The original background polling loop."""
    logger.info(f"Background scheduler started. Polling every {CHECK_INTERVAL_MINUTES} minutes.")
    
    digest_sent_date = None
    
    while True:
        now = datetime.now()
        # Send Daily Digest at 8:00 AM Cambodia time (UTC+7 usually, assuming server is on same timezone)
        if now.hour == 8 and now.minute < CHECK_INTERVAL_MINUTES:
            if digest_sent_date != now.date():
                await send_daily_digest(bot)
                digest_sent_date = now.date()
                
        await process_articles(bot)
        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set.")
        return

    logger.info("Starting Webhook, Scheduler, and Telegram Bot...")
    
    # 1. Start the aiohttp web server IMMEDIATELY so Render detects the open port
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/trigger', webhook_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"Webhook server listening on http://0.0.0.0:{port}/trigger")

    # 2. Build Telegram Application and attach handlers
    import bot as bot_module
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, InlineQueryHandler
    
    application = Application.builder().token(BOT_TOKEN).build()
    app['bot'] = application.bot # Attach bot to web app after building
    
    application.add_handler(CommandHandler("start", bot_module.start))
    application.add_handler(CommandHandler("stop", bot_module.stop))
    application.add_handler(CommandHandler("status", bot_module.status))
    application.add_handler(CommandHandler("broadcast", bot_module.broadcast))
    application.add_handler(CommandHandler("addurl", bot_module.addurl))
    application.add_handler(CommandHandler("removeurl", bot_module.removeurl))
    application.add_handler(CommandHandler("listurls", bot_module.listurls))
    application.add_handler(CommandHandler("stats", bot_module.bot_stats))
    application.add_handler(CommandHandler("latest", bot_module.latest))
    application.add_handler(CommandHandler("categories", bot_module.categories_menu))
    application.add_handler(CallbackQueryHandler(bot_module.button_handler))
    application.add_handler(InlineQueryHandler(bot_module.inline_search))
    
    # Initialize and start the Telegram bot
    await application.initialize()
    await application.start()
    
    # Call the on_startup hook to init DB and set commands
    await bot_module.on_startup(application)
    
    # Start polling for commands
    await application.updater.start_polling()
    logger.info("Telegram Bot Polling started!")
    
    # 3. Start the heavy background polling loop last
    bg_task = asyncio.create_task(background_scheduler(application.bot))
    active_tasks.add(bg_task)
    
    logger.info("System fully operational!")
    
    # Keep the main process alive
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker shut down gracefully by user (Ctrl+C).")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
