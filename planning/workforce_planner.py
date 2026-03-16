"""planning/workforce_planner.py

Phase 7 workforce projection engine.

Operates on a monthly time horizon — separate from the intraday DES layer.
Does NOT import or extend des_runner.py.

Headcount flow per period
-------------------------
  opening_headcount
    - attrition  (floor(opening_hc * monthly_attrition_rate_pct / 100))
    + new_hires  (from hiring plan CSV; 0 if period absent)
  = closing_headcount

Effective FTE
-------------
New hire cohorts are tracked from the month they join.  Each period, every
cohort's months_elapsed is compared against training/ramp thresholds:

  elapsed < training_duration_months
      → in training; contributes training_productivity_pct % FTE

  training_duration_months <= elapsed < training_duration_months + ramp_duration_months
      → in ramp; FTE linearly interpolates from ramp_start_pct % to 100 %

  elapsed >= training_duration_months + ramp_duration_months
      → fully productive; contributes 100 % FTE

  available_fte = effective_fte * (1 - shrinkage_pct / 100)

Known simplification (Phase 7 launch)
--------------------------------------
Attrition is applied proportionally across ALL headcount including agents still
in training or ramp.  Per-cohort or tenure-banded attrition is not modelled.
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd


@dataclass
class PlanningParams:
    """All inputs required by the projection engine.

    Attributes
    ----------
    planning_start_date : pd.Timestamp
        First day of the first planning period.
    planning_horizon_months : int
        Number of monthly periods to project (1–36).
    opening_headcount : int
        Total headcount at the start of period 0.
    monthly_attrition_rate_pct : float
        Percentage of total headcount that leaves each month (e.g. 3.0 → 3 %).
    training_duration_months : float
        How many months a new hire spends in training (0 = no training period).
    training_productivity_pct : float
        FTE contribution (%) during training (0 = invisible, 50 = half-FTE).
    ramp_duration_months : float
        Months of post-training ramp (0 = immediate full productivity).
    ramp_start_pct : float
        FTE % at the first ramp month; linearly increases to 100 %.
    shrinkage_pct : float
        Shrinkage percentage from the operational model (e.g. 35.0 for 35 %).
        Applied to effective_fte to produce available_fte.
    """

    planning_start_date: pd.Timestamp
    planning_horizon_months: int
    opening_headcount: int
    monthly_attrition_rate_pct: float
    training_duration_months: float
    training_productivity_pct: float
    ramp_duration_months: float
    ramp_start_pct: float
    shrinkage_pct: float


def _cohort_contribution(
    size: float,
    elapsed: float,
    params: PlanningParams,
) -> Tuple[float, str]:
    """Return (fte_contribution, state_label) for one cohort at months_elapsed.

    Parameters
    ----------
    size : float
        Current (possibly fractional) headcount of the cohort.
    elapsed : float
        Months since the cohort joined.
    params : PlanningParams

    Returns
    -------
    fte : float
        FTE equivalent contributed by this cohort this period.
    state : str
        One of 'training', 'ramp', 'productive'.
    """
    if elapsed < params.training_duration_months:
        fte = size * (params.training_productivity_pct / 100.0)
        return fte, "training"

    ramp_end = params.training_duration_months + params.ramp_duration_months
    if elapsed < ramp_end:
        if params.ramp_duration_months > 0:
            ramp_progress = (elapsed - params.training_duration_months) / params.ramp_duration_months
        else:
            ramp_progress = 1.0
        pct = params.ramp_start_pct + (100.0 - params.ramp_start_pct) * ramp_progress
        fte = size * (pct / 100.0)
        return fte, "ramp"

    return size, "productive"


def project_workforce(
    params: PlanningParams,
    hiring_plan_df: Optional[pd.DataFrame] = None,
    required_fte_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Generate a monthly workforce headcount and FTE projection.

    Parameters
    ----------
    params : PlanningParams
    hiring_plan_df : DataFrame | None
        Output of load_hiring_plan().  Months not present default to 0 hires.
    required_fte_df : DataFrame | None
        Output of load_required_fte_plan().  Months not present produce NaN
        in the required_fte and surplus_deficit columns.

    Returns
    -------
    DataFrame with one row per planning period and columns:
        period_start, period_label,
        opening_headcount, attrition, new_hires,
        in_training, in_ramp, productive_headcount,
        effective_fte, available_fte,
        required_fte, surplus_deficit,
        closing_headcount
    """
    attrition_rate = params.monthly_attrition_rate_pct / 100.0
    shrinkage = params.shrinkage_pct / 100.0

    # --- Build period-keyed lookups (year, month) → value ---
    hiring_lookup: dict = {}
    if hiring_plan_df is not None and not hiring_plan_df.empty:
        for _, row in hiring_plan_df.iterrows():
            ts = pd.Timestamp(row["period_start"])
            hiring_lookup[(ts.year, ts.month)] = int(row["planned_hires"])

    req_fte_lookup: dict = {}
    if required_fte_df is not None and not required_fte_df.empty:
        for _, row in required_fte_df.iterrows():
            ts = pd.Timestamp(row["period_start"])
            req_fte_lookup[(ts.year, ts.month)] = float(row["required_fte"])

    # --- Initialise cohort state ---
    # Cohorts are stored as mutable [size, months_elapsed] pairs.
    # The existing workforce is treated as one cohort already past all
    # training/ramp thresholds (fully productive from period 0).
    past_all = params.training_duration_months + params.ramp_duration_months + 1.0
    cohorts: List[List[float]] = [[float(params.opening_headcount), past_all]]

    rows = []

    for m in range(params.planning_horizon_months):
        period_ts = params.planning_start_date + pd.DateOffset(months=m)
        period_ts = pd.Timestamp(period_ts)
        period_key = (period_ts.year, period_ts.month)
        period_label = period_ts.strftime("%b %Y")

        # 1. Opening headcount (sum of all surviving cohort members)
        opening_hc = sum(c[0] for c in cohorts)

        # 2. Apply proportional attrition
        attrition_count = math.floor(opening_hc * attrition_rate)
        attrition_count = min(attrition_count, math.floor(opening_hc))  # safety clamp
        if opening_hc > 0 and attrition_count > 0:
            surviving_fraction = max(0.0, 1.0 - (attrition_count / opening_hc))
            for c in cohorts:
                c[0] *= surviving_fraction

        # 3. New hires join at the start of this period (elapsed = 0)
        new_hires = hiring_lookup.get(period_key, 0)
        if new_hires > 0:
            cohorts.append([float(new_hires), 0.0])

        # 4. Compute FTE contributions from all cohorts
        in_training = 0.0
        in_ramp = 0.0
        productive = 0.0
        effective_fte = 0.0

        for c in cohorts:
            size, elapsed = c[0], c[1]
            fte, state = _cohort_contribution(size, elapsed, params)
            effective_fte += fte
            if state == "training":
                in_training += size
            elif state == "ramp":
                in_ramp += size
            else:
                productive += size

        available_fte = effective_fte * (1.0 - shrinkage)

        # 5. Closing headcount
        closing_hc = sum(c[0] for c in cohorts)

        # 6. Required FTE and surplus/deficit
        req_fte = req_fte_lookup.get(period_key, float("nan"))
        if math.isnan(req_fte):
            surplus_deficit = float("nan")
        else:
            surplus_deficit = available_fte - req_fte

        rows.append({
            "period_start":         period_ts,
            "period_label":         period_label,
            "opening_headcount":    int(round(opening_hc)),
            "attrition":            attrition_count,
            "new_hires":            new_hires,
            "in_training":          round(in_training, 1),
            "in_ramp":              round(in_ramp, 1),
            "productive_headcount": round(productive, 1),
            "effective_fte":        round(effective_fte, 1),
            "available_fte":        round(available_fte, 1),
            "required_fte":         round(req_fte, 1) if not math.isnan(req_fte) else float("nan"),
            "surplus_deficit":      round(surplus_deficit, 1) if not math.isnan(surplus_deficit) else float("nan"),
            "closing_headcount":    int(round(closing_hc)),
        })

        # 7. Age all cohorts by one month for the next period
        for c in cohorts:
            c[1] += 1.0

    return pd.DataFrame(rows)
