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

# CloudScraper engine configured with desktop browser fingerprints
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

def is_published_today(pub_date_str):
    """Checks if publication date matches today's date in IST."""
    try:
        dt = email.utils.parsedate_to_datetime(pub_date_str)
        dt_ist = dt.astimezone(IST)
        return dt_ist.date() == TODAY_DATE
    except Exception:
        try:
            # Fallback for ISO / SQL-like formats
            cleaned_date = re.sub(r'([+-]\d{2}):(\d{2})$', r'\1\2', pub_date_str)
            dt = datetime.fromisoformat(cleaned_date)
            if dt.tzinfo is None:
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
    """Fetches article body and reading time, preserving ALL punctuation strictly."""
    try:
        resp = scraper.get(url, timeout=15)
        resp.encoding = 'utf-8' # Preserves strict punctuation (—, –, “, ”, etc.)
        
        doc = Document(resp.text)
        soup = BeautifulSoup(doc.summary(), 'html.parser')
        
        text_body = soup.get_text(separator='\n\n', strip=True)
        reading_time = get_reading_time(resp.text, text_body)
        
        return text_body, reading_time
    except Exception as e:
        print(f"Scrape error for {url}: {e}")
        return "", ""

# ==========================================
# 1. THE HINDU EXTRACTION
# ==========================================
def get_hindu_editorials():
    print("📰 Fetching The Hindu...")
    rss_url = "https://www.thehindu.com/opinion/editorial/feeder/default.rss"
    try:
        resp = scraper.get(rss_url, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"⚠️ Failed to fetch The Hindu feed: {e}")
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

# ==========================================
# 2. THE INDIAN EXPRESS EXTRACTION
# ==========================================
def fetch_indian_express_rss():
    """Tries multiple proxy tunnels to download the Indian Express RSS feed."""
    rss_url = "https://indianexpress.com/section/opinion/editorials/feed/"
    proxy_urls = [
        f"https://api.allorigins.win/raw?url={requests.utils.quote(rss_url)}",
        f"https://corsproxy.io/?{requests.utils.quote(rss_url)}"
    ]
    
    for proxy in proxy_urls:
        try:
            resp = requests.get(proxy, timeout=15)
            if resp.status_code == 200 and b"<rss" in resp.content:
                return ET.fromstring(resp.content)
        except Exception:
            continue
    return None

def fetch_indian_express_html():
    """Direct fallback: Scrapes the Opinion/Editorials category page."""
    print("🔄 Switching to direct HTML section parser for Indian Express...")
    category_url = "https://indianexpress.com/section/opinion/editorials/"
    try:
        resp = scraper.get(category_url, timeout=15)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        articles = []
        seen_links = set()
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/article/opinion/editorials/' in href and href not in seen_links:
                seen_links.add(href)
                title = a_tag.get_text(strip=True)
                if len(title) > 20:
                    articles.append({"link": href, "title": title})
            if len(articles) >= 4:
                break
        return articles
    except Exception as e:
        print(f"⚠️ Direct HTML section scrape failed: {e}")
        return []

def get_indian_express_editorials():
    print("📰 Fetching The Indian Express...")
    root = fetch_indian_express_rss()
    
    valid_articles = []
    fallback_articles = []
    
    # Path A: Parse via RSS if proxy succeeded
    if root is not None:
        for item in root.findall('.//item'):
            pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
            link = item.find('link').text if item.find('link') is not None else ""
            title = item.find('title').text if item.find('title') is not None else ""
            
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
    
    # Path B: Direct HTML section scraping if RSS failed completely
    if len(valid_articles) == 0 and len(fallback_articles) == 0:
        html_articles = fetch_indian_express_html()
        for item in html_articles:
            body_text, reading_time = scrape_article(item["link"])
            if body_text:
                article_data = {
                    "newspaper": "The Indian Express",
                    "title": item["title"],
                    "link": item["link"],
                    "timestamp": str(datetime.now(IST).strftime("%a, %d %b %Y %H:%M:%S +0530")),
                    "reading_time": reading_time,
                    "passage": body_text,
                    "length": len(body_text)
                }
                fallback_articles.append(article_data)

    target_list = valid_articles if len(valid_articles) > 0 else fallback_articles
    
    if len(valid_articles) == 0 and len(fallback_articles) > 0:
        print("⚠️ No Indian Express editorials found for strictly today. Using latest available.")
    
    target_list.sort(key=lambda x: x["length"], reverse=True)
    top_2 = target_list[:2]
    
    for article in top_2:
        del article["length"]
        
    return top_2

# ==========================================
# 3. PIPELINE EXECUTION
# ==========================================
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
    
    # ensure_ascii=False ensures em-dashes and smart quotes stay native UTF-8
    with open('today_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
        
    print(f"✅ Successfully saved {len(all_editorials)} editorials to today_editorials.json")

if __name__ == "__main__":
    run()