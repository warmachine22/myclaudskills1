#!/usr/bin/env python3
"""Run the market-evidence tools for one bundle and write evidence.json beside it.

Stage 1 of this skill collects what the company says about itself. This collects what the
market says about the company, from sources that are free and need no key:

  options        the implied move, skew and term structure into the next event
  comps          live relative valuation against a peer set the caller names
  reverse DCF    the free-cash-flow growth today's price already requires
  primary        revenue, margins, inventory, receivables and share count read straight
                 out of the SEC filings rather than an aggregator

None of it is opinion, and all of it is checkable. The reverse DCF is skipped rather than
faked when trailing free cash flow is negative, and every block records its own failure
instead of disappearing.

    python sf_evidence.py ./NVDA-bundle --peers AMD,AVGO,TSM,MU --event 2026-11-17
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def _run(script: str, args: list[str]) -> dict | None:
    """Invoke a sibling tool in JSON mode. Exit code 2 means an honest refusal."""
    cmd = [sys.executable, str(HERE / script), *args, "-f", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{script} timed out"}
    raw = (proc.stdout or "").strip()
    if not raw:
        return {"ok": False, "error": (proc.stderr or "no output")[-300:]}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"{script} returned non-JSON: {raw[:200]}"}


def build(folder: pathlib.Path, peers: list[str], event: str | None) -> dict:
    bundle = json.loads((folder / "bundle.json").read_text(encoding="utf-8"))
    ticker = bundle["meta"]["ticker"]
    quote = bundle.get("quote") or {}
    price = quote.get("price")
    snap = (bundle.get("finviz") or {}).get("snapshot") or {}

    def snap_num(key):
        cell = snap.get(key)
        if isinstance(cell, dict) and cell.get("num") is not None:
            return float(cell["num"])
        return None

    ev: dict = {"ticker": ticker, "price_at_build": price, "blocks": {}}

    event = event or (bundle.get("resolved") or {}).get("next_report_date")
    ev["blocks"]["options"] = _run(
        "sf_options.py", [ticker] + (["--event", event] if event else []))

    if peers:
        ev["blocks"]["comps"] = _run("sf_comps.py", [ticker, "--peers", ",".join(peers)])

    ev["blocks"]["primary"] = _run("sf_edgar.py", [ticker, "--facts"])

    # reverse DCF needs a positive cash stream; refuse loudly rather than invent one
    fcf = None
    for row in ((bundle.get("financials") or {}).get("income_annual") or {}).get("rows", []):
        if row.get("title") == "Free Cash Flow" and row.get("values"):
            fcf = row["values"][0]
            break
    shares = quote.get("shares")
    beta = snap_num("Beta") or 1.0
    cash_ps = snap_num("Cash/sh")
    mcap, evalue = snap_num("Market Cap"), snap_num("Enterprise Value")
    net_cash = None
    if mcap and evalue:
        net_cash = (mcap - evalue) / 1e6  # $m; positive means net cash
    elif cash_ps and shares:
        net_cash = cash_ps * shares / 1e6

    if fcf and fcf > 0 and shares:
        ev["blocks"]["reverse_dcf"] = _run("sf_reverse_dcf.py", [
            ticker, "--price", str(price), "--fcf", str(round(fcf / 1e6, 1)),
            "--shares", str(round(shares / 1e6, 1)),
            "--net-cash", str(round(net_cash or 0, 1)), "--beta", str(beta)])
    else:
        ev["blocks"]["reverse_dcf"] = {
            "ok": False,
            "error": (f"trailing free cash flow is {fcf if fcf is not None else 'unavailable'} - "
                      "a reverse DCF needs a positive cash stream to grow, so none was run "
                      "and no number is shown."),
            "skipped": True,
        }
    return ev


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("bundle")
    ap.add_argument("--peers", default="", help="comma-separated peer tickers")
    ap.add_argument("--event", help="date the option chain should bracket")
    args = ap.parse_args()
    folder = pathlib.Path(args.bundle)
    peers = [p.strip().upper() for p in args.peers.split(",") if p.strip()]
    ev = build(folder, peers, args.event)
    out = folder / "evidence.json"
    out.write_text(json.dumps(ev, indent=1), encoding="utf-8")
    ok = [k for k, v in ev["blocks"].items() if isinstance(v, dict) and v.get("ok")]
    bad = [k for k, v in ev["blocks"].items() if not (isinstance(v, dict) and v.get("ok"))]
    print(f"wrote {out}  ok: {', '.join(ok) or 'none'}"
          + (f"  |  unavailable: {', '.join(bad)}" if bad else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
