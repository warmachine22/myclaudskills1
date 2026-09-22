#!/usr/bin/env python3
"""What growth does today's price already require?

A forward DCF asks "what is it worth?" and answers with whatever you assumed. A reverse
DCF asks the more useful and much harder-to-fool question: hold the price fixed, and
solve for the growth rate that justifies it. The output is not an opinion about value -
it is a statement about the market's own embedded assumption, which can then be compared
against guidance, consensus, and history.

That comparison is the whole point. If the price requires 25% free-cash-flow growth for
a decade and the company has guided 8%, the market is not "expensive" in the abstract -
it is carrying a specific, falsifiable assumption that can be checked next quarter.

It also fills a real hole. The normal-multiple engine refused or degraded on three of the
first five names this dashboard covered (negative EPS, or a "normal" multiple whose two
window halves differed by 120-495%). A reverse DCF needs no multiple history at all -
only cash flow, a discount rate and a horizon - so it works precisely where the other
method breaks.

    python sf_reverse_dcf.py NVDA --fcf 127006 --shares 24398 --net-cash 20000 \\
        --price 217.55 --beta 2.21

Free inputs only: cash flow from the filings (see sf_edgar.py), the risk-free rate from
the live 10-year Treasury via Yahoo, and an equity risk premium the caller states.
"""

from __future__ import annotations

import argparse
import json
import sys

try:
    import yfinance as yf
except ImportError:
    yf = None


def risk_free_rate() -> tuple[float, str]:
    """Live 10-year Treasury yield; falls back to a stated constant if offline."""
    if yf is not None:
        try:
            hist = yf.Ticker("^TNX").history(period="5d")
            if not hist.empty:
                # ^TNX quotes in tenths of a percent
                return float(hist["Close"].iloc[-1]) / 100.0, "live ^TNX (10-year Treasury)"
        except Exception:
            pass
    return 0.045, "fallback constant - live ^TNX unavailable"


def wacc(beta: float, rf: float, erp: float, debt_weight: float = 0.0,
         cost_of_debt: float = 0.05, tax: float = 0.21) -> float:
    """CAPM cost of equity, blended with after-tax debt where a weight is supplied."""
    coe = rf + beta * erp
    if debt_weight <= 0:
        return coe
    return (1 - debt_weight) * coe + debt_weight * cost_of_debt * (1 - tax)


def implied_value(fcf: float, growth: float, years: int, fade_to: float,
                  discount: float, terminal_growth: float,
                  net_cash: float, shares: float) -> float:
    """Per-share value from an explicit forecast that fades linearly to a terminal rate."""
    pv, cash = 0.0, fcf
    for year in range(1, years + 1):
        # linear fade from the solved rate toward the terminal rate over the horizon
        g = growth + (fade_to - growth) * (year - 1) / max(years - 1, 1)
        cash *= (1 + g)
        pv += cash / ((1 + discount) ** year)
    terminal = cash * (1 + terminal_growth) / (discount - terminal_growth)
    pv += terminal / ((1 + discount) ** years)
    return (pv + net_cash) / shares


