import os
import json
import glob
import requests
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
        if "one-word" in cat or "one word" in cat:
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

def send_to_telegram(pdf_path, ist_date_short, editorial_titles):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("⚠️ Telegram BOT_TOKEN or ADMIN_CHAT_ID missing. Skipping Telegram delivery.")
        return

    # Build formatted numbered lines for the quote box
    quote_lines = [f"{idx:02d} {title}" for idx, title in enumerate(editorial_titles, start=1)]
    quote_content = "\n".join(quote_lines)

    # Telegram HTML caption with expandable blockquote
    caption = (
        f"📚 <b>Weekly Vocab Lab Compilation ({ist_date_short})</b>\n"
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
        print("🚀 Successfully delivered Weekly Magazine PDF to Telegram!")
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

    # 1. Read all JSON backup files sorted chronologically
    json_files = sorted(glob.glob(os.path.join(backups_dir, "*.json")))
    if not json_files:
        print(f"⚠️ No backup JSON files found in: {backups_dir}")
        return

    aggregated_editorials = []

    # 2. Extract editorials from Monday to Saturday files
    for file_path in json_files:
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                daily_data = json.load(f)
                aggregated_editorials.extend(daily_data.get("editorials", []))
            except json.JSONDecodeError:
                print(f"⚠️ Skipping corrupted JSON: {file_path}")

    # 3. Limit to a maximum of 25 editorials
    aggregated_editorials = aggregated_editorials[:25]

    # 4. Format vocabulary for template rendering
    processed_articles = []
    editorial_titles = []
    for art in aggregated_editorials:
        title_clean = art.get("title", "Untitled Editorial")
        editorial_titles.append(title_clean)
        
        vocab_list = art.get("editorial_vocabulary", [])
        categorized_vocab = categorize_vocabulary(vocab_list)
        
        processed_articles.append({
            "title": title_clean,
            "newspaper": art.get("newspaper", "Editorial"),
            "timestamp": art.get("timestamp", ""),
            "categorized_vocab": categorized_vocab
        })

    # 5. Render Jinja2 template
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    ist_time = datetime.now(ist_offset)
    edition_date = ist_time.strftime("%B %d, %Y")
    ist_date_short = ist_time.strftime("%d %b %Y")

    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("weekly_template.html")
    
    rendered_html = template.render(
        edition_date=edition_date,
        editorials=processed_articles
    )

    rendered_html_path = os.path.join(build_dir, "weekly_magazine.html")
    with open(rendered_html_path, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    # 6. Generate PDF via Playwright
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

    # 7. Dispatch to Telegram Admin
    send_to_telegram(output_pdf_path, ist_date_short, editorial_titles)

if __name__ == "__main__":
    compile_weekly_magazine()
