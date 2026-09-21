import logging
import nltk
from nltk.tokenize import sent_tokenize, word_tokenize
from nltk.corpus import stopwords
from collections import defaultdict

logger = logging.getLogger(__name__)

# Ensure tokenizers are downloaded
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')
    nltk.download('punkt_tab')
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

import math

BOILERPLATE_PATTERNS = [
    r'click here', r'subscribe', r'read more', r'follow us', r'all rights reserved',
    r'photo by', r'image source', r'copyright \d{4}', r'sign up for', r'download our app',
    r'advertisement', r'sponsored content', r'terms of service', r'privacy policy'
]

def is_boilerplate(sentence: str) -> bool:
    """Checks if a sentence is boilerplate web text rather than actual news content."""
    s_lower = sentence.lower()
    if len(s_lower) < 25 or len(s_lower) > 350:
        return True
    for pat in BOILERPLATE_PATTERNS:
        if re.search(pat, s_lower):
            return True
    return False

import re

def extractive_summary(text: str, sentences_count: int = 4) -> str:
    """
    Generates a high-precision journalistic summary:
    - Normalizes sentence scores by length (no bias towards rambling run-ons)
    - Inverted-pyramid weighting (lead sentences get boosted)
    - Boilerplate & ad filtering
    """
    if not text or len(text.strip()) < 100:
        return text

    try:
        raw_sentences = sent_tokenize(text)
        # Filter boilerplate sentences
        sentences = [s.strip().replace('\n', ' ').replace('\r', '') for s in raw_sentences if not is_boilerplate(s)]
        if not sentences:
            sentences = [s.strip().replace('\n', ' ').replace('\r', '') for s in raw_sentences[:sentences_count]]
            
        if len(sentences) <= sentences_count:
            return " ||| ".join(sentences)
            
        words = word_tokenize(text.lower())
        stop_words = set(stopwords.words('english'))
        
        # Calculate word frequencies
        word_frequencies = defaultdict(int)
        for word in words:
            if word.isalnum() and word not in stop_words and len(word) > 2:
                word_frequencies[word] += 1
                
        max_frequency = max(word_frequencies.values()) if word_frequencies else 1
        for word in word_frequencies.keys():
            word_frequencies[word] = word_frequencies[word] / max_frequency
            
        # Score sentences with Inverted-Pyramid Weighting & Length Normalization
        sentence_scores = {}
        for i, sentence in enumerate(sentences):
            s_words = word_tokenize(sentence.lower())
            if not s_words:
                continue
                
            raw_score = sum(word_frequencies.get(w, 0) for w in s_words)
            # Normalize by square root of length to avoid penalizing concise sentences
            length_factor = math.sqrt(len(s_words)) if len(s_words) > 0 else 1.0
            norm_score = raw_score / length_factor
            
            # Inverted Pyramid boost: Lead sentences in journalism contain key facts
            if i == 0:
                norm_score *= 1.6  # First sentence (Lead)
            elif i == 1:
                norm_score *= 1.3  # Second sentence
            elif i == 2:
                norm_score *= 1.15 # Third sentence
                
            sentence_scores[i] = norm_score
                        
        # Get top sentences and keep them in chronological narrative order
        top_indices = sorted(sentence_scores, key=sentence_scores.get, reverse=True)[:sentences_count]
        top_indices.sort()
        
        summary_sentences = [sentences[i] for i in top_indices]
        clean_sentences = [str(s).strip() for s in summary_sentences if s.strip()]
        return " ||| ".join(clean_sentences)
        
    except Exception as e:
        logger.error(f"Summarization error: {e}")
        return text[:500] + "..."
