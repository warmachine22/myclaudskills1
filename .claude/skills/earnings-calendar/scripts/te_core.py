"""Shared helpers for the Trading Economics calendar skills.

Stdlib only. Handles HTTP with a polite UA + retry, an on-disk response cache,
date-range presets that mirror the site's own dropdown, and country-code
normalisation (TE uses lowercase ISO3 everywhere).
"""

from __future__ import annotations

import datetime as _dt
import gzip
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

CACHE_DIR = os.path.join(tempfile.gettempdir(), "te-calendar-cache")
DEFAULT_TTL = 600  # seconds


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, hashlib.sha256(key.encode()).hexdigest()[:32] + ".cache")


def cache_get(key: str, ttl: int):
    if ttl <= 0:
        return None
    p = _cache_path(key)
    try:
        if time.time() - os.path.getmtime(p) > ttl:
            return None
        with open(p, "rb") as fh:
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return None


def cache_put(key: str, value: str) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "wb") as fh:
            fh.write(value.encode("utf-8"))
    except OSError:
        pass


def cache_clear() -> int:
    n = 0
    try:
        for f in os.listdir(CACHE_DIR):
            if f.endswith(".cache"):
                os.remove(os.path.join(CACHE_DIR, f))
                n += 1
    except OSError:
        pass
    return n


# tradingeconomics.com serves a short-lived edge cache that can hand back the
# previous response when two requests land within a second or so of each other —
# different cookies, same body. Spacing live requests avoids it, and is the
# polite thing to do anyway.
MIN_INTERVAL = 2.5
_last_request = [0.0]


def _throttle():
    wait = MIN_INTERVAL - (time.time() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    _last_request[0] = time.time()


def _decode(resp) -> str:
    raw = resp.read()
    enc = (resp.headers.get("Content-Encoding") or "").lower()
    if enc == "gzip":
        raw = gzip.decompress(raw)
    elif enc == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, "replace")


def fetch(url, *, cookies=None, headers=None, data=None, ttl=DEFAULT_TTL, retries=3,
          soft=False):
    """GET (or POST when `data` is given) with cache, gzip and retry.

    `soft=True` returns None instead of exiting when the request fails — used by
    callers that have a recovery path (e.g. re-discovering a server action ID).
    """
    ck = "\n".join([url, cookies or "", (data or b"").decode("utf-8", "replace") if isinstance(data, bytes) else (data or "")])
    hit = cache_get(ck, ttl)
    if hit is not None:
        return hit

    hdrs = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }
    if cookies:
        hdrs["Cookie"] = cookies
    if headers:
        hdrs.update(headers)
    body = data.encode("utf-8") if isinstance(data, str) else data

    last = None
    for attempt in range(retries):
        try:
            _throttle()
            req = urllib.request.Request(url, data=body, headers=hdrs)
            with urllib.request.urlopen(req, timeout=45) as resp:
                text = _decode(resp)
            cache_put(ck, text)
            return text
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last = exc
            if soft and isinstance(exc, urllib.error.HTTPError):
                return None  # caller has its own recovery path
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    if soft:
        return None
    raise SystemExit(f"fetch failed for {url}: {last}")


# --------------------------------------------------------------------------
# Date ranges — mirrors the site's own dropdown semantics
# --------------------------------------------------------------------------

RANGES = [
    "recent", "today", "tomorrow", "thisweek", "nextweek", "thismonth",
    "nextmonth", "yesterday", "prevweek", "prevmonth",
]

_RANGE_ALIASES = {
    "this-week": "thisweek", "this week": "thisweek", "week": "thisweek",
    "next-week": "nextweek", "next week": "nextweek",
    "this-month": "thismonth", "this month": "thismonth", "month": "thismonth",
    "next-month": "nextmonth", "next month": "nextmonth",
    "last-week": "prevweek", "last week": "prevweek", "lastweek": "prevweek",
    "previous-week": "prevweek", "previous week": "prevweek",
    "last-month": "prevmonth", "last month": "prevmonth", "lastmonth": "prevmonth",
    "previous-month": "prevmonth", "previous month": "prevmonth",
    "upcoming": "recent",
}


def resolve_range(name, today=None):
    """Return (start_date, end_date) as inclusive ISO strings.

    Week boundaries are Sunday-to-Saturday, exactly as tradingeconomics.com
    computes them. `recent` is yesterday .. today+5.
    """
    key = _RANGE_ALIASES.get(str(name).strip().lower(), str(name).strip().lower())
    d = today or _dt.date.today()
    if key == "recent":
        s, e = d - _dt.timedelta(days=1), d + _dt.timedelta(days=5)
    elif key == "today":
        s = e = d
    elif key == "tomorrow":
        s = e = d + _dt.timedelta(days=1)
    elif key == "yesterday":
        s = e = d - _dt.timedelta(days=1)
    elif key in ("thisweek", "nextweek", "prevweek"):
        sunday = d - _dt.timedelta(days=(d.weekday() + 1) % 7)
        shift = {"thisweek": 0, "nextweek": 7, "prevweek": -7}[key]
        s = sunday + _dt.timedelta(days=shift)
        e = s + _dt.timedelta(days=6)
    elif key == "thismonth":
        s = d.replace(day=1)
        e = (s + _dt.timedelta(days=32)).replace(day=1) - _dt.timedelta(days=1)
    elif key == "nextmonth":
        s = (d.replace(day=1) + _dt.timedelta(days=32)).replace(day=1)
        e = (s + _dt.timedelta(days=32)).replace(day=1) - _dt.timedelta(days=1)
    elif key == "prevmonth":
        e = d.replace(day=1) - _dt.timedelta(days=1)
        s = e.replace(day=1)
    else:
        raise SystemExit(
            f"unknown range '{name}'. Use one of: {', '.join(RANGES)} "
            "(or --start/--end for a custom window)."
        )
    return s.isoformat(), e.isoformat()


