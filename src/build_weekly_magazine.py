import os
import json
import glob
import requests
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

CATEGORY_METADATA = [
    {
        "key": "core_vocab",
        "title": "EDITORIAL VOCABULARY",
        "icon": "📖",
        "class_tag": "hdr-vocab",
        "num_bg": "#0b1e36"
    },
    {
        "key": "one_word_subs",
        "title": "ONE-WORD SUBSTITUTIONS",
        "icon": "📝",
        "class_tag": "hdr-ows",
        "num_bg": "#b45309"
    },
    {
        "key": "fixed_prepositions",
        "title": "FIXED PREPOSITIONS",
        "icon": "🔗",
        "class_tag": "hdr-prep",
        "num_bg": "#0f766e"
    },
    {
        "key": "phrasal_verbs",
        "title": "PHRASAL VERBS",
        "icon": "⚡",
        "class_tag": "hdr-phr",
        "num_bg": "#6d28d9"
    },
    {
        "key": "idioms",
        "title": "IDIOMS & PHRASES",
        "icon": "💡",
        "class_tag": "hdr-idm",
        "num_bg": "#e11d48"
    },
    {
        "key": "foreign_words",
        "title": "FOREIGN WORDS & PHRASES",
        "icon": "🌐",
        "class_tag": "hdr-foreign",
        "num_bg": "#2563eb"
    }
]

def categorize_vocabulary(vocab_items):
    categorized = {cat["key"]: [] for cat in CATEGORY_METADATA}

    for item in vocab_items:
        cat = str(item.get("category", "")).strip().lower()
        if "one-word" in cat or "one word" in cat:
            categorized["one_word_subs"].append(item)
        elif "preposition" in cat:
            categorized["fixed_prepositions"].append(item)
        elif "phrasal" in cat:
            categorized["phrasal_verbs"].append(item)
        elif "idiom" in cat:
            categorized["idioms"].append(item)
        elif "foreign" in cat:
            categorized["foreign_words"].append(item)
        else:
            categorized["core_vocab"].append(item)
            
    return categorized

def paginate_vocabulary(universal_vocab, start_page_num=4):
    """
    Chunks vocabulary items into distinct A4 pages so content never touches
    the top edge and every page receives its own footer and watermark.
    """
    pages = []
    current_page_sections = []
    current_page_capacity = 0
    MAX_PAGE_CAPACITY = 8.0  # Equivalent to 8 items (item = 1.0, header = 1.0)
    current_page_num = start_page_num

    for meta in CATEGORY_METADATA:
        items = universal_vocab.get(meta["key"], [])
        if not items:
            continue

        total_in_cat = len(items)
        item_idx = 0
        is_first_chunk = True

        while item_idx < total_in_cat:
            header_cost = 1.0
            space_left = MAX_PAGE_CAPACITY - current_page_capacity

            # If we can't fit at least the header and 2 items, start a fresh page
            if space_left < (header_cost + 2.0):
                if current_page_sections:
                    pages.append({
                        "page_num": current_page_num,
                        "sections": current_page_sections
                    })
                    current_page_num += 1
                    current_page_sections = []
                    current_page_capacity = 0
                space_left = MAX_PAGE_CAPACITY

            # Available slots on this page
            items_can_fit = int(space_left - header_cost)
            items_chunk = items[item_idx: item_idx + items_can_fit]

            current_page_sections.append({
                "category_title": meta["title"],
                "icon": meta["icon"],
                "class_tag": meta["class_tag"],
                "num_bg": meta["num_bg"],
                "show_header": True,
                "is_continuation": not is_first_chunk,
                "total_in_category": total_in_cat,
                "items": items_chunk
            })

            current_page_capacity += header_cost + len(items_chunk)
            item_idx += len(items_chunk)
            is_first_chunk = False

            if current_page_capacity >= (MAX_PAGE_CAPACITY - 0.5):
                pages.append({
                    "page_num": current_page_num,
                    "sections": current_page_sections
                })
                current_page_num += 1
                current_page_sections = []
                current_page_capacity = 0

    if current_page_sections:
        pages.append({
            "page_num": current_page_num,
            "sections": current_page_sections
        })

    return pages

