import json
import re
import subprocess
from bs4 import BeautifulSoup
from readability import Document
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
TODAY_DATE = datetime.now(IST).date()

HEADERS = [
    "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "-H", "Accept-Language: en-US,en;q=0.9"
]

def fetch_hindu_html(url):
    """Direct fetch for The Hindu (works reliably on runner IPs)."""
    try:
        cmd = ["curl", "-sL", "--compressed", "-m", "20"] + HEADERS + [url]
        result = subprocess.run(cmd, capture_output=True, timeout=25)
        return result.stdout.decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"⚠️ Hindu fetch error for {url}: {e}")
        return ""

def fetch_jina_markdown(url):
    """Fetches via Jina Reader edge proxy to bypass Cloudflare bot protection."""
    try:
        jina_url = f"https://r.jina.ai/{url}"
        cmd = ["curl", "-sL", "-m", "25", jina_url]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        return result.stdout.decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"⚠️ Jina fetch error for {url}: {e}")
        return ""

def parse_jina_article(raw_markdown):
    """Parses clean title and body text from Jina reader output."""
    if not raw_markdown or "Just a moment..." in raw_markdown:
        return "", "", ""

    lines = raw_markdown.splitlines()
    title = ""
    content_lines = []
    is_content = False

    for line in lines:
        if line.startswith("Title:"):
            title = line.replace("Title:", "").strip()
        elif "Markdown Content:" in line:
            is_content = True
            continue
        elif is_content:
            # Filter out boilerplate, social sharing, and ad footer lines
            lowered = line.lower()
            if any(term in lowered for term in ["join our telegram", "click here to join", "ie_social", "express investigation"]):
                continue
            content_lines.append(line)

    passage = "\n".join(content_lines).strip()
    passage = re.sub(r'\n{3,}', '\n\n', passage)

    if not title and passage:
        title = passage.splitlines()[0].strip('# ')

    words = len(passage.split())
    r_time = f"{max(1, round(words / 200))} min read"
    return title, passage, r_time

def apply_readability(html):
    """Applies readability engine to raw HTML for The Hindu."""
    try:
        doc = Document(html)
        clean_title = doc.title().split(' - ')[0].split(' | ')[0].strip()
        summary_soup = BeautifulSoup(doc.summary(), 'html.parser')
        passage = summary_soup.get_text(separator='\n\n', strip=True)

        words = len(passage.split())
        r_time = f"{max(1, round(words / 200))} min read"
        return clean_title, passage, r_time
    except Exception as e:
        print(f"⚠️ Readability error: {e}")
        return "", "", ""

def get_hindu_editorials():
    print("📰 Visiting The Hindu Editorial Section...")
    html = fetch_hindu_html("https://www.thehindu.com/opinion/editorial/")
    soup = BeautifulSoup(html, 'html.parser')

    links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('/'):
            href = "https://www.thehindu.com" + href
        if '/opinion/editorial/' in href and href != "https://www.thehindu.com/opinion/editorial/" and href not in links:
            links.append(href)

    articles = []
    for link in links[:5]:
        article_html = fetch_hindu_html(link)
        title, passage, r_time = apply_readability(article_html)
        if passage and len(passage) > 300:
            print(f"  ✓ Fetched: {title[:50]}...")
            articles.append({
                "newspaper": "The Hindu",
                "title": title,
                "link": link,
                "timestamp": str(TODAY_DATE),
                "reading_time": r_time,
                "passage": passage
            })
        if len(articles) >= 2:
            break

    return articles

def get_indian_express_editorials():
    print("📰 Visiting The Indian Express Editorial Section...")
    # Fetch section listing through Jina Reader to avoid Cloudflare challenge
    section_md = fetch_jina_markdown("https://indianexpress.com/section/opinion/editorials/")

    # Match all full editorial article URLs
    found_urls = re.findall(r'https://indianexpress\.com/article/opinion/editorials/[a-zA-Z0-9\-_]+/?', section_md)
    
    links = []
    for url in found_urls:
        clean_url = url.rstrip('/') + '/'
        if clean_url != "https://indianexpress.com/article/opinion/editorials/" and clean_url not in links:
            links.append(clean_url)

    print(f"  ℹ️ Found {len(links)} Indian Express editorial candidate links.")

    articles = []
    for link in links[:5]:
        raw_md = fetch_jina_markdown(link)
        title, passage, r_time = parse_jina_article(raw_md)
        if passage and len(passage) > 300:
            print(f"  ✓ Fetched: {title[:50]}...")
            articles.append({
                "newspaper": "The Indian Express",
                "title": title,
                "link": link,
                "timestamp": str(TODAY_DATE),
                "reading_time": r_time,
                "passage": passage
            })
        if len(articles) >= 2:
            break

    return articles

def run():
    print(f"🚀 Starting Speedreader pipeline for {TODAY_DATE} (IST)...")

    all_editorials = []
    all_editorials.extend(get_hindu_editorials())
    all_editorials.extend(get_indian_express_editorials())

    output = {
        "date_scraped": str(TODAY_DATE),
        "total_articles": len(all_editorials),
        "editorials": all_editorials
    }

    with open('today_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

    print(f"✅ Successfully compiled {len(all_editorials)} editorials into today_editorials.json")

if __name__ == "__main__":
    run()