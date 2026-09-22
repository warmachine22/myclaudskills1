"""Inline-SVG chart builders for the forecast dashboard.

Same idiom as fair-value's fv_chart.py — SVG assembled in Python, no chart
library, no CDN, no fonts. Colours are the dataviz reference palette, already
validated in both modes (slots 1/2 worst adjacent CVD dE 24.7 light / 26.8 dark).

Every builder returns an SVG string, or None when the data cannot support the
chart. A None means the renderer omits the figure rather than drawing an empty
frame.
"""

from __future__ import annotations

import datetime as dt
import math

# Role names only; the page defines the values per theme.
PRICE = "var(--series-1)"
SECOND = "var(--series-2)"
GOOD = "var(--good)"
BAD = "var(--bad)"
MUTED = "var(--muted)"
GRID = "var(--grid)"


def _log(v):
    return math.log10(max(v, 1e-9))


def _nice_ticks(lo, hi, limit=7):
    """Linear ticks on a 1/2/2.5/5 ladder."""
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / limit
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for step in (1, 2, 2.5, 5, 10):
        if raw <= step * magnitude:
            step *= magnitude
            break
    else:
        step = 10 * magnitude
    start = math.floor(lo / step) * step
    out, value = [], start
    while value <= hi + step * 0.001:
        if value >= lo - step * 0.001:
            out.append(round(value, 10))
        value += step
    return out


def _log_ticks(lo, hi, limit=8):
    ladders = ((1,), (1, 5), (1, 2, 5), (1, 2, 3, 5, 7),
               (1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9))

    def build(mantissas):
        out, exponent = [], math.floor(_log(lo))
        while exponent <= math.ceil(_log(hi)):
            for m in mantissas:
                v = m * (10 ** exponent)
                if lo <= v <= hi:
                    out.append(v)
            exponent += 1
        return out

    best = build(ladders[0])
    for mantissas in ladders:
        ticks = build(mantissas)
        if 0 < len(ticks) <= limit:
            best = ticks
    return best


def _money(v, dp=0):
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e12:
        return f"${v/1e12:.1f}T"
    if a >= 1e9:
        return f"${v/1e9:.1f}B"
    if a >= 1e6:
        return f"${v/1e6:.0f}M"
    if a >= 1000:
        return f"${v:,.0f}"
    return f"${v:.{dp}f}" if a >= 10 else f"${v:.2f}"


def _svg(body, w, h, label):
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" '
            f'aria-label="{label}" preserveAspectRatio="xMidYMid meet">'
            f'{body}</svg>')


# --------------------------------------------------------------------------
# 1. Price with moving averages and volume
# --------------------------------------------------------------------------

