---
name: earnings-calendar
description: Which companies report earnings on a given day, week or month, with impact stars (1-3), consensus EPS/revenue, actuals, beat/miss and market cap — from tradingeconomics.com/earnings. Use when the user asks what earnings are coming out today/tomorrow/this week/next week/this month, which are the big or important ones, what reported last week and how it went, when a specific company next reports, or wants an earnings schedule filtered by country or market cap.
---

# Earnings calendar (Trading Economics)

Answers "who reports when, and how did it go" from the site's own data — the same
rows the earnings calendar renders, with the star rating it uses to mark market
movers.

**Three stars = the ones that move the market.** For any question about
"important", "big", or "high impact" earnings, filter to `-i 3`.

## Usage

```bash
python ~/.claude/skills/earnings-calendar/scripts/te_earnings.py tomorrow -i 3
```

Markdown by default, grouped by day. `-f json` for structured data, `-f csv` for
a spreadsheet, `-o FILE` to write instead of print.

### The four commands

| Command | What it does |
|---|---|
| `calendar [range]` | The schedule. This is the default — the word `calendar` can be omitted. |
| `company TICKER` | One name's report history, beat/miss per quarter, and its next scheduled date |
| `search NAME` | Find a company's Trading Economics ticker |
| `refresh-ids` / `cache-clear` | Maintenance (see bottom) |

### Ranges

`recent` `today` `tomorrow` `thisweek` `nextweek` `thismonth` `nextmonth`
`yesterday` `prevweek` `prevmonth` — or `--start 2026-08-10 --end 2026-08-20`
for any custom window. Weeks run **Sunday to Saturday**, matching the site.
Default is `thisweek`.

### Calendar options

| Option | Effect |
|---|---|
| `-i, --impact {1,2,3}` | Minimum stars. **`-i 3` = high impact only.** Default 1 (everything). |
| `-g, --group` | `world` (default), `g20`, `america`, `europe`, `asia`, `africa` |
| `-c, --countries` | `us`, `us,de,jp`, `united states`, ISO2/ISO3/names — overrides `--group` |
| `--min-cap 10B` | Drop anything smaller. Good for cutting micro caps out of a long list. |
| `--reported yes\|no` | `yes` = only names that already printed numbers; `no` = still to come |
| `--sort date\|cap\|impact\|surprise` | `cap` = biggest companies first (flat list), `surprise` = biggest EPS beats/misses first |
| `--search TEXT` | Ticker or company-name substring |
| `--limit N` | Cap the output |

### Recipes for the questions that actually get asked

```bash
# What important earnings are coming out this week?
python ~/.claude/skills/earnings-calendar/scripts/te_earnings.py thisweek -i 3

# Which ones are happening tomorrow?
python ~/.claude/skills/earnings-calendar/scripts/te_earnings.py tomorrow -i 3

# US mega caps reporting this month, biggest first
python ~/.claude/skills/earnings-calendar/scripts/te_earnings.py thismonth -i 3 -c us --sort cap

# What happened last week — biggest beats and misses
python ~/.claude/skills/earnings-calendar/scripts/te_earnings.py prevweek -i 3 --reported yes --sort surprise

# When does Nvidia next report, and how has it done?
python ~/.claude/skills/earnings-calendar/scripts/te_earnings.py company NVDA
```

## Reading the output

| Column | Meaning |
|---|---|
| Imp | `***` high / `**` medium / `*` low — Trading Economics' own market-impact rating |
| When | `before open` (AM session), `after close` (PM), or `unspecified` |
| EPS act / est | Reported EPS then consensus. `—` means not reported yet. |
| Rev act / est | Same for revenue |
| vs est | EPS surprise vs consensus. `beat >>est` / `miss <<est` appear when consensus is near zero and the percentage would be meaningless. |
| FQ | Fiscal quarter being reported (`Q2`, `H1`, …), **not** the calendar quarter |

Numbers are in each company's own reporting currency — a Japanese name's EPS is
yen, revenue in `T` is trillions of yen. Market cap is USD. Don't add across
currencies.

Ticker suffixes are exchange codes, not countries in the obvious way:
`:US` United States · `:CN` **Canada** · `:LN` London · `:GR` Germany ·
`:JP` Japan · `:HK` Hong Kong · `:CH` mainland China · `:IN` India ·
`:AU` Australia · `:SW` Switzerland · `:BZ` Brazil · `:FP` France.
`company` accepts a bare ticker and assumes `:US`; pass the full `SHOP:CN` form
for anything else, or run `search` first.

## When answering the user

- Lead with the 3-star names — that is the whole point of the star rating.
- Say what is *estimated* vs what was *reported*: a row with `—` in the actual
  column has not printed yet, and its consensus is an expectation, not a result.
- Consensus in this dataset occasionally mixes GAAP and adjusted EPS, which
  produces an implausible surprise (a "+216% beat"). Flag those as a data
  quirk rather than reporting them as a blowout; `stockanalysis` is the better
  source for a single company's actual quarter.
- For depth on one company after finding it here — transcripts, guidance,
  segment detail — hand off to the `stockanalysis` skill.

## How it works, and being a good citizen

The earnings page is a Next.js app; its data comes from React Server Actions,
which this skill calls directly and gets clean JSON back. No HTML parsing, so a
restyle can't silently corrupt numbers — a real schema change shows up as
missing fields instead of wrong ones.

Responses are cached for 10 minutes in the system temp dir, so repeated
questions in one session cost one request. Use `--refresh` when you specifically
need live numbers on a reporting day. Fetch the window you need in one call
rather than looping day by day; the whole month is a single request. Live
requests are spaced ~2.5s apart on purpose.

Trading Economics sells this data through a paid API. This skill reads the same
public pages a browser does, at browser-like volume — keep it that way: no
scheduled scraping loops, no bulk harvesting.

## Maintenance

Server-action IDs change whenever the site redeploys. The skill detects a stale
ID, re-reads it from the page's JS chunks, and retries automatically — you'll
see `re-discovering ... action IDs` on stderr once, then normal output.
`refresh-ids` forces that by hand.

If it fails outright, the page structure changed. The anchors to re-check in
`scripts/te_earnings.py`:

- Action lookup: `createServerReference)("<40-hex-id>", …, "fetchEarningsAction")`
  inside `https://tradingeconomics.com/_next/static/chunks/*.js`
- Request: `POST /earnings`, header `next-action: <id>`, `Accept: text/x-component`,
  body `[{"startDate":"YYYY-MM-DD","endDate":"YYYY-MM-DD","group":"world"}]`
- Response: React-Flight lines, the payload is the first `N:[ … ]` line that
  parses as a list of objects. A leading `$` in a value is escaped as `$$`.
- Event fields: `date, symbol, name, country, iso2, importance, fiscalReference,
  marketCap, session, eps{actual,forecast,previous}, revenue{…}`

Companion skill: **economic-calendar** for macro releases and central-bank
decisions from the same site.
