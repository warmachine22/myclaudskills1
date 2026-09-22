#!/usr/bin/env python3
"""HTML for the market-evidence section: options, comps, reverse DCF, primary filings.

Kept separate from render.py so the main renderer needs only an import and one entry in
its section list. Every block degrades to a stated reason rather than vanishing, because
a missing section reads as "nothing to say" when the truth is usually "the data did not
come back".
"""

from __future__ import annotations

import html
import json
import pathlib


def esc(v) -> str:
    return html.escape(str(v)) if v is not None else ""


def _money(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "&mdash;"
    return f"${v:,.2f}" if abs(v) < 1000 else f"${v:,.0f}"


def _warn(text: str) -> str:
    return f'<p class="warn">{esc(text)}</p>'


def _options(block: dict, price: float | None) -> str:
    if not block or not block.get("ok"):
        return _warn("Options read unavailable: "
                     + str((block or {}).get("error", "no chain returned")))
    s = block.get("event_straddle") or {}
    lo = block["spot"] * (1 - s["implied_move_pct"] / 100)
    hi = block["spot"] * (1 + s["implied_move_pct"] / 100)
    tiles = [("Implied move", f"&plusmn;{s['implied_move_pct']:.1f}%"),
             ("Implied range", f"{_money(lo)} – {_money(hi)}"),
             ("ATM implied vol", f"{s['atm_iv']:.1f}%" if s.get("atm_iv") else "&mdash;"),
             ("Expiry", f"{s['expiry']} ({s['days_to_expiry']}d)")]
    out = ['<div class="minis">' + "".join(
        f'<div class="mini"><div class="k">{esc(k)}</div><div class="v">{v}</div></div>'
        for k, v in tiles) + "</div>"]
    bits = []
    if block.get("skew"):
        k = block["skew"]
        bits.append(f"Skew {k['skew_pts']:+.1f} pts &mdash; {esc(k['reading'])} "
                    f"(puts {k['put_iv_pct']:.1f}% vs calls {k['call_iv_pct']:.1f}%, "
                    f"{esc(k['method'])})")
    if block.get("term_structure"):
        t = block["term_structure"]
        bits.append(f"Term structure {t['spread_pts']:+.1f} pts &mdash; {esc(t['reading'])} "
                    f"({t['near_expiry']} {t['near_iv_pct']:.1f}% vs "
                    f"{t['far_expiry']} {t['far_iv_pct']:.1f}%)")
    if bits:
        out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bits) + "</ul>")
    if block.get("note"):
        out.append(_warn(block["note"]))
    return "".join(out)


def _comps(block: dict) -> str:
    if not block or not block.get("ok"):
        return _warn("Peer comparison unavailable: "
                     + str((block or {}).get("error", "no peer data returned")))
    cols = [("market_cap", "Mkt cap", "{:,.1f}B"), ("ev_sales", "EV/Sales", "{:.1f}x"),
            ("ev_ebitda", "EV/EBITDA", "{:.1f}x"), ("fwd_pe", "Fwd P/E", "{:.1f}x"),
            ("gross_margin", "Gross", "{:.1f}%"), ("op_margin", "Op", "{:.1f}%"),
            ("rev_growth", "Rev growth", "{:.1f}%"), ("beta", "Beta", "{:.2f}")]
    head = "".join(f'<th class="n">{esc(lab)}</th>' for _, lab, _ in cols)
    body = []
    subject = block.get("subject")
    for r in block.get("rows", []):
        if not r.get("ok"):
            continue
        cells = ""
        for key, _, spec in cols:
            v = r.get(key)
            cells += (f'<td class="n">{spec.format(v)}</td>' if v is not None
                      else '<td class="n">&mdash;</td>')
        cls = ' class="q"' if r["ticker"] == subject else ""
        name = (f"<strong>{esc(r['ticker'])}</strong>" if r["ticker"] == subject
                else esc(r["ticker"]))
        body.append(f"<tr><td{cls}>{name}</td>{cells}</tr>")
    stats = block.get("stats") or {}
    if stats:
        med = "".join(
            (f'<td class="n">{spec.format(stats[key]["median"])}</td>'
             if stats.get(key) else '<td class="n">&mdash;</td>')
            for key, _, spec in cols)
        body.append(f'<tr><td class="q"><em>median</em></td>{med}</tr>')
    out = ['<div class="scroll"><table class="scen"><thead><tr><th>Ticker</th>'
           f"{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"]
    ranks = block.get("ranks") or {}
    if ranks:
        labels = {k: lab for k, lab, _ in cols}
        items = []
        for key, r in ranks.items():
            if key not in labels:
                continue
            gap = (f", {r['vs_median_pct']:+.0f}% vs median"
                   if r.get("vs_median_pct") is not None else "")
            items.append(f"<li>{esc(labels[key])}: {r['rank']} lowest of {r['of']} "
                         f"({esc(r['direction'])}{gap})</li>")
        if items:
            out.append("<ul>" + "".join(items) + "</ul>")
    if block.get("failed"):
        out.append(_warn("No data returned for: " + ", ".join(block["failed"])))
    return "".join(out)


