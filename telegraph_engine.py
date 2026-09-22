import asyncio
import html
import logging
import os
from typing import Optional

from telegraph import Telegraph

logger = logging.getLogger(__name__)

# Telegra.ph's documented limits
_MAX_TITLE_CHARS = 256
_MAX_AUTHOR_CHARS = 128
_MAX_URL_CHARS = 512
_MAX_CONTENT_CHARS = 50000

# Environment variable to persist and reuse Telegraph account across restarts
_ACCESS_TOKEN_ENV = "TELEGRAPH_ACCESS_TOKEN"

# Global client instance
_telegraph = Telegraph(access_token=os.environ.get(_ACCESS_TOKEN_ENV) or None)
_account_ready = bool(_telegraph.get_access_token())
_account_lock: Optional[asyncio.Lock] = None
_account_lock_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_account_lock() -> asyncio.Lock:
    """
    Lazily obtains an asyncio.Lock tied to the current running event loop.
    Prevents 'RuntimeError: There is no current event loop' at import time
    and avoids loop mismatch across different threads or asyncio.run calls.
    """
    global _account_lock, _account_lock_loop
    current_loop = asyncio.get_running_loop()
    if _account_lock is None or _account_lock_loop != current_loop or current_loop.is_closed():
        _account_lock = asyncio.Lock()
        _account_lock_loop = current_loop
    return _account_lock


def _escape_text(value: str) -> str:
    """Escapes text for safe placement inside HTML element content."""
    return html.escape(value, quote=False)


def _escape_attr(value: str) -> str:
    """Escapes a value for safe placement inside an HTML attribute (e.g. a URL)."""
    return html.escape(value, quote=True)


def _build_html_content(content_text: str = "", image_url: Optional[str] = None, source_url: Optional[str] = None) -> str:
    """
    Builds the Telegra.ph HTML body for an article.
    Safely validates media/source URLs and escapes content to avoid broken tags.
    """
    html_blocks = []

    # 1. Lead Image (must be a valid web URL)
    if image_url and isinstance(image_url, str) and image_url.strip():
        clean_img = image_url.strip()
        if clean_img.startswith(("http://", "https://", "/file/")):
            html_blocks.append(f'<img src="{_escape_attr(clean_img)}"/>')

    # 2. Body Text (truncated to avoid exceeding Telegraph 64KB node limit)
    raw_text = str(content_text or "")
    if len(raw_text) > _MAX_CONTENT_CHARS:
        raw_text = raw_text[:_MAX_CONTENT_CHARS].rstrip() + "\n...(អត្ថបទត្រូវបានកាត់ខ្លី)"

    # Split text by paragraphs to preserve newlines
    for p in raw_text.split('\n'):
        p = p.strip()
        if p:
            # Unescape first to prevent double-escaping (e.g., &amp;amp;)
            clean_p = _escape_text(html.unescape(p))
            html_blocks.append(f'<p>{clean_p}</p>')

    # 3. Original Source Link
    if source_url and isinstance(source_url, str) and source_url.strip():
        clean_source = source_url.strip()
        if clean_source.startswith(("http://", "https://")):
            html_blocks.append('<hr/>')
            safe_url = _escape_attr(clean_source)
            html_blocks.append(
                f'<p><em>🔗 <a href="{safe_url}">អានប្រភពដើម (Read Original Source)</a></em></p>'
            )

    return "".join(html_blocks)


async def _ensure_account(force_refresh: bool = False) -> None:
    """Lazily creates or refreshes the shared Telegraph account in a thread-safe way."""
    global _account_ready, _telegraph

    # Check if token was populated in os.environ after module import (e.g. load_dotenv)
    if not _account_ready and not force_refresh:
        env_token = os.environ.get(_ACCESS_TOKEN_ENV)
        if env_token and env_token.strip():
            _telegraph.access_token = env_token.strip()
            _account_ready = True
            return

    if _account_ready and not force_refresh:
        return

    async with _get_account_lock():
        if _account_ready and not force_refresh:
            return

        await asyncio.to_thread(
            _telegraph.create_account,
            short_name='KhmerNewsBot',
            author_name='NewsBot',
        )
        _account_ready = True
        logger.info(
            "Telegraph account initialized. To reuse it across restarts, "
            f"set {_ACCESS_TOKEN_ENV}={_telegraph.get_access_token()} in your environment."
        )


async def get_telegraph_url(
    title: str,
    content_text: str = "",
    image_url: Optional[str] = None,
    source_url: Optional[str] = None,
    author_name: str = "NewsBot",
    author_url: Optional[str] = None,
) -> str:
    """
    Generates a Telegraph Instant View page for the given article.
    Handles network calls in worker threads to prevent event loop blocking.
    """
    if not title or not str(title).strip():
        logger.error("Failed to create Telegraph page: title is required")
        return ""

    # Sanitize title: Telegraph rejects titles containing newlines (\n, \r)
    safe_title = " ".join(str(title).split())
    if not safe_title:
        logger.error("Failed to create Telegraph page: title is required")
        return ""

    if len(safe_title) > _MAX_TITLE_CHARS:
        safe_title = safe_title[: _MAX_TITLE_CHARS - 1].rstrip() + '…'

    # Build and validate HTML payload
    html_content = _build_html_content(content_text, image_url, source_url)
    if not html_content or not html_content.strip():
        html_content = '<p>&nbsp;</p>'

    # Sanitize author metadata
    clean_author = " ".join(str(author_name).split()) if author_name else None
    if clean_author and len(clean_author) > _MAX_AUTHOR_CHARS:
        clean_author = clean_author[: _MAX_AUTHOR_CHARS - 1].rstrip() + '…'

    clean_author_url = None
    target_author_url = author_url or source_url
    if target_author_url and isinstance(target_author_url, str) and target_author_url.strip().startswith(("http://", "https://")):
        clean_author_url = target_author_url.strip()
        if len(clean_author_url) > _MAX_URL_CHARS:
            clean_author_url = None

    create_kwargs = {
        "title": safe_title,
        "html_content": html_content,
    }
    if clean_author:
        create_kwargs["author_name"] = clean_author
    if clean_author_url:
        create_kwargs["author_url"] = clean_author_url

    try:
        await _ensure_account()
        response = await asyncio.to_thread(_telegraph.create_page, **create_kwargs)
        return response.get('url', '') if isinstance(response, dict) else ""
    except Exception as e:
        err_msg = str(e).upper()
        # If the stored access token has expired or is invalid, refresh account and retry once
        if "ACCESS_TOKEN" in err_msg or "TOKEN_INVALID" in err_msg:
            logger.warning("Telegraph access token invalid; recreating account and retrying...")
            try:
                await _ensure_account(force_refresh=True)
                response = await asyncio.to_thread(_telegraph.create_page, **create_kwargs)
                return response.get('url', '') if isinstance(response, dict) else ""
            except Exception as retry_err:
                logger.error(f"Retry creating Telegraph page failed: {retry_err}")
                return ""

        logger.error(f"Failed to create Telegraph page: {e}")
        return ""