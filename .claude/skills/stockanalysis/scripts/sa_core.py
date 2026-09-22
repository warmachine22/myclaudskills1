"""Core fetch / cache / decode layer for the stockanalysis.com skill.

stockanalysis.com is a SvelteKit app. Every page URL has a companion data
endpoint: take the page URL (with trailing slash) and append `__data.json`.
It returns the same data the page renders, encoded in svelte's `devalue`
flattened format -- a single array where integers are pointers into that
array. `unflatten()` below rehydrates it into ordinary Python objects.

That means we never parse HTML, so the scraper does not break when the site
restyles. It only breaks if the site changes its data model, which is rare
and loud (missing keys, not silently wrong numbers).

Stdlib only. No API key.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://stockanalysis.com"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# --- politeness ------------------------------------------------------------
# One request at a time, spaced out. The site is a free service; we cache
# aggressively and never hammer it.
MIN_INTERVAL = float(os.environ.get("SA_MIN_INTERVAL", "1.2"))
MAX_RETRIES = 3
TIMEOUT = float(os.environ.get("SA_TIMEOUT", "45"))

_last_request_at = 0.0

CACHE_DIR = Path(
    os.environ.get("SA_CACHE_DIR", Path.home() / ".cache" / "stockanalysis")
)

# Default cache lifetimes in seconds, by logical resource kind.
# Transcripts and filings are immutable once published -> effectively forever.
TTL = {
    "quote": 300,            # 5 min
    "overview": 900,         # 15 min
    "news": 900,
    "financials": 21600,     # 6 h
    "statistics": 21600,
    "metrics": 21600,
    "forecast": 21600,
    "company": 604800,       # 7 d
    "filings": 3600,         # 1 h (new filings appear intraday)
    "transcripts": 3600,     # index: 1 h
    "transcript": 2592000,   # body: 30 d (immutable)
    "history": 3600,
    "default": 21600,
}


class FetchError(RuntimeError):
    pass


class NotFound(FetchError):
    pass


class Redirect(FetchError):
    """SvelteKit answers a wrong-section URL with a redirect node, not a 3xx."""

    def __init__(self, location):
        super().__init__(f"redirect to {location}")
        self.location = location


# --- devalue ---------------------------------------------------------------

_UNDEFINED = -1
_HOLE = -2
_NAN = -3
_POS_INF = -4
_NEG_INF = -5
_NEG_ZERO = -6


def unflatten(values):
    """Rehydrate svelte `devalue.stringify` output into plain Python."""
    if values is None or isinstance(values, (int, float, str, bool)):
        return values
    hydrated: dict[int, object] = {}

    def hydrate(index):
        if index == _UNDEFINED:
            return None
        if index == _NAN:
            return None
        if index == _POS_INF:
            return float("inf")
        if index == _NEG_INF:
            return float("-inf")
        if index == _NEG_ZERO:
            return -0.0
        if index in hydrated:
            return hydrated[index]
        value = values[index]
        if value is None or not isinstance(value, (list, dict)):
            hydrated[index] = value
            return value
        if isinstance(value, list):
            if value and isinstance(value[0], str):
                tag = value[0]
                if tag in ("Date", "RegExp", "BigInt"):
                    hydrated[index] = value[1]
                    return hydrated[index]
                if tag == "Set":
                    out: list = []
                    hydrated[index] = out
                    out.extend(hydrate(i) for i in value[1:])
                    return out
                if tag == "Map":
                    m: dict = {}
                    hydrated[index] = m
                    for i in range(1, len(value), 2):
                        m[str(hydrate(value[i]))] = hydrate(value[i + 1])
                    return m
                if tag == "null":
                    o: dict = {}
                    hydrated[index] = o
                    for i in range(1, len(value), 2):
                        o[value[i]] = hydrate(value[i + 1])
                    return o
            arr: list = []
            hydrated[index] = arr
            arr.extend(None if i == _HOLE else hydrate(i) for i in value)
            return arr
        obj: dict = {}
        hydrated[index] = obj
        for k, v in value.items():
            obj[k] = hydrate(v)
        return obj

    return hydrate(0)


# --- http ------------------------------------------------------------------


def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:20]
    slug = re.sub(r"[^a-z0-9]+", "-", url.replace(BASE, "").lower()).strip("-")[:60]
    return CACHE_DIR / f"{slug or 'root'}--{h}.json"


def _throttle():
    global _last_request_at
    gap = time.time() - _last_request_at
    if gap < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - gap)
    _last_request_at = time.time()


def http_get(url: str, timeout: float = TIMEOUT) -> str:
    """GET with throttling, gzip, and bounded retries. Raises FetchError."""
    last = None
    for attempt in range(MAX_RETRIES):
        _throttle()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound(f"404 {url}") from e
            last = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep((2 ** attempt) * 1.5 + random.random())
                continue
            raise FetchError(f"HTTP {e.code} {url}") from e
        except Exception as e:  # noqa: BLE001 - network flakiness
            last = e
            time.sleep((2 ** attempt) * 1.0 + random.random())
    raise FetchError(f"failed after {MAX_RETRIES} tries: {url} ({last})")


def fetch_data(path: str, params: dict | None = None, kind: str = "default",
               refresh: bool = False, ttl: float | None = None):
    """Fetch a page's `__data.json` and return the decoded node list.

    `path` is site-relative, e.g. "/stocks/nvda/financials/". Trailing slash
    is added if missing. Returns a list of nodes; nodes[0] is layout/session
    state, nodes[1] is symbol info, and the page payload is normally the last
    non-null node (use `page_node()`).
    """
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    url = f"{BASE}{path}__data.json"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)

    cache_ttl = TTL.get(kind, TTL["default"]) if ttl is None else ttl
    cp = _cache_path(url)
    if not refresh and cache_ttl > 0 and cp.exists():
        try:
            if time.time() - cp.stat().st_mtime < cache_ttl:
                with cp.open(encoding="utf-8") as f:
                    return json.load(f)
        except (OSError, ValueError):
            pass

    text = http_get(url)
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise FetchError(f"non-JSON response from {url}") from e

    if doc.get("type") == "redirect":
        raise Redirect(doc.get("location"))

    nodes = []
    for node in doc.get("nodes", []):
        if isinstance(node, dict) and node.get("type") == "data":
            nodes.append(unflatten(node["data"]))
        elif isinstance(node, dict) and node.get("type") == "error":
            # SvelteKit reports a missing route as an error *node* with HTTP
            # 200, not a 404 status. Surface it as NotFound like a real 404.
            status = node.get("status")
            msg = (node.get("error") or {}).get("message", "error")
            if status == 404:
                raise NotFound(f"404 {url} ({msg})")
            raise FetchError(f"{status} {url} ({msg})")
        else:
            nodes.append(None)

    if cache_ttl > 0:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = cp.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(nodes, f)
            tmp.replace(cp)
        except OSError:
            pass
    return nodes


PRO = "[PRO]"


def depro(obj):
    """Replace the site's `"[PRO]"` paywall sentinel with None, recursively.

    Free responses interleave real numbers with this string for periods behind
    the Pro tier. Leaving it in place would poison any arithmetic downstream.
    """
    if isinstance(obj, dict):
        return {k: depro(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [depro(v) for v in obj]
    return None if obj == PRO else obj


def fetch_api(path: str, params: dict | None = None, kind: str = "default",
              refresh: bool = False):
    """Hit stockanalysis.com's REST API (`/api/...`) and return `data`.

    Only worth using for price history: unlike the page endpoints, the API
    actually honours `range`/`period`, so it can return years of bars where the
    page payload is capped at ~6 months.
    """
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    cp = _cache_path(url)
    cache_ttl = TTL.get(kind, TTL["default"])
    if not refresh and cache_ttl > 0 and cp.exists():
        try:
            if time.time() - cp.stat().st_mtime < cache_ttl:
                with cp.open(encoding="utf-8") as f:
                    return json.load(f)
        except (OSError, ValueError):
            pass
    doc = json.loads(http_get(url))
    if doc.get("status") not in (None, 200):
        raise FetchError(f"api status {doc.get('status')} for {url}")
    data = doc.get("data", doc)
    # Shape differs by whether query params were sent: bare calls double-nest.
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        data = data["data"]
    if cache_ttl > 0:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = cp.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(data, f)
            tmp.replace(cp)
        except OSError:
            pass
    return data


def download(url: str, dest: Path, overwrite: bool = False) -> tuple[Path, int, bool]:
    """Fetch a binary asset (IR PDFs) to disk. Returns (path, bytes, skipped).

    Streams to a temp file and renames, so an interrupted run never leaves a
    truncated PDF that a later run would treat as complete.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not overwrite and dest.stat().st_size > 0:
        return dest, dest.stat().st_size, True
    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    total = 0
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp, tmp.open("wb") as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    tmp.replace(dest)
    return dest, total, False


