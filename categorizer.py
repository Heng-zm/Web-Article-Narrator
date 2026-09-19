import re

CATEGORIES = [
    "បច្ចេកវិទ្យា", # Technology
    "សង្គម", # Society
    "នយោបាយ", # Politics
    "សង្គ្រាម", # War
    "ពត៌មានក្នុងស្រុក", # Local
    "អន្តរជាតិ" # International
]

KEYWORDS = {
    "បច្ចេកវិទ្យា": ["tech", "software", "apple", "google", "microsoft", "cyber", "ai", "internet", "smartphone", "digital", "ev", "បច្ចេកវិទ្យា", "ទូរស័ព្ទ", "កុំព្យូទ័រ", "អ៊ីនធឺណិត", "ស្មាតហ្វូន", "បណ្ដាញសង្គម", "ឌីជីថល", "អេឡិចត្រូនិក", "កម្មវិធី", "អវកាស", "រថយន្តអគ្គិសនី"],
    "សង្គម": ["society", "people", "education", "health", "culture", "community", "crime", "accident", "police", "សង្គម", "ប្រជាពលរដ្ឋ", "អប់រំ", "សុខាភិបាល", "វប្បធម៌", "សាសនា", "គ្រោះថ្នាក់", "ឧក្រិដ្ឋកម្ម", "ប៉ូលិស", "ឃាតកម្ម", "គ្រោះធម្មជាតិ", "ក្មេងទំនើង"],
    "នយោបាយ": ["politic", "government", "election", "minister", "parliament", "senate", "law", "diplomac", "នយោបាយ", "រដ្ឋាភិបាល", "ការបោះឆ្នោត", "រដ្ឋមន្ត្រី", "គណបក្ស", "សភា", "ព្រឹទ្ធសភា", "នាយករដ្ឋមន្ត្រី", "ច្បាប់", "សិទ្ធិមនុស្ស", "ការទូត"],
    "សង្គ្រាម": ["war", "military", "army", "weapon", "missile", "russia", "ukraine", "gaza", "israel", "conflict", "terror", "សង្គ្រាម", "កងទ័ព", "អាវុធ", "មីស៊ីល", "រុស្ស៊ី", "អ៊ុយក្រែន", "អ៊ីស្រាអែល", "ហាម៉ាស់", "បាញ់ប្រហារ", "យោធា", "ភេរវកម្ម", "ជម្លោះ"],
    "ពត៌មានក្នុងស្រុក": ["cambodia", "phnom penh", "siem reap", "sihanoukville", "national", "khmer", "ក្នុងស្រុក", "កម្ពុជា", "ភ្នំពេញ", "សៀមរាប", "ព្រះសីហនុ", "ក្រសួង", "សម្តេច", "ជាតិ", "អាជ្ញាធរ", "ខេត្ត"],
    "អន្តរជាតិ": ["international", "global", "world", "us", "china", "europe", "asean", "foreign", "អន្តរជាតិ", "ពិភពលោក", "អាមេរិក", "ចិន", "អឺរ៉ុប", "អាស៊ាន", "បរទេស", "អង្គការសហប្រជាជាតិ"]
}

def categorize_article(km_text: str, en_title: str) -> list:
    """Returns a list of matching categories for a given article using Smart NLP."""
    combined_text = (km_text + " " + en_title).lower()
    
    matched_categories = set()
    
    for category, keywords in KEYWORDS.items():
        for kw in keywords:
            kw = kw.lower()
            # If the keyword is English letters only, use word boundary regex to prevent 'us' matching 'just'
            if re.match(r'^[a-z0-9\s]+$', kw):
                if re.search(rf"\b{re.escape(kw)}\b", combined_text):
                    matched_categories.add(category)
                    break
            else:
                # Khmer doesn't use spaces, so substring matching is perfect
                if kw in combined_text:
                    matched_categories.add(category)
                    break
                
    return list(matched_categories)
