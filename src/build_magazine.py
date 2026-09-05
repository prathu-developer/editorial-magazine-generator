import os
import sys
import re
import json
import requests
import io
import time
from datetime import datetime, timezone, timedelta
from PIL import Image
from evidence_lens import extract_evidence_spans
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
from pypdf import PdfWriter, PdfReader
from pypdf.annotations import Link
from pypdf.generic import Fit

def optimize_asset_image(src_path: str, cache_dir: str, max_width: int = 1654, quality: int = 85) -> str:
    """Downsamples raster covers/watermarks to 200 DPI A4 and compresses JPEGs."""
    if not os.path.exists(src_path):
        return src_path

    filename = os.path.basename(src_path)
    opt_path = os.path.join(cache_dir, f"opt_{filename}")

    if os.path.exists(opt_path) and os.path.getmtime(opt_path) >= os.path.getmtime(src_path):
        return opt_path

    try:
        with Image.open(src_path) as img:
            if img.width > max_width:
                height = int((max_width / img.width) * img.height)
                img = img.resize((max_width, height), Image.Resampling.LANCZOS)

            if img.format == "PNG":
                img.save(opt_path, "PNG", optimize=True)
            else:
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(opt_path, "JPEG", quality=quality, optimize=True, progressive=True)
        return opt_path
    except Exception as err:
        print(f"⚠️ Could not optimize {src_path}: {err}. Retaining original.")
        return src_path

def sanitize_vocab_text(text: str) -> str:
    if not text:
        return ""
    fixes = {
        r'\breve\s+al\b': 'reveal',
        r'\bide\s+a\b': 'idea',
        r'\bsome\s+one\b': 'someone',
        r'\bint\s+o\b': 'into',
        r'\bwith\s+in\b': 'within'
    }
    for pattern, repl in fixes.items():
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text

def clean_and_highlight_passage(passage_text, vocab_items):
    # Clean broken LaTeX / math currency strings before processing paragraphs
    passage_text = passage_text.replace(r'$\overline{7}', '₹').replace(r'$\approx', '₹~')
    passage_text = re.sub(r'\$(\\overline\{7\}|\\approx)?', '₹', passage_text)
    
    raw_paras = [p.strip() for p in re.split(r'[\r\n]+', passage_text) if p.strip()]
    cleaned_paras = []
    
    # Sort vocab by length descending so multi-word phrases match before single words
    sorted_vocab = sorted(
        vocab_items,
        key=lambda x: len(x.get("word_or_phrase", "")),
        reverse=True
    )

    for p in raw_paras:
        # 1. Skip scraper timestamps & metadata
        if re.match(r'^(Published|Updated|- ?[A-Za-z]+|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b)', p, re.IGNORECASE):
            continue

        # 2. Skip dedicated tag/taxonomy lines
        is_tag_block = bool(re.match(r'^[\w\s\(\)-]+(\s+/\s+[\w\s\(\)-]+){2,}$', p.strip())) or p.count(' / ') >= 3
        if is_tag_block:
            continue

        # 3. Strip trailing category tags
        p = re.sub(r'(\s+/\s+[\w\s\(\)-]+){2,}$', '', p)
        if not p.strip():
            continue

        # --- FIX ISSUE 3: Reserve claimed characters to prevent duplicate matching ---
        vocab_spans = []
        claimed = [False] * len(p)
        for item in sorted_vocab:
            term = item.get("word_or_phrase", "").strip()
            idx = item.get("order_index", "")
            if not term:
                continue
            # Use lookaround boundaries to support hyphens and apostrophes reliably
            pattern = rf'(?<![A-Za-z0-9])({re.escape(term)})(?![A-Za-z0-9])'
            for match in re.finditer(pattern, p, re.IGNORECASE):
                start, end = match.start(), match.end()
                # Skip sub-words if a longer phrase already claimed this character segment
                if any(claimed[i] for i in range(start, end)):
                    continue
                for i in range(start, end):
                    claimed[i] = True
                vocab_spans.append({
                    "start": start,
                    "end": end,
                    "idx": idx
                })

        # --- FIX ISSUE 2: Clip boundary-crossing spans and build strictly nested HTML ---
        raw_evidence = extract_evidence_spans(p)
        clean_evidence = []
        for e in raw_evidence:
            e_start, e_end = e["start"], e["end"]
            for v in vocab_spans:
                v_start, v_end = v["start"], v["end"]
                # If spans cross boundaries partially, trim evidence to prevent illegal HTML overlap
                if e_start < v_start < e_end < v_end:
                    e_end = v_start
                elif v_start < e_start < v_end < e_end:
                    e_start = v_end
            if e_start < e_end:
                clean_evidence.append({"start": e_start, "end": e_end})

        # Assign strict nesting priorities:
        # 1: Vocab Close (inner), 2: Evidence Close (outer), 3: Evidence Open (outer), 4: Vocab Open (inner)
        tags_by_pos = {}
        for v in vocab_spans:
            tags_by_pos.setdefault(v["end"], []).append((1, f'<sup class="v-idx">{v["idx"]}</sup></span>'))
            tags_by_pos.setdefault(v["start"], []).append((4, '<span class="vocab-hl">'))

        for e in clean_evidence:
            tags_by_pos.setdefault(e["end"], []).append((2, '</span>'))
            tags_by_pos.setdefault(e["start"], []).append((3, '<span class="evidence-hl">'))

        # Construct annotated paragraph from left to right
        annotated_para = []
        last_idx = 0
        for pos in sorted(tags_by_pos.keys()):
            annotated_para.append(p[last_idx:pos])
            for _, tag_str in sorted(tags_by_pos[pos], key=lambda x: x[0]):
                annotated_para.append(tag_str)
            last_idx = pos
        annotated_para.append(p[last_idx:])

        cleaned_paras.append("".join(annotated_para))
        
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

