# Method reference

Formulas, thresholds and the reasoning behind each choice. Read this before
changing `fv_model.py`.

## 1. The trailing series

```
ttm_eps[i]  = Σ eps_actual over reported quarters i-3 .. i     (basis-locked)
avail[i]    = earnings_date[i]  or  fiscal_end_date[i] + 45 days
multiple[t] = close[t] / ttm_eps[j]    where j = max{ j : avail[j] <= date[t] }
```

**Why `earnings_date` and not `fiscal_end_date`.** Joining on the fiscal end
credits the market with knowing Apple's December-quarter EPS on 31 December, when
it was announced on 28 January. That is lookahead bias, and it lands exactly
where the TTM series steps — the points of maximum distortion. The cost of the
lag is that the first ~45 days of each quarter carry the prior figure, which is
precisely what an investor actually saw. `--lag period` exposes the alternative
for comparison; it is never the default.

Weeks before the first knowable TTM figure are dropped, never back-filled.
Weeks where the denominator is ≤ 0 keep their observation (so the guardrails can
count them) but carry `multiple = None`.

Typical result: AAPL ~1,340 weekly observations from 2000, NVDA ~980 from 2007.

## 2. Basis lock

| Basis | History | Forwards |
|---|---|---|
| `adj` (default) | `eps_actual` | `eps_estimate` |
| `gaap` | `gaap_eps_actual` | `gaap_eps_estimate` |

EPS is read **only** through `eps_of(row, basis, kind)`. There is deliberately no
fallback from adjusted to GAAP on a missing value — a null drops the quarter and
truncates the window with a warning. NVDA's 2026Q1 is 1.8663 adjusted against
2.39 GAAP, a 28% gap on one quarter; silent substitution must be structurally
impossible, not merely discouraged.

**finviz's `snapshot["EPS (ttm)"]` and `snapshot["P/E"]` are GAAP diluted.**
Verified on NVDA: Σ4Q GAAP 6.5280 ≡ snapshot 6.53, while Σ4Q adjusted is 5.8363.
So on the default basis our current P/E (37.6x) legitimately differs from the one
finviz displays (33.6x). Both are printed. This is not an error to reconcile.

Two checks run every time, tolerance 1.5%:

1. Σ4Q GAAP EPS vs `snapshot["EPS (ttm)"]` — validates quarter selection and
   ordering against finviz's own TTM.
2. `price / snapshot EPS` vs `snapshot P/E` — validates the snapshot internally.

A breach sets `checks.basis_ok = false` and prints `BASIS_MISMATCH`. It catches
restatements, share-count discontinuities and schema drift with one comparison.

## 3. Windows and the headline choice

Standard windows are 5 / 10 / 15 years, plus the requested one. A window is
skipped when the underlying series spans less than 90% of it — otherwise a
5-year-deep series would produce three identical rows implying agreement that
isn't there. When nothing qualifies, the full span is described as `max`.

**Regime test:** compare the median multiple of the window's first half to its
second. A shift over ±35% means the halves describe different eras, and the
headline falls back to the longest *shorter* window that passes. If every window
fails, the shortest is used and the report says plainly that no stable multiple
exists.

Worked example — AAPL: 15y halves 14.6 → 29.9 (+104%), 10y 18.5 → 30.9 (+67%),
5y passes. The naive 15-year answer would call it ~50% overvalued off a $161 fair
value. The 5-year window gives ~30.9x and a far more defensible read.

## 4. Percentiles

Linear interpolation, numpy-compatible. `percentile(values, q)` with `q` in
0–100. The band defaults to p25/p75 (`--bands`).

Winsorization clamps multiples outside p1/p99 when there are ≥ 20 observations,
so a single near-zero-EPS quarter cannot set the band. The count of clamped
values is reported in `NEAR_ZERO_EPS`.

## 5. Growth adjustment

```
g_hist = (ttm_eps_now / ttm_eps_5y_ago) ^ (1/5) - 1
g_fwd  = (eps_FYn / ttm_eps_now) ^ (1/years_to_FYn) - 1     # newest FY with ≥5 analysts
factor = clamp(sqrt(g_fwd / g_hist), 0.60, 1.00)
normal_adjusted = normal_raw * factor
```

- **Never marks up.** `factor` caps at 1.0; accelerating growth prints a note and
  changes no number. The failure mode of this method is paying a hypergrowth
  multiple for a decelerating business, not the reverse, so the correction is
  one-sided by design.
- **`sqrt`, not linear.** In a two-stage dividend-discount model, justified P/E
  responds to growth sublinearly over the relevant range; linear halves the
  multiple when growth halves, which is too violent. `--growth-haircut linear`
  for those who disagree, `none` to disable, a bare number to set it directly.
