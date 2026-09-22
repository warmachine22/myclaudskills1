"""Per-page extractors and markdown renderers for stockanalysis.com.

Each `cmd_*` builds a plain dict (the JSON shape) and hands it to `sa.emit`
together with a markdown renderer. Markdown is the default because it is
dense, self-labelling and cheap for a model to read; JSON is there for
programmatic use.
"""

from __future__ import annotations

import sys

import sa_core as sa
from sa_core import human, md_table

# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _base(args) -> str:
    return sa.resolve_base(args.ticker)


def _get(args, suffix: str = "", params=None, kind="default"):
    """Fetch <base><suffix>/__data.json for the ticker in `args`."""
    path = _base(args) + suffix.lstrip("/")
    return sa.fetch_data(path, params=params, kind=kind,
                         refresh=getattr(args, "refresh", False))


def _tkr(info: dict) -> str:
    """Non-US `/quote/` symbols leave `ticker` null; `uid` is always set."""
    return info.get("ticker") or info.get("uid") or (info.get("symbol") or "").upper()


def _hdr(info: dict, section: str) -> str:
    q = info.get("quote") or {}
    bits = [f"# {info.get('nameFull') or info.get('name')} ({_tkr(info)}) — {section}"]
    if q.get("p") is not None:
        chg = q.get("cp")
        arrow = "" if chg is None else f" ({chg:+.2f}%)"
        bits.append(f"**{q['p']}** {info.get('curr', {}).get('price', '')}{arrow} · "
                    f"{info.get('exchange', '')} · as of {q.get('u', 'n/a')}")
    return "\n".join(bits)


def _emit(args, obj, md_fn):
    sa.emit(obj, args.format, md_fn, getattr(args, "out", None))


def _pick(d: dict, *keys):
    return {k: d.get(k) for k in keys if k in d}


# The overview's `changes` block holds the *price as of* each lookback point
# (price1w = close one week ago), not a percentage. Convert to returns.
_PERIOD_LABELS = {
    "price1d": "1 day", "price1w": "1 week", "price1m": "1 month",
    "price3m": "3 months", "price6m": "6 months", "priceYTD": "YTD",
    "price1y": "1 year", "price3y": "3 years", "price5y": "5 years",
    "price10y": "10 years", "priceMAX": "All time",
}


def _performance(changes, current):
    if not isinstance(changes, dict) or not current:
        return []
    out = []
    for k, label in _PERIOD_LABELS.items():
        past = changes.get(k)
        if not isinstance(past, (int, float)) or past <= 0:
            continue
        out.append({"period": label, "price_then": past,
                    "change_pct": (current / past - 1) * 100})
    return out


# ---------------------------------------------------------------------------
# overview / quote / news
# ---------------------------------------------------------------------------


def _overview_payload(args):
    nodes = _get(args, kind="overview")
    info = sa.symbol_info(nodes)
    p = sa.page_node(nodes, want_keys=("marketCap", "analystChart"))
    return info, p


def cmd_quote(args):
    info, _ = _overview_payload(args)
    q = info.get("quote") or {}
    obj = {
        "ticker": _tkr(info), "name": info.get("nameFull"),
        "exchange": info.get("exchange"), "currency": (info.get("curr") or {}).get("price"),
        "price": q.get("p"), "change": q.get("c"), "change_pct": q.get("cp"),
        "open": q.get("o"), "high": q.get("h"), "low": q.get("l"),
        "prev_close": q.get("cl"), "volume": q.get("v"),
        "week52_high": q.get("h52"), "week52_low": q.get("l52"),
        "as_of": q.get("u"), "market_state": q.get("ms"),
        "extended_price": q.get("ep"), "extended_change_pct": q.get("ecp"),
        "extended_session": q.get("es"), "extended_as_of": q.get("eu"),
    }

    def md(o):
        lines = [f"# {o['name']} ({o['ticker']}) — quote",
                 f"**{o['price']} {o['currency'] or ''}**  {o['change']:+} ({o['change_pct']:+.2f}%)"
                 if o["price"] is not None and o["change"] is not None else "",
                 f"as of {o['as_of']} · market {o['market_state']}", ""]
        rows = [["Open", o["open"]], ["High", o["high"]], ["Low", o["low"]],
                ["Prev close", o["prev_close"]], ["Volume", human(o["volume"], 0)],
                ["52-week range", f"{o['week52_low']} – {o['week52_high']}"]]
        if o.get("extended_price"):
            rows.append([o.get("extended_session") or "Extended",
                         f"{o['extended_price']} ({o['extended_change_pct']:+.2f}%)"])
        lines.append(md_table(["Field", "Value"], rows))
        return "\n".join(x for x in lines if x != "")

    _emit(args, obj, md)


def _news_items(p, limit=None):
    news = p.get("news") or {}
    data = news.get("data") if isinstance(news, dict) else news
    out = []
    for a in (data or [])[:limit]:
        out.append({
            "title": a.get("title"), "url": a.get("url"),
            "source": a.get("source") or a.get("sourceName"),
            "published": a.get("timeFormatted") or a.get("time") or a.get("date"),
            "summary": a.get("text"),
        })
    return out


def _news_md(items) -> str:
    out = []
    for a in items:
        meta = " · ".join(x for x in (a.get("source"), a.get("published")) if x)
        out.append(f"### {a['title']}\n{meta}\n\n{(a.get('summary') or '').strip()}\n\n<{a.get('url')}>")
    return "\n\n".join(out)


def cmd_news(args):
    info, p = _overview_payload(args)
    items = _news_items(p)
    obj = {"ticker": _tkr(info), "count": len(items), "articles": items}

    def md(o):
        return _hdr(info, "recent news") + f"\n\n_{o['count']} articles_\n\n" + _news_md(o["articles"])

    _emit(args, obj, md)


def _info_table(raw):
    """Three shapes in the wild: stocks give `[{t,v,u}]`, ETFs give
    `[[label, value]]`, and the dividend tab gives a flat dict."""
    if isinstance(raw, dict):
        return dict(raw)
    out = {}
    for r in raw or []:
        if isinstance(r, dict):
            out[r.get("t")] = r.get("v")
        elif isinstance(r, (list, tuple)) and len(r) >= 2:
            out[r[0]] = r[1]
    return out


def _etf_overview(args, info, p):
    obj = {
        "ticker": _tkr(info), "name": info.get("nameFull"), "instrument": "ETF",
        "exchange": info.get("exchange"), "currency": (info.get("curr") or {}).get("price"),
        "quote": _pick(info.get("quote") or {}, "p", "c", "cp", "o", "h", "l",
                       "cl", "v", "h52", "l52", "u", "ms"),
        "aum": p.get("aum"), "nav": p.get("nav"),
        "expense_ratio": p.get("expenseRatio"), "pe_ratio": p.get("peRatio"),
        "shares_out": p.get("sharesOut"), "beta": p.get("beta"),
        "inception": p.get("inception"), "holdings_count": p.get("holdings"),
        "dividend_per_share": p.get("dps"), "dividend_yield": p.get("dividendYield"),
        "payout_frequency": p.get("payoutFrequency"), "ex_dividend_date": p.get("exDivDate"),
        "profile_facts": _info_table(p.get("infoTable")),
        "performance": p.get("performance") or {},
        "description": p.get("description"),
        "website": p.get("etf_website"),
        "top_holdings": (p.get("holdingsTable") or {}).get("holdings") or [],
        "holdings_updated": (p.get("holdingsTable") or {}).get("updated"),
        "top10_pct": (p.get("holdingsTable") or {}).get("top10"),
        "news": _news_items(p, 10),
    }

    def md(o):
        L = [_hdr(info, "ETF overview"), "",
             md_table(["Metric", "Value"],
                      [["AUM", o["aum"]], ["NAV", o["nav"]],
                       ["Expense ratio", o["expense_ratio"]], ["PE ratio", o["pe_ratio"]],
                       ["Shares out", o["shares_out"]], ["Beta", o["beta"]],
                       ["Inception", o["inception"]], ["# holdings", o["holdings_count"]],
                       ["Dividend / share", o["dividend_per_share"]],
                       ["Dividend yield", o["dividend_yield"]],
                       ["Payout frequency", o["payout_frequency"]],
                       ["Ex-dividend", o["ex_dividend_date"]]]), ""]
        if o["profile_facts"]:
            L += ["## Profile", md_table(["Field", "Value"], list(o["profile_facts"].items())), ""]
        if o["performance"]:
            L += ["## Performance",
                  md_table(["Period", "Return"],
                           [[k, human(v, 2, pct=True)] for k, v in o["performance"].items()]), ""]
        if o["top_holdings"]:
            L += [f"## Top holdings (as of {o['holdings_updated']}, top 10 = {o['top10_pct']}%)",
                  md_table(["Name", "Ticker", "Weight", "Shares"],
                           [[h.get("n"), h.get("s"), h.get("as"), h.get("sh")]
                            for h in o["top_holdings"][:25]]), ""]
        if o["description"]:
            L += ["## Description", sa.strip_html(o["description"]), ""]
        if o["news"]:
            L += ["## Recent news", _news_md(o["news"]), ""]
        return "\n".join(L)

    _emit(args, obj, md)


