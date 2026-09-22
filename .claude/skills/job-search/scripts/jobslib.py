# -*- coding: utf-8 -*-
import requests, re, warnings, sys, io, concurrent.futures as cf
import profile as PROF
warnings.filterwarnings("ignore")
try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception: pass
S = requests.Session(); S.headers.update({"User-Agent":"Mozilla/5.0"}); T=20
ENTRY = PROF.TITLE_INCLUDE
BAD = re.compile(r"(sales|account exec|recruit|marketing|counsel|legal|"
    r"communications|talent community|hackathon|quantitative (trader|researcher)|\btrader\b)", re.I)
NONUS = re.compile(r"(amsterdam|london|netherlands|denmark|aarhus|zug|switzerland|spain|poland|"
    r"emea|apac|india|bangalore|hyderabad|toronto|vancouver|montreal|dublin|berlin|munich|paris|"
    r"singapore|sydney|tokyo|tel aviv|israel|brazil|mexico|colombia|argentina|europe|shanghai|beijing|"
    r"united kingdom|\buk\b|germany|france|portugal|romania|ukraine|philippines|korea|japan|china|guildford|quebec)", re.I)
PRIMARY=PROF.PRIMARY_RE
NEAR=PROF.NEAR_RE
RM=re.compile(r"(remote|home based|anywhere|distributed)",re.I)

def collect(gh=(), lever=(), ashby=()):
    out=[]
    def add(co,t,l,u,src):
        if not t or not u: return
        if BAD.search(t) or PROF.TITLE_EXCLUDE.search(t) or not ENTRY.search(t): return
        l=(l or "").strip()
        if NONUS.search(l): return
        out.append(dict(company=co,title=t.strip(),location=l,url=u,source=src))
    def _gh(tok):
        try:
            r=S.get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs",timeout=T)
            if r.status_code!=200: return
            for j in r.json().get("jobs",[]):
                add(tok,j.get("title"),(j.get("location") or {}).get("name"),j.get("absolute_url"),"greenhouse")
        except Exception: pass
    def _lv(o):
        try:
            r=S.get(f"https://api.lever.co/v0/postings/{o}?mode=json",timeout=T)
            if r.status_code!=200: return
            for j in r.json(): add(o,j.get("text"),(j.get("categories") or {}).get("location"),j.get("hostedUrl"),"lever")
        except Exception: pass
    def _ab(o):
        try:
            r=S.get(f"https://api.ashbyhq.com/posting-api/job-board/{o}",timeout=T)
            if r.status_code!=200: return
            for j in r.json().get("jobs",[]):
                add(o,j.get("title"),j.get("location"),j.get("jobUrl") or j.get("applyUrl"),"ashby")
        except Exception: pass
    with cf.ThreadPoolExecutor(32) as ex:
        list(ex.map(_gh,set(gh))); list(ex.map(_lv,set(lever))); list(ex.map(_ab,set(ashby)))
    seen=set(); ded=[]
    for o in out:
        if o["url"] in seen: continue
        seen.add(o["url"])
        o["tier"]="NYC" if PRIMARY.search(o["location"]) else ("REMOTE" if RM.search(o["location"]) else
                "NEAR" if NEAR.search(o["location"]) else "OTHER")
        ded.append(o)
    return ded

def show(ded):
    print("TOTAL:",len(ded))
    for tier in ("NYC","NEAR","REMOTE","OTHER"):
        rows=[o for o in ded if o["tier"]==tier]
        if not rows: continue
        print("\n===== "+tier+" ("+str(len(rows))+") =====")
        for o in sorted(rows,key=lambda x:x["company"]):
            print(f'{o["company"][:16]:<16} | {o["title"][:56]:<56} | {o["location"][:26]:<26} | {o["url"]}')
