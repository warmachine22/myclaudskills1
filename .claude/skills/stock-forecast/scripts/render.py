#!/usr/bin/env python3
"""Stage 3: bundle + analysis -> one self-contained dashboard.

    python render.py ./NVDA-bundle -o NVDA-forecast.html

Numbers come from bundle.json. Judgment comes from analysis.json, which the
model writes after reading the bundle. If a required judgment block is missing
this refuses to render — a page with a confident header and empty reasoning is
worse than no page.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sf_charts as charts
import sf_evidence_render
import sf_estimate_render  # noqa: E402
from analysis_contract import (  # noqa: E402
    scorecard_result, target_departure, validate_analysis)

REQUIRED = {
    "thesis": "2-4 sentences: the call and why",
    "company_explainer": "what the company actually does, plain language",
    "scorecard": "list of {dimension, score, weight, evidence}",
    "rating": "BUY or SELL — never neutral",
    "conviction": "high | medium | low",
    "target_price": "{value, horizon, derivation}",
    "section_commentary": "{technicals, financials, fair_value, revisions, ...}",
    "falsifiers": "list of what would prove this call wrong",
}
OPTIONAL = ("said_vs_delivered", "qa_read", "deck_findings", "bull_case",
            "bear_case", "risks", "scenarios")


def esc(value):
    return html.escape(str(value)) if value is not None else ""


def md_inline(text):
    """A deliberately tiny subset: **bold**, *italic*, `code`. Nothing else, so
    model-written prose can never inject markup into the page."""
    import re
    out = esc(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<em>\1</em>", out)
    out = re.sub(r"`(.+?)`", r"<code>\1</code>", out)
    return out


def paragraphs(text):
    if not text:
        return ""
    if isinstance(text, list):
        text = "\n\n".join(str(t) for t in text)
    return "".join(f"<p>{md_inline(block.strip())}</p>"
                   for block in str(text).split("\n\n") if block.strip())


def num(snapshot, key):
    cell = (snapshot or {}).get(key)
    if not isinstance(cell, dict):
        return None
    if cell.get("num") is not None:
        return float(cell["num"])
    import re
    m = re.search(r"-?\d+(?:\.\d+)?", str(cell.get("value") or ""))
    return float(m.group(0)) if m else None


def snap_text(snapshot, key):
    cell = (snapshot or {}).get(key)
    return cell.get("value") if isinstance(cell, dict) else None


def money(v, dp=2):
    return "—" if v is None else f"${v:,.{dp}f}"


def pct(v, dp=1, signed=True):
    if v is None:
        return "—"
    return f"{v:+.{dp}f}%" if signed else f"{v:.{dp}f}%"


def big(v):
    if v is None:
        return "—"
    a = abs(v)
    for cut, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= cut:
            return f"${v/cut:.2f}{suffix}"
    return f"${v:,.0f}"


def quote_value(bundle, key, snapshot_key=None):
    quote = bundle.get("quote") or {}
    value = quote.get(key)
    if value is not None:
        return value
    snapshot = ((bundle.get("finviz") or {}).get("snapshot") or {})
    return num(snapshot, snapshot_key or key)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def validate(analysis, bundle=None):
    try:
        warnings = validate_analysis(analysis, bundle)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    result = scorecard_result(analysis["scorecard"])
    if result["rating"] != str(analysis["rating"]).upper():
        raise SystemExit(
            f"rating {analysis['rating']} disagrees with weighted score mapping "
            f"{result['rating']}"
        )
    analysis["_contract_warnings"] = warnings
    if bundle is not None:
        analysis["_target_departure"] = target_departure(analysis, bundle)
    return str(analysis["rating"]).strip().upper()


def composite(scorecard):
    return scorecard_result(scorecard).get("composite")


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------

def section(id_, title, body, note=None):
    if not body:
        return ""
    note_html = f'<p class="note">{md_inline(note)}</p>' if note else ""
    return (f'<section id="{id_}"><h2>{esc(title)}</h2>{body}{note_html}</section>')


def commentary(analysis, key):
    return paragraphs((analysis.get("section_commentary") or {}).get(key))


def build_header(bundle, analysis, rating, score):
    meta = bundle["meta"]
    snapshot = (bundle.get("finviz") or {}).get("snapshot") or {}
    price = quote_value(bundle, "price", "Price")
    target = analysis["target_price"]
    tv = target.get("value")
    upside = (tv / price - 1) * 100 if tv and price else None
    conviction = str(analysis["conviction"]).lower()
    dots = {"high": 3, "medium": 2, "low": 1}[conviction]
    meter = "".join(f'<i class="{"on" if i < dots else ""}"></i>' for i in range(3))
    next_report = (bundle.get("resolved") or {}).get("next_report_date")
    change = quote_value(bundle, "change_pct", "Change")
    market_cap = quote_value(bundle, "market_cap", "Market Cap")

    tiles = [
        ("Price", money(price), f'{pct(change)} today' if change is not None else ""),
        ("Our 12-month target", money(tv), f"{pct(upside)} implied" if upside is not None else ""),
        ("Market cap", big(market_cap), ""),
        ("Next report", esc(next_report or "—"),
         esc(((bundle.get("finviz") or {}).get("next_report") or {}).get("session") or "")),
    ]
    tile_html = "".join(
        f'<div class="tile"><div class="k">{esc(k)}</div><div class="v">{v}</div>'
        f'<div class="s">{s}</div></div>' for k, s_, v, s in
        [(k, None, v, s) for k, v, s in tiles])

    return f"""
