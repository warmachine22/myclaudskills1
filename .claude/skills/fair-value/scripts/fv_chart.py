"""Self-contained HTML chart: price against the normal-multiple fair-value line.

Inline SVG generated here in Python — no chart library, no CDN, no fonts, no
network. One small inline script adds a hover crosshair; everything the chart
says is legible with JavaScript disabled.

Colours are the dataviz reference palette, slots 1 and 2, validated for both
modes (worst adjacent CVD dE 24.7 light / 26.8 dark).

The y-axis is logarithmic. Over ten years a compounder's price can move two
orders of magnitude, and on a linear axis the entire early history collapses
onto the baseline — the years where the stock was cheapest become invisible.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import math

W, H = 960, 460
PAD = {"top": 28, "right": 96, "bottom": 40, "left": 62}
PLOT_W = W - PAD["left"] - PAD["right"]
PLOT_H = H - PAD["top"] - PAD["bottom"]


def _log(value):
    return math.log10(max(value, 1e-6))


def _nice_log_ticks(lo, hi, limit=9):
    """Decade ticks, thinned by dropping mantissas rather than every other tick.

    Subsampling a 1-2-5 ladder with a stride produces 1, 5, 20, 100 — which reads
    as an irregular axis. Dropping whole mantissa classes keeps it a ladder.
    """
    def ladder(mantissas):
        out = []
        exponent = math.floor(_log(lo))
        while exponent <= math.ceil(_log(hi)):
            for mantissa in mantissas:
                value = mantissa * (10 ** exponent)
                if lo <= value <= hi:
                    out.append(value)
            exponent += 1
        return out

    # Coarse to fine; keep the densest ladder that still fits. A range inside one
    # decade (a mature stock over ten years) needs the fine ladder or it gets a
    # single tick.
    ladders = ((1,), (1, 5), (1, 2, 5), (1, 2, 3, 5, 7),
               (1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9))
    best = ladder(ladders[0])
    for mantissas in ladders:
        ticks = ladder(mantissas)
        if 0 < len(ticks) <= limit:
            best = ticks
    return best


def _fmt_price(value):
    if value >= 1000:
        return f"${value:,.0f}"
    if value >= 10:
        return f"${value:.0f}"
    if value >= 1:
        return f"${value:.1f}"
    return f"${value:.2f}"


def build_svg(report):
    observations = report["window_observations"]
    points = [o for o in observations if o.multiple is not None and o.eps and o.eps > 0]
    if len(points) < 10:
        return None, []

    stats = report["stats"]
    factor = report["growth"]["factor"]
    normal = report["normal_adjusted"]
    low = stats["p_low"] * factor
    high = stats["p_high"] * factor

    rows = []
    for o in points:
        rows.append({
            "d": o.date.isoformat(), "p": o.price, "e": o.eps,
            "m": o.multiple, "fv": normal * o.eps,
            "lo": low * o.eps, "hi": high * o.eps,
        })

    values = [r["p"] for r in rows] + [r["lo"] for r in rows] + [r["hi"] for r in rows]
    y_min, y_max = min(values), max(values)
    y_min, y_max = y_min * 0.88, y_max * 1.12

    start = points[0].date.toordinal()
    span = max(points[-1].date.toordinal() - start, 1)
    log_min, log_max = _log(y_min), _log(y_max)
    log_span = max(log_max - log_min, 1e-9)

    def x_of(date):
        return PAD["left"] + PLOT_W * (date.toordinal() - start) / span

    def y_of(value):
        return PAD["top"] + PLOT_H * (1 - (_log(value) - log_min) / log_span)

    for row, o in zip(rows, points):
        row["x"] = round(x_of(o.date), 2)
        row["y"] = round(y_of(o.price), 2)

    parts = []
    add = parts.append

    # --- gridlines and y axis ---------------------------------------------
    for tick in _nice_log_ticks(y_min, y_max):
        y = y_of(tick)
        add(f'<line class="grid" x1="{PAD["left"]}" y1="{y:.1f}" '
            f'x2="{PAD["left"] + PLOT_W}" y2="{y:.1f}"/>')
        add(f'<text class="tick" x="{PAD["left"] - 8}" y="{y + 3.5:.1f}" '
            f'text-anchor="end">{_fmt_price(tick)}</text>')

    # --- x axis: one tick per calendar year --------------------------------
    years = sorted({o.date.year for o in points})
    stride = max(1, len(years) // 9)
    for year in years[::stride]:
        first = next((o.date for o in points if o.date.year == year), None)
        if not first:
            continue
        x = x_of(first)
        add(f'<line class="grid" x1="{x:.1f}" y1="{PAD["top"]}" x2="{x:.1f}" '
            f'y2="{PAD["top"] + PLOT_H}"/>')
        add(f'<text class="tick" x="{x:.1f}" y="{PAD["top"] + PLOT_H + 18}" '
            f'text-anchor="middle">{year}</text>')

    # --- the band, drawn first so lines sit on top -------------------------
    upper = " ".join(f"{x_of(o.date):.1f},{y_of(r['hi']):.1f}"
                     for o, r in zip(points, rows))
    lower = " ".join(f"{x_of(o.date):.1f},{y_of(r['lo']):.1f}"
                     for o, r in reversed(list(zip(points, rows))))
    add(f'<polygon class="band" points="{upper} {lower}"/>')

    # --- fair-value line: steps at earnings, so draw it stepped ------------
    fair_path = []
    previous = None
    for o, r in zip(points, rows):
        x, y = x_of(o.date), y_of(r["fv"])
        if previous is None:
            fair_path.append(f"M{x:.1f},{y:.1f}")
        elif abs(y - previous) > 0.01:
            fair_path.append(f"L{x:.1f},{previous:.1f} L{x:.1f},{y:.1f}")
        else:
            fair_path.append(f"L{x:.1f},{y:.1f}")
        previous = y
    add(f'<path class="fair" d="{" ".join(fair_path)}"/>')

    price_path = "M" + " L".join(f"{r['x']},{r['y']}" for r in rows)
    add(f'<path class="price" d="{price_path}"/>')

    # --- direct labels at the right edge -----------------------------------
    last = rows[-1]
    label_x = PAD["left"] + PLOT_W + 8
    add(f'<circle class="dot price-dot" cx="{last["x"]}" cy="{last["y"]}" r="4.5"/>')
    add(f'<text class="label price-ink" x="{label_x}" y="{last["y"] + 4:.1f}">Price</text>')
    fair_y = y_of(last["fv"])
    if abs(fair_y - last["y"]) < 14:
        fair_y += 15 if fair_y >= last["y"] else -15
    add(f'<circle class="dot fair-dot" cx="{last["x"]}" cy="{y_of(last["fv"]):.1f}" r="4.5"/>')
    add(f'<text class="label fair-ink" x="{label_x}" y="{fair_y + 4:.1f}">Fair value</text>')

    # --- hover layer (progressive enhancement) -----------------------------
    add(f'<g id="cross" style="display:none">'
        f'<line id="cx" class="cross" y1="{PAD["top"]}" y2="{PAD["top"] + PLOT_H}"/>'
        f'<circle id="cp" class="dot price-dot" r="5"/>'
        f'<circle id="cf" class="dot fair-dot" r="5"/></g>')
    add(f'<rect id="hit" x="{PAD["left"]}" y="{PAD["top"]}" width="{PLOT_W}" '
        f'height="{PLOT_H}" fill="transparent"/>')

    svg = (f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" '
           f'aria-label="Price against the normal-multiple fair value line" '
           f'preserveAspectRatio="xMidYMid meet">' + "".join(parts) + "</svg>")
    return svg, rows


CSS = """
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--page);color:var(--ink);
  font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1040px;margin:0 auto}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;
  padding:20px 22px}
