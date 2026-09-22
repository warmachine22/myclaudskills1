#!/usr/bin/env python3
"""Deterministic half of the finviz market-sentiment indicator.

This script does NO scoring and makes NO API calls. The scoring is done by the
agent (Claude) reading the worklist in-context. The split is:

    prepare    -> emit a numbered worklist + a state file
    (agent scores every line, writes a scores file)
    aggregate  -> weight the scores, decide BUY/SELL, write the report

Everything in `aggregate` is fixed arithmetic: the same scores always produce
the same verdict. The judgment lives entirely in the agent; the decision lives
entirely here. Neither half can quietly do the other's job.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import date as _date, datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Weighting constants - the whole deterministic model lives here
# --------------------------------------------------------------------------

# Importance is raised to this power before weighting, so a 10 counts far more
# than two 5s. 1.0 would make importance purely linear.
IMPORTANCE_EXPONENT = 1.5

# Sentiment decays toward irrelevance for a *24-hour* call; a headline this
# many hours old carries half the weight of one published now.
RECENCY_HALF_LIFE_HOURS = 6.0

# Floor so genuinely major older news never falls out of the index entirely.
MIN_RECENCY_WEIGHT = 0.05

# Headlines shown as a bare date (no clock time) are assumed to be midday ET.
ASSUMED_HOUR_FOR_DATE_ONLY = 12

# Which feed the headline came from. Wire stories are the signal; blogs are
# opinion; finviz's own Market Pulse summaries sit in between.
SECTION_WEIGHTS = {
    "News": 1.00,
    "Market Pulse": 0.85,
    "Stocks News": 0.70,
    "Blogs": 0.65,
}
DEFAULT_SECTION_WEIGHT = 0.75

# Paid-distribution wires carry company-authored copy, not journalism, and are
# dominated by micro-cap promotion. They count, but at half weight.
PROMOTIONAL_SOURCES = {
    "pr newswire", "prnewswire", "globenewswire", "business wire",
    "businesswire", "accesswire", "newsfile", "ein presswire", "prweb",
    "investorshub", "newmediawire", "issuerdirect",
}
PROMOTIONAL_WEIGHT = 0.50

SOCIAL_SOURCES = {"stocktwits"}
SOCIAL_WEIGHT = 0.75

# Conviction bands on the weighted-mean sentiment (which spans -10..+10).
CONVICTION_BANDS = [
    (0.5, "marginal"),
    (1.5, "weak"),
    (3.0, "moderate"),
    (5.0, "strong"),
    (float("inf"), "very strong"),
]

DEFAULT_STATE = "sentiment-state.json"
DEFAULT_WORKLIST = "sentiment-worklist.txt"

# --- 3x ETF recommendation layer ---------------------------------------
# Shrinkage constant: a theme backed by little evidence gets pulled toward
# zero, so one loud headline cannot crown an ETF. Higher = more skeptical.
EVIDENCE_K = 1.0

# A theme needs at least this many distinct scored headlines to be actionable.
MIN_SUPPORTING_HEADLINES = 2

# How many picks to surface.
TOP_N_RECOMMENDATIONS = 3


# --------------------------------------------------------------------------
# Eastern time (matches the finviz-news skill; no tzdata dependency)
# --------------------------------------------------------------------------

def _et_offset_for(naive_utc: datetime) -> timezone:
    y = naive_utc.year

    def nth_sunday(month, n):
        d = _date(y, month, 1)
        d += timedelta(days=(6 - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)

    start = datetime.combine(nth_sunday(3, 2), datetime.min.time()) + timedelta(hours=7)
    end = datetime.combine(nth_sunday(11, 1), datetime.min.time()) + timedelta(hours=6)
    return timezone(timedelta(hours=-4 if start <= naive_utc < end else -5))


def now_eastern() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        return datetime.now(timezone.utc).astimezone(_et_offset_for(utc_now))


def parse_headline_time(item: dict, now: datetime) -> datetime | None:
    """Recover a datetime from a headline, assuming midday for date-only rows."""
    raw = item.get("datetime") or item.get("date")
    if not raw:
        return None
    try:
        if "T" in raw:
            dt = datetime.fromisoformat(raw)
        else:
            d = _date.fromisoformat(raw)
            dt = datetime(d.year, d.month, d.day, ASSUMED_HOUR_FOR_DATE_ONLY)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now.tzinfo)
    return dt


# --------------------------------------------------------------------------
# Deterministic weighting
# --------------------------------------------------------------------------

def recency_weight(item: dict, now: datetime) -> tuple[float, float | None]:
    dt = parse_headline_time(item, now)
    if dt is None:
        return MIN_RECENCY_WEIGHT, None
    age_hours = (now - dt).total_seconds() / 3600.0
    if age_hours <= 0:
        return 1.0, 0.0
    decay = math.exp(-math.log(2) * age_hours / RECENCY_HALF_LIFE_HOURS)
    return max(decay, MIN_RECENCY_WEIGHT), age_hours


def source_weight(item: dict) -> float:
    source = (item.get("source") or "").strip().lower()
    if not source:
        return 1.0
    if source in PROMOTIONAL_SOURCES:
        return PROMOTIONAL_WEIGHT
    if source in SOCIAL_SOURCES:
        return SOCIAL_WEIGHT
    return 1.0


def weigh(item: dict, importance: int, now: datetime) -> dict:
    """Combine the agent's importance score with the fixed structural weights."""
    imp = max(1, min(10, int(importance)))
    imp_w = (imp / 10.0) ** IMPORTANCE_EXPONENT
    rec_w, age = recency_weight(item, now)
    sec_w = SECTION_WEIGHTS.get(item.get("section"), DEFAULT_SECTION_WEIGHT)
    src_w = source_weight(item)
    return {
        "importance_weight": round(imp_w, 5),
        "recency_weight": round(rec_w, 5),
        "section_weight": sec_w,
        "source_weight": src_w,
        "age_hours": round(age, 2) if age is not None else None,
        "weight": round(imp_w * rec_w * sec_w * src_w, 6),
    }


