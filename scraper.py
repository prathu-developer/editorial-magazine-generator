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

# Standard headers matching your working environment
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
    """Extracts explicit reading time or calculates standard 200 WPM."""
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
    CRITICAL: resp.encoding = 'utf-8' strictly preserves all em-dashes (—),
    en-dashes (–), semicolons (;), and smart quotation marks.
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

def parse_rss_items(xml_content):
    """Parses XML resiliently using BeautifulSoup and regex fallbacks."""
    items = []
    
    # 1. Try tolerant XML parser
    try:
        soup = BeautifulSoup(xml_content, 'xml')
        for item in soup.find_all('item'):
            title = item.find('title').get_text(strip=True) if item.find('title') else ""
            link = item.find('link').get_text(strip=True) if item.find('link') else ""
            pub_date = item.find('pubDate').get_text(strip=True) if item.find('pubDate') else ""
            if link:
                items.append({'title': title, 'link': link, 'pubDate': pub_date})
    except Exception:
        pass
        
    # 2. Regex fallback if XML structure is corrupted
    if not items:
        raw_text = xml_content.decode('utf-8', errors='ignore') if isinstance(xml_content, bytes) else xml_content
        raw_items = re.findall(r'<item>(.*?)</item>', raw_text, re.DOTALL)
        for item_str in raw_items:
            title_m = re.search(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', item_str, re.DOTALL)
            link_m = re.search(r'<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>', item_str, re.DOTALL)
            date_m = re.search(r'<pubDate>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</pubDate>', item_str, re.DOTALL)
            
            link = link_m.group(1).strip() if link_m else ""
            title = title_m.group(1).strip() if title_m else ""
            pub_date = date_m.group(1).strip() if date_m else ""
            
            if link:
                items.append({'title': title, 'link': link, 'pubDate': pub_date})
                
    return items

def get_hindu_editorials():
    print("📰 Fetching The Hindu...")
    rss_url = "https://www.thehindu.com/opinion/editorial/feeder/default.rss"
    try:
        resp = requests.get(rss_url, headers=HEADERS_DEFAULT, timeout=15)
        raw_items = parse_rss_items(resp.content)
    except Exception as e:
        print(f"⚠️ Error fetching The Hindu feed: {e}")
        return []
    
    today_articles = []
    fallback_articles = []
    
    for item in raw_items:
        pub_date = item['pubDate']
        link = item['link']
        title = item['title']
        
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
                
    if len(today_articles) >= 2:
        return today_articles[:2]
    
    print("⚠️ The Hindu: Today's editorials not published yet. Using latest available.")
    return fallback_articles[:2]

def get_indian_express_editorials():
    print("📰 Fetching The Indian Express...")
    rss_url = "https://indianexpress.com/section/opinion/editorials/feed/"
    try:
        resp = requests.get(rss_url, headers=HEADERS_DEFAULT, timeout=15)
        raw_items = parse_rss_items(resp.content)
    except Exception as e:
        print(f"⚠️ Error fetching The Indian Express feed: {e}")
        return []
    
    scraped_pool = []
    for item in raw_items[:4]:
        pub_date = item['pubDate']
        link = item['link']
        title = item['title']
        
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
            
    today_pool = [a for a in scraped_pool if a["is_today"]]
    target_pool = today_pool if len(today_pool) >= 2 else scraped_pool
    
    if len(today_pool) < 2:
        print("⚠️ The Indian Express: Today's editorials not published yet. Using latest available.")
        
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
    
    # ensure_ascii=False guarantees raw UTF-8 output for punctuation preservation
    with open('today_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=4)
        
    print(f"✅ Successfully compiled {len(all_editorials)} editorials into today_editorials.json")

if __name__ == "__main__":
    run()