h1{font-size:19px;margin:0 0 2px;font-weight:650}
.sub{color:var(--ink-2);font-size:13px;margin:0 0 4px}
.muted{color:var(--muted);font-size:12px}
.figs{display:flex;flex-wrap:wrap;gap:26px;margin:16px 0 6px;
  padding-bottom:16px;border-bottom:1px solid var(--border)}
.fig .k{color:var(--muted);font-size:11px;text-transform:uppercase;
  letter-spacing:.05em}
.fig .v{font-size:22px;font-weight:600;margin-top:2px}
.legend{display:flex;gap:18px;align-items:center;margin:12px 0 0;font-size:13px;
  color:var(--ink-2);flex-wrap:wrap}
.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;
  margin-right:7px;vertical-align:middle}
.legend .sw-band{height:11px;border-radius:3px;background:var(--band);
  border:1px solid var(--fair)}
.chart{position:relative;margin-top:10px;overflow-x:auto}
.grid{stroke:var(--grid);stroke-width:1}
.tick{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.band{fill:var(--band);stroke:none}
.fair{fill:none;stroke:var(--fair);stroke-width:2;stroke-linejoin:round}
.price{fill:none;stroke:var(--price);stroke-width:2;stroke-linejoin:round;
  stroke-linecap:round}
.dot{stroke:var(--surface);stroke-width:2}
.price-dot{fill:var(--price)} .fair-dot{fill:var(--fair)}
.label{font-size:12px;font-weight:600}
.price-ink{fill:var(--price)} .fair-ink{fill:var(--fair)}
.cross{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3}
#tip{position:absolute;pointer-events:none;display:none;background:var(--surface);
  border:1px solid var(--border);border-radius:7px;padding:8px 10px;font-size:12px;
  box-shadow:0 4px 14px rgba(0,0,0,.14);min-width:150px;z-index:5}
