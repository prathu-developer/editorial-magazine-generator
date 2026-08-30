import os
import sys
import time
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, quote_plus
from bs4 import BeautifulSoup
from readability import Document
from curl_cffi import requests as cffi_requests
import requests as std_requests

IST = timezone(timedelta(hours=5, minutes=30))
NOW_IST = datetime.now(IST)
TODAY_DATE = NOW_IST.date()
HISTORY_FILE = "editorial_history.json"
OUTPUT_FILE = "daily_editorials.json"

SCRAPINGANT_KEY = os.getenv("SCRAPINGANT_API_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ENV_ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
HARDCODED_ADMIN_ID = "5103843488"

# Deduplicate recipient Telegram IDs
RECIPIENT_CHAT_IDS = list({cid for cid in [ENV_ADMIN_CHAT_ID, HARDCODED_ADMIN_ID] if cid})

session = cffi_requests.Session(impersonate="chrome124")

def load_history():
    """Loads scraping history and prunes entries older than 7 days."""
    cutoff_date = TODAY_DATE - timedelta(days=7)
    if not os.path.exists(HISTORY_FILE):
        return {"history": []}

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            history = data.get("history", [])
            filtered_history = [
                entry for entry in history
                if datetime.strptime(entry.get("scraped_date", str(TODAY_DATE)), "%Y-%m-%d").date() >= cutoff_date
            ]
            return {"history": filtered_history}
    except Exception as e:
        print(f"⚠️ Error reading {HISTORY_FILE}: {e}. Initializing fresh history.")
        return {"history": []}

def save_history(history_data):
    """Saves updated history ledger."""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history_data, f, ensure_ascii=False, indent=4)

def is_already_scraped(title, url, history_entries):
    """Checks whether an article was already collected in the past 7 days."""
    norm_title = re.sub(r'\W+', '', title.lower())
    norm_url = url.split("?")[0].rstrip("/")

    for entry in history_entries:
        entry_title = re.sub(r'\W+', '', entry.get("title", "").lower())
        entry_url = entry.get("link", "").split("?")[0].rstrip("/")
        if norm_title == entry_title or norm_url == entry_url:
            return True
    return False

def fetch_page(url, max_retries=2, timeout=25, use_proxy=False):
    """Fetches web page content with automatic proxy fallback on 403 or timeout."""
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    if use_proxy and SCRAPINGANT_KEY:
        target_url = f"https://api.scrapingant.com/v2/general?url={quote_plus(url)}&x-api-key={SCRAPINGANT_KEY}&browser=false"
        try:
            res = session.get(target_url, headers=headers, timeout=60)
            if res.status_code == 200 and len(res.text) > 500:
                return res.text
        except Exception as e:
            print(f"  ⚠️ Proxy fetch error for {url}: {e}")
        return ""

    for attempt in range(1, max_retries + 1):
        try:
            res = session.get(url, headers=headers, timeout=timeout)
            if res.status_code == 200 and len(res.text) > 500:
                return res.text
            
            if res.status_code in [403, 429] and SCRAPINGANT_KEY:
                print(f"  🛡️ HTTP {res.status_code} on {url}. Retrying with ScrapingAnt proxy...")
                proxy_url = f"https://api.scrapingant.com/v2/general?url={quote_plus(url)}&x-api-key={SCRAPINGANT_KEY}&browser=false"
                p_res = session.get(proxy_url, headers=headers, timeout=60)
                if p_res.status_code == 200 and len(p_res.text) > 500:
                    return p_res.text

            print(f"  ⚠️ [Attempt {attempt}/{max_retries}] Status {res.status_code} for {url}")
        except Exception as e:
            print(f"  ⚠️ [Attempt {attempt}/{max_retries}] Fetch error for {url}: {e}")
            if SCRAPINGANT_KEY:
                print(f"  🛡️ Timeout/Error. Retrying with ScrapingAnt proxy...")
                try:
                    proxy_url = f"https://api.scrapingant.com/v2/general?url={quote_plus(url)}&x-api-key={SCRAPINGANT_KEY}&browser=false"
                    p_res = session.get(proxy_url, headers=headers, timeout=60)
                    if p_res.status_code == 200 and len(p_res.text) > 500:
                        return p_res.text
                except Exception:
                    pass
        
        if attempt < max_retries:
            time.sleep(2)

    return ""

def extract_article_datetime(html):
    """Extracts publication datetime in IST from metadata or JSON-LD."""
    soup = BeautifulSoup(html, 'html.parser')
    
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
    """Formats datetime to standard readable format."""
    if pub_dt:
        return pub_dt.strftime("%B %d, %Y %I:%M %p IST")
    return f"{TODAY_DATE.strftime('%B %d, %Y')} IST"

def extract_clean_paragraphs(container):
    """Sanitizes text and preserves editorial paragraphs."""
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
    """Extracts article body based on source selectors with Readability fallback."""
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

    doc = Document(html)
    summary_soup = BeautifulSoup(doc.summary(), 'html.parser')
    return extract_clean_paragraphs(summary_soup)