def send_to_telegram(pdf_path, date_range_formatted, editorial_titles):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("⚠️ Telegram credentials not found. Skipping Telegram upload.")
        return

    quote_lines = [f"{idx:02d} {title}" for idx, title in enumerate(editorial_titles, start=1)]
    quote_content = "\n".join(quote_lines)

    caption = (
        f"📚 <b>Ez Editorialś Weekly Compilation ({date_range_formatted})</b>\n"
        f"<blockquote expandable>{quote_content}</blockquote>"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    filename = os.path.basename(pdf_path)

    print(f"📤 Uploading {filename} to Telegram...")
    with open(pdf_path, "rb") as doc:
        files = {"document": (filename, doc, "application/pdf")}
        payload = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        res = requests.post(url, data=payload, files=files)
        
    if res.status_code == 200:
        print("🚀 Successfully sent Weekly Compilation to Telegram!")
    else:
        print(f"❌ Telegram API Error ({res.status_code}): {res.text}")

def compile_weekly_magazine():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backups_dir = os.path.join(base_dir, "backups")
    assets_dir = os.path.join(base_dir, "assets")
    templates_dir = os.path.join(base_dir, "templates")
    build_dir = os.path.join(base_dir, "build")
    output_dir = os.path.join(base_dir, "output")

    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # 1. Check for watermark in assets
    watermark_path = os.path.join(assets_dir, "watermark.png")
    has_watermark = os.path.exists(watermark_path)
    watermark_src = f"file://{watermark_path}" if has_watermark else None

    # 2. Collect JSON backup files
    json_files = sorted(glob.glob(os.path.join(backups_dir, "*.json")))
    if not json_files:
        print(f"⚠️ No backup JSON files found in: {backups_dir}")
        return

    aggregated_editorials = []
    all_raw_dates = []

    for file_path in json_files:
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                daily_data = json.load(f)
                aggregated_editorials.extend(daily_data.get("editorials", []))
                scraped_date = daily_data.get("date_scraped")
                if scraped_date:
                    all_raw_dates.append(scraped_date)
            except json.JSONDecodeError:
                print(f"⚠️ Skipping corrupted JSON: {file_path}")

    # Maximum 25 editorials
    aggregated_editorials = aggregated_editorials[:25]

    # Calculate date range
    all_raw_dates = sorted(list(set(all_raw_dates)))
    if all_raw_dates:
        start_dt = datetime.strptime(all_raw_dates[0], "%Y-%m-%d")
        end_dt = datetime.strptime(all_raw_dates[-1], "%Y-%m-%d")
        date_range_formatted = f"{start_dt.strftime('%d %b')} – {end_dt.strftime('%d %b %Y')}"
    else:
        now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        date_range_formatted = now.strftime("%d %b %Y")

    newspapers = set()
    index_entries = []
    editorial_titles = []
    all_vocab_items = []

    for art in aggregated_editorials:
        title = art.get("title", "Untitled Editorial")
        np = art.get("newspaper", "Editorial")
        editorial_titles.append(title)
        newspapers.add(np)

        index_entries.append({
            "title": title,
            "newspaper": np,
            "timestamp": art.get("timestamp", "")
        })

        all_vocab_items.extend(art.get("editorial_vocabulary", []))

    # Universal Categorization
    universal_vocab = categorize_vocabulary(all_vocab_items)
    
    # Assign global 1..N order index per category
    for cat_key in universal_vocab:
        for idx, item in enumerate(universal_vocab[cat_key], start=1):
            item["order_index"] = idx

    # Paginate vocabulary starting from Page 4
    vocab_pages = paginate_vocabulary(universal_vocab, start_page_num=4)
    newspapers_covered = " & ".join(sorted(newspapers)) if newspapers else "National Dailies"

    render_payload = {
        "has_watermark": has_watermark,
        "watermark_src": watermark_src,
        "date_range_formatted": date_range_formatted,
        "total_articles": len(aggregated_editorials),
        "total_words": len(all_vocab_items),
        "newspapers_covered": newspapers_covered,
        "index_entries": index_entries,
        "vocab_pages": vocab_pages
    }

    # Render Template
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("weekly_template.html")
    rendered_html = template.render(data=render_payload)

    rendered_html_path = os.path.join(build_dir, "weekly_magazine.html")
    with open(rendered_html_path, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    # Output PDF
    ist_time = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    pdf_filename = f"Weekly_Compilation_{ist_time.strftime('%Y-%m-%d')}.pdf"
    output_pdf_path = os.path.join(output_dir, pdf_filename)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = browser.new_page()
        page.goto(f"file://{rendered_html_path}", wait_until="networkidle")
        page.pdf(
            path=output_pdf_path,
            format="A4",
            print_background=True,
            prefer_css_page_size=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )
        browser.close()

    print(f"✅ Generated Weekly Magazine: {output_pdf_path}")
    send_to_telegram(output_pdf_path, date_range_formatted, editorial_titles)

if __name__ == "__main__":
    compile_weekly_magazine()
