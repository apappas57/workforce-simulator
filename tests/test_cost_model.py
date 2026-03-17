"""tests/test_cost_model.py

Unit tests for models/cost_model.py — Phase 13 cost & financial analytics.

Covers:
  - CostConfig dataclass defaults and custom values
  - calculate_interval_costs(): labour, idle, SLA breach, overstaffing/understaffing
  - calculate_cost_summary(): aggregation and key presence
  - project_monthly_labour_cost(): monthly cost overlay on planning projection
"""

import unittest

import pandas as pd
import numpy as np

from models.cost_model import (
    CostConfig,
    calculate_interval_costs,
    calculate_cost_summary,
    project_monthly_labour_cost,
    _WORKING_HOURS_PER_MONTH,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _erlang_df(n=4, calls=50, sl=0.85, req_agents=10.0):
    """Minimal Erlang C output DataFrame for cost model tests."""
    return pd.DataFrame({
        "interval":                      list(range(n)),
        "calls_offered":                 [float(calls)] * n,
        "erlang_required_net_agents":    [req_agents] * n,
        "erlang_pred_service_level":     [sl] * n,
        "erlang_pred_occupancy":         [0.75] * n,
    })


def _roster_df(n=4, agents=12.0):
    """Minimal roster DataFrame for cost model tests."""
    return pd.DataFrame({
        "interval":          list(range(n)),
        "roster_net_agents": [agents] * n,
    })


def _planning_df():
    return pd.DataFrame({
        "month":         [1, 2, 3],
        "available_fte": [50.0, 52.0, 55.0],
        "required_fte":  [48.0, 51.0, 53.0],
    })


# ---------------------------------------------------------------------------
# CostConfig
# ---------------------------------------------------------------------------

class TestCostConfig(unittest.TestCase):

    def test_default_hourly_rate(self):
        self.assertEqual(CostConfig().hourly_agent_cost, 30.0)

    def test_default_penalty(self):
        self.assertEqual(CostConfig().penalty_per_abandoned, 8.0)

    def test_default_idle_fraction(self):
        self.assertEqual(CostConfig().idle_rate_fraction, 1.0)

    def test_custom_values_preserved(self):
        cfg = CostConfig(hourly_agent_cost=25.0, penalty_per_abandoned=5.0, idle_rate_fraction=0.5)
        self.assertEqual(cfg.hourly_agent_cost, 25.0)
        self.assertEqual(cfg.penalty_per_abandoned, 5.0)
        self.assertEqual(cfg.idle_rate_fraction, 0.5)


# ---------------------------------------------------------------------------
# calculate_interval_costs
# ---------------------------------------------------------------------------

class TestCalculateIntervalCosts(unittest.TestCase):

    def setUp(self):
        self.cfg = CostConfig(hourly_agent_cost=30.0, penalty_per_abandoned=8.0)

    def test_returns_dataframe(self):
        result = calculate_interval_costs(_erlang_df(), self.cfg, 15)
        self.assertIsInstance(result, pd.DataFrame)

    def test_empty_input_returns_empty(self):
        result = calculate_interval_costs(pd.DataFrame(), self.cfg, 15)
        self.assertTrue(result.empty)

    def test_row_count_matches_input(self):
        result = calculate_interval_costs(_erlang_df(n=8), self.cfg, 15)
        self.assertEqual(len(result), 8)

    def test_labour_cost_formula(self):
        """agents * hourly_rate * (interval_min / 60) = labour_cost."""
        # 10 agents * £30/hr * 0.25h = £75.00
        result = calculate_interval_costs(_erlang_df(n=1), self.cfg, 15)
        self.assertAlmostEqual(result["labour_cost"].iloc[0], 75.0, places=2)

    def test_labour_cost_scales_with_interval_duration(self):
        """30-min interval costs exactly double a 15-min interval."""
        r15 = calculate_interval_costs(_erlang_df(n=1), self.cfg, 15)
        r30 = calculate_interval_costs(_erlang_df(n=1), self.cfg, 30)
        self.assertAlmostEqual(r30["labour_cost"].iloc[0], r15["labour_cost"].iloc[0] * 2, places=2)

    def test_no_overstaffing_when_roster_matches_requirement(self):
        """When no roster is provided, rostered == required, so no overstaffing."""
        result = calculate_interval_costs(_erlang_df(), self.cfg, 15)
        self.assertTrue((result["overstaffing"] == 0).all())

    def test_overstaffing_when_roster_exceeds_requirement(self):
        roster = _roster_df(agents=15.0)   # requirement is 10.0
        result = calculate_interval_costs(_erlang_df(), self.cfg, 15, roster_df=roster)
        self.assertTrue((result["overstaffing"] == 5.0).all())

    def test_understaffing_when_roster_below_requirement(self):
        roster = _roster_df(agents=7.0)    # requirement is 10.0
        result = calculate_interval_costs(_erlang_df(), self.cfg, 15, roster_df=roster)
        self.assertTrue((result["understaffing"] == 3.0).all())

    def test_roster_drives_labour_cost(self):
        """When a roster is provided, rostered headcount — not requirement — drives cost."""
        # 15 rostered agents * £30/hr * 0.25h = £112.50
        roster = _roster_df(n=1, agents=15.0)
        result = calculate_interval_costs(_erlang_df(n=1), self.cfg, 15, roster_df=roster)
        self.assertAlmostEqual(result["labour_cost"].iloc[0], 112.5, places=2)

    def test_sla_breach_uses_sl_gap(self):
        """SL=0.80 → 20% abandon rate → abandoned_calls = calls * 0.20."""
        result = calculate_interval_costs(_erlang_df(n=1, calls=100, sl=0.80), self.cfg, 15)
        self.assertAlmostEqual(result["abandoned_calls"].iloc[0], 20.0, places=2)

    def test_des_abandon_rate_overrides_sl_gap(self):
        """DES empirical abandon rate (5%) used instead of SL-gap (20%)."""
        des_daily = pd.DataFrame({"daily_abandon_rate": [0.05]})
        result = calculate_interval_costs(
            _erlang_df(n=1, calls=100, sl=0.80), self.cfg, 15, des_daily=des_daily
        )
        self.assertAlmostEqual(result["abandoned_calls"].iloc[0], 5.0, places=2)

    def test_zero_calls_produces_zero_cost(self):
        df = pd.DataFrame({
            "interval":                   [0],
            "calls_offered":              [0.0],
            "erlang_required_net_agents": [0.0],
            "erlang_pred_service_level":  [1.0],
            "erlang_pred_occupancy":      [0.0],
        })
        result = calculate_interval_costs(df, self.cfg, 15)
        self.assertEqual(result["labour_cost"].iloc[0], 0.0)
        self.assertEqual(result["sla_breach_cost"].iloc[0], 0.0)

    def test_required_columns_present(self):
        result = calculate_interval_costs(_erlang_df(), self.cfg, 15)
        for col in ["interval", "calls_offered", "agents_required",
                    "labour_cost", "idle_cost", "sla_breach_cost", "total_cost"]:
            self.assertIn(col, result.columns, f"Missing column: {col}")

    def test_total_cost_equals_labour_plus_breach(self):
        result = calculate_interval_costs(_erlang_df(n=1, sl=0.80), self.cfg, 15)
        expected = result["labour_cost"].iloc[0] + result["sla_breach_cost"].iloc[0]
        self.assertAlmostEqual(result["total_cost"].iloc[0], expected, places=4)


# ---------------------------------------------------------------------------
# calculate_cost_summary
# ---------------------------------------------------------------------------

class TestCalculateCostSummary(unittest.TestCase):

    def _cost_df(self, sl=0.90):
        cfg = CostConfig(hourly_agent_cost=30.0, penalty_per_abandoned=8.0)
        return calculate_interval_costs(_erlang_df(n=4, sl=sl), cfg, 15)

    def test_returns_dict(self):
        self.assertIsInstance(calculate_cost_summary(self._cost_df()), dict)

    def test_empty_input_returns_empty_dict(self):
        self.assertEqual(calculate_cost_summary(pd.DataFrame()), {})

    def test_required_keys_present(self):
        result = calculate_cost_summary(self._cost_df())
        for key in [
            "total_labour_cost", "total_sla_breach_cost", "total_idle_cost",
            "total_cost", "avg_cost_per_call", "peak_interval_cost",
            "idle_cost_pct", "overstaffed_intervals_pct", "understaffed_intervals_pct",
        ]:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_total_cost_equals_labour_plus_breach(self):
        result = calculate_cost_summary(self._cost_df(sl=0.80))
        expected = round(result["total_labour_cost"] + result["total_sla_breach_cost"], 2)
        self.assertAlmostEqual(result["total_cost"], expected, places=2)

    def test_avg_cost_per_call_positive(self):
        result = calculate_cost_summary(self._cost_df())
        self.assertGreater(result["avg_cost_per_call"], 0.0)

    def test_no_overstaffing_when_perfectly_staffed(self):
        """No roster → agents_rostered == agents_required → no overstaffing."""
        result = calculate_cost_summary(self._cost_df())
        self.assertEqual(result["overstaffed_intervals_pct"], 0.0)

    def test_overstaffed_pct_full_when_all_overstaffed(self):
        cfg = CostConfig()
        cost_df = calculate_interval_costs(_erlang_df(n=4), cfg, 15, roster_df=_roster_df(agents=20.0))
        result = calculate_cost_summary(cost_df)
        self.assertEqual(result["overstaffed_intervals_pct"], 100.0)


# ---------------------------------------------------------------------------
# project_monthly_labour_cost
# ---------------------------------------------------------------------------

class TestProjectMonthlyLabourCost(unittest.TestCase):

    def test_adds_cost_columns(self):
        cfg = CostConfig(hourly_agent_cost=30.0)
        result = project_monthly_labour_cost(_planning_df(), cfg)
        self.assertIn("monthly_labour_cost", result.columns)
        self.assertIn("monthly_required_cost", result.columns)
        self.assertIn("monthly_cost_gap", result.columns)

    def test_monthly_cost_formula(self):
        """50 FTE * £30/hr * 151.67 h/month."""
        cfg = CostConfig(hourly_agent_cost=30.0)
        result = project_monthly_labour_cost(_planning_df(), cfg)
        expected = round(50.0 * 30.0 * _WORKING_HOURS_PER_MONTH, 2)
        self.assertAlmostEqual(result["monthly_labour_cost"].iloc[0], expected, places=0)

    def test_positive_gap_when_available_exceeds_required(self):
        """available=50, required=48 → cost gap positive (over-spend)."""
        cfg = CostConfig(hourly_agent_cost=30.0)
        result = project_monthly_labour_cost(_planning_df(), cfg)
        self.assertGreater(result["monthly_cost_gap"].iloc[0], 0.0)

    def test_custom_working_hours(self):
        cfg = CostConfig(hourly_agent_cost=30.0)
        result = project_monthly_labour_cost(_planning_df(), cfg, working_hours_per_month=160.0)
        expected = round(50.0 * 30.0 * 160.0, 2)
        self.assertAlmostEqual(result["monthly_labour_cost"].iloc[0], expected, places=0)

    def test_empty_input_returns_empty(self):
        result = project_monthly_labour_cost(pd.DataFrame(), CostConfig())
        self.assertTrue(result.empty)

    def test_row_count_unchanged(self):
        cfg = CostConfig()
        result = project_monthly_labour_cost(_planning_df(), cfg)
        self.assertEqual(len(result), len(_planning_df()))


if __name__ == "__main__":
    unittest.main()