def conviction_for(magnitude: float) -> str:
    for threshold, label in CONVICTION_BANDS:
        if magnitude < threshold:
            return label
    return CONVICTION_BANDS[-1][1]


def decide(scored: list[dict]) -> dict:
    """Turn weighted per-headline scores into one non-neutral directional call.

    net is the weight-weighted mean sentiment, so it stays on the -10..+10
    scale regardless of how many headlines were scored. index maps that onto
    0-100 with 50 as the dead-neutral midpoint.
    """
    total_w = sum(s["weight"] for s in scored)
    if total_w == 0:
        return {
            "signal": "BUY", "index": 50.0, "net_sentiment": 0.0,
            "conviction": "marginal", "tie_break": "no-weighted-headlines",
            "total_weight": 0.0,
            "bullish_share": 0.0, "bearish_share": 0.0, "neutral_share": 0.0,
        }

    raw = sum(s["sentiment"] * s["weight"] for s in scored)
    net = raw / total_w

    bull_w = sum(s["weight"] for s in scored if s["sentiment"] > 0)
    bear_w = sum(s["weight"] for s in scored if s["sentiment"] < 0)
    # Clamp: float subtraction can leave a tiny negative that prints as "-0%".
    neut_w = max(0.0, total_w - bull_w - bear_w)

    # The indicator must resolve to BUY or SELL. Cascade, in order:
    tie_break = None
    if net > 0:
        signal = "BUY"
    elif net < 0:
        signal = "SELL"
    elif bull_w != bear_w:
        signal = "BUY" if bull_w > bear_w else "SELL"
        tie_break = "weighted-breadth"
    else:
        heaviest = max(scored, key=lambda s: (s["weight"], -s["id"]))
        if heaviest["sentiment"] != 0:
            signal = "BUY" if heaviest["sentiment"] > 0 else "SELL"
            tie_break = "heaviest-headline"
        else:
            unweighted = sum(s["sentiment"] for s in scored)
            if unweighted != 0:
                signal = "BUY" if unweighted > 0 else "SELL"
                tie_break = "unweighted-sum"
            else:
                signal = "BUY"
                tie_break = "exhausted-default-buy"

    return {
        "signal": signal,
        "index": round(50 + 5 * net, 2),
        "net_sentiment": round(net, 4),
        "conviction": conviction_for(abs(net)),
        "tie_break": tie_break,
        "total_weight": round(total_w, 4),
        "bullish_share": round(bull_w / total_w, 4),
        "bearish_share": round(bear_w / total_w, 4),
        "neutral_share": round(neut_w / total_w, 4),
    }