def _overview_obj(info, p):
    return {
        "ticker": _tkr(info), "name": info.get("nameFull"),
        "exchange": info.get("exchange"), "cik": info.get("cik"),
        "ipo_date": info.get("ipoDate"),
        "currency": (info.get("curr") or {}).get("price"),
        "quote": _pick(info.get("quote") or {}, "p", "c", "cp", "o", "h", "l",
                       "cl", "v", "h52", "l52", "u", "ms", "ep", "ecp", "es"),
        "market_cap": p.get("marketCap"),
        "market_cap_growth_pct": p.get("marketCapGrowth"),
        "revenue": p.get("revenue"), "revenue_basis": p.get("revenue_type"),
        "revenue_growth_pct": p.get("revenueGrowth"),
        "net_income": p.get("netIncome"),
        "net_income_growth_pct": p.get("netIncomeGrowth"),
        "shares_out": p.get("sharesOut"),
        "eps": p.get("eps"), "eps_growth_pct": p.get("epsGrowth"),
        "pe_ratio": p.get("peRatio"), "forward_pe": p.get("forwardPE"),
        "dividend": p.get("dividend"), "ex_dividend_date": p.get("exDividendDate"),
        "beta": p.get("beta"),
        "analyst_consensus": p.get("analysts"), "analyst_target": p.get("target"),
        "analyst_target_detail": p.get("analystTarget"),
        "analyst_ratings": p.get("analystChart"),
        "analyst_summary": p.get("analystIntro"),
        "next_earnings_date": p.get("earningsDate"),
        "description": p.get("description"),
        "profile_facts": _info_table(p.get("infoTable")),
        "financial_summary": p.get("financialIntro"),
        "annual_history": p.get("financialChart"),
        "performance": _performance(p.get("changes"), (info.get("quote") or {}).get("p")),
        "news": _news_items(p, 10),
        "source": "stockanalysis.com",
        "data_provider": ((p.get("trust") or {}).get("summary") or {}).get("text"),
    }


def _overview_md(o) -> str:
    L = [f"# {o['name']} ({o['ticker']}) — overview",
         f"{o['exchange']} · {o['currency']} · IPO {o['ipo_date']} · CIK {o['cik']}", ""]
    q = o["quote"]
    if q.get("p") is not None:
        L += [f"**Price {q['p']}** {q.get('c', 0):+} ({q.get('cp', 0):+.2f}%) — as of {q.get('u')}",
              f"Day {q.get('l')}–{q.get('h')} · 52wk {q.get('l52')}–{q.get('h52')} · Vol {human(q.get('v'), 0)}", ""]
    L += ["## Key figures", md_table(
        ["Metric", "Value", "YoY"],
        [["Market cap", o["market_cap"], human(o["market_cap_growth_pct"], 1, pct=True)],
         [f"Revenue ({o['revenue_basis'] or ''})", o["revenue"], human(o["revenue_growth_pct"], 1, pct=True)],
         ["Net income", o["net_income"], human(o["net_income_growth_pct"], 1, pct=True)],
         ["EPS", o["eps"], human(o["eps_growth_pct"], 1, pct=True)],
         ["Shares out", o["shares_out"], ""],
         ["PE ratio", o["pe_ratio"], ""],
         ["Forward PE", o["forward_pe"], ""],
         ["Beta", o["beta"], ""],
         ["Dividend", o["dividend"], ""],
         ["Ex-dividend", o["ex_dividend_date"], ""],
         ["Next earnings", o["next_earnings_date"], ""]]), ""]
    if o["profile_facts"]:
        L += ["## Profile", md_table(["Field", "Value"], list(o["profile_facts"].items())), ""]
    if o["performance"]:
        L += ["## Price performance",
              md_table(["Period", "Price then", "Change"],
                       [[r["period"], r["price_then"], human(r["change_pct"], 2, pct=True)]
                        for r in o["performance"]]), ""]
    ac = o["analyst_ratings"] or {}
    L += ["## Analyst view",
          f"Consensus: **{o['analyst_consensus']}** · Target {o['analyst_target']}"]
    if ac:
        L.append("Ratings: " + ", ".join(f"{k} {v}" for k, v in ac.items()))
    if o["analyst_summary"]:
        L.append("\n" + o["analyst_summary"])
    L.append("")
    if o["financial_summary"]:
        L += ["## Financial summary", o["financial_summary"], ""]
    if o["annual_history"]:
        rows = [[r.get("year"), human(r.get("revenue")), human(r.get("revenueGrowth"), 1, pct=True),
                 human(r.get("earnings")), human(r.get("earningsGrowth"), 1, pct=True)]
                for r in o["annual_history"]]
        L += [md_table(["FY", "Revenue", "Rev growth", "Earnings", "Earn growth"], rows), ""]
    if o["description"]:
        L += ["## Business", o["description"], ""]
    if o["news"]:
        L += ["## Recent news", _news_md(o["news"]), ""]
    L += ["---", f"Source: stockanalysis.com. {o.get('data_provider') or ''}"]
    return "\n".join(L)


def cmd_overview(args):
    info, p = _overview_payload(args)
    if (info.get("type") or "").lower() == "etf":
        return _etf_overview(args, info, p)
    _emit(args, _overview_obj(info, p), _overview_md)


# ---------------------------------------------------------------------------
# financials
#
# Payloads are COLUMN-oriented: `financialData` maps a line-item id to a list
# of values aligned with `datekey` (newest first). `map` is the ordered row
# spec -- it owns display labels, section breaks and number formats, and may
# name ids that carry no data (render those blank).
# ---------------------------------------------------------------------------

_STATEMENT_PATHS = {
    "overview": "financials/",
    "income": "financials/income-statement/",
    "balance": "financials/balance-sheet/",
    "cash-flow": "financials/cash-flow-statement/",
    "ratios": "financials/ratios/",
}


def _fmt_cell(v, fmt):
    if v is None:
        return ""
    if fmt == "percentage":
        return f"{v * 100:,.2f}%" if isinstance(v, (int, float)) else str(v)
    if fmt in ("pershare", "divpershare"):
        return f"{v:,.3f}".rstrip("0").rstrip(".") if isinstance(v, (int, float)) else str(v)
    if fmt == "ratio":
        return f"{v:,.2f}" if isinstance(v, (int, float)) else str(v)
    return human(v)


def _growth_series(values, prior):
    """YoY growth for each column, using `prior` to extend past the last one.

    The site never ships growth pre-computed; it derives it client-side from
    financialData + prior. Columns are newest-first, so the comparison base for
    column i is column i+1 (annual) -- and for quarterly the site's own growth
    rows are still period-over-prior-column, which is what `prior` extends.
    """
    seq = list(values) + list(prior or [])
    out = []
    for i in range(len(values)):
        cur, base = seq[i], seq[i + 1] if i + 1 < len(seq) else None
        if isinstance(cur, (int, float)) and isinstance(base, (int, float)) and base != 0:
            out.append((cur - base) / abs(base) * 100)
        else:
            out.append(None)
    return out


def _financials_table(p, limit=0, with_growth=True):
    fd = sa.depro(p.get("financialData") or {})
    prior = sa.depro(p.get("prior") or {})
    rows_spec = p.get("map") or []
    dates = fd.get("datekey") or []
    fy = fd.get("fiscalYear") or []
    fq = fd.get("fiscalQuarter") or []
    n = len(dates)
    keep = min(limit, n) if limit else n

    periods = []
    for i in range(keep):
        label = dates[i]
        if label != "TTM" and i < len(fy):
            label = f"FY{fy[i]}" + (f" {fq[i]}" if fq[i] and fq[i] != "Q4" else "")
            if p.get("period") == "quarterly" and i < len(fq):
                label = f"{fq[i]} FY{fy[i]}"
        periods.append({"label": label, "date": dates[i],
                        "fiscal_year": fy[i] if i < len(fy) else None,
                        "fiscal_quarter": fq[i] if i < len(fq) else None})

    rows, section = [], None
    for spec in rows_spec:
        rid = spec.get("id")
        if spec.get("sectionStart"):
            section = spec["sectionStart"]
        vals = fd.get(rid)
        if vals is None:
            continue  # map row with no data for this company
        row = {"id": rid, "title": spec.get("title") or rid,
               "section": section, "format": spec.get("format"),
               "values": vals[:keep]}
        g = spec.get("growth")
        if with_growth and g:
            row["growth_title"] = g.get("title")
            row["growth"] = _growth_series(vals, prior.get(rid))[:keep]
            row["growth_inverted"] = g.get("format") == "inverted-growth"
        rows.append(row)
    return periods, rows


