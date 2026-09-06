import json
import re
from typing import Any, Dict, List, Tuple

# ==============================================================================
# COMPILED NUMERIC & STATISTICAL PATTERNS (NUMBERS & UNITS ONLY)
# ==============================================================================

# 1. Currencies, Outlays & Price Ranges (INR, USD, EUR, GBP)
FINANCIAL_PATTERN = re.compile(
    r'(?:(?:Rs\.?|₹|\$|USD|EUR|€|GBP|£)\s*[\d\.,]+'
    r'(?:\s*(?:to|-|and)\s*(?:Rs\.?|₹|\$|USD|EUR|€|GBP|£)?\s*[\d\.,]+)?'
    r'(?:\s*(?:lakh\s+crore|crore|lakh|thousand|million|billion|trillion))?'
    r'(?:\s*(?:per|/)\s*(?:kg|tonne|quintal|barrel|litre|annum|month|year|capita|unit|ration\s+card))?)'
    r'|'
    r'(?:[\d\.,]+\s*(?:lakh\s+crore|crore|lakh|million|billion|trillion)\s*(?:economy|outlay|budget|package|capex|revenue))',
    re.IGNORECASE
)

# 2. Macro Rates, Shifts, Percentages & Basis Points
RATES_AND_MACRO_PATTERN = re.compile(
    r'(?:[\d\.,]+\s*(?:%|per\s*cent|percent)(?:\s*(?:to|-|and)\s*[\d\.,]+\s*(?:%|per\s*cent|percent))?(?:\s+of\s+GDP)?)'
    r'|'
    r'(?:[\d\.,]+(?:%|per\s*cent)?\s*(?:to|-)\s*[\d\.,]+\s*(?:%|per\s*cent|percent))'
    r'|'
    r'(?:[\d\.,]+\s*(?:-|to|\s+)?(?:basis\s+points|bps))',
    re.IGNORECASE
)

# 3. Demographic Counts, Beneficiaries & Large Quantities
DEMOGRAPHICS_AND_QUANTITIES_PATTERN = re.compile(
    r'\b[\d\.,]+\s+(?:lakh\s+crore|crore|lakh|thousand|million|billion|trillion)\b'
    r'(?:\s+(?:additional\s+)?(?:people|citizens|electors|voters|civilians|men|women|residents|'
    r'beneficiaries|households|families|candidates|seats|homes|appeals|cases|tonnes|mt|jobs|farmers|indians))?',
    re.IGNORECASE
)

# 4. Physical, Energy, Agrarian & Climate Measurements
PHYSICAL_AND_CLIMATE_PATTERN = re.compile(
    r'\b[\d\.,]+\s*(?:°C|degrees?\s+celsius|degrees|centimetres|cm|kilometres|km|sq\s*km|'
    r'square\s+kilometres|hectares|acres|metres|GW|MW|gigawatts|megawatts|tonnes|mt|quintal|cusecs)\b',
    re.IGNORECASE
)

# 5. Proportions, Fractions & Ratios
PROPORTIONS_PATTERN = re.compile(
    r'\b\d+\s*-\s*\d+\s+(?:lead|series|victory|draw|win)\b'
    r'|'
    r'\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+out\s+of\s+(?:the\s+)?(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b'
    r'|'
    r'\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+of\s+(?:[A-Za-z’\'-]+\s+){0,2}\d+\b'
    r'|'
    r'\b(?:two-thirds|three-quarters|a\s+quarter|a\s+third|a\s+tenth|a\s+fifth|half|sixfold)\b',
    re.IGNORECASE
)

# 6. Compound Temporal Limits & Physical Constraints
THRESHOLDS_AND_LIMITS_PATTERN = re.compile(
    r'\b\d+(?:-|\s+)(?:day|month|year|hour|minute|quarter|round|judge|member|test|time|point)-'
    r'(?:old|high|streak|window|limit|curfew|drop|cut|hike|surge|bench|titlist|finalist|edition|deficit)\b'
    r'|'
    r'\b(?:under-18|two-hour|24-hour|best-of-five)\b',
    re.IGNORECASE
)

# 7. Discrete Counts & Raw High-Precision Numbers
DISCRETE_COUNTS_PATTERN = re.compile(
    r'\b[\d\.,]+\s+(?:people|indians|voters|electors|civilians|residents|newborns|babies|'
    r'bridges|roads|appeals|tribunals|colleges|institutions|launches|protesters|cases|'
    r'seats|candidates|graduates|states|countries|drones|rockets|firms|points|runs)\b'
    r'|'
    r'\b\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\b',
    re.IGNORECASE
)