def strip_html(s: str) -> str:
    """Site descriptions arrive as HTML on some tabs and plain text on others."""
    import html as _html
    if not s:
        return ""
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n{3,}", "\n\n", _html.unescape(s)).strip()


def page_node(nodes, want_keys=()):
    """Pick the node holding the page payload.

    Prefer the last non-empty node; if `want_keys` is given, prefer the first
    node containing any of them (guards against layout nodes sneaking in).
    """
    candidates = [n for n in nodes[1:] if isinstance(n, dict) and n]
    if want_keys:
        for n in candidates:
            if any(k in n for k in want_keys):
                return n
    for n in reversed(candidates):
        if "info" not in n or len(n) > 1:
            return n
    return candidates[-1] if candidates else {}


def symbol_info(nodes):
    """The `info` block: name, exchange, quote, currency, available features."""
    for n in nodes:
        if isinstance(n, dict) and isinstance(n.get("info"), dict):
            return n["info"]
    return {}


# --- url building ----------------------------------------------------------

_EXCHANGE_PREFIX = {
    # stockanalysis routes non-US listings under /quote/<mic>/<TICKER>/
    "tsx": "/quote/tsx/", "tsxv": "/quote/tsxv/", "cse": "/quote/cse/",
    "lon": "/quote/lon/", "epa": "/quote/epa/", "etr": "/quote/etr/",
    "ams": "/quote/ams/", "bme": "/quote/bme/", "sto": "/quote/sto/",
    "hel": "/quote/hel/", "cph": "/quote/cph/", "osl": "/quote/osl/",
    "swx": "/quote/swx/", "bit": "/quote/bit/", "wse": "/quote/wse/",
    "tyo": "/quote/tyo/", "hkg": "/quote/hkg/", "shh": "/quote/shh/",
    "shz": "/quote/shz/", "asx": "/quote/asx/", "nse": "/quote/nse/",
    "bom": "/quote/bom/", "kls": "/quote/kls/", "sgx": "/quote/sgx/",
    "krx": "/quote/krx/", "twse": "/quote/twse/", "tal": "/quote/tal/",
    "bmv": "/quote/bmv/", "bvmf": "/quote/bvmf/", "jse": "/quote/jse/",
}


