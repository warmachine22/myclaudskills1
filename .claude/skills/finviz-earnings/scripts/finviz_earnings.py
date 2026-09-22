#!/usr/bin/env python3
"""Finviz earnings-tab scraper: history, forecasts, revisions, price reaction.

The earnings tab (https://finviz.com/quote.ashx?t=TICKER&ty=ea) embeds every
number it renders in a single JSON island:

    <script id="route-init-data" type="application/json"> { ... } </script>

so this reads structured JSON rather than parsing rendered HTML. A restyle
cannot silently corrupt a value; a real schema change shows up as a missing
key. One HTTP request per ticker covers all six datasets plus the fundamentals
snapshot table.

Stdlib only. Responses cached 10 minutes in the system temp dir.
"""

from __future__ import annotations

import argparse
import csv
import html as _html
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://finviz.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CACHE_DIR = os.path.join(tempfile.gettempdir(), "finviz-earnings-cache")
CACHE_TTL = 600  # seconds
MIN_INTERVAL = 2.5  # seconds between live requests — be a good citizen
_last_fetch = [0.0]

# Order matters: this is the chronological order of the reaction chain.
# minus_1_week / plus_1_week sit outside the contiguous daily chain.
CHAIN = ["minus_1_day", "open", "close", "plus_1_day", "plus_2_days", "plus_3_days"]
PRE = ["minus_1_week", "minus_3_days", "minus_2_days", "minus_1_day"]


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------

def _cache_path(ticker: str) -> str:
    return os.path.join(CACHE_DIR, f"{ticker.upper().replace('/', '_')}.html")


def fetch_page(ticker: str, refresh: bool = False, retries: int = 3) -> str:
    """Return the earnings-tab HTML, from cache when fresh."""
    path = _cache_path(ticker)
    if not refresh and os.path.exists(path):
        if time.time() - os.path.getmtime(path) < CACHE_TTL:
            with open(path, encoding="utf-8") as fh:
                return fh.read()

    url = f"{BASE}/quote.ashx?t={urllib.parse.quote(ticker)}&p=d&ty=ea"
    last = None
    for attempt in range(retries):
        wait = MIN_INTERVAL - (time.time() - _last_fetch[0])
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                page = resp.read().decode("utf-8", errors="replace")
            _last_fetch[0] = time.time()
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(page)
            return page
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            last = exc
            _last_fetch[0] = time.time()
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


RE_ISLAND = re.compile(
    r'<script id="route-init-data" type="application/json">(.*?)</script>', re.S
)


def parse_island(page: str) -> dict:
    m = RE_ISLAND.search(page)
    if not m:
        raise RuntimeError(
            "route-init-data island not found — page structure changed "
            "(see Maintenance in SKILL.md)"
        )
    return json.loads(m.group(1))


# --------------------------------------------------------------------------
# Fundamentals snapshot table
# --------------------------------------------------------------------------

# Capture the label cell's full attribute string, then pull the tooltip out of
# it separately — an inline optional group matches empty and loses the tooltip,
# because data-boxover-html is not always in the same attribute position.
RE_PAIR = re.compile(
    r'<td([^>]*snapshot-td2[^>]*)>'
    r'\s*<div class="snapshot-td-label">(.*?)</div>\s*</td>\s*'
    r'<td[^>]*snapshot-td2[^>]*>\s*<div class="snapshot-td-content">(.*?)</div>',
    re.S,
)
RE_TIP = re.compile(r'data-boxover-html="([^"]*)"')
RE_TAG = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    text = RE_TAG.sub(" ", text or "")
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_snapshot(page: str) -> dict:
    """The ~84-metric fundamentals table (P/E, Forward P/E, PEG, margins, ...).

    Values are kept as displayed strings; `num` carries a float only when the
    cell holds a single unambiguous number. Cells like '236.54 -6.18%' or
    '25.99% 14.87%' hold two figures and are left as text on purpose.
    """
    out: dict[str, dict] = {}
    for attrs, label, value in RE_PAIR.findall(page):
        label = _clean(label)
        raw = _clean(value)
        if not label:
            continue
        entry = {"value": raw, "num": _to_num(raw)}
        m = RE_TIP.search(attrs)
        tip = _clean(m.group(1)) if m else ""
        if tip:
            entry["description"] = tip
        # finviz reuses one label for two different metrics: 'EPS next Y' is
        # both the dollar estimate and the growth rate. Keying naively drops
        # one of them silently — suffix instead, and keep the tooltip so the
        # caller can tell which is which.
        key = label
        n = 2
        while key in out:
            key = f"{label} ({n})"
            n += 1
        out[key] = entry
    return out


def _to_num(raw: str):
    """Parse a single finviz cell into a float, or None if it isn't one number."""
    if raw is None:
        return None
    s = raw.strip().replace(",", "")
    if s in ("", "-", "—"):
        return None
    if len(s.split()) > 1:  # two figures in one cell
        return None
    mult = 1.0
    pct = s.endswith("%")
    if pct:
        s = s[:-1]
    if s and s[-1] in "KMBT":
        mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[s[-1]]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

