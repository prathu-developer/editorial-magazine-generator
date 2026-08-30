import os
import sys
import time
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, quote_plus
from bs4 import BeautifulSoup
from readability import Document
from curl_cffi import requests

IST = timezone(timedelta(hours=5, minutes=30))
NOW_IST = datetime.now(IST)
TODAY_DATE = NOW_IST.date()

# Optional proxy key for Cloudflare/protected sites
SCRAPINGANT_KEY = os.getenv("SCRAPINGANT_API_KEY")

session = requests.Session(impersonate="chrome124")

def fetch_page(url, max_retries=3, timeout=60, use_proxy=False):
    """Fetches full page content using curl_cffi with optional ScrapingAnt fallback."""
    if use_proxy and SCRAPINGANT_KEY:
        target_url = f"https://api.scrapingant.com/v2/general?url={quote_plus(url)}&x-api-key={SCRAPINGANT_KEY}&browser=false"
    else:
        target_url = url

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(target_url, headers=headers, timeout=timeout)
            if response.status_code == 200 and len(response.text) > 500:
                return response.text
            print(f"  ⚠️ [Attempt {attempt}/{max_retries}] Status {response.status_code} for {url}")
        except Exception as e:
            print(f"  ⚠️ [Attempt {attempt}/{max_retries}] Fetch error for {url}: {e}")
        
        if attempt < max_retries:
            time.sleep(2)

    return ""

def extract_article_datetime(html):
    """Extracts exact publication datetime in IST from OpenGraph or JSON-LD."""
    soup = BeautifulSoup(html, 'html.parser')
    
    # 1. Meta tags
    for meta in soup.find_all('meta'):
        prop = meta.get('property', '') or meta.get('name', '') or meta.get('itemprop', '')
        if prop in ['article:published_time', 'publish-date', 'datePublished', 'og:published_time', 'pubdate']:
            content = meta.get('content', '')
            if content:
                try:
                    return datetime.fromisoformat(content.replace('Z', '+00:00')).astimezone(IST)
                except Exception:
                    match = re.search(r'(\d{4}-\d{2}-\d{2})', content)
                    if match:
                        d = datetime.strptime(match.group(1), "%Y-%m-%d").date()
                        return datetime(d.year, d.month, d.day, 6, 0, tzinfo=IST)

    # 2. JSON-LD metadata
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
    """Formats datetime object into readable string."""
    if pub_dt:
        return pub_dt.strftime("%B %d, %Y %I:%M %p IST")
    return f"{TODAY_DATE.strftime('%B %d, %Y')} IST"

def is_recent_edition(pub_dt, max_hours=36):
    """Checks if the article was published recently (within 36 hours)."""
    if not pub_dt:
        return True
    age_hours = (NOW_IST - pub_dt).total_seconds() / 3600.0
    return 0 <= age_hours <= max_hours

def extract_clean_paragraphs(container):
    """Sanitizes text and preserves clean paragraph structures."""
    if not container:
        return ""
    
    for unwanted in container.find_all(['script', 'style', 'aside', 'figure', 'button', 'iframe', 'form', 'nav', 'svg']):
        unwanted.decompose()
    for ad in container.find_all(class_=re.compile(r'ad-|ad_|newsletter|social|also-read|comment|widget|promo|related', re.I)):
        ad.decompose()

    paragraphs = []
    for p in container.find_all(['p', 'div.story-paragraph']):
        text = re.sub(r'\s+', ' ', p.get_text()).strip()
        if not text or len(text) < 25:
            continue
        if re.match(r'^(published|updated|first published|read also|also read|subscribe to)\s*[-:]', text, re.I):
            continue
        if "Add as a preferred source" in text or "Follow us on" in text:
            continue
        paragraphs.append(text)

    return "\n\n".join(paragraphs)

def extract_content(html, newspaper):
    """Extracts article body based on source-specific selectors with readability fallback."""
    soup = BeautifulSoup(html, 'html.parser')

    selectors_by_source = {
        "The Indian Express": ['#pcl-full-content', '.story-details', '.full-details', 'div[itemprop="articleBody"]'],
        "The Hindu": ['.articlebodycontent', 'div[itemprop="articleBody"]', '.storycontent', '.content'],
        "The Hindu BusinessLine": ['.articlebodycontent', 'div[itemprop="articleBody"]', '.contentbody', '.storycontent', '.paywall'],
        "Finshots": ['.post-content', 'article.post', '.story-content'],
        "Financial Express": ['.wp-block-post-content', '.story-details', 'div[itemprop="articleBody"]', '.main-story-content'],
        "Hindustan Times": ['.detail', '.storyDetails', 'div[itemprop="articleBody"]', '.story-content'],
        "Deccan Herald": ['.story-element-text', 'div[itemprop="articleBody"]', '.article-content', '.content-wrapper'],
        "The Daily Pioneer": ['.story-content', '.entry-content', '.post-content', '.news-detail'],
        "The Statesman": ['.entry-content', '.post-content', 'div[itemprop="articleBody"]', '.article-description'],
        "The Telegraph": ['.story-content', '.article-body', 'div[itemprop="articleBody"]', '#content-area'],
        "The Guardian": ['div[data-gu-name="body"]', '#maincontent', 'article', '.article-body-commercial-selector'],
        "Al Jazeera": ['.wysiwyg', 'div.article__sub-header', 'div.article-content', '.article-body'],
        "ThePrint": ['.td-post-content', '.entry-content', 'div[itemprop="articleBody"]'],
        "The Wire": ['.post-content', '.entry-content', 'div[itemprop="articleBody"]', '.wire-content']
    }

    selectors = selectors_by_source.get(newspaper, ['div[itemprop="articleBody"]', 'article', '.entry-content'])
    for selector in selectors:
        container = soup.select_one(selector)
        if container:
            text = extract_clean_paragraphs(container)
            if len(text) > 250:
                return text

    # JSON-LD fallback
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get('@type') in ['NewsArticle', 'OpinionNewsArticle', 'Article'] and 'articleBody' in item:
                    body = item['articleBody'].strip()
                    if len(body) > 250:
                        return body
        except Exception:
            continue

    # Readability fallback
    doc = Document(html)
    summary_soup = BeautifulSoup(doc.summary(), 'html.parser')
    return extract_clean_paragraphs(summary_soup)

