#!/usr/bin/env python3
"""A record of every call, marked to market.

This is the gap that mattered most and cost nothing to fill. Five forecasts were issued
with confident conviction labels and nothing recorded them, which made "high conviction"
an unfalsifiable word. A forecast process that does not keep score cannot improve; it can
only repeat.

The ledger is append-only JSON. Each entry is stamped at the moment of the call with the
price then, so returns cannot be quietly re-based later. Marking uses live Yahoo prices.

    python sf_ledger.py record --bundle ./NVDA-bundle --version v2
    python sf_ledger.py mark
    python sf_ledger.py report -f md

Three things it measures, none of which flatter:

  hit rate      did the direction pay? A BUY that fell is wrong however good the reasoning.
  edge vs SPY   the same call measured against just owning the index, which is the only
                benchmark that matters for a single-stock call.
  calibration   whether conviction actually sorts outcomes. If low-conviction calls do as
                well as high, the conviction label is noise and should be dropped.

Sample sizes here are tiny and will be for a long time. The report says so on every run
rather than letting a 3-for-5 hit rate read as skill.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
from datetime import date, datetime

try:
    import yfinance as yf
except ImportError:
    yf = None

LEDGER = pathlib.Path(__file__).resolve().parent.parent / "call-ledger.json"


def _load() -> list[dict]:
    if not LEDGER.exists():
        return []
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _save(rows: list[dict]) -> None:
    LEDGER.write_text(json.dumps(rows, indent=1), encoding="utf-8")


def record(bundle_dir: str, version: str = "v1", note: str = "") -> dict:
    folder = pathlib.Path(bundle_dir)
    bundle = json.loads((folder / "bundle.json").read_text(encoding="utf-8"))
    analysis = json.loads((folder / "analysis.json").read_text(encoding="utf-8"))

    weights = {"Valuation vs fair value": .22, "Earnings execution and delivery": .20,
               "Growth trajectory": .16, "Estimate revisions": .15,
               "Quality and balance sheet": .12, "Technical setup": .10,
               "Market and macro backdrop": .05}
    num = den = 0.0
    for row in analysis.get("scorecard") or []:
        if row.get("unavailable") or row.get("score") is None:
            continue
        w = float(row.get("weight") or weights.get(row.get("dimension"), 0))
        num += float(row["score"]) * w
        den += w

    entry = {
        "id": f"{bundle['meta']['ticker']}-{version}-{date.today().isoformat()}",
        "ticker": bundle["meta"]["ticker"],
        "version": version,
        "called_on": date.today().isoformat(),
        "collected_at": bundle["meta"].get("collected_at"),
        "price_at_call": (bundle.get("quote") or {}).get("price"),
        "rating": analysis.get("rating"),
        "conviction": analysis.get("conviction"),
        "composite": round(num / den, 4) if den else None,
        "target": (analysis.get("target_price") or {}).get("value"),
        "horizon": (analysis.get("target_price") or {}).get("horizon"),
        "street_target": ((bundle.get("forecast") or {}).get("price_target") or {}).get("average"),
        "next_report": (bundle.get("resolved") or {}).get("next_report_date"),
        "note": note,
    }
    rows = [r for r in _load() if r["id"] != entry["id"]]
    rows.append(entry)
    _save(rows)
    return entry


def _spot(ticker: str) -> float | None:
    if yf is None:
        return None
    try:
        h = yf.Ticker(ticker).history(period="5d")
        return float(h["Close"].iloc[-1]) if not h.empty else None
    except Exception:
        return None


def mark() -> list[dict]:
    rows = _load()
    spy = _spot("SPY")
    spy_hist = None
    if yf is not None:
        try:
            spy_hist = yf.Ticker("SPY").history(period="2y")
        except Exception:
            spy_hist = None

    for r in rows:
        px = _spot(r["ticker"])
        if px is None or not r.get("price_at_call"):
            continue
        r["price_now"] = round(px, 2)
        r["marked_on"] = date.today().isoformat()
        ret = px / float(r["price_at_call"]) - 1
        r["return_pct"] = round(ret * 100, 2)

        # benchmark over the identical window, so the comparison is apples to apples
        bench = None
        if spy_hist is not None and not spy_hist.empty and spy:
            try:
                start = datetime.strptime(r["called_on"], "%Y-%m-%d")
                window = spy_hist[spy_hist.index.tz_localize(None) >= start]
                if not window.empty:
                    bench = spy / float(window["Close"].iloc[0]) - 1
            except Exception:
                bench = None
        if bench is not None:
            r["spy_return_pct"] = round(bench * 100, 2)
            r["excess_pct"] = round((ret - bench) * 100, 2)

        # a SELL is right when the stock falls; direction, not magnitude
        signed = ret if str(r.get("rating")).upper() == "BUY" else -ret
        r["direction_correct"] = bool(signed > 0)
        r["signed_return_pct"] = round(signed * 100, 2)
        if r.get("excess_pct") is not None:
            signed_x = (r["excess_pct"] / 100) if str(r.get("rating")).upper() == "BUY" \
                else -(r["excess_pct"] / 100)
            r["signed_excess_pct"] = round(signed_x * 100, 2)
        if r.get("target") and r.get("price_at_call"):
            r["implied_at_call_pct"] = round(
                (float(r["target"]) / float(r["price_at_call"]) - 1) * 100, 2)
    _save(rows)
    return rows


def report() -> dict:
    rows = [r for r in _load() if r.get("return_pct") is not None]
    if not rows:
        return {"ok": False, "error": "nothing marked yet - run `mark` first"}
    signed = [r["signed_return_pct"] for r in rows]
    excess = [r["signed_excess_pct"] for r in rows if r.get("signed_excess_pct") is not None]
    out = {
        "ok": True,
        "calls": len(rows),
        "hit_rate_pct": round(100 * sum(1 for r in rows if r["direction_correct"]) / len(rows), 1),
        "mean_signed_return_pct": round(statistics.mean(signed), 2),
        "median_signed_return_pct": round(statistics.median(signed), 2),
        "mean_signed_excess_pct": round(statistics.mean(excess), 2) if excess else None,
        "by_conviction": {},
        "by_rating": {},
        "rows": sorted(rows, key=lambda r: r.get("signed_return_pct", 0), reverse=True),
        "health_warning": None,
    }
    for key, field in (("by_conviction", "conviction"), ("by_rating", "rating")):
        for r in rows:
            bucket = str(r.get(field) or "?").lower()
            out[key].setdefault(bucket, []).append(r["signed_return_pct"])
        out[key] = {k: {"n": len(v), "mean_signed_pct": round(statistics.mean(v), 2),
                        "hit_rate_pct": round(100 * sum(1 for x in v if x > 0) / len(v), 1)}
                    for k, v in out[key].items()}
    if len(rows) < 20:
        out["health_warning"] = (
            f"{len(rows)} marked calls. Nothing here is statistically meaningful - at this "
            "sample a single outcome moves the hit rate by double digits, and holding periods "
            "are far shorter than the 12-month horizon the targets were set on. Read it as "
            "bookkeeping, not as evidence of skill.")
    return out


def to_markdown(d: dict) -> str:
    if not d.get("ok"):
        return f"_{d.get('error')}_"
    L = [f"### Call ledger — {d['calls']} marked", "",
         f"- Hit rate **{d['hit_rate_pct']:.0f}%** (direction correct)",
         f"- Mean signed return **{d['mean_signed_return_pct']:+.2f}%** · "
         f"median {d['median_signed_return_pct']:+.2f}%"]
    if d.get("mean_signed_excess_pct") is not None:
        L.append(f"- Mean signed excess over SPY **{d['mean_signed_excess_pct']:+.2f}%**")
    L += ["", "| Call | Rating | Conv | Called | Price then | Now | Return | Signed | vs SPY |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in d["rows"]:
        xs = (f"{r['signed_excess_pct']:+.1f}%"
              if r.get("signed_excess_pct") is not None else "-")
        L.append(
            f"| {r['ticker']} {r.get('version', '')} | {r.get('rating')} "
            f"| {r.get('conviction')} | {r.get('called_on')} "
            f"| ${r['price_at_call']:,.2f} | ${r['price_now']:,.2f} "
            f"| {r['return_pct']:+.1f}% | {r['signed_return_pct']:+.1f}% | {xs} |")
    if d.get("by_conviction"):
        L += ["", "**By conviction** (does the label sort outcomes?)", ""]
        for k, v in d["by_conviction"].items():
            L.append(f"- {k}: n={v['n']}, mean {v['mean_signed_pct']:+.2f}%, "
                     f"hit {v['hit_rate_pct']:.0f}%")
    if d.get("health_warning"):
        L += ["", f"> {d['health_warning']}"]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record"); rec.add_argument("--bundle", required=True)
    rec.add_argument("--version", default="v1"); rec.add_argument("--note", default="")
    sub.add_parser("mark")
    rep = sub.add_parser("report"); rep.add_argument("-f", "--format",
                                                     choices=("md", "json"), default="md")
    args = ap.parse_args()

    if args.cmd == "record":
        print(json.dumps(record(args.bundle, args.version, args.note), indent=2))
    elif args.cmd == "mark":
        rows = mark()
        print(f"marked {sum(1 for r in rows if r.get('price_now'))} of {len(rows)} calls")
    else:
        d = report()
        print(json.dumps(d, indent=2) if args.format == "json" else to_markdown(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
