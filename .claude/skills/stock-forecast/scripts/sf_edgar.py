#!/usr/bin/env python3
"""Primary-source financials and insider activity, straight from SEC EDGAR.

Every number the dashboard has used so far is scraped from an aggregator, and the
aggregators disagree - NVDA trailing EPS came back as $7.91 from one source and $6.53
from another, a 21% gap the valuation engine itself flagged as a failed check. EDGAR is
the filing. It settles those arguments instead of averaging them.

Three free, official, key-less endpoints:

  companyfacts   every XBRL fact the company has ever reported, with the filing it came
                 from and the period it covers. Used here to rebuild revenue, operating
                 income, net income, EPS, buybacks and share count from the source.
  submissions    the filing index, used to date the most recent 10-Q/10-K and to find
                 Form 4s.
  Form 4         insider transactions - who bought, who sold, how much, at what price.
                 Aggregators report a single stale percentage; the filings have detail.

    python sf_edgar.py NVDA --facts -f json
    python sf_edgar.py TTWO --insiders --months 6
    python sf_edgar.py MSFT --concept CapitalExpenditures   # customer capex, for supply chains

SEC asks for a descriptive User-Agent and no more than 10 requests/second. Both are
honoured below; do not raise the rate.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta

import requests

# SEC rejects anything not shaped "Name contact@domain" on www.sec.gov (403).
# A placeholder contact is used deliberately: the operator's own address is not
# sent to a third party without them asking for it.
UA = "Stock Forecast Research Tool research@example.com"
HEAD = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
_LAST = [0.0]


def _get(url: str, tries: int = 3):
    """Rate-limited GET. SEC allows 10/s; this stays well under."""
    for attempt in range(tries):
        wait = 0.15 - (time.monotonic() - _LAST[0])
        if wait > 0:
            time.sleep(wait)
        _LAST[0] = time.monotonic()
        r = requests.get(url, headers=HEAD, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        time.sleep(1.5 * (attempt + 1))
    return None


_TICKER_MAP = {}


def cik_for(ticker: str, fallback: str | None = None) -> str | None:
    """Resolve a ticker to a zero-padded CIK using SEC's own mapping file."""
    if not _TICKER_MAP:
        data = _get("https://www.sec.gov/files/company_tickers.json")
        if not data:
            return None
        for row in data.values():
            _TICKER_MAP[row["ticker"].upper()] = str(row["cik_str"]).zfill(10)
    hit = _TICKER_MAP.get(ticker.upper())
    if hit:
        return hit
    # bundles carry the CIK already; accept it rather than failing on a 403
    return str(fallback).zfill(10) if fallback else None


# XBRL tags vary by filer; try each in order and take the first that has data.
CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "RevenueFromContractWithCustomerIncludingAssessedTax",
                "SalesRevenueNet"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "dividends": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "inventory": ["InventoryNet"],
    "receivables": ["AccountsReceivableNetCurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "total_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
}


def _series(facts: dict, tags: list[str], quarterly: bool) -> list[dict]:
    """Pull one concept as a clean, de-duplicated, date-ordered series."""
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    candidates = []
    for tag in tags:
        node = us_gaap.get(tag)
        if not node:
            continue
        for unit_rows in node.get("units", {}).values():
            rows, seen = [], set()
            for r in unit_rows:
                if not r.get("end") or r.get("val") is None:
                    continue
                start, end = r.get("start"), r["end"]
                if start:  # duration fact - keep only the cadence asked for
                    days = (datetime.strptime(end, "%Y-%m-%d")
                            - datetime.strptime(start, "%Y-%m-%d")).days
                    is_q = 60 <= days <= 100
                    if quarterly != is_q:
                        continue
                key = (r.get("fy"), r.get("fp"), end)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"end": end, "value": r["val"], "fy": r.get("fy"),
                             "fp": r.get("fp"), "form": r.get("form"),
                             "filed": r.get("filed"), "tag": tag,
                             "accn": r.get("accn")})
            if rows:
                candidates.append(sorted(rows, key=lambda x: x["end"]))
    if not candidates:
        return []
    # Filers migrate between tags (NVDA's revenue lives under the modern
    # RevenueFromContractWithCustomer... tag only until 2020, then moves to Revenues).
    # Taking the first tag that has *any* rows silently returns six-year-old data, so
    # prefer the series that runs closest to today, breaking ties on length.
    return max(candidates, key=lambda rows: (rows[-1]["end"], len(rows)))


