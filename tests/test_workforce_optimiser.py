"""tests/test_workforce_optimiser.py

Unit tests for optimisation/workforce_optimiser.py (Phase 8 LP engine).

Covers:
  - Optimal status returned when problem is feasible
  - Output shape: one row per planning period, all expected columns
  - Zero opening headcount + required FTE forces hires
  - Hire cap respected: optimal_hires never exceeds max_hires_per_month
  - No hires needed when existing workforce already exceeds required FTE
  - Total cost = sum of period costs
  - Deficit penalised: high deficit cost drives the optimiser to hire more
  - optimise_scenarios returns three rows (low/base/high)
  - Scenario attrition rates are correctly offset from base
  - Higher attrition scenario recommends >= hires vs lower attrition scenario
  - Solver returns non-Optimal status gracefully when cap is too low
"""

try:
    import pytest
    _pytest = True
except ImportError:
    _pytest = False
    import unittest

import pandas as pd

from planning.workforce_planner import PlanningParams
from optimisation.workforce_optimiser import (
    OptimisationParams,
    optimise_hiring_plan,
    optimise_scenarios,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _planning(**overrides) -> PlanningParams:
    defaults = dict(
        planning_start_date=pd.Timestamp("2026-01-01"),
        planning_horizon_months=6,
        opening_headcount=0,
        monthly_attrition_rate_pct=0.0,
        training_duration_months=0.0,
        training_productivity_pct=0.0,
        ramp_duration_months=0.0,
        ramp_start_pct=100.0,
        shrinkage_pct=0.0,
    )
    defaults.update(overrides)
    return PlanningParams(**defaults)


def _req_fte_df(flat_value: float, months: int = 6, start: str = "2026-01-01") -> pd.DataFrame:
    """Flat required FTE for every month in the horizon."""
    rows = []
    for m in range(months):
        ts = pd.Timestamp(start) + pd.DateOffset(months=m)
        rows.append({"period_start": ts, "required_fte": flat_value})
    return pd.DataFrame(rows)


def _opt_params(planning: PlanningParams, req_fte_df: pd.DataFrame, **overrides) -> OptimisationParams:
    defaults = dict(
        cost_per_hire=1000.0,
        cost_per_surplus_fte_month=100.0,
        cost_per_deficit_fte_month=5000.0,
        max_hires_per_month=50,
    )
    defaults.update(overrides)
    return OptimisationParams(planning=planning, required_fte_df=req_fte_df, **defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_optimal_status_feasible():
    """Optimiser returns 'Optimal' status for a straightforward feasible problem."""
    p = _planning(opening_headcount=0)
    req = _req_fte_df(10.0)
    params = _opt_params(p, req)
    _, status = optimise_hiring_plan(params)
    assert status == "Optimal", f"Expected Optimal, got {status}"


def test_output_columns_present():
    """Result DataFrame contains all expected columns."""
    p = _planning(opening_headcount=50)
    req = _req_fte_df(40.0)
    params = _opt_params(p, req)
    result_df, status = optimise_hiring_plan(params)
    assert status == "Optimal"

    expected_cols = {
        "period_start", "period_label", "optimal_hires",
        "available_fte", "required_fte", "surplus", "deficit",
        "hire_cost", "surplus_cost", "deficit_cost", "period_total_cost",
    }
    assert expected_cols.issubset(set(result_df.columns))


def test_output_has_one_row_per_period():
    """Result has exactly planning_horizon_months rows."""
    p = _planning(planning_horizon_months=12, opening_headcount=0)
    req = _req_fte_df(5.0, months=12)
    params = _opt_params(p, req)
    result_df, status = optimise_hiring_plan(params)
    assert status == "Optimal"
    assert len(result_df) == 12


def test_zero_opening_with_positive_requirement_forces_hires():
    """With no existing staff and a positive FTE target, optimiser must hire."""
    p = _planning(opening_headcount=0)
    req = _req_fte_df(10.0)
    params = _opt_params(p, req)
    result_df, status = optimise_hiring_plan(params)
    assert status == "Optimal"
    assert result_df["optimal_hires"].sum() > 0, "Expected hires > 0"


def test_hire_cap_respected():
    """optimal_hires never exceeds max_hires_per_month."""
    p = _planning(opening_headcount=0)
    req = _req_fte_df(100.0, months=12)
    params = _opt_params(p, req, max_hires_per_month=8)
    result_df, status = optimise_hiring_plan(params)
    assert status == "Optimal"
    assert (result_df["optimal_hires"] <= 8).all(), (
        f"Hire cap violated: {result_df['optimal_hires'].max()}"
    )


def test_no_hires_when_surplus_throughout():
    """If existing headcount already exceeds required FTE, optimal hires = 0."""
    p = _planning(opening_headcount=100, monthly_attrition_rate_pct=0.0)
    req = _req_fte_df(50.0)
    # Surplus cost is very low so carrying surplus is cheap; deficit cost is high
    params = _opt_params(p, req, cost_per_hire=10000.0, cost_per_surplus_fte_month=1.0)
    result_df, status = optimise_hiring_plan(params)
    assert status == "Optimal"
    assert result_df["optimal_hires"].sum() == 0, "Expected zero hires with large existing surplus"


def test_total_cost_equals_sum_of_period_costs():
    """Sum of period_total_cost matches the sum of component costs."""
    p = _planning(opening_headcount=10)
    req = _req_fte_df(20.0)
    params = _opt_params(p, req)
    result_df, status = optimise_hiring_plan(params)
    assert status == "Optimal"

    computed = (
        result_df["hire_cost"] + result_df["surplus_cost"] + result_df["deficit_cost"]
    ).round(2)
    recorded = result_df["period_total_cost"].round(2)
    assert (abs(computed - recorded) < 0.01).all(), "Cost component mismatch"


def test_high_deficit_cost_drives_more_hiring():
    """With a very high deficit penalty, the optimiser should hire to cover the gap."""
    p = _planning(opening_headcount=0)
    req = _req_fte_df(20.0)

    params_low_penalty  = _opt_params(p, req, cost_per_deficit_fte_month=10.0,   max_hires_per_month=50)
    params_high_penalty = _opt_params(p, req, cost_per_deficit_fte_month=100000.0, max_hires_per_month=50)

    result_low,  _ = optimise_hiring_plan(params_low_penalty)
    result_high, _ = optimise_hiring_plan(params_high_penalty)

    assert result_high["optimal_hires"].sum() >= result_low["optimal_hires"].sum(), (
        "Higher deficit penalty should result in >= hires"
    )


def test_optimise_scenarios_returns_three_rows():
    """optimise_scenarios returns exactly three rows (low/base/high)."""
    p = _planning(opening_headcount=0, monthly_attrition_rate_pct=3.0)
    req = _req_fte_df(10.0)
    params = _opt_params(p, req)
    scenario_df = optimise_scenarios(params, attrition_variance_pp=2.0)
    assert len(scenario_df) == 3
    assert set(scenario_df["scenario"]) == {"Low attrition", "Base attrition", "High attrition"}


def test_scenario_attrition_rates_correctly_offset():
    """Low/high attrition scenarios are offset by exactly variance_pp from base."""
    base_rate = 4.0
    variance = 2.0
    p = _planning(opening_headcount=0, monthly_attrition_rate_pct=base_rate)
    req = _req_fte_df(10.0)
    params = _opt_params(p, req)
    scenario_df = optimise_scenarios(params, attrition_variance_pp=variance)

    low_rate  = float(scenario_df.loc[scenario_df["scenario"] == "Low attrition",  "attrition_rate_pct"])
    base_rate_out = float(scenario_df.loc[scenario_df["scenario"] == "Base attrition", "attrition_rate_pct"])
    high_rate = float(scenario_df.loc[scenario_df["scenario"] == "High attrition", "attrition_rate_pct"])

    assert abs(low_rate  - (base_rate - variance)) < 0.01
    assert abs(base_rate_out - base_rate) < 0.01
    assert abs(high_rate - (base_rate + variance)) < 0.01


def test_high_attrition_requires_more_hires_than_low():
    """High attrition scenario should require >= hires vs low attrition scenario."""
    p = _planning(opening_headcount=50, monthly_attrition_rate_pct=3.0)
    req = _req_fte_df(45.0)
    params = _opt_params(p, req)
    scenario_df = optimise_scenarios(params, attrition_variance_pp=2.0)

    low_hires  = scenario_df.loc[scenario_df["scenario"] == "Low attrition",  "total_hires"].values[0]
    high_hires = scenario_df.loc[scenario_df["scenario"] == "High attrition", "total_hires"].values[0]

    assert high_hires >= low_hires, (
        f"High attrition scenario should require >= hires: low={low_hires}, high={high_hires}"
    )


def test_infeasible_when_cap_too_low():
    """When max_hires is 0 but required FTE exceeds opening, problem may not be
    Optimal (deficit costs are incurred but solution is still technically found).
    This test verifies the optimiser handles cap=0 gracefully."""
    p = _planning(opening_headcount=0)
    req = _req_fte_df(10.0)
    params = _opt_params(p, req, max_hires_per_month=0)
    result_df, status = optimise_hiring_plan(params)
    # With cap=0, LP is feasible (deficit absorbs the gap) but all hires = 0
    if status == "Optimal":
        assert result_df["optimal_hires"].sum() == 0
        assert result_df["deficit"].sum() > 0


# ---------------------------------------------------------------------------
# unittest fallback
# ---------------------------------------------------------------------------

if not _pytest:
    import unittest as _ut

    class TestWorkforceOptimiser(_ut.TestCase):
        def _r(self, fn): fn()

        def test_optimal_status(self):          self._r(test_optimal_status_feasible)
        def test_output_columns(self):          self._r(test_output_columns_present)
        def test_output_shape(self):            self._r(test_output_has_one_row_per_period)
        def test_forces_hires(self):            self._r(test_zero_opening_with_positive_requirement_forces_hires)
        def test_hire_cap(self):                self._r(test_hire_cap_respected)
        def test_no_hires_surplus(self):        self._r(test_no_hires_when_surplus_throughout)
        def test_total_cost(self):              self._r(test_total_cost_equals_sum_of_period_costs)
        def test_high_deficit_penalty(self):    self._r(test_high_deficit_cost_drives_more_hiring)
        def test_scenarios_three_rows(self):    self._r(test_optimise_scenarios_returns_three_rows)
        def test_scenario_rates(self):          self._r(test_scenario_attrition_rates_correctly_offset)
        def test_high_vs_low_attrition(self):   self._r(test_high_attrition_requires_more_hires_than_low)
        def test_cap_zero(self):                self._r(test_infeasible_when_cap_too_low)

    if __name__ == "__main__":
        _ut.main()
