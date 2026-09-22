---
name: job-search
description: Find and verify real, currently-open job listings for a specific candidate by querying company applicant-tracking systems directly, reading every job description in full, and filtering on eligibility and skills match. Produces a self-contained HTML page of application links with the requirement evidence shown for each. Use when asked to find jobs, refresh a job list, check for new openings for someone, or re-run a previous job search.
---

# Job search: verified listings for a specific candidate

Finds jobs by querying company ATS boards directly rather than scraping job aggregators.
Every link is tested live, and every posting is read in full and judged against the
candidate's actual eligibility and stack before it is kept.

## Why this approach

Job aggregators and curated lists can retain expired postings. Company ATS APIs provide a better source for current requisitions. Use search engines and directories to discover employers, then verify each listing against its company board.

Two filters matter independently, and both are needed:
- Eligibility — can the candidate apply at all? Degree, years, graduation window, and enrollment rules come from the active profile.
- Skills fit — does the work match the configured strengths and exclusions? A role can fit the years range while still requiring an unrelated technical stack.
## Step 1 — the candidate profile

Everything person-specific lives in `profiles/<slug>.json`; `profiles/active.txt` names the
profile to use. The pipeline scripts read it through `scripts/profile.py`, so the same code
serves any candidate. **Never edit the scripts to retarget — edit or add a profile.**

**If a profile already exists for this candidate, use it. Do not re-interview.** Re-runs should be
one command. Only refresh the profile when the person's situation has changed.

**For a new candidate:** read their resume, then ask the questions below with AskUserQuestion —
batch them, don't interrogate one at a time. Infer what you safely can from the resume (skills,
graduation date, years of experience) and confirm rather than asking from scratch.

1. **Work authorization** — citizen / permanent resident / needs sponsorship. Changes whether
   cleared and federal roles are viable at all.
2. **Location** — primary market, willing to relocate, remote acceptable, and any commute radius.
   Becomes `locations.primary` / `.near` / `.remote_ok` / `.relocate_ok`.
3. **Role focus** — generalist SWE, frontend, backend, mobile, AI/LLM, data, games. Drives
   `title_include` and the `strong_skills` weights.