- **Floor 0.60.** Below that the business has changed enough that its own history
  is a weak anchor, and the output says so rather than extrapolating further.
- `years_to_FYn` uses the actual fiscal end date, not a round number of years.
- If either rate is undefined or non-positive (a negative base), no haircut is
  applied and the reason is printed.

Worked example — NVDA: trailing 5y 81.5%/yr against forward 47.2%/yr to FY2028
(2.5 years out) → ratio 0.579 → factor 0.761 → 51.1x becomes 38.9x, moving FY1
fair value from $460 to $350.

## 6. Guardrail thresholds

| Flag | Test | `warn` | `refuse` |
|---|---|---|---|
| `NEGATIVE_EPS` | share of weeks with denominator ≤ 0 | ≤ 5% | > 5% |
| `NEAR_ZERO_EPS` | weeks with denominator < 20% of window median | ≤ 10% | > 10% |
| `VOLATILE_BASE` | peak-to-trough drawdown | > 50% | — |
| `REGIME_SHIFT` | \|median₂/median₁ − 1\| | > 0.35 | — |
| `EXTREME_MULTIPLE` | normal multiple | > 60x P/E, > 15x P/S | — |
| `THIN_COVERAGE` | forward-year analyst count | < 5 | — |
| `SHORT_HISTORY` | usable weeks | — | < 156 |

The denominator tests apply to whichever denominator is in use. A name on P/S is
never refused for negative EPS — negative EPS is why it is on P/S.

`NEAR_ZERO_EPS` is the one nothing else catches: BA's trailing-5y median P/E
computes to 228.9x off a positive-but-tiny denominator, which no sign test flags.

`EXTREME_MULTIPLE` catches the quietest failure of all — PLTR's 134x "normal"
multiple makes it look 27% cheap while every other number in the report looks
reasonable.

## 7. Base rates

Bucket weekly observations into multiple quartiles *within the window*, then
measure the realised 52-week (or 156-week) forward price return of each bucket.
Forward pairing requires a matching observation within ±21 days of the target
date.

Three things address the overlap problem:

1. **Effective independent observations** = `n / horizon_weeks`, printed in the
   table header, not a footnote. 470 weekly observations hold about 9 independent
   one-year periods.
2. **Non-overlapping estimate** — sample every 52nd observation, repeat across
   all 52 phase offsets, report the median of the per-phase medians so no single
   start date drives the result.
3. **`monotonic`** — true only when bucket medians decline strictly from cheap to
   expensive. When false, the renderer leads with "no monotonic relationship" and
   that cannot be suppressed by a flag.

NVDA's 10-year run is the regression case: directionally right at the extremes
(Q1 +128%, Q4 +62%) but Q3 sits below Q4, so the caveat fires.

## 8. P/S fallback

```
ttm_rev[i] = Σ revenue_actual over quarters i-3..i          # $mm
shares[q]  = marketCap[q] / lastClosePrice[q]               # sa trailing ratios
ps[t]      = close[t] / (ttm_rev[t] * 1e6 / shares[t])
```

Reconciled against `snapshot["P/S"]`, tolerance 5%, reported either way.
Verified: BA ours 2.02 vs finviz 1.96; RIVN 3.58 vs 3.80 (flagged).

The series is **truncated** at the oldest known share count rather than carrying
it backwards — an extrapolated share count would silently fabricate multiples for
years it cannot cover. The free tier gives ~20 quarters, so the window is ~5
years. Forward revenue per share uses today's share count; for the loss-making
names that need this fallback, dilution is usually material and the output says
so.

## 9. Chart

Log y-axis, always. Over ten years a compounder moves two orders of magnitude and
a linear axis collapses the early history onto the baseline — precisely the years
when the stock was cheapest.

Colours are the `dataviz` reference palette slots 1 and 2, validated in both
modes (worst adjacent CVD ΔE 24.7 light / 26.8 dark; all six checks pass). The
band is the fair-value hue at 13% (light) / 20% (dark). The fair-value line is
drawn stepped, because it only changes when earnings are announced.

Tick ladders run coarse to fine — `(1)`, `(1,5)`, `(1,2,5)`, `(1,2,3,5,7)`,
`(1,1.5,2,…,9)` — keeping the densest that fits in 9 ticks. Subsampling a 1-2-5
ladder with a stride yields 1, 5, 20, 100, which reads as an irregular axis.

The page is self-contained: no CDN, no fonts, no network. One inline script adds
a hover crosshair; everything the chart says is legible with JS disabled.
