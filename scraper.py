import requests
from bs4 import BeautifulSoup
from readability import Document
import json
import re
import urllib.parse
from datetime import datetime, timezone, timedelta
import email.utils

# Indian Standard Time (IST) configuration
IST = timezone(timedelta(hours=5, minutes=30))
TODAY_DATE = datetime.now(IST).date()

# The exact lightweight headers from your working script
HEADERS_DEFAULT = {'User-Agent': 'Mozilla/5.0'}
HEADERS_BROWSER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def is_recent_editorial(pub_date_str):
    """Safeguard: Verifies if the article was published within the last 36 hours."""
    if not pub_date_str: return False
    try:
        dt = email.utils.parsedate_to_datetime(pub_date_str)
        dt_ist = dt.astimezone(IST)
        now_ist = datetime.now(IST)
        hours_diff = (now_ist - dt_ist).total_seconds() / 3600
        return -12 <= hours_diff <= 36
    except Exception:
        return False

def fetch_feed_with_proxy(url):
    """Fetches the RSS feed. Tunnels through a multi-proxy waterfall if Cloudflare blocks."""
    try:
        resp = requests.get(url, headers=HEADERS_DEFAULT, timeout=15)
        if resp.status_code == 200 and b'<item>' in resp.content:
            return resp.content.decode('utf-8', errors='ignore')
    except Exception:
        pass
        
    print("⚠️ Direct fetch blocked by firewall. Using multi-proxy waterfall...")
    
    # Waterfall array of proxies to try if the direct fetch is blocked
    proxies = [
        f"https://api.codetabs.com/v1/proxy?quest={url}",
        f"https://api.allorigins.win/raw?url={urllib.parse.quote(url)}"
    ]
    
    for proxy_url in proxies:
        try:
            proxy_name = proxy_url.split('/')[2]
            print(f"🔄 Tunneling through {proxy_name}...")
            # Increased timeout to 30s to completely prevent the 'ReadTimeout' error
            resp = requests.get(proxy_url, timeout=30)
            if resp.status_code == 200 and '<item>' in resp.text:
                return resp.text
        except Exception as e:
            print(f"⚠️ {proxy_name} proxy failed: {e}")
        
    return ""

def parse_rss_regex(raw_text):
    """Bypasses XML ParseErrors entirely by extracting data as raw text."""
    items_text = re.findall(r'<item>(.*?)</item>', raw_text, re.DOTALL | re.IGNORECASE)
    items = []
    
    for it in items_text:
        link = re.search(r'<link>(.*?)</link>', it, re.IGNORECASE)
        title = re.search(r'<title>(.*?)</title>', it, re.IGNORECASE)
        pub_date = re.search(r'<pubDate>(.*?)</pubDate>', it, re.IGNORECASE)
        
        if link:
            clean_link = link.group(1).replace('<![CDATA[', '').replace(']]>', '').strip()
            clean_title = title.group(1).replace('<![CDATA[', '').replace(']]>', '').strip() if title else ""
            clean_date = pub_date.group(1).strip() if pub_date else ""
            items.append({'link': clean_link, 'title': clean_title, 'pubDate': clean_date})
            
    return items

def scrape_reader_mode_extended(url):
    """Fetches clean text using Reader Mode + Reading Time."""
    try:
        resp = requests.get(url, headers=HEADERS_BROWSER, timeout=20)
        
        # Anti-Cloudflare safeguard for the actual article pages
        if resp.status_code in [403, 503, 401]:
            print(f"⚠️ Article blocked. Tunneling {url}...")
            resp = requests.get(f"https://api.codetabs.com/v1/proxy?quest={url}", timeout=30)
            
        resp.encoding = 'utf-8' # Preserves strict punctuation (—, ”, etc.)
        
        doc = Document(resp.text)
        soup = BeautifulSoup(doc.summary(), 'html.parser')
        
        text = soup.get_text(separator='\n\n', strip=True)
        
        rt_match = soup.find(string=re.compile(r'\b\d+\s*min(ute)?s?\s*read\b', re.IGNORECASE))
        if rt_match:
            reading_time = rt_match.strip()
        else:
            word_count = len(text.split())
            reading_time = f"{max(1, round(word_count / 200))} min read"
            
        return text, reading_time
    except Exception as e:
        print(f"Scrape error for {url}: {e}")
        return "", ""

def get_hindu_editorials():
    print("📰 Fetching The Hindu...")
    raw_xml = fetch_feed_with_proxy("https://www.thehindu.com/opinion/editorial/feeder/default.rss")
    items = parse_rss_regex(raw_xml)
    
    scraped_pool = []
    for item in items[:5]:
        text, r_time = scrape_reader_mode_extended(item['link'])
        if text:
            scraped_pool.append({
                "newspaper": "The Hindu",
                "title": item['title'],
                "link": item['link'],
                "timestamp": item['pubDate'],
                "reading_time": r_time,
                "passage": text,
                "is_recent": is_recent_editorial(item['pubDate'])
            })
            
    recent = [a for a in scraped_pool if a["is_recent"]]
    target = recent if len(recent) >= 2 else scraped_pool
    
    if len(recent) < 2:
        print("⚠️ The Hindu: 0 recent articles found. Using latest available.")
        
    target = target[:2]
    for a in target:
        a.pop("is_recent", None)
        
    return target

def get_indian_express_editorials():
    print("📰 Fetching The Indian Express...")
    raw_xml = fetch_feed_with_proxy("https://indianexpress.com/section/opinion/editorials/feed/")
    items = parse_rss_regex(raw_xml)
    
    scraped_pool = []
    for item in items[:5]:
        text, r_time = scrape_reader_mode_extended(item['link'])
        if text and len(text) > 150:  # Ensures we don't accidentally save blank blocks
            scraped_pool.append({
                "newspaper": "The Indian Express",
                "title": item['title'],
                "link": item['link'],
                "timestamp": item['pubDate'],
                "reading_time": r_time,
                "passage": text,
                "length": len(text),
                "is_recent": is_recent_editorial(item['pubDate'])
            })
            
    recent = [a for a in scraped_pool if a["is_recent"]]
    target = recent if len(recent) >= 2 else scraped_pool
    
    if len(recent) < 2:
        print("⚠️ The Indian Express: 0 recent articles found. Using latest available.")
        
    target.sort(key=lambda x: x["length"], reverse=True)
    top_2 = target[:2]
    
    for a in top_2:
        a.pop("length", None)
        a.pop("is_recent", None)
        
    return top_2

def run():
    print(f"🚀 Starting daily editorial pipeline for {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')} (IST)...")
    
    all_editorials = []
    all_editorials.extend(get_hindu_editorials())
    all_editorials.extend(get_indian_express_editorials())
    
    output_payload = {
        "date_scraped": str(TODAY_DATE),
        "total_articles": len(all_editorials),
        "editorials": all_editorials
    }
    
    with open('today_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=4)
        
    print(f"✅ Successfully compiled {len(all_editorials)} editorials into today_editorials.json")

if __name__ == "__main__":
    run()