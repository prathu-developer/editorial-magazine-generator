import re
from typing import List, Dict, Any

# ==============================================================================
# COMPILED EVIDENCE PATTERNS (CORRECTED)
# ==============================================================================

# 1. Proportions, Fractions and Ratios
PROPORTIONS_PATTERN = re.compile(
    r'\b(?:nearly|almost|barely|hardly|more than|less than|about|at least)?\s*'
    r'(?:a\s+tenth|a\s+fifth|a\s+quarter|a\s+third|half|two-thirds|three-quarters|one-tenth|one-fifth)\s+'
    r'of\s+(?:the\s+)?(?:[\w’\'-]+\s+){0,6}'
    r'(?:[\d\.,]+\s*(?:%|per\s+cent|mt|tonnes|lakh|crore|million|billion|electors|voters|appeals|households|names|people|civilians|men|women|points))?',
    re.IGNORECASE
)

# 2. Relational Counts & Population Metrics
RELATIONAL_COUNTS_PATTERN = re.compile(
    r'\b(?:barely|nearly|almost|at least|more than|less than|issues?\s+of)?\s*'
    r'[\d\.,]+\s*(?:lakh|crore|thousand|million|billion)?\s+'
    r'(?:of\s+(?:the\s+)?(?:nearly|almost|barely|about)?\s*(?:[\d\.,]+\s*(?:lakh|crore|thousand|million|billion)?\s+)?(?:[\w’\'-]+\s+){0,4}(?:tribunals|appeals|electors|constituencies|cases|members|respondents|dealers|mills|people|districts)'
    r'|Dalits|citizens|people|residents|users)\b',
    re.IGNORECASE
)

# 3. Currency / Financials (Fixed: Requires currency symbol, captures singles and ranges)
FINANCIAL_PATTERN = re.compile(
    r'\b(?:pay\s+up\s+to|cost\s+of|budget\s+of|revenue\s+of|valued\s+at|average\s+of|from\s+(?:an\s+average\s+of\s+)?)?\s*'
    r'(?:Rs\.?|₹|\$|€|USD|EUR|GBP)\s*[\d\.,]+\s*(?:lakh|crore|million|billion|trillion)?'
    r'(?:\s*(?:to|-|and)\s*(?:Rs\.?|₹|\$|€|USD|EUR|GBP)?\s*[\d\.,]+\s*(?:lakh|crore|million|billion|trillion)?)?'
    r'(?:\s*per\s+(?:kg|tonne|litre|unit|month|annum|capita))?'
    r'(?:\s+(?:over\s+a\s+decade|within\s+a\s+month|per\s+year))?',
    re.IGNORECASE
)

# 4. Statistical Noun Phrases & Deficits
STAT_NOUN_PHRASE_PATTERN = re.compile(
    r'\b(?:shortfall|excess|diversion(?:s)?|deficit|surplus|growth|share|proportion|total|cut(?:s)?|'
    r'reduction(?:s)?|loss(?:es)?|deletions?|stock\s+limit|ceiling|threshold|target)\s+'
    r'of\s+(?:barely|about|nearly|almost|at least|more than|less than|up to)?\s*'
    r'(?:Rs\.?|₹|\$|€)?\s*[\d\.,]+\s*'
    r'(?:%|per\s+cent|mt|tonnes|kg|lakh|crore|million|billion|seats|points|days|months|years)?'
    r'(?:\s*,\s*[\d\.,]+\s*(?:mt|tonnes|lakh|crore|million)?)*'
    r'(?:\s+(?:and|to)\s+[\d\.,]+\s*(?:mt|tonnes|lakh|crore|million)?)?'
    r'(?:\s+respectively)?',
    re.IGNORECASE
)

# 5. Trends, Rate Movements & Tariffs
TREND_MOVEMENT_PATTERN = re.compile(
    r'\b(?:slashed|increased|decreased|rose|fell|dropped|surged|declined|climbed|soared|shrunk|'
    r'contracted|raised|reduced|lost|cut)\s+'
    r'(?:by|to|from)\s+(?:barely|nearly|almost|at least|more than|less than)?\s*'
    r'(?:Rs\.?|₹|\$|€)?\s*[\d\.,]+\s*(?:%|per\s+cent|lakh|crore|million|billion|points|tonnes|mt)?\s*'
    r'(?:to\s+(?:zero|[\d\.,]+\s*(?:%|per\s+cent|lakh|crore|million|billion|points|tonnes|mt)?))?',
    re.IGNORECASE
)

