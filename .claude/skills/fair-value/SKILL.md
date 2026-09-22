---
name: fair-value
description: What a stock is worth at its own historical multiple — the normal-P/E method (FastGraphs / Peter Lynch style). Computes the stock's median P/E over 5/10/15 years, applies it to forward EPS estimates for a fair-value band, shows how the price has traded above or below that line since, and back-tests whether the multiple has actually predicted its forward returns. Use when the user asks whether a stock is expensive or cheap right now, what it is worth, its fair value or price target off historical P/E, whether it trades above or below its normal multiple, whether the multiple is stretched or has re-rated, or wants a valuation sanity check before buying.
---

# Normal-multiple fair value

The oldest back-of-envelope in equity research: a company that has historically
commanded 30x earnings, with $20 of expected EPS, is worth about $600. This skill
runs that properly — with a band instead of a point, a growth adjustment, and
guardrails that refuse the question when the arithmetic would mislead.

Everything comes through the **finviz-earnings** and **yahoo-finance** skills.
This one makes no HTTP requests of its own.

## Usage

```bash
python ~/.claude/skills/fair-value/scripts/fair_value.py NVDA
```

That single command is the answer to "is NVDA expensive right now?". Markdown by
default; `-f json` for the full structure, `-f csv` for the series.

| Command | What you get |
|---|---|
| `value T` | **Default** — verdict, windows, scenario grid, history, base rates, guardrails. The word `value` can be omitted. |
| `series T` | The weekly `date,price,ttm_eps,multiple` series |
| `history T` | The year-end table alone |
| `backtest T` | Base rates alone |
| `grid T` | The scenario matrix alone |
| `cache-clear` | Wipe cached payloads |

| Option | Effect |
|---|---|
| `--window 5\|10\|15\|max` | Years for the headline multiple (default 10). All available windows are reported regardless. |
| `--basis adj\|gaap` | Adjusted street consensus (default) or GAAP. Binds history *and* forwards together. |
| `--metric auto\|pe\|ps` | `auto` falls back to P/S when EPS is unusable |
| `--multiple X` | Override the normal multiple with your own |
| `--growth-haircut auto\|none\|linear\|0.8` | How hard to discount decelerating growth |
| `--bands 25,75` | Bear/bull percentiles |
| `--horizon 1y\|3y` | Back-test forward window |
| `--lag report\|period` | Point-in-time join (default) or fiscal-end |
| `--chart [FILE]` | Also write a self-contained HTML chart |
| `--no-backtest` · `-f` · `-o` · `--refresh` | |

Exit codes: `0` ok · `1` fetch failed / unknown ticker · **`2` refused** — the
guardrails ruled out a defensible number. That is a real answer, not a bug.

```bash
# Is it cheap against its own history?
python ~/.claude/skills/fair-value/scripts/fair_value.py MSFT

# With the picture, and a longer lookback
python ~/.claude/skills/fair-value/scripts/fair_value.py KO --window 15 --chart

# Your own multiple instead of the historical one
python ~/.claude/skills/fair-value/scripts/fair_value.py AAPL --multiple 26

# Compare bases — they will disagree, and that matters
python ~/.claude/skills/fair-value/scripts/fair_value.py NVDA --basis gaap
```

## The method

1. Roll reported quarterly EPS into a trailing-twelve-month series, each point
   dated to **the day it was announced** — not its fiscal period end.
2. Divide weekly split-adjusted closes by it. That is a point-in-time P/E series,
   typically 10–25 years long.
3. The **normal multiple** is the median of that series over the chosen window.
4. Haircut it if forward growth is slower than trailing growth.
5. Fair value = normal multiple x forward EPS consensus. The p25/p75 of the same
   distribution give the bear/bull band.
6. Back-test: bucket the weekly history by multiple quartile and measure what
   forward returns actually followed.

## Reading the output correctly — binding

These are not style preferences. Each one is a way the method lies.

- **A median multiple describes one stock's own past, not what the business is
  worth.** A company that has always traded at 130x will look "cheap" at 110x.
  The `EXTREME_MULTIPLE` flag exists for exactly this; never quote a discount
  against an extreme anchor without repeating the flag.
- **A regime shift makes the long-window answer meaningless.** AAPL's naive
  15-year median says it is ~50% overvalued, which is an artifact of the
  pre-services era, not a finding. When windows disagree, say so.
- **The historical multiple embeds the growth the company used to have.** If
  forward growth is half the trailing rate, the old multiple is not "normal", it
  is stale. Report the haircut and the two growth rates behind it.
- **Adjusted ≠ GAAP, and finviz's own P/E is GAAP.** On the default adjusted
  basis our current P/E will differ from the number finviz, Google and most
  screeners display — NVDA is 37.6x adjusted against 33.6x GAAP. The header says
  so; do not "correct" it. Never mix bases: history and forwards must be one.
- **Base rates are what happened.** Weekly windows overlap, so 470 observations
  hold roughly 9 independent years. Quote the effective sample, and when the
  buckets are not monotonic say the multiple has *not* been predictive for that
  name rather than burying it.
