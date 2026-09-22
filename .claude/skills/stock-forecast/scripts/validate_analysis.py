#!/usr/bin/env python3
"""Validate an analysis.json payload against the dashboard contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from analysis_contract import scorecard_result, validate_analysis


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis", help="analysis.json path")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
        warnings = validate_analysis(payload)
        result = scorecard_result(payload["scorecard"])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"invalid analysis: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"valid": True, "warnings": warnings, "score": result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
