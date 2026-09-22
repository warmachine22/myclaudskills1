# -*- coding: utf-8 -*-
"""Build the final roster from roles that passed the eligibility read."""
import json, re, io, sys, warnings
import profile as PROF
warnings.filterwarnings("ignore")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

NONUS = re.compile(r"(amsterdam|london|netherlands|denmark|zug|switzerland|spain|poland|emea|apac|"
                   r"india|bangalore|bengaluru|hyderabad|gurugram|toronto|ontario|alberta|british columbia|"
                   r"vancouver|montreal|quebec|canada|dublin|berlin|munich|paris|singapore|sydney|tokyo|"
                   r"tel aviv|israel|brazil|mexico|colombia|argentina|europe|shanghai|beijing|taipei|taiwan|"
                   r"united kingdom|\buk\b|germany|france|portugal|romania|bucharest|barcelona|ukraine|"
                   r"philippines|korea|seoul|japan|china|bulgaria|sofia|belfast|northern ireland|estonia|"
                   r"malaysia|thailand|australia|\banz\b|"
                   r"chile|turkey|türkiye|latam|peru|uruguay|paraguay|bolivia|ecuador|"
                   r"costa rica|panama|guatemala|nigeria|kenya|ghana|egypt|morocco|"
                   r"pakistan|bangladesh|sri lanka|nepal|vietnam|indonesia|hong kong|"
                   r"dubai|\buae\b|saudi|qatar|jordan|lebanon|armenia|georgia \(country\)|"
                   r"kazakhstan|uzbekistan|belarus|lithuania|latvia|estonia|croatia|"
                   r"slovenia|hungary|czech|austria|switzerland|sweden|norway|finland|"
                   r"iceland|ireland|belgium|luxembourg|cyprus|malta|new zealand|"
                   # region-level values seen in ATS location fields
                   r"\basia\b|latin america|\bafrica\b|middle east|oceania|\bcaribbean\b|"
                   r"russia|vladivostok|moscow|serbia|belgrade|montenegro|albania|"
                   r"kuala lumpur|jakarta|manila|bangkok|ho chi minh|hanoi|karachi|lahore)", re.I)
NY = PROF.PRIMARY_RE
NEAR = PROF.NEAR_RE
RM = re.compile(r"(remote|anywhere|distributed|home based)", re.I)

DROP_TITLE = re.compile(r"(student worker|contract\b|\bsdet\b|development engineer in test|"
                        r"quality assurance)", re.I)

# The harvesters key companies by ATS slug, so the same firm appears as both
# "roblox" and "Roblox". Normalise for display and de-duplication.
CANON = {"roblox": "Roblox", "nuro": "Nuro", "zoox": "Zoox", "verkada": "Verkada",
         "palantir": "Palantir", "jumptrading": "Jump Trading", "stripe": "Stripe",
         "notion": "Notion", "nintendo": "Nintendo", "mixpanel": "Mixpanel",
         "discord": "Discord", "gusto": "Gusto", "elastic": "Elastic", "warp": "Warp",
         "quora": "Quora", "canonical": "Canonical", "vercel": "Vercel",
         "flexport": "Flexport", "handshake": "Handshake", "crusoe": "Crusoe",
         "cerebras": "Cerebras", "planetscale": "PlanetScale", "pariveda": "Pariveda",
         "uniswap": "Uniswap Labs", "maximor": "Maximor AI", "bridger": "Bridger",
         "runsybil-jobs": "RunSybil", "n1": "N1", "ellipsislabs": "Ellipsis Labs",
         "valon": "Valon", "sierra": "Sierra", "imc": "IMC Trading",
         "akunacapital": "Akuna Capital", "simplisafe": "SimpliSafe", "whoop": "WHOOP",
         "ctccampusboard": "Chicago Trading Co.", "visa": "Visa"}


CANON.update({
    "breezecash": "Breeze", "clark": "Clark", "waymark": "Waymark", "atoms": "Atoms",
    "sigmacomputing": "Sigma Computing", "thenewyorktimes": "The New York Times",
    "underdogfantasy": "Underdog", "alloycampus": "Alloy", "hereio": "HERE",
    "nycedc": "NYC Economic Development Corp", "everlaw": "Everlaw",
    "diligentcorporation": "Diligent", "usenourish": "Nourish", "clarityai": "Clarity AI",
    "perfectserve": "PerfectServe", "voltus": "Voltus", "traackr": "Traackr",
    "silnahealth.com": "Silna Health", "gigaml": "Giga", "mechanize": "Mechanize",
    "pylon-labs": "Pylon", "kikoff": "Kikoff", "close": "Close", "truelogic": "Truelogic",
    "agility.io": "Agility IO", "applied": "Applied Intuition",
    "accenturefederalservices": "Accenture Federal Services",
    "valkyrietrading": "Valkyrie Trading", "muttdata": "Mutt Data",
    "weekdayworks": "Weekday", "policyme": "PolicyMe", "asapp-2": "ASAPP",
    "prosper": "Prosper", "3pillarglobal": "3Pillar Global", "66degrees": "66degrees",
    "iconcareers": "ICON", "idme": "ID.me", "rackner": "Rackner", "sage49": "Sage",
    "beaconbiosignals": "Beacon Biosignals", "inthepocket": "In The Pocket",
    "pdtpartners": "PDT Partners", "evenup": "EvenUp", "xsolla": "Xsolla",
    "wingtra-2": "Wingtra", "jobnimbus": "JobNimbus", "newengeninc": "New Engen",
    "marqeta": "Marqeta", "lingarogroup": "Lingaro", "jobgether": "Jobgether",
    "benchling": "Benchling", "sentry": "Sentry", "attentive": "Attentive",
    "bettercloud": "BetterCloud", "digitalocean": "DigitalOcean", "fastly": "Fastly",
    "cloudflare": "Cloudflare", "opentable": "OpenTable", "classpath": "ClassPass",
    "classpass": "ClassPass", "hellofresh": "HelloFresh", "betterhelp": "BetterHelp",
    "harrys": "Harry's", "bark": "BARK", "calm": "Calm", "oscar": "Oscar Health",
    "oscarhealth": "Oscar Health", "orrgroup": "Orr Group", "blueengine": "Blue Engine",
    "envisionconsulting": "Envision Consulting", "shipbob": "ShipBob",
})


