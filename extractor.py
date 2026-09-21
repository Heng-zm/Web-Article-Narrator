import trafilatura
from readability import Document
from urllib.parse import urljoin, urlparse
import hashlib
import logging
from bs4 import BeautifulSoup
import cloudscraper
import asyncio
from requests.adapters import HTTPAdapter
import feedparser
from duckduckgo_search import DDGS
import re
import warnings

# Suppress the harmless duckduckgo_search renaming warning
warnings.filterwarnings("ignore", category=RuntimeWarning, module="duckduckgo_search")

def verify_article_sources(english_title: str) -> dict:
    """Uses DuckDuckGo to search the English title and find verification across global sources."""
    if not english_title:
        return {"verified": False, "sources": 0}
        
    try:
        results = DDGS().text(english_title, max_results=5)
        # Trusted domains
        trusted = ['reuters.com', 'apnews.com', 'bbc.com', 'cnn.com', 'bloomberg.com', 'aljazeera.com', 'nytimes.com']
        
        found_trusted = set()
        for res in results:
            url = res.get('href', '').lower()
            for t in trusted:
                if t in url:
                    found_trusted.add(t)
                    
        return {
            "verified": len(found_trusted) > 0,
            "sources": len(found_trusted)
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Verification failed for {english_title}: {e}")
        return {"verified": False, "sources": 0}

logger = logging.getLogger(__name__)

def get_scraper():
    """Returns a fresh CloudScraper instance with ultra-realistic human headers."""
    import random
    
    # Randomize browser versions slightly
    browsers = ['chrome', 'firefox']
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': random.choice(browsers),
            'platform': 'windows',
            'desktop': True
        }
    )
    
    # Inject deep human-like headers (removed 'br' because requests lacks native brotli support)
    scraper.headers.update({
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,km;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-Fetch-User': '?1',
        'DNT': '1',
        'Cache-Control': 'max-age=0',
        'Referer': 'https://www.google.com/'
    })
    
    # Configure pool to avoid warnings during concurrent batches
    adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50)
    scraper.mount('http://', adapter)
    scraper.mount('https://', adapter)
    return scraper

