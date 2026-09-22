# -*- coding: utf-8 -*-
"""Scan full job descriptions for profile eligibility signals and skill match.

Title-based filtering can miss roles whose titles do not describe their level clearly.
This pulls the description body from Greenhouse (?content=true) and Lever, extracts
the minimum years of experience required, and scores overlap with the active profile.
"""
import requests, json, re, html, warnings, sys, io, concurrent.futures as cf
warnings.filterwarnings("ignore")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import profile as PROF
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"})
T = 40

ENG = PROF.TITLE_INCLUDE
BAD = re.compile(r"(manager|director|\bVP\b|head of|architect|"
                 r"\bII\b|\bIII\b|\bIV\b|intern\b|internship|phd|scientist|sales|account|"
                 r"recruit|marketing|counsel|legal|designer|analyst|advocate|educator|"
                 r"representative|specialist|\bL[2-9]\b|engineer\s*[2-9]\b|\b[2-9]\b\s*$)", re.I)
NONUS = re.compile(r"(amsterdam|london|netherlands|denmark|zug|switzerland|spain|poland|emea|apac|"
                   r"india|bangalore|hyderabad|toronto|vancouver|montreal|dublin|berlin|munich|paris|"
                   r"singapore|sydney|tokyo|tel aviv|israel|brazil|mexico|colombia|argentina|europe|"
                   r"shanghai|beijing|united kingdom|\buk\b|germany|france|portugal|romania|ukraine|"
                   r"philippines|korea|japan|china|bulgaria|sofia|serbia|belgrade|poland|krakow|warsaw)", re.I)
RM = re.compile(r"(remote|anywhere|distributed)", re.I)

# Minimum-years patterns are compared with the active profile's ceiling.
YEARS = re.compile(r"(\d+)\s*(?:\+|plus|-\s*\d+)?\s*(?:or more\s*)?years?(?:\s+of)?\s+"
                   r"(?:relevant\s+|professional\s+|industry\s+|software\s+|engineering\s+)*experience", re.I)
JUNIOR = re.compile(r"(new grad|new-grad|recent (?:college )?grad|entry.level|early career|"
                    r"junior|0\s*[-–to]+\s*2 years|1\s*[-–to]+\s*2 years|0\s*[-–to]+\s*3 years|"
                    r"graduating|university grad|no prior professional experience|"
                    r"recently graduated|bachelor'?s degree.{0,40}(?:required|or equivalent))", re.I)

STACK = PROF.STRONG


def clean(h):
    if not h:
        return ""
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    return re.sub(r"\s+", " ", t)


def min_years(txt):
    vals = [int(m) for m in YEARS.findall(txt) if int(m) <= 20]
    return min(vals) if vals else None


def score_stack(txt):
    return sum(weight * min(len(re.findall(pattern, txt, re.I)), 3)
               for pattern, weight in STACK.items())


out = []


def keep(co, title, loc, url, body, src):
    if (not title or not url or BAD.search(title) or PROF.TITLE_EXCLUDE.search(title)
            or not ENG.search(title)):
        return
    loc = (loc or "").strip()
    if NONUS.search(loc):
        return
    txt = clean(body)
    if len(txt) < 200:
        return
    my = min_years(txt)
    jr = bool(JUNIOR.search(txt))
    if my is not None and my > PROF.MAX_YEARS + 1:
        return
    if PROF.MAX_YEARS <= 2 and not (jr or (my is not None and my <= PROF.MAX_YEARS)):
        return
    st = score_stack(txt)
    if st < PROF.MIN_STACK_SCORE:
        return
    out.append(dict(company=co, title=title.strip(), location=loc, url=url, source=src,
                    min_years=my, junior_signal=jr, stack=st,
                    tier="NYC" if PROF.PRIMARY_RE.search(loc) else
                         "REMOTE" if RM.search(loc) else
                         "NEAR" if PROF.NEAR_RE.search(loc) else "OTHER"))


def gh(tok):
    try:
        r = S.get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs?content=true", timeout=T)
        if r.status_code != 200:
            return
        for j in r.json().get("jobs", []):
            keep(tok, j.get("title"), (j.get("location") or {}).get("name"),
                 j.get("absolute_url"), j.get("content"), "greenhouse")
    except Exception:
        pass


def lv(org):
    try:
        r = S.get(f"https://api.lever.co/v0/postings/{org}?mode=json", timeout=T)
        if r.status_code != 200:
            return
        for j in r.json():
            body = (j.get("description") or "") + " " + json.dumps(j.get("lists") or [])
            keep(org, j.get("text"), (j.get("categories") or {}).get("location"),
                 j.get("hostedUrl"), body, "lever")
    except Exception:
        pass


def ab(org):
    """Ashby's board API returns full descriptions, so scan those too."""
    try:
        r = S.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}", timeout=T)
        if r.status_code != 200:
            return
        for j in r.json().get("jobs", []):
            keep(org, j.get("title"), j.get("location"),
                 j.get("jobUrl") or j.get("applyUrl"),
                 j.get("descriptionHtml") or j.get("descriptionPlain"), "ashby")
    except Exception:
        pass


by = json.load(open("boards.json", encoding="utf-8"))
ghs = [t for t, _ in by["greenhouse"]]
lvs = [t for t, _ in by["lever"]]
abs_ = [t for t, _ in by["ashby"]]
print("scanning descriptions: %d greenhouse + %d lever + %d ashby boards"
      % (len(ghs), len(lvs), len(abs_)))
with cf.ThreadPoolExecutor(14) as ex:
    list(ex.map(gh, ghs))
    list(ex.map(lv, lvs))
    list(ex.map(ab, abs_))

seen = set()
ded = []
for o in out:
    if o["url"] in seen:
        continue
    seen.add(o["url"])
    ded.append(o)
ded.sort(key=lambda x: (-(x["tier"] == "NYC"), -(x["tier"] == "REMOTE"), -x["stack"]))
json.dump(ded, open("content_hits.json", "w", encoding="utf-8"), indent=1)

print("TOTAL content-matched:", len(ded))
for tier in ("NYC", "REMOTE", "OTHER"):
    rows = [o for o in ded if o["tier"] == tier]
    print("\n===== %s (%d) =====" % (tier, len(rows)))
    for o in rows[:45]:
        yr = "min %syr" % o["min_years"] if o["min_years"] is not None else "no yrs stated"
        print("  %-14s | %-46s | %-24s | stack %2d | %-13s | %s"
              % (o["company"][:14], o["title"][:46], o["location"][:24], o["stack"], yr, o["url"][:58]))