def _period_sort_key(p: dict):
    return p.get("fiscalEndDate") or ""


def _pct(new, old):
    if new is None or old in (None, 0):
        return None
    return (new / old - 1.0) * 100.0


def _surprise(actual, estimate):
    if actual is None or estimate in (None, 0):
        return None, None
    return actual - estimate, (actual - estimate) / abs(estimate) * 100.0


def normalise_periods(rows: list[dict]) -> list[dict]:
    """Sort oldest→newest and attach surprise figures.

    finviz emits history descending then appends forward periods ascending, so
    the raw array is not in any single order — always sort by fiscalEndDate.
    """
    out = []
    for r in sorted(rows, key=_period_sort_key):
        eps_d, eps_p = _surprise(r.get("epsActual"), r.get("epsEstimate"))
        gaap_d, gaap_p = _surprise(r.get("epsReportedActual"), r.get("epsReportedEstimate"))
        rev_d, rev_p = _surprise(r.get("salesActual"), r.get("salesEstimate"))
        item = {
            "fiscal_period": r.get("fiscalPeriod"),
            "fiscal_end_date": (r.get("fiscalEndDate") or "")[:10] or None,
            "earnings_date": (r.get("earningsDate") or "")[:10] or None,
            "reported": r.get("epsActual") is not None,
            "eps_estimate": r.get("epsEstimate"),
            "eps_actual": r.get("epsActual"),
            "eps_surprise": eps_d,
            "eps_surprise_pct": eps_p,
            "eps_analysts": r.get("epsAnalysts"),
            "gaap_eps_estimate": r.get("epsReportedEstimate"),
            "gaap_eps_actual": r.get("epsReportedActual"),
            "gaap_eps_surprise": gaap_d,
            "gaap_eps_surprise_pct": gaap_p,
            "gaap_eps_analysts": r.get("epsReportedAnalysts"),
            "revenue_estimate": r.get("salesEstimate"),
            "revenue_actual": r.get("salesActual"),
            "revenue_surprise": rev_d,
            "revenue_surprise_pct": rev_p,
            "revenue_analysts": r.get("salesAnalysts"),
        }
        for k_src, k_dst in (("peRatio", "pe_ratio"), ("peRatioGaap", "pe_ratio_gaap"),
                             ("psRatio", "ps_ratio")):
            if k_src in r:
                item[k_dst] = r[k_src]
        out.append(item)
    return out


def normalise_reactions(rows: list[dict]) -> list[dict]:
    """One record per earnings event, with returns computed from raw prices.

    The baseline is `minus_1_day` — the last close BEFORE the market could
    react. finviz's own footnote: daily change is measured on the report date
    for BMO releases and the following day for AMC releases, so `open`/`close`
    always refer to the first session that could trade on the news.

    Percentages are recomputed here from prices rather than chained from
    finviz's per-point `priceDiff`, because the two week-offset points are
    measured against their own prior day and would corrupt a compounded chain.
    """
    out = []
    for r in sorted(rows, key=lambda x: x.get("reportDate") or "", reverse=True):
        rx = r.get("reactions") or {}

        def px(key):
            node = rx.get(key) or {}
            return node.get("price")

        def dt(key):
            node = rx.get(key) or {}
            return node.get("date")

        base = px("minus_1_day")
        report_day = (r.get("reportDate") or "")[:10]
        react_day = dt("close")
        # AMC releases react the following session; BMO react same day.
        session = None
        if report_day and react_day:
            session = "AMC" if react_day > report_day else "BMO"

        item = {
            "report_date": report_day,
            "report_time": (r.get("reportDate") or "")[11:16] or None,
            "session": session,
            "fiscal_period": r.get("fiscalPeriod"),
            "fiscal_end_date": (r.get("fiscalEndDate") or "")[:10] or None,
            "reaction_date": react_day,
            "rsi_14": r.get("rsi"),
            "baseline_close": base,
            "prices": {k: px(k) for k in rx},
            "dates": {k: dt(k) for k in rx},
        }

        # Returns vs the pre-earnings baseline close.
        item["gap_pct"] = _pct(px("open"), base)
        item["day_pct"] = _pct(px("close"), base)
        item["intraday_pct"] = _pct(px("close"), px("open"))
        item["high_pct"] = _pct(px("high"), base)
        item["low_pct"] = _pct(px("low"), base)
        if px("high") is not None and px("low") is not None and base:
            item["range_pct"] = (px("high") - px("low")) / base * 100.0
        else:
            item["range_pct"] = None
        item["d1_pct"] = _pct(px("plus_1_day"), base)
        item["d2_pct"] = _pct(px("plus_2_days"), base)
        item["d3_pct"] = _pct(px("plus_3_days"), base)
        item["w1_pct"] = _pct(px("plus_1_week"), base)

        # Run-in to the print.
        item["pre_3d_pct"] = _pct(base, px("minus_3_days"))
        item["pre_1w_pct"] = _pct(base, px("minus_1_week"))

        # SPY excess. Only the contiguous daily chain can be compounded; the
        # week points are measured off their own prior day, so they are left out.
        spy = {k: (rx.get(k) or {}).get("spyPriceDiff") for k in rx}
        item["spy_day_pct"] = spy.get("close")
        if item["day_pct"] is not None and spy.get("close") is not None:
            item["excess_day_pct"] = item["day_pct"] - spy["close"]
        else:
            item["excess_day_pct"] = None

        cum_spy, ok = 1.0, True
        for key in ("close", "plus_1_day", "plus_2_days", "plus_3_days"):
            v = spy.get(key)
            if v is None:
                ok = False
                break
            cum_spy *= 1.0 + v / 100.0
        if ok and item["d3_pct"] is not None:
            item["spy_d3_pct"] = (cum_spy - 1.0) * 100.0
            item["excess_d3_pct"] = item["d3_pct"] - item["spy_d3_pct"]
        else:
            item["spy_d3_pct"] = None
            item["excess_d3_pct"] = None

        out.append(item)
    return out


