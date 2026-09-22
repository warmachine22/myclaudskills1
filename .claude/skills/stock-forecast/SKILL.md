---
name: stock-forecast
description: Build a complete standalone HTML forecast dashboard for one stock — live price and technicals, financial history and forward estimates, fair value from its own historical multiple, an analysis of the latest earnings call and slide deck including what management guided versus what they delivered, a weighted scorecard, an explicit BUY or SELL rating that is never neutral, and our own target price with the reasoning shown. Use when the user asks for a full analysis, research report, dashboard, deep dive, forecast, outlook or rating on a stock, wants to know whether to buy or sell it, asks what a company is worth with the reasoning laid out, or asks to pull everything we know about a ticker into one page.
---

# Stock forecast dashboard

The capstone skill: it runs the other seven finance skills, reads what they
return, and produces one self-contained page that explains a company, values it,
reads its last earnings call, and commits to a call with a target price.

**This is a forecast, not a prediction.** A decision has to be made on incomplete
information — that is the premise. The page therefore shows its evidence, its
weights, its uncertainty, and what would prove it wrong.

## The three stages

The split is the whole design. Numbers cannot be invented because they all come
from a collected bundle. Judgment cannot be faked because a script refuses to
render a page without it.

| Stage | Who | Command |
|---|---|---|
| 1. Collect | script | `python scripts/collect.py TICKER --depth deep -d ./TICKER-bundle` |
| 2. Analyse | **you** | read the bundle, write `analysis.json` into it |
| 3. Render | script | `python scripts/render.py ./TICKER-bundle -o TICKER-forecast.html` |

Then publish the HTML as an Artifact and give the user the link.

### Stage 1 — collect

```bash
python ~/.claude/skills/stock-forecast/scripts/collect.py NVDA --depth deep -d ./NVDA-bundle
```

`--depth deep` (default) gets six quarters of transcript summaries, the full
latest call, the newest slide deck rendered to contact sheets, and market
headlines. `standard` skips the deck; `fast` is the numbers plus the latest
quarter only.

Writes into the bundle directory:

| File | What |
|---|---|
| `bundle.json` | every number the page will show (~35k tokens — read it whole) |
| `series.json` | heavy chart arrays; the renderer reads these, you do not |
| `READ-ME-FIRST.md` | what to read next and what to write |
| `transcripts/*.md` | per-quarter summaries with **Outlook and guidance** |
| `transcripts/*-FULL.md` | the latest call including Q&A with named analysts |
| `deck-sheets/*.png` | **contact sheets — look at these** |
| `deck-text/*.txt` | extracted deck text |
| `market-news.json` | market-wide headlines for the backdrop |

Cold run ≈ 2–4 minutes; warm ≈ 10 seconds, since every source is cached by its
own skill.

### Stage 2 — analyse

Read `READ-ME-FIRST.md`, then `bundle.json`, then the transcript summaries, then
the full latest call, then **open the deck contact sheets as images**. Write
`analysis.json` into the bundle directory.

Required keys — the renderer refuses without them: `thesis`,
`company_explainer`, `scorecard`, `rating`, `conviction`, `target_price`,
`section_commentary`, `falsifiers`. Strongly expected in deep mode:
`said_vs_delivered`, `qa_read`, `deck_findings`.

Two references govern this stage:
- **`references/scorecard.md`** — the seven dimensions, weights, scoring scale, conviction rules, target-price method, worked example.
- **`references/sections.md`** — what each section must contain, and the honesty rules.

### Stage 3 — render

```bash
python ~/.claude/skills/stock-forecast/scripts/render.py ./NVDA-bundle -o NVDA-forecast.html
```

One self-contained file: inline SVG charts, no CDN, no fonts, no network, light
and dark themes. It refuses to render if a required judgment block is missing,
and refuses a rating that is not exactly BUY or SELL.

## What the page contains

Header with rating badge, target and conviction meter · the call and the
scorecard with evidence · what the company does · price and technicals · financial
history and projections · fair value with the engine's guardrails verbatim · the
earnings call, said-vs-delivered, the Q&A read and deck findings · estimate
revisions and how it trades through prints · the forecast and its arithmetic ·
what would change our mind · full provenance.

