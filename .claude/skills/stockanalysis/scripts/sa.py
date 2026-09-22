#!/usr/bin/env python3
"""stockanalysis.com scraper -- grounded fundamentals, filings and transcripts.

Run `python sa.py --help` for the command list.
Every command takes `--format json|md` and `--out FILE`.
"""

from __future__ import annotations

import argparse
import sys

import sa_core as sa
import sa_pages as pages

# Windows consoles default to cp1252 and choke on the site's typographic
# punctuation; force UTF-8 so piping and printing both survive.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="sa.py",
        description="Pull grounded data from stockanalysis.com.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Tickers: NVDA (US stock) | SPY (auto-detects ETF) | TSX:SHOP (non-US)\n"
            "Data is cached on disk; use --refresh to bypass, `cache-clear` to wipe."
        ),
    )
    ap.add_argument("--format", "-f", choices=("md", "json"), default="md",
                    help="output format (default md -- compact and LLM-friendly)")
    ap.add_argument("--out", "-o", help="write to this file instead of stdout")
    ap.add_argument("--refresh", action="store_true", help="ignore cache")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        """Accept the global flags after the subcommand too -- `sa.py brief NVDA
        --out x.md` is the order people actually type."""
        p.add_argument("--format", "-f", choices=("md", "json"), default=None,
                       dest="_format")
        p.add_argument("--out", "-o", default=None, dest="_out")
        p.add_argument("--refresh", action="store_true", dest="_refresh")
        return p

    def add(name, help_):
        p = common(sub.add_parser(name, help=help_))
        p.add_argument("ticker")
        return p

    add("overview", "snapshot: price, valuation, analyst view, next earnings date")
    add("quote", "just the live/last quote")
    add("company", "business description, sector, employees, executives, contact")
    add("statistics", "the full statistics grid (valuation, margins, short interest...)")
    add("forecast", "analyst ratings, price targets, revenue/EPS estimates by year & quarter")
    add("news", "recent news headlines with summaries")
    add("dividend", "dividend summary and full payment history")
    add("ratings", "recent individual analyst rating actions")
    add("employees", "headcount history, revenue/profit per employee, peers")

    p = add("financials", "income statement / balance sheet / cash flow / ratios")
    p.add_argument("--statement", "-s", default="overview",
                   choices=("overview", "income", "balance", "cash-flow", "ratios"))
    p.add_argument("--period", "-p", default="annual",
                   choices=("annual", "quarterly", "trailing"))
    p.add_argument("--limit", type=int, default=0,
                   help="keep only the N most recent periods (0 = all returned)")

    p = add("metrics", "company-specific breakdowns (revenue by segment/geography, ...)")
    p.add_argument("--sub", "-s", default=None,
                   help="sub-page slug, or 'all'; omit to list what's available")
    p.add_argument("--period", "-p", default=None, choices=("quarterly", "trailing"),
                   help="default: both")
    p.add_argument("--tail", type=int, default=0,
                   help="keep only the N most recent periods per series")

    p = add("filings", "IR document list (earnings releases, decks, reports, proxies)")
    p.add_argument("--type", "-t", default=None,
                   help="slides|earnings_release|quarterly_report|annual_report|"
                        "proxy|press_release|registration (10-K/10-Q/8-K also accepted)")
    p.add_argument("--limit", type=int, default=50, help="0 = no limit")

    p = add("download", "download those IR documents as PDFs")
    p.add_argument("--type", "-t", default=None, help="same values as `filings --type`")
    p.add_argument("--dir", "-d", default=None, help="output directory (default ./TICKER-documents)")
    p.add_argument("--limit", type=int, default=0, help="cap the number of files")
    p.add_argument("--latest", action="store_true",
                   help="only the most recent event's documents")
    p.add_argument("--event", default=None, help="one event id (from `filings --format json`)")
    p.add_argument("--since", default=None, help="only documents dated on/after YYYY-MM-DD")
    p.add_argument("--overwrite", action="store_true", help="re-download existing files")

    p = add("transcripts", "earnings call transcript index")
    p.add_argument("--limit", type=int, default=20, help="0 = no limit")
    p.add_argument("--all", action="store_true",
                   help="include non-earnings events too (keynotes, AGMs, conferences)")

    p = common(sub.add_parser("transcript", help="one full earnings call transcript"))
    p.add_argument("ticker")
    p.add_argument("quarter", nargs="?", default="latest",
                   help="'latest', 'q1-2027', a full slug, or an index (0 = newest)")
    p.add_argument("--no-body", action="store_true", help="metadata + summary only")

    p = add("history", "historical price / return table")
    p.add_argument("--range", "-r", default=None, help="e.g. 1Y, 5Y, MAX")

    p = add("brief", "EARNINGS BRIEFING PACK -- everything needed to script a video")
    p.add_argument("--transcripts", "-n", type=int, default=2,
                   help="how many recent call transcripts to include (default 2)")
    p.add_argument("--no-transcript-body", action="store_true",
                   help="include transcript metadata but not the full text")

    p = common(sub.add_parser("raw", help="escape hatch: dump any page's decoded payload"))
    p.add_argument("path", help="site-relative path, e.g. /stocks/nvda/dividend/")
    p.add_argument("--param", "-P", action="append", default=[],
                   help="query param as key=value (repeatable)")
    p.add_argument("--node", type=int, default=None, help="dump one node index")

    sub.add_parser("cache-clear", help="delete the on-disk cache")
    return ap


HANDLERS = {
    "overview": pages.cmd_overview,
    "quote": pages.cmd_quote,
    "company": pages.cmd_company,
    "statistics": pages.cmd_statistics,
    "forecast": pages.cmd_forecast,
    "news": pages.cmd_news,
    "financials": pages.cmd_financials,
    "metrics": pages.cmd_metrics,
    "filings": pages.cmd_filings,
    "download": pages.cmd_download,
    "transcripts": pages.cmd_transcripts,
    "transcript": pages.cmd_transcript,
    "history": pages.cmd_history,
    "dividend": pages.cmd_dividend,
    "ratings": pages.cmd_ratings,
    "employees": pages.cmd_employees,
    "brief": pages.cmd_brief,
    "raw": pages.cmd_raw,
}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # Subcommand-level flags win over the global ones when both are given.
    for name in ("format", "out", "refresh"):
        v = getattr(args, "_" + name, None)
        if v:
            setattr(args, name, v)
    if args.cmd == "cache-clear":
        print(f"removed {sa.clear_cache()} cached responses", file=sys.stderr)
        return 0
    try:
        HANDLERS[args.cmd](args)
    except sa.NotFound as e:
        print(f"not found: {e}", file=sys.stderr)
        print("check the ticker, or use `raw` to probe the path directly.", file=sys.stderr)
        return 1
    except sa.FetchError as e:
        print(f"fetch failed: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