def price_chart(technicals, years=2, width=920, height=380):
    series = (technicals or {}).get("series")
    if not series or len(series["dates"]) < 60:
        return None
    dates, closes = series["dates"], series["close"]
    sma50, sma200, volumes = series["sma50"], series["sma200"], series["volume"]

    cutoff = (dt.date.fromisoformat(dates[-1]) - dt.timedelta(days=int(365.25 * years))).isoformat()
    start = next((i for i, d in enumerate(dates) if d >= cutoff), 0)
    dates, closes = dates[start:], closes[start:]
    sma50, sma200, volumes = sma50[start:], sma200[start:], volumes[start:]

    pad = {"t": 14, "r": 58, "b": 26, "l": 8}
    vol_h = 52
    plot_h = height - pad["t"] - pad["b"] - vol_h - 10
    plot_w = width - pad["l"] - pad["r"]

    values = [c for c in closes] + [v for v in (sma50 + sma200) if v is not None]
    lo, hi = min(values) * 0.96, max(values) * 1.04
    log_lo, log_span = _log(lo), max(_log(hi) - _log(lo), 1e-9)
    first = dt.date.fromisoformat(dates[0]).toordinal()
    span = max(dt.date.fromisoformat(dates[-1]).toordinal() - first, 1)

    def x_of(d):
        return pad["l"] + plot_w * (dt.date.fromisoformat(d).toordinal() - first) / span

    def y_of(v):
        return pad["t"] + plot_h * (1 - (_log(v) - log_lo) / log_span)

    parts = []
    for tick in _log_ticks(lo, hi):
        y = y_of(tick)
        parts.append(f'<line class="g" x1="{pad["l"]}" y1="{y:.1f}" x2="{pad["l"]+plot_w}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tk" x="{pad["l"]+plot_w+6}" y="{y+3.5:.1f}">{_money(tick)}</text>')

    seen = set()
    for i, d in enumerate(dates):
        year = d[:4]
        if year in seen:
            continue
        seen.add(year)
        if i == 0:
            continue
        x = x_of(d)
        parts.append(f'<line class="g" x1="{x:.1f}" y1="{pad["t"]}" x2="{x:.1f}" y2="{pad["t"]+plot_h}"/>')
        parts.append(f'<text class="tk" x="{x:.1f}" y="{height-8}" text-anchor="middle">{year}</text>')

    # volume, scaled independently under the price panel
    vol_top = pad["t"] + plot_h + 10
    vmax = max(volumes) or 1
    bar_w = max(0.6, plot_w / max(len(dates), 1) * 0.8)
    bars = []
    for i, d in enumerate(dates):
        h = (volumes[i] / vmax) * vol_h
        if h < 0.4:
            continue
        rising = closes[i] >= (closes[i - 1] if i else closes[i])
        bars.append(f'<rect x="{x_of(d)-bar_w/2:.1f}" y="{vol_top+vol_h-h:.1f}" '
                    f'width="{bar_w:.1f}" height="{h:.1f}" '
                    f'fill="{GOOD if rising else BAD}" opacity="0.30"/>')
    parts.append("".join(bars))

    def path(values_list, css):
        points, started = [], False
        for i, d in enumerate(dates):
            v = values_list[i]
            if v is None:
                continue
            points.append(("M" if not started else "L") + f"{x_of(d):.1f},{y_of(v):.1f}")
            started = True
        return f'<path class="{css}" d="{" ".join(points)}"/>' if len(points) > 2 else ""

    parts.append(path(sma200, "ma200"))
    parts.append(path(sma50, "ma50"))
    parts.append(path(closes, "px"))

    last_x, last_y = x_of(dates[-1]), y_of(closes[-1])
    parts.append(f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3.5" class="dot-px"/>')
    return _svg("".join(parts), width, height, "Price with 50 and 200 day moving averages")


# --------------------------------------------------------------------------
# 2. Revenue / EPS history and forward estimates
# --------------------------------------------------------------------------

def estimates_chart(annual_rows, key="revenue", width=920, height=250):
    """Bars per fiscal year; reported solid, estimated hatched."""
    rows = [r for r in (annual_rows or [])
            if (r.get(f"{key}_actual") is not None or r.get(f"{key}_estimate") is not None)]
    if len(rows) < 4:
        return None
    rows = rows[-11:]

    values, labels, estimated = [], [], []
    for r in rows:
        reported = bool(r.get("reported"))
        value = r.get(f"{key}_actual") if reported else r.get(f"{key}_estimate")
        if value is None:
            value = r.get(f"{key}_estimate") if reported else None
        if value is None:
            continue
        values.append(float(value))
        labels.append(str(r.get("fiscal_period", ""))[:6])
        estimated.append(not reported)
    if len(values) < 4:
        return None

    pad = {"t": 16, "r": 56, "b": 30, "l": 8}
    plot_w = width - pad["l"] - pad["r"]
    plot_h = height - pad["t"] - pad["b"]
    hi = max(values) * 1.12
    lo = min(0, min(values) * 1.1)

    def y_of(v):
        return pad["t"] + plot_h * (1 - (v - lo) / max(hi - lo, 1e-9))

    parts = []
    for tick in _nice_ticks(lo, hi, 5):
        y = y_of(tick)
        parts.append(f'<line class="g" x1="{pad["l"]}" y1="{y:.1f}" x2="{pad["l"]+plot_w}" y2="{y:.1f}"/>')
        label = _money(tick * 1e6) if key == "revenue" else f"{tick:.2f}"
        parts.append(f'<text class="tk" x="{pad["l"]+plot_w+6}" y="{y+3.5:.1f}">{label}</text>')

    slot = plot_w / len(values)
    bar_w = slot * 0.62
    zero_y = y_of(max(lo, 0))
    for i, value in enumerate(values):
        x = pad["l"] + slot * i + (slot - bar_w) / 2
        y = y_of(value)
        top, h = min(y, zero_y), abs(zero_y - y)
        fill = SECOND if estimated[i] else PRICE
        opacity = "0.45" if estimated[i] else "1"
        parts.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{bar_w:.1f}" '
                     f'height="{max(h,1):.1f}" rx="3" fill="{fill}" opacity="{opacity}"/>')
        parts.append(f'<text class="tk" x="{x+bar_w/2:.1f}" y="{height-16}" '
                     f'text-anchor="middle">{labels[i]}</text>')
        if estimated[i]:
            parts.append(f'<text class="tk est" x="{x+bar_w/2:.1f}" y="{height-5}" '
                         f'text-anchor="middle">est</text>')
    return _svg("".join(parts), width, height,
                f"{key} by fiscal year, reported and estimated")


