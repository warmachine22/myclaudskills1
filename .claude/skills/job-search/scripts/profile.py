# -*- coding: utf-8 -*-
"""Candidate profile loader — the one place anything person-specific lives.

The pipeline scripts import from here so the same code serves any candidate.
Create a profile with the intake questions in SKILL.md, save it as
profiles/<slug>.json, and point profiles/active.txt at the slug.
"""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
PROF_DIR = os.path.join(os.path.dirname(HERE), "profiles")


def _active_slug():
    env = os.environ.get("JOB_PROFILE")
    if env:
        return env
    p = os.path.join(PROF_DIR, "active.txt")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            s = f.read().strip()
            if s:
                return s
    cands = [f[:-5] for f in os.listdir(PROF_DIR) if f.endswith(".json") and not f.endswith(".example.json")] \
        if os.path.isdir(PROF_DIR) else []
    if len(cands) == 1:
        return cands[0]
    raise SystemExit("No active profile. Create profiles/<slug>.json and "
                     "write the slug into profiles/active.txt (or set JOB_PROFILE).")


def load():
    slug = _active_slug()
    path = os.path.join(PROF_DIR, slug + ".json")
    if not os.path.exists(path):
        raise SystemExit("Profile not found: %s" % path)
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    p.setdefault("slug", slug)
    return p


P = load()

# ---- derived values the pipeline needs ----
_g = str(P.get("graduation_month", "")).strip()          # "YYYY-MM", or "" if N/A
if re.match(r"^\d{4}-\d{1,2}$", _g):
    _y, _m = _g.split("-")
    GRAD_MONTHS = int(_y) * 12 + int(_m)
else:
    GRAD_MONTHS = None                                    # no graduation gate to apply

MAX_YEARS = int(P.get("max_years_required", 2))           # hard reject above this
STRETCH_YEARS = int(P.get("stretch_years", MAX_YEARS))    # flag, don't reject, at this
YEARS_EXPERIENCE = float(P.get("years_experience", 0))
HAS_ADVANCED_DEGREE = bool(P.get("has_advanced_degree", False))
IS_STUDENT = bool(P.get("currently_enrolled", False))

STRONG = P.get("strong_skills", {})
WEAK = P.get("weak_skills", {})
MIN_STACK_SCORE = int(P.get("min_stack_score", 6))

_loc = P.get("locations", {})
PRIMARY_RE = (re.compile("(%s)" % "|".join(_loc["primary"]), re.I)
              if _loc.get("primary") else re.compile(r"(?!)"))
NEAR_RE = (re.compile("(%s)" % "|".join(_loc["near"]), re.I)
           if _loc.get("near") else re.compile(r"(?!)"))
REMOTE_OK = bool(_loc.get("remote_ok", True))
RELOCATE_OK = bool(_loc.get("relocate_ok", True))
PRIMARY_LABEL = _loc.get("primary_label", "Primary market")
NEAR_LABEL = _loc.get("near_label", "Within commuting reach")
COMPANY_EXCLUDE = {str(x).strip().casefold() for x in P.get("company_exclude", [])}

TITLE_INCLUDE = re.compile("(%s)" % "|".join(
    P.get("title_include", [r"software\s+engineer", "engineer", "developer"])), re.I)
TITLE_EXCLUDE = re.compile("(%s)" % "|".join(
    P.get("title_exclude", ["senior", "staff", "principal"])), re.I)

NAME = P.get("name", "Candidate")
HEADLINE = P.get("headline", "")
OUTPUT_PATH = P.get("output_path", os.path.join(
    os.path.expanduser("~"), "Desktop", "%s-job-links.html" % P.get("slug", "candidate")))