def normalise_revisions(rows: list[dict]) -> list[dict]:
    types = {"E": "eps", "R": "gaap_eps", "S": "revenue"}
    out = []
    for r in rows:
        out.append({
            "fiscal_period": r.get("fiscalPeriod"),
            "metric": types.get(r.get("estimateType"), r.get("estimateType")),
            "date": (r.get("estimateDate") or "")[:10] or None,
            "relative_fiscal_period": r.get("relativeFiscalPeriod"),
            "analysts": r.get("estimates"),
            "up_revisions": r.get("upRevisions"),
            "down_revisions": r.get("downRevisions"),
            "mean": r.get("mean"),
            "high": r.get("high"),
            "low": r.get("low"),
            "price": r.get("price"),
        })
    out.sort(key=lambda x: (x["metric"] or "", x["fiscal_period"] or "", x["date"] or ""))
    return out


# --------------------------------------------------------------------------
# Derived statistics
# --------------------------------------------------------------------------

def _stats(values: list[float]) -> dict | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    up = sum(1 for v in vals if v > 0)
    return {
        "n": n,
        "hit_rate_pct": up / n * 100.0,
        "up": up,
        "down": n - up,
        "mean": sum(vals) / n,
        "median": median,
        "best": s[-1],
        "worst": s[0],
        "avg_abs": sum(abs(v) for v in vals) / n,
    }


STRATEGIES = [
    ("hold_through_print", "day_pct",
     "Buy at the close before the report, sell at the close of the first session after it"),
    ("overnight_gap_only", "gap_pct",
     "Buy at the close before the report, sell at the next open (captures the gap only)"),
    ("post_gap_drift", "intraday_pct",
     "Buy at the open after the report, sell at that day's close (fade or follow-through)"),
    ("hold_3_days", "d3_pct",
     "Buy at the close before the report, sell 3 sessions later"),
    ("hold_1_week", "w1_pct",
     "Buy at the close before the report, sell one week later"),
    ("run_in_3_days", "pre_3d_pct",
     "Buy 3 sessions before the report, sell at the close before it (no event risk held)"),
    ("run_in_1_week", "pre_1w_pct",
     "Buy one week before the report, sell at the close before it (no event risk held)"),
]


def derive(events: list[dict], periods: list[dict], limit: int | None = None) -> dict:
    """Historical base rates. Descriptive statistics on a small sample — not a
    forecast, and every consumer of this output must say so."""
    ev = events[:limit] if limit else events

    strategies = {}
    for key, field, desc in STRATEGIES:
        st = _stats([e.get(field) for e in ev])
        if st:
            st["description"] = desc
            strategies[key] = st

    reported = [p for p in periods if p["reported"]]
    beats = {}
    for label, field in (("eps", "eps_surprise"), ("gaap_eps", "gaap_eps_surprise"),
                         ("revenue", "revenue_surprise")):
        recent = [p for p in reported if p.get(field) is not None]
        recent = recent[-len(ev):] if ev else recent
        if not recent:
            continue
        n = len(recent)
        beat = sum(1 for p in recent if p[field] > 0)
        pcts = [p[f"{field}_pct"] for p in recent if p.get(f"{field}_pct") is not None]
        beats[label] = {
            "n": n,
            "beats": beat,
            "misses": n - beat,
            "beat_rate_pct": beat / n * 100.0,
            "avg_surprise_pct": (sum(pcts) / len(pcts)) if pcts else None,
        }

    # Did beating actually pay? Joins the fundamental result to the tape.
    by_period = {p["fiscal_period"]: p for p in periods}
    joined = []
    for e in ev:
        p = by_period.get(e["fiscal_period"])
        if not p or e.get("day_pct") is None or p.get("eps_surprise") is None:
            continue
        joined.append((p["eps_surprise"] > 0, e["day_pct"]))
    beat_payoff = None
    if joined:
        beat_up = [d for b, d in joined if b and d > 0]
        beat_all = [d for b, d in joined if b]
        miss_all = [d for b, d in joined if not b]
        beat_payoff = {
            "n": len(joined),
            "beat_and_rose": len(beat_up),
            "beat_and_fell": len(beat_all) - len(beat_up),
            "beat_then_rose_pct": (len(beat_up) / len(beat_all) * 100.0) if beat_all else None,
            "avg_move_on_beat": (sum(beat_all) / len(beat_all)) if beat_all else None,
            "avg_move_on_miss": (sum(miss_all) / len(miss_all)) if miss_all else None,
            "misses_in_sample": len(miss_all),
        }

    return {
        "sample_size": len(ev),
        "window": {
            "oldest": ev[-1]["report_date"] if ev else None,
            "newest": ev[0]["report_date"] if ev else None,
        },
        "strategies": strategies,
        "beat_rates": beats,
        "beat_payoff": beat_payoff,
        "absolute_move": _stats([e.get("day_pct") for e in ev]),
        "excess_vs_spy_day": _stats([e.get("excess_day_pct") for e in ev]),
    }