# --------------------------------------------------------------------------
# 3x ETF recommendation
# --------------------------------------------------------------------------

def recommend_etfs(scored: list[dict], verdict: dict) -> dict:
    """Rank 3x LONG products against the tagged themes - bullish tape only.

    Hard gate: nothing is recommended unless the aggregate sentiment is
    genuinely positive. A BUY that only exists because a tie-break fired is a
    coin flip, not a bullish read, so it is refused too.
    """
    from etf_universe import (CAVEATS, REJECTED, UNIVERSE, popularity_rank,
                              structure_note)

    if verdict["net_sentiment"] <= 0:
        return {
            "issued": False,
            "reason": f"sentiment is not bullish (net {verdict['net_sentiment']:+.3f}, "
                      f"index {verdict['index']}). No long recommendation is made on a "
                      "flat or negative tape.",
            "picks": [],
        }
    if verdict.get("tie_break"):
        return {
            "issued": False,
            "reason": f"direction was decided by tie-break ({verdict['tie_break']}), "
                      "not by positive sentiment. Treated as no signal.",
            "picks": [],
        }

    # Aggregate weighted sentiment per theme.
    theme_stats: dict[str, dict] = {}
    for s in scored:
        for tag in s.get("themes", []):
            st = theme_stats.setdefault(tag, {"weight": 0.0, "raw": 0.0, "n": 0,
                                              "headlines": []})
            st["weight"] += s["weight"]
            st["raw"] += s["sentiment"] * s["weight"]
            st["n"] += 1
            st["headlines"].append(s)
    for st in theme_stats.values():
        st["net"] = st["raw"] / st["weight"] if st["weight"] else 0.0

    ranked = []
    for ticker, (name, structure, leverage, themes) in UNIVERSE.items():
        matched = [theme_stats[t] for t in themes if t in theme_stats]
        if not matched:
            continue
        weight = sum(m["weight"] for m in matched)
        raw = sum(m["raw"] for m in matched)
        # Distinct headlines, since one story can carry several of an ETF's themes.
        ids = {h["id"] for m in matched for h in m["headlines"]}
        if weight <= 0:
            continue
        theme_net = raw / weight
        confidence = weight / (weight + EVIDENCE_K)
        entry = {
            "ticker": ticker,
            "name": name,
            "structure": structure,
            "leverage": leverage,
            "themes": themes,
            "matched_themes": [t for t in themes if t in theme_stats],
            "supporting_headlines": len(ids),
            "evidence_weight": round(weight, 4),
            "theme_net": round(theme_net, 4),
            "confidence": round(confidence, 4),
            "score": round(theme_net * confidence, 4),
            "eligible": theme_net > 0 and len(ids) >= MIN_SUPPORTING_HEADLINES,
        }
        notes = []
        if structure_note(ticker):
            notes.append(structure_note(ticker))
        if ticker in CAVEATS:
            notes.append(CAVEATS[ticker])
        entry["caveats"] = notes
        # Top supporting headlines, strongest contribution first.
        support = sorted(
            {h["id"]: h for m in matched for h in m["headlines"]}.values(),
            key=lambda h: h["contribution"], reverse=True,
        )
        entry["top_support"] = [
            {"id": h["id"], "headline": h["headline"], "sentiment": h["sentiment"],
             "importance": h["importance"], "contribution": h["contribution"]}
            for h in support[:3]
        ]
        ranked.append(entry)

    ranked.sort(key=lambda e: (e["eligible"], e["score"], -popularity_rank(e["ticker"])),
                reverse=True)

    # Funds mapping to the identical matched-theme set are the same trade
    # (SPXL/UPRO/UDOW all just express "broad_market"). Collapse each group to
    # one representative so the picks are genuinely distinct ideas, and list
    # the rest as equivalents.
    picks, seen_signatures = [], {}
    for e in ranked:
        if not e["eligible"]:
            continue
        sig = frozenset(e["matched_themes"])
        if sig in seen_signatures:
            seen_signatures[sig]["equivalents"].append(e["ticker"])
            continue
        e["equivalents"] = []
        seen_signatures[sig] = e
        picks.append(e)
        if len(picks) >= TOP_N_RECOMMENDATIONS:
            break
    # Late-arriving members of an already-selected group still get recorded.
    for e in ranked:
        if not e["eligible"]:
            continue
        sig = frozenset(e["matched_themes"])
        rep = seen_signatures.get(sig)
        if rep is not None and rep is not e and e["ticker"] not in rep["equivalents"]:
            rep["equivalents"].append(e["ticker"])

    return {
        "issued": bool(picks),
        "reason": None if picks else (
            "sentiment is bullish, but no theme cleared the evidence bar "
            f"(needs positive theme sentiment and >= {MIN_SUPPORTING_HEADLINES} "
            "supporting headlines)."
        ),
        "gate": {
            "net_sentiment": verdict["net_sentiment"],
            "index": verdict["index"],
            "rule": "long recommendations only when net_sentiment > 0 and no tie-break",
        },
        "method": {
            "theme_net": "weighted mean sentiment of headlines tagged with the ETF's themes",
            "confidence": f"evidence_weight / (evidence_weight + {EVIDENCE_K})",
            "score": "theme_net * confidence",
            "min_supporting_headlines": MIN_SUPPORTING_HEADLINES,
        },
        "picks": picks,
        "ranking": ranked,
        "theme_scores": {
            t: {"net": round(st["net"], 3), "weight": round(st["weight"], 3), "n": st["n"]}
            for t, st in sorted(theme_stats.items(), key=lambda kv: -kv[1]["net"])
        },
        "excluded_from_universe": REJECTED,
    }