def generate_hash(text: str) -> str:
    """Generates a SHA-256 hash for a given text (usually URL)."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def fetch_url_sync(url: str) -> str:
    with get_scraper() as scraper:
        response = scraper.get(url, timeout=15)
        response.raise_for_status()
        return response.text

async def fetch_url(url: str) -> str:
    """Fetches HTML content of a URL asynchronously, bypassing Cloudflare."""
    try:
        return await asyncio.to_thread(fetch_url_sync, url)
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None

def sanitize_html(html: str) -> str:
    """Remove NULL bytes and XML-incompatible control characters from HTML."""
    if not html:
        return html
    # Strip NULL bytes and C0/C1 control chars except tab, newline, carriage return
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', html)

def extract_article_text(html: str) -> str:
    """Extracts article text from HTML using trafilatura, fallback to readability."""
    try:
        html = sanitize_html(html)
        text = trafilatura.extract(html, include_links=False, include_images=False, include_comments=False)
        if text:
            return text
            
        # Fallback to readability-lxml
        doc = Document(html)
        # The summary contains HTML, so we strip tags with BeautifulSoup
        soup = BeautifulSoup(doc.summary(), 'lxml')
        text = soup.get_text(separator='\n')
        return text.strip()
    except Exception as e:
        logger.error(f"Failed to extract text: {e}")
        return None

def is_listing_page(html: str, base_url: str) -> list:
    """
    Heuristic to extract fresh article links from a homepage or listing page.
    Compatible with Khmer continuous text, English word boundaries, and news URL paths.
    """
    soup = BeautifulSoup(html, 'lxml')
    links = soup.find_all('a', href=True)
    base_domain = urlparse(base_url).netloc.replace('www.', '')
    
    article_links = []
    seen = set()
    excluded = ('/about', '/contact', '/privacy', '/terms', '/login', '/register', '/search', '/tag/', '/category/', '/author/')
    
    for link in links:
        href = link.get('href', '').strip()
        text = link.get_text(strip=True)
        if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
            continue
            
        full_url = urljoin(base_url, href).split('?')[0].split('#')[0].rstrip('/')
        if full_url in seen or full_url == base_url.rstrip('/'):
            continue
            
        link_domain = urlparse(full_url).netloc.replace('www.', '')
        if base_domain not in link_domain:
            continue
            
        path = urlparse(full_url).path.lower()
        if any(ex in path for ex in excluded):
            continue
            
        word_count = len(text.split())
        char_count = len(text)
        has_news_slug = bool(re.search(r'/(news|article|story|post|detail|\d{4}/\d{2}|\d+)/', path))
        
        if (word_count >= 3 or char_count >= 12 or has_news_slug) and char_count >= 6:
            seen.add(full_url)
            article_links.append(full_url)
            
    return article_links[:15]

def extract_metadata(html: str, base_url: str) -> tuple:
    """Parses HTML once to extract both title and main image."""
    title = "ព័ត៌មានថ្មី (New Article)"
    image_url = None
    try:
        soup = BeautifulSoup(html, 'lxml')
        
        # Extract title
        meta_title = soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            title = meta_title['content']
        elif soup.title and soup.title.string:
            title = soup.title.string
            
        # Extract image
        meta_og = soup.find('meta', property='og:image')
        if meta_og and meta_og.get('content'):
            image_url = urljoin(base_url, meta_og['content'])
            
    except Exception as e:
        logger.error(f"Metadata extraction error: {e}")
        
    return title, image_url

async def get_new_articles(base_url: str) -> list:
    """
    Main entry point for real-time extraction.
    Ultra-Fast & Resource-Efficient:
    1. Checks RSS feed or HTML homepage.
    2. Filters out already-sent articles in RAM BEFORE downloading full page HTML.
    3. Only downloads full content for TRULY NEW articles.
    """
    import storage
    
    html = await fetch_url(base_url)
    if not html:
        return []

    try:
        # 1. Check for RSS feed link in HTML head or default /feed
        rss_candidates = []
        soup = BeautifulSoup(html, 'lxml')
        rss_meta = soup.find('link', type=lambda t: t and ('rss' in t or 'atom' in t))
        if rss_meta and rss_meta.get('href'):
            rss_candidates.append(urljoin(base_url, rss_meta['href']))
        rss_candidates.append(base_url.rstrip('/') + '/feed')
        rss_candidates.append(base_url.rstrip('/') + '/rss')

        feed_data = None
        for r_url in rss_candidates[:2]:
            feed_xml = await fetch_url(r_url)
            if feed_xml and ('<rss' in feed_xml or '<feed' in feed_xml):
                feed_data = feedparser.parse(feed_xml)
                if feed_data and feed_data.entries:
                    break

        # If RSS feed is available
        if feed_data and feed_data.entries:
            articles = []
            for entry in feed_data.entries[:5]:
                link = getattr(entry, 'link', None)
                if not link:
                    continue
                clean_link = link.split('?')[0]
                url_hash = generate_hash(clean_link)
                # Skip in RAM if already sent!
                if await storage.is_article_sent(url_hash):
                    continue
                    
                title = getattr(entry, 'title', 'ព័ត៌មានថ្មី')
                desc = getattr(entry, 'description', '')
                
                # Fetch full article HTML only for truly new ones
                page_html = await fetch_url(link)
                meta_title, image_url = extract_metadata(page_html, base_url) if page_html else (title, None)
                article_text = extract_article_text(page_html) if page_html else desc
                
                articles.append({
                    'url': link,
                    'title': title,
                    'text': article_text if article_text else desc,
                    'hash': url_hash,
                    'image_url': image_url
                })
            if articles:
                return articles

        # 2. Fallback to HTML Listing Extraction with RAM pre-filtering
        links = is_listing_page(html, base_url)
        if links:
            # Pre-filter: only keep links that have NOT been sent yet
            unsent_links = []
            for link in links:
                h = generate_hash(link.split('?')[0])
                if not await storage.is_article_sent(h):
                    unsent_links.append(link)
                    
            if not unsent_links:
                return []  # Zero new articles -> return instantly in 0.01s!
                
            logger.info(f"[{base_url}] Found {len(unsent_links)} brand new articles to process.")
            
            async def fetch_and_extract(link):
                article_html = await fetch_url(link)
                if article_html:
                    text = await asyncio.to_thread(extract_article_text, article_html)
                    title, image_url = await asyncio.to_thread(extract_metadata, article_html, link)
                    if text and len(text) > 80:
                        return {
                            'url': link,
                            'title': title,
                            'text': text,
                            'hash': generate_hash(link.split('?')[0]),
                            'image_url': image_url
                        }
                return None

            tasks = [fetch_and_extract(link) for link in unsent_links[:3]]
            results = await asyncio.gather(*tasks)
            return [r for r in results if r is not None]
        else:
            # Single article page
            single_hash = generate_hash(base_url.split('?')[0])
            if await storage.is_article_sent(single_hash):
                return []
            text = await asyncio.to_thread(extract_article_text, html)
            title, image_url = await asyncio.to_thread(extract_metadata, html, base_url)
            if text and len(text) > 80:
                return [{
                    'url': base_url,
                    'title': title,
                    'text': text,
                    'hash': single_hash,
                    'image_url': image_url
                }]
            return []

    except Exception as e:
        logger.error(f"Failed to extract new articles from {base_url}: {e}")
        return []
