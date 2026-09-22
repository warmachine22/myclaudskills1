"""Validation and deterministic math for the stock forecast analysis contract.

The model owns the written interpretation. This module owns the invariants that
keep the page honest: score ranges, available-weight normalization, BUY/SELL
mapping, and the bounded target-price blend.
"""

from __future__ import annotations

import math
from typing import Any


# Seven dimensions. Reconciled from two implementations that disagreed:
# one weighted valuation heaviest, the other management execution. Execution now
# carries the larger practical weight of the two qualitative reads, because a
# company's record of doing what it said is the most checkable evidence
# available — but valuation stays first, since it is the single largest
# determinant of forward return. Growth and balance-sheet quality are kept
# separate rather than merged: they fail independently, and merging them hides
# a profitable-but-decelerating business behind a strong balance sheet.
#
# These weights are a judgment, not an empirical result. They are here, in one
# place, so they can be argued with.
DIMENSIONS = (
    ("Valuation vs fair value", 0.22),
    ("Earnings execution and delivery", 0.20),
    ("Growth trajectory", 0.16),
    ("Estimate revisions", 0.15),
    ("Quality and balance sheet", 0.12),
    ("Technical setup", 0.10),
    ("Market and macro backdrop", 0.05),
)
DEFAULT_WEIGHTS = dict(DIMENSIONS)


