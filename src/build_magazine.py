import os
import re
import json
import requests
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

def clean_and_highlight_passage(passage_text, vocab_items):
    raw_paras = [p.strip() for p in re.split(r'[\r\n]+', passage_text) if p.strip()]
    cleaned_paras = []
    
    sorted_vocab = sorted(
        vocab_items,
        key=lambda x: len(x.get("word_or_phrase", "")),
        reverse=True
    )

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

        highlighted = p
        for item in sorted_vocab:
            term = item.get("word_or_phrase", "").strip()
            idx = item.get("order_index", "")
            if not term:
                continue
            
            pattern = re.compile(rf'\b({re.escape(term)})\b', re.IGNORECASE)
            highlighted = pattern.sub(
                rf'<span class="vocab-hl">\1<sup class="v-idx">{idx}</sup></span>',
                highlighted
            )
            
        cleaned_paras.append(highlighted)
        
    return cleaned_paras

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

def send_to_telegram(pdf_path, ist_date_short, editorial_titles):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("⚠️ Telegram BOT_TOKEN or ADMIN_CHAT_ID missing. Skipping Telegram delivery.")
        return

    # Build formatted lines for the quote box
    quote_lines = [f"{idx:02d} {title}" for idx, title in enumerate(editorial_titles, start=1)]
    quote_content = "\n".join(quote_lines)

    # Telegram HTML caption with expandable blockquote
    caption = (
        f"📝 <b>Today's Editorials ({ist_date_short})</b>\n"
        f"<blockquote expandable>{quote_content}</blockquote>"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    filename = os.path.basename(pdf_path)

    print(f"📤 Uploading {filename} to Telegram...")
    with open(pdf_path, "rb") as doc:
        files = {
            "document": (filename, doc, "application/pdf")
        }
        payload = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML"
        }
        res = requests.post(url, data=payload, files=files)
        
    if res.status_code == 200:
        print("🚀 Successfully delivered magazine PDF to Telegram!")
    else:
        print(f"❌ Telegram API Error ({res.status_code}): {res.text}")

def match_vocab_to_paragraphs(paragraphs, vocab_items):
    """Returns vocab items that appear in the given paragraphs."""
    combined_text = " ".join(paragraphs)
    matched_vocab = []
    unmatched_vocab = []
    
    for item in vocab_items:
        term = item.get("word_or_phrase", "").strip()
        if not term:
            continue
        # Check presence using word boundary
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
    
    # Continuous Budget: Set to extreme numbers to prevent page splitting
    p1_max_words = 999999
    p1_max_vocab = 999999
    
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

