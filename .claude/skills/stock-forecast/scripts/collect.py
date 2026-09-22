#!/usr/bin/env python3
"""Stage 1 of stock-forecast: gather everything the other eight skills know.

    python collect.py NVDA --depth deep -d ./NVDA-bundle

Writes a bundle directory the model then reads to write its analysis. Every
number the dashboard shows comes from here, so nothing on the page has to be
remembered or invented.

Each source is reached through its own skill's CLI, inheriting that skill's
cache, throttle and User-Agent. Different hosts run in parallel; calls to the
same host stay strictly sequential so no site sees a burst.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sf_indicators as indicators  # noqa: E402

SKILLS = Path(os.environ.get(
    "STOCK_FORECAST_SKILLS_ROOT",
    os.environ.get("CODEX_STOCK_FORECAST_SKILLS_ROOT",
                   Path(__file__).resolve().parents[2]),
)).resolve()


def _sibling(names, *relative, env=None):
    """Locate a sibling skill's script under any of its known folder names.

    The same suite is installed under two naming schemes — Claude Code uses
    `fair-value`, `stockanalysis`, `finviz-news`; Codex uses
    `normal-multiple-valuation`, `stockanalysis-company-research`,
    `market-news-brief`. Resolving both keeps one codebase running unmodified in
    either install and straight from a git clone.

    Returns the first path that exists, or the first candidate so the caller
    still reports a clean "not installed" error rather than a NameError.
    """
    if env:
        override = os.environ.get(env)
        if override:
            return Path(override)
    candidates = []
    for name in names:
        for rel in relative:
            candidates.append(SKILLS / name / Path(rel))
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


SA = _sibling(("stockanalysis", "stockanalysis-company-research"),
              "scripts/sa.py", env="SF_SA_SCRIPT")
DECKS = _sibling(("stockanalysis", "stockanalysis-company-research"),
                 "scripts/decks.py")
FINVIZ = _sibling(("finviz-earnings", "finviz-earnings-research"),
                  "scripts/finviz_earnings.py", env="SF_FINVIZ_SCRIPT")
FINVIZ_VALIDATE = _sibling(("finviz-stock-research",),
                           "scripts/validate_snapshot.py")
YF = _sibling(("yahoo-finance", "yahoo-market-data", "yahoo-finance-data"),
              "scripts/yf.py", env="SF_YF_SCRIPT")
FAIRVALUE = _sibling(("fair-value", "normal-multiple-valuation"),
                     "scripts/fair_value.py", env="SF_FAIRVALUE_SCRIPT")
CALENDAR = _sibling(("earnings-calendar", "company-earnings-calendar"),
                    "scripts/te_earnings.py")
MACRO = _sibling(("economic-calendar", "macro-economic-calendar"),
                 "scripts/te_calendar.py")
# finviz-news keeps its scraper at the skill root; market-news-brief moved it
# into scripts/ and renamed it.
NEWS = _sibling(("finviz-news", "market-news-brief"),
                "scripts/fetch_finviz_news.py", "scrape_finviz_news.py",
                env="SF_NEWS_SCRIPT")

DEPTHS = {"fast": 1, "standard": 3, "deep": 6}

def _skill_of(path):
    """The installed folder name behind a resolved script, for the page footer.

    The two installs name the same skill differently, so the provenance table is
    built from what actually resolved rather than hardcoded to one scheme.
    """
    try:
        return path.parents[1].name if path.parent.name == "scripts" else path.parent.name
    except (IndexError, AttributeError):
        return "unknown"


# One source of truth per field. Shown in the page footer; a second source is
# used only to cross-check, never to average.
PROVENANCE = {
    "live quote / profile": f"{_skill_of(YF)} (cross-checked against Finviz and StockAnalysis)",
    "OHLCV and computed indicators": f"{_skill_of(YF)} + sf_indicators.py",
    "Finviz stock snapshot": f"{_skill_of(FINVIZ_VALIDATE)} (browser capture when available)",
    "forward estimates, revisions, earnings reactions": _skill_of(FINVIZ),
    "financial history, segments, profile, transcripts, filings": _skill_of(SA),
    "analyst price targets": f"{_skill_of(SA)} (cross-checked against Finviz)",
    "fair value, normal multiple, base rates": _skill_of(FAIRVALUE),
    "next confirmed report date": f"{_skill_of(CALENDAR)} (cross-checked against Finviz)",
    "market backdrop headlines": f"{_skill_of(NEWS)} (market-wide, not ticker-specific)",
    "macro backdrop": _skill_of(MACRO),
}


class Collector:
    def __init__(self, ticker, depth, out_dir, refresh=False, finviz_snapshot=None):
        normalized = str(ticker or "").strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9._-]{0,14}", normalized):
            raise InvalidTickerError(ticker)
        self.ticker = normalized
        self.depth = depth
        self.dir = Path(out_dir)
        self.refresh = refresh
        self.finviz_snapshot = Path(finviz_snapshot) if finviz_snapshot else None
        self.errors = []
        self.source_status = {}
        self.started = time.time()

    # -- plumbing ---------------------------------------------------------
    def run(self, script, args, timeout=300, label=None, expect_stdout=True):
        """`expect_stdout=False` for tools that write a file and report on stderr —
        empty stdout is success there, not a failure."""
        label = label or Path(script).stem
        last_message = None
        attempts = 0
        for attempt in range(3):
            attempts = attempt + 1
            try:
                proc = subprocess.run([sys.executable, str(script), *map(str, args)],
                                      capture_output=True, text=True, timeout=timeout,
                                      encoding="utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                last_message = f"timed out after {timeout}s"
                proc = None
            if proc is not None:
                # Only the fair-value engine uses exit 2 for an honest refusal;
                # every other source treats exit 2 as a failed collection.
                accepted = proc.returncode == 0 or (
                    proc.returncode == 2 and label == "normal-multiple-valuation"
                )
                if accepted and (not expect_stdout or proc.stdout.strip()):
                    self.source_status[label] = {
                        "status": "ok" if proc.returncode == 0 else "refused",
                        "attempts": attempt + 1,
                        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                    }
                    return proc.stdout
                detail = (proc.stderr or proc.stdout or "").strip().splitlines()
                last_message = detail[-1] if detail else f"exit {proc.returncode}"
                transient = any(token in last_message.lower() for token in (
                    "429", "rate limit", "http 5", "timed out", "timeout",
                    "temporarily", "connection", "503", "502", "504",
                ))
                if not transient:
                    break
            if attempt < 2:
                time.sleep(1.0 + attempt * 1.5)
        self.source_status[label] = {
            "status": "failed",
            "attempts": attempts,
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        }
        self.errors.append({"source": label, "message": last_message or "unknown failure"})
        return None

    def run_json(self, script, args, timeout=300, label=None):
        text = self.run(script, args, timeout, label)
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError as exc:
            self.errors.append({"source": label or Path(script).stem,
                                "message": f"unreadable JSON: {exc}"})
            return None

    def sa(self, args, **kw):
        extra = ["--refresh"] if self.refresh else []
        return self.run_json(SA, [*args, "--format", "json", *extra],
                             label="stockanalysis-company-research", **kw)

    def log(self, message):
        print(f"  {message}", file=sys.stderr, flush=True)

    # -- source groups (one thread each; sequential inside) ----------------
    def gather_stockanalysis(self):
        out = {}
        self.log("stockanalysis-company-research: profile, financials, forecast...")
        out["profile"] = self.sa(["company", self.ticker])
        out["overview"] = self.sa(["overview", self.ticker])

        instrument = (out["overview"] or {}).get("instrument")
        if instrument and instrument.upper() == "ETF":
            raise UnsupportedInstrumentError(self.ticker, instrument)

        out["statistics"] = self.sa(["statistics", self.ticker])
        out["income_annual"] = self.sa(
            ["financials", self.ticker, "-s", "income", "-p", "annual"])
        out["income_quarterly"] = self.sa(
            ["financials", self.ticker, "-s", "income", "-p", "quarterly"])
        out["ratios_annual"] = self.sa(
            ["financials", self.ticker, "-s", "ratios", "-p", "annual"])
        out["forecast"] = self.sa(["forecast", self.ticker])
        out["segments"] = self.sa(["metrics", self.ticker])
        out["news"] = self.sa(["news", self.ticker])
        out["filings"] = self.sa(["filings", self.ticker])
        out["transcript_index"] = self.sa(["transcripts", self.ticker])
        return out

    def gather_finviz(self):
        self.log("finviz-earnings-research: estimates, revisions, reactions...")
        extra = ["--refresh"] if self.refresh else []
        return self.run_json(FINVIZ, ["raw", self.ticker, "-f", "json", *extra],
                             label="finviz-earnings-research")

    def gather_finviz_snapshot(self):
        """Load an optional browser-captured Finviz deep snapshot.

        The broader Finviz skill intentionally uses the read-only in-app browser
        rather than a direct HTTP scraper. The model can supply a merged snapshot
        with --finviz-snapshot after that capture; otherwise the earnings scraper's
        snapshot remains the documented partial fallback.
        """
        if not self.finviz_snapshot:
            self.source_status["finviz-stock-research"] = {
                "status": "not_captured",
                "message": "No browser snapshot supplied; using Finviz earnings fallback.",
                "checked_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            }
            return None
        try:
            payload = json.loads(self.finviz_snapshot.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.source_status["finviz-stock-research"] = {"status": "failed"}
            self.errors.append({"source": "finviz-stock-research",
                                "message": f"could not read snapshot: {exc}"})
            return None
        if str(payload.get("ticker") or "").upper() != self.ticker:
            self.source_status["finviz-stock-research"] = {"status": "failed"}
            self.errors.append({"source": "finviz-stock-research",
                                "message": "snapshot ticker does not match requested ticker"})
            return None
        self.run(FINVIZ_VALIDATE, [str(self.finviz_snapshot)],
                 label="finviz-stock-research", expect_stdout=False)
        self.source_status.setdefault("finviz-stock-research", {})["snapshot"] = str(
            self.finviz_snapshot)
        return payload

    def gather_quote(self):
        self.log("yahoo-market-data: live quote and profile...")
        return self.run_json(YF, ["quote", self.ticker, "--format", "json"],
                             label="yahoo-market-data", timeout=120)

    def gather_prices(self):
        self.log("yahoo: 5y daily bars...")
        text = self.run(YF, ["history", self.ticker, "--period", "5y",
                             "--interval", "1d", "--format", "csv"],
                        label="yahoo-finance-data")
        if not text:
            return None
        bars = []
        for row in csv.DictReader(io.StringIO(text)):
            try:
                bars.append({"date": row["date"][:10],
                             "open": float(row["open"]), "high": float(row["high"]),
                             "low": float(row["low"]), "close": float(row["close"]),
                             "volume": float(row.get("volume") or 0)})
            except (ValueError, KeyError, TypeError):
                continue
        return bars or None

    def gather_fair_value(self):
        self.log("normal-multiple-valuation: normal multiple, band, base rates...")
        extra = ["--refresh"] if self.refresh else []
        return self.run_json(FAIRVALUE, [self.ticker, "-f", "json", *extra],
                             label="normal-multiple-valuation")

    def gather_calendar(self):
        return self.run_json(CALENDAR, ["company", self.ticker, "-f", "json"],
                             label="company-earnings-calendar", timeout=120)

    def gather_macro(self):
        """Collect high-impact recent and upcoming macro events."""
        self.log("macro-economic-calendar: recent and upcoming market events...")
        extra = ["--refresh"] if self.refresh else []
        out = {}
        for window in ("recent", "thisweek", "nextweek"):
            result = self.run_json(
                MACRO,
                [window, "-i", "2", "-f", "json", "--limit", "40", *extra],
                label="macro-economic-calendar",
                timeout=180,
            )
            if result is not None:
                out[window] = result
        return out or None

    def gather_market_news(self):
        """Market-wide headlines for the backdrop dimension.

        The market-news-brief skill deliberately needs a human-or-model in
        the loop to score headlines, which does not fit a single subprocess call.
        We take its input instead — the raw feed — and form the backdrop view in
        stage 2, where judgment already lives.
        """
        self.log("market news: headlines for backdrop...")
        # The two installs ship different front-ends to the same scraper:
        # market-news-brief streams compact JSON to stdout, finviz-news writes a
        # file and reports on stderr. Pick by filename rather than guessing.
        target = self.dir / "market-news.json"
        if NEWS.name == "scrape_finviz_news.py":
            self.run(NEWS, ["--out", str(target), "--dedupe", "--compact", "--quiet"],
                     timeout=240, label="market-news", expect_stdout=False)
            if not target.exists():
                return None
            try:
                payload = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        else:
            payload = self.run_json(NEWS, ["--output-mode", "compact-json"],
                                    timeout=240, label="market-news")
            if not payload:
                return None
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        headlines = payload.get("headlines") or []
        return {"date": payload.get("date"), "count": len(headlines),
                "top": [{"headline": h.get("headline"),
                         "source": h.get("source") or h.get("publisher"),
                         "url": h.get("article_url") or h.get("url"),
                         "tickers": h.get("tickers") or h.get("related_tickers"),
                         "datetime": h.get("datetime") or h.get("published_datetime"),
                         "summary": h.get("summary")}
                        for h in headlines[:40]]}

    # -- transcripts and decks --------------------------------------------
    def gather_transcripts(self, index):
        rows = (index or {}).get("transcripts") or (index or {}).get("rows") or []
        if isinstance(index, list):
            rows = index
        if not rows:
            return {"summaries": [], "latest_full": None, "count": 0}

        import re
        earnings_rows = [
            row for row in rows
            if re.search(r"\bQ[1-4]\s+\d{4}\b", str(
                row.get("quarterLabel") or row.get("label") or row.get("title") or ""),
                re.IGNORECASE)
        ]
        rows = earnings_rows or rows
        wanted = DEPTHS[self.depth]
        folder = self.dir / "transcripts"
        folder.mkdir(parents=True, exist_ok=True)
        summaries = []
        self.log(f"stockanalysis-company-research: {wanted} earnings transcript summaries + latest full...")
        for row in rows[:wanted]:
            slug = row.get("slug") or row.get("id")
            label = row.get("label") or slug
            if not slug:
                continue
            path = folder / f"{slug}.md"
            text = self.run(SA, ["transcript", self.ticker, slug, "--no-body",
                                 "--format", "md"], label="stockanalysis-company-research")
            if not text:
                continue
            path.write_text(text, encoding="utf-8")
            summaries.append({"slug": slug, "label": label, "date": row.get("date"),
                              "path": str(path.relative_to(self.dir)).replace("\\", "/"),
                              "guidance": _extract_section(text, "Outlook and guidance"),
                              "highlights": _extract_section(text, "Financial highlights"),
                              "risks": _extract_section(text, "Risk factors and uncertainties")})

        latest_full = None
        if rows:
            slug = rows[0].get("slug") or rows[0].get("id")
            text = self.run(SA, ["transcript", self.ticker, slug, "--format", "md"],
                            label="stockanalysis-company-research")
            if text:
                path = folder / f"{slug}-FULL.md"
                path.write_text(text, encoding="utf-8")
                latest_full = str(path.relative_to(self.dir)).replace("\\", "/")
        return {"summaries": summaries, "latest_full": latest_full, "count": len(rows),
                "selected_count": len(summaries)}

    def gather_decks(self):
        """Download latest investor materials and render pages text cannot see."""
        deck_dir = self.dir / "documents"
        self.log("stockanalysis-company-research: downloading latest investor materials...")
        for doc_type in ("slides", "earnings_release", "quarterly_report"):
            self.run(SA, ["download", self.ticker, "--type", doc_type, "--latest",
                          "-d", str(deck_dir)], label="stockanalysis-company-research",
                     timeout=420)
        pdfs = sorted(deck_dir.glob("*.pdf")) if deck_dir.exists() else []
        if not pdfs:
            self.errors.append({"source": "investor-materials", "message": "no PDF materials available"})
            return {"files": [], "audit": None, "text_dir": None, "sheets_dir": None}

        audit = self.run(DECKS, ["audit", str(deck_dir)], label="decks", timeout=300)
        text_dir = self.dir / "deck-text"
        sheets_dir = self.dir / "deck-sheets"
        self.run(DECKS, ["text", str(deck_dir), "-o", str(text_dir)],
                 label="decks", timeout=300)
        self.log("decks: rendering contact sheets for visual reading...")
        self.run(DECKS, ["sheets", str(deck_dir), "-o", str(sheets_dir)],
                 label="decks", timeout=600)
        return {
            "files": [p.name for p in pdfs],
            "audit": audit,
            "text_dir": "deck-text",
            "sheets_dir": "deck-sheets",
            "sheets": sorted(p.name for p in sheets_dir.glob("*.png")) if sheets_dir.exists() else [],
        }

    # -- orchestration -----------------------------------------------------
    def collect(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=7) as pool:
            f_sa = pool.submit(self.gather_stockanalysis)
            f_fv = pool.submit(self.gather_finviz)
            f_fv_stock = pool.submit(self.gather_finviz_snapshot)
            f_quote = pool.submit(self.gather_quote)
            f_px = pool.submit(self.gather_prices)
            f_cal = pool.submit(self.gather_calendar)
            f_news = (pool.submit(self.gather_market_news)
                      if self.depth == "deep" else None)
            f_macro = (pool.submit(self.gather_macro)
                       if self.depth == "deep" else None)
            sa_data = f_sa.result()
            finviz = f_fv.result()
            finviz_stock = f_fv_stock.result()
            quote = f_quote.result()
            bars = f_px.result()
            calendar = f_cal.result()
            market_news = f_news.result() if f_news else None
            macro = f_macro.result() if f_macro else None

        quote_type = str((quote or {}).get("quote_type") or "").upper()
        if quote_type in {"ETF", "MUTUALFUND", "INDEX", "CRYPTOCURRENCY", "CURRENCY"}:
            raise UnsupportedInstrumentError(self.ticker, quote_type)

        # fair-value shells out to finviz and yahoo itself, so run it after their
        # caches are warm rather than alongside them.
        fair_value = self.gather_fair_value()

        technicals = indicators.summarise(bars) if bars else None
        if technicals and finviz:
            technicals["cross_check"] = _cross_check(technicals, finviz.get("snapshot") or {})

        transcripts = self.gather_transcripts((sa_data or {}).get("transcript_index"))
        decks = {"files": []}
        if self.depth == "deep":
            decks = self.gather_decks()

        snapshot = (finviz or {}).get("snapshot") or {}
        if finviz_stock is None:
            finviz_stock = {
                "schema_version": "fallback",
                "source": "finviz-stock-research",
                "ticker": self.ticker,
                "status": "partial",
                "coverage_note": "No browser capture supplied; using the Finviz earnings snapshot.",
                "pages": {"earnings_fallback": {"status": "captured", "data": snapshot}},
            }
        bundle = {
            "meta": {
                "ticker": self.ticker,
                "name": ((sa_data or {}).get("profile") or {}).get("name")
                or (quote or {}).get("name")
                or (finviz or {}).get("company"),
                "depth": self.depth,
                "collected_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "runtime_seconds": round(time.time() - self.started, 1),
            },
            "provenance": PROVENANCE,
            "errors": self.errors,
            "source_status": self.source_status,
            "quote": quote,
            "finviz_stock": finviz_stock,
            "profile": (sa_data or {}).get("profile"),
            "overview": _slim_overview((sa_data or {}).get("overview")),
            "statistics": (sa_data or {}).get("statistics"),
            "financials": {
                "income_annual": (sa_data or {}).get("income_annual"),
                "income_quarterly": (sa_data or {}).get("income_quarterly"),
                "ratios_annual": (sa_data or {}).get("ratios_annual"),
            },
            "forecast": (sa_data or {}).get("forecast"),
            "segments": (sa_data or {}).get("segments"),
            "news": (sa_data or {}).get("news"),
            "filings": (sa_data or {}).get("filings"),
            "finviz": {
                "snapshot": snapshot,
                "quarterly": (finviz or {}).get("quarterly") or [],
                "annual": (finviz or {}).get("annual") or [],
                "price_reactions": (finviz or {}).get("price_reactions") or [],
                "next_report": (finviz or {}).get("next_report"),
                "revisions": _sample_revisions(
                    (finviz or {}).get("revisions") or [],
                    [r.get("fiscal_period") for r in ((finviz or {}).get("annual") or [])
                     if not r.get("reported")]),
            },
            "calendar": calendar,
            "fair_value": fair_value,
            "technicals": technicals,
            "transcripts": transcripts,
            "decks": decks,
            "market_news": market_news,
            "macro": macro,
        }
        bundle["cross_checks"] = _reconcile(bundle)

        # The heavy arrays are chart input, never reading material. Splitting them
        # out keeps bundle.json small enough for the model to read whole — with
        # them inlined it is ~500KB, most of it daily price points.
        series = {
            "technicals": (bundle["technicals"] or {}).pop("series", None)
            if bundle["technicals"] else None,
            "fair_value": (bundle["fair_value"] or {}).pop("series", None)
            if bundle["fair_value"] else None,
            "finviz_quarterly": bundle["finviz"].pop("quarterly", []),
            "finviz_annual": bundle["finviz"].get("annual", []),
            "finviz_revisions": bundle["finviz"].pop("revisions", []),
            "price_reactions": bundle["finviz"].get("price_reactions", []),
            "segments": bundle.pop("segments", None),
        }
        bundle["series_file"] = "series.json"
        bundle["segments_summary"] = _segment_summary(series["segments"])
        bundle["finviz"]["quarterly_recent"] = series["finviz_quarterly"][-8:]
        bundle["finviz"]["revision_trend"] = _revision_trend(series["finviz_revisions"])
        bundle["filings"] = _slim_filings(bundle.get("filings"))
        bundle["news"] = _slim_news(bundle.get("news"))

        (self.dir / "series.json").write_text(
            json.dumps(series, default=str), encoding="utf-8")
        (self.dir / "bundle.json").write_text(
            json.dumps(bundle, indent=2, default=str), encoding="utf-8")
        (self.dir / "READ-ME-FIRST.md").write_text(_briefing(bundle, self.dir),
                                                   encoding="utf-8")
        return bundle


class InvalidTickerError(ValueError):
    def __init__(self, ticker):
        super().__init__(
            f"'{ticker}' is not a valid stock ticker. Use letters followed by "
            "letters, numbers, dots, or hyphens."
        )


class UnsupportedInstrumentError(Exception):
    def __init__(self, ticker, instrument):
        super().__init__(
            f"'{ticker}' resolved to '{instrument}'. This skill forecasts operating "
            "companies and does not publish incomplete ETF, fund, index, crypto, "
            "currency, or futures reports.")




# --------------------------------------------------------------------------
# Shaping helpers
# --------------------------------------------------------------------------

def _extract_section(markdown, heading):
    """Pull one '#### Heading' block out of a transcript summary."""
    start = markdown.find(f"#### {heading}")
    if start < 0:
        return None
    start += len(heading) + 5
    end = markdown.find("\n#### ", start)
    if end < 0:
        end = markdown.find("\n### ", start)
    return markdown[start: end if end > 0 else start + 2000].strip() or None


def _slim_overview(overview):
    if not overview:
        return None
    drop = {"news", "profile_facts", "financial_summary", "description"}
    return {k: v for k, v in overview.items() if k not in drop}


def _sample_revisions(rows, forward_periods=None, metrics=("eps",), keep_periods=2,
                      every_days=7):
    """8,800 rows is a chart nobody can draw. Keep EPS consensus for the fiscal
    years that are still *ahead*, weekly.

    The forward periods come from finviz's own unreported annual rows rather than
    from sorting the labels — lexical order happily selects a fiscal year that
    has already closed, which then charts a 'forecast' of a known result.
    """
    if not rows:
        return []
    wanted = [r for r in rows if r.get("metric") in metrics and r.get("mean")]
    if forward_periods:
        forward = list(forward_periods)[:keep_periods]
    else:
        periods = sorted({r["fiscal_period"] for r in wanted if r.get("fiscal_period")})
        forward = [p for p in periods if "FY" in str(p)][-keep_periods:] or periods[-keep_periods:]
    out, last_kept = [], {}
    for row in sorted(wanted, key=lambda r: (r.get("fiscal_period") or "", r.get("date") or "")):
        period = row.get("fiscal_period")
        if period not in forward:
            continue
        date = row.get("date") or ""
        previous = last_kept.get(period)
        if previous and _days_between(previous, date) < every_days:
            continue
        last_kept[period] = date
        out.append({k: row.get(k) for k in
                    ("fiscal_period", "date", "mean", "high", "low", "analysts",
                     "up_revisions", "down_revisions", "price")})
    return out


def _days_between(a, b):
    import datetime as dt
    try:
        return (dt.date.fromisoformat(b[:10]) - dt.date.fromisoformat(a[:10])).days
    except ValueError:
        return 999


def _snapshot_num(snapshot, key):
    cell = (snapshot or {}).get(key)
    if not isinstance(cell, dict):
        return None
    if cell.get("num") is not None:
        return float(cell["num"])
    import re
    m = re.search(r"-?\d+(?:\.\d+)?", str(cell.get("value") or ""))
    return float(m.group(0)) if m else None


def _cross_check(technicals, snapshot):
    """Our computed indicators against the ones finviz publishes.

    The SMA gaps track the price difference between our last daily bar and
    finviz's live quote; that is expected. RSI and ATR should match closely.
    """
    latest = technicals["latest"]
    checks = []
    for label, ours, theirs, tol in (
        ("RSI (14)", latest.get("rsi14"), _snapshot_num(snapshot, "RSI (14)"), 2.0),
        ("ATR (14)", latest.get("atr14"), _snapshot_num(snapshot, "ATR (14)"), 0.8),
    ):
        if ours is None or theirs is None:
            continue
        checks.append({"metric": label, "ours": round(ours, 2), "theirs": theirs,
                       "ok": abs(ours - theirs) <= tol})
    live = _snapshot_num(snapshot, "Price")
    if live and technicals.get("price"):
        checks.append({"metric": "price (last bar vs live)",
                       "ours": round(technicals["price"], 2), "theirs": live,
                       "ok": abs(technicals["price"] / live - 1) <= 0.05})
    return checks


def _reconcile(bundle):
    """Where two sources report the same thing, surface the gap rather than average."""
    out = []
    snapshot = bundle["finviz"]["snapshot"]
    quote_price = (bundle.get("quote") or {}).get("price")
    finviz_price = _snapshot_num(snapshot, "Price")
    if quote_price and finviz_price:
        quote_gap = abs(float(quote_price) / finviz_price - 1)
        out.append({"field": "live quote", "yahoo-market-data": round(float(quote_price), 2),
                    "finviz": finviz_price, "gap_pct": round(quote_gap * 100, 2),
                    "agree": quote_gap <= 0.01})
    forecast = bundle.get("forecast") or {}
    target_sa = ((forecast.get("price_target") or {}).get("average"))
    target_fv = _snapshot_num(snapshot, "Target Price")
    if target_sa and target_fv:
        gap = abs(target_sa / target_fv - 1)
        out.append({"field": "analyst price target", "stockanalysis": round(target_sa, 2),
                    "finviz": target_fv, "gap_pct": round(gap * 100, 1),
                    "agree": gap <= 0.05})
    next_finviz = (bundle["finviz"].get("next_report") or {}).get("date")
    calendar = bundle.get("calendar")
    next_cal = None
    if isinstance(calendar, list) and calendar:
        # the calendar returns newest-first; the *next* report is the earliest
        # date still unreported, not the furthest one out
        upcoming = sorted((r for r in calendar if not r.get("reported")),
                          key=lambda r: r.get("date") or "")
        next_cal = (upcoming[0].get("date") if upcoming else None)
    # finviz's `next_report` can still be pointing at the quarter that just
    # reported. The next report is the earliest candidate date still in the
    # future — showing a past date as "next earnings" is a visible wrong answer.
    import datetime as _dt
    today = _dt.date.today().isoformat()
    future = sorted(d for d in (next_finviz, next_cal) if d and d >= today)
    resolved = future[0] if future else None
    if next_finviz or next_cal:
        out.append({"field": "next report date", "finviz": next_finviz,
                    "earnings-calendar": next_cal, "resolved": resolved,
                    "agree": bool(next_finviz and next_cal and next_finviz == next_cal)})
    bundle.setdefault("resolved", {})["next_report_date"] = resolved
    fair_value = bundle.get("fair_value") or {}
    if fair_value.get("price") and finviz_price:
        out.append({"field": "valuation-engine input price", "normal-multiple-valuation": fair_value["price"],
                    "finviz": finviz_price,
                    "agree": abs(float(fair_value["price"]) / finviz_price - 1) <= 0.01})
    return out


def _segment_summary(segments, keep=3):
    """Segment tables are large; keep the newest column of each so the reader can
    see the revenue mix without the whole history."""
    if not segments:
        return None
    out = []
    for group in (segments.get("groups") or [])[:keep]:
        rows = []
        for row in (group.get("rows") or [])[:12]:
            values = row.get("values") or []
            rows.append({"label": row.get("title") or row.get("label"),
                         "latest": values[0] if values else None,
                         "prior": values[1] if len(values) > 1 else None})
        out.append({"title": group.get("title"),
                    "periods": (group.get("periods") or [])[:2], "rows": rows})
    return out


def _revision_trend(rows, windows=(90, 180)):
    """Direction of the consensus over the last 90 and 180 days — the number the
    scorecard actually uses, rather than 146 raw snapshots."""
    if not rows:
        return None
    import datetime as _dt
    by_period = {}
    for row in rows:
        by_period.setdefault(row.get("fiscal_period"), []).append(row)
    out = []
    for period, series in by_period.items():
        series.sort(key=lambda r: r.get("date") or "")
        latest = series[-1]
        try:
            end = _dt.date.fromisoformat(latest["date"][:10])
        except (KeyError, ValueError, TypeError):
            continue
        entry = {"fiscal_period": period, "latest_mean": latest.get("mean"),
                 "analysts": latest.get("analysts")}
        for days in windows:
            target = end - _dt.timedelta(days=days)
            earlier = [r for r in series
                       if r.get("date") and _dt.date.fromisoformat(r["date"][:10]) <= target]
            if earlier and earlier[-1].get("mean"):
                base = float(earlier[-1]["mean"])
                entry[f"change_{days}d_pct"] = round(
                    (float(latest["mean"]) / base - 1) * 100, 2) if base else None
        entry["up_revisions"] = sum(r.get("up_revisions") or 0 for r in series[-12:])
        entry["down_revisions"] = sum(r.get("down_revisions") or 0 for r in series[-12:])
        out.append(entry)
    return out


def _slim_filings(filings, keep=14):
    if not filings:
        return None
    rows = filings.get("filings") or filings.get("documents") or filings.get("rows") or []
    return {"count": len(rows), "types": filings.get("types"), "recent": rows[:keep]}


def _slim_news(news, keep=8):
    if not news:
        return None
    rows = news.get("news") or news.get("items") or news.get("rows") or []
    return [{k: item.get(k) for k in ("date", "title", "source", "url", "summary")}
            for item in rows[:keep]]


def _briefing(bundle, folder):
    """What the model should read next, and what it must write."""
    ticker = bundle["meta"]["ticker"]
    transcripts = bundle["transcripts"]
    decks = bundle.get("decks") or {}
    sheets = decks.get("sheets") or []
    fair_value = bundle.get("fair_value") or {}
    refused = fair_value.get("refused")

    lines = [
        f"# {ticker} — collected bundle", "",
        f"Depth **{bundle['meta']['depth']}** · collected {bundle['meta']['collected_at']} "
        f"· {bundle['meta']['runtime_seconds']}s", "",
        "## Read these, in this order", "",
        "1. `bundle.json` — every number the page will show. Nothing goes on the page "
        "that is not in here.",
    ]
    if bundle.get("finviz_stock", {}).get("status") == "partial":
        lines.append("2. `finviz_stock` is a partial fallback. If a browser capture is available, "
                     "rerun collection with `--finviz-snapshot` to add the broader Finviz tabs.")
    if transcripts["summaries"]:
        lines.append(f"3. `transcripts/*.md` — {len(transcripts['summaries'])} quarterly "
                     "summaries. Each has **Outlook and guidance**; compare quarter N-1's "
                     "guidance against quarter N's highlights. That comparison IS the "
                     "said-vs-delivered table.")
    if transcripts.get("latest_full"):
        lines.append(f"4. `{transcripts['latest_full']}` — the full latest call. Read the "
                     "Q&A: who asked what, who got a straight answer, what got deflected.")
    if sheets:
        lines.append(f"5. `deck-sheets/` — {len(sheets)} contact sheets. **Look at these "
                     "images.** Investor decks bake text into pictures; roughly half the "
                     "pages of a keynote deck return nothing to text extraction. The audit "
                     "in `bundle.decks.audit` says which pages those are.")
        lines.append(f"6. `deck-text/` — extracted text for the pages that do have it.")
    lines += ["", "## Then write `analysis.json` here", "",
              "Required keys — `render.py` refuses to build the page without them:", "",
              "```",
              "company_explainer   what it actually does, plain language",
              "said_vs_delivered[] {quarter, guided, delivered, verdict, quote}",
              "qa_read             who got answers, what was deflected",
              "deck_findings[]     what the slides show (incl. image-only pages)",
              "section_commentary  {technicals, financials, fair_value, revisions, ...}",
              "scorecard[]         {dimension, score -2..2, weight, evidence, source}",
              "rating              BUY | SELL   (never neutral)",
              "conviction          high | medium | low",
              "target_price        {value, horizon, derivation, bull, bear}",
              "falsifiers[]        what would prove this call wrong",
              "```", ""]
    lines += ["## Decision rules", "",
              "Score the six required dimensions from -2 to +2: earnings execution "
              "(25%), financial trajectory and balance sheet (20%), forward estimates "
              "and revisions (15%), valuation (20%), technical setup (10%), and market "
              "and macro backdrop (10%). Exclude unavailable dimensions and renormalize "
              "the remaining weights. Composite > 0 is BUY; composite <= 0 is SELL.", "",
              "For the 12-month target, use normal-multiple fair value as the primary "
              "anchor, apply a bounded quality adjustment, and blend 75% of that result "
              "with 25% analyst consensus when reliable. If both anchors are unavailable, "
              "set target_price.value to null and explain why; never invent a number.", ""]
    if refused:
        lines += ["> ⚠ **fair-value refused for this name.** Score the valuation "
                  "dimension as unavailable, drop conviction, and say so on the page. "
                  "Do not invent a fair value.", ""]
    if bundle.get("macro"):
        lines += ["Macro events are in `bundle.json`. Use recent, thisweek, and nextweek "
                  "to explain the market backdrop without treating macro releases as company facts.", ""]
    if bundle["errors"]:
        lines += ["## Collection errors", ""]
        lines += [f"- **{e['source']}** — {e['message']}" for e in bundle["errors"]]
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="collect.py", description="Gather every skill's view of one ticker.")
    parser.add_argument("ticker")
    parser.add_argument("--depth", choices=list(DEPTHS), default="deep")
    parser.add_argument("-d", "--dir", help="bundle directory (default ./TICKER-bundle)")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--finviz-snapshot",
        help="optional merged browser-captured Finviz snapshot JSON",
    )
    args = parser.parse_args(argv)

    out_dir = args.dir or f"./{args.ticker.upper()}-bundle"
    try:
        collector = Collector(args.ticker, args.depth, out_dir, args.refresh,
                              args.finviz_snapshot)
        print(f"collecting {collector.ticker} ({args.depth})...", file=sys.stderr)
        bundle = collector.collect()
    except (InvalidTickerError, UnsupportedInstrumentError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    errors = len(bundle["errors"])
    print(f"\nbundle -> {out_dir}", file=sys.stderr)
    print(f"  {bundle['meta']['runtime_seconds']}s · "
          f"{len(bundle['transcripts']['summaries'])} transcript summaries · "
          f"{len((bundle.get('decks') or {}).get('sheets') or [])} deck sheets · "
          f"{errors} error{'' if errors == 1 else 's'}", file=sys.stderr)
    print(f"  next: read {out_dir}/READ-ME-FIRST.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
