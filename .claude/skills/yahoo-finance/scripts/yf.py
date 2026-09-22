#!/usr/bin/env python3
"""Yahoo Finance data fetcher: quotes, historical prices, fundamentals, symbol search.

Uses yfinance when available; falls back to Yahoo's public chart/quote JSON
endpoints via requests so the script still works on a bare Python install.

Run `python yf.py <command> --help` for options.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

try:
    import logging

    import yfinance as yf

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
except Exception:  # pragma: no cover - fallback path
    yf = None

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
BASE = "https://query1.finance.yahoo.com"

VALID_PERIODS = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"]
VALID_INTERVALS = ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h",
                   "1d", "5d", "1wk", "1mo", "3mo"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _http_json(url, params=None, tries=3):
    if requests is None:
        die("neither yfinance nor requests is installed; run: pip install yfinance")
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=20)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code in (400, 401, 403, 404):
                break  # not transient -- don't burn retries
        except Exception as e:  # network hiccup
            last = str(e)
        time.sleep(0.6 * (i + 1))
    die(f"request failed for {url} -- {last}")


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def _num(v):
    try:
        if v is None:
            return None
        f = float(v)
        return None if f != f else f  # drop NaN
    except (TypeError, ValueError):
        return None


def _fmt(v, nd=2, fine=True):
    """fine=True gives sub-$10 values 4 decimals (FX pairs, penny stocks)."""
    if v is None:
        return "-"
    if abs(v) >= 1e12:
        return f"{v/1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"{v/1e9:.2f}B"
    if abs(v) >= 1e6 and nd == 0:
        return f"{v/1e6:.2f}M"
    if fine and nd == 2 and v != 0 and abs(v) < 10:
        return f"{v:,.4f}"  # FX pairs and sub-$10 tickers need the extra digits
    return f"{v:,.{nd}f}"


def _ts(epoch, tz_offset=0):
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch + tz_offset, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# quote
# --------------------------------------------------------------------------- #
def fetch_quote(symbol):
    """Return a normalized quote dict for one symbol."""
    q = {"symbol": symbol.upper()}
    if yf is not None:
        try:
            t = yf.Ticker(symbol)
            fi = t.fast_info
            g = lambda k: _num(getattr(fi, k, None))
            q.update(
                price=g("last_price"), previous_close=g("previous_close"),
                open=g("open"), day_high=g("day_high"), day_low=g("day_low"),
                year_high=g("year_high"), year_low=g("year_low"),
                volume=g("last_volume"), avg_volume_10d=g("ten_day_average_volume"),
                market_cap=g("market_cap"), shares=g("shares"),
                currency=getattr(fi, "currency", None),
                exchange=getattr(fi, "exchange", None),
                quote_type=getattr(fi, "quote_type", None),
            )
        except Exception:
            pass
    if q.get("price") is None:  # fallback: chart meta
        data = _http_json(f"{BASE}/v8/finance/chart/{symbol}",
                          {"range": "1d", "interval": "1d"})
        res = (data.get("chart") or {}).get("result") or []
        if not res:
            err = ((data.get("chart") or {}).get("error") or {}).get("description")
            die(f"no data for '{symbol}'{': ' + err if err else ''}")
        m = res[0].get("meta", {})
        q.update(
            price=_num(m.get("regularMarketPrice")),
            previous_close=_num(m.get("chartPreviousClose") or m.get("previousClose")),
            day_high=_num(m.get("regularMarketDayHigh")), day_low=_num(m.get("regularMarketDayLow")),
            year_high=_num(m.get("fiftyTwoWeekHigh")), year_low=_num(m.get("fiftyTwoWeekLow")),
            volume=_num(m.get("regularMarketVolume")),
            currency=m.get("currency"), exchange=m.get("fullExchangeName") or m.get("exchangeName"),
            quote_type=m.get("instrumentType"), name=m.get("longName") or m.get("shortName"),
            market_time=_ts(m.get("regularMarketTime")),
        )
    p, pc = q.get("price"), q.get("previous_close")
    q["change"] = round(p - pc, 4) if p is not None and pc else None
    q["change_pct"] = round((p - pc) / pc * 100, 4) if p is not None and pc else None
    q["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    return q


def cmd_quote(a):
    quotes = [fetch_quote(s) for s in a.symbols]
    if a.format == "json":
        print(json.dumps(quotes if len(quotes) > 1 else quotes[0], indent=2))
        return
    if a.format == "csv":
        cols = ["symbol", "price", "change", "change_pct", "previous_close", "open",
                "day_low", "day_high", "year_low", "year_high", "volume",
                "market_cap", "currency"]
        w = csv.DictWriter(sys.stdout, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(quotes)
        return
    hdr = f"{'SYMBOL':<10}{'PRICE':>12}{'CHG':>10}{'CHG%':>9}{'DAY RANGE':>24}{'52W RANGE':>24}{'VOLUME':>14}{'MKT CAP':>12}"
    print(hdr)
    print("-" * len(hdr))
    for q in quotes:
        cp = q.get("change_pct")
        sign = "+" if cp is not None and cp >= 0 else ""
        p = q.get("price")
        # decimal precision follows the instrument, not each individual number
        fine = p is not None and abs(p) < 10
        f = lambda v: _fmt(v, fine=fine)
        dr = f"{f(q.get('day_low'))} - {f(q.get('day_high'))}"
        yr = f"{f(q.get('year_low'))} - {f(q.get('year_high'))}"
        print(f"{q['symbol']:<10}{f(p):>12}"
              f"{sign + f(q.get('change')) if q.get('change') is not None else '-':>10}"
              f"{sign + _fmt(cp, fine=False) + '%' if cp is not None else '-':>9}"
              f"{dr:>24}{yr:>24}{_fmt(q.get('volume'), 0):>14}{_fmt(q.get('market_cap'), 0):>12}")
    cur = quotes[0].get("currency")
    print(f"\ncurrency: {cur or 'n/a'}   fetched: {quotes[0]['fetched_at']}   source: Yahoo Finance")


# --------------------------------------------------------------------------- #
# history
# --------------------------------------------------------------------------- #
def fetch_history(symbol, period=None, interval="1d", start=None, end=None, auto_adjust=False):
    """Return (rows, meta). rows = list of dicts with date/open/high/low/close/volume."""
    rows = []
    if yf is not None:
        try:
            t = yf.Ticker(symbol)
            kw = dict(interval=interval, auto_adjust=auto_adjust, actions=True)
            if start:
                kw.update(start=start, end=end)
            else:
                kw.update(period=period or "1mo")
            df = t.history(**kw)
            if df is not None and not df.empty:
                intraday = any(x in interval for x in ("m", "h"))
                for idx, r in df.iterrows():
                    row = {
                        "date": idx.strftime("%Y-%m-%d %H:%M:%S%z" if intraday else "%Y-%m-%d"),
                        "open": _num(r.get("Open")), "high": _num(r.get("High")),
                        "low": _num(r.get("Low")), "close": _num(r.get("Close")),
                        "volume": _num(r.get("Volume")),
                    }
                    if "Adj Close" in df.columns:
                        row["adj_close"] = _num(r.get("Adj Close"))
                    if _num(r.get("Dividends")):
                        row["dividends"] = _num(r.get("Dividends"))
                    if _num(r.get("Stock Splits")):
                        row["splits"] = _num(r.get("Stock Splits"))
                    rows.append(row)
        except Exception:
            rows = []
    if not rows:  # fallback: raw chart endpoint
        params = {"interval": interval, "events": "div,split"}
        if start:
            params["period1"] = int(datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
            params["period2"] = int(datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) \
                if end else int(time.time())
        else:
            params["range"] = period or "1mo"
        data = _http_json(f"{BASE}/v8/finance/chart/{symbol}", params)
        res = (data.get("chart") or {}).get("result") or []
        if not res:
            err = ((data.get("chart") or {}).get("error") or {}).get("description")
            die(f"no history for '{symbol}'{': ' + err if err else ''}")
        r0 = res[0]
        stamps = r0.get("timestamp") or []
        ind = (r0.get("indicators") or {}).get("quote", [{}])[0]
        adj = ((r0.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
        intraday = any(x in interval for x in ("m", "h"))
        for i, ts in enumerate(stamps):
            d = datetime.fromtimestamp(ts, tz=timezone.utc)
            row = {
                "date": d.strftime("%Y-%m-%d %H:%M:%S" if intraday else "%Y-%m-%d"),
                "open": _num((ind.get("open") or [None] * len(stamps))[i]),
                "high": _num((ind.get("high") or [None] * len(stamps))[i]),
                "low": _num((ind.get("low") or [None] * len(stamps))[i]),
                "close": _num((ind.get("close") or [None] * len(stamps))[i]),
                "volume": _num((ind.get("volume") or [None] * len(stamps))[i]),
            }
            if adj:
                row["adj_close"] = _num(adj[i])
            if row["close"] is not None:
                rows.append(row)
    return rows


def cmd_history(a):
    if a.start:
        rows = fetch_history(a.symbol, interval=a.interval, start=a.start, end=a.end,
                             auto_adjust=a.auto_adjust)
    else:
        rows = fetch_history(a.symbol, period=a.period, interval=a.interval,
                             auto_adjust=a.auto_adjust)
    if not rows:
        die(f"no rows returned for {a.symbol}")
    if a.tail:
        rows = rows[-a.tail:]

    cols = ["date", "open", "high", "low", "close"]
    if any("adj_close" in r for r in rows):
        cols.append("adj_close")
    cols.append("volume")
    for extra in ("dividends", "splits"):
        if any(extra in r for r in rows):
            cols.append(extra)

    if a.format == "json":
        out = json.dumps(rows, indent=2)
    elif a.format == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        out = buf.getvalue()
    else:
        lines = ["".join(c.upper().rjust(14 if c != "date" else 21) for c in cols)]
        lines.append("-" * len(lines[0]))
        for r in rows:
            lines.append("".join(
                (str(r.get(c, "-")) if c == "date" else _fmt(r.get(c), 0 if c == "volume" else 2)
                 ).rjust(21 if c == "date" else 14) for c in cols))
        first, last = rows[0]["close"], rows[-1]["close"]
        pct = (last - first) / first * 100 if first else None
        lines.append("")
        lines.append(f"{a.symbol.upper()}  {len(rows)} bars  {rows[0]['date']} -> {rows[-1]['date']}  "
                     f"close {_fmt(first)} -> {_fmt(last)}  "
                     f"({'+' if pct and pct >= 0 else ''}{_fmt(pct, fine=False)}% over range)")
        out = "\n".join(lines)

    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="") as f:
            f.write(out if out.endswith("\n") else out + "\n")
        print(f"wrote {len(rows)} rows to {a.out}")
    else:
        print(out)


# --------------------------------------------------------------------------- #
# info / search
# --------------------------------------------------------------------------- #
KEEP = ["longName", "shortName", "symbol", "quoteType", "sector", "industry",
        "country", "website", "currency", "exchange", "marketCap", "enterpriseValue",
        "trailingPE", "forwardPE", "priceToBook", "beta", "dividendYield",
        "dividendRate", "payoutRatio", "trailingEps", "forwardEps", "profitMargins",
        "revenueGrowth", "totalRevenue", "totalCash", "totalDebt", "freeCashflow",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyDayAverage", "twoHundredDayAverage",
        "averageVolume", "sharesOutstanding", "targetMeanPrice", "recommendationKey",
        "numberOfAnalystOpinions", "longBusinessSummary"]


def cmd_info(a):
    if yf is None:
        die("`info` needs yfinance: pip install yfinance")
    t = yf.Ticker(a.symbol)
    try:
        raw = t.info or {}
    except Exception as e:
        die(f"could not fetch info for {a.symbol}: {e}")
    info = {k: raw[k] for k in KEEP if raw.get(k) is not None}
    if not info:
        die(f"no info returned for {a.symbol}")
    if a.format == "json":
        print(json.dumps(info, indent=2))
        return
    summary = info.pop("longBusinessSummary", None)
    for k, v in info.items():
        print(f"{k:<26} {_fmt(v, 2) if isinstance(v, (int, float)) else v}")
    if summary and not a.no_summary:
        print("\nsummary:")
        print(summary[:1200] + ("..." if len(summary) > 1200 else ""))


def cmd_search(a):
    data = _http_json(f"{BASE}/v1/finance/search",
                      {"q": a.query, "quotesCount": a.limit, "newsCount": 0})
    hits = data.get("quotes") or []
    if not hits:
        die(f"no symbols matched '{a.query}'")
    if a.format == "json":
        print(json.dumps(hits, indent=2))
        return
    print(f"{'SYMBOL':<12}{'TYPE':<10}{'EXCHANGE':<12}NAME")
    print("-" * 70)
    for h in hits:
        print(f"{h.get('symbol', '-'):<12}{h.get('quoteType', '-'):<10}"
              f"{h.get('exchange', '-'):<12}{h.get('shortname') or h.get('longname') or '-'}")


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(prog="yf.py", description="Yahoo Finance quotes and history")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("quote", help="current/last quote for one or more symbols")
    q.add_argument("symbols", nargs="+")
    q.add_argument("--format", choices=["table", "json", "csv"], default="table")
    q.set_defaults(func=cmd_quote)

    h = sub.add_parser("history", help="historical OHLCV bars")
    h.add_argument("symbol")
    h.add_argument("--period", default="1mo", choices=VALID_PERIODS,
                   help="lookback window (ignored when --start is given)")
    h.add_argument("--interval", default="1d", choices=VALID_INTERVALS)
    h.add_argument("--start", help="YYYY-MM-DD (inclusive)")
    h.add_argument("--end", help="YYYY-MM-DD (exclusive); defaults to today")
    h.add_argument("--format", choices=["table", "csv", "json"], default="table")
    h.add_argument("--out", help="write to this file instead of stdout")
    h.add_argument("--tail", type=int, help="keep only the last N rows")
    h.add_argument("--auto-adjust", action="store_true",
                   help="adjust OHLC for splits/dividends (default: raw prices)")
    h.set_defaults(func=cmd_history)

    i = sub.add_parser("info", help="fundamentals / profile for a symbol")
    i.add_argument("symbol")
    i.add_argument("--format", choices=["table", "json"], default="table")
    i.add_argument("--no-summary", action="store_true")
    i.set_defaults(func=cmd_info)

    s = sub.add_parser("search", help="find a ticker symbol by company name")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--format", choices=["table", "json"], default="table")
    s.set_defaults(func=cmd_search)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
