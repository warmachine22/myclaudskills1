#!/usr/bin/env python3
"""Scrape headlines from finviz.com news feeds into a JSON file.

Covers three feeds, each of which uses a different row layout:
  view 1  https://finviz.com/news       Market News  (two tables: News + Blogs)
  view 6  https://finviz.com/news?v=6   Market Pulse (headline spans, no links)
  view 3  https://finviz.com/news?v=3   Stocks News  (links + ticker badges + source)

Stdlib only. Timestamps are resolved to US/Eastern, which is what finviz displays.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date as _date, datetime, timedelta, timezone

BASE = "https://finviz.com"

VIEWS = {
    "1": {"url": f"{BASE}/news", "label": "Market News"},
    "6": {"url": f"{BASE}/news?v=6", "label": "Market Pulse"},
    "3": {"url": f"{BASE}/news?v=3", "label": "Stocks News"},
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


# --------------------------------------------------------------------------
# Eastern time
# --------------------------------------------------------------------------

def _eastern_tz():
    """America/New_York, falling back to the US DST rule if tzdata is absent."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:
        return None


def _et_offset_for(naive_utc: datetime) -> timezone:
    """US Eastern offset: DST from 2nd Sunday of March to 1st Sunday of November."""
    y = naive_utc.year

    def nth_sunday(month, n):
        d = _date(y, month, 1)
        d += timedelta(days=(6 - d.weekday()) % 7)  # first Sunday
        return d + timedelta(weeks=n - 1)

    start = datetime.combine(nth_sunday(3, 2), datetime.min.time()) + timedelta(hours=7)
    end = datetime.combine(nth_sunday(11, 1), datetime.min.time()) + timedelta(hours=6)
    return timezone(timedelta(hours=-4 if start <= naive_utc < end else -5))


def now_eastern() -> datetime:
    tz = _eastern_tz()
    if tz is not None:
        return datetime.now(tz)
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    return datetime.now(timezone.utc).astimezone(_et_offset_for(utc_now))


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

def fetch(url: str, retries: int = 3, timeout: int = 30) -> str:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


# --------------------------------------------------------------------------
# Date parsing
# --------------------------------------------------------------------------

RE_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})\s*(AM|PM)$", re.I)
RE_MONTH = re.compile(r"^([A-Z][a-z]{2})-(\d{1,2})$")
RE_REL = re.compile(r"^(\d+)\s*(min|mins|minute|minutes|hour|hours|day|days)$", re.I)


def resolve_date(raw: str, now: datetime) -> dict:
    """Turn a finviz date-cell label into calendar fields.

    Handles '03:35AM' (today), 'Aug-02', '13 min', '2 hours', 'Yesterday'.
    Returns date/time/datetime (any of which may be None if unresolvable).
    """
    out = {"date_raw": raw, "date": None, "time": None, "datetime": None}
    raw = (raw or "").strip()
    if not raw:
        return out

    dt = None

    m = RE_CLOCK.match(raw)
    if m:
        hour, minute, mer = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if mer == "PM" and hour != 12:
            hour += 12
        elif mer == "AM" and hour == 12:
            hour = 0
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if dt is None:
        m = RE_REL.match(raw)
        if m:
            n, unit = int(m.group(1)), m.group(2).lower()
            delta = (
                timedelta(minutes=n) if unit.startswith("min")
                else timedelta(hours=n) if unit.startswith("hour")
                else timedelta(days=n)
            )
            dt = (now - delta).replace(second=0, microsecond=0)

    if dt is None and raw.lower().startswith("yesterday"):
        dt = (now - timedelta(days=1)).replace(second=0, microsecond=0)

    if dt is not None:
        out["date"] = dt.date().isoformat()
        out["time"] = dt.strftime("%H:%M")
        out["datetime"] = dt.isoformat()
        return out

    # 'Aug-02' - date only, no time on the page
    m = RE_MONTH.match(raw)
    if m and m.group(1) in MONTHS:
        month, day = MONTHS[m.group(1)], int(m.group(2))
        year = now.year
        try:
            d = _date(year, month, day)
        except ValueError:
            return out
        if d > now.date() + timedelta(days=1):  # label rolled back over new year
            d = _date(year - 1, month, day)
        out["date"] = d.isoformat()
        out["datetime"] = d.isoformat()
    return out


