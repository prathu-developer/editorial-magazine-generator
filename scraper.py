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
HEADERS_BROWSER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

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
        resp = requests.get(url, headers=HEADERS_BROWSER, timeout=15)
        resp.encoding = 'utf-8'
        
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
        resp = requests.get(rss_url, headers=HEADERS_BROWSER, timeout=15)
        resp.raise_for_status()
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
        resp = requests.get(rss_url, headers=HEADERS_BROWSER, timeout=15)
        resp.raise_for_status()
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