#!/usr/bin/env python3
"""Earnings calendar from tradingeconomics.com/earnings.

The page is a Next.js app whose data comes from React Server Actions. Calling
those actions directly returns clean JSON — no HTML parsing, so a restyle can't
silently corrupt numbers.

  fetchEarningsAction            [{"startDate","endDate","group"|"countries"}]
  fetchHistoricalEarningsAction  ["SYMBOL:CC"]   past + next reports for one name
  fetchAllCompaniesAction        []              every covered company

Action IDs are build-specific, so they are rediscovered from the page's JS
chunks whenever a call fails and cached on disk.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from te_core import (  # noqa: E402
    CACHE_DIR, DEFAULT_TTL, RANGES, cache_clear, country_list, day_label,
    dump_json, esc, fetch, parse_date, resolve_range, stars, write_out,
)

PAGE = "https://tradingeconomics.com/earnings"
IDS_FILE = os.path.join(CACHE_DIR, "action-ids.json")

# Known-good IDs as of the last time this skill was verified; refreshed
# automatically when the site redeploys.
FALLBACK_IDS = {
    "fetchEarningsAction": "40a526eb9d810cb916c90828a025233f3c0da554f7",
    "fetchHistoricalEarningsAction": "40529ca07fd1acb4cb850c3e4dbf9cc7f8d91499b6",
    "fetchAllCompaniesAction": "00e3c69d73e5158387ed173fbd6ca5bdab838ad416",
}

GROUPS = {"g20", "world", "africa", "america", "asia", "europe"}

SESSION_LABEL = {"AM": "before open", "PM": "after close", "": "unspecified"}


# --------------------------------------------------------------------------
# Server-action plumbing
# --------------------------------------------------------------------------

def _load_ids():
    try:
        with open(IDS_FILE, encoding="utf-8") as fh:
            got = json.load(fh)
        if all(k in got for k in FALLBACK_IDS):
            return got
    except (OSError, ValueError):
        pass
    return dict(FALLBACK_IDS)


def _save_ids(ids):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(IDS_FILE, "w", encoding="utf-8") as fh:
            json.dump(ids, fh)
    except OSError:
        pass


def discover_ids():
    """Re-read the action IDs out of the live page's JS chunks."""
    page = fetch(PAGE, ttl=0)
    chunks = sorted(set(re.findall(r"_next/static/chunks/[A-Za-z0-9]+\.js", page)))
    found = {}
    for path in chunks:
        js = fetch("https://tradingeconomics.com/" + path, ttl=86400)
        for aid, fname in re.findall(
            r'createServerReference\)?\("([0-9a-f]{32,64})"[^)]*?"(\w+Action)"', js
        ):
            found[fname] = aid
        if all(k in found for k in FALLBACK_IDS):
            break
    if not found.get("fetchEarningsAction"):
        raise SystemExit(
            "could not find the earnings server action on tradingeconomics.com — "
            "the page structure changed; see the Maintenance section of SKILL.md"
        )
    ids = dict(FALLBACK_IDS)
    ids.update(found)
    _save_ids(ids)
    return ids


def call_action(name, payload, ttl=DEFAULT_TTL, _retry=True):
    ids = _load_ids()
    body = json.dumps(payload, separators=(",", ":"))
    text = fetch(
        PAGE, data=body, ttl=ttl, soft=_retry,
        headers={
            "Accept": "text/x-component",
            "Content-Type": "text/plain;charset=UTF-8",
            "next-action": ids[name],
            "Origin": "https://tradingeconomics.com",
            "Referer": PAGE,
        },
    )
    data = _parse_flight(text) if text else None
    if data is None:
        if _retry:
            print("re-discovering tradingeconomics server action IDs...", file=sys.stderr)
            discover_ids()
            return call_action(name, payload, ttl=0, _retry=False)
        raise SystemExit(
            f"{name} returned no usable payload — the earnings page changed; "
            "see the Maintenance section of SKILL.md"
        )
    return data


def _parse_flight(text):
    """Pull the data array out of a React-Flight response.

    Lines look like `1:[{...}]`. Flight escapes a leading '$' as '$$'.
    """
    for line in text.splitlines():
        m = re.match(r"^[0-9a-f]+:(\[.*)$", line)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return _unescape(data)
    return None


def _unescape(node):
    if isinstance(node, str):
        return node[1:] if node.startswith("$$") else node
    if isinstance(node, list):
        return [_unescape(x) for x in node]
    if isinstance(node, dict):
        return {k: _unescape(v) for k, v in node.items()}
    return node


# --------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------