# --------------------------------------------------------------------------
# HTML parsing
# --------------------------------------------------------------------------

RE_ROW = re.compile(
    r"<tr[^>]*\bnews_table-row\b[^>]*>(.*?)</tr>", re.S | re.I
)
RE_TABLE = re.compile(r"<table[^>]*styled-table-new[^>]*>", re.I)
RE_HEADING = re.compile(r'news-calendar_heading[^>]*>\s*([^<]+?)\s*<', re.I)
# date label: the <td> cell only (v3 reuses the class on a <span> for the source)
RE_DATE_TD = re.compile(
    r'<td[^>]*\bnews_date-cell\b[^>]*>\s*(.*?)\s*</td>', re.S | re.I
)
RE_LINK = re.compile(
    r'<a\s+href="([^"]+)"[^>]*\bnn-tab-link\b[^>]*>\s*(.*?)\s*</a>', re.S | re.I
)
RE_PULSE = re.compile(
    r'<span[^>]*\bmarket-pulse-headline\b[^>]*>\s*(.*?)\s*</span>', re.S | re.I
)
RE_TICKER = re.compile(r'data-boxover-ticker="([^"]+)"')
RE_SRC_SPAN = re.compile(
    r'<span[^>]*\bnews_date-cell\b[^>]*>\s*([^<]*?)\s*</span>', re.S | re.I
)
RE_SRC_ICON = re.compile(r'icons_(?:news|blogs)\.svg[^#]*#([a-z0-9_\-]+?)-(?:light|dark)"')
RE_TRACK_SRC = re.compile(r"trackAndOpenNews\(event,\s*'([^']+)'")
RE_BOXOVER_TEXT = re.compile(r'data-boxover-text="([^"]*)"')
RE_TAG = re.compile(r"<[^>]+>")


def unescape_js(text: str) -> str:
    """Decode the JS string escapes finviz emits inside trackAndOpenNews(...)."""
    text = re.sub(
        r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text or ""
    )
    return re.sub(r"\\(['\"\\/])", r"\1", text)


def clean(text: str) -> str:
    """Strip tags/entities and collapse whitespace, including invisible marks."""
    text = RE_TAG.sub(" ", text or "")
    text = html.unescape(text)
    text = text.replace("​", "").replace("⁠", "").replace("﻿", "")
    return re.sub(r"\s+", " ", text).strip()


def absolute(url: str) -> str:
    if not url:
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE + url
    return url


def parse_row(row_html: str, view: str, section: str, now: datetime) -> dict | None:
    m = RE_DATE_TD.search(row_html)
    raw_date = clean(m.group(1)) if m else ""

    headline, url = None, None
    m = RE_LINK.search(row_html)
    if m:
        url = absolute(html.unescape(m.group(1)))
        headline = clean(m.group(2))
    else:
        m = RE_PULSE.search(row_html)
        if m:
            headline = clean(m.group(1))

    if not headline:
        return None

    # source: named icon (view 1), trackAndOpenNews label or badge span (view 3)
    source = None
    m = RE_SRC_ICON.search(row_html)
    if m:
        source = m.group(1).replace("_", " ").replace("-", " ").title()
    if source is None:
        m = RE_TRACK_SRC.search(row_html)
        if m:
            source = clean(unescape_js(m.group(1)))
    if source is None:
        spans = [clean(s) for s in RE_SRC_SPAN.findall(row_html)]
        spans = [s for s in spans if s and not RE_REL.match(s) and not RE_MONTH.match(s)]
        if spans:
            source = spans[-1]

    tickers = sorted({html.unescape(t) for t in RE_TICKER.findall(row_html)})

    description = None
    m = RE_BOXOVER_TEXT.search(row_html)
    if m:
        desc = clean(m.group(1))
        if desc and desc != headline:
            description = desc

    item = {
        "headline": headline,
        "url": url,
        "source": source,
        "tickers": tickers,
        "section": section,
        "view": view,
        "feed": VIEWS[view]["label"],
    }
    if description:
        item["description"] = description
    item.update(resolve_date(raw_date, now))
    return item


