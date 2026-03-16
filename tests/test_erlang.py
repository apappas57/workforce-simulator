"""
Unit tests for the Erlang C engine (models/erlang.py).

Coverage goals:
  - erlang_c_prob_wait:       boundary conditions + known analytical values
  - erlang_c_service_level:   boundary conditions + monotonicity properties
  - erlang_c_asa_seconds:     boundary conditions + relationship to prob_wait
  - solve_staffing_erlang_for_interval: occupancy cap, SL target, zero demand
  - solve_staffing_erlang (DataFrame):  output columns, shrinkage arithmetic
"""

import math
try:
    import pytest
except ImportError:
    pytest = None
import pandas as pd
import numpy as np
import sys
import os

# Allow imports from the project root regardless of how pytest is invoked
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.erlang import (
    erlang_c_prob_wait,
    erlang_c_service_level,
    erlang_c_asa_seconds,
    solve_staffing_erlang_for_interval,
    solve_staffing_erlang,
)
from config.sim_config import SimConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_single_interval_df(calls: float, aht: float = 360.0) -> pd.DataFrame:
    """Minimal DataFrame accepted by solve_staffing_erlang."""
    return pd.DataFrame({
        "interval": [0],
        "calls_offered": [calls],
        "aht_seconds_used": [aht],
    })


DEFAULT_CFG = SimConfig(
    interval_minutes=15,
    aht_seconds=360.0,
    shrinkage=0.35,
    occupancy_cap=0.85,
    sl_threshold_seconds=180.0,
    sl_target=0.60,
    seed=42,
)


# ---------------------------------------------------------------------------
# erlang_c_prob_wait
# ---------------------------------------------------------------------------

class TestErlangCProbWait:
    def test_zero_demand_returns_zero(self):
        assert erlang_c_prob_wait(a=0.0, c=10) == 0.0

    def test_zero_agents_returns_one(self):
        assert erlang_c_prob_wait(a=5.0, c=0) == 1.0

    def test_overloaded_returns_one(self):
        # traffic >= agents => system is saturated
        assert erlang_c_prob_wait(a=10.0, c=10) == 1.0
        assert erlang_c_prob_wait(a=15.0, c=10) == 1.0

    def test_result_is_probability(self):
        for a in [0.5, 1.0, 5.0, 9.9]:
            pw = erlang_c_prob_wait(a=a, c=10)
            assert 0.0 <= pw <= 1.0, f"prob_wait out of range for a={a}"

    def test_more_agents_reduces_wait_probability(self):
        # Keeping demand constant, adding agents should reduce P(wait)
        a = 8.0
        pw_10 = erlang_c_prob_wait(a=a, c=10)
        pw_15 = erlang_c_prob_wait(a=a, c=15)
        pw_20 = erlang_c_prob_wait(a=a, c=20)
        assert pw_10 >= pw_15 >= pw_20

    def test_single_agent_light_load(self):
        # For c=1, Erlang C collapses to M/M/1: P(wait) = utilisation = a
        a = 0.5
        expected = a  # server utilisation when c=1
        result = erlang_c_prob_wait(a=a, c=1)
        assert abs(result - expected) < 1e-6, f"M/M/1 mismatch: {result} vs {expected}"


# ---------------------------------------------------------------------------
# erlang_c_service_level
# ---------------------------------------------------------------------------

class TestErlangCServiceLevel:
    def test_zero_demand_returns_one(self):
        assert erlang_c_service_level(a=0.0, c=10, aht_seconds=360.0, t_seconds=180.0) == 1.0

    def test_zero_agents_returns_zero(self):
        assert erlang_c_service_level(a=5.0, c=0, aht_seconds=360.0, t_seconds=180.0) == 0.0

    def test_overloaded_returns_zero(self):
        assert erlang_c_service_level(a=10.0, c=10, aht_seconds=360.0, t_seconds=180.0) == 0.0

    def test_result_is_probability(self):
        sl = erlang_c_service_level(a=8.0, c=10, aht_seconds=360.0, t_seconds=180.0)
        assert 0.0 <= sl <= 1.0

    def test_more_agents_increases_service_level(self):
        kwargs = dict(a=8.0, aht_seconds=360.0, t_seconds=180.0)
        sl_10 = erlang_c_service_level(c=10, **kwargs)
        sl_12 = erlang_c_service_level(c=12, **kwargs)
        sl_20 = erlang_c_service_level(c=20, **kwargs)
        assert sl_10 <= sl_12 <= sl_20

    def test_longer_threshold_increases_service_level(self):
        # A more generous answer-time threshold should always yield ≥ SL
        kwargs = dict(a=5.0, c=8, aht_seconds=360.0)
        sl_60  = erlang_c_service_level(t_seconds=60.0,  **kwargs)
        sl_180 = erlang_c_service_level(t_seconds=180.0, **kwargs)
        sl_600 = erlang_c_service_level(t_seconds=600.0, **kwargs)
        assert sl_60 <= sl_180 <= sl_600


# ---------------------------------------------------------------------------
# erlang_c_asa_seconds
# ---------------------------------------------------------------------------

