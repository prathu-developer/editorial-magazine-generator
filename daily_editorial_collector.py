import os
import json
import re
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, quote_plus, urlparse

from bs4 import BeautifulSoup
from readability import Document
from curl_cffi import requests

IST = timezone(timedelta(hours=5, minutes=30))
NOW_IST = datetime.now(IST)
TODAY_DATE = NOW_IST.date()
LOOKBACK_HOURS = 24

SCRAPINGANT_KEY = os.getenv("SCRAPINGANT_API_KEY", "").strip()

session = requests.Session(impersonate="chrome124")

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

# NOTE:
# - enabled=True means the source is included in the daily run.
# - selectors are intentionally broad because publishers change HTML frequently.
# - category is preserved in JSON so your magazine can distinguish Editorial/Opinion/Analysis.
SOURCES = [
    {
        "key": "new_indian_express",
        "name": "The New Indian Express",
        "category": "Editorial",
        "listing_urls": ["https://www.newindianexpress.com/editorial"],
        "link_patterns": [r"/editorial/"],
        "content_selectors": [
            "div[itemprop='articleBody']", ".article-detail", ".field-name-body", ".article_body"
        ],
        "max_candidates": 12,
        "max_articles": 6,
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
        "max_candidates": 12,
        "max_articles": 5,
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
        "max_candidates": 12,
        "max_articles": 5,
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
        "max_candidates": 12,
        "max_articles": 5,
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
        "max_candidates": 12,
        "max_articles": 5,
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
        "max_candidates": 12,
        "max_articles": 5,
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
        "max_candidates": 12,
        "max_articles": 5,
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
        "max_candidates": 15,
        "max_articles": 6,
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
        "max_candidates": 15,
        "max_articles": 6,
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
        "max_candidates": 10,
        "max_articles": 4,
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
        "max_candidates": 12,
        "max_articles": 5,
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
        "max_candidates": 12,
        "max_articles": 5,
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
        "max_candidates": 12,
        "max_articles": 5,
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
        "max_candidates": 12,
        "max_articles": 5,
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
        "max_candidates": 12,
        "max_articles": 5,
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
        "max_candidates": 10,
        "max_articles": 4,
        "use_scrapingant": True,
        "enabled": True,
    },
]


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
    """Parse common publication timestamp formats and return IST-aware datetime."""
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
        "%d %b %Y, %I:%M %p",
        "%d %B %Y, %I:%M %p",
        "%d %b %Y %I:%M %p",
        "%d %B %Y %I:%M %p",
        "%b %d, %Y, %I:%M %p",
        "%B %d, %Y, %I:%M %p",
        "%b %d, %Y %I:%M %p",
        "%B %d, %Y %I:%M %p",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value[:80], fmt).replace(tzinfo=IST)
        except Exception:
            continue

    patterns = (
        r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d{2},?\s+\d{1,2}:\d{2}\s*(?:AM|PM))",
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+20\d{2},?\s+\d{1,2}:\d{2}\s*(?:AM|PM))",
    )
    for pattern in patterns:
        match = re.search(pattern, value, re.I)
        if not match:
            continue
        candidate = re.sub(r"\s+", " ", match.group(1)).replace(" ,", ",")
        for fmt in formats[:8]:
            try:
                return datetime.strptime(candidate, fmt).replace(tzinfo=IST)
            except Exception:
                continue
    return None


