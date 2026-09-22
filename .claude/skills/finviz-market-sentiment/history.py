#!/usr/bin/env python3
"""Append-only log of bullish calls, and the HTML table that displays it.

Only runs that ACTUALLY ISSUED a recommendation are recorded. A bearish or
flat tape writes nothing at all - by design, this is a log of calls made, not
a log of runs performed.

    append   add this run to history.json (silently skips if no recommendation)
    render   turn history.json into a standalone HTML table

A run is keyed by (date, label), so re-running the same slot corrects that
row in place rather than appending a duplicate.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from collections import Counter
from datetime import datetime

from render_artifact import TOKENS

TITLE = "Bullish Call History"
DEFAULT_HISTORY = "history.json"


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def load(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("entries", []) if isinstance(data, dict) else data


def save(path: str, entries: list[dict]) -> None:
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"updated_at": datetime.now().astimezone().isoformat(),
                   "count": len(entries), "entries": entries},
                  fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# --------------------------------------------------------------------------

def cmd_append(args) -> int:
    with open(args.report, encoding="utf-8") as fh:
        report = json.load(fh)

    rec = report.get("recommendation", {}) or {}
    ind = report.get("indicator", {}) or {}

    if not rec.get("issued"):
        print("no recommendation issued - nothing recorded "
              f"({rec.get('reason', 'gate not cleared')})")
        return 0

    picks = rec.get("picks", [])
    if not picks:
        print("recommendation flagged issued but carried no picks - nothing recorded")
        return 0

    stamp = report.get("generated_at", "")
    try:
        dt = datetime.fromisoformat(stamp)
        date_s, time_s = dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    except ValueError:
        date_s, time_s = stamp[:10], stamp[11:16]

    entry = {
        "date": date_s,
        "time": time_s,
        "timestamp": stamp,
        "label": args.label,
        "signal": ind.get("signal"),
        "index": ind.get("index"),
        "conviction": ind.get("conviction"),
        "tickers": [p["ticker"] for p in picks[:3]],
        "names": [p["name"] for p in picks[:3]],
        "themes": sorted({t for p in picks[:3] for t in p.get("matched_themes", [])}),
    }

    entries = load(args.history)
    key = (entry["date"], entry["label"])
    existing = [e for e in entries if (e.get("date"), e.get("label")) == key]
    if existing:
        entries = [e for e in entries if (e.get("date"), e.get("label")) != key]
        print(f"replacing existing {entry['label']} entry for {entry['date']}")
    entries.append(entry)
    save(args.history, entries)

    print(f"recorded {entry['date']} {entry['time']} {entry['label']}: "
          f"{', '.join(entry['tickers'])} (index {entry['index']})")
    return 0


# --------------------------------------------------------------------------

CSS = TOKENS + """
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.mono{font-family:ui-monospace,"SF Mono","Cascadia Mono","Segoe UI Mono",Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums}
.wrap{max-width:56rem;margin:0 auto;padding:1.75rem 1.25rem 4rem;display:flex;flex-direction:column;gap:1.4rem}
.status{display:flex;flex-wrap:wrap;align-items:baseline;gap:.5rem 1rem;
  padding-bottom:.9rem;border-bottom:1px solid var(--rule)}
.status h1{margin:0;font-size:.95rem;font-weight:650;letter-spacing:.01em}
.stamp{margin-left:auto;font-size:.78rem;color:var(--muted)}
.note{font-size:.82rem;color:var(--muted);line-height:1.5;max-width:46rem}

.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.75rem}
.stat{background:var(--card);border:1px solid var(--rule);border-radius:6px;padding:.75rem .9rem;
  display:flex;flex-direction:column;gap:.1rem}
.stat-val{font-size:1.5rem;font-weight:650;line-height:1.15}
.stat-lbl{font-size:.67rem;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);font-weight:650}
.stat-sub{font-size:.72rem;color:var(--muted)}

.scroll{overflow-x:auto;background:var(--card);border:1px solid var(--rule);border-radius:8px;
  box-shadow:var(--shadow)}
table{border-collapse:collapse;width:100%;min-width:34rem}
caption{text-align:left;padding:.85rem 1rem .1rem;font-size:.72rem;letter-spacing:.11em;
  text-transform:uppercase;color:var(--faint);font-weight:650}
th{text-align:left;font-size:.66rem;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);
  font-weight:650;padding:.6rem .7rem;border-bottom:1px solid var(--rule);white-space:nowrap}
th.num,td.num{text-align:right}
td{padding:.6rem .7rem;border-bottom:1px solid var(--rule);font-size:.85rem;vertical-align:middle}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--accent-soft)}
.date{font-weight:600;white-space:nowrap}
.time{color:var(--muted);white-space:nowrap}
.run{font-size:.66rem;font-weight:650;letter-spacing:.07em;text-transform:uppercase;
  padding:.15rem .45rem;border-radius:3px;background:var(--accent-soft);color:var(--accent);
  white-space:nowrap}