def compile_magazine():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "schema.json")
    templates_dir = os.path.join(base_dir, "templates")
    build_dir = os.path.join(base_dir, "build")
    output_dir = os.path.join(base_dir, "output")

    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Data schema not found at: {json_path}")
    
    with open(json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # Real-time Indian Standard Time (IST)
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    ist_time = datetime.now(ist_offset)
    
    pdf_filename = f"{ist_time.strftime('%d-%b-%Y')}.pdf"
    output_pdf_path = os.path.join(output_dir, pdf_filename)
    
    formatted_date_ist = ist_time.strftime(f"%B {ist_time.day}, %Y")
    ist_date_short = ist_time.strftime(f"{ist_time.day} %b %Y")

    processed_articles = []
    toc_entries = []
    editorial_titles = []
    page_counter = 3

    for art in raw_data.get("editorials", []):
        vocab_list = art.get("editorial_vocabulary", [])
        categorized_vocab = categorize_vocabulary(vocab_list)
        
        tone_data = art.get("analysis", {})
        clean_expl = tone_data.get("tone_simple_explanation", "").strip("()")
        
        meta_sub = art.get("editorial_metadata", {}).get("subtitle", "")
        subtitle = meta_sub if meta_sub and meta_sub != "N/A" else None
        title_clean = art.get("title", "")
        editorial_titles.append(title_clean)

        reader_pages, lab_pages = partition_article(art, categorized_vocab, vocab_list, page_counter)
        
        target_reader_id = f"article-p{page_counter}"
        target_vocab_id = f"vocab-p{lab_pages[0]['page_num']}"

        toc_entries.append({
            "title": title_clean,
            "newspaper": art.get("newspaper", "Editorial"),
            "topic": art.get("editorial_metadata", {}).get("topic", "General Studies"),
            "reading_time": art.get("reading_time", "2 min read"),
            "page_num": f"Page {page_counter:02d}",
            "target_id": target_reader_id
        })

        total_art_pages = len(reader_pages) + len(lab_pages)

        processed_articles.append({
            "newspaper": art.get("newspaper", "Editorial"),
            "title": title_clean,
            "subtitle": subtitle,
            "topic": art.get("editorial_metadata", {}).get("topic", "General Studies"),
            "reading_time": art.get("reading_time", "2 min read"),
            "timestamp": art.get("timestamp", formatted_date_ist),
            "analysis": {
                "tone": tone_data.get("tone", "Analytical"),
                "tone_simple_explanation": clean_expl,
                "analysis_summary": tone_data.get("analysis_summary", "")
            },
            "reader_pages": reader_pages,
            "lab_pages": lab_pages,
            "target_reader_id": target_reader_id,
            "target_vocab_id": target_vocab_id,
            "last_lab_page": lab_pages[-1]["page_num"]
        })
        
        page_counter += total_art_pages

    # Check assets
    assets_dir = os.path.join(base_dir, "assets")
    front_cover_path = os.path.join(assets_dir, "front_cover_bg.jpg")
    toc_bg_path = os.path.join(assets_dir, "toc_bg.jpg")
    back_cover_path = os.path.join(assets_dir, "back_cover_bg.jpg")
    
    watermark_png = os.path.join(assets_dir, "watermark.png")
    watermark_svg = os.path.join(assets_dir, "watermark.svg")
    watermark_src = None
    if os.path.exists(watermark_png):
        watermark_src = f"file://{watermark_png}"
    elif os.path.exists(watermark_svg):
        watermark_src = f"file://{watermark_svg}"

    render_payload = {
        "date_formatted": formatted_date_ist,
        "date_scraped": raw_data.get("date_scraped", formatted_date_ist),
        "has_front_cover": os.path.exists(front_cover_path),
        "front_cover_src": f"file://{front_cover_path}",
        "has_toc_bg": os.path.exists(toc_bg_path),
        "toc_bg_src": f"file://{toc_bg_path}",
        "has_back_cover": os.path.exists(back_cover_path),
        "back_cover_src": f"file://{back_cover_path}",
        "has_watermark": watermark_src is not None,
        "watermark_src": watermark_src,
        "toc_entries": toc_entries,
        "total_articles": len(processed_articles),
        "articles": processed_articles
    }

    env = Environment(loader=FileSystemLoader([templates_dir, base_dir]))
    template = env.get_template("template.html")
    rendered_html = template.render(data=render_payload)

    rendered_html_path = os.path.join(build_dir, "rendered_content.html")
    with open(rendered_html_path, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    # PDF generation
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = browser.new_page()
        page.goto(f"file://{rendered_html_path}", wait_until="networkidle")
        page.evaluate("() => document.fonts.ready")
        
        # Calculate the total height of the continuous document
        body_height = page.evaluate("document.documentElement.scrollHeight")
        
        page.pdf(
            path=output_pdf_path,
            width="210mm",             # Keep width so ribbons and cover images scale perfectly
            height=f"{body_height}px", # Stretch height continuously 
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"}
        )
        browser.close()

    print(f"✅ Generated Complete Magazine: {output_pdf_path}")

    # Dispatch to Telegram DM
    send_to_telegram(output_pdf_path, ist_date_short, editorial_titles)

if __name__ == "__main__":
    compile_magazine()