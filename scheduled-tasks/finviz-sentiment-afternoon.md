---
name: finviz-sentiment-afternoon
description: Afternoon (3:00 PM ET, weekdays) sentiment + 3x ETF call — updates the live dashboard artifact and pushes to phone
---

AFTERNOON market sentiment run (3:00 PM ET, final hour before the US close).

Use the `finviz-market-sentiment` skill (Skill tool) at .claude\skills\finviz-market-sentiment\ — read its SKILL.md and follow it exactly. There is NO API key and NO API call: YOU are the model that scores the headlines, in-context. Do not look for credentials.

Set <SENTIMENT_RUNS_DIR> to a writable location for run artifacts, and resolve the skill path from the repository root before running.

STEP 0 — confirm the output directory exists
  python -c "import os;os.makedirs(r'<SENTIMENT_RUNS_DIR>',exist_ok=True);print('ok')"

STEP 1 — prepare
  python ".claude\skills\finviz-market-sentiment\finviz_sentiment.py" prepare --limit 120 --worklist "<SENTIMENT_RUNS_DIR>\afternoon-worklist.txt" --state "<SENTIMENT_RUNS_DIR>\afternoon-state.json"

STEP 2 — score every headline yourself
Read <SENTIMENT_RUNS_DIR>\afternoon-worklist.txt
Score EVERY id using the rubric in SKILL.md. Write <SENTIMENT_RUNS_DIR>\afternoon-scores.txt with one line per headline:
  <id> <importance 1-10> <sentiment -10..10> <themes|-> <short note>
Use only the theme vocabulary in etf_universe.py. Critical direction rule: sentiment is SHARED across an entry's tags, so never tag a "falling oil lifts stocks" headline with oil_gas — falling oil is bearish for oil producers. Tag only the theme the sentiment actually describes. Score every id; anything skipped is silently excluded from the index.

STEP 3 — aggregate
  python ".claude\skills\finviz-market-sentiment\finviz_sentiment.py" aggregate --scores "<SENTIMENT_RUNS_DIR>\afternoon-scores.txt" --state "<SENTIMENT_RUNS_DIR>\afternoon-state.json" --out "<SENTIMENT_RUNS_DIR>\afternoon-sentiment.json"

STEP 4 — record history, then render
  python ".claude\skills\finviz-market-sentiment\history.py" append --report "<SENTIMENT_RUNS_DIR>\afternoon-sentiment.json" --label "Afternoon" --history "<SENTIMENT_RUNS_DIR>\history.json"
  python ".claude\skills\finviz-market-sentiment\history.py" render --history "<SENTIMENT_RUNS_DIR>\history.json" --out "<SENTIMENT_RUNS_DIR>\history.html"
  python ".claude\skills\finviz-market-sentiment\render_artifact.py" --report "<SENTIMENT_RUNS_DIR>\afternoon-sentiment.json" --label "Afternoon" --out "<SENTIMENT_RUNS_DIR>\dashboard.html"
  python ".claude\skills\finviz-market-sentiment\send_report.py" --report "<SENTIMENT_RUNS_DIR>\afternoon-sentiment.json" --label "Afternoon" --out "<SENTIMENT_RUNS_DIR>\afternoon-report.txt"
history.py append records NOTHING when no recommendation was issued — that is intended, do not work around it. send_report.py --out only writes a file; it does NOT send email (none is configured or wanted).

STEP 5 — UPDATE BOTH LIVE ARTIFACTS (do not skip, do not change either URL)
Two separate artifacts, each with its own permanent URL stored in a file. Update BOTH with the correct URL for each — do not swap them.
  a) Read <SENTIMENT_RUNS_DIR>\artifact-url.txt
     Artifact: file_path <SENTIMENT_RUNS_DIR>\dashboard.html, url = that URL, favicon 📊,
     description: Live market sentiment reading and 3x leveraged ETF call, refreshed by the scheduled pre-market and afternoon runs.
  b) Read <SENTIMENT_RUNS_DIR>\history-url.txt
     Artifact: file_path <SENTIMENT_RUNS_DIR>\history.html, url = that URL, favicon 📒,
     description: Running log of every bullish sentiment call with its date, time, and the three 3x ETFs it pointed to.
The `url` parameter is REQUIRED on both — this is a fresh conversation that did not publish them, so without `url` a new link is minted and the user's bookmark goes stale. Keep each favicon exactly as given. Never edit artifact-url.txt or history-url.txt.

STEP 6 — compare against the morning run
If <SENTIMENT_RUNS_DIR>\premarket-sentiment.json exists AND its generated_at is from TODAY, note the shift (e.g. "62.6 -> 48.1, flipped to SELL"). If missing or stale, skip silently — never compare against a different day.

STEP 7 — notify
a) PushNotification (status "proactive"), ONE line under 200 chars, no markdown:
   "Afternoon: <SIGNAL> <index>/100 <conviction> (AM <index>) — top 3x <TICKER>. <5-8 word driver>."
   If no recommendation was issued, say so instead of naming a ticker.
b) SendUserFile with <SENTIMENT_RUNS_DIR>\afternoon-report.txt, status "proactive", display "attach", one-line caption with signal, index, and morning delta.

STEP 8 — final message
State signal, index, conviction, morning shift if available, the picks (or that none were issued), whether a history row was recorded, and confirm both artifacts updated at their existing URLs.

RULES
- If recommendation.issued is false, state plainly that NO recommendation is being made and give recommendation.reason verbatim. Never soften a refusal into a suggestion and never name a ticker "for when it turns."
- Always repeat every caveat attached to a pick.
- Flag prominently if counts.unscored is large, or aggregate.tie_break is populated (direction decided by rule, not data — report as NO SIGNAL regardless of direction shown).
- If any STEP 1-4 command fails, STOP. Do not fabricate a reading, do not append history, do not republish either artifact with stale numbers. Push a notification with the failing command and the actual error text, and end.
