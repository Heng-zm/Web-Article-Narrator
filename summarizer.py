import logging
import math
import re
import threading
from collections import defaultdict
from typing import List

import nltk
from nltk.tokenize import sent_tokenize
from nltk.corpus import stopwords

logger = logging.getLogger(__name__)

# ── NLTK bootstrap (Thread-safe cold-start logic) ──────────
_nltk_lock = threading.Lock()

with _nltk_lock:
    for _pkg, _path in [('punkt', 'tokenizers/punkt'), ('punkt_tab', 'tokenizers/punkt_tab'), ('stopwords', 'corpora/stopwords')]:
        try:
            nltk.data.find(_path)
        except LookupError:
            nltk.download(_pkg, quiet=True)

# Module-level cache — built once, reused on every call
_STOP_WORDS: set = set(stopwords.words('english'))

# ── Constants ─────────────────────────────────────────────────────────────────
_BOILERPLATE_RE = re.compile(
    r'click here|subscribe|read more|follow us|all rights reserved|'
    r'photo by|image source|copyright \d{4}|sign up for|download our app|'
    r'advertisement|sponsored content|terms of service|privacy policy',
    re.IGNORECASE
)
_KHMER_RE = re.compile(r'[\u1780-\u17FF]')
_KHMER_SENT_SEP = re.compile(r'[។!\?]+')   # Khmer period + universal punctuation

# Telegram caption budget shared with header/footer (~950 total, ~600 for body)
_MAX_SENTENCE_CHARS = 180   # hard cap per bullet
_MIN_SENTENCE_CHARS = 25    # skip trivially short fragments

# Inverted-pyramid position boosts
_POSITION_BOOST = {0: 1.7, 1: 1.35, 2: 1.15}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_khmer(text: str) -> bool:
    return bool(_KHMER_RE.search(text))


def _split_sentences(text: str) -> List[str]:
    """
    Splits text into sentences.
    • Khmer text  → split on ។ / ! / ? (NLTK punkt is English-only)
    • Other text  → NLTK sent_tokenize
    """
    if _is_khmer(text):
        raw = _KHMER_SENT_SEP.split(text)
    else:
        raw = sent_tokenize(text)
    return [s.strip().replace('\n', ' ').replace('\r', '') for s in raw]


def _is_boilerplate(sentence: str) -> bool:
    if len(sentence) < _MIN_SENTENCE_CHARS or len(sentence) > 350:
        return True
    return bool(_BOILERPLATE_RE.search(sentence))


def _word_freq(text: str) -> dict:
    """
    Returns normalized TF-IDF-style word frequencies.
    Uses simple log(1 + count) weighting to dampen very common words.
    """
    tokens = re.findall(r'\b[a-zA-Z\u1780-\u17FF]{3,}\b', text.lower())
    freq: dict = defaultdict(float)
    for w in tokens:
        if w not in _STOP_WORDS:
            freq[w] += 1.0
    if not freq:
        return freq
    max_f = max(freq.values())
    return {w: math.log1p(c) / math.log1p(max_f) for w, c in freq.items()}


def _sentence_vector(sentence: str, freq: dict) -> dict:
    """Sparse TF vector for a sentence (used for cosine dedup)."""
    tokens = re.findall(r'\b[a-zA-Z\u1780-\u17FF]{3,}\b', sentence.lower())
    vec: dict = defaultdict(float)
    for w in tokens:
        if w in freq:
            vec[w] += freq[w]
    return dict(vec)


def _cosine_sim(a: dict, b: dict) -> float:
    """Cosine similarity between two sparse vectors."""
    if not a or not b:
        return 0.0
    dot = sum(a.get(k, 0) * v for k, v in b.items())
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return dot / norm if norm else 0.0


# ── Public API ────────────────────────────────────────────────────────────────

def extractive_summary(text: str, sentences_count: int = 4, max_chars_per_sentence: int = _MAX_SENTENCE_CHARS) -> str:
    """
    Extractive summarizer optimized for Telegram news bullets.

    Improvements over v1:
    • Khmer-aware sentence splitting (no NLTK dependency for km text)
    • TF-IDF-style word weighting (log-damped, more balanced scores)
    • Cosine-similarity deduplication (no repetitive bullet points)
    • Per-sentence character cap so bullets fit Telegram's caption budget
    • Module-level stopword cache (no per-call I/O)
    • Inverted-pyramid position boosts retained
    """
    if not text or len(text.strip()) < _MIN_SENTENCE_CHARS:
        return text or ""

    try:
        # 1. Split & filter
        raw_sents = _split_sentences(text)
        sentences = [s for s in raw_sents if not _is_boilerplate(s)]
        if not sentences:
            sentences = [s for s in raw_sents if len(s) >= _MIN_SENTENCE_CHARS][:sentences_count]

        if len(sentences) <= sentences_count:
            return _format_output(sentences, max_chars_per_sentence)

        # 2. Build frequency table once
        freq = _word_freq(text)
        if not freq:
            # No scoreable words (e.g. pure Khmer with no Latin): return first N sentences
            return _format_output(sentences[:sentences_count], max_chars_per_sentence)

        # 3. Score each sentence
        scored = []
        for i, sent in enumerate(sentences):
            tokens = re.findall(r'\b[a-zA-Z\u1780-\u17FF]{3,}\b', sent.lower())
            if not tokens:
                continue
            raw_score = sum(freq.get(w, 0) for w in tokens)
            # Normalize by sqrt(length) to avoid bias toward long run-ons
            norm_score = raw_score / math.sqrt(len(tokens))
            # Position boost
            norm_score *= _POSITION_BOOST.get(i, 1.0)
            scored.append((i, norm_score, sent))

        if not scored:
            return _format_output(sentences[:sentences_count], max_chars_per_sentence)

        # 4. Greedy selection with cosine deduplication
        scored.sort(key=lambda x: x[1], reverse=True)
        selected_indices = []
        selected_vectors = []
        sim_threshold = 0.55  # sentences more similar than this are considered duplicates

        for idx, score, sent in scored:
            if len(selected_indices) >= sentences_count:
                break
            vec = _sentence_vector(sent, freq)
            if any(_cosine_sim(vec, sv) >= sim_threshold for sv in selected_vectors):
                continue  # Skip near-duplicate
            selected_indices.append(idx)
            selected_vectors.append(vec)

        # 5. Restore chronological order
        selected_indices.sort()
        selected_sentences = [sentences[i] for i in selected_indices]

        return _format_output(selected_sentences, max_chars_per_sentence)

    except Exception as e:
        logger.error(f"Summarization error: {e}")
        return text[:500] + "..."


def _format_output(sentences: List[str], max_chars: int) -> str:
    """
    Truncates each sentence to max_chars and joins with ' ||| ' delimiter
    that the bot splits into bullet points.
    """
    result = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(s) > max_chars:
            # Cut at last word boundary before the limit
            cut = s[:max_chars].rsplit(' ', 1)[0]
            s = cut.rstrip('.,;:') + '…'
        result.append(s)
    return ' ||| '.join(result)