def parse_date(text):
    t = str(text).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d-%m-%Y", "%b %d %Y", "%B %d %Y"):
        try:
            return _dt.datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            continue
    raise SystemExit(f"could not parse date '{text}' (expected YYYY-MM-DD)")


def day_label(iso):
    try:
        d = _dt.date.fromisoformat(iso)
    except ValueError:
        return iso
    return d.strftime("%A, %B %d %Y").replace(" 0", " ")


# --------------------------------------------------------------------------
# Countries — TE uses lowercase ISO3 in both the cookie and the server action
# --------------------------------------------------------------------------

ISO3 = {
    "argentina": "arg", "australia": "aus", "austria": "aut", "bangladesh": "bgd",
    "belgium": "bel", "brazil": "bra", "bulgaria": "bgr", "canada": "can",
    "chile": "chl", "china": "chn", "colombia": "col", "croatia": "hrv",
    "cyprus": "cyp", "czech republic": "cze", "czechia": "cze", "denmark": "dnk",
    "egypt": "egy", "estonia": "est", "euro area": "emu", "eurozone": "emu",
    "finland": "fin", "france": "fra", "germany": "deu", "greece": "grc",
    "hong kong": "hkg", "hungary": "hun", "iceland": "isl", "india": "ind",
    "indonesia": "idn", "ireland": "irl", "israel": "isr", "italy": "ita",
    "japan": "jpn", "kenya": "ken", "latvia": "lva", "lithuania": "ltu",
    "luxembourg": "lux", "malaysia": "mys", "mexico": "mex", "morocco": "mar",
    "netherlands": "nld", "new zealand": "nzl", "nigeria": "nga", "norway": "nor",
    "pakistan": "pak", "peru": "per", "philippines": "phl", "poland": "pol",
    "portugal": "prt", "qatar": "qat", "romania": "rou", "russia": "rus",
    "saudi arabia": "sau", "singapore": "sgp", "slovakia": "svk", "slovenia": "svn",
    "south africa": "zaf", "south korea": "kor", "korea": "kor", "spain": "esp",
    "sri lanka": "lka", "sweden": "swe", "switzerland": "che", "taiwan": "twn",
    "thailand": "tha", "turkey": "tur", "ukraine": "ukr",
    "united arab emirates": "are", "uae": "are", "united kingdom": "gbr",
    "uk": "gbr", "britain": "gbr", "great britain": "gbr",
    "united states": "usa", "usa": "usa", "us": "usa", "america": "usa",
    "vietnam": "vnm",
}

# ISO2 -> ISO3 for the majors, so "us,de,jp" works too
ISO2_TO_ISO3 = {
    "ar": "arg", "au": "aus", "at": "aut", "be": "bel", "br": "bra", "bg": "bgr",
    "ca": "can", "cl": "chl", "cn": "chn", "co": "col", "hr": "hrv", "cy": "cyp",
    "cz": "cze", "dk": "dnk", "eg": "egy", "ee": "est", "fi": "fin", "fr": "fra",
    "de": "deu", "gr": "grc", "hk": "hkg", "hu": "hun", "is": "isl", "in": "ind",
    "id": "idn", "ie": "irl", "il": "isr", "it": "ita", "jp": "jpn", "kr": "kor",
    "lv": "lva", "lt": "ltu", "lu": "lux", "my": "mys", "mx": "mex", "ma": "mar",
    "nl": "nld", "nz": "nzl", "ng": "nga", "no": "nor", "pk": "pak", "pe": "per",
    "ph": "phl", "pl": "pol", "pt": "prt", "qa": "qat", "ro": "rou", "ru": "rus",
    "sa": "sau", "sg": "sgp", "sk": "svk", "si": "svn", "za": "zaf", "es": "esp",
    "se": "swe", "ch": "che", "tw": "twn", "th": "tha", "tr": "tur", "ua": "ukr",
    "ae": "are", "gb": "gbr", "us": "usa", "vn": "vnm",
}

