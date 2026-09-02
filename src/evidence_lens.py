import re
from typing import List, Dict, Any

# ==============================================================================
# COMPILED EVIDENCE PATTERNS (INDIA EDITORIAL SPECIFIC)
# ==============================================================================

# 1. Financials, Currencies, Budget Targets & Prices
FINANCIAL_PATTERN = re.compile(
    r'\b(?:pay\s+up\s+to|cost\s+of|budget\s+of|revenue\s+of|valued\s+at|average\s+of|from\s+(?:an\s+average\s+of\s+)?|'
    r'capex\s+(?:target\s+)?of|outlay\s+of|allocation\s+of|collections?\s+of|target\s+of|package\s+of|worth\s+over|worth)?\s*'
    r'(?:Rs\.?|₹|\$|€|USD|EUR|GBP)\s*[\d\.,]+\s*(?:lakh\s+crore|crore|lakh|thousand|million|billion|trillion)?'
    r'(?:\s*(?:to|-|and)\s*(?:Rs\.?|₹|\$|€|USD|EUR|GBP)?\s*[\d\.,]+\s*(?:lakh\s+crore|crore|lakh|thousand|million|billion|trillion)?)?'
    r'(?:\s*per\s+(?:kg|tonne|quintal|litre|barrel|unit|month|annum|capita|year))?'
    r'(?:\s+(?:over\s+a\s+decade|within\s+a\s+month|within\s+a\s+year|per\s+year|annually|in\s+FY\d+))?\b',
    re.IGNORECASE
)

# 2. Rates, Inflation, Basis Points, GDP Shifts & Percentage of GDP
RATES_AND_MACRO_PATTERN = re.compile(
    r'\b(?:fiscal\s+deficit|revenue\s+deficit|current\s+account\s+deficit|growth|inflation|retail\s+inflation|gdp|unemployment\s+rate|turnout|quota|reservation|tariff)\s+'
    r'(?:of|at|to|by|rose\s+to|fell\s+to|stood\s+at)?\s*'
    r'(?:barely|nearly|almost|at least|more than|less than|around)?\s*'
    r'[\d\.,]+\s*(?:%|per\s+cent)(?:\s+of\s+GDP)?\b'
    r'|\b(?:hiked|raised|cut|reduced|lowered|slashed|eased)\s+(?:the\s+repo\s+rate\s+)?(?:by|to)\s+[\d\.,]+\s*(?:basis\s+points|bps)\b'
    r'|\b[\d\.,]+\s*(?:basis\s+points|bps)\s+(?:rate\s+cut|hike|reduction|increase)\b'
    r'|\b(?:slashed|increased|decreased|rose|fell|dropped|surged|declined|climbed|soared|shrunk|contracted|expanded|grew)\s+'
    r'(?:by|to|from)\s+(?:barely|nearly|almost|at least|more than|less than)?\s*'
    r'(?:Rs\.?|₹|\$|€)?\s*[\d\.,]+\s*(?:%|per\s+cent|lakh|crore|million|billion|points|tonnes|mt)?\s*'
    r'(?:to\s+(?:zero|[\d\.,]+\s*(?:%|per\s+cent|lakh|crore|million|billion|points|tonnes|mt)?))?\b',
    re.IGNORECASE
)

# 3. Proportions, Fractions & Relational Counts
PROPORTIONS_PATTERN = re.compile(
    r'\b(?:nearly|almost|barely|hardly|more than|less than|about|at least|only)?\s*'
    r'(?:a\s+tenth|a\s+fifth|a\s+quarter|a\s+third|half|two-thirds|three-quarters|one-tenth|one-fifth)\s+'
    r'of\s+(?:the\s+)?(?:[\w’\'-]+\s+){0,6}'
    r'(?:[\d\.,]+\s*(?:%|per\s+cent|mt|tonnes|lakh|crore|million|billion|electors|voters|appeals|households|names|people|civilians|men|women|points))?'
    r'|\b(?:barely|nearly|almost|at least|more than|less than|only)?\s*'
    r'[\d\.,]+\s*(?:%|per\s+cent|lakh|crore|thousand|million|billion)?\s+'
    r'(?:of\s+(?:the\s+)?(?:nearly|almost|barely|about)?\s*(?:[\d\.,]+\s*(?:lakh|crore|thousand|million|billion)?\s+)?(?:[\w’\'-]+\s+){0,4}'
    r'(?:tribunals|appeals|electors|constituencies|cases|members|respondents|dealers|mills|people|districts|decisions|names|households|judges|courts)|and\s+[\d\.,]+\s*(?:%|per\s+cent)\s+respectively)\b'
    r'|\b(?:nine|eight|seven|six|five|four|three|two|one|\d+)\s+of\s+[\w’\'-]+(?:\s+[\w’\'-]+)?(?:’s|\'s)?\s+\d+\b',
    re.IGNORECASE
)