def parse_article(url, newspaper, use_proxy=False):
    """Downloads and extracts full metadata and passage for a single editorial."""
    html = fetch_page(url, use_proxy=use_proxy)
    if not html:
        return None

    try:
        pub_dt = extract_article_datetime(html)
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract title
        h1 = soup.find('h1')
        if h1:
            for badge in h1.find_all(['span', 'div', 'a']):
                badge.decompose()
            raw_title = h1.get_text(strip=True)
        else:
            raw_title = Document(html).title()

        clean_title = raw_title.split(' - ')[0].split(' | ')[0].split(' : ')[0].strip()
        clean_title = re.sub(r'^(Opinion|Editorial|The Guardian view on)\s*:?\s*', '', clean_title, flags=re.IGNORECASE).strip()

        # Extract passage
        passage = extract_content(html, newspaper)
        if not passage or len(passage) < 250:
            return None

        words = len(passage.split())
        reading_time = f"{max(1, round(words / 200))} min read"

        return {
            "title": clean_title,
            "link": url,
            "timestamp": str(TODAY_DATE),
            "published_at": format_published_time(pub_dt),
            "reading_time": reading_time,
            "passage": passage,
            "word_count": words,
            "pub_dt": pub_dt
        }
    except Exception as e:
        print(f"  ⚠️ Error parsing {url}: {e}")
        return None

def extract_links(section_url, filter_pattern, max_links=8, use_proxy=False):
    """Fetches section index page and finds matching editorial links."""
    html = fetch_page(section_url, use_proxy=use_proxy)
    if not html:
        return []

    soup = BeautifulSoup(html, 'html.parser')
    links = []
    
    for a in soup.find_all('a', href=True):
        href = a['href']
        full_url = urljoin(section_url, href).split('?')[0].split('#')[0].rstrip('/') + '/'
        
        if full_url == section_url.rstrip('/') + '/':
            continue

        if re.search(filter_pattern, full_url, re.IGNORECASE):
            if full_url not in links:
                links.append(full_url)
                if len(links) >= max_links:
                    break

    return links