GROUPS = {
    "g20": [
        "usa", "emu", "chn", "jpn", "deu", "gbr", "fra", "ind", "ita", "bra",
        "can", "kor", "rus", "aus", "mex", "idn", "sau", "tur", "che", "swe",
        "esp", "sgp", "zaf", "arg",
    ],
    "world": [
        "afg", "alb", "dza", "asm", "and", "ago", "aia", "atg", "arg", "arm", "abw",
        "aus", "aut", "aze", "bhs", "bhr", "bgd", "brb", "blr", "bel", "blz", "ben",
        "bmu", "btn", "bol", "bih", "bwa", "bra", "brn", "bgr", "bfa", "bdi", "khm",
        "cmr", "can", "cpv", "cym", "caf", "tcd", "chi", "chl", "chn", "cxr", "col",
        "ccc", "com", "cod", "cok", "cri", "hrv", "cub", "cyp", "cze", "dnk", "dji",
        "dma", "dom", "eap", "tls", "ecu", "egy", "slv", "gnq", "eri", "est", "eth",
        "emu", "eca", "eun", "flk", "fro", "fji", "fin", "fra", "pyf", "gab", "gmb",
        "geo", "deu", "gha", "gib", "grc", "grl", "grd", "gum", "gtm", "gin", "gnb",
        "guy", "hti", "hpc", "hic", "noc", "oec", "hnd", "hkg", "hun", "isl", "ind",
        "idn", "irn", "irq", "irl", "imy", "isr", "ita", "civ", "jam", "jpn", "jor",
        "kaz", "ken", "kir", "unk", "kwt", "kgz", "lao", "lac", "lva", "ldc", "lbn",
        "lso", "lbr", "lby", "lie", "ltu", "lmy", "lic", "lmc", "lux", "mac", "mkd",
        "mdg", "mwi", "mys", "mdv", "mli", "mlt", "mhl", "mrt", "mus", "myt", "mex",
        "fsm", "mna", "mic", "mda", "mco", "mng", "mne", "msr", "mar", "moz", "mmr",
        "nam", "npl", "nld", "ant", "ncl", "nzl", "nic", "ner", "nga", "nfk", "prk",
        "mnp", "nor", "omn", "oth", "pak", "plw", "pse", "pan", "png", "pry", "per",
        "phl", "pcn", "pol", "prt", "pri", "qat", "cog", "reu", "rou", "rus", "rwa",
        "wsm", "smr", "stp", "sau", "sen", "srb", "syc", "sle", "sgp", "svk", "svn",
        "slb", "som", "zaf", "sas", "kor", "ssd", "esp", "lka", "shn", "kna", "lca",
        "spm", "vct", "ssa", "sdn", "sur", "swz", "swe", "che", "syr", "twn", "tjk",
        "tza", "tha", "tgo", "tkl", "ton", "tto", "tun", "tur", "tkm", "tuv", "uga",
        "ukr", "are", "gbr", "usa", "umc", "ury", "uzb", "vut", "ven", "vnm", "vir",
        "wlf", "wbg", "wld", "yem", "zmb", "zwe", "opc", "imf", "g20", "g7"
    ],
    "major": ["usa", "emu", "chn", "jpn", "deu", "gbr", "fra", "can", "aus", "che"],
    "us": ["usa"],
    "americas": ["usa", "can", "mex", "bra", "arg", "chl", "col", "per"],
    "europe": [
        "emu", "deu", "gbr", "fra", "ita", "esp", "nld", "che", "swe", "nor",
        "dnk", "bel", "aut", "irl", "prt", "pol", "grc", "fin", "cze", "hun",
    ],
    "asia": [
        "chn", "jpn", "ind", "kor", "idn", "sgp", "hkg", "twn", "tha", "mys",
        "phl", "vnm", "pak", "bgd", "lka",
    ],
}


def to_iso3(token):
    t = str(token).strip().lower().replace("_", " ")
    if not t:
        return None
    if t in GROUPS:
        return None  # handled by caller
    if len(t) == 3 and t.isalpha() and t not in ISO3:
        return t  # already an ISO3/TE code
    if t in ISO3:
        return ISO3[t]
    if len(t) == 2 and t in ISO2_TO_ISO3:
        return ISO2_TO_ISO3[t]
    return t.replace(" ", "")[:3]


def country_list(spec):
    """'us,germany' or 'g20' -> ['usa','deu'] / the group's codes."""
    if not spec:
        return []
    out = []
    for tok in re.split(r"[,;|]+", str(spec)):
        tok = tok.strip().lower()
        if not tok:
            continue
        if tok in GROUPS:
            out.extend(GROUPS[tok])
        else:
            code = to_iso3(tok)
            if code:
                out.append(code)
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


# --------------------------------------------------------------------------
# Small formatting helpers
# --------------------------------------------------------------------------

STARS = {1: "*", 2: "**", 3: "***"}


def stars(n):
    try:
        return STARS.get(int(n), "")
    except (TypeError, ValueError):
        return ""


def esc(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def write_out(text, path=None):
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {path}", file=sys.stderr)
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        print(text)


def dump_json(obj, path=None, compact=False):
    text = json.dumps(obj, indent=None if compact else 2, ensure_ascii=False)
    write_out(text, path)
