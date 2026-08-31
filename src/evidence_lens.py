import re
from typing import List, Dict, Any

# ==============================================================================
# COMPILED EVIDENCE PATTERNS
# ==============================================================================

PROPORTIONS_PATTERN = re.compile(
    r'\b(?:nearly|almost|barely|hardly|more than|less than|about|at least)?\s*'
    r'(?:a\s+tenth|a\s+fifth|a\s+quarter|a\s+third|half|two-thirds|three-quarters|one-tenth|one-fifth)\s+'
    r'of\s+(?:the\s+)?(?:[\w’\'-]+\s+){0,6}'
    r'(?:[\d\.,]+\s*(?:%|per\s+cent|mt|tonnes|lakh|crore|million|billion|electors|voters|appeals|households|names|people|civilians|men|women|points))?',
    re.IGNORECASE
)

RELATIONAL_COUNTS_PATTERN = re.compile(
    r'\b(?:barely|nearly|almost|at least|more than|less than)?\s*'
    r'[\d\.,]+\s*(?:lakh|crore|thousand|million)?\s+of\s+(?:the\s+)?(?:nearly|almost|barely|about)?\s*'
    r'(?:[\d\.,]+\s*(?:lakh|crore|thousand|million|billion)?\s+)?(?:[\w’\'-]+\s+){0,4}'
    r'(?:tribunals|appeals|electors|constituencies|cases|members|respondents|dealers|mills|people|districts)',
    re.IGNORECASE
)

PRICE_RANGE_PATTERN = re.compile(
    r'\b(?:from\s+)?(?:an\s+average\s+of\s+)?'
    r'(?:Rs\.?|₹|\$|€|USD|EUR|GBP)?\s*[\d\.,]+\s*'
    r'(?:to|-|and)\s*'
    r'(?:Rs\.?|₹|\$|€|USD|EUR|GBP)?\s*[\d\.,]+'
    r'(?:\s*per\s+(?:kg|tonne|quintal|litre|barrel|unit|month|annum|capita))?'
    r'(?:\s+within\s+(?:a|an|\d+)\s+(?:day|week|month|year)s?)?',
    re.IGNORECASE
)

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

TREND_MOVEMENT_PATTERN = re.compile(
    r'\b(?:slashed|increased|decreased|rose|fell|dropped|surged|declined|climbed|soared|shrunk|'
    r'contracted|raised|reduced|lost|cut)\s+'
    r'(?:by|to|from)\s+(?:barely|nearly|almost|at least|more than|less than)?\s*'
    r'(?:Rs\.?|₹|\$|€)?\s*[\d\.,]+\s*(?:%|per\s+cent|lakh|crore|million|billion|points|tonnes|mt)?\s*'
    r'(?:to\s+(?:zero|[\d\.,]+\s*(?:%|per\s+cent|lakh|crore|million|billion|points|tonnes|mt)?))?',
    re.IGNORECASE
)

THRESHOLDS_PATTERN = re.compile(
    r'\b(?:holding\s+(?:any\s+[\w\s]+)?beyond|beyond|within|at least|up to|capped at|maximum of|minimum of)\s+'
    r'[\d\.,]+\s*(?:days|months|years|hours|tonnes|mt|kg|seats|crore|lakh|percent|per cent)'
    r'|\b[\d\.,]+\s*(?:tonnes|mt|kg|crore|lakh|seats)\s+or\s+more\b',
    re.IGNORECASE
)

NON_DIGIT_QUANT_PATTERN = re.compile(
    r'\b(?:more\s+than\s+half|nearly\s+half|less\s+than\s+half)\s+of\s+(?:their|the|all)?\s*[\w\s]{2,25}\b'
    r'|\b(?:more\s+than\s+doubled|declined\s+by\s+half|shrunk\s+by\s+half|tripled|contracted\s+sharply)\b'
    r'|\b(?:the\s+)?(?:highest|lowest|steepest|sharpest)\s+(?:in|since|over|across)\s+(?:the\s+)?(?:decade|country|region|state|history|\d+\s+years?)\b',
    re.IGNORECASE
)

PERCENT_COMPOSITION_PATTERN = re.compile(
    r'\b(?:only\s+)?[\d\.,]+\s*(?:%|per\s+cent)\s+of\s+(?:[\w’\'-]+\s+){1,6}'
    r'|\b(?:nearly|about|around|approximate(?:ly)?)?\s*[\d\.,]+\s*(?:%|per\s+cent)\s+and\s+[\d\.,]+\s*(?:%|per\s+cent)\s+respectively\b',
    re.IGNORECASE
)

EXCLUSION_PATTERN = re.compile(
    r'^(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}'
    r'|^\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)'
    r'|^(?:19\d\d|20\d\d)$',
    re.IGNORECASE
)

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
        PROPORTIONS_PATTERN, RELATIONAL_COUNTS_PATTERN, PRICE_RANGE_PATTERN,
        STAT_NOUN_PHRASE_PATTERN, TREND_MOVEMENT_PATTERN, THRESHOLDS_PATTERN,
        NON_DIGIT_QUANT_PATTERN, PERCENT_COMPOSITION_PATTERN
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