# --------------------------------------------------------------------------
# 3. Estimate revision trend — are analysts raising or cutting?
# --------------------------------------------------------------------------

def revisions_chart(rows, width=920, height=230):
    rows = [r for r in (rows or []) if r.get("date") and r.get("mean")]
    if len(rows) < 8:
        return None
    periods = sorted({r["fiscal_period"] for r in rows})
    pad = {"t": 16, "r": 58, "b": 26, "l": 8}
    plot_w = width - pad["l"] - pad["r"]
    plot_h = height - pad["t"] - pad["b"]

    dates = [dt.date.fromisoformat(r["date"][:10]).toordinal() for r in rows]
    first, last = min(dates), max(dates)
    span = max(last - first, 1)
    means = [float(r["mean"]) for r in rows]
    lo, hi = min(means) * 0.94, max(means) * 1.06

    def x_of(o):
        return pad["l"] + plot_w * (o - first) / span

    def y_of(v):
        return pad["t"] + plot_h * (1 - (v - lo) / max(hi - lo, 1e-9))

    parts = []
    for tick in _nice_ticks(lo, hi, 5):
        y = y_of(tick)
        parts.append(f'<line class="g" x1="{pad["l"]}" y1="{y:.1f}" x2="{pad["l"]+plot_w}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tk" x="{pad["l"]+plot_w+6}" y="{y+3.5:.1f}">{tick:.2f}</text>')

    colours = [PRICE, SECOND]
    for index, period in enumerate(periods):
        subset = [r for r in rows if r["fiscal_period"] == period]
        subset.sort(key=lambda r: r["date"])
        points = " ".join(
            f'{x_of(dt.date.fromisoformat(r["date"][:10]).toordinal()):.1f},'
            f'{y_of(float(r["mean"])):.1f}' for r in subset)
        parts.append(f'<polyline points="{points}" fill="none" '
                     f'stroke="{colours[index % 2]}" stroke-width="2" '
                     f'stroke-linejoin="round"/>')
        if subset:
            end = subset[-1]
            parts.append(
                f'<text class="tk lbl" x="{pad["l"]+plot_w+6}" '
                f'y="{y_of(float(end["mean"]))-6:.1f}" fill="{colours[index % 2]}">'
                f'{period}</text>')

    seen = set()
    for r in rows:
        year = r["date"][:4]
        if year in seen:
            continue
        seen.add(year)
        x = x_of(dt.date.fromisoformat(r["date"][:10]).toordinal())
        parts.append(f'<text class="tk" x="{x:.1f}" y="{height-6}" text-anchor="middle">{year}</text>')
    return _svg("".join(parts), width, height, "Consensus EPS estimate over time")


# --------------------------------------------------------------------------
# 4. Earnings reactions — surprise against the move
# --------------------------------------------------------------------------

