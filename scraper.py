import cloudscraper
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from readability import Document
import json
import os
import re
from datetime import datetime, timezone, timedelta
import email.utils

# Set standard timezone to IST (Indian Standard Time)
IST = timezone(timedelta(hours=5, minutes=30))
TODAY_DATE = datetime.now(IST).date()

# 🔥 Create a CloudScraper instance to bypass 403 Forbidden / Cloudflare blocks
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

def is_published_today(pub_date_str):
    """Checks if the RSS publication date strictly matches today's date in IST."""
    try:
        dt = email.utils.parsedate_to_datetime(pub_date_str)
        dt_ist = dt.astimezone(IST)
        return dt_ist.date() == TODAY_DATE
    except Exception as e:
        print(f"Date parsing error for '{pub_date_str}': {e}")
        return False

def get_reading_time(html_content, text_body):
    """Extracts reading time from HTML or calculates it as a fallback."""
    soup = BeautifulSoup(html_content, 'html.parser')
    rt_match = soup.find(string=re.compile(r'\b\d+\s*min(ute)?s?\s*read\b', re.IGNORECASE))
    if rt_match:
        return rt_match.strip()
        
    word_count = len(text_body.split())
    minutes = max(1, round(word_count / 200))
    return f"{minutes} min read (Calculated)"

def scrape_article(url):
    """Fetches clean text, preserving ALL punctuation strictly."""
    try:
        # Use cloudscraper instead of requests
        resp = scraper.get(url, timeout=20)
        resp.encoding = 'utf-8' # CRITICAL: Prevents garbled special punctuation
        
        doc = Document(resp.text)
        soup = BeautifulSoup(doc.summary(), 'html.parser')
        
        text_body = soup.get_text(separator='\n\n', strip=True)
        reading_time = get_reading_time(resp.text, text_body)
        
        return text_body, reading_time
    except Exception as e:
        print(f"Scrape error for {url}: {e}")
        return "", ""

def extract_feed(rss_url, newspaper_name):
    """Generic function to fetch and parse an RSS feed."""
    print(f"📰 Fetching {newspaper_name}...")
    try:
        resp = scraper.get(rss_url, timeout=20)
        resp.raise_for_status()
        return ET.fromstring(resp.content)
    except ET.ParseError:
        print(f"⚠️ {newspaper_name} blocked the XML request. Try again later.")
        return None
    except Exception as e:
        print(f"⚠️ Failed to fetch {newspaper_name} feed: {e}")
        return None

def get_hindu_editorials():
    rss_url = "https://www.thehindu.com/opinion/editorial/feeder/default.rss"
    root = extract_feed(rss_url, "The Hindu")
    if not root: return []
    
    editorials = []
    fallback_editorials = []
    
    for item in root.findall('.//item'):
        pub_date = item.find('pubDate').text
        link = item.find('link').text
        title = item.find('title').text
        body_text, reading_time = scrape_article(link)
        
        if body_text:
            article_data = {
                "newspaper": "The Hindu",
                "title": title,
                "link": link,
                "timestamp": pub_date,
                "reading_time": reading_time,
                "passage": body_text
            }
            
            # Store everything in fallback just in case today's check fails
            fallback_editorials.append(article_data)
            
            if is_published_today(pub_date):
                editorials.append(article_data)
                
            if len(editorials) >= 2:
                break
                
    # Smart Fallback: If no articles published *strictly* today, grab the latest 2 available
    if len(editorials) == 0 and len(fallback_editorials) > 0:
        print("⚠️ No Hindu editorials found for strictly today. Using the latest available.")
        return fallback_editorials[:2]
        
    return editorials

def get_indian_express_editorials():
    rss_url = "https://indianexpress.com/section/opinion/editorials/feed/"
    root = extract_feed(rss_url, "The Indian Express")
    if not root: return []
    
    valid_articles = []
    fallback_articles = []
    
    for item in root.findall('.//item'):
        pub_date = item.find('pubDate').text
        link = item.find('link').text
        title = item.find('title').text
        body_text, reading_time = scrape_article(link)
        
        if body_text:
            article_data = {
                "newspaper": "The Indian Express",
                "title": title,
                "link": link,
                "timestamp": pub_date,
                "reading_time": reading_time,
                "passage": body_text,
                "length": len(body_text)
            }
            
            fallback_articles.append(article_data)
            
            if is_published_today(pub_date):
                valid_articles.append(article_data)
                
    # Smart Fallback: If strict today fails, use the fallback list
    target_list = valid_articles if len(valid_articles) > 0 else fallback_articles
    
    if len(valid_articles) == 0 and len(fallback_articles) > 0:
         print("⚠️ No Indian Express editorials found for strictly today. Using the latest available.")
    
    # Sort by length descending, grab top 2
    target_list.sort(key=lambda x: x["length"], reverse=True)
    top_2 = target_list[:2]
    
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
    
    # CRITICAL: ensure_ascii=False ensures punctuation like em-dashes and quotes stay native.
    with open('today_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
        
    print(f"✅ Successfully saved {len(all_editorials)} editorials to today_editorials.json")

if __name__ == "__main__":
    run()