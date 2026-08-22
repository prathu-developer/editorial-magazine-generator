import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from readability import Document
import json
import re
from datetime import datetime, timezone, timedelta
import email.utils

# Timezone set to Indian Standard Time (IST)
IST = timezone(timedelta(hours=5, minutes=30))
TODAY_DATE = datetime.now(IST).date()

# Proven header configuration
HEADERS_DEFAULT = {'User-Agent': 'Mozilla/5.0'}
HEADERS_BROWSER = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://indianexpress.com/',
}
# Feed endpoints specifically want an RSS-flavored Accept header
HEADERS_FEED = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://indianexpress.com/',
}

def fetch_with_fallback(url, headers, timeout=15):
    """
    Fetches a URL directly. If the direct request is blocked (403 Forbidden),
    retries the SAME url through a chain of public read-only proxies.

    Why this exists: some sites (e.g. Indian Express) block requests coming from
    known cloud/datacenter IP ranges -- including GitHub Actions runners -- even
    when headers look like a normal browser. Confirmed by testing: identical
    headers succeed from a home/residential IP and fail (403) from GitHub Actions.
    Routing through a third-party proxy server sidesteps the IP block since the
    request now originates from the proxy's IP, not GitHub's.
    """
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = 'utf-8'
        return resp
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 403:
            print(f"   ↪️ Direct fetch got 403 for {url}. Retrying via proxy...")
            return _fetch_via_proxy(url, timeout)
        raise

def _fetch_via_proxy(url, timeout=15):
    """
    Fetches a url via a chain of public proxies (tried in order), each of which
    makes the request server-side from its own (non-blocklisted) IP.
    Free public proxies are individually unreliable (rate limits, outages) --
    e.g. api.allorigins.win returned a 522 in testing -- so we try several
    before giving up, rather than depending on just one.
    """
    encoded_url = requests.utils.quote(url, safe='')
    proxy_attempts = [
        ("allorigins", f"https://api.allorigins.win/raw?url={encoded_url}"),
        ("codetabs", f"https://api.codetabs.com/v1/proxy?quest={url}"),
        ("corsproxy.io", f"https://corsproxy.io/?url={encoded_url}"),
    ]

    last_error = None
    for name, proxy_url in proxy_attempts:
        try:
            resp = requests.get(proxy_url, timeout=timeout * 2)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            print(f"   ✅ Proxy '{name}' succeeded for {url}")
            return resp
        except Exception as e:
            print(f"   ⚠️ Proxy '{name}' failed: {e}")
            last_error = e
            continue

    raise Exception(f"All proxies failed for {url}. Last error: {last_error}")

def is_published_today(pub_date_str):
    """Safeguard: Verifies if the article was published today in IST."""
    try:
        dt = email.utils.parsedate_to_datetime(pub_date_str)
        dt_ist = dt.astimezone(IST)
        return dt_ist.date() == TODAY_DATE
    except Exception:
        return False

def get_reading_time(html_content, text_body):
    """Extracts stated reading time from HTML metadata or calculates standard 200 WPM."""
    soup = BeautifulSoup(html_content, 'html.parser')
    rt_match = soup.find(string=re.compile(r'\b\d+\s*min(ute)?s?\s*read\b', re.IGNORECASE))
    if rt_match:
        return rt_match.strip()
    
    word_count = len(text_body.split())
    minutes = max(1, round(word_count / 200))
    return f"{minutes} min read"

def scrape_article_data(url):
    """
    Fetches article body and reading time.
    CRITICAL: resp.encoding = 'utf-8' strictly preserves all em-dashes, en-dashes, 
    semicolons, and smart quotation marks.
    """
    try:
        resp = fetch_with_fallback(url, headers=HEADERS_BROWSER, timeout=15)
        
        doc = Document(resp.text)
        soup = BeautifulSoup(doc.summary(), 'html.parser')
        
        text_body = soup.get_text(separator='\n\n', strip=True)
        reading_time = get_reading_time(resp.text, text_body)
        
        return text_body, reading_time
    except Exception as e:
        print(f"Scrape error for {url}: {e}")
        return "", ""

