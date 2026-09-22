"""Technical indicators from OHLCV. Pure functions, stdlib only.

No installed skill computes these, so they are written here rather than reused.
Every indicator that finviz also publishes is cross-checked against its snapshot
value at collection time — a divergence beyond tolerance is a bug in this file,
not a rounding difference.

Conventions: series are lists aligned to the input bars, oldest first, with
`None` padding where the window has not filled yet.
"""

from __future__ import annotations

import math


def sma(values, window):
    out, running = [], 0.0
    for i, value in enumerate(values):
        running += value
        if i >= window:
            running -= values[i - window]
        out.append(running / window if i >= window - 1 else None)
    return out


def ema(values, window):
    """Standard EMA seeded with the first `window` simple average."""
    if len(values) < window:
        return [None] * len(values)
    k = 2.0 / (window + 1)
    out = [None] * (window - 1)
    current = sum(values[:window]) / window
    out.append(current)
    for value in values[window:]:
        current = value * k + current * (1 - k)
        out.append(current)
    return out


def rsi(values, window=14):
    """Wilder's RSI — the smoothing finviz and every charting package use.

    A simple-average RSI drifts several points away from the published figure,
    which is why the collector cross-checks this against finviz's `RSI (14)`.
    """
    if len(values) <= window:
        return [None] * len(values)
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    out = [None] * len(values)
    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window

    def level(gain, loss):
        if loss == 0:
            return 100.0
        rs = gain / loss
        return 100.0 - (100.0 / (1.0 + rs))

    out[window] = level(avg_gain, avg_loss)
    for i in range(window, len(gains)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window
        out[i + 1] = level(avg_gain, avg_loss)
    return out


def macd(values, fast=12, slow=26, signal=9):
    fast_line, slow_line = ema(values, fast), ema(values, slow)
    line = [(f - s) if (f is not None and s is not None) else None
            for f, s in zip(fast_line, slow_line)]
    seed = [v for v in line if v is not None]
    signal_line = [None] * len(line)
    if len(seed) >= signal:
        start = next(i for i, v in enumerate(line) if v is not None)
        smoothed = ema(seed, signal)
        for offset, value in enumerate(smoothed):
            signal_line[start + offset] = value
    histogram = [(m - s) if (m is not None and s is not None) else None
                 for m, s in zip(line, signal_line)]
    return {"macd": line, "signal": signal_line, "histogram": histogram}


def bollinger(values, window=20, mult=2.0):
    middle = sma(values, window)
    upper, lower, width = [], [], []
    for i, mid in enumerate(middle):
        if mid is None:
            upper.append(None); lower.append(None); width.append(None)
            continue
        chunk = values[i - window + 1: i + 1]
        variance = sum((v - mid) ** 2 for v in chunk) / window
        sd = math.sqrt(variance)
        upper.append(mid + mult * sd)
        lower.append(mid - mult * sd)
        width.append((2 * mult * sd / mid) if mid else None)
    return {"middle": middle, "upper": upper, "lower": lower, "width": width}


def realised_vol(values, window=20, annualise=True):
    """Annualised standard deviation of daily log returns."""
    returns = [None]
    for i in range(1, len(values)):
        prior = values[i - 1]
        returns.append(math.log(values[i] / prior) if prior > 0 else None)
    out = []
    for i in range(len(values)):
        chunk = [r for r in returns[max(0, i - window + 1): i + 1] if r is not None]
        if len(chunk) < window // 2:
            out.append(None)
            continue
        mean = sum(chunk) / len(chunk)
        sd = math.sqrt(sum((r - mean) ** 2 for r in chunk) / max(len(chunk) - 1, 1))
        out.append(sd * math.sqrt(252) if annualise else sd)
    return out


def atr(highs, lows, closes, window=14):
    if len(closes) < 2:
        return [None] * len(closes)
    true_range = [None]
    for i in range(1, len(closes)):
        true_range.append(max(highs[i] - lows[i],
                              abs(highs[i] - closes[i - 1]),
                              abs(lows[i] - closes[i - 1])))
    out = [None] * len(closes)
    valid = [t for t in true_range if t is not None]
    if len(valid) < window:
        return out
    current = sum(valid[:window]) / window
    out[window] = current
    for i in range(window + 1, len(closes)):
        current = (current * (window - 1) + true_range[i]) / window
        out[i] = current
    return out


def drawdown_from_high(values, lookback=252):
    """Distance below the trailing high, as a negative fraction."""
    out = []
    for i in range(len(values)):
        window = values[max(0, i - lookback + 1): i + 1]
        peak = max(window)
        out.append(values[i] / peak - 1.0 if peak else None)
    return out


def crosses(fast_series, slow_series, dates, lookback=260):
    """Golden/death crosses in the recent window, newest first."""
    events = []
    start = max(1, len(dates) - lookback)
    for i in range(start, len(dates)):
        f0, s0 = fast_series[i - 1], slow_series[i - 1]
        f1, s1 = fast_series[i], slow_series[i]
        if None in (f0, s0, f1, s1):
            continue
        if f0 <= s0 and f1 > s1:
            events.append({"date": dates[i], "type": "golden"})
        elif f0 >= s0 and f1 < s1:
            events.append({"date": dates[i], "type": "death"})
    return list(reversed(events))


def summarise(bars):
    """Everything the dashboard needs, from a list of {date,open,high,low,close,volume}.

    Returns both the latest reading of each indicator and the series behind it,
    so the page can print a number and draw the line from the same computation.
    """
    if len(bars) < 60:
        return None
    dates = [b["date"] for b in bars]
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    volumes = [b.get("volume") or 0 for b in bars]

    sma20, sma50, sma200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    rsi14 = rsi(closes, 14)
    macd_set = macd(closes)
    bands = bollinger(closes)
    vol20 = realised_vol(closes, 20)
    atr14 = atr(highs, lows, closes, 14)
    dd = drawdown_from_high(closes)
    last = len(closes) - 1
    price = closes[last]

    def pct_from(series):
        value = series[last]
        return (price / value - 1.0) if value else None

    window52 = closes[-252:] if len(closes) >= 252 else closes
    high52, low52 = max(window52), min(window52)
    avg_volume = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else None

    # Stack: price above both averages, and the 50 above the 200, is the
    # textbook uptrend. Reported as a count so the scorecard can use it.
    stack = sum([
        1 if sma50[last] and price > sma50[last] else 0,
        1 if sma200[last] and price > sma200[last] else 0,
        1 if (sma50[last] and sma200[last] and sma50[last] > sma200[last]) else 0,
    ])

    return {
        "as_of": dates[last],
        "price": price,
        "latest": {
            "sma20": sma20[last], "sma50": sma50[last], "sma200": sma200[last],
            "pct_from_sma20": pct_from(sma20),
            "pct_from_sma50": pct_from(sma50),
            "pct_from_sma200": pct_from(sma200),
            "rsi14": rsi14[last],
            "macd": macd_set["macd"][last],
            "macd_signal": macd_set["signal"][last],
            "macd_histogram": macd_set["histogram"][last],
            "bollinger_upper": bands["upper"][last],
            "bollinger_lower": bands["lower"][last],
            "bollinger_width": bands["width"][last],
            "realised_vol_20d": vol20[last],
            "atr14": atr14[last],
            "drawdown_from_52w_high": dd[last],
            "high_52w": high52, "low_52w": low52,
            "pct_from_52w_high": price / high52 - 1.0 if high52 else None,
            "pct_above_52w_low": price / low52 - 1.0 if low52 else None,
            "avg_volume_20d": avg_volume,
            "trend_stack": stack,
        },
        "crosses": crosses(sma50, sma200, dates)[:4],
        "series": {
            "dates": dates, "close": closes, "volume": volumes,
            "sma50": sma50, "sma200": sma200,
            "rsi14": rsi14, "macd_histogram": macd_set["histogram"],
        },
    }
