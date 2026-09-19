import logging
import nltk
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lsa import LsaSummarizer

logger = logging.getLogger(__name__)

# Ensure tokenizers are downloaded
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)
    nltk.download('punkt_tab', quiet=True)

def extractive_summary(text: str, sentences_count: int = 4) -> str:
    """
    Extracts the most important sentences from a text using LSA (Latent Semantic Analysis) algorithm.
    No AI APIs required.
    """
    if not text or len(text.split()) < 30:
        return text
        
    try:
        # Parse the text. Using 'english' tokenizer works fine as a baseline for sentence splitting.
        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summarizer = LsaSummarizer()
        
        # Extract the most important sentences
        sentences = summarizer(parser.document, sentences_count)
        
        # Clean internal newlines and use a strict delimiter that survives translation
        clean_sentences = [str(s).strip().replace('\n', ' ').replace('\r', '') for s in sentences]
        return " ||| ".join(clean_sentences)
    except Exception as e:
        logger.error(f"Summarization error: {e}")
        return text[:500] + "..."