def get_earnings(start, end, group="world", countries=None, ttl=DEFAULT_TTL):
    arg = {"startDate": start, "endDate": end}
    if countries:
        arg["countries"] = ",".join(countries)
    else:
        arg["group"] = group
    rows = call_action("fetchEarningsAction", [arg], ttl=ttl)
    return [normalise(r) for r in rows]


def get_company_history(symbol, ttl=DEFAULT_TTL):
    sym = symbol.strip().upper()
    if ":" not in sym:
        sym += ":US"
    rows = call_action("fetchHistoricalEarningsAction", [sym], ttl=ttl)
    return [normalise(r) for r in rows]


def get_companies(ttl=86400):
    return call_action("fetchAllCompaniesAction", [], ttl=ttl)


def find_company(query, ttl=86400):
    q = query.strip().lower()
    hits = []
    for c in get_companies(ttl):
        sym, name = c.get("symbol", ""), c.get("name", "")
        if q == sym.lower() or q == f"{sym}:{c.get('countryCode','')}".lower():
            hits.insert(0, c)
        elif q in sym.lower() or q in name.lower():
            hits.append(c)
    return hits


# --------------------------------------------------------------------------
# Shaping
# --------------------------------------------------------------------------

_MULT = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def to_number(text):
    if text in (None, "", "-"):
        return None
    t = str(text).strip().replace(",", "").lstrip("$€£¥")
    mult = _MULT.get(t[-1:].upper(), 1)
    if mult != 1:
        t = t[:-1]
    try:
        return float(t) * mult
    except ValueError:
        return None


def surprise(actual, forecast):
    a, f = to_number(actual), to_number(forecast)
    if a is None or f is None or f == 0:
        return None
    return (a - f) / abs(f) * 100.0


def normalise(row):
    eps = row.get("eps") or {}
    rev = row.get("revenue") or {}
    out = {
        "date": row.get("date"),
        "symbol": row.get("symbol"),
        "name": row.get("name"),
        "country": row.get("country"),
        "iso2": row.get("iso2"),
        "importance": row.get("importance"),
        "fiscal": row.get("fiscalReference"),
        "session": (row.get("session") or "").upper(),
        "market_cap": row.get("marketCap"),
        "market_cap_num": to_number((row.get("marketCap") or "").lstrip("$")),
        "eps_actual": eps.get("actual"),
        "eps_consensus": eps.get("forecast"),
        "eps_previous": eps.get("previous"),
        "revenue_actual": rev.get("actual"),
        "revenue_consensus": rev.get("forecast"),
        "revenue_previous": rev.get("previous"),
        "url": row.get("companyUrl"),
    }
    out["eps_surprise_pct"] = surprise(out["eps_actual"], out["eps_consensus"])
    out["revenue_surprise_pct"] = surprise(out["revenue_actual"], out["revenue_consensus"])
    out["reported"] = out["eps_actual"] not in (None, "") or out["revenue_actual"] not in (None, "")
    return out


def beat_tag(pct):
    """Percent surprise, clamped so a near-zero consensus can't produce noise."""
    if pct is None:
        return ""
    if abs(pct) > 999:
        return "beat >>est" if pct > 0 else "miss <<est"
    if pct > 0.5:
        return f"beat +{pct:.0f}%"
    if pct < -0.5:
        return f"miss {pct:.0f}%"
    return "in line"


def sort_events(rows, key):
    if key == "cap":
        rows.sort(key=lambda r: -(r["market_cap_num"] or 0))
    elif key == "surprise":
        rows.sort(key=lambda r: -(abs(r["eps_surprise_pct"]) if r["eps_surprise_pct"] is not None else -1))
    elif key == "impact":
        rows.sort(key=lambda r: (r["date"] or "", -(r["importance"] or 0), -(r["market_cap_num"] or 0)))
    else:  # date
        rows.sort(key=lambda r: (r["date"] or "", r["session"] or "z", -(r["market_cap_num"] or 0)))
    return rows


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def _cap(row):
    return (row["market_cap"] or "").replace("$", "$") or ""


