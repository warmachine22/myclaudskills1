---
name: finviz-earnings
description: Per-company earnings history, forward estimates, analyst revisions, implied valuation, and how the stock has actually traded around each of its last 12 reports (gap, day move, drift, vs SPY, RSI) — from the finviz earnings tab. Use when the user asks how a stock behaves around earnings, whether it usually beats, what the market expects this quarter, what a company is worth on forward estimates, its forward P/E or implied multiple, whether estimates are being revised up or down, or wants base rates and historical patterns for an upcoming report.
---

# Finviz earnings

Everything on `finviz.com/stock?t=<TICKER>&p=d&ty=ea` — earnings history,
forward consensus, estimate revisions, the fundamentals snapshot, and the
price-action-around-earnings table — from **one HTTP request per ticker**.

The page embeds all of it as JSON in a `route-init-data` script island, so this
reads typed values rather than parsing rendered HTML. Stdlib-only Python, no
dependencies, responses cached 10 minutes.

Full field catalogue, the derivation formulas, and the parsing traps:
**`references/data-map.md`** — read it before changing the parser or before
quoting anything unusual.

## Usage

```bash
python ~/.claude/skills/finviz-earnings/scripts/finviz_earnings.py <command> <TICKER>
```

| Command | What you get |
|---|---|
| `summary` | The briefing: next report, beat rates, how the stock moved, base rates, valuation |
| `reaction` | The price-action table per report + base rates by holding window |
| `estimates` | Quarterly EPS / GAAP EPS / revenue, reported and forecast |
| `annual` | Same by fiscal year, with historical P/E and P/S |
| `revisions` | Consensus drift, dispersion, up/down revision counts |
| `valuation` | Implied multiples off the estimate strip + the 84-field snapshot |
| `raw` | Everything, normalised, as JSON |

Options: `-n N` rows/events (default 12) · `-f md|json|csv` · `-o FILE` ·
`--refresh` to bypass the cache.

```bash
# How does NVDA actually trade through its prints?
python ~/.claude/skills/finviz-earnings/scripts/finviz_earnings.py reaction NVDA

# What is it worth on forward consensus?
python ~/.claude/skills/finviz-earnings/scripts/finviz_earnings.py valuation NVDA

# Everything, for analysis
python ~/.claude/skills/finviz-earnings/scripts/finviz_earnings.py raw AMAT -f json -o amat.json
```

Exit codes: `0` ok · `1` fetch failed or unknown ticker.

## The price-reaction model

The baseline for every percentage is **the last close before the market could
react**. finviz reacts on the report date for BMO releases and the following
session for AMC releases; the scraper derives which from the data, not a guess.

| Field | Meaning |
|---|---|
| `gap_pct` | Close-before → next open. The overnight repricing. |
| `day_pct` | Close-before → reaction-day close. **The headline number.** |
| `intraday_pct` | Open → close. Whether the gap held or faded. |
| `d1/d2/d3/w1_pct` | Cumulative from the baseline — *not* finviz's per-day column |
| `pre_3d_pct` / `pre_1w_pct` | The run-in before the print |
| `excess_day_pct` | Same-day move minus SPY's |

Seven holding windows get a hit rate, mean, median, best and worst:
hold-through-print, overnight-gap-only, post-gap-drift, hold-3-days,
hold-1-week, run-in-3-days, run-in-1-week.

Also computed — and usually the most interesting line in the output — **whether
beating actually paid**. NVDA has beaten EPS on 8 of its last 8 reports and the
stock fell on 6 of them. That divergence is the story; the beat rate alone is
not.

## Honest reporting — binding

The numbers are easy to misuse. These are not style preferences:

- **8–12 events is a small sample.** Report base rates as *what has happened*,
  never as the probability of what happens next. The renderers append that
  caveat; do not strip it.
- **Never turn a base rate into a recommendation.** "It rose 6 of the last 8
  times" is an observation. "So buy it before the print" is advice, and this
  skill does not give advice.
- **Unreported rows are consensus, not results.** Label estimates as estimates.
- **Adjusted ≠ GAAP.** Both are published with separate consensus. NVDA's
  2026Q1 GAAP surprise was +36.5% against +6.5% adjusted. State which one you
  are quoting.
- **Forward multiples rest on consensus**, which is revised constantly. A
  forward year with fewer than 5 analysts is flagged `thin_coverage` — never
  quote one without saying how thin it is.
- **Revenue is in millions** in the raw payload; **fiscal ≠ calendar** quarters.
- **Annual `pe_ratio` older than ~10 years is back-filled by finviz** using
  today's price, which produces absurd multiples (NVDA 2015FY: 8,140x). Those
  rows are auto-detected, nulled, and stamped `multiple_backfilled` — never
  restore them, and never chart `pe_ratio_stale`.

## Being a good citizen

Finviz sells this through Finviz Elite. This reads the same public page a
browser does, at browser volume: one request per ticker, cached 10 minutes,
spaced ≥ 2.5 s, `User-Agent` set (finviz rejects the default urllib agent). No
scheduled scraping loops, no bulk universe harvesting.

## Companion skills

`earnings-calendar` (who reports when) · `stockanalysis` (transcripts, segments,
filings) · `finviz-news` (headlines) · `yahoo-finance` (price history).

Typical chain: `earnings-calendar` finds the name → **this skill** supplies the
setup, the base rates and the valuation → `stockanalysis` supplies what
management actually said.

## Maintenance

If the script reports `route-init-data island not found`, the page changed. The
anchors to re-check are listed at the bottom of `references/data-map.md`.
