---
name: yahoo-finance
description: Retrieve stock quotes, historical OHLCV price data, fundamentals, and ticker lookups from Yahoo Finance. Use whenever the user asks for a stock/ETF/index/crypto/FX price, a price chart or historical prices, performance over a period, market cap, P/E, dividend yield, 52-week range, analyst targets, or wants price data exported to CSV/JSON for analysis. Triggers on tickers (AAPL, ^GSPC, BTC-USD, EURUSD=X) or phrases like "how is X trading", "pull X's price history", "compare X and Y returns".
---

# Yahoo Finance data

Fetch market data via `scripts/yf.py`. Requires network access. Uses the
`yfinance` package when installed and silently falls back to Yahoo's public
JSON endpoints (needs only `requests`) otherwise — no API key either way.

## Commands

Run from the skill directory, or use the full path to `scripts/yf.py`.

```bash
python scripts/yf.py quote AAPL MSFT NVDA
python scripts/yf.py history AAPL --period 1y --interval 1d
python scripts/yf.py history AAPL --start 2024-01-01 --end 2025-01-01 --format csv --out aapl.csv
python scripts/yf.py info MSFT
python scripts/yf.py search "vanguard total stock"
```

| Command | Purpose | Key options |
| --- | --- | --- |
| `quote SYM...` | Last price, change, day/52w range, volume, market cap | `--format table\|json\|csv` |
| `history SYM` | OHLCV bars | `--period`, `--interval`, `--start`, `--end`, `--tail N`, `--auto-adjust`, `--format table\|csv\|json`, `--out FILE` |
| `info SYM` | Fundamentals + profile (P/E, margins, analyst target, summary) | `--format table\|json`, `--no-summary` |
| `search QUERY` | Company name -> ticker symbol | `--limit N`, `--format table\|json` |

**`--period`**: `1d 5d 1mo 3mo 6mo 1y 2y 5y 10y ytd max` (ignored when `--start` is given).
**`--interval`**: `1m 2m 5m 15m 30m 60m 90m 1h 1d 5d 1wk 1mo 3mo`.
`--end` is exclusive. `--tail N` keeps the last N rows.

## Symbol formats

| Asset | Example |
| --- | --- |
| US equity / ETF | `AAPL`, `SPY` |
| Index | `^GSPC` (S&P 500), `^DJI`, `^IXIC`, `^VIX` |
| Crypto | `BTC-USD`, `ETH-USD` |
| FX | `EURUSD=X`, `JPY=X` |
| Futures | `CL=F` (crude), `GC=F` (gold) |
| Non-US listing | `SAP.DE`, `7203.T`, `SHOP.TO`, `BP.L` |

Don't guess a ticker — run `search` when the user names a company instead of a symbol.

## Working with the data

- **Multi-symbol comparisons, indicators, returns**: pull each symbol with
  `--format csv --out <file>` into the scratchpad, then analyze with pandas.
  Don't hand-compute across long tables.
- **Adjusted vs raw**: default output is raw OHLC plus an `adj_close` column
  when Yahoo provides one. Use `--auto-adjust` to fold split/dividend
  adjustments into OHLC itself — do this for any multi-year return calculation.
- **Intraday limits**: Yahoo serves `1m` data for ~7 days back and other
  intraday intervals for ~60 days. Longer ranges silently return fewer rows.
- **Long tables**: use `--tail` or write to a file; don't dump thousands of
  rows into the conversation.

## Reporting results

State the price with its currency and the as-of timestamp the tool prints —
quotes may be delayed and reflect the last close when markets are shut. Yahoo
Finance data is unofficial and occasionally has bad ticks; if a number looks
implausible, re-fetch before reporting it.

Present the numbers and let the user draw conclusions. Do not give buy/sell
recommendations or personalized investment advice; Claude is not a licensed
financial advisor.

## Failure modes

- `no data for 'X'` — bad or delisted ticker; try `search`.
- Empty intraday result — market closed and the window predates available
  intraday history; widen `--period` or switch to `1d`.
- Repeated failures across symbols — network/rate limit. Wait a few seconds
  and retry; the script already retries transient errors 3x.
- Missing `yfinance` and `requests` — `pip install yfinance` (pulls in both).
  `info` requires `yfinance` specifically; the other commands don't.