def render_md(rows, meta):
    lines = [f"# Earnings calendar — {meta['start']} to {meta['end']}"]
    bits = [f"{len(rows)} companies"]
    if meta["impact"] > 1:
        bits.insert(0, f"impact {'*' * meta['impact']}+ only")
    bits.append("scope: " + (",".join(meta["countries"]) if meta["countries"] else meta["group"]))
    lines.append("_" + " · ".join(bits) + "_")
    lines.append("")
    if not rows:
        lines.append("No companies report in this window with these filters.")
        return "\n".join(lines)

    n3 = sum(1 for r in rows if r["importance"] == 3)
    n2 = sum(1 for r in rows if r["importance"] == 2)
    n1 = sum(1 for r in rows if (r["importance"] or 1) == 1)
    reported = sum(1 for r in rows if r["reported"])
    lines.append(f"**By impact:** {n3} high (***) · {n2} medium (**) · {n1} low (*) "
                 f"— {reported} already reported, {len(rows) - reported} still to come")
    lines.append("")

    grouped = meta.get("sort", "date") in ("date", "impact")
    header = ("| Imp | Ticker | Company | When | EPS act / est | Rev act / est | "
              "vs est | Mkt cap | FQ |")
    rule = "|---|---|---|---|---|---|---|---|---|"

    def row_md(r, with_date=False):
        eps = f"{r['eps_actual'] or '—'} / {r['eps_consensus'] or '—'}"
        rev = f"{r['revenue_actual'] or '—'} / {r['revenue_consensus'] or '—'}"
        cells = [stars(r["importance"]), esc(r["symbol"]), esc(r["name"]),
                 SESSION_LABEL.get(r["session"], r["session"] or ""),
                 esc(eps), esc(rev), beat_tag(r["eps_surprise_pct"]),
                 esc(_cap(r)), esc(r["fiscal"] or "")]
        if with_date:
            cells.insert(0, r["date"] or "")
        return "| " + " | ".join(cells) + " |"

    if not grouped:
        lines.append("| Date " + header)
        lines.append("|---" + rule)
        for r in rows:
            lines.append(row_md(r, with_date=True))
        lines.append("")
    else:
        current = None
        for idx, r in enumerate(rows):
            if r["date"] != current:
                current = r["date"]
                lines += [f"## {day_label(current)}", "", header, rule]
            lines.append(row_md(r))
            if idx + 1 == len(rows) or rows[idx + 1]["date"] != r["date"]:
                lines.append("")
    lines.append(f"Source: {PAGE} (fetched {meta['fetched_at']}). "
                 "EPS/revenue in the company's reporting currency; "
                 "`vs est` compares reported EPS to consensus.")
    return "\n".join(lines)


