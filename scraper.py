import os
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from readability import Document
from curl_cffi import requests

IST = timezone(timedelta(hours=5, minutes=30))
TODAY_DATE = datetime.now(IST).date()

# ScrapingAnt API Key from GitHub Actions Secrets
SCRAPINGANT_KEY = os.getenv("SCRAPINGANT_API_KEY")

session = requests.Session(impersonate="chrome124")

def fetch_page(url):
    """Fetches full page content; routes Indian Express via ScrapingAnt to bypass Cloudflare 403."""
    if "indianexpress.com" in url and SCRAPINGANT_KEY:
        target_url = f"https://api.scrapingant.com/v2/general?url={quote_plus(url)}&x-api-key={SCRAPINGANT_KEY}&browser=false"
    else:
        target_url = url

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
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

def extract_clean_paragraphs(container):
    """Extracts text from <p> tags while preventing inline links from causing extra line breaks."""
    for unwanted in container.find_all(['script', 'style', 'aside', 'figure', 'button', 'iframe']):
        unwanted.decompose()
    for ad in container.find_all(class_=re.compile(r'ad-|ad_|newsletter|social|also-read|comment', re.I)):
        ad.decompose()

    paragraphs = []
    for p in container.find_all('p'):
        # Normalize internal whitespace so inline <a> tags merge seamlessly into text
        text = re.sub(r'\s+', ' ', p.get_text()).strip()
        
        # Filter out empty text, timestamps, and Google source labels
        if not text or len(text) < 25:
            continue
        if re.match(r'^(published|updated|first published)\s*[-:]', text, re.I):
            continue
        if "Add as a preferred source" in text:
            continue

        paragraphs.append(text)

    return "\n\n".join(paragraphs)

def extract_indian_express_content(html):
    """Extracts Indian Express editorial paragraphs preserving original paragraph breaks."""
    soup = BeautifulSoup(html, 'html.parser')

    # 1. Prefer story containers to keep true paragraph structure
    selectors = ['#pcl-full-content', '.story-details', '.full-details', 'div[itemprop="articleBody"]']
    for selector in selectors:
        container = soup.select_one(selector)
        if container:
            text = extract_clean_paragraphs(container)
            if len(text) > 300:
                return text

    # 2. Fallback to JSON-LD metadata
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

    # 3. Readability fallback
    doc = Document(html)
    summary_soup = BeautifulSoup(doc.summary(), 'html.parser')
    return extract_clean_paragraphs(summary_soup)

def extract_hindu_content(html):
    """Extracts clean editorial paragraphs from The Hindu without mid-sentence breaks."""
    soup = BeautifulSoup(html, 'html.parser')

    container = soup.select_one('.articlebodycontent, div[itemprop="articleBody"], .storycontent, .content')
    if container:
        text = extract_clean_paragraphs(container)
        if len(text) > 300:
            return text

    doc = Document(html)
    summary_soup = BeautifulSoup(doc.summary(), 'html.parser')
    return extract_clean_paragraphs(summary_soup)

def apply_speedreader(url, newspaper="The Indian Express"):
    """Extracts clean title, proper paragraphs, and estimated reading time."""
    html = fetch_page(url)
    if not html:
        return "", "", ""

    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Extract and clean title
        h1 = soup.find('h1')
        if h1:
            for badge in h1.find_all(['span', 'div', 'a']):
                badge.decompose()
            raw_title = h1.get_text(strip=True)
        else:
            raw_title = Document(html).title()

        clean_title = raw_title.split(' - ')[0].split(' | ')[0].strip()
        # Clean glued or prepended "Opinion" / "Editorial"
        clean_title = re.sub(r'^Opinion([A-Z])', r'\1', clean_title)
        clean_title = re.sub(r'^(Opinion|Editorial)\s*:?\s*', '', clean_title, flags=re.IGNORECASE).strip()

        # 2. Extract passage without broken lines
        if newspaper == "The Indian Express":
            passage = extract_indian_express_content(html)
        else:
            passage = extract_hindu_content(html)

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
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('/'):
            href = "https://indianexpress.com" + href
        if '/article/opinion/editorials/' in href and href != "https://indianexpress.com/section/opinion/editorials/" and href not in links:
            links.append(href)

    if not links:
        found = re.findall(r'https://indianexpress\.com/article/opinion/editorials/[a-zA-Z0-9\-_]+/?', html)
        for link in found:
            clean_link = link.rstrip('/') + '/'
            if clean_link not in links and clean_link != "https://indianexpress.com/article/opinion/editorials/":
                links.append(clean_link)

    print(f"  ℹ️ Found {len(links)} Indian Express editorial candidate links.")

    candidates = []
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

    # Sort descending by word count and keep only the top 2 longest articles
    candidates.sort(key=lambda item: item["word_count"], reverse=True)
    selected_articles = candidates[:2]

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