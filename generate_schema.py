import os
import sys
import json
import re
import time
from datetime import datetime, timezone, timedelta
import requests
from google import genai
from google.genai import types
from concurrent.futures import ThreadPoolExecutor

# Timezone definition
IST = timezone(timedelta(hours=5, minutes=30))

# Load keys safely from GitHub Secrets or Environment[cite: 1, 2]
API_KEYS = [
    os.environ.get("GEMINI_KEY_1"),
    os.environ.get("GEMINI_KEY_2"),
    os.environ.get("GEMINI_KEY_3")
]

# Strict Model Priority Order[cite: 1]
MODELS = [
    'gemini-3.7-flash',  # 1st Priority[cite: 1]
    'gemini-3.6-flash',  # 2nd Fallback[cite: 1]
    'gemini-3.5-flash'   # 3rd Fallback[cite: 1]
]

# --- EMBEDDED PROMPT TEMPLATE ---[cite: 4]
PROMPT_TEMPLATE = r"""# System Role
You are an elite linguistic analyst and competitive-exam vocabulary curator. Your task is to process a single editorial, extract/generate its metadata, perform a concise critical analysis, and create a curated master list of high-yield vocabulary items strictly formatted as a valid JSON object. Do not print, reproduce, or echo the editorial text.

---

# Core Processing Rules

### 1. Metadata Generation Rule (Subtitle / Deck)
* If the source editorial explicitly includes a subtitle, capture it verbatim.
* **If no subtitle is provided in the source**, you MUST synthesize an engaging, high-impact **1-sentence subtitle/deck (8–15 words)** that encapsulates the central takeaway or core argument of the editorial. NEVER output `"N/A"` for the subtitle.

### 2. Ruthless Curation & Chronological Order
* Extract **20–25 items** from the editorial.
* Act as an uncompromising gatekeeper: select only high-yield, advanced C1/C2 terms, competitive-exam staples, and words that form the central pivot of the author's argument. Prioritise vocabulary useful for Banking, SSC, CAT and similar competitive exams. Ruthlessly discard common, intermediate (B1/B2), or secondary filler words.
* Extract items strictly in the **order of their first appearance** in the editorial text.
* **Verbatim In-Text Form (No Lemmatization):** Extract words/phrases in their **exact grammatical form as written in the passage** (e.g., if the text has *"conceded"*, write `"Conceded"`, NOT the base root `"Concede"`; if the text has *"retreating"*, write `"Retreating"`, NOT `"Retreat"`). Do not reduce words to infinitive/root dictionary forms.

### 3. Category Balancing
Actively scan the text to balance the 20–25 items across these categories (do not select single words only):
* **Vocabulary** (Single advanced words)
* **One-Word Substitutions**
* **Fixed Prepositions** (e.g., *wary of*, *prone to*, *adept at*)
* **Phrasal Verbs** (e.g., *shore up*, *rein in*)
* **Idioms & Phrases**
* **Foreign Words** (e.g., *status quo*, *ad hoc*, *fait accompli*)

### 4. Linguistic Standards
* **British English:** Use British English spellings exclusively across all fields (e.g., *mobilisation*, *colour*, *analyse*).
* **Editorial Context:** All definitions, synonyms, antonyms, and mnemonics must strictly reflect the precise contextual usage in the text. Prefer clear, familiar, exam-useful synonyms and antonyms; avoid unnecessarily obscure alternatives.

---

# JSON Output Schema

Output exclusively a valid, parseable JSON object matching this exact structure:

```json
{
  "editorial_metadata": {
    "title": "Main headline of the editorial",
    "subtitle": "Generated crisp 1-sentence summary deck (8–15 words) explaining the core issue if not present in the source",
    "author": "Author name / byline (or 'Editorial Board' / 'N/A' if unknown)",
    "topic": "Core subject domain (e.g., Geopolitics, Fiscal Policy, Judicial Reform, Public Health)"
  },
  "analysis": {
    "tone": "Author's primary tone in competitive-exam vocabulary (e.g., Analytical, Critical, Appreciative, Concerned, Cautious, Persuasive / Advocative, Optimistic, Pessimistic, Balanced, Objective / Neutral, Informative / Explanatory, Sceptical, Disapproving, Cautionary, Sarcastic, Cynical, Empathetic, Conciliatory, Hostile, Indifferent, Admonitory)",
    "tone_simple_explanation": "1–4 word simple meaning (e.g., 'warning of dangers')",
    "analysis_summary": "2–3 concise sentences in clear B1–B2 English. Explain why the author uses this tone, what key argument/evidence establishes it, and what the author is trying to highlight, question, warn about, or advocate. Do not retell the article."
  },
  "editorial_vocabulary": [
    {
      "order_index": 1,
      "word_or_phrase": "Exact word or phrase as used in the passage (e.g., 'Conceded', NOT 'Concede')",
      "category": "Vocabulary",
      "part_of_speech": "Noun",
      "connotation": "Neutral",
      "easy_synonym": "A simple, familiar synonym that students can easily understand and remember while preserving the contextual meaning.",
      "hindi_meaning": "लामबंदी",
      "mnemonic_trick": "A short, memorable word-association or mental image that genuinely helps recall the meaning; use a natural sound/word connection where possible, and never force a weak association.",
      "concise_meaning": "A concise, context-accurate definition in simple English that clearly explains the word's meaning without merely repeating the word or its synonym.",
      "british_synonyms": [
        "organising",
        "marshalling",
        "assembling"
      ],
      "british_antonyms": [
        "demobilisation",
        "dispersal",
        "inactivation"
      ]
    }
  ]
}"""

