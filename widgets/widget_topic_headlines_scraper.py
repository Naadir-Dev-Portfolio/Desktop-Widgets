#!/usr/bin/env python3
# scrape_headlines_final_v4.py

import csv
import html
import json
import re
import time
import calendar
import random
from pathlib import Path
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import feedparser



# --- Configuration ---

# Updated Headers to be even more realistic
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}

TIMEOUT = 15
OUTPUT_DIRNAME = "webScrapes"
OUTPUT_FILENAME = "headlines.csv"

TOP_N_PER_SOURCE = 40
RSS_FETCH_MAX = 60

# HTML Scraping Limits
SKY_CANDIDATE_LIMIT = 40 
MAX_WORKERS = 8

# Sky News cooldown: skip HTML scraping if the CSV was modified less than this many seconds ago
SKY_SCRAPE_COOLDOWN_SECONDS = 600  # 10 minutes

# --- Regex ---
RE_HREF = re.compile(r'href=["\'](.*?)["\']', re.IGNORECASE)
RE_SKY_STORY_PATH = re.compile(r"^/story/|^https?://news\.sky\.com/story/", re.IGNORECASE)
RE_TITLE_TAG = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
RE_META_PROP = re.compile(r'<meta[^>]+property="([^"]+)"[^>]+content="([^"]+)"', re.IGNORECASE)
RE_META_NAME = re.compile(r'<meta[^>]+name="([^"]+)"[^>]+content="([^"]+)"', re.IGNORECASE)
RE_TIME_TAG = re.compile(r"<time[^>]+datetime=\"([^\"]+)\"", re.IGNORECASE)
RE_JSONLD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)

def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""

def _parse_iso_to_epoch(iso_str: str) -> float:
    try:
        s = iso_str.strip().replace("Z", "+00:00")
        if len(s) == 19: s += "+00:00"
        from datetime import datetime
        dt = datetime.fromisoformat(s)
        return float(dt.timestamp())
    except Exception:
        return 0.0

def _dedupe_and_sort(items):
    by_title = {}
    for it in items:
        key = " ".join(it["title"].lower().split())
        prev = by_title.get(key)
        if prev is None or it["ts"] > prev["ts"]:
            by_title[key] = it
    uniq = list(by_title.values())
    uniq.sort(key=lambda x: x["ts"], reverse=True)
    return uniq

# --- Network ---

def create_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=2)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    try:
        s.get("https://news.sky.com/", timeout=5)
    except:
        pass
    return s

def fetch_content(session, url, is_xml=False, referer=None):
    try:
        local_headers = {}
        if referer:
            local_headers["Referer"] = referer
        
        if "sky.com" in url:
            time.sleep(random.uniform(0.1, 0.3))

        r = session.get(url, timeout=TIMEOUT, headers=local_headers)
        if r.status_code == 403:
            return None
        r.raise_for_status()
        return r.content if is_xml else r.text
    except Exception:
        return None

# --- RSS Handler ---

def fetch_rss(session, url):
    xml_bytes = fetch_content(session, url, is_xml=True)
    if not xml_bytes:
        try:
            parsed = feedparser.parse(url)
        except Exception:
            return []
    else:
        parsed = feedparser.parse(xml_bytes)

    out = []
    entries = parsed.entries if hasattr(parsed, 'entries') else []
    for e in entries[:RSS_FETCH_MAX]:
        title = (getattr(e, "title", "") or "").strip()
        link = (getattr(e, "link", "") or "").strip()
        if not title or not link: continue
        
        ts = time.time()
        for key in ("published_parsed", "updated_parsed"):
            val = getattr(e, key, None)
            if val:
                try:
                    ts = float(calendar.timegm(val))
                    break
                except: pass
        
        out.append({
            "title": html.unescape(title),
            "link": link,
            "source": _domain(link) or _domain(url),
            "ts": ts,
        })
    return out

# --- Sky HTML Scraper ---

def _extract_ts_from_html(html_text):
    props = dict((k.lower(), v) for k, v in RE_META_PROP.findall(html_text))
    for key in ("article:published_time", "og:updated_time", "article:modified_time"):
        if props.get(key) and (ts := _parse_iso_to_epoch(props[key])): return ts

    names = dict((k.lower(), v) for k, v in RE_META_NAME.findall(html_text))
    for key in ("publish-date", "date", "dc.date", "parsely-pub-date"):
        if names.get(key) and (ts := _parse_iso_to_epoch(names[key])): return ts

    if m := RE_TIME_TAG.search(html_text):
        if ts := _parse_iso_to_epoch(m.group(1)): return ts

    for blob in RE_JSONLD.findall(html_text):
        try:
            data = json.loads(blob)
            nodes = data if isinstance(data, list) else [data]
            if isinstance(data, dict) and "@graph" in data: nodes.extend(data["@graph"])
            for node in nodes:
                if not isinstance(node, dict): continue
                t = str(node.get("@type", "")).lower()
                if "newsarticle" in t or "article" in t:
                    for k in ("datePublished", "dateModified"):
                        if node.get(k) and (ts := _parse_iso_to_epoch(node[k])): return ts
        except: continue
    return 0.0

def _fetch_single_sky_story(session, url, section_url):
    html_text = fetch_content(session, url, referer=section_url)
    if not html_text: return None
    
    title = ""
    if m := RE_TITLE_TAG.search(html_text):
        title = html.unescape(re.sub(r"\s+", " ", m.group(1)).strip())
        title = re.sub(r"\s*\|\s*Sky News\s*$", "", title, flags=re.IGNORECASE).strip()
    
    ts = _extract_ts_from_html(html_text) or time.time()
    return {"title": title or url, "link": url, "source": _domain(url), "ts": ts}