def render_csv(rows):
    cols = ["date", "symbol", "name", "country", "importance", "session", "fiscal",
            "eps_actual", "eps_consensus", "eps_previous", "eps_surprise_pct",
            "revenue_actual", "revenue_consensus", "revenue_previous",
            "revenue_surprise_pct", "market_cap", "url"]
    out = [",".join(cols)]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c)
            v = "" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))
            cells.append('"' + v.replace('"', '""') + '"' if any(x in v for x in ',"\n') else v)
        out.append(",".join(cells))
    return "\n".join(out)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="te_earnings.py",
        description="Who reports earnings when, with consensus vs actual, from "
                    "tradingeconomics.com/earnings.",
    )
    sub = p.add_subparsers(dest="cmd")

    cal = sub.add_parser("calendar", help="earnings over a date window (default command)")
    cal.add_argument("range", nargs="?", default="thisweek",
                     help="preset window: " + ", ".join(RANGES) + " (default thisweek)")
    cal.add_argument("--start")
    cal.add_argument("--end")
    cal.add_argument("--impact", "-i", type=int, choices=[1, 2, 3], default=1,
                     help="minimum star level: 3 = market movers only (default 1 = all)")
    cal.add_argument("--group", "-g", default="world",
                     help="g20, world, america, europe, asia, africa (default world)")
    cal.add_argument("--countries", "-c",
                     help="comma list of countries/ISO codes; overrides --group")
    cal.add_argument("--min-cap", help="drop companies below this market cap, e.g. 10B")
    cal.add_argument("--reported", choices=["yes", "no"],
                     help="yes = only names that already reported; no = only upcoming")
    cal.add_argument("--sort", choices=["date", "cap", "impact", "surprise"], default="date")
    cal.add_argument("--search", help="filter by ticker or company name substring")
    cal.add_argument("--limit", type=int)
    cal.add_argument("--format", "-f", choices=["md", "json", "csv"], default="md")
    cal.add_argument("--out", "-o")
    cal.add_argument("--refresh", action="store_true")

    co = sub.add_parser("company", help="one company's report history + next date")
    co.add_argument("symbol", help="ticker, e.g. NVDA or NVDA:US or SHOP:CN")
    co.add_argument("--limit", type=int, default=12)
    co.add_argument("--format", "-f", choices=["md", "json", "csv"], default="md")
    co.add_argument("--out", "-o")
    co.add_argument("--refresh", action="store_true")

    se = sub.add_parser("search", help="look up a company's TE ticker by name")
    se.add_argument("query")
    se.add_argument("--limit", type=int, default=15)

    sub.add_parser("cache-clear", help="wipe cached responses")
    sub.add_parser("refresh-ids", help="re-discover the server action IDs")

    argv = list(sys.argv[1:] if argv is None else argv)
    known = {"calendar", "company", "search", "cache-clear", "refresh-ids"}
    if argv and argv[0] not in known and argv[0] not in ("-h", "--help"):
        argv = ["calendar"] + argv
    elif not argv:
        argv = ["calendar"]
    args = p.parse_args(argv)

    if args.cmd == "cache-clear":
        print(f"cleared {cache_clear()} cached responses", file=sys.stderr)
        return 0
    if args.cmd == "refresh-ids":
        print(json.dumps(discover_ids(), indent=2))
        return 0
    if args.cmd == "search":
        hits = find_company(args.query)[: args.limit]
        if not hits:
            print(f"no company matched '{args.query}'")
            return 1
        for c in hits:
            print(f"{c['symbol']}:{c['countryCode']:<3} {c['name']}")
        return 0

    ttl = 0 if args.refresh else DEFAULT_TTL

    if args.cmd == "company":
        rows = get_company_history(args.symbol, ttl)
        if not rows:
            print(f"no earnings history for '{args.symbol}'. Try: "
                  f"te_earnings.py search {args.symbol}", file=sys.stderr)
            return 1
        rows.sort(key=lambda r: r["date"] or "", reverse=True)
        rows = rows[: args.limit]
        if args.format == "json":
            dump_json(rows, args.out)
        elif args.format == "csv":
            write_out(render_csv(rows), args.out)
        else:
            head = rows[0]
            lines = [f"# {head['name']} ({head['symbol']}) — earnings history",
                     f"_{head['country']} · impact {stars(head['importance'])} · "
                     f"market cap {head['market_cap']}_", "",
                     "| Date | FQ | When | EPS act / est | vs est | Prev EPS | "
                     "Rev act / est | Prev rev |", "|---|---|---|---|---|---|---|---|"]
            for r in rows:
                lines.append(
                    "| {d} | {fq} | {s} | {ea} / {ee} | {t} | {ep} | {ra} / {re_} | {rp} |".format(
                        d=r["date"], fq=r["fiscal"] or "",
                        s=SESSION_LABEL.get(r["session"], r["session"] or ""),
                        ea=r["eps_actual"] or "—", ee=r["eps_consensus"] or "—",
                        t=beat_tag(r["eps_surprise_pct"]), ep=r["eps_previous"] or "—",
                        ra=r["revenue_actual"] or "—", re_=r["revenue_consensus"] or "—",
                        rp=r["revenue_previous"] or "—",
                    )
                )
            upcoming = [r for r in rows if not r["reported"]]
            if upcoming:
                nxt = min(upcoming, key=lambda r: r["date"])
                lines += ["", f"**Next report:** {day_label(nxt['date'])} "
                              f"({SESSION_LABEL.get(nxt['session'], 'time TBC')}), "
                              f"consensus EPS {nxt['eps_consensus'] or 'n/a'}, "
                              f"revenue {nxt['revenue_consensus'] or 'n/a'}."]
            lines += ["", f"Source: {head['url']}"]
            write_out("\n".join(lines), args.out)
        return 0

    # calendar
    if args.start or args.end:
        start = parse_date(args.start) if args.start else None
        end = parse_date(args.end) if args.end else start
        start = start or end
    else:
        start, end = resolve_range(args.range)
    if end < start:
        start, end = end, start

    group = str(args.group).strip().lower()
    if group not in GROUPS:
        raise SystemExit(f"unknown group '{args.group}'. Options: {', '.join(sorted(GROUPS))}")
    countries = country_list(args.countries)

    rows = get_earnings(start, end, group, countries, ttl)
    rows = [r for r in rows if (r["importance"] or 1) >= args.impact]
    if args.min_cap:
        floor = to_number(args.min_cap)
        if floor:
            rows = [r for r in rows if (r["market_cap_num"] or 0) >= floor]
    if args.reported == "yes":
        rows = [r for r in rows if r["reported"]]
    elif args.reported == "no":
        rows = [r for r in rows if not r["reported"]]
    if args.search:
        q = args.search.lower()
        rows = [r for r in rows
                if q in (r["symbol"] or "").lower() or q in (r["name"] or "").lower()]
    sort_events(rows, args.sort)
    if args.limit:
        rows = rows[: args.limit]

    meta = {
        "start": start, "end": end, "impact": args.impact, "group": group,
        "countries": countries, "count": len(rows), "sort": args.sort,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": PAGE,
    }
    if args.format == "json":
        dump_json({"meta": meta, "earnings": rows}, args.out)
    elif args.format == "csv":
        write_out(render_csv(rows), args.out)
    else:
        write_out(render_md(rows, meta), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