<header>
  <div class="id">
    <div>
      <h1>{esc(meta['ticker'])} <span class="co">{esc(meta.get('name') or '')}</span></h1>
      <p class="sub">{esc((bundle.get('profile') or {}).get('sector') or '')}
        {'· ' + esc((bundle.get('profile') or {}).get('industry') or '') if (bundle.get('profile') or {}).get('industry') else ''}
        · {esc((bundle.get('profile') or {}).get('country') or '')}</p>
    </div>
    <div class="verdict {rating.lower()}">
      <div class="badge">{rating}</div>
      <div class="conv">conviction <span class="meter">{meter}</span> {esc(conviction)}</div>
      <div class="score">composite {score:+.2f}</div>
    </div>
  </div>
  <div class="tiles">{tile_html}</div>
</header>"""


def build_scorecard(analysis, svg):
    rows = analysis["scorecard"]
    body = ['<div class="fig">' + (svg or "") + "</div>",
            '<table class="score-table"><thead><tr><th>Dimension</th><th>Score</th>'
            '<th>Weight</th><th>Evidence</th></tr></thead><tbody>']
    for r in rows:
        unavailable = bool(r.get("unavailable")) or r.get("score") is None
        score = float(r["score"]) if not unavailable else None
        cls = "muted" if unavailable else ("pos" if score > 0 else ("neg" if score < 0 else "zero"))
        weight = r.get("weight")
        score_text = "unavailable" if unavailable else f"{score:+.1f}"
        body.append(
            f'<tr><td>{esc(r["dimension"])}</td>'
            f'<td class="n {cls}">{score_text}</td>'
            f'<td class="n">{(str(round(float(weight)*100)) + "%") if weight else "—"}</td>'
            f'<td class="ev">{md_inline(r["evidence"])}</td></tr>')
    body.append("</tbody></table>")
    return "".join(body)


def build_technicals(bundle, analysis, svg):
    technicals = bundle.get("technicals")
    if not technicals:
        return ""
    latest = technicals["latest"]
    snapshot = (bundle.get("finviz") or {}).get("snapshot") or {}
    stack = latest.get("trend_stack")
    items = [
        ("RSI (14)", f'{latest["rsi14"]:.1f}' if latest.get("rsi14") else "—",
         "overbought >70 · oversold <30"),
        ("vs 50-day", pct((latest.get("pct_from_sma50") or 0) * 100), ""),
        ("vs 200-day", pct((latest.get("pct_from_sma200") or 0) * 100), ""),
        ("Trend stack", f"{stack}/3" if stack is not None else "—",
         "price&gt;50d, price&gt;200d, 50d&gt;200d"),
        ("From 52w high", pct((latest.get("pct_from_52w_high") or 0) * 100), ""),
        ("MACD histogram", f'{latest["macd_histogram"]:+.2f}'
         if latest.get("macd_histogram") is not None else "—", ""),
        ("Bollinger range", f'{money(latest.get("bollinger_lower"), 2)} – '
         f'{money(latest.get("bollinger_upper"), 2)}'
         if latest.get("bollinger_lower") is not None and latest.get("bollinger_upper") is not None else "—",
         "20-day band · 2 standard deviations"),
        ("ATR (14)", money(latest.get("atr14"), 2), "average true range"),
        ("Realised vol (20d)", f'{latest["realised_vol_20d"]*100:.0f}%'
         if latest.get("realised_vol_20d") else "—", "annualised"),
        ("Drawdown from 52w high", pct((latest.get("drawdown_from_52w_high") or 0) * 100), ""),
        ("Beta", str(num(snapshot, "Beta") or "—"), "Finviz snapshot"),
    ]
    strip = "".join(
        f'<div class="mini"><div class="k">{esc(k)}</div><div class="v">{v}</div>'
        f'<div class="s">{s}</div></div>' for k, v, s in items)
    crosses = technicals.get("crosses") or []
    cross_note = ""
    if crosses:
        c = crosses[0]
        cross_note = (f'<p class="note">Most recent signal: a <strong>{c["type"]} cross</strong> '
                      f'on {esc(c["date"])} (50-day through the 200-day).</p>')
    return (f'<div class="fig">{svg or ""}</div>'
            f'<div class="legend"><span><i class="sw px"></i>Price</span>'
            f'<span><i class="sw ma50"></i>50-day</span>'
            f'<span><i class="sw ma200"></i>200-day</span>'
            f'<span><i class="sw vol"></i>Volume</span></div>'
            f'<div class="minis">{strip}</div>{cross_note}'
            f'{commentary(analysis, "technicals")}')


def build_financials(bundle, analysis, rev_svg, eps_svg):
    parts = []
    if rev_svg:
        parts.append('<h3>Revenue by fiscal year</h3>'
                     f'<div class="fig">{rev_svg}</div>')
    if eps_svg:
        parts.append('<h3>Earnings per share by fiscal year</h3>'
                     f'<div class="fig">{eps_svg}</div>')
    if parts:
        parts.append('<p class="note">Solid bars are reported results; faded bars are '
                     'analyst consensus, not outcomes.</p>')
    forecast = bundle.get("forecast") or {}
    headline = (forecast.get("headline_estimates") or {}).get("annual") or {}
    rows = []
    for key, label in (("epsThis", "EPS, current FY"), ("epsNext", "EPS, next FY"),
                       ("revenueThis", "Revenue, current FY"),
                       ("revenueNext", "Revenue, next FY")):
        entry = headline.get(key) or {}
        if entry.get("this") is None:
            continue
        rows.append(f'<tr><td>{label}</td><td class="n">{entry.get("last") or "—"}</td>'
                    f'<td class="n">{entry.get("this")}</td>'
                    f'<td class="n">{pct(entry.get("growth"))}</td></tr>')
    if rows:
        parts.append('<table><thead><tr><th>Consensus</th><th>Last</th><th>Estimate</th>'
                     '<th>Growth</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>")
    parts.append(commentary(analysis, "financials"))
    return "".join(parts)


def build_fair_value(bundle, analysis, svg):
    fv = bundle.get("fair_value")
    if not fv:
        return ('<p class="warn">The fair-value engine returned nothing for this name, '
                'so no normal-multiple valuation is shown.</p>'
                + commentary(analysis, "fair_value"))
    parts = []
    if fv.get("refused"):
        flags = [f for f in fv.get("flags", []) if f["severity"] == "refuse"]
        parts.append('<div class="warn"><strong>The fair-value engine refused this name.</strong>'
                     '<ul>' + "".join(f"<li>{esc(f['detail'])}</li>" for f in flags) +
                     '</ul>No normal multiple is defensible here, so this dimension is '
                     'excluded from the scorecard rather than guessed.</div>')
    else:
        metric = "P/E" if fv.get("metric") == "pe" else "P/S"
        stats = fv.get("stats") or {}
        tiles = [
            (f"Normal {metric}", f'{fv["normal_adjusted"]:.1f}x'),
            ("Fair value", money(fv.get("fair_value"))),
            ("Premium / discount", pct((fv.get("premium") or 0) * 100)),
            ("Multiple percentile",
             f'{stats.get("percentile_now"):.0f}th' if stats.get("percentile_now") is not None else "—"),
        ]
        parts.append('<div class="minis">' + "".join(
            f'<div class="mini"><div class="k">{esc(k)}</div><div class="v">{v}</div></div>'
            for k, v in tiles) + "</div>")
        if svg:
            parts.append(f'<div class="fig">{svg}</div>'
                         '<div class="legend"><span><i class="sw px"></i>Price</span>'
                         '<span><i class="sw fv"></i>Fair value line</span>'
                         '<span><i class="sw band"></i>Bear–bull band</span></div>')
    warns = [f for f in fv.get("flags", []) if f["severity"] == "warn"]
    if warns:
        parts.append('<details><summary>' + str(len(warns)) +
                     ' caveat(s) from the valuation engine</summary><ul>' +
                     "".join(f"<li>{esc(f['detail'])}</li>" for f in warns) +
                     "</ul></details>")
    parts.append(commentary(analysis, "fair_value"))
    return "".join(parts)


def build_said_vs_delivered(analysis):
    rows = analysis.get("said_vs_delivered") or []
    if not rows:
        return ""
    verdict_class = {"beat": "pos", "met": "zero", "missed": "neg", "dropped": "neg"}
    body = ['<table class="svd"><thead><tr><th>Quarter</th><th>What they guided</th>'
            '<th>What landed</th><th>Verdict</th></tr></thead><tbody>']
    for r in rows:
        verdict = str(r.get("verdict", "")).lower()
        cls = next((v for k, v in verdict_class.items() if k in verdict), "zero")
        quote = (f'<div class="quote">“{md_inline(r["quote"])}”</div>'
                 if r.get("quote") else "")
        body.append(
            f'<tr><td class="q">{esc(r.get("quarter"))}</td>'
            f'<td>{md_inline(r.get("guided"))}{quote}</td>'
            f'<td>{md_inline(r.get("delivered"))}</td>'
            f'<td class="{cls} verdict-cell">{esc(r.get("verdict"))}'
            f'{source_badge(r)}</td></tr>')
    body.append("</tbody></table>")
    return "".join(body)


def source_badge(record):
    """Render a compact source link without allowing arbitrary HTML/URLs."""
    if not isinstance(record, dict):
        return ""
    label = record.get("source") or record.get("source_id")
    url = record.get("url") or record.get("source_url")
    if not label and not url:
        return ""
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        return f' <a class="src" href="{esc(url)}" target="_blank" rel="noreferrer">[{esc(label or "source")}]</a>'
    return f' <span class="src">[{esc(label or url)}]</span>'


def _embedded_image(folder, rel_dir, name, max_bytes=1_500_000):
    if not folder or not name:
        return None
    path = Path(folder) / rel_dir / str(name)
    try:
        if not path.exists() or path.stat().st_size > max_bytes:
            return None
        import base64
        import mimetypes
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{data}"
    except OSError:
        return None


def build_qa(qa):
    if not qa:
        return ""
    if not isinstance(qa, list):
        return paragraphs(qa)
    rows = []
    for item in qa:
        if isinstance(item, str):
            rows.append(f"<tr><td colspan=\"4\">{md_inline(item)}</td></tr>")
            continue
        status = str(item.get("status") or item.get("answer_quality") or "read").lower()
        cls = "pos" if status in {"answered", "clear", "direct"} else (
            "neg" if status in {"deflected", "partial", "partially answered"} else "zero")
        rows.append(
            f'<tr><td>{md_inline(item.get("questioner") or item.get("analyst") or "Analyst")}</td>'
            f'<td>{md_inline(item.get("question") or item.get("prompt"))}</td>'
            f'<td class="{cls}">{esc(item.get("status") or item.get("answer_quality") or "read")}</td>'
            f'<td>{md_inline(item.get("answer") or item.get("read") or item.get("takeaway"))}'
            f'{source_badge(item)}</td></tr>')
    if not rows:
        return ""
    return ('<table class="qa"><thead><tr><th>Questioner</th><th>Question</th>'
            '<th>Read</th><th>What management answered</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def build_call_section(bundle, analysis, folder=None):
    parts = []
    errors = bundle.get("errors") or []
    if errors:
        parts.append('<p class="note"><strong>Collection gaps:</strong> ' +
                     "; ".join(f"{esc(e['source'])} — {esc(e['message'])}" for e in errors) +
                     "</p>")
    transcripts = bundle.get("transcripts") or {}
    if not transcripts.get("latest_full") and not transcripts.get("summaries"):
        parts.append('<div class="warn"><strong>No earnings transcripts were collected.</strong> '
                     'The accountability and Q&amp;A read are unavailable for this run; '
                     'conviction should be reduced.</div>')
    elif transcripts.get("latest_full"):
        parts.append('<details><summary>Latest full transcript collected</summary><p class="note">'
                     + esc(transcripts["latest_full"]) + '</p></details>')
    svd = build_said_vs_delivered(analysis)
    if svd:
        parts.append("<h3>What management said they would do, and what happened</h3>")
        parts.append(svd)
    if analysis.get("qa_read"):
        parts.append("<h3>The Q&amp;A</h3>")
        parts.append(build_qa(analysis["qa_read"]))
    findings = analysis.get("deck_findings") or []
    if findings:
        parts.append("<h3>From the slide deck</h3><ul class=\"findings\">")
        for f in findings:
            if isinstance(f, dict):
                page = f' <span class="src">slide {esc(f.get("page"))}</span>' if f.get("page") else ""
                parts.append(f"<li>{md_inline(f.get('finding') or f.get('text'))}{page}"
                             f"{source_badge(f)}</li>")
            else:
                parts.append(f"<li>{md_inline(f)}</li>")
        parts.append("</ul>")
    decks = bundle.get("decks") or {}
    if decks.get("files"):
        parts.append('<details><summary>Downloaded investor materials</summary><ul>')
        parts.extend(f"<li>{esc(name)}</li>" for name in decks["files"])
        parts.append("</ul></details>")
    else:
        parts.append('<div class="warn"><strong>No investor slide deck or release was collected.</strong> '
                     'Material findings from those documents are unavailable for this run.</div>')
    sheets = decks.get("sheets") or []
    if folder and sheets:
        thumbs = []
        for name in sheets[:4]:
            src = _embedded_image(folder, decks.get("sheets_dir") or "deck-sheets", name)
            if src:
                thumbs.append(f'<figure><img src="{src}" alt="Investor material contact sheet {esc(name)}">'
                              f'<figcaption>{esc(name)}</figcaption></figure>')
        if thumbs:
            parts.append('<h3>Visual audit of investor materials</h3>'
                         '<div class="thumb-grid">' + "".join(thumbs) + "</div>")
    parts.append(commentary(analysis, "earnings_call"))
    return "".join(parts)


def build_market_context(bundle, analysis):
    parts = []
    news = bundle.get("market_news") or {}
    headlines = news.get("top") or []
    if headlines:
        rows = []
        for item in headlines[:10]:
            title = item.get("headline") or item.get("title") or "Untitled headline"
            source = item.get("source") or item.get("publisher") or "Finviz"
            url = item.get("url")
            title_html = (f'<a href="{esc(url)}" target="_blank" rel="noreferrer">{esc(title)}</a>'
                          if isinstance(url, str) and url.startswith(("http://", "https://"))
                          else esc(title))
            rows.append(f"<li>{title_html} <span class=\"src\">{esc(source)}</span></li>")
        parts.append("<h3>Market-news backdrop</h3><ul class=\"findings\">" + "".join(rows) + "</ul>")

    macro = bundle.get("macro") or {}
    macro_rows = []
    for window in ("recent", "thisweek", "nextweek"):
        payload = macro.get(window) or {}
        events = payload.get("events") or payload.get("calendar") or []
        for event in events[:12]:
            macro_rows.append(
                f'<tr><td>{esc(event.get("date") or event.get("datetime"))}</td>'
                f'<td>{esc(event.get("event") or event.get("name") or event.get("title"))}</td>'
                f'<td>{esc(event.get("country") or event.get("currency"))}</td>'
                f'<td>{esc(event.get("impact") or event.get("stars"))}</td>'
                f'<td>{esc(event.get("actual"))} / {esc(event.get("consensus") or event.get("forecast"))}</td></tr>')
    if macro_rows:
        parts.append('<h3>Macro calendar</h3><table><thead><tr><th>Date</th><th>Event</th>'
                     '<th>Country</th><th>Impact</th><th>Actual / consensus</th></tr></thead><tbody>'
                     + "".join(macro_rows[:24]) + "</tbody></table>")
    parts.append(commentary(analysis, "market_context"))
    parts.append(commentary(analysis, "macro"))
    return "".join(parts)


def build_street(bundle, analysis, svg):
    parts = []
    if svg:
        parts.append('<h3>Where consensus has moved</h3>'
                     f'<div class="fig">{svg}</div>')
    trend = bundle["finviz"].get("revision_trend") or []
    if trend:
        rows = "".join(
            f'<tr><td>{esc(t["fiscal_period"])}</td><td class="n">{t.get("latest_mean")}</td>'
            f'<td class="n {"pos" if (t.get("change_90d_pct") or 0) > 0 else "neg"}">'
            f'{pct(t.get("change_90d_pct"))}</td>'
            f'<td class="n {"pos" if (t.get("change_180d_pct") or 0) > 0 else "neg"}">'
            f'{pct(t.get("change_180d_pct"))}</td>'
            f'<td class="n">{t.get("up_revisions")}↑ / {t.get("down_revisions")}↓</td>'
            f'<td class="n">{t.get("analysts")}</td></tr>' for t in trend)
        parts.append('<table><thead><tr><th>Fiscal year</th><th>Consensus EPS</th>'
                     '<th>90 days</th><th>180 days</th><th>Revisions</th><th>Analysts</th>'
                     '</tr></thead><tbody>' + rows + "</tbody></table>")

    forecast = bundle.get("forecast") or {}
    target = forecast.get("price_target") or {}
    ours = (analysis.get("target_price") or {}).get("value")
    if target.get("average"):
        parts.append(
            '<div class="minis">'
            f'<div class="mini"><div class="k">Street target (avg)</div>'
            f'<div class="v">{money(target["average"])}</div>'
            f'<div class="s">{target.get("count") or "?"} analysts · '
            f'{money(target.get("low"))}–{money(target.get("high"))}</div></div>'
            f'<div class="mini"><div class="k">Our target</div>'
            f'<div class="v">{money(ours)}</div>'
            f'<div class="s">independent of consensus</div></div>'
            "</div>")
    reactions = bundle["finviz"].get("price_reactions") or []
    if reactions:
        parts.append(commentary(analysis, "reactions"))
    parts.append(commentary(analysis, "revisions"))
    return "".join(parts)


def build_forecast(analysis):
    target = analysis["target_price"]
    unavailable = target.get("value") is None or target.get("available") is False
    parts = [f'<div class="target-hero {"unavailable" if unavailable else ""}"><div class="k">12-month target</div>'
             f'<div class="v">{money(target.get("value"))}</div>'
             f'<div class="s">{esc(target.get("horizon") or "12 months")}</div></div>']
    if unavailable:
        parts.append('<div class="warn"><strong>No defensible target was available.</strong> '
                     f'{paragraphs(target.get("reason") or target.get("derivation"))}</div>')
    parts.append(paragraphs(target.get("derivation")))
    departure = analysis.get("_target_departure")
    if departure:
        cross = (departure.get("cross_check") or {}).get("street_average")
        parts.append(
            '<p class="note">Deterministic anchor '
            f'<strong>{money(departure["anchor"])}</strong> '
            '(normal-multiple fair value adjusted by the quality scores). '
            f'Our target sits <strong>{departure["drift"]:+.0%}</strong> from it'
            + (f'; analyst consensus is {money(cross)}, shown as a cross-check and '
               'excluded from both figures.' if cross else '.')
            + '</p>')
    bull, bear = target.get("bull"), target.get("bear")
    if bull or bear:
        parts.append('<div class="cases">')
        if bull:
            parts.append(f'<div class="case up"><h4>Bull — {money(bull.get("value")) if isinstance(bull, dict) else ""}</h4>'
                         f'{paragraphs(bull.get("text") if isinstance(bull, dict) else bull)}</div>')
        if bear:
            parts.append(f'<div class="case down"><h4>Bear — {money(bear.get("value")) if isinstance(bear, dict) else ""}</h4>'
                         f'{paragraphs(bear.get("text") if isinstance(bear, dict) else bear)}</div>')
        parts.append("</div>")
    return "".join(parts)


def build_scenarios(bundle, analysis):
    """Probability-weighted scenario table, expected value, and a sensitivity grid.

    Probabilities are the model's judgment and are labelled as such on the page. The
    arithmetic is not: implied returns, the weighted expected value and every cell of
    the sensitivity grid are derived here from the live price and the authored
    (eps, multiple) pairs, so a hand-typed number can never contradict the table.
    """
    block = analysis.get("scenarios") or {}
    cases = block.get("cases") or []
    if not cases:
        return ""
    price = quote_value(bundle, "price", "Price")
    rows, total_p, ev, priced = [], 0.0, 0.0, []
    for case in cases:
        try:
            prob = float(case.get("probability"))
        except (TypeError, ValueError):
            continue
        value = case.get("value")
        if value is None and case.get("eps") is not None and case.get("multiple") is not None:
            value = float(case["eps"]) * float(case["multiple"])
        priced.append((prob, value))
        total_p += prob
        if value is not None:
            ev += prob * float(value)
        ret = ((float(value) / price - 1) * 100) if (value and price) else None
        cls = "pos" if (ret or 0) > 2 else ("neg" if (ret or 0) < -2 else "zero")
        rows.append(
            f'<tr><td class="q">{md_inline(case.get("label"))}</td>'
            f'<td class="n">{prob * 100:.0f}%</td>'
            f'<td>{md_inline(case.get("drivers"))}</td>'
            f'<td class="n">{("%.2f" % float(case["eps"])) if case.get("eps") is not None else "&mdash;"}</td>'
            f'<td class="n">{("%.0fx" % float(case["multiple"])) if case.get("multiple") is not None else "&mdash;"}</td>'
            f'<td class="n">{money(value)}</td>'
            f'<td class="n {cls}">{("%+.0f%%" % ret) if ret is not None else "&mdash;"}</td></tr>')

    parts = [paragraphs(block.get("basis"))]
    parts.append('<table class="scen"><thead><tr><th>Scenario</th><th class="n">P</th>'
                 '<th>What has to happen</th><th class="n">EPS</th><th class="n">Multiple</th>'
                 '<th class="n">Value</th><th class="n">vs spot</th></tr></thead><tbody>'
                 + "".join(rows) + "</tbody></table>")

    ev_ret = ((ev / price - 1) * 100) if price else None
    upside_p = sum(prob for prob, value in priced
                   if value is not None and price and float(value) > price)
    tiles = [("Probability-weighted value", money(ev)),
             ("vs spot", (f"{ev_ret:+.1f}%" if ev_ret is not None else "—")),
             ("Chance of a gain", f"{upside_p * 100:.0f}%"),
             ("Our target", money((analysis.get("target_price") or {}).get("value")))]
    parts.append('<div class="minis">' + "".join(
        f'<div class="mini"><div class="k">{esc(k)}</div><div class="v">{v}</div></div>'
        for k, v in tiles) + "</div>")
    if abs(total_p - 1.0) > 0.005:
        parts.append(f'<p class="warn">Scenario probabilities sum to {total_p * 100:.0f}%, '
                     'not 100% — the weighted value below is therefore not a complete '
                     'expectation.</p>')

    grid = block.get("sensitivity") or {}
    eps_axis, mult_axis = grid.get("eps") or [], grid.get("multiples") or []
    if eps_axis and mult_axis:
        head = "".join(f'<th class="n">{float(m):.0f}x</th>' for m in mult_axis)
        body = ""
        for e in eps_axis:
            cells = ""
            for m in mult_axis:
                v = float(e) * float(m)
                mark = "pos" if price and v > price * 1.02 else (
                    "neg" if price and v < price * 0.98 else "zero")
                cells += f'<td class="n {mark}">{money(v)}</td>'
            body += f'<tr><td class="q">{money(float(e))}</td>{cells}</tr>'
        parts.append(f'<h3>{esc(grid.get("title") or "Sensitivity")}</h3>')
        parts.append('<div class="scroll"><table class="scen sens"><thead><tr>'
                     f'<th>EPS \\ multiple</th>{head}</tr></thead><tbody>{body}'
                     "</tbody></table></div>")
        parts.append(paragraphs(grid.get("note")))
    parts.append(commentary(analysis, "scenarios"))
    return "".join(parts)


def build_falsifiers(analysis):
    items = analysis.get("falsifiers") or []
    return ('<ul class="falsifiers">' +
            "".join(f"<li>{md_inline(i)}</li>" for i in items) + "</ul>")


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

CSS = """
*{box-sizing:border-box}
body{margin:0;padding:24px 20px 60px;background:var(--page);color:var(--ink);
 font:15px/1.62 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:27px;margin:0;font-weight:680;letter-spacing:-.01em}
