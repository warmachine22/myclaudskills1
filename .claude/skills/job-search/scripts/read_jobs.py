# -*- coding: utf-8 -*-
"""Fetch each posting's FULL description and check it against the active profile.

Link-liveness is not enough: a live requisition can still fail the candidate's
education, experience, enrollment, clearance, or graduation criteria. This pulls
the description and extracts:
  - minimum years of experience demanded
  - whether a Master's/PhD is REQUIRED (vs merely preferred)
  - security-clearance requirements
  - graduation-year gates that conflict with the active profile
"""
import requests, json, re, html, warnings, sys, io, concurrent.futures as cf
from urllib.parse import urlparse, parse_qs
import profile as PROF
warnings.filterwarnings("ignore")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                  "Accept-Language": "en-US,en;q=0.9"})
T = 30
_ashby_cache = {}


def strip(h):
    """HTML -> plain text.

    Greenhouse returns ESCAPED markup (&lt;p&gt;), so unescaping must happen BEFORE
    tag removal; doing it after leaves literal '<p>' strings all through the text.
    Unescape twice to cover double-encoded payloads, then drop tags.
    """
    if not h:
        return ""
    t = html.unescape(html.unescape(h))
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t\xa0]+", " ", t)


def ashby_board(org):
    if org.lower() not in _ashby_cache:
        try:
            r = S.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}", timeout=T)
            _ashby_cache[org.lower()] = r.json().get("jobs", []) if r.status_code == 200 else []
        except Exception:
            _ashby_cache[org.lower()] = []
    return _ashby_cache[org.lower()]


try:
    with open("desc_cache.json", encoding="utf-8") as _f:
        DESC_CACHE = json.load(_f)
except Exception:
    DESC_CACHE = {}

try:
    _GH_TOKENS = [t for t, _ in json.load(open("boards.json", encoding="utf-8"))["greenhouse"]]
except Exception:
    _GH_TOKENS = []