# --------------------------------------------------------------------------
# prepare
# --------------------------------------------------------------------------

def load_headlines(input_path: str | None) -> tuple[list[dict], dict]:
    if input_path:
        with open(input_path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("headlines", []), {
            "source_file": input_path,
            "fetched_at": data.get("fetched_at"),
        }

    scraper_dir = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "finviz-news")
    )
    if not os.path.exists(os.path.join(scraper_dir, "scrape_finviz_news.py")):
        sys.exit(
            "error: no --input given and the finviz-news scraper was not found at\n"
            f"  {scraper_dir}\n"
            "Pass --input <finviz-news-YYYY-MM-DD.json> instead."
        )
    sys.path.insert(0, scraper_dir)
    import scrape_finviz_news as scr

    now = scr.now_eastern()
    items, feeds = [], []
    for view in ["1", "6", "3"]:
        try:
            page = scr.fetch(scr.VIEWS[view]["url"])
            found = scr.parse_page(page, view, now)
            items.extend(found)
            feeds.append({"view": view, "count": len(found), "status": "ok"})
        except Exception as exc:
            feeds.append({"view": view, "count": 0, "status": "error", "error": str(exc)})
    items.sort(
        key=lambda x: (x.get("datetime") or "", x.get("headline") or ""), reverse=True
    )
    return items, {"scraped": True, "fetched_at": now.isoformat(), "feeds": feeds}


