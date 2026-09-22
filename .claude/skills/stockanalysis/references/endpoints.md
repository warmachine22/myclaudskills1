# stockanalysis.com endpoint map

Reference for maintaining the scraper. Read this if a command starts returning
empty sections — it tells you where each field comes from and how to re-derive
the map from scratch.

## The core trick

The site is a SvelteKit app. Any page URL, with `__data.json` appended to the
trailing-slash form, returns the data that page renders:

```
https://stockanalysis.com/stocks/nvda/financials/  →
https://stockanalysis.com/stocks/nvda/financials/__data.json
```

The response is `{"type":"data","nodes":[...]}`. Each node's `data` is a
**devalue-flattened array**: index 0 is the root, and every integer elsewhere is
a pointer into the same array. Negative values are sentinels (`-1` undefined,
`-2` array hole, `-3` NaN, `-4/-5` ±Inf, `-6` −0). `sa_core.unflatten()`
rehydrates it.

Node layout is consistent across every page sampled:

| Node | Contents |
|---|---|
| `nodes[0]` | session / theme / cookie state — ignore |
| `nodes[1]` | `{"info": {...}}` — symbol metadata, live quote, **feature manifest** |
| `nodes[2]` | the page payload |

`page_node()` picks it defensively rather than hardcoding index 2.

`robots.txt` allows all generic user agents (`User-agent: * / Disallow:`).
A browser `User-Agent` header is still required.

## `info` — fetch once, reuse

`nodes[1].info` rides along on *every* request, free:

- `ticker`, `nameFull`, `exchange`, `cik`, `ipoDate`, `curr` (separate
  `price` / `financial` / `dividend` currencies — they differ for non-US)
- `quote` — full live quote: `p` price, `c`/`cp` change, `o/h/l/cl`, `v`,
  `h52`/`l52`, `u` as-of string, `ms` market state, `ep`/`ecp`/`es` extended hours
- **`features`** — boolean map of which tabs exist for this symbol
  (`financials`, `statistics`, `forecast`, `transcripts`, `filings`, `metrics`,
  `profile`, `dividend`, `employees`, `market_cap`, `revenue`, `ratings`,
  `history`, `chart`). `brief` gates on this.
- `ticker` is **null for non-US `/quote/` symbols** — fall back to `uid`.

## URL families

| Instrument | Pattern | Notes |
|---|---|---|
| US stock / ADR | `/stocks/{sym}/` | includes foreign ADRs like ASML |
| ETF | `/etf/{sym}/` | `/stocks/{sym}/` answers with a **redirect node**, not a 404 |
| Non-US listing | `/quote/{exchange}/{TICKER}/` | exchange lowercase, ticker **uppercase** |

Non-US symbols expose only `chart` + `history`. Don't request other tabs.

## Page inventory

| Path | Payload keys | Notes |
|---|---|---|
| `/` | `marketCap, revenue, netIncome, eps, peRatio, forwardPE, dividend, beta, analysts, target, earningsDate, description, infoTable, financialChart, analystChart, analystTarget, news, chart, changes` | Scalars are **pre-formatted strings** (`"5.31T"`); `*Growth` siblings are raw floats |
| `/company/` | `profile, description (HTML), contact, details, executives, filings, logoURL` | `filings[].path` is relative to `sec.gov/Archives/edgar/data/`. No sub-tabs. |
| `/statistics/` | 19 groups + `trust` | Every group `{text, data:[{id,title,value,hover,url,proOnly}]}`. **No raw numbers** — `value` is display text, `hover` is full precision. |
| `/financials/` | `sections[7]` | Overview/chart route, **not** the income statement. Only place segment revenue lives (`/financials/segments/` 404s). |
| `/financials/income-statement/` etc. | `financialData, map, prior, ttmPrior, full_count, details` | See below |
| `/forecast/` | `estimates, estimatesCharts, currentRatings, priceTargets, targets, recommendations, ratings` | See below |
| `/metrics/` | `data.{groups, navigationItems, singlePages, quarterlyMetrics, trailingMetrics}` | Sub-tabs are **company-specific** |
| `/transcripts/` | `transcripts[]` | Full history in one payload, no pagination |
| `/transcripts/{slug}/` | `transcriptQuarter` | Full body, no paywall |
| `/filings/` | `events[]` | Quartr IR docs grouped by event, **not** EDGAR forms |
| `/dividend/` | `infoTable (dict!), history, chartData` | `infoTable` is a flat dict here, unlike elsewhere |
| `/history/` | `data.data[]` | Double-nested. ~6 months only; params ignored |
| `/ratings/` | `widget, ratings, meta` | 8 of `meta.total` rows; rest load client-side |
| `/employees/` | `stats, historical, peers` | `historical_quarterly` is null when `hasQuarterly` is false |
| `/market-cap/` | `stats, tables{daily,weekly,monthly,quarterly,annual}, peers` | 25 rows per table |
| `/chart/`, `/holders/`, `/ownership/` | — | **404. There is no ownership/insider data anywhere on the site.** |