h1 .co{font-weight:400;color:var(--ink-2);font-size:19px;margin-left:8px}
h2{font-size:19px;margin:0 0 14px;font-weight:640;letter-spacing:-.01em}
h3{font-size:15px;margin:24px 0 8px;font-weight:640;color:var(--ink-2)}
h4{font-size:14px;margin:0 0 6px}
p{margin:0 0 12px}
.sub{color:var(--ink-2);font-size:13.5px;margin:4px 0 0}
header{background:var(--surface);border:1px solid var(--border);border-radius:14px;
 padding:22px 24px;margin-bottom:18px}
.id{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;
 flex-wrap:wrap}
.verdict{text-align:right;min-width:170px}
.badge{font-size:30px;font-weight:750;letter-spacing:.02em;line-height:1.1}
.verdict.buy .badge{color:var(--good)} .verdict.sell .badge{color:var(--bad)}
.conv{font-size:12.5px;color:var(--ink-2);margin-top:4px}
.score{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.meter{display:inline-flex;gap:3px;vertical-align:middle;margin:0 3px}
.meter i{width:7px;height:7px;border-radius:50%;background:var(--border-solid);display:block}
.verdict.buy .meter i.on{background:var(--good)}
.verdict.sell .meter i.on{background:var(--bad)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;
 margin-top:20px;padding-top:18px;border-top:1px solid var(--border)}
.tile .k,.mini .k{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;
 color:var(--muted);font-weight:600}
.tile .v{font-size:23px;font-weight:640;margin-top:3px;font-variant-numeric:tabular-nums}
.tile .s,.mini .s{font-size:11.5px;color:var(--ink-2);margin-top:1px}
section{background:var(--surface);border:1px solid var(--border);border-radius:14px;
 padding:22px 24px;margin-bottom:18px}
.fig{margin:8px 0 4px;overflow-x:auto}
.minis{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:14px;
 margin:14px 0}
.mini .v{font-size:17px;font-weight:620;margin-top:2px;font-variant-numeric:tabular-nums}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin:10px 0}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);
 vertical-align:top}
