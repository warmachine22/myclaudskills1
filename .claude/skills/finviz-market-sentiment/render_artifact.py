#!/usr/bin/env python3
"""Render a finviz-sentiment report as a self-contained HTML dashboard.

The output is published as an Artifact and REDEPLOYED TO THE SAME URL on every
scheduled run, so one link always shows the latest reading.

Self-contained by necessity: the Artifact CSP blocks every external host, so
there are no font CDNs, no external CSS, no remote images. Theme-aware in both
directions - prefers-color-scheme sets the default, and the viewer's toggle
stamps data-theme on the root, which must win.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime

TITLE = "Market Sentiment Monitor"


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def fmt_when(iso: str) -> tuple[str, str]:
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%a %b %-d, %Y").replace(" 0", " "), dt.strftime("%-I:%M %p").lstrip("0")
    except Exception:
        try:
            dt = datetime.fromisoformat(iso)
            return dt.strftime("%a %b %d, %Y"), dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            return iso[:10], iso[11:16]


# Shared design tokens. history.py imports these so both artifacts stay one
# visual system instead of drifting apart.
TOKENS = """
:root{
  --paper:#EDEFF2; --card:#F7F8FA; --ink:#131A24; --muted:#5C6875; --faint:#8A95A1;
  --rule:#D2D8DF; --accent:#3A5C7D; --accent-soft:#E2E9F1;
  --bull:#1B7F5A; --bear:#B4362F; --warn:#8A6D2F;
  --bull-soft:#DCEFE6; --bear-soft:#F7E0DE; --warn-soft:#F5EBD6;
  --shadow:0 1px 2px rgba(19,26,36,.06),0 4px 16px rgba(19,26,36,.05);
}
@media (prefers-color-scheme:dark){
  :root{
    --paper:#0E1319; --card:#161D26; --ink:#E4E9EF; --muted:#96A3B2; --faint:#6B7887;
    --rule:#242E3A; --accent:#7FA8CE; --accent-soft:#1B2735;
    --bull:#42C08D; --bear:#F0736A; --warn:#D9AC5B;
    --bull-soft:#12291F; --bear-soft:#2C1715; --warn-soft:#2A2115;
    --shadow:0 1px 2px rgba(0,0,0,.3),0 4px 16px rgba(0,0,0,.25);
  }
}
:root[data-theme="dark"]{
  --paper:#0E1319; --card:#161D26; --ink:#E4E9EF; --muted:#96A3B2; --faint:#6B7887;
  --rule:#242E3A; --accent:#7FA8CE; --accent-soft:#1B2735;
  --bull:#42C08D; --bear:#F0736A; --warn:#D9AC5B;
  --bull-soft:#12291F; --bear-soft:#2C1715; --warn-soft:#2A2115;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 4px 16px rgba(0,0,0,.25);
}
:root[data-theme="light"]{
  --paper:#EDEFF2; --card:#F7F8FA; --ink:#131A24; --muted:#5C6875; --faint:#8A95A1;
  --rule:#D2D8DF; --accent:#3A5C7D; --accent-soft:#E2E9F1;
  --bull:#1B7F5A; --bear:#B4362F; --warn:#8A6D2F;
  --bull-soft:#DCEFE6; --bear-soft:#F7E0DE; --warn-soft:#F5EBD6;
  --shadow:0 1px 2px rgba(19,26,36,.06),0 4px 16px rgba(19,26,36,.05);
}
"""

CSS = TOKENS + """
*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  font-size:15px; line-height:1.55; -webkit-font-smoothing:antialiased;
}
.mono{font-family:ui-monospace,"SF Mono","Cascadia Mono","Segoe UI Mono",Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums;}
.wrap{max-width:60rem;margin:0 auto;padding:1.75rem 1.25rem 4rem;display:flex;flex-direction:column;gap:1.5rem}

/* status bar */
.status{display:flex;flex-wrap:wrap;align-items:baseline;gap:.5rem 1rem;
  padding-bottom:.9rem;border-bottom:1px solid var(--rule)}
.status h1{margin:0;font-size:.95rem;font-weight:650;letter-spacing:.01em}
.run-tag{font-size:.7rem;font-weight:650;letter-spacing:.09em;text-transform:uppercase;
  color:var(--accent);background:var(--accent-soft);padding:.2rem .5rem;border-radius:3px}
.stamp{margin-left:auto;font-size:.78rem;color:var(--muted)}

/* verdict */
.verdict{background:var(--card);border:1px solid var(--rule);border-radius:8px;
  box-shadow:var(--shadow);overflow:hidden}
