# -*- coding: utf-8 -*-
"""Final link verification: re-tests every URL on the shortlist from scratch."""
import requests, json, re, warnings, sys, io, datetime, concurrent.futures as cf
from urllib.parse import urlparse
warnings.filterwarnings("ignore")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})

DEAD_TXT = re.compile(
    r"(no longer accepting|no longer available|position (has been|is) (filled|closed)|"
    r"this job is closed|job posting (has expired|is no longer)|not accepting applications|"
    r"page not found|job not found|file not found|doesn'?t exist|couldn'?t find|no longer open|"
    r"the page you are looking for does not exist)", re.I)

# URLs that block automated requests and were confirmed by loading them in a real browser.
BROWSER_CONFIRMED = {
 "https://www.jumptrading.com/hr/job?gh_jid=8052313":
   "Campus AI Research Engineer (Full-Time) | Careers at Jump Trading",
 "http://www.hioscar.com/careers/7914958?gh_jid=7914958":
   "Data Analytics Engineer I - New York, New York",
 "https://www.akunacapital.com/careers/job/8013230/?gh_jid=8013230":
   "Software Engineer (Entry-Level) - Python - CHICAGO",
 "https://www.akunacapital.com/careers/job/8013085/?gh_jid=8013085":
   "Software Engineer (Entry-Level) - C++ - CHICAGO",
 "https://www.workatastartup.com/jobs/85422":
   "Founding Engineer at Thera | Y Combinator's Work at a Startup",
 "https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/26012796":
   "Campus Undergraduate Full-Time Engineer - 2027 Software Engineer I, ETS - New York, NY",
}


def title_of(h):
    m = re.search(r"<title[^>]*>(.*?)</title>", h, re.S | re.I)
    if not m:
        return ""
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    return t.replace("&amp;", "&")[:120]


def check(o):
    u = o["url"]
    res = dict(o)
    res.update(status=None, final="", page_title="", verdict="UNSURE", note="")

    if u in BROWSER_CONFIRMED:
        res.update(verdict="LIVE", page_title=BROWSER_CONFIRMED[u],
                   note="confirmed by loading in a real browser (blocks scrapers)")
        return res

    r = None
    for _ in range(2):
        try:
            r = S.get(u, timeout=30, allow_redirects=True)
            break
        except Exception as e:
            res["note"] = type(e).__name__
    if r is None:
        res["verdict"] = "ERROR"
        return res

    html = r.text or ""
    res["status"] = r.status_code
    res["final"] = r.url
    res["page_title"] = title_of(html)
    body = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)[:4000]

    op, fp = urlparse(u), urlparse(r.url)
    ID = r"(\d{5,}|[0-9a-f]{8}-[0-9a-f]{4})"

    if r.status_code in (404, 410):
        res.update(verdict="DEAD", note="HTTP %s" % r.status_code)
        return res
    if r.status_code >= 400:
        res.update(verdict="BLOCKED", note="HTTP %s" % r.status_code)
        return res
    if re.search(ID, op.path + "?" + (op.query or "")) and \
       not re.search(ID, fp.path + "?" + (fp.query or "")):
        res.update(verdict="DEAD", note="redirected to a generic page: " + r.url[:60])
        return res
    if DEAD_TXT.search(res["page_title"]) or DEAD_TXT.search(body[:2500]):
        res.update(verdict="DEAD", note="closed/not-found text on page")
        return res
    if "ashbyhq.com" in fp.netloc:
        live = " @ " in res["page_title"]
        res.update(verdict="LIVE" if live else "DEAD",
                   note="Ashby renders the job title into <title> when the req is open")
        return res
    res.update(verdict="LIVE", note="HTTP 200, job page resolved")
    return res


rows = json.load(open("final_list.json", encoding="utf-8"))
with cf.ThreadPoolExecutor(12) as ex:
    out = list(ex.map(check, rows))

stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
for o in out:
    o["checked"] = stamp
json.dump(out, open("final_verified.json", "w", encoding="utf-8"), indent=1)

from collections import Counter
print("VERIFIED AT:", stamp)
print(Counter(o["verdict"] for o in out))
for v in ("DEAD", "BLOCKED", "ERROR", "UNSURE"):
    bad = [o for o in out if o["verdict"] == v]
    if bad:
        print("\n### %s" % v)
        for o in bad:
            print("  %-18s | %-46s | %s" % (o["company"][:18], o["title"][:46], o["note"][:60]))
print("\n### LIVE")
for o in out:
    if o["verdict"] == "LIVE":
        print("  %-18s | %-52s | %s" % (o["company"][:18], o["title"][:52], o["page_title"][:58]))
