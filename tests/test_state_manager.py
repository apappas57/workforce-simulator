"""tests/test_state_manager.py

Unit tests for persistence/state_manager.py.

These tests use a temporary directory to avoid touching the real state/
directory, and require no Streamlit runtime — state_manager is pure Python.
"""

import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

# Patch STATE_DIR before importing state_manager so tests use a temp dir.
_TMP = tempfile.mkdtemp()

import persistence.state_manager as sm  # noqa: E402  (import after patching below)

try:
    import pyarrow  # noqa: F401
    _parquet_available = True
except ImportError:
    _parquet_available = False


def _patch_state_dir(tmp_path: Path):
    """Context manager that redirects state_manager to use tmp_path."""
    return patch.multiple(
        sm,
        STATE_DIR=tmp_path,
        _SETTINGS_FILE=tmp_path / "settings.json",
    )


class TestDeserialise(unittest.TestCase):
    """Unit tests for _deserialise() — type coercion for widget initialisation."""

    def test_date_key_none_returns_month_start(self):
        result = sm._deserialise("planning_start_date", None)
        self.assertIsInstance(result, datetime.date)
        self.assertEqual(result.day, 1)

    def test_date_key_iso_string_parsed(self):
        result = sm._deserialise("opt_planning_start", "2026-06-01")
        self.assertEqual(result, datetime.date(2026, 6, 1))

    def test_date_key_invalid_string_returns_month_start(self):
        result = sm._deserialise("planning_start_date", "not-a-date")
        self.assertIsInstance(result, datetime.date)
        self.assertEqual(result.day, 1)

    def test_non_date_key_passthrough(self):
        self.assertEqual(sm._deserialise("sb_aht_seconds", 420.0), 420.0)
        self.assertEqual(sm._deserialise("opt_horizon", 24), 24)

    def test_invalid_input_tz_falls_back_to_utc(self):
        result = sm._deserialise("sb_input_tz", "Pacific/Auckland")
        self.assertEqual(result, "UTC")

    def test_invalid_model_tz_falls_back_to_melbourne(self):
        result = sm._deserialise("sb_model_tz", "garbage")
        self.assertEqual(result, "Australia/Melbourne")

    def test_valid_tz_passthrough(self):
        self.assertEqual(sm._deserialise("sb_input_tz", "UTC"), "UTC")
        self.assertEqual(
            sm._deserialise("sb_model_tz", "Australia/Melbourne"),
            "Australia/Melbourne",
        )


class TestSerialise(unittest.TestCase):
    """Unit tests for _serialise() — converts Python objects to JSON-safe types."""

    def test_date_serialised_to_iso_string(self):
        result = sm._serialise(datetime.date(2026, 4, 1))
        self.assertEqual(result, "2026-04-01")

    def test_datetime_serialised_to_date_iso_string(self):
        result = sm._serialise(datetime.datetime(2026, 4, 1, 12, 0, 0))
        self.assertEqual(result, "2026-04-01")

    def test_scalar_passthrough(self):
        self.assertEqual(sm._serialise(42), 42)
        self.assertEqual(sm._serialise(3.14), 3.14)
        self.assertEqual(sm._serialise("hello"), "hello")


class TestLoadSettings(unittest.TestCase):
    """load_settings() — returns defaults when no file exists, merges when it does."""

    def test_returns_defaults_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with _patch_state_dir(tmp_path):
                result = sm.load_settings()
        self.assertIn("sb_interval_minutes", result)
        self.assertEqual(result["sb_interval_minutes"], 15)
        self.assertEqual(result["sb_aht_seconds"], 360.0)

    def test_merges_saved_values_over_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings_file = tmp_path / "settings.json"
            settings_file.write_text(
                json.dumps({"sb_aht_seconds": 480.0, "sb_seed": 99}),
                encoding="utf-8",
            )
            with _patch_state_dir(tmp_path):
                result = sm.load_settings()
        self.assertEqual(result["sb_aht_seconds"], 480.0)
        self.assertEqual(result["sb_seed"], 99)
        # Unmodified defaults remain
        self.assertEqual(result["sb_interval_minutes"], 15)

    def test_graceful_on_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "settings.json").write_text("not valid json", encoding="utf-8")
            with _patch_state_dir(tmp_path):
                result = sm.load_settings()
        # Falls back to defaults without raising
        self.assertEqual(result["sb_interval_minutes"], 15)

    def test_date_keys_are_datetime_date_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "settings.json").write_text(
                json.dumps({"planning_start_date": "2026-07-01"}),
                encoding="utf-8",
            )
            with _patch_state_dir(tmp_path):
                result = sm.load_settings()
        self.assertIsInstance(result["planning_start_date"], datetime.date)
        self.assertEqual(result["planning_start_date"], datetime.date(2026, 7, 1))


class TestSaveSettings(unittest.TestCase):
    """save_settings() — writes known keys from session state to disk."""

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_state = {
                "sb_interval_minutes": 30,
                "sb_aht_seconds": 600.0,
                "sb_shrinkage": 0.25,
                "sb_occupancy_cap": 0.80,
                "sb_sl_target": 0.70,
                "sb_sl_threshold_seconds": 120.0,
                "sb_avg_calls": 200.0,
                "sb_seed": 7,
                "sb_input_tz": "UTC",
                "sb_model_tz": "Australia/Melbourne",
                "planning_start_date": datetime.date(2026, 9, 1),
                "planning_horizon_months": 18,
            }
            with _patch_state_dir(tmp_path):
                sm.save_settings(fake_state)
                result = sm.load_settings()
        self.assertEqual(result["sb_interval_minutes"], 30)
        self.assertEqual(result["sb_aht_seconds"], 600.0)
        self.assertEqual(result["planning_horizon_months"], 18)
        self.assertEqual(result["planning_start_date"], datetime.date(2026, 9, 1))

    def test_ignores_unknown_keys(self):
        """save_settings should not blow up on extra keys in session state."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_state = {
                "sb_seed": 42,
                "some_unrelated_key": "ignored",
                "planning_projection": pd.DataFrame(),
            }
            with _patch_state_dir(tmp_path):
                sm.save_settings(fake_state)   # should not raise
                result = sm.load_settings()
        self.assertEqual(result["sb_seed"], 42)


class TestSaveLoadDataFrame(unittest.TestCase):
    """save_dataframe() / load_dataframes() — parquet roundtrip."""

    @unittest.skipUnless(_parquet_available, "pyarrow not installed in this environment")
    def test_save_and_load_roundtrip(self):
        df = pd.DataFrame({"period_label": ["2026-01", "2026-02"], "hires": [5, 3]})
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with _patch_state_dir(tmp_path):
                sm.save_dataframe("planning_projection", df)
                result = sm.load_dataframes()
        pd.testing.assert_frame_equal(result["planning_projection"], df)

    def test_missing_file_yields_empty_dataframe(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with _patch_state_dir(tmp_path):
                result = sm.load_dataframes()
        for key in sm.PERSISTENT_DF_KEYS:
            self.assertTrue(result[key].empty)

    def test_save_noop_for_empty_dataframe(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with _patch_state_dir(tmp_path):
                sm.save_dataframe("planning_projection", pd.DataFrame())
                parquet_path = tmp_path / "planning_projection.parquet"
        self.assertFalse(parquet_path.exists())

    def test_save_noop_for_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with _patch_state_dir(tmp_path):
                sm.save_dataframe("optimisation_result", None)  # should not raise


if __name__ == "__main__":
    unittest.main()