def fetch_desc(url):
    """Return (text, method). Prefer ATS APIs; fall back to raw HTML.

    Anything in desc_cache.json wins — that is where descriptions captured from
    client-rendered pages (Gem, unlisted Ashby) are stored so they only have to be
    read through a browser once.
    """
    cached = DESC_CACHE.get(url)
    if cached and len(cached) > 200:
        return cached, "cache"
    u = urlparse(url)
    q = parse_qs(u.query)
    try:
        # Dover renders client-side, but its page calls a public JSON endpoint.
        if "app.dover.com" in u.netloc:
            m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", url)
            if m:
                r = S.get("https://app.dover.com/api/v1/jobs/%s/get_job_description" % m.group(1),
                          timeout=T, headers={"Accept": "application/json"})
                if r.status_code == 200:
                    try:
                        d = r.json()
                    except Exception:
                        d = None
                    if isinstance(d, dict):
                        blob = json.dumps(d.get("user_facing_description")
                                          or d.get("user_provided_description")
                                          or d.get("generated_description") or d)
                        txt = strip(blob)
                        if len(txt) > 200:
                            return txt, "dover-api"

        # Workday: the public job URL maps onto its cxs job-detail resource.
        m = re.match(r"https?://([^.]+)\.wd(\d+)\.myworkdayjobs\.com/([^/]+)(/job/.+)", url)
        if m:
            tn, wdn, site, path = m.groups()
            api = "https://%s.wd%s.myworkdayjobs.com/wday/cxs/%s/%s%s" % (tn, wdn, tn, site, path)
            r = S.get(api, timeout=T, headers={"Accept": "application/json"})
            if r.status_code == 200:
                info = r.json().get("jobPostingInfo") or {}
                d = strip(info.get("jobDescription") or "")
                if len(d) > 200:
                    return d, "workday-api"

        # Oracle Cloud HCM (American Express, Con Edison et al): the requisition-details
        # resource carries the full description in ExternalDescriptionStr. Two URL
        # shapes exist: /job/{id} and /jobs/preview/{id}.
        if "oraclecloud.com" in u.netloc and re.search(r"/(job|jobs/preview)/", u.path):
            jid = u.path.rstrip("/").split("/")[-1]
            site = "CX_1"
            m = re.search(r"/sites/([^/]+)/", u.path)
            if m:
                site = m.group(1)
            base = "%s://%s" % (u.scheme, u.netloc)
            api = (f"{base}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
                   f"?expand=all&finder=ById;Id=%22{jid}%22,siteNumber={site}")
            r = S.get(api, timeout=T, headers={"Accept": "application/json"})
            if r.status_code == 200:
                items = r.json().get("items") or []
                if items:
                    d = items[0]
                    txt = " ".join(str(d.get(k) or "") for k in
                                   ("ExternalDescriptionStr", "CorporateDescriptionStr"))
                    return strip(txt), "oracle-api"

        # SmartRecruiters: the web page 403s automated requests, but the public API
        # serves the same posting, so read requirements there.
        if "smartrecruiters.com" in u.netloc:
            parts = [p for p in u.path.split("/") if p]
            if len(parts) >= 2:
                co = parts[0]
                jid = re.match(r"(\d+)", parts[1])
                if jid:
                    api = (f"https://api.smartrecruiters.com/v1/companies/{co}"
                           f"/postings/{jid.group(1)}")
                    r = S.get(api, timeout=T, headers={"Accept": "application/json"})
                    if r.status_code == 200:
                        secs = (r.json().get("jobAd") or {}).get("sections") or {}
                        txt = " ".join(str((secs.get(k) or {}).get("text", "")) for k in secs)
                        if txt.strip():
                            return strip(txt), "smartrecruiters-api"

        # Workable marks a pulled posting by redirecting to ?not_found=true
        if "apply.workable.com" in u.netloc:
            r = S.get(url, timeout=T, allow_redirects=True)
            if "not_found=true" in r.url:
                return "", "workable-closed"
            parts = [p for p in u.path.split("/") if p]
            acct = parts[0] if parts else ""
            code = parts[-1] if parts else ""
            # The account widget carries full descriptions; match on shortcode.
            try:
                w = S.get(f"https://apply.workable.com/api/v1/widget/accounts/{acct}"
                          f"?details=true", timeout=T)
                if w.status_code == 200:
                    for j in w.json().get("jobs", []):
                        link = (j.get("shortlink") or "") + (j.get("url") or "")
                        if code and code in link:
                            d = strip(j.get("description") or "")
                            if len(d) > 200:
                                return d, "workable-api"
            except Exception:
                pass
            m = re.search(r'"description":"(.{200,20000}?)","', r.text)
            if m:
                try:
                    raw = m.group(1).encode().decode("unicode_escape")
                except Exception:
                    raw = m.group(1)
                return strip(raw), "workable-html"
            return strip(r.text), "workable-raw"

        if "ashbyhq.com" in u.netloc:
            parts = [p for p in u.path.split("/") if p]
            org, jid = parts[0], (parts[1] if len(parts) > 1 else "")
            for j in ashby_board(org):
                if j.get("id") == jid or jid in (j.get("jobUrl") or ""):
                    return strip(j.get("descriptionHtml") or j.get("descriptionPlain")), "ashby-api"
            return "", "ashby-miss"
        if "greenhouse.io" in u.netloc:
            m = re.search(r"/(?:embed/job_app|jobs)/(\d+)", u.path) or re.search(r"jobs/(\d+)", url)
            tok = None
            pm = re.match(r"/([^/]+)/jobs/", u.path)
            if pm:
                tok = pm.group(1)
            tok = tok or (q.get("for", [None])[0])
            jid = (m.group(1) if m else (q.get("gh_jid", [None])[0]))
            if tok and jid:
                r = S.get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs/{jid}", timeout=T)
                if r.status_code == 200:
                    return strip(r.json().get("content")), "gh-api"
        if "lever.co" in u.netloc:
            parts = [p for p in u.path.split("/") if p]
            if len(parts) >= 2:
                r = S.get(f"https://api.lever.co/v0/postings/{parts[0]}/{parts[1]}?mode=json", timeout=T)
                if r.status_code == 200:
                    d = r.json()
                    return strip(d.get("description", "") + " " + json.dumps(d.get("lists", []))), "lever-api"
        # Many companies host Greenhouse jobs on their own domain and pass gh_jid.
        # The board token is rarely the first hostname label (careers.withwaymo.com ->
        # "waymo", www.hioscar.com -> "oscar"), so match against known tokens too.
        jid = q.get("gh_jid", [None])[0]
        if jid:
            host = u.netloc.lower()
            cands = [p for p in host.replace("-", ".").split(".")
                     if p not in ("www", "com", "io", "ai", "co", "careers", "jobs", "boards")]
            cands += [t for t in _GH_TOKENS if len(t) > 3 and t in host]
            for tok in dict.fromkeys(cands):
                r = S.get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs/{jid}", timeout=T)
                if r.status_code == 200:
                    d = strip(r.json().get("content"))
                    if len(d) > 200:
                        return d, "gh-api"
        r = S.get(url, timeout=T, allow_redirects=True)
        if r.status_code == 200:
            return strip(r.text), "html"
        return "", "http-%s" % r.status_code
    except Exception as e:
        return "", "err-" + type(e).__name__


