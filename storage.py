import os
import aiosqlite
import logging
import asyncio

logger = logging.getLogger(__name__)

# Use persistent volume if on Wasmer, otherwise use local directory
if os.path.exists('/data'):
    DB_FILE = '/data/bot_database.db'
else:
    DB_FILE = 'bot_database.db'

_conn = None

async def init_db():
    """Initialize SQLite database tables and keep connection open."""
    global _conn
    try:
        if _conn is None:
            _conn = await aiosqlite.connect(DB_FILE)
            
        await _conn.execute('''
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY
            )
        ''')
        await _conn.execute('''
            CREATE TABLE IF NOT EXISTS sent_articles (
                url_hash TEXT PRIMARY KEY,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await _conn.execute('''
            CREATE TABLE IF NOT EXISTS base_urls (
                url TEXT PRIMARY KEY
            )
        ''')
        await _conn.execute('''
            CREATE TABLE IF NOT EXISTS user_categories (
                chat_id INTEGER,
                category TEXT,
                PRIMARY KEY (chat_id, category)
            )
        ''')
        await _conn.commit()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

async def add_base_url(url: str):
    try:
        await _conn.execute('INSERT OR IGNORE INTO base_urls (url) VALUES (?)', (url,))
        await _conn.commit()
    except Exception as e:
        logger.error(f"Failed to add base url {url}: {e}")

async def get_base_urls() -> list:
    try:
        async with _conn.execute('SELECT url FROM base_urls') as cursor:
            records = await cursor.fetchall()
            return [r[0] for r in records]
    except Exception as e:
        logger.error(f"Failed to get base urls: {e}")
        return []

async def remove_base_url(url: str):
    try:
        await _conn.execute('DELETE FROM base_urls WHERE url = ?', (url,))
        await _conn.commit()
    except Exception as e:
        logger.error(f"Failed to remove base url {url}: {e}")

async def get_stats() -> dict:
    try:
        async with _conn.execute('SELECT COUNT(*) FROM subscribers') as cursor:
            subs_count = (await cursor.fetchone())[0]
        async with _conn.execute('SELECT COUNT(*) FROM sent_articles') as cursor:
            arts_count = (await cursor.fetchone())[0]
        return {'subscribers': subs_count, 'articles': arts_count}
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return {'subscribers': 0, 'articles': 0}

async def add_subscriber(chat_id: int):
    try:
        await _conn.execute('INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)', (chat_id,))
        await _conn.commit()
    except Exception as e:
        logger.error(f"Failed to add subscriber {chat_id}: {e}")

async def remove_subscriber(chat_id: int):
    try:
        await _conn.execute('DELETE FROM subscribers WHERE chat_id = ?', (chat_id,))
        await _conn.commit()
    except Exception as e:
        logger.error(f"Failed to remove subscriber {chat_id}: {e}")

async def get_subscribers() -> list:
    try:
        async with _conn.execute('SELECT chat_id FROM subscribers') as cursor:
            records = await cursor.fetchall()
            return [r[0] for r in records]
    except Exception as e:
        logger.error(f"Failed to get subscribers: {e}")
        return []

async def is_article_sent(url_hash: str) -> bool:
    try:
        async with _conn.execute('SELECT 1 FROM sent_articles WHERE url_hash = ?', (url_hash,)) as cursor:
            record = await cursor.fetchone()
            return bool(record)
    except Exception as e:
        logger.error(f"Failed to check sent article {url_hash}: {e}")
        return False

async def mark_article_sent(url_hash: str):
    try:
        await _conn.execute('INSERT OR IGNORE INTO sent_articles (url_hash) VALUES (?)', (url_hash,))
        await _conn.commit()
    except Exception as e:
        logger.error(f"Failed to mark article as sent {url_hash}: {e}")

async def get_sent_articles_count() -> int:
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            async with conn.execute('SELECT COUNT(*) FROM sent_articles') as cursor:
                val = await cursor.fetchone()
                return val[0] if val else 0
    except Exception as e:
        logger.error(f"Failed to get sent articles count: {e}")
        return 0

async def get_user_categories(chat_id: int) -> list:
    """Returns a list of selected categories for a user."""
    try:
        async with _conn.execute('SELECT category FROM user_categories WHERE chat_id = ?', (chat_id,)) as cursor:
            records = await cursor.fetchall()
            return [r[0] for r in records]
    except Exception as e:
        logger.error(f"Failed to get categories for {chat_id}: {e}")
        return []

async def get_all_user_categories() -> dict:
    """Returns a dictionary mapping chat_ids to their selected categories. Solves N+1 query problem."""
    try:
        async with _conn.execute('SELECT chat_id, category FROM user_categories') as cursor:
            records = await cursor.fetchall()
            mapping = {}
            for chat_id, category in records:
                if chat_id not in mapping:
                    mapping[chat_id] = []
                mapping[chat_id].append(category)
            return mapping
    except Exception as e:
        logger.error(f"Failed to get all user categories: {e}")
        return {}

async def toggle_user_category(chat_id: int, category: str) -> bool:
    """Toggles a category for a user. Returns True if added, False if removed."""
    try:
        current = await get_user_categories(chat_id)
        if category in current:
            await _conn.execute('DELETE FROM user_categories WHERE chat_id = ? AND category = ?', (chat_id, category))
            added = False
        else:
            await _conn.execute('INSERT INTO user_categories (chat_id, category) VALUES (?, ?)', (chat_id, category))
            added = True
        await _conn.commit()
        return added
    except Exception as e:
        logger.error(f"Failed to toggle category {category} for {chat_id}: {e}")
        return False
