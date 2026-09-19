import logging
import re
import time
import requests

logger = logging.getLogger(__name__)

def is_khmer(text: str) -> bool:
    """Check if text contains Khmer characters."""
    return bool(re.search(r'[\u1780-\u17FF]', text))

def translate_chunk(chunk: str, target_lang: str = 'km') -> str:
    """Translates a small chunk of text using multiple fallback endpoints."""
    import random
    import requests
    from extractor import get_scraper
    
    # 1. Try Google Translate with rotating clients
    clients = ["gtx", "dict-chrome-ex", "te"]
    for client in clients:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": client,
            "sl": "auto",
            "tl": target_lang,
            "dt": "t",
            "q": chunk
        }
        try:
            with get_scraper() as scraper:
                response = scraper.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    return "".join([sentence[0] for sentence in data[0]])
        except Exception:
            continue
            
    # 2. Fallback to Lingva Proxies using clean requests to avoid WAF 403s
    logger.warning(f"Google Translate failed for all clients, switching to Lingva Proxy...")
    instances = [
        "lingva.ml",
        "translate.astian.org",
        "lingva.garudalinux.org"
    ]
    
    import urllib.parse
    safe_text = urllib.parse.quote(chunk)
    for instance in instances:
        try:
            lingva_url = f"https://{instance}/api/v1/auto/{target_lang}/{safe_text}"
            res = requests.get(lingva_url, timeout=10) # Clean requests to bypass cloudscraper WAF issues
            if res.status_code == 200:
                return res.json().get('translation', chunk)
        except Exception as e:
            logger.error(f"Lingva proxy {instance} failed: {e}")
            continue
            
    return chunk

def translate_text(text: str, target_lang: str = 'km') -> str:
    """
    Translates text. Splits large texts into chunks to avoid limits.
    Skips if text is already mostly Khmer.
    """
    if not text:
        return ""
        
    if is_khmer(text):
        return text
        
    try:
        # Splitting text into chunks of ~4000 chars (Google gtx supports up to 5000)
        # This massively reduces the number of network requests and prevents 429 errors!
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        translated_chunks = []
        
        for chunk in chunks:
            if chunk.strip():
                t_chunk = translate_chunk(chunk, target_lang)
                translated_chunks.append(t_chunk)
                time.sleep(2.0)  # Heavy safe delay between chunks
                
        return "".join(translated_chunks)
        
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text
