import re
from typing import List, Dict, Any
import spacy
from spacy.matcher import Matcher

# Load lightweight model once at module level
nlp = spacy.load("en_core_web_sm")

# Initialize linguistic pattern matcher
matcher = Matcher(nlp.vocab)

# ==============================================================================
# STRUCTURAL GRAMMAR RULES (ZERO-MAINTENANCE PATTERNS)
# ==============================================================================

# 1. Constitutional Articles & Statutory Sections (e.g., "Article 21A", "Section 144")
matcher.add("LEGAL_PROVISIONS", [
    [
        {"LOWER": {"IN": ["article", "art."]}},
        {"TEXT": {"REGEX": r"^\d+[A-Za-z]?(?:\(\d+\))?$"}}
    ],
    [
        {"LOWER": {"IN": ["section", "sec."]}},
        {"TEXT": {"REGEX": r"^\d+[A-Za-z]?$"}},
        {"LOWER": "of", "OP": "?"},
        {"LOWER": "the", "OP": "?"},
        {"IS_TITLE": True, "OP": "*"}
    ],
    [
        {"TEXT": {"REGEX": r"^\d+(?:st|nd|rd|th)$"}},
        {"LOWER": "constitutional", "OP": "?"},
        {"LOWER": "amendment"},
        {"LOWER": "act", "OP": "?"}
    ],
    [
        {"TEXT": {"REGEX": r"^(?:two|three|five|seven|nine|\d+)-judge$"}},
        {"LOWER": "bench"}
    ],
    [
        {"LOWER": "constitution"},
        {"LOWER": "bench"}
    ]
])

# 2. Institutional Entities (e.g., "[Any Title Words] + Commission / Committee / Panel")
matcher.add("INSTITUTIONS", [
    [
        {"IS_TITLE": True, "OP": "+"},
        {"LOWER": {"IN": ["committee", "commission", "panel", "tribunal", "board", "council", "authority"]}}
    ]
])

# 3. Statutory Enactments (e.g., "[Any Title Words] + Act / Bill / Code, [Optional Year]")
matcher.add("STATUTES", [
    [
        {"IS_TITLE": True, "OP": "+"},
        {"LOWER": {"IN": ["act", "bill", "code", "ordinance"]}},
        {"TEXT": ",", "OP": "?"},
        {"IS_DIGIT": True, "LENGTH": 4, "OP": "?"}
    ]
])

# 4. Welfare Schemes & National Missions (e.g., "[Any Title Words] + Scheme / Mission / Yojana")
matcher.add("POLICIES_AND_SCHEMES", [
    [
        {"IS_TITLE": True, "OP": "+"},
        {"LOWER": {"IN": ["scheme", "mission", "yojana", "initiative", "programme", "program", "pact", "accord"]}}
    ]
])

# 5. Indices, Surveys & Global Reports (e.g., "[Any Title Words] + Index / Report / Survey")
matcher.add("REPORTS_AND_INDICES", [
    [
        {"IS_TITLE": True, "OP": "+"},
        {"LOWER": {"IN": ["index", "report", "survey", "ranking"]}}
    ]
])

# 6. Global Summits & Multilateral Acronyms (e.g., "COP29", "G20", "BRICS", "UNCLOS")
matcher.add("GLOBAL_FORUMS", [
    [
        {"TEXT": {"REGEX": r"^(?:COP\d+|G\d+|BRICS|ASEAN|BIMSTEC|UNCLOS|NATO|OPEC|SAARC|QUAD|I2U2)$"}}
    ]
])

# Fast regex for basis points and fiscal metrics where spaCy labels them CARDINAL
MACRO_UNITS_REGEX = re.compile(
    r'\b[\d\.,]+\s*(?:basis\s+points|bps|GW|MW|megawatts|gigawatts|sq\s+km|hectares|tonnes|mt)\b',
    re.IGNORECASE
)

# Narrative exclusions to avoid highlighting standalone years or months
EXCLUSION_REGEX = re.compile(
    r'^(?:january|february|march|april|may|june|july|august|september|october|november|december|\d{1,2}|19\d\d|20\d\d)$',
    re.IGNORECASE
)

# ==============================================================================
# SPAN MERGER & BOUNDARY RESOLVER
# ==============================================================================

def merge_overlapping_spans(spans: List[Dict[str, int]]) -> List[Dict[str, int]]:
    """Sorts and merges overlapping/nested boundary spans cleanly."""
    if not spans:
        return []

    # Sort primarily by start position asc, secondarily by span length desc
    spans.sort(key=lambda s: (s["start"], -(s["end"] - s["start"])))
    merged = [spans[0]]

    for current in spans[1:]:
        last = merged[-1]
        if current["start"] <= last["end"]:
            # Overlapping or adjacent: expand boundary to max end position
            if current["end"] > last["end"]:
                last["end"] = current["end"]
        else:
            merged.append(current)

    return merged


def extract_evidence_spans(paragraph_text: str) -> List[Dict[str, Any]]:
    """
    Extracts high-yield quantitative, legal, and institutional spans from 
    editorial paragraphs using spaCy NER and linguistic token patterns.
    """
    if not paragraph_text or not paragraph_text.strip():
        return []

    doc = nlp(paragraph_text)
    raw_spans = []

    # 1. Statistical NER: Percentages, Currencies, and Standard Physical Quantities
    for ent in doc.ents:
        if ent.label_ in ("PERCENT", "MONEY", "QUANTITY"):
            text = ent.text.strip()
            if not EXCLUSION_REGEX.match(text):
                raw_spans.append({"start": ent.start_char, "end": ent.end_char})

    # 2. Structural Linguistic Matcher: Law, Polity, Schemes, Committees, Treaties
    matches = matcher(doc)
    for _, start_token, end_token in matches:
        span = doc[start_token:end_token]
        text = span.text.strip()
        if not EXCLUSION_REGEX.match(text):
            raw_spans.append({"start": span.start_char, "end": span.end_char})

    # 3. Macro Units Fallback: Catch basis points, energy, and metric tonnage
    for match in MACRO_UNITS_REGEX.finditer(paragraph_text):
        raw_spans.append({"start": match.start(), "end": match.end()})

    return merge_overlapping_spans(raw_spans)