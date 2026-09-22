# Data map — what lives on the finviz earnings tab, and how to get it

Complete catalogue of the page at `https://finviz.com/quote.ashx?t=<TICKER>&ty=ea`
(the UI links it as `finviz.com/stock?t=<TICKER>&p=d&ty=ea`).

---

## How the page delivers its data

Everything the tab renders is embedded server-side in one JSON island:

```html
<script id="route-init-data" type="application/json">{ ... }</script>
```

**One HTTP request returns all six datasets.** There is no XHR to chase, no
pagination, no per-tab call. The visible tables are hydrated from this blob by
client-side JS, which is why grepping the HTML for `Price Reaction` or
`Report Date` finds nothing — those strings never exist in the source.

This matters for accuracy: the scraper reads typed JSON, not rendered markup.
A restyle cannot silently corrupt a number. A real schema change surfaces as a
missing key and a loud error, not a wrong value.

The fundamentals snapshot table is the one exception — it *is* server-rendered
HTML, in `<table class="snapshot-table2">`, and is parsed with a regex.

### The island's five arrays

| Key | Rows (NVDA) | Contents |
|---|---|---|
| `earningsDate` | scalar | Next report timestamp, e.g. `2026-08-26T16:30:00` |
| `earningsData` | 87 | Quarterly EPS / GAAP EPS / revenue, actual + estimate + analyst counts |
| `earningsAnnualData` | 21 | Same by fiscal year, plus `peRatio`, `peRatioGaap`, `psRatio` |
| `priceReactionData` | 12 | The price-action-around-earnings table |
| `earningsRevisionsData` | 8,803 | Every consensus snapshot over time |

Row counts vary by ticker (WMT: 125 quarters, 7,470 revisions).

---

## Category 1 · Next report

From `earningsDate` plus the first unreported row of `earningsData`.

| Field | Example | Note |
|---|---|---|
| Report datetime | `2026-08-26T16:30:00` | Eastern |
| Session | `AMC` / `BMO` | Derived: hour ≥ 16 → AMC |
| Fiscal period | `2026Q2` | Fiscal, **not** calendar quarter |
| EPS estimate | `2.0835` | Adjusted/non-GAAP consensus |
| GAAP EPS estimate | `2.1084` | Separate consensus |
| Revenue estimate | `91913.6062` | **In millions** |
| Analyst count | `40` | How many stand behind the number |

---

## Category 2 · Quarterly & annual history + forecast

`earningsData` (quarters) and `earningsAnnualData` (fiscal years). Per row:

| Field | Meaning |
|---|---|
| `fiscalPeriod` | `2026Q2` / `2010FY` |
| `fiscalEndDate` | Period end — **the only reliable sort key** |
| `earningsDate` | When it was reported (null for future periods) |
| `epsEstimate` / `epsActual` | Adjusted EPS consensus and result |
| `epsReportedEstimate` / `epsReportedActual` | **GAAP** EPS consensus and result |
| `salesEstimate` / `salesActual` | Revenue, in millions |
| `epsAnalysts` / `epsReportedAnalysts` / `salesAnalysts` | Coverage depth per metric |
| `peRatio` / `peRatioGaap` / `psRatio` | Annual rows only — historical multiples, **see the back-fill trap below** |

**Ordering trap.** The array is history *descending* with forward periods
*appended ascending*. `earningsData[0]` is the current quarter and
`earningsData[-1]` is the furthest-out forecast. Never assume a single
direction — always sort by `fiscalEndDate`.

**Reported vs forecast.** `epsActual is None` means the period has not been
reported; its figures are consensus. The scraper exposes this as `reported`.

**Back-filled annual multiples (silent, and the worst trap on the page).** For
fiscal years beyond roughly the last ten, finviz computes the annual `peRatio`
and `psRatio` as **today's price** over that year's EPS — not the price as it
was then. NVDA's 2015FY returns `8140.7`; AAPL's 2010FY returns `577`. Plotted
as history this draws a valuation cliff that never happened.

The scraper detects it exactly rather than by a year cutoff: if
`peRatio × epsActual` reproduces the current price to within 2%, the row was
back-filled. The value moves to `pe_ratio_stale`, the live field is set to
`null`, and `multiple_backfilled: true` is stamped on the row — so anything
plotting `pe_ratio` gets a gap instead of a fabricated spike. Six rows are
neutralised on both NVDA and AAPL (2010FY–2015FY).

Forward years legitimately use today's price over forward EPS, so rows with no
actual are left untouched.