.idx{font-weight:650;color:var(--bull);white-space:nowrap}
.tk{font-weight:650;letter-spacing:.01em;white-space:nowrap}
.rank{color:var(--faint);font-size:.7rem;margin-right:.3rem}
.empty{padding:2.5rem 1rem;text-align:center;color:var(--muted);font-size:.88rem}
.freq{display:flex;flex-wrap:wrap;gap:.35rem}
.pill{font-size:.72rem;padding:.2rem .5rem;border-radius:3px;background:var(--accent-soft);
  color:var(--accent);font-weight:600;white-space:nowrap}
.disc{font-size:.75rem;color:var(--faint);line-height:1.55;border-top:1px solid var(--rule);padding-top:1rem}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


def render(entries: list[dict]) -> str:
    P: list[str] = []
    P.append(f"<title>{esc(TITLE)}</title>")
    P.append(f"<style>{CSS}</style>")
    P.append('<div class="wrap">')

    now = datetime.now().astimezone()
    P.append('<div class="status">')
    P.append(f"<h1>{esc(TITLE)}</h1>")
    P.append(f'<span class="stamp mono">updated {esc(now.strftime("%b %d, %Y &middot; %H:%M"))} ET</span>')
    P.append("</div>")

    P.append('<p class="note">Every run that produced a bullish reading, with the three '
             '3&times; funds it pointed to. Runs that came back bearish or flat issue no '
             'recommendation and are deliberately not logged &mdash; so gaps in this table are '
             'either a non-bullish tape or a run that did not happen.</p>')

    if entries:
        tick_counts = Counter(t for e in entries for t in e.get("tickers", []))
        top_counts = Counter(e["tickers"][0] for e in entries if e.get("tickers"))
        dates = sorted({e["date"] for e in entries})
        avg_idx = sum(float(e.get("index") or 0) for e in entries) / len(entries)

        P.append('<div class="summary">')
        P.append('<div class="stat"><span class="stat-lbl">Calls logged</span>'
                 f'<span class="stat-val mono">{len(entries)}</span>'
                 f'<span class="stat-sub">{esc(dates[0])} &rarr; {esc(dates[-1])}</span></div>')
        P.append('<div class="stat"><span class="stat-lbl">Avg index</span>'
                 f'<span class="stat-val mono">{avg_idx:.1f}</span>'
                 '<span class="stat-sub">across logged calls</span></div>')
        most = top_counts.most_common(1)
        P.append('<div class="stat"><span class="stat-lbl">Most often #1</span>'
                 f'<span class="stat-val mono">{esc(most[0][0]) if most else "&mdash;"}</span>'
                 f'<span class="stat-sub">{most[0][1] if most else 0} of {len(entries)} calls</span></div>')
        P.append("</div>")

        P.append('<div><div class="stat-lbl" style="margin-bottom:.45rem">Appearances in any slot</div>'
                 '<div class="freq">')
        for t, c in tick_counts.most_common(12):
            P.append(f'<span class="pill mono">{esc(t)} &times;{c}</span>')
        P.append("</div></div>")

    P.append('<div class="scroll">')
    P.append("<table>")
    P.append("<caption>Newest first</caption>")
    P.append("<thead><tr>"
             "<th>Date</th><th>Time</th><th>Run</th><th class='num'>Index</th>"
             "<th>#1</th><th>#2</th><th>#3</th>"
             "</tr></thead>")
    P.append("<tbody>")
    if not entries:
        P.append('<tr><td colspan="7"><div class="empty">No bullish calls logged yet. '
                 'The first bullish run will appear here.</div></td></tr>')
    for e in entries:
        tk = e.get("tickers", [])
        P.append("<tr>")
        P.append(f'<td class="date mono">{esc(e.get("date"))}</td>')
        P.append(f'<td class="time mono">{esc(e.get("time"))}</td>')
        P.append(f'<td><span class="run">{esc(e.get("label"))}</span></td>')
        idx = e.get("index")
        P.append(f'<td class="num idx mono">{float(idx):.1f}</td>' if idx is not None
                 else '<td class="num">&mdash;</td>')
        for i in range(3):
            if i < len(tk):
                P.append(f'<td class="tk mono"><span class="rank">{i+1}</span>{esc(tk[i])}</td>')
            else:
                P.append('<td class="mono" style="color:var(--faint)">&mdash;</td>')
        P.append("</tr>")
    P.append("</tbody></table></div>")

    P.append('<div class="disc">A record of what the sentiment reading pointed to at the time, '
             'not a performance record &mdash; no entry, exit, or return is tracked here. '
             'Not investment advice. 3&times; leveraged products reset daily and are built for '
             'holding periods measured in hours to days.</div>')
    P.append("</div>")
    return "\n".join(P)


def cmd_render(args) -> int:
    entries = load(args.history)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(render(entries))
    print(f"wrote {args.out} ({len(entries)} entries)")
    return 0


# --------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Bullish-call history log and table.")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("append", help="record this run (skips unless a recommendation was issued)")
    a.add_argument("--report", required=True, help="finviz-sentiment-*.json")
    a.add_argument("--label", required=True, help="'Pre-market' or 'Afternoon'")
    a.add_argument("--history", default=DEFAULT_HISTORY)
    a.set_defaults(func=cmd_append)

    r = sub.add_parser("render", help="render history.json as an HTML table")
    r.add_argument("--history", default=DEFAULT_HISTORY)
    r.add_argument("--out", required=True)
    r.set_defaults(func=cmd_render)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
