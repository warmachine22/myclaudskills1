# -*- coding: utf-8 -*-
"""Harvest SmartRecruiters boards (fifth ATS).

The web pages 403 automated requests but the public API is open. Note some
companies opt out of the public feed even with a live careers site, so always
check totalFound > 0 rather than assuming absence means no jobs.
"""
import requests, json, re, sys, io, warnings, concurrent.futures as cf
warnings.filterwarnings("ignore")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
S = requests.Session(); S.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
T = 25

COMPANIES = """KrgTechnologyInc GrowSquares DellforTechnologies AtriaGroupLLC HasanaInc
Socotec visa Bosch Publicis Ubisoft McKinsey Avature Squarepoint
IPG Wunderman Datadog Peloton""".split()

ENG = re.compile(r"(software|engineer|developer|programmer|full.?stack|back.?end|front.?end|web|mobile)", re.I)
BAD = re.compile(r"(senior|\bsr\b|staff|principal|\blead\b|manager|director|head of|"
                 r"\bII\b|\bIII\b|intern\b|internship|architect|sales|recruit|designer)", re.I)
US = re.compile(r"(united states|new york|brooklyn|remote|usa)", re.I)

rows = []
def one(co):
    out = []
    try:
        r = S.get(f"https://api.smartrecruiters.com/v1/companies/{co}/postings?limit=100", timeout=T)
        if r.status_code != 200:
            return out
        d = r.json()
        if not d.get("totalFound"):
            return out
        for p in d.get("content", []):
            t = p.get("name") or ""
            if not ENG.search(t) or BAD.search(t):
                continue
            loc = p.get("location") or {}
            locs = ", ".join(str(x) for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x)
            if not US.search(locs) and not loc.get("remote"):
                continue
            pid = p.get("id")
            url = f"https://jobs.smartrecruiters.com/{co}/{pid}"
            out.append(dict(company=co, title=t.strip(), location=locs or "United States",
                            url=url, source="smartrecruiters"))
    except Exception:
        pass
    return out

with cf.ThreadPoolExecutor(10) as ex:
    for got in ex.map(one, COMPANIES):
        rows.extend(got)

finds = json.load(open("agent_finds.json", encoding="utf-8"))
have = {o["url"] for o in finds}
added = 0
for r in rows:
    if r["url"] in have: continue
    finds.append(dict(company=r["company"], title=r["title"], location=r["location"],
                      url=r["url"], fit=2, note="")); have.add(r["url"]); added += 1
json.dump(finds, open("agent_finds.json", "w", encoding="utf-8"), indent=1)
print("smartrecruiters roles found: %d | added: %d" % (len(rows), added))
for r in rows[:25]:
    print("  %-22s | %-46s | %s" % (r["company"][:22], r["title"][:46], r["location"][:30]))
