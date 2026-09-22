# -*- coding: utf-8 -*-
"""Judge whether the work matches the active profile, separately from eligibility."""
import json, re, sys, warnings, concurrent.futures as cf
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
import profile as PROF
from read_jobs import fetch_desc   # installs the UTF-8 stdout wrapper too

STRONG = PROF.STRONG

WEAK = PROF.WEAK

def _label(pat):
    """Turn a regex pattern into a readable skill name.

    An earlier version stripped the character class [\\b()?:] which also deleted
    literal 'b's, producing "ack.end" and "moile app".
    """
    s = pat.replace(r"\b", "").replace("\\", "")
    s = re.sub(r"\(.*?\)\??", "", s)      # drop optional groups like (ful)?
    s = s.replace(".?", " ").replace(".", " ")
    s = re.sub(r"[?:^$]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def count(text, table):
    total, hits = 0, []
    for pat, w in table.items():
        n = len(re.findall(pat, text, re.I))
        if n:
            total += w * min(n, 3)
            hits.append((_label(pat), n))
    hits.sort(key=lambda x: -x[1])
    return total, hits


def evidence(text, pat, width=110):
    m = re.search(pat, text, re.I)
    if not m:
        return ""
    s = max(0, m.start() - 40)
    return re.sub(r"\s+", " ", text[s:m.end() + width]).strip()


def fit(text, title):
    if len(text) < 300:
        return "UNKNOWN", 0, 0, "could not read description"
    s, shits = count(text, STRONG)
    w, whits = count(text, WEAK)
    top_weak = ", ".join(h[0] for h in whits[:3])
    top_strong = ", ".join(h[0] for h in shits[:4])

    if w > s * 1.15 and w >= 8:
        return ("MISMATCH", s, w,
                "work centres on %s, which is outside the configured profile" % (top_weak or "other skills"))
    if s < PROF.MIN_STACK_SCORE and w >= 6:
        return "MISMATCH", s, w, "work centres on %s rather than the configured profile" % (top_weak or "other skills")
    if s < PROF.MIN_STACK_SCORE:
        # Names no technologies at all — a vague posting is not evidence of a mismatch.
        return ("GENERIC", s, w,
                "posting names no specific stack; generic software engineering role")
    if w >= s * 0.8 and w >= 6:
        return ("PARTIAL", s, w,
                "mixes profile strengths (%s) with %s" % (top_strong or "configured skills", top_weak))
    return "CORE", s, w, "matches profile strengths: %s" % (top_strong or "configured skills")


if __name__ == "__main__":
    rows = [o for o in json.load(open("eligibility.json", encoding="utf-8"))
            if o["verdict"] in ("GOOD", "STRETCH", "REACH")]
    print("scoring skills fit for %d eligible roles" % len(rows))

    def work(o):
        txt, _ = fetch_desc(o["url"])
        v, s, w, why = fit(txt, o["title"])
        return dict(o, skill_verdict=v, strong=s, weak=w, skill_why=why)

    with cf.ThreadPoolExecutor(12) as ex:
        res = list(ex.map(work, rows))
    json.dump(res, open("skills.json", "w", encoding="utf-8"), indent=1)

    from collections import Counter
    print(Counter(o["skill_verdict"] for o in res))
    for v in ("MISMATCH", "PARTIAL"):
        print("\n===== %s =====" % v)
        for o in res:
            if o["skill_verdict"] == v:
                print("  %-16s | %-42s | %s"
                      % (o["company"][:16], o["title"][:42], o["skill_why"][:88]))
