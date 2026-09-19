import trafilatura
from readability import Document
from urllib.parse import urljoin
import hashlib
import logging
from bs4 import BeautifulSoup
import cloudscraper
import asyncio
from requests.adapters import HTTPAdapter
import feedparser
from duckduckgo_search import DDGS

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

def extract_article_text(html: str) -> str:
    """Extracts article text from HTML using trafilatura, fallback to readability."""
    try:
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
    Heuristic to determine if a page is a listing and return potential article links.
    Returns a list of URLs if it's a listing, otherwise empty list.
    """
    soup = BeautifulSoup(html, 'lxml')
    links = soup.find_all('a', href=True)
    
    article_links = set()
    # Simple heuristic: if a link's text is long enough and href is on the same domain, it might be an article
    for link in links:
        href = link.get('href')
        text = link.get_text(strip=True)
        if len(text.split()) > 4: # Likely a title
            full_url = urljoin(base_url, href)
            # Basic domain check, to avoid external links
            if base_url.split('/')[2] in full_url:
                article_links.add(full_url)
                
    # If we found multiple links that look like articles, it's a listing page
    if len(article_links) > 2:
        return list(article_links)
    return []

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
    Main entry point for extraction.
    Returns a list of dicts: [{'url': str, 'title': str, 'text': str, 'hash': str, 'image_url': str}]
    """
    html = await fetch_url(base_url)
    if not html:
        return []

    articles = []
    
    # Check if listing page
    links = is_listing_page(html, base_url)
    
    try:
        # Check RSS first
        rss_url = base_url.rstrip('/') + '/feed'
        html = await fetch_url(rss_url)
        
        # Determine if it's actually XML/RSS
        if html and ('<rss' in html or '<feed' in html):
            logger.info(f"Found RSS feed for {base_url}")
            feed = feedparser.parse(html)
            
            articles = []
            for entry in feed.entries[:3]:
                link = entry.link
                title = entry.title
                text = entry.get('description', '')
                
                # Fetch to get proper image if needed
                page_html = await fetch_url(link)
                meta_title, image_url = extract_metadata(page_html, base_url) if page_html else (title, None)
                article_text = extract_article_text(page_html) if page_html else text
                
                articles.append({
                    'url': link,
                    'title': title,
                    'text': article_text if article_text else text,
                    'hash': generate_hash(link.split('?')[0]),
                    'image_url': image_url
                })
            return articles

        # Fallback to HTML
        logger.info(f"No RSS found, falling back to HTML scraping for {base_url}")
        html = await fetch_url(base_url)
        if not html:
            return []

        articles = []
        
        async def fetch_and_extract(link):
            article_html = await fetch_url(link)
            if article_html:
                text = await asyncio.to_thread(extract_article_text, article_html)
                title, image_url = await asyncio.to_thread(extract_metadata, article_html, link)
                
                if text and len(text) > 100: # Ensure it's not empty or tiny
                    return {
                        'url': link,
                        'title': title,
                        'text': text,
                        'hash': generate_hash(link.split('?')[0]),
                        'image_url': image_url
                    }
            return None

        # Check if listing page
        links = is_listing_page(html, base_url)
        
        if links:
            logger.info(f"Detected listing page. Found {len(links)} potential articles.")
            # Only process a few to avoid spamming if it's a huge listing
            tasks = [fetch_and_extract(link) for link in links[:3]]
            results = await asyncio.gather(*tasks)
            articles = [r for r in results if r is not None]
        else:
            logger.info("Detected single article page.")
            text = await asyncio.to_thread(extract_article_text, html)
            title, image_url = await asyncio.to_thread(extract_metadata, html, base_url)
            
            if text and len(text) > 100:
                articles.append({
                    'url': base_url,
                    'title': title,
                    'text': text,
                    'hash': generate_hash(base_url),
                    'image_url': image_url
                })
                
        return articles

    except Exception as e:
        logger.error(f"Failed to extract new articles: {e}")
        return []
