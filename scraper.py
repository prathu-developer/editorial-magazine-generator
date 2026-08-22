import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from readability import Document
import json
import re
from datetime import datetime, timezone, timedelta
import email.utils

# Indian Standard Time (IST) configuration
IST = timezone(timedelta(hours=5, minutes=30))
TODAY_DATE = datetime.now(IST).date()

# The proven, lightweight header that bypasses the firewall
HEADERS_DEFAULT = {'User-Agent': 'Mozilla/5.0'}
HEADERS_BROWSER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def is_recent_editorial(pub_date_str):
    """
    Safeguard: Verifies if the article was published within the last 36 hours.
    This fixes the bug where Saturday morning newspapers use Friday night timestamps.
    """
    if not pub_date_str: return False
    try:
        dt = email.utils.parsedate_to_datetime(pub_date_str)
        dt_ist = dt.astimezone(IST)
        now_ist = datetime.now(IST)
        
        # Calculate time difference in hours
        hours_diff = (now_ist - dt_ist).total_seconds() / 3600
        
        # True if published in the last 36 hours (allows for late-night early publishing)
        # We also allow -2 to account for newspapers accidentally using future timezones.
        return -2 <= hours_diff <= 36
    except Exception:
        return False

def get_node_text(item, tag_name):
    """Helper to safely extract text from both ElementTree and BeautifulSoup tags."""
    node = item.find(tag_name)
    if node is None:
        node = item.find(tag_name.lower()) # Fallback for lowercase parsers
    if node is not None and getattr(node, 'text', None):
        return node.text.strip()
    return ""

def scrape_reader_mode_extended(url):
    """Fetches clean text using Reader Mode + Reading Time."""
    try:
        resp = requests.get(url, headers=HEADERS_BROWSER, timeout=15)
        # CRITICAL: Force UTF-8 to strictly preserve em-dashes (—), quotes (“ ”), etc.
        resp.encoding = 'utf-8' 
        
        doc = Document(resp.text)
        soup = BeautifulSoup(doc.summary(), 'html.parser')
        
        # Use \n\n to preserve passage breaks
        text = soup.get_text(separator='\n\n', strip=True)
        
        # Extract Reading Time
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
    rss_url = "https://www.thehindu.com/opinion/editorial/feeder/default.rss"
    try:
        resp = requests.get(rss_url, headers=HEADERS_DEFAULT, timeout=15)
        root = ET.fromstring(resp.content)
        items = root.findall('.//item')
    except Exception as e:
        print(f"⚠️ Failed to parse The Hindu: {e}")
        return []
        
    recent_articles = []
    fallback_articles = []
    
    for item in items:
        pub_date = get_node_text(item, 'pubDate')
        link = get_node_text(item, 'link')
        title = get_node_text(item, 'title')
        
        if not link: continue
        
        text, r_time = scrape_reader_mode_extended(link)
        
        if text:
            article_data = {
                "newspaper": "The Hindu",
                "title": title,
                "link": link,
                "timestamp": pub_date,
                "reading_time": r_time,
                "passage": text
            }
            fallback_articles.append(article_data)
            
            if is_recent_editorial(pub_date):
                recent_articles.append(article_data)
                
            if len(recent_articles) >= 2:
                break
                
    if len(recent_articles) >= 2:
        return recent_articles[:2]
        
    print(f"⚠️ The Hindu: 0 recent articles found. Using latest available.")
    return fallback_articles[:2]

def get_indian_express_editorials():
    print("📰 Fetching The Indian Express...")
    rss_url = "https://indianexpress.com/section/opinion/editorials/feed/"
    
    try:
        resp = requests.get(rss_url, headers=HEADERS_DEFAULT, timeout=15)
        # 🔥 THE CRASH FIX: Try normal XML parse, fallback to resilient BeautifulSoup
        try:
            root = ET.fromstring(resp.content)
            items = root.findall('.//item')
        except ET.ParseError:
            print("⚠️ Indian Express XML was malformed. Using resilient fallback parser...")
            soup = BeautifulSoup(resp.content, 'xml')
            items = soup.find_all('item')
            
    except Exception as e:
        print(f"⚠️ Failed to fetch The Indian Express: {e}")
        return []
        
    scraped_pool = []
    
    # Process up to the latest 5 items in the feed
    for item in items[:5]:
        pub_date = get_node_text(item, 'pubDate')
        link = get_node_text(item, 'link')
        title = get_node_text(item, 'title')
        
        if not link: continue
            
        text, r_time = scrape_reader_mode_extended(link)
        
        if text:
            scraped_pool.append({
                "newspaper": "The Indian Express",
                "title": title,
                "link": link,
                "timestamp": pub_date,
                "reading_time": r_time,
                "passage": text,
                "length": len(text),
                "is_recent": is_recent_editorial(pub_date)
            })
            
    recent_pool = [a for a in scraped_pool if a["is_recent"]]
    target_pool = recent_pool if len(recent_pool) > 0 else scraped_pool
    
    if len(recent_pool) == 0:
        print("⚠️ The Indian Express: 0 recent articles found. Using latest available.")
        
    # The Magic Sort: longest articles first
    target_pool.sort(key=lambda x: x["length"], reverse=True)
    top_2 = target_pool[:2]
    
    # Clean up the temporary keys
    for article in top_2:
        del article["length"]
        if "is_recent" in article:
            del article["is_recent"]
        
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
    
    # CRITICAL: ensure_ascii=False guarantees raw UTF-8 output so special punctuation stays perfect
    with open('today_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=4)
        
    print(f"✅ Successfully compiled {len(all_editorials)} editorials into today_editorials.json")

if __name__ == "__main__":
    run()