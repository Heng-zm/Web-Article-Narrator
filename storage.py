import os
import aiosqlite
import logging
import asyncio
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)

# --- SUPABASE CLIENT ---
_supabase = None
if USE_SUPABASE:
    try:
        from supabase import create_client, Client
        _supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Using Supabase (PostgreSQL) for storage.")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        USE_SUPABASE = False

# --- SQLITE FALLBACK ---
if not USE_SUPABASE:
    logger.info("Using local SQLite for storage.")
    if os.path.exists('/data'):
        DB_FILE = '/data/bot_database.db'
    else:
        DB_FILE = 'bot_database.db'
_conn = None

async def init_db():
    if USE_SUPABASE:
        return
        
    global _conn
    try:
        if _conn is None:
            _conn = await aiosqlite.connect(DB_FILE)
            
        await _conn.execute('''CREATE TABLE IF NOT EXISTS subscribers (chat_id INTEGER PRIMARY KEY)''')
        await _conn.execute('''CREATE TABLE IF NOT EXISTS sent_articles (url_hash TEXT PRIMARY KEY, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        await _conn.execute('''CREATE TABLE IF NOT EXISTS base_urls (url TEXT PRIMARY KEY)''')
        await _conn.execute('''CREATE TABLE IF NOT EXISTS user_categories (chat_id INTEGER, category TEXT, PRIMARY KEY (chat_id, category))''')
        await _conn.commit()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

# --- BASE URLS ---
async def add_base_url(url: str):
    if USE_SUPABASE:
        try:
            await asyncio.to_thread(lambda: _supabase.table('base_urls').upsert({'url': url}).execute())
        except Exception as e:
            logger.error(f"Supabase add_base_url error: {e}")
    else:
        try:
            await _conn.execute('INSERT OR IGNORE INTO base_urls (url) VALUES (?)', (url,))
            await _conn.commit()
        except Exception as e:
            logger.error(f"Failed to add base url {url}: {e}")

async def get_base_urls() -> list:
    if USE_SUPABASE:
        try:
            res = await asyncio.to_thread(lambda: _supabase.table('base_urls').select('url').execute())
            return [r['url'] for r in res.data]
        except Exception as e:
            logger.error(f"Supabase get_base_urls error: {e}")
            return []
    else:
        try:
            async with _conn.execute('SELECT url FROM base_urls') as cursor:
                records = await cursor.fetchall()
                return [r[0] for r in records]
        except Exception as e:
            logger.error(f"Failed to get base urls: {e}")
            return []

async def remove_base_url(url: str):
    if USE_SUPABASE:
        try:
            await asyncio.to_thread(lambda: _supabase.table('base_urls').delete().eq('url', url).execute())
        except Exception as e:
            logger.error(f"Supabase remove_base_url error: {e}")
    else:
        try:
            await _conn.execute('DELETE FROM base_urls WHERE url = ?', (url,))
            await _conn.commit()
        except Exception as e:
            logger.error(f"Failed to remove base url {url}: {e}")

# --- IN-MEMORY CACHE FOR ULTRA-FAST RESPONSIVENESS ---
_user_categories_cache = {}  # chat_id -> set of categories
_subscribers_cache = None    # set of subscriber chat_ids

# --- SUBSCRIBERS ---
async def add_subscriber(chat_id: int):
    global _subscribers_cache
    if _subscribers_cache is not None:
        _subscribers_cache.add(chat_id)
        
    if USE_SUPABASE:
        try:
            await asyncio.to_thread(lambda: _supabase.table('subscribers').upsert({'chat_id': chat_id}).execute())
        except Exception as e:
            logger.error(f"Supabase add_subscriber error: {e}")
    else:
        try:
            await _conn.execute('INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)', (chat_id,))
            await _conn.commit()
        except Exception as e:
            logger.error(f"Failed to add subscriber {chat_id}: {e}")

async def remove_subscriber(chat_id: int):
    global _subscribers_cache
    if _subscribers_cache is not None:
        _subscribers_cache.discard(chat_id)
    _user_categories_cache.pop(chat_id, None)
    
    if USE_SUPABASE:
        try:
            await asyncio.to_thread(lambda: _supabase.table('subscribers').delete().eq('chat_id', chat_id).execute())
            # Clean up categories too
            await asyncio.to_thread(lambda: _supabase.table('user_categories').delete().eq('chat_id', chat_id).execute())
        except Exception as e:
            logger.error(f"Supabase remove_subscriber error: {e}")
    else:
        try:
            await _conn.execute('DELETE FROM subscribers WHERE chat_id = ?', (chat_id,))
            await _conn.execute('DELETE FROM user_categories WHERE chat_id = ?', (chat_id,))
            await _conn.commit()
        except Exception as e:
            logger.error(f"Failed to remove subscriber {chat_id}: {e}")

async def get_subscribers() -> list:
    global _subscribers_cache
    if _subscribers_cache is not None:
        return list(_subscribers_cache)

    if USE_SUPABASE:
        try:
            res = await asyncio.to_thread(lambda: _supabase.table('subscribers').select('chat_id').execute())
            _subscribers_cache = set(r['chat_id'] for r in res.data)
            return list(_subscribers_cache)
        except Exception as e:
            logger.error(f"Supabase get_subscribers error: {e}")
            return []
    else:
        try:
            async with _conn.execute('SELECT chat_id FROM subscribers') as cursor:
                records = await cursor.fetchall()
                _subscribers_cache = set(r[0] for r in records)
                return list(_subscribers_cache)
        except Exception as e:
            logger.error(f"Failed to get subscribers: {e}")
            return []

# --- SENT ARTICLES ---
async def is_article_sent(url_hash: str) -> bool:
    if USE_SUPABASE:
        try:
            res = await asyncio.to_thread(lambda: _supabase.table('sent_articles').select('url_hash').eq('url_hash', url_hash).execute())
            return len(res.data) > 0
        except Exception as e:
            logger.error(f"Supabase is_article_sent error: {e}")
            return False
    else:
        try:
            async with _conn.execute('SELECT 1 FROM sent_articles WHERE url_hash = ?', (url_hash,)) as cursor:
                record = await cursor.fetchone()
                return bool(record)
        except Exception as e:
            return False

async def mark_article_sent(url_hash: str):
    if USE_SUPABASE:
        try:
            await asyncio.to_thread(lambda: _supabase.table('sent_articles').upsert({'url_hash': url_hash}).execute())
        except Exception as e:
            logger.error(f"Supabase mark_article_sent error: {e}")
    else:
        try:
            await _conn.execute('INSERT OR IGNORE INTO sent_articles (url_hash) VALUES (?)', (url_hash,))
            await _conn.commit()
        except Exception as e:
            logger.error(f"Failed to mark article as sent {url_hash}: {e}")

async def get_sent_articles_count() -> int:
    if USE_SUPABASE:
        try:
            res = await asyncio.to_thread(lambda: _supabase.table('sent_articles').select('*', count='exact').execute())
            return res.count if res.count else 0
        except Exception as e:
            return 0
    else:
        try:
            async with _conn.execute('SELECT COUNT(*) FROM sent_articles') as cursor:
                val = await cursor.fetchone()
                return val[0] if val else 0
        except Exception as e:
            return 0

# --- USER CATEGORIES (CACHED) ---
async def get_user_categories(chat_id: int) -> list:
    if chat_id in _user_categories_cache:
        return list(_user_categories_cache[chat_id])

    if USE_SUPABASE:
        try:
            res = await asyncio.to_thread(lambda: _supabase.table('user_categories').select('category').eq('chat_id', chat_id).execute())
            cats = set(r['category'] for r in res.data)
            _user_categories_cache[chat_id] = cats
            return list(cats)
        except Exception as e:
            return []
    else:
        try:
            async with _conn.execute('SELECT category FROM user_categories WHERE chat_id = ?', (chat_id,)) as cursor:
                records = await cursor.fetchall()
                cats = set(r[0] for r in records)
                _user_categories_cache[chat_id] = cats
                return list(cats)
        except Exception as e:
            return []

async def get_all_user_categories() -> dict:
    if USE_SUPABASE:
        try:
            res = await asyncio.to_thread(lambda: _supabase.table('user_categories').select('chat_id, category').execute())
            mapping = {}
            for row in res.data:
                cid = row['chat_id']
                if cid not in mapping:
                    mapping[cid] = []
                mapping[cid].append(row['category'])
                
            for cid, cats in mapping.items():
                _user_categories_cache[cid] = set(cats)
            return mapping
        except Exception as e:
            return {cid: list(cats) for cid, cats in _user_categories_cache.items()}
    else:
        try:
            async with _conn.execute('SELECT chat_id, category FROM user_categories') as cursor:
                records = await cursor.fetchall()
                mapping = {}
                for chat_id, category in records:
                    if chat_id not in mapping:
                        mapping[chat_id] = []
                    mapping[chat_id].append(category)
                    
                for cid, cats in mapping.items():
                    _user_categories_cache[cid] = set(cats)
                return mapping
        except Exception as e:
            return {cid: list(cats) for cid, cats in _user_categories_cache.items()}

async def toggle_user_category(chat_id: int, category: str) -> bool:
    # 1. Instant Cache Update for zero-latency response
    current = set(await get_user_categories(chat_id))
    if category in current:
        current.remove(category)
        added = False
    else:
        current.add(category)
        added = True
    _user_categories_cache[chat_id] = current

    # 2. Asynchronous DB Persistence in background
    if USE_SUPABASE:
        try:
            if not added:
                await asyncio.to_thread(lambda: _supabase.table('user_categories').delete().eq('chat_id', chat_id).eq('category', category).execute())
            else:
                await asyncio.to_thread(lambda: _supabase.table('user_categories').upsert({'chat_id': chat_id, 'category': category}).execute())
        except Exception as e:
            logger.error(f"Supabase toggle_user_category error: {e}")
    else:
        try:
            if not added:
                await _conn.execute('DELETE FROM user_categories WHERE chat_id = ? AND category = ?', (chat_id, category))
            else:
                await _conn.execute('INSERT INTO user_categories (chat_id, category) VALUES (?, ?)', (chat_id, category))
            await _conn.commit()
        except Exception as e:
            logger.error(f"SQLite toggle_user_category error: {e}")
            
    return added

async def get_category_stats() -> dict:
    """Returns {category: user_count} for admin dashboard."""
    all_prefs = await get_all_user_categories()
    stats = {}
    for chat_id, cats in all_prefs.items():
        for cat in cats:
            stats[cat] = stats.get(cat, 0) + 1
    return dict(sorted(stats.items(), key=lambda x: x[1], reverse=True))

# --- STATS ---
async def get_stats() -> dict:
    try:
        if USE_SUPABASE:
            s_res = await asyncio.to_thread(lambda: _supabase.table('subscribers').select('*', count='exact').execute())
            subs_count = s_res.count if s_res.count else 0
            return {'subscribers': subs_count, 'articles': await get_sent_articles_count()}
        else:
            async with _conn.execute('SELECT COUNT(*) FROM subscribers') as cursor:
                subs_count = (await cursor.fetchone())[0]
            return {'subscribers': subs_count, 'articles': await get_sent_articles_count()}
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return {'subscribers': 0, 'articles': 0}

# --- IN-MEMORY ARTICLE CACHE (INDEXED BY CATEGORY) ---
_articles_by_category = {}  # category -> list of processed article dicts
_all_recent_articles = []   # list of all recent article dicts (max 50)
_user_last_action = {}      # chat_id -> timestamp

def is_user_throttled(chat_id: int, min_interval_seconds: float = 2.0) -> bool:
    """Debounce helper: Returns True if user actions are too rapid to prevent server overload."""
    import time
    now = time.time()
    last = _user_last_action.get(chat_id, 0)
    if now - last < min_interval_seconds:
        return True
    _user_last_action[chat_id] = now
    return False

def store_processed_articles(articles: list):
    """
    Stores processed, translated, categorized articles in RAM.
    Guarantees instant responses for hundreds of concurrent users without re-scraping.
    """
    global _all_recent_articles, _articles_by_category
    for art in articles:
        if not art or not art.get('url'):
            continue
        existing_urls = {a['url'] for a in _all_recent_articles}
        if art['url'] not in existing_urls:
            _all_recent_articles.insert(0, art)
            
        cats = art.get('categories', [])
        for cat in cats:
            if cat not in _articles_by_category:
                _articles_by_category[cat] = []
            cat_urls = {a['url'] for a in _articles_by_category[cat]}
            if art['url'] not in cat_urls:
                _articles_by_category[cat].insert(0, art)
                _articles_by_category[cat] = _articles_by_category[cat][:25]

    _all_recent_articles = _all_recent_articles[:50]

def get_articles_for_categories(user_cats: list, limit: int = 3) -> list:
    """
    Returns articles matching ANY of the user's chosen categories.
    Guarantees STRICT category separation: only matching articles are returned.
    """
    if not user_cats:
        return _all_recent_articles[:limit]
        
    matched = []
    seen_urls = set()
    for cat in user_cats:
        for art in _articles_by_category.get(cat, []):
            if art['url'] not in seen_urls:
                seen_urls.add(art['url'])
                matched.append(art)
                if len(matched) >= limit:
                    return matched
    return matched

def get_cached_recent_articles(limit: int = 10) -> list:
    """Returns most recent processed articles from memory."""
    return _all_recent_articles[:limit]