def extract_published_at(html):
    """Extract a precise publication datetime. Date-only metadata is intentionally ignored."""
    soup = BeautifulSoup(html, "html.parser")

    meta_names = {
        "article:published_time", "publish-date", "datepublished", "datepublishedtime",
        "parsely-pub-date", "article:published", "publishdate", "pubdate",
        "dc.date", "dcterms.date", "datecreated"
    }
    for meta in soup.find_all("meta"):
        prop = (meta.get("property") or meta.get("name") or meta.get("itemprop") or "").lower().strip()
        if prop in meta_names:
            dt = parse_datetime_value(meta.get("content"))
            if dt:
                return dt

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
                            return dt
        except Exception:
            continue

    for tag in soup.select("time[datetime], meta[itemprop='datePublished']"):
        raw = tag.get("datetime") or tag.get("content") or tag.get_text(" ", strip=True)
        dt = parse_datetime_value(raw)
        if dt:
            return dt

    # Last resort: only accept a timestamp explicitly associated with "published".
    text = soup.get_text(" ", strip=True)
    patterns = (
        r"published(?:\s+on|\s*:|\s*-)?\s*(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d{2},?\s+\d{1,2}:\d{2}\s*(?:AM|PM))",
        r"published(?:\s+on|\s*:|\s*-)?\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+20\d{2},?\s+\d{1,2}:\d{2}\s*(?:AM|PM))",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            dt = parse_datetime_value(match.group(1))
            if dt:
                return dt
    return None


def is_within_last_24_hours(published_at):
    if not published_at:
        return False
    age = NOW_IST - published_at
    return timedelta(0) <= age <= timedelta(hours=LOOKBACK_HOURS)


def clean_text(text):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


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

    # De-duplicate repeated paragraphs while retaining order.
    seen = set()
    unique = []
    for p in paragraphs:
        key = re.sub(r"\W+", "", p.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return "\n\n".join(unique)


def jsonld_article_body(html):
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            raw = script.string or script.get_text()
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        for item in stack:
            if not isinstance(item, dict):
                continue
            typ = item.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if any(t in {"NewsArticle", "OpinionNewsArticle", "Article", "ReportageNewsArticle"} for t in types if t):
                body = item.get("articleBody")
                if isinstance(body, str) and len(body) > 300:
                    return body.strip()
    return ""


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

    body = jsonld_article_body(html)
    if len(body) > 300:
        return body

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
    raw = re.sub(r"\s+[|–—-]\s+(The Guardian|Al Jazeera|The New Indian Express).*$", "", raw, flags=re.I)
    raw = re.sub(r"^(Opinion|Editorial|Analysis)\s*[:|-]\s*", "", raw, flags=re.I)
    return raw.strip()


def get_links_from_listing(html, source):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href:
            continue
        url = urljoin(source["listing_urls"][0], href)
        if not url.startswith(("http://", "https://")):
            continue
        if any(re.search(p, url, re.I) for p in source.get("link_patterns", [])):
            key = url.rstrip("/")
            if key not in seen and same_domain(url, source["listing_urls"][0]):
                seen.add(key)
                links.append(url)
    return links


def is_probably_article(url):
    bad = [
        "/author/", "/tag/", "/category/", "/topic/", "/search", "/page/", "#", "/video/", "/gallery/"
    ]
    return not any(x in url.lower() for x in bad)


def fingerprint(source_name, title, url):
    raw = f"{source_name}|{title.lower().strip()}|{url.lower().strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def scrape_source(source):
    print(f"\n📰 {source['name']} ({source['category']})")
    candidates = []
    seen = set()

    for listing_url in source["listing_urls"]:
        html = fetch_page(listing_url, source.get("use_scrapingant", False))
        if not html:
            continue
        links = get_links_from_listing(html, source)
        for link in links:
            if not is_probably_article(link):
                continue
            key = link.rstrip("/")
            if key not in seen:
                seen.add(key)
                candidates.append(link)
        if candidates:
            break

    print(f"    Found {len(candidates)} candidate links")

    articles = []
    for link in candidates[: source.get("max_candidates", 12)]:
        html = fetch_page(link, source.get("use_scrapingant", False))
        if not html:
            continue

        published_at = extract_published_at(html)
        if not is_within_last_24_hours(published_at):
            print(f"    ⏭️ Outside 24-hour window or timestamp unavailable: {link}")
            continue

        title = extract_title(html)
        passage = extract_article_content(html, source.get("content_selectors", []))
        if not title or len(passage) < 300:
            continue

        words = len(passage.split())
        if words < 120:
            continue

        articles.append({
            "source": source["name"],
            "type": source["category"],
            "title": title,
            "link": link,
            "timestamp": published_at.isoformat(),
            "reading_time": f"{max(1, round(words / 200))} min read",
            "passage": passage,
            "word_count": words,
            "id": fingerprint(source["name"], title, link),
        })

        print(f"    ✓ {title[:75]} ({words} words)")
        if len(articles) >= source.get("max_articles", 5):
            break

    # Prefer longer substantive pieces while keeping source order stable for ties.
    articles.sort(key=lambda x: x["word_count"], reverse=True)
    for article in articles:
        article.pop("word_count", None)

    print(f"    ✅ Selected {len(articles)} article(s)")
    return articles


def run():
    print(f"🚀 Starting Today's Editorials collection at {NOW_IST.isoformat()} | rolling window: last {LOOKBACK_HOURS}h")

    # Optional test controls:
    # EDITORIAL_SOURCES="new_indian_express,pioneer,guardian"
    # EDITORIAL_MAX_SOURCES=3
    requested = {x.strip().lower() for x in os.getenv("EDITORIAL_SOURCES", "").split(",") if x.strip()}
    max_sources_raw = os.getenv("EDITORIAL_MAX_SOURCES", "").strip()
    try:
        max_sources = int(max_sources_raw) if max_sources_raw else None
    except ValueError:
        max_sources = None

    active_sources = [s for s in SOURCES if s.get("enabled", True)]
    if requested:
        active_sources = [s for s in active_sources if s["key"].lower() in requested]
    if max_sources is not None:
        active_sources = active_sources[:max_sources]

    print(f"🔧 Sources enabled for this run: {len(active_sources)}")
    all_articles = []
    source_stats = []
    seen_ids = set()

    for source in active_sources:
        try:
            articles = scrape_source(source)
            added = 0
            for article in articles:
                if article["id"] in seen_ids:
                    continue
                seen_ids.add(article["id"])
                all_articles.append(article)
                added += 1
            source_stats.append({
                "source": source["name"],
                "category": source["category"],
                "articles": added,
                "status": "ok" if added else "no_articles",
            })
        except Exception as exc:
            print(f"    ❌ Source failed but pipeline continues: {exc}")
            source_stats.append({
                "source": source["name"],
                "category": source["category"],
                "articles": 0,
                "status": "error",
                "error": str(exc),
            })

    output = {
        "date_scraped": TODAY_DATE.isoformat(),
        "run_timestamp": NOW_IST.isoformat(),
        "lookback_hours": LOOKBACK_HOURS,
        "timezone": "Asia/Kolkata",
        "total_articles": len(all_articles),
        "sources": source_stats,
        "editorials": all_articles,
    }

    with open("today_editorials.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n📊 SOURCE SUMMARY")
    for item in source_stats:
        print(f"  {item['source']}: {item['articles']} ({item['status']})")
    print(f"\n✅ Successfully compiled {len(all_articles)} article(s) into today_editorials.json")


if __name__ == "__main__":
    run()