- **Forward estimates are consensus and get revised.** A fiscal year resting on
  fewer than 5 analysts is flagged and excluded from the headline.
- **Cyclicals invert the signal.** A low P/E on peak earnings is a warning, not a
  bargain. The `VOLATILE_BASE` flag fires; repeat it.
- **This is one lens.** It says nothing about balance sheet, competition,
  management or why the multiple was what it was. No buy/sell recommendations.

## Guardrails

Every check runs and reports, including the ones that pass. `refuse` blocks the
headline and triggers the fallback ladder.

| Flag | Fires when |
|---|---|
| `NEGATIVE_EPS` | Trailing EPS ≤ 0 — `warn` under 5% of weeks, `refuse` above |
| `NEAR_ZERO_EPS` | Trailing EPS under 20% of the window median, which inflates the multiple without ever going negative. This is the one nothing else catches. |
| `VOLATILE_BASE` | Peak-to-trough drop over 50%, or a loss inside the window |
| `REGIME_SHIFT` | Median multiple moved >35% between the window's halves |
| `EXTREME_MULTIPLE` | The "normal" multiple is itself above 60x (P/E) or 15x (P/S) |
| `THIN_COVERAGE` | A forward year resting on fewer than 5 analysts |
| `SHORT_HISTORY` | Under 156 usable weeks |
| `WINDOW_FALLBACK` | The requested window was unusable; a shorter one is in use |
| `METRIC_FALLBACK` | P/E was unusable and P/S is in play |
| `BASIS_MISMATCH` | Our TTM EPS disagrees with finviz's by more than 1.5% |

## When P/E does not work

`auto` falls back to **P/S**, rebuilding revenue per share from a share count
derived as `marketCap / lastClosePrice` via the stockanalysis skill. Two limits,
both stated in the output: the free tier caps share history at ~20 quarters so
the P/S window is about 5 years, and forward revenue per share assumes today's
share count — for the loss-making companies that need this fallback, dilution is
usually material.

**P/FCF is deliberately not a third rung.** finviz publishes a current P/FCF with
no history; a band built from a single point would be this skill's worst possible
failure.

## Caching and runtime

Payloads cache 6 hours in the system temp dir (`FV_CACHE_TTL` to change,
`--refresh` to bypass, `cache-clear` to wipe). Measured: **cold ≈ 12s** — two
subprocesses, finviz's 2.5s throttle, and a full-history price download — and
**warm ≈ 0.2s**. `--chart` adds ~150ms; the P/S fallback one more call. Ask for
several tickers in a row and only the first of each pays the cold cost.

## Being a good citizen

This skill issues no requests of its own — every byte arrives through the sibling
skills' caches, throttles and User-Agent headers. Do not bypass them by calling
the upstream sites directly, and do not loop this over a universe of tickers; it
is built for one name at a time.

## Companion skills

`finviz-earnings` (the estimate strip, revisions, how it trades through prints) ·
`stockanalysis` (transcripts, statements, segments) · `yahoo-finance` (prices) ·
`earnings-calendar` (who reports when).

Typical chain: `earnings-calendar` finds the name → **this skill** frames the
valuation → `stockanalysis` says what management actually claimed.

## Maintenance

Formulas, thresholds and the full field map: **`references/method.md`** — read it
before changing the maths.

Two upstream traps are encoded in the code and must stay that way:

- **Never use `adj_close` or `--auto-adjust` from yahoo-finance.** The raw `close`
  is already split-adjusted; `adj_close` additionally strips dividends. KO on
  2015-01-02: `close` 42.14 vs `adj_close` 29.39. Feeding the latter into a P/E
  history understates the multiple of every dividend payer and makes it look
  permanently overvalued.
- **Never read `annual[].pe_ratio` / `pe_ratio_gaap` / `ps_ratio` from finviz.**
  For fiscal years older than ~10 finviz divides *today's* price by that year's
  EPS — AAPL's 2010FY shows 577x. If a future version reads them, it is a bug.

Upstream anchors:

- `finviz_earnings.py raw T -f json` → `quarterly[].{fiscal_period,
  fiscal_end_date, earnings_date, reported, eps_actual, gaap_eps_actual,
  eps_estimate, revenue_actual}` · `annual[].{fiscal_period, fiscal_end_date,
  reported, eps_estimate, eps_analysts, revenue_estimate, revenue_analysts}` ·
  `snapshot.{Price, P/E, EPS (ttm), P/S, Dividend Est., Shs Outstand}` as
  `{value, num, description}` with `num: null` on two-figure cells.
- `yf.py history T --period max --interval 1wk --format csv` →
  `date,open,high,low,close,adj_close,volume`.
- `sa.py financials T -s ratios -p trailing --format json` → `periods[].date`
  (first column is `"TTM"`, not a date) and `rows[].{id, values}` for
  `marketCap`, `lastClosePrice`, `ps`.

If a run reports a `BASIS_MISMATCH`, our four-quarter EPS sum stopped agreeing
with finviz's own TTM figure — usually a restatement, sometimes a schema change.
Check `_basis_checks` in `scripts/fair_value.py` first.