def derive_valuation(snapshot: dict, periods: list[dict]) -> dict:
    """Implied multiples from the forward estimate strip.

    NTM EPS is the sum of the next four *unreported* quarterly estimates. If
    fewer than four are published the field is null rather than annualised —
    padding a partial year is how a forward multiple starts lying.
    """
    price = (snapshot.get("Price") or {}).get("num")
    quarters = [p for p in periods if p["fiscal_period"] and "Q" in p["fiscal_period"]]
    forward = [p for p in quarters if not p["reported"] and p["eps_estimate"] is not None]
    forward.sort(key=lambda p: p["fiscal_end_date"] or "")

    ntm_eps = None
    ntm_periods = []
    if len(forward) >= 4:
        ntm_eps = sum(p["eps_estimate"] for p in forward[:4])
        ntm_periods = [p["fiscal_period"] for p in forward[:4]]

    ttm_eps = None
    reported_q = [p for p in quarters if p["reported"] and p["eps_actual"] is not None]
    reported_q.sort(key=lambda p: p["fiscal_end_date"] or "")
    if len(reported_q) >= 4:
        ttm_eps = sum(p["eps_actual"] for p in reported_q[-4:])

    out = {
        "price": price,
        "ttm_eps_summed": ttm_eps,
        "ttm_pe_implied": (price / ttm_eps) if price and ttm_eps else None,
        "ntm_eps_estimate": ntm_eps,
        "ntm_periods": ntm_periods,
        "ntm_pe_implied": (price / ntm_eps) if price and ntm_eps else None,
        "implied_growth_ntm_pct": ((ntm_eps / ttm_eps - 1) * 100.0)
                                  if ntm_eps and ttm_eps else None,
        "reported_multiples": {
            k: (snapshot.get(k) or {}).get("value")
            for k in ("P/E", "Forward P/E", "PEG", "P/S", "P/B", "P/FCF",
                      "EV/EBITDA", "EV/Sales", "Target Price", "Recom")
            if k in snapshot
        },
        "growth_expectations": {
            k: (snapshot.get(k) or {}).get("value")
            for k in ("EPS next Y", "EPS next Q", "EPS this Y", "EPS next 5Y",
                      "Sales past 3/5Y", "EPS past 3/5Y")
            if k in snapshot
        },
    }

    # Forward-year multiples straight off the estimate strip.
    annual = [p for p in periods if p["fiscal_period"] and p["fiscal_period"].endswith("FY")]
    fy = []
    for p in sorted(annual, key=lambda x: x["fiscal_end_date"] or ""):
        if p["reported"] or p["eps_estimate"] is None:
            continue
        n = p["eps_analysts"] or 0
        fy.append({
            "fiscal_period": p["fiscal_period"],
            "eps_estimate": p["eps_estimate"],
            "implied_pe": (price / p["eps_estimate"]) if price and p["eps_estimate"] else None,
            "analysts": p["eps_analysts"],
            # Out-year consensus often rests on a handful of submissions. Flag it
            # rather than dropping it — but never quote a thin year unqualified.
            "thin_coverage": n < 5,
        })
    out["forward_years"] = fy
    return out


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def load(ticker: str, refresh: bool = False) -> dict:
    page = fetch_page(ticker, refresh=refresh)
    island = parse_island(page)
    snapshot = parse_snapshot(page)

    quarterly = normalise_periods(island.get("earningsData") or [])
    annual = normalise_periods(island.get("earningsAnnualData") or [])
    events = normalise_reactions(island.get("priceReactionData") or [])
    revisions = normalise_revisions(island.get("earningsRevisionsData") or [])

    _flag_stale_annual_multiples(annual, snapshot)

    next_date = island.get("earningsDate")
    next_period = next((p for p in quarterly if not p["reported"]), None)

    return {
        "ticker": ticker.upper(),
        "company": snapshot.get("_company", {}).get("value"),
        "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "source": f"{BASE}/quote.ashx?t={ticker.upper()}&ty=ea",
        "next_report": {
            "datetime": next_date,
            "date": (next_date or "")[:10] or None,
            "session": _session_from_time(next_date),
            "fiscal_period": next_period["fiscal_period"] if next_period else None,
            "eps_estimate": next_period["eps_estimate"] if next_period else None,
            "gaap_eps_estimate": next_period["gaap_eps_estimate"] if next_period else None,
            "revenue_estimate": next_period["revenue_estimate"] if next_period else None,
            "analysts": next_period["eps_analysts"] if next_period else None,
        },
        "quarterly": quarterly,
        "annual": annual,
        "price_reactions": events,
        "revisions": revisions,
        "snapshot": snapshot,
    }