4. **Seniority ceiling** — how many years a posting may demand before it is out of reach.
   `max_years_required` (hard reject above) and `stretch_years` (flag, don't reject).
5. **Student status** — currently enrolled, or already graduated. If graduated, postings requiring
   current enrolment must be rejected; set `graduation_month` so cohort windows can be judged.
6. **Anything to exclude** — domains they don't want or aren't credible in. Goes in `weak_skills`
   (weighted) or `title_exclude` (hard).

Then write the profile. Key fields:

| Field | Meaning |
|---|---|
| `graduation_month` | `"YYYY-MM"`, or `""` for no graduation gate |
| `max_years_required` | reject postings demanding more than this |
| `stretch_years` | at/above this, mark STRETCH rather than reject |
| `currently_enrolled` | if false, "must be currently enrolled" postings are rejected |
| `strong_skills` / `weak_skills` | regex → weight; scoring tables for skills fit |
| `min_stack_score` | below this and with weak signals present, it's a mismatch |
| `locations.primary` / `.near` | regex fragments for location tiering |
| `title_include` / `title_exclude` | role-shape gates applied to the title |
| `company_exclude` | company names to omit from results |
| `output_path` | where the HTML is written (one file, overwritten each run) |

Regex fragments are JSON strings, so backslashes double: `"\\bpython\\b"`.

## Run order

```bash
cd <skill>/scripts
# --- optional intake: only when adding employers (see "Growing coverage") ---
python discover.py        # brute-force ATS slugs from a list of company names
python workable.py        # Workable boards -> desc_cache.json
python small_ats.py       # Breezy + specific JazzHR/Rippling/Dover roles
python smartrec.py        # SmartRecruiters boards
python workday_oracle.py  # Workday + Oracle Cloud (big employers)

# --- the run itself ---
python harvest_all.py     # title-based sweep across every cached board
python scan_content.py    # description-based sweep (catches junior roles with plain titles)
python read_jobs.py       # fetch EVERY description, judge eligibility
python skills_fit.py      # judge stack match against the resume
python select_final.py    # pick, dedupe, tier by location, name companies properly
python rescore.py         # rank every survivor by match to the resume
python verify_final.py    # re-test every surviving link for liveness
python gen_html2.py       # write the HTML deliverable
python shot.py file:///<out.html> page.png   # visual check (Playwright)
```

Order matters: `rescore.py` must run **after** `select_final.py` (which rewrites
`final_list.json`) and **before** `gen_html2.py`, which renders in rank order.

`boards.json` caches **646 verified ATS boards (~38,800 open postings)** — 304 Greenhouse,
88 Lever, 254 Ashby. Reuse it; a re-run starts warm. `desc_cache.json` holds descriptions
captured from client-rendered pages so they are only browser-read once.

### Producing a "what's new" file

```bash
JOB_BASELINE=$(pwd)/baseline_urls.json JOB_OUT=/path/new-only.html python gen_html2.py
```
Snapshot the delivered set **before** re-running (the pipeline overwrites its state):
write every URL from `final_verified.json` — union it with prior runs — into
`baseline_urls.json`. With `JOB_BASELINE` set, the generator emits only unseen roles,
renumbered from 1, under a "New since the last list" heading.

## The five ATS APIs

| System | Endpoint | Notes |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | `content=true` returns full descriptions |
| Lever | `api.lever.co/v0/postings/{org}?mode=json` | includes `description` + `lists` |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{org}` | **case-sensitive slugs**; includes `descriptionHtml` |
| Workable | `apply.workable.com/api/v1/widget/accounts/{acct}?details=true` | v1 widget silently **caps at 30 jobs** |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/{co}/postings` | web pages 403 bots; API is open |

Also working: **Workday** (`POST {tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs`)
and **Oracle Cloud HCM** (`{tenant}.fa.{region}.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions`).

## Growing coverage — the highest-leverage lever

Board coverage is often the binding constraint. Expand the employer list for the candidate's target location, role type, and industries, then verify every board slug against its public API.

1. Search ATS domains directly for the target role and market. Harvest company slugs from real postings, then confirm the slug against the API.
2. Mine local employer directories and industry lists, then resolve each employer to its ATS.
3. Use parallel agents for discovery breadth only. Run every result through the full description, fit, and link-verification pipeline before including it.

The checked-in boards.json is a starting set, not a complete or current market map. Run discover.py to add employers and remove boards that are no longer useful.

## When asked for more, audit rejections first

Before expanding coverage or changing filters, group eligibility.json rejections by reason and inspect borderline cases. Resolve unreadable postings, then reassess experience gates and skills-fit decisions against the active profile. Keep each decision tied to the posting text so filter changes remain auditable.
## Hard-won gotchas — do not rediscover these

- **Ashby's public API omits unlisted postings.** API absence does NOT mean the job is dead.
  Load the URL: a live Ashby job renders its title as `"<Job Title> @ <Company>"`.
- **Oracle needs `expand=requisitionList`** or it returns `TotalJobsCount` with an empty array.
- **Workable marks pulled postings by redirecting to `?not_found=true`.** Its v1 widget caps at
  30 jobs and its v3 paging token did not advance in testing — a role can exist in Google's
  index and still be closed.
- **Greenhouse returns HTML-escaped markup.** Unescape *before* stripping tags or you get
  literal `<p>` in your "clean" text.
- **Dover renders client-side but has a public JSON endpoint**:
  `app.dover.com/api/v1/jobs/{uuid}/get_job_description`, no auth. Found by opening a Dover
  page in the Browser pane and reading its network requests — do that before concluding a
  client-rendered ATS is unreadable.
- **Gem batches its content over GraphQL.** Not worth reverse-engineering; read the page once
  in a browser and put the text in `desc_cache.json`, which `fetch_desc` checks first.
- **Workday job pages map onto a detail resource**: the public
  `{tenant}.wd{N}.myworkdayjobs.com/{site}/job/...` URL becomes
  `/wday/cxs/{tenant}/{site}/job/...`.
- **Oracle has two URL shapes** — `/job/{id}` and `/jobs/preview/{id}`; handle both, and read
  the `siteNumber` from `/sites/{X}/` (Con Edison uses CX_1033, not CX_1).
- **Companies hosting Greenhouse on their own domain** pass `gh_jid`, but the board token is
  often NOT the first hostname label (`careers.withwaymo.com` → `waymo`,
  `www.hioscar.com` → `oscar`). Match the hostname against known tokens.
- **The Muse's `category`/`location` filters are broken** (a "Software Engineering / New York"
  query returns Walmart and FBI listings). RemoteOK's public feed is mostly spam.
  Adzuna, USAJobs and Findwork all require a free API key.
- **BambooHR and Recruitee came back dry** for NYC engineering — Recruitee surfaced only
  staffing-agency boards.

## Filter design, and the bugs that mattered

Write regexes with word boundaries and verify matches before trusting a rejection. Real bugs hit:

- `m\.?s\.?` with no boundary matched the "ms" inside *systems*, *teams*, *requirements* →
  **20 false rejections**. Degree rules now run per-sentence and treat "BS **or** MS required" as a pass.