def _finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def scorecard_result(scorecard: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the normalized composite and evidence coverage.

    Rows marked unavailable are excluded and the remaining weights are
    renormalized. The score is deliberately allowed to be exactly zero; the
    public decision mapping treats zero as SELL so the dashboard never emits a
    neutral rating.
    """
    available = []
    unavailable = []
    expected = set(DEFAULT_WEIGHTS)
    for row in scorecard or []:
        dimension = str(row.get("dimension") or "")
        weight = float(row.get("weight") if row.get("weight") is not None
                       else DEFAULT_WEIGHTS.get(dimension, 0))
        is_unavailable = bool(row.get("unavailable")) or row.get("score") is None
        if is_unavailable:
            unavailable.append(dimension)
            continue
        score = float(row["score"])
        if not _finite_number(score) or score < -2 or score > 2:
            raise ValueError(f"score for '{dimension}' must be between -2 and +2")
        if weight < 0:
            raise ValueError(f"weight for '{dimension}' cannot be negative")
        available.append((dimension, score, weight))

    total_weight = sum(weight for _, _, weight in available)
    composite = (sum(score * weight for _, score, weight in available) / total_weight
                 if total_weight else None)
    expected_available = expected.intersection({d for d, _, _ in available})
    coverage = sum(DEFAULT_WEIGHTS[d] for d in expected_available)
    rating = "BUY" if composite is not None and composite > 0 else "SELL"
    return {
        "composite": composite,
        "rating": rating,
        "available_weight": total_weight,
        "coverage": coverage,
        "available_dimensions": [d for d, _, _ in available],
        "unavailable_dimensions": unavailable,
    }


def target_departure(analysis: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any] | None:
    """How far the model's target sits from the deterministic anchor.

    Departing is allowed and often correct — the anchor is arithmetic, and a
    company mid-re-rating will not be well served by it. Departing *silently* is
    not, so the page shows both numbers and the gap.
    """
    target = analysis.get("target_price") or {}
    value = target.get("value")
    if not _finite_number(value):
        return None
    anchor = derive_target(bundle or {}, analysis.get("scorecard") or [])
    if not anchor.get("available") or not _finite_number(anchor.get("value")):
        return None
    anchor_value = float(anchor["value"])
    if anchor_value <= 0:
        return None
    return {
        "anchor": anchor_value,
        "target": float(value),
        "drift": float(value) / anchor_value - 1.0,
        "method": anchor.get("method"),
        "cross_check": anchor.get("cross_check"),
    }


def validate_analysis(analysis: dict[str, Any],
                      bundle: dict[str, Any] | None = None) -> list[str]:
    """Validate an analysis payload and return non-fatal warnings.

    Raises ValueError for structural or integrity failures. Warnings are
    intentionally returned separately so the renderer can expose them without
    blocking a low-conviction page.

    Passing `bundle` additionally checks the target against the deterministic
    anchor and warns on a large unexplained departure.
    """
    if not isinstance(analysis, dict):
        raise ValueError("analysis.json must contain an object")
    required = ("thesis", "company_explainer", "scorecard", "rating",
                "conviction", "target_price", "section_commentary", "falsifiers")
    missing = [key for key in required if not analysis.get(key)]
    if missing:
        raise ValueError("analysis.json is missing required blocks: " + ", ".join(missing))

    rating = str(analysis["rating"]).strip().upper()
    if rating not in {"BUY", "SELL"}:
        raise ValueError("rating must be BUY or SELL; neutral is not allowed")
    conviction = str(analysis["conviction"]).strip().lower()
    if conviction not in {"high", "medium", "low"}:
        raise ValueError("conviction must be high, medium, or low")

    rows = analysis["scorecard"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("scorecard must be a non-empty list")
    row_map = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("dimension"):
            raise ValueError(f"invalid scorecard row: {row!r}")
        dimension = str(row["dimension"])
        row_map[dimension] = row
        if not row.get("evidence"):
            raise ValueError(f"scorecard row '{dimension}' has no evidence")
        if not row.get("unavailable"):
            if row.get("score") is None or not _finite_number(row.get("score")):
                raise ValueError(f"scorecard row '{dimension}' needs a numeric score")
            if not -2 <= float(row["score"]) <= 2:
                raise ValueError(f"scorecard row '{dimension}' must be between -2 and +2")

    warnings = []
    missing_dimensions = [dimension for dimension, _ in DIMENSIONS if dimension not in row_map]
    if missing_dimensions:
        raise ValueError("scorecard is missing dimensions: " + "; ".join(missing_dimensions))
    result = scorecard_result(rows)
    if result["rating"] != rating:
        warnings.append(
            f"rating {rating} disagrees with weighted score mapping {result['rating']}"
        )
    if result["coverage"] < 0.60:
        warnings.append("less than 60% of the planned evidence weight is available")
    target = analysis["target_price"]
    if not isinstance(target, dict) or not target.get("horizon"):
        raise ValueError("target_price must include a horizon")
    target_value = target.get("value")
    if target_value is not None and (not _finite_number(target_value) or float(target_value) <= 0):
        raise ValueError("target_price.value must be a positive number or null")
    if target_value is None and not (target.get("reason") or target.get("derivation")):
        raise ValueError("an unavailable target needs a reason or derivation")
    if bundle is not None:
        departure = target_departure(analysis, bundle)
        if departure and abs(departure["drift"]) > 0.25:
            words = len(str(target.get("derivation") or "").split())
            if words < 40:
                warnings.append(
                    f"target {departure['target']:.2f} is {departure['drift']:+.0%} from "
                    f"the {departure['anchor']:.2f} anchor with only a brief derivation — "
                    "a departure that large needs its reasoning spelled out")
    if not isinstance(analysis["section_commentary"], dict):
        raise ValueError("section_commentary must be an object")
    if not isinstance(analysis["falsifiers"], list):
        raise ValueError("falsifiers must be a list")
    return warnings


def _first_number(*values: Any) -> float | None:
    for value in values:
        if _finite_number(value) and float(value) > 0:
            return float(value)
    return None


def derive_target(bundle: dict[str, Any], scorecard: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive a deterministic 12-month target *anchor* from collected facts.

    Historical normal-multiple fair value is the anchor; the model's quality
    scores move it by at most 10%.

    **Analyst consensus never moves this number.** It is returned alongside as a
    cross-check so the page can show the gap and the model can explain it, but a
    target that blends in the Street is no longer an independent view — it
    inherits the herd's anchoring, which is the specific thing this dashboard
    exists to avoid. (An earlier revision blended 75/25 with consensus; that was
    removed deliberately.)

    This is an anchor, not a verdict. The model may depart from it and often
    should — a company mid-re-rating, or one whose forward year is not the right
    denominator, will not be well served by arithmetic alone. Departing requires
    stating why, and `validate_analysis` records how far the final number sits
    from this anchor so the page can show both.

    If fair value is refused there is no anchor: the Street target is returned
    explicitly labelled a proxy, and the model must construct its own basis.
    """
    fair = bundle.get("fair_value") or {}
    fv = _first_number(fair.get("fair_value"))
    band = fair.get("band") or []
    if isinstance(band, dict):
        band_low = _first_number(band.get("low"), band.get("bear"))
        band_high = _first_number(band.get("high"), band.get("bull"))
    else:
        band_low = _first_number(band[0]) if len(band) > 0 else None
        band_high = _first_number(band[1]) if len(band) > 1 else None

    forecast = bundle.get("forecast") or {}
    street = forecast.get("price_target") or {}
    street_avg = _first_number(street.get("average"), street.get("mean"), street.get("target"))
    street_low = _first_number(street.get("low"))
    street_high = _first_number(street.get("high"))

    by_dimension = {str(row.get("dimension")): row for row in scorecard or []}
    quality_names = (
        "Earnings execution and delivery",
        "Growth trajectory",
        "Quality and balance sheet",
        "Estimate revisions",
    )
    quality_rows = [
        float(by_dimension[name]["score"])
        for name in quality_names
        if name in by_dimension and not by_dimension[name].get("unavailable")
        and by_dimension[name].get("score") is not None
    ]
    quality_score = sum(quality_rows) / len(quality_rows) if quality_rows else 0.0
    quality_modifier = _clamp(1.0 + 0.05 * quality_score, 0.90, 1.10)

    if fv is not None:
        base = fv * quality_modifier
        bull = max([value for value in (band_high, base) if value is not None])
        bear = min([value for value in (band_low, base) if value is not None])
        gap = ((base / street_avg - 1) if street_avg else None)
        return {
            "available": True,
            "method": "normal-multiple-plus-quality",
            "value": round(base, 2),
            "horizon": "12 months",
            "derivation": (
                f"Normal-multiple fair value {fv:.2f} adjusted by a "
                f"{quality_modifier - 1:+.1%} quality modifier. Analyst consensus "
                + (f"of {street_avg:.2f} is shown as a cross-check "
                   f"({gap:+.0%} versus this anchor) and does not enter the "
                   "calculation." if street_avg else "was unavailable.")
            ),
            "bull": {"value": round(bull, 2), "text": "Upper end of the fair-value band."},
            "bear": {"value": round(bear, 2), "text": "Lower end of the fair-value band."},
            "anchors": {"fair_value": fv, "quality_modifier": round(quality_modifier, 4)},
            "cross_check": {"street_average": street_avg, "street_low": street_low,
                            "street_high": street_high, "gap_vs_anchor": gap},
        }
    if street_avg is not None:
        base = street_avg
        bull = street_high or base * 1.15
        bear = street_low or base * 0.85
        return {
            "available": True,
            "method": "street-target-proxy",
            "value": round(base, 2),
            "horizon": "12 months",
            "derivation": (
                "The historical-multiple engine refused this company; the analyst "
                "consensus target is shown as a clearly labeled low-confidence proxy."
            ),
            "bull": {"value": round(bull, 2), "text": "Upper analyst range or a bounded proxy."},
            "bear": {"value": round(bear, 2), "text": "Lower analyst range or a bounded proxy."},
            "anchors": {"fair_value": None, "street_average": street_avg},
        }
    return {
        "available": False,
        "method": "unavailable",
        "value": None,
        "horizon": "12 months",
        "derivation": "No defensible historical-multiple or analyst target was available.",
        "reason": "The valuation engine refused the name and no reliable analyst target was collected.",
        "bull": None,
        "bear": None,
        "anchors": {"fair_value": None, "street_average": None},
    }
