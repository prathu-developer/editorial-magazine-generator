import os
import json
import glob
import requests
import pypdf
from pypdf import PdfReader, PdfWriter
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

def get_pos_rank(pos_raw):
    """Returns sort rank: Verb (1) -> Noun (2) -> Adjective (3) -> Adverb (4) -> Others (5)."""
    pos = str(pos_raw).strip().lower()
    if "adverb" in pos or "adv" in pos:
        return 4
    if "verb" in pos:
        return 1
    if "noun" in pos:
        return 2
    if "adj" in pos:
        return 3
    return 5

def categorize_vocabulary(vocab_items):
    """
    Deduplicates items per category (preserving first chronological occurrence)
    and sorts each category: Letter -> POS Priority -> Alphabetical.
    """
    categorized = {
        "core_vocab": [],
        "one_word_subs": [],
        "fixed_prepositions": [],
        "phrasal_verbs": [],
        "idioms": [],
        "foreign_words": []
    }
    seen_words = {cat: set() for cat in categorized}

    for item in vocab_items:
        cat = str(item.get("category", "")).strip().lower()
        if "one-word" in cat or "one word" in cat:
            target = "one_word_subs"
        elif "preposition" in cat:
            target = "fixed_prepositions"
        elif "phrasal" in cat:
            target = "phrasal_verbs"
        elif "idiom" in cat:
            target = "idioms"
        elif "foreign" in cat:
            target = "foreign_words"
        else:
            target = "core_vocab"

        word_key = str(item.get("word_or_phrase", "")).strip().lower()
        if word_key and word_key not in seen_words[target]:
            seen_words[target].add(word_key)
            categorized[target].append(item)

    # Sort each category: Letter -> POS -> Word
    for cat in categorized:
        categorized[cat].sort(key=lambda x: (
            str(x.get("word_or_phrase", "")).strip()[:1].upper(),
            get_pos_rank(x.get("part_of_speech", "")),
            str(x.get("word_or_phrase", "")).strip().lower()
        ))

    return categorized

def send_to_telegram(pdf_path, date_range_formatted, total_articles, total_words, newspapers_covered, universal_vocab):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("⚠️ Telegram BOT_TOKEN or ADMIN_CHAT_ID missing. Skipping Telegram upload.")
        return

    # Category counts breakdown
    core_count = len(universal_vocab.get("core_vocab", []))
    ows_count = len(universal_vocab.get("one_word_subs", []))
    prep_count = len(universal_vocab.get("fixed_prepositions", []))
    phr_count = len(universal_vocab.get("phrasal_verbs", []))
    idm_count = len(universal_vocab.get("idioms", []))
    foreign_count = len(universal_vocab.get("foreign_words", []))

    caption = (
        f"📚 <b>Ez Editorialś Weekly Vocab Lab</b>\n"
        f"🗓 <b>Edition:</b> {date_range_formatted}\n"
        f"🗞 <b>Newspapers Covered:</b> {newspapers_covered}\n\n"
        f"📊 <b>Compilation Overview:</b>\n"
        f"• <b>Total Editorials:</b> {total_articles} Articles\n"
        f"• <b>Total High-Yield Lexicons:</b> {total_words} Words\n\n"
        f"🗂 <b>What's Inside:</b>\n"
        f"📖 <b>Editorial Vocab:</b> {core_count} words (with Hindi & Connotations)\n"
        f"📝 <b>One-Word Substitutions:</b> {ows_count} terms\n"
        f"🔗 <b>Fixed Prepositions:</b> {prep_count} rules\n"
        f"⚡ <b>Phrasal Verbs:</b> {phr_count} phrases\n"
        f"💡 <b>Idioms & Expressions:</b> {idm_count} idioms\n"
    )

    if foreign_count > 0:
        caption += f"🌐 <b>Foreign Words & Phrases:</b> {foreign_count} terms\n"

    caption += (
        f"\n🎯 <i>Curated for SSC CGL, Banking, UPSC & State PCS aspirants. "
        f"Includes British synonyms/antonyms & complete editorial index on Page 03.</i>"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    filename = os.path.basename(pdf_path)

    print(f"📤 Uploading {filename} to Telegram...")
    with open(pdf_path, "rb") as doc:
        files = {"document": (filename, doc, "application/pdf")}
        payload = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML"
        }
        res = requests.post(url, data=payload, files=files)
        
    if res.status_code == 200:
        print("🚀 Successfully sent Weekly Compilation to Telegram!")
    else:
        print(f"❌ Telegram API Error ({res.status_code}): {res.text}")

