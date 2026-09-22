---
name: finviz-market-sentiment
description: Score finviz headlines for importance and investor sentiment, combine them deterministically into a 0-100 index and a non-neutral BUY/SELL call for the next 24 hours, and - only on a bullish reading - recommend which 3x leveraged long ETF best fits the news. You do the scoring yourself in-context; there is no API call and no API key. Use when the user asks about current market sentiment, whether the market looks bullish or bearish, wants a sentiment reading on the news, asks what investors are likely to do next, or asks which leveraged ETF to trade.
---

# Finviz market sentiment

**You are the model.** This skill never calls an API and needs no credentials.
You read the headlines and score them yourself; a script does the arithmetic.

The split is the whole point:

- **You judge** each headline — importance and sentiment. All the judgment,
  none of the decision.
- **The script decides** — a fixed formula turns your scores into an index and
  a verdict. Same scores in, same verdict out. No judgment, all of the decision.

Neither half can quietly do the other's job. Do not eyeball a verdict and do
not let the script infer sentiment.

## Workflow

### 1. Prepare

```bash
python ~/.claude/skills/finviz-market-sentiment/finviz_sentiment.py prepare
```

Scrapes fresh headlines via the sibling `finviz-news` skill and writes
`sentiment-worklist.txt` (numbered, for you to read) and
`sentiment-state.json` (full records, for the aggregator). Defaults to the 120
most recent.

Options: `--input <finviz-news-*.json>` to score an existing file instead of
scraping, `--limit N` (`0` = all), `--worklist`, `--state`.

### 2. Score every line yourself

Read the worklist and apply the rubric below. Write one line per headline to a
scores file:

```
<id> <importance> <sentiment> <themes> [optional short note]
```

e.g. `12 8 -6 rates_down,broad_market hot inflation print`

`themes` is a comma-separated list from the vocabulary below, or `-` for none.
It drives the ETF layer — a headline with no theme still counts toward the
index but steers no recommendation. Ids must match the worklist. Commas or
colons work as separators, and a JSON `{"scores": [...]}` file is also
accepted.

**Score every id.** Anything you skip is excluded from the index entirely
(never treated as neutral), which silently narrows the sample the verdict
rests on.

### 3. Aggregate

```bash
python ~/.claude/skills/finviz-market-sentiment/finviz_sentiment.py aggregate --scores scores.txt
```

Validates coverage and ranges, applies the weighting, and writes
`finviz-sentiment-YYYY-MM-DD.json` plus a console summary with the top
bullish and bearish drivers. Add `--strict` to fail rather than proceed on an
incomplete sample.

## Scoring rubric

Score each headline **independently**. Do not let one headline's score
influence another's, and do not try to balance the batch or produce a pleasing
spread — the aggregation handles balance.

### importance (1-10) — how much the average investor would care

Judge by how broadly the news moves capital.

| | |
|---|---|
| 1-2 | a single micro-cap, a routine promotional press release, filler |
| 3-4 | one small/mid-cap company, minor product or personnel news |
| 5-6 | a large-cap company's own news, or a sector-level story |
| 7-8 | a mega-cap move, a major sector shock, an important economic print |
| 9-10 | broad market, macro, monetary policy, or geopolitics that reprices everything |

### sentiment (-10..+10) — which way investors would read it for equities

| | |
|---|---|
| -10..-7 | severely bearish |
| -6..-3 | clearly bearish |
| -2..-1 | mildly bearish |
| 0 | genuinely neutral, purely factual, or too ambiguous to call |
| +1..+2 | mildly bullish |
| +3..+6 | clearly bullish |
| +7..+10 | strongly bullish |

Judge from the **market's likely reaction**, not from whether the event is
good for the world. Falling oil is bullish for equities even though it's bad
for producers. Rate cuts are usually bullish; hot inflation usually bearish.

Headlines describing a move that already happened ("stocks rise as…") should
be scored on what the move implies going forward, not double-counted as fresh
news.

