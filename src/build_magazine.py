import os
import re
import json
import requests
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
from pypdf import PdfWriter

def clean_and_highlight(passage_text, vocab_items):
    raw_paras = [p.strip() for p in re.split(r'[\r\n]+', passage_text) if p.strip()]
    cleaned_paras = []
    
    sorted_vocab = sorted(
        vocab_items,
        key=lambda x: len(x.get("word_or_phrase", "")),
        reverse=True
    )

    for p in raw_paras:
        if re.match(r'^(Published|Updated|- ?[A-Za-z]+|\d{1,2}\s+[A-Za-z]+)', p, re.IGNORECASE):
            continue
        if p.count('/') >= 2 or len(re.findall(r'\s*/\s*', p)) >= 2:
            continue
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
    all_matched = {id(item) for cat_list in categorized.values() for item in cat_list}
    for item in vocab_items:
        if id(item) not in all_matched:
            categorized["core_vocab"].append(item)
    return categorized

def send_to_telegram(pdf_path, ist_date_short, editorial_titles):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("⚠️ Telegram credentials missing. Skipping delivery.")
        return

    quote_lines = [f"{idx:02d} {title}" for idx, title in enumerate(editorial_titles, start=1)]
    quote_content = "\n".join(quote_lines)
    caption = f"📝 <b>Today's Editorials ({ist_date_short})</b>\n<blockquote expandable>{quote_content}</blockquote>"

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    filename = os.path.basename(pdf_path)
    print(f"📤 Uploading {filename} to Telegram...")
    with open(pdf_path, "rb") as doc:
        requests.post(url, data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}, files={"document": (filename, doc, "application/pdf")})

def compile_magazine():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "schema.json")
    templates_dir = os.path.join(base_dir, "templates")
    build_dir = os.path.join(base_dir, "build")
    output_dir = os.path.join(base_dir, "output")

    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    with open(json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

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

    for idx, art in enumerate(raw_data.get("editorials", []), start=1):
        vocab_list = art.get("editorial_vocabulary", [])
        categorized_vocab = categorize_vocabulary(vocab_list)
        paragraphs = clean_and_highlight(art.get("passage", ""), vocab_list)
        title_clean = art.get("title", "")
        editorial_titles.append(title_clean)
        
        reader_page_num = page_counter
        lab_page_num = page_counter + 1

        toc_entries.append({
            "title": title_clean,
            "newspaper": art.get("newspaper", "Editorial"),
            "topic": art.get("editorial_metadata", {}).get("topic", "General Studies"),
            "reading_time": art.get("reading_time", "2 min read"),
            "page_num": f"Page {reader_page_num:02d}",
            "target_id": f"article-{idx}"
        })

        meta_sub = art.get("editorial_metadata", {}).get("subtitle", "")
        tone_data = art.get("analysis", {})
        
        processed_articles.append({
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
            "vocab": vocab_list,
            "categorized_vocab": categorized_vocab,
            "reader_page_num": reader_page_num,
            "lab_page_num": lab_page_num,
            "target_reader_id": f"article-{idx}",
            "target_vocab_id": f"vocab-{idx}"
        })
        page_counter += 2

    # Asset paths
    assets_dir = os.path.join(base_dir, "assets")
    front_cover_path = os.path.join(assets_dir, "front_cover_bg.jpg")
    toc_bg_path = os.path.join(assets_dir, "toc_bg.jpg")
    back_cover_path = os.path.join(assets_dir, "back_cover_bg.jpg")
    watermark_png = os.path.join(assets_dir, "watermark.png")

    render_payload = {
        "date_formatted": formatted_date_ist,
        "date_scraped": raw_data.get("date_scraped", formatted_date_ist),
        "has_front_cover": os.path.exists(front_cover_path),
        "front_cover_src": f"file://{front_cover_path}",
        "has_toc_bg": os.path.exists(toc_bg_path),
        "toc_bg_src": f"file://{toc_bg_path}",
        "has_back_cover": os.path.exists(back_cover_path),
        "back_cover_src": f"file://{back_cover_path}",
        "has_watermark": os.path.exists(watermark_png),
        "watermark_src": f"file://{watermark_png}",
        "toc_entries": toc_entries,
        "articles": processed_articles,
        "back_cover_page_num": page_counter
    }

    env = Environment(loader=FileSystemLoader([templates_dir, base_dir]))
    template = env.get_template("template.html")
    rendered_html = template.render(data=render_payload)

    rendered_html_path = os.path.join(build_dir, "rendered_content.html")
    with open(rendered_html_path, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    # Compile Continuous PDF
    print("🎨 Rendering Dynamic Continuous PDF...")
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = browser.new_page()
        page.goto(f"file://{rendered_html_path}", wait_until="networkidle")
        page.evaluate("() => document.fonts.ready")

        page.pdf(
            path=output_pdf_path,
            print_background=True,
            prefer_css_page_size=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )
        browser.close()

    print(f"✅ Generated Complete Magazine: {output_pdf_path}")
    send_to_telegram(output_pdf_path, ist_date_short, editorial_titles)

if __name__ == "__main__":
    compile_magazine()