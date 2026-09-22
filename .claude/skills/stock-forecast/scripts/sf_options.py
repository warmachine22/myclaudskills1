#!/usr/bin/env python3
"""What the options market has already priced in.

The forecast dashboard repeatedly has to answer "how much of this is baked in?" and
until now answered it with estimate revisions and analyst ratings - both slow, both
opinion. The options market answers it directly and continuously, for free.

Three readings, all from public chains:

  implied move     the ATM straddle at the first expiry after the next earnings date,
                   as a percentage of spot. This is the market's one-standard-deviation
                   expectation for the event, and it is the single most useful number
                   here: it says what a surprise has to beat to matter.
  skew             25-delta put IV minus 25-delta call IV. Positive means downside
                   protection is bid relative to upside - the market is paying up to
                   hedge rather than to speculate.
  term structure   near-dated IV against a later expiry. Backwardation (near > far) is
                   the signature of a dated event the market is bracing for.

    python sf_options.py NVDA --event 2026-11-17 -f json

Everything comes from Yahoo option chains via yfinance. No key, no subscription. Chains
are thin or stale for some names and the script says so rather than inventing a number.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    print("yfinance is required: pip install yfinance", file=sys.stderr)
    raise


def _mid(row) -> float | None:
    """Mid price, falling back to last when a side of the book is missing."""
    bid, ask, last = row.get("bid"), row.get("ask"), row.get("lastPrice")
    try:
        if bid and ask and bid > 0 and ask > 0:
            return (float(bid) + float(ask)) / 2
    except (TypeError, ValueError):
        pass
    try:
        return float(last) if last and float(last) > 0 else None
    except (TypeError, ValueError):
        return None


def _nearest(frame, spot: float):
    """The row whose strike is closest to spot."""
    if frame is None or frame.empty:
        return None
    frame = frame.copy()
    frame["_d"] = (frame["strike"] - spot).abs()
    return frame.sort_values("_d").iloc[0]


def _atm_straddle(chain, spot: float) -> dict | None:
    call, put = _nearest(chain.calls, spot), _nearest(chain.puts, spot)
    if call is None or put is None:
        return None
    cp, pp = _mid(call), _mid(put)
    if cp is None or pp is None:
        return None
    total = cp + pp
    ivs = [float(x) for x in (call.get("impliedVolatility"), put.get("impliedVolatility"))
           if x and float(x) > 0]
    return {
        "strike": float(call["strike"]),
        "call": round(cp, 2),
        "put": round(pp, 2),
        "straddle": round(total, 2),
        "implied_move_pct": round(total / spot * 100, 2),
        "atm_iv": round(sum(ivs) / len(ivs) * 100, 1) if ivs else None,
        "call_volume": int(call.get("volume") or 0),
        "put_volume": int(put.get("volume") or 0),
        "call_oi": int(call.get("openInterest") or 0),
        "put_oi": int(put.get("openInterest") or 0),
    }


def _delta_iv(frame, spot: float, target: float, is_call: bool) -> float | None:
    """IV at roughly the target delta, approximated by moneyness.

    A true delta needs a pricing model and a rate; for a skew *difference* the
    approximation is adequate and it keeps this script dependency-light. 25-delta is
    approximated at approximately 10% out of the money, which is close enough for
    equities at typical tenors and is stated as an approximation on the page.
    """
    if frame is None or frame.empty:
        return None
    strike = spot * (1.10 if is_call else 0.90)
    frame = frame.copy()
    frame["_d"] = (frame["strike"] - strike).abs()
    row = frame.sort_values("_d").iloc[0]
    iv = row.get("impliedVolatility")
    try:
        return float(iv) * 100 if iv and float(iv) > 0 else None
    except (TypeError, ValueError):
        return None


def analyse(ticker: str, event: str | None = None) -> dict:
    tk = yf.Ticker(ticker)
    try:
        fast = tk.fast_info
        spot = float(fast["last_price"])
    except Exception:
        hist = tk.history(period="5d")
        if hist.empty:
            return {"ticker": ticker, "ok": False, "error": "no price available"}
        spot = float(hist["Close"].iloc[-1])

    try:
        expiries = list(tk.options)
    except Exception as exc:
        return {"ticker": ticker, "ok": False, "error": f"no option chain: {exc}"}
    if not expiries:
        return {"ticker": ticker, "ok": False, "error": "no listed options"}

    today = date.today()
    event_date = None
    if event:
        try:
            event_date = datetime.strptime(event, "%Y-%m-%d").date()
        except ValueError:
            pass

    def dte(e: str) -> int:
        return (datetime.strptime(e, "%Y-%m-%d").date() - today).days

    # the expiry that actually brackets the event, else the front month
    if event_date:
        after = [e for e in expiries if datetime.strptime(e, "%Y-%m-%d").date() >= event_date]
        event_expiry = after[0] if after else expiries[-1]
    else:
        event_expiry = next((e for e in expiries if dte(e) >= 1), expiries[0])

    out = {
        "ticker": ticker,
        "ok": True,
        "spot": round(spot, 2),
        "as_of": today.isoformat(),
        "event_date": event,
        "expiries_available": len(expiries),
        "note": None,
    }

    chain = tk.option_chain(event_expiry)
    front = _atm_straddle(chain, spot)
    if not front:
        return {**out, "ok": False, "error": f"chain at {event_expiry} unusable (no two-sided market)"}
    front["expiry"] = event_expiry
    front["days_to_expiry"] = dte(event_expiry)
    front["covers_event"] = bool(event_date and
                                 datetime.strptime(event_expiry, "%Y-%m-%d").date() >= event_date)
    out["event_straddle"] = front

    # a straddle spans the whole tenor, not just the event; annualise for comparability
    if front["days_to_expiry"] > 0:
        out["implied_annualised_vol_pct"] = round(
            front["implied_move_pct"] * math.sqrt(365 / front["days_to_expiry"]), 1)

    put_iv = _delta_iv(chain.puts, spot, 0.25, is_call=False)
    call_iv = _delta_iv(chain.calls, spot, 0.25, is_call=True)
    if put_iv and call_iv:
        out["skew"] = {
            "put_iv_pct": round(put_iv, 1),
            "call_iv_pct": round(call_iv, 1),
            "skew_pts": round(put_iv - call_iv, 1),
            "reading": ("downside protection bid" if put_iv - call_iv > 2 else
                        "upside bid" if put_iv - call_iv < -2 else "roughly symmetric"),
            "method": "approximated at +/-10% moneyness rather than a solved 25-delta",
        }

    # term structure: the event expiry against something a couple of months further out
    far = next((e for e in expiries if dte(e) >= front["days_to_expiry"] + 45), None)
    if far:
        far_straddle = _atm_straddle(tk.option_chain(far), spot)
        if far_straddle and front.get("atm_iv") and far_straddle.get("atm_iv"):
            spread = front["atm_iv"] - far_straddle["atm_iv"]
            out["term_structure"] = {
                "near_expiry": event_expiry, "near_iv_pct": front["atm_iv"],
                "far_expiry": far, "far_iv_pct": far_straddle["atm_iv"],
                "spread_pts": round(spread, 1),
                "reading": ("backwardation - the market is bracing for a dated event"
                            if spread > 2 else
                            "contango - no near-term event premium" if spread < -2 else
                            "flat"),
            }

    liquidity = front["call_oi"] + front["put_oi"]
    if liquidity < 500:
        out["note"] = (f"thin chain: {liquidity} contracts of open interest at the ATM strike. "
                       "Treat the implied move as indicative only.")
    return out


def to_markdown(d: dict) -> str:
    if not d.get("ok"):
        return f"**{d['ticker']}** — options read unavailable: {d.get('error')}"
    s = d["event_straddle"]
    lines = [f"### {d['ticker']} — what the options market has priced in",
             "",
             f"Spot ${d['spot']:.2f} · chain as of {d['as_of']}",
             "",
             f"- **Implied move ±{s['implied_move_pct']:.1f}%** "
             f"(${s['straddle']:.2f} straddle at the ${s['strike']:.0f} strike, "
             f"{s['expiry']} expiry, {s['days_to_expiry']}d)",
             f"- Range implied: **${d['spot'] * (1 - s['implied_move_pct'] / 100):.2f} – "
             f"${d['spot'] * (1 + s['implied_move_pct'] / 100):.2f}**"]
    if s.get("atm_iv"):
        lines.append(f"- ATM implied volatility {s['atm_iv']:.1f}%")
    if d.get("skew"):
        k = d["skew"]
        lines.append(f"- Skew {k['skew_pts']:+.1f} pts ({k['reading']}) — "
                     f"puts {k['put_iv_pct']:.1f}% vs calls {k['call_iv_pct']:.1f}%")
    if d.get("term_structure"):
        t = d["term_structure"]
        lines.append(f"- Term structure {t['spread_pts']:+.1f} pts ({t['reading']}) — "
                     f"{t['near_expiry']} {t['near_iv_pct']:.1f}% vs "
                     f"{t['far_expiry']} {t['far_iv_pct']:.1f}%")
    if d.get("note"):
        lines += ["", f"_{d['note']}_"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ticker")
    ap.add_argument("--event", help="date the chain should bracket, YYYY-MM-DD")
    ap.add_argument("-f", "--format", choices=("md", "json"), default="md")
    args = ap.parse_args()
    result = analyse(args.ticker.upper(), args.event)
    print(json.dumps(result, indent=2) if args.format == "json" else to_markdown(result))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
