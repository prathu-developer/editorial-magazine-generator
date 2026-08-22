import requests
from bs4 import BeautifulSoup
from readability import Document
import json
import re
from datetime import datetime, timezone, timedelta

# Indian Standard Time (IST)
IST = timezone(timedelta(hours=5, minutes=30))
TODAY_DATE = datetime.now(IST).date()

# Standard browser headers to access the category pages
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9'
}

def brave_speedreader_mode(url):
    """
    Acts exactly like Brave Browser's Speedreader.
    Strips away all website junk and returns the clean title and passage.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'utf-8' # Preserves strict punctuation (—, ”, etc.)
        
        # 1. Pass the raw HTML to the Readability engine
        doc = Document(resp.text)
        raw_title = doc.title()
        
        # 2. Clean up the title (Remove " - The Hindu" etc.)
        clean_title = raw_title.split(' - ')[0].split(' | ')[0].strip()
        
        # 3. Extract the clean passage
        soup = BeautifulSoup(doc.summary(), 'html.parser')
        passage = soup.get_text(separator='\n\n', strip=True)
        
        # 4. Calculate reading time
        word_count = len(passage.split())
        r_time = f"{max(1, round(word_count / 200))} min read"
            
        return clean_title, passage, r_time
    except Exception as e:
        print(f"Speedreader error for {url}: {e}")
        return "", "", ""

def get_hindu_editorials():
    print("📰 Visiting The Hindu Category Page...")
    category_url = "https://www.thehindu.com/opinion/editorial/"
    
    try:
        resp = requests.get(category_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Scrape all unique editorial links from the page
        links = []
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            # Only grab article links, ignore the main page URL
            if '/opinion/editorial/' in href and href != category_url and href not in links:
                links.append(href)
                
    except Exception as e:
        print(f"⚠️ Failed to load The Hindu page: {e}")
        return []

    # Process the top 2 articles through the Speedreader
    articles = []
    for link in links[:2]:
        title, passage, r_time = brave_speedreader_mode(link)
        if passage:
            articles.append({
                "newspaper": "The Hindu",
                "title": title,
                "link": link,
                "timestamp": str(TODAY_DATE), # Assuming top articles are today's
                "reading_time": r_time,
                "passage": passage
            })
    return articles

def get_indian_express_editorials():
    print("📰 Visiting The Indian Express Category Page...")
    category_url = "https://indianexpress.com/section/opinion/editorials/"
    
    try:
        resp = requests.get(category_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Scrape all unique editorial links
        links = []
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/article/opinion/editorials/' in href and href not in links:
                links.append(href)
                
    except Exception as e:
        print(f"⚠️ Failed to load The Indian Express page: {e}")
        return []

    # Process the top 2 articles through the Speedreader
    articles = []
    for link in links[:2]:
        title, passage, r_time = brave_speedreader_mode(link)
        if passage and len(passage) > 200: # Ensure we didn't scrape a blank page
            articles.append({
                "newspaper": "The Indian Express",
                "title": title,
                "link": link,
                "timestamp": str(TODAY_DATE), 
                "reading_time": r_time,
                "passage": passage
            })
    return articles

def run():
    print(f"🚀 Starting front-door scraper for {TODAY_DATE} (IST)...")
    
    all_editorials = []
    all_editorials.extend(get_hindu_editorials())
    all_editorials.extend(get_indian_express_editorials())
    
    output_payload = {
        "date_scraped": str(TODAY_DATE),
        "total_articles": len(all_editorials),
        "editorials": all_editorials
    }
    
    with open('today_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=4)
        
    print(f"✅ Successfully compiled {len(all_editorials)} editorials into today_editorials.json")

if __name__ == "__main__":
    run()