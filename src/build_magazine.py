import os
import sys
import re
import json
import requests
import io
import time
import base64
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

def create_dark_watermark(src_path: str, cache_dir: str) -> str:
    """Generates an inverted dark-mode watermark once with PIL so Chromium embeds it as a single native XObject."""
    if not os.path.exists(src_path):
        return src_path

    filename = os.path.basename(src_path)
    dark_path = os.path.join(cache_dir, f"dark_opt_{filename}")

    if os.path.exists(dark_path) and os.path.getmtime(dark_path) >= os.path.getmtime(src_path):
        return dark_path

    try:
        from PIL import ImageOps
        with Image.open(src_path) as img:
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            r, g, b, a = img.split()
            rgb = Image.merge("RGB", (r, g, b))
            inv_rgb = ImageOps.invert(rgb)
            r2, g2, b2 = inv_rgb.split()
            dark_img = Image.merge("RGBA", (r2, g2, b2, a))
            dark_img.save(dark_path, "PNG", optimize=True)
        return dark_path
    except Exception as err:
        print(f"⚠️ Could not create dark watermark ({err}). Using original.")
        return src_path

# The exact families/weights/styles your template.html actually uses.
STATIC_FONT_SPECS = [
    ("Lora", [(400, "normal"), (500, "normal"), (600, "normal"), (700, "normal"), (400, "italic")]),
    ("Montserrat", [(400, "normal"), (500, "normal"), (600, "normal"), (700, "normal"), (800, "normal")]),
    ("Inter", [(400, "normal"), (500, "normal"), (600, "normal"), (700, "normal"), (800, "normal"), (900, "normal")]),
    ("Noto Sans Devanagari", [(400, "normal"), (500, "normal"), (600, "normal"), (700, "normal"), (800, "normal")]),
]