# --- 1. MODEL TIER ROTATION & RETRY ---[cite: 1]
def call_gemini_with_rotation(prompt):
    """
    Exhausts each model tier across all available API keys before falling back
    to the next model tier (3.7-flash -> 3.6-flash -> 3.5-flash).[cite: 1]
    """
    max_retries_per_key = 2
    
    for model_name in MODELS:
        print(f"\n🎯 [MODEL TIER] Trying Priority Model: {model_name}")
        
        for i, key in enumerate(API_KEYS):
            if not key:
                continue
            
            client = genai.Client(api_key=key)
            
            for attempt in range(max_retries_per_key):
                try:
                    print(f"🤖 Attempting with Key {i+1} using {model_name} (Try {attempt+1}/{max_retries_per_key})...")
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.3,
                            response_mime_type="application/json"
                        )
                    )
                    return response.text.strip()
                    
                except Exception as e:
                    error_msg = str(e).lower()
                    
                    if "429" in error_msg or "quota" in error_msg or "exhausted" in error_msg:
                        print(f"⚠️ Key {i+1} Quota Exhausted on {model_name}. Skipping to next key...")
                        break
                    elif "503" in error_msg or "unavailable" in error_msg:
                        print(f"⚠️ Server Overloaded (503) on {model_name} (Key {i+1}). Waiting 10s...")
                        time.sleep(10)
                        continue
                    else:
                        print(f"⚠️ Error on Key {i+1} ({model_name}): {e}")
                        time.sleep(3)
                        
        print(f"🔻 Model '{model_name}' exhausted across all available keys. Triggering fallback model...")

    raise RuntimeError("🚨 All priority models (3.7 -> 3.6 -> 3.5) and API keys exhausted!")

# --- 2. PROMPT CONSTRUCTOR ---
def build_editorial_prompt(editorial):
    """Appends editorial content to the embedded prompt instructions."""
    article_title = editorial.get("title", "N/A")
    newspaper = editorial.get("newspaper", "N/A")
    passage = editorial.get("passage", "")

    return f"""{PROMPT_TEMPLATE}

---

# INPUT EDITORIAL
Newspaper: {newspaper}
Title: {article_title}

Passage:
\"\"\"
{passage}
\"\"\"
"""