SOURCES_CONFIG = [
    # 1. Economy, Banking & Regulatory Policy
    {
        "category": "Economy, Banking & Regulatory Policy",
        "newspaper": "Finshots",
        "section_url": "https://finshots.in/archive/",
        "pattern": r"https://finshots\.in/archive/[a-zA-Z0-9\-]+/",
        "limit": 1,
        "use_proxy": False
    },
    {
        "category": "Economy, Banking & Regulatory Policy",
        "newspaper": "Financial Express",
        "section_url": "https://www.financialexpress.com/opinion/",
        "pattern": r"/opinion/[a-zA-Z0-9\-_]+/",
        "limit": 1,
        "use_proxy": False
    },
    {
        "category": "Economy, Banking & Regulatory Policy",
        "newspaper": "The Hindu BusinessLine",
        "section_url": "https://www.thehindubusinessline.com/opinion/editorial/",
        "pattern": r"/opinion/editorial/[a-zA-Z0-9\-_]+",
        "limit": 1,
        "use_proxy": False
    },
    # 2. General Governance, National Issues & Vocabulary
    {
        "category": "General Governance, National Issues & Vocabulary",
        "newspaper": "The Indian Express",
        "section_url": "https://indianexpress.com/section/opinion/editorials/",
        "pattern": r"/article/opinion/editorials/[a-zA-Z0-9\-_]+/",
        "limit": 1,
        "use_proxy": True
    },
    {
        "category": "General Governance, National Issues & Vocabulary",
        "newspaper": "The Hindu",
        "section_url": "https://www.thehindu.com/opinion/editorial/",
        "pattern": r"/opinion/editorial/[a-zA-Z0-9\-_]+",
        "limit": 1,
        "use_proxy": False
    },
    {
        "category": "General Governance, National Issues & Vocabulary",
        "newspaper": "Hindustan Times",
        "section_url": "https://www.hindustantimes.com/opinion",
        "pattern": r"/opinion/[a-zA-Z0-9\-_]+-\d+\.html",
        "limit": 1,
        "use_proxy": False
    },
    {
        "category": "General Governance, National Issues & Vocabulary",
        "newspaper": "Deccan Herald",
        "section_url": "https://www.deccanherald.com/opinion-editorial",
        "pattern": r"/opinion/[a-zA-Z0-9\-_]+",
        "limit": 1,
        "use_proxy": False
    },
    {
        "category": "General Governance, National Issues & Vocabulary",
        "newspaper": "The Daily Pioneer",
        "section_url": "https://www.dailypioneer.com/category/opinion",
        "pattern": r"/category/opinion/[a-zA-Z0-9\-_]+|/opinion/[a-zA-Z0-9\-_]+",
        "limit": 1,
        "use_proxy": False
    },
    {
        "category": "General Governance, National Issues & Vocabulary",
        "newspaper": "The Statesman",
        "section_url": "https://www.thestatesman.com/opinion",
        "pattern": r"/opinion/[a-zA-Z0-9\-_]+",
        "limit": 1,
        "use_proxy": False
    },
    {
        "category": "General Governance, National Issues & Vocabulary",
        "newspaper": "The Telegraph",
        "section_url": "https://www.telegraphindia.com/opinion",
        "pattern": r"/opinion/[a-zA-Z0-9\-_]+/\d+",
        "limit": 1,
        "use_proxy": False
    },
    # 3. International Relations, Climate & Complex RC
    {
        "category": "International Relations, Climate & Complex RC",
        "newspaper": "The Guardian",
        "section_url": "https://www.theguardian.com/profile/editorial",
        "pattern": r"/commentisfree/\d{4}/[a-z]{3}/\d{2}/",
        "limit": 1,
        "use_proxy": False
    },
    {
        "category": "International Relations, Climate & Complex RC",
        "newspaper": "Al Jazeera",
        "section_url": "https://www.aljazeera.com/opinion/",
        "pattern": r"/opinion/\d{4}/\d+/\d+/[a-zA-Z0-9\-_]+",
        "limit": 1,
        "use_proxy": False
    },
    # 4. Digital Opinion Portals
    {
        "category": "Digital Opinion Portals",
        "newspaper": "ThePrint",
        "section_url": "https://theprint.in/category/opinion/",
        "pattern": r"/opinion/[a-zA-Z0-9\-_]+/\d+/?",
        "limit": 1,
        "use_proxy": False
    },
    {
        "category": "Digital Opinion Portals",
        "newspaper": "The Wire",
        "section_url": "https://thewire.in/editors-pick",
        "pattern": r"https://thewire\.in/(economy|politics|government|society|rights|external-affairs)/[a-zA-Z0-9\-_]+",
        "limit": 1,
        "use_proxy": False
    }
]

def collect_editorials():
    print(f"🚀 Starting Multi-Source Editorial Collector for {TODAY_DATE} (IST)...")
    all_articles = []

    for cfg in SOURCES_CONFIG:
        print(f"\n📰 Scanning: [{cfg['category']}] -> {cfg['newspaper']}...")
        links = extract_links(cfg['section_url'], cfg['pattern'], max_links=6, use_proxy=cfg.get('use_proxy', False))
        
        candidates = []
        for link in links:
            article = parse_article(link, cfg['newspaper'], use_proxy=cfg.get('use_proxy', False))
            if not article:
                continue

            if article["pub_dt"] and not is_recent_edition(article["pub_dt"]):
                print(f"  ⏭️ Skipping older piece: {article['title'][:35]}...")
                continue

            print(f"  ✓ Fetched: {article['title'][:45]}... ({article['word_count']} words)")
            candidates.append({
                "category": cfg["category"],
                "newspaper": cfg["newspaper"],
                "title": article["title"],
                "link": article["link"],
                "timestamp": article["timestamp"],
                "published_at": article["published_at"],
                "reading_time": article["reading_time"],
                "passage": article["passage"],
                "word_count": article["word_count"]
            })

            if len(candidates) >= cfg["limit"]:
                break

        for item in candidates:
            item.pop("word_count", None)
            all_articles.append(item)

    return all_articles

def run():
    editorials = collect_editorials()
    
    if len(editorials) == 0:
        raise RuntimeError(f"Collector finished but found 0 valid editorials for {TODAY_DATE}.")

    output = {
        "date_scraped": str(TODAY_DATE),
        "total_articles": len(editorials),
        "categories_covered": list(set([item["category"] for item in editorials])),
        "editorials": editorials
    }

    # Only save to daily_editorials.json
    with open('daily_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

    print(f"\n✅ Successfully compiled {len(editorials)} articles into daily_editorials.json")

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
                    "text": f"🚨 **EDITORIAL COLLECTOR FAILED:**\n\n**Error:**\n`{e}`",
                    "parse_mode": "Markdown"
                })
            except Exception:
                pass
        print(f"Fatal error: {e}")
        sys.exit(1)
