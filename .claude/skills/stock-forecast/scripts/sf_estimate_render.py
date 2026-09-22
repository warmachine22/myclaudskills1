#!/usr/bin/env python3
"""HTML for the 'our estimate versus the street' section.

Presents both numbers with equal weight. The consensus is not treated as an error to be
corrected - it is a large, well-resourced sample of people who model these companies for
a living, and where it differs from us the page says which of us is making the more
aggressive assumption rather than which is right.
"""

from __future__ import annotations

import html
import json
import pathlib


def esc(v) -> str:
    return html.escape(str(v)) if v is not None else ""


def _paras(text) -> str:
    if not text:
        return ""
    return "".join(f"<p>{esc(p)}</p>" for p in str(text).split("\n\n") if p.strip())


def build(bundle: dict, analysis: dict, folder) -> str:
    path = pathlib.Path(folder) / "estimate-v2.json"
    if not path.exists():
        return ""
    try:
        est = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""

    cases, cmp_ = est.get("cases") or {}, est.get("comparison") or {}
    parts = [_paras(est.get("method"))]

    ours, street = cmp_.get("our_base_eps"), cmp_.get("street_eps")
    gap = cmp_.get("gap_pct")
    tiles = [("Our estimate", f"${ours:,.2f}" if ours else "&mdash;"),
             ("Our range", (f"${cmp_['our_low_eps']:,.2f} &ndash; ${cmp_['our_high_eps']:,.2f}"
                            if cmp_.get("our_low_eps") is not None else "&mdash;")),
             ("Street", (f"${street:,.2f}" if street else "&mdash;")
              + (f" <span class='sub'>({cmp_['street_analysts']} analysts)</span>"
                 if cmp_.get("street_analysts") else "")),
             ("Gap", (f"{gap:+.1f}%" if gap is not None else "&mdash;"))]
    parts.append('<div class="minis">' + "".join(
        f'<div class="mini"><div class="k">{esc(k)}</div><div class="v">{v}</div></div>'
        for k, v in tiles) + "</div>")
    if cmp_.get("verdict"):
        parts.append(f'<p><strong>Our build is {esc(cmp_["verdict"])}.</strong></p>')

    # the full build, so every step between drivers and EPS is visible
    rows = [("Revenue ($m)", "revenue_m", "{:,.0f}"),
            ("Gross margin", "gross_margin_pct", "{:.1f}%"),
            ("Gross profit ($m)", "gross_profit_m", "{:,.0f}"),
            ("Operating expense ($m)", "opex_m", "{:,.0f}"),
            ("Operating income ($m)", "operating_income_m", "{:,.0f}"),
            ("Operating margin", "operating_margin_pct", "{:.1f}%"),
            ("Other income ($m)", "other_income_m", "{:,.0f}"),
            ("Tax rate", "tax_rate_pct", "{:.1f}%"),
            ("Net income ($m)", "net_income_m", "{:,.0f}"),
            ("Diluted shares (m)", "shares_m", "{:,.0f}"),
            ("EPS", "eps", "{:,.2f}")]
    body = ""
    for label, key, spec in rows:
        cells = ""
        for case in ("low", "base", "high"):
            v = (cases.get(case) or {}).get(key)
            cells += (f'<td class="n">{spec.format(v)}</td>' if v is not None
                      else '<td class="n">&mdash;</td>')
        strong = ' class="q"' if key == "eps" else ' class="q"'
        body += f"<tr><td{strong}>{esc(label)}</td>{cells}</tr>"
    parts.append('<div class="scroll"><table class="scen"><thead><tr><th>Line</th>'
                 '<th class="n">Low</th><th class="n">Base</th><th class="n">High</th>'
                 f"</tr></thead><tbody>{body}</tbody></table></div>")

    drivers = est.get("drivers") or []
    if drivers:
        items = []
        for d in drivers:
            rng = (f"{d['low']} / {d['base']} / {d['high']}"
                   if d.get("low") is not None else str(d.get("base")))
            base_note = (f" on a base of {d['base_value']:,.0f}"
                         if d.get("base_value") else "")
            items.append(
                f"<li><strong>{esc(d.get('label'))}</strong> "
                f"<span class='sub'>({esc(d.get('type'))})</span>: {esc(rng)}{esc(base_note)}"
                + (f"<div class='quote'>{esc(d['source'])}</div>" if d.get("source") else "")
                + (f"<p class='note'>{esc(d['rationale'])}</p>" if d.get("rationale") else "")
                + "</li>")
        parts.append("<h3>Every driver, and where it came from</h3>")
        parts.append('<ul class="findings">' + "".join(items) + "</ul>")

    if est.get("notes"):
        parts.append(f'<p class="note">{esc(est["notes"])}</p>')
    if cmp_.get("blinding_note"):
        parts.append(f'<div class="warn"><strong>On the blinding.</strong> '
                     f'{esc(cmp_["blinding_note"])}</div>')

    parts.append(_paras((analysis.get("section_commentary") or {}).get("own_estimate")))
    return "".join(p for p in parts if p)
