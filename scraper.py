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

def is_published_today(pub_date_str):
    """Safeguard: Verifies if the article was published today in IST."""
    try:
        dt = email.utils.parsedate_to_datetime(pub_date_str)
        return dt.astimezone(IST).date() == TODAY_DATE
    except Exception:
        return False

# --- EXACT ENGINE FROM YOUR WORKING SCRIPT ---
def scrape_reader_mode_extended(url):
    """Fetches clean text using Reader Mode + Reading Time."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
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
        # Using exact request from generate_vocab_2.py
        resp = requests.get(rss_url)
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"⚠️ Failed to parse The Hindu: {e}")
        return []
        
    editorials = []
    for item in root.findall('.//item'):
        pub_date = item.find('pubDate').text
        
        # Date Safeguard
        if not is_published_today(pub_date):
            continue
            
        link = item.find('link').text
        title = item.find('title').text
        text, r_time = scrape_reader_mode_extended(link)
        
        if text:
            editorials.append({
                "newspaper": "The Hindu",
                "title": title,
                "link": link,
                "timestamp": pub_date,
                "reading_time": r_time,
                "passage": text
            })
            
        if len(editorials) >= 2:
            break
            
    return editorials

def get_indian_express_editorials():
    print("📰 Fetching The Indian Express...")
    rss_url = "https://indianexpress.com/section/opinion/editorials/feed/"
    # Using exact header from generate_vocab_2.py
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        resp = requests.get(rss_url, headers=headers)
        
        # 🔥 THE CRASH FIX: Try to parse normally, but catch the "mismatched tag" error safely
        try:
            root = ET.fromstring(resp.content)
            items = root.findall('.//item')
        except ET.ParseError:
            print("⚠️ Indian Express XML was malformed. Using resilient fallback parser...")
            # BeautifulSoup's XML parser fixes broken tags automatically without crashing
            soup = BeautifulSoup(resp.content, 'xml')
            items = soup.find_all('item')
            
    except Exception as e:
        print(f"⚠️ Failed to fetch The Indian Express: {e}")
        return []
        
    valid_articles = []
    
    for item in items:
        # Handle both ElementTree and BeautifulSoup tag objects smoothly
        pub_date = item.find('pubDate').text if hasattr(item, 'find') and item.find('pubDate') is not None else ""
        link = item.find('link').text if hasattr(item, 'find') and item.find('link') is not None else ""
        title = item.find('title').text if hasattr(item, 'find') and item.find('title') is not None else ""
        
        # Date Safeguard
        if not is_published_today(pub_date):
            continue
            
        text, r_time = scrape_reader_mode_extended(link)
        
        if text:
            valid_articles.append({
                "newspaper": "The Indian Express",
                "title": title,
                "link": link,
                "timestamp": pub_date,
                "reading_time": r_time,
                "passage": text,
                "length": len(text)
            })
            
    # The Magic Sort from generate_vocab_2.py
    valid_articles.sort(key=lambda x: x["length"], reverse=True)
    top_2 = valid_articles[:2]
    
    # Clean up the temporary length key
    for article in top_2:
        del article["length"]
        
    return top_2

def run():
    print(f"🚀 Starting daily editorial pipeline for {TODAY_DATE} (IST)...")
    
    all_editorials = []
    all_editorials.extend(get_hindu_editorials())
    all_editorials.extend(get_indian_express_editorials())
    
    if len(all_editorials) == 0:
        print("⚠️ 0 articles found for strictly today. (Newspapers might not be published yet).")
    
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