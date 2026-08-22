import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from readability import Document
import json
import os
import re
from datetime import datetime, timezone, timedelta
import email.utils

# Set standard timezone to IST (Indian Standard Time) for accurate newspaper date matching
IST = timezone(timedelta(hours=5, minutes=30))
TODAY_DATE = datetime.now(IST).date()

def is_published_today(pub_date_str):
    """Safeguard: Checks if the RSS publication date strictly matches today's date in IST."""
    try:
        # Parse standard RSS RFC 2822 date
        dt = email.utils.parsedate_to_datetime(pub_date_str)
        # Convert to IST to match the newspaper's local release date
        dt_ist = dt.astimezone(IST)
        return dt_ist.date() == TODAY_DATE
    except Exception as e:
        print(f"Date parsing error for '{pub_date_str}': {e}")
        return False

def get_reading_time(html_content, text_body):
    """Extracts reading time from HTML or calculates it as a fallback."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Try to find an explicit "X min read" in the page's text or metadata
    rt_match = soup.find(string=re.compile(r'\b\d+\s*min(ute)?s?\s*read\b', re.IGNORECASE))
    if rt_match:
        # Clean up any surrounding whitespace or newlines
        return rt_match.strip()
        
    # 2. Fallback: Calculate standard reading time (~200 words per minute)
    word_count = len(text_body.split())
    minutes = max(1, round(word_count / 200))
    return f"{minutes} min read (Calculated)"

def scrape_article(url):
    """Fetches clean text and reading time, preserving ALL punctuation strictly."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        # CRITICAL: Force UTF-8 encoding to prevent garbling em-dashes (—), smart quotes, etc.
        resp.encoding = 'utf-8' 
        
        doc = Document(resp.text)
        soup = BeautifulSoup(doc.summary(), 'html.parser')
        
        # Extract text strictly preserving special punctuation
        text_body = soup.get_text(separator='\n\n', strip=True)
        reading_time = get_reading_time(resp.text, text_body)
        
        return text_body, reading_time
    except Exception as e:
        print(f"Scrape error for {url}: {e}")
        return "", ""

def get_hindu_editorials():
    print("📰 Fetching The Hindu...")
    rss_url = "https://www.thehindu.com/opinion/editorial/feeder/default.rss"
    # Added realistic headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml, */*'
    }
    
    try:
        resp = requests.get(rss_url, headers=headers, timeout=15)
        resp.raise_for_status() # Check for 403 or 404 errors
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"⚠️ Failed to fetch or parse The Hindu feed: {e}")
        return []
    
    editorials = []
    for item in root.findall('.//item'):
        pub_date = item.find('pubDate').text
        
        # SAFEGUARD: Skip if not published today
        if not is_published_today(pub_date):
            continue
            
        link = item.find('link').text
        title = item.find('title').text
        body_text, reading_time = scrape_article(link)
        
        if body_text:
            editorials.append({
                "newspaper": "The Hindu",
                "title": title,
                "link": link,
                "timestamp": pub_date,
                "reading_time": reading_time,
                "passage": body_text
            })
            
        # Stop once we have our 2 valid editorials for today
        if len(editorials) >= 2:
            break
            
    return editorials

def get_indian_express_editorials():
    print("📰 Fetching The Indian Express...")
    rss_url = "https://indianexpress.com/section/opinion/editorials/feed/"
    # Heavy disguise headers to bypass bot protection
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive'
    }
    
    try:
        resp = requests.get(rss_url, headers=headers, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        print("⚠️ Indian Express blocked the XML request (returned HTML). Skipping for today.")
        return []
    except Exception as e:
        print(f"⚠️ Failed to fetch The Indian Express feed: {e}")
        return []
    
    valid_articles = []
    
    for item in root.findall('.//item'):
        pub_date = item.find('pubDate').text
        
        # SAFEGUARD: Skip if not published today
        if not is_published_today(pub_date):
            continue
            
        link = item.find('link').text
        title = item.find('title').text
        body_text, reading_time = scrape_article(link)
        
        if body_text:
            valid_articles.append({
                "newspaper": "The Indian Express",
                "title": title,
                "link": link,
                "timestamp": pub_date,
                "reading_time": reading_time,
                "passage": body_text,
                "length": len(body_text) # Temporary key for sorting
            })
            
    # Sort today's articles by length descending, then grab the top 2
    valid_articles.sort(key=lambda x: x["length"], reverse=True)
    top_2 = valid_articles[:2]
    
    # Remove the temporary 'length' key before final output
    for article in top_2:
        del article["length"]
        
    return top_2

def run():
    print(f"🚀 Starting scraper for {TODAY_DATE} (IST)...")
    
    all_editorials = []
    all_editorials.extend(get_hindu_editorials())
    all_editorials.extend(get_indian_express_editorials())
    
    final_output = {
        "date_scraped": str(TODAY_DATE),
        "total_articles_extracted": len(all_editorials),
        "editorials": all_editorials
    }
    
    # CRITICAL: ensure_ascii=False guarantees that Unicode punctuation 
    # (like —, –, ”, ‘) remains exactly as scraped.
    with open('today_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
        
    print(f"✅ Successfully saved {len(all_editorials)} editorials to today_editorials.json")

if __name__ == "__main__":
    run()
