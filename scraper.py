import json
import re
import subprocess
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from readability import Document
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
TODAY_DATE = datetime.now(IST).date()

HEADERS = [
    "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "-H", "Accept-Language: en-US,en;q=0.9",
    "-H", "Sec-Fetch-Dest: document",
    "-H", "Sec-Fetch-Mode: navigate",
    "-H", "Sec-Fetch-Site: none",
    "-H", "Sec-Fetch-User: ?1",
    "-H", "Upgrade-Insecure-Requests: 1"
]

def fetch_html(url, use_jina_fallback=True):
    """Fetches URL using cURL, falling back to Jina Reader if blocked by Cloudflare."""
    try:
        cmd = ["curl", "-sL", "--compressed", "-m", "20"] + HEADERS + [url]
        result = subprocess.run(cmd, capture_output=True, timeout=25)
        html = result.stdout.decode('utf-8', errors='ignore')

        # Detect Cloudflare challenge / block
        is_blocked = (
            not html.strip()
            or "Just a moment..." in html
            or "Attention Required! | Cloudflare" in html
            or "<title>Access Denied</title>" in html
            or "Cloudflare Ray ID" in html
        )

        if is_blocked and use_jina_fallback:
            print(f"⚠️ Direct request blocked by firewall for {url}. Routing via Jina Reader proxy...")
            jina_url = f"https://r.jina.ai/{url}"
            cmd_jina = ["curl", "-sL", "-m", "25", "-H", "X-Return-Format: html", jina_url]
            res_jina = subprocess.run(cmd_jina, capture_output=True, timeout=30)
            html = res_jina.stdout.decode('utf-8', errors='ignore')

        return html
    except Exception as e:
        print(f"⚠️ Fetch error for {url}: {e}")
        return ""

def extract_indian_express_body(soup, raw_html=""):
    """Extracts text from Indian Express JSON-LD metadata, Jina markdown, or DOM."""
    # Method 1: Check JSON-LD metadata schema
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get('@type') in ['NewsArticle', 'OpinionNewsArticle', 'Article'] and 'articleBody' in item:
                    return item['articleBody'].strip()
        except Exception:
            continue

    # Method 2: DOM container selectors
    selectors = [
        '#pcl-full-content',
        '.story-details',
        '.full-details',
        'div[itemprop="articleBody"]',
        '.story_details'
    ]
    for selector in selectors:
        container = soup.select_one(selector)
        if container:
            paras = [
                p.get_text(strip=True) for p in container.find_all('p')
                if p.get_text(strip=True) and not p.find_parent('div', class_=re.compile(r'ad|social|newsletter', re.I))
            ]
            if len(paras) >= 2:
                return "\n\n".join(paras)

    # Method 3: Fallback to plain paragraphs if fetched via proxy
    all_paras = [p.get_text(strip=True) for p in soup.find_all('p') if len(p.get_text(strip=True)) > 40]
    if len(all_paras) >= 3:
        return "\n\n".join(all_paras)

    return ""

def apply_speedreader(url, newspaper):
    """Extracts clean title, body passage, and reading time."""
    html = fetch_html(url)
    if not html:
        return "", "", ""

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Determine Title
        doc = Document(html)
        raw_title = doc.title() or (soup.find('h1').get_text(strip=True) if soup.find('h1') else "")
        clean_title = raw_title.split(' - ')[0].split(' | ')[0].strip()

        # Readability extraction
        summary_soup = BeautifulSoup(doc.summary(), 'html.parser')
        passage = summary_soup.get_text(separator='\n\n', strip=True)

        # Fallback if readability was stripped by custom CMS tags
        if len(passage) < 300:
            if newspaper == "The Indian Express":
                fallback_passage = extract_indian_express_body(soup, html)
                if len(fallback_passage) >= 300:
                    passage = fallback_passage

        words = len(passage.split())
        r_time = f"{max(1, round(words / 200))} min read"

        return clean_title, passage, r_time
    except Exception as e:
        print(f"⚠️ Parser error for {url}: {e}")
        return "", "", ""

def get_hindu_editorials():
    print("📰 Visiting The Hindu Editorial Section...")
    html = fetch_html("https://www.thehindu.com/opinion/editorial/")
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
        title, passage, r_time = apply_speedreader(link, "The Hindu")
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
    html = fetch_html("https://indianexpress.com/section/opinion/editorials/")
    
    # Extract editorial article URLs using regex
    found_links = re.findall(r'https?://indianexpress\.com/article/opinion/editorials/[a-zA-Z0-9\-_]+/', html)
    links = []
    for link in found_links:
        if link not in links and not link.endswith('/editorials/'):
            links.append(link)

    print(f"  ℹ️ Found {len(links)} Indian Express editorial candidate links.")

    articles = []
    for link in links[:5]:
        title, passage, r_time = apply_speedreader(link, "The Indian Express")
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