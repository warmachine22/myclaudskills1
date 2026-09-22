"""All the maths for the fair-value skill. Pure functions, no I/O.

The invariant that matters most: EPS is read *only* through `eps_of()`, which is
locked to one basis. There is no fallback from adjusted to GAAP on a missing
value — mixing them is a 28% error on a single NVDA quarter, and silent
substitution must be structurally impossible rather than merely discouraged.
"""

from __future__ import annotations

import datetime as dt
import math
from bisect import bisect_right

# --------------------------------------------------------------------------
# Basis lock
# --------------------------------------------------------------------------

BASIS_KEYS = {
    "adj": ("eps_actual", "eps_estimate", "eps_analysts"),
    "gaap": ("gaap_eps_actual", "gaap_eps_estimate", "gaap_eps_analysts"),
}

BASIS_LABEL = {"adj": "adjusted (street consensus)", "gaap": "GAAP"}

REPORT_LAG_DAYS = 45  # only when finviz has no earnings_date for a quarter


def eps_of(row, basis, kind="actual"):
    """The one door through which EPS is read. No cross-basis fallback."""
    actual_key, estimate_key, _ = BASIS_KEYS[basis]
    value = row.get(actual_key if kind == "actual" else estimate_key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def analysts_of(row, basis):
    value = row.get(BASIS_KEYS[basis][2])
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Small statistics helpers (stdlib only, numpy-compatible percentiles)
# --------------------------------------------------------------------------

def percentile(values, q):
    """Linear-interpolation percentile, q in 0..100. `values` need not be sorted."""
    data = sorted(v for v in values if v is not None)
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * (q / 100.0)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return data[int(pos)]
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def median(values):
    return percentile(values, 50)


def mean(values):
    data = [v for v in values if v is not None]
    return sum(data) / len(data) if data else None


def rank_pct(values, target):
    """Share of observations at or below `target`, as a percentile 0-100."""
    data = [v for v in values if v is not None]
    if not data or target is None:
        return None
    return 100.0 * sum(1 for v in data if v <= target) / len(data)


def _date(text):
    return dt.date.fromisoformat(str(text)[:10])


def _years_between(start, end):
    return (end - start).days / 365.25


# --------------------------------------------------------------------------
# Trailing-twelve-month series
# --------------------------------------------------------------------------

class TtmPoint:
    __slots__ = ("available", "eps", "revenue", "period", "period_end")

    def __init__(self, available, eps, revenue, period, period_end):
        self.available = available
        self.eps = eps
        self.revenue = revenue
        self.period = period
        self.period_end = period_end


def ttm_points(quarterly, basis, lag="report"):
    """Roll reported quarters into trailing-12-month sums.

    Each point becomes available on the date the market could actually know it —
    the earnings announcement — not the fiscal period end. Joining on the fiscal
    end would credit the market with knowing December's EPS on December 31 when
    it was announced in late January: lookahead bias landing exactly where the
    series steps.
    """
    rows = [r for r in quarterly if r.get("reported") and r.get("fiscal_end_date")]
    rows.sort(key=lambda r: r["fiscal_end_date"])

    points, dropped = [], 0
    for i in range(3, len(rows)):
        window = rows[i - 3: i + 1]
        eps_values = [eps_of(r, basis) for r in window]
        if any(v is None for v in eps_values):
            dropped += 1
            continue
        period_end = _date(window[-1]["fiscal_end_date"])
        if lag == "period":
            available = period_end
        else:
            reported_on = window[-1].get("earnings_date")
            available = (_date(reported_on) if reported_on
                         else period_end + dt.timedelta(days=REPORT_LAG_DAYS))
        revenues = [r.get("revenue_actual") for r in window]
        revenue = (sum(float(v) for v in revenues)
                   if all(isinstance(v, (int, float)) for v in revenues) else None)
        points.append(TtmPoint(available, sum(eps_values), revenue,
                               window[-1].get("fiscal_period"), period_end))
    points.sort(key=lambda p: p.available)
    return points, dropped


class Obs:
    __slots__ = ("date", "price", "eps", "revenue", "multiple", "period")

    def __init__(self, date, price, eps, revenue, multiple, period):
        self.date = date
        self.price = price
        self.eps = eps
        self.revenue = revenue
        self.multiple = multiple
        self.period = period


def join_weekly(bars, points, shares=None):
    """Step-join weekly closes onto the TTM series.

    `multiple` is None where the denominator is non-positive; the observation is
    kept so the guardrails can count it.
    """
    if not points:
        return []
    if shares:
        shares = [(_date(d) if not isinstance(d, dt.date) else d, s) for d, s in shares]
    available = [p.available for p in points]
    observations = []
    for date_text, close in bars:
        bar_date = _date(date_text)
        idx = bisect_right(available, bar_date) - 1
        if idx < 0:
            continue  # before the first knowable TTM figure
        point = points[idx]
        if shares is None:
            denominator = point.eps
        else:
            share_count = _step_lookup(shares, bar_date)
            denominator = ((point.revenue * 1e6 / share_count)
                           if point.revenue and share_count else None)
        multiple = (close / denominator) if denominator and denominator > 0 else None
        observations.append(Obs(bar_date, close, point.eps, point.revenue,
                                multiple, point.period))
    return observations


def _step_lookup(pairs, target):
    dates = [d for d, _ in pairs]
    idx = bisect_right(dates, target) - 1
    if idx < 0:
        return None
    return pairs[idx][1]


# --------------------------------------------------------------------------
# Windows and distribution
# --------------------------------------------------------------------------

def window_slice(observations, years, today=None):
    if not observations:
        return []
    if years in (None, "max"):
        return list(observations)
    cutoff = (today or observations[-1].date) - dt.timedelta(days=int(round(365.25 * years)))
    return [o for o in observations if o.date >= cutoff]


def describe(observations, bands=(25, 75), current=None):
    usable = [o.multiple for o in observations if o.multiple is not None]
    if not usable:
        return None
    low, high = bands
    return {
        "n": len(observations),
        "n_usable": len(usable),
        "p_low": percentile(usable, low),
        "median": percentile(usable, 50),
        "p_high": percentile(usable, high),
        "min": min(usable),
        "max": max(usable),
        "bands": (low, high),
        "first": observations[0].date.isoformat(),
        "last": observations[-1].date.isoformat(),
        "percentile_now": rank_pct(usable, current),
    }


def winsorize(observations, lo_q=1, hi_q=99):
    """Clamp extreme multiples so one near-zero-EPS quarter cannot set the band."""
    usable = [o.multiple for o in observations if o.multiple is not None]
    if len(usable) < 20:
        return observations, 0
    lo, hi = percentile(usable, lo_q), percentile(usable, hi_q)
    clamped = 0
    out = []
    for o in observations:
        multiple = o.multiple
        if multiple is not None and (multiple < lo or multiple > hi):
            multiple = min(max(multiple, lo), hi)
            clamped += 1
        out.append(Obs(o.date, o.price, o.eps, o.revenue, multiple, o.period))
    return out, clamped


def regime_check(observations, threshold=0.35):
    """Compare the median multiple of the window's first half to its second."""
    usable = [o for o in observations if o.multiple is not None]
    if len(usable) < 52:
        return None
    half = len(usable) // 2
    first = median([o.multiple for o in usable[:half]])
    second = median([o.multiple for o in usable[half:]])
    if not first or not second:
        return None
    shift = second / first - 1
    return {"first_half": first, "second_half": second, "shift": shift,
            "shifted": abs(shift) > threshold, "threshold": threshold}


# --------------------------------------------------------------------------
# Guardrails
# --------------------------------------------------------------------------

def guardrails(observations, regime, forward_rows, basis, metric="pe",
               dropped_quarters=0, winsorized=0, min_weeks=156, switch_reason=None):
    """Every check runs and reports, including the ones that pass.

    The denominator tests apply to whichever denominator is actually in use. A
    name on P/S must not be refused for negative EPS — negative EPS is precisely
    why it is on P/S.
    """
    flags = []
    total = len(observations)
    is_pe = metric == "pe"
    label = "trailing EPS" if is_pe else "trailing revenue"
    code_negative = "NEGATIVE_EPS" if is_pe else "NEGATIVE_REVENUE"
    code_near = "NEAR_ZERO_EPS" if is_pe else "NEAR_ZERO_REVENUE"

    def denominator(o):
        return o.eps if is_pe else o.revenue

    def add(code, severity, detail):
        flags.append({"code": code, "severity": severity, "detail": detail})

    if not is_pe and switch_reason:
        add("METRIC_FALLBACK", "warn",
            switch_reason + " — valuing on sales instead, which ignores whether "
            "those sales earn anything")

    if total < min_weeks:
        add("SHORT_HISTORY", "refuse",
            f"only {total} weeks of joined history (need {min_weeks})")
    else:
        add("SHORT_HISTORY", "ok", f"{total} weeks of history")

    negative = [o for o in observations
                if denominator(o) is not None and denominator(o) <= 0]
    share = len(negative) / total if total else 0
    if not negative:
        add(code_negative, "ok", f"no weeks with negative {label}")
    elif share <= 0.05:
        add(code_negative, "warn",
            f"{len(negative)} of {total} weeks ({share:.0%}) had negative {label} "
            "and are excluded from the multiple")
    else:
        add(code_negative, "refuse",
            f"{len(negative)} of {total} weeks ({share:.0%}) had negative {label}")

    positive = [denominator(o) for o in observations
                if denominator(o) and denominator(o) > 0]
    if positive:
        base = median(positive)
        near_zero = [o for o in observations
                     if denominator(o) and 0 < denominator(o) < 0.20 * base]
        near_share = len(near_zero) / total if total else 0
        if not near_zero:
            add(code_near, "ok",
                f"lowest {label} is {min(positive) / base:.0%} of the window median")
        elif near_share <= 0.10:
            add(code_near, "warn",
                f"{len(near_zero)} weeks had {label} under 20% of the window median, "
                f"inflating the multiple; {winsorized} extreme values clamped")
        else:
            add(code_near, "refuse",
                f"{len(near_zero)} of {total} weeks ({near_share:.0%}) had {label} "
                "near zero — the multiple is meaningless there")

        peak, drawdown, went_negative = 0.0, 0.0, False
        for o in observations:
            value = denominator(o)
            if value is None:
                continue
            if value <= 0:
                went_negative = True
            peak = max(peak, value)
            if peak > 0:
                drawdown = max(drawdown, min(1.0, 1 - value / peak))
        if went_negative:
            add("VOLATILE_BASE", "warn",
                f"{label} fell all the way to a loss inside this window — a median "
                "multiple across a full cycle is the honest read, and any single-year "
                "estimate is a weak anchor")
        elif drawdown > 0.50:
            add("VOLATILE_BASE", "warn",
                f"{label} fell {drawdown:.0%} peak-to-trough inside this window. If "
                "that is a cycle, the multiple looks cheapest exactly when earnings "
                "are at their peak; if it is a young company scaling up, the early "
                "multiples describe a different business")
        else:
            add("VOLATILE_BASE", "ok", f"max {label} drawdown {drawdown:.0%}")

    if regime and regime.get("shifted"):
        add("REGIME_SHIFT", "warn",
            f"median multiple moved {regime['shift']:+.0%} between the first and "
            f"second half of this window ({regime['first_half']:.1f} to "
            f"{regime['second_half']:.1f}) — 'normal' is not stable here")
    elif regime:
        add("REGIME_SHIFT", "ok",
            f"first half {regime['first_half']:.1f} vs second {regime['second_half']:.1f} "
            f"({regime['shift']:+.0%})")

    # A stock that has always been expensive will always look cheap against its
    # own history. Anchoring on an extreme multiple is the method's quietest
    # failure, because every number in the report still looks reasonable.
    normal = median([o.multiple for o in observations if o.multiple is not None])
    ceiling = 60.0 if is_pe else 15.0
    if normal and normal > ceiling:
        add("EXTREME_MULTIPLE", "warn",
            f"the 'normal' multiple here is {normal:.0f}x — itself a price that "
            "embeds years of flawless growth. 'Cheap against its own history' is not "
            "the same as cheap, and a de-rating toward the wider market would swamp "
            "any of the fair values above")
    elif normal:
        add("EXTREME_MULTIPLE", "ok", f"normal multiple {normal:.1f}x is not extreme")

    thin = [r for r in forward_rows if (r.get("analysts") or 0) < 5]
    if thin:
        add("THIN_COVERAGE", "warn",
            "; ".join(f"{r['period']} rests on {r.get('analysts') or 0} analysts"
                      for r in thin) + " — excluded from the headline")
    elif forward_rows:
        add("THIN_COVERAGE", "ok",
            f"all {len(forward_rows)} forward years have 5+ analysts")

    if dropped_quarters:
        add("MISSING_EPS", "warn",
            f"{dropped_quarters} quarters lacked {BASIS_LABEL[basis]} EPS and were "
            "dropped rather than filled from the other basis")

    return flags


def worst_severity(flags):
    for level in ("refuse", "warn", "ok"):
        if any(f["severity"] == level for f in flags):
            return level
    return "ok"


# --------------------------------------------------------------------------
# Growth adjustment
# --------------------------------------------------------------------------

def cagr(start, end, years):
    if not start or not end or start <= 0 or end <= 0 or years <= 0:
        return None
    return (end / start) ** (1.0 / years) - 1.0


def trailing_cagr(observations, years):
    if not observations:
        return None
    latest = observations[-1]
    target = latest.date - dt.timedelta(days=int(round(365.25 * years)))
    older = [o for o in observations if o.date <= target]
    if not older or not older[-1].eps:
        return None
    return cagr(older[-1].eps, latest.eps, years)


def growth_adjust(observations, forward_rows, mode="auto", today=None):
    """Haircut the normal multiple when growth is decelerating.

    Never marks up. The failure mode of this method is paying a hypergrowth
    multiple for a business that has stopped growing, not the reverse, so the
    correction is deliberately one-sided.
    """
    result = {"mode": mode, "factor": 1.0, "hist_5y": trailing_cagr(observations, 5),
              "hist_10y": trailing_cagr(observations, 10), "forward": None,
              "forward_period": None, "forward_years": None, "note": None}

    if mode == "none":
        result["note"] = "growth haircut disabled"
        return result
    try:
        result["factor"] = max(0.0, min(1.0, float(mode)))
        result["mode"] = "manual"
        result["note"] = f"factor set manually to {result['factor']:.3f}"
        return result
    except (TypeError, ValueError):
        pass

    usable = [r for r in forward_rows if r.get("eps") and (r.get("analysts") or 0) >= 5]
    if not usable or not observations or not observations[-1].eps:
        result["note"] = "no forward estimate with 5+ analysts — no haircut applied"
        return result

    target = usable[-1]
    today = today or observations[-1].date
    years = _years_between(today, _date(target["end"])) if target.get("end") else None
    if not years or years <= 0:
        result["note"] = "forward horizon unknown — no haircut applied"
        return result

    forward = cagr(observations[-1].eps, target["eps"], years)
    result.update({"forward": forward, "forward_period": target["period"],
                   "forward_years": years})

    hist = result["hist_5y"]
    if hist is None or hist <= 0 or forward is None or forward <= 0:
        result["note"] = ("growth undefined on one side (a negative or zero base) "
                          "— no haircut applied")
        return result

    ratio = forward / hist
    if mode == "linear":
        raw = ratio
    else:  # sqrt, the default: justified P/E responds to growth sublinearly
        raw = math.sqrt(ratio)
    result["ratio"] = ratio
    result["factor"] = max(0.60, min(1.00, raw))
    if ratio > 1.25:
        result["note"] = ("growth is accelerating — no markup applied, so the normal "
                          "multiple may understate")
    elif result["factor"] >= 0.999:
        result["note"] = "growth broadly stable — no haircut needed"
    elif raw < 0.60:
        result["note"] = ("haircut hit its 0.60 floor — the business has changed enough "
                          "that its own history is a weak anchor")
    return result


# --------------------------------------------------------------------------
# Forward estimates, fair value, scenarios
# --------------------------------------------------------------------------

def forward_years(annual, basis, limit=3, metric="pe", shares=None):
    """Forward per-share denominators, one row per unreported fiscal year.

    For P/S the estimate is revenue (reported in millions) divided by today's
    share count — forward dilution is unknowable, and for the loss-making names
    that need this fallback it is usually material. The caller must say so.
    """
    rows = []
    for row in annual:
        if row.get("reported"):
            continue
        if metric == "pe":
            value = eps_of(row, basis, "estimate")
            analysts = analysts_of(row, basis)
        else:
            revenue = row.get("revenue_estimate")
            value = (float(revenue) * 1e6 / shares) if revenue and shares else None
            analysts = row.get("revenue_analysts")
        if value is None:
            continue
        try:
            analysts = int(analysts)
        except (TypeError, ValueError):
            analysts = None
        rows.append({"period": row.get("fiscal_period"),
                     "end": row.get("fiscal_end_date"),
                     "eps": value, "analysts": analysts})
    rows.sort(key=lambda r: r["end"] or "")
    return rows[:limit]


def fair_value(multiple, eps):
    return multiple * eps if multiple and eps else None


def scenario_grid(stats, factor, rows):
    multiples = {
        "bear": stats["p_low"] * factor,
        "base": stats["median"] * factor,
        "bull": stats["p_high"] * factor,
    }
    grid = []
    for row in rows:
        grid.append({
            "period": row["period"], "end": row["end"], "eps": row["eps"],
            "analysts": row["analysts"], "thin": (row.get("analysts") or 0) < 5,
            "values": {k: fair_value(m, row["eps"]) for k, m in multiples.items()},
        })
    return {"multiples": multiples, "rows": grid}


def implied_return(price, target_value, years, dividend_yield=None):
    """Total and annualised return if the price meets the fair-value line.

    Horizons under a year are NOT annualised: compounding a six-month move to a
    yearly rate turns a 59% gain into "+160%/yr", which reads as a forecast
    nobody made.
    """
    if not price or not target_value or not years or years <= 0:
        return None
    total = target_value / price - 1.0
    annualised = ((target_value / price) ** (1.0 / years) - 1.0) if years >= 1.0 else None
    return {"years": years, "total_price": total,
            "price_cagr": annualised, "dividend_yield": dividend_yield,
            "annualised": (annualised + (dividend_yield or 0.0)) if annualised else None}


# --------------------------------------------------------------------------
# History table
# --------------------------------------------------------------------------

def year_table(observations, normal_multiple, today=None):
    by_year = {}
    for o in observations:
        by_year[o.date.year] = o
    this_year = (today or dt.date.today()).year
    rows = []
    for year in sorted(by_year):
        o = by_year[year]
        value = fair_value(normal_multiple, o.eps)
        rows.append({
            "year": year, "label": f"{year} YTD" if year == this_year else str(year),
            "date": o.date.isoformat(), "price": o.price,
            "eps": o.eps, "period": o.period, "multiple": o.multiple,
            "fair_value": value,
            "premium": (o.price / value - 1.0) if value and value > 0 else None,
        })
    return rows


def share_above(observations, normal_multiple):
    usable = [o for o in observations if o.multiple is not None]
    if not usable:
        return None
    above = sum(1 for o in usable if o.multiple > normal_multiple)
    return {"weeks": len(usable), "above": above, "share": above / len(usable)}


# --------------------------------------------------------------------------
# Base rates
# --------------------------------------------------------------------------

BUCKET_LABELS = ["Q1 cheapest", "Q2", "Q3", "Q4 richest"]


def backtest(observations, horizon_weeks=52, buckets=4):
    """Realised forward return by multiple bucket.

    Weekly windows overlap heavily, so the effective independent sample is
    roughly n / horizon_weeks. Both that figure and a non-overlapping estimate
    are returned; the caller must show them.
    """
    usable = [o for o in observations if o.multiple is not None]
    if len(usable) < horizon_weeks + 40:
        return None

    dates = [o.date for o in usable]
    pairs = []
    for i, o in enumerate(usable):
        target = o.date + dt.timedelta(weeks=horizon_weeks)
        j = bisect_right(dates, target - dt.timedelta(days=10))
        if j >= len(usable):
            continue
        if abs((usable[j].date - target).days) > 21:
            continue
        pairs.append((o.multiple, usable[j].price / o.price - 1.0, i))
    if len(pairs) < 40:
        return None

    edges = [percentile([p[0] for p in pairs], 100.0 * k / buckets)
             for k in range(1, buckets)]

    def bucket_of(multiple):
        return sum(1 for e in edges if multiple > e)

    groups = [[] for _ in range(buckets)]
    for multiple, ret, _ in pairs:
        groups[bucket_of(multiple)].append(ret)

    lows = [min(p[0] for p in pairs)] + edges
    highs = edges + [max(p[0] for p in pairs)]
    rows = []
    for k, returns in enumerate(groups):
        if not returns:
            rows.append(None)
            continue
        rows.append({
            "label": BUCKET_LABELS[k] if buckets == 4 else f"B{k + 1}",
            "low": lows[k], "high": highs[k], "n": len(returns),
            "median": median(returns), "mean": mean(returns),
            "positive": sum(1 for r in returns if r > 0) / len(returns),
        })

    present = [r for r in rows if r]
    medians = [r["median"] for r in present]
    monotonic = all(medians[i] >= medians[i + 1] for i in range(len(medians) - 1))

    # Non-overlapping: sample every horizon_weeks-th observation, once per phase,
    # then take the median across phases so no single start date drives it.
    phase_medians = [[] for _ in range(buckets)]
    for phase in range(horizon_weeks):
        subset = pairs[phase::horizon_weeks]
        if len(subset) < 3:
            continue
        for k in range(buckets):
            returns = [r for m, r, _ in subset if bucket_of(m) == k]
            if returns:
                phase_medians[k].append(median(returns))
    independent = [median(p) if p else None for p in phase_medians]

    return {
        "horizon_weeks": horizon_weeks, "n": len(pairs),
        "effective_n": len(pairs) / horizon_weeks,
        "buckets": rows, "monotonic": monotonic,
        "non_overlapping": independent,
    }


# --------------------------------------------------------------------------
# Metric selection
# --------------------------------------------------------------------------

def choose_metric(pe_observations, pe_flags, requested="auto"):
    """pe -> ps -> refuse. Returns (metric, reason) with reason set on a switch."""
    if requested in ("pe", "ps"):
        return requested, None
    usable = [o for o in pe_observations if o.multiple is not None]
    if not usable:
        return "ps", "P/E unusable: trailing EPS was never positive in this window"
    blocking = [f for f in pe_flags if f["severity"] == "refuse"]
    if blocking:
        return "ps", "P/E unusable: " + "; ".join(f["detail"] for f in blocking)
    return "pe", None
