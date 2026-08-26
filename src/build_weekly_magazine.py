import os
import json
import glob
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

def categorize_vocabulary(vocab_items):
    """Sorts vocabulary into specific categories."""
    categorized = {
        "Core_Vocabulary": [],
        "One_Word_Substitutions": [],
        "Fixed_Prepositions": [],
        "Phrasal_Verbs": [],
        "Idioms_and_Phrases": [],
        "Foreign_Words": []
    }

    for item in vocab_items:
        cat = str(item.get("category", "")).strip().lower()
        if "one-word" in cat:
            categorized["One_Word_Substitutions"].append(item)
        elif "preposition" in cat:
            categorized["Fixed_Prepositions"].append(item)
        elif "phrasal" in cat:
            categorized["Phrasal_Verbs"].append(item)
        elif "idiom" in cat:
            categorized["Idioms_and_Phrases"].append(item)
        elif "foreign" in cat:
            categorized["Foreign_Words"].append(item)
        else:
            categorized["Core_Vocabulary"].append(item)
            
    return categorized

def compile_weekly_magazine():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    backups_dir = os.path.join(base_dir, "backups")
    build_dir = os.path.join(base_dir, "build")
    output_dir = os.path.join(base_dir, "output")

    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # 1. Read all JSON files from the backups directory
    json_files = sorted(glob.glob(os.path.join(backups_dir, "*.json")))
    if not json_files:
        print("No backup files found in the 'backups' directory.")
        return

    aggregated_editorials = []

    # 2. Extract editorials from Monday to Saturday
    for file_path in json_files:
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                daily_data = json.load(f)
                aggregated_editorials.extend(daily_data.get("editorials", []))
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON file: {file_path}")

    # 3. Limit to maximum 25 editorials as requested
    aggregated_editorials = aggregated_editorials[:25]

    # 4. Process the vocabulary for the template
    processed_articles = []
    for art in aggregated_editorials:
        vocab_list = art.get("editorial_vocabulary", [])
        categorized_vocab = categorize_vocabulary(vocab_list)
        
        processed_articles.append({
            "title": art.get("title", "Untitled Editorial"),
            "newspaper": art.get("newspaper", "Editorial"),
            "timestamp": art.get("timestamp", ""),
            "categorized_vocab": categorized_vocab
        })

    # 5. Render HTML with Jinja2
    ist_time = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    edition_date = ist_time.strftime("%B %d, %Y")

    env = Environment(loader=FileSystemLoader(base_dir))
    template = env.get_template("template.html")
    rendered_html = template.render(
        edition_date=edition_date,
        editorials=processed_articles
    )

    rendered_html_path = os.path.join(build_dir, "weekly_magazine.html")
    with open(rendered_html_path, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    # 6. Generate PDF using Playwright
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
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
        )
        browser.close()

    print(f"✅ Generated Weekly Magazine: {output_pdf_path}")

if __name__ == "__main__":
    compile_weekly_magazine()
