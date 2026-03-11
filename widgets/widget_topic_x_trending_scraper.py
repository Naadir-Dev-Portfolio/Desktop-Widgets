#!/usr/bin/env python3
# scrape_trends24_1hour_translate_logged.py
# requirements: requests, beautifulsoup4, argostranslate (optional)

import csv
import re
from pathlib import Path
from urllib.parse import urljoin
from time import perf_counter

import requests
from bs4 import BeautifulSoup

try:
    from argostranslate import package as argos_package
    from argostranslate import translate as argos_translate
except Exception:
    argos_package = None
    argos_translate = None


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

# ORDER YOU REQUESTED (then remaining in sensible importance order)
URLS = {
    "united-kingdom": "https://trends24.in/united-kingdom/",
    "united-states": "https://trends24.in/united-states/",
    "worldwide": "https://trends24.in/",
    "australia": "https://trends24.in/australia/",
    "canada": "https://trends24.in/canada/",
    "mexico": "https://trends24.in/mexico/",
    # rest (most relevant → less relevant, tweak as you like)
    "germany": "https://trends24.in/germany/",
    "france": "https://trends24.in/france/",
    "japan": "https://trends24.in/japan/",
    "russia": "https://trends24.in/russia/",
}

OUTPUT_DIRNAME = "webScrapes"
OUTPUT_FILENAME = "trends.csv"
TIMEOUT_SECONDS = 20
TOP_N = 50


def log(msg: str):
    print(f"[+] {msg}")


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def fetch_html(url: str) -> str:
    log(f"FETCH {url}")
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def ensure_argos_model(src: str, dst: str = "en") -> bool:
    if argos_package is None or argos_translate is None:
        return False

    installed = argos_translate.get_installed_languages()
    installed_codes = {l.code for l in installed}

    if src in installed_codes and dst in installed_codes:
        return True

    log(f"ARGOS install model {src}→{dst} (one-time)")
    argos_package.update_package_index()
    for p in argos_package.get_available_packages():
        if p.from_code == src and p.to_code == dst:
            argos_package.install_from_path(p.download())
            return True

    return False


def translate_text(text: str, src: str) -> str:
    if not src or src == "en":
        return text
    if not ensure_argos_model(src):
        return text

    installed = argos_translate.get_installed_languages()
    try:
        from_lang = next(l for l in installed if l.code == src)
        to_lang = next(l for l in installed if l.code == "en")
    except StopIteration:
        return text

    try:
        return from_lang.get_translation(to_lang).translate(text)
    except Exception:
        return text


def detect_lang_code(text: str) -> str:
    """
    Lightweight, zero-dependency detection aimed at your examples.
    Returns Argos-ish language codes where possible.
    """
    t = text or ""

    # Arabic
    if re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", t):
        return "ar"

    # Japanese (Hiragana/Katakana + common CJK)
    if re.search(r"[\u3040-\u30FF\u31F0-\u31FF]", t) or re.search(r"[\u4E00-\u9FFF]", t):
        return "ja"

    # Cyrillic
    if re.search(r"[\u0400-\u04FF]", t):
        return "ru"

    # Turkish-specific letters
    if re.search(r"[çğıİöşüÇĞİÖŞÜ]", t):
        return "tr"

    # German / French etc are ambiguous vs English; skip unless you want aggressive translation
    return "en"


def parse_region_trends24_latest_block(html_text: str, base_url: str):
    """
    Implements the proven console logic for trends24:
    - find all h3.title[data-timestamp]
    - pick the newest block by max data-timestamp
    - scrape the next sibling ol.trend-card__list
    - extract twitter/x search links, dedupe, rank
    """
    soup = BeautifulSoup(html_text, "html.parser")

    blocks = []
    for h3 in soup.select('h3.title[data-timestamp]'):
        ts_raw = h3.get("data-timestamp") or ""
        try:
            ts = float(ts_raw)
        except Exception:
            continue

        ol = h3.find_next_sibling("ol", class_="trend-card__list")
        if not ol:
            continue

        blocks.append((ts, h3, ol))

    if not blocks:
        log("PARSED 0 rows (no blocks)")
        return []

    blocks.sort(key=lambda x: x[0], reverse=True)
    _, _, ol = blocks[0]

    links = ol.select('a[href*="twitter.com/search"], a[href*="x.com/search"]')

    seen_href = set()
    out = []
    for a in links:
        href = (a.get("href") or "").strip()
        if not href:
            continue

        href = urljoin(base_url, href)
        if href in seen_href:
            continue
        seen_href.add(href)

        topic = clean(a.get_text()) or clean(a.get("aria-label")) or clean(a.get("title"))
        if not topic:
            continue

        out.append({"rank": len(out) + 1, "topic": topic, "href": href})
        if len(out) >= TOP_N:
            break

    log(f"PARSED {len(out)} rows")
    return out


def scrape_all():
    result = {}
    for region, url in URLS.items():
        log(f"START region={region}")
        t0 = perf_counter()

        try:
            html = fetch_html(url)
            rows = parse_region_trends24_latest_block(html, url)
        except Exception as e:
            log(f"ERROR region={region} {e}")
            rows = []

        # translate per-topic based on detected language (esp. worldwide mixed languages)
        out = []
        for i, r in enumerate(rows, 1):
            topic = r["topic"]
            lang = detect_lang_code(topic)
            topic_en = translate_text(topic, lang)
            out.append({"rank": r.get("rank") or i, "topic": topic_en, "href": r["href"]})

        log(f"DONE region={region} rows={len(out)} time={perf_counter() - t0:.2f}s")
        result[region] = out

    return result


def write_csv(data: dict, out_path: Path):
    log(f"WRITE CSV {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["region", "rank", "topic", "url"])
        for region, rows in data.items():
            for r in rows:
                w.writerow([region, r["rank"], r["topic"], r["href"]])


def main():
    t0 = perf_counter()
    log("SCRAPE START")
    data = scrape_all()

    out_dir = Path(__file__).resolve().parent / OUTPUT_DIRNAME
    out_file = out_dir / OUTPUT_FILENAME
    write_csv(data, out_file)

    log(
        f"FINISHED total_rows={sum(len(v) for v in data.values())} "
        f"time={perf_counter() - t0:.2f}s"
    )


if __name__ == "__main__":
    main()
