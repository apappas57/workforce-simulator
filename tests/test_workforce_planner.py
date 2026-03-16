"""tests/test_workforce_planner.py

Unit tests for planning/workforce_planner.py (Phase 7 projection engine).

Covers:
  - Stable state (no attrition, no hires)
  - Attrition-only decay
  - Headcount flow identity (closing = opening - attrition + hires)
  - Training pipeline: new hires invisible until training elapses
  - Ramp pipeline: partial FTE during ramp, full after
  - Zero training + zero ramp: new hires immediately productive
  - Shrinkage applied correctly to effective FTE
  - Required FTE and surplus/deficit calculation
  - No hiring plan → new_hires always 0
  - No required FTE → required_fte column is NaN
  - Output shape: one row per planning period
  - Clamp: attrition never drives headcount below zero
"""

try:
    import pytest
    _pytest = True
except ImportError:
    _pytest = False
    import unittest

import math
import pandas as pd

from planning.workforce_planner import PlanningParams, project_workforce


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _params(**overrides) -> PlanningParams:
    """Return a baseline PlanningParams with easy per-test overrides."""
    defaults = dict(
        planning_start_date=pd.Timestamp("2026-01-01"),
        planning_horizon_months=6,
        opening_headcount=100,
        monthly_attrition_rate_pct=0.0,
        training_duration_months=0.0,
        training_productivity_pct=0.0,
        ramp_duration_months=0.0,
        ramp_start_pct=100.0,
        shrinkage_pct=0.0,
    )
    defaults.update(overrides)
    return PlanningParams(**defaults)


def _hiring_df(data: dict) -> pd.DataFrame:
    """Build a minimal hiring_plan DataFrame from {YYYY-MM-DD: hires}."""
    rows = [
        {"period_start": pd.Timestamp(k), "planned_hires": v}
        for k, v in data.items()
    ]
    return pd.DataFrame(rows)


