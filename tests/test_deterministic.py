"""
Unit tests for the deterministic staffing model (models/deterministic.py).

Coverage goals:
  - Output columns are present and correctly typed
  - Workload arithmetic is correct
  - Occupancy cap and shrinkage are applied as expected
  - Per-interval AHT column is used when present
  - Ceiling rounding is applied to integer agent columns
"""

import math
import sys
import os

import numpy as np
import pandas as pd
try:
    import pytest
except ImportError:
    pytest = None

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.deterministic import deterministic_staffing
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
    sl_target=0.60,
    seed=42,
)


def _make_df(calls_list, aht_col=None):
    df = pd.DataFrame({
        "interval": range(len(calls_list)),
        "calls_offered": calls_list,
    })
    if aht_col is not None:
        df["aht_seconds"] = aht_col
    return df


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class TestDeterministicOutputStructure:
    def test_required_columns_present(self):
        df = _make_df([100])
        out = deterministic_staffing(df, DEFAULT_CFG)
        for col in [
            "aht_seconds_used",
            "interval_seconds",
            "workload_seconds",
            "workload_hours",
            "raw_concurrent_agents",
            "required_net_after_occ",
            "required_paid_after_shrink",
            "det_required_net_ceil",
            "det_required_paid_ceil",
        ]:
            assert col in out.columns, f"Missing column: {col}"

    def test_row_count_preserved(self):
        df = _make_df(list(range(1, 97)))
        out = deterministic_staffing(df, DEFAULT_CFG)
        assert len(out) == 96

    def test_ceil_columns_are_int(self):
        df = _make_df([100, 200])
        out = deterministic_staffing(df, DEFAULT_CFG)
        assert out["det_required_net_ceil"].dtype in (int, np.int32, np.int64)
        assert out["det_required_paid_ceil"].dtype in (int, np.int32, np.int64)


# ---------------------------------------------------------------------------
# Arithmetic correctness
# ---------------------------------------------------------------------------

class TestDeterministicArithmetic:
    def test_workload_seconds(self):
        calls, aht = 100.0, 360.0
        df = _make_df([calls])
        out = deterministic_staffing(df, DEFAULT_CFG)
        expected = calls * aht
        assert abs(out["workload_seconds"].iloc[0] - expected) < 1e-6

    def test_workload_hours(self):
        calls, aht = 100.0, 360.0
        df = _make_df([calls])
        out = deterministic_staffing(df, DEFAULT_CFG)
        expected = (calls * aht) / 3600.0
        assert abs(out["workload_hours"].iloc[0] - expected) < 1e-6

    def test_raw_concurrent_agents(self):
        calls, aht, interval_min = 100.0, 360.0, 15
        df = _make_df([calls])
        cfg = SimConfig(interval_minutes=interval_min, aht_seconds=aht)
        out = deterministic_staffing(df, cfg)
        expected = (calls * aht) / (interval_min * 60)
        assert abs(out["raw_concurrent_agents"].iloc[0] - expected) < 1e-6

    def test_occupancy_cap_applied(self):
        calls, aht, occ_cap = 100.0, 360.0, 0.80
        df = _make_df([calls])
        cfg = SimConfig(aht_seconds=aht, occupancy_cap=occ_cap)
        out = deterministic_staffing(df, cfg)
        raw = out["raw_concurrent_agents"].iloc[0]
        expected = raw / occ_cap
        assert abs(out["required_net_after_occ"].iloc[0] - expected) < 1e-6

    def test_shrinkage_applied(self):
        calls, aht, shrink = 100.0, 360.0, 0.30
        df = _make_df([calls])
        cfg = SimConfig(aht_seconds=aht, shrinkage=shrink)
        out = deterministic_staffing(df, cfg)
        net = out["required_net_after_occ"].iloc[0]
        expected = net / (1.0 - shrink)
        assert abs(out["required_paid_after_shrink"].iloc[0] - expected) < 1e-6

    def test_net_ceil_is_ceiling_of_net(self):
        df = _make_df([100])
        out = deterministic_staffing(df, DEFAULT_CFG)
        net = out["required_net_after_occ"].iloc[0]
        ceil = out["det_required_net_ceil"].iloc[0]
        assert ceil == math.ceil(net)

    def test_paid_ceil_is_ceiling_of_paid(self):
        df = _make_df([100])
        out = deterministic_staffing(df, DEFAULT_CFG)
        paid = out["required_paid_after_shrink"].iloc[0]
        ceil = out["det_required_paid_ceil"].iloc[0]
        assert ceil == math.ceil(paid)

    def test_zero_calls_gives_zero_agents(self):
        df = _make_df([0])
        out = deterministic_staffing(df, DEFAULT_CFG)
        assert out["det_required_net_ceil"].iloc[0] == 0
        assert out["det_required_paid_ceil"].iloc[0] == 0

    def test_zero_shrinkage_paid_equals_net(self):
        df = _make_df([100])
        cfg = SimConfig(shrinkage=0.0)
        out = deterministic_staffing(df, cfg)
        net = out["required_net_after_occ"].iloc[0]
        paid = out["required_paid_after_shrink"].iloc[0]
        assert abs(paid - net) < 1e-9


# ---------------------------------------------------------------------------
# Per-interval AHT column
# ---------------------------------------------------------------------------

class TestDeterministicPerIntervalAht:
    def test_aht_col_used_when_present(self):
        # Interval 0 has double the AHT — should produce double the workload
        df = _make_df([100, 100], aht_col=[720.0, 360.0])
        out = deterministic_staffing(df, DEFAULT_CFG)
        ws0 = out["workload_seconds"].iloc[0]
        ws1 = out["workload_seconds"].iloc[1]
        assert abs(ws0 - 2 * ws1) < 1e-6

    def test_cfg_aht_used_when_no_column(self):
        df = _make_df([100])
        cfg = SimConfig(aht_seconds=500.0)
        out = deterministic_staffing(df, cfg)
        assert out["aht_seconds_used"].iloc[0] == 500.0

    def test_per_interval_aht_overrides_cfg(self):
        df = _make_df([100], aht_col=[250.0])
        cfg = SimConfig(aht_seconds=500.0)
        out = deterministic_staffing(df, cfg)
        assert out["aht_seconds_used"].iloc[0] == 250.0