# 4. Energy, Agriculture, Climate & Physical Measurements
PHYSICAL_AND_CLIMATE_PATTERN = re.compile(
    r'\b(?:installed\s+capacity\s+of|target\s+of|capacity\s+of|generation\s+of)?\s*'
    r'[\d\.,]+\s*(?:GW|MW|gigawatts|megawatts|kilowatts)\b'
    r'|\b(?:warming\s+(?:limit\s+)?of|threshold\s+of|target\s+of|rise\s+of)?\s*[\d\.,]+\s*(?:°C|degrees?\s+Celsius)\s*(?:threshold|limit|target)?\b'
    r'|\b(?:MSP\s+of|procurement\s+of|stock\s+of|buffer\s+stock\s+of|shortfall\s+of|diversion(?:s)?\s+of|production\s+of)\s+'
    r'(?:Rs\.?|₹)?\s*[\d\.,]+\s*(?:per\s+quintal|quintal|mt|million\s+tonnes|tonnes|lakh\s+tonnes|kg)\b'
    r'|\b(?:spanning|covering|across|over|area\s+of)\s+[\d\.,]+\s*(?:hectares|sq\s+km|square\s+kilometres|acres)\b',
    re.IGNORECASE
)

# 5. Demographics, Welfare Beneficiaries, Judicial Pendency & Casualties
DEMOGRAPHICS_AND_IMPACT_PATTERN = re.compile(
    r'\b(?:issues\s+of|killing\s+of|murder\s+of|bodies\s+of|loss\s+of|settlement\s+between\s+[\w\s]+and|died\s+in\s+[\w\s]+|pendency\s+of|backlog\s+of|coverage\s+of|free\s+foodgrains\s+to|cash\s+transfer\s+of|transferred\s+to|support\s+to)?\s*'
    r'(?:at\s+least|more\s+than|less\s+than|nearly|almost|barely|about|over)?\s*'
    r'[\d\.,]+\s+(?:lakh|crore|thousand|million|billion)\s*'
    r'(?:Dalits|citizens|electors|voters|people|civilians|men|women|residents|users|households|beneficiaries|families|states|US\s+states|deaths|casualties|cases|appeals|internally\s+displaced\s+people)\b',
    re.IGNORECASE
)

# 6. Regulatory Limits, Ceilings & Policy Curfews
THRESHOLDS_AND_LIMITS_PATTERN = re.compile(
    r'\b(?:holding\s+(?:any\s+[\w\s]+)?beyond|beyond|within|at least|up to|capped at|maximum of|minimum of|limits?\s+for|ceiling\s+of)\s+'
    r'(?:[\d\.,]+|one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:-hour\s+daily)?\s*(?:days|months|years|hours|tonnes|mt|kg|seats|crore|lakh|percent|per cent|users?)\b'
    r'|\b[\d\.,]+\s*(?:tonnes|mt|kg|crore|lakh|seats)\s+or\s+more\b'
    r'|\b(?:two-hour|one-hour|24-hour)\s+daily\s+limits?\b'
    r'|\b(?:midnight-to-6-am|12\s*am\s*to\s*6\s*am)\s+curfew\b'
    r'|\bunder-18\s+users?\b'
    r'|\b(?:50%|fifty\s+per\s+cent)\s+(?:reservation\s+)?ceiling\b',
    re.IGNORECASE
)

# 7. Evidentiary Studies, Survey Years & Baseline Scrutiny
EVIDENTIARY_BENCHMARKS_PATTERN = re.compile(
    r'\b(?:a\s+)?(?:19\d\d|20\d\d)\s+(?:Census(?:\s+data)?|NFHS-\d+(?:\s+survey|\s+data)?|study|survey|report|data|review)\b'
    r'|\bfirst\s+review\s+(?:[\w\s\(\)]+)?since\s+(?:19\d\d|20\d\d)\b'
    r'|\b(?:lowest|highest|steepest)\s+since\s+(?:19\d\d|20\d\d)\b',
    re.IGNORECASE
)

# Narrative / Calendar Exclusions (Filters solitary dates and years)
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
        FINANCIAL_PATTERN,
        RATES_AND_MACRO_PATTERN,
        PROPORTIONS_PATTERN,
        PHYSICAL_AND_CLIMATE_PATTERN,
        DEMOGRAPHICS_AND_IMPACT_PATTERN,
        THRESHOLDS_AND_LIMITS_PATTERN,
        EVIDENTIARY_BENCHMARKS_PATTERN
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