def parse_article(url, newspaper, use_proxy=False):
    """Extracts article content, clean title, and publication timestamp."""
    html = fetch_page(url, use_proxy=use_proxy)
    if not html:
        return None

    try:
        pub_dt = extract_article_datetime(html)
        soup = BeautifulSoup(html, 'html.parser')
        
        h1 = soup.find('h1')
        if h1:
            for badge in h1.find_all(['span', 'div', 'a']):
                badge.decompose()
            raw_title = h1.get_text(strip=True)
        else:
            raw_title = Document(html).title()

        clean_title = raw_title.split(' - ')[0].split(' | ')[0].split(' : ')[0].strip()
        clean_title = re.sub(r'^(Opinion|Editorial|The Guardian view on)\s*:?\s*', '', clean_title, flags=re.IGNORECASE).strip()

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
            "pub_dt": pub_dt or datetime(NOW_IST.year, NOW_IST.month, NOW_IST.day, tzinfo=IST)
        }
    except Exception as e:
        print(f"  ⚠️ Error parsing {url}: {e}")
        return None

def extract_links(section_url, filter_pattern, max_links=10, use_proxy=False):
    """Collects candidate editorial links from the index page."""
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
        "pattern": r"/opinion/[a-zA-Z0-9\-_]+",
        "limit": 1,
        "use_proxy": False
    },
    {
        "category": "General Governance, National Issues & Vocabulary",
        "newspaper": "Deccan Herald",
        "section_url": "https://www.deccanherald.com/opinion/editorial",
        "pattern": r"/opinion/(editorial/)?[a-zA-Z0-9\-_]+",
        "limit": 1,
        "use_proxy": False
    },
    {
        "category": "General Governance, National Issues & Vocabulary",
        "newspaper": "The Daily Pioneer",
        "section_url": "https://www.dailypioneer.com/category/opinion",
        "pattern": r"/(category/)?opinion/[a-zA-Z0-9\-_]+",
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
        "pattern": r"/opinion/[a-zA-Z0-9\-_]+",
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
        "pattern": r"/opinion/\d{4}/\d{1,2}/\d{1,2}/[a-zA-Z0-9\-_]+",
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
        "pattern": r"https://thewire\.in/[a-zA-Z0-9\-_]+/[a-zA-Z0-9\-_]+",
        "limit": 1,
        "use_proxy": False
    }
]

def collect_editorials():
    print(f"🚀 Starting Multi-Source Editorial Collector for {TODAY_DATE} (IST)...")
    history_data = load_history()
    history_entries = history_data.get("history", [])
    
    all_articles = []
    new_history_records = []

    for cfg in SOURCES_CONFIG:
        print(f"\n📰 Scanning: [{cfg['category']}] -> {cfg['newspaper']}...")
        links = extract_links(cfg['section_url'], cfg['pattern'], max_links=8, use_proxy=cfg.get('use_proxy', False))
        
        parsed_candidates = []
        for link in links:
            article = parse_article(link, cfg['newspaper'], use_proxy=cfg.get('use_proxy', False))
            if not article:
                continue

            if is_already_scraped(article["title"], article["link"], history_entries):
                print(f"  ⏭️ Already collected within past week: {article['title'][:35]}...")
                continue

            parsed_candidates.append(article)

        if not parsed_candidates:
            print(f"  ⚠️ No new uncollected pieces found for {cfg['newspaper']}.")
            continue

        parsed_candidates.sort(key=lambda item: item["pub_dt"], reverse=True)
        selected_candidates = parsed_candidates[:cfg["limit"]]

        for item in selected_candidates:
            print(f"  ✓ Picked Latest: {item['title'][:45]}... ({item['published_at']})")
            
            all_articles.append({
                "category": cfg["category"],
                "newspaper": cfg["newspaper"],
                "title": item["title"],
                "link": item["link"],
                "timestamp": item["timestamp"],
                "published_at": item["published_at"],
                "reading_time": item["reading_time"],
                "passage": item["passage"]
            })

            new_history_records.append({
                "newspaper": cfg["newspaper"],
                "title": item["title"],
                "link": item["link"],
                "scraped_date": str(TODAY_DATE)
            })

    history_data["history"].extend(new_history_records)
    save_history(history_data)

    return all_articles

def send_telegram_document_to_recipients(file_path):
    """Sends JSON file copy to all configured Telegram recipient chat IDs."""
    if not BOT_TOKEN or not RECIPIENT_CHAT_IDS:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            total_articles = len(json.load(f).get("editorials", []))
    except Exception:
        total_articles = 0

    caption = f"📰 *Daily Editorials Collected*\n📅 Date: {TODAY_DATE}\n⚡ Total Articles: {total_articles}"

    for chat_id in RECIPIENT_CHAT_IDS:
        try:
            with open(file_path, "rb") as f:
                res = std_requests.post(
                    url,
                    data={"chat_id": str(chat_id), "caption": caption, "parse_mode": "Markdown"},
                    files={"document": (os.path.basename(file_path), f, "application/json")},
                    timeout=45
                )
            if res.status_code == 200:
                print(f"📤 Sent `{file_path}` to Telegram Admin ({chat_id}).")
            else:
                print(f"⚠️ Failed sending document to {chat_id}: {res.text}")
        except Exception as e:
            print(f"⚠️ Telegram send error for {chat_id}: {e}")

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

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

    print(f"\n✅ Successfully compiled {len(editorials)} articles into {OUTPUT_FILE}")
    
    send_telegram_document_to_recipients(OUTPUT_FILE)

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        if BOT_TOKEN and RECIPIENT_CHAT_IDS:
            for chat_id in RECIPIENT_CHAT_IDS:
                try:
                    std_requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                        "chat_id": str(chat_id),
                        "text": f"🚨 **DAILY EDITORIAL COLLECTOR FAILED:**\n\n**Error:**\n`{e}`",
                        "parse_mode": "Markdown"
                    }, timeout=20)
                except Exception:
                    pass
        print(f"Fatal error: {e}")
        sys.exit(1)