# ---------- eligibility parsing ----------
YEARS = re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:\s*[-–to]+\s*\d{1,2})?\s*"
                   r"(?:or more\s*)?years?[^.;)]{0,40}?experience", re.I)
# Degree rules are evaluated per-sentence. An earlier version used `m\.?s\.?` with no
# word boundary, which matched the "ms" inside "systems"/"teams"/"requirements" and
# produced 20 false rejections. Boundaries are mandatory here.
ADV_DEGREE = re.compile(r"\b(master'?s|m\.s\.|m\.sc|msc|ph\.?d|doctorate|graduate degree|"
                        r"advanced degree)\b", re.I)
BACHELOR_OK = re.compile(r"\b(bachelor'?s?|b\.s\.|b\.a\.|\bbs\b|\bba\b|undergraduate degree|"
                         r"4[- ]year degree|or equivalent (?:experience|practical))\b", re.I)
HARD_REQ = re.compile(r"\b(required|require|must have|must possess|minimum qualification)\b", re.I)
SOFT_REQ = re.compile(r"\b(preferred|a plus|nice to have|bonus|ideally|desirable)\b", re.I)
CLEAR = re.compile(r"(active\s+(?:ts/sci|top secret|secret|security)\s*clearance|"
                   r"must (?:possess|hold|have)[^.;]{0,40}clearance|"
                   r"clearance is required|eligible to obtain[^.;]{0,30}clearance)", re.I)
# Current-enrollment requirements are separate from graduation-year windows.
# The active profile controls whether enrollment is an eligibility requirement.
ENROLLED_REQ = re.compile(
    r"(currently enrolled|must be enrolled|actively (?:enrolled|pursuing)|"
    r"currently pursuing (?:a|an|your)?\s*(?:bachelor|master|degree|b\.s|undergraduate)|"
    r"must be (?:a )?(?:current|active) (?:student|undergraduate)|"
    r"returning to (?:school|university|campus)|rising (?:senior|junior)|"
    r"enrolled in (?:a|an) (?:accredited |full.time )?(?:degree|university|college|bachelor)|"
    r"will be returning to your studies|current university student|"
    r"pursuing a (?:bachelor|master)'?s? degree)", re.I)

