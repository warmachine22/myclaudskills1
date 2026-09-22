# -*- coding: utf-8 -*-
"""Rank every surviving role by how well it matches the active candidate profile.

The tiered grouping answers "where is it?"; this answers "which roles match best?".
Score is transparent so the ordering can be reviewed:

  stack overlap        how much of the configured toolkit the posting names
  - mismatch penalty   weight of skills not listed in the profile
  + entry signal       explicitly invites new grads / entry level
  + low bar            no stated years floor, or 1 year
  + title shape        "Software Engineer I" beats a vague or senior-leaning title
  + location           modest nudge, so fit leads and geography breaks ties
"""
import json, re, io, sys, warnings
import profile as PROF
warnings.filterwarnings("ignore")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

skills = {o["url"]: o for o in json.load(open("skills.json", encoding="utf-8"))}
rows = json.load(open("final_list.json", encoding="utf-8"))

TITLE_TOP = re.compile(r"(new grad|junior|associate|entry.level|early career|"
                       r"engineer\s*i\b|developer\s*i\b)", re.I)
TITLE_GOOD = re.compile(r"(full.?stack|back.?end|front.?end|product engineer|"
                        r"software engineer|web|mobile|application)", re.I)
TITLE_OK = re.compile(r"(forward deployed|deployed engineer|solutions|platform|growth)", re.I)

LOC_BONUS = {"NYC": 6, "REMOTE": 4, "NEAR": 3, "OTHER": 0}


def score(o):
    s = skills.get(o["url"], {})
    strong = s.get("strong", 0) or 0
    weak = s.get("weak", 0) or 0
    reasons = " ".join(s.get("reasons", []) or [])

    # Very long postings repeat keywords and inflate the raw stack score, so cap the
    # contribution — beyond this the signal is repetition, not a better match.
    strong = min(strong, 60)
    pts = float(strong) - 0.6 * float(weak)
    bits = ["stack %d" % strong]
    if weak:
        bits.append("-%d mismatch" % weak)

    if PROF.MAX_YEARS <= 2 and re.search(r"new grad|entry.level|early career", reasons, re.I):
        pts += 8
        bits.append("+entry-level")

    my = o.get("min_years")
    if my is None or my == 0:
        pts += 6
        bits.append("+no years bar")
    elif my <= PROF.MAX_YEARS:
        pts += 3
        bits.append("+within experience ceiling")

    t = o["title"]
    if PROF.MAX_YEARS <= 2 and TITLE_TOP.search(t):
        pts += 7
        bits.append("+junior title")
    elif TITLE_GOOD.search(t):
        pts += 4
    elif TITLE_OK.search(t):
        pts += 2

    if o.get("skill_verdict") == "GENERIC":
        pts -= 6
        bits.append("-vague posting")
    if o.get("verdict") == "STRETCH":
        pts -= 10
        bits.append("-stretch")
    if o.get("verdict") == "REACH":
        pts -= 14
        bits.append("-reach (above profile ceiling)")

    pts += LOC_BONUS.get(o.get("tier"), 0)
    if o.get("tier") in ("NYC", "NEAR", "REMOTE"):
        bits.append("+" + o["tier"].lower())

    return round(pts, 1), ", ".join(bits)


for o in rows:
    o["match_score"], o["match_why"] = score(o)

rows.sort(key=lambda x: (-x["match_score"], x["company"].lower()))
for i, o in enumerate(rows, 1):
    o["rank"] = i
json.dump(rows, open("final_list.json", "w", encoding="utf-8"), indent=1)

print("ranked %d roles by resume match\n" % len(rows))
print("TOP 25:")
for o in rows[:25]:
    print("  %3d. %-24s | %-46s | %-6s | %5.1f | %s"
          % (o["rank"], o["company"][:24], o["title"][:46], o["tier"],
             o["match_score"], o["match_why"][:52]))
print("\nBOTTOM 5:")
for o in rows[-5:]:
    print("  %3d. %-24s | %-46s | %-6s | %5.1f"
          % (o["rank"], o["company"][:24], o["title"][:46], o["tier"], o["match_score"]))