def base_path(ticker: str, kind: str = "stocks") -> str:
    """Site-relative base path for a symbol.

    - "NVDA"        -> /stocks/nvda/
    - "SPY" (etf)   -> /etf/spy/          (pass kind="etf")
    - "TSX:SHOP"    -> /quote/tsx/SHOP/
    """
    t = ticker.strip()
    if ":" in t:
        ex, sym = t.split(":", 1)
        pre = _EXCHANGE_PREFIX.get(ex.strip().lower())
        if pre:
            return f"{pre}{sym.strip().upper()}/"
        return f"/quote/{ex.strip().lower()}/{sym.strip().upper()}/"
    if kind == "etf":
        return f"/etf/{t.lower()}/"
    return f"/stocks/{t.lower()}/"


_base_cache: dict[str, str] = {}


def resolve_base(ticker: str) -> str:
    """Find the right base path for a symbol.

    `/stocks/spy/` doesn't 404 for an ETF -- it answers with a redirect node
    pointing at `/etf/spy/`, so follow that rather than guessing. Memoised
    because every command resolves the base before its real request.
    """
    key = ticker.strip().lower()
    if key in _base_cache:
        return _base_cache[key]
    if ":" in ticker:
        _base_cache[key] = base_path(ticker)
        return _base_cache[key]
    p = base_path(ticker, "stocks")
    try:
        fetch_data(p, kind="overview")
    except Redirect as r:
        loc = r.location or ""
        p = loc if loc.endswith("/") else loc + "/"
        fetch_data(p, kind="overview")   # confirm the target actually resolves
    except NotFound:
        p = base_path(ticker, "etf")
        try:
            fetch_data(p, kind="overview")
        except NotFound:
            raise NotFound(
                f"no stockanalysis.com page for {ticker!r} (tried "
                f"{base_path(ticker, 'stocks')} and {p}). For a non-US listing "
                f"use EXCHANGE:TICKER, e.g. TSX:SHOP.") from None
    _base_cache[key] = p
    return p


# --- formatting helpers ----------------------------------------------------


def human(n, digits: int = 2, pct: bool = False):
    """Format a number the way a human reads it: 5.31T, 215.94B, -3.4%."""
    if n is None or isinstance(n, bool):
        return "n/a"
    if isinstance(n, str):
        return n
    try:
        x = float(n)
    except (TypeError, ValueError):
        return str(n)
    if x != x or x in (float("inf"), float("-inf")):
        return "n/a"
    if pct:
        return f"{x:,.{digits}f}%"
    a = abs(x)
    for cut, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= cut:
            return f"{x / cut:,.{digits}f}{suf}"
    if a < 10:
        return f"{x:,.{digits}f}"
    return f"{x:,.0f}"


def md_table(headers, rows) -> str:
    """GitHub-flavoured markdown table. Values are stringified as-is."""
    headers = [str(h) for h in headers]
    body = [[("" if c is None else str(c)) for c in r] for r in rows]
    widths = [len(h) for h in headers]
    for r in body:
        for i, c in enumerate(r[: len(widths)]):
            widths[i] = max(widths[i], len(c))
    out = ["| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |",
           "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
    for r in body:
        cells = [(r[i] if i < len(r) else "").ljust(widths[i]) for i in range(len(widths))]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def emit(obj, fmt: str, md_fn=None, out=None):
    """Write `obj` as json, or as markdown via `md_fn(obj)`."""
    if fmt == "json":
        text = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    else:
        text = md_fn(obj) if md_fn else json.dumps(obj, indent=2, default=str)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        print(f"wrote {out} ({len(text):,} chars)", file=sys.stderr)
    else:
        print(text)


def clear_cache() -> int:
    n = 0
    if CACHE_DIR.exists():
        for f in CACHE_DIR.glob("*.json"):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    return n
