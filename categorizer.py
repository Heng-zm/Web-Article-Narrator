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
    "បច្ចេកវិទ្យា": ["tech", "software", "apple", "google", "microsoft", "cyber", "ai", "internet", "បច្ចេកវិទ្យា", "កុំព្យូទ័រ", "ទូរស័ព្ទ", "ឌីជីថល"],
    "សង្គម": ["society", "people", "education", "health", "culture", "community", "សង្គម", "ប្រជាជន", "អប់រំ", "វប្បធម៌", "សុខភាព", "យុវជន"],
    "នយោបាយ": ["politic", "government", "election", "minister", "parliament", "senate", "នយោបាយ", "រដ្ឋាភិបាល", "បោះឆ្នោត", "រដ្ឋមន្ត្រី", "សភា", "គណបក្ស", "ហ៊ុន ម៉ាណែត", "ហ៊ុន សែន"],
    "សង្គ្រាម": ["war", "military", "army", "weapon", "missile", "russia", "ukraine", "gaza", "israel", "សង្គ្រាម", "យោធា", "កងទ័ព", "អាវុធ", "មីស៊ីល"],
    "ពត៌មានក្នុងស្រុក": ["cambodia", "phnom penh", "siem reap", "sihanoukville", "កម្ពុជា", "ភ្នំពេញ", "សៀមរាប", "ក្រសួង", "ខេត្ត", "ខ្មែរ", "ព្រះមហាក្សត្រ", "សម្តេច"],
    "អន្តរជាតិ": ["international", "global", "world", "us", "china", "europe", "អន្តរជាតិ", "ពិភពលោក", "អាមេរិក", "ចិន", "អឺរ៉ុប", "បរទេស", "អាស៊ាន", "asean"]
}

def categorize_article(km_text: str, en_title: str) -> list:
    """Returns a list of matching categories for a given article."""
    combined_text = (km_text + " " + en_title).lower()
    
    matched_categories = set()
    
    for category, keywords in KEYWORDS.items():
        for kw in keywords:
            if kw in combined_text:
                matched_categories.add(category)
                break # Only need one match per category
                
    # If no categories matched, maybe default to Local or Society? Let's just return empty list.
    return list(matched_categories)
