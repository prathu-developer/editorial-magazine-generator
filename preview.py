import os
import re
import json
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader

def clean_and_highlight(passage_text, vocab_items):
    raw_paras = [p.strip() for p in passage_text.split("\n\n") if p.strip()]
    cleaned = []
    sorted_vocab = sorted(vocab_items, key=lambda x: len(x.get("word_or_phrase", "")), reverse=True)
    for p in raw_paras:
        if p.startswith("Published") or p.startswith("Updated") or p.startswith("- August") or p.startswith("-August"):
            continue
        h = p
        for item in sorted_vocab:
            term = item.get("word_or_phrase", "").strip()
            idx = item.get("order_index", "")
            if term:
                pattern = re.compile(rf'\b({re.escape(term)})\b', re.IGNORECASE)
                h = pattern.sub(rf'<span class="vocab-hl">\1<sup class="v-idx">{idx}</sup></span>', h)
        cleaned.append(h)
    return cleaned

def generate_preview():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(base_dir, "schema.json"), "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # Pure standard-library IST calculation (100% compatible with Windows & Linux)
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    ist_time = datetime.now(ist_offset)
    formatted_date_ist = ist_time.strftime(f"%B {ist_time.day}, %Y")

    processed = []
    toc = []
    page_counter = 3

    for art in raw_data.get("editorials", []):
        v_list = art.get("editorial_vocabulary", [])
        cats = {
            "core_vocab": [v for v in v_list if v.get("category") == "Vocabulary"],
            "fixed_prepositions": [v for v in v_list if v.get("category") == "Fixed Prepositions"],
            "phrasal_verbs": [v for v in v_list if v.get("category") == "Phrasal Verbs"],
            "one_word_subs": [v for v in v_list if v.get("category") == "One-Word Substitutions"],
            "idioms": [v for v in v_list if v.get("category") == "Idioms & Phrases"],
            "foreign_words": [v for v in v_list if v.get("category") == "Foreign Words"]
        }
        toc.append({
            "title": art.get("title", ""),
            "newspaper": art.get("newspaper", "Editorial"),
            "page_num": f"Page {page_counter:02d}"
        })
        processed.append({
            "newspaper": art.get("newspaper", "Editorial"),
            "title": art.get("title", ""),
            "subtitle": art.get("editorial_metadata", {}).get("subtitle"),
            "topic": art.get("editorial_metadata", {}).get("topic", "General Studies"),
            "reading_time": art.get("reading_time", "2 min read"),
            "analysis": {
                "tone": art.get("analysis", {}).get("tone", "Analytical"),
                "tone_simple_explanation": art.get("analysis", {}).get("tone_simple_explanation", "").strip("()"),
                "analysis_summary": art.get("analysis", {}).get("analysis_summary", "")
            },
            "paragraphs": clean_and_highlight(art.get("passage", ""), v_list),
            "all_vocab": v_list,
            "categorized_vocab": cats,
            "page_p1": page_counter,
            "page_p2": page_counter + 1
        })
        page_counter += 2

    # Relative web paths for local browser / VS Code preview
    payload = {
        "date_formatted": formatted_date_ist,
        "date_scraped": raw_data.get("date_scraped", formatted_date_ist),
        "has_front_cover": os.path.exists(os.path.join(base_dir, "assets", "front_cover_bg.jpg")),
        "front_cover_src": "../assets/front_cover_bg.jpg",
        "has_toc_bg": os.path.exists(os.path.join(base_dir, "assets", "toc_bg.jpg")),
        "toc_bg_src": "../assets/toc_bg.jpg",
        "has_back_cover": os.path.exists(os.path.join(base_dir, "assets", "back_cover_bg.jpg")),
        "back_cover_src": "../assets/back_cover_bg.jpg",
        "has_watermark": os.path.exists(os.path.join(base_dir, "assets", "watermark.png")),
        "watermark_src": "../assets/watermark.png",
        "toc_entries": toc,
        "articles": processed
    }

    env = Environment(loader=FileSystemLoader(os.path.join(base_dir, "templates")))
    template = env.get_template("template.html")
    os.makedirs(os.path.join(base_dir, "build"), exist_ok=True)
    out_file = os.path.join(base_dir, "build", "rendered_content.html")
    
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(template.render(data=payload))
        
    print(f"✨ Preview generated: {out_file}")

if __name__ == "__main__":
    generate_preview()