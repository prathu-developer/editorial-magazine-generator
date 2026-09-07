import os
import sys
import re
import json
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader

# Resolve repository paths whether executed from repo root or src/
CURRENT_DIR = os.path.abspath(os.path.dirname(__file__))
REPO_ROOT = CURRENT_DIR if os.path.exists(os.path.join(CURRENT_DIR, "schema.json")) else os.path.dirname(CURRENT_DIR)
SRC_DIR = os.path.join(REPO_ROOT, "src")

for path in (REPO_ROOT, SRC_DIR):
    if os.path.exists(path) and path not in sys.path:
        sys.path.insert(0, path)

from evidence_lens import extract_evidence_spans

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

    all_matched = {id(item) for cat_list in categorized.values() for item in cat_list}
    for item in vocab_items:
        if id(item) not in all_matched:
            categorized["core_vocab"].append(item)

    return categorized

def match_vocab_to_paragraphs(paragraphs, vocab_items):
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
    raw_paras = clean_and_highlight_passage(art_raw.get("passage", ""), all_vocab)
    p1_max_words = 999999
    p1_max_vocab = 999999
    
    needs_split = (sum(len(p.split()) for p in raw_paras) > p1_max_words) or (len(all_vocab) > p1_max_vocab)
    
    reader_pages = []
    if not needs_split or len(raw_paras) <= 1:
        reader_pages.append({
            "is_continuation": False,
            "paragraphs": raw_paras,
            "vocab": all_vocab,
            "page_num": start_page,
            "has_next_reader_page": False
        })
    else:
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
                limit = 350
            else:
                curr_page_paras.append(para)
                curr_words += w_count

        if curr_page_paras:
            pages_paras.append(curr_page_paras)

        assigned_vocab_ids = set()
        for idx, paras in enumerate(pages_paras):
            is_first = (idx == 0)
            is_last = (idx == len(pages_paras) - 1)
            
            page_vocab, _ = match_vocab_to_paragraphs(paras, all_vocab)
            page_vocab = [v for v in page_vocab if id(v) not in assigned_vocab_ids]
            for v in page_vocab:
                assigned_vocab_ids.add(id(v))

            if is_last:
                page_vocab.extend([v for v in all_vocab if id(v) not in assigned_vocab_ids])

            current_page_num = start_page + idx
            reader_pages.append({
                "is_continuation": not is_first,
                "paragraphs": paras,
                "vocab": page_vocab,
                "page_num": current_page_num,
                "has_next_reader_page": not is_last,
                "next_page_num": current_page_num + 1 if not is_last else None
            })

    other_cats = {k: v for k, v in categorized_vocab.items() if k != "core_vocab" and v}
    lab_start_page = start_page + len(reader_pages)
    lab_pages = []

    if not other_cats:
        lab_pages.append({
            "is_continuation": False,
            "page_num": lab_start_page,
            "show_analysis": True,
            "categorized_vocab": categorized_vocab,
            "has_next_lab_page": False
        })
    else:
        lab_pages.append({
            "is_continuation": False,
            "page_num": lab_start_page,
            "show_analysis": True,
            "categorized_vocab": {"core_vocab": categorized_vocab.get("core_vocab", [])},
            "has_next_lab_page": True
        })
        lab_pages.append({
            "is_continuation": True,
            "page_num": lab_start_page + 1,
            "show_analysis": False,
            "categorized_vocab": other_cats,
            "has_next_lab_page": False
        })
        
    return reader_pages, lab_pages

def generate_preview():
    json_path = os.path.join(REPO_ROOT, "schema.json")
    templates_dir = os.path.join(REPO_ROOT, "templates")
    assets_dir = os.path.join(REPO_ROOT, "assets")
    build_dir = os.path.join(REPO_ROOT, "build")
    os.makedirs(build_dir, exist_ok=True)

    if not os.path.exists(json_path):
        raise FileNotFoundError(f"schema.json not found at: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    ist_offset = timezone(timedelta(hours=5, minutes=30))
    ist_time = datetime.now(ist_offset)
    formatted_date_ist = ist_time.strftime(f"%B {ist_time.day}, %Y")

    processed_articles = []
    toc_entries = []
    page_counter = 3

    for art in raw_data.get("editorials", []):
        vocab_list = art.get("editorial_vocabulary", [])
        for item in vocab_list:
            item["concise_meaning"] = sanitize_vocab_text(item.get("concise_meaning", ""))
            item["mnemonic_trick"] = sanitize_vocab_text(item.get("mnemonic_trick", ""))

        categorized_vocab = categorize_vocabulary(vocab_list)
        tone_data = art.get("analysis", {})
        clean_expl = tone_data.get("tone_simple_explanation", "").strip("()")
        
        meta_sub = art.get("editorial_metadata", {}).get("subtitle", "")
        subtitle = meta_sub if meta_sub and meta_sub != "N/A" else None
        title_clean = art.get("title", "")

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
                "analysis_summary": tone_data.get("analysis_summary", "")
            },
            "reader_pages": reader_pages,
            "lab_pages": lab_pages,
            "target_reader_id": target_reader_id,
            "target_vocab_id": target_vocab_id,
            "last_lab_page": lab_pages[-1]["page_num"]
        })
        
        page_counter += total_art_pages

    def get_asset_uri(filename):
        target = os.path.join(assets_dir, filename)
        if os.path.exists(target):
            # Compute relative path from build/ to assets/ so HTML opens cleanly in any browser
            return os.path.relpath(target, build_dir).replace("\\", "/")
        return ""

    front_cover_uri = get_asset_uri("front_cover_bg.jpg")
    toc_bg_uri = get_asset_uri("toc_bg.jpg")
    back_cover_uri = get_asset_uri("back_cover_bg.jpg")
    watermark_uri = get_asset_uri("watermark.svg") or get_asset_uri("watermark.png")

    base_payload = {
        "date_formatted": formatted_date_ist,
        "date_scraped": raw_data.get("date_scraped", formatted_date_ist),
        "has_front_cover": bool(front_cover_uri),
        "front_cover_src": front_cover_uri,
        "has_toc_bg": bool(toc_bg_uri),
        "toc_bg_src": toc_bg_uri,
        "has_back_cover": bool(back_cover_uri),
        "back_cover_src": back_cover_uri,
        "has_watermark": bool(watermark_uri),
        "watermark_src": watermark_uri,
        "toc_entries": toc_entries,
        "total_articles": len(processed_articles),
        "articles": processed_articles
    }

    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("template.html")

    # Generate both light and dark preview files
    variants = [
        {"file": "rendered_content_light.html", "is_dark": False},
        {"file": "rendered_content_dark.html", "is_dark": True},
        {"file": "rendered_content.html", "is_dark": False}  # Default fallback
    ]

    for v in variants:
        payload = dict(base_payload)
        payload["is_dark_mode"] = v["is_dark"]
        out_path = os.path.join(build_dir, v["file"])
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(template.render(data=payload))
        print(f"✨ Generated: {out_path}")

if __name__ == "__main__":
    generate_preview()