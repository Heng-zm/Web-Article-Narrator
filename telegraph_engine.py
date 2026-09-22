import asyncio
import html
import logging
import os

from telegraph import Telegraph

logger = logging.getLogger(__name__)

# Telegra.ph's documented title length limit.
_MAX_TITLE_CHARS = 256

# If set, reuse this account instead of creating a brand-new one on every
# restart. `create_account()` always issues a fresh token and discards any
# previous one (it doesn't just "resume" an existing account), so without
# this the bot silently orphans a new anonymous Telegraph account every time
# the process restarts.
_ACCESS_TOKEN_ENV = "TELEGRAPH_ACCESS_TOKEN"

# Single global instance
_telegraph = Telegraph(access_token=os.environ.get(_ACCESS_TOKEN_ENV))
_account_ready = bool(_telegraph.get_access_token())
_account_lock = asyncio.Lock()


def _escape_text(value: str) -> str:
    """Escapes text for safe placement inside HTML element content."""
    return html.escape(value, quote=False)


def _escape_attr(value: str) -> str:
    """Escapes a value for safe placement inside an HTML attribute (e.g. a URL)."""
    return html.escape(value, quote=True)


def _build_html_content(content_text: str, image_url: str = None, source_url: str = None) -> str:
    """
    Builds the Telegra.ph HTML body for an article.

    Every piece of scraped/user-derived text is HTML-escaped: an unescaped
    '&', '<', '>' or '"' in article text or a URL would otherwise produce
    malformed HTML (broken tags, attributes that end early) and a garbled or
    partially-empty rendered page.
    """
    html_blocks = []
    if image_url:
        html_blocks.append(f'<img src="{_escape_attr(image_url)}"/>')

    # Split text by paragraphs to preserve newlines. Guard against None so a
    # caller passing no body text doesn't crash on .split().
    for p in (content_text or "").split('\n'):
        p = p.strip()
        if p:
            html_blocks.append(f'<p>{_escape_text(p)}</p>')

    if source_url:
        html_blocks.append('<hr/>')
        safe_url = _escape_attr(source_url)
        html_blocks.append(
            f'<p><em>🔗 <a href="{safe_url}">អានប្រភពដើម (Read Original Source)</a></em></p>'
        )

    return "".join(html_blocks)


async def _ensure_account() -> None:
    """Lazily creates the shared Telegraph account, once, in a thread-safe way."""
    global _account_ready
    if _account_ready:
        return
    async with _account_lock:
        if _account_ready:  # re-check: another task may have won the race
            return
        await asyncio.to_thread(
            _telegraph.create_account,
            short_name='KhmerNewsBot',
            author_name='NewsBot',
        )
        _account_ready = True
        logger.info(
            "Created a new Telegraph account. To reuse it across restarts, "
            f"set {_ACCESS_TOKEN_ENV}={_telegraph.get_access_token()} in the environment."
        )


async def get_telegraph_url(title: str, content_text: str, image_url: str = None, source_url: str = None) -> str:
    """
    Generates a Telegraph Instant View page for the given article.

    This is a coroutine because the underlying `telegraph` package only
    offers a blocking/synchronous client. Its network calls are run in a
    worker thread via asyncio.to_thread so they don't block the event loop
    (and every other concurrent user) for the duration of each request.
    Callers must `await` this function.
    """
    if not title or not title.strip():
        logger.error("Failed to create Telegraph page: title is required")
        return ""

    try:
        await _ensure_account()

        safe_title = title.strip()
        if len(safe_title) > _MAX_TITLE_CHARS:
            safe_title = safe_title[: _MAX_TITLE_CHARS - 1].rstrip() + '…'

        html_content = _build_html_content(content_text, image_url, source_url)
        if not html_content:
            # Telegra.ph rejects pages with no real content nodes at all.
            html_content = '<p>&nbsp;</p>'

        response = await asyncio.to_thread(
            _telegraph.create_page,
            title=safe_title,
            html_content=html_content,
        )
        return response['url']
    except Exception as e:
        logger.error(f"Failed to create Telegraph page: {e}")
        return ""