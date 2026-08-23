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

def fetch_html_curl(url):
    """Fetches URL content using cURL with complete browser headers."""
    try:
        cmd = ["curl", "-sL", "--compressed"] + HEADERS + [url]
        result = subprocess.run(cmd, capture_output=True, timeout=25)
        html = result.stdout.decode('utf-8', errors='ignore')
        
        # Fallback to alternative public CORS/proxy if blocked by Cloudflare
        if not html or "Just a moment..." in html or "<title>Access Denied</title>" in html:
            print(f"⚠️ Direct request blocked for {url}. Attempting proxy tunnel...")
            proxy_url = f"https://corsproxy.io/?{url}"
            proxy_cmd = ["curl", "-sL", "--compressed"] + HEADERS + [proxy_url]
            proxy_res = subprocess.run(proxy_cmd, capture_output=True, timeout=25)
            html = proxy_res.stdout.decode('utf-8', errors='ignore')
            
        return html
    except Exception as e:
        print(f"⚠️ Fetch error for {url}: {e}")
        return ""

def extract_indian_express_body(soup):
    """Directly extracts paragraph text from Indian Express DOM or JSON-LD metadata."""
    # Method 1: Check JSON-LD schema (contains pristine article text)
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get('@type') in ['NewsArticle', 'OpinionNewsArticle', 'Article'] and 'articleBody' in item:
                    return item['articleBody'].strip()
        except Exception:
            continue

    # Method 2: Common Indian Express content containers
    selectors = [
        '#pcl-full-content',
        '.story-details',
        '.full-details',
        '.heading-part ~ div',
        'div[itemprop="articleBody"]'
    ]
    for selector in selectors:
        container = soup.select_one(selector)
        if container:
            paragraphs = [
                p.get_text(strip=True) for p in container.find_all('p') 
                if p.get_text(strip=True) and not p.find_parent('div', class_=re.compile(r'ad|social|newsletter', re.I))
            ]
            if len(paragraphs) >= 2:
                return "\n\n".join(paragraphs)

    return ""

def apply_speedreader(url, newspaper="The Indian Express"):
    """Extracts clean title, article body, and reading time."""
    html = fetch_html_curl(url)
    if not html:
        return "", "", ""
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        passage = ""
        
        # Primary: Readability engine
        doc = Document(html)
        raw_title = doc.title() or (soup.find('h1').get_text(strip=True) if soup.find('h1') else "")
        clean_title = raw_title.split(' - ')[0].split(' | ')[0].strip()
        
        summary_soup = BeautifulSoup(doc.summary(), 'html.parser')
        passage = summary_soup.get_text(separator='\n\n', strip=True)
        
        # Fallback: Targeted DOM/JSON-LD parsing if Readability fails
        if len(passage) < 300 and newspaper == "The Indian Express":
            fallback_passage = extract_indian_express_body(soup)
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
    html = fetch_html_curl("https://www.thehindu.com/opinion/editorial/")
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
    print("📰 Visiting The Indian Express Editorial Feed...")
    # Using the official RSS feed avoids dynamic rendering and bot challenge roadblocks
    feed_url = "https://indianexpress.com/section/opinion/editorials/feed/"
    feed_xml = fetch_html_curl(feed_url)
    
    links = []
    if feed_xml:
        try:
            root = ET.fromstring(feed_xml)
            for item in root.findall('.//item'):
                link = item.find('link')
                if link is not None and link.text and link.text not in links:
                    links.append(link.text.strip())
        except Exception:
            pass

    # Fallback to category HTML if RSS parsing encounters an error
    if not links:
        html = fetch_html_curl("https://indianexpress.com/section/opinion/editorials/")
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('/'):
                href = "https://indianexpress.com" + href
            if '/article/opinion/editorials/' in href and href not in links:
                links.append(href)
            
    articles = []
    for link in links[:5]:
        title, passage, r_time = apply_speedreader(link, "The Indian Express")
        if passage and len(passage) > 300:
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