import requests
from bs4 import BeautifulSoup # type: ignore
from readability import Document # type: ignore
import json
import re
from datetime import datetime, timezone, timedelta
import email.utils
from googlenewsdecoder import gnewsdecoder # type: ignore

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
        resp.encoding = resp.apparent_encoding or resp.encoding
        
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

def resolve_google_news_url(google_url):
    """Resolve a Google News RSS URL to the original publisher URL."""
    try:
        result = gnewsdecoder(
            google_url,
            interval=1
        )

        if result and result.get("status"):
            return result.get("decoded_url", "")

        print(
            f"      ⚠️ Google decoder failed: "
            f"{result.get('message', 'unknown error') if result else 'no result'}"
        )
        return ""

    except Exception as e:
        print(f"      ⚠️ Google URL resolution failed: {e}")
        return ""

def get_indian_express_editorials():
    print("📰 Fetching The Indian Express...")

    rss_url = (
        "https://news.google.com/rss/search?"
        "q=site%3Aindianexpress.com%2Farticle%2Fopinion%2Feditorials%2F"
        "&hl=en-IN&gl=IN&ceid=IN%3Aen"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-IN,en;q=0.9",
    }

    try:
        resp = requests.get(rss_url, headers=headers, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")

        print(f"   📡 Google News items found: {len(items)}")

    except Exception as e:
        print(f"⚠️ Failed to fetch Indian Express discovery feed: {e}")
        return []

    articles = []
    seen_urls = set()

    for item in items:

        title_tag = item.find("title")
        link_tag = item.find("link")
        source_tag = item.find("source")
        pub_date_tag = item.find("pubDate")

        title = title_tag.get_text(strip=True) if title_tag else ""
        google_link = link_tag.get_text(strip=True) if link_tag else ""
        source = source_tag.get_text(strip=True) if source_tag else ""
        pub_date = pub_date_tag.get_text(strip=True) if pub_date_tag else ""

        # Only accept The Indian Express results.
        if source.lower() != "the indian express":
            continue

        if not google_link:
            continue

        print(f"   🔎 {title}")
        print(f"      Source: {source}")
        print(f"      Google URL: {google_link}")

        # Resolve Google News redirect to the real article URL.
        real_url = resolve_google_news_url(google_link)

        if not real_url:
            print("      ⚠️ Could not resolve URL")
            continue

        print(f"      Real URL: {real_url}")

        # Verify the final destination is actually Indian Express.
        if "indianexpress.com" not in real_url:
            print("      ⚠️ Final URL is not Indian Express")
            continue

        if "/article/opinion/editorials/" not in real_url:
            print("      ⚠️ Not an editorial URL")
            continue

        if real_url in seen_urls:
            continue

        seen_urls.add(real_url)

        # Extract article content using existing engine.
        text, r_time = scrape_speedreader_mode(real_url)

        if not text:
            print("      ⚠️ Article body extraction failed")
            continue

        if len(text) <= 150:
            print(f"      ⚠️ Body too short ({len(text)} chars)")
            continue

        articles.append({
            "newspaper": "The Indian Express",
            "title": title,
            "link": real_url,
            "timestamp": pub_date,
            "reading_time": r_time,
            "passage": text
        })

        print(f"      ✅ Extracted {len(text)} characters")

        if len(articles) >= 2:
            break

    if len(articles) == 0:
        print("⚠️ The Indian Express: 0 editorials extracted.")
    else:
        print(
            f"✅ The Indian Express: "
            f"{len(articles)} editorials extracted."
        )

    return articles

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