---
name: economic-calendar
description: Scheduled economic data releases and central-bank events — CPI, jobs/payrolls, jobless claims, GDP, PMIs, Fed/ECB/BoE decisions, bond auctions, market holidays — with impact stars (1-3), actual vs consensus vs previous, from tradingeconomics.com/calendar. Use when the user asks what economic data or reports are out today/tomorrow/this week/next month, which are high impact, when the next Fed decision or CPI print is, what the jobs number came in at, or wants the macro calendar for a country or category.
---

# Economic calendar (Trading Economics)

Answers "what macro data is out when, and what did it print" from the site's own
rendered table — the same rows a human sees, with the star rating that marks
market-moving releases.

**Three stars = the market movers** (payrolls, CPI, Fed decisions). For any
question about "important" or "high impact" data, filter to `-i 3`.

## Usage

```bash
python ~/.claude/skills/economic-calendar/scripts/te_calendar.py thisweek -i 3
```

Markdown by default, grouped by day. `-f json` for structured data, `-f csv` for
a spreadsheet, `-o FILE` to write instead of print.

### Ranges

`recent` `today` `tomorrow` `thisweek` `nextweek` `thismonth` `nextmonth`
`yesterday` `prevweek` `prevmonth` — or `--start 2026-08-10 --end 2026-08-20`
for any custom window. Weeks run **Sunday to Saturday**, matching the site.
Default is `thisweek`.

### Options

| Option | Effect |
|---|---|
| `-i, --impact {1,2,3}` | Minimum stars. **`-i 3` = high impact only.** Default 1 (everything — a week is ~200 rows, so filter or `--limit` for readability). |
| `-c, --countries` | `us`, `us,de,jp`, `united states`, ISO2/ISO3/names, or a group: `g20`, `major`, `us`, `americas`, `europe`, `asia`, `world` |
| `--category` | `interest-rate` `inflation` `labour` `gdp` `trade` `government` `business` `consumer` `housing` `bonds` `energy` `holidays` (aliases: `rates`, `cpi`, `jobs`, `pmi`, `auctions`, …) |
| `--tz` | Timezone for the Time column: `ET` (default), `UTC`, `London`, `Berlin`, `Tokyo`, `India`, … or raw minutes like `-240` |
| `--search TEXT` | Match event name, country or category — e.g. `--search "jobless"` |
| `--limit N` | Cap the output |

### Recipes for the questions that actually get asked

```bash
# What high-impact data is out this week?
python ~/.claude/skills/economic-calendar/scripts/te_calendar.py thisweek -i 3

# What's happening tomorrow in the US?
python ~/.claude/skills/economic-calendar/scripts/te_calendar.py tomorrow -c us

# Next central-bank decisions
python ~/.claude/skills/economic-calendar/scripts/te_calendar.py nextmonth --category interest-rate -i 2

# Jobless claims — every print in the last month
python ~/.claude/skills/economic-calendar/scripts/te_calendar.py prevmonth -c us --search "jobless"

# What did last week's data actually come in at?
python ~/.claude/skills/economic-calendar/scripts/te_calendar.py prevweek -i 3

# Which markets are closed over the holidays?
python ~/.claude/skills/economic-calendar/scripts/te_calendar.py nextmonth --category holidays
```

### Country scope, and what the default covers

With no `-c`, you get the site's own default selection — roughly 20 major
economies (US, euro area and its big members, UK, Japan, China, Canada,
Australia, Brazil, Mexico, Turkey…). That is where essentially every 3-star
event lives, so it is the right default for "what matters this week".

Pass `-c world` when the question is about a smaller economy — Sweden,
Switzerland, Taiwan, Israel, Philippines and ~230 others only appear then. A
week is ~200 rows on the default scope and ~370 on `world`.

## Reading the output

| Column | Meaning |
|---|---|
| Time | Release time in the `--tz` timezone (default US Eastern) |
| Imp | `***` high / `**` medium / `*` low — Trading Economics' market-impact rating |
| Event | Indicator name; `(JUL)`, `(Q2)`, `(AUG/07)` is the **reference period** the data covers, not the release date |
| Actual | What printed. Blank means it hasn't been released yet. |
| Consensus | Market expectation (survey median) |
| Previous | Prior period's value, with `rev. from X` when it was revised |
| TE Forecast | Trading Economics' own model forecast — **not** the market consensus. Say which one you're quoting. |

## When answering the user

- Lead with the 3-star rows; everything else is background.
- Distinguish released from scheduled: a blank Actual means the number is still
  ahead, and Consensus is an expectation.
- Actual vs Consensus is the market-relevant comparison. Consensus vs TE
  Forecast is not a surprise — it's two different estimates.
- Times shift with the timezone flag. When the user cares about a US open or a
  specific hour, state the zone you used.

## How it works, and being a good citizen

The calendar page is server-rendered and driven entirely by cookies, so one
plain GET with the right cookie string returns exactly the table the site would
show a human with those filters selected:

| Cookie | Value |
|---|---|
| `cal-custom-range` | `YYYY-MM-DD\|YYYY-MM-DD`, inclusive both ends |
| `calendar-importance` | `1`, `2` or `3` — minimum star level |
| `calendar-countries` | lowercase ISO3, comma separated (`usa,deu`) |
| `cal-timezone-offset` | minutes from UTC (`-240` = UTC-4) |

Category is a URL path (`/calendar/inflation`). Holidays are the exception —
`/calendar/holidays` is empty; they live on `/holidays`, which the script parses
separately and which only covers roughly three months ahead.

Responses are cached for 10 minutes in the system temp dir, so repeated
questions in one session cost one request. Use `--refresh` on a release day when
you need the number the moment it prints. Fetch the window you need in one call
rather than looping day by day.

Live requests are spaced ~2.5s apart. That is deliberate: the site sits behind a
short-lived edge cache that will hand back the *previous* response — different
cookies, same body — when two requests land within about a second. The script
also re-requests if a response contains no dates inside the window it asked for.

Trading Economics sells this data through a paid API. This skill reads the same
public pages a browser does, at browser-like volume — keep it that way: no
scheduled scraping loops, no bulk harvesting.

## Maintenance

The parser is regex-based against server-rendered HTML. If a run returns zero
events for a window that clearly has some, the markup changed. Anchors to
re-check in `scripts/te_calendar.py`:

- Table: `<table id="calendar" …>`; rows start at `<tr data-url=`
- Row attributes: `data-id`, `data-country`, `data-category`, `data-event`,
  `data-symbol`
- Date: `class=' YYYY-MM-DD'` on the first cell
- Impact **and** time: `<span class="event-N calendar-date-S">HH:MM AM</span>`
  where `S` is the star count 1-3
- Country: `class="calendar-iso">XX` and the flag `<div title="Country">`
- Values: `<span id='actual'>`, `<span id='previous'>`, `<a id='consensus'>`,
  `<a id='forecast'>`, and `title='Previous revised from …'`

The site's own range presets (`calendar-range=0..6,-1..-3`) still work but are
fuzzy — "Previous Week" means the last 7 days, "Previous Month" the last 30. The
script uses explicit custom ranges instead so the window is exactly what was
asked for.

Companion skill: **earnings-calendar** for company earnings from the same site.
