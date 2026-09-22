---
name: stockanalysis
description: Pull grounded, citable company fundamentals from stockanalysis.com — full earnings call transcripts, analyst forecasts and price targets, income statement / balance sheet / cash flow / ratios, valuation statistics, segment breakdowns, filings, company profile, dividends and news. Use when the user asks about a company's earnings, quarterly results, guidance, revenue/EPS/margins, analyst estimates or targets, what management said on an earnings call, a stock's fundamentals or valuation, or wants research, a script, or a briefing for content about a stock or its earnings release.
---

# stockanalysis.com

Grounded company data — fundamentals, forecasts, filings and **full earnings call
transcripts** — pulled from stockanalysis.com's own page-data endpoints.

Reach for this over general web search whenever the question is about a specific
company's numbers or what management actually said. Everything returned is what
the site itself renders, so it is citable and auditable.

## How it works

The site is a SvelteKit app: every page URL, with `__data.json` appended, returns
the exact data that page renders. `scripts/sa_core.py` decodes it. **No HTML
parsing**, so a restyle can't silently corrupt numbers — a real schema change
shows up as missing sections instead of wrong ones.

Stdlib-only Python. No API key, no install, no dependencies. (The optional
`decks.py` PDF reader is the one exception — it needs PyMuPDF and Pillow.)

## Usage

```bash
python ~/.claude/skills/stockanalysis/scripts/sa.py overview NVDA
```

Markdown by default (dense, self-labelling, cheap for a model to read).
`--format json` for programmatic use, `--out FILE` to write instead of print,
`--refresh` to bypass the cache. These work before *or* after the subcommand.

### Commands

| Command | What you get |
|---|---|
| `overview T` | Price, market cap, revenue/EPS + growth, PE, analyst consensus & target, next earnings date, 5y history, business description, recent news. ETFs get an AUM/expense/holdings view instead. |
| `quote T` | Last + extended-hours quote only |
| `brief T` | **Earnings briefing pack** — see below |
| `financials T` | `-s overview\|income\|balance\|cash-flow\|ratios`, `-p annual\|quarterly\|trailing`, `--limit N` |
| `forecast T` | Ratings breakdown, target high/avg/low + implied upside, revenue & EPS estimates by fiscal year and quarter, estimate dispersion, consensus history |
| `statistics T` | The full statistics grid — valuation, EV ratios, margins, financial position, short interest, dividends, price stats, fair-value estimates |
| `transcripts T` | Earnings call index (`--all` to include keynotes/AGMs) |
| `transcript T [q1-2027]` | One **full** call transcript, split into Prepared Remarks and Q&A |
| `metrics T` | Company-specific segment breakdowns; `--sub SLUG` or `--sub all` |
| `company T` | Description, sector, employees, executives, identifiers (CIK/CUSIP/ISIN), EDGAR filing links |
| `filings T` | IR document list — earnings releases, slide decks, annual/quarterly reports, proxies (`--type 10-K`) |
| `download T` | **Fetch those documents as PDFs to disk** — see below |
| `news T` | Recent headlines with summaries |
| `dividend T` | Yield, payout ratio, full payment history |
| `ratings T` | Individual analyst actions with each analyst's track record |
| `employees T` | Headcount history, revenue/profit per employee, peer comparison |
| `history T` | Price bars (`--range 1Y\|5Y\|MAX` for more than ~6 months) |
| `raw PATH` | Escape hatch: dump any page's decoded payload |
| `cache-clear` | Wipe the on-disk cache |

### Tickers

| Kind | Form |
|---|---|
| US stock or ADR | `NVDA`, `ASML` |
| ETF | `SPY` — auto-detected via redirect |
| Non-US listing | `EXCHANGE:TICKER` — `TSX:SHOP`, `LON:BP`, `TYO:7203` |

Non-US listings only expose price history and a partial overview; the commands
report that rather than failing.

## The `brief` command

The one to reach for when producing content about an earnings release. One
markdown document containing overview, forecast, statistics, annual and
quarterly income statements, cash flow, segment breakdown, the last N earnings
call transcripts **in full**, filings and company profile.