## Financials specifics

`financialData` is **column-oriented**: `{line_item_id: [values]}`, every list
index-aligned to `datekey`, **newest first**. Meta keys `datekey`, `fiscalYear`,
`fiscalQuarter` come first and are strings.

- Absolute figures are **full units of currency** (`215938000000` = $215.94B).
- Margins/rates are **decimal fractions** (`0.741454` = 74.15%), not percent.
- `map` is the ordered row spec and the authority on labels, `format`
  (`percentage` / `pershare` / `ratio` / `reduce_precision`), `sectionStart`
  group breaks, and which `growth` rows to synthesize. It may name ids absent
  from `financialData` — render those blank.
- **Growth is never returned pre-computed.** Derive it from `financialData`
  plus `prior` (off-screen older periods, same orientation).
  `format: "inverted-growth"` means flip the sign for display.
- `?p=annual|quarterly|trailing` is the **only** working parameter. Anything
  unrecognised silently falls back to annual — always check the returned
  `period` field.
- `?range=` / `?r=` do nothing. The 10Y/20Y/Max buttons are Pro-gated.
- Caps: **6 annual columns** (5 years + TTM) or **20 quarters**. `full_count`
  reports what exists server-side (22 / 46) — the gap is the paywall.
- Annual always prepends a `"TTM"` column; quarterly does not — **except
  `ratios`, where quarterly does**. Test `datekey[0] == "TTM"`, don't assume.
- `ttmPrior` uses *different key names* than `financialData`
  (`ratio_gross_profit_margin` vs `grossMargin`). Not worth joining; compute
  TTM growth from the `p=trailing` series instead.

## Forecast specifics

- `estimates.table.{annual,quarterly}` is column-oriented. **`lastDate` is an
  integer index**, not a date: columns `0..lastDate` are reported actuals,
  everything after is an estimate.
- Free tier gives current FY + 1 forward year, and ~2 forward quarters.
  Gated cells hold the literal string `"[PRO]"` — `sa_core.depro()` nulls them.
- Two disagreeing price-target objects: `priceTargets` (S&P Global) and
  `targets` (TipRanks, with `chart` history and `filtered` look-back windows).
- Upside % is not in this payload; compute from `quote.p`, or read
  `analystForecasts.priceTargetChange` on `/statistics/`.
- `recommendations` = 12 monthly consensus snapshots. `ratings` = 5 recent
  individual analyst actions (`/ratings/` returns 8 of the same shape).

## Transcripts specifics

- Index returns the **complete history in one request** (149 events for NVDA,
  back to 2010). No pagination. Roughly 40% are earnings calls
  (`quarterLabel` matches `Q[1-4] YYYY`); the rest are keynotes, AGMs,
  conferences.
- Detail slug is `{quartrEventId}-{kebab-title}`, e.g. `568907-q1-2027`.
  Date-only forms like `/2027-q1/` do **not** exist.
