"""supply/shrinkage_calculator.py

Phase 6 remainder — observed shrinkage from activity-coded staffing data.

When a staffing CSV includes an `activity` column, this module classifies each
activity as productive or non-productive and computes the observed shrinkage rate
(non-productive staff-intervals / total classifiable staff-intervals).

The result lets users validate or replace the manual "Activity shrinkage %" slider
in the Demand tab with a data-derived figure.

Public API
----------
classify_activity(activity: str) -> str
    Returns "productive", "non_productive", or "unknown".

compute_observed_shrinkage(staffing_df: pd.DataFrame) -> dict
    Returns a summary dict; see docstring for keys.
"""

import pandas as pd

# ── Activity keyword sets ──────────────────────────────────────────────────────
# Matching is case-insensitive substring search (e.g. "on call" matches
# "On Call", "Inbound-OnCall", etc.).  Add synonyms here as needed.

_PRODUCTIVE_KEYWORDS: set = {
    "available",
    "ready",
    "on call",
    "inbound",
    "outbound",
    "handling",
    "talking",
    "busy",
    "logged in",
    "signed in",
    "answering",
    "in call",
}

_NON_PRODUCTIVE_KEYWORDS: set = {
    "break",
    "lunch",
    "morning tea",
    "afternoon tea",
    "tea break",
    "training",
    "meeting",
    "team meeting",
    "coaching",
    "admin",
    "administration",
    "admin time",
    "offline",
    "aux",
    "away",
    "unavailable",
    "wrap",
    "acw",
    "after call work",
    "after-call",
    "bio break",
    "comfort break",
    "system",
    "personal",
    "not ready",
    "not available",
    "1:1",
    "one on one",
    "onboarding",
    "project",
    "email",
    "back office",
}


def classify_activity(activity) -> str:
    """Classify a single activity label.

    Parameters
    ----------
    activity : str or None/NaN
        Raw value from the activity column.

    Returns
    -------
    str
        "productive", "non_productive", or "unknown".
    """
    if activity is None or (isinstance(activity, float) and activity != activity):
        return "unknown"  # NaN check

    norm = str(activity).lower().strip()
    if not norm:
        return "unknown"

    for keyword in _PRODUCTIVE_KEYWORDS:
        if keyword in norm:
            return "productive"

    for keyword in _NON_PRODUCTIVE_KEYWORDS:
        if keyword in norm:
            return "non_productive"

    return "unknown"


def compute_observed_shrinkage(staffing_df: pd.DataFrame) -> dict:
    """Derive observed shrinkage from activity-coded staffing data.

    Expects the staffing DataFrame to follow the canonical schema from
    staffing_loader.py.  The `activity` column may be absent or mostly null
    — both are handled gracefully.

    Shrinkage is weighted by `available_staff` if that column is present,
    so intervals with more agents carry proportionally more weight.

    Parameters
    ----------
    staffing_df : pd.DataFrame
        Canonical staffing DataFrame (output of load_staffing_csv / validate).

    Returns
    -------
    dict with keys:
        has_activity_data : bool
            True if the activity column exists and has at least some non-null values.
        coverage_pct : float
            % of total staff-weight where activity classification is known
            (productive or non_productive, not unknown).  0.0 if no activity data.
        observed_shrinkage_pct : float or None
            Non-productive staff-weight / classifiable staff-weight, expressed as
            a percentage (e.g. 18.5 for 18.5 %).  None if coverage is zero.
        productive_pct : float or None
            % of classifiable staff-weight on productive activities.
        non_productive_pct : float or None
            % of classifiable staff-weight on non-productive activities.
        unknown_pct : float or None
            % of total staff-weight with unknown activity.
        activity_breakdown : pd.DataFrame
            One row per distinct activity value with columns:
            activity, classification, staff_weight, pct_of_total.
            Empty DataFrame if no activity column.
    """
    _EMPTY = {
        "has_activity_data": False,
        "coverage_pct": 0.0,
        "observed_shrinkage_pct": None,
        "productive_pct": None,
        "non_productive_pct": None,
        "unknown_pct": None,
        "activity_breakdown": pd.DataFrame(),
    }

    if "activity" not in staffing_df.columns:
        return _EMPTY

    df = staffing_df.copy()

    # Weight each row by available_staff if present; fall back to 1 per row.
    if "available_staff" in df.columns:
        df["_weight"] = df["available_staff"].fillna(0.0).clip(lower=0.0)
    else:
        df["_weight"] = 1.0

    # Drop rows with zero weight — they contribute nothing.
    df = df[df["_weight"] > 0].copy()

    if df.empty or df["activity"].isna().all():
        return _EMPTY

    df["_classification"] = df["activity"].apply(classify_activity)

    total_weight = df["_weight"].sum()
    if total_weight == 0:
        return _EMPTY

    # Per-classification totals
    by_class = df.groupby("_classification", as_index=False)["_weight"].sum()
    by_class_dict = dict(zip(by_class["_classification"], by_class["_weight"]))

    productive_w    = by_class_dict.get("productive", 0.0)
    non_productive_w = by_class_dict.get("non_productive", 0.0)
    unknown_w       = by_class_dict.get("unknown", 0.0)

    classifiable_w = productive_w + non_productive_w
    coverage_pct = (classifiable_w / total_weight * 100.0) if total_weight > 0 else 0.0

    if classifiable_w > 0:
        observed_shrinkage_pct = non_productive_w / classifiable_w * 100.0
        productive_pct         = productive_w / classifiable_w * 100.0
        non_productive_pct     = non_productive_w / classifiable_w * 100.0
    else:
        observed_shrinkage_pct = None
        productive_pct = None
        non_productive_pct = None

    unknown_pct = (unknown_w / total_weight * 100.0) if total_weight > 0 else None

    # Per-activity breakdown
    breakdown = (
        df.groupby("activity", as_index=False)["_weight"]
        .sum()
        .rename(columns={"_weight": "staff_weight"})
    )
    breakdown["classification"] = breakdown["activity"].apply(classify_activity)
    breakdown["pct_of_total"] = (breakdown["staff_weight"] / total_weight * 100.0).round(1)
    breakdown = breakdown.sort_values("staff_weight", ascending=False).reset_index(drop=True)

    return {
        "has_activity_data": True,
        "coverage_pct": round(coverage_pct, 1),
        "observed_shrinkage_pct": round(observed_shrinkage_pct, 1) if observed_shrinkage_pct is not None else None,
        "productive_pct": round(productive_pct, 1) if productive_pct is not None else None,
        "non_productive_pct": round(non_productive_pct, 1) if non_productive_pct is not None else None,
        "unknown_pct": round(unknown_pct, 1) if unknown_pct is not None else None,
        "activity_breakdown": breakdown[["activity", "classification", "staff_weight", "pct_of_total"]],
    }