th{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
 font-weight:650}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.pos{color:var(--good)} .neg{color:var(--bad)} .zero{color:var(--ink-2)} .muted{color:var(--muted)}
.score-table td.ev{color:var(--ink-2);font-size:13px}
.verdict-cell{text-transform:capitalize;font-weight:620}
.svd td.q{font-weight:620;white-space:nowrap}
.quote{margin-top:6px;padding-left:10px;border-left:2px solid var(--border-solid);
 color:var(--ink-2);font-size:12.5px;font-style:italic}
.note{color:var(--ink-2);font-size:12.5px;margin-top:10px}
.warn{background:var(--warn-bg);border:1px solid var(--warn-br);border-radius:9px;
 padding:12px 14px;margin:10px 0;font-size:13.5px}
.warn ul{margin:6px 0 0;padding-left:18px}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--ink-2);
 margin-top:2px}
.sw{display:inline-block;width:13px;height:3px;border-radius:2px;margin-right:6px;
 vertical-align:middle}
.sw.px{background:var(--series-1)} .sw.ma50{background:var(--series-2)}
.sw.ma200{background:var(--muted)} .sw.vol{background:var(--good);height:9px}
.sw.fv{background:var(--series-2)}
.sw.band{background:var(--band);height:10px;border:1px solid var(--series-2)}
.findings li,.falsifiers li{margin:6px 0}
.src{color:var(--muted);font-size:11.5px}
.src a{color:inherit}
.thumb-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:10px 0}
.thumb-grid figure{margin:0;border:1px solid var(--border);padding:8px;background:var(--page)}
.thumb-grid img{display:block;width:100%;height:auto}
.thumb-grid figcaption{font-size:11px;color:var(--muted);margin-top:5px;overflow-wrap:anywhere}
.qa td:nth-child(1){white-space:nowrap;font-weight:600}
.target-hero.unavailable .v{color:var(--muted)}
.target-hero{text-align:center;padding:18px 0 6px}
.target-hero .k{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;
 color:var(--muted);font-weight:600}