def _financials_md(o) -> str:
    L = [o["_header"], "",
         f"**{o['statement']}** · {o['period']} · {o['currency'] or ''} · "
         f"fiscal year {o['fiscal_year_span'] or 'n/a'}",
         f"_{len(o['periods'])} periods shown; {o['periods_available'] or '?'} exist "
         f"server-side (older ones are behind the site's Pro tier)_", ""]
    heads = ["Line item"] + [p["label"] for p in o["periods"]]
    body, section = [], object()
    for r in o["rows"]:
        if r["section"] != section:
            section = r["section"]
            if section:
                body.append([f"**{section}**"] + [""] * len(o["periods"]))
        body.append([r["title"]] + [_fmt_cell(v, r["format"]) for v in r["values"]])
        if r.get("growth"):
            sign = -1 if r.get("growth_inverted") else 1
            body.append(["· " + (r["growth_title"] or "Growth (YoY)")] +
                        [("" if g is None else f"{sign * g:+,.1f}%") for g in r["growth"]])
    L.append(md_table(heads, body))
    L += ["", "Absolute figures are in units of the reporting currency (full dollars). "
          "Growth rows are derived, not reported.",
          f"Source: {o['source_name']} via stockanalysis.com · last updated {o['last_updated']}"]
    return "\n".join(L)


def _fin_overview(args, info, p):
    """The /financials/ route is a chart page, not a statement: data lives in
    `sections`, and it is the only place segment revenue is exposed."""
    sections = []
    for s in sa.depro(p.get("sections") or []):
        data = s.get("data") or {}
        dates = data.get("datekey") or []
        fy = data.get("fiscalYear") or []
        rows = []
        for spec in s.get("rows") or []:
            rid = spec.get("id")
            if rid in data:
                rows.append({"id": rid, "title": spec.get("title") or rid,
                             "is_total": bool(spec.get("isTotal")),
                             "values": data[rid],
                             "ttm": (s.get("ttm") or {}).get(rid)})
        sections.append({
            "id": s.get("id"), "title": s.get("title"), "kind": s.get("kind"),
            "ttm_label": s.get("ttmLabel") or "TTM",
            "ttm_date": (s.get("ttm") or {}).get("datekey"),
            "periods": [f"FY{y}" for y in fy] or dates, "dates": dates, "rows": rows,
        })
    obj = {"ticker": _tkr(info), "statement": "overview",
           "period": p.get("period"), "sections": sections,
           "currency": (p.get("details") or {}).get("currency"),
           "fiscal_year_span": (p.get("details") or {}).get("fiscalYear"),
           "_header": _hdr(info, "financials overview")}

    def md(o):
        L = [o["_header"], "", f"_{o['period']} · fiscal year {o['fiscal_year_span']}_", ""]
        for s in o["sections"]:
            L.append(f"## {s['title']}")
            heads = ["Line item"] + s["periods"] + [f"{s['ttm_label']} ({s['ttm_date'] or ''})"]
            body = [[("**%s**" % r["title"]) if r["is_total"] else r["title"]]
                    + [human(v) for v in r["values"]] + [human(r["ttm"])]
                    for r in s["rows"]]
            L += [md_table(heads, body), ""]
        L.append("Segment breakdowns live in this overview only — there is no "
                 "standalone segments page.")
        return "\n".join(L)

    _emit(args, obj, md)


def cmd_financials(args):
    path = _STATEMENT_PATHS[args.statement]
    nodes = _get(args, path, params={"p": args.period}, kind="financials")
    info = sa.symbol_info(nodes)
    p = sa.page_node(nodes, ("financialData", "sections", "statement"))

    if args.statement == "overview":
        return _fin_overview(args, info, p)

    # `?p=` silently falls back to annual when unrecognised -- report what we
    # actually got rather than what we asked for.
    got = p.get("period")
    if got and args.period != "annual" and got not in (args.period, "ttm"):
        print(f"note: requested period={args.period}, site returned {got}", file=sys.stderr)

    periods, rows = _financials_table(p, args.limit)
    details = p.get("details") or {}
    trust = p.get("trust") or {}
    obj = {
        "ticker": _tkr(info), "name": info.get("nameFull"),
        "statement": (p.get("head") or {}).get("heading") or args.statement,
        "period": got, "currency": details.get("currency") or (info.get("curr") or {}).get("financial"),
        "fiscal_year_span": details.get("fiscalYear"),
        "last_trailing_date": details.get("lastTrailingDate"),
        "periods_available": p.get("full_count"),
        "source_name": (trust.get("sources") or [{}])[0].get("name"),
        "last_updated": trust.get("lastUpdated"),
        "periods": periods, "rows": rows,
        "_header": _hdr(info, f"{(p.get('head') or {}).get('heading') or args.statement}"
                              f" ({got or args.period})"),
    }
    _emit(args, obj, _financials_md)


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------

_STAT_GROUP_TITLES = {
    "valuation": "Valuation", "dates": "Key dates", "shares": "Share statistics",
    "ratios": "Valuation ratios", "evRatios": "Enterprise value ratios",
    "financialPosition": "Financial position", "financialEfficiency": "Financial efficiency",
    "taxes": "Taxes", "stockPrice": "Stock price statistics",
    "shortSelling": "Short selling", "incomeStatement": "Income statement",
    "balanceSheet": "Balance sheet", "cashFlow": "Cash flow", "margins": "Margins",
    "dividends": "Dividends & yields", "analystForecasts": "Analyst forecasts",
    "stockSplits": "Stock splits", "scores": "Financial health scores",
    "fairValue": "Fair value estimates",
}


def cmd_statistics(args):
    nodes = _get(args, "statistics/", kind="statistics")
    info = sa.symbol_info(nodes)
    p = sa.page_node(nodes, ("valuation", "margins"))
    groups = []
    for key, g in p.items():
        if key == "trust" or not isinstance(g, dict) or "data" not in g:
            continue
        groups.append({
            "key": key, "title": _STAT_GROUP_TITLES.get(key, key),
            "note": g.get("text"),
            "rows": [{"id": r.get("id"), "label": r.get("title"),
                      "value": r.get("value"), "precise": r.get("hover")}
                     for r in g.get("data") or []],
        })
    trust = p.get("trust") or {}
    obj = {"ticker": _tkr(info), "name": info.get("nameFull"),
           "as_of": (info.get("quote") or {}).get("u"),
           "source_name": (trust.get("sources") or [{}])[0].get("name"),
           "groups": groups}

    def md(o):
        L = [_hdr(info, "statistics"), ""]
        for g in o["groups"]:
            L.append(f"## {g['title']}")
            L.append(md_table(["Metric", "Value", "Precise"],
                              [[r["label"], r["value"],
                                r["precise"] if r["precise"] != r["value"] else ""]
                               for r in g["rows"]]))
            L.append("")
        L.append(f"Values are the site's display strings; `Precise` is its full-precision "
                 f"form. Source: {o['source_name']}.")
        return "\n".join(L)

    _emit(args, obj, md)


# ---------------------------------------------------------------------------
# forecast
# ---------------------------------------------------------------------------

_EST_ROWS = [
    ("revenue", "Revenue", "num"), ("revenueGrowth", "Revenue growth", "pct"),
    ("eps", "EPS", "ps"), ("epsGrowth", "EPS growth", "pct"),
    ("adjustedEps", "Adjusted EPS", "ps"), ("adjustedEpsGrowth", "Adj. EPS growth", "pct"),
    ("netIncome", "Net income", "num"), ("grossProfit", "Gross profit", "num"),
    ("grossMargin", "Gross margin", "pct"), ("operatingIncome", "Operating income", "num"),
    ("freeCashFlow", "Free cash flow", "num"), ("dps", "Dividend per share", "ps"),
    ("peForward", "Forward PE", "ratio"), ("analysts", "# analysts", "int"),
]


def _est_cell(v, kind):
    if v is None:
        return ""
    if kind == "pct":
        return f"{v:,.1f}%" if isinstance(v, (int, float)) else str(v)
    if kind in ("ps", "ratio"):
        return f"{v:,.2f}" if isinstance(v, (int, float)) else str(v)
    if kind == "int":
        return f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)
    return human(v)