def _flag_stale_annual_multiples(annual: list[dict], snapshot: dict) -> None:
    """Neutralise finviz's back-filled annual P/E and P/S.

    For fiscal years beyond roughly the last ten, finviz computes the annual
    multiple as **today's price** over that year's EPS instead of the price as
    it was then. NVDA's 2015FY comes back as 8,140x; AAPL's 2010FY as 577x.
    Charting those as history draws a valuation cliff that never happened.

    Detection is exact rather than a year cutoff: if `pe_ratio × eps_actual`
    reproduces the current price, the row was back-filled. The value is moved
    to `pe_ratio_stale` and the live field nulled, so a consumer that plots
    `pe_ratio` silently gets a gap instead of a fabricated spike.

    Forward years legitimately use today's price over forward EPS, so rows with
    no actual are left alone.
    """
    price = (snapshot.get("Price") or {}).get("num")
    if not price:
        return
    for row in annual:
        for field, actual in (("pe_ratio", row.get("eps_actual")),
                              ("ps_ratio", None)):
            val = row.get(field)
            if val is None or actual in (None, 0):
                continue
            if abs(val * actual - price) / price < 0.02:
                row[f"{field}_stale"] = val
                row[field] = None
                row["multiple_backfilled"] = True


def _session_from_time(iso: str | None) -> str | None:
    """AMC/BMO from the release timestamp; 16:00+ ET is after the close."""
    if not iso or len(iso) < 16:
        return None
    try:
        hh = int(iso[11:13])
    except ValueError:
        return None
    return "AMC" if hh >= 16 else "BMO"


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def _f(v, dp=2, suffix="", dash="—"):
    if v is None:
        return dash
    return f"{v:,.{dp}f}{suffix}"


def _sf(v, dp=2, suffix="%"):
    if v is None:
        return "—"
    return f"{v:+,.{dp}f}{suffix}"


def _money(v):
    if v is None:
        return "—"
    a = abs(v)
    for cut, sfx in ((1e6, "T"), (1e3, "B"), (1, "M")):
        if a >= cut:
            return f"{v / cut:,.2f}{sfx}"
    return f"{v:,.2f}M"


def render_reaction(data: dict, limit: int) -> str:
    ev = data["price_reactions"][:limit]
    o = [f"# {data['ticker']} — price reaction to earnings", ""]
    nr = data["next_report"]
    if nr["date"]:
        o.append(f"**Next report:** {nr['date']} {nr['session'] or ''} · "
                 f"{nr['fiscal_period'] or ''} · EPS est {_f(nr['eps_estimate'])} · "
                 f"Rev est {_money(nr['revenue_estimate'])}")
        o.append("")
    o.append("Baseline for every percentage is the **close before the market could "
             "react** (the report date for BMO releases, the prior close for AMC).")
    o.append("")
    o.append("| Report | Period | Sess | Run-in 3d | Gap | **Day** | vs SPY | +1d | +3d | +1w | Range | RSI |")
    o.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for e in ev:
        o.append(
            f"| {e['report_date']} | {e['fiscal_period']} | {e['session'] or '—'} "
            f"| {_sf(e['pre_3d_pct'])} | {_sf(e['gap_pct'])} | **{_sf(e['day_pct'])}** "
            f"| {_sf(e['excess_day_pct'])} | {_sf(e['d1_pct'])} | {_sf(e['d3_pct'])} "
            f"| {_sf(e['w1_pct'])} | {_f(e['range_pct'], 2, '%')} | {_f(e['rsi_14'], 0)} |"
        )
    o.append("")

    d = derive(data["price_reactions"], data["quarterly"], limit=limit)
    o.append(f"## Base rates — last {d['sample_size']} reports "
             f"({d['window']['oldest']} → {d['window']['newest']})")
    o.append("")
    o.append("| Strategy | Hit rate | Mean | Median | Best | Worst |")
    o.append("|---|---|---|---|---|---|")
    for key, _field, _desc in STRATEGIES:
        st = d["strategies"].get(key)
        if not st:
            continue
        o.append(f"| {key.replace('_', ' ')} | {st['up']}/{st['n']} "
                 f"({st['hit_rate_pct']:.0f}%) | {_sf(st['mean'])} | {_sf(st['median'])} "
                 f"| {_sf(st['best'])} | {_sf(st['worst'])} |")
    o.append("")
    am = d["absolute_move"]
    if am:
        o.append(f"**Average absolute move on the day:** {am['avg_abs']:.2f}% "
                 f"· biggest {am['best']:+.2f}% · worst {am['worst']:+.2f}%")
    bp = d.get("beat_payoff")
    if bp and bp.get("beat_then_rose_pct") is not None:
        o.append(f"**Beat ≠ rally:** beat EPS {bp['beat_and_rose'] + bp['beat_and_fell']} "
                 f"times in this window; the stock rose on {bp['beat_and_rose']} of them "
                 f"({bp['beat_then_rose_pct']:.0f}%). Average move on a beat "
                 f"{bp['avg_move_on_beat']:+.2f}%.")
    o.append("")
    o.append("_Descriptive statistics on a small sample of past events. Base rates are "
             "not probabilities of future outcomes._")
    return "\n".join(o)


