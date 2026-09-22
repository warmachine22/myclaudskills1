#!/usr/bin/env python3
"""Email a finviz-sentiment report over Gmail SMTP.

CREDENTIALS ARE NEVER STORED HERE AND NEVER PASSED ON THE COMMAND LINE.
This script reads them from the environment only:

    GMAIL_ADDRESS        the sending Gmail address
    GMAIL_APP_PASSWORD   a Google App Password (NOT the account password)
    SENTIMENT_EMAIL_TO   optional recipient; defaults to GMAIL_ADDRESS

A Google App Password requires 2-Step Verification on the account and is
generated at https://myaccount.google.com/apppasswords . It is a 16-character
token scoped to this one use and revocable at any time without touching the
account password.

Set the variables yourself; nothing else in this repo should ever contain them.
The password is never logged, echoed, or written to disk by this script - it is
read from the environment, handed to smtplib, and dropped.

Use --dry-run to render the email to stdout without credentials or sending.
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # implicit TLS

DISCLAIMER = (
    "News-sentiment read only. No backtest, not calibrated to returns, not "
    "investment advice. 3x products reset daily, decay in chop, and are built "
    "for intraday-to-days holding, not weeks."
)


def _fmt_pick(p: dict) -> list[str]:
    lines = [
        f"  {p['ticker']}  -  {p['name']}",
        f"    score {p['score']:+.3f} | theme sentiment {p['theme_net']:+.2f} | "
        f"confidence {p['confidence']:.2f} | {p['supporting_headlines']} supporting headlines",
        f"    themes: {', '.join(p['matched_themes'])}",
    ]
    if p.get("equivalents"):
        lines.append(f"    same trade: {', '.join(p['equivalents'])}")
    for c in p.get("caveats", []):
        lines.append(f"    ! {c}")
    return lines


def build_email(report: dict, label: str) -> tuple[str, str]:
    ind = report["indicator"]
    agg = report["aggregate"]
    counts = report["counts"]
    rec = report.get("recommendation", {})
    date = report.get("generated_at", "")[:10]

    subject = (f"{label} sentiment {date}: {ind['signal']} "
               f"{ind['index']}/100 ({ind['conviction']})")

    L: list[str] = []
    L.append(f"{label.upper()} MARKET SENTIMENT - {report.get('generated_at','')}")
    L.append("=" * 66)
    L.append("")
    L.append(f"SIGNAL          {ind['signal']}  ({ind['conviction']} conviction)")
    L.append(f"INDEX           {ind['index']}/100   (50 = balanced)")
    L.append(f"NET SENTIMENT   {agg['net_sentiment']:+.3f}  on a -10..+10 scale")
    L.append(f"HORIZON         {ind['horizon']}")
    L.append("")
    L.append(f"Weighted mass:  {agg['bullish_share']:.0%} bullish / "
             f"{agg['bearish_share']:.0%} bearish / {agg['neutral_share']:.0%} neutral")
    L.append(f"Headlines:      {counts['scored']} scored "
             f"({counts['bullish']} bullish, {counts['bearish']} bearish, "
             f"{counts['neutral']} neutral)")

    if counts.get("unscored"):
        L.append("")
        L.append(f"** WARNING: {counts['unscored']} headlines could not be scored and "
                 "were excluded. This reading rests on a partial sample. **")
    if agg.get("tie_break"):
        L.append("")
        L.append(f"** The direction was decided by tie-break ({agg['tie_break']}), not "
                 "by the data. Treat this as NO SIGNAL regardless of the direction "
                 "shown. **")

    L.append("")
    L.append("-" * 66)
    L.append("3X ETF RECOMMENDATION")
    L.append("-" * 66)
    if rec.get("issued"):
        for i, p in enumerate(rec.get("picks", []), 1):
            L.append(f"{i}.")
            L.extend(_fmt_pick(p))
            L.append("")
    else:
        L.append("NO RECOMMENDATION.")
        L.append(f"  {rec.get('reason', 'sentiment did not clear the bullish gate.')}")
        L.append("")

    L.append("-" * 66)
    L.append("TOP BULLISH DRIVERS")
    L.append("-" * 66)
    for h in report.get("top_bullish", [])[:3]:
        L.append(f"  [imp {h['importance']}, sent {h['sentiment']:+d}] {h['headline']}")
    L.append("")
    L.append("-" * 66)
    L.append("TOP BEARISH DRIVERS")
    L.append("-" * 66)
    for h in report.get("top_bearish", [])[:3]:
        L.append(f"  [imp {h['importance']}, sent {h['sentiment']:+d}] {h['headline']}")

    if report.get("narrative"):
        L.append("")
        L.append("-" * 66)
        L.append("READ")
        L.append("-" * 66)
        L.append(report["narrative"])

    L.append("")
    L.append("=" * 66)
    L.append(DISCLAIMER)
    return subject, "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Email a finviz-sentiment report via Gmail SMTP.")
    p.add_argument("--report", required=True, help="the finviz-sentiment-*.json file")
    p.add_argument("--label", default="Market", help="e.g. 'Pre-market' or 'Afternoon'")
    p.add_argument("--to", help="recipient (default: $SENTIMENT_EMAIL_TO, else $GMAIL_ADDRESS)")
    p.add_argument("--dry-run", action="store_true",
                   help="print the email and exit; no credentials needed, nothing sent")
    p.add_argument("--out", help="write the rendered report to this file and exit; "
                                 "no credentials needed, nothing sent")
    args = p.parse_args(argv)

    with open(args.report, encoding="utf-8") as fh:
        report = json.load(fh)
    subject, body = build_email(report, args.label)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(subject + "\n\n" + body + "\n")
        print(f"wrote {args.out}")
        return 0

    if args.dry_run:
        print(f"To:      {args.to or os.environ.get('SENTIMENT_EMAIL_TO') or os.environ.get('GMAIL_ADDRESS') or '(unset)'}")
        print(f"Subject: {subject}")
        print()
        print(body)
        return 0

    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = args.to or os.environ.get("SENTIMENT_EMAIL_TO") or sender

    missing = [n for n, v in [("GMAIL_ADDRESS", sender),
                              ("GMAIL_APP_PASSWORD", password)] if not v]
    if missing:
        sys.exit(
            "error: missing environment variable(s): " + ", ".join(missing) + "\n"
            "  These are read from the environment only and must be set by you.\n"
            "  GMAIL_APP_PASSWORD must be a Google App Password (requires 2-Step\n"
            "  Verification), generated at https://myaccount.google.com/apppasswords\n"
            "  - not your account password. Use --dry-run to preview without them."
        )

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=30) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        # Deliberately does not echo the credential.
        sys.exit(
            "error: Gmail rejected the login.\n"
            "  Check that GMAIL_APP_PASSWORD is a current App Password (16 chars,\n"
            "  2-Step Verification enabled) and that GMAIL_ADDRESS matches the\n"
            "  account it was generated for."
        )
    except Exception as exc:
        sys.exit(f"error: send failed: {type(exc).__name__}: {exc}")

    print(f"sent '{subject}' to {recipient}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