def _estimate_table(tbl):
    """Column-oriented -> list of periods. `lastDate` is the index of the last
    REPORTED period; everything after it is an estimate."""
    tbl = sa.depro(tbl or {})
    dates = tbl.get("dates") or []
    last = tbl.get("lastDate")
    last = last if isinstance(last, int) else -1
    fy, fq = tbl.get("fiscalYear") or [], tbl.get("fiscalQuarter") or []
    cols = []
    for i, d in enumerate(dates):
        q = fq[i] if i < len(fq) else ""
        y = fy[i] if i < len(fy) else ""
        cols.append({
            "label": (f"{q} FY{y}" if q else f"FY{y}") or d,
            "period_end": d, "fiscal_year": y, "fiscal_quarter": q or None,
            "is_estimate": i > last,
            "values": {k: tbl.get(k, [None] * len(dates))[i] for k, _, _ in _EST_ROWS
                       if isinstance(tbl.get(k), list)},
        })
    return cols


def _est_md(title, cols) -> str:
    # Far-out estimate columns are entirely Pro-gated; rendering a wall of empty
    # cells buys nothing, so drop columns that carry no data at all.
    dropped = len(cols)
    cols = [c for c in cols if any(v is not None for v in c["values"].values())]
    dropped -= len(cols)
    if not cols:
        return ""
    heads = ["Line item"] + [c["label"] + ("*" if c["is_estimate"] else "") for c in cols]
    body = []
    for key, label, kind in _EST_ROWS:
        if not any(c["values"].get(key) is not None for c in cols):
            continue
        body.append([label] + [_est_cell(c["values"].get(key), kind) for c in cols])
    note = "_* = analyst estimate; unmarked columns are reported actuals."
    if dropped:
        note += f" {dropped} further estimate period(s) exist but are behind the site's Pro tier."
    return f"### {title}\n" + md_table(heads, body) + "\n\n" + note + "_"


def cmd_forecast(args):
    nodes = _get(args, "forecast/", kind="forecast")
    info = sa.symbol_info(nodes)
    p = sa.page_node(nodes, ("estimates", "currentRatings"))
    est = p.get("estimates") or {}
    cr = p.get("currentRatings") or {}
    pt = p.get("priceTargets") or {}
    tg = p.get("targets") or {}
    price = (info.get("quote") or {}).get("p")
    avg = pt.get("avg") or tg.get("average")

    charts = {}
    for k, v in (p.get("estimatesCharts") or {}).items():
        charts[k] = {d: sa.depro(x) for d, x in (v or {}).items() if isinstance(x, dict)}

    obj = {
        "ticker": _tkr(info), "name": info.get("nameFull"),
        "price": price, "currency": pt.get("currency") or tg.get("currency"),
        "ratings": {"consensus": cr.get("consensus"), "analyst_count": cr.get("count"),
                    "score": cr.get("score"),
                    "breakdown": _pick(cr, "strongBuy", "buy", "hold", "sell", "strongSell")},
        "price_target": {
            "average": avg, "median": pt.get("median") or tg.get("median"),
            "low": pt.get("low"), "high": pt.get("high"),
            "count": pt.get("numPriceTargets") or tg.get("count"),
            "updated": tg.get("updated"),
            "upside_pct": ((avg / price - 1) * 100) if (avg and price) else None,
        },
        "headline_estimates": sa.depro(est.get("stats") or {}),
        "annual": _estimate_table((est.get("table") or {}).get("annual")),
        "quarterly": _estimate_table((est.get("table") or {}).get("quarterly")),
        "estimate_dispersion": charts,
        "ratings_history": sa.depro(p.get("recommendations") or []),
        "recent_analyst_actions": [
            {"date": r.get("date"), "firm": r.get("firm"), "analyst": r.get("analyst"),
             "action": r.get("action_rt"), "rating_new": r.get("rating_new"),
             "rating_old": r.get("rating_old"), "target_new": r.get("pt_now"),
             "target_old": r.get("pt_old")}
            for r in (p.get("ratings") or [])],
        "source": p.get("estimatesSource"),
    }

    def md(o):
        r, t = o["ratings"], o["price_target"]
        L = [_hdr(info, "analyst forecast"), "",
             "## Consensus",
             f"**{r['consensus']}** from {r['analyst_count']} analysts — " +
             ", ".join(f"{k} {v}" for k, v in (r["breakdown"] or {}).items()), "",
             "## Price target",
             md_table(["", "Value"],
                      [["Average", t["average"]], ["Median", t["median"]],
                       ["Low", t["low"]], ["High", t["high"]],
                       ["# targets", t["count"]], ["Updated", t["updated"]],
                       ["Implied upside",
                        human(t["upside_pct"], 2, pct=True) if t["upside_pct"] is not None else "n/a"]]),
             ""]
        hs = o["headline_estimates"]
        if hs:
            body = []
            for scope in ("annual", "quarterly"):
                for k, lbl in (("revenueThis", "Revenue, current"), ("revenueNext", "Revenue, next"),
                               ("epsThis", "EPS, current"), ("epsNext", "EPS, next")):
                    d = (hs.get(scope) or {}).get(k)
                    if d:
                        body.append([f"{scope.title()} — {lbl}", human(d.get("last")),
                                     human(d.get("this")), human(d.get("growth"), 1, pct=True)])
            if body:
                L += ["## Headline estimates",
                      md_table(["", "Last", "Estimate", "Growth"], body), ""]
        L += ["## Estimates by period", _est_md("Annual", o["annual"]), "",
              _est_md("Quarterly", o["quarterly"]), ""]
        disp = o["estimate_dispersion"]
        if disp.get("revenue") or disp.get("eps"):
            body = []
            for metric in ("revenue", "eps"):
                for d, v in (disp.get(metric) or {}).items():
                    body.append([metric.upper(), d, v.get("no"), human(v.get("low")),
                                 human(v.get("avg")), human(v.get("high"))])
            L += ["## Estimate dispersion",
                  md_table(["Metric", "Period end", "# analysts", "Low", "Avg", "High"], body), ""]
        if o["recent_analyst_actions"]:
            L += ["## Recent analyst actions",
                  md_table(["Date", "Firm", "Analyst", "Action", "Rating", "Target (was)"],
                           [[a["date"], a["firm"], a["analyst"], a["action"], a["rating_new"],
                             f"{a['target_new']} ({a['target_old']})"]
                            for a in o["recent_analyst_actions"]]), ""]
        if o["ratings_history"]:
            L += ["## Consensus history",
                  md_table(["Month", "Total", "Strong buy", "Buy", "Hold", "Sell", "Strong sell", "Consensus"],
                           [[h.get("month"), h.get("total"), h.get("strongBuy"), h.get("buy"),
                             h.get("hold"), h.get("sell"), h.get("strongSell"), h.get("consensus")]
                            for h in o["ratings_history"]]), ""]
        L.append("Estimates are forward-looking analyst opinion, not company guidance.")
        return "\n".join(L)

    _emit(args, obj, md)


# ---------------------------------------------------------------------------
# metrics
#
# Sub-tabs are COMPANY-SPECIFIC segment breakdowns (NVDA has "Revenue by
# Geography", a bank would have something else), so they are discovered from
# the hub's navigationItems rather than hardcoded. The hub itself gates all but
# the ~8 most recent periods; the group sub-pages return 20 clean periods with
# change/growth precomputed, so prefer those.
# ---------------------------------------------------------------------------