# 6. Quantitative Thresholds & Policy Limits (Fixed: Catches "two-hour" and "under-18")
THRESHOLDS_PATTERN = re.compile(
    r'\b(?:holding\s+(?:any\s+[\w\s]+)?beyond|beyond|within|at least|up to|capped at|maximum of|minimum of|limits?\s+for)\s+'
    r'(?:[\d\.,]+|one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:-hour\s+daily)?\s*(?:days|months|years|hours|tonnes|mt|kg|seats|crore|lakh|percent|per cent|users?)'
    r'|\b[\d\.,]+\s*(?:tonnes|mt|kg|crore|lakh|seats)\s+or\s+more\b'
    r'|\b(?:two-hour|one-hour|24-hour)\s+daily\s+limits?\b'
    r'|\bunder-18\s+users?\b',
    re.IGNORECASE
)

# 7. Non-Digit Quantitative Statements
NON_DIGIT_QUANT_PATTERN = re.compile(
    r'\b(?:more\s+than\s+half|nearly\s+half|less\s+than\s+half)\s+of\s+(?:their|the|all)?\s*[\w\s]{2,25}\b'
    r'|\b(?:more\s+than\s+doubled|declined\s+by\s+half|shrunk\s+by\s+half|tripled|contracted\s+sharply)\b'
    r'|\b(?:the\s+)?(?:highest|lowest|steepest|sharpest)\s+(?:in|since|over|across)\s+(?:the\s+)?(?:decade|country|region|state|history|\d+\s+years?)\b',
    re.IGNORECASE
)

# 8. Percentage Composition
PERCENT_COMPOSITION_PATTERN = re.compile(
    r'\b(?:only\s+)?[\d\.,]+\s*(?:%|per\s+cent)\s+of\s+(?:[\w’\'-]+\s+){1,6}'
    r'|\b(?:nearly|about|around|approximate(?:ly)?)?\s*[\d\.,]+\s*(?:%|per\s+cent)\s+and\s+[\d\.,]+\s*(?:%|per\s+cent)\s+respectively\b',
    re.IGNORECASE
)

# 9. Contextual Sports/Match Metrics (Fixed: Avoids capturing bare "1-0" or "167 and 44")
SPORTS_METRICS_PATTERN = re.compile(
    r'\b(?:India[\'’]s\s+\d+-\d+\s+series\s+victory|clean\s+sweep\s+at\s+\d+-\d+|secured\s+a\s+\d+-\d+\s+draw|won\s+by\s+[\d\.,]+\s+runs)\b',
    re.IGNORECASE
)

# Strip ordinary narrative dates and isolated calendar years
EXCLUSION_PATTERN = re.compile(
    r'^(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}'
    r'|^\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)'
    r'|^(?:19\d\d|20\d\d)$',
    re.IGNORECASE
)


# ==============================================================================
# SPAN RESOLVER & MERGER
# ==============================================================================

def merge_overlapping_spans(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not spans:
        return []
    spans.sort(key=lambda s: (s["start"], -(s["end"] - s["start"])))
    merged = [spans[0]]
    for current in spans[1:]:
        last = merged[-1]
        if current["start"] <= last["end"]:
            if current["end"] > last["end"]:
                last["end"] = current["end"]
        else:
            merged.append(current)
    return merged

def extract_evidence_spans(paragraph_text: str) -> List[Dict[str, Any]]:
    raw_spans = []
    patterns = [
        PROPORTIONS_PATTERN, RELATIONAL_COUNTS_PATTERN, FINANCIAL_PATTERN,
        STAT_NOUN_PHRASE_PATTERN, TREND_MOVEMENT_PATTERN, THRESHOLDS_PATTERN,
        NON_DIGIT_QUANT_PATTERN, PERCENT_COMPOSITION_PATTERN, SPORTS_METRICS_PATTERN
    ]

    for regex in patterns:
        for match in regex.finditer(paragraph_text):
            span_text = match.group(0).strip()
            if EXCLUSION_PATTERN.match(span_text):
                continue
            raw_spans.append({
                "start": match.start(),
                "end": match.end()
            })

    return merge_overlapping_spans(raw_spans)