#!/usr/bin/env python3
"""Build our own EPS estimate from drivers - structurally blind to consensus.

Every target this dashboard has produced was "our multiple on someone else's earnings
number". That makes the whole exercise a view on the rating and never a view on the
business, and it is the largest remaining gap in the method. This closes it.

HOW THE BLINDING ACTUALLY WORKS, AND WHAT IT CANNOT DO
-----------------------------------------------------
The honest position first: whoever writes a model spec has usually already seen the
consensus number, and no script can unsee it. Claiming a clean-room estimate would be a
lie. What this tool does instead is make anchoring *visible and expensive*:

  1. It refuses to read consensus. `load_bundle_context` strips every forecast field
     before the spec author sees anything, and `main` hard-fails if a spec references
     one. The number cannot leak in through the data path.
  2. EPS is never authored. It is computed from a fixed accounting identity - revenue,
     margin, opex, other income, tax, share count - so there is no field in which to
     type a preferred answer. Moving the output means moving a named driver.
  3. Every driver carries a `source` and a `rationale`, and the build prints them beside
     the arithmetic. An assumption smuggled in to hit a number has to be written down
     next to the guidance it contradicts.

That is procedural blinding, not amnesia, and the reveal step labels it as such.

    python sf_estimate.py build specs/NVDA-FY2028.json          # blind: no consensus loaded
    python sf_estimate.py reveal specs/NVDA-FY2028.json --bundle ./NVDA-bundle

Line types, applied in this fixed order so the build is always an accounting identity:

    revenue      absolute ($m) or growth on a stated base
    gross_margin percent of revenue
    opex         absolute ($m) or growth on a stated base
    other_income absolute ($m), below the operating line (interest, investments)
    tax_rate     percent of pretax income
    shares       diluted share count (millions)

Each carries low / base / high. The three cases are computed independently, so "low" is
a coherent scenario rather than a single driver flexed.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ORDER = ["revenue", "gross_margin", "opex", "other_income", "tax_rate", "shares"]

# Anything matching these is consensus and must never reach a spec author.
FORBIDDEN_KEYS = ("forecast", "price_target", "estimate", "consensus", "analyst",
                  "revision", "epsnext", "epsthis", "headline_estimates")


def load_bundle_context(folder: pathlib.Path) -> dict:
    """Reported history and guidance only. Every forecast field is stripped."""
    bundle = json.loads((folder / "bundle.json").read_text(encoding="utf-8"))
    keep = {
        "ticker": bundle["meta"]["ticker"],
        "name": bundle["meta"].get("name"),
        "price": (bundle.get("quote") or {}).get("price"),
        "shares_outstanding_m": round((bundle.get("quote") or {}).get("shares", 0) / 1e6, 1),
        "reported": {},
    }
    for statement in ("income_annual", "income_quarterly"):
        node = (bundle.get("financials") or {}).get(statement) or {}
        rows = {r["title"]: r.get("values") for r in node.get("rows", [])
                if r.get("title") in ("Revenue", "Gross Profit", "Operating Income",
                                      "Net Income", "EPS (Diluted)", "Gross Margin",
                                      "Operating Margin",
                                      "Shares Outstanding (Diluted)", "Free Cash Flow")}
        keep["reported"][statement] = {
            "periods": [p.get("label") for p in node.get("periods", [])],
            "rows": rows,
        }
    return keep


def _collect_keys(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(str(k).lower())
            _collect_keys(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_keys(v, out)


def _assert_blind(spec: dict) -> None:
    """Reject consensus *data*, not the word "estimate" appearing in a rationale.

    An earlier version scanned the whole serialised spec and tripped on prose - a driver
    explaining that one quarter "is estimated" is exactly the kind of disclosure this tool
    wants, not a leak. The check now looks at structural keys, and separately at whether a
    source cites a broker rather than a filing, a call or a reported figure.
    """
    keys = set()
    _collect_keys(spec, keys)
    hits = sorted(k for k in keys if any(f in k for f in FORBIDDEN_KEYS))
    cited = [l.get("id") for l in spec.get("lines", [])
             if any(w in str(l.get("source", "")).lower()
                    for w in ("consensus", "analysts expect", "street expects", "broker"))]
    if cited:
        raise SystemExit(
            "drivers " + ", ".join(map(str, cited)) + " cite a consensus source - restate them "
            "from the filing, the call, or reported history.")
    if hits:
        raise SystemExit(
            "spec references consensus-shaped fields " + ", ".join(hits) +
            " - the estimate must be built from reported results, management guidance and "
            "market conditions only. Remove them and restate the driver from its source.")


def _line(spec: dict, line_id: str) -> dict | None:
    for line in spec.get("lines", []):
        if line.get("id") == line_id:
            return line
    return None


def _value(line: dict, case: str) -> float:
    if line is None:
        return 0.0
    if case in line:
        return float(line[case])
    return float(line.get("base", 0.0))


def compute(spec: dict, case: str) -> dict:
    """Run the accounting identity for one scenario."""
    rev_line = _line(spec, "revenue")
    if rev_line is None:
        raise SystemExit("spec has no revenue line")

    if rev_line.get("type") == "growth":
        base = float(rev_line["base_value"])
        revenue = base * (1 + _value(rev_line, case))
    else:
        revenue = _value(rev_line, case)

    gm_line = _line(spec, "gross_margin")
    gross_margin = _value(gm_line, case)
    gross_profit = revenue * gross_margin

    opex_line = _line(spec, "opex")
    if opex_line is not None and opex_line.get("type") == "growth":
        opex = float(opex_line["base_value"]) * (1 + _value(opex_line, case))
    else:
        opex = _value(opex_line, case)

    operating_income = gross_profit - opex
    other_income = _value(_line(spec, "other_income"), case)
    pretax = operating_income + other_income
    tax_rate = _value(_line(spec, "tax_rate"), case)
    net_income = pretax * (1 - tax_rate)
    shares = _value(_line(spec, "shares"), case)
    eps = net_income / shares if shares else None

    return {
        "case": case,
        "revenue_m": round(revenue, 1),
        "gross_margin_pct": round(gross_margin * 100, 2),
        "gross_profit_m": round(gross_profit, 1),
        "opex_m": round(opex, 1),
        "operating_income_m": round(operating_income, 1),
        "operating_margin_pct": round(operating_income / revenue * 100, 2) if revenue else None,
        "other_income_m": round(other_income, 1),
        "pretax_m": round(pretax, 1),
        "tax_rate_pct": round(tax_rate * 100, 2),
        "net_income_m": round(net_income, 1),
        "shares_m": round(shares, 1),
        "eps": round(eps, 3) if eps is not None else None,
    }


def build(spec: dict) -> dict:
    _assert_blind(spec)
    out = {
        "ticker": spec["ticker"],
        "period_label": spec["period_label"],
        "period_end": spec.get("period_end"),
        "blind": True,
        "method": spec.get("method"),
        "cases": {c: compute(spec, c) for c in ("low", "base", "high")},
        "drivers": [
            {"id": l["id"], "label": l.get("label", l["id"]), "type": l.get("type", "absolute"),
             "low": l.get("low"), "base": l.get("base"), "high": l.get("high"),
             "base_value": l.get("base_value"),
             "source": l.get("source"), "rationale": l.get("rationale")}
            for l in spec.get("lines", [])
        ],
        "notes": spec.get("notes"),
    }
    return out


def reveal(spec: dict, folder: pathlib.Path) -> dict:
    """Only now is consensus loaded, and only to compare - never to adjust."""
    ours = build(spec)
    bundle = json.loads((folder / "bundle.json").read_text(encoding="utf-8"))
    forecast = bundle.get("forecast") or {}

    street = None
    target_end = spec.get("period_end")
    for row in forecast.get("annual", []) or []:
        if row.get("period_end") == target_end:
            vals = row.get("values") or {}
            street = vals.get("adjustedEps") or vals.get("eps")
            street_n = vals.get("analysts")
            break
    else:
        street_n = None
    if street is None:
        fv = (bundle.get("fair_value") or {}).get("forward") or []
        for row in fv:
            if row.get("end") == target_end:
                street, street_n = row.get("eps"), row.get("analysts")
                break

    base_eps = ours["cases"]["base"]["eps"]
    gap = ((base_eps / street - 1) * 100) if (street and base_eps) else None
    ours["comparison"] = {
        "our_base_eps": base_eps,
        "our_low_eps": ours["cases"]["low"]["eps"],
        "our_high_eps": ours["cases"]["high"]["eps"],
        "street_eps": street,
        "street_analysts": street_n,
        "gap_pct": round(gap, 1) if gap is not None else None,
        "verdict": (None if gap is None else
                    "materially above the street" if gap > 8 else
                    "materially below the street" if gap < -8 else
                    "broadly in line with the street"),
        "blinding_note": (
            "The estimate above was computed before this comparison was run: the build tool "
            "refuses to load any forecast field, and EPS is derived from the accounting "
            "identity rather than entered. That is procedural blinding, not amnesia - whoever "
            "wrote the drivers may well have seen the consensus figure at some earlier point. "
            "The defence against anchoring is that every driver is sourced and printed, so a "
            "number bent to match consensus would have to show up as an assumption that "
            "contradicts its own citation."),
    }
    return ours


def to_markdown(d: dict) -> str:
    L = [f"### {d['ticker']} — our own estimate for {d['period_label']}", ""]
    if d.get("method"):
        L += [d["method"], ""]
    L += ["| Line | Low | Base | High |", "|---|---:|---:|---:|"]
    c = d["cases"]
    rows = [("Revenue ($m)", "revenue_m", "{:,.0f}"),
            ("Gross margin", "gross_margin_pct", "{:.1f}%"),
            ("Operating expense ($m)", "opex_m", "{:,.0f}"),
            ("Operating income ($m)", "operating_income_m", "{:,.0f}"),
            ("Operating margin", "operating_margin_pct", "{:.1f}%"),
            ("Tax rate", "tax_rate_pct", "{:.1f}%"),
            ("Net income ($m)", "net_income_m", "{:,.0f}"),
            ("Diluted shares (m)", "shares_m", "{:,.0f}"),
            ("**EPS**", "eps", "**{:,.2f}**")]
    for label, key, spec in rows:
        L.append(f"| {label} | " + " | ".join(
            spec.format(c[case][key]) if c[case].get(key) is not None else "—"
            for case in ("low", "base", "high")) + " |")
    L += ["", "**Drivers**", ""]
    for drv in d["drivers"]:
        rng = (f"{drv['low']} / {drv['base']} / {drv['high']}"
               if drv.get("low") is not None else str(drv.get("base")))
        L.append(f"- **{drv['label']}** ({drv['type']}): {rng}")
        if drv.get("source"):
            L.append(f"  - source: {drv['source']}")
        if drv.get("rationale"):
            L.append(f"  - {drv['rationale']}")
    if d.get("comparison"):
        k = d["comparison"]
        L += ["", "**Side by side with the street**", "",
              f"- Ours (base): **${k['our_base_eps']:,.2f}** "
              f"(low ${k['our_low_eps']:,.2f} / high ${k['our_high_eps']:,.2f})"]
        if k.get("street_eps"):
            L.append(f"- Street: **${k['street_eps']:,.2f}** "
                     f"on {k.get('street_analysts') or '?'} analysts")
            L.append(f"- Gap: **{k['gap_pct']:+.1f}%** — {k['verdict']}")
        L += ["", f"_{k['blinding_note']}_"]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "reveal", "context"):
        p = sub.add_parser(name)
        p.add_argument("spec" if name != "context" else "bundle")
        if name == "reveal":
            p.add_argument("--bundle", required=True)
        p.add_argument("-f", "--format", choices=("md", "json"), default="md")
        p.add_argument("-o", "--out")
    args = ap.parse_args()

    if args.cmd == "context":
        result = load_bundle_context(pathlib.Path(args.bundle))
        print(json.dumps(result, indent=2))
        return 0

    spec = json.loads(pathlib.Path(args.spec).read_text(encoding="utf-8"))
    result = (build(spec) if args.cmd == "build"
              else reveal(spec, pathlib.Path(args.bundle)))
    text = json.dumps(result, indent=2) if args.format == "json" else to_markdown(result)
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(result, indent=2) if args.out.endswith(".json") else text,
            encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