def cmd_prepare(args) -> int:
    headlines, meta = load_headlines(args.input)
    if not headlines:
        sys.exit("error: no headlines found")

    total = len(headlines)
    if args.limit and args.limit > 0 and total > args.limit:
        meta["dropped_by_limit"] = total - args.limit
        headlines = headlines[:args.limit]

    now = now_eastern()
    state = {
        "prepared_at": now.isoformat(),
        "timezone": "America/New_York",
        "input": meta,
        "total_available": total,
        "headlines": headlines,
    }
    with open(args.state, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)

    lines = [
        f"# {len(headlines)} headlines to score (of {total} available)",
        f"# prepared {now.isoformat()}",
        "# columns: id | section | source | time | headline | tickers",
        "# score EVERY id. write lines of: <id> <importance 1-10> <sentiment -10..10> [note]",
        "",
    ]
    for i, x in enumerate(headlines):
        lines.append(
            " | ".join([
                str(i),
                (x.get("section") or "-"),
                (x.get("source") or "-"),
                (x.get("time") or x.get("date") or "-"),
                (x.get("headline") or "").replace("\n", " "),
                ",".join(x.get("tickers", [])[:4]),
            ])
        )
    with open(args.worklist, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    if not args.quiet:
        print(f"prepared {len(headlines)} headlines (of {total} available)",
              file=sys.stderr)
        print(f"  worklist -> {args.worklist}", file=sys.stderr)
        print(f"  state    -> {args.state}", file=sys.stderr)
        print("  next: read the worklist, score every id, then run 'aggregate'",
              file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# aggregate
# --------------------------------------------------------------------------

# <id> <importance> <sentiment> <themes|-> [note]
SCORE_LINE = re.compile(
    r"^\s*(\d+)\s*[|:,\s]\s*(-?\d+)\s*[|:,\s]\s*([+-]?\d+)\s*[|:,\s]\s*"
    r"([A-Za-z_,\-]+)\s*(?:[|:,]\s*)?(.*)$"
)


def split_themes(raw: str) -> list[str]:
    if not raw or raw.strip() in {"-", "none", "_"}:
        return []
    return [t.strip().lower() for t in raw.split(",") if t.strip() and t.strip() != "-"]


def parse_scores(path: str) -> tuple[dict[int, dict], list[str]]:
    """Read `<id> <importance> <sentiment> <themes> [note]` lines, or JSON."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    problems: list[str] = []
    scores: dict[int, dict] = {}

    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(text)
        rows = data.get("scores", data) if isinstance(data, dict) else data
        if isinstance(rows, dict):
            rows = [
                {"id": int(k), **v} if isinstance(v, dict)
                else {"id": int(k), "importance": v[0], "sentiment": v[1]}
                for k, v in rows.items()
            ]
        for r in rows:
            themes = r.get("themes", [])
            if isinstance(themes, str):
                themes = split_themes(themes)
            scores[int(r["id"])] = {
                "importance": int(r["importance"]),
                "sentiment": int(r["sentiment"]),
                "themes": [t.lower() for t in themes],
                "rationale": (r.get("rationale") or "").strip(),
            }
        return scores, problems

    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = SCORE_LINE.match(line)
        if not m:
            problems.append(f"line {lineno}: could not parse {line[:60]!r}")
            continue
        hid, imp, sen = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if hid in scores:
            problems.append(f"line {lineno}: duplicate id {hid} (keeping the first)")
            continue
        scores[hid] = {
            "importance": imp,
            "sentiment": sen,
            "themes": split_themes(m.group(4)),
            "rationale": m.group(5).strip(),
        }
    return scores, problems


def cmd_aggregate(args) -> int:
    if not os.path.exists(args.state):
        sys.exit(f"error: state file not found: {args.state} (run 'prepare' first)")
    with open(args.state, encoding="utf-8") as fh:
        state = json.load(fh)
    headlines = state["headlines"]

    scores, problems = parse_scores(args.scores)

    # Validation: coverage and range. Nothing is silently coerced to neutral.
    unknown = sorted(i for i in scores if i < 0 or i >= len(headlines))
    for i in unknown:
        problems.append(f"id {i} is outside the prepared range 0..{len(headlines)-1}; dropped")
        del scores[i]
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from etf_universe import validate_themes

    for i, s in scores.items():
        bad_tags = validate_themes(s.get("themes", []))
        if bad_tags:
            problems.append(f"id {i}: unknown theme tag(s) {bad_tags}; ignored")
            s["themes"] = [t for t in s["themes"] if t not in bad_tags]
        if not 1 <= s["importance"] <= 10:
            problems.append(f"id {i}: importance {s['importance']} out of 1..10; clamped")
            s["importance"] = max(1, min(10, s["importance"]))
        if not -10 <= s["sentiment"] <= 10:
            problems.append(f"id {i}: sentiment {s['sentiment']} out of -10..10; clamped")
            s["sentiment"] = max(-10, min(10, s["sentiment"]))

    missing = [i for i in range(len(headlines)) if i not in scores]
    if missing and args.strict:
        sys.exit(
            f"error: {len(missing)} of {len(headlines)} headlines are unscored "
            f"(ids {missing[:15]}{'...' if len(missing) > 15 else ''}).\n"
            "Score them, or re-run without --strict to exclude them."
        )

    now = now_eastern()
    scored = []
    for i, item in enumerate(headlines):
        s = scores.get(i)
        if s is None:
            continue
        w = weigh(item, s["importance"], now)
        entry = {
            "id": i,
            "headline": item.get("headline"),
            "url": item.get("url"),
            "source": item.get("source"),
            "tickers": item.get("tickers", []),
            "section": item.get("section"),
            "date": item.get("date"),
            "time": item.get("time"),
            "importance": s["importance"],
            "sentiment": s["sentiment"],
            "themes": s.get("themes", []),
            "rationale": s["rationale"],
        }
        entry.update(w)
        entry["contribution"] = round(s["sentiment"] * w["weight"], 5)
        scored.append(entry)

    if not scored:
        sys.exit("error: no headlines were scored")

    verdict = decide(scored)
    recommendation = recommend_etfs(scored, verdict)
    by_impact = sorted(scored, key=lambda s: abs(s["contribution"]), reverse=True)

    payload = {
        "generated_at": now.isoformat(),
        "timezone": "America/New_York",
        "scored_by": "agent-inline (no API call)",
        "prepared_at": state.get("prepared_at"),
        "indicator": {
            "signal": verdict["signal"],
            "index": verdict["index"],
            "conviction": verdict["conviction"],
            "horizon": "next 24 hours",
            "scale": "0-100, 50 = perfectly balanced; >50 leans buy, <50 leans sell",
        },
        "aggregate": verdict,
        "recommendation": recommendation,
        "weighting": {
            "formula": "weight = (importance/10)^E * recency * section * source; "
                       "net = sum(sentiment*weight)/sum(weight); index = 50 + 5*net",
            "importance_exponent": IMPORTANCE_EXPONENT,
            "recency_half_life_hours": RECENCY_HALF_LIFE_HOURS,
            "min_recency_weight": MIN_RECENCY_WEIGHT,
            "section_weights": SECTION_WEIGHTS,
            "promotional_weight": PROMOTIONAL_WEIGHT,
            "social_weight": SOCIAL_WEIGHT,
        },
        "counts": {
            "headlines_prepared": len(headlines),
            "scored": len(scored),
            "unscored": len(missing),
            "bullish": sum(1 for s in scored if s["sentiment"] > 0),
            "bearish": sum(1 for s in scored if s["sentiment"] < 0),
            "neutral": sum(1 for s in scored if s["sentiment"] == 0),
        },
        "validation": {
            "problems": problems,
            "unscored_ids": missing,
        },
        "top_bearish": [s for s in by_impact if s["sentiment"] < 0][:10],
        "top_bullish": [s for s in by_impact if s["sentiment"] > 0][:10],
        "headlines": scored,
        "input": state.get("input", {}),
    }

    out_path = args.out or f"finviz-sentiment-{now.date().isoformat()}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    if not args.quiet:
        c = payload["counts"]
        print()
        print(f"  SIGNAL: {verdict['signal']}  ({verdict['conviction']} conviction)")
        print(f"  index {verdict['index']}/100   net sentiment {verdict['net_sentiment']:+.2f}")
        print(f"  weighted mass: {verdict['bullish_share']:.0%} bullish / "
              f"{verdict['bearish_share']:.0%} bearish / {verdict['neutral_share']:.0%} neutral")
        print(f"  scored {c['scored']}/{c['headlines_prepared']} "
              f"({c['bullish']} bullish, {c['bearish']} bearish, {c['neutral']} neutral)")
        if verdict["tie_break"]:
            print(f"  tie-break applied: {verdict['tie_break']}")
        if missing:
            print(f"  WARNING: {len(missing)} headlines unscored, excluded from the index")
        for p in problems[:10]:
            print(f"  ! {p}")
        if len(problems) > 10:
            print(f"  ! ...and {len(problems) - 10} more validation problems")
        print()
        print("  TOP BULLISH")
        for s in [x for x in by_impact if x["sentiment"] > 0][:5]:
            print(f"    {s['contribution']:+6.2f}  imp{s['importance']:<3d} "
                  f"sent{s['sentiment']:+3d}  {s['headline'][:66]}")
        print("  TOP BEARISH")
        for s in [x for x in by_impact if x["sentiment"] < 0][:5]:
            print(f"    {s['contribution']:+6.2f}  imp{s['importance']:<3d} "
                  f"sent{s['sentiment']:+3d}  {s['headline'][:66]}")
        print()
        if recommendation["issued"]:
            print("  3X RECOMMENDATION (bullish tape)")
            for n, e in enumerate(recommendation["picks"], 1):
                print(f"    {n}. {e['ticker']:<5} {e['name']}")
                print(f"       score {e['score']:+.3f}  theme_net {e['theme_net']:+.2f}"
                      f"  conf {e['confidence']:.2f}"
                      f"  support {e['supporting_headlines']} headlines"
                      f"  [{', '.join(e['matched_themes'])}]")
                if e.get("equivalents"):
                    print(f"       = same trade: {', '.join(e['equivalents'])}")
                for cav in e["caveats"]:
                    print(f"       ! {cav}")
        else:
            print("  NO 3X RECOMMENDATION")
            print(f"    {recommendation['reason']}")
        print()
        print(f"  wrote {out_path}")
    return 0


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Finviz market sentiment: prepare a worklist, then aggregate agent scores."
    )
    sub = p.add_subparsers(dest="command", required=True)

    pre = sub.add_parser("prepare", help="scrape/load headlines and emit a worklist")
    pre.add_argument("--input", help="existing finviz-news JSON (default: scrape fresh)")
    pre.add_argument("--limit", type=int, default=120,
                     help="keep only the N most recent headlines (default 120; 0 = all)")
    pre.add_argument("--worklist", default=DEFAULT_WORKLIST)
    pre.add_argument("--state", default=DEFAULT_STATE)
    pre.add_argument("--quiet", action="store_true")
    pre.set_defaults(func=cmd_prepare)

    agg = sub.add_parser("aggregate", help="weight agent scores into a BUY/SELL call")
    agg.add_argument("--scores", required=True,
                     help="file of '<id> <importance> <sentiment> [note]' lines, or JSON")
    agg.add_argument("--state", default=DEFAULT_STATE)
    agg.add_argument("--out", help="output path (default finviz-sentiment-<date>.json)")
    agg.add_argument("--strict", action="store_true",
                     help="fail if any prepared headline is unscored")
    agg.add_argument("--quiet", action="store_true")
    agg.set_defaults(func=cmd_aggregate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