CANON.update({
    "langchain": "LangChain", "pear-vc": "Pear VC", "pear vc": "Pear VC",
    "aquaticcapitalmanagement": "Aquatic Capital Management",
    "blossom-health": "Blossom Health", "eliseai": "EliseAI", "august": "August Law",
    "phoebe-work": "Phoebe", "happyrobot.ai": "HappyRobot", "finch-legal": "Finch Legal",
    "circle-health": "Circle Health", "wynd-labs": "Wynd Labs", "xbowcareers": "XBOW",
    "geobrowser": "Geo Browser", "0g": "0G Labs", "applytosuno": "Suno",
    "suno (applytosuno)": "Suno", "alternativepayments": "Alternative Payments",
    "norm-ai": "Norm Ai", "norm ai": "Norm Ai", "junior": "Junior (junior.com)",
    "hatch": "Hatch", "beli": "Beli", "lava": "Lava", "hex": "Hex", "omni": "Omni",
    "expa": "Expa", "aditude": "Aditude", "cribl": "Cribl", "precisely": "Precisely",
    "fingerprint": "Fingerprint", "abnormal": "Abnormal Security", "bellese": "Bellese",
    "translucent": "Translucent", "eulerity": "Eulerity", "modal": "Modal",
    "workato": "Workato", "plaid": "Plaid", "vercel": "Vercel", "ramp": "Ramp",
    "garnerhealth": "Garner Health", "newrelic": "New Relic", "verisign": "Verisign",
    "vestwell": "Vestwell", "supabase": "Supabase", "yext": "Yext", "xsolla": "Xsolla",
    "anthropic": "Anthropic", "airtable": "Airtable", "atoms": "Atoms", "zip": "Zip",
})


def canon(name):
    """Map an ATS slug to a human company name; fall back to a tidy title-case."""
    n = (name or "").strip()
    if n.lower() in CANON:
        return CANON[n.lower()]
    if n and n.islower():
        pretty = re.sub(r"\.(com|io|ai)$", "", n).replace("-", " ").replace("_", " ")
        return pretty.title()
    return n

rows = json.load(open("skills.json", encoding="utf-8"))
prev = {o["url"]: o for o in json.load(open("final_list.json", encoding="utf-8"))}

sel, seen = [], set()
for o in rows:
    if o["verdict"] not in ("GOOD", "STRETCH", "REACH"):
        continue
    if o.get("skill_verdict") not in ("CORE", "GENERIC"):
        continue
    loc = o["location"] or ""
    if NONUS.search(loc):
        continue
    if ((o["company"] or "").strip().casefold() in PROF.COMPANY_EXCLUDE
            or DROP_TITLE.search(o["title"] or "")):
        continue
    o = dict(o, company=canon(o["company"]))
    key = (o["company"].lower(), re.sub(r"[^a-z0-9]", "", o["title"].lower())[:40])
    if key in seen:
        continue
    seen.add(key)

    tier = ("NYC" if NY.search(loc) else "REMOTE" if RM.search(loc)
            else "NEAR" if NEAR.search(loc) else "OTHER")
    ev = "; ".join(o["reasons"])
    if o["verdict"] == "STRETCH":
        ev = "STRETCH — " + ev
    elif o["verdict"] == "REACH":
        ev = "REACH — " + ev
    ev += ".  Skills: " + o.get("skill_why", "")
    # Keep the hand-written fit note where we have one. This script reads its own
    # previous output, so strip any requirements line already appended before adding
    # a fresh one, or it compounds on every run.
    old = prev.get(o["url"], {})
    note = (old.get("note") or "").split("Requirements check:")[0]
    note = note.replace("•", "").strip().rstrip("·").strip()
    if note and not note.startswith("GATE"):
        note = "%s  •  Requirements check: %s" % (note, ev)
    else:
        note = "Requirements check: %s" % ev

    core = o.get("skill_verdict") == "CORE"
    fit = 3 if (core and tier in ("NYC", "NEAR", "REMOTE")) else 2 if core else 1
    if o["verdict"] in ("STRETCH", "REACH"):
        fit = 1
    sel.append(dict(company=o["company"], title=o["title"], location=loc, url=o["url"],
                    fit=fit, note=note, tier=tier, verdict=o["verdict"],
                    skill_verdict=o.get("skill_verdict"), min_years=o["min_years"]))

order = {"NYC": 0, "NEAR": 1, "REMOTE": 2, "OTHER": 3}
sel.sort(key=lambda x: (order[x["tier"]], -x["fit"], x["company"].lower()))
json.dump(sel, open("final_list.json", "w", encoding="utf-8"), indent=1)

from collections import Counter
print("SELECTED:", len(sel), Counter(o["tier"] for o in sel))
for t in ("NYC", "NEAR", "REMOTE", "OTHER"):
    r = [o for o in sel if o["tier"] == t]
    print("\n===== %s (%d) =====" % (t, len(r)))
    for o in r:
        print("  %-16s | %-46s | %-20s | %s"
              % (o["company"][:16], o["title"][:46], o["location"][:20],
                 (o["note"].split("Requirements check: ")[-1])[:52]))
