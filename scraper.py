import requests
from bs4 import BeautifulSoup
from readability import Document
import json
import re
from datetime import datetime, timezone, timedelta
import email.utils

# Indian Standard Time (IST) configuration
IST = timezone(timedelta(hours=5, minutes=30))
TODAY_DATE = datetime.now(IST).date()

def is_recent_editorial(pub_date_str):
    """36-hour window safeguard to handle late-night publishing offsets."""
    if not pub_date_str: return False
    try:
        dt = email.utils.parsedate_to_datetime(pub_date_str)
        dt_ist = dt.astimezone(IST)
        now_ist = datetime.now(IST)
        hours_diff = (now_ist - dt_ist).total_seconds() / 3600
        return -12 <= hours_diff <= 36
    except Exception:
        return False

def scrape_speedreader_mode(url):
    """
    Exact content engine from generate_vocab_2.py using the Speedreader logic.
    Strips away all website junk and returns the clean passage.
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        # CRITICAL: Force UTF-8 to strictly preserve em-dashes (—), quotes (“ ”), etc.
        resp.encoding = 'utf-8' 
        
        doc = Document(resp.text)
        soup = BeautifulSoup(doc.summary(), 'html.parser')
        
        # Use \n\n to preserve passage breaks
        text = soup.get_text(separator='\n\n', strip=True)
        
        # Calculate reading time
        rt_match = soup.find(string=re.compile(r'\b\d+\s*min(ute)?s?\s*read\b', re.IGNORECASE))
        if rt_match:
            r_time = rt_match.strip()
        else:
            word_count = len(text.split())
            r_time = f"{max(1, round(word_count / 200))} min read"
            
        return text, r_time
    except Exception as e:
        print(f"Speedreader error for {url}: {e}")
        return "", ""

def get_hindu_editorials():
    print("📰 Fetching The Hindu...")
    rss_url = "https://www.thehindu.com/opinion/editorial/feeder/default.rss"
    try:
        # Exact request method from generate_vocab_2.py
        resp = requests.get(rss_url, timeout=15)
        # BeautifulSoup XML parser automatically heals broken tags
        soup = BeautifulSoup(resp.content, 'xml')
        items = soup.find_all('item')
    except Exception as e:
        print(f"⚠️ Failed to parse The Hindu: {e}")
        return []
        
    articles = []
    
    for item in items[:5]:
        link = item.find('link').text.strip() if item.find('link') else ""
        title = item.find('title').text.strip() if item.find('title') else ""
        pub_date = item.find('pubDate').text.strip() if item.find('pubDate') else ""
        
        if not link or not is_recent_editorial(pub_date):
            continue
            
        text, r_time = scrape_speedreader_mode(link)
        
        if text:
            articles.append({
                "newspaper": "The Hindu",
                "title": title,
                "link": link,
                "timestamp": pub_date,
                "reading_time": r_time,
                "passage": text
            })
            
            if len(articles) >= 2:
                break
                
    if len(articles) == 0:
        print("⚠️ The Hindu: 0 recent articles found.")
        
    return articles

def get_indian_express_editorials():
    print("📰 Fetching The Indian Express...")
    rss_url = "https://indianexpress.com/section/opinion/editorials/feed/"
    
    # The proven Cloudflare-bypass header from generate_vocab_2.py
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        resp = requests.get(rss_url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.content, 'xml')
        items = soup.find_all('item')
    except Exception as e:
        print(f"⚠️ Failed to fetch The Indian Express: {e}")
        return []
        
    articles = []
    
    for item in items[:5]:
        link = item.find('link').text.strip() if item.find('link') else ""
        title = item.find('title').text.strip() if item.find('title') else ""
        pub_date = item.find('pubDate').text.strip() if item.find('pubDate') else ""
        
        if not link or not is_recent_editorial(pub_date):
            continue
            
        text, r_time = scrape_speedreader_mode(link)
        
        if text and len(text) > 150: # Safeguard against empty blocks
            articles.append({
                "newspaper": "The Indian Express",
                "title": title,
                "link": link,
                "timestamp": pub_date,
                "reading_time": r_time,
                "passage": text,
                "length": len(text) # For the Magic Sort
            })
            
    if len(articles) == 0:
        print("⚠️ The Indian Express: 0 recent articles found.")
        
    # The Magic Sort from generate_vocab_2.py
    articles.sort(key=lambda x: x["length"], reverse=True)
    top_2 = articles[:2]
    
    # Clean up the temporary key
    for article in top_2:
        del article["length"]
        
    return top_2

def run():
    print(f"🚀 Starting Speedreader pipeline for {TODAY_DATE} (IST)...")
    
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