.target-hero .v{font-size:40px;font-weight:700;font-variant-numeric:tabular-nums;
 line-height:1.15}
.target-hero .s{font-size:12.5px;color:var(--ink-2)}
.mini .sub,li .sub{font-weight:400;color:var(--muted);font-size:12px}
table.scen{width:100%;border-collapse:collapse;margin:14px 0;font-size:13.5px}
table.scen th,table.scen td{padding:9px 10px;border-bottom:1px solid var(--border);
vertical-align:top;text-align:left}
table.scen th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
table.scen td.n,table.scen th.n{text-align:right;font-variant-numeric:tabular-nums;
white-space:nowrap}
table.scen td.q{font-weight:620}
table.sens td.q{text-align:right}
table.sens tbody td{text-align:right}
.scroll{overflow-x:auto}
.cases{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:14px}
.case{padding:14px 16px;border-radius:10px;border:1px solid var(--border)}
.case.up{background:var(--good-bg)} .case.down{background:var(--bad-bg)}
.case p{font-size:13.5px;margin-bottom:8px}
details{margin:10px 0;font-size:13px}
summary{cursor:pointer;color:var(--ink-2)}
details ul{margin:8px 0 0;padding-left:18px;color:var(--ink-2)}
nav{position:sticky;top:0;background:var(--page);padding:10px 0;margin-bottom:14px;
 z-index:9;border-bottom:1px solid var(--border);display:flex;gap:14px;
 flex-wrap:wrap;font-size:12.5px}
