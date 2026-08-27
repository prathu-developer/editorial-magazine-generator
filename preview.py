import os
import re
import json
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader

def clean_and_highlight_passage(passage_text, vocab_items):
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
def match_vocab_to_paragraphs(paragraphs, vocab_items):
    """Returns vocab items that appear in the given paragraphs."""
    combined_text = " ".join(paragraphs)
    matched_vocab = []
    unmatched_vocab = []
    
    for item in vocab_items:
        term = item.get("word_or_phrase", "").strip()
        if not term:
            continue
        if re.search(rf'\b{re.escape(term)}\b', combined_text, re.IGNORECASE):
            matched_vocab.append(item)
        else:
            unmatched_vocab.append(item)
            
    return matched_vocab, unmatched_vocab

def partition_article(art_raw, categorized_vocab, all_vocab, start_page):
    """Partitions an editorial and its vocab lab dynamically across pages."""
    raw_paras = clean_and_highlight_passage(art_raw.get("passage", ""), all_vocab)
    total_words = sum(len(p.split()) for p in raw_paras)
    total_vocab = len(all_vocab)
    title_len = len(art_raw.get("title", ""))
    
    # Page 1 Budget: Masthead + Subtitle leaves room for ~220 words & max 14 vocab items
    p1_max_words = 190 if title_len > 60 else 230
    p1_max_vocab = 14
    
    needs_split = (total_words > p1_max_words) or (total_vocab > p1_max_vocab)
    
    reader_pages = []
    if not needs_split or len(raw_paras) <= 1:
        # Single Reader Page
        reader_pages.append({
            "is_continuation": False,
            "paragraphs": raw_paras,
            "vocab": all_vocab,
            "page_num": start_page,
            "has_next_reader_page": False
        })
    else:
        # Multi-page distribution
        pages_paras = []
        curr_page_paras = []
        curr_words = 0
        limit = p1_max_words

        for para in raw_paras:
            w_count = len(para.split())
            if curr_page_paras and (curr_words + w_count > limit):
                pages_paras.append(curr_page_paras)
                curr_page_paras = [para]
                curr_words = w_count
                limit = 350  # Continuation pages have no masthead, accommodating more words
            else:
                curr_page_paras.append(para)
                curr_words += w_count

        if curr_page_paras:
            pages_paras.append(curr_page_paras)

        if len(pages_paras) == 1 and len(raw_paras) >= 2:
            mid = len(raw_paras) // 2
            pages_paras = [raw_paras[:mid], raw_paras[mid:]]

        # Allocate matching vocabulary to each page
        assigned_vocab_ids = set()
        for idx, paras in enumerate(pages_paras):
            is_first = (idx == 0)
            is_last = (idx == len(pages_paras) - 1)
            
            page_vocab, _ = match_vocab_to_paragraphs(paras, all_vocab)
            # Retain only unassigned terms
            page_vocab = [v for v in page_vocab if id(v) not in assigned_vocab_ids]
            for v in page_vocab:
                assigned_vocab_ids.add(id(v))

            # Push any leftovers to the last reader page
            if is_last:
                leftovers = [v for v in all_vocab if id(v) not in assigned_vocab_ids]
                page_vocab.extend(leftovers)

            current_page_num = start_page + idx
            reader_pages.append({
                "is_continuation": not is_first,
                "paragraphs": paras,
                "vocab": page_vocab,
                "page_num": current_page_num,
                "has_next_reader_page": not is_last,
                "next_page_num": current_page_num + 1 if not is_last else None
            })

    # Vocab Lab Split Logic (Over 10 total ribbons spans 2 Lab pages)
    total_ribbons = sum(len(items) for items in categorized_vocab.values())
    lab_start_page = start_page + len(reader_pages)
    lab_pages = []
    
    if total_ribbons <= 10:
        lab_pages.append({
            "is_continuation": False,
            "page_num": lab_start_page,
            "show_analysis": True,
            "categorized_vocab": categorized_vocab,
            "has_next_lab_page": False
        })
    else:
        # Lab Page 1: Analysis + Core Vocab Ribbons
        lab_pages.append({
            "is_continuation": False,
            "page_num": lab_start_page,
            "show_analysis": True,
            "categorized_vocab": {"core_vocab": categorized_vocab.get("core_vocab", [])},
            "has_next_lab_page": True
        })
        # Lab Page 2: Remaining categories
        other_cats = {k: v for k, v in categorized_vocab.items() if k != "core_vocab" and v}
        lab_pages.append({
            "is_continuation": True,
            "page_num": lab_start_page + 1,
            "show_analysis": False,
            "categorized_vocab": other_cats,
            "has_next_lab_page": False
        })
        
    return reader_pages, lab_pages

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

    for idx, art in enumerate(raw_data.get("editorials", []), start=1):
        v_list = art.get("editorial_vocabulary", [])
        cats = categorize_vocabulary(v_list)
        paragraphs = clean_and_highlight_passage(art.get("passage", ""), v_list)
        title_clean = art.get("title", "")
        
        reader_page_num = page_counter
        lab_page_num = page_counter + 1

        toc.append({
            "title": title_clean,
            "newspaper": art.get("newspaper", "Editorial"),
            "topic": art.get("editorial_metadata", {}).get("topic", "General Studies"),
            "reading_time": art.get("reading_time", "2 min read"),
            "page_num": f"Page {reader_page_num:02d}",
            "target_id": f"reader-{idx}"
        })

        meta_sub = art.get("editorial_metadata", {}).get("subtitle", "")
        tone_data = art.get("analysis", {})

        processed.append({
            "id": idx,
            "newspaper": art.get("newspaper", "Editorial"),
            "title": title_clean,
            "subtitle": meta_sub if meta_sub and meta_sub != "N/A" else None,
            "topic": art.get("editorial_metadata", {}).get("topic", "General Studies"),
            "reading_time": art.get("reading_time", "2 min read"),
            "analysis": {
                "tone": tone_data.get("tone", "Analytical"),
                "tone_simple_explanation": tone_data.get("tone_simple_explanation", "").strip("()"),
                "analysis_summary": tone_data.get("analysis_summary", "")
            },
            "paragraphs": paragraphs,
            "vocab": v_list,
            "categorized_vocab": cats,
            "reader_page_num": reader_page_num,
            "lab_page_num": lab_page_num
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