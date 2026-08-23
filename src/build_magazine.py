import os
import re
import json
import pypdf
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

def clean_and_highlight_passage(passage_text, vocab_items):
    """
    Cleans passage paragraphs and highlights vocabulary words with tiny superscript numbers.
    No underlines are added for a clean editorial look.
    """
    raw_paras = [p.strip() for p in passage_text.split("\n\n") if p.strip()]
    cleaned_paras = []
    
    # Sort vocab by phrase length descending to match multi-word phrases first
    sorted_vocab = sorted(
        vocab_items,
        key=lambda x: len(x.get("word_or_phrase", "")),
        reverse=True
    )

    for p in raw_paras:
        # Filter out trailing metadata strings inside passage
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
    """
    Splits vocabulary items into distinct grammatical categories.
    """
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

    processed_articles = []
    page_counter = 3

    for art in raw_data.get("editorials", []):
        vocab_list = art.get("editorial_vocabulary", [])
        categorized_vocab = categorize_vocabulary(vocab_list)
        paragraphs = clean_and_highlight_passage(art.get("passage", ""), vocab_list)
        
        # Clean double parentheses from tone explanation
        tone_data = art.get("analysis", {})
        raw_expl = tone_data.get("tone_simple_explanation", "")
        clean_expl = raw_expl.strip("()")
        
        meta_sub = art.get("editorial_metadata", {}).get("subtitle", "")
        subtitle = meta_sub if meta_sub and meta_sub != "N/A" else None
        
        processed_articles.append({
            "newspaper": art.get("newspaper", "Editorial"),
            "title": art.get("title", ""),
            "subtitle": subtitle,
            "topic": art.get("editorial_metadata", {}).get("topic", "General Studies"),
            "reading_time": art.get("reading_time", "2 min read"),
            "timestamp": art.get("timestamp", raw_data.get("date_scraped", "")),
            "analysis": {
                "tone": tone_data.get("tone", "Analytical"),
                "tone_simple_explanation": clean_expl,
                "analysis_summary": tone_data.get("analysis_summary", "")
            },
            "paragraphs": paragraphs,
            "all_vocab": vocab_list,
            "categorized_vocab": categorized_vocab,
            "core_vocab_count": len(categorized_vocab["core_vocab"]),
            "page_p1": page_counter,
            "page_p2": page_counter + 1
        })
        page_counter += 2

    render_payload = {
        "date_scraped": raw_data.get("date_scraped", ""),
        "total_articles": len(processed_articles),
        "articles": processed_articles
    }

    env = Environment(loader=FileSystemLoader([templates_dir, base_dir]))
    template = env.get_template("template.html")
    rendered_html = template.render(data=render_payload)

    rendered_html_path = os.path.join(build_dir, "rendered_content.html")
    with open(rendered_html_path, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    # Print to PDF using Headless Chromium
    dynamic_pdf = os.path.join(build_dir, "dynamic_content.pdf")
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = browser.new_page()
        page.goto(f"file://{rendered_html_path}", wait_until="networkidle")
        page.evaluate("() => document.fonts.ready")
        page.pdf(
            path=dynamic_pdf,
            format="A4",
            print_background=True,
            prefer_css_page_size=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )
        browser.close()

    # Merge Static Covers
    merger = pypdf.PdfMerger()
    front_cover = os.path.join(base_dir, "assets", "static_front_cover.pdf")
    back_cover = os.path.join(base_dir, "assets", "static_back_cover.pdf")

    if os.path.exists(front_cover):
        merger.append(front_cover)

    merger.append(dynamic_pdf)

    if os.path.exists(back_cover):
        merger.append(back_cover)

    merger.write(output_pdf_path)
    merger.close()
    print(f"✅ Generated Magazine PDF successfully at: {output_pdf_path}")

if __name__ == "__main__":
    compile_magazine()