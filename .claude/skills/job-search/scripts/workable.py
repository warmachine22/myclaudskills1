# -*- coding: utf-8 -*-
"""Harvest Workable boards and cache descriptions.

Workable is a fourth ATS my pipeline didn't speak. Its v3 endpoint pages properly
(the v1 widget silently caps at 30 jobs, which is why the MLabs junior role was
invisible at first). Descriptions are written to desc_cache.json so read_jobs.py
can judge eligibility without re-fetching.
"""
import requests, json, re, sys, io, warnings, concurrent.futures as cf
warnings.filterwarnings("ignore")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                  "Accept": "application/json", "Content-Type": "application/json"})
T = 25

ACCOUNTS = """mlabs rokt fuku alongside-team thetie talentpluto cvector aurora-3
sylvera pave tomorrowhealth ridgeline overtime petal ramp attentive
capsule oscar ro cedar zocdoc kickstarter squarespace vimeo""".split()

ENG = re.compile(r"(software|engineer|developer|programmer|full.?stack|back.?end|front.?end|"
                 r"web|mobile|application)", re.I)
ENTRY = re.compile(r"(junior|graduate|new grad|entry.level|early career|associate|"
                   r"engineer i\b|developer i\b|\bi\b$)", re.I)
BAD = re.compile(r"(senior|\bsr\b|staff|principal|\blead\b|manager|director|head of|"
                 r"\bII\b|\bIII\b|intern\b|internship|architect)", re.I)
NONUS = re.compile(r"(united kingdom|england|london|china|shanghai|serbia|romania|poland|"
                   r"bulgaria|slovakia|india|canada|germany|france|spain|japan|singapore|"
                   r"australia|brazil|mexico|israel|netherlands|portugal|greece|turkey|ukraine)", re.I)


def page(acct):
    """POST the v3 jobs endpoint, following its paging token."""
    out, token, seen = [], None, set()
    for _ in range(8):
        body = {"query": "", "location": [], "department": [], "worktype": [], "remote": []}
        # the paging cursor goes in the query string, not the body
        url = f"https://apply.workable.com/api/v3/accounts/{acct}/jobs"
        if token:
            url += "?token=" + token
        try:
            r = S.post(url, data=json.dumps(body), timeout=T)
            if r.status_code != 200:
                return out
            d = r.json()
        except Exception:
            return out
        res = d.get("results") or []
        if not res:
            break
        for j in res:
            sc = j.get("shortcode")
            if sc and sc not in seen:
                seen.add(sc)
                out.append(j)
        token = d.get("nextPage") or d.get("token")
        if not token or len(out) >= (d.get("total") or 0):
            break
    return out


def detail(acct, shortcode):
    try:
        r = S.get(f"https://apply.workable.com/api/v1/widget/accounts/{acct}?details=true", timeout=T)
        if r.status_code == 200:
            for j in r.json().get("jobs", []):
                if j.get("shortlink", "").endswith(shortcode):
                    return j.get("description") or ""
    except Exception:
        pass
    return ""


def strip(h):
    import html as H
    if not h:
        return ""
    t = H.unescape(H.unescape(h))
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


rows, cache = [], {}


def work(acct):
    got = []
    for j in page(acct):
        title = j.get("title") or ""
        if not ENG.search(title) or BAD.search(title) or not ENTRY.search(title):
            continue
        loc = j.get("location") or {}
        if isinstance(loc, dict):
            loc = ", ".join(str(x) for x in
                            [loc.get("city"), loc.get("region"), loc.get("country")] if x)
        loc = str(loc)
        if NONUS.search(loc):
            continue
        sc = j.get("shortcode")
        url = f"https://apply.workable.com/{acct}/j/{sc}/"
        desc = strip(j.get("description") or "") or strip(detail(acct, sc))
        got.append((dict(company=acct, title=title.strip(), location=loc or "United States",
                         url=url, source="workable"), desc))
    return got


with cf.ThreadPoolExecutor(10) as ex:
    for got in ex.map(work, ACCOUNTS):
        for row, desc in got:
            rows.append(row)
            if len(desc) > 200:
                cache[row["url"]] = desc

json.dump(rows, open("workable_jobs.json", "w", encoding="utf-8"), indent=1)
try:
    old = json.load(open("desc_cache.json", encoding="utf-8"))
except Exception:
    old = {}
old.update(cache)
json.dump(old, open("desc_cache.json", "w", encoding="utf-8"), indent=1)

print("workable roles kept: %d (descriptions cached: %d)" % (len(rows), len(cache)))
for r in rows:
    print("  %-16s | %-46s | %-26s | %s"
          % (r["company"][:16], r["title"][:46], r["location"][:26], r["url"]))
