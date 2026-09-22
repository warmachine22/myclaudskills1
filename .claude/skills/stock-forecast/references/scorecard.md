# The scorecard

The rating is a weighted sum of seven scores, each between −2 and +2, each with
cited evidence.

**The arithmetic is not yours to do.** `analysis_contract.py` owns the composite,
the rating mapping, the conviction rule and the target anchor. You supply scores
and evidence; the module decides. That split is deliberate — it is the same one
the page uses everywhere else, and it means two runs with the same scores cannot
disagree about the conclusion.

```bash
# check your work before rendering
python scripts/validate_analysis.py ./TICKER-bundle/analysis.json
python scripts/score_model.py ./TICKER-bundle --analysis ./TICKER-bundle/analysis.json
```

---

## The seven dimensions

| Dimension | Weight | Scored from |
|---|---:|---|
| Valuation vs fair value | 22% | `bundle.fair_value` — premium, percentile, guardrails, back-test |
| Earnings execution and delivery | 20% | said-vs-delivered from transcripts + surprise history |
| Growth trajectory | 16% | revenue/EPS growth, trailing vs forward CAGR, acceleration |
| Estimate revisions | 15% | `bundle.finviz.revision_trend` — 90/180-day change, up vs down |
| Quality and balance sheet | 12% | margins, returns on capital, leverage, concentration |
| Technical setup | 10% | `bundle.technicals.latest` — trend stack, MACD, RSI |
| Market and macro backdrop | 5% | `bundle.market_news` + `bundle.macro` — market-wide, **not** ticker-specific |

The dimension names are **exact keys**. `validate_analysis` raises if any is
missing — a scorecard that quietly omits a dimension would renormalise its weight
onto the others and change the rating without saying so.

### Why these weights

Reconciled from two implementations that disagreed. One weighted valuation
heaviest; the other put management execution first.

Valuation stays first at 22% because it remains the single largest determinant of
forward return. But execution rose to 20% — the record of doing what you said you
would do is the most *checkable* qualitative evidence available, and unlike a
multiple it cannot be argued away. Growth and balance-sheet quality are kept
separate rather than merged, because they fail independently: merging them hides
a decelerating business behind a strong balance sheet. Macro sits at 5% because it
is market-wide data being applied to a single company.

They are a judgment, not an empirical result. Change them in
`analysis_contract.py` — one place, and every consumer follows.

## Scoring scale

| Score | Meaning |
|---:|---|
| +2 | Unambiguously favourable; hard to argue the other side |
| +1 | Favourable with a real caveat |
| 0 | Genuinely balanced, or the evidence cuts both ways |
| −1 | Unfavourable with a mitigating factor |
| −2 | Unambiguously unfavourable |

Reserve ±2 for one-sided evidence. If your evidence sentence contains a "but", it
is a ±1 or ±1.5.

Every row needs `evidence` citing the actual numbers. A score without evidence is
an opinion wearing a number, and the validator rejects it.

## Composite, rating, conviction

```
composite = Σ(score × weight) / Σ(available weight)
rating    = BUY if composite > 0 else SELL
```

Unavailable dimensions carry `"unavailable": true` and drop out of both sums, so
the composite is normalised over what actually had data — and `coverage` records
how much that was.

**There is no neutral bucket.** A composite of +0.05 is a BUY, a low-conviction
one. Zero maps to SELL so the page can never emit a non-answer.

| Conviction | When |
|---|---|
| high | \|composite\| ≥ 1.0 and every dimension had data |
| medium | \|composite\| ≥ 0.5, or ≥1.0 with one dimension unavailable |
| low | \|composite\| < 0.5, **or** ≥2 dimensions unavailable, **or** fair-value refused |

The validator warns if your stated rating disagrees with the computed mapping, and
if coverage falls below 60%.

## Target price

`derive_target()` computes a deterministic **anchor**: the normal-multiple fair
value, moved by at most ±10% by your execution, growth, quality and revisions
scores.

**Analyst consensus never enters that calculation.** It is returned alongside as a
cross-check so the page can show the gap. An earlier revision blended 75/25 with
the Street; that was removed on purpose — a blended target inherits the herd's
anchoring, which is the specific thing an independent view exists to avoid.

The anchor is a starting point, not a verdict. Depart from it when the arithmetic
does not fit — a company mid-re-rating, or one whose forward year is the wrong
denominator. But departing requires reasoning: the page prints both numbers and
the gap, and the validator warns when a departure over 25% arrives with a thin
derivation.

State the load-bearing assumption. It is almost always the EPS estimate, not the
multiple — say what the target becomes if that estimate is wrong.

If fair value was refused there is no anchor. Build the target from something else
entirely — a peer multiple, a sales multiple, an explicit scenario — and say which.

## Worked example — NVDA, August 2026

| Dimension | Score | Why |
|---|---:|---|
| Valuation vs fair value | +1.5 | 36% below the $349.66 implied by its own 10-year multiple; 19th percentile. Not +2: the back-test found **no monotonic relationship** between cheapness and forward return for this stock. |
| Earnings execution and delivery | +1.5 | Revenue guidance beaten five quarters running; EPS eight. Not +2: Q1 FY2026 gross margin missed by ten points on a $4.5B H20 charge. |
| Growth trajectory | +1.5 | Revenue +85% YoY, third consecutive accelerating quarter. Not +2: trailing 5-year EPS CAGR 81.5% vs ~47% forward. |
| Estimate revisions | +2.0 | FY consensus EPS +8.7% in 90 days on 388 up-revisions vs 31 down. One-sided. |
| Quality and balance sheet | +1.0 | 74% gross margin, 114% ROE, 0.07 debt/equity. Held at +1: hyperscale is ~half of Data Center revenue; China assumed at zero. |
| Technical setup | +1.0 | Trend stack 3/3, MACD positive, 5% off the high. Held at +1: 42.5% annualised volatility, earnings in three weeks. |
| Market and macro backdrop | +0.5 | S&P at a record high — supportive, but a record high is also peak complacency. |

Composite **+1.42** → **BUY**, conviction **high**, coverage 100%.

Anchor **$375.89** (fair value $349.66 × 1.075 quality modifier). Final target
**$420**, a +12% departure justified by applying 33× to FY2027 EPS rather than the
anchor's FY2026 basis. Street consensus $302.83 shown as a cross-check, excluded
from both.
