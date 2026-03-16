"""
Unit tests for the DES-driven staffing solver (optimisation/staffing_solver.py).

The solver calls run_des_engine internally, which is expensive.  We mock it here
so these tests remain fast and isolated from the DES layer.  The mock returns a
controllable sim_out dict that lets us verify solver logic independently.

Coverage goals:
  - Return dict contains all expected keys
  - target_met is True when mock SL/abandon are within spec from iteration 1
  - Solver increments staff on failing intervals
  - Solver stops on stagnation before hitting max_iterations
  - Solver respects max_iterations cap
  - staffing_curve DataFrame has expected columns
"""

import sys
import os
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
try:
    import pytest
except ImportError:
    pytest = None

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from optimisation.staffing_solver import solve_staffing_to_target
from config.sim_config import SimConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_CFG = SimConfig(
    interval_minutes=15,
    aht_seconds=360.0,
    shrinkage=0.35,
    occupancy_cap=0.85,
    sl_threshold_seconds=180.0,
    sl_target=0.80,
    seed=42,
)

N = 4  # number of intervals in test DataFrames


def _make_validate_df(staff: int = 10, n: int = N) -> pd.DataFrame:
    return pd.DataFrame({
        "interval": range(n),
        "calls_offered": [100.0] * n,
        "staff_for_des": [staff] * n,
    })


def _make_sim_out(overall_sl: float, overall_abandon: float, n: int = N) -> dict:
    """Build a minimal sim_out dict matching what run_des_engine returns."""
    return {
        "overall": {
            "sim_service_level": overall_sl,
            "sim_abandon_rate": overall_abandon,
        },
        "interval_kpis": pd.DataFrame({
            "sim_service_level": [overall_sl] * n,
            "sim_abandon_rate":  [overall_abandon] * n,
            "sim_calls":         [100.0] * n,
        }),
    }


SOLVER_KWARGS = dict(
    cfg=DEFAULT_CFG,
    service_time_dist="exponential",
    enable_abandonment=True,
    patience_dist="exponential",
    mean_patience_seconds=120.0,
)


# ---------------------------------------------------------------------------
# Return structure
# ---------------------------------------------------------------------------

class TestSolverReturnStructure:
    def test_all_keys_present(self):
        mock_out = _make_sim_out(overall_sl=0.90, overall_abandon=0.02)

        with patch("optimisation.staffing_solver.run_des_engine", return_value=mock_out):
            result = solve_staffing_to_target(
                base_validate_df=_make_validate_df(),
                **SOLVER_KWARGS,
            )

        for key in [
            "solved_validate_df",
            "final_sim_out",
            "iterations_used",
            "target_met",
            "staffing_curve",
            "final_overall_service_level",
            "final_overall_abandon_rate",
            "stagnated",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_staffing_curve_columns(self):
        mock_out = _make_sim_out(0.90, 0.02)

        with patch("optimisation.staffing_solver.run_des_engine", return_value=mock_out):
            result = solve_staffing_to_target(
                base_validate_df=_make_validate_df(),
                **SOLVER_KWARGS,
            )

        sc = result["staffing_curve"]
        assert "interval" in sc.columns
        assert "required_staff_for_des" in sc.columns
        assert len(sc) == N


# ---------------------------------------------------------------------------
# target_met logic
# ---------------------------------------------------------------------------

class TestSolverTargetMet:
    def test_target_met_when_sl_and_abandon_within_spec(self):
        # SL above target, abandon below threshold → target met on first iteration
        mock_out = _make_sim_out(overall_sl=0.90, overall_abandon=0.02)

        with patch("optimisation.staffing_solver.run_des_engine", return_value=mock_out):
            result = solve_staffing_to_target(
                base_validate_df=_make_validate_df(),
                **SOLVER_KWARGS,
            )

        assert result["target_met"] is True
        assert result["iterations_used"] == 1

    def test_target_not_met_when_sl_below_target(self):
        # SL always below target → should exhaust iterations without meeting target
        mock_out = _make_sim_out(overall_sl=0.50, overall_abandon=0.02)

        with patch("optimisation.staffing_solver.run_des_engine", return_value=mock_out):
            result = solve_staffing_to_target(
                base_validate_df=_make_validate_df(),
                max_iterations=3,
                **SOLVER_KWARGS,
            )

        assert result["target_met"] is False

    def test_target_not_met_when_abandon_above_threshold(self):
        # SL fine but abandon too high → should not declare target met
        mock_out = _make_sim_out(overall_sl=0.90, overall_abandon=0.15)

        with patch("optimisation.staffing_solver.run_des_engine", return_value=mock_out):
            result = solve_staffing_to_target(
                base_validate_df=_make_validate_df(),
                max_iterations=3,
                max_abandon_rate=0.05,
                **SOLVER_KWARGS,
            )

        assert result["target_met"] is False


# ---------------------------------------------------------------------------
# Staff increments
# ---------------------------------------------------------------------------

class TestSolverStaffIncrements:
    def test_staff_increases_when_target_not_met(self):
        mock_out = _make_sim_out(overall_sl=0.50, overall_abandon=0.02)
        df = _make_validate_df(staff=10)
        initial_staff = df["staff_for_des"].sum()

        with patch("optimisation.staffing_solver.run_des_engine", return_value=mock_out):
            result = solve_staffing_to_target(
                base_validate_df=df,
                max_iterations=5,
                **SOLVER_KWARGS,
            )

        final_staff = result["solved_validate_df"]["staff_for_des"].sum()
        assert final_staff > initial_staff


# ---------------------------------------------------------------------------
# Stopping conditions
# ---------------------------------------------------------------------------

class TestSolverStoppingConditions:
    def test_stops_at_max_iterations(self):
        mock_out = _make_sim_out(overall_sl=0.50, overall_abandon=0.02)

        with patch("optimisation.staffing_solver.run_des_engine", return_value=mock_out):
            result = solve_staffing_to_target(
                base_validate_df=_make_validate_df(),
                max_iterations=4,
                **SOLVER_KWARGS,
            )

        assert result["iterations_used"] <= 4

    def test_stagnation_stops_early(self):
        # Return identical SL every call → improvement = 0 → stagnation
        mock_out = _make_sim_out(overall_sl=0.55, overall_abandon=0.02)

        with patch("optimisation.staffing_solver.run_des_engine", return_value=mock_out):
            result = solve_staffing_to_target(
                base_validate_df=_make_validate_df(),
                max_iterations=20,
                stagnation_rounds=2,
                min_improvement=0.01,
                **SOLVER_KWARGS,
            )

        # Should have stopped well before 20 due to stagnation
        assert result["iterations_used"] < 20
        assert result["stagnated"] is True


# ---------------------------------------------------------------------------
# Custom target_service_level override
# ---------------------------------------------------------------------------

class TestSolverTargetOverride:
    def test_custom_target_overrides_cfg(self):
        # With a custom very low target, a modest SL should satisfy it immediately
        mock_out = _make_sim_out(overall_sl=0.65, overall_abandon=0.02)

        with patch("optimisation.staffing_solver.run_des_engine", return_value=mock_out):
            result = solve_staffing_to_target(
                base_validate_df=_make_validate_df(),
                target_service_level=0.60,   # lower than mock SL of 0.65
                **SOLVER_KWARGS,
            )

        assert result["target_met"] is True