JUNIOR_OK = re.compile(r"(new grad|new-grad|recent (?:college )?grad|entry.level|early career|"
                       r"0\s*[-–to]+\s*2 years|1\s*[-–to]+\s*2 years|0\s*[-–to]+\s*3 years|"
                       r"no prior professional experience|recently graduated|"
                       r"bachelor'?s degree[^.;]{0,50}(?:required|or equivalent))", re.I)


def sentences(text):
    return [s for s in re.split(r"[.;\n\r•]|</li>", text) if s.strip()]


def needs_advanced_degree(text):
    """Find a required advanced degree, while allowing sentences with alternatives."""
    for s in sentences(text):
        if not ADV_DEGREE.search(s):
            continue
        if BACHELOR_OK.search(s) or SOFT_REQ.search(s):
            continue
        if HARD_REQ.search(s) or re.match(r"\s*(ph\.?d|master'?s)", s, re.I):
            return True, re.sub(r"\s+", " ", s.strip())[:150]
    return False, ""


def grad_gate(text):
    """True when a graduation window excludes the active profile's graduation month.

    Upper-bound phrasing such as "by August 2027" is not a gate for earlier
    graduates. If the profile has no graduation month, do not apply this filter.
    """
    MON = {m: i + 1 for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"])}
    RANGE = re.compile(r"(?:between\s+)?([A-Za-z]+)\s+(20\d{2})\s*(?:[-–—]|to|and|through)\s*"
                       r"([A-Za-z]+)?\s*(20\d{2})", re.I)
    GRAD = PROF.GRAD_MONTHS       # from the candidate profile
    if GRAD is None:
        return False, ""

    for s in sentences(text):
        if not re.search(r"graduat|class of|degree completion", s, re.I):
            continue
        # An explicit window: reject when it starts after the profile's graduation month.
        m = RANGE.search(s)
        if m:
            mon = MON.get((m.group(1) or "").lower())
            if mon:
                start = int(m.group(2)) * 12 + mon
                if start > GRAD:
                    return True, re.sub(r"\s+", " ", s.strip())[:150]
                continue
        if not re.search(r"20(27|28)", s) or re.search(r"20(25|26)", s):
            continue
        if re.search(r"\b(by|before|no later than|on or before|prior to|through)\b\s*"
                     r"(?:\w+\s+)?20(27|28)", s, re.I):
            continue          # upper bound only — earlier graduates still qualify
        return True, re.sub(r"\s+", " ", s.strip())[:150]
    return False, ""


SWE_TITLE = PROF.TITLE_INCLUDE
NON_SWE = PROF.TITLE_EXCLUDE


def judge(text, title):
    """Return (verdict, min_years, reasons[])."""
    reasons = []
    t = title or ""
    if NON_SWE.search(t) or not SWE_TITLE.search(t):
        return "REJECT", None, ["not a software engineering role"]

    # Cohort year and degree track are sometimes stated only in the title.
    if (not PROF.HAS_ADVANCED_DEGREE and
            re.search(r"\bmaster'?s\b|\bMS\b(?!\w)|\bPhD\b", t, re.I)):
        return "REJECT", None, ["title names an advanced-degree track not listed in the profile"]
    if PROF.GRAD_MONTHS is not None:
        title_years = [int(y) for y in re.findall(r"\b(20\d{2})\b", t)]
        if any(year * 12 > PROF.GRAD_MONTHS for year in title_years):
            return "REJECT", None, ["title targets a graduation cohort after the profile graduation date"]

    if len(text) < 300:
        return "UNKNOWN", None, ["could not read description"]
    yrs = sorted({int(m) for m in YEARS.findall(text) if 0 < int(m) <= 25})
    my = yrs[0] if yrs else None
    jr = bool(JUNIOR_OK.search(text))

    masters, msnip = needs_advanced_degree(text)
    masters = masters and not PROF.HAS_ADVANCED_DEGREE
    if masters:
        reasons.append("requires an advanced degree: “%s”" % msnip)
    clear = bool(CLEAR.search(text))
    if clear:
        reasons.append("requires an active security clearance")

    enrolled = False
    m = ENROLLED_REQ.search(text) if not PROF.IS_STUDENT else None
    if m:
        # "graduated" / "recent grad" language elsewhere means the enrolment phrase is
        # describing the programme generally, not gating applicants.
        s = next((x for x in sentences(text) if ENROLLED_REQ.search(x)), "")
        if not re.search(r"(recent(ly)? grad|have graduated|already graduated|"
                         r"or equivalent experience|within (?:the )?(?:past|last))", s, re.I):
            enrolled = True
            reasons.append("requires current student enrolment: “%s”"
                           % re.sub(r"\s+", " ", s.strip())[:120])
    gate27, gsnip = grad_gate(text)
    if gate27:
        reasons.append("graduation gate: “%s”" % gsnip)
    if my is not None and my > PROF.MAX_YEARS:
        reasons.append("asks %d+ years of experience" % my)

    # Hard disqualifiers stay hard regardless of how good the fit is.
    if masters or clear or gate27 or enrolled:
        return "REJECT", my, reasons

    # A years floor one step above the profile ceiling is a reach, not a wall.
    # Surface it clearly rather than discarding it; anything higher is a reject.
    if my is not None and my > PROF.MAX_YEARS:
        if my <= PROF.MAX_YEARS + 1:
            return "REACH", my, ["asks %d+ years — one year above the profile ceiling; assess as a reach"
                                 % my]
        return "REJECT", my, reasons
    if my is not None and my >= PROF.STRETCH_YEARS and not jr:
        return "STRETCH", my, ["asks %d+ years; candidate has ~%s years"
                               % (my, PROF.P.get("years_experience", "?"))]
    if jr or my is None or my < PROF.STRETCH_YEARS:
        note = []
        if jr:
            note.append("explicitly open to new grads / entry level")
        if my is not None:
            note.append("%d-year floor" % my)
        else:
            note.append("no years-of-experience floor stated")
        return "GOOD", my, note
    return "STRETCH", my, ["unclear requirements"]


def load_pool():
    pool, seen = [], set()
    def add(rows, default_fit=2):
        for o in rows:
            u = (o.get("url") or "").split("?utm_source")[0]
            if not u or u in seen:
                continue
            seen.add(u)
            pool.append(dict(company=o.get("company", ""), title=o.get("title", ""),
                             location=o.get("location", ""), url=u,
                             fit=o.get("fit", default_fit), note=o.get("note", "")))
    for f in ("final_list.json", "content_hits.json", "raw_all.json", "bigco.json",
              "raw_jobs.json", "raw_jobs2.json", "agent_finds.json"):
        try:
            add(json.load(open(f, encoding="utf-8")))
        except Exception:
            pass
    return pool


def work(o):
    txt, how = fetch_desc(o["url"])
    v, my, rs = judge(txt, o["title"])
    o = dict(o)
    o.update(verdict=v, min_years=my, reasons=rs, method=how, desc_len=len(txt))
    return o


if __name__ == "__main__":
    pool = load_pool()
    print("candidate pool:", len(pool))
    with cf.ThreadPoolExecutor(12) as ex:
        res = list(ex.map(work, pool))
    json.dump(res, open("eligibility.json", "w", encoding="utf-8"), indent=1)
    from collections import Counter
    print(Counter(o["verdict"] for o in res))
    print(Counter(o["method"] for o in res).most_common(8))
    for v in ("GOOD", "STRETCH"):
        rows = [o for o in res if o["verdict"] == v]
        print("\n===== %s (%d) =====" % (v, len(rows)))
        for o in rows:
            print("  %-16s | %-48s | %-22s | %s"
                  % (o["company"][:16], o["title"][:48], o["location"][:22],
                     "; ".join(o["reasons"])[:44]))
