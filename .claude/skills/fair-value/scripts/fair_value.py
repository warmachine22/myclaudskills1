#!/usr/bin/env python3
"""Normal-multiple fair value — what a stock is worth at its own historical multiple.

    python fair_value.py NVDA

Reads everything through the finviz-earnings and yahoo-finance skills; makes no
requests of its own.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fv_data as data  # noqa: E402
import fv_model as model  # noqa: E402

WINDOWS = [5, 10, 15]
TOLERANCE = 0.015  # basis reconciliation


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def build_report(args):
    ticker = args.ticker.upper()
    refresh = bool(args.refresh)
    basis = args.basis

    raw = data.finviz_raw(ticker, refresh)
    bars = data.weekly_closes(ticker, refresh)
    snapshot = raw["snapshot"]

    price = data.snapshot_num(snapshot, "Price") or bars[-1][1]
    quarterly = raw["quarterly"]

    points, dropped = model.ttm_points(quarterly, basis, args.lag)
    if not points:
        raise data.FVDataError(
            "finviz", f"no complete four-quarter {model.BASIS_LABEL[basis]} EPS "
                      f"history for '{ticker}'")
    observations = model.join_weekly(bars, points)
    if not observations:
        raise data.FVDataError(
            "yahoo", f"price history for '{ticker}' does not overlap its earnings history")

    forward = model.forward_years(raw["annual"], basis, limit=3)

    # ---- basis reconciliation -------------------------------------------
    checks = _basis_checks(quarterly, snapshot, points, price, basis)

    # ---- pick the metric -------------------------------------------------
    probe_window = model.window_slice(observations, args.window)
    probe_flags = model.guardrails(probe_window, model.regime_check(probe_window),
                                   forward, basis, "pe", dropped)
    metric, switch_reason = model.choose_metric(probe_window, probe_flags, args.metric)

    shares = None
    ps_note = None
    if metric == "ps":
        try:
            shares = data.sa_share_counts(ticker, refresh)
        except data.FVDataError as exc:
            raise data.FVDataError(
                "sa", f"the P/S fallback needs the stockanalysis skill ({exc}). "
                      f"Try --metric pe --window 5 to see the P/E view anyway.")
        observations = model.join_weekly(bars, points, shares)
        # Share history is ~20 quarters on the free tier. Truncate there rather
        # than carrying the oldest known count backwards — an extrapolated share
        # count would silently fabricate multiples for years it cannot cover.
        first_known = dt.date.fromisoformat(shares[0][0])
        observations = [o for o in observations if o.date >= first_known]
        if not [o for o in observations if o.multiple is not None]:
            raise data.FVDataError("sa", f"could not build a P/S series for '{ticker}'")
        current_shares = (data.snapshot_num(snapshot, "Shs Outstand") or shares[-1][1])
        forward = model.forward_years(raw["annual"], basis, 3, "ps", current_shares)
        ps_note = _ps_reconcile(observations, snapshot, shares)

    # ---- windows, and the regime-aware headline choice --------------------
    current_eps = observations[-1].eps
    current_multiple = None
    if metric == "pe":
        current_multiple = price / current_eps if current_eps and current_eps > 0 else None
    else:
        last = observations[-1]
        if last.multiple:
            current_multiple = last.multiple * (price / last.price)

    windows, headline_years = _windows(observations, args, current_multiple)
    headline = windows[headline_years]
    window_obs = model.window_slice(observations, headline_years)
    window_obs, clamped = model.winsorize(window_obs)
    stats = model.describe(window_obs, tuple(args.bands), current_multiple)
    regime = model.regime_check(window_obs)

    flags = model.guardrails(window_obs, regime, forward, basis, metric,
                             dropped, clamped, switch_reason=switch_reason)
    if str(headline_years) != str(args.window) and args.window != "max":
        flags.insert(0, {
            "code": "WINDOW_FALLBACK", "severity": "warn",
            "detail": f"the requested {args.window}y window was not usable (its halves "
                      f"describe different eras, or the history is shorter than that), "
                      f"so the headline uses {headline_years}y instead"})
    refused = model.worst_severity(flags) == "refuse" and args.multiple is None

    # ---- growth adjustment ------------------------------------------------
    growth = model.growth_adjust(observations, forward, args.growth_haircut)
    normal_raw = args.multiple if args.multiple else stats["median"]
    factor = 1.0 if args.multiple else growth["factor"]
    normal_adj = normal_raw * factor

    grid = model.scenario_grid(
        {"p_low": (args.multiple or stats["p_low"]),
         "median": normal_raw,
         "p_high": (args.multiple or stats["p_high"])},
        factor, forward)

    headline_row = next((r for r in forward if (r.get("analysts") or 0) >= 5), None)
    fv = model.fair_value(normal_adj, headline_row["eps"]) if headline_row else None
    band = None
    if headline_row:
        band = (model.fair_value(grid["multiples"]["bear"], headline_row["eps"]),
                model.fair_value(grid["multiples"]["bull"], headline_row["eps"]))

    dividend = (data.snapshot_pct(snapshot, "Dividend Est.")
                or data.snapshot_pct(snapshot, "Dividend TTM"))
    today = dt.date.today()
    returns = []
    for row in forward[:2]:
        value = model.fair_value(normal_adj, row["eps"])
        years = (dt.date.fromisoformat(row["end"]) - today).days / 365.25 if row["end"] else None
        implied = model.implied_return(price, value, years, dividend)
        if implied:
            implied["period"] = row["period"]
            implied["thin"] = (row.get("analysts") or 0) < 5
            returns.append(implied)

    table = model.year_table(window_obs, normal_adj, today)
    above = model.share_above(window_obs, normal_adj)
    bt = None
    if not args.no_backtest:
        bt = model.backtest(window_obs, 52 if args.horizon != "3y" else 156)

    stale = abs(price / bars[-1][1] - 1.0) > 0.03

    return {
        "ticker": ticker, "company": raw.get("company"), "metric": metric,
        "metric_switch": switch_reason, "basis": basis, "lag": args.lag,
        "basis_label": model.BASIS_LABEL[basis], "checks": checks,
        "price": price, "as_of": raw.get("fetched_at"),
        "last_bar": {"date": bars[-1][0], "close": bars[-1][1], "stale": stale},
        "current": {"eps": current_eps, "multiple": current_multiple,
                    "period": observations[-1].period},
        "windows": {str(k): v for k, v in windows.items()},
        "headline_window": headline_years, "stats": stats, "regime": regime,
        "growth": growth, "normal_raw": normal_raw, "normal_adjusted": normal_adj,
        "multiple_override": args.multiple,
        "forward": forward, "headline_estimate": headline_row,
        "fair_value": fv, "band": band,
        "premium": (price / fv - 1.0) if fv else None,
        "grid": grid, "returns": returns, "dividend_yield": dividend,
        "ps_note": ps_note,
        "year_table": table, "above": above, "backtest": bt,
        "flags": flags, "refused": refused,
        "observations": observations, "window_observations": window_obs,
    }


def _basis_checks(quarterly, snapshot, points, price, basis):
    """Two reconciliations, run every time.

    finviz's snapshot `EPS (ttm)` and `P/E` are GAAP diluted, so on the default
    adjusted basis our multiple legitimately differs from the one every site
    displays. Both are reported rather than silently reconciled.
    """
    reported = [r for r in quarterly if r.get("reported") and r.get("fiscal_end_date")]
    reported.sort(key=lambda r: r["fiscal_end_date"])
    last4 = reported[-4:]

    def total(kind):
        values = [model.eps_of(r, kind) for r in last4]
        return sum(values) if len(values) == 4 and all(v is not None for v in values) else None

    gaap_sum = total("gaap")
    adj_sum = total("adj")
    snapshot_eps = data.snapshot_num(snapshot, "EPS (ttm)")
    snapshot_pe = data.snapshot_num(snapshot, "P/E")

    ok, detail = True, []
    if gaap_sum and snapshot_eps:
        drift = abs(gaap_sum / snapshot_eps - 1.0)
        if drift > TOLERANCE:
            ok = False
            detail.append(f"our GAAP TTM EPS {gaap_sum:.2f} vs finviz {snapshot_eps:.2f} "
                          f"({drift:.1%} apart)")
    if snapshot_eps and snapshot_pe and price:
        implied = price / snapshot_eps
        if abs(implied / snapshot_pe - 1.0) > 0.03:
            detail.append(f"finviz P/E {snapshot_pe:.1f} vs price/EPS {implied:.1f}")

    return {
        "ok": ok, "detail": "; ".join(detail) or None,
        "ttm_adjusted": adj_sum, "ttm_gaap": gaap_sum,
        "snapshot_eps_ttm": snapshot_eps, "snapshot_pe": snapshot_pe,
        "used": adj_sum if basis == "adj" else gaap_sum,
        "pe_adjusted": (price / adj_sum) if adj_sum and adj_sum > 0 else None,
        "pe_gaap": (price / gaap_sum) if gaap_sum and gaap_sum > 0 else None,
    }


def _ps_reconcile(observations, snapshot, shares):
    """Our reconstructed P/S against the one finviz publishes."""
    theirs = data.snapshot_num(snapshot, "P/S")
    ours = observations[-1].multiple if observations else None
    if not theirs or not ours:
        return None
    drift = abs(ours / theirs - 1.0)
    return {
        "ours": ours, "theirs": theirs, "drift": drift, "ok": drift <= 0.05,
        "quarters": len(shares),
    }


def _windows(observations, args, current_multiple):
    """Describe every window, then pick the headline one.

    A window whose median multiple shifted materially between its first and
    second half is not describing one regime, so the headline falls back to the
    longest shorter window that is stable.
    """
    described = {}
    span_years = (observations[-1].date - observations[0].date).days / 365.25
    candidates = sorted(set(WINDOWS + ([args.window] if isinstance(args.window, int) else [])))
    for years in candidates + (["max"] if args.window == "max" else []):
        # Don't offer a 15-year window when only 5 years of data exist — three
        # identical rows would imply agreement that isn't there.
        if isinstance(years, int) and span_years < years * 0.9:
            continue
        subset = model.window_slice(observations, years)
        if len(subset) < 52:
            continue
        subset, _ = model.winsorize(subset)
        stats = model.describe(subset, tuple(args.bands), current_multiple)
        if not stats:
            continue
        stats["regime"] = model.regime_check(subset)
        stats["span_years"] = span_years if years == "max" else float(years)
        described[years] = stats

    if not described:
        # Shorter history than the smallest standard window — describe what
        # exists rather than refusing to look at it.
        subset, _ = model.winsorize(list(observations))
        stats = model.describe(subset, tuple(args.bands), current_multiple)
        if not stats:
            raise data.FVDataError(
                "yahoo", "not enough overlapping price and earnings history to form "
                         "any window")
        stats["regime"] = model.regime_check(subset)
        stats["span_years"] = span_years
        described["max"] = stats
        return described, "max"

    requested = args.window if args.window in described else max(
        k for k in described if isinstance(k, int))
    order = [w for w in sorted(described, key=lambda w: (w == "max", w))
             if w == requested or (isinstance(w, int) and isinstance(requested, int)
                                   and w < requested)]
    for candidate in reversed(order):
        regime = described[candidate].get("regime")
        if not regime or not regime.get("shifted"):
            return described, candidate
    return described, min(described, key=lambda w: (w == "max", w))


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def _pct(value, digits=0):
    return "—" if value is None else f"{value * 100:+.{digits}f}%"


def _money(value):
    return "—" if value is None else f"${value:,.2f}"


def _mult(value):
    return "—" if value is None else f"{value:.1f}x"


def _win_label(key, windows):
    """'10y' — or 'all 4.2y' for the everything-we-have fallback."""
    stats = windows.get(str(key)) or windows.get(key) or {}
    span = stats.get("span_years")
    if str(key) == "max":
        return f"all {span:.1f}y" if span else "all available"
    return f"{key}y"


def _ordinal(value):
    n = int(round(value))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _window_key(key):
    try:
        return int(key)
    except (TypeError, ValueError):
        return 10 ** 6


def render_md(r):
    metric_name = "P/E" if r["metric"] == "pe" else "P/S"
    out = [f"# {r['ticker']} — normal-multiple fair value"]
    if r.get("company"):
        out[0] += f"\n\n_{r['company']}_"
    out.append("")

    if r["metric_switch"]:
        out += [f"> **Metric: {metric_name}** — {r['metric_switch']}", ""]

    checks = r["checks"]
    current = r["current"]
    if r["metric"] == "pe":
        out.append(f"Price **{_money(r['price'])}** · trailing EPS "
                   f"**{checks['used']:.2f}** ({r['basis_label']}, through "
                   f"{current['period']}) · current P/E **{_mult(current['multiple'])}**")
        if r["basis"] == "adj" and checks["pe_gaap"] and checks["pe_adjusted"]:
            if abs(checks["pe_gaap"] / checks["pe_adjusted"] - 1) > 0.02:
                out.append(f"On GAAP the multiple is {checks['pe_gaap']:.1f}x — that is "
                           "what finviz and most sites display. This report uses "
                           f"{r['basis_label']} EPS throughout so the history and the "
                           "forward estimates stay on one basis.")
        out.append("Basis check: "
                   + ("passed" if checks["ok"] else f"**FAILED** — {checks['detail']}"))
    else:
        out.append(f"Price **{_money(r['price'])}** · trailing revenue/share "
                   f"**{_money(r['price'] / current['multiple']) if current['multiple'] else '—'}** "
                   f"(through {current['period']}) · current P/S "
                   f"**{_mult(current['multiple'])}**")
        note = r.get("ps_note")
        if note:
            out.append(f"Share count reconstructed from stockanalysis; our P/S "
                       f"{note['ours']:.2f} vs finviz {note['theirs']:.2f} "
                       + ("(reconciles)" if note["ok"]
                          else f"— **{note['drift']:.0%} apart, treat with suspicion**")
                       + f". Only {note['quarters']} quarters of share history are "
                       "available, so this window is short.")
    if r["last_bar"]["stale"]:
        out.append(f"⚠ last weekly close {_money(r['last_bar']['close'])} "
                   f"({r['last_bar']['date']}) is more than 3% from the live price.")
    out.append("")

    if r["refused"]:
        out += ["## No defensible fair value", "",
                "The guardrails below rule out a normal multiple for this name. A "
                "number here would be worse than none.", ""]
        out += _flags_md(r)
        shorter = max(2, int(r["headline_window"]) // 2) if isinstance(
            r["headline_window"], int) else 3
        out += ["If you want a look anyway, `--window {n}` narrows to the recent era "
                "and `--multiple X` applies a multiple of your own — both still print "
                "these warnings.".format(n=shorter), ""]
        return "\n".join(out)

    warns = [f for f in r["flags"] if f["severity"] == "warn"]
    if warns:
        out += ["> ⚠ **{n} caveat{s}** on this valuation — {codes}. Read the Guardrails "
                "section before using the number above.".format(
                    n=len(warns), s="" if len(warns) == 1 else "s",
                    codes=", ".join(f["code"].replace("_", " ").lower() for f in warns)),
                ""]

    # ---- verdict ----------------------------------------------------------
    growth = r["growth"]
    estimate = r["headline_estimate"]
    out += ["## Verdict", "", "| | |", "|---|---|"]
    label = f"Normal multiple ({_win_label(r['headline_window'], r['windows'])} median)"
    if r["multiple_override"]:
        label = "Normal multiple (manual override)"
    out.append(f"| {label} | **{_mult(r['normal_raw'])}** |")
    if abs(growth["factor"] - 1.0) > 0.001:
        detail = ""
        if growth.get("forward") is not None and growth.get("hist_5y") is not None:
            detail = (f" — forward {growth['forward'] * 100:.0f}%/yr to "
                      f"{growth['forward_period']} vs trailing 5y "
                      f"{growth['hist_5y'] * 100:.0f}%/yr")
        out.append(f"| Growth haircut | x{growth['factor']:.2f}{detail} |")
        out.append(f"| **Normal multiple, adjusted** | **{_mult(r['normal_adjusted'])}** |")
    if estimate:
        unit = "EPS" if r["metric"] == "pe" else "revenue/share"
        out.append(f"| Fair value on {estimate['period']} {unit} "
                   f"{estimate['eps']:.2f} | **{_money(r['fair_value'])}** |")
        if r["band"]:
            out.append(f"| Band ({_mult(r['grid']['multiples']['bear'])} – "
                       f"{_mult(r['grid']['multiples']['bull'])}) | "
                       f"{_money(r['band'][0])} – {_money(r['band'][1])} |")
        out.append(f"| Premium / discount | **{_pct(r['premium'])}** |")
    if r["stats"].get("percentile_now") is not None:
        out.append(f"| Today's multiple in its own "
                   f"{_win_label(r['headline_window'], r['windows'])} range | "
                   f"**{_ordinal(r['stats']['percentile_now'])} percentile** |")
    out.append("")

    if r["returns"]:
        parts = []
        for item in r["returns"]:
            mark = " †" if item["thin"] else ""
            if item["annualised"] is not None:
                parts.append(f"**{item['annualised'] * 100:+.0f}%/yr** to {item['period']} "
                             f"({item['years']:.1f}y, {item['total_price'] * 100:+.0f}% "
                             f"total){mark}")
            else:
                parts.append(f"**{item['total_price'] * 100:+.0f}% total** to "
                             f"{item['period']} ({item['years']:.1f}y — too short to "
                             f"annualise meaningfully){mark}")
        line = "Implied return if the price meets the line: " + " · ".join(parts) + "."
        if r["dividend_yield"]:
            line += (f" Annualised figures add a {r['dividend_yield'] * 100:.2f}% forward "
                     "dividend yield; the rest is price.")
        out += [line, ""]
    if growth.get("note"):
        out += [f"_{growth['note']}._", ""]

    # ---- windows ----------------------------------------------------------
    out += [f"## Normal {metric_name} by window", "",
            "| Window | Weeks | p25 | Median | p75 | Regime check |",
            "|---|---|---|---|---|---|"]
    for key, stats in sorted(r["windows"].items(),
                             key=lambda kv: (kv[0] == "max", _window_key(kv[0]))):
        regime = stats.get("regime") or {}
        if not regime:
            note = "—"
        elif regime.get("shifted"):
            note = (f"**shifted** {regime['first_half']:.1f} → "
                    f"{regime['second_half']:.1f} ({regime['shift'] * 100:+.0f}%)")
        else:
            note = (f"ok — {regime['first_half']:.1f} vs {regime['second_half']:.1f} "
                    f"({regime['shift'] * 100:+.0f}%)")
        name = _win_label(key, r["windows"])
        if str(key) == str(r["headline_window"]):
            name = f"**{name}**"
        out.append(f"| {name} | {stats['n_usable']} | {stats['p_low']:.1f} | "
                   f"{stats['median']:.1f} | {stats['p_high']:.1f} | {note} |")
    out.append("")
    shifted = [k for k, s in r["windows"].items()
               if (s.get("regime") or {}).get("shifted")]
    headline_label = _win_label(r["headline_window"], r["windows"])
    if shifted:
        names = ", ".join(_win_label(s, r["windows"]) for s in shifted)
        if str(r["headline_window"]) in [str(s) for s in shifted]:
            out += [f"**Every window fails the regime test** ({names}) — this stock has "
                    "not had one stable multiple in any period we can measure. The "
                    f"**{headline_label}** window is used as the least-bad option and "
                    "the fair value above should be read as a rough bearing, not a "
                    "level.", ""]
        else:
            out += [f"Window(s) {names} fail the regime test — their halves describe "
                    f"different eras. The **{headline_label}** window is the headline.",
                    ""]

    # ---- grid -------------------------------------------------------------
    multiples = r["grid"]["multiples"]
    unit_long = "forward EPS" if r["metric"] == "pe" else "forward revenue/share"
    out += [f"## Scenario grid — multiple x {unit_long}", "",
            f"| | Bear {_mult(multiples['bear'])} | Base {_mult(multiples['base'])} "
            f"| Bull {_mult(multiples['bull'])} |", "|---|---|---|---|"]
    for row in r["grid"]["rows"]:
        mark = " †" if row["thin"] else ""
        cells = []
        for key in ("bear", "base", "bull"):
            text = _money(row["values"][key])
            cells.append(f"({text})" if row["thin"] else text)
        out.append(f"| **{row['period']}** {row['eps']:.2f} "
                   f"({row['analysts'] or 0} analysts){mark} | " + " | ".join(cells) + " |")
    out.append("")
    out.append(f"Against {_money(r['price'])} today."
               + (" † thin coverage — parenthesised cells are excluded from the headline."
                  if any(row["thin"] for row in r["grid"]["rows"]) else ""))
    if abs(r["growth"]["factor"] - 1.0) > 0.001:
        out.append(f"Multiples are growth-adjusted; unadjusted they would be "
                   f"{r['stats']['p_low']:.1f} / {r['stats']['median']:.1f} / "
                   f"{r['stats']['p_high']:.1f}.")
    out.append("")

    # ---- history ----------------------------------------------------------
    out += ["## History — calendar year-end", "",
            f"| Year | Price | {'TTM EPS' if r['metric'] == 'pe' else 'TTM rev/sh'} "
            f"| Through | {metric_name} | "
            f"Fair value @{_mult(r['normal_adjusted'])} | Prem/disc |",
            "|---|---|---|---|---|---|---|"]
    for row in r["year_table"]:
        out.append(f"| {row['label']} | {_money(row['price'])} | "
                   f"{row['eps']:.2f} | {row['period']} | {_mult(row['multiple'])} | "
                   f"{_money(row['fair_value'])} | {_pct(row['premium'])} |")
    out.append("")
    if r["above"]:
        out.append(f"At the {_mult(r['normal_adjusted'])} line above, the stock spent "
                   f"**{r['above']['share']:.0%}** of the last {r['above']['weeks']} weeks "
                   "trading higher than it. "
                   + ("Against the unadjusted median the split is 50/50 by construction — "
                      "this figure is only informative because the multiple was "
                      "growth-adjusted downward."
                      if abs(r["growth"]["factor"] - 1.0) > 0.001 else
                      "That is 50/50 by construction: the line *is* the median. What "
                      "matters is the spread of the premium column, not the count."))
        out.append("")

    # ---- base rates -------------------------------------------------------
    bt = r["backtest"]
    if bt:
        horizon = bt["horizon_weeks"] // 52
        out.append(f"## Base rates — forward {horizon}y return by {metric_name} quartile")
        out.append("")
        if not bt["monotonic"]:
            out += ["**No monotonic relationship.** Cheaper quartiles have not "
                    "reliably produced better forward returns for this stock in this "
                    "window — the multiple alone has not been predictive here.", ""]
        out += [f"| Bucket | {metric_name} range | n | Median fwd {horizon}y | Mean | Positive |",
                "|---|---|---|---|---|---|"]
        for bucket in bt["buckets"]:
            if not bucket:
                continue
            out.append(f"| {bucket['label']} | {bucket['low']:.1f} – {bucket['high']:.1f} | "
                       f"{bucket['n']} | {_pct(bucket['median'])} | {_pct(bucket['mean'])} | "
                       f"{bucket['positive'] * 100:.0f}% |")
        out.append("")
        independent = ", ".join(
            f"{model.BUCKET_LABELS[i].split()[0]} {_pct(v)}"
            for i, v in enumerate(bt["non_overlapping"]) if v is not None)
        out.append(f"Windows overlap: {bt['n']} observations contain roughly "
                   f"**{bt['effective_n']:.0f} independent** {horizon}-year periods. "
                   f"Non-overlapping estimate: {independent}. "
                   "This is what has happened, not what will happen.")
        out.append("")

    out += _flags_md(r)

    lag = ("its earnings announcement date (point-in-time, no lookahead)"
           if r["lag"] == "report" else "its fiscal period end (lookahead — --lag period)")
    out += ["## Method", "",
            f"{metric_name} = weekly split-adjusted close ÷ trailing-twelve-month "
            f"{r['basis_label']} {'EPS' if r['metric'] == 'pe' else 'revenue per share'}, "
            f"where each week takes the most recent figure as of {lag}. "
            "History and forward estimates are both finviz "
            f"{r['basis_label']} consensus — the same basis. "
            "Prices from Yahoo Finance (raw close, which is split-adjusted; "
            "dividend-adjusted prices would understate historical multiples).",
            "",
            "One valuation lens among several. It assumes the past multiple is a "
            "reasonable anchor for the future, which is exactly what the guardrails "
            "above test. Not advice.", ""]
    if r.get("as_of"):
        out.append(f"Data as of {r['as_of']}.")
    return "\n".join(out)


def _flags_md(r):
    out = ["## Guardrails", ""]
    symbol = {"ok": "ok", "warn": "**warn**", "refuse": "**REFUSE**"}
    for flag in r["flags"]:
        out.append(f"- {symbol[flag['severity']]} — {flag['detail']}")
    out.append("")
    return out


# --------------------------------------------------------------------------
# Other renderers
# --------------------------------------------------------------------------

def series_rows(r):
    return [{"date": o.date.isoformat(), "price": f"{o.price:.4f}",
             "ttm_eps": ("" if o.eps is None else f"{o.eps:.4f}"),
             "multiple": ("" if o.multiple is None else f"{o.multiple:.4f}")}
            for o in r["observations"]]


def to_csv(rows, columns):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in columns})
    return buffer.getvalue().rstrip("\n")


def jsonable(r):
    out = {k: v for k, v in r.items()
           if k not in ("observations", "window_observations")}
    out["series"] = series_rows(r)
    return out


def write(text, path):
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")
        print(f"wrote {path}", file=sys.stderr)
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        print(text)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

COMMANDS = ("value", "series", "history", "backtest", "grid", "cache-clear")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="fair_value.py",
        description="What a stock is worth at its own historical multiple.")
    parser.add_argument("command", nargs="?", default="value",
                        help="value (default) · series · history · backtest · grid · cache-clear")
    parser.add_argument("ticker", nargs="?", help="ticker symbol")
    parser.add_argument("--window", default="10",
                        help="years for the headline multiple: 5, 10, 15 or max (default 10)")
    parser.add_argument("--basis", choices=["adj", "gaap"], default="adj",
                        help="adjusted street consensus (default) or GAAP; binds history "
                             "and forward estimates together")
    parser.add_argument("--metric", choices=["auto", "pe", "ps"], default="auto")
    parser.add_argument("--lag", choices=["report", "period"], default="report",
                        help="join EPS on its announcement date (default) or fiscal end")
    parser.add_argument("--bands", default="25,75", help="bear,bull percentiles")
    parser.add_argument("--multiple", type=float, help="override the normal multiple")
    parser.add_argument("--growth-haircut", default="auto",
                        help="auto (default) · none · sqrt · linear · a factor like 0.8")
    parser.add_argument("--horizon", choices=["1y", "3y"], default="1y")
    parser.add_argument("--no-backtest", action="store_true")
    parser.add_argument("--chart", nargs="?", const="", default=None,
                        metavar="FILE", help="also write a self-contained HTML chart")
    parser.add_argument("-f", "--format", choices=["md", "json", "csv"], default="md")
    parser.add_argument("-o", "--out")
    parser.add_argument("--refresh", action="store_true")

    argv = list(argv)
    if argv and argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv = ["value"] + argv
    args = parser.parse_args(argv)

    if args.command != "cache-clear" and not args.ticker:
        parser.error("a ticker is required, e.g. fair_value.py NVDA")

    try:
        args.bands = tuple(sorted(float(x) for x in str(args.bands).split(",")))
        if len(args.bands) != 2:
            raise ValueError
    except ValueError:
        parser.error("--bands takes two percentiles, e.g. --bands 25,75")
    args.window = "max" if str(args.window).lower() == "max" else int(args.window)
    if args.growth_haircut in ("auto", "sqrt"):
        args.growth_haircut = "auto"
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.command == "cache-clear":
        print(f"cleared {data.cache_clear()} cached payloads", file=sys.stderr)
        return 0

    try:
        report = build_report(args)
    except data.FVDataError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    if args.command == "series":
        rows = series_rows(report)
        columns = ["date", "price", "ttm_eps", "multiple"]
        text = (json.dumps(rows, indent=2) if args.format == "json"
                else to_csv(rows, columns))
    elif args.format == "json":
        text = json.dumps(jsonable(report), indent=2, default=str)
    elif args.format == "csv":
        if args.command == "history":
            rows = report["year_table"]
            text = to_csv(rows, ["year", "date", "price", "eps", "period",
                                 "multiple", "fair_value", "premium"])
        else:
            text = to_csv(series_rows(report), ["date", "price", "ttm_eps", "multiple"])
    else:
        full = render_md(report)
        if args.command == "value":
            text = full
        else:
            text = _section(full, args.command)

    if args.chart is not None:
        import fv_chart
        path = args.chart or f"{report['ticker']}-fair-value.html"
        fv_chart.write_chart(report, path)
        print(f"wrote chart {path}", file=sys.stderr)

    write(text, args.out)
    return 2 if report["refused"] else 0


def _section(markdown, command):
    """Slice one section out of the full report for the focused subcommands."""
    wanted = {"history": "## History", "backtest": "## Base rates",
              "grid": "## Scenario grid"}[command]
    lines = markdown.splitlines()
    head = [lines[0], ""]
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith(wanted))
    except StopIteration:
        return "\n".join(head) + f"\n_{wanted[3:]} is not available for this name._"
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("## ")), len(lines))
    return "\n".join(head + lines[start:end])


if __name__ == "__main__":
    raise SystemExit(main())
