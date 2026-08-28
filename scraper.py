import os
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from readability import Document
from curl_cffi import requests

IST = timezone(timedelta(hours=5, minutes=30))
NOW_IST = datetime.now(IST)
TODAY_DATE = NOW_IST.date()

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

def extract_article_datetime(html):
    """Extracts exact publication datetime in IST to capture accurate publication timestamps."""
    soup = BeautifulSoup(html, 'html.parser')
    
    # 1. Check Meta tags
    for meta in soup.find_all('meta'):
        prop = meta.get('property', '') or meta.get('name', '') or meta.get('itemprop', '')
        if prop in ['article:published_time', 'publish-date', 'datePublished', 'og:published_time']:
            content = meta.get('content', '')
            if content:
                try:
                    return datetime.fromisoformat(content.replace('Z', '+00:00')).astimezone(IST)
                except Exception:
                    match = re.search(r'(\d{4}-\d{2}-\d{2})', content)
                    if match:
                        d = datetime.strptime(match.group(1), "%Y-%m-%d").date()
                        return datetime(d.year, d.month, d.day, 6, 0, tzinfo=IST)

    # 2. Check JSON-LD metadata
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            items = data if isinstance(data, list) else [data]
            for item in items:
                if 'datePublished' in item:
                    date_str = str(item['datePublished'])
                    try:
                        return datetime.fromisoformat(date_str.replace('Z', '+00:00')).astimezone(IST)
                    except Exception:
                        match = re.search(r'(\d{4}-\d{2}-\d{2})', date_str)
                        if match:
                            d = datetime.strptime(match.group(1), "%Y-%m-%d").date()
                            return datetime(d.year, d.month, d.day, 6, 0, tzinfo=IST)
        except Exception:
            continue

    return None

def format_published_time(pub_dt):
    """Formats datetime object to standard readable string (e.g., 'August 28, 2026 07:39 AM IST')."""
    if pub_dt:
        return pub_dt.strftime("%B %d, %Y %I:%M %p IST")
    return f"{TODAY_DATE.strftime('%B %d, %Y')} IST"

def is_todays_edition(pub_dt):
    """Checks if article belongs to today's morning edition (within 20h or published after 5 PM yesterday)."""
    if not pub_dt:
        return True
    
    age_hours = (NOW_IST - pub_dt).total_seconds() / 3600.0
    if 0 <= age_hours <= 20:
        return True
    if pub_dt.date() == TODAY_DATE:
        return True
    return False

def extract_clean_paragraphs(container):
    """Extracts text from <p> tags while keeping inline links smoothly inside sentences."""
    for unwanted in container.find_all(['script', 'style', 'aside', 'figure', 'button', 'iframe']):
        unwanted.decompose()
    for ad in container.find_all(class_=re.compile(r'ad-|ad_|newsletter|social|also-read|comment', re.I)):
        ad.decompose()

    paragraphs = []
    for p in container.find_all('p'):
        text = re.sub(r'\s+', ' ', p.get_text()).strip()
        
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

    selectors = ['#pcl-full-content', '.story-details', '.full-details', 'div[itemprop="articleBody"]']
    for selector in selectors:
        container = soup.select_one(selector)
        if container:
            text = extract_clean_paragraphs(container)
            if len(text) > 300:
                return text

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
    """Extracts clean title, proper paragraphs, estimated reading time, and publish datetime."""
    html = fetch_page(url)
    if not html:
        return "", "", "", None

    try:
        pub_dt = extract_article_datetime(html)
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Clean Title
        h1 = soup.find('h1')
        if h1:
            for badge in h1.find_all(['span', 'div', 'a']):
                badge.decompose()
            raw_title = h1.get_text(strip=True)
        else:
            raw_title = Document(html).title()

        clean_title = raw_title.split(' - ')[0].split(' | ')[0].strip()
        clean_title = re.sub(r'^Opinion([A-Z])', r'\1', clean_title)
        clean_title = re.sub(r'^(Opinion|Editorial)\s*:?\s*', '', clean_title, flags=re.IGNORECASE).strip()

        # 2. Extract Passage
        if newspaper == "The Indian Express":
            passage = extract_indian_express_content(html)
        else:
            passage = extract_hindu_content(html)

        words = len(passage.split())
        r_time = f"{max(1, round(words / 200))} min read"
        return clean_title, passage, r_time, pub_dt
    except Exception as e:
        print(f"⚠️ Parsing error for {url}: {e}")
        return "", "", "", None

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
    for link in links[:6]:
        title, passage, r_time, pub_dt = apply_speedreader(link, "The Hindu")
        
        if pub_dt and not is_todays_edition(pub_dt):
            print(f"  ⏭️ Skipping older Hindu editorial ({pub_dt.strftime('%Y-%m-%d %H:%M')}): {title[:40]}...")
            continue

        if passage and len(passage) > 300:
            print(f"  ✓ Fetched: {title[:55]}...")
            articles.append({
                "newspaper": "The Hindu",
                "title": title,
                "link": link,
                "timestamp": str(TODAY_DATE),
                "published_at": format_published_time(pub_dt),
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
    consecutive_older = 0

    for link in links:
        if consecutive_older >= 2 and len(candidates) >= 1:
            break

        title, passage, r_time, pub_dt = apply_speedreader(link, "The Indian Express")
        
        if pub_dt and not is_todays_edition(pub_dt):
            consecutive_older += 1
            print(f"  ⏭️ Skipping older Express editorial ({pub_dt.strftime('%Y-%m-%d %H:%M')}): {title[:40]}...")
            continue

        if passage and len(passage) > 300:
            consecutive_older = 0
            words = len(passage.split())
            print(f"  ✓ Fetched: {title[:45]}... ({words} words)")
            candidates.append({
                "newspaper": "The Indian Express",
                "title": title,
                "link": link,
                "timestamp": str(TODAY_DATE),
                "published_at": format_published_time(pub_dt),
                "reading_time": r_time,
                "passage": passage,
                "word_count": words
            })

    # Sort today's candidates by length and select top 2
    candidates.sort(key=lambda item: item["word_count"], reverse=True)
    selected_articles = candidates[:2]

    for article in selected_articles:
        article.pop("word_count", None)

    return selected_articles

# At the end of scraper.py:
def run():
    print(f"🚀 Starting Speedreader pipeline for {TODAY_DATE} (IST)...")

    all_editorials = []
    all_editorials.extend(get_hindu_editorials())
    all_editorials.extend(get_indian_express_editorials())

    if len(all_editorials) == 0:
        raise RuntimeError(f"Scraper completed but found 0 valid editorials for {TODAY_DATE}.")

    output = {
        "date_scraped": str(TODAY_DATE),
        "total_articles": len(all_editorials),
        "editorials": all_editorials
    }

    with open('today_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

    print(f"✅ Successfully compiled {len(all_editorials)} editorials into today_editorials.json")

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        admin_chat_id = os.getenv("ADMIN_CHAT_ID")
        if bot_token and admin_chat_id:
            try:
                requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                    "chat_id": admin_chat_id,
                    "text": f"🚨 **STEP 1 FAILED (Editorial Scraper):**\n\n**Error:**\n`{e}`",
                    "parse_mode": "Markdown"
                })
            except Exception:
                pass
        print(f"Fatal scraper error: {e}")
        sys.exit(1)