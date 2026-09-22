"""Data adapters for the fair-value skill.

Every byte comes through a sibling skill's CLI, so their caches, throttles and
User-Agent headers apply. We add one cache layer of our own because
yahoo-finance has none.

Nothing in this module does maths. Nothing in fv_model does I/O.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CACHE_DIR = Path(tempfile.gettempdir()) / "fair-value-cache"
CACHE_TTL = int(os.environ.get("FV_CACHE_TTL", "21600"))  # 6 hours

_SKILLS = Path(__file__).resolve().parents[2]

SCRIPTS = {
    "finviz": Path(os.environ.get(
        "FV_FINVIZ_SCRIPT",
        _SKILLS / "finviz-earnings" / "scripts" / "finviz_earnings.py")),
    "yahoo": Path(os.environ.get(
        "FV_YF_SCRIPT",
        _SKILLS / "yahoo-finance" / "scripts" / "yf.py")),
    "sa": Path(os.environ.get(
        "FV_SA_SCRIPT",
        _SKILLS / "stockanalysis" / "scripts" / "sa.py")),
}

INSTALL_HINT = {
    "finviz": "the finviz-earnings skill",
    "yahoo": "the yahoo-finance skill",
    "sa": "the stockanalysis skill",
}


class FVDataError(Exception):
    """A source could not be read. Carries a user-facing message."""

    def __init__(self, source, message):
        self.source = source
        super().__init__(message)


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------

def _cache_file(source, ticker, args):
    key = hashlib.sha256("|".join([source, ticker, *map(str, args)]).encode()).hexdigest()[:16]
    return CACHE_DIR / f"fv-{ticker.upper()}-{source}-{key}.json"


def _cache_read(path, refresh):
    if refresh:
        return None
    try:
        if time.time() - path.stat().st_mtime > CACHE_TTL:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _cache_write(path, payload):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except (OSError, TypeError):
        pass


def cache_clear():
    n = 0
    try:
        for f in CACHE_DIR.glob("fv-*.json"):
            f.unlink()
            n += 1
    except OSError:
        pass
    return n


# --------------------------------------------------------------------------
# Subprocess
# --------------------------------------------------------------------------

def _run(source, args, timeout=120):
    script = SCRIPTS[source]
    if not script.exists():
        raise FVDataError(source, f"{INSTALL_HINT[source]} is not installed at {script}")
    try:
        proc = subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise FVDataError(source, f"{INSTALL_HINT[source]} timed out after {timeout}s")
    if proc.returncode != 0 or not proc.stdout.strip():
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = detail[-1] if detail else f"exit {proc.returncode}"
        raise FVDataError(source, detail)
    return proc.stdout


# --------------------------------------------------------------------------
# finviz — one call carries EPS history, forward estimates and the snapshot
# --------------------------------------------------------------------------

def finviz_raw(ticker, refresh=False):
    path = _cache_file("finviz", ticker, ["raw"])
    hit = _cache_read(path, refresh)
    if hit is not None:
        return hit

    args = ["raw", ticker, "-f", "json"]
    if refresh:
        args.append("--refresh")
    try:
        raw = json.loads(_run("finviz", args))
    except ValueError as exc:
        raise FVDataError("finviz", f"unreadable JSON from finviz-earnings: {exc}")

    # `revisions` is ~9,000 rows we never use; drop it before it hits the cache.
    slim = {
        "ticker": raw.get("ticker"),
        "company": raw.get("company"),
        "fetched_at": raw.get("fetched_at"),
        "next_report": raw.get("next_report"),
        "quarterly": raw.get("quarterly") or [],
        "annual": raw.get("annual") or [],
        "snapshot": raw.get("snapshot") or {},
    }
    if not slim["quarterly"]:
        raise FVDataError("finviz", f"no earnings history for '{ticker}'")
    _cache_write(path, slim)
    return slim


def snapshot_num(snapshot, key):
    """Snapshot values are {value, num, description}; `num` is null on the
    two-figure cells like Dividend TTM '0.28 (0.13%)'."""
    cell = (snapshot or {}).get(key)
    if not isinstance(cell, dict):
        return None
    if cell.get("num") is not None:
        return float(cell["num"])
    m = re.search(r"-?\d+(?:\.\d+)?", str(cell.get("value") or ""))
    return float(m.group(0)) if m else None


def snapshot_pct(snapshot, key):
    """The parenthesised percentage of a two-figure cell, as a fraction."""
    cell = (snapshot or {}).get(key)
    if not isinstance(cell, dict):
        return None
    m = re.search(r"\((-?\d+(?:\.\d+)?)%\)", str(cell.get("value") or ""))
    return float(m.group(1)) / 100.0 if m else None


# --------------------------------------------------------------------------
# yahoo — weekly closes. NEVER adj_close: see the module docstring in SKILL.md
# --------------------------------------------------------------------------

def weekly_closes(ticker, refresh=False):
    """[(YYYY-MM-DD, close)] weekly, oldest first, back as far as Yahoo goes.

    Uses the raw `close` column, which is split-adjusted but NOT dividend
    adjusted. `adj_close` strips dividends and would understate the historical
    multiple of every dividend payer (KO 2015: 42.14 vs 29.39).
    """
    path = _cache_file("yahoo", ticker, ["max", "1wk"])
    hit = _cache_read(path, refresh)
    if hit is not None:
        return [(d, float(c)) for d, c in hit]

    out = _run("yahoo", ["history", ticker, "--period", "max",
                         "--interval", "1wk", "--format", "csv"])
    bars = []
    for row in csv.DictReader(io.StringIO(out)):
        close = row.get("close")
        date = row.get("date")
        if not date or close in (None, "", "nan"):
            continue
        try:
            value = float(close)
        except ValueError:
            continue
        if value > 0:
            bars.append((date[:10], value))
    if not bars:
        raise FVDataError("yahoo", f"no price history for '{ticker}'")
    bars.sort(key=lambda b: b[0])
    _cache_write(path, bars)
    return bars


# --------------------------------------------------------------------------
# stockanalysis — only for the P/S fallback (share count reconstruction)
# --------------------------------------------------------------------------

def sa_share_counts(ticker, refresh=False):
    """[(period_end_date, shares)] from marketCap / lastClosePrice.

    Free tier returns 20 trailing quarters, so the P/S window caps at ~5 years.
    """
    path = _cache_file("sa", ticker, ["ratios", "trailing"])
    hit = _cache_read(path, refresh)
    if hit is not None:
        return [(d, float(s)) for d, s in hit]

    args = ["financials", ticker, "-s", "ratios", "-p", "trailing", "--format", "json"]
    if refresh:
        args.append("--refresh")
    try:
        payload = json.loads(_run("sa", args))
    except ValueError as exc:
        raise FVDataError("sa", f"unreadable JSON from stockanalysis: {exc}")

    periods = payload.get("periods") or []
    rows = {r.get("id"): r.get("values") or [] for r in (payload.get("rows") or [])}
    caps, prices = rows.get("marketCap") or [], rows.get("lastClosePrice") or []
    counts = []
    for i, period in enumerate(periods):
        date = (period or {}).get("date")
        cap = caps[i] if i < len(caps) else None
        price = prices[i] if i < len(prices) else None
        # The first column is the rolling window, labelled "TTM" rather than a
        # date; skip it and let the newest real quarter carry recent weeks.
        if not date or not re.match(r"^\d{4}-\d{2}-\d{2}", str(date)) or not cap or not price:
            continue
        try:
            shares = float(cap) / float(price)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if shares > 0:
            counts.append((str(date)[:10], shares))
    if not counts:
        raise FVDataError("sa", f"no share-count data for '{ticker}'")
    counts.sort(key=lambda c: c[0])
    _cache_write(path, counts)
    return counts


def sa_current_ps(ticker, refresh=False):
    """stockanalysis' own TTM P/S, for cross-checking our reconstruction."""
    try:
        args = ["financials", ticker, "-s", "ratios", "-p", "trailing", "--format", "json"]
        payload = json.loads(_run("sa", args))
    except (FVDataError, ValueError):
        return None
    for row in payload.get("rows") or []:
        if row.get("id") == "ps":
            values = row.get("values") or []
            return float(values[0]) if values and values[0] else None
    return None
