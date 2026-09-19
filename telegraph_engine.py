import logging
from telegraph import Telegraph

logger = logging.getLogger(__name__)

# Single global instance
_telegraph = Telegraph()
_account_created = False

def get_telegraph_url(title: str, content_text: str, image_url: str = None) -> str:
    """
    Generates a Telegraph Instant View page for the given article.
    """
    global _account_created
    try:
        if not _account_created:
            _telegraph.create_account(short_name='KhmerNewsBot', author_name='NewsBot')
            _account_created = True

        # Build clean HTML content
        html_blocks = []
        if image_url:
            html_blocks.append(f'<img src="{image_url}"/>')
        
        # Split text by paragraphs to preserve newlines
        paragraphs = content_text.split('\n')
        for p in paragraphs:
            if p.strip():
                html_blocks.append(f'<p>{p.strip()}</p>')

        html_content = "".join(html_blocks)

        response = _telegraph.create_page(
            title=title,
            html_content=html_content
        )
        return response['url']
    except Exception as e:
        logger.error(f"Failed to create Telegraph page: {e}")
        return ""
