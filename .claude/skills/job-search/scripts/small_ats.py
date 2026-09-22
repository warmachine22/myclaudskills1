# -*- coding: utf-8 -*-
"""Harvest the smaller ATS platforms that small NYC companies use.

Greenhouse/Lever/Ashby/Workable are covered elsewhere. This adds Breezy (clean JSON),
plus specific verified roles on JazzHR, Rippling and Dover whose pages are
server-rendered, so read_jobs.py can fetch their descriptions over plain HTTP.
"""
import requests, json, re, html, sys, io, warnings, concurrent.futures as cf
warnings.filterwarnings("ignore")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"})
T = 25

BREEZY = """beli arcspan ash-wellness-inc lava subscribe tristero atlas-technica
critical-software""".split()

ENG = re.compile(r"(software|engineer|developer|programmer|full.?stack|back.?end|front.?end|web|mobile)", re.I)
BAD = re.compile(r"(senior|\bsr\b|staff|principal|\blead\b|manager|director|head of|"
                 r"\bII\b|\bIII\b|intern\b|internship|architect|sales|recruit)", re.I)
NONUS = re.compile(r"(portugal|lisbon|coimbra|london|united kingdom|india|canada|germany|"
                   r"poland|romania|spain|brazil|mexico|israel|singapore|australia|remote - eu)", re.I)


def strip(h_):
    if not h_:
        return ""
    t = html.unescape(html.unescape(h_))
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


rows, cache = [], {}


def breezy(acct):
    out = []
    try:
        r = S.get(f"https://{acct}.breezy.hr/json", timeout=T)
        if r.status_code != 200:
            return out
        for j in r.json():
            title = j.get("name") or ""
            if not ENG.search(title) or BAD.search(title):
                continue
            loc = j.get("location") or {}
            if isinstance(loc, dict):
                c = loc.get("city") or ""
                st = (loc.get("state") or {})
                st = st.get("name") if isinstance(st, dict) else st
                co = (loc.get("country") or {})
                co = co.get("name") if isinstance(co, dict) else co
                loc = ", ".join(str(x) for x in [c, st, co] if x)
            loc = str(loc) or "United States"
            if NONUS.search(loc):
                continue
            url = j.get("url") or f"https://{acct}.breezy.hr/p/{j.get('_id','')}"
            desc = strip(j.get("description") or "")
            out.append((dict(company=acct, title=title.strip(), location=loc,
                             url=url, source="breezy"), desc))
    except Exception:
        pass
    return out


with cf.ThreadPoolExecutor(10) as ex:
    for got in ex.map(breezy, BREEZY):
        for row, desc in got:
            rows.append(row)
            if len(desc) > 200:
                cache[row["url"]] = desc

# Specific roles verified live on platforms without a clean list API.
MANUAL = [
 ("CoreIntels", "Software Engineer (New Grad)", "New York, NY (hybrid)",
  "https://app.dover.com/apply/coreintels/2d471cb2-d4d8-4e46-8dc8-95be2dcfbb6d"),
 ("Book of the Month", "Associate Software Engineer, Frontend", "New York, NY",
  "https://bookofthemonth.applytojob.com/apply/ByZkWONsJH/Associate-Software-Engineer-Frontend"),
 ("Book of the Month", "Associate Product Engineer", "New York, NY",
  "https://bookofthemonth.applytojob.com/apply/Dm0wnvkdV8/Associate-Product-Engineer"),
 ("Prometheum", "Software Engineer 1 (Full-Stack)", "New York, NY / Remote",
  "https://prometheum.applytojob.com/apply/Lmc9MW6rCq/Software-Engineer-1-FullStack"),
 ("Supernova Technology", "Junior Software Engineer", "United States",
  "https://ats.rippling.com/supernova-technology/jobs/7ea1a05c-b0e6-4f1a-b53c-193ce3d91502"),
 ("WellHive", "Junior Software Engineer (Infrastructure)", "Remote (US)",
  "https://wellhive.applytojob.com/apply/b3TR1levbS/Junior-Software-Engineer-Infrastructure"),
 ("LoadUp Technologies", "Junior Software Engineer", "Remote (US)",
  "https://loaduptechnologies.applytojob.com/apply/JWyPr7W36V/Junior-Software-Engineer"),
 ("Rippling", "Software Engineer I", "United States",
  "https://ats.rippling.com/rippling/jobs/66767a72-10fb-475c-b0a9-f58abcbc8c44"),
]
for c, t, l, u in MANUAL:
    rows.append(dict(company=c, title=t, location=l, url=u, source="small-ats"))

try:
    old = json.load(open("desc_cache.json", encoding="utf-8"))
except Exception:
    old = {}
old.update(cache)
json.dump(old, open("desc_cache.json", "w", encoding="utf-8"), indent=1)

# merge into agent_finds.json so read_jobs picks these up
try:
    finds = json.load(open("agent_finds.json", encoding="utf-8"))
except Exception:
    finds = []
have = {o["url"] for o in finds}
added = 0
for r in rows:
    if r["url"] in have:
        continue
    finds.append(dict(company=r["company"], title=r["title"], location=r["location"],
                      url=r["url"], fit=2, note=""))
    have.add(r["url"])
    added += 1
json.dump(finds, open("agent_finds.json", "w", encoding="utf-8"), indent=1)

print("breezy roles: %d | manual: %d | added to pool: %d | descriptions cached: %d"
      % (len(rows) - len(MANUAL), len(MANUAL), added, len(cache)))
for r in rows:
    print("  %-20s | %-44s | %s" % (r["company"][:20], r["title"][:44], r["location"][:28]))
