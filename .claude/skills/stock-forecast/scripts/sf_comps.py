#!/usr/bin/env python3
"""Relative valuation against a named peer set.

The first five forecasts this dashboard produced included two direct competitors
(Coherent and Lumentum), their largest supplier's customer (IREN) and the company at the
centre of all of it (NVIDIA) - and not one page referenced another. Each was valued only
against its own history. That is a real hole: a multiple is not high or low in the
abstract, it is high or low against the alternatives available on the same day.

This closes it. Peers are supplied explicitly rather than guessed from a sector code,
because "peer" is a judgment and a bad peer set produces a confident wrong answer. Every
figure is live from Yahoo, which is free and needs no key.

    python sf_comps.py COHR --peers LITE,APH,FN,AAOI,NVDA -f md
    python sf_comps.py TTWO --peers EA,RBLX,PLTK,U,MSFT

Reported per name: market cap, EV/Sales, forward P/E, PEG, gross and operating margin,
revenue growth, and where the subject ranks on each. The rank is the point - it converts
"expensive" into "third of six on forward earnings, first on growth".
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    print("yfinance is required: pip install yfinance", file=sys.stderr)
    raise

FIELDS = [
    ("market_cap", "Mkt cap", "marketCap", 1e-9, "$%.1fB"),
    ("ev_sales", "EV/Sales", "enterpriseToRevenue", 1, "%.1fx"),
    ("ev_ebitda", "EV/EBITDA", "enterpriseToEbitda", 1, "%.1fx"),
    ("fwd_pe", "Fwd P/E", "forwardPE", 1, "%.1fx"),
    ("peg", "PEG", "trailingPegRatio", 1, "%.2f"),
    ("gross_margin", "Gross %", "grossMargins", 100, "%.1f%%"),
    ("op_margin", "Op %", "operatingMargins", 100, "%.1f%%"),
    ("rev_growth", "Rev gth", "revenueGrowth", 100, "%.1f%%"),
    ("beta", "Beta", "beta", 1, "%.2f"),
]

# Higher is better for these; for the rest, lower is cheaper.
HIGHER_IS_RICHER = {"ev_sales", "ev_ebitda", "fwd_pe", "peg"}


def pull(ticker: str) -> dict:
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as exc:
        return {"ticker": ticker, "ok": False, "error": str(exc)[:120]}
    row = {"ticker": ticker, "ok": True, "name": info.get("shortName") or ticker}
    for key, _, src, scale, _ in FIELDS:
        val = info.get(src)
        try:
            row[key] = float(val) * scale if val is not None else None
        except (TypeError, ValueError):
            row[key] = None
    return row


def compare(subject: str, peers: list[str]) -> dict:
    tickers = [subject] + [p for p in peers if p != subject]
    rows = [pull(t) for t in tickers]
    good = [r for r in rows if r.get("ok")]

    stats = {}
    for key, *_ in [(f[0],) for f in FIELDS]:
        vals = [r[key] for r in good if r.get(key) is not None]
        if len(vals) >= 3:
            stats[key] = {"median": statistics.median(vals),
                          "min": min(vals), "max": max(vals), "n": len(vals)}

    # where the subject sits in the peer distribution
    subj = next((r for r in good if r["ticker"] == subject), None)
    ranks = {}
    if subj:
        for key, *_ in [(f[0],) for f in FIELDS]:
            vals = sorted([r[key] for r in good if r.get(key) is not None])
            if subj.get(key) is None or len(vals) < 3:
                continue
            pos = vals.index(subj[key]) + 1
            ranks[key] = {
                "rank": pos, "of": len(vals),  # ascending: 1 = lowest raw value
                "vs_median_pct": (round((subj[key] / stats[key]["median"] - 1) * 100, 1)
                                  if stats.get(key) and stats[key]["median"] else None),
                "direction": ("richer than peers" if key in HIGHER_IS_RICHER
                              and stats.get(key) and subj[key] > stats[key]["median"]
                              else "cheaper than peers" if key in HIGHER_IS_RICHER
                              else "above peers" if stats.get(key)
                              and subj[key] > stats[key]["median"] else "below peers"),
            }
    return {"ok": bool(subj and stats), "subject": subject, "rows": rows,
            "stats": stats, "ranks": ranks,
            "failed": [r["ticker"] for r in rows if not r.get("ok")]}


def fmt(key: str, value) -> str:
    if value is None:
        return "—"
    spec = next(f[4] for f in FIELDS if f[0] == key)
    try:
        return spec % value
    except (TypeError, ValueError):
        return "—"


def to_markdown(d: dict) -> str:
    heads = ["Ticker"] + [f[1] for f in FIELDS]
    out = [f"### {d['subject']} versus its peer set", "",
           "| " + " | ".join(heads) + " |",
           "|" + "---|" * len(heads)]
    for r in d["rows"]:
        if not r.get("ok"):
            out.append(f"| {r['ticker']} | " + " | ".join(["—"] * len(FIELDS)) + " |")
            continue
        mark = "**" if r["ticker"] == d["subject"] else ""
        cells = " | ".join(fmt(f[0], r.get(f[0])) for f in FIELDS)
        out.append(f"| {mark}{r['ticker']}{mark} | {cells} |")
    if d["stats"]:
        med = " | ".join(fmt(f[0], d["stats"].get(f[0], {}).get("median")) for f in FIELDS)
        out.append(f"| _median_ | {med} |")
    if d["ranks"]:
        out += ["", "**Where the subject sits**", ""]
        for key, r in d["ranks"].items():
            label = next(f[1] for f in FIELDS if f[0] == key)
            gap = (f", {r['vs_median_pct']:+.0f}% vs median"
                   if r.get("vs_median_pct") is not None else "")
            out.append(f"- {label}: {r['rank']} lowest of {r['of']} ({r['direction']}{gap})")
    if d["failed"]:
        out += ["", f"_No data for: {', '.join(d['failed'])}._"]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("subject")
    ap.add_argument("--peers", required=True, help="comma-separated tickers")
    ap.add_argument("-f", "--format", choices=("md", "json"), default="md")
    args = ap.parse_args()
    peers = [p.strip().upper() for p in args.peers.split(",") if p.strip()]
    result = compare(args.subject.upper(), peers)
    print(json.dumps(result, indent=2) if args.format == "json" else to_markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