def parse_page(html_text: str, view: str, now: datetime) -> list[dict]:
    """Split the page into its tables and parse every news row."""
    starts = [m.start() for m in RE_TABLE.finditer(html_text)]
    if not starts:
        return []

    # view 1 renders two side-by-side tables; their headings appear, in order,
    # in the header row above them ("News", "Blogs").
    headings = [clean(h) for h in RE_HEADING.findall(html_text)]
    default = {"1": "News", "6": "Market Pulse", "3": "Stocks News"}[view]

    items: list[dict] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(html_text)
        segment = html_text[start:end]
        rows = RE_ROW.findall(segment)
        if not rows:
            continue
        section = headings[idx] if view == "1" and idx < len(headings) else default
        for row in rows:
            item = parse_row(row, view, section, now)
            if item:
                items.append(item)
    return items


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def sort_key(item: dict):
    return (item.get("datetime") or "", item.get("headline") or "")


def dedupe_items(items: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for item in items:
        key = re.sub(r"[^a-z0-9]+", "", (item["headline"] or "").lower())
        if key in seen:
            existing = seen[key]
            existing.setdefault("also_in", [])
            if item["feed"] not in existing["also_in"]:
                existing["also_in"].append(item["feed"])
            if not existing.get("url") and item.get("url"):
                existing["url"] = item["url"]
            if not existing.get("tickers") and item.get("tickers"):
                existing["tickers"] = item["tickers"]
        else:
            seen[key] = item
    return list(seen.values())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Scrape finviz news headlines into JSON.")
    p.add_argument("--out", help="output path (default finviz-news-YYYY-MM-DD.json)")
    p.add_argument(
        "--views",
        default="1,6,3",
        help="comma-separated finviz views to scrape: 1=Market News, 6=Market Pulse, 3=Stocks News",
    )
    p.add_argument("--dedupe", action="store_true", help="collapse identical headlines across feeds")
    p.add_argument("--compact", action="store_true", help="write minified JSON")
    p.add_argument("--quiet", action="store_true", help="suppress the stderr summary")
    args = p.parse_args(argv)

    views = [v.strip() for v in args.views.split(",") if v.strip()]
    bad = [v for v in views if v not in VIEWS]
    if bad:
        print(f"error: unknown view(s) {bad}; valid: {sorted(VIEWS)}", file=sys.stderr)
        return 2

    now = now_eastern()
    items: list[dict] = []
    meta: list[dict] = []

    for view in views:
        url = VIEWS[view]["url"]
        entry = {"view": view, "label": VIEWS[view]["label"], "url": url}
        try:
            page = fetch(url)
            found = parse_page(page, view, now)
            items.extend(found)
            entry.update(status="ok", count=len(found))
            if not found:
                entry["status"] = "no-rows-parsed"
        except Exception as exc:
            entry.update(status="error", count=0, error=str(exc))
        meta.append(entry)
        if not args.quiet:
            print(f"  view {view} ({entry['label']}): {entry['status']}, "
                  f"{entry.get('count', 0)} headlines", file=sys.stderr)

    if args.dedupe:
        items = dedupe_items(items)

    items.sort(key=sort_key, reverse=True)

    payload = {
        "fetched_at": now.isoformat(),
        "fetched_at_utc": now.astimezone(timezone.utc).isoformat(),
        "date": now.date().isoformat(),
        "timezone": "America/New_York",
        "count": len(items),
        "feeds": meta,
        "headlines": items,
    }

    out_path = args.out or f"finviz-news-{now.date().isoformat()}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        if args.compact:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    if not args.quiet:
        print(f"wrote {len(items)} headlines to {out_path}", file=sys.stderr)

    failed = [m for m in meta if m["status"] == "error"]
    if failed and not items:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
