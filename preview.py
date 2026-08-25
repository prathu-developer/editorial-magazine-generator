import os
import re
import json
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader

def clean_and_highlight(passage_text, vocab_items):
    raw_paras = [p.strip() for p in re.split(r'[\r\n]+', passage_text) if p.strip()]
    cleaned = []
    sorted_vocab = sorted(vocab_items, key=lambda x: len(x.get("word_or_phrase", "")), reverse=True)
    
    for p in raw_paras:
        # 1. Skip scraper timestamps & metadata
        if re.match(r'^(Published|Updated|- ?[A-Za-z]+|\d{1,2}\s+[A-Za-z]+)', p, re.IGNORECASE):
            continue
            
        # 2. Skip tag & taxonomy blocks containing multiple slashes
        if p.count('/') >= 2 or len(re.findall(r'\s*/\s*', p)) >= 2:
            continue
            
        # 3. Strip trailing inline tags attached directly to the last sentence
        p = re.sub(r'(\s*[\w\s]+(\s*/\s*[\w\s]+){2,}\s*)$', '', p)
        if not p.strip():
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

def categorize_vocabulary(vocab_items):
    def match_cat(item, target_cat):
        cat = str(item.get("category", "")).strip().lower()
        return cat == target_cat.lower()

    categorized = {
        "core_vocab": [v for v in vocab_items if match_cat(v, "Vocabulary")],
        "one_word_subs": [v for v in vocab_items if match_cat(v, "One-Word Substitutions")],
        "fixed_prepositions": [v for v in vocab_items if match_cat(v, "Fixed Prepositions")],
        "phrasal_verbs": [v for v in vocab_items if match_cat(v, "Phrasal Verbs")],
        "idioms": [v for v in vocab_items if match_cat(v, "Idioms & Phrases") or match_cat(v, "Idioms and Phrases")],
        "foreign_words": [v for v in vocab_items if match_cat(v, "Foreign Words")]
    }

    # Catch any untagged/mismatched item and route it safely to core_vocab
    all_matched = {id(item) for cat_list in categorized.values() for item in cat_list}
    for item in vocab_items:
        if id(item) not in all_matched:
            categorized["core_vocab"].append(item)

    return categorized

def generate_preview():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    
    # Handle project path resolution
    json_path = os.path.join(base_dir, "schema.json")
    if not os.path.exists(json_path):
        json_path = os.path.join(os.path.dirname(base_dir), "schema.json")
        
    templates_dir = os.path.join(base_dir, "templates")
    if not os.path.exists(templates_dir):
        templates_dir = os.path.join(os.path.dirname(base_dir), "templates")

    with open(json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # Calculate Indian Standard Time (IST)
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    ist_time = datetime.now(ist_offset)
    formatted_date_ist = ist_time.strftime(f"%B {ist_time.day}, %Y")

    processed = []
    toc = []
    page_counter = 3

    for art in raw_data.get("editorials", []):
        v_list = art.get("editorial_vocabulary", [])
        cats = categorize_vocabulary(v_list)

        target_reader_id = f"article-p{page_counter}"
        target_vocab_id = f"article-p{page_counter + 1}"

        toc.append({
            "title": art.get("title", ""),
            "newspaper": art.get("newspaper", "Editorial"),
            "topic": art.get("editorial_metadata", {}).get("topic", "General Studies"),
            "page_num": f"Page {page_counter:02d}",
            "target_id": target_reader_id
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
            "page_p2": page_counter + 1,
            "target_reader_id": target_reader_id,
            "target_vocab_id": target_vocab_id
        })
        page_counter += 2

    # Check asset paths
    assets_dir = os.path.join(base_dir, "assets")
    if not os.path.exists(assets_dir):
        assets_dir = os.path.join(os.path.dirname(base_dir), "assets")

    payload = {
        "date_formatted": formatted_date_ist,
        "date_scraped": raw_data.get("date_scraped", formatted_date_ist),
        "has_front_cover": os.path.exists(os.path.join(assets_dir, "front_cover_bg.jpg")),
        "front_cover_src": "../assets/front_cover_bg.jpg",
        "has_toc_bg": os.path.exists(os.path.join(assets_dir, "toc_bg.jpg")),
        "toc_bg_src": "../assets/toc_bg.jpg",
        "has_back_cover": os.path.exists(os.path.join(assets_dir, "back_cover_bg.jpg")),
        "back_cover_src": "../assets/back_cover_bg.jpg",
        "has_watermark": os.path.exists(os.path.join(assets_dir, "watermark.png")),
        "watermark_src": "../assets/watermark.png",
        "toc_entries": toc,
        "total_articles": len(processed),
        "articles": processed
    }

    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("template.html")
    
    build_dir = os.path.join(base_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    out_file = os.path.join(build_dir, "rendered_content.html")
    
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(template.render(data=payload))
        
    print(f"✨ Clean preview generated successfully: {out_file}")

if __name__ == "__main__":
    generate_preview()