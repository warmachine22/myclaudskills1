#!/usr/bin/env python3
"""Economic calendar from tradingeconomics.com/calendar.

The calendar page is server-rendered and driven entirely by cookies, so one
plain GET with the right cookie string returns exactly the table the site would
show a human with those filters selected.

  cal-custom-range      YYYY-MM-DD|YYYY-MM-DD   (inclusive both ends)
  calendar-importance   1 | 2 | 3               (minimum star level)
  calendar-countries    lowercase ISO3, comma separated
  cal-timezone-offset   minutes from UTC (e.g. -240 = UTC-4)

Category is a URL path: /calendar/inflation, /calendar/interest-rate, ...
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html as _html
import json
import re
import sys
import time

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from te_core import (  # noqa: E402
    DEFAULT_TTL, GROUPS, RANGES, cache_clear, country_list, day_label,
    dump_json, esc, fetch, parse_date, resolve_range, stars, write_out,
)

BASE = "https://tradingeconomics.com/calendar"

CATEGORIES = {
    "all": "", "interest-rate": "interest-rate", "rates": "interest-rate",
    "inflation": "inflation", "prices": "inflation", "cpi": "inflation",
    "labour": "labour", "labor": "labour", "jobs": "labour",
    "employment": "labour", "gdp": "gdp", "growth": "gdp",
    "trade": "trade", "government": "government", "fiscal": "government",
    "business": "business", "business-confidence": "business", "pmi": "business",
    "consumer": "consumer", "sentiment": "consumer", "housing": "housing",
    "bonds": "bonds", "auctions": "bonds", "energy": "energy",
    "holidays": "holidays",
}

CATEGORY_LABEL = {
    "": "All Events", "interest-rate": "Interest Rate",
    "inflation": "Prices & Inflation", "labour": "Labour Market",
    "gdp": "GDP Growth", "trade": "Foreign Trade", "government": "Government",
    "business": "Business Confidence", "consumer": "Consumer Sentiment",
    "housing": "Housing Market", "bonds": "Bond Auctions", "energy": "Energy",
    "holidays": "Holidays",
}

TZ_ALIAS = {
    "et": -240, "est": -300, "edt": -240, "eastern": -240,
    "ct": -300, "cst": -360, "cdt": -300, "central": -300,
    "mt": -360, "mst": -420, "mdt": -360,
    "pt": -420, "pst": -480, "pdt": -420, "pacific": -420,
    "utc": 0, "gmt": 0, "z": 0,
    "london": 60, "bst": 60, "cet": 60, "cest": 120, "berlin": 120,
    "frankfurt": 120, "paris": 120, "tokyo": 540, "jst": 540,
    "hk": 480, "hongkong": 480, "shanghai": 480, "sydney": 600, "india": 330,
    "ist": 330,
}


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def _text(fragment):
    t = re.sub(r"<[^>]+>", " ", fragment or "")
    t = _html.unescape(t)
    t = t.replace("�", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def _cell(fragment, elem_id):
    m = re.search(
        r"<(?:span|a)[^>]*\bid='%s'[^>]*>(.*?)</(?:span|a)>" % elem_id,
        fragment, re.S | re.I,
    )
    return (_text(m.group(1)) or None) if m else None


def parse_rows(page_html):
    """Split the calendar table into rows and pull every field out of each."""
    start = page_html.find('id="calendar"')
    if start < 0:
        return []
    body = page_html[start:]
    chunks = body.split("<tr data-url=")[1:]
    events = []
    for chunk in chunks:
        # a row ends where the next one starts; trailing markup is harmless
        head = chunk[:400]
        attrs = dict(re.findall(r"data-([a-z]+)=[\"']([^\"']*)[\"']", "data-url=" + head))
        date_m = re.search(r"class='\s*(\d{4}-\d{2}-\d{2})'", chunk)
        imp_m = re.search(r'class="event-\d+\s+calendar-date-(\d)"', chunk)
        time_m = re.search(
            r'<span class="event-\d+[^"]*">\s*(?:<[^>]+>\s*)*([^<]{0,24}?)\s*</span>', chunk, re.S
        )
        iso_m = re.search(r'class="calendar-iso">\s*([A-Z]{2})', chunk)
        ctry_m = re.search(r"<div title=\"([^\"]+)\" class='flag", chunk)
        ev_m = re.search(r"<a class='calendar-event'[^>]*>(.*?)</a>", chunk, re.S)
        ref_m = re.search(r'<span class="calendar-reference">(.*?)</span>', chunk, re.S)
        rev_m = re.search(r"title='Previous revised from ([^']+)'", chunk)

        if not ev_m and not attrs.get("event"):
            continue

        raw_time = _text(time_m.group(1)) if time_m else ""
        events.append({
            "id": attrs.get("id"),
            "date": date_m.group(1) if date_m else None,
            "time": raw_time or None,
            "importance": int(imp_m.group(1)) if imp_m else None,
            "country": (ctry_m.group(1) if ctry_m else (attrs.get("country") or "").title()),
            "iso2": iso_m.group(1) if iso_m else None,
            "event": _text(ev_m.group(1)) if ev_m else (attrs.get("event") or "").title(),
            "reference": _text(ref_m.group(1)) if ref_m else None,
            "category": attrs.get("category"),
            "symbol": attrs.get("symbol") or None,
            "actual": _cell(chunk, "actual"),
            "previous": _cell(chunk, "previous"),
            "consensus": _cell(chunk, "consensus"),
            "forecast": _cell(chunk, "forecast"),
            "revised_from": _html.unescape(rev_m.group(1)) if rev_m else None,
            "url": "https://tradingeconomics.com" + attrs["url"] if attrs.get("url") else None,
        })
    return events


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------

def build_cookie(start, end, impact, countries, tz_offset):
    parts = [f"cal-custom-range={start}|{end}", f"cal-timezone-offset={int(tz_offset)}"]
    if impact and int(impact) > 1:
        parts.append(f"calendar-importance={int(impact)}")
    if countries:
        parts.append("calendar-countries=" + ",".join(countries))
    return "; ".join(parts)


def get_events(start, end, impact=1, countries=None, category="", tz_offset=0, ttl=DEFAULT_TTL):
    url = BASE + ("/" + category if category else "")
    cookie = build_cookie(start, end, impact, countries or [], tz_offset)
    page = fetch(url, cookies=cookie, ttl=ttl)
    rows = parse_rows(page)
    # Guard against a stale edge-cached body: if nothing the page returned falls
    # inside the requested window, the cookies were not applied. Ask again.
    if rows and not any(r["date"] and start <= r["date"] <= end for r in rows):
        time.sleep(3)
        rows = parse_rows(fetch(url, cookies=cookie, ttl=0))
    # the site can bleed a day past the window; clamp to what was asked for
    rows = [r for r in rows if r["date"] and start <= r["date"] <= end]
    if impact:
        rows = [r for r in rows if (r["importance"] or 0) >= int(impact)]
    rows.sort(key=lambda r: (r["date"] or "", _sort_time(r["time"]), -(r["importance"] or 0)))
    return rows


HOLIDAY_URL = "https://tradingeconomics.com/holidays"
_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def get_holidays(start, end, countries=None, ttl=DEFAULT_TTL):
    """Public/market holidays. These live on their own page, not in /calendar."""
    page = fetch(HOLIDAY_URL, ttl=ttl)
    i = page.find('<table id="calendar"')
    if i < 0:
        return []
    body = page[i: page.find("</table>", i)]
    year, out = None, []
    for chunk in body.split("<tr")[1:]:
        ym = re.search(r"class='year-row'><td colspan='12'>(\d{4})</td>", chunk)
        if ym:
            year = int(ym.group(1))
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", chunk, re.S)
        if len(cells) < 4 or year is None:
            continue
        dm = re.match(r"([A-Z]{3})/(\d{1,2})", _text(cells[0]))
        iso = re.search(r"flag flag-([a-z]{2})", cells[1])
        if not dm:
            continue
        try:
            iso_date = _dt.date(year, _MONTHS[dm.group(1)], int(dm.group(2))).isoformat()
        except (KeyError, ValueError):
            continue
        out.append({
            "date": iso_date, "time": "All day", "importance": 1,
            "country": _text(cells[2]), "iso2": (iso.group(1).upper() if iso else None),
            "event": _text(cells[3]), "reference": None, "category": "holiday",
            "symbol": None, "actual": None, "previous": None, "consensus": None,
            "forecast": None, "revised_from": None, "url": HOLIDAY_URL,
        })
    if out:
        covered_from, covered_to = min(h["date"] for h in out), max(h["date"] for h in out)
        if start < covered_from or end > covered_to:
            print(f"note: the holidays page only covers {covered_from} .. {covered_to}; "
                  "dates outside that window cannot be listed.", file=sys.stderr)
    out = [h for h in out if start <= h["date"] <= end]
    if countries:
        from te_core import to_iso3  # local: only needed for this filter
        want = set(countries)
        out = [h for h in out if to_iso3(h["country"]) in want]
    out.sort(key=lambda h: (h["date"], h["country"]))
    return out


def _sort_time(t):
    if not t:
        return "99:99"
    m = re.match(r"(\d{1,2}):(\d{2})\s*([AP]M)?", t.strip(), re.I)
    if not m:
        return "99:98"
    h, mi, ap = int(m.group(1)), m.group(2), (m.group(3) or "").upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mi}"


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def tz_label(off):
    off = int(off)
    if off == 0:
        return "UTC"
    sign = "+" if off > 0 else "-"
    h, m = divmod(abs(off), 60)
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


def render_md(events, meta):
    lines = []
    scope = meta["category_label"]
    imp = meta["impact"]
    lines.append(f"# Economic calendar — {meta['start']} to {meta['end']}")
    bits = [f"{len(events)} events", f"times in {tz_label(meta['tz'])}"]
    if scope != "All Events":
        bits.insert(0, scope)
    if imp > 1:
        bits.insert(0, f"impact {'*' * imp}+ only")
    if meta.get("countries"):
        bits.append("countries: " + ",".join(meta["countries"]))
    lines.append("_" + " · ".join(bits) + "_")
    lines.append("")

    if not events:
        lines.append("No events matched these filters.")
        return "\n".join(lines)

    by_imp = {3: 0, 2: 0, 1: 0}
    for e in events:
        by_imp[e["importance"] or 1] = by_imp.get(e["importance"] or 1, 0) + 1
    lines.append(
        f"**By impact:** {by_imp.get(3,0)} high (***) · "
        f"{by_imp.get(2,0)} medium (**) · {by_imp.get(1,0)} low (*)"
    )
    lines.append("")

    current = None
    for idx, e in enumerate(events):
        if e["date"] != current:
            current = e["date"]
            lines.append(f"## {day_label(current)}")
            lines.append("")
            lines.append("| Time | Imp | Country | Event | Actual | Consensus | Previous | TE Forecast |")
            lines.append("|---|---|---|---|---|---|---|---|")
        ref = f" ({e['reference']})" if e["reference"] else ""
        prev = e["previous"] or ""
        if e["revised_from"]:
            prev += f" (rev. from {e['revised_from']})"
        lines.append(
            "| {t} | {i} | {c} | {ev} | {a} | {con} | {p} | {f} |".format(
                t=esc(e["time"] or ""), i=stars(e["importance"]),
                c=esc(e["iso2"] or e["country"]), ev=esc(e["event"] + ref),
                a=esc(e["actual"] or ""), con=esc(e["consensus"] or ""),
                p=esc(prev), f=esc(e["forecast"] or ""),
            )
        )
        if idx + 1 == len(events) or events[idx + 1]["date"] != e["date"]:
            lines.append("")
    lines.append(f"Source: {meta['url']} (fetched {meta['fetched_at']})")
    return "\n".join(lines)


def render_csv(events):
    cols = ["date", "time", "importance", "country", "iso2", "event", "reference",
            "category", "actual", "consensus", "previous", "revised_from",
            "forecast", "symbol", "url"]
    out = [",".join(cols)]
    for e in events:
        row = []
        for c in cols:
            v = "" if e.get(c) is None else str(e[c])
            row.append('"' + v.replace('"', '""') + '"' if any(x in v for x in ',"\n') else v)
        out.append(",".join(row))
    return "\n".join(out)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="te_calendar.py",
        description="Economic calendar (releases, central-bank decisions, auctions) "
                    "from tradingeconomics.com.",
    )
    p.add_argument("range", nargs="?", default="thisweek",
                   help="preset window: " + ", ".join(RANGES) + " (default thisweek)")
    p.add_argument("--start", help="custom window start YYYY-MM-DD (overrides preset)")
    p.add_argument("--end", help="custom window end YYYY-MM-DD, inclusive")
    p.add_argument("--impact", "-i", type=int, choices=[1, 2, 3], default=1,
                   help="minimum star level: 3 = high impact only (default 1 = all)")
    p.add_argument("--countries", "-c",
                   help="comma list of countries/ISO codes, or a group: "
                        + ", ".join(GROUPS))
    p.add_argument("--category", default="all",
                   help="event type: " + ", ".join(sorted(set(CATEGORIES))))
    p.add_argument("--tz", default="ET",
                   help="timezone for the Time column: name (ET, UTC, London, Tokyo) "
                        "or minutes offset like -240. Default ET.")
    p.add_argument("--format", "-f", choices=["md", "json", "csv"], default="md")
    p.add_argument("--out", "-o", help="write to file instead of stdout")
    p.add_argument("--limit", type=int, help="keep only the first N events")
    p.add_argument("--search", help="only events whose name/country matches this text")
    p.add_argument("--refresh", action="store_true", help="bypass the 10-minute cache")
    p.add_argument("--cache-clear", action="store_true", help="wipe the cache and exit")
    args = p.parse_args(argv)

    if args.cache_clear:
        print(f"cleared {cache_clear()} cached responses", file=sys.stderr)
        return 0

    if args.start or args.end:
        start = parse_date(args.start) if args.start else _dt.date.today().isoformat()
        end = parse_date(args.end) if args.end else start
    else:
        start, end = resolve_range(args.range)
    if end < start:
        start, end = end, start

    cat_key = str(args.category).strip().lower()
    if cat_key not in CATEGORIES:
        raise SystemExit(f"unknown category '{args.category}'. "
                         f"Options: {', '.join(sorted(set(CATEGORIES)))}")
    category = CATEGORIES[cat_key]

    tz_raw = str(args.tz).strip().lower()
    if re.fullmatch(r"[+-]?\d{1,4}", tz_raw):
        tz = int(tz_raw)
    elif tz_raw in TZ_ALIAS:
        tz = TZ_ALIAS[tz_raw]
    else:
        raise SystemExit(f"unknown timezone '{args.tz}'. Use minutes (e.g. -240) or "
                         f"one of: {', '.join(sorted(TZ_ALIAS))}")

    countries = country_list(args.countries)
    ttl = 0 if args.refresh else DEFAULT_TTL

    if category == "holidays":
        events = get_holidays(start, end, countries, ttl)
    else:
        events = get_events(start, end, args.impact, countries, category, tz, ttl)

    if args.search:
        needle = args.search.lower()
        events = [e for e in events
                  if needle in (e["event"] or "").lower()
                  or needle in (e["country"] or "").lower()
                  or needle in (e["category"] or "").lower()]
    if args.limit:
        events = events[: args.limit]

    meta = {
        "start": start, "end": end, "impact": args.impact, "tz": tz,
        "countries": countries, "category": category,
        "category_label": CATEGORY_LABEL.get(category, category or "All Events"),
        "url": BASE + ("/" + category if category else ""),
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(events),
    }

    if args.format == "json":
        dump_json({"meta": meta, "events": events}, args.out)
    elif args.format == "csv":
        write_out(render_csv(events), args.out)
    else:
        write_out(render_md(events, meta), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
