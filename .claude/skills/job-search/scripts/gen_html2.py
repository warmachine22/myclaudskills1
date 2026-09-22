# -*- coding: utf-8 -*-
import json, html, collections, os
import profile as PROF

rows = json.load(open("final_verified.json", encoding="utf-8"))
stamp = rows[0]["checked"]
# Only publish links that passed the final liveness test.
dropped_dead = [o for o in rows if o["verdict"] != "LIVE"]
_rank = {o["url"]: o.get("rank", 9999) for o in
         json.load(open("final_list.json", encoding="utf-8"))}
rows = [o for o in rows if o["verdict"] == "LIVE"]
rows.sort(key=lambda o: _rank.get(o["url"], 9999))
_baseline_path = os.environ.get("JOB_BASELINE")
DELTA = bool(_baseline_path)
if DELTA:
    _seen = set(json.load(open(_baseline_path, encoding="utf-8")))
    rows = [o for o in rows if o["url"] not in _seen]
    for i, o in enumerate(rows, 1):
        o["rank"] = i
curated = {o["url"]: o for o in json.load(open("final_list.json", encoding="utf-8"))}
elig = json.load(open("eligibility.json", encoding="utf-8"))

for o in rows:
    c = curated.get(o["url"], {})
    o["note"] = c.get("note", o.get("note", ""))
    o["tier"] = c.get("tier", "OTHER")
    o["fit"] = c.get("fit", 2)
    o["rank"] = c.get("rank", 0)
    o["match_score"] = c.get("match_score", 0)
    o["match_why"] = c.get("match_why", "")
    o["verdict2"] = c.get("verdict", "GOOD")

BUCKETS = [
    ("NYC", PROF.PRIMARY_LABEL, "On-site or hybrid in the primary market."),
    ("NEAR", PROF.NEAR_LABEL, "Commutable / short-haul relocation."),
    ("REMOTE", "Fully remote", "No relocation required."),
    ("OTHER", "Other locations", "Ranked by how cleanly the requirements match."),
]

rej = [o for o in elig if o["verdict"] == "REJECT"]
rej_reasons = collections.Counter()
for o in rej:
    r = "; ".join(o["reasons"])
    if "not a software" in r:
        rej_reasons["Not a software engineering role"] += 1
    elif "years" in r:
        rej_reasons["Experience requirement exceeds the profile ceiling"] += 1
    elif "graduation gate" in r:
        rej_reasons["Graduation-date gate conflicts with the profile"] += 1
    elif "clearance" in r:
        rej_reasons["Requires an active security clearance"] += 1
    elif "advanced degree" in r:
        rej_reasons["Requires a Master's or PhD"] += 1

examples = [o for o in rej if "years" in "; ".join(o["reasons"])][:10]


def stars(n):
    return '<span class="fit fit%d">%s<span class="dim">%s</span></span>' % (
        n, "\u25cf" * n, "\u25cb" * (3 - n))


parts = []
TIER_LABEL = {"NYC": PROF.PRIMARY_LABEL, "NEAR": PROF.NEAR_LABEL,
              "REMOTE": "Remote", "OTHER": "Other locations"}
# The curated copy above re-applies the full-list rank, so renumber here for a delta.
if DELTA:
    for _i, _o in enumerate(rows, 1):
        _o["rank"] = _i

_heading = ("New since the last list" if DELTA else "Ranked by match to the profile")
_sub = ("Only roles that were not in the previous file. " if DELTA else "")
parts.append('<section><h2>%s <span class="count">%d</span></h2>'
             '<p class="sub">%sBest fit first. The score combines profile skill fit, role-level '
             'signals, and the configured location preferences, with fit leading geography.</p>'
             % (_heading, len(rows), _sub))
for o in rows:
    note = html.escape(o["note"])
    if "Requirements check:" in note:
        head, chk = note.split("Requirements check:", 1)
        body = ('<p class="note">%s</p>' % head.replace("\u2022", "").strip()) if head.strip() else ""
        body += '<p class="check"><b>Requirements check</b> &middot; %s</p>' % chk.strip()
    else:
        body = '<p class="note">%s</p>' % note
    _v = o.get("verdict2")
    stretch = ('<span class="gate">stretch</span>' if _v == "STRETCH"
               else '<span class="gate">reach</span>' if _v == "REACH" else "")
    tier = TIER_LABEL.get(o.get("tier"), "")
    parts.append("""<article class="job">
  <div class="jhead">
    <div class="rankbox">%d</div>
    <div class="jmain"><h3>%s</h3>
      <div class="co">%s &middot; <span class="loc">%s</span> <span class="tier">%s</span></div></div>
    <div class="right">%s %s</div>
  </div>
  %s
  <p class="why"><b>Match %.0f</b> &middot; %s</p>
  <a class="apply" href="%s" target="_blank" rel="noopener">Apply &rarr;</a>
  <div class="verified">link tested live %s &middot; server returned: <code>%s</code></div>
</article>""" % (o.get("rank", 0), html.escape(o["title"]), html.escape(o["company"]),
                 html.escape(o["location"]), html.escape(tier),
                 stars(o["fit"]), stretch, body,
                 o.get("match_score", 0), html.escape(o.get("match_why", "")),
                 html.escape(o["url"]), stamp,
                 html.escape(o["page_title"][:78] or "(rendered client-side)")))
parts.append("</section>")

rej_rows = "".join("<tr><td>%s</td><td class=num>%d</td></tr>" % (html.escape(k), v)
                   for k, v in rej_reasons.most_common())
ex_rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                  % (html.escape(o["company"]), html.escape(o["title"][:52]),
                     html.escape("; ".join(o["reasons"])[:80]))
                  for o in examples)

