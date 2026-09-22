#!/usr/bin/env python3
"""Render the 3x ETF universe as a standalone HTML reference page.

Generated entirely from etf_universe.py, so the page can never disagree with
what the recommendation engine actually uses. Regenerate after any change to
the universe.
"""

from __future__ import annotations

import argparse
import html
import sys
from datetime import datetime

from etf_universe import (CATEGORIES, CAVEATS, DESCRIPTIONS, REJECTED, THEMES,
                          UNIVERSE)
from render_artifact import TOKENS

TITLE = "3x ETF Universe"


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


CSS = TOKENS + """
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.mono{font-family:ui-monospace,"SF Mono","Cascadia Mono","Segoe UI Mono",Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums}
.wrap{max-width:60rem;margin:0 auto;padding:1.75rem 1.25rem 4rem;display:flex;flex-direction:column;gap:1.5rem}

.status{display:flex;flex-wrap:wrap;align-items:baseline;gap:.5rem 1rem;
  padding-bottom:.9rem;border-bottom:1px solid var(--rule)}
.status h1{margin:0;font-size:.95rem;font-weight:650;letter-spacing:.01em}
.stamp{margin-left:auto;font-size:.78rem;color:var(--muted)}
.note{font-size:.85rem;color:var(--muted);line-height:1.55;max-width:48rem}
.note b{color:var(--ink);font-weight:600}

.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(8rem,1fr));gap:.7rem}
.stat{background:var(--card);border:1px solid var(--rule);border-radius:6px;padding:.7rem .85rem;
  display:flex;flex-direction:column;gap:.05rem}
.stat-val{font-size:1.45rem;font-weight:650;line-height:1.15}
.stat-lbl{font-size:.66rem;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);font-weight:650}

.cat{display:flex;flex-direction:column;gap:.55rem}
.cat-head{display:flex;align-items:baseline;gap:.6rem;border-bottom:1px solid var(--rule);
  padding-bottom:.4rem}
.cat-name{font-size:.78rem;letter-spacing:.1em;text-transform:uppercase;font-weight:650;color:var(--accent)}
.cat-count{font-size:.7rem;color:var(--faint)}

.rows{display:flex;flex-direction:column}
.row{display:grid;grid-template-columns:5.5rem 1fr;gap:.15rem .9rem;padding:.65rem 0;
  border-bottom:1px solid var(--rule)}
.row:last-child{border-bottom:none}
.sym{font-size:1rem;font-weight:700;letter-spacing:.01em;grid-row:span 2;align-self:start;
  display:flex;flex-direction:column;gap:.25rem}
.badge{font-size:.6rem;letter-spacing:.07em;font-weight:650;padding:.1rem .3rem;border-radius:3px;
  align-self:flex-start;background:var(--rule);color:var(--muted)}
.badge.etn{background:var(--warn-soft);color:var(--warn)}
.badge.lev4{background:var(--bear-soft);color:var(--bear)}
.name{font-size:.86rem;font-weight:600;line-height:1.35}
.desc{font-size:.82rem;color:var(--muted);line-height:1.45}
.cav{font-size:.78rem;color:var(--muted);padding-left:.9rem;position:relative;
  line-height:1.45;margin-top:.25rem}
.cav::before{content:"!";position:absolute;left:0;color:var(--warn);font-weight:700}

.panel{background:var(--card);border:1px solid var(--rule);border-radius:8px;padding:1rem 1.15rem;
  display:flex;flex-direction:column;gap:.6rem;box-shadow:var(--shadow)}
.panel.danger{border-left:3px solid var(--bear)}
.panel h2{margin:0;font-size:.74rem;letter-spacing:.1em;text-transform:uppercase;
  color:var(--faint);font-weight:650}
.rej{display:grid;grid-template-columns:5.5rem 1fr;gap:.3rem .9rem;font-size:.83rem;line-height:1.45}
.rej .sym-x{font-weight:700;color:var(--bear);text-decoration:line-through}
.rej .why{color:var(--muted)}

.themes{display:flex;flex-wrap:wrap;gap:.3rem}
.chip{font-size:.68rem;letter-spacing:.03em;padding:.15rem .45rem;border-radius:3px;
  background:var(--accent-soft);color:var(--accent);font-weight:600}
.disc{font-size:.75rem;color:var(--faint);line-height:1.55;border-top:1px solid var(--rule);padding-top:1rem}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media (max-width:30rem){
  .row{grid-template-columns:1fr;gap:.2rem}
  .sym{grid-row:auto;flex-direction:row;align-items:center;gap:.45rem}
}
"""