def render_estimates(data: dict, limit: int, annual: bool = False) -> str:
    rows = data["annual"] if annual else data["quarterly"]
    reported = [r for r in rows if r["reported"]]
    forward = [r for r in rows if not r["reported"]]
    shown = reported[-limit:] + forward

    o = [f"# {data['ticker']} — {'annual' if annual else 'quarterly'} EPS & revenue", ""]
    o.append("| Period | End | EPS est | EPS act | Surprise | GAAP act | Rev est | Rev act | Surprise | Analysts |")
    o.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in shown:
        o.append(
            f"| {r['fiscal_period']} | {r['fiscal_end_date'] or '—'} "
            f"| {_f(r['eps_estimate'])} | {_f(r['eps_actual'])} "
            f"| {_sf(r['eps_surprise_pct'])} | {_f(r['gaap_eps_actual'])} "
            f"| {_money(r['revenue_estimate'])} | {_money(r['revenue_actual'])} "
            f"| {_sf(r['revenue_surprise_pct'])} | {r['eps_analysts'] or '—'} |"
        )
    o.append("")
    o.append(f"{len(reported)} reported periods · {len(forward)} forward estimates. "
             "Rows with no actual have not been reported — their figures are consensus.")
    return "\n".join(o)


def render_valuation(data: dict) -> str:
    v = derive_valuation(data["snapshot"], data["quarterly"] + data["annual"])
    o = [f"# {data['ticker']} — valuation", ""]
    o.append(f"**Price:** {_f(v['price'])}")
    o.append("")
    o.append("## Implied from the estimate strip")
    o.append("")
    o.append("| Measure | Value |")
    o.append("|---|---|")
    o.append(f"| TTM EPS (sum of last 4 reported quarters) | {_f(v['ttm_eps_summed'])} |")
    o.append(f"| Implied trailing P/E | {_f(v['ttm_pe_implied'], 1)} |")
    o.append(f"| NTM EPS (sum of next 4 estimates) | {_f(v['ntm_eps_estimate'])} |")
    o.append(f"| Implied forward P/E (NTM) | {_f(v['ntm_pe_implied'], 1)} |")
    o.append(f"| Implied EPS growth, TTM → NTM | {_sf(v['implied_growth_ntm_pct'], 1)} |")
    if v["ntm_periods"]:
        o.append(f"| NTM window | {', '.join(v['ntm_periods'])} |")
    o.append("")
    if v["forward_years"]:
        o.append("## Forward fiscal years")
        o.append("")
        o.append("| Period | EPS est | Implied P/E | Analysts |")
        o.append("|---|---|---|---|")
        for f in v["forward_years"]:
            flag = " ⚠ thin" if f["thin_coverage"] else ""
            o.append(f"| {f['fiscal_period']} | {_f(f['eps_estimate'])} "
                     f"| {_f(f['implied_pe'], 1)} | {f['analysts'] or '—'}{flag} |")
        o.append("")
        if any(f["thin_coverage"] for f in v["forward_years"]):
            o.append("⚠ = fewer than 5 analysts. Out-year consensus can rest on one or "
                     "two submissions and is not comparable to a well-covered year. "
                     "Do not quote these without saying how many analysts stand behind them.")
            o.append("")
    o.append("## As finviz reports them")
    o.append("")
    o.append("| Metric | Value |")
    o.append("|---|---|")
    for k, val in v["reported_multiples"].items():
        o.append(f"| {k} | {val} |")
    for k, val in v["growth_expectations"].items():
        o.append(f"| {k} | {val} |")
    o.append("")
    o.append("_Forward multiples are built on analyst consensus, which is an "
             "expectation and is revised often. `Forward P/E` from finviz uses the "
             "next fiscal year; the NTM figure above uses the next four quarters — "
             "they will not match, and neither is wrong._")
    return "\n".join(o)