class TestErlangCAsaSeconds:
    def test_zero_demand_returns_zero(self):
        assert erlang_c_asa_seconds(a=0.0, c=10, aht_seconds=360.0) == 0.0

    def test_zero_agents_returns_inf(self):
        assert erlang_c_asa_seconds(a=5.0, c=0, aht_seconds=360.0) == float("inf")

    def test_overloaded_returns_inf(self):
        assert erlang_c_asa_seconds(a=10.0, c=10, aht_seconds=360.0) == float("inf")

    def test_proportional_to_prob_wait(self):
        # ASA = P(wait) * AHT / (c - a)  — verify the relationship holds
        a, c, aht = 8.0, 10, 360.0
        pw = erlang_c_prob_wait(a=a, c=c)
        expected_asa = pw * aht / (c - a)
        result_asa = erlang_c_asa_seconds(a=a, c=c, aht_seconds=aht)
        assert abs(result_asa - expected_asa) < 1e-9

    def test_more_agents_reduces_asa(self):
        kwargs = dict(a=8.0, aht_seconds=360.0)
        asa_10 = erlang_c_asa_seconds(c=10, **kwargs)
        asa_15 = erlang_c_asa_seconds(c=15, **kwargs)
        assert asa_10 >= asa_15


# ---------------------------------------------------------------------------
# solve_staffing_erlang_for_interval
# ---------------------------------------------------------------------------

class TestSolveStaffingErlangForInterval:
    def _solve(self, calls, aht=360.0, interval_min=15, sl_target=0.60,
                sl_threshold=180.0, occupancy_cap=0.85):
        return solve_staffing_erlang_for_interval(
            calls_offered=calls,
            interval_seconds=interval_min * 60,
            aht_seconds=aht,
            sl_target=sl_target,
            sl_threshold_seconds=sl_threshold,
            occupancy_cap=occupancy_cap,
        )

    def test_zero_calls_returns_zero_agents(self):
        c, sl, asa, occ = self._solve(calls=0)
        assert c == 0
        assert sl == 1.0
        assert asa == 0.0
        assert occ == 0.0

    def test_returns_tuple_of_correct_types(self):
        c, sl, asa, occ = self._solve(calls=100)
        assert isinstance(c, int)
        assert isinstance(sl, float)
        assert isinstance(asa, float)
        assert isinstance(occ, float)

    def test_service_level_meets_target(self):
        c, sl, asa, occ = self._solve(calls=100, sl_target=0.80)
        assert sl >= 0.80, f"SL {sl:.3f} did not meet 0.80 target with {c} agents"

    def test_occupancy_cap_respected(self):
        c, sl, asa, occ = self._solve(calls=200, occupancy_cap=0.85)
        assert occ <= 0.85 + 1e-6, f"Occupancy {occ:.4f} exceeded cap 0.85"

    def test_more_calls_requires_more_agents(self):
        c_low,  *_ = self._solve(calls=50)
        c_high, *_ = self._solve(calls=200)
        assert c_high >= c_low

    def test_tighter_sl_requires_more_agents(self):
        c_60, *_ = self._solve(calls=100, sl_target=0.60)
        c_90, *_ = self._solve(calls=100, sl_target=0.90)
        assert c_90 >= c_60

    def test_lower_occupancy_cap_requires_more_agents(self):
        c_85, *_ = self._solve(calls=100, occupancy_cap=0.85)
        c_70, *_ = self._solve(calls=100, occupancy_cap=0.70)
        assert c_70 >= c_85


# ---------------------------------------------------------------------------
# solve_staffing_erlang (DataFrame wrapper)
# ---------------------------------------------------------------------------

class TestSolveStaffingErlangDf:
    def test_output_columns_present(self):
        df = _make_single_interval_df(calls=100)
        out = solve_staffing_erlang(df, DEFAULT_CFG)
        for col in [
            "erlang_required_net_agents",
            "erlang_pred_service_level",
            "erlang_pred_asa_seconds",
            "erlang_pred_occupancy",
            "erlang_required_paid_agents",
            "erlang_required_paid_agents_ceil",
        ]:
            assert col in out.columns, f"Missing column: {col}"

    def test_paid_agents_accounts_for_shrinkage(self):
        df = _make_single_interval_df(calls=100)
        out = solve_staffing_erlang(df, DEFAULT_CFG)
        net = out["erlang_required_net_agents"].iloc[0]
        paid = out["erlang_required_paid_agents"].iloc[0]
        expected_paid = net / (1.0 - DEFAULT_CFG.shrinkage)
        assert abs(paid - expected_paid) < 1e-6

    def test_paid_ceil_is_ceiling_of_paid(self):
        df = _make_single_interval_df(calls=100)
        out = solve_staffing_erlang(df, DEFAULT_CFG)
        paid = out["erlang_required_paid_agents"].iloc[0]
        paid_ceil = out["erlang_required_paid_agents_ceil"].iloc[0]
        assert paid_ceil == math.ceil(paid)

    def test_zero_shrinkage_paid_equals_net(self):
        cfg_no_shrink = SimConfig(shrinkage=0.0)
        df = _make_single_interval_df(calls=100)
        out = solve_staffing_erlang(df, cfg_no_shrink)
        net = out["erlang_required_net_agents"].iloc[0]
        paid = out["erlang_required_paid_agents"].iloc[0]
        assert abs(paid - net) < 1e-9

    def test_row_count_preserved(self):
        df = pd.DataFrame({
            "interval": range(96),
            "calls_offered": np.random.randint(50, 200, 96),
            "aht_seconds_used": [360.0] * 96,
        })
        out = solve_staffing_erlang(df, DEFAULT_CFG)
        assert len(out) == 96

    def test_zero_calls_row_gives_zero_net_agents(self):
        df = _make_single_interval_df(calls=0)
        out = solve_staffing_erlang(df, DEFAULT_CFG)
        assert out["erlang_required_net_agents"].iloc[0] == 0
