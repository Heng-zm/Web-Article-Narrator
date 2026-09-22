"""
formatter.py — Shared Telegram message formatter.

Single source of truth for assembling article captions used by:
  - main.py  (scheduled pipeline broadcast)
  - bot.py   (/latest command, send_articles_for_categories)

Output format:
  {header}
  ចំណុចសំខាន់ៗ៖
  • bullet 1
  • bullet 2
  {footer}
"""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urlparse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

# Maximum total caption length Telegram allows for sendPhoto (1024 chars).
# We stay under 1020 to leave a tiny safety margin.
_MAX_CAPTION = 1020

# Hard cap per bullet (inherited from summarizer's _MAX_SENTENCE_CHARS).
# Bullets longer than this were already truncated upstream — this is a final guard.
_MAX_BULLET_CHARS = 180


def _build_bullets(km_text: str, budget: int) -> str:
    """
    Converts the '|||'-delimited summary string into HTML bullet lines,
    respecting the remaining character budget.
    """
    if not km_text or budget <= 0:
        return ""
        
    lines = [l.strip().lstrip("•-*🔹").strip() for l in km_text.split("|||") if l.strip()]
    if not lines:
        return ""
        
    body = "<b>ចំណុចសំខាន់ៗ៖</b>\n"
    used = 0
    
    for line in lines:
        if not line:
            continue
            
        if len(line) > _MAX_BULLET_CHARS:
            line = line[:_MAX_BULLET_CHARS].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
            
        # Account for bullet and newline syntax overhead in character budget
        overhead = 3  # "• " + "\n"
        
        if used + len(line) + overhead > budget:
            remaining = budget - used - overhead
            if remaining > 15:
                body += f"• {line[:remaining - 1]}…\n"
            break
            
        body += f"• {line}\n"
        used += len(line) + overhead
        
    return body.strip()


def format_article_message(
    *,
    km_title: str,
    km_text: str,
    url: str,
    verification: dict | None = None,
    analysis: dict | None = None,
    telegraph_url: str | None = None,
    date_str: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Builds the Telegram caption string and inline keyboard for one article.

    Returns:
        (caption_str, InlineKeyboardMarkup)

    Parameters:
        km_title      — Translated Khmer title
        km_text       — '|||'-delimited summary (already translated to Khmer)
        url           — Original article URL
        verification  — dict with keys 'verified' (bool) and 'sources' (int), or None
        analysis      — dict from analyze_article_metadata (categories, hashtags, is_hot)
        telegraph_url — Optional Telegraph instant-view URL
        date_str      — Date string override; defaults to today dd/mm/yyyy
    """
    analysis = analysis or {}
    verification = verification or {}
    date_str = date_str or datetime.now().strftime("%d/%m/%Y")
    domain = urlparse(url).netloc.replace("www.", "")

    # Guard against abnormally long titles crushing the budget
    if len(km_title) > 300:
        km_title = km_title[:300].rsplit(" ", 1)[0] + "…"

    # ── Header ────────────────────────────────────────────────────────────────
    if analysis.get("is_hot"):
        header = (
            f"🚨🔥 <b>ព័ត៌មានក្តៅគគុក (BREAKING NEWS)</b> 🔥🚨\n\n"
            f"📰 <b>{km_title}</b>\n\n"
        )
    else:
        header = f"📰 <b>{km_title}</b>\n\n"

    # ── Footer ────────────────────────────────────────────────────────────────
    if verification.get("verified"):
        sources = verification.get("sources", 1)
        status_badge = f"✅ បានបញ្ជាក់ដោយ {sources} ប្រភព (Verified)"
    else:
        status_badge = "⚠️ មិនមានប្រភពអន្តរជាតិ (Unverified)"

    hashtags = analysis.get("hashtags", "")
    footer = (
        f"🔗 <b>ប្រភព:</b> {domain}\n"
        f"🛡️ <b>បញ្ជាក់ប្រភព:</b> {status_badge}\n"
        f"📅 {date_str}\n\n"
        f"{hashtags}"
    ).strip()

    # ── Bullet body (respects remaining budget) ───────────────────────────────
    # We allocate exact remaining space so we don't need a blind HTML-breaking truncation later.
    overhead = len(header) + len(footer) + 2  # for \n\n between body and footer
    bullet_header_len = len("<b>ចំណុចសំខាន់ៗ៖</b>\n")
    
    bullet_budget = max(0, _MAX_CAPTION - overhead - bullet_header_len)
    body = _build_bullets(km_text, bullet_budget)

    # Assemble safely
    if body:
        caption = f"{header}{body}\n\n{footer}"
    else:
        caption = f"{header}{footer}"

    # ── Inline keyboard ───────────────────────────────────────────────────────
    keyboard: list[list[InlineKeyboardButton]] = []

    if telegraph_url:
        keyboard.append([InlineKeyboardButton("⚡ អានអត្ថបទពេញ (Instant View)", url=telegraph_url)])

    article_cats = analysis.get("categories", [])
    if "សង្គ្រាម" in article_cats:
        try:
            from categorizer import get_conflict_map_info
            combined_text = f"{km_title} {km_text}"
            map_info = get_conflict_map_info(text=combined_text, url=url)
            if map_info:
                keyboard.append([InlineKeyboardButton(map_info["label"], url=map_info["url"])])
        except Exception as exc:
            logger.warning(f"Conflict map lookup failed: {exc}")

    keyboard.append([InlineKeyboardButton("🔗 អានប្រភពដើម (Read Original)", url=url)])

    return caption, InlineKeyboardMarkup(keyboard)