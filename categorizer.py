import re

CATEGORIES = [
    "បច្ចេកវិទ្យា",     # Technology
    "សង្គម",           # Society
    "នយោបាយ",         # Politics
    "សង្គ្រាម",         # War
    "ពត៌មានក្នុងស្រុក",  # Local
    "អន្តរជាតិ"        # International
]

KEYWORDS = {
    "បច្ចេកវិទ្យា": [
        "tech", "software", "hardware", "apple", "google", "microsoft", "cyber", "ai", 
        "internet", "smartphone", "digital", "ev", "data", "cloud", "chip", "semiconductor",
        "បច្ចេកវិទ្យា", "ទូរស័ព្ទ", "កុំព្យូទ័រ", "អ៊ីនធឺណិត", "ស្មាតហ្វូន", "បណ្ដាញសង្គម", 
        "ឌីជីថល", "អេឡិចត្រូនិក", "កម្មវិធី", "អវកាស", "រថយន្តអគ្គិសនី", "បញ្ញាសិប្បនិម្មិត"
    ],
    "សង្គម": [
        "society", "people", "education", "health", "culture", "community", "crime", 
        "accident", "police", "hospital", "school", "traffic", "poverty",
        "សង្គម", "ប្រជាពលរដ្ឋ", "អប់រំ", "សុខាភិបាល", "វប្បធម៌", "សាសនា", "គ្រោះថ្នាក់", 
        "ឧក្រិដ្ឋកម្ម", "ប៉ូលិស", "ឃាតកម្ម", "គ្រោះធម្មជាតិ", "ក្មេងទំនើង", "ចរាចរណ៍", "មន្ទីរពេទ្យ"
    ],
    "នយោបាយ": [
        "politic", "government", "election", "minister", "parliament", "senate", "law", 
        "diplomac", "president", "policy", "sanction", "treaty", "ambassador",
        "នយោបាយ", "រដ្ឋាភិបាល", "ការបោះឆ្នោត", "រដ្ឋមន្ត្រី", "គណបក្ស", "សភា", "ព្រឹទ្ធសភា", 
        "នាយករដ្ឋមន្ត្រី", "ច្បាប់", "សិទ្ធិមនុស្ស", "ការទូត", "ក្រសួង", "នយោបាយការបរទេស"
    ],
    "សង្គ្រាម": [
        "war", "military", "army", "weapon", "missile", "russia", "ukraine", "gaza", 
        "israel", "conflict", "terror", "troops", "attack", "invasion", "defense",
        "សង្គ្រាម", "កងទ័ព", "អាវុធ", "មីស៊ីល", "រុស្ស៊ី", "អ៊ុយក្រែន", "អ៊ីស្រាអែល", 
        "ហាម៉ាស់", "បាញ់ប្រហារ", "យោធា", "ភេរវកម្ម", "ជម្លោះ", "ការវាយប្រហារ", "ទាហាន"
    ],
    "ពត៌មានក្នុងស្រុក": [
        "cambodia", "phnom penh", "siem reap", "sihanoukville", "national", "khmer", 
        "battambang", "kampot", "kandal", "angkor",
        "ក្នុងស្រុក", "កម្ពុជា", "ភ្នំពេញ", "សៀមរាប", "ព្រះសីហនុ", "ក្រសួង", "សម្តេច", 
        "ជាតិ", "អាជ្ញាធរ", "ខេត្ត", "រាជធានី", "បាត់ដំបង", "កំពត", "កណ្តាល"
    ],
    "អន្តរជាតិ": [
        "international", "global", "world", "us", "china", "europe", "asean", "foreign", 
        "united nations", "beijing", "washington", "nato",
        "អន្តរជាតិ", "ពិភពលោក", "អាមេរិក", "ចិន", "អឺរ៉ុប", "អាស៊ាន", "បរទេស", 
        "អង្គការសហប្រជាជាតិ", "សហភាពអឺរ៉ុប", "មហាអំណាច"
    ]
}

HOT_KEYWORDS = [
    'breaking', 'urgent', 'alert', 'exclusive', 'emergency', 'attack', 'blast', 
    'dead', 'killed', 'disaster', 'crash', 'explosion', 'quake',
    'បន្ទាន់', 'ក្តៅគគុក', 'ទាន់ហេតុការណ៍', 'រន្ធត់', 'ផ្ទុះ', 'ស្លាប់', 'គ្រោះមហន្តរាយ', 'បាញ់ប្រហារ'
]

def analyze_article_metadata(km_title: str = "", km_text: str = "", en_title: str = "") -> dict:
    """
    Performs comprehensive smart NLP analysis:
    - Weighted category classification (title 3x weight, body 1x weight)
    - Hot news / Breaking news score
    - Urgency level
    - Dynamic clean hashtags
    """
    title_combined = f"{km_title} {en_title}".lower()
    body_combined = km_text.lower()
    full_text = f"{title_combined} {body_combined}"
    
    # 1. Weighted Category Scoring
    category_scores = {}
    for category, keywords in KEYWORDS.items():
        score = 0.0
        for kw in keywords:
            kw_lower = kw.lower()
            # English word boundary match
            if re.match(r'^[a-z0-9\s]+$', kw_lower):
                pattern = rf"\b{re.escape(kw_lower)}\b"
                if re.search(pattern, title_combined):
                    score += 3.0  # Title match carries 3x weight
                if re.search(pattern, body_combined):
                    score += 1.0
            else:
                # Khmer continuous text match
                if kw_lower in title_combined:
                    score += 3.0
                if kw_lower in body_combined:
                    score += 1.0
        if score > 0:
            category_scores[category] = score
            
    # Select categories that have a meaningful score (sorted by highest relevance)
    sorted_categories = sorted(category_scores.items(), key=lambda x: x[1], reverse=True)
    # Take top categories with score >= 2.0 (or top 1 if any score)
    matched_categories = [cat for cat, score in sorted_categories if score >= 2.0]
    if not matched_categories and sorted_categories:
        matched_categories = [sorted_categories[0][0]]
        
    # 2. Hot News / Urgency Analysis
    hot_hits = 0
    for kw in HOT_KEYWORDS:
        if kw in full_text:
            hot_hits += 1
            
    is_hot = hot_hits >= 1
    if hot_hits >= 2:
        urgency = "HIGH"
    elif hot_hits == 1:
        urgency = "MEDIUM"
    else:
        urgency = "LOW"
        
    # 3. Dynamic Hashtags
    if matched_categories:
        hashtags = " ".join([f"#{cat.replace(' ', '_')}" for cat in matched_categories[:3]])
    else:
        hashtags = "#ព័ត៌មានទូទៅ"
        
    return {
        "categories": matched_categories,
        "is_hot": is_hot,
        "urgency": urgency,
        "hashtags": hashtags,
        "category_scores": category_scores
    }

def categorize_article(km_text: str, en_title: str) -> list:
    """Backwards-compatible wrapper returning list of categories."""
    result = analyze_article_metadata(km_text=km_text, en_title=en_title)
    return result["categories"]
