---
name: finviz-news
description: Scrape stock market headlines from finviz.com news feeds (Market News, Market Pulse, Stocks News) into a dated JSON file. Use when the user asks to pull, grab, scrape, or save finviz headlines/news, wants a JSON dump of current market news, or mentions finviz.com/news.
---

# Finviz news scraper

Pulls headlines from three finviz feeds and writes them to a single JSON file with
resolved dates. Stdlib-only Python, no dependencies.

| View | URL | Feed | What it contains |
|------|-----|------|------------------|
| `1` | `https://finviz.com/news` | Market News | Two tables: **News** (wire stories) and **Blogs** |
| `6` | `https://finviz.com/news?v=6` | Market Pulse | Finviz-generated company summaries, no external links |
| `3` | `https://finviz.com/news?v=3` | Stocks News | Ticker-tagged stories and press releases |

## Usage

Run from the directory where the JSON should land:

```bash
python ~/.claude/skills/finviz-news/scrape_finviz_news.py
```

Writes `finviz-news-YYYY-MM-DD.json` (~370 headlines) and prints a per-feed summary
to stderr.

Options:

- `--out PATH` — output file path
- `--views 1,6,3` — which feeds to scrape (default all three)
- `--dedupe` — collapse identical headlines appearing in more than one feed; the
  survivor gets an `also_in` list
- `--compact` — minified JSON instead of indented
- `--quiet` — no stderr summary

Exit codes: `0` ok, `1` all feeds failed, `2` bad arguments.

## Output shape

```json
{
  "fetched_at": "2026-08-03T03:42:28-04:00",
  "fetched_at_utc": "2026-08-03T07:42:28+00:00",
  "date": "2026-08-03",
  "timezone": "America/New_York",
  "count": 370,
  "feeds": [{"view": "1", "label": "Market News", "url": "...", "status": "ok", "count": 180}],
  "headlines": [
    {
      "headline": "Stocks Rise as Oil Plunge Eases Pressure on Yields: Markets Wrap",
      "url": "https://www.bloomberg.com/news/articles/...",
      "source": "Bloomberg",
      "tickers": [],
      "section": "News",
      "view": "1",
      "feed": "Market News",
      "description": "optional, from the row's hover text",
      "date_raw": "03:35AM",
      "date": "2026-08-03",
      "time": "03:35",
      "datetime": "2026-08-03T03:35:00-04:00"
    }
  ]
}
```

Headlines are sorted newest first. `url` is null for Market Pulse rows (finviz
publishes no link for them); `source` is null there too. `time`/`datetime` carry a
clock time only when the page exposed one — older rows are labelled `Aug-02` with no
time, so they resolve to a date only.

## How dates are resolved

Finviz shows times in US/Eastern and uses four label formats. All are normalised
against the current Eastern time:

- `03:35AM` → today at that time
- `13 min`, `2 hours`, `3 days` → subtracted from now
- `Aug-02` → that calendar date, current year, rolled back a year if the result
  would be in the future (handles the December/January boundary)
- `Yesterday` → now minus one day

Eastern time comes from `zoneinfo`; if the tz database is missing (possible on
Windows without `tzdata`) it falls back to the built-in US DST rule.

## Maintenance notes

The parser is regex-based against finviz's server-rendered HTML. If a run reports
`no-rows-parsed`, the markup changed — fetch the page and re-check these anchors in
`scrape_finviz_news.py`:

- Rows: `<tr class="... news_table-row ...">`
- Date label: the `<td>` with class `news_date-cell`. **View 3 reuses that same
  class on a `<span>` for the source name**, which is why the date regex is
  `<td>`-scoped.
- Headline: `<a class="nn-tab-link">` (views 1 and 3) or
  `<span class="market-pulse-headline">` (view 6)
- Tickers: `data-boxover-ticker="..."`
- Source: the icon sprite id, `icons_news.svg#bloomberg-light` /
  `icons_blogs.svg#zero-hedge-light`; view 3 falls back to the
  `trackAndOpenNews(event, 'PR Newswire', ...)` argument
- View 1's two tables are matched to the "News"/"Blogs" headings by document order

Rows carrying `news_ad-icon-cell` are ad slots with a date but no headline; they are
skipped by design (6 per run on view 1 currently).

A `User-Agent` header is required — finviz rejects the default urllib agent. Fetches
retry three times with backoff.