# Exclusion Guards: Legal sections, forms, and pure calendar dates
NOISE_CONTEXT_REGEX = re.compile(
    r'\b(?:Article|Section|Schedule|Clause|Rule|Form|Order|Act)\s+[\dA-Za-z\(\)]+\b',
    re.IGNORECASE
)
CALENDAR_DATE_REGEX = re.compile(
    r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:,\s+\d{4})?\b'
    r'|\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)(?:\s+\d{4})?\b'
    r'|\b\d{1,2}:\d{2}(?:\s*(?:AM|PM|IST))?\b',
    re.IGNORECASE
)
STANDALONE_YEAR_REGEX = re.compile(
    r'\b(?<![₹\$\d\.,\-])(19\d\d|20\d\d)(?![%\d\.,\w\-])\b'
)

# ==============================================================================
# SPAN RESOLVER & MERGER
# ==============================================================================

def _get_exclusion_ranges(text: str) -> List[Tuple[int, int]]:
    exclusions = []
    for regex in [NOISE_CONTEXT_REGEX, CALENDAR_DATE_REGEX, STANDALONE_YEAR_REGEX]:
        for match in regex.finditer(text):
            exclusions.append((match.start(), match.end()))
    return exclusions


def _is_excluded(start: int, end: int, exclusions: List[Tuple[int, int]]) -> bool:
    for ex_start, ex_end in exclusions:
        if not (end <= ex_start or start >= ex_end):
            return True
    return False


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
                if "text" in last and "text" in current:
                    last["text"] = current.get("full_text", "")[last["start"]:last["end"]]
        else:
            merged.append(current)

    return merged


def extract_evidence_spans(paragraph_text: str) -> List[Dict[str, Any]]:
    """
    Direct replacement for your original function.
    Extracts strictly numeric and statistical spans, skipping legal noise and calendar dates.
    """
    exclusions = _get_exclusion_ranges(paragraph_text)
    raw_spans = []
    patterns = [
        FINANCIAL_PATTERN,
        RATES_AND_MACRO_PATTERN,
        DEMOGRAPHICS_AND_QUANTITIES_PATTERN,
        PHYSICAL_AND_CLIMATE_PATTERN,
        PROPORTIONS_PATTERN,
        THRESHOLDS_AND_LIMITS_PATTERN,
        DISCRETE_COUNTS_PATTERN
    ]

    for regex in patterns:
        for match in regex.finditer(paragraph_text):
            start, end = match.start(), match.end()
            if _is_excluded(start, end, exclusions):
                continue
            raw_spans.append({
                "start": start,
                "end": end,
                "text": paragraph_text[start:end].strip(),
                "full_text": paragraph_text
            })

    merged = merge_overlapping_spans(raw_spans)
    for s in merged:
        s.pop("full_text", None)
    return merged


# ==============================================================================
# PIPELINE HIGHLIGHTING UTILITIES
# ==============================================================================

def highlight_passage(passage: str, highlight_format: str = "html") -> Tuple[str, List[str]]:
    """
    Highlights all statistical and numeric entries in a passage.
    Returns the highlighted text along with the list of extracted numbers.
    """
    spans = extract_evidence_spans(passage)
    if not spans:
        return passage, []

    extracted_numbers = [s["text"] for s in spans]
    builder = []
    last_idx = 0

    for span in spans:
        builder.append(passage[last_idx:span["start"]])
        val = passage[span["start"]:span["end"]]
        if highlight_format == "html":
            builder.append(f'<mark class="stat-number">{val}</mark>')
        else:
            builder.append(f'**{val}**')
        last_idx = span["end"]

    builder.append(passage[last_idx:])
    return "".join(builder), extracted_numbers


def process_editorials_json(file_path: str, output_path: str = None, highlight_format: str = "html") -> Dict[str, Any]:
    """
    Reads daily editorial JSON, updates every 'passage' field, and stores extracted values.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for article in data.get("editorials", []):
        if "passage" in article and isinstance(article["passage"], str):
            highlighted, numbers = highlight_passage(article["passage"], highlight_format=highlight_format)
            article["passage_highlighted"] = highlighted
            article["passage_numeric_data"] = numbers

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    return data