import os
import sys
import json
import re
import time
import requests
from google import genai
from google.genai import types

# Load keys safely from GitHub Secrets or Environment
API_KEYS = [
    os.environ.get("GEMINI_KEY_1"),
    os.environ.get("GEMINI_KEY_2"),
    os.environ.get("GEMINI_KEY_3")
]

# Models for rotation and fallback
MODELS = [
    'gemini-3.7-flash',
    'gemini-3.6-flash',
    'gemini-3.5-flash'
]

# --- 1. GEMINI BULLDOZER (KEY ROTATION & RETRY) ---
def call_gemini_with_rotation(prompt):
    """Tries keys and models to handle rate limits or server overloads."""
    max_retries = 3
    
    for attempt in range(max_retries):
        for i, key in enumerate(API_KEYS):
            if not key:
                continue
            client = genai.Client(api_key=key)
            
            for model_name in MODELS:
                try:
                    print(f"🤖 Attempting with Key {i+1} using {model_name} (Attempt {attempt+1}/{max_retries})...")
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
                        print(f"⚠️ Key {i+1} ({model_name}) Quota Exhausted. Rotating to fallback model/key...")
                        continue
                    elif "503" in error_msg or "unavailable" in error_msg:
                        print(f"⚠️ Server Overload (503) on {model_name}. Waiting 20 seconds...")
                        time.sleep(20)
                        continue 
                    else:
                        print(f"⚠️ Error on Key {i+1} ({model_name}): {e}")
                        time.sleep(3)
                        
    raise RuntimeError("🚨 All API keys and model fallbacks failed due to sustained errors.")

# --- 2. PROMPT BUILDER ---
def build_editorial_prompt(editorial, prompt_template):
    """Combines prompt.md guidelines with the current editorial content."""
    article_title = editorial.get("title", "N/A")
    newspaper = editorial.get("newspaper", "N/A")
    passage = editorial.get("passage", "")

    return f"""{prompt_template}

---

# INPUT EDITORIAL
Newspaper: {newspaper}
Title: {article_title}

Passage:
\"\"\"
{passage}
\"\"\"
"""

# --- 3. CLEAN & PARSE JSON ---
def parse_llm_json(raw_text):
    """Extracts and parses JSON string safely, removing markdown code blocks."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    return json.loads(cleaned.strip())

# --- 4. MAIN PIPELINE ---
def run_schema_pipeline(
    input_file="today_editorials.json",
    prompt_file="prompt.md",
    output_file="schema.json",
    audit_file="schema_audit_log.md"
):
    # 1. Load inputs
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file '{input_file}' not found.")

    with open(input_file, "r", encoding="utf-8") as f:
        input_data = json.load(f)

    # Load prompt.md if present, otherwise fall back to embedded template
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as f:
            prompt_template = f.read()
    else:
        raise FileNotFoundError(f"Prompt file '{prompt_file}' not found.")

    editorials = input_data.get("editorials", [])
    total_editorials = len(editorials)
    print(f"📰 Found {total_editorials} editorials in {input_file}.")

    # Initialize Audit Log
    with open(audit_file, "w", encoding="utf-8") as log:
        log.write(f"# 🧠 Schema Generation Audit Log\n\nTotal Articles to Process: {total_editorials}\n\n---\n\n")

    processed_editorials = []

    # 2. Iterate through each editorial one at a time
    for index, editorial in enumerate(editorials, start=1):
        title = editorial.get("title", f"Editorial {index}")
        print(f"\n🚀 Processing Editorial [{index}/{total_editorials}]: {title}...")

        prompt = build_editorial_prompt(editorial, prompt_template)
        raw_response = call_gemini_with_rotation(prompt)

        # Log raw response
        with open(audit_file, "a", encoding="utf-8") as log:
            log.write(f"## 📰 Editorial {index}: {title}\n```json\n{raw_response}\n```\n\n---\n\n")

        try:
            generated_content = parse_llm_json(raw_response)
        except json.JSONDecodeError as json_err:
            print(f"⚠️ JSON parsing error on editorial {index}: {json_err}. Storing raw string fallback.")
            generated_content = {"error": "Invalid JSON produced", "raw": raw_response}

        # Merge: Original editorial data FIRST, followed by prompt-generated schema content
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
        time.sleep(3) # Short breather between editorial requests

    # 3. Assemble and save final schema.json
    final_output = {
        "date_scraped": input_data.get("date_scraped", ""),
        "total_articles": len(processed_editorials),
        "editorials": processed_editorials
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=4, ensure_ascii=False)

    print(f"\n✅ All {total_editorials} editorials processed and successfully saved to '{output_file}'!")

# --- 5. EXECUTION & TELEGRAM NOTIFICATION ---
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