def render() -> str:
    etns = [t for t, v in UNIVERSE.items() if v[1] == "ETN"]
    P: list[str] = []
    P.append(f"<title>{esc(TITLE)}</title>")
    P.append(f"<style>{CSS}</style>")
    P.append('<div class="wrap">')

    now = datetime.now().astimezone()
    P.append('<div class="status">')
    P.append(f"<h1>{esc(TITLE)}</h1>")
    P.append(f'<span class="stamp mono">{esc(now.strftime("%b %d, %Y"))}</span>')
    P.append("</div>")

    P.append('<p class="note">Every product the recommender can choose from. All of them are '
             '<b>long</b> positions &mdash; nothing inverse is included, because a recommendation '
             'is only ever issued on a bullish reading and an inverse fund would point the wrong '
             'way. Verified against issuer product pages before inclusion.</p>')

    P.append('<div class="summary">')
    P.append(f'<div class="stat"><span class="stat-lbl">Products</span>'
             f'<span class="stat-val mono">{len(UNIVERSE)}</span></div>')
    P.append(f'<div class="stat"><span class="stat-lbl">Categories</span>'
             f'<span class="stat-val mono">{len(CATEGORIES)}</span></div>')
    P.append(f'<div class="stat"><span class="stat-lbl">ETNs</span>'
             f'<span class="stat-val mono">{len(etns)}</span></div>')
    P.append(f'<div class="stat"><span class="stat-lbl">Themes</span>'
             f'<span class="stat-val mono">{len(THEMES)}</span></div>')
    P.append("</div>")

    for cat_name, tickers in CATEGORIES:
        P.append('<section class="cat">')
        P.append('<div class="cat-head">')
        P.append(f'<span class="cat-name">{esc(cat_name)}</span>')
        P.append(f'<span class="cat-count mono">{len(tickers)}</span>')
        P.append("</div>")
        P.append('<div class="rows">')
        for t in tickers:
            name, structure, lev, _themes = UNIVERSE[t]
            P.append('<div class="row">')
            P.append('<div class="sym mono">' + esc(t))
            if structure == "ETN":
                P.append('<span class="badge etn">ETN</span>')
            if lev != 3:
                P.append(f'<span class="badge lev4">{lev}&times;</span>')
            P.append("</div>")
            P.append(f'<div class="name">{esc(name)}</div>')
            P.append(f'<div class="desc">{esc(DESCRIPTIONS.get(t, ""))}')
            if t in CAVEATS:
                P.append(f'<div class="cav">{esc(CAVEATS[t])}</div>')
            P.append("</div>")
            P.append("</div>")
        P.append("</div></section>")

    P.append('<div class="panel danger">')
    P.append("<h2>Excluded &mdash; do not reintroduce</h2>")
    P.append('<div class="rej">')
    for t, why in REJECTED.items():
        P.append(f'<span class="sym-x mono">{esc(t)}</span><span class="why">{esc(why)}</span>')
    P.append("</div>")
    P.append('<p class="desc" style="margin:0">These were proposed for the universe and rejected. '
             'Any new candidate must have both its leverage <b>and its direction</b> verified on '
             'the issuer&rsquo;s own page before it is added.</p>')
    P.append("</div>")

    P.append('<div class="panel">')
    P.append(f"<h2>What an ETN is &mdash; {len(etns)} of {len(UNIVERSE)} here</h2>")
    P.append('<p class="desc" style="margin:0">An ETN is an unsecured promise from the issuing '
             'bank, not a fund holding assets. If the issuer fails you are an unsecured creditor '
             'regardless of how the underlying index performed. Remote day to day, but a genuinely '
             'different instrument from an ETF.</p>')
    P.append('<div class="themes">')
    for t in sorted(etns):
        P.append(f'<span class="chip mono">{esc(t)}</span>')
    P.append("</div></div>")

    P.append('<div class="disc">Reference list only &mdash; inclusion here is not a recommendation. '
             'Which of these (if any) gets suggested depends entirely on the news reading at the '
             'time, and nothing is suggested on a flat or falling tape. Not investment advice. '
             '3&times; leveraged products reset daily, decay in choppy markets, and are built for '
             'holding periods measured in hours to days, not weeks.</div>')
    P.append("</div>")
    return "\n".join(P)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Render the 3x ETF universe reference page.")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(render())
    print(f"wrote {args.out} ({len(UNIVERSE)} products)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