def render_revisions(data: dict, limit: int) -> str:
    o = [f"# {data['ticker']} — estimate revisions", ""]
    by = {}
    for r in data["revisions"]:
        by.setdefault((r["metric"], r["fiscal_period"]), []).append(r)
    rows = []
    for (metric, period), items in by.items():
        items.sort(key=lambda x: x["date"] or "")
        last = items[-1]
        first = items[0]
        drift = None
        if first["mean"] not in (None, 0) and last["mean"] is not None:
            drift = (last["mean"] / first["mean"] - 1) * 100.0
        rows.append({"metric": metric, "period": period, "last": last,
                     "first": first, "drift": drift, "n": len(items)})
    # Newest revision first regardless of metric, so a fresh EPS cut surfaces
    # next to a fresh revenue cut instead of being buried under one metric.
    rows.sort(key=lambda r: (r["last"]["date"] or "", r["metric"]), reverse=True)

    o.append("| Metric | Period | Latest | Mean est | Low | High | Up | Down | Since first est |")
    o.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows[:limit]:
        l = r["last"]
        o.append(f"| {r['metric']} | {r['period']} | {l['date']} | {_f(l['mean'])} "
                 f"| {_f(l['low'])} | {_f(l['high'])} | {l['up_revisions'] or 0} "
                 f"| {l['down_revisions'] or 0} | {_sf(r['drift'], 1)} |")
    o.append("")
    o.append(f"{len(data['revisions'])} revision snapshots on file. `Up`/`Down` count "
             "analysts who moved their number at the latest snapshot; the last column "
             "is drift in the consensus mean since the first snapshot for that period.")
    return "\n".join(o)


def render_summary(data: dict, limit: int) -> str:
    nr = data["next_report"]
    d = derive(data["price_reactions"], data["quarterly"], limit=limit)
    v = derive_valuation(data["snapshot"], data["quarterly"] + data["annual"])
    snap = data["snapshot"]

    o = [f"# {data['ticker']} — earnings briefing", ""]
    if nr["date"]:
        o.append(f"**Next report:** {nr['date']} {nr['session'] or ''} · "
                 f"{nr['fiscal_period'] or ''}")
        o.append(f"**Consensus:** EPS {_f(nr['eps_estimate'])} · "
                 f"GAAP EPS {_f(nr['gaap_eps_estimate'])} · "
                 f"Revenue {_money(nr['revenue_estimate'])} "
                 f"({nr['analysts'] or '—'} analysts)")
        o.append("")

    o.append("## Track record")
    o.append("")
    for label, key in (("EPS", "eps"), ("GAAP EPS", "gaap_eps"), ("Revenue", "revenue")):
        b = d["beat_rates"].get(key)
        if b:
            o.append(f"- **{label}:** beat {b['beats']}/{b['n']} "
                     f"({b['beat_rate_pct']:.0f}%) · avg surprise "
                     f"{_sf(b['avg_surprise_pct'])}")
    o.append("")

    o.append("## What the stock did")
    o.append("")
    am = d["absolute_move"]
    if am:
        o.append(f"- Average absolute move on the reaction day: **{am['avg_abs']:.2f}%** "
                 f"(up {am['up']}/{am['n']})")
        o.append(f"- Best {am['best']:+.2f}% · worst {am['worst']:+.2f}% · "
                 f"median {am['median']:+.2f}%")
    ex = d["excess_vs_spy_day"]
    if ex:
        o.append(f"- Versus SPY the same day: mean {ex['mean']:+.2f}%, "
                 f"beat the index {ex['up']}/{ex['n']} times")
    bp = d.get("beat_payoff")
    if bp and bp.get("beat_then_rose_pct") is not None:
        o.append(f"- Beat EPS and still fell: "
                 f"**{bp['beat_and_fell']} of {bp['beat_and_rose'] + bp['beat_and_fell']}** times")
    o.append("")

    o.append("## Base rates by holding window")
    o.append("")
    o.append("| Strategy | Hit rate | Mean | Median |")
    o.append("|---|---|---|---|")
    for key, _f2, _desc in STRATEGIES:
        st = d["strategies"].get(key)
        if st:
            o.append(f"| {key.replace('_', ' ')} | {st['up']}/{st['n']} "
                     f"({st['hit_rate_pct']:.0f}%) | {_sf(st['mean'])} | {_sf(st['median'])} |")
    o.append("")

    o.append("## Valuation")
    o.append("")
    o.append(f"- Price {_f(v['price'])} · trailing P/E "
             f"{(snap.get('P/E') or {}).get('value', '—')} · forward P/E "
             f"{(snap.get('Forward P/E') or {}).get('value', '—')} · PEG "
             f"{(snap.get('PEG') or {}).get('value', '—')}")
    if v["ntm_pe_implied"]:
        o.append(f"- Implied P/E on the next four quarters of consensus: "
                 f"**{v['ntm_pe_implied']:.1f}×** "
                 f"(NTM EPS {_f(v['ntm_eps_estimate'])})")
    if v["implied_growth_ntm_pct"] is not None:
        o.append(f"- Consensus implies EPS growth of "
                 f"{v['implied_growth_ntm_pct']:+.1f}% over the next twelve months")
    for f in v["forward_years"][:3]:
        o.append(f"- {f['fiscal_period']}: EPS {_f(f['eps_estimate'])} → "
                 f"{_f(f['implied_pe'], 1)}× at today's price")
    o.append("")
    o.append(f"_Source: {data['source']} · fetched {data['fetched_at'][:19]}. "
             "Historical base rates describe a small sample of past events and are "
             "not predictions. Consensus figures are expectations, not results._")
    return "\n".join(o)