Surprise is computed, not supplied: `actual - estimate`, and
`(actual - estimate) / abs(estimate) × 100`. `abs()` matters — a company
crossing from a loss to a profit otherwise produces a sign-flipped percentage.

---

## Category 3 · Price reaction to earnings ★

`priceReactionData` — 12 most recent events. **The section you asked about.**

Per event: `reportDate`, `fiscalPeriod`, `fiscalEndDate`, `rsi` (RSI-14), and a
`reactions` object with twelve named points:

| Point | What it is |
|---|---|
| `minus_1_week`, `minus_3_days`, `minus_2_days`, `minus_1_day` | Run-in closes |
| `open`, `high`, `low`, `close` | The **first session that could trade on the news** |
| `plus_1_day`, `plus_2_days`, `plus_3_days`, `plus_1_week` | Follow-through closes |

Each point carries `date`, `price`, `prevPrice`, `priceDiff` (% vs its own prior
day) and `spyPriceDiff` (SPY's move that same day — the benchmark).

### Three traps that will produce wrong numbers

**1 · The reaction day is not always the report date.** finviz's own footnote:
*"Daily change and RSI 14 are based on the report date for BMO releases and the
following day for AMC releases."* For an AMC reporter (NVDA, 16:30) the
`open`/`close` points are the **next** session. For a BMO reporter (WMT, 08:30)
they are the report date itself. Verified on both. The scraper derives the
session by comparing `reactions.open.date` to `reportDate` rather than trusting
the clock alone.

**2 · The chain breaks at the week points.** `priceDiff` is measured against
each point's own prior day, so the daily points chain contiguously
(`close → plus_1_day → plus_2_days → plus_3_days`) but `minus_1_week` and
`plus_1_week` do **not** — their `prevPrice` is an unrelated day. Compounding
straight through the array produces silent garbage. The scraper recomputes every
percentage from raw `price` values against a single baseline instead.

**3 · The baseline must be `minus_1_day`.** That is the last close before the
market could react. Every strategy return in this skill is measured from it.

### Derived measures (computed here, not supplied by finviz)

| Measure | Formula |
|---|---|
| `gap_pct` | `open / baseline − 1` — the overnight repricing |
| `day_pct` | `close / baseline − 1` — **the headline reaction** |
| `intraday_pct` | `close / open − 1` — did the gap hold or fade |
| `range_pct` | `(high − low) / baseline` — the day's swing |
| `d1/d2/d3/w1_pct` | Cumulative from baseline, **not** finviz's per-day change |
| `pre_3d_pct`, `pre_1w_pct` | Run-in into the print |
| `excess_day_pct` | `day_pct − spyPriceDiff` on the reaction day |
| `excess_d3_pct` | vs SPY compounded across the contiguous chain only |

**Cumulative vs per-day.** finviz's `+1 Day` column shows that day's own move
(-1.90% for NVDA's May 2026 print). This skill's `+1d` shows the cumulative move
from the pre-earnings close (-3.64%). Both are correct; they answer different
questions. The cumulative form is the one that answers *"what if I had bought
before the print and sold at +1 day"* — which is the whole point of the table.

---

## Category 4 · Estimate revisions

`earningsRevisionsData` — thousands of consensus snapshots. Per row:
`fiscalPeriod`, `estimateType` (**`E`** adjusted EPS · **`R`** GAAP EPS ·
**`S`** sales), `estimateDate`, `relativeFiscalPeriod` (1–6), `estimates`
(analyst count), `upRevisions`, `downRevisions`, `mean`, `high`, `low`, and
`price` (the stock's price at that snapshot).

Two things this supports that nothing else does: **estimate drift** (how far
consensus has moved since coverage began) and **dispersion** (`high` vs `low` —
how much analysts disagree, which is a decent proxy for how uncertain the print
is).

---

## Category 5 · Valuation & fundamentals snapshot

The server-rendered `snapshot-table2`: **84 label/value pairs**, each with a
tooltip that defines the metric. Groups:

| Group | Fields |
|---|---|
| Size & identity | Index, Market Cap, Enterprise Value, Income, Sales, Employees, IPO |
| Valuation | P/E, **Forward P/E**, **PEG**, P/S, P/B, P/C, P/FCF, EV/EBITDA, EV/Sales |
| Per share | Book/sh, Cash/sh, EPS (ttm), **EPS next Y**, EPS next Q |
| Growth | EPS this Y, **EPS next Y (2)**, EPS next 5Y, EPS past 3/5Y, Sales past 3/5Y, EPS Y/Y TTM, Sales Y/Y TTM, EPS Q/Q, Sales Q/Q |
| Dividends | Dividend Est., Dividend TTM, Ex-Date, Gr. 3/5Y, Payout |
| Balance sheet | Quick/Current Ratio, Debt/Eq, LT Debt/Eq |
| Profitability | ROA, ROE, ROIC, Gross/Oper./Profit Margin |
| Ownership | Insider Own/Trans, Inst Own/Trans |
| Short interest | Short Float, Short Ratio, Short Interest |
| Technical | SMA20/50/200, 52W High/Low, Volatility, ATR, RSI (14), Beta, Rel/Avg Volume |
| Performance | Perf Week → Perf 10Y |
| Analyst | **Recom** (1 = Buy, 5 = Sell), **Target Price** |
| Quote | Prev Close, Price, Change, Earnings, EPS/Sales Surpr. |

**Duplicate-label trap.** `EPS next Y` appears **twice** — once as the dollar
estimate (`12.78`) and once as the growth rate (`42.00%`). Keying naively by
label silently drops one. The scraper suffixes the second as
`EPS next Y (2)` and keeps every tooltip so the two can be told apart.

**Two-figure cells.** `52W High` is `236.54 -6.18%`; `EPS past 3/5Y` is
`204.08% 95.27%`. These hold two numbers in one cell. The scraper keeps the
display string and sets `num` to `null` rather than guessing which figure was
meant.

### Implied valuation (derived)

| Measure | How |
|---|---|
| TTM EPS | Sum of the last 4 **reported** quarterly `epsActual` |
| NTM EPS | Sum of the next 4 **unreported** quarterly `epsEstimate` |
| Implied forward P/E | `price / NTM EPS` |
| Implied EPS growth | `NTM EPS / TTM EPS − 1` |
| Forward-year P/E | `price / FY epsEstimate`, per forward fiscal year |

NTM is `null` when fewer than four forward quarters are published — a partial
year is never annualised, because padding one is how a forward multiple starts
lying. Forward years with **fewer than 5 analysts** are flagged `thin_coverage`;
NVDA's 2029FY consensus rests on a single submission.

`Forward P/E` from finviz uses the **next fiscal year**; the NTM figure uses the
**next four quarters**. They legitimately differ. Cross-check: WMT's 2027FY
implied 34.5× against finviz's reported 34.49 — matches.

---

## Category 6 · Peers & ETF holders

Peer tickers and holding ETFs are rendered as links in the page footer. Not
currently extracted — add only if a use case appears.

---

## Collecting it fairly

Finviz sells this data through Finviz Elite. This skill reads the same public
page a browser does, at browser volume. Keep it that way:

- **One request per ticker.** All six datasets come from one fetch; never hit
  the page once per section.
- **Cached 10 minutes** in the system temp dir. Repeated questions in a session
  cost one request. `--refresh` when a number must be live on a reporting day.
- **Requests spaced ≥ 2.5 s.** Enforced in `fetch_page`, matching the sibling
  finviz skills.
- **No scheduled loops, no bulk universe harvesting.** Pull the tickers a task
  actually needs.
- A `User-Agent` header is **required** — finviz rejects the default urllib
  agent.

## Reporting it accurately

- A row with no actual is **consensus, not a result**. Say so.
- Adjusted and GAAP EPS are different numbers with different consensus. NVDA's
  2026Q1 GAAP surprise was +36.5% against +6.5% adjusted — quoting the wrong one
  is the most common way earnings coverage misleads.
- Revenue is **in millions** in the raw payload.
- Fiscal ≠ calendar. NVDA's `2026Q2` ends 2026-07-31.
- 8–12 events is a **small sample**. Report base rates as history, never as a
  probability of what happens next. The renderers append that caveat
  automatically; don't strip it.
- Never convert a base rate into a recommendation.

---

## Maintenance

If `route-init-data island not found` is raised, the page changed. Anchors to
re-check in `scripts/finviz_earnings.py`:

- **Island:** `<script id="route-init-data" type="application/json">…</script>`
- **Snapshot pairs:** `<td … snapshot-td2 …><div class="snapshot-td-label">…`
  followed by `<div class="snapshot-td-content">`
- **Tooltip:** `data-boxover-html="…"` on the *label* cell — note it is not in a
  fixed attribute position, so it is extracted from the captured attribute
  string rather than inline in the pair regex
- **Session footnote** (confirms the AMC/BMO rule): *"Daily change and RSI 14 are
  based on the report date for BMO releases and the following day for AMC
  releases."*