def get_hindu_editorials():
    print("📰 Fetching The Hindu...")
    rss_url = "https://www.thehindu.com/opinion/editorial/feeder/default.rss"
    try:
        resp = fetch_with_fallback(rss_url, headers=HEADERS_FEED, timeout=15)
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        print(f"⚠️ Error parsing The Hindu feed: {e}")
        print(f"   Status: {resp.status_code}, Content-Type: {resp.headers.get('Content-Type')}")
        print(f"   First 300 chars: {resp.text[:300]!r}")
        return []
    except Exception as e:
        print(f"⚠️ Error fetching The Hindu feed: {e}")
        return []
    
    today_articles = []
    fallback_articles = []
    
    for item in root.findall('.//item'):
        pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
        link = item.find('link').text if item.find('link') is not None else ""
        title = item.find('title').text if item.find('title') is not None else ""
        
        body_text, reading_time = scrape_article_data(link)
        
        if body_text:
            article_data = {
                "newspaper": "The Hindu",
                "title": title,
                "link": link,
                "timestamp": pub_date,
                "reading_time": reading_time,
                "passage": body_text
            }
            fallback_articles.append(article_data)
            
            if is_published_today(pub_date):
                today_articles.append(article_data)
                
            if len(today_articles) >= 2:
                break
                
    # Use today's articles if available; otherwise fallback to latest available
    if len(today_articles) >= 2:
        return today_articles[:2]
    
    print("⚠️ The Hindu: Today's editorials not published yet. Using latest available.")
    return fallback_articles[:2]

def get_indian_express_editorials():
    print("📰 Fetching The Indian Express...")
    rss_url = "https://indianexpress.com/section/opinion/editorials/feed/"
    try:
        resp = fetch_with_fallback(rss_url, headers=HEADERS_FEED, timeout=15)
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        print(f"⚠️ Error parsing The Indian Express feed: {e}")
        print(f"   Status: {resp.status_code}, Content-Type: {resp.headers.get('Content-Type')}")
        print(f"   First 300 chars: {resp.text[:300]!r}")
        return []
    except Exception as e:
        print(f"⚠️ Error fetching The Indian Express feed: {e}")
        return []
    
    scraped_pool = []
    for item in root.findall('.//item')[:4]:
        pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
        link = item.find('link').text if item.find('link') is not None else ""
        title = item.find('title').text if item.find('title') is not None else ""
        
        body_text, reading_time = scrape_article_data(link)
        
        if body_text:
            scraped_pool.append({
                "newspaper": "The Indian Express",
                "title": title,
                "link": link,
                "timestamp": pub_date,
                "reading_time": reading_time,
                "passage": body_text,
                "length": len(body_text),
                "is_today": is_published_today(pub_date)
            })
            
    # Filter for today's articles first
    today_pool = [a for a in scraped_pool if a["is_today"]]
    target_pool = today_pool if len(today_pool) >= 2 else scraped_pool
    
    if len(today_pool) < 2:
        print("⚠️ The Indian Express: Today's editorials not published yet. Using latest available.")
        
    # Sort by length descending and pick top 2
    target_pool.sort(key=lambda x: x["length"], reverse=True)
    top_2 = target_pool[:2]
    
    for article in top_2:
        del article["length"]
        del article["is_today"]
        
    return top_2

def run():
    print(f"🚀 Starting daily editorial pipeline for {TODAY_DATE} (IST)...")
    
    all_editorials = []
    all_editorials.extend(get_hindu_editorials())
    all_editorials.extend(get_indian_express_editorials())
    
    output_payload = {
        "date_scraped": str(TODAY_DATE),
        "total_articles": len(all_editorials),
        "editorials": all_editorials
    }
    
    # ensure_ascii=False guarantees special punctuation characters remain literal UTF-8
    with open('today_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=4)
        
    print(f"✅ Successfully compiled {len(all_editorials)} editorials into today_editorials.json")

if __name__ == "__main__":
    run()