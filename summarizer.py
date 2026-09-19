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
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

def extractive_summary(text: str, sentences_count: int = 4) -> str:
    """Generates an extractive summary using pure NLTK word frequencies (bypasses sumy/docopt)."""
    if not text or len(text.strip()) < 100:
        return text

    try:
        sentences = sent_tokenize(text)
        if len(sentences) <= sentences_count:
            clean_sentences = [str(s).strip().replace('\n', ' ').replace('\r', '') for s in sentences]
            return " ||| ".join(clean_sentences)
            
        words = word_tokenize(text.lower())
        stop_words = set(stopwords.words('english'))
        
        # Calculate word frequencies
        word_frequencies = defaultdict(int)
        for word in words:
            if word.isalnum() and word not in stop_words:
                word_frequencies[word] += 1
                
        max_frequency = max(word_frequencies.values()) if word_frequencies else 1
        for word in word_frequencies.keys():
            word_frequencies[word] = word_frequencies[word] / max_frequency
            
        # Score sentences
        sentence_scores = {}
        for i, sentence in enumerate(sentences):
            for word in word_tokenize(sentence.lower()):
                if word in word_frequencies:
                    if i not in sentence_scores:
                        sentence_scores[i] = word_frequencies[word]
                    else:
                        sentence_scores[i] += word_frequencies[word]
                        
        # Get top sentences and sort them by original order
        top_sentences_indices = sorted(sentence_scores, key=sentence_scores.get, reverse=True)[:sentences_count]
        top_sentences_indices.sort()
        
        summary_sentences = [sentences[i] for i in top_sentences_indices]
        
        # Clean internal newlines and use a strict delimiter that survives translation
        clean_sentences = [str(s).strip().replace('\n', ' ').replace('\r', '') for s in summary_sentences]
        return " ||| ".join(clean_sentences)
        
    except Exception as e:
        logger.error(f"Summarization error: {e}")
        return text[:500] + "..."