TPL = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{NAME}} - Eligibility-Checked Job Links</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1a1a18;--dim:#6b6b66;--line:#e3e3de;--accent:#b8552a;--ok:#2f7d52;--warn:#9a6b00}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:40px 22px 80px}
h1{font-size:30px;margin:0 0 6px;letter-spacing:-.02em}
.lede{color:var(--dim);margin:0 0 22px}
.bar{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 26px}
.pill{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:6px 13px;font-size:13px}
.pill b{color:var(--ok)}
h2{font-size:19px;margin:34px 0 2px}
.count{color:var(--dim);font-weight:400;font-size:14px}
.sub{color:var(--dim);font-size:13px;margin:0 0 14px}
.job{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:15px 17px;margin:0 0 11px}
.jhead{display:flex;gap:12px;align-items:flex-start}
.job h3{margin:0;font-size:16px;line-height:1.3}
.co{color:var(--dim);font-size:13px;margin-top:3px}
.right{display:flex;align-items:center;gap:8px;flex-shrink:0}
.fit{letter-spacing:2px;font-size:12px}
.fit3{color:var(--ok)}.fit2{color:var(--warn)}.fit1{color:var(--dim)}
.dim{color:var(--line)}
.gate{background:#fdf3e3;color:#8a5a00;border:1px solid #f0dcb8;border-radius:5px;padding:2px 7px;font-size:11px}
.note{margin:10px 0 6px;font-size:13.5px;color:#3d3d39}
.rankbox{flex-shrink:0;width:34px;height:34px;border-radius:9px;background:#f0f0ec;border:1px solid var(--line);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600;color:var(--dim);font-variant-numeric:tabular-nums}
.jmain{flex:1;min-width:0}
.tier{background:#eef2f7;border:1px solid #dde5ee;border-radius:5px;padding:1px 7px;font-size:11px;color:#41556e;margin-left:4px}
.why{margin:2px 0 12px;font-size:11.5px;color:var(--dim)}
.why b{color:#3d3d39}
.check{margin:6px 0 12px;font-size:12.5px;color:#2f5d45;background:#f2f8f4;border:1px solid #d8ebe0;border-radius:7px;padding:7px 10px}
.check b{color:#1f4a34}
.apply{display:inline-block;background:var(--ink);color:#fff;text-decoration:none;padding:7px 15px;border-radius:7px;font-size:13px;font-weight:500}
.apply:hover{background:var(--accent)}
.verified{margin-top:10px;font-size:11px;color:var(--dim);border-top:1px dashed var(--line);padding-top:8px}
code{font-size:11px;background:#f0f0ec;padding:1px 5px;border-radius:4px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13px;margin-bottom:18px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:#f0f0ec;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--dim)}
td.num{text-align:right;font-variant-numeric:tabular-nums;width:60px}
tr:last-child td{border-bottom:0}
.callout{background:#fffdf6;border:1px solid #f0e4c4;border-left:3px solid var(--warn);border-radius:8px;padding:14px 16px;margin:0 0 26px;font-size:14px}
.callout b{color:#8a5a00}
</style></head><body><div class="wrap">
<h1>Eligibility-checked job links for {{NAME}}</h1>
<p class="lede">{{HEADLINE}}</p>
<div class="bar">
  <span class="pill"><b>{{N}}</b> roles that match the profile</span>
  <span class="pill">{{POOL}} postings read in full</span>
  <span class="pill">{{REJ}} rejected on requirements</span>
  <span class="pill">links tested {{STAMP}}</span>
</div>

<div class="callout">
<b>Every posting below was read, not just link-checked.</b> The full description was checked
against the active profile's degree, experience, clearance, enrollment, and graduation criteria.
Anything that failed was removed. The green line on each card quotes what the posting asks for,
so you can review the reasoning. Roles marked <span class="gate">stretch</span> or
<span class="gate">reach</span> sit above the profile's preferred experience range and deserve
closer review before applying.
</div>

{{JOBS}}

<h2>What was filtered out, and why</h2>
<p class="sub">{{REJ}} postings were removed after reading their requirements.</p>
<table><tr><th>Reason for rejection</th><th class=num>Count</th></tr>{{REJROWS}}</table>

<p class="sub">Examples of roles that looked right by title but failed on requirements:</p>
<table><tr><th>Company</th><th>Role</th><th>Why it was cut</th></tr>{{EXROWS}}</table>

<p style="color:var(--dim);font-size:12px;margin-top:28px">
Method: company ATS boards (Greenhouse, Lever, Ashby, Workday, Oracle Cloud) were queried through
their public APIs, which return only currently-open reqs. Each posting's full description was then
fetched and parsed for degree, experience, clearance and graduation requirements. Finally every
surviving link was re-tested for HTTP status, redirect target and page title on {{STAMP}}.
Reqs close without notice &mdash; re-check anything more than a few days old.
</p>
</div></body></html>"""

doc = (TPL.replace("{{N}}", str(len(rows)))
          .replace("{{POOL}}", str(len(elig)))
          .replace("{{REJ}}", str(len(rej)))
          .replace("{{STAMP}}", stamp)
          .replace("{{JOBS}}", "\n".join(parts))
          .replace("{{NAME}}", html.escape(PROF.NAME))
          .replace("{{HEADLINE}}", html.escape(PROF.HEADLINE))
          .replace("{{REJROWS}}", rej_rows)
          .replace("{{EXROWS}}", ex_rows))

open(os.environ.get("JOB_OUT", PROF.OUTPUT_PATH), "w", encoding="utf-8").write(doc)
print("wrote page with", len(rows), "roles;", len(rej), "rejected of", len(elig), "read")