def _slugify(s: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def _metrics_hub(args):
    nodes = _get(args, "metrics/", kind="metrics")
    return sa.symbol_info(nodes), (sa.page_node(nodes, ("data",)).get("data") or {})


def _series_rows(series, period_key):
    out = []
    for s in series or []:
        vals = sa.depro(s.get("values") or [])
        out.append({
            "name": s.get("name"), "value_type": s.get("valueType"),
            "period": period_key,
            "points": [{"date": v.get("x"), "value": v.get("y"),
                        "change": v.get("change"), "growth_pct": v.get("growth")}
                       for v in vals],
        })
    return out


def _metric_val(v, value_type):
    """Series carry `valueType` CURRENCY or PERCENT; the growth series are the
    latter and would read as tiny dollar amounts if formatted as money."""
    if v is None:
        return ""
    if value_type == "PERCENT":
        return human(v, 1, pct=True)
    return human(v)


def _metrics_md(o) -> str:
    L = [o["_header"], ""]
    if o.get("available"):
        L += ["## Available sub-pages",
              md_table(["Slug", "Title", "Kind"],
                       [[a["slug"], a["title"], a["kind"]] for a in o["available"]]),
              "", "_Pass one with `--sub SLUG`, or `--sub all` for every group._", ""]
    for grp in o["groups"]:
        L.append(f"## {grp['title']}")
        if o.get("available"):
            # Hub view: pivot to series-as-rows so a category fits one table.
            for period in ("quarterly", "trailing"):
                series = [s for s in grp["series"] if s["period"] == period and s["points"]]
                if not series:
                    continue
                dates = series[0]["points"]
                L += [f"### {period.title()}",
                      md_table(["Series"] + [p["date"] for p in dates],
                               [[s["name"]] + [_metric_val(p["value"], s["value_type"])
                                               for p in s["points"]]
                                for s in series]), ""]
            continue
        for s in grp["series"]:
            pts = s["points"]
            if not pts:
                continue
            L += [f"### {s['name']} ({s['period']})",
                  md_table(["Period end", "Value", "YoY change", "YoY growth"],
                           [[p["date"], _metric_val(p["value"], s["value_type"]),
                             _metric_val(p["change"], s["value_type"]),
                             human(p["growth_pct"], 1, pct=True) if p["growth_pct"] is not None else ""]
                            for p in pts]), ""]
    if o.get("gated"):
        L.append("_The hub gates all but the most recent periods. The group sub-pages "
                 "(`--sub SLUG`) return ~20 ungated periods with growth precomputed — "
                 "use those for real series._")
    return "\n".join(L)


def cmd_metrics(args):
    info, hub = _metrics_hub(args)
    nav = hub.get("navigationItems") or []
    singles = hub.get("singlePages") or []
    available = ([{"slug": _slugify(t), "title": t, "kind": "group"} for t in nav] +
                 [{"slug": (s.get("page_path") or "").strip("/"),
                   "title": s.get("metric_name"), "kind": "single"} for s in singles])

    want_periods = [args.period] if args.period else ["quarterly", "trailing"]
    groups, gated = [], False

    if not args.sub:
        # No sub-page named: show the menu plus a short recent window from the
        # hub. The hub gates everything older than ~8 periods, and dumping all
        # 40 series x 47 periods would drown the useful part.
        window = args.tail or 6
        by_cat = {}
        for pk in want_periods:
            for s in hub.get(f"{pk}Metrics") or []:
                rows = _series_rows([s], pk)
                for r in rows:
                    if any(p["value"] is None for p in r["points"]):
                        gated = True
                    r["points"] = r["points"][:window]
                by_cat.setdefault(s.get("category") or "Metrics", []).extend(rows)
        groups = [{"title": k, "series": v} for k, v in by_cat.items()]
    else:
        subs = [a for a in available if a["kind"] == "group"] if args.sub == "all" \
            else [a for a in available if a["slug"] == args.sub.strip("/")]
        if not subs:
            raise sa.NotFound(
                f"no metrics sub-page {args.sub!r}; available: "
                + ", ".join(a["slug"] for a in available))
        for a in subs:
            nodes = _get(args, f"metrics/{a['slug']}/", kind="metrics")
            d = sa.page_node(nodes, ("data",)).get("data") or {}
            payload = d.get("data") or {}
            series = []
            for pk in want_periods:
                block = payload.get(pk)
                if isinstance(block, dict):      # single-metric page
                    block = [block]
                rows = _series_rows(block, pk)
                if args.tail:
                    for r in rows:
                        r["points"] = r["points"][: args.tail]
                series.extend(rows)
            groups.append({"title": d.get("title") or a["title"], "slug": a["slug"],
                           "series": series})
        available = None

    obj = {"ticker": _tkr(info), "name": info.get("nameFull"),
           "available": available, "groups": groups, "gated": gated,
           "last_updated": hub.get("sourceLastUpdated"),
           "_header": _hdr(info, "metrics")}
    _emit(args, obj, _metrics_md)


# ---------------------------------------------------------------------------
# filings
#
# Note: this is the site's Quartr-sourced IR document set grouped by event, not
# an EDGAR form list. There is no 10-K/10-Q form code -- documents carry a
# `type` like `annual_report` / `quarterly_report` / `earnings_release`.
# ---------------------------------------------------------------------------

# Friendly aliases so `--type 10-K` does what a user expects.
_FILING_ALIASES = {
    "10-k": "annual_report", "10k": "annual_report", "annual": "annual_report",
    "10-q": "quarterly_report", "10q": "quarterly_report", "quarterly": "quarterly_report",
    "8-k": "press_release", "8k": "press_release", "press": "press_release",
    "earnings": "earnings_release", "release": "earnings_release",
    "deck": "slides", "presentation": "slides",
    "def-14a": "proxy", "proxy": "proxy", "s-1": "registration",
}


def _filings_events(args):
    nodes = _get(args, "filings/", kind="filings")
    return sa.symbol_info(nodes), (sa.page_node(nodes, ("events",)).get("events") or [])


def _flatten_filings(events, want_type=None, limit=0):
    want = _FILING_ALIASES.get((want_type or "").lower().strip(), want_type)
    out = []
    for ev in events:
        for f in ev.get("filings") or []:
            if want and f.get("type") != want:
                continue
            out.append({
                "date": ev.get("eventDate"),
                "event": ev.get("title"),
                "fiscal_year": ev.get("fiscalYear"),
                "fiscal_period": ev.get("fiscalPeriod"),
                "type": f.get("type"),
                "title": f.get("title") or ev.get("title"),
                "url": f.get("fileUrl"),
                "file_id": f.get("id"),
                "event_id": ev.get("eventId"),
            })
    return out[:limit] if limit else out


def cmd_filings(args):
    info, events = _filings_events(args)
    rows = _flatten_filings(events, args.type, args.limit)
    kinds = sorted({f.get("type") for ev in events for f in ev.get("filings") or []})
    obj = {"ticker": _tkr(info), "count": len(rows),
           "available_types": kinds, "filings": rows}

    def md(o):
        L = [_hdr(info, "filings & IR documents"), "",
             f"_{o['count']} documents_ · types: {', '.join(o['available_types'])}", ""]
        L.append(md_table(
            ["Date", "FY", "Period", "Type", "Title", "URL"],
            [[r["date"], r["fiscal_year"], r["fiscal_period"] or "", r["type"],
              r["title"], r["url"]] for r in o["filings"]]))
        L += ["", "Documents are PDFs hosted by Quartr; the `?ref=` query string is "
              "required — use the URL verbatim."]
        return "\n".join(L)

    _emit(args, obj, md)


def _doc_filename(ticker, r) -> str:
    """Sortable, self-describing: NVDA_2026-05-20_FY2027-Q1_earnings_release.pdf"""
    import re as _re
    period = ""
    if r.get("fiscal_year"):
        period = f"_FY{r['fiscal_year']}" + (f"-{r['fiscal_period']}" if r.get("fiscal_period") else "")
    name = f"{ticker}_{r.get('date')}{period}_{r.get('type')}"
    return _re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") + ".pdf"


def cmd_download(args):
    from pathlib import Path
    info, events = _filings_events(args)
    ticker = _tkr(info)
    rows = _flatten_filings(events, args.type, 0)

    if args.event:
        rows = [r for r in rows if str(r["event_id"]) == str(args.event)]
    if args.since:
        rows = [r for r in rows if (r["date"] or "") >= args.since]
    if args.latest:
        # The most recent *earnings* event, not merely the most recent event --
        # conferences and keynotes publish decks too and would otherwise win.
        earnings = {"earnings_release", "quarterly_report", "annual_report"}
        newest = next((r["event_id"] for r in rows if r["type"] in earnings),
                      rows[0]["event_id"] if rows else None)
        rows = [r for r in rows if r["event_id"] == newest]
    if args.limit:
        rows = rows[: args.limit]

    if not rows:
        print("no documents matched those filters; run `filings` to see what exists",
              file=sys.stderr)
        return

    out_dir = Path(args.dir or f"{ticker}-documents")
    results, total = [], 0
    for r in rows:
        if not r["url"]:
            continue
        dest = out_dir / _doc_filename(ticker, r)
        try:
            path, size, skipped = sa.download(r["url"], dest, overwrite=args.overwrite)
            total += size
            results.append({**r, "path": str(path), "bytes": size,
                            "status": "cached" if skipped else "downloaded"})
            print(f"  {'skip' if skipped else 'get '} {dest.name} ({size / 1e6:.2f} MB)",
                  file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - report and keep going
            results.append({**r, "path": None, "bytes": 0, "status": f"failed: {e}"})
            print(f"  FAIL {dest.name}: {e}", file=sys.stderr)

    ok = [r for r in results if r["bytes"]]
    print(f"{len(ok)}/{len(results)} documents, {total / 1e6:.1f} MB -> {out_dir}",
          file=sys.stderr)
    obj = {"ticker": ticker, "directory": str(out_dir), "count": len(ok),
           "total_bytes": total, "documents": results}

    def md(o):
        return "\n".join([
            _hdr(info, "downloaded documents"), "",
            f"_{o['count']} files, {o['total_bytes'] / 1e6:.1f} MB in `{o['directory']}`_", "",
            md_table(["Date", "FY", "Type", "File", "Size", "Status"],
                     [[r["date"], r["fiscal_year"], r["type"],
                       Path(r["path"]).name if r["path"] else "—",
                       f"{r['bytes'] / 1e6:.2f} MB" if r["bytes"] else "",
                       r["status"]] for r in o["documents"]]),
            "", "PDFs are as published by the company (via Quartr). Read them with "
            "the `pdf` skill, or point a PDF reader at the paths above."])

    _emit(args, obj, md)


# ---------------------------------------------------------------------------
# transcripts
# ---------------------------------------------------------------------------

_EARNINGS_RE = __import__("re").compile(r"^Q[1-4]\s")


def _transcript_index(args):
    nodes = _get(args, "transcripts/", kind="transcripts")
    return sa.symbol_info(nodes), (sa.page_node(nodes, ("transcripts",)).get("transcripts") or [])


def _is_earnings(t) -> bool:
    return bool(_EARNINGS_RE.match(t.get("quarterLabel") or ""))


def _index_row(t):
    return {
        "slug": t.get("detailSlug"),
        "label": t.get("quarterLabel"),
        "title": t.get("eventTitle"),
        "date": t.get("eventDate"),
        "fiscal_year": t.get("fiscalYear"),
        "is_earnings_call": _is_earnings(t),
        "has_chapters": bool(t.get("audioChapters")),
        "summary": t.get("summaryShort"),
        "audio_url": t.get("audioUrl"),
        "documents": [{"id": f.get("id"), "label": f.get("label")}
                      for f in t.get("files") or []],
        "event_id": t.get("quartrEventId"),
    }


def cmd_transcripts(args):
    info, items = _transcript_index(args)
    rows = [_index_row(t) for t in items]
    if not getattr(args, "all", False):
        rows = [r for r in rows if r["is_earnings_call"]]
    total = len(rows)
    rows = rows[: args.limit] if args.limit else rows
    obj = {"ticker": _tkr(info), "count": len(rows), "total_available": total,
           "note": "pass a `slug` to the `transcript` command for the full text",
           "transcripts": rows}

    def md(o):
        L = [_hdr(info, "earnings call transcripts"), "",
             f"_showing {o['count']} of {o['total_available']}_", "",
             md_table(["Slug", "Label", "Date", "Event", "Docs"],
                      [[r["slug"], r["label"], r["date"], r["title"],
                        ", ".join(d["label"] for d in r["documents"])] for r in o["transcripts"]])]
        withsum = [r for r in o["transcripts"] if r.get("summary")]
        if withsum:
            L += ["", "## Summaries"]
            for r in withsum:
                L.append(f"**{r['label']} ({r['date']})** — {r['summary']}")
        return "\n".join(L)

    _emit(args, obj, md)


def _turn_text(turn) -> str:
    """paragraphs -> list[list[sentence]] -> blank-line separated prose."""
    paras = turn.get("paragraphs") or []
    out = []
    for p in paras:
        if isinstance(p, list):
            out.append(" ".join((s or {}).get("text", "") for s in p).strip())
        elif isinstance(p, str):
            out.append(p.strip())
    return "\n\n".join(x for x in out if x)


def _turn_start(turn):
    for p in turn.get("paragraphs") or []:
        if isinstance(p, list) and p and isinstance(p[0], dict):
            s = p[0].get("startSec")
            if isinstance(s, (int, float)):
                return s
    return None


def _section_for(start, chapters):
    if start is None:
        return None
    for ch in chapters:
        lo, hi = ch.get("startTimestamp"), ch.get("endTimestamp")
        if lo is not None and start >= lo and (hi is None or start < hi):
            return ch.get("title")
    return None


def _assign_sections(turns, chapters):
    """Label each turn 'Prepared Remarks' / 'Q&A'.

    Chapters are authoritative when present. They are missing on a good number
    of events (including some recent earnings calls), so fall back to the
    structural tell: the Q&A starts at the first analyst turn.
    """
    if chapters:
        labelled = [(_section_for(_turn_start(t), chapters), t) for t in turns]
        if any(s for s, _ in labelled):
            cur = "Prepared Remarks"
            out = []
            for s, t in labelled:
                cur = s or cur
                out.append((cur, t))
            return out
    qa_at = None
    for i, t in enumerate(turns):
        if (t.get("role") or "").strip().lower() == "analyst":
            qa_at = i
            break
    if qa_at is None:
        return [(None, t) for t in turns]
    # Roll back to the operator hand-off that opens the Q&A, if there is one.
    j = qa_at
    while j > 0 and (turns[j - 1].get("speakerName") or "").strip().lower() == "operator":
        j -= 1
    return [("Prepared Remarks" if i < j else "Q&A", t) for i, t in enumerate(turns)]


def _html_to_md(html: str) -> str:
    import html as _h
    import re as _re
    if not html:
        return ""
    s = _re.sub(r"(?i)<h[1-6][^>]*>", "\n\n#### ", html)
    s = _re.sub(r"(?i)</h[1-6]>", "\n", s)
    s = _re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = _re.sub(r"(?i)</(p|div|ul|ol|li)>", "\n", s)
    s = _re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = _re.sub(r"<[^>]+>", "", s)
    s = _h.unescape(s)
    return _re.sub(r"\n{3,}", "\n\n", s).strip()


def _resolve_slug(items, want: str):
    """'latest' | index | 'q1-2027' | 'Q1 2027' | a full detailSlug."""
    earnings = [t for t in items if _is_earnings(t)]
    pool = earnings or items
    w = (want or "latest").strip().lower()
    if w in ("latest", "last", "newest"):
        return pool[0] if pool else None
    if w.isdigit():
        i = int(w)
        return pool[i] if i < len(pool) else None
    for t in items:
        if (t.get("detailSlug") or "").lower() == w:
            return t
    norm = w.replace(" ", "-")
    for t in items:
        slug = (t.get("detailSlug") or "").lower()
        label = (t.get("quarterLabel") or "").lower().replace(" ", "-")
        # detailSlug is "<eventId>-q1-2027"; match on the tail
        if label == norm or slug.endswith("-" + norm) or norm in slug:
            return t
    return None


def _fetch_transcript(args, slug: str):
    nodes = _get(args, f"transcripts/{slug}/", kind="transcript")
    return sa.page_node(nodes, ("transcriptQuarter",)).get("transcriptQuarter") or {}


def _transcript_obj(tq, with_body=True):
    turns = tq.get("transcriptTurns") or []
    obj = {
        "slug": tq.get("detailSlug"), "label": tq.get("quarterLabel"),
        "title": tq.get("eventTitle"), "date": tq.get("eventDate"),
        "fiscal_year": tq.get("fiscalYear"),
        "is_earnings_call": _is_earnings(tq),
        "audio_url": tq.get("audioUrl"),
        "documents": [{"id": f.get("id"), "label": f.get("label")}
                      for f in tq.get("files") or []],
        "summary_short": tq.get("summaryShort"),
        "summary_long": _html_to_md(tq.get("summaryLongHtml") or ""),
        "chapters": tq.get("audioChapters") or [],
        "speakers": [], "turn_count": len(turns), "format": None,
    }
    seen = {}
    for t in turns:
        n = t.get("speakerName")
        if n and n not in seen:
            seen[n] = {"name": n, "role": t.get("role"), "company": t.get("company")}
    obj["speakers"] = list(seen.values())
    if not with_body:
        return obj
    if turns:
        obj["format"] = "turns"
        obj["turns"] = [
            {"section": sec, "speaker": t.get("speakerName"), "role": t.get("role"),
             "company": t.get("company"), "start_sec": _turn_start(t),
             "text": _turn_text(t)}
            for sec, t in _assign_sections(turns, obj["chapters"])
        ]
        obj["chars"] = sum(len(t["text"]) for t in obj["turns"])
    elif tq.get("fullTranscriptBody"):
        # Legacy pre-2013 events: one unattributed plain-text blob.
        obj["format"] = "plaintext"
        obj["body"] = tq["fullTranscriptBody"]
        obj["chars"] = len(obj["body"])
    else:
        obj["format"] = "none"
    return obj


def _transcript_md(o, header: str = "") -> str:
    L = [header] if header else []
    title = o["title"] if o["title"] == o["label"] else f"{o['title']} — {o['label']}"
    L += [f"## {title} · {o['date']}",
          f"_fiscal year {o['fiscal_year']} · {o['turn_count']} speaker turns · "
          f"{o.get('chars', 0):,} chars_"]
    if o["documents"]:
        L.append("Documents: " + ", ".join(d["label"] for d in o["documents"]))
    if o["audio_url"]:
        L.append(f"Audio: <{o['audio_url']}>")
    L.append("")
    if o["summary_long"]:
        L += ["### Site summary", o["summary_long"], ""]
    elif o["summary_short"]:
        L += ["### Site summary", o["summary_short"], ""]
    if o["speakers"]:
        L += ["### Participants",
              md_table(["Speaker", "Role", "Company"],
                       [[s["name"], s["role"] or "", s["company"] or ""] for s in o["speakers"]]),
              ""]
    if o["format"] == "plaintext":
        L += ["### Transcript",
              "_legacy format: no speaker attribution available for this call_", "",
              o["body"]]
    elif o["format"] == "turns":
        cur = object()
        for t in o.get("turns", []):
            if t["section"] != cur:
                cur = t["section"]
                L += ["", f"### {cur or 'Transcript'}", ""]
            who = t["speaker"]
            tail = " — ".join(x for x in (t["role"], t["company"]) if x)
            L.append(f"**{who}**" + (f" _({tail})_" if tail else "") + "\n\n" + t["text"] + "\n")
    else:
        L.append("_no transcript body published for this event_")
    return "\n".join(L)


def cmd_transcript(args):
    info, items = _transcript_index(args)
    t = _resolve_slug(items, args.quarter)
    if t is None:
        raise sa.NotFound(
            f"no transcript matching {args.quarter!r} — "
            f"run `transcripts {args.ticker}` to list the available slugs")
    tq = _fetch_transcript(args, t["detailSlug"])
    obj = _transcript_obj(tq or t, with_body=not args.no_body)
    obj["ticker"] = _tkr(info)
    _emit(args, obj, lambda o: _transcript_md(
        o, f"# {info.get('nameFull')} ({info.get('ticker')}) — earnings call transcript\n"))


# ---------------------------------------------------------------------------
# company profile
# ---------------------------------------------------------------------------


def cmd_company(args):
    nodes = _get(args, "company/", kind="company")
    info = sa.symbol_info(nodes)
    p = sa.page_node(nodes, ("profile", "executives"))
    prof = p.get("profile") or {}
    contact = p.get("contact") or {}
    obj = {
        "ticker": _tkr(info), "name": prof.get("name") or info.get("nameFull"),
        "description": sa.strip_html(p.get("description") or ""),
        "sector": (prof.get("sector") or {}).get("value"),
        "industry": (prof.get("industry") or {}).get("value"),
        "country": prof.get("country"), "founded": prof.get("founded"),
        "ipo_date": prof.get("ipoDate"), "ceo": prof.get("ceo"),
        "employees": (prof.get("employees") or {}).get("value"),
        "logo_url": p.get("logoURL"),
        "contact": {"address": sa.strip_html(contact.get("address") or ""),
                    "phone": contact.get("phone"), "website": contact.get("website")},
        "identifiers": p.get("details") or {},
        "executives": [{"name": e.get("Name"), "title": e.get("Title")}
                       for e in p.get("executives") or []],
        "recent_sec_filings": [
            {"date": f.get("date"), "type": f.get("type"), "title": f.get("title"),
             "url": f"https://www.sec.gov/Archives/edgar/data/{f.get('path')}"
                    if f.get("path") else None}
            for f in p.get("filings") or []],
    }

    def md(o):
        L = [_hdr(info, "company profile"), "",
             md_table(["Field", "Value"],
                      [["Sector", o["sector"]], ["Industry", o["industry"]],
                       ["Country", o["country"]], ["Founded", o["founded"]],
                       ["IPO date", o["ipo_date"]], ["CEO", o["ceo"]],
                       ["Employees", human(o["employees"], 0)],
                       ["Website", o["contact"]["website"]],
                       ["Phone", o["contact"]["phone"]]]), ""]
        if o["contact"]["address"]:
            L += ["**Address**", o["contact"]["address"].replace("\n", ", "), ""]
        if o["description"]:
            L += ["## Business", o["description"], ""]
        if o["identifiers"]:
            L += ["## Identifiers",
                  md_table(["Field", "Value"], list(o["identifiers"].items())), ""]
        if o["executives"]:
            L += ["## Management",
                  md_table(["Name", "Title"],
                           [[e["name"], e["title"]] for e in o["executives"]]), ""]
        if o["recent_sec_filings"]:
            L += ["## Recent SEC filings (EDGAR)",
                  md_table(["Date", "Form", "Title", "URL"],
                           [[f["date"], f["type"], f["title"], f["url"]]
                            for f in o["recent_sec_filings"]]), ""]
        return "\n".join(L)

    _emit(args, obj, md)


# ---------------------------------------------------------------------------
# price history
#
# The page payload is capped at ~6 months and silently ignores `?range=`. The
# REST API honours range/period, so use it when available and fall back to the
# page for non-US symbols where the API has no route.
# ---------------------------------------------------------------------------


def _api_symbol(info):
    kind = "e" if (info.get("type") or "").lower() == "etf" else "s"
    sym = info.get("symbol") or (info.get("ticker") or "").lower()
    if (info.get("type") or "").lower() not in ("stocks", "etf"):
        return None  # non-US /quote/ symbols have no API route
    return f"/api/symbol/{kind}/{sym}/history"


def cmd_history(args):
    nodes = _get(args, kind="overview")
    info = sa.symbol_info(nodes)
    rng = (args.range or "").upper() or None
    rows, via = None, "page"
    api = _api_symbol(info)
    if api and rng:
        period = {"1D": "Daily", "5D": "Daily"}.get(rng, "Daily")
        if rng in ("5Y", "10Y", "MAX"):
            period = "Weekly"
        try:
            rows = sa.fetch_api(api, {"range": rng, "period": period}, kind="history",
                                refresh=args.refresh)
            via = f"api range={rng} period={period}"
        except sa.FetchError:
            rows = None
    if rows is None:
        h = _get(args, "history/", kind="history")
        node = sa.page_node(h, ("data",)).get("data") or {}
        rows = node.get("data") if isinstance(node, dict) else node
        via = "page (~6 months; pass --range for longer via the API)"

    bars = [{"date": r.get("t"), "open": r.get("o"), "high": r.get("h"), "low": r.get("l"),
             "close": r.get("c"), "adj_close": r.get("a"), "volume": r.get("v"),
             "change_pct": r.get("ch")} for r in (rows or [])]
    obj = {"ticker": _tkr(info), "currency": (info.get("curr") or {}).get("price"),
           "source": via, "count": len(bars), "bars": bars}

    def md(o):
        return "\n".join([
            _hdr(info, "price history"), "",
            f"_{o['count']} bars · {o['currency']} · via {o['source']}_", "",
            md_table(["Date", "Open", "High", "Low", "Close", "Adj close", "Volume", "Chg %"],
                     [[b["date"], b["open"], b["high"], b["low"], b["close"], b["adj_close"],
                       human(b["volume"], 0), "" if b["change_pct"] is None else f"{b['change_pct']:+.2f}%"]
                      for b in o["bars"]])])

    _emit(args, obj, md)


# ---------------------------------------------------------------------------
# dividend / ratings / employees
# ---------------------------------------------------------------------------


def cmd_dividend(args):
    nodes = _get(args, "dividend/", kind="financials")
    info = sa.symbol_info(nodes)
    p = sa.page_node(nodes, ("infoTable", "history"))
    it = p.get("infoTable")
    summary = it if isinstance(it, dict) else {}
    obj = {"ticker": _tkr(info), "summary": summary,
           "history": [{"ex_date": r.get("dt"), "amount": r.get("amt"),
                        "declared": r.get("dec"), "record": r.get("record"),
                        "pay_date": r.get("pay")} for r in p.get("history") or []],
           "has_more": (p.get("meta") or {}).get("has_more_dividends")}

    def md(o):
        L = [_hdr(info, "dividends"), ""]
        if o["summary"]:
            L += [md_table(["Field", "Value"],
                           [[k, v] for k, v in o["summary"].items() if not str(k).endswith("Url")]), ""]
        if o["history"]:
            L += ["## Dividend history",
                  md_table(["Ex-date", "Amount", "Declared", "Record", "Pay date"],
                           [[r["ex_date"], r["amount"], r["declared"], r["record"], r["pay_date"]]
                            for r in o["history"]]), ""]
        else:
            L.append("_no dividend history — this company does not pay a dividend_")
        return "\n".join(L)

    _emit(args, obj, md)


def cmd_ratings(args):
    nodes = _get(args, "ratings/", kind="forecast")
    info = sa.symbol_info(nodes)
    p = sa.page_node(nodes, ("ratings", "widget"))
    w = (p.get("widget") or {}).get("all") or {}
    obj = {"ticker": _tkr(info),
           "consensus": w.get("consensus"), "analyst_count": w.get("count"),
           "price_target": w.get("price_target"), "currency": w.get("currency"),
           "total_actions_available": (p.get("meta") or {}).get("total"),
           "actions": [{"date": r.get("date"), "firm": r.get("firm"),
                        "analyst": r.get("analyst"), "action": r.get("action_rt"),
                        "rating_new": r.get("rating_new"), "rating_old": r.get("rating_old"),
                        "target_new": r.get("pt_now"), "target_old": r.get("pt_old"),
                        "analyst_success_rate": (r.get("scores") or {}).get("success_rate"),
                        "analyst_avg_return": (r.get("scores") or {}).get("avg_return")}
                       for r in p.get("ratings") or []]}

    def md(o):
        return "\n".join([
            _hdr(info, "analyst ratings"), "",
            f"**{o['consensus']}** · {o['analyst_count']} analysts · "
            f"target {o['price_target']} {o['currency']}", "",
            f"_{len(o['actions'])} of {o['total_actions_available']} recent actions "
            f"(the rest load client-side and are not in the payload)_", "",
            md_table(["Date", "Firm", "Analyst", "Action", "Rating (was)", "Target (was)",
                      "Analyst hit rate"],
                     [[a["date"], a["firm"], a["analyst"], a["action"],
                       f"{a['rating_new']} ({a['rating_old'] or '—'})",
                       f"{a['target_new']} ({a['target_old'] or '—'})",
                       "" if a["analyst_success_rate"] is None else f"{a['analyst_success_rate']}"]
                      for a in o["actions"]])])

    _emit(args, obj, md)


def cmd_employees(args):
    nodes = _get(args, "employees/", kind="company")
    info = sa.symbol_info(nodes)
    p = sa.page_node(nodes, ("stats", "historical"))
    st = p.get("stats") or {}
    obj = {"ticker": _tkr(info),
           "current": st.get("current"), "change": st.get("change"),
           "growth_pct": st.get("growth"),
           "revenue_per_employee": st.get("revenue_per_employee"),
           "profit_per_employee": st.get("profit_per_employee"),
           "history": [{"date": r.get("date"), "count": r.get("count"),
                        "change": r.get("change"), "growth_pct": r.get("growth")}
                       for r in p.get("historical") or []],
           "peers": [{"ticker": r.get("s"), "name": r.get("n"), "employees": r.get("employees")}
                     for r in p.get("peers") or []]}

    def md(o):
        L = [_hdr(info, "employees"), "",
             md_table(["Metric", "Value"],
                      [["Employees", human(o["current"], 0)],
                       ["YoY change", human(o["change"], 0)],
                       ["YoY growth", human(o["growth_pct"], 1, pct=True)],
                       ["Revenue / employee", human(o["revenue_per_employee"])],
                       ["Profit / employee", human(o["profit_per_employee"])]]), ""]
        if o["history"]:
            L += ["## History",
                  md_table(["Period end", "Employees", "Change", "Growth"],
                           [[r["date"], human(r["count"], 0), human(r["change"], 0),
                             human(r["growth_pct"], 1, pct=True)] for r in o["history"]]), ""]
        if o["peers"]:
            L += ["## Peers",
                  md_table(["Ticker", "Name", "Employees"],
                           [[r["ticker"], r["name"], human(r["employees"], 0)]
                            for r in o["peers"]]), ""]
        return "\n".join(L)

    _emit(args, obj, md)


# ---------------------------------------------------------------------------
# brief -- the composed earnings briefing pack
# ---------------------------------------------------------------------------


class _Sub:
    """Stand-in args object for calling one extractor from inside another."""

    def __init__(self, src, **kw):
        self.ticker, self.refresh = src.ticker, src.refresh
        self.format, self.out = "json", None
        self.__dict__.update(kw)


def _capture(fn, args):
    """Run a cmd_* and return the object it would have emitted, not print it."""
    box = {}
    real = sa.emit
    try:
        sa.emit = lambda obj, fmt, md_fn=None, out=None: box.update(
            {"obj": obj, "md": md_fn(obj) if md_fn else ""})
        fn(args)
    finally:
        sa.emit = real
    return box.get("obj"), box.get("md")


def cmd_brief(args):
    nodes = _get(args, kind="overview")
    info = sa.symbol_info(nodes)
    raw_feats = info.get("features") or {}
    ov = sa.page_node(nodes, ("marketCap", "analystChart"))

    # `features` enumerates every tab a full US listing has. Non-US symbols get
    # a short dict -- a key simply being absent there means "no such tab", so
    # only default to True when there is no manifest at all.
    def feat(name: str) -> bool:
        return bool(raw_feats.get(name, False)) if raw_feats else True

    parts, collected = [], {}
    name = info.get("nameFull") or info.get("ticker")
    parts.append(f"# {name} ({_tkr(info)}) — earnings briefing pack")
    q = info.get("quote") or {}
    parts.append(f"_Generated from stockanalysis.com. Price {q.get('p')} "
                 f"{(info.get('curr') or {}).get('price')} as of {q.get('u')}. "
                 f"Next earnings: {ov.get('earningsDate') or 'n/a'}._")
    parts.append("\n> Everything below is scraped data, not analysis. Fiscal-year "
                 "labels are the company's own — check `fiscal year` spans before "
                 "converting to calendar years.\n")

    def section(title, fn, sub, gate=True):
        if not gate:
            parts.append(f"\n---\n\n# {title}\n\n_not available for this symbol_")
            return
        try:
            obj, md = _capture(fn, sub)
            collected[title] = obj
            parts.append("\n---\n\n" + (md or ""))
        except (sa.FetchError, KeyError, TypeError, IndexError) as e:
            parts.append(f"\n---\n\n# {title}\n\n_unavailable: {e}_")

    section("Overview", cmd_overview, _Sub(args), gate=True)
    section("Analyst forecast", cmd_forecast, _Sub(args), feat("forecast"))
    section("Statistics", cmd_statistics, _Sub(args), feat("statistics"))
    section("Income statement (annual)", cmd_financials,
            _Sub(args, statement="income", period="annual", limit=0),
            feat("financials"))
    section("Income statement (quarterly)", cmd_financials,
            _Sub(args, statement="income", period="quarterly", limit=9),
            feat("financials"))
    section("Cash flow (annual)", cmd_financials,
            _Sub(args, statement="cash-flow", period="annual", limit=0),
            feat("financials"))
    section("Segment breakdown", cmd_financials,
            _Sub(args, statement="overview", period="annual", limit=0),
            feat("financials"))

    # Transcripts: newest N earnings calls, oldest first so the reader walks
    # forward through what was promised and then what was delivered.
    if feat("transcripts") and args.transcripts > 0:
        try:
            _, items = _transcript_index(args)
            picks = [t for t in items if _is_earnings(t)][: args.transcripts]
            parts.append("\n---\n\n# Earnings call transcripts\n")
            if len(picks) > 1:
                parts.append(
                    f"_{len(picks)} calls, oldest first. Read the earlier call's "
                    "guidance and outlook, then check it against the later call's "
                    "reported numbers — that gap is usually the story._\n")
            tobjs = []
            for t in reversed(picks):
                tq = _fetch_transcript(args, t["detailSlug"])
                o = _transcript_obj(tq or t, with_body=not args.no_transcript_body)
                tobjs.append(o)
                parts.append(_transcript_md(o))
            collected["transcripts"] = tobjs
        except sa.FetchError as e:
            parts.append(f"\n---\n\n# Earnings call transcripts\n\n_unavailable: {e}_")

    section("Filings & IR documents", cmd_filings,
            _Sub(args, type=None, limit=30), feat("filings"))
    section("Company profile", cmd_company, _Sub(args), feat("profile"))

    if args.format == "json":
        collected["_meta"] = {"ticker": _tkr(info), "name": name,
                              "generated_from": "stockanalysis.com",
                              "as_of": q.get("u"),
                              "next_earnings": ov.get("earningsDate")}
        sa.emit(collected, "json", None, args.out)
    else:
        sa.emit("\n".join(parts), "md", lambda s: s, args.out)


# ---------------------------------------------------------------------------
# raw escape hatch
# ---------------------------------------------------------------------------


def _unmangle(path: str) -> str:
    """Undo MSYS/Git-Bash POSIX-path conversion.

    Git Bash rewrites a leading `/stocks/...` argument into
    `C:/Program Files/Git/stocks/...` before python ever sees it. Recover the
    site-relative path by cutting back to a known section root.
    """
    import re as _re
    m = _re.search(r"/(stocks|etf|quote)/.*", path.replace("\\", "/"))
    return m.group(0) if m else path


def cmd_raw(args):
    params = {}
    for kv in args.param:
        if "=" in kv:
            k, v = kv.split("=", 1)
            params[k] = v
    nodes = sa.fetch_data(_unmangle(args.path), params=params or None,
                          refresh=getattr(args, "refresh", False))
    obj = nodes if args.node is None else nodes[args.node]
    sa.emit(obj, "json", None, getattr(args, "out", None))
