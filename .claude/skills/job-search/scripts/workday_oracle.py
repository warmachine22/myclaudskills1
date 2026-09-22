# -*- coding: utf-8 -*-
"""Harvest the big employers that don't use Greenhouse/Lever/Ashby.

Workday and Oracle Cloud HCM both expose public JSON endpoints (verified by research).
This unlocks Capital One, Amex, NBCU, Verizon, Take-Two etc. that the ATS harvester missed.
"""
import requests, json, re, warnings, sys, io, concurrent.futures as cf
warnings.filterwarnings("ignore")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                  "Content-Type": "application/json", "Accept": "application/json"})
T = 30

ENTRY = re.compile(r"(new grad|new-grad|early career|entry.level|university|campus|associate |"
                   r"junior|graduate|software engineer i\b|engineer i\b|developer i\b|"
                   r"new college grad|rotational|analyst program)", re.I)
BAD = re.compile(r"(senior|\bsr\b|staff|principal|\blead\b|manager|director|\bVP\b|"
                 r"\bII\b|\bIII\b|\bIV\b|intern\b|internship|phd|sales|counsel|nurse|"
                 r"technician|mechanic|driver|clerk|cashier|associate director|"
                 r"associate general|associate manager|associate vice)", re.I)
TECH = re.compile(r"(software|engineer|developer|programmer|data|technolog|full.?stack|"
                  r"backend|frontend|application|platform|cyber|machine learning)", re.I)

# (label, tenant, wdN, site)
WORKDAY = [
    ("Capital One", "capitalone", 12, "Capital_One"),
    ("NBCUniversal", "nbcuni", 1, "NBCUniversalCareers"),
    ("Warner Bros. Discovery", "warnerbros", 5, "global"),
    ("Verizon", "verizon", 12, "verizon_jobs"),
    ("Take-Two Interactive", "take2games", 1, "Take2_Careers"),
    ("Paramount", "paramount", 5, "ParamountCareers"),
    ("Nasdaq", "nasdaq", 1, "nasdaq_careers"),
    ("S&P Global", "spgi", 5, "SPGI_Careers"),
    ("Prudential", "prudential", 5, "PRUDENTIAL_CAREERS"),
    ("MetLife", "metlife", 5, "MetLife_Careers"),
    ("Nvidia", "nvidia", 5, "NVIDIAExternalCareerSite"),
    ("Salesforce", "salesforce", 12, "External_Career_Site"),
]

# (label, tenant, region, site)
ORACLE = [
    ("American Express", "egug", "us2", "CX_1"),
]

found = []


def wd(entry):
    label, tenant, n, site = entry
    url = f"https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    got = 0
    for off in (0, 20, 40, 60):
        body = {"appliedFacets": {}, "limit": 20, "offset": off,
                "searchText": "software engineer"}
        try:
            r = S.post(url, json=body, timeout=T)
            if r.status_code != 200:
                return (label, "FAIL http %s" % r.status_code, 0)
            posts = r.json().get("jobPostings", [])
            if not posts:
                break
            for p in posts:
                t = p.get("title") or ""
                loc = p.get("locationsText") or ""
                if BAD.search(t) or not TECH.search(t) or not ENTRY.search(t):
                    continue
                path = p.get("externalPath") or ""
                link = f"https://{tenant}.wd{n}.myworkdayjobs.com/{site}{path}"
                found.append(dict(company=label, title=t.strip(), location=loc.strip(),
                                  url=link, source="workday"))
                got += 1
        except Exception as e:
            return (label, "ERR %s" % type(e).__name__, 0)
    return (label, "ok", got)


def orc(entry):
    label, tenant, region, site = entry
    base = f"https://{tenant}.fa.{region}.oraclecloud.com"
    got = 0
    reqs = []
    try:
        # `expand=requisitionList` is required — without it the response carries
        # TotalJobsCount but an empty list.
        for off in (0, 200, 400, 600):
            url = (f"{base}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
                   f"?onlyData=true&expand=requisitionList"
                   f"&finder=findReqs;siteNumber={site},limit=200,offset={off}")
            r = S.get(url, timeout=T)
            if r.status_code != 200:
                return (label, "FAIL http %s" % r.status_code, 0)
            items = r.json().get("items") or []
            batch = []
            for it in items:
                batch.extend(it.get("requisitionList") or [])
            if not batch:
                break
            reqs.extend(batch)
        for q in reqs:
            t = q.get("Title") or ""
            if BAD.search(t) or not TECH.search(t) or not ENTRY.search(t):
                continue
            jid = q.get("Id")
            link = f"{base}/hcmUI/CandidateExperience/en/sites/{site}/job/{jid}"
            found.append(dict(company=label, title=t.strip(),
                              location=(q.get("PrimaryLocation") or "").strip(),
                              url=link, source="oracle"))
            got += 1
    except Exception as e:
        return (label, "ERR %s" % type(e).__name__, 0)
    return (label, "ok", got)


with cf.ThreadPoolExecutor(10) as ex:
    res = list(ex.map(wd, WORKDAY)) + list(ex.map(orc, ORACLE))

for label, status, n in res:
    print("%-24s %-16s %d hits" % (label, status, n))

seen = set()
ded = []
for o in found:
    if o["url"] in seen:
        continue
    seen.add(o["url"])
    ded.append(o)
json.dump(ded, open("bigco.json", "w", encoding="utf-8"), indent=1)
print("\nENTRY-LEVEL HITS:", len(ded))
for o in ded:
    print("  %-22s | %-52s | %-26s | %s"
          % (o["company"][:22], o["title"][:52], o["location"][:26], o["url"][:70]))