## Which skill supplies what

One source of truth per field; a second source cross-checks but never averages.

| Field | Source |
|---|---|
| Price, market cap, technical snapshot, short interest | `finviz-earnings` |
| OHLCV and computed indicators | `yahoo-finance` + `sf_indicators.py` |
| Forward estimates, revisions, earnings reactions | `finviz-earnings` |
| Financial history, segments, profile, transcripts, filings, decks | `stockanalysis` |
| Analyst price targets | `stockanalysis`, cross-checked vs finviz |
| Fair value, normal multiple, base rates | `fair-value` |
| Next confirmed report date | `earnings-calendar`, cross-checked vs finviz |
| Market backdrop headlines | `finviz-news` (market-wide, not ticker-specific) |

Disagreements are surfaced in the Sources section rather than smoothed. The
"next report date" resolution is a real case: finviz's `next_report` can still
point at the quarter that just reported, so the collector takes the earliest
candidate date still in the future.

## Reading the output correctly — binding

- **The rating is never neutral, and that is a choice, not a claim of certainty.**
  Conviction carries the uncertainty. A low-conviction BUY on a name where the
  fair-value engine refused is close to a coin flip, and the page says so.
- **A discount to a stock's own historical multiple is not the same as cheap.**
  A company that has always traded at 130x will always look cheap against itself.
- **Check the fair-value back-test before leaning on valuation.** For several
  names — NVDA among them — cheapness has not predicted forward returns.
- **Beating estimates and rising afterwards are different things.** NVDA has beaten
  EPS eight quarters running and fallen on the day after four of its last six.
- **Estimates are consensus and get revised.** A fiscal year with fewer than five
  analysts is a placeholder.
- **Look at the deck images.** `decks.py audit` reports pages with no text, not
  pages whose data is in a picture. Verified on NVDA: the audit said the deck
  scraped cleanly while the entire Data Center revenue table existed only as an
  image. See `references/sections.md`.
- Not investment advice. The reasoning is shown so it can be disagreed with.

## Limitations

- **Operating companies only.** ETFs are rejected with a clear message —
  `financials`, `forecast` and `transcript` do not exist for a fund.
- Non-US listings have thin coverage upstream and will produce a sparse page.
- The scorecard weights are a judgment, written in `references/scorecard.md` so
  they can be argued with.
- Recency is bounded by each upstream skill's cache (10 minutes to 6 hours). Pass
  `--refresh` on a reporting day.

## Being a good citizen

This skill issues no requests of its own — every byte arrives through a sibling
skill's cache, throttle and User-Agent. Different hosts are queried in parallel;
calls to the same host stay sequential so no site sees a burst. Do not bypass the
siblings by calling the upstream sites directly, and do not loop this over a
universe of tickers: one deep run pulls a 13 MB PDF and ~20 requests, which is
fine for a name you are actually researching and rude at scale.

## Maintenance

Anchors to re-check if a run comes back thin:

- `collect.py` expects `sa.py transcripts` to return `{transcripts: [{slug, label, date}]}`, and `transcript T <slug> --no-body` to contain `#### Outlook and guidance` and `#### Financial highlights`. The said-vs-delivered table is built from those two headings.
- `sa.py download --type slides --latest -d DIR` supplies the deck; `decks.py audit|text|sheets` processes it. PyMuPDF and Pillow are required for the last two.
- `finviz_earnings.py raw` supplies `quarterly`, `annual`, `revisions`, `price_reactions`, `snapshot`. Snapshot cells are `{value, num, description}` with `num: null` on two-figure cells like `52W High`; **`SMA20/50/200` are percentage distances from price, not levels**.
- `fair_value.py T -f json` exits **2** when it honestly refuses — the collector treats that as a result, not a failure.
- Indicators are cross-checked against the finviz snapshot on every run and reported in the Sources section. RSI and ATR should match closely; the SMA gaps track the difference between our last daily bar and finviz's live quote.

Companion skills: `fair-value`, `finviz-earnings`, `stockanalysis`,
`yahoo-finance`, `earnings-calendar`, `finviz-news`, `finviz-market-sentiment`.