- **Two mutually exclusive body formats:**
  - `transcriptTurns` (2013→present) — `[{speakerName, role, company,
    paragraphs}]` where `paragraphs` is a list of lists of
    `{text, startSec, endSec}` (two levels of nesting).
  - `fullTranscriptBody` (some pre-2013) — one plain-text blob, **no speaker
    attribution**.
- **No paywall, no truncation.** Earnings calls run 45k–75k chars.
- Prepared Remarks vs Q&A: `audioChapters` gives authoritative
  `{title, startTimestamp, endTimestamp}` in seconds, aligned to `startSec` —
  but it is **absent on many events, including recent earnings calls**. The
  fallback is structural: Q&A starts at the first `role == "Analyst"` turn,
  rolled back over the operator hand-off.
- `summaryLongHtml` (recent events) is a ~4KB pre-digested HTML summary with
  Executive summary / Financial highlights / Outlook and guidance sections.
  Cheap substitute when the full body is overkill.
- `transcripts[].files[].id` joins to `filings[].filings[].id` to turn a
  document stub into a downloadable URL.

## Filings specifics

Not EDGAR. There is no form code, no SEC URL, no description; `/filings/10-k/`
and `/sec-filings/` both 404, and `?type=` / `?page=` are ignored. Documents
carry a `type` from: `slides`, `earnings_release`, `quarterly_report`, `proxy`,
`annual_report`, `press_release`, `registration`. Filter client-side.
`fileUrl` needs its `?ref=` query string kept verbatim.

For actual EDGAR links, use `/company/` → `filings[].path`.

## Metrics specifics

Sub-tabs are **company-specific segment breakdowns** (NVDA: revenue by segment /
market platform / geography). Generic pages like `/metrics/revenue/` do not
exist — those live at the top level (`/stocks/nvda/revenue/`). Discover the real
set from the hub's `navigationItems` (slugified) and `singlePages[].page_path`.

The hub gates all but the ~8 most recent periods. The **group sub-pages return
~20 ungated periods with `change` and `growth` precomputed** — prefer them.
Series carry `valueType` of `CURRENCY` or `PERCENT`; format accordingly.

## Price history

Page params are ignored (~6 months, fixed). The undocumented REST API honours
them:

```
/api/symbol/s/{sym}/history?range=5Y&period=Weekly     # stocks
/api/symbol/e/{sym}/history?range=1Y&period=Monthly    # ETFs
/api/quotes/s/{sym}                                    # live quote
```

Shape gotcha: **with params `data` is a flat list; without them it is
`{"data":{"data":[...]}}`.** No API route exists for non-US `/quote/` symbols —
fall back to the page payload there.

## Cross-cutting inconsistencies

Three shapes vary by page and will bite a naive parser:

1. **News**: overview uses `{url, title, source, text, time, ago}`; sub-pages use
   a terser `{t, u, n, d}`. `time` is not a stable format — some rows are
   `"Aug 5, 2026, 2:51 PM EDT"`, others ISO-8601. `ago` is always present.
2. **`infoTable`**: stocks give `[{t, v, u}]`, ETFs give `[[label, value]]`,
   `/dividend/` gives a flat dict. `_info_table()` normalises all three.
3. **Formatted strings vs raw numbers** coexist in the same object — `/statistics/`
   is strings only, `/employees/` is numbers only, `/` mixes them.

Also: the overview's `changes` block holds **past prices**, not percentages
(`price1w: 190.01` = the close a week ago). Convert against the live quote.

## Re-deriving this map

```bash
python -c "
import sys; sys.path.insert(0,'../scripts')
import sa_core as sa, json
nodes = sa.fetch_data('/stocks/nvda/SOMEPAGE/')
print(json.dumps(sa.page_node(nodes), indent=1, default=str)[:6000])
"
```

Or use the built-in escape hatch, which needs no code:

```bash
python scripts/sa.py raw /stocks/nvda/dividend/ --node 2
```