def fetch_sky_section_html(session, section_url, pool):
    section_html = fetch_content(session, section_url)
    if not section_html: 
        return None 

    links = []
    seen = set()
    for href in RE_HREF.findall(section_html):
        href = href.strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"): continue
        absu = urljoin(section_url, href).split("?")[0]
        if absu not in seen and (RE_SKY_STORY_PATH.search(href) or RE_SKY_STORY_PATH.search(absu)):
            seen.add(absu)
            links.append(absu)
    
    if not links: return None 

    candidates = links[:SKY_CANDIDATE_LIMIT]
    items = []
    futures = [pool.submit(_fetch_single_sky_story, session, u, section_url) for u in candidates]
    
    for fut in as_completed(futures):
        try:
            it = fut.result()
            if it and it.get("title"): items.append(it)
        except: pass
            
    return items

# --- Main Configuration ---

SKY_RSS_FALLBACKS = {
    "https://news.sky.com/uk": "https://feeds.skynews.com/feeds/rss/uk.xml",
    "https://news.sky.com/business": "https://feeds.skynews.com/feeds/rss/business.xml",
    "https://news.sky.com/world": "https://feeds.skynews.com/feeds/rss/world.xml",
    "https://news.sky.com/money": "https://feeds.skynews.com/feeds/rss/money.xml",
}

SOURCES = {
    "Sky News - UK": {"type": "sky", "url": "https://news.sky.com/uk"},
    "Sky News - Business": {"type": "sky", "url": "https://news.sky.com/business"},
    "Sky News - World": {"type": "sky", "url": "https://news.sky.com/world"},
    "Sky News - Money": {"type": "sky", "url": "https://news.sky.com/money"},

    "Al Jazeera - All": {"type": "rss", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    "BBC News - World": {"type": "rss", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    "BBC News - Business": {"type": "rss", "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
    "Deutsche Welle - Top": {"type": "rss", "url": "https://rss.dw.com/rdf/rss-en-top"},
    "Deutsche Welle - World": {"type": "rss", "url": "https://rss.dw.com/rdf/rss-en-world"},
    "UN News - All": {"type": "rss", "url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml"},
}

def _should_skip_sky_scraping():
    """Return True if the CSV was modified less than SKY_SCRAPE_COOLDOWN_SECONDS ago."""
    csv_path = Path(__file__).resolve().parent / OUTPUT_DIRNAME / OUTPUT_FILENAME
    if not csv_path.exists():
        return False
    age = time.time() - csv_path.stat().st_mtime
    return age < SKY_SCRAPE_COOLDOWN_SECONDS

def main():
    start_time = time.time()
    session = create_session()
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    
    skip_sky = _should_skip_sky_scraping()
    if skip_sky:
        print(f"[INFO] CSV is less than {SKY_SCRAPE_COOLDOWN_SECONDS // 60} min old "
              f"— skipping Sky HTML scraping, using RSS fallback only.\n")
    
    all_data = {}
    
    print(f"{'SOURCE':<30} | {'STATUS'}")
    print("-" * 60)

    try:
        for region_name, cfg in SOURCES.items():
            items = []
            try:
                if cfg["type"] == "rss":
                    items = fetch_rss(session, cfg["url"])
                elif cfg["type"] == "sky":
                    if skip_sky:
                        # Cooldown active: go straight to RSS fallback, no Sky HTML requests
                        fallback_url = SKY_RSS_FALLBACKS.get(cfg["url"])
                        if fallback_url:
                            print(f"{region_name:<30} | Cooldown active -> RSS Fallback")
                            items = fetch_rss(session, fallback_url)
                        else:
                            items = []
                    else:
                        # Normal path: try HTML scraping first
                        items = fetch_sky_section_html(session, cfg["url"], pool)
                    
                        if items is None or len(items) == 0:
                            fallback_url = SKY_RSS_FALLBACKS.get(cfg["url"])
                            if fallback_url:
                                print(f"{region_name:<30} | HTML Blocked/Empty -> RSS Fallback")
                                items = fetch_rss(session, fallback_url)
                            else:
                                items = []

                final_items = _dedupe_and_sort(items)[:TOP_N_PER_SOURCE]
                print(f"{region_name:<30} | Found {len(final_items)} items")

                rows = []
                for i, it in enumerate(final_items, 1):
                    rows.append({"rank": i, "topic": it["title"], "href": it["link"]})
                all_data[region_name] = rows
            except Exception as e:
                print(f"{region_name:<30} | ERROR: {e}")

    finally:
        pool.shutdown(wait=True)
        session.close()

    # Write CSV
    out_dir = Path(__file__).resolve().parent / OUTPUT_DIRNAME
    out_file = out_dir / OUTPUT_FILENAME
    out_dir.mkdir(parents=True, exist_ok=True)
    
    total_rows = 0
    with out_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["region", "rank", "topic", "url"])
        for region in SOURCES.keys():
            if region in all_data:
                rows = all_data[region]
                total_rows += len(rows)
                for row in rows:
                    w.writerow([region, row["rank"], row["topic"], row["href"]])

    elapsed = time.time() - start_time
    print("-" * 60)
    print(f"Total time: {elapsed:.2f}s")
    print(f"Saved {total_rows} rows to: {out_file}")

if __name__ == "__main__":
    main()