**Importance and sentiment are independent.** A hugely important headline can
be neutral (importance 9, sentiment 0). A trivial one can be very bullish
(importance 2, sentiment +8). Use the full range; do not cluster near the
middle.

### Traps in this particular feed

- **Duplicates.** The same story often appears in two feeds (a wire story plus
  its press release). Score each occurrence on its merits — the source weight
  already discounts the promotional copy. Don't try to dedupe by hand.
- **Low-float momentum noise.** "No clear catalyst identified for X's 25%
  surge" is importance 1, not a bullish signal. There are usually dozens.
- **Contradictory macro.** Feeds routinely carry both "tensions easing" and
  "tensions worst yet" within the hour. Score both honestly and let the
  weighting fight it out — then say so in your summary.

## Theme tagging

Tag each headline with what it is *about*, so the ETF layer can map news to
instruments. Vocabulary (authoritative list and descriptions live in
[etf_universe.py](etf_universe.py) — `THEMES`):

`broad_market` `high_beta` `smallcap` `midcap` · `megacap_tech` `tech` `semis`
`software_internet` `ai` · `financials` `banks` `banks_regional` · `energy`
`oil_gas` `gold` `miners` · `healthcare` `biotech` `pharma` · `industrials`
`defense` `transport` `airlines` `travel` `autos` · `consumer` `retail`
`housing` `real_estate` `utilities` · `rates_down` · `china` `korea` `europe`
`mexico` `emerging`

Rules:

- Tag what the headline **implies for that theme's direction**, since the
  sentiment score is shared across its tags. "Oil plunges" is bullish for
  `broad_market` but bearish for `oil_gas` — if a headline cuts both ways,
  tag the theme the sentiment score actually describes and leave the other
  off, or split your reasoning into the note.
- `rates_down` means *yields falling*. A dovish Fed or a bond rally is
  positive for it; a hot inflation print is negative.
- Unknown tags are dropped with a warning, so typos silently weaken the
  recommendation rather than breaking the run — keep to the vocabulary.
- `-` is a legitimate answer. Most low-float momentum noise deserves it.

## 3x ETF recommendation layer

**Fires only on a bullish reading.** The universe is entirely long products,
so a recommendation on a flat or falling tape would point the wrong way. Two
hard gates in `recommend_etfs()`:

1. `net_sentiment > 0` — strictly positive. Bearish or exactly flat → nothing.
2. No tie-break. An index of exactly 50.0 that resolved to BUY by rule is a
   coin flip, not a bullish read → nothing.

"Bullish even in the slightest" is honored literally: net `+0.10`
(index 50.48) still produces picks.

Ranking, per ETF:

```
theme_net  = weighted mean sentiment across headlines tagged with the ETF's themes
confidence = evidence_weight / (evidence_weight + 1.0)      # shrinkage
score      = theme_net × confidence
```

The shrinkage stops one loud headline from crowning a niche fund. An ETF also
needs `theme_net > 0` and at least **2** distinct supporting headlines to be
eligible.

Funds whose matched themes are identical are the same trade (SPXL / UPRO /
UDOW all just express `broad_market`), so each theme signature is collapsed to
one representative — chosen by score, then by the `POPULARITY` liquidity proxy
— and the rest are listed as `equivalents`. Picks are therefore distinct
ideas, not three spellings of one.

### Universe

45 verified 3x **long** products in [etf_universe.py](etf_universe.py),
covering broad US, tech/AI, financials, energy, metals, healthcare,
industrials/transport, consumer, real assets, rates, and five regions.

Three candidates are permanently excluded, recorded in `REJECTED` and echoed
into every report so the exclusion is auditable:

| Ticker | Why excluded |
|---|---|
| `OILD` | **−3X inverse** (bearish). The bull counterpart `OILU` is in the universe instead. |
| `YSPY` | Not 3x — a GraniteShares YieldBOOST income ETF that *sells puts* on 3x SPY; caps upside. |
| `SEMY` | Not 3x — same YieldBOOST put-selling structure on 3x semis. |

