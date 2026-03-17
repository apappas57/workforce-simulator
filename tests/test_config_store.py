"""tests/test_config_store.py

Unit tests for persistence/config_store.py — Phase 16 named config profiles.

All tests use temporary directories to avoid touching configs/ on disk.

Covers:
  - list_configs(): empty dir, sorted names, .json filter
  - save_config() + load_config(): round-trip, sb_* filter, date serialisation
  - delete_config(): happy path and silent no-op
  - config_exists(): before and after save
  - Error cases: invalid name, name too long, missing config
"""

import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import persistence.config_store as cs


# ---------------------------------------------------------------------------
# Helper: redirect CONFIGS_DIR to a temp path for the duration of a test
# ---------------------------------------------------------------------------

def _patch_configs_dir(tmp_path: Path):
    """Redirect config_store to use *tmp_path* instead of configs/."""
    return patch.multiple(cs, CONFIGS_DIR=tmp_path)


# ---------------------------------------------------------------------------
# list_configs
# ---------------------------------------------------------------------------

class TestListConfigs(unittest.TestCase):

    def test_empty_directory_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                self.assertEqual(cs.list_configs(), [])

    def test_returns_sorted_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "zebra.json").write_text('{"name":"zebra","settings":{}}')
            (p / "alpha.json").write_text('{"name":"alpha","settings":{}}')
            (p / "mango.json").write_text('{"name":"mango","settings":{}}')
            with _patch_configs_dir(p):
                result = cs.list_configs()
            self.assertEqual(result, ["alpha", "mango", "zebra"])

    def test_ignores_non_json_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "config.json").write_text('{"name":"config","settings":{}}')
            (p / "notes.txt").write_text("not json")
            (p / "config.yaml").write_text("key: value")
            with _patch_configs_dir(p):
                result = cs.list_configs()
            self.assertEqual(result, ["config"])

    def test_creates_directory_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "deeply" / "nested"
            with _patch_configs_dir(nested):
                result = cs.list_configs()   # should not raise
            self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# save_config + load_config round-trip
# ---------------------------------------------------------------------------

class TestSaveAndLoadConfig(unittest.TestCase):

    def _ss(self):
        """Minimal session-state-like dict with sb_* and non-sb_* keys."""
        return {
            "sb_interval_minutes":   15,
            "sb_calls_per_interval": 120,
            "sb_aht_seconds":        240,
            "other_key":             "should_be_ignored",
            "roster_scale":          1.0,   # non-sb_* — must be excluded
        }

    def test_round_trip_values_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                cs.save_config("round_trip", self._ss())
                loaded = cs.load_config("round_trip")
            self.assertEqual(loaded["sb_interval_minutes"], 15)
            self.assertEqual(loaded["sb_calls_per_interval"], 120)
            self.assertEqual(loaded["sb_aht_seconds"], 240)

    def test_non_sb_keys_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                cs.save_config("filter_test", self._ss())
                loaded = cs.load_config("filter_test")
            self.assertNotIn("other_key", loaded)
            self.assertNotIn("roster_scale", loaded)

    def test_creates_json_file_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            with _patch_configs_dir(p):
                cs.save_config("disk_test", self._ss())
            self.assertTrue((p / "disk_test.json").exists())

    def test_overwrite_updates_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                cs.save_config("cfg", {"sb_x": 1})
                cs.save_config("cfg", {"sb_x": 99})
                loaded = cs.load_config("cfg")
            self.assertEqual(loaded["sb_x"], 99)

    def test_date_serialisation_round_trip(self):
        ss = {"sb_planning_start_date": datetime.date(2026, 9, 1)}
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                cs.save_config("date_cfg", ss)
                loaded = cs.load_config("date_cfg")
            self.assertEqual(loaded["sb_planning_start_date"], datetime.date(2026, 9, 1))

    def test_opt_planning_start_date_round_trip(self):
        ss = {"sb_opt_planning_start": datetime.date(2027, 1, 1)}
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                cs.save_config("opt_date", ss)
                loaded = cs.load_config("opt_date")
            self.assertEqual(loaded["sb_opt_planning_start"], datetime.date(2027, 1, 1))

    def test_load_nonexistent_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                with self.assertRaises(FileNotFoundError):
                    cs.load_config("ghost_config")


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------

class TestNameValidation(unittest.TestCase):

    def test_invalid_name_with_slash_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                with self.assertRaises(ValueError):
                    cs.save_config("bad/name", {"sb_x": 1})

    def test_invalid_name_with_special_chars_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                with self.assertRaises(ValueError):
                    cs.save_config("name!@#", {"sb_x": 1})

    def test_name_too_long_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                with self.assertRaises(ValueError):
                    cs.save_config("a" * 65, {"sb_x": 1})

    def test_valid_name_with_spaces_and_hyphens_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                cs.save_config("Q4 2026 - baseline", {"sb_x": 42})
                loaded = cs.load_config("Q4 2026 - baseline")
            self.assertEqual(loaded["sb_x"], 42)


# ---------------------------------------------------------------------------
# delete_config
# ---------------------------------------------------------------------------

class TestDeleteConfig(unittest.TestCase):

    def test_delete_removes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                cs.save_config("to_delete", {"sb_x": 1})
                self.assertTrue(cs.config_exists("to_delete"))
                cs.delete_config("to_delete")
                self.assertFalse(cs.config_exists("to_delete"))

    def test_delete_nonexistent_is_silent_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                cs.delete_config("does_not_exist")   # must not raise


# ---------------------------------------------------------------------------
# config_exists
# ---------------------------------------------------------------------------

class TestConfigExists(unittest.TestCase):

    def test_exists_after_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                cs.save_config("exists_test", {"sb_x": 1})
                self.assertTrue(cs.config_exists("exists_test"))

    def test_not_exists_before_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                self.assertFalse(cs.config_exists("never_saved"))

    def test_not_exists_after_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _patch_configs_dir(Path(tmp)):
                cs.save_config("temp", {"sb_x": 1})
                cs.delete_config("temp")
                self.assertFalse(cs.config_exists("temp"))


if __name__ == "__main__":
    unittest.main()