```bash
python ~/.claude/skills/stockanalysis/scripts/sa.py brief NVDA -n 3 --out nvda-brief.md
```

`-n 2` is the default and transcripts are ordered **oldest first on purpose**:
the substance is in comparing what management guided to last quarter against
what they delivered this quarter. Read the earlier call's *Outlook and guidance*
section, then check it against the later call's reported numbers.

Expect ~170 KB for two transcripts. Use `--out` and read the file rather than
piping it into the conversation. `--no-transcript-body` keeps the structure and
the site's own call summaries without the full text.

Each transcript also carries the site's pre-digested summary (Executive summary
/ Financial highlights / Outlook and guidance / Segment performance / Risk
factors) — often enough on its own for a script outline.

## Downloading investor documents

`filings` lists them; `download` fetches the actual PDFs. These are the
company's own published materials (hosted by Quartr) — the earnings slide deck,
the press release, the 10-K/10-Q, the proxy.

```bash
# the current quarter's earnings release + deck + report
python .../sa.py download NVDA --latest

# every annual report since 2020, into ./filings/
python .../sa.py download NVDA --type annual_report --since 2020-01-01 --dir filings
```

| Flag | Effect |
|---|---|
| `--latest` | The most recent **earnings** event's documents (skips conference decks) |
| `--type` | `slides`, `earnings_release`, `quarterly_report`, `annual_report`, `proxy`, `press_release`, `registration`. `10-K`/`10-Q`/`8-K` are accepted as aliases |
| `--since YYYY-MM-DD`, `--limit N`, `--event ID` | Narrow the set |
| `--dir`, `--overwrite` | Destination (default `./TICKER-documents`); re-runs skip existing files |

**Pull the 10-Q even when you already have the deck and the transcript.** The
quarterly and annual reports carry disclosures management does not put on a
slide or say out loud. In NVIDIA's Q1 FY2027 the 10-Q was the only source for
customer concentration (three direct customers at 21%, 17% and 16% of total
revenue, against two at 16% and 14% a year earlier), for zero data-center
Hopper shipments to China that quarter, and for non-US-headquartered customers
falling from 42% to 22% of revenue. None of it appeared in the deck or the
call. When the question is about risk or concentration rather than growth, go
to the filing first and grep the extracted text for `Concentration of Revenue`,
`direct customers represented`, and `purchase obligations`.

Note that `--latest` covers only the most recent *earnings* event, so it will
not pick up an off-cycle proxy or an annual report from a prior quarter — ask
for those by `--type`.

Files land as `NVDA_2026-05-20_FY2027-Q1_earnings_release.pdf` — sortable and
self-describing. Downloads stream to a `.part` file and rename on completion, so
an interrupted run never leaves a truncated PDF behind.

Slide decks run 3–17 MB and proxies can exceed 17 MB; `--limit` before bulk
pulls.

### Reading the PDFs you just downloaded

**Text extraction alone will miss about half of a keynote deck.** Investor and
roadshow decks are text-native and scrape cleanly. Keynote decks (GTC, CES,
AGM) are exported with type baked into images: measured on NVIDIA's Aug 2026
set, pages returning under 60 characters were 54% (GTC Oct 2025), 49% (GTC
Taipei 2026), 47% (AGM 2026), 42% (GTC 2026), 36% (CES 2026), against ~10% for
roadshow decks.

Those pages are not empty. They carry the product roadmap, demand-mix charts,
customer and partner rosters, and the diagrams that make the economic argument.
A text-only pass silently drops all of it and gives no signal that it did.

So: extract text first (cheap, and enough for earnings decks), then **audit, and
look at whatever the text missed**. `scripts/decks.py` does all four steps.

```bash
D=~/.claude/skills/stockanalysis/scripts/decks.py

python $D audit  NVDA-documents              # which pages are text-invisible
python $D text   NVDA-documents -o deck-text # one .txt per PDF, page-delimited
python $D sheets NVDA-documents -o deck-img  # 6-up contact sheets to scan
python $D page   NVDA-documents/GTC.pdf 26 -o deck-img   # one page, full res
```

`audit` ends with a list of the decks over 30% invisible — those are the ones
worth rendering. Read the contact sheets to find what matters, then re-render
individual pages at full resolution when a figure needs reading precisely.