def reactions_chart(reactions, width=920, height=210):
    rows = [r for r in (reactions or []) if r.get("day_pct") is not None]
    if len(rows) < 4:
        return None
    rows = list(reversed(rows))[-12:]
    pad = {"t": 18, "r": 52, "b": 30, "l": 8}
    plot_w = width - pad["l"] - pad["r"]
    plot_h = height - pad["t"] - pad["b"]
    moves = [float(r["day_pct"]) for r in rows]
    limit = max(abs(min(moves)), abs(max(moves))) * 1.2 or 1

    def y_of(v):
        return pad["t"] + plot_h * (1 - (v + limit) / (2 * limit))

    parts = []
    zero = y_of(0)
    for tick in _nice_ticks(-limit, limit, 4):
        y = y_of(tick)
        parts.append(f'<line class="g" x1="{pad["l"]}" y1="{y:.1f}" x2="{pad["l"]+plot_w}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tk" x="{pad["l"]+plot_w+6}" y="{y+3.5:.1f}">{tick:+.0f}%</text>')
    parts.append(f'<line x1="{pad["l"]}" y1="{zero:.1f}" x2="{pad["l"]+plot_w}" '
                 f'y2="{zero:.1f}" stroke="{MUTED}" stroke-width="1"/>')

    slot = plot_w / len(rows)
    bar_w = slot * 0.55
    for i, r in enumerate(rows):
        move = float(r["day_pct"])
        x = pad["l"] + slot * i + (slot - bar_w) / 2
        y = y_of(move)
        top, h = min(y, zero), abs(zero - y)
        parts.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{bar_w:.1f}" '
                     f'height="{max(h,1):.1f}" rx="2.5" '
                     f'fill="{GOOD if move >= 0 else BAD}"/>')
        label = str(r.get("fiscal_period") or "")[-4:]
        parts.append(f'<text class="tk" x="{x+bar_w/2:.1f}" y="{height-16}" '
                     f'text-anchor="middle">{label}</text>')
        surprise = r.get("eps_surprise_pct")
        if surprise is not None:
            parts.append(f'<text class="tk est" x="{x+bar_w/2:.1f}" y="{height-5}" '
                         f'text-anchor="middle">{float(surprise):+.0f}%</text>')
    return _svg("".join(parts), width, height,
                "Share price move on each earnings day, with EPS surprise")


# --------------------------------------------------------------------------
# 5. Fair-value line, redrawn in the dashboard's own language
# --------------------------------------------------------------------------