.verdict-stripe{height:4px}
.verdict-body{padding:1.4rem 1.5rem 1.5rem;display:flex;flex-wrap:wrap;gap:1.5rem 2.5rem;align-items:flex-start}
.signal-block{display:flex;flex-direction:column;gap:.15rem}
.signal{font-size:3.2rem;line-height:1;font-weight:700;letter-spacing:-.02em}
.conviction{font-size:.76rem;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);font-weight:600}
.index-block{display:flex;flex-direction:column;gap:.15rem;min-width:9rem}
.index-val{font-size:2.1rem;line-height:1.1;font-weight:600}
.index-val .of{font-size:.95rem;color:var(--faint);font-weight:400}
.lbl{font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);font-weight:650}

/* gauge */
.gauge{flex:1 1 16rem;min-width:14rem;display:flex;flex-direction:column;gap:.45rem}
.gauge-track{position:relative;height:12px;border-radius:6px;
  background:linear-gradient(90deg,var(--bear) 0%,var(--rule) 50%,var(--bull) 100%);opacity:.85}
.gauge-mid{position:absolute;left:50%;top:-4px;bottom:-4px;width:1px;background:var(--ink);opacity:.45}
.gauge-pin{position:absolute;top:-5px;width:3px;height:22px;border-radius:2px;background:var(--ink);
  transform:translateX(-1.5px)}
.gauge-ends{display:flex;justify-content:space-between;font-size:.66rem;color:var(--faint);letter-spacing:.06em}

/* mass bar */
.mass{display:flex;flex-direction:column;gap:.4rem}
.mass-bar{display:flex;height:9px;border-radius:5px;overflow:hidden;background:var(--rule)}
.mass-bar span{display:block}
.mass-key{display:flex;flex-wrap:wrap;gap:.35rem 1.1rem;font-size:.75rem;color:var(--muted)}
.dot{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:.35rem;vertical-align:baseline}

/* flags */
.flag{display:flex;gap:.6rem;padding:.7rem .9rem;border-radius:6px;font-size:.82rem;line-height:1.45;
  border:1px solid transparent}
.flag.warn{background:var(--warn-soft);border-color:var(--warn);color:var(--ink)}
.flag b{font-weight:650}

/* sections */
h2{margin:0 0 .7rem;font-size:.72rem;letter-spacing:.11em;text-transform:uppercase;
  color:var(--faint);font-weight:650}
section{display:flex;flex-direction:column}

/* picks */
.picks{display:flex;flex-direction:column;gap:.7rem}
.pick{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--bull);
  border-radius:6px;padding:.9rem 1rem;display:flex;flex-direction:column;gap:.45rem}
.pick-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:.55rem}
.tick{font-size:1.15rem;font-weight:700;letter-spacing:.01em}
.pick-name{font-size:.85rem;color:var(--muted)}
.pick-score{margin-left:auto;font-size:.85rem;font-weight:650;color:var(--bull)}
.metrics{display:flex;flex-wrap:wrap;gap:.3rem .9rem;font-size:.74rem;color:var(--muted)}
.metrics b{color:var(--ink);font-weight:600}
.chips{display:flex;flex-wrap:wrap;gap:.3rem}
.chip{font-size:.68rem;letter-spacing:.03em;padding:.15rem .45rem;border-radius:3px;
  background:var(--accent-soft);color:var(--accent);font-weight:600}
.chip.same{background:transparent;border:1px dashed var(--rule);color:var(--faint)}
.caveat{font-size:.76rem;color:var(--muted);padding-left:.85rem;position:relative;line-height:1.45}
.caveat::before{content:"!";position:absolute;left:0;color:var(--warn);font-weight:700}

/* held state */
.held{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--muted);
  border-radius:6px;padding:1.1rem 1.15rem;display:flex;flex-direction:column;gap:.4rem}
.held-title{font-size:1rem;font-weight:650;letter-spacing:.01em}
.held-why{font-size:.85rem;color:var(--muted);line-height:1.5}

/* drivers */
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(17rem,1fr));gap:1.25rem}
.drv{display:flex;flex-direction:column;gap:.5rem}
.row{display:flex;flex-direction:column;gap:.28rem}
.row-top{display:flex;gap:.6rem;align-items:baseline}
.row-txt{font-size:.83rem;line-height:1.4}
.row-num{margin-left:auto;font-size:.73rem;font-weight:650;white-space:nowrap}
.row-bar{height:3px;border-radius:2px}
.meta{font-size:.68rem;color:var(--faint);letter-spacing:.04em}

/* method */
details{background:var(--card);border:1px solid var(--rule);border-radius:6px;padding:.75rem .95rem}
summary{cursor:pointer;font-size:.75rem;letter-spacing:.09em;text-transform:uppercase;
  color:var(--faint);font-weight:650}
summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:3px}
details[open] summary{margin-bottom:.7rem}
.method-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));gap:.9rem;font-size:.79rem;
  color:var(--muted);line-height:1.5}