def render_csv(data: dict, section: str, limit: int) -> str:
    buf = io.StringIO()
    if section == "reaction":
        rows = data["price_reactions"][:limit]
        cols = ["report_date", "fiscal_period", "session", "reaction_date", "rsi_14",
                "baseline_close", "pre_1w_pct", "pre_3d_pct", "gap_pct", "day_pct",
                "intraday_pct", "high_pct", "low_pct", "range_pct", "d1_pct",
                "d2_pct", "d3_pct", "w1_pct", "spy_day_pct", "excess_day_pct",
                "spy_d3_pct", "excess_d3_pct"]
    elif section in ("estimates", "annual"):
        rows = data["annual"] if section == "annual" else data["quarterly"]
        cols = ["fiscal_period", "fiscal_end_date", "earnings_date", "reported",
                "eps_estimate", "eps_actual", "eps_surprise", "eps_surprise_pct",
                "eps_analysts", "gaap_eps_estimate", "gaap_eps_actual",
                "gaap_eps_surprise_pct", "revenue_estimate", "revenue_actual",
                "revenue_surprise_pct", "revenue_analysts"]
    elif section == "revisions":
        rows = data["revisions"]
        cols = ["metric", "fiscal_period", "date", "relative_fiscal_period",
                "analysts", "up_revisions", "down_revisions", "mean", "high",
                "low", "price"]
    else:
        rows, cols = [], []
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Finviz earnings data: history, forecasts, revisions, price reaction.")
    p.add_argument("command",
                   choices=["summary", "reaction", "estimates", "annual",
                            "revisions", "valuation", "raw"],
                   help="which view to produce")
    p.add_argument("ticker", help="ticker symbol, e.g. NVDA")
    p.add_argument("-n", "--limit", type=int, default=12,
                   help="rows / events to include (default 12)")
    p.add_argument("-f", "--format", choices=["md", "json", "csv"], default="md")
    p.add_argument("-o", "--out", help="write to this path instead of stdout")
    p.add_argument("--refresh", action="store_true",
                   help="bypass the 10-minute cache")
    args = p.parse_args(argv)

    # Windows consoles default to cp1252 and choke on the em-dash / arrow used
    # in the tables. Force UTF-8 on stdout rather than degrading the output.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    try:
        data = load(args.ticker, refresh=args.refresh)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not data["quarterly"] and not data["price_reactions"]:
        print(f"error: no earnings data for {args.ticker.upper()} — check the ticker",
              file=sys.stderr)
        return 1

    if args.format == "json":
        if args.command == "raw":
            payload = data
        elif args.command == "reaction":
            payload = {"ticker": data["ticker"], "source": data["source"],
                       "fetched_at": data["fetched_at"],
                       "next_report": data["next_report"],
                       "price_reactions": data["price_reactions"][:args.limit],
                       "derived": derive(data["price_reactions"], data["quarterly"],
                                         limit=args.limit)}
        elif args.command == "valuation":
            payload = {"ticker": data["ticker"], "source": data["source"],
                       "valuation": derive_valuation(
                           data["snapshot"], data["quarterly"] + data["annual"]),
                       "snapshot": data["snapshot"]}
        elif args.command == "annual":
            payload = {"ticker": data["ticker"], "annual": data["annual"]}
        elif args.command == "estimates":
            payload = {"ticker": data["ticker"], "quarterly": data["quarterly"]}
        elif args.command == "revisions":
            payload = {"ticker": data["ticker"], "revisions": data["revisions"]}
        else:
            payload = {"ticker": data["ticker"], "source": data["source"],
                       "next_report": data["next_report"],
                       "derived": derive(data["price_reactions"], data["quarterly"],
                                         limit=args.limit),
                       "valuation": derive_valuation(
                           data["snapshot"], data["quarterly"] + data["annual"])}
        text = json.dumps(payload, indent=2, ensure_ascii=False)
    elif args.format == "csv":
        text = render_csv(data, args.command, args.limit)
    else:
        if args.command == "reaction":
            text = render_reaction(data, args.limit)
        elif args.command == "estimates":
            text = render_estimates(data, args.limit)
        elif args.command == "annual":
            text = render_estimates(data, args.limit, annual=True)
        elif args.command == "valuation":
            text = render_valuation(data)
        elif args.command == "revisions":
            text = render_revisions(data, args.limit)
        elif args.command == "raw":
            text = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            text = render_summary(data, args.limit)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
            if not text.endswith("\n"):
                fh.write("\n")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
