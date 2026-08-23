import os
import sys
import json
import re
import time
from datetime import datetime
import requests
from google import genai
from google.genai import types

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
* Act as an uncompromising gatekeeper: select only high-yield, advanced C1/C2 terms, competitive-exam staples, and words that form the central pivot of the author's argument. Ruthlessly discard common, intermediate (B1/B2), or secondary filler words.
* Extract items strictly in the **order of their first appearance** in the editorial text.

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
* **Editorial Context:** All definitions, synonyms, antonyms, and mnemonics must strictly reflect the precise contextual usage in the text.

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
    "tone": "Author's primary tone in competitive-exam vocabulary (e.g., Analytical, Critical, Balanced, Appreciative, Cautious, Optimistic)",
    "tone_simple_explanation": "1–3 word simple meaning in parentheses (e.g., 'carefully examining')",
    "analysis_summary": "2–4 concise sentences in clear English (CEFR B1–B2). Must state the tone, explain why it was adopted relative to the main argument/conclusion, and summarize the author's overall stance without retelling the entire article."
  },
  "editorial_vocabulary": [
    {
      "order_index": 1,
      "word_or_phrase": "Mobilisation",
      "category": "Vocabulary",
      "part_of_speech": "Noun",
      "connotation": "Neutral",
      "easy_synonym": "rallying",
      "hindi_meaning": "लामबंदी",
      "mnemonic_trick": "Think of mobile + nation — getting the entire nation on the move for a unified cause.",
      "concise_meaning": "Organising people, resources, or armed forces for active service or a common public campaign.",
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
                    
                    # Quota Exhausted: Skip immediate retries for this key and move to next key[cite: 1]
                    if "429" in error_msg or "quota" in error_msg or "exhausted" in error_msg:
                        print(f"⚠️ Key {i+1} Quota Exhausted on {model_name}. Skipping to next key...")
                        break
                        
                    # Server Overload (503): Brief pause and retry on same key[cite: 1]
                    elif "503" in error_msg or "unavailable" in error_msg:
                        print(f"⚠️ Server Overloaded (503) on {model_name} (Key {i+1}). Waiting 10s...")
                        time.sleep(10)
                        continue
                        
                    # Generic Network/API Error[cite: 1]
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

# --- 4. MAIN PIPELINE ---
def run_schema_pipeline(
    input_file="today_editorials.json",
    output_file="schema.json",
    audit_file="schema_audit_log.md"
):
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file '{input_file}' not found.")

    with open(input_file, "r", encoding="utf-8") as f:
        input_data = json.load(f)

    editorials = input_data.get("editorials", [])
    total_editorials = len(editorials)
    print(f"📰 Found {total_editorials} editorials in {input_file}.")

    # Initialize Audit Log
    with open(audit_file, "w", encoding="utf-8") as log:
        log.write(f"# 🧠 Schema Generation Audit Log\n\nTotal Articles to Process: {total_editorials}\n\n---\n\n")

    processed_editorials = []

    # Process editorials one by one
    for index, editorial in enumerate(editorials, start=1):
        title = editorial.get("title", f"Editorial {index}")
        print(f"\n🚀 Processing Editorial [{index}/{total_editorials}]: {title}...")

        prompt = build_editorial_prompt(editorial)
        raw_response = call_gemini_with_rotation(prompt)

        # Append response to Audit Log
        with open(audit_file, "a", encoding="utf-8") as log:
            log.write(f"## 📰 Editorial {index}: {title}\n```json\n{raw_response}\n```\n\n---\n\n")

        try:
            generated_content = parse_llm_json(raw_response)
        except json.JSONDecodeError as json_err:
            print(f"⚠️ JSON parse error on editorial {index}: {json_err}. Fallback raw string stored.")
            generated_content = {"error": "Invalid JSON produced", "raw": raw_response}

        # Store original data first, followed by prompt-generated content[cite: 3, 4]
        merged_editorial = {
            "newspaper": editorial.get("newspaper", ""),
            "title": editorial.get("title", ""),
            "link": editorial.get("link", ""),
            "timestamp": editorial.get("timestamp", ""),
            "reading_time": editorial.get("reading_time", ""),
            "passage": editorial.get("passage", ""),
            "editorial_metadata": generated_content.get("editorial_metadata", {}),
            "analysis": generated_content.get("analysis", {}),
            "editorial_vocabulary": generated_content.get("editorial_vocabulary", [])
        }

        processed_editorials.append(merged_editorial)
        time.sleep(3)

    # Build final schema payload
    final_output = {
        "date_scraped": input_data.get("date_scraped", ""),
        "total_articles": len(processed_editorials),
        "editorials": processed_editorials
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=4, ensure_ascii=False)

    # 💾 Trigger 7-Day Rolling Backup
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
                requests.post(f"[https://api.telegram.org/bot](https://api.telegram.org/bot){bot_token}/sendMessage", json={
                    "chat_id": admin_chat_id,
                    "text": f"🚨 **CRITICAL ERROR (Schema Generator):**\nPipeline failed during execution!\n\n`{e}`",
                    "parse_mode": "Markdown"
                })
            except Exception:
                pass
        print(f"Fatal pipeline error: {e}")
        sys.exit(1)