def fetch_static_google_fonts(cache_dir: str) -> str:
    """
    Downloads STATIC (non-variable) woff2 files for the exact weights/styles used,
    via Google Fonts' legacy v1 CSS API — which always returns separate per-weight
    files, unlike the v2 (css2) API previously used, which can silently serve a
    single variable font file instead. Chromium's PDF export embeds static fonts as
    normal compact outlines; it was falling back to slow per-glyph Type 3 fonts on
    the variable file the old @import pulled in. Cached across runs via manifest.css.
    """
    fonts_dir = os.path.join(cache_dir, "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    manifest_path = os.path.join(fonts_dir, "manifest.css")

    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            return f.read()

    family_params = []
    for family, variants in STATIC_FONT_SPECS:
        weight_tokens = [f"{w}italic" if s == "italic" else str(w) for w, s in variants]
        family_params.append(f"{family.replace(' ', '+')}:{','.join(weight_tokens)}")
    url = "https://fonts.googleapis.com/css?family=" + "|".join(family_params) + "&display=swap"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        css_text = resp.text
    except Exception as err:
        print(f"⚠️ Could not fetch static Google Fonts CSS ({err}). Falling back to no custom fonts.")
        return ""

    def _download_and_rewrite(match):
        remote_url = match.group(1)
        local_name = remote_url.rstrip("/").split("/")[-1]
        local_path = os.path.join(fonts_dir, local_name)
        if not os.path.exists(local_path):
            try:
                r = requests.get(remote_url, timeout=20)
                r.raise_for_status()
                with open(local_path, "wb") as f_out:
                    f_out.write(r.content)
            except Exception as err:
                print(f"⚠️ Could not download font file {remote_url}: {err}")
                return match.group(0)
        return f"url('fonts/{local_name}')"

    local_css = re.sub(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", _download_and_rewrite, css_text)

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(local_css)

    return local_css

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
    # Clean broken LaTeX / math currency strings without destroying legitimate dollar signs ($)
    passage_text = passage_text.replace(r'$\overline{7}', '₹').replace(r'$\approx', '₹~')
    passage_text = re.sub(r'\$(?:\\overline\{7\}|\\approx)', '₹', passage_text)
    passage_text = passage_text.replace(r'\overline{7}', '₹')
    
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

        # Reserve claimed character segments to prevent duplicate sub-token matching
        vocab_spans = []
        claimed = [False] * len(p)
        for item in sorted_vocab:
            term = item.get("word_or_phrase", "").strip()
            idx = item.get("order_index", "")
            if not term:
                continue
            pattern = rf'(?<![A-Za-z0-9])({re.escape(term)})(?![A-Za-z0-9])'
            for match in re.finditer(pattern, p, re.IGNORECASE):
                start, end = match.start(), match.end()
                if any(claimed[i] for i in range(start, end)):
                    continue
                for i in range(start, end):
                    claimed[i] = True
                vocab_spans.append({
                    "start": start,
                    "end": end,
                    "idx": idx
                })

        # Clip boundary-crossing spans to prevent overlapping HTML
        raw_evidence = extract_evidence_spans(p)
        clean_evidence = []
        for e in raw_evidence:
            e_start, e_end = e["start"], e["end"]
            for v in vocab_spans:
                v_start, v_end = v["start"], v["end"]
                if e_start < v_start < e_end < v_end:
                    e_end = v_start
                elif v_start < e_start < v_end < e_end:
                    e_start = v_end
            if e_start < e_end:
                clean_evidence.append({"start": e_start, "end": e_end})

        # Nesting order: Vocab Close (1), Evidence Close (2), Evidence Open (3), Vocab Open (4)
        tags_by_pos = {}
        for v in vocab_spans:
            tags_by_pos.setdefault(v["end"], []).append((1, f'<sup class="v-idx">{v["idx"]}</sup></span>'))
            tags_by_pos.setdefault(v["start"], []).append((4, '<span class="vocab-hl">'))

        for e in clean_evidence:
            tags_by_pos.setdefault(e["end"], []).append((2, '</span>'))
            tags_by_pos.setdefault(e["start"], []).append((3, '<span class="evidence-hl">'))

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
    
    enable_group_publish = os.getenv("ENABLE_GROUP_PUBLISH", "false").strip().lower() == "true"
    source_chat_id = os.getenv("TELEGRAM_GROUP_CHAT_ID")   
    source_thread_id = os.getenv("TELEGRAM_THREAD_ID")     
    target_chat_id = os.getenv("TARGET_CHAT_ID")  
    raw_thread_id = os.getenv("TARGET_THREAD_ID")
    target_thread_id = int(raw_thread_id) if raw_thread_id and raw_thread_id.isdigit() else None

    if not bot_token:
        print("⚠️ Telegram BOT_TOKEN missing. Skipping Telegram delivery.")
        return

    # Build caption with strict 1024-character safety truncation
    header = f"📝 <b>Today's Editorials ({ist_date_short})</b>\n<blockquote expandable>"
    footer = "</blockquote>"
    max_body_len = 1000 - len(header) - len(footer)

    quote_lines = [
        f"{idx:02d} {item['title']} ({item['newspaper']})"
        for idx, item in enumerate(editorial_items, start=1)
    ]
    
    quote_body = ""
    for line in quote_lines:
        candidate = f"{quote_body}\n{line}".strip() if quote_body else line
        if len(candidate) > max_body_len:
            quote_body = (quote_body + "\n...").strip()
            break
        quote_body = candidate

    caption_light = f"{header}{quote_body}{footer}"
    caption_dark = f"🌙 <b>Dark Mode Edition (Night Study) • {ist_date_short}</b>"

    def upload_single_pdf(file_path, target_chat, caption, thread_id=None, include_thumb=True):
        filename = os.path.basename(file_path)
        last_error = "Unknown error"
        
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
                    
                    if res.status_code == 200:
                        return res
                    
                    last_error = f"HTTP {res.status_code}: {res.text}"
                    print(f"⚠️ Upload attempt {attempt}/3 returned error ({last_error}). Retrying...")
            except (requests.exceptions.RequestException, TimeoutError) as err:
                last_error = str(err)
                print(f"⚠️ Upload attempt {attempt}/3 encountered network fault ({err}). Retrying...")
            finally:
                if thumb_f:
                    thumb_f.close()
            time.sleep(5)
            
        raise RuntimeError(f"Failed to upload {filename} to chat {target_chat} after 3 attempts: {last_error}")

    def relay_group_file(file_path, caption, include_thumb=False, attach_buttons=False):
        filename = os.path.basename(file_path)
        print(f"📤 Uploading {filename} to Source Thread ({source_thread_id})...")
        res = upload_single_pdf(file_path, source_chat_id, caption, thread_id=source_thread_id, include_thumb=include_thumb)

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
            raise RuntimeError(f"Failed to relay {filename} to {target_chat_id}: {copy_res.text}")

        new_msg_id = copy_res.json()["result"]["message_id"]

        if attach_buttons:
            markup = {
                "inline_keyboard": [
                    [{"text": "📖 Mark as Read • 0", "callback_data": f"read_{new_msg_id}"}],
                    [{"text": "🎯 Daily Topic Trials", "url": "https://t.me/Ez_vocab_bot/leaderboard"}]
                ]
            }
            btn_res = requests.post(
                f"https://api.telegram.org/bot{bot_token}/editMessageReplyMarkup",
                json={"chat_id": target_chat_id, "message_id": new_msg_id, "reply_markup": markup},
                timeout=10
            )
            if btn_res.status_code != 200:
                print(f"⚠️ Warning: Interactive buttons could not be attached: {btn_res.text}")

        return new_msg_id

    # 1. Admin Delivery
    if admin_chat_id:
        print("📤 Delivering both files to Admin Telegram...")
        upload_single_pdf(light_pdf_path, admin_chat_id, caption_light, include_thumb=True)
        time.sleep(1.5)
        upload_single_pdf(dark_pdf_path, admin_chat_id, caption_dark, include_thumb=True)

    # 2. Group Publishing
    if enable_group_publish:
        missing_creds = []
        if not source_chat_id: missing_creds.append("TELEGRAM_GROUP_CHAT_ID")
        if not source_thread_id: missing_creds.append("TELEGRAM_THREAD_ID")
        if not target_chat_id: missing_creds.append("TARGET_CHAT_ID")
        if target_thread_id is None: missing_creds.append("TARGET_THREAD_ID")

        if missing_creds:
            print(f"⚠️ Group publishing skipped: Missing secrets [{', '.join(missing_creds)}].", flush=True)
            print("ℹ️ To enable group publishing, add TARGET_CHAT_ID and TARGET_THREAD_ID to repository Secrets.", flush=True)
        else:
            relay_group_file(light_pdf_path, caption_light, include_thumb=True, attach_buttons=False)
            time.sleep(1.5)
            relay_group_file(dark_pdf_path, caption_dark, include_thumb=True, attach_buttons=True)
            print("🚀 Publication completed: Both files stacked with thumbnails and buttons.", flush=True)

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

def get_stance_theme(tone_str: str) -> dict:
    """Returns chromatic tone gradients and organic geometric shapes based on editorial stance."""
    t = (tone_str or "").lower()
    if any(k in t for k in ["critical", "pessimistic", "disapproving", "sarcastic", "cynical", "hostile", "admonitory"]):
        return {"tone_a": "#f43f5e", "tone_b": "#e11d48", "shape": "shape-jagged"}
    elif any(k in t for k in ["cautious", "concerned", "cautionary", "sceptical", "skeptical"]):
        return {"tone_a": "#f59e0b", "tone_b": "#d97706", "shape": "shape-wave"}
    elif any(k in t for k in ["optimistic", "appreciative", "empathetic", "conciliatory"]):
        return {"tone_a": "#10b981", "tone_b": "#059669", "shape": "shape-circle"}
    else:
        # Informative, Analytical, Persuasive, Balanced
        return {"tone_a": "#38bdf8", "tone_b": "#0ea5e9", "shape": "shape-circle"}

def compute_word_tone_mix(vocab_items: list) -> dict:
    """Calculates counts and exact track percentage distributions for Positive, Neutral, and Negative words."""
    pos = 0
    neu = 0
    neg = 0
    for v in vocab_items:
        connot = str(v.get("connotation", "")).strip().lower()
        if "pos" in connot:
            pos += 1
        elif "neg" in connot:
            neg += 1
        else:
            neu += 1

    total = pos + neu + neg
    if total == 0:
        return {
            "pos_count": 0, "neu_count": 0, "neg_count": 0,
            "pos_pct": 0, "neu_pct": 100, "neg_pct": 0,
            "total": 0
        }

    pos_pct = round((pos / total) * 100)
    neu_pct = round((neu / total) * 100)
    neg_pct = max(0, 100 - (pos_pct + neu_pct))

    return {
        "pos_count": pos,
        "neu_count": neu,
        "neg_count": neg,
        "pos_pct": pos_pct,
        "neu_pct": neu_pct,
        "neg_pct": neg_pct,
        "total": total
    }

def partition_article(art_raw, categorized_vocab, all_vocab, start_page):
    """Partitions an editorial: Page 1 gets Vocabulary + One-Word Substitutions; Page 2 gets remaining categories."""
    raw_paras = clean_and_highlight_passage(art_raw.get("passage", ""), all_vocab)
    
    # 1. Continuous Reader Page (Always renders on a single dynamic-height page)
    reader_pages = [{
        "is_continuation": False,
        "paragraphs": raw_paras,
        "vocab": all_vocab,
        "page_num": start_page,
        "has_next_reader_page": False
    }]

    # 2. Continuous Vocab Lab Partitioning
    # Page 1: Core Vocabulary + One-Word Substitutions
    page1_cats = {}
    if categorized_vocab.get("core_vocab"):
        page1_cats["core_vocab"] = categorized_vocab["core_vocab"]
    if categorized_vocab.get("one_word_subs"):
        page1_cats["one_word_subs"] = categorized_vocab["one_word_subs"]

    # Page 2: All subsequent categories (Fixed Prepositions, Phrasals, Idioms, Foreign Words)
    page2_cats = {
        k: v for k, v in categorized_vocab.items()
        if k not in ("core_vocab", "one_word_subs") and v
    }

    lab_start_page = start_page + 1
    lab_pages = []

    if not page2_cats:
        lab_pages.append({
            "is_continuation": False,
            "page_num": lab_start_page,
            "show_analysis": True,
            "categorized_vocab": page1_cats,
            "has_next_lab_page": False
        })
    else:
        lab_pages.append({
            "is_continuation": False,
            "page_num": lab_start_page,
            "show_analysis": True,
            "categorized_vocab": page1_cats,
            "has_next_lab_page": True
        })
        lab_pages.append({
            "is_continuation": True,
            "page_num": lab_start_page + 1,
            "show_analysis": False,
            "categorized_vocab": page2_cats,
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

    # IST Time configuration: Anchor date strictly to schema.json date_scraped
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    raw_date_str = raw_data.get("date_scraped")

    if raw_date_str:
        try:
            edition_date = datetime.strptime(raw_date_str, "%Y-%m-%d").replace(tzinfo=ist_offset)
        except ValueError:
            edition_date = datetime.now(ist_offset)
    else:
        edition_date = datetime.now(ist_offset)

    current_ist_str = datetime.now(ist_offset).strftime("%Y-%m-%d")
    if raw_date_str and raw_date_str != current_ist_str:
        print(f"⚠️ Notice: Anchoring build to schema date '{raw_date_str}' (Current runner IST date: '{current_ist_str}').")

    if not raw_data.get("editorials"):
        raise ValueError("schema.json contains 0 editorials.")

    date_slug = edition_date.strftime("%d-%b-%Y")
    pdf_filename = f"{date_slug}.pdf"
    output_pdf_path = os.path.join(output_dir, pdf_filename)

    formatted_date_ist = edition_date.strftime(f"%B {edition_date.day}, %Y")
    ist_date_short = edition_date.strftime(f"{edition_date.day} %b %Y")

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
            "link": art.get("link", "").strip(),
            "analysis": {
                "tone": tone_data.get("tone", "Analytical"),
                "tone_simple_explanation": clean_expl,
                "analysis_summary": tone_data.get("analysis_summary", ""),
                "tone_a": get_stance_theme(tone_data.get("tone", "Analytical"))["tone_a"],
                "tone_b": get_stance_theme(tone_data.get("tone", "Analytical"))["tone_b"],
                "shape": get_stance_theme(tone_data.get("tone", "Analytical"))["shape"],
                "word_tone_mix": compute_word_tone_mix(vocab_list)
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
    watermark_dark_src = None

    if os.path.exists(watermark_svg):
        watermark_src = f"file://{watermark_svg}".replace("\\", "/")
        watermark_dark_src = watermark_src
    elif os.path.exists(watermark_png):
        opt_wm = optimize_asset_image(watermark_png, build_dir, max_width=800)
        watermark_src = f"file://{opt_wm}".replace("\\", "/")
        # Creates an inverted light-colored watermark file for Dark Mode
        dark_wm = create_dark_watermark(opt_wm, build_dir)
        watermark_dark_src = f"file://{dark_wm}".replace("\\", "/")

    # Filenames for both standard and dark-mode variants
    date_slug = edition_date.strftime('%d-%b-%Y')
    light_pdf_filename = f"{date_slug}.pdf"
    dark_pdf_filename = f"{date_slug}-dark-mode.pdf"
    
    light_pdf_path = os.path.join(output_dir, light_pdf_filename)
    dark_pdf_path = os.path.join(output_dir, dark_pdf_filename)

    font_face_css = fetch_static_google_fonts(build_dir)

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
        "articles": processed_articles,
        "font_face_css": font_face_css
    }

    env = Environment(loader=FileSystemLoader([templates_dir, base_dir]))
    template = env.get_template("template.html")

    # Define build list
    build_variants = [
        {"is_dark": False, "html_file": "rendered_content_light.html", "pdf_path": light_pdf_path, "name": "Light Mode"},
        {"is_dark": True,  "html_file": "rendered_content_dark.html",  "pdf_path": dark_pdf_path,  "name": "Dark Mode"}
    ]

    with sync_playwright() as p:
        for var in build_variants:
            print(f"🔨 Building {var['name']} PDF...", flush=True)
            payload = dict(base_render_payload)
            payload["is_dark_mode"] = var["is_dark"]
            
            # If generating Dark Mode, swap the watermark to the inverted version
            if var["is_dark"] and watermark_dark_src:
                payload["watermark_src"] = watermark_dark_src

            rendered_html = template.render(data=payload)
            rendered_html_path = os.path.join(build_dir, var["html_file"])
            with open(rendered_html_path, "w", encoding="utf-8") as f:
                f.write(rendered_html)

            # Isolated browser lifecycle per variant without --single-process or --no-zygote
            browser = p.chromium.launch(args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ])

            try:
                page = browser.new_page(
                    viewport={"width": 794, "height": 1123},
                    device_scale_factor=2
                )
                page.goto(f"file://{rendered_html_path}", wait_until="networkidle")
                page.evaluate("() => document.fonts.ready")

                # 1. Single layout pass: extract all geometry, links, and target IDs upfront
                render_manifest = page.evaluate("""() => {
                    const pages = Array.from(document.querySelectorAll('.page'));
                    const idToPage = {};

                    pages.forEach((pageElem, pageIdx) => {
                        pageElem.querySelectorAll('[id]').forEach(el => {
                            if (el.id) idToPage[el.id] = pageIdx;
                        });
                    });

                    const pagesMeta = pages.map((pageElem, idx) => {
                        const pageRect = pageElem.getBoundingClientRect();
                        const links = [];

                        pageElem.querySelectorAll('a[href^="#"]').forEach(a => {
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
                            index: idx,
                            isCover: pageElem.classList.contains('cover-page'),
                            widthPx: Math.ceil(pageRect.width) || 794,
                            heightPx: Math.ceil(pageRect.height),
                            links: links
                        };
                    });

                    return { idToPage, pagesMeta };
                }""")

                id_to_page = render_manifest["idToPage"]
                pages_meta = render_manifest["pagesMeta"]
                writer = PdfWriter()
                pending_links = []

                # 2. Rendering pass: toggle node visibility and apply hybrid raster-vector baking
                for i, page_meta in enumerate(pages_meta):
                    page.evaluate("""(targetIndex) => {
                        const pages = document.querySelectorAll('.page');
                        pages.forEach((p, idx) => {
                            p.style.display = (idx === targetIndex) ? '' : 'none';
                        });
                    }""", i)

                    if i == 0 and not var["is_dark"]:
                        page.screenshot(path=thumb_path, type="jpeg", quality=85)

                    # For inner editorial & vocab pages: pre-bake frosted glass to eliminate PDF live blur shaders
                    if not page_meta["isCover"]:
                        page.evaluate("""(targetIndex) => {
                            const p = document.querySelectorAll('.page')[targetIndex];
                            p.classList.add('bake-hidden');
                        }""", i)

                        page_elem = page.locator('.page').nth(i)
                        bg_bytes = page_elem.screenshot(type="jpeg", quality=92)
                        bg_b64 = base64.b64encode(bg_bytes).decode('utf-8')

                        page.evaluate("""({ targetIndex, b64 }) => {
                            const p = document.querySelectorAll('.page')[targetIndex];
                            p.classList.remove('bake-hidden');
                            p.classList.add('bake-applied');
                            p.style.backgroundImage = `url('data:image/jpeg;base64,${b64}')`;
                        }""", {"targetIndex": i, "b64": bg_b64})

                    page_height = "297mm" if page_meta["isCover"] else f"{page_meta['heightPx']}px"
                    pdf_bytes = page.pdf(
                        width="210mm",
                        height=page_height,
                        print_background=True,
                        margin={"top": "0", "bottom": "0", "left": "0", "right": "0"}
                    )

                    # Release baked background immediately to keep runner memory low
                    if not page_meta["isCover"]:
                        page.evaluate("""(targetIndex) => {
                            const p = document.querySelectorAll('.page')[targetIndex];
                            p.classList.remove('bake-applied');
                            p.style.backgroundImage = '';
                        }""", i)

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

                # Bookmarks & Outlines: Guard against missing cover/TOC pages
                bookmark_page = 0
                if payload.get("has_front_cover") and len(writer.pages) > bookmark_page:
                    writer.add_outline_item("Front Cover", bookmark_page)
                    bookmark_page += 1
                    
                if payload.get("has_toc_bg") and len(writer.pages) > bookmark_page:
                    writer.add_outline_item("Table of Contents", bookmark_page)
                    bookmark_page += 1

                for art in processed_articles:
                    r_idx = id_to_page.get(art["target_reader_id"])
                    if r_idx is not None and r_idx < len(writer.pages):
                        parent_outline = writer.add_outline_item(f"{art['title']} ({art['newspaper']})", r_idx)
                        l_idx = id_to_page.get(art["target_vocab_id"])
                        if l_idx is not None and l_idx < len(writer.pages):
                            writer.add_outline_item("Vocabulary Lab", l_idx, parent=parent_outline)

                for page_obj in writer.pages:
                    page_obj.compress_content_streams()

                # Merge byte-identical objects (fonts, cover/watermark images) that
                # were duplicated once per logical page during the per-page render loop.
                writer.compress_identical_objects(
                    remove_duplicates=True,
                    remove_unreferenced=True
                )

                with open(var["pdf_path"], "wb") as f_out:
                    writer.write(f_out)

                print(f"✅ Generated {var['name']}: {var['pdf_path']}", flush=True)
            finally:
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