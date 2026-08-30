import os
import json
import re
import hashlib
from datetime import datetime, timezone, timedelta, date
from urllib.parse import urljoin, quote_plus, urlparse

from bs4 import BeautifulSoup
from readability import Document
from curl_cffi import requests

IST = timezone(timedelta(hours=5, minutes=30))
NOW_IST = datetime.now(IST)
TODAY_DATE = NOW_IST.date()

SCRAPINGANT_KEY = os.getenv("SCRAPINGANT_API_KEY", "").strip()
HISTORY_FILE = "editorial_history.json"
OUTPUT_FILE = "additional_editorials.json"

session = requests.Session(impersonate="chrome124")

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

SOURCES = [
    {
        "key": "new_indian_express",
        "name": "The New Indian Express",
        "category": "Editorial",
        "listing_urls": ["https://www.newindianexpress.com/editorial"],
        "link_patterns": [r"/editorial/"],
        "content_selectors": ["div[itemprop='articleBody']", ".article-detail", ".field-name-body", ".article_body"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "pioneer",
        "name": "The Pioneer",
        "category": "Opinion",
        "listing_urls": ["https://dailypioneer.com/category/opinion"],
        "link_patterns": [r"/.*\.html$", r"/.*opinion.*"],
        "content_selectors": [".story-details", ".main-content", ".article-detail", "div[itemprop='articleBody']"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "statesman",
        "name": "The Statesman",
        "category": "Opinion",
        "listing_urls": ["https://www.thestatesman.com/opinion"],
        "link_patterns": [r"/opinion/"],
        "content_selectors": ["div[itemprop='articleBody']", ".td-post-content", ".article-content", ".single-post-content"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "telegraph_india",
        "name": "The Telegraph India",
        "category": "Opinion",
        "listing_urls": ["https://www.telegraphindia.com/opinion"],
        "link_patterns": [r"/opinion/", r"/india/"],
        "content_selectors": ["div[itemprop='articleBody']", ".article-body", ".story-body", ".article-content"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "deccan_herald",
        "name": "Deccan Herald",
        "category": "Editorial/Opinion",
        "listing_urls": ["https://www.deccanherald.com/opinion/editorial"],
        "link_patterns": [r"/opinion/", r"/editorial"],
        "content_selectors": ["div[itemprop='articleBody']", ".content-body", ".story-content", ".article-body"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "businessline",
        "name": "BusinessLine",
        "category": "Opinion",
        "listing_urls": ["https://www.thehindubusinessline.com/opinion/"],
        "link_patterns": [r"/opinion/"],
        "content_selectors": ["div[itemprop='articleBody']", ".articleBody", ".article-body", ".story-content"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "financial_express",
        "name": "Financial Express",
        "category": "Opinion",
        "listing_urls": ["https://www.financialexpress.com/opinion/"],
        "link_patterns": [r"/opinion/"],
        "content_selectors": ["div[itemprop='articleBody']", ".article-content", ".content-area", ".story-content"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "guardian",
        "name": "The Guardian",
        "category": "Opinion",
        "listing_urls": ["https://www.theguardian.com/commentisfree"],
        "link_patterns": [r"/commentisfree/"],
        "content_selectors": ["div.article-body-commercial-selector", "div[itemprop='articleBody']", ".article-body-view"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "aljazeera",
        "name": "Al Jazeera",
        "category": "Opinion/Analysis",
        "listing_urls": ["https://www.aljazeera.com/opinions/"],
        "link_patterns": [r"/opinions/"],
        "content_selectors": ["div.wysiwyg", "div.article-body", "div[itemprop='articleBody']", ".article__content"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "conversation",
        "name": "The Conversation",
        "category": "Expert Analysis",
        "listing_urls": ["https://theconversation.com/global/topics/india-180", "https://theconversation.com/global"],
        "link_patterns": [r"https://theconversation\.com/", r"/"],
        "content_selectors": ["div.grid--cols-1", "div[itemprop='articleBody']", ".article-body", ".content"],
        "max_candidates": 20,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "theprint",
        "name": "ThePrint",
        "category": "Opinion/Analysis",
        "listing_urls": ["https://theprint.in/category/opinion/"],
        "link_patterns": [r"/opinion/"],
        "content_selectors": ["div[itemprop='articleBody']", ".td-post-content", ".article-content", ".entry-content"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "scroll",
        "name": "Scroll.in",
        "category": "Opinion/Analysis",
        "listing_urls": ["https://scroll.in/topic/opinion"],
        "link_patterns": [r"/article/", r"/topic/opinion"],
        "content_selectors": ["div[itemprop='articleBody']", ".story-details", ".article-body", ".content"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "wire",
        "name": "The Wire",
        "category": "Opinion/Analysis",
        "listing_urls": ["https://thewire.in/opinion"],
        "link_patterns": [r"/opinion/"],
        "content_selectors": ["div[itemprop='articleBody']", ".article-body", ".field-name-body", ".content"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "firstpost",
        "name": "Firstpost",
        "category": "Opinion/Analysis",
        "listing_urls": ["https://www.firstpost.com/opinion"],
        "link_patterns": [r"/opinion/"],
        "content_selectors": ["div[itemprop='articleBody']", ".article-full-content", ".story-content", ".main-content"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "quint",
        "name": "The Quint",
        "category": "Opinion/Analysis",
        "listing_urls": ["https://www.thequint.com/opinion"],
        "link_patterns": [r"/opinion/"],
        "content_selectors": ["div[itemprop='articleBody']", ".story-content", ".article-body", ".story-page-content"],
        "max_candidates": 25,
        "max_articles": 8,
        "use_scrapingant": False,
        "enabled": True,
    },
    {
        "key": "economic_times",
        "name": "Economic Times",
        "category": "Opinion",
        "listing_urls": ["https://economictimes.indiatimes.com/opinion/editorial"],
        "link_patterns": [r"/opinion/editorial/"],
        "content_selectors": ["div.artText", "div[itemprop='articleBody']", ".article-content", ".artText"],
        "max_candidates": 20,
        "max_articles": 6,
        "use_scrapingant": True,
        "enabled": True,
    },
]


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("seen_ids", []))
        except Exception:
            return set()
    return set()


def save_history(history_set):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump({"seen_ids": sorted(list(history_set))}, f, indent=2)


def same_domain(url, root_url):
    try:
        return urlparse(url).netloc == urlparse(root_url).netloc
    except Exception:
        return True


def fetch_page(url, use_scrapingant=False):
    target_url = url
    if use_scrapingant and SCRAPINGANT_KEY:
        target_url = (
            "https://api.scrapingant.com/v2/general"
            f"?url={quote_plus(url)}&x-api-key={SCRAPINGANT_KEY}&browser=false"
        )
    try:
        response = session.get(target_url, headers=HEADERS, timeout=30, allow_redirects=True)
        if response.status_code == 200 and response.text:
            return response.text
        print(f"    ⚠️ HTTP {response.status_code}: {url}")
    except Exception as e:
        print(f"    ⚠️ Fetch error: {url} -> {e}")
    return ""


def parse_datetime_value(value):
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except Exception:
        pass

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d %b %Y, %I:%M %p",
        "%d %B %Y, %I:%M %p",
        "%d %b %Y %I:%M %p",
        "%d %B %Y %I:%M %p",
        "%b %d, %Y, %I:%M %p",
        "%B %d, %Y, %I:%M %p",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(value[:40], fmt)
            return parsed.replace(tzinfo=IST)
        except Exception:
            continue

    match = re.search(r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d{2})", value, re.I)
    if match:
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(match.group(1), fmt).replace(tzinfo=IST)
            except Exception:
                pass
    return None


def extract_published_date(html, url=""):
    soup = BeautifulSoup(html, "html.parser")

    meta_names = {
        "article:published_time", "publish-date", "datepublished", "datepublishedtime",
        "parsely-pub-date", "article:published", "publishdate", "pubdate",
        "dc.date", "dcterms.date", "datecreated", "date"
    }
    for meta in soup.find_all("meta"):
        prop = (meta.get("property") or meta.get("name") or meta.get("itemprop") or "").lower().strip()
        if prop in meta_names:
            dt = parse_datetime_value(meta.get("content"))
            if dt:
                return dt.date(), dt.isoformat()

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            raw = script.string or script.get_text()
            data = json.loads(raw)
            stack = data if isinstance(data, list) else [data]
            for item in stack:
                if not isinstance(item, dict):
                    continue
                for key in ("datePublished", "dateCreated"):
                    if key in item:
                        dt = parse_datetime_value(item[key])
                        if dt:
                            return dt.date(), dt.isoformat()
        except Exception:
            continue

    for tag in soup.select("time[datetime], meta[itemprop='datePublished']"):
        raw = tag.get("datetime") or tag.get("content") or tag.get_text(" ", strip=True)
        dt = parse_datetime_value(raw)
        if dt:
            return dt.date(), dt.isoformat()

    url_match = re.search(r"/(\d{4})[/-](\d{1,2})[/-](\d{1,2})", url)
    if url_match:
        try:
            y, m, d = map(int, url_match.groups())
            dt = datetime(y, m, d, tzinfo=IST)
            return dt.date(), dt.isoformat()
        except Exception:
            pass

    return None, None


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def extract_clean_paragraphs(container):
    if not container:
        return ""
    container = BeautifulSoup(str(container), "html.parser")
    for unwanted in container.find_all(["script", "style", "aside", "figure", "button", "iframe", "nav", "form"]):
        unwanted.decompose()
    for ad in container.find_all(class_=re.compile(r"ad-|ad_|newsletter|social|also-read|comment|related|subscribe", re.I)):
        ad.decompose()

    paragraphs = []
    for p in container.find_all("p"):
        text = clean_text(p.get_text(" ", strip=True))
        if not text or len(text) < 25:
            continue
        if re.match(r"^(published|updated|first published|last updated)\s*[-:]", text, re.I):
            continue
        if text.lower() in {"advertisement", "read more", "also read"}:
            continue
        paragraphs.append(text)

    seen = set()
    unique = []
    for p in paragraphs:
        key = re.sub(r"\W+", "", p.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return "\n\n".join(unique)


def extract_article_content(html, selectors):
    soup = BeautifulSoup(html, "html.parser")
    for selector in selectors:
        try:
            container = soup.select_one(selector)
        except Exception:
            container = None
        if container:
            text = extract_clean_paragraphs(container)
            if len(text) > 300:
                return text

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
            stack = data if isinstance(data, list) else [data]
            for item in stack:
                if isinstance(item, dict) and item.get("articleBody"):
                    body = item["articleBody"].strip()
                    if len(body) > 300:
                        return body
        except Exception:
            continue

    try:
        doc = Document(html)
        summary = BeautifulSoup(doc.summary(), "html.parser")
        text = extract_clean_paragraphs(summary)
        if len(text) > 300:
            return text
    except Exception:
        pass
    return ""


def extract_title(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    raw = h1.get_text(" ", strip=True) if h1 else ""
    if not raw:
        for meta_key in ["og:title", "twitter:title"]:
            tag = soup.find("meta", attrs={"property": meta_key}) or soup.find("meta", attrs={"name": meta_key})
            if tag and tag.get("content"):
                raw = tag["content"].strip()
                break
    if not raw:
        try:
            raw = Document(html).title()
        except Exception:
            raw = ""
    raw = clean_text(raw)
    raw = re.sub(r"\s+[|–—-]\s+(The Guardian|Al Jazeera|The New Indian Express|The Pioneer).*$", "", raw, flags=re.I)
    raw = re.sub(r"^(Opinion|Editorial|Analysis)\s*[:|-]\s*", "", raw, flags=re.I)
    return raw.strip()


def get_links_from_listing(html, source, listing_url):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href:
            continue
        url = urljoin(listing_url, href)
        if not url.startswith(("http://", "https://")):
            continue
        if any(re.search(p, url, re.I) for p in source.get("link_patterns", [])):
            key = url.rstrip("/")
            if key not in seen and same_domain(url, listing_url):
                seen.add(key)
                links.append(url)
    return links


def is_probably_article(url):
    bad = ["/author/", "/tag/", "/category/", "/topic/", "/search", "/page/", "#", "/video/", "/gallery/"]
    return not any(x in url.lower() for x in bad)


def fingerprint(source_name, title, url):
    raw = f"{source_name}|{title.lower().strip()}|{url.lower().strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def scrape_source(source, history_ids):
    print(f"\n📰 {source['name']} ({source['category']})")
    candidates = []
    seen = set()

    for listing_url in source["listing_urls"]:
        html = fetch_page(listing_url, source.get("use_scrapingant", False))
        if not html:
            continue
        links = get_links_from_listing(html, source, listing_url)
        for link in links:
            if not is_probably_article(link):
                continue
            key = link.rstrip("/")
            if key not in seen:
                seen.add(key)
                candidates.append(link)

    print(f"    Found {len(candidates)} candidate links across listing pages")

    inspected_articles = []
    for link in candidates[: source.get("max_candidates", 25)]:
        html = fetch_page(link, source.get("use_scrapingant", False))
        if not html:
            continue

        pub_date, iso_timestamp = extract_published_date(html, link)
        if not pub_date:
            continue

        title = extract_title(html)
        if not title:
            continue

        art_id = fingerprint(source["name"], title, link)
        if art_id in history_ids:
            continue

        passage = extract_article_content(html, source.get("content_selectors", []))
        if len(passage) < 300:
            continue

        words = len(passage.split())
        if words < 120:
            continue

        inspected_articles.append({
            "source": source["name"],
            "type": source["category"],
            "title": title,
            "link": link,
            "timestamp": iso_timestamp,
            "pub_date": pub_date,
            "reading_time": f"{max(1, round(words / 200))} min read",
            "passage": passage,
            "word_count": words,
            "id": art_id,
        })

    if not inspected_articles:
        print("    ⚠️ No new valid articles parsed.")
        return []

    latest_pub_date = max(item["pub_date"] for item in inspected_articles)
    print(f"    🎯 Latest publication date available: {latest_pub_date.isoformat()}")

    selected = [
        item for item in inspected_articles if item["pub_date"] == latest_pub_date
    ]

    selected.sort(key=lambda x: x["word_count"], reverse=True)
    max_count = source.get("max_articles", 8)
    final_articles = selected[:max_count]

    for item in final_articles:
        item["target_editorial_date"] = item.pop("pub_date").isoformat()
        item.pop("word_count", None)
        print(f"    ✓ [{item['target_editorial_date']}] {item['title'][:70]}")

    print(f"    ✅ Selected all {len(final_articles)} article(s) for {latest_pub_date.isoformat()}")
    return final_articles


def run():
    print(f"🚀 Starting Editorial Collector at {NOW_IST.isoformat()}")

    history_ids = load_history()
    print(f"💾 Loaded {len(history_ids)} historical article ID(s)")

    requested = {x.strip().lower() for x in os.getenv("EDITORIAL_SOURCES", "").split(",") if x.strip()}
    active_sources = [s for s in SOURCES if s.get("enabled", True)]
    if requested:
        active_sources = [s for s in active_sources if s["key"].lower() in requested]

    all_articles = []
    source_stats = []
    new_seen_ids = set(history_ids)

    for source in active_sources:
        try:
            articles = scrape_source(source, history_ids)
            for art in articles:
                new_seen_ids.add(art["id"])
                all_articles.append(art)

            source_stats.append({
                "source": source["name"],
                "category": source["category"],
                "articles": len(articles),
                "latest_date": articles[0]["target_editorial_date"] if articles else None,
                "status": "ok" if articles else "no_new_articles",
            })
        except Exception as exc:
            print(f"    ❌ Error on {source['name']}: {exc}")
            source_stats.append({
                "source": source["name"],
                "category": source["category"],
                "articles": 0,
                "latest_date": None,
                "status": "error",
                "error": str(exc),
            })

    output = {
        "run_timestamp": NOW_IST.isoformat(),
        "timezone": "Asia/Kolkata",
        "total_articles": len(all_articles),
        "sources": source_stats,
        "editorials": all_articles,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    save_history(new_seen_ids)

    print("\n📊 RUN SUMMARY")
    for item in source_stats:
        date_str = f"({item['latest_date']})" if item["latest_date"] else ""
        print(f"  {item['source']}: {item['articles']} articles {date_str} [{item['status']}]")
    print(f"\n✅ Output written to {OUTPUT_FILE} and updated {HISTORY_FILE}")


if __name__ == "__main__":
    run()