def solve_growth(price: float, fcf: float, years: int, discount: float,
                 terminal_growth: float, net_cash: float, shares: float,
                 fade_to: float | None = None) -> float | None:
    """Bisect for the initial growth rate that reproduces the market price."""
    fade = terminal_growth if fade_to is None else fade_to
    lo, hi = -0.60, 2.50
    f = lambda g: implied_value(fcf, g, years, fade, discount, terminal_growth,
                                net_cash, shares) - price
    if f(lo) > 0:
        return None  # price is below even a collapsing business - nothing to solve
    if f(hi) < 0:
        return None  # price requires more than 250% growth; report as unsolvable
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def analyse(price: float, fcf: float, shares: float, beta: float,
            net_cash: float = 0.0, erp: float = 0.05, years: int = 10,
            terminal_growth: float = 0.025, discount_override: float | None = None) -> dict:
    rf, rf_src = risk_free_rate()
    disc = discount_override if discount_override else wacc(beta, rf, erp)
    implied = solve_growth(price, fcf, years, disc, terminal_growth, net_cash, shares)

    out = {
        "ok": implied is not None,
        "price": price,
        "inputs": {
            "fcf_musd": fcf, "shares_m": shares, "net_cash_musd": net_cash,
            "beta": beta, "risk_free_pct": round(rf * 100, 2), "risk_free_source": rf_src,
            "equity_risk_premium_pct": round(erp * 100, 2),
            "discount_rate_pct": round(disc * 100, 2),
            "horizon_years": years, "terminal_growth_pct": round(terminal_growth * 100, 2),
        },
        "implied_growth_pct": round(implied * 100, 1) if implied is not None else None,
        "reading": None,
        "sensitivity": [],
    }
    if implied is None:
        out["error"] = ("no growth rate in [-60%, +250%] reproduces this price - the "
                        "inputs or the discount rate are the problem, not the market")
        return out

    out["reading"] = (
        f"At ${price:,.2f} the market requires free cash flow to compound at "
        f"{implied * 100:.1f}% a year for {years} years, fading to {terminal_growth * 100:.1f}%, "
        f"discounted at {disc * 100:.1f}%.")

    # A single CAPM discount rate can dominate the answer - a 2.2 beta produces a ~16%
    # hurdle that makes almost anything look demanding. Solving the same question across
    # a band of rates separates "the market assumes a lot" from "we assumed a lot".
    out["implied_growth_by_discount"] = []
    for d in (0.08, 0.10, 0.12, disc):
        g = solve_growth(price, fcf, years, d, terminal_growth, net_cash, shares)
        out["implied_growth_by_discount"].append({
            "discount_pct": round(d * 100, 1),
            "implied_growth_pct": round(g * 100, 1) if g is not None else None,
            "label": "CAPM" if abs(d - disc) < 1e-9 else "stated",
        })

    # what the price would be across a grid of growth and discount assumptions
    for g in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
        row = {"growth_pct": round(g * 100, 1), "values": {}}
        for d in (disc - 0.02, disc, disc + 0.02):
            row["values"][f"{d * 100:.1f}%"] = round(
                implied_value(fcf, g, years, terminal_growth, d, terminal_growth,
                              net_cash, shares), 2)
        out["sensitivity"].append(row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ticker", nargs="?", default="")
    ap.add_argument("--price", type=float, required=True)
    ap.add_argument("--fcf", type=float, required=True,
                    help="trailing free cash flow, $m (negative is allowed but unsolvable)")
    ap.add_argument("--shares", type=float, required=True, help="diluted shares, millions")
    ap.add_argument("--net-cash", type=float, default=0.0,
                    help="net cash (negative for net debt), $m")
    ap.add_argument("--beta", type=float, default=1.0)
    ap.add_argument("--erp", type=float, default=5.0, help="equity risk premium, %%")
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--terminal", type=float, default=2.5, help="terminal growth, %%")
    ap.add_argument("--discount", type=float, help="override the computed WACC, %%")
    ap.add_argument("-f", "--format", choices=("md", "json"), default="md")
    args = ap.parse_args()

    if args.fcf <= 0:
        print(json.dumps({"ok": False, "ticker": args.ticker,
                          "error": ("trailing free cash flow is negative or zero, so there is "
                                    "no cash stream to grow. A reverse DCF cannot be run and "
                                    "no number should be invented; use a sales-based method "
                                    "and say so.")}, indent=2))
        return 2

    res = analyse(args.price, args.fcf, args.shares, args.beta, args.net_cash,
                  args.erp / 100, args.years, args.terminal / 100,
                  args.discount / 100 if args.discount else None)
    res["ticker"] = args.ticker.upper()

    if args.format == "json":
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 2

    print(f"### {res['ticker']} — what the price already assumes\n")
    if not res["ok"]:
        print(res.get("error"))
        return 2
    i = res["inputs"]
    print(res["reading"], "\n")
    print(f"- Discount rate **{i['discount_rate_pct']:.1f}%** "
          f"= {i['risk_free_pct']:.2f}% risk-free ({i['risk_free_source']}) "
          f"+ {i['beta']:.2f} beta × {i['equity_risk_premium_pct']:.1f}% ERP")
    print(f"- Starting free cash flow ${i['fcf_musd']:,.0f}m over {i['shares_m']:,.0f}m shares")
    if res.get("implied_growth_by_discount"):
        print("\n**Implied growth at other discount rates**\n")
        print("| Discount rate | Required FCF growth |")
        print("|---|---|")
        for row in res["implied_growth_by_discount"]:
            g = row["implied_growth_pct"]
            tag = " (CAPM)" if row["label"] == "CAPM" else ""
            shown = f"{g:.1f}%" if g is not None else "unsolvable"
            print(f"| {row['discount_pct']:.1f}%{tag} | {shown} |")
    print(f"\n| FCF growth | {' | '.join(res['sensitivity'][0]['values'].keys())} |")
    print("|---|" + "---|" * len(res["sensitivity"][0]["values"]))
    for row in res["sensitivity"]:
        cells = " | ".join(f"${v:,.0f}" for v in row["values"].values())
        print(f"| {row['growth_pct']:.0f}% | {cells} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
