import json
import re
import subprocess
from bs4 import BeautifulSoup
from readability import Document
from datetime import datetime, timezone, timedelta

# Indian Standard Time (IST)
IST = timezone(timedelta(hours=5, minutes=30))
TODAY_DATE = datetime.now(IST).date()

def fetch_html_curl(url):
    """
    Uses system cURL to bypass Python's HTTP fingerprint which Cloudflare blocks.
    Acts exactly like a normal browser request.
    """
    try:
        cmd = [
            "curl", "-sL", "--compressed",
            "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            url
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=20)
        html = result.stdout.decode('utf-8', errors='ignore')
        
        # Cloudflare block check
        if not html or "Just a moment..." in html or "Cloudflare" in html:
            print(f"⚠️ cURL blocked by firewall for {url}. Using proxy tunnel...")
            proxy_cmd = ["curl", "-sL", f"https://api.allorigins.win/raw?url={url}"]
            proxy_res = subprocess.run(proxy_cmd, capture_output=True, timeout=20)
            html = proxy_res.stdout.decode('utf-8', errors='ignore')
            
        return html
    except Exception as e:
        print(f"⚠️ Fetch error for {url}: {e}")
        return ""

def apply_speedreader(url):
    """Simulates Brave's Speedreader using Readability."""
    html = fetch_html_curl(url)
    if not html: return "", "", ""
    
    try:
        # Pass the raw HTML to the Readability engine
        doc = Document(html)
        raw_title = doc.title()
        clean_title = raw_title.split(' - ')[0].split(' | ')[0].strip()
        
        soup = BeautifulSoup(doc.summary(), 'html.parser')
        passage = soup.get_text(separator='\n\n', strip=True)
        
        # Calculate standard reading time
        words = len(passage.split())
        r_time = f"{max(1, round(words / 200))} min read"
        
        return clean_title, passage, r_time
    except Exception as e:
        print(f"⚠️ Speedreader error for {url}: {e}")
        return "", "", ""

def get_hindu_editorials():
    print("📰 Visiting The Hindu Front Page...")
    html = fetch_html_curl("https://www.thehindu.com/opinion/editorial/")
    soup = BeautifulSoup(html, 'html.parser')
    
    links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        # Fix relative links
        if href.startswith('/'):
            href = "https://www.thehindu.com" + href
            
        # Must be an editorial link, not the category page itself
        if '/opinion/editorial/' in href and href != "https://www.thehindu.com/opinion/editorial/" and href not in links:
            links.append(href)
            
    articles = []
    for link in links[:5]:
        title, passage, r_time = apply_speedreader(link)
        if passage and len(passage) > 300:
            articles.append({
                "newspaper": "The Hindu",
                "title": title,
                "link": link,
                "timestamp": str(TODAY_DATE), # Assuming top articles are today's
                "reading_time": r_time,
                "passage": passage
            })
        if len(articles) >= 2: break
        
    return articles

def get_indian_express_editorials():
    print("📰 Visiting The Indian Express Front Page...")
    html = fetch_html_curl("https://indianexpress.com/section/opinion/editorials/")
    soup = BeautifulSoup(html, 'html.parser')
    
    links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        # Fix relative links
        if href.startswith('/'):
            href = "https://indianexpress.com" + href
            
        # Must be a specific article link
        if '/article/opinion/editorials/' in href and href not in links:
            links.append(href)
            
    articles = []
    for link in links[:5]:
        title, passage, r_time = apply_speedreader(link)
        if passage and len(passage) > 300:
            articles.append({
                "newspaper": "The Indian Express",
                "title": title,
                "link": link,
                "timestamp": str(TODAY_DATE), 
                "reading_time": r_time,
                "passage": passage
            })
        if len(articles) >= 2: break
        
    return articles

def run():
    print(f"🚀 Starting Speedreader pipeline for {TODAY_DATE} (IST)...")
    
    all_editorials = []
    all_editorials.extend(get_hindu_editorials())
    all_editorials.extend(get_indian_express_editorials())
    
    output = {
        "date_scraped": str(TODAY_DATE),
        "total_articles": len(all_editorials),
        "editorials": all_editorials
    }
    
    # CRITICAL: ensure_ascii=False ensures em-dashes and quotes stay native UTF-8
    with open('today_editorials.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)
        
    print(f"✅ Successfully compiled {len(all_editorials)} editorials into today_editorials.json")

if __name__ == "__main__":
    run()