- "Graduating **by** August 2027" is an *upper bound* and includes candidates who graduated earlier. Only reject
  when a window's **start** is after the graduation date (parse "between Sept 2026 – July 2027").
- Cohort year and degree track are often in the **title only** ("Campus Undergraduate Full-Time
  Engineer - 2027 Software Engineer I", "Campus Graduate Masters"). Check titles, not just bodies.
- **Current-enrolment** requirements ("currently pursuing a bachelor's", "currently enrolled in
  M.S. program") exclude someone who has already graduated — separate from a year window.
- IT service-desk roles carry "Engineer" titles (Jr. Systems Engineer, IT Project Engineer) and
  score as "generic software engineering". Exclude explicitly.
- A posting that names **no** technologies is vague, not a mismatch — mark GENERIC, don't reject.
- **Location filters need region-level values, not just countries.** ATS location fields carry
  "Asia", "Latin America", "South Africa", "AMER" as well as city names — 17 non-US roles reached
  the delivered list before this was caught. Non-US markets also appear in the **title**
  ("Junior Software Engineer (LATAM)") while the location field says something else.
- **Cap the stack score.** Very long postings repeat keywords and inflate raw overlap; one scored
  98 purely by repetition. Beyond ~60 the signal is length, not fit.
- **Don't strip regex metacharacters with a character class.** `[\b()?:]` also deletes literal
  `b`s, printing "ack.end" and "moile app" as skill names.

## The REACH tier

A years floor one step above the profile ceiling is a reach, not a wall — a strong candidate
with shipped work does get those interviews. `read_jobs.py` returns `REACH` for
`MAX_YEARS + 1`, which is kept, chipped `reach` in the output and pushed down the ranking.
Anything higher is a genuine reject. Hard disqualifiers (degree, clearance, cohort gate,
enrolment) stay hard regardless of fit.

## Location and public-channel constraints

Hiring channels, examination rules, work authorization, and eligibility requirements vary by market and change over time. Check current official sources before treating a channel as open or closed. The included employer-board data and non-US filters are a US-oriented starting point; adapt them before searching another country or a materially different labor market.
## Verifying links

HTTP 200 is not proof: pulled postings often return 200, redirect to a generic careers page, or
serve an app shell. `verify_final.py` checks status, **redirect target** (a job ID in the request
that is gone from the final URL means dead), closed-posting text, and per-ATS title signals.
Only `verdict == "LIVE"` may reach the page — filter in the generator too, not just the selector.

## Ranking and output

`rescore.py` ranks every survivor by match to the active profile and writes `match_score` +
`match_why`. The score is deliberately transparent: skill overlap, a mismatch penalty, role-level
signals, years-of-experience fit, and a small location nudge. REACH and STRETCH roles are
penalised so they sort below solid matches.

`gen_html2.py` writes one self-contained HTML page as a **single ranked list, best fit first**
(it was previously grouped by location, which scattered the strongest matches). Each card shows
rank, a location chip, a fit rating, the **requirement evidence quoted from the posting**, the
match score with its reasoning, the verification timestamp, and the page title the server returned.
It also publishes the rejection tally so the filtering is auditable.

Send it with SendUserFile and overwrite the same path — one file, not one per run. Use the
`JOB_BASELINE`/`JOB_OUT` delta mode above when the ask is specifically "only what's new".

## Reporting rules

- State counts plainly and say what was rejected and why.
- Never claim a link is live without testing it. Say "unreadable, excluded" rather than assuming.
- If a filter change removes previously-shown roles, say so and name them.

## Local profile handling

Candidate profiles and job-run artifacts are private inputs. This repository contains no real candidate profile or prior search results. To run the workflow, copy `profiles/profile.example.json` to `profiles/<slug>.json`, fill it from the candidate's current resume and preferences, then set `profiles/active.txt` to that slug or pass `JOB_PROFILE`. Keep these local files out of commits; the adjacent `.gitignore` excludes them.
## Adapting to a very different candidate

The profile covers common role, experience, skill, and location filters. The harvesting scripts are still tuned for early-career software roles. Beyond the profile:

- **Senior candidates** — raise `max_years_required`/`stretch_years`, drop the seniority words from
  `title_exclude`, and clear `graduation_month`. The graduation and enrolment gates then no-op.
- **Non-engineering roles** — replace `title_include`, the role-title filters in the harvesters, and both skill tables. The eligibility
  machinery (degree, years, enrollment, and link status) is reusable, but the existing title and
  location filters also need to be retargeted.
- **A different city** — set `locations.primary`/`near`. Board coverage in `boards.json` is
  NYC-weighted, so run `discover.py` with local company names and mine the ATS domains by search
  (`site:job-boards.greenhouse.io "junior software engineer <city>"`) — that is what surfaced the
  small employers here.