# --- 3. JSON PARSER ---
def parse_llm_json(raw_text):
    """Strips markdown fences and parses string to a dictionary."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    return json.loads(cleaned.strip())

# --- BACKUP & RETENTION ENGINE ---
def save_backup(final_output, input_date_str=None, backup_dir="backups", max_days=7):
    """
    Saves a copy of schema.json named '{YYYY-MM-DD}_{Day}.json' and
    purges backups older than 7 days (rolling 1-week retention).
    """
    os.makedirs(backup_dir, exist_ok=True)
    
    if input_date_str:
        try:
            dt = datetime.strptime(input_date_str, "%Y-%m-%d")
        except ValueError:
            dt = datetime.now()
    else:
        dt = datetime.now()

    date_str = dt.strftime("%Y-%m-%d")
    day_name = dt.strftime("%A")
    backup_filename = f"{date_str}_{day_name}.json"
    backup_filepath = os.path.join(backup_dir, backup_filename)

    with open(backup_filepath, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=4, ensure_ascii=False)
    print(f"📦 Backup created: '{backup_filepath}'")

    existing_backups = sorted([
        f for f in os.listdir(backup_dir) 
        if f.endswith(".json") and re.match(r"^\d{4}-\d{2}-\d{2}_\w+\.json$", f)
    ])
    
    if len(existing_backups) > max_days:
        stale_backups = existing_backups[:-max_days]
        for stale in stale_backups:
            stale_path = os.path.join(backup_dir, stale)
            os.remove(stale_path)
            print(f"🗑️ Removed stale backup (older than 7 days): '{stale_path}'")

# --- 4. MAIN PIPELINE (PARALLELIZED) ---
def _process_single_editorial(args):
    index, editorial, total_editorials = args
    title = editorial.get("title", f"Editorial {index}")
    print(f"🚀 Processing Editorial [{index}/{total_editorials}]: {title}...")

    prompt = build_editorial_prompt(editorial)
    raw_response = call_gemini_with_rotation(prompt)

    try:
        generated_content = parse_llm_json(raw_response)
    except json.JSONDecodeError as json_err:
        print(f"⚠️ JSON parse error on editorial {index}: {json_err}. Fallback raw string stored.")
        generated_content = {"error": "Invalid JSON produced", "raw": raw_response}

    merged_editorial = {**editorial}
    merged_editorial.update({
        "editorial_metadata": generated_content.get("editorial_metadata", {}),
        "analysis": generated_content.get("analysis", {}),
        "editorial_vocabulary": generated_content.get("editorial_vocabulary", [])
    })

    return index, merged_editorial, raw_response

def run_schema_pipeline(
    input_file="today_editorials.json",
    output_file="schema.json",
    audit_file="schema_audit_log.md"
):
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file '{input_file}' not found.")

    with open(input_file, "r", encoding="utf-8") as f:
        input_data = json.load(f)

    today_ist = datetime.now(IST).strftime("%Y-%m-%d")
    date_scraped = input_data.get("date_scraped", "")
    
    if date_scraped != today_ist:
        raise ValueError(
            f"Stale data detected! 'today_editorials.json' is from '{date_scraped}', "
            f"but today is '{today_ist}' (IST)."
        )

    editorials = input_data.get("editorials", [])
    total_editorials = len(editorials)
    
    if total_editorials == 0:
        raise ValueError("today_editorials.json contains 0 editorials to process.")

    print(f"📰 Found {total_editorials} fresh editorials for {today_ist}. Processing concurrently...")

    # Run all articles in parallel using worker threads
    tasks = [(i, ed, total_editorials) for i, ed in enumerate(editorials, start=1)]
    with ThreadPoolExecutor(max_workers=min(4, total_editorials)) as executor:
        results = list(executor.map(_process_single_editorial, tasks))

    # Maintain original chronological article order
    results.sort(key=lambda x: x[0])
    processed_editorials = [r[1] for r in results]

    # Write the complete audit log
    with open(audit_file, "w", encoding="utf-8") as log:
        log.write(f"# 🧠 Schema Generation Audit Log\n\nTotal Articles: {total_editorials}\n\n---\n\n")
        for idx, ed, raw_resp in results:
            log.write(f"## 📰 Editorial {idx}: {ed.get('title')}\n```json\n{raw_resp}\n```\n\n---\n\n")

    final_output = {
        "date_scraped": input_data.get("date_scraped", ""),
        "total_articles": len(processed_editorials),
        "editorials": processed_editorials
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=4, ensure_ascii=False)

    save_backup(final_output, input_date_str=input_data.get("date_scraped"))
    print(f"\n✅ All {total_editorials} editorials processed and saved to '{output_file}'!")

# --- 5. RUNNER & TELEGRAM ALERTS ---
if __name__ == "__main__":
    try:
        run_schema_pipeline()
    except Exception as e:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        admin_chat_id = os.environ.get("ADMIN_CHAT_ID")
        if bot_token and admin_chat_id:
            try:
                requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                    "chat_id": admin_chat_id,
                    "text": f"🚨 **STEP 2 FAILED (Schema Generator):**\n\n**Error:**\n`{e}`",
                    "parse_mode": "Markdown"
                })
            except Exception:
                pass
        print(f"Fatal pipeline error: {e}")
        sys.exit(1)