def _req_fte_df(data: dict) -> pd.DataFrame:
    """Build a minimal required_fte_plan DataFrame from {YYYY-MM-DD: fte}."""
    rows = [
        {"period_start": pd.Timestamp(k), "required_fte": float(v)}
        for k, v in data.items()
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_output_shape():
    """One row per planning period, all expected columns present."""
    p = _params(planning_horizon_months=12)
    df = project_workforce(p)
    assert len(df) == 12

    expected_cols = {
        "period_start", "period_label",
        "opening_headcount", "attrition", "new_hires",
        "in_training", "in_ramp", "productive_headcount",
        "effective_fte", "available_fte",
        "required_fte", "surplus_deficit",
        "closing_headcount",
    }
    assert expected_cols.issubset(set(df.columns))


def test_stable_state_no_attrition_no_hires():
    """With zero attrition and zero hires, headcount is constant."""
    p = _params(opening_headcount=80, monthly_attrition_rate_pct=0.0, planning_horizon_months=6)
    df = project_workforce(p)

    assert (df["opening_headcount"] == 80).all()
    assert (df["closing_headcount"] == 80).all()
    assert (df["attrition"] == 0).all()
    assert (df["new_hires"] == 0).all()


def test_stable_state_fte_equals_headcount_no_shrinkage():
    """With no shrinkage, no training, no ramp: effective_fte == headcount."""
    p = _params(opening_headcount=50, shrinkage_pct=0.0)
    df = project_workforce(p)

    for _, row in df.iterrows():
        assert abs(row["effective_fte"] - row["closing_headcount"]) < 0.5


def test_attrition_reduces_headcount():
    """3 % monthly attrition should reduce headcount each period."""
    p = _params(opening_headcount=100, monthly_attrition_rate_pct=3.0, planning_horizon_months=6)
    df = project_workforce(p)

    for i in range(1, len(df)):
        assert df["closing_headcount"].iloc[i] < df["closing_headcount"].iloc[i - 1], (
            f"Headcount did not decrease in period {i}"
        )


def test_headcount_flow_identity():
    """closing_headcount == opening_headcount - attrition + new_hires (within rounding).

    Attrition is continuous (floating-point), so we compare rounded closing
    against the rounded expected value with a tolerance of 1.
    """
    p = _params(
        opening_headcount=100,
        monthly_attrition_rate_pct=5.0,
        planning_horizon_months=6,
    )
    hiring = _hiring_df({"2026-01-01": 10, "2026-03-01": 15})
    df = project_workforce(p, hiring_plan_df=hiring)

    for _, row in df.iterrows():
        # With continuous attrition, attrition is a float; identity holds exactly
        # before rounding so we allow ±1 after int(round(...)) display rounding.
        expected_closing = row["opening_headcount"] - row["attrition"] + row["new_hires"]
        assert abs(row["closing_headcount"] - round(expected_closing)) <= 1, (
            f"Flow identity failed for {row['period_label']}: "
            f"opening={row['opening_headcount']}, attrition={row['attrition']}, "
            f"hires={row['new_hires']}, closing={row['closing_headcount']}"
        )


def test_training_pipeline_new_hires_not_productive_during_training():
    """New hires with 2-month training + 0 ramp should not be in productive until month 2."""
    p = _params(
        opening_headcount=0,
        monthly_attrition_rate_pct=0.0,
        training_duration_months=2.0,
        training_productivity_pct=0.0,
        ramp_duration_months=0.0,
        ramp_start_pct=100.0,
        shrinkage_pct=0.0,
        planning_horizon_months=5,
    )
    hiring = _hiring_df({"2026-01-01": 10})
    df = project_workforce(p, hiring_plan_df=hiring)

    # Month 0 (Jan): 10 hires just joined, elapsed=0, training_duration=2 → in training
    assert df.loc[0, "in_training"] == 10.0
    assert df.loc[0, "productive_headcount"] == 0.0
    assert df.loc[0, "effective_fte"] == 0.0  # training_productivity_pct=0

    # Month 1 (Feb): elapsed=1, still < 2 → still in training
    assert df.loc[1, "in_training"] == 10.0
    assert df.loc[1, "productive_headcount"] == 0.0

    # Month 2 (Mar): elapsed=2, training_duration=2 → graduated → productive (ramp=0)
    assert df.loc[2, "productive_headcount"] == 10.0
    assert df.loc[2, "in_training"] == 0.0
    assert df.loc[2, "effective_fte"] == 10.0


def test_ramp_partial_fte():
    """Agents in ramp contribute partial FTE according to ramp_start_pct."""
    p = _params(
        opening_headcount=0,
        monthly_attrition_rate_pct=0.0,
        training_duration_months=0.0,
        training_productivity_pct=0.0,
        ramp_duration_months=4.0,
        ramp_start_pct=50.0,
        shrinkage_pct=0.0,
        planning_horizon_months=6,
    )
    hiring = _hiring_df({"2026-01-01": 10})
    df = project_workforce(p, hiring_plan_df=hiring)

    # Month 0: elapsed=0, ramp_progress=0 → pct=50% → fte=5
    assert abs(df.loc[0, "effective_fte"] - 5.0) < 0.1
    assert df.loc[0, "in_ramp"] == 10.0

    # Month 1: elapsed=1, ramp_progress=0.25 → pct=50+50*0.25=62.5% → fte=6.25
    assert abs(df.loc[1, "effective_fte"] - 6.25) < 0.1

    # Month 2: elapsed=2, ramp_progress=0.5 → pct=75% → fte=7.5
    assert abs(df.loc[2, "effective_fte"] - 7.5) < 0.1

    # Month 4: elapsed=4 >= ramp_duration → fully productive
    assert df.loc[4, "productive_headcount"] == 10.0
    assert abs(df.loc[4, "effective_fte"] - 10.0) < 0.1


def test_zero_training_zero_ramp_immediately_productive():
    """With training=0 and ramp=0, new hires are fully productive from day one."""
    p = _params(
        opening_headcount=0,
        monthly_attrition_rate_pct=0.0,
        training_duration_months=0.0,
        ramp_duration_months=0.0,
        ramp_start_pct=100.0,
        shrinkage_pct=0.0,
        planning_horizon_months=3,
    )
    hiring = _hiring_df({"2026-01-01": 20})
    df = project_workforce(p, hiring_plan_df=hiring)

    assert df.loc[0, "productive_headcount"] == 20.0
    assert df.loc[0, "effective_fte"] == 20.0
    assert df.loc[0, "in_training"] == 0.0
    assert df.loc[0, "in_ramp"] == 0.0


def test_shrinkage_applied_to_effective_fte():
    """available_fte == effective_fte * (1 - shrinkage/100)."""
    p = _params(
        opening_headcount=100,
        shrinkage_pct=35.0,
        training_duration_months=0.0,
        ramp_duration_months=0.0,
        monthly_attrition_rate_pct=0.0,
        planning_horizon_months=3,
    )
    df = project_workforce(p)

    for _, row in df.iterrows():
        expected = round(row["effective_fte"] * 0.65, 1)
        assert abs(row["available_fte"] - expected) < 0.2, (
            f"available_fte mismatch: got {row['available_fte']}, expected ~{expected}"
        )


def test_required_fte_and_surplus_deficit():
    """surplus_deficit = available_fte - required_fte for matched periods."""
    p = _params(
        opening_headcount=100,
        shrinkage_pct=0.0,
        monthly_attrition_rate_pct=0.0,
        planning_horizon_months=3,
    )
    req = _req_fte_df({"2026-01-01": 80.0, "2026-02-01": 90.0, "2026-03-01": 110.0})
    df = project_workforce(p, required_fte_df=req)

    assert abs(df.loc[0, "required_fte"] - 80.0) < 0.1
    assert abs(df.loc[0, "surplus_deficit"] - (df.loc[0, "available_fte"] - 80.0)) < 0.1

    assert abs(df.loc[2, "required_fte"] - 110.0) < 0.1
    # With 100 headcount and no shrinkage, available_fte ~100 → deficit ~-10
    assert df.loc[2, "surplus_deficit"] < 0


def test_no_hiring_plan_defaults_to_zero():
    """Without a hiring plan, new_hires is 0 for all periods."""
    p = _params(planning_horizon_months=6)
    df = project_workforce(p)
    assert (df["new_hires"] == 0).all()


def test_no_required_fte_columns_are_nan():
    """Without required FTE input, required_fte and surplus_deficit are NaN."""
    p = _params(planning_horizon_months=4)
    df = project_workforce(p)
    assert df["required_fte"].isna().all()
    assert df["surplus_deficit"].isna().all()


def test_period_labels_match_start_dates():
    """period_label should match the strftime of period_start."""
    p = _params(planning_start_date=pd.Timestamp("2026-06-01"), planning_horizon_months=3)
    df = project_workforce(p)

    assert df.loc[0, "period_label"] == "Jun 2026"
    assert df.loc[1, "period_label"] == "Jul 2026"
    assert df.loc[2, "period_label"] == "Aug 2026"


def test_attrition_clamp_no_negative_headcount():
    """Even at 100 % attrition rate, headcount should not go negative."""
    p = _params(
        opening_headcount=10,
        monthly_attrition_rate_pct=100.0,
        planning_horizon_months=3,
    )
    df = project_workforce(p)
    assert (df["closing_headcount"] >= 0).all()


def test_hiring_in_future_period_not_in_earlier_periods():
    """Hires scheduled for March should not appear in January or February."""
    p = _params(
        opening_headcount=50,
        monthly_attrition_rate_pct=0.0,
        planning_horizon_months=4,
    )
    hiring = _hiring_df({"2026-03-01": 20})
    df = project_workforce(p, hiring_plan_df=hiring)

    assert df.loc[0, "new_hires"] == 0  # Jan
    assert df.loc[1, "new_hires"] == 0  # Feb
    assert df.loc[2, "new_hires"] == 20  # Mar
    assert df.loc[3, "new_hires"] == 0  # Apr


# ---------------------------------------------------------------------------
# unittest fallback runner
# ---------------------------------------------------------------------------

if not _pytest:
    import unittest as _ut

    class TestWorkforcePlanner(_ut.TestCase):
        def _run(self, fn):
            fn()

        def test_output_shape(self):               self._run(test_output_shape)
        def test_stable_state(self):               self._run(test_stable_state_no_attrition_no_hires)
        def test_fte_equals_headcount(self):        self._run(test_stable_state_fte_equals_headcount_no_shrinkage)
        def test_attrition(self):                  self._run(test_attrition_reduces_headcount)
        def test_flow_identity(self):              self._run(test_headcount_flow_identity)
        def test_training_pipeline(self):          self._run(test_training_pipeline_new_hires_not_productive_during_training)
        def test_ramp_partial_fte(self):           self._run(test_ramp_partial_fte)
        def test_zero_training_ramp(self):         self._run(test_zero_training_zero_ramp_immediately_productive)
        def test_shrinkage(self):                  self._run(test_shrinkage_applied_to_effective_fte)
        def test_surplus_deficit(self):            self._run(test_required_fte_and_surplus_deficit)
        def test_no_hiring_plan(self):             self._run(test_no_hiring_plan_defaults_to_zero)
        def test_no_req_fte(self):                 self._run(test_no_required_fte_columns_are_nan)
        def test_period_labels(self):              self._run(test_period_labels_match_start_dates)
        def test_attrition_clamp(self):            self._run(test_attrition_clamp_no_negative_headcount)
        def test_future_hires(self):               self._run(test_hiring_in_future_period_not_in_earlier_periods)

    if __name__ == "__main__":
        _ut.main()