def _reverse_dcf(block: dict) -> str:
    if not block or not block.get("ok"):
        return _warn("Reverse DCF not run: "
                     + str((block or {}).get("error", "inputs unavailable")))
    i = block["inputs"]
    rows = "".join(
        f'<tr><td class="q">{r["discount_pct"]:.1f}%'
        + (" (CAPM)" if r.get("label") == "CAPM" else "")
        + "</td><td class=\"n\">"
        + (f'{r["implied_growth_pct"]:.1f}%' if r.get("implied_growth_pct") is not None
           else "unsolvable") + "</td></tr>"
        for r in block.get("implied_growth_by_discount", []))
    out = [f'<p>{esc(block["reading"])}</p>']
    if rows:
        out.append('<table class="scen"><thead><tr><th>Discount rate</th>'
                   '<th class="n">Required FCF growth</th></tr></thead>'
                   f"<tbody>{rows}</tbody></table>")
    out.append(f'<p class="note">Starting free cash flow ${i["fcf_musd"]:,.0f}m over '
               f'{i["shares_m"]:,.0f}m shares, {i["horizon_years"]}-year explicit horizon '
               f'fading to {i["terminal_growth_pct"]:.1f}%. Risk-free '
               f'{i["risk_free_pct"]:.2f}% from {esc(i["risk_free_source"])}; '
               f'CAPM rate uses beta {i["beta"]:.2f} and a '
               f'{i["equity_risk_premium_pct"]:.1f}% equity risk premium.</p>')
    return "".join(out)


def _primary(block: dict) -> str:
    if not block or not block.get("ok"):
        return _warn("SEC filing data unavailable: "
                     + str((block or {}).get("error", "companyfacts did not return")))
    series = block.get("series") or {}
    want = [("revenue", "Revenue"), ("operating_income", "Operating income"),
            ("net_income", "Net income"), ("eps_diluted", "Diluted EPS"),
            ("inventory", "Inventory"), ("receivables", "Receivables"),
            ("shares_diluted", "Diluted shares"), ("buybacks", "Buybacks")]
    rows = []
    for key, label in want:
        s = series.get(key)
        if not s:
            continue
        last = s[-1]
        v = last["value"]
        if key == "eps_diluted":
            shown = f"{v:,.2f}"
        elif key == "shares_diluted":          # a count, not an amount of money
            shown = f"{v/1e9:,.2f}bn shares"
        elif abs(v) >= 1e9:
            shown = f"${v/1e9:,.2f}bn"
        else:
            shown = f"${v:,.0f}"
        rows.append(f'<tr><td class="q">{esc(label)}</td><td class="n">{shown}</td>'
                    f'<td class="n">{esc(last["end"])}</td>'
                    f'<td>{esc(last["form"])} · <code>{esc(last["tag"])}</code></td></tr>')
    if not rows:
        return _warn("No usable XBRL series returned for this filer.")
    out = ['<table class="scen"><thead><tr><th>Line</th><th class="n">Latest</th>'
           '<th class="n">Period end</th><th>Filing / tag</th></tr></thead>'
           f"<tbody>{''.join(rows)}</tbody></table>"]
    f = block.get("latest_periodic_filing")
    if f:
        out.append(f'<p class="note">Most recent periodic filing: {esc(f["form"])}, '
                   f'filed {esc(f["filed"])}. Every figure above is read from the XBRL '
                   f'facts the company itself filed, not from an aggregator.</p>')
    return "".join(out)


def build(bundle: dict, analysis: dict, folder) -> str:
    """Assemble the section. Returns '' when no evidence file exists."""
    path = pathlib.Path(folder) / "evidence.json"
    if not path.exists():
        return ""
    try:
        ev = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    blocks = ev.get("blocks") or {}
    price = ev.get("price_at_build")

    parts = []
    commentary = (analysis.get("section_commentary") or {})

    def para(key):
        text = commentary.get(key)
        if not text:
            return ""
        return "".join(f"<p>{esc(p)}</p>" for p in str(text).split("\n\n") if p.strip())

    parts.append("<h3>What the options market has priced in</h3>")
    parts.append(_options(blocks.get("options"), price))
    parts.append(para("options"))

    parts.append("<h3>Against its peers</h3>")
    parts.append(_comps(blocks.get("comps")))
    parts.append(para("comps"))

    parts.append("<h3>What the price already assumes</h3>")
    parts.append(_reverse_dcf(blocks.get("reverse_dcf")))
    parts.append(para("reverse_dcf"))

    parts.append("<h3>Straight from the filings</h3>")
    parts.append(_primary(blocks.get("primary")))
    parts.append(para("primary"))

    return "".join(p for p in parts if p)
