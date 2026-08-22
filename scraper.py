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

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5'
}

def is_published_today(pub_date_str):
    """Safeguard: Verifies if the article was published today in IST."""
    try:
        dt = email.utils.parsedate_to_datetime(pub_date_str)
        dt_ist = dt.astimezone(IST)
        return dt_ist.date() == TODAY_DATE
    except Exception:
        try:
            # Fallback for ISO / SQL strings
            clean_str = re.sub(r'([+-]\d{2}):(\d{2})$', r'\1\2', pub_date_str)
            dt = datetime.fromisoformat(clean_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(IST).date() == TODAY_DATE
        except Exception:
            return False

def get_reading_time(html_content, text_body):
    """Extracts stated reading time or calculates standard 200 WPM."""
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
    en-dashes (–), semicolons (;), and smart quotation marks (“ ” ‘ ’).
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'utf-8'
        
        doc = Document(resp.text)
        soup = BeautifulSoup(doc.summary(), 'html.parser')
        
        text_body = soup.get_text(separator='\n\n', strip=True)
        reading_time = get_reading_time(resp.text, text_body)
        
        return text_body, reading_time
    except Exception as e:
        print(f"Scrape error for {url}: {e}")
        return "", ""

def parse_xml_items(xml_content):
    """Resiliently parses XML items across various namespaces and formats."""
    items = []
    try:
        soup = BeautifulSoup(xml_content, 'html.parser')
        for item in soup.find_all('item'):
            title_tag = item.find('title')
            link_tag = item.find('link')
            date_tag = item.find('pubdate') or item.find('pubDate')
            
            title = title_tag.get_text(strip=True) if title_tag else ""
            link = link_tag.get_text(strip=True) if link_tag else ""
            pub_date = date_tag.get_text(strip=True) if date_tag else ""
            
            # Extract standard clean URL if wrapped in CDATA/HTML
            if not link and item.find('guid'):
                link = item.find('guid').get_text(strip=True)
                
            if link and link.startswith("http"):
                items.append({'title': title, 'link': link, 'pubDate': pub_date})
    except Exception:
        pass
    return items

# ==========================================
# 1. THE HINDU EXTRACTION (2 Articles)
# ==========================================
def get_hindu_editorials():
    print("📰 Fetching The Hindu...")
    rss_url = "https://www.thehindu.com/opinion/editorial/feeder/default.rss"
    try:
        resp = requests.get(rss_url, headers=HEADERS, timeout=15)
        resp.encoding = 'utf-8'
        raw_items = parse_xml_items(resp.content)
    except Exception as e:
        print(f"⚠️ Failed to fetch The Hindu feed: {e}")
        raw_items = []
    
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

# ==========================================
# 2. THE INDIAN EXPRESS EXTRACTION (2 Articles)
# ==========================================
def get_indian_express_editorials():
    print("📰 Fetching The Indian Express...")
    scraped_pool = []
    
    # ── Attempt A: Direct Category Page Scraping (Bypasses RSS 403 blocks)
    try:
        cat_url = "https://indianexpress.com/section/opinion/editorials/"
        resp = requests.get(cat_url, headers=HEADERS, timeout=15)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        seen_links = set()
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/article/opinion/editorials/' in href and href not in seen_links:
                seen_links.add(href)
                title = a_tag.get_text(strip=True)
                
                body_text, reading_time = scrape_article_data(href)
                if body_text and len(body_text) > 300:
                    scraped_pool.append({
                        "newspaper": "The Indian Express",
                        "title": title or "Indian Express Editorial",
                        "link": href,
                        "timestamp": datetime.now(IST).strftime("%a, %d %b %Y %H:%M:%S +0530"),
                        "reading_time": reading_time,
                        "passage": body_text,
                        "length": len(body_text),
                        "is_today": True
                    })
                if len(scraped_pool) >= 3:
                    break
    except Exception as e:
        print(f"⚠️ Section scrape failed: {e}")

    # ── Attempt B: Google News Syndication RSS (Always reliable fallback)
    if len(scraped_pool) < 2:
        try:
            gn_url = "https://news.google.com/rss/search?q=site:indianexpress.com/article/opinion/editorials&hl=en-IN&gl=IN&ceid=IN:en"
            resp = requests.get(gn_url, headers=HEADERS, timeout=15)
            resp.encoding = 'utf-8'
            items = parse_xml_items(resp.content)
            
            for item in items[:4]:
                body_text, reading_time = scrape_article_data(item['link'])
                if body_text and len(body_text) > 300:
                    scraped_pool.append({
                        "newspaper": "The Indian Express",
                        "title": item['title'],
                        "link": item['link'],
                        "timestamp": item['pubDate'],
                        "reading_time": reading_time,
                        "passage": body_text,
                        "length": len(body_text),
                        "is_today": is_published_today(item['pubDate'])
                    })
        except Exception as e:
            print(f"⚠️ Google News fallback failed: {e}")

    # Prioritise today's articles, sort by length descending, and grab top 2
    today_pool = [a for a in scraped_pool if a.get("is_today")]
    target_pool = today_pool if len(today_pool) >= 2 else scraped_pool
    
    if len(today_pool) < 2:
        print("⚠️ The Indian Express: Using latest available editorials.")
        
    target_pool.sort(key=lambda x: x["length"], reverse=True)
    top_2 = target_pool[:2]
    
    for article in top_2:
        del article["length"]
        if "is_today" in article:
            del article["is_today"]
            
    return top_2

# ==========================================
# 3. PIPELINE RUNNER
# ==========================================
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
    
    # CRITICAL: ensure_ascii=False ensures em-dashes and smart quotes are preserved verbatim
    with open('today_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=4)
        
    print(f"✅ Successfully compiled {len(all_editorials)} editorials into today_editorials.json")

if __name__ == "__main__":
    run()