def compile_weekly_magazine():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backups_dir = os.path.join(base_dir, "backups")
    templates_dir = os.path.join(base_dir, "templates")
    build_dir = os.path.join(base_dir, "build")
    output_dir = os.path.join(base_dir, "output")

    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # Determine the week window with support for manual overrides and Sunday runs
    ist = timezone(timedelta(hours=5, minutes=30))
    target_env = os.getenv("TARGET_DATE")
    
    if target_env:
        ref_date = datetime.strptime(target_env.strip(), "%Y-%m-%d").date()
    else:
        ref_date = datetime.now(ist).date()
        # If triggered on Sunday, pull the Monday-Saturday week that just ended
        if ref_date.weekday() == 6:
            ref_date -= timedelta(days=1)

    current_monday = ref_date - timedelta(days=ref_date.weekday())
    current_saturday = current_monday + timedelta(days=5)

    all_files = sorted(glob.glob(os.path.join(backups_dir, "*.json")))
    json_files = []

    for file_path in all_files:
        filename = os.path.basename(file_path)
        try:
            # Extracts 'YYYY-MM-DD' from 'YYYY-MM-DD_Weekday.json'
            date_part = filename.split("_")[0]
            file_date = datetime.strptime(date_part, "%Y-%m-%d").date()

            # Include only files belonging to the ongoing week
            if current_monday <= file_date <= current_saturday:
                json_files.append(file_path)
        except (ValueError, IndexError):
            continue

    if not json_files:
        print(f"⚠️ No JSON files found for the current week ({current_monday} to {current_saturday}) in: {backups_dir}")
        return

    print(f"📂 Loaded {len(json_files)} files for week {current_monday} to {current_saturday}:")
    for f in json_files:
        print(f"   • {os.path.basename(f)}")

    aggregated_editorials = []
    all_raw_dates = []

    for file_path in json_files:
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                daily_data = json.load(f)
                aggregated_editorials.extend(daily_data.get("editorials", []))
                
                # Extract date from json metadata or filename
                scraped_date = daily_data.get("date_scraped")
                if scraped_date:
                    all_raw_dates.append(scraped_date)
            except json.JSONDecodeError:
                print(f"⚠️ Skipping corrupted JSON: {file_path}")

    # Calculate date range from Monday to Saturday
    all_raw_dates = sorted(list(set(all_raw_dates)))
    if all_raw_dates:
        start_dt = datetime.strptime(all_raw_dates[0], "%Y-%m-%d")
        end_dt = datetime.strptime(all_raw_dates[-1], "%Y-%m-%d")
        date_range_formatted = f"{start_dt.strftime('%d %b')} – {end_dt.strftime('%d %b %Y')}"
    else:
        now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        date_range_formatted = now.strftime("%d %b %Y")

    # Collect unique newspapers and build TOC index entries
    newspapers = set()
    index_entries = []
    editorial_titles = []
    all_vocab_items = []

    for art in aggregated_editorials:
        title = art.get("title", "Untitled Editorial")
        np = art.get("newspaper", "Editorial")
        editorial_titles.append(title)
        newspapers.add(np)

        # Ingest vocabulary from ALL editorials across the entire week
        all_vocab_items.extend(art.get("editorial_vocabulary", []))

        index_entries.append({
            "title": title,
            "newspaper": np,
            "timestamp": art.get("timestamp", "")
        })

    # Limit only Page 3's Index cards to 25 so Page 3 never overflows
    index_entries = index_entries[:25]

    # Universal Categorization across all 25 articles
    universal_vocab = categorize_vocabulary(all_vocab_items)
    newspapers_covered = " & ".join(sorted(newspapers)) if newspapers else "National Dailies"

    total_unique_words = sum(len(items) for items in universal_vocab.values())

    # Prepare Template Engine
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("weekly_template.html")

    rendered_html_path = os.path.join(build_dir, "weekly_magazine.html")
    pass1_pdf_path = os.path.join(build_dir, "temp_pass1.pdf")
    base_pdf_path = os.path.join(build_dir, "temp_base.pdf")
    overlay_pdf_path = os.path.join(build_dir, "temp_overlay.pdf")

    ist_time = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    pdf_filename = f"Weekly_Compilation_{ist_time.strftime('%Y-%m-%d')}.pdf"
    output_pdf_path = os.path.join(output_dir, pdf_filename)

    # Initial fallback TOC page numbers (inner pages start at 4)
    toc_pages = {k: 4 for k in universal_vocab.keys()}

    # CRITICAL: Removed '--single-process' which causes Chromium to crash on Linux runners
    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu"
        ])
        page = browser.new_page()

        # -------------------------------------------------------------
        # PASS 1: Render draft HTML & detect start page for each section
        # -------------------------------------------------------------
        with open(rendered_html_path, "w", encoding="utf-8") as f:
            f.write(template.render(
                date_range_formatted=date_range_formatted,
                total_articles=len(aggregated_editorials),
                total_words=total_unique_words,
                newspapers_covered=newspapers_covered,
                index_entries=index_entries,
                universal_vocab=universal_vocab,
                toc_pages=toc_pages
            ))

        page.goto(f"file://{rendered_html_path}", wait_until="networkidle")
        page.evaluate("() => document.fonts.ready")
        page.pdf(
            path=pass1_pdf_path,
            format="A4",
            print_background=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )

        # Scan PDF for Category Headers (Search ONLY page 4 onwards to avoid Page 2 TOC false matches)
        reader1 = PdfReader(pass1_pdf_path)
        category_markers = [
            ("core_vocab", "__SEC_CORE__"),
            ("one_word_subs", "__SEC_OWS__"),
            ("fixed_prepositions", "__SEC_PREP__"),
            ("phrasal_verbs", "__SEC_PHR__"),
            ("idioms", "__SEC_IDM__"),
            ("foreign_words", "__SEC_FOR__")
        ]

        detected_pages = {}
        for page_idx, p_obj in enumerate(reader1.pages, start=1):
            if page_idx < 4:
                continue
            text = (p_obj.extract_text() or "").upper()
            for cat_key, marker in category_markers:
                if cat_key not in detected_pages and marker in text:
                    detected_pages[cat_key] = page_idx

        toc_pages.update(detected_pages)

        # -------------------------------------------------------------
        # PASS 2: Render final HTML with exact TOC numbers
        # -------------------------------------------------------------
        with open(rendered_html_path, "w", encoding="utf-8") as f:
            f.write(template.render(
                date_range_formatted=date_range_formatted,
                total_articles=len(aggregated_editorials),
                total_words=total_unique_words,
                newspapers_covered=newspapers_covered,
                index_entries=index_entries,
                universal_vocab=universal_vocab,
                toc_pages=toc_pages
            ))

        page.goto(f"file://{rendered_html_path}", wait_until="networkidle")
        page.evaluate("() => document.fonts.ready")
        page.pdf(
            path=base_pdf_path,
            format="A4",
            print_background=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )

        # -------------------------------------------------------------
        # PASS 3: Generate Dynamic Footer Page Numbers for inner pages
        # -------------------------------------------------------------
        final_reader = PdfReader(base_pdf_path)
        total_pages = len(final_reader.pages)

        overlay_pages_html = []
        for i in range(1, total_pages + 1):
            if 4 <= i < total_pages:
                overlay_pages_html.append(f'<div class="overlay-page"><div class="footer-page-badge">Page {i:02d}</div></div>')
            else:
                overlay_pages_html.append('<div class="overlay-page"></div>')

        # Drop the external @import; use system sans-serif stack to prevent font bloat
        overlay_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <style>
          @page {{ size: 210mm 297mm; margin: 0; }}
          * {{ box-sizing: border-box; margin: 0; padding: 0; -webkit-print-color-adjust: exact !important; }}
          body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Montserrat", sans-serif; }}
          .overlay-page {{ width: 210mm; height: 297mm; position: relative; }}
          .overlay-page:not(:last-child) {{ page-break-after: always; break-after: page; }}
          .footer-page-badge {{
            position: absolute;
            bottom: 1.8mm;
            right: 12mm;
            font-size: 8px;
            font-weight: 800;
            color: #ffffff;
            background: #0f2b48;
            padding: 2px 8px;
            border-radius: 4px;
            letter-spacing: 0.3px;
          }}
        </style>
        </head>
        <body>
          {''.join(overlay_pages_html)}
        </body>
        </html>
        """

        page.set_content(overlay_html, wait_until="load")
        page.pdf(
            path=overlay_pdf_path,
            format="A4",
            print_background=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )
        browser.close()

    # -------------------------------------------------------------
    # MERGE: Stamp overlay badges & Lossless Compression
    # -------------------------------------------------------------
    overlay_reader = PdfReader(overlay_pdf_path)
    writer = PdfWriter()

    for idx, pdf_page in enumerate(final_reader.pages):
        if 3 <= idx < len(final_reader.pages) - 1:
            if idx < len(overlay_reader.pages):
                pdf_page.merge_page(overlay_reader.pages[idx])
        writer.add_page(pdf_page)

    # 1. Deduplicate identical fonts, graphics states, and forms across all merged pages
    writer.compress_identical_objects()

    # 2. Apply lossless zlib Flate compression to all content streams
    for page in writer.pages:
        page.compress_content_streams()

    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    # Cleanup temporary PDFs
    for tmp in [pass1_pdf_path, base_pdf_path, overlay_pdf_path]:
        if os.path.exists(tmp):
            os.remove(tmp)

    print(f"✅ Generated Weekly Magazine with TOC & Page Numbers: {output_pdf_path}")
    send_to_telegram(
        pdf_path=output_pdf_path,
        date_range_formatted=date_range_formatted,
        total_articles=len(aggregated_editorials),
        total_words=total_unique_words,
        newspapers_covered=newspapers_covered,
        universal_vocab=universal_vocab
    )

if __name__ == "__main__":
    compile_weekly_magazine()