Never reintroduce these. If a new candidate is proposed, verify leverage
**and direction** on the issuer's page before adding it.

`CAVEATS` carries per-ticker warnings that must be surfaced with any pick —
ETN credit risk, thin AUM (JETU ~$4M), and the funds that structurally fight a
risk-on tape (`TMF`/`TYD` need yields to *fall*; `SHNY`/`GDXU` are safe-haven).

## The weighting mechanism

Per headline:

```
weight = (importance/10)^1.5  ×  recency  ×  section  ×  source
```

| Factor | Range | Why |
|---|---|---|
| `(importance/10)^1.5` | 0.03–1.0 | Super-linear, so importance-10 macro outweighs a pile of importance-3 noise rather than being drowned by it. A 10 is ~31x a 1. |
| `recency` | 0.05–1.0 | Exponential decay, 6-hour half-life. This is a *24-hour* call. Floored at 0.05 so major older news never vanishes. |
| `section` | 0.65–1.0 | News 1.0, Market Pulse 0.85, Stocks News 0.70, Blogs 0.65 — wire reporting over opinion. |
| `source` | 0.5–1.0 | Paid-distribution wires (PR Newswire, GlobeNewswire, Business Wire, ACCESSWIRE, InvestorsHub…) are company-authored promo, so 0.5. Stocktwits 0.75. Everything else 1.0. |

Then across all scored headlines:

```
net   = Σ(sentiment × weight) / Σ(weight)        →  -10 .. +10
index = 50 + 5 × net                             →    0 .. 100
```

`net` is a weighted **mean**, not a sum, so the index doesn't drift just
because a slow news day produced fewer headlines. Bad *and* important pushes
the index down much harder than bad *and* trivial — that comes from the
multiply plus the exponent.

Conviction bands on `|net|`: <0.5 marginal, <1.5 weak, <3 moderate, <5 strong,
else very strong.

All constants are named at the top of
[finviz_sentiment.py](finviz_sentiment.py) and are the intended tuning surface.

## Never neutral

The indicator always resolves to `BUY` or `SELL`. The cascade, recorded in
`aggregate.tie_break`:

1. `net > 0` → BUY; `net < 0` → SELL (normal path, `tie_break: null`)
2. Exactly 0 → bullish vs bearish **weighted mass** (`weighted-breadth`)
3. Still tied → sign of the heaviest single headline (`heaviest-headline`)
4. Still tied → sign of the unweighted sentiment sum (`unweighted-sum`)
5. All zero → BUY (`exhausted-default-buy`)

Steps 2-5 essentially never fire on real data; they exist so the output is
total. An index of exactly 50.0 with a populated `tie_break` was a coin-flip
resolved by rule — report it as no signal regardless of the printed direction.

## Reporting to the user

Lead with the signal, index, and conviction. Then explain *why* using
`top_bullish` / `top_bearish` from the output — those rank by `|contribution|`
and are the headlines actually moving the number, which is the first thing to
check when a verdict looks surprising.

If a recommendation was issued, give the picks with their supporting themes
and headline count, and **always** repeat their `caveats`. If it was refused,
say so and give `recommendation.reason` — never soften a refusal into a
suggestion, and never name a ticker "for when it turns."

Always surface, when true:

- a large `counts.unscored` — the reading rests on a partial sample
- a populated `tie_break` — the call was decided by rule, not by the data
- contradictory macro headlines on opposite sides of the ledger
- that this measures **news sentiment**, has no backtest, and is not
  calibrated to returns. A 62.6 means "the flow leans clearly positive," not
  an expected move.

On any 3x recommendation, state plainly that these are **daily-reset leveraged
products**: they decay in chop, are designed for intraday-to-days holding, not
weeks, and a 3x fund can lose a third of its value on a 11% adverse move in
the underlying. This is a read of the news flow, not investment advice, and
you are not a financial adviser.

Your scores are a judgment call and will shift somewhat between runs — the
aggregation is what's deterministic, not the inputs. Say so rather than
implying the number is more precise than it is.