.method-grid b{color:var(--ink);font-weight:600;display:block;font-size:.72rem;letter-spacing:.06em;
  text-transform:uppercase;margin-bottom:.15rem}
code{font-family:ui-monospace,"SF Mono","Cascadia Mono",Menlo,Consolas,monospace;font-size:.94em;
  background:var(--accent-soft);padding:.05rem .3rem;border-radius:3px}
.disc{font-size:.75rem;color:var(--faint);line-height:1.55;border-top:1px solid var(--rule);padding-top:1rem}
.scroll{overflow-x:auto}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media (max-width:34rem){
  .signal{font-size:2.5rem}
  .verdict-body{padding:1.1rem 1.1rem 1.25rem;gap:1.1rem}
}
"""


def render(report: dict, run_label: str) -> str:
    ind = report["indicator"]
    agg = report["aggregate"]
    counts = report["counts"]
    rec = report.get("recommendation", {}) or {}
    w = report.get("weighting", {})

    bullish = ind["signal"] == "BUY"
    tone = "var(--bull)" if bullish else "var(--bear)"
    day, clock = fmt_when(report.get("generated_at", ""))
    idx = float(ind["index"])
    pin = max(0.0, min(100.0, idx))

    bull_pct = agg["bullish_share"] * 100
    bear_pct = agg["bearish_share"] * 100
    neut_pct = agg["neutral_share"] * 100

    P: list[str] = []
    P.append(f"<title>{esc(TITLE)}</title>")
    P.append(f"<style>{CSS}</style>")
    P.append('<div class="wrap">')

    # status bar
    P.append('<div class="status">')
    P.append(f'<h1>{esc(TITLE)}</h1>')
    P.append(f'<span class="run-tag">{esc(run_label)}</span>')
    P.append(f'<span class="stamp mono">{esc(day)} &middot; {esc(clock)} ET</span>')
    P.append("</div>")

    # verdict
    P.append('<div class="verdict">')
    P.append(f'<div class="verdict-stripe" style="background:{tone}"></div>')
    P.append('<div class="verdict-body">')
    P.append('<div class="signal-block">')
    P.append(f'<div class="signal" style="color:{tone}">{esc(ind["signal"])}</div>')
    P.append(f'<div class="conviction">{esc(ind["conviction"])} conviction &middot; {esc(ind["horizon"])}</div>')
    P.append("</div>")
    P.append('<div class="index-block">')
    P.append('<div class="lbl">Index</div>')
    P.append(f'<div class="index-val mono">{idx:.1f}<span class="of">/100</span></div>')
    P.append(f'<div class="conviction mono">net {agg["net_sentiment"]:+.2f}</div>')
    P.append("</div>")
    P.append('<div class="gauge">')
    P.append('<div class="lbl">Bearish &mdash; Balanced &mdash; Bullish</div>')
    P.append('<div class="gauge-track"><div class="gauge-mid"></div>'
             f'<div class="gauge-pin" style="left:{pin:.2f}%"></div></div>')
    P.append('<div class="gauge-ends mono"><span>0</span><span>50</span><span>100</span></div>')
    P.append("</div>")
    P.append("</div></div>")

    # weighted mass
    P.append('<section class="mass">')
    P.append("<h2>Weighted mass</h2>")
    P.append('<div class="mass-bar">')
    P.append(f'<span style="width:{bull_pct:.2f}%;background:var(--bull)"></span>')
    P.append(f'<span style="width:{neut_pct:.2f}%;background:var(--rule)"></span>')
    P.append(f'<span style="width:{bear_pct:.2f}%;background:var(--bear)"></span>')
    P.append("</div>")
    P.append('<div class="mass-key mono">'
             f'<span><i class="dot" style="background:var(--bull)"></i>{bull_pct:.0f}% bullish</span>'
             f'<span><i class="dot" style="background:var(--rule)"></i>{neut_pct:.0f}% neutral</span>'
             f'<span><i class="dot" style="background:var(--bear)"></i>{bear_pct:.0f}% bearish</span>'
             f'<span>{counts["scored"]} headlines scored</span></div>')
    P.append("</section>")

    # integrity flags
    flags = []
    if agg.get("tie_break"):
        flags.append(
            f'<b>Decided by tie-break ({esc(agg["tie_break"])}), not by the data.</b> '
            "Treat this as no signal regardless of the direction shown.")
    if counts.get("unscored"):
        flags.append(
            f'<b>{counts["unscored"]} headlines could not be scored</b> and were excluded '
            "from the index. This reading rests on a partial sample.")
    for f in flags:
        P.append(f'<div class="flag warn">{f}</div>')

    # recommendation
    P.append("<section>")
    P.append("<h2>3&times; leveraged ETF &mdash; bullish tape only</h2>")
    if rec.get("issued"):
        P.append('<div class="picks">')
        for p in rec.get("picks", []):
            P.append('<div class="pick">')
            P.append('<div class="pick-head">')
            P.append(f'<span class="tick mono">{esc(p["ticker"])}</span>')
            P.append(f'<span class="pick-name">{esc(p["name"])}</span>')
            P.append(f'<span class="pick-score mono">{p["score"]:+.2f}</span>')
            P.append("</div>")
            P.append('<div class="metrics mono">'
                     f'<span>theme sentiment <b>{p["theme_net"]:+.2f}</b></span>'
                     f'<span>confidence <b>{p["confidence"]:.2f}</b></span>'
                     f'<span>support <b>{p["supporting_headlines"]}</b> headlines</span></div>')
            P.append('<div class="chips">')
            for t in p.get("matched_themes", []):
                P.append(f'<span class="chip">{esc(t)}</span>')
            for e in p.get("equivalents", []):
                P.append(f'<span class="chip same">= {esc(e)}</span>')
            P.append("</div>")
            for c in p.get("caveats", []):
                P.append(f'<div class="caveat">{esc(c)}</div>')
            P.append("</div>")
        P.append("</div>")
    else:
        P.append('<div class="held">')
        P.append('<div class="held-title">No recommendation</div>')
        P.append(f'<div class="held-why">{esc(rec.get("reason", "The bullish gate was not cleared."))}</div>')
        P.append('<div class="held-why" style="color:var(--faint)">Every product in the universe is a '
                 'long position, so nothing is suggested on a flat or falling tape.</div>')
        P.append("</div>")
    P.append("</section>")

    # drivers
    def driver_col(title: str, rows: list, color: str) -> None:
        P.append('<div class="drv">')
        P.append(f"<h2>{title}</h2>")
        peak = max((abs(r["contribution"]) for r in rows), default=1) or 1
        for r in rows[:5]:
            share = abs(r["contribution"]) / peak * 100
            P.append('<div class="row">')
            P.append('<div class="row-top">')
            P.append(f'<span class="row-txt">{esc(r["headline"])}</span>')
            P.append(f'<span class="row-num mono" style="color:{color}">{r["contribution"]:+.2f}</span>')
            P.append("</div>")
            P.append(f'<div class="row-bar" style="width:{share:.1f}%;background:{color}"></div>')
            P.append(f'<div class="meta mono">importance {r["importance"]} &middot; '
                     f'sentiment {r["sentiment"]:+d}</div>')
            P.append("</div>")
        if not rows:
            P.append('<div class="meta">None.</div>')
        P.append("</div>")

    P.append('<div class="cols">')
    driver_col("Pushing it up", report.get("top_bullish", []), "var(--bull)")
    driver_col("Pushing it down", report.get("top_bearish", []), "var(--bear)")
    P.append("</div>")

    # method
    P.append("<details><summary>How this is calculated</summary>")
    P.append('<div class="method-grid">')
    P.append("<div><b>Scoring</b>Every headline is read individually and given an importance "
             "(1&ndash;10) and a sentiment (&minus;10&hellip;+10). That judgment is the only "
             "subjective input.</div>")
    P.append(f"<div><b>Weighting</b><code>(importance/10)^{w.get('importance_exponent','1.5')}</code> "
             f"&times; recency &times; section &times; source. Recency halves every "
             f"{w.get('recency_half_life_hours','6')} hours.</div>")
    P.append("<div><b>Index</b>Weighted <em>mean</em> sentiment, mapped to 0&ndash;100 with 50 as "
             "balanced. A mean, not a sum, so a quiet news day doesn't drift the number.</div>")
    P.append("<div><b>ETF pick</b>Weighted sentiment of the themes each fund tracks, shrunk toward "
             "zero when the supporting evidence is thin. Needs positive theme sentiment and at "
             "least two supporting headlines.</div>")
    P.append("</div></details>")

    P.append('<div class="disc">Sentiment reading of financial news headlines. It has no backtest '
             'and is not calibrated to actual returns &mdash; an index of 62 means the news flow '
             'leans positive, not that a move of any particular size is expected. Not investment '
             'advice. 3&times; leveraged products reset daily, decay in choppy markets, and are '
             'built for holding periods measured in hours to days, not weeks.</div>')
    P.append("</div>")
    return "\n".join(P)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Render a sentiment report as an HTML artifact.")
    p.add_argument("--report", required=True, help="finviz-sentiment-*.json")
    p.add_argument("--label", default="Latest", help="e.g. 'Pre-market' or 'Afternoon'")
    p.add_argument("--out", required=True, help="output .html path")
    args = p.parse_args(argv)

    with open(args.report, encoding="utf-8") as fh:
        report = json.load(fh)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(render(report, args.label))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