def fair_value_chart(fair_value, width=920, height=320):
    series = (fair_value or {}).get("series") or []
    stats = (fair_value or {}).get("stats") or {}
    normal = (fair_value or {}).get("normal_adjusted")
    if len(series) < 20 or not normal or not stats.get("p_low"):
        return None
    factor = ((fair_value.get("growth") or {}).get("factor")) or 1.0
    low, high = stats["p_low"] * factor, stats["p_high"] * factor

    rows = []
    for r in series:
        try:
            eps = float(r["ttm_eps"]) if r.get("ttm_eps") else None
            price = float(r["price"])
        except (TypeError, ValueError):
            continue
        if not eps or eps <= 0:
            continue
        rows.append({"d": r["date"], "p": price, "fv": normal * eps,
                     "lo": low * eps, "hi": high * eps})
    if len(rows) < 20:
        return None

    pad = {"t": 14, "r": 58, "b": 26, "l": 8}
    plot_w = width - pad["l"] - pad["r"]
    plot_h = height - pad["t"] - pad["b"]
    values = [r["p"] for r in rows] + [r["lo"] for r in rows] + [r["hi"] for r in rows]
    lo_v, hi_v = min(values) * 0.9, max(values) * 1.1
    log_lo, log_span = _log(lo_v), max(_log(hi_v) - _log(lo_v), 1e-9)
    first = dt.date.fromisoformat(rows[0]["d"]).toordinal()
    span = max(dt.date.fromisoformat(rows[-1]["d"]).toordinal() - first, 1)

    def x_of(d):
        return pad["l"] + plot_w * (dt.date.fromisoformat(d).toordinal() - first) / span

    def y_of(v):
        return pad["t"] + plot_h * (1 - (_log(v) - log_lo) / log_span)

    parts = []
    for tick in _log_ticks(lo_v, hi_v):
        y = y_of(tick)
        parts.append(f'<line class="g" x1="{pad["l"]}" y1="{y:.1f}" x2="{pad["l"]+plot_w}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tk" x="{pad["l"]+plot_w+6}" y="{y+3.5:.1f}">{_money(tick)}</text>')
    seen = set()
    for r in rows:
        year = r["d"][:4]
        if year in seen:
            continue
        seen.add(year)
        x = x_of(r["d"])
        parts.append(f'<line class="g" x1="{x:.1f}" y1="{pad["t"]}" x2="{x:.1f}" y2="{pad["t"]+plot_h}"/>')
        parts.append(f'<text class="tk" x="{x:.1f}" y="{height-6}" text-anchor="middle">{year}</text>')

    upper = " ".join(f'{x_of(r["d"]):.1f},{y_of(r["hi"]):.1f}' for r in rows)
    lower = " ".join(f'{x_of(r["d"]):.1f},{y_of(r["lo"]):.1f}' for r in reversed(rows))
    parts.append(f'<polygon points="{upper} {lower}" class="band"/>')

    fair, previous = [], None
    for r in rows:
        x, y = x_of(r["d"]), y_of(r["fv"])
        if previous is None:
            fair.append(f"M{x:.1f},{y:.1f}")
        elif abs(y - previous) > 0.01:
            fair.append(f"L{x:.1f},{previous:.1f} L{x:.1f},{y:.1f}")
        else:
            fair.append(f"L{x:.1f},{y:.1f}")
        previous = y
    parts.append(f'<path class="fv" d="{" ".join(fair)}"/>')
    parts.append('<path class="px" d="M' +
                 " L".join(f'{x_of(r["d"]):.1f},{y_of(r["p"]):.1f}' for r in rows) + '"/>')
    return _svg("".join(parts), width, height,
                "Price against the normal-multiple fair value line")


# --------------------------------------------------------------------------
# 6. Scorecard — the rating, made visible
# --------------------------------------------------------------------------

def scorecard_chart(scorecard, width=920, row_h=30):
    rows = [r for r in (scorecard or []) if r.get("score") is not None]
    if not rows:
        return None
    height = len(rows) * row_h + 34
    label_w, bar_w = 210, 320
    centre = label_w + bar_w / 2
    parts = [f'<line x1="{centre}" y1="16" x2="{centre}" y2="{height-14}" '
             f'stroke="{MUTED}" stroke-width="1" stroke-dasharray="2 3"/>']
    for i, r in enumerate(rows):
        y = 24 + i * row_h
        score = max(-2.0, min(2.0, float(r["score"])))
        weight = float(r.get("weight") or 0)
        length = (abs(score) / 2) * (bar_w / 2)
        x = centre if score >= 0 else centre - length
        colour = GOOD if score > 0 else (BAD if score < 0 else MUTED)
        parts.append(f'<text class="sc-lbl" x="0" y="{y+4}">{r["dimension"]}</text>')
        parts.append(f'<rect x="{x:.1f}" y="{y-7}" width="{max(length,2):.1f}" '
                     f'height="14" rx="3" fill="{colour}" opacity="0.85"/>')
        parts.append(f'<text class="sc-num" x="{label_w+bar_w+12}" y="{y+4}">'
                     f'{score:+.1f}</text>')
        if weight:
            parts.append(f'<text class="sc-wt" x="{label_w+bar_w+56}" y="{y+4}">'
                         f'{weight*100:.0f}%</text>')
    for value, dx in ((-2, -bar_w / 2), (0, 0), (2, bar_w / 2)):
        parts.append(f'<text class="sc-wt" x="{centre+dx:.0f}" y="{height-2}" '
                     f'text-anchor="middle">{value:+d}</text>')
    return _svg("".join(parts), width, height, "Scorecard by dimension")
