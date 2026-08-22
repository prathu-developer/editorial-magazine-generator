import cloudscraper
import requests
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

# CloudScraper instance
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

def is_published_today(pub_date_str):
    """Checks if publication date matches today's date in IST across RSS/JSON formats."""
    try:
        # Standard RSS RFC 2822
        dt = email.utils.parsedate_to_datetime(pub_date_str)
        dt_ist = dt.astimezone(IST)
        return dt_ist.date() == TODAY_DATE
    except (TypeError, ValueError):
        try:
            # SQL format from rss2json
            dt = datetime.strptime(pub_date_str, "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
            dt_ist = dt.astimezone(IST)
            return dt_ist.date() == TODAY_DATE
        except Exception:
            return False

def clean_html_to_text(html_content):
    """Strips HTML tags while strictly preserving em-dashes, quotes, and punctuation."""
    soup = BeautifulSoup(html_content, 'html.parser')
    for elem in soup(["script", "style", "nav", "header", "footer", "aside"]):
        elem.extract()
    return soup.get_text(separator='\n\n', strip=True)

def get_reading_time(html_content, text_body):
    """Extracts explicit reading time or calculates standard 200 WPM."""
    soup = BeautifulSoup(html_content, 'html.parser')
    rt_match = soup.find(string=re.compile(r'\b\d+\s*min(ute)?s?\s*read\b', re.IGNORECASE))
    if rt_match:
        return rt_match.strip()
        
    word_count = len(text_body.split())
    minutes = max(1, round(word_count / 200))
    return f"{minutes} min read (Calculated)"

def scrape_article(url):
    """Fetches clean text directly from the web page."""
    try:
        resp = scraper.get(url, timeout=15)
        resp.encoding = 'utf-8' # Preserves strict punctuation
        
        doc = Document(resp.text)
        soup = BeautifulSoup(doc.summary(), 'html.parser')
        
        text_body = soup.get_text(separator='\n\n', strip=True)
        reading_time = get_reading_time(resp.text, text_body)
        
        return text_body, reading_time
    except Exception:
        return "", ""

def get_hindu_editorials():
    print("📰 Fetching The Hindu...")
    rss_url = "https://www.thehindu.com/opinion/editorial/feeder/default.rss"
    try:
        resp = scraper.get(rss_url, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"⚠️ Failed to fetch The Hindu: {e}")
        return []
    
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
            fallback_editorials.append(article_data)
            
            if is_published_today(pub_date):
                editorials.append(article_data)
                
            if len(editorials) >= 2:
                break
                
    if len(editorials) == 0 and len(fallback_editorials) > 0:
        print("⚠️ No Hindu editorials found for strictly today. Using latest available.")
        return fallback_editorials[:2]
        
    return editorials

def get_indian_express_editorials():
    print("📰 Fetching The Indian Express (via Proxy API)...")
    rss_url = "https://indianexpress.com/section/opinion/editorials/feed/"
    api_url = f"https://api.rss2json.com/v1/api.json?rss_url={rss_url}"
    
    try:
        resp = requests.get(api_url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        items = data.get('items', [])
    except Exception as e:
        print(f"⚠️ Indian Express proxy request failed: {e}")
        return []
    
    valid_articles = []
    fallback_articles = []
    
    for item in items:
        pub_date = item.get('pubDate', '')
        link = item.get('link', '')
        title = item.get('title', '')
        
        # 1. Attempt standard page scraping
        body_text, reading_time = scrape_article(link)
        
        # 2. Fallback to RSS feed payload if page access is 403-blocked
        if not body_text:
            raw_content = item.get('content') or item.get('description', '')
            body_text = clean_html_to_text(raw_content)
            reading_time = get_reading_time(raw_content, body_text)
            
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
                
    target_list = valid_articles if len(valid_articles) > 0 else fallback_articles
    
    if len(valid_articles) == 0 and len(fallback_articles) > 0:
        print("⚠️ No Indian Express editorials found for strictly today. Using latest available.")
    
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
    
    with open('today_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
        
    print(f"✅ Successfully saved {len(all_editorials)} editorials to today_editorials.json")

if __name__ == "__main__":
    run()