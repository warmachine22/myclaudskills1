#!/usr/bin/env python3
"""Print deterministic score and target helpers for a collected bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from analysis_contract import derive_target, scorecard_result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir")
    parser.add_argument("--analysis", help="optional analysis.json for score/target inspection")
    args = parser.parse_args(argv)
    folder = Path(args.bundle_dir)
    bundle = json.loads((folder / "bundle.json").read_text(encoding="utf-8"))
    analysis = {}
    if args.analysis:
        analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
    scorecard = analysis.get("scorecard") or []
    payload = {"score": scorecard_result(scorecard) if scorecard else None}
    if scorecard:
        payload["target"] = derive_target(bundle, scorecard)
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