nav a{color:var(--ink-2);text-decoration:none}
nav a:hover{color:var(--ink)}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:28px;
 line-height:1.7}
svg .g{stroke:var(--grid);stroke-width:1}
svg .tk{fill:var(--muted);font-size:10.5px;font-variant-numeric:tabular-nums}
svg .tk.est{fill:var(--series-2);font-size:9.5px}
svg .tk.lbl{font-size:11px;font-weight:600}
svg .px{fill:none;stroke:var(--series-1);stroke-width:1.9;stroke-linejoin:round}
svg .fv{fill:none;stroke:var(--series-2);stroke-width:1.9;stroke-linejoin:round}
svg .ma50{fill:none;stroke:var(--series-2);stroke-width:1.4;opacity:.9}
svg .ma200{fill:none;stroke:var(--muted);stroke-width:1.4;opacity:.9}
svg .band{fill:var(--band);stroke:none}
svg .dot-px{fill:var(--series-1);stroke:var(--surface);stroke-width:2}
svg .sc-lbl{fill:var(--ink);font-size:12.5px}
svg .sc-num{fill:var(--ink);font-size:12px;font-weight:640;
 font-variant-numeric:tabular-nums}
svg .sc-wt{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
@media (max-width:640px){.cases{grid-template-columns:1fr}
 .id{flex-direction:column}.verdict{text-align:left}
 table{table-layout:fixed;width:100%;overflow-wrap:anywhere}
 th,td{padding:7px 6px;overflow-wrap:anywhere}
 .svd td.q,.qa td:nth-child(1){white-space:normal}}
"""

LIGHT = """--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink-2:#52514e;
--muted:#898781;--grid:#e1e0d9;--border:rgba(11,11,11,.10);--border-solid:#d8d7d0;
--series-1:#2a78d6;--series-2:#eb6834;--band:rgba(235,104,52,.13);
--good:#0ca30c;--bad:#d03b3b;--good-bg:rgba(12,163,12,.07);--bad-bg:rgba(208,59,59,.06);
--warn-bg:rgba(250,178,25,.10);--warn-br:rgba(250,178,25,.45);"""

DARK = """--page:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink-2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--border:rgba(255,255,255,.10);--border-solid:#3a3a37;
--series-1:#3987e5;--series-2:#d95926;--band:rgba(217,89,38,.20);
--good:#0ca30c;--bad:#e05a5a;--good-bg:rgba(12,163,12,.10);--bad-bg:rgba(224,90,90,.10);
--warn-bg:rgba(250,178,25,.10);--warn-br:rgba(250,178,25,.40);"""


def render(bundle, series, analysis, folder=None):
    rating = validate(analysis, bundle)
    score = composite(analysis["scorecard"]) or 0.0
    meta = bundle["meta"]

    price_svg = charts.price_chart(
        {"series": (series or {}).get("technicals")} if series.get("technicals") else None)
    rev_svg = charts.estimates_chart(series.get("finviz_annual"), "revenue")
    eps_svg = charts.estimates_chart(series.get("finviz_annual"), "eps")
    revisions_svg = charts.revisions_chart(series.get("finviz_revisions"))
    reactions_svg = charts.reactions_chart(series.get("price_reactions"))
    fv_svg = charts.fair_value_chart(
        {**(bundle.get("fair_value") or {}), "series": (series or {}).get("fair_value")}
        if bundle.get("fair_value") else None)
    score_svg = charts.scorecard_chart(analysis["scorecard"])

    unavailable = [r for r in analysis["scorecard"] if r.get("unavailable")]
    banner = ""
    contract_warnings = analysis.get("_contract_warnings") or []
    if unavailable or str(analysis["conviction"]).lower() == "low" or contract_warnings:
        names = ", ".join(r["dimension"] for r in unavailable)
        banner = ('<div class="warn"><strong>Read this call with extra caution.</strong> '
                  + (f'These inputs were unavailable or refused: {esc(names)}. ' if names else "")
                  + (f'{esc(" ".join(contract_warnings))} ' if contract_warnings else "")
                  + 'A call is still made — the premise of this dashboard is that a '
                    'decision has to be made on incomplete information — but conviction '
                    'is correspondingly low.</div>')

    # (id, nav label, heading, body). A section with an empty body is dropped,
    # and the nav is built from the survivors so it can never point at nothing.
    planned = [
        ("call", "The call", "The call",
         banner + paragraphs(analysis["thesis"]) + build_scorecard(analysis, score_svg)),
        ("business", "Business", "What this company does",
         paragraphs(analysis["company_explainer"]) + _segments_table(bundle)),
        ("technicals", "Price", "Price and technical setup",
         build_technicals(bundle, analysis, price_svg)),
        ("financials", "Financials", "Financial history and what is expected next",
         build_financials(bundle, analysis, rev_svg, eps_svg)),
        ("valuation", "Fair value", "Fair value",
         build_fair_value(bundle, analysis, fv_svg)),
        ("earnings-call", "Earnings call", "The earnings call",
         build_call_section(bundle, analysis, folder)),
        ("street", "The street", "Estimates and the street",
         build_street(bundle, analysis, revisions_svg) +
         (f'<h3>How it trades through its prints</h3><div class="fig">{reactions_svg}</div>'
          if reactions_svg else "")),
        ("market-context", "Market context", "Market and macro context",
         build_market_context(bundle, analysis)),
        ("forecast", "Forecast", "Our forecast", build_forecast(analysis)),
        ("own-estimate", "Our estimate", "Our own estimate versus the street",
         sf_estimate_render.build(bundle, analysis, folder)),
        ("evidence", "Market evidence", "Market evidence",
         sf_evidence_render.build(bundle, analysis, folder)),
        ("scenarios", "Scenarios", "Scenario analysis",
         build_scenarios(bundle, analysis)),
        ("falsifiers", "What would change our mind", "What would change our mind",
         build_falsifiers(analysis)),
    ]
    live = [(i, nav_label, heading, html_body) for i, nav_label, heading, html_body
            in planned if html_body and html_body.strip()]
    nav = "".join(f'<a href="#{i}">{esc(label)}</a>' for i, label, _, _ in live)

    body = [build_header(bundle, analysis, rating, score), f"<nav>{nav}</nav>"]
    body += [section(i, heading, html_body) for i, _, heading, html_body in live]

    stamp = meta.get("collected_at")
    footer = (f'Data collected {esc(stamp)} · depth {esc(meta.get("depth"))}<br>'
              f'This is a forecast built from public information, '
              f'not a prediction and not investment advice. '
              f'The reasoning above is shown so you can disagree with it.')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(meta['ticker'])} — forecast dashboard</title>
<style>
:root{{color-scheme:light;{LIGHT}}}
:root[data-theme="light"]{{{LIGHT}}}
{CSS}
</style></head><body><div class="wrap">
{"".join(body)}
<footer>{footer}</footer>
</div></body></html>"""


def _segments_table(bundle):
    groups = bundle.get("segments_summary") or []
    if not groups:
        return ""
    parts = []
    for group in groups[:2]:
        rows = [r for r in group["rows"] if r.get("latest") is not None]
        if not rows:
            continue
        parts.append(f'<h3>{esc(group.get("title") or "Segments")}</h3>')
        parts.append('<table><thead><tr><th>Line</th><th class="n">Latest</th>'
                     '<th class="n">Prior</th></tr></thead><tbody>' +
                     "".join(f'<tr><td>{esc(r["label"])}</td><td class="n">{esc(r["latest"])}</td>'
                             f'<td class="n">{esc(r.get("prior"))}</td></tr>' for r in rows) +
                     "</tbody></table>")
    return "".join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="render.py")
    parser.add_argument("bundle_dir")
    parser.add_argument("-o", "--out")
    parser.add_argument("--analysis", help="alternate analysis file inside the bundle, "
                        "e.g. analysis-v2.json, so revisions can sit beside the original")
    args = parser.parse_args(argv)

    folder = Path(args.bundle_dir)
    bundle = json.loads((folder / "bundle.json").read_text(encoding="utf-8"))
    series_path = folder / "series.json"
    series = json.loads(series_path.read_text(encoding="utf-8")) if series_path.exists() else {}
    analysis_path = folder / (args.analysis or "analysis.json")
    if not analysis_path.exists():
        raise SystemExit(
            f"no analysis.json in {folder}.\n"
            "Stage 2 is the model's job: read READ-ME-FIRST.md, then write the "
            "analysis. The page will not render without it.")
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))

    out = args.out or f"{bundle['meta']['ticker']}-forecast.html"
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(bundle, series, analysis, folder), encoding="utf-8")
    print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
