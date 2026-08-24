import os
import re
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

def clean_and_highlight_passage(passage_text, vocab_items):
    raw_paras = [p.strip() for p in passage_text.split("\n\n") if p.strip()]
    cleaned_paras = []
    
    sorted_vocab = sorted(
        vocab_items,
        key=lambda x: len(x.get("word_or_phrase", "")),
        reverse=True
    )

    for p in raw_paras:
        if p.startswith("Published") or p.startswith("Updated") or p.startswith("- August") or p.startswith("-August"):
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
    categorized = {
        "core_vocab": [],
        "fixed_prepositions": [],
        "phrasal_verbs": [],
        "one_word_subs": [],
        "idioms": [],
        "foreign_words": []
    }
    
    for item in vocab_items:
        cat = item.get("category", "")
        if cat == "Vocabulary":
            categorized["core_vocab"].append(item)
        elif cat == "Fixed Prepositions":
            categorized["fixed_prepositions"].append(item)
        elif cat == "Phrasal Verbs":
            categorized["phrasal_verbs"].append(item)
        elif cat == "One-Word Substitutions":
            categorized["one_word_subs"].append(item)
        elif cat == "Idioms & Phrases":
            categorized["idioms"].append(item)
        elif cat == "Foreign Words":
            categorized["foreign_words"].append(item)
        else:
            categorized["core_vocab"].append(item)
            
    return categorized

def compile_magazine():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "schema.json")
    templates_dir = os.path.join(base_dir, "templates")
    build_dir = os.path.join(base_dir, "build")
    output_dir = os.path.join(base_dir, "output")
    output_pdf_path = os.path.join(output_dir, "Daily_Editorial_Magazine.pdf")

    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Data schema not found at: {json_path}")
    
    with open(json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # Calculate real-time Indian Standard Time (IST) Date
    ist_time = datetime.now(ZoneInfo("Asia/Kolkata"))
    formatted_date_ist = ist_time.strftime(f"%B {ist_time.day}, %Y")

    processed_articles = []
    toc_entries = []
    page_counter = 3  # Page 1 = Front Cover, Page 2 = TOC

    for idx, art in enumerate(raw_data.get("editorials", []), start=1):
        vocab_list = art.get("editorial_vocabulary", [])
        categorized_vocab = categorize_vocabulary(vocab_list)
        paragraphs = clean_and_highlight_passage(art.get("passage", ""), vocab_list)
        
        # Clean double brackets from tone explanation
        tone_data = art.get("analysis", {})
        raw_expl = tone_data.get("tone_simple_explanation", "")
        clean_expl = raw_expl.strip("()")
        
        meta_sub = art.get("editorial_metadata", {}).get("subtitle", "")
        subtitle = meta_sub if meta_sub and meta_sub != "N/A" else None

        # Build TOC Entry
        toc_entries.append({
            "slot_num": f"{idx:02d}",
            "title": art.get("title", ""),
            "newspaper": art.get("newspaper", "Editorial"),
            "page_num": f"Page {page_counter:02d}"
        })
        
        processed_articles.append({
            "newspaper": art.get("newspaper", "Editorial"),
            "title": art.get("title", ""),
            "subtitle": subtitle,
            "topic": art.get("editorial_metadata", {}).get("topic", "General Studies"),
            "reading_time": art.get("reading_time", "2 min read"),
            "timestamp": art.get("timestamp", formatted_date_ist),
            "analysis": {
                "tone": tone_data.get("tone", "Analytical"),
                "tone_simple_explanation": clean_expl,
                "analysis_summary": tone_data.get("analysis_summary", "")
            },
            "paragraphs": paragraphs,
            "all_vocab": vocab_list,
            "categorized_vocab": categorized_vocab,
            "page_p1": page_counter,
            "page_p2": page_counter + 1
        })
        page_counter += 2

    # Check asset paths (Updated to .jpg for massive file size reduction)
    assets_dir = os.path.join(base_dir, "assets")
    front_cover_path = os.path.join(assets_dir, "front_cover_bg.jpg")
    toc_bg_path = os.path.join(assets_dir, "toc_bg.jpg")
    back_cover_path = os.path.join(assets_dir, "back_cover_bg.jpg")

    render_payload = {
        "date_formatted": formatted_date_ist,
        "date_scraped": raw_data.get("date_scraped", formatted_date_ist),
        "has_front_cover": os.path.exists(front_cover_path),
        "front_cover_src": f"file://{front_cover_path}",
        "has_toc_bg": os.path.exists(toc_bg_path),
        "toc_bg_src": f"file://{toc_bg_path}",
        "has_back_cover": os.path.exists(back_cover_path),
        "back_cover_src": f"file://{back_cover_path}",
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

    # Render all pages in one pass
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = browser.new_page()
        page.goto(f"file://{rendered_html_path}", wait_until="networkidle")
        page.evaluate("() => document.fonts.ready")
        page.pdf(
            path=output_pdf_path,
            format="A4",
            print_background=True,
            prefer_css_page_size=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )
        browser.close()

    print(f"✅ Generated Complete Magazine with TOC at: {output_pdf_path}")

if __name__ == "__main__":
    compile_magazine()