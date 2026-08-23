import json
import re
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from readability import Document
from curl_cffi import requests

IST = timezone(timedelta(hours=5, minutes=30))
TODAY_DATE = datetime.now(IST).date()

# Reusable session with browser TLS/JA3 fingerprint impersonation
session = requests.Session(impersonate="chrome124")

import os
from urllib.parse import quote_plus

SCRAPINGANT_KEY = os.getenv("SCRAPINGANT_API_KEY")

def fetch_page(url):
    """Fetches full page content; routes Indian Express through ScrapingAnt to bypass Cloudflare 403."""
    if "indianexpress.com" in url and SCRAPINGANT_KEY:
        # browser=false uses 1 credit/request; set browser=true if JS execution is needed
        target_url = f"https://api.scrapingant.com/v2/general?url={quote_plus(url)}&x-api-key={SCRAPINGANT_KEY}&browser=false"
    else:
        target_url = url

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    
    try:
        response = session.get(target_url, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.text
        print(f"⚠️ Failed to fetch {url} (Status: {response.status_code})")
        return ""
    except Exception as e:
        print(f"⚠️ Fetch error for {url}: {e}")
        return ""

def extract_indian_express_content(html):
    """Extracts pristine article body from JSON-LD schema or content containers."""
    soup = BeautifulSoup(html, 'html.parser')
    
    # 1. Extract from JSON-LD metadata (immune to layout changes and ads)
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get('@type') in ['NewsArticle', 'OpinionNewsArticle', 'Article'] and 'articleBody' in item:
                    body = item['articleBody'].strip()
                    if len(body) > 300:
                        return body
        except Exception:
            continue

    # 2. Extract from story containers
    selectors = ['#pcl-full-content', '.story-details', '.full-details', 'div[itemprop="articleBody"]']
    for selector in selectors:
        container = soup.select_one(selector)
        if container:
            paras = [
                p.get_text(strip=True) for p in container.find_all('p')
                if p.get_text(strip=True) and not p.find_parent('div', class_=re.compile(r'ad|social|newsletter', re.I))
            ]
            if len(paras) >= 2:
                return "\n\n".join(paras)

    # 3. Readability fallback
    doc = Document(html)
    summary_soup = BeautifulSoup(doc.summary(), 'html.parser')
    return summary_soup.get_text(separator='\n\n', strip=True)

def apply_speedreader(url, newspaper="The Indian Express"):
    """Extracts clean title, body text, and estimated reading time."""
    html = fetch_page(url)
    if not html:
        return "", "", ""

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract title
        h1 = soup.find('h1')
        raw_title = h1.get_text(strip=True) if h1 else Document(html).title()
        clean_title = raw_title.split(' - ')[0].split(' | ')[0].strip()

        if newspaper == "The Indian Express":
            passage = extract_indian_express_content(html)
        else:
            doc = Document(html)
            summary_soup = BeautifulSoup(doc.summary(), 'html.parser')
            passage = summary_soup.get_text(separator='\n\n', strip=True)

        words = len(passage.split())
        r_time = f"{max(1, round(words / 200))} min read"
        return clean_title, passage, r_time
    except Exception as e:
        print(f"⚠️ Parsing error for {url}: {e}")
        return "", "", ""

def get_hindu_editorials():
    print("📰 Visiting The Hindu Editorial Section...")
    html = fetch_page("https://www.thehindu.com/opinion/editorial/")
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
            print(f"  ✓ Fetched: {title[:55]}...")
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
    html = fetch_page("https://indianexpress.com/section/opinion/editorials/")
    soup = BeautifulSoup(html, 'html.parser')

    links = []
    # Match both absolute and relative editorial links
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('/'):
            href = "https://indianexpress.com" + href
        if '/article/opinion/editorials/' in href and href != "https://indianexpress.com/section/opinion/editorials/" and href not in links:
            links.append(href)

    # Regex fallback if markup changes
    if not links:
        found = re.findall(r'https://indianexpress\.com/article/opinion/editorials/[a-zA-Z0-9\-_]+/?', html)
        for link in found:
            clean_link = link.rstrip('/') + '/'
            if clean_link not in links and clean_link != "https://indianexpress.com/article/opinion/editorials/":
                links.append(clean_link)

    print(f"  ℹ️ Found {len(links)} Indian Express editorial candidate links.")

    candidates = []
    # Fetch all published candidate editorials (checking top 3-4 links)
    for link in links[:4]:
        title, passage, r_time = apply_speedreader(link, "The Indian Express")
        if passage and len(passage) > 300:
            words = len(passage.split())
            print(f"  ✓ Fetched: {title[:45]}... ({words} words)")
            candidates.append({
                "newspaper": "The Indian Express",
                "title": title,
                "link": link,
                "timestamp": str(TODAY_DATE),
                "reading_time": r_time,
                "passage": passage,
                "word_count": words
            })

    # Sort all fetched candidates by word count (highest to lowest)
    candidates.sort(key=lambda item: item["word_count"], reverse=True)

    # Keep only the top 2 longest articles
    selected_articles = candidates[:2]

    # Remove the temporary word_count key before returning
    for article in selected_articles:
        article.pop("word_count", None)

    return selected_articles

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