#tip b{display:block;margin-bottom:4px;font-size:12px}
#tip .r{display:flex;justify-content:space-between;gap:14px;
  font-variant-numeric:tabular-nums}
#tip .r span:first-child{color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}
th,td{text-align:right;padding:5px 8px;border-bottom:1px solid var(--border);
  font-variant-numeric:tabular-nums}
th:first-child,td:first-child{text-align:left}
th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;
  letter-spacing:.04em}
details{margin-top:18px} summary{cursor:pointer;color:var(--ink-2);font-size:13px}
.note{margin-top:16px;color:var(--ink-2);font-size:12.5px;line-height:1.6}
.warn{margin-top:14px;padding:10px 12px;border-radius:7px;font-size:12.5px;
  background:var(--warn-bg);border:1px solid var(--warn-br);color:var(--ink)}
.warn ul{margin:6px 0 0;padding-left:18px} .warn li{margin:3px 0}
"""

THEME_LIGHT = """
--page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink-2:#52514e;
--muted:#898781; --grid:#e1e0d9; --border:rgba(11,11,11,.10);
--price:#2a78d6; --fair:#eb6834; --band:rgba(235,104,52,.13);
--warn-bg:rgba(250,178,25,.10); --warn-br:rgba(250,178,25,.45);
"""

THEME_DARK = """
--page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink-2:#c3c2b7;
--muted:#898781; --grid:#2c2c2a; --border:rgba(255,255,255,.10);
--price:#3987e5; --fair:#d95926; --band:rgba(217,89,38,.20);
--warn-bg:rgba(250,178,25,.10); --warn-br:rgba(250,178,25,.40);
"""

SCRIPT = """
(function(){
  var data=JSON.parse(document.getElementById('pts').textContent);
  var svg=document.querySelector('svg'), hit=document.getElementById('hit'),
      g=document.getElementById('cross'), cx=document.getElementById('cx'),
      cp=document.getElementById('cp'), cf=document.getElementById('cf'),
      tip=document.getElementById('tip'), box=document.querySelector('.chart');
  if(!svg||!hit||!data.length) return;
  function money(v){return '$'+(v>=1000?v.toLocaleString(undefined,{maximumFractionDigits:0})
    :v>=10?v.toFixed(0):v.toFixed(2));}
  function move(ev){
    var r=svg.getBoundingClientRect(), vb=svg.viewBox.baseVal,
        ux=(ev.clientX-r.left)*(vb.width/r.width), best=0, bd=1e9;
    for(var i=0;i<data.length;i++){var d=Math.abs(data[i].x-ux); if(d<bd){bd=d;best=i;}}
    var p=data[best];
    g.style.display=''; cx.setAttribute('x1',p.x); cx.setAttribute('x2',p.x);
    cp.setAttribute('cx',p.x); cp.setAttribute('cy',p.y);
    cf.setAttribute('cx',p.x); cf.setAttribute('cy',p.fvy);
    var prem=(p.p/p.fv-1)*100;
    tip.innerHTML='<b>'+p.d+'</b>'
      +'<div class="r"><span>Price</span><span>'+money(p.p)+'</span></div>'
      +'<div class="r"><span>Fair value</span><span>'+money(p.fv)+'</span></div>'
      +'<div class="r"><span>Premium</span><span>'+(prem>=0?'+':'')+prem.toFixed(0)+'%</span></div>'
      +'<div class="r"><span>Multiple</span><span>'+p.m.toFixed(1)+'x</span></div>';
    tip.style.display='block';
    var bx=box.getBoundingClientRect(), scale=bx.width/vb.width,
        left=p.x*scale+14, tw=tip.offsetWidth;
    if(left+tw>bx.width) left=p.x*scale-tw-14;
    tip.style.left=Math.max(0,left)+'px';
    tip.style.top=Math.max(0,p.y*scale-10)+'px';
  }
  hit.addEventListener('mousemove',move);
  hit.addEventListener('touchmove',function(e){if(e.touches[0])move(e.touches[0]);},
    {passive:true});
  box.addEventListener('mouseleave',function(){g.style.display='none';
    tip.style.display='none';});
})();
"""


def write_chart(report, path):
    svg, rows = build_svg(report)
    if not svg:
        raise ValueError("not enough usable observations to draw a chart")

    metric = "P/E" if report["metric"] == "pe" else "P/S"
    esc = html.escape
    ticker = esc(report["ticker"])
    company = esc(report["company"] or "")
    window = report["headline_window"]

    # Only the fields the hover needs; keeps the payload small.
    log_rows = []
    for row in rows:
        log_rows.append({"d": row["d"], "x": row["x"], "y": row["y"],
                         "p": round(row["p"], 2), "fv": round(row["fv"], 2),
                         "m": round(row["m"], 2), "fvy": 0})
    # fvy is the y pixel of the fair-value line at that x
    band_scale = build_svg  # keep reference readable; recompute below
    for row, source in zip(log_rows, rows):
        row["fvy"] = _fv_y(report, source)

    premium = report["premium"]
    figures = [
        ("Price", _fmt_price(report["price"])),
        (f"Normal {metric}", f"{report['normal_adjusted']:.1f}x"),
        ("Fair value", _fmt_price(report["fair_value"]) if report["fair_value"] else "—"),
        ("Premium / discount", f"{premium * 100:+.0f}%" if premium is not None else "—"),
    ]
    figures_html = "".join(
        f'<div class="fig"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>'
        for k, v in figures)

    warns = [f for f in report["flags"] if f["severity"] in ("warn", "refuse")]
    warn_html = ""
    if warns:
        items = "".join(f"<li>{esc(f['detail'])}</li>" for f in warns)
        warn_html = (f'<div class="warn"><strong>{len(warns)} caveat'
                     f'{"" if len(warns) == 1 else "s"} on this valuation</strong>'
                     f'<ul>{items}</ul></div>')

    table_rows = "".join(
        f"<tr><td>{esc(str(row['label']))}</td><td>{_fmt_price(row['price'])}</td>"
        f"<td>{row['eps']:.2f}</td>"
        f"<td>{row['multiple']:.1f}x</td>"
        f"<td>{_fmt_price(row['fair_value'])}</td>"
        f"<td>{row['premium'] * 100:+.0f}%</td></tr>"
        for row in report["year_table"] if row["multiple"] and row["fair_value"])

    estimate = report["headline_estimate"]
    basis = esc(report["basis_label"])
    subtitle = (f"{metric} fair value at its own {window}"
                f"{'y' if str(window) != 'max' else ''} normal multiple")

    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{ticker} — normal-multiple fair value</title>
<style>
:root{{color-scheme:light dark;{THEME_LIGHT}}}
@media (prefers-color-scheme: dark){{:root:where(:not([data-theme="light"])){{{THEME_DARK}}}}}
:root[data-theme="dark"]{{{THEME_DARK}}}
:root[data-theme="light"]{{{THEME_LIGHT}}}
{CSS}
</style></head><body>
<div class="wrap"><div class="card">
  <h1>{ticker}{f" — {company}" if company else ""}</h1>
  <p class="sub">{esc(subtitle)} · {basis} earnings</p>
  <div class="figs">{figures_html}</div>
  <div class="legend">
    <span><i style="background:var(--price)"></i>Weekly close</span>
    <span><i style="background:var(--fair)"></i>Fair value
      ({report['normal_adjusted']:.1f}x x trailing {'EPS' if report['metric'] == 'pe' else 'revenue/share'})</span>
    <span><i class="sw-band"></i>Bear–bull band
      ({report['grid']['multiples']['bear']:.1f}x–{report['grid']['multiples']['bull']:.1f}x)</span>
  </div>
  <div class="chart">{svg}<div id="tip"></div></div>
  <p class="muted">Log scale — on a linear axis a decade of compounding flattens the
    early years, which is exactly where the stock was cheapest.</p>
  {warn_html}
  <details><summary>Year-end table</summary>
    <table><thead><tr><th>Year</th><th>Price</th>
      <th>{'TTM EPS' if report['metric'] == 'pe' else 'TTM rev/sh'}</th>
      <th>{metric}</th><th>Fair value</th><th>Prem/disc</th></tr></thead>
      <tbody>{table_rows}</tbody></table></details>
  <p class="note">
    Fair value = the stock's own {window}{'y' if str(window) != 'max' else ''} median
    {metric} (growth-adjusted where shown) x its trailing-twelve-month
    {'earnings' if report['metric'] == 'pe' else 'revenue per share'}, plotted through
    time. { "Forward estimate: " + esc(str(estimate['period'])) + " at "
            + f"{estimate['eps']:.2f}" + " from "
            + str(estimate['analysts'] or 0) + " analysts." if estimate else "" }
    Each week uses the most recent figure as of its earnings announcement, so the
    line never knows a result before it was published. Prices are split-adjusted
    closes. This is one valuation lens among several, and it assumes the past
    multiple is a reasonable anchor for the future — the caveats above are the
    tests of that assumption. Not advice.
  </p>
</div></div>
<script type="application/json" id="pts">{json.dumps(log_rows)}</script>
<script>{SCRIPT}</script>
</body></html>"""

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(document)
    return path


def _fv_y(report, row):
    """Recover the fair-value line's pixel y for the hover marker."""
    observations = [o for o in report["window_observations"]
                    if o.multiple is not None and o.eps and o.eps > 0]
    stats, factor = report["stats"], report["growth"]["factor"]
    low = stats["p_low"] * factor
    high = stats["p_high"] * factor
    values = []
    for o in observations:
        values += [o.price, low * o.eps, high * o.eps]
    y_min, y_max = min(values) * 0.88, max(values) * 1.12
    log_min, log_span = _log(y_min), max(_log(y_max) - _log(y_min), 1e-9)
    return round(PAD["top"] + PLOT_H * (1 - (_log(row["fv"]) - log_min) / log_span), 2)