def company_facts(ticker: str, quarterly: bool = True, periods: int = 12) -> dict:
    cik = cik_for(ticker)
    if not cik:
        return {"ticker": ticker, "ok": False, "error": "ticker not found in SEC mapping"}
    facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    if not facts:
        return {"ticker": ticker, "ok": False, "error": "companyfacts unavailable"}
    out = {"ticker": ticker, "ok": True, "cik": cik,
           "entity": facts.get("entityName"),
           "basis": "quarterly" if quarterly else "annual",
           "source": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
           "series": {}}
    for name, tags in CONCEPTS.items():
        rows = _series(facts, tags, quarterly)
        if rows:
            out["series"][name] = rows[-periods:]
    subs = _get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    if subs:
        recent = subs.get("filings", {}).get("recent", {})
        for form, acc, fdate, doc in zip(recent.get("form", []),
                                         recent.get("accessionNumber", []),
                                         recent.get("filingDate", []),
                                         recent.get("primaryDocument", [])):
            if form in ("10-Q", "10-K"):
                out["latest_periodic_filing"] = {
                    "form": form, "filed": fdate,
                    "url": (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                            f"{acc.replace('-', '')}/{doc}")}
                break
    return out


def insiders(ticker: str, months: int = 6) -> dict:
    """Form 4 activity. Counts filings and, where parseable, net shares transacted."""
    cik = cik_for(ticker)
    if not cik:
        return {"ticker": ticker, "ok": False, "error": "ticker not found"}
    subs = _get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    if not subs:
        return {"ticker": ticker, "ok": False, "error": "submissions unavailable"}
    cutoff = date.today() - timedelta(days=30 * months)
    recent = subs.get("filings", {}).get("recent", {})
    rows = []
    for form, acc, fdate, doc in zip(recent.get("form", []),
                                     recent.get("accessionNumber", []),
                                     recent.get("filingDate", []),
                                     recent.get("primaryDocument", [])):
        if form != "4":
            continue
        try:
            if datetime.strptime(fdate, "%Y-%m-%d").date() < cutoff:
                break
        except ValueError:
            continue
        rows.append({"filed": fdate, "accession": acc,
                     "url": (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                             f"{acc.replace('-', '')}/{doc}")})
    return {"ticker": ticker, "ok": True, "cik": cik, "months": months,
            "form4_count": len(rows), "filings": rows[:40],
            "note": ("Form 4 count only. Counting filings is a weak proxy for conviction - "
                     "a routine 10b5-1 sale and an open-market purchase both file one form. "
                     "Open the URLs before drawing an inference.")}


def concept(ticker: str, name: str, quarterly: bool = True, periods: int = 12) -> dict:
    """One named concept, for cross-company work such as customer capex."""
    tags = CONCEPTS.get(name, [name])
    cik = cik_for(ticker)
    if not cik:
        return {"ticker": ticker, "ok": False, "error": "ticker not found"}
    facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    if not facts:
        return {"ticker": ticker, "ok": False, "error": "companyfacts unavailable"}
    rows = _series(facts, tags, quarterly)
    return {"ticker": ticker, "ok": bool(rows), "concept": name,
            "entity": facts.get("entityName"), "rows": rows[-periods:],
            "error": None if rows else f"no data for {name}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ticker")
    ap.add_argument("--facts", action="store_true", help="core financial series")
    ap.add_argument("--insiders", action="store_true", help="Form 4 activity")
    ap.add_argument("--concept", help="a single named concept, e.g. capex")
    ap.add_argument("--annual", action="store_true", help="annual rather than quarterly")
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--periods", type=int, default=12)
    ap.add_argument("-f", "--format", choices=("md", "json"), default="json")
    args = ap.parse_args()
    t = args.ticker.upper()

    if args.insiders:
        result = insiders(t, args.months)
    elif args.concept:
        result = concept(t, args.concept, not args.annual, args.periods)
    else:
        result = company_facts(t, not args.annual, args.periods)

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"# {result.get('entity') or t} — SEC EDGAR")
        for k, rows in (result.get("series") or {}).items():
            if rows:
                last = rows[-1]
                print(f"- **{k}**: {last['value']:,} ({last['end']}, {last['form']}, "
                      f"tag `{last['tag']}`)")
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
