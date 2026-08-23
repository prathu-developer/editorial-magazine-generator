import requests
from bs4 import BeautifulSoup # type: ignore
from readability import Document # type: ignore
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

def get_indian_express_editorials():
    print("📰 Fetching The Indian Express...")

    listing_url = "https://indianexpress.com/section/editorials/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
    }

    try:
        resp = requests.get(
            listing_url,
            headers=headers,
            timeout=20
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

    except Exception as e:
        print(f"⚠️ Failed to fetch The Indian Express listing: {e}")
        return []

    articles = []
    seen_urls = set()

    # Current IE editorial listing is ordered newest → oldest.
    # Find editorial article links directly instead of relying on RSS.
    for a in soup.find_all("a", href=True):

        href = a.get("href", "").strip()

        if not href:
            continue

        # Only accept actual Indian Express editorial article URLs.
        if "/article/opinion/editorials/" not in href:
            continue

        if href.startswith("/"):
            href = "https://indianexpress.com" + href

        # Remove tracking/query parameters.
        href = href.split("?")[0]

        if href in seen_urls:
            continue

        title = a.get_text(" ", strip=True)

        # Ignore empty / navigation links.
        if not title or len(title) < 15:
            continue

        seen_urls.add(href)

        # Try to obtain the date from the surrounding card.
        parent = a.parent
        card_text = ""

        for _ in range(5):
            if parent is None:
                break

            text = parent.get_text(" ", strip=True)

            if re.search(
                r"(January|February|March|April|May|June|July|August|"
                r"September|October|November|December)\s+\d{1,2},\s+\d{4}",
                text,
                re.IGNORECASE
            ):
                card_text = text
                break

            parent = parent.parent

        date_match = re.search(
            r"(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+"
            r"\d{1,2},\s+\d{4}",
            card_text,
            re.IGNORECASE
        )

        # We don't rely entirely on the listing date.
        # The page itself is ordered newest-first.
        pub_date = date_match.group(0) if date_match else ""

        # Convert the page date into RFC-style text for consistency.
        if pub_date:
            try:
                dt = datetime.strptime(pub_date, "%B %d, %Y")
                dt = dt.replace(tzinfo=IST)
                pub_date = dt.strftime("%a, %d %b %Y %H:%M:%S +0530")
            except Exception:
                pass

        print(f"   🔎 Found: {title}")

        # Extract actual article body using your existing engine.
        text, r_time = scrape_speedreader_mode(href)

        if not text:
            print(f"   ⚠️ Body extraction failed: {href}")
            continue

        if len(text) <= 150:
            print(f"   ⚠️ Body too short: {href}")
            continue

        articles.append({
            "newspaper": "The Indian Express",
            "title": title,
            "link": href,
            "timestamp": pub_date,
            "reading_time": r_time,
            "passage": text,
        })

        # We only need the first two newest editorials.
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