def send_to_telegram(light_pdf_path, dark_pdf_path, ist_date_short, editorial_items, thumb_path=None):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    admin_chat_id = os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    
    # Group Thread Publishing Configuration
    enable_group_publish = os.getenv("ENABLE_GROUP_PUBLISH", "false").strip().lower() == "true"
    source_chat_id = os.getenv("TELEGRAM_GROUP_CHAT_ID")   
    source_thread_id = os.getenv("TELEGRAM_THREAD_ID")     
    target_chat_id = os.getenv("TARGET_CHAT_ID", "-1003875580290")  
    target_thread_id = int(os.getenv("TARGET_THREAD_ID", "3"))                                   

    if not bot_token:
        print("⚠️ Telegram BOT_TOKEN missing. Skipping Telegram delivery.")
        return

    quote_lines = [
        f"{idx:02d} {item['title']} ({item['newspaper']})"
        for idx, item in enumerate(editorial_items, start=1)
    ]
    quote_content = "\n".join(quote_lines)

    # 1. Main Light Edition Caption (Contains the index)
    caption_light = (
        f"📝 <b>Today's Editorials ({ist_date_short})</b>\n"
        f"<blockquote expandable>{quote_content}</blockquote>"
    )

    # 2. Dark Edition Caption (Compact tag so it sits cleanly below)
    caption_dark = f"🌙 <b>Dark Mode Edition (Night Study) • {ist_date_short}</b>"

    def upload_single_pdf(file_path, target_chat, caption, thread_id=None, include_thumb=True):
        filename = os.path.basename(file_path)
        for attempt in range(1, 4):
            thumb_f = None
            try:
                with open(file_path, "rb") as doc:
                    payload = {
                        "chat_id": target_chat,
                        "caption": caption,
                        "parse_mode": "HTML"
                    }
                    if thread_id:
                        payload["message_thread_id"] = int(thread_id)

                    files = {"document": (filename, doc, "application/pdf")}
                    if include_thumb and thumb_path and os.path.exists(thumb_path):
                        thumb_f = open(thumb_path, "rb")
                        files["thumbnail"] = ("thumb.jpg", thumb_f, "image/jpeg")

                    res = requests.post(
                        f"https://api.telegram.org/bot{bot_token}/sendDocument",
                        data=payload,
                        files=files,
                        timeout=(15, 300)
                    )
                    return res
            except (requests.exceptions.RequestException, TimeoutError) as err:
                print(f"⚠️ Upload attempt {attempt}/3 failed ({err}). Retrying in 5s...")
                time.sleep(5)
            finally:
                if thumb_f:
                    thumb_f.close()
        return None

    def relay_group_file(file_path, caption, include_thumb=False, attach_buttons=False):
        filename = os.path.basename(file_path)
        print(f"📤 Uploading {filename} to Source Thread ({source_thread_id})...")
        res = upload_single_pdf(file_path, source_chat_id, caption, thread_id=source_thread_id, include_thumb=include_thumb)
        if not (res and res.status_code == 200):
            print(f"❌ Upload failed for {filename}")
            return None

        source_msg_id = res.json()["result"]["message_id"]
        print(f"🔄 Relaying {filename} to Target Thread {target_thread_id}...")
        
        copy_res = requests.post(
            f"https://api.telegram.org/bot{bot_token}/copyMessage",
            json={
                "chat_id": target_chat_id,
                "from_chat_id": source_chat_id,
                "message_id": source_msg_id,
                "message_thread_id": target_thread_id
            },
            timeout=15
        )

        if copy_res.status_code != 200:
            print(f"❌ Failed to relay {filename}")
            return None

        new_msg_id = copy_res.json()["result"]["message_id"]

        # Attach interactive buttons only to the final message
        if attach_buttons:
            markup = {
                "inline_keyboard": [
                    [{"text": "📖 Mark as Read • 0", "callback_data": f"read_{new_msg_id}"}],
                    [{"text": "🎯 Daily Topic Trials", "url": "https://t.me/Ez_vocab_bot/leaderboard"}]
                ]
            }
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/editMessageReplyMarkup",
                json={"chat_id": target_chat_id, "message_id": new_msg_id, "reply_markup": markup},
                timeout=10
            )
            print("🪄 Interactive attendance & trial buttons attached at the bottom!")

        return new_msg_id

    # 1. Admin Delivery
    if admin_chat_id:
        print("📤 Delivering both files to Admin Telegram...")
        upload_single_pdf(light_pdf_path, admin_chat_id, caption_light, include_thumb=True)
        time.sleep(1.5)
        upload_single_pdf(dark_pdf_path, admin_chat_id, caption_dark, include_thumb=False)

    # 2. Group Publishing: Light Mode first (no buttons), Dark Mode second (with buttons at bottom)
    if enable_group_publish:
        if not source_chat_id or not source_thread_id:
            print("⚠️ Group publishing enabled, but group IDs are missing.")
            return

        # Step 1: Send Light PDF (NO buttons, with thumbnail & full index)
        relay_group_file(light_pdf_path, caption_light, include_thumb=True, attach_buttons=False)
        
        # Brief pause to ensure correct ordering
        time.sleep(1.5)

        # Step 2: Send Dark PDF immediately below (WITH buttons at the bottom)
        relay_group_file(dark_pdf_path, caption_dark, include_thumb=False, attach_buttons=True)
        print("🚀 Publication completed: Both files stacked with buttons at the bottom.")

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

    # Vocab Lab Split Logic
    other_cats = {k: v for k, v in categorized_vocab.items() if k != "core_vocab" and v}
    lab_start_page = start_page + len(reader_pages)
    lab_pages = []

    if not other_cats:
        # If an article only has core vocabulary, keep it on a single natural-height lab page
        lab_pages.append({
            "is_continuation": False,
            "page_num": lab_start_page,
            "show_analysis": True,
            "categorized_vocab": categorized_vocab,
            "has_next_lab_page": False
        })
    else:
        # Lab Page 1: Analysis + Core Vocab Ribbons (Natural Height)
        lab_pages.append({
            "is_continuation": False,
            "page_num": lab_start_page,
            "show_analysis": True,
            "categorized_vocab": {"core_vocab": categorized_vocab.get("core_vocab", [])},
            "has_next_lab_page": True
        })
        # Lab Page 2: Continuation with all secondary categories (Natural Height)
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
    thumb_path = os.path.join(build_dir, "cover_thumb.jpg")

    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Data schema not found at: {json_path}")
    
    with open(json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # IST Time configuration
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    ist_time = datetime.now(ist_offset)
    today_ist_str = ist_time.strftime("%Y-%m-%d")
    schema_date = raw_data.get("date_scraped", today_ist_str)

    # Log warning on date divergence instead of crashing manual re-runs or runs near midnight
    if schema_date != today_ist_str:
        print(f"⚠️ Notice: schema.json date is '{schema_date}', current IST date is '{today_ist_str}'. Proceeding with build.")

    if not raw_data.get("editorials"):
        raise ValueError("schema.json contains 0 editorials.")

    # Real-time Indian Standard Time (IST)
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    ist_time = datetime.now(ist_offset)
    
    pdf_filename = f"{ist_time.strftime('%d-%b-%Y')}.pdf"
    output_pdf_path = os.path.join(output_dir, pdf_filename)
    
    formatted_date_ist = ist_time.strftime(f"%B {ist_time.day}, %Y")
    ist_date_short = ist_time.strftime(f"{ist_time.day} %b %Y")

    processed_articles = []
    toc_entries = []
    editorial_items = []
    page_counter = 3

    for art in raw_data.get("editorials", []):
        vocab_list = art.get("editorial_vocabulary", [])
        
        # Sanitize word-splits in vocab definitions and memory hooks
        for item in vocab_list:
            item["concise_meaning"] = sanitize_vocab_text(item.get("concise_meaning", ""))
            item["mnemonic_trick"] = sanitize_vocab_text(item.get("mnemonic_trick", ""))

        categorized_vocab = categorize_vocabulary(vocab_list)
        
        tone_data = art.get("analysis", {})
        clean_expl = tone_data.get("tone_simple_explanation", "").strip("()")
        
        meta_sub = art.get("editorial_metadata", {}).get("subtitle", "")
        subtitle = meta_sub if meta_sub and meta_sub != "N/A" else None
        title_clean = art.get("title", "")
        editorial_items.append({
            "title": title_clean,
            "newspaper": art.get("newspaper", "Editorial")
        })

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
            "published_at": art.get("published_at") or art.get("editorial_metadata", {}).get("published_at") or raw_data.get("date_scraped", formatted_date_ist),
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

    # Check assets and optimize raster images to 200 DPI
    assets_dir = os.path.join(base_dir, "assets")
    raw_front_cover = os.path.join(assets_dir, "front_cover_bg.jpg")
    raw_toc_bg = os.path.join(assets_dir, "toc_bg.jpg")
    raw_back_cover = os.path.join(assets_dir, "back_cover_bg.jpg")

    front_cover_path = optimize_asset_image(raw_front_cover, build_dir)
    toc_bg_path = optimize_asset_image(raw_toc_bg, build_dir)
    back_cover_path = optimize_asset_image(raw_back_cover, build_dir)

    watermark_png = os.path.join(assets_dir, "watermark.png")
    watermark_svg = os.path.join(assets_dir, "watermark.svg")
    watermark_src = None
    if os.path.exists(watermark_svg):
        watermark_src = f"file://{watermark_svg}".replace("\\", "/")
    elif os.path.exists(watermark_png):
        opt_wm = optimize_asset_image(watermark_png, build_dir, max_width=800)
        watermark_src = f"file://{opt_wm}".replace("\\", "/")

    # Filenames for both standard and dark-mode variants
    date_slug = ist_time.strftime('%d-%b-%Y')
    light_pdf_filename = f"{date_slug}.pdf"
    dark_pdf_filename = f"{date_slug}-dark-mode.pdf"
    
    light_pdf_path = os.path.join(output_dir, light_pdf_filename)
    dark_pdf_path = os.path.join(output_dir, dark_pdf_filename)

    base_render_payload = {
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

    # Define build list
    build_variants = [
        {"is_dark": False, "html_file": "rendered_content_light.html", "pdf_path": light_pdf_path, "name": "Light Mode"},
        {"is_dark": True,  "html_file": "rendered_content_dark.html",  "pdf_path": dark_pdf_path,  "name": "Dark Mode"}
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])

        for var in build_variants:
            print(f"🔨 Building {var['name']} PDF...")
            payload = dict(base_render_payload)
            payload["is_dark_mode"] = var["is_dark"]

            rendered_html = template.render(data=payload)
            rendered_html_path = os.path.join(build_dir, var["html_file"])
            with open(rendered_html_path, "w", encoding="utf-8") as f:
                f.write(rendered_html)

            page = browser.new_page(viewport={"width": 794, "height": 1123})
            page.goto(f"file://{rendered_html_path}", wait_until="networkidle")
            page.evaluate("() => document.fonts.ready")

            id_to_page = page.evaluate("""() => {
                const map = {};
                document.querySelectorAll('.page').forEach((pageElem, pageIdx) => {
                    pageElem.querySelectorAll('[id]').forEach(el => {
                        if (el.id) map[el.id] = pageIdx;
                    });
                });
                return map;
            }""")

            page_count = page.evaluate("() => document.querySelectorAll('.page').length")
            writer = PdfWriter()
            pending_links = []

            for i in range(page_count):
                page_meta = page.evaluate("""(targetIndex) => {
                    const pages = document.querySelectorAll('.page');
                    pages.forEach((p, idx) => {
                        p.style.display = (idx === targetIndex) ? '' : 'none';
                    });
                    const current = pages[targetIndex];
                    const pageRect = current.getBoundingClientRect();
                    
                    const links = [];
                    current.querySelectorAll('a[href^="#"]').forEach(a => {
                        const rect = a.getBoundingClientRect();
                        const targetId = (a.getAttribute('href') || '').replace('#', '').trim();
                        if (targetId && rect.width > 0 && rect.height > 0) {
                            links.push({
                                targetId: targetId,
                                x: rect.left - pageRect.left,
                                y: rect.top - pageRect.top,
                                w: rect.width,
                                h: rect.height
                            });
                        }
                    });

                    return {
                        isCover: current.classList.contains('cover-page'),
                        widthPx: Math.ceil(pageRect.width) || 794,
                        heightPx: Math.ceil(pageRect.height),
                        links: links
                    };
                }""", i)

                if i == 0 and not var["is_dark"]:
                    page.screenshot(path=thumb_path, type="jpeg", quality=85)

                page_height = "297mm" if page_meta["isCover"] else f"{page_meta['heightPx']}px"
                pdf_bytes = page.pdf(
                    width="210mm",
                    height=page_height,
                    print_background=True,
                    margin={"top": "0", "bottom": "0", "left": "0", "right": "0"}
                )

                reader = PdfReader(io.BytesIO(pdf_bytes))
                if len(reader.pages) > 0:
                    p_obj = reader.pages[0]
                    writer.add_page(p_obj)

                    mb = p_obj.mediabox
                    media_w, media_h = float(mb.width), float(mb.height)
                    scale_x = media_w / page_meta["widthPx"]
                    scale_y = media_h / page_meta["heightPx"]

                    for lk in page_meta["links"]:
                        target_idx = id_to_page.get(lk["targetId"])
                        if target_idx is None:
                            m = re.search(r'-p(\d+)', lk["targetId"])
                            if m:
                                target_idx = int(m.group(1)) - 1
                                
                        if target_idx is not None and target_idx != i:
                            x1 = lk["x"] * scale_x
                            x2 = (lk["x"] + lk["w"]) * scale_x
                            y1 = media_h - (lk["y"] + lk["h"]) * scale_y
                            y2 = media_h - lk["y"] * scale_y
                            pending_links.append((i, target_idx, (x1, y1, x2, y2)))

            # Internal Click Annotations
            for src_page, target_page, rect in pending_links:
                if target_page < len(writer.pages):
                    writer.add_annotation(
                        page_number=src_page,
                        annotation=Link(
                            rect=rect,
                            target_page_index=target_page,
                            fit=Fit(fit_type="/Fit")
                        )
                    )

            # Bookmarks & Outlines
            writer.add_outline_item("Front Cover", 0)
            writer.add_outline_item("Table of Contents", 1)
            for art in processed_articles:
                r_idx = id_to_page.get(art["target_reader_id"])
                if r_idx is not None and r_idx < len(writer.pages):
                    parent_outline = writer.add_outline_item(f"{art['title']} ({art['newspaper']})", r_idx)
                    l_idx = id_to_page.get(art["target_vocab_id"])
                    if l_idx is not None and l_idx < len(writer.pages):
                        writer.add_outline_item("Vocabulary Lab", l_idx, parent=parent_outline)

            for page_obj in writer.pages:
                page_obj.compress_content_streams()

            with open(var["pdf_path"], "wb") as f_out:
                writer.write(f_out)

            page.close()
            print(f"✅ Generated {var['name']}: {var['pdf_path']}")

        browser.close()

    # Dispatch both files to Telegram sequentially
    send_to_telegram(light_pdf_path, dark_pdf_path, ist_date_short, editorial_items, thumb_path)

if __name__ == "__main__":
    try:
        compile_magazine()
    except Exception as e:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
        if bot_token and chat_id:
            try:
                requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": f"🚨 **STEP 3 FAILED (Magazine Generator):**\n\n**Error:**\n`{e}`",
                    "parse_mode": "Markdown"
                })
            except Exception:
                pass
        print(f"Fatal magazine build error: {e}")
        sys.exit(1)