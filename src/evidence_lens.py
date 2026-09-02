import os
import re
import json
from typing import List, Dict, Any

# ==============================================================================
# SAFE OFFLINE FALLBACK (Zero proper nouns, zero acronym clutter)
# ==============================================================================
SAFE_FALLBACK_PATTERNS = [
    # Constitutional Articles & Statutory Laws
    re.compile(r'\b(?:Article|Art\.)\s+\d+[A-Z]?(?:\(\d+\))?\b', re.IGNORECASE),
    re.compile(r'\bSection\s+\d+[A-Z]?(?:\s+of\s+the\s+[A-Za-z\s]+)?\b', re.IGNORECASE),
    re.compile(r'\b\d+(?:st|nd|rd|th)\s+Constitutional\s+Amendment(?:\s+Act)?\b', re.IGNORECASE),
    re.compile(r'\b(?:two|three|five|seven|nine)-judge\s+bench\b', re.IGNORECASE),
    
    # Exact Macroeconomic Data Points
    re.compile(r'\b[\d\.,]+\s*(?:%|per\s+cent)\b(?:\s+(?:growth|inflation|deficit|increase|drop|surge|contracted))?', re.IGNORECASE),
    re.compile(r'\b[\d\.,]+\s*(?:basis\s+points|bps)\b', re.IGNORECASE),
    re.compile(r'\b(?:Rs\.?|₹|\$)\s*[\d\.,]+\s*(?:lakh\s+crore|crore|lakh|thousand|million|billion)\b', re.IGNORECASE),
]

def fallback_regex_spans(text: str) -> List[Dict[str, int]]:
    """Clean fallback used only if Gemini is unreachable or returns an error."""
    spans = []
    for pattern in SAFE_FALLBACK_PATTERNS:
        for match in pattern.finditer(text):
            spans.append({"start": match.start(), "end": match.end()})
    return spans


# ==============================================================================
# GEMINI 3.5 FLASH LITE EVIDENCE EXTRACTION
# ==============================================================================
def get_api_keys() -> List[str]:
    """Collects all configured Gemini API keys into a prioritized pool."""
    keys = []
    # 1. Check comma-separated multi-key secret
    multi_keys = os.getenv("GEMINI_API_KEYS", "")
    if multi_keys:
        keys.extend([k.strip() for k in multi_keys.split(",") if k.strip()])
    
    # 2. Check legacy single-key secret
    single_key = os.getenv("GEMINI_API_KEY", "").strip()
    if single_key and single_key not in keys:
        keys.append(single_key)
        
    return keys


def extract_article_evidence(full_passage: str) -> List[str]:
    """
    Calls Gemini 3.5 Flash Lite with automatic multi-key failover.
    If Key 1 hits a 429 or network glitch, it immediately rotates to Key 2 and 3.
    """
    if not full_passage or not full_passage.strip():
        return []

    api_keys = get_api_keys()
    if not api_keys:
        print("⚠️ No GEMINI_API_KEYS found. Using offline safe fallback.")
        return []

    from google import genai
    from google.genai import types

    prompt = (
        "You are an expert exam analyst for UPSC and Banking competitive exams.\n"
        "Analyze this editorial and extract 2 to 4 high-yield factual or quantitative phrases "
        "that an aspirant must memorize for Mains answers.\n\n"
        "STRICT RULES:\n"
        "1. ONLY select: Constitutional Articles/Amendments, statutory sections, "
        "macroeconomic metrics with units (inflation rates, GDP shifts, basis points, outlays), "
        "or specific government committee/policy recommendations.\n"
        "2. NEVER extract standalone words, countries, or acronyms (NO 'NATO', 'RBI', 'G20', 'Court').\n"
        "3. MUST BE EXACT, VERBATIM SUBSTRINGS copied directly from the passage text. "
        "Do NOT paraphrase, alter, or edit even a single word.\n\n"
        f"Editorial Passage:\n\"\"\"\n{full_passage}\n\"\"\""
    )

    # Rotate through the key pool on failure
    for idx, key in enumerate(api_keys, start=1):
        try:
            client = genai.Client(api_key=key, http_options={"timeout": 5.0})

            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "quotes": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Exact verbatim phrases copied from the article text."
                            }
                        },
                        "required": ["quotes"]
                    }
                )
            )

            data = json.loads(response.text)
            raw_quotes = data.get("quotes", [])
            valid_quotes = [q.strip() for q in raw_quotes if q and len(q.strip().split()) >= 2]
            
            if valid_quotes:
                return valid_quotes

        except Exception as e:
            print(f"⚠️ API Key #{idx} failed ({e}). Rotating to next key...")
            continue

    print("⚠️ All Gemini API keys failed or exhausted. Using offline safe fallback.")
    return []


def extract_evidence_spans(paragraph_text: str, evidence_quotes: List[str] = None) -> List[Dict[str, int]]:
    """
    Maps extracted evidence quotes to exact start/end character offsets in each paragraph.
    Falls back gracefully to safe numeric regex if quotes are unavailable.
    """
    if not paragraph_text or not paragraph_text.strip():
        return []

    spans = []

    # 1. Match AI-extracted verbatim quotes if available
    if evidence_quotes:
        for quote in evidence_quotes:
            start_idx = paragraph_text.find(quote)
            if start_idx != -1:
                spans.append({
                    "start": start_idx,
                    "end": start_idx + len(quote)
                })

    # 2. If AI returned no valid quotes for this paragraph, run safe numeric fallback
    if not spans:
        spans = fallback_regex_spans(paragraph_text)

    # Sort and deduplicate overlapping spans
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