`decks.py` needs PyMuPDF (and Pillow for contact sheets); it exits with a
`pip install` hint if they're missing. The `pdf` skill and the Read tool's
`pages` parameter also work — Read needs poppler (`pdftoppm`) on PATH.

## Caching and politeness

Cached under `~/.cache/stockanalysis` with lifetimes matched to how fast each
resource actually changes: 5 min quotes, 15 min overview/news, 6 h financials,
7 d company profile, 30 d transcripts (immutable once published). Requests are
serialised with a ~1.2 s minimum gap and retried with backoff on 429/5xx.

Tune with `SA_MIN_INTERVAL`, `SA_CACHE_DIR`, `SA_TIMEOUT`. `robots.txt` permits
this, but it is a free public site — pull what you need, don't sweep hundreds of
tickers.

## Reading the output correctly

- **Fiscal ≠ calendar year.** NVIDIA's "FY2026" ended January 2026. Every
  financials table prints its fiscal-year span; carry the site's label through
  rather than silently converting.
- **Growth rows are derived, not reported.** The site computes them client-side
  and so does this scraper.
- **Blank cells mean paywalled, not zero.** The free tier caps history at 5
  annual periods / 20 quarters and ~2 forward quarters of estimates; the output
  says how many more exist server-side.
- **Estimates are analyst opinion, not company guidance.** Guidance is in the
  transcript, in management's own words. Don't conflate them.
- **Do not use the `Free cash flow` row in `forecast`.** It is on a different
  basis from the cash flow statement and from management's own figures, and it
  disagrees with both. Measured on AMAT (Aug 2026): `forecast` reported FY2025
  FCF of 3.65B against management's stated $5.7B and a cash-flow-statement
  derivation of 5.70B; Q1 FY2026 468.88M against management's $1B; Q2 FY2026
  **negative** 456.25M against management's +$210M. The sign itself flipped.
  For free cash flow use `financials -s cash-flow` (operating cash flow minus
  capital expenditures) or the transcript. The revenue, EPS, margin and net
  income rows in `forecast` reconcile fine — this trap is specific to FCF.
- **In `metrics`, `0.00` means "not reported under this taxonomy", not zero.**
  Companies re-cut their reporting segments, and the site carries old and new
  rows side by side. NVIDIA split Data Center into Hyperscale and ACIE in Q1
  FY2027: the new rows read `0.00` for the 19 quarters before the change, and
  the retired rows (Gaming, Automotive, ProViz) read `0.00` for the quarter
  after it. Neither is a real zero. When a segment series has a wall of `0.00`
  at one end, check the latest transcript for a segment change before
  interpreting — and look for a restated history, which companies usually
  publish alongside it (NVIDIA put nine restated quarters in its roadshow deck,
  not in any data feed).
- The `financials` and `statistics` numbers come from Fiscal.ai and S&P Global
  Market Intelligence respectively; transcripts and filings from Quartr. Quotes
  may be delayed — every command prints an as-of timestamp.
- Quote transcripts accurately and attribute the speaker. Don't sharpen vague
  guidance into a precise number.
- Present the numbers; don't give buy/sell recommendations or personalized
  investment advice.

## Failure modes

- `not found: no stockanalysis.com page for 'X'` — bad ticker, or a non-US
  listing needing the `EXCHANGE:TICKER` form.
- `_not available for this symbol_` inside a brief — the site genuinely has no
  such tab for it (checked against the payload's own feature manifest, so no
  wasted requests).
- A section empties out across every ticker — the site changed its data model.
  `references/endpoints.md` documents where each field comes from and how to
  re-derive the map; `sa.py raw PATH` dumps any page's payload for inspection.

## Files

- `scripts/sa.py` — CLI
- `scripts/sa_core.py` — devalue decoder, throttled fetcher, cache, URL resolution
- `scripts/sa_pages.py` — per-page extractors and markdown renderers
- `scripts/decks.py` — read downloaded PDFs: `audit` / `text` / `sheets` / `page`
- `references/endpoints.md` — full endpoint map, payload shapes, known quirks
