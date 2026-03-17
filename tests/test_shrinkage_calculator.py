"""tests/test_shrinkage_calculator.py

Unit tests for supply/shrinkage_calculator.py.

Tests cover classify_activity() and compute_observed_shrinkage() across all
relevant edge cases: missing column, all-productive, all-non-productive, mixed,
null values, case insensitivity, staff-weight weighting, and coverage %.
"""

import math
import unittest

import pandas as pd

from supply.shrinkage_calculator import classify_activity, compute_observed_shrinkage


class TestClassifyActivity(unittest.TestCase):
    """classify_activity() — single-label classification."""

    def test_productive_keywords(self):
        for label in ["Available", "READY", "On Call", "Inbound", "Talking", "Busy"]:
            with self.subTest(label=label):
                self.assertEqual(classify_activity(label), "productive")

    def test_non_productive_keywords(self):
        for label in ["Break", "LUNCH", "Training", "Meeting", "Admin", "Wrap", "ACW", "Offline"]:
            with self.subTest(label=label):
                self.assertEqual(classify_activity(label), "non_productive")

    def test_case_insensitive(self):
        self.assertEqual(classify_activity("BREAK"), "non_productive")
        self.assertEqual(classify_activity("available"), "productive")
        self.assertEqual(classify_activity("Available"), "productive")

    def test_unknown_label(self):
        self.assertEqual(classify_activity("other"), "unknown")
        self.assertEqual(classify_activity("custom_activity_xyz"), "unknown")

    def test_null_values(self):
        self.assertEqual(classify_activity(None), "unknown")
        self.assertEqual(classify_activity(float("nan")), "unknown")
        self.assertEqual(classify_activity(""), "unknown")

    def test_substring_match(self):
        # Should match because "break" appears within the string
        self.assertEqual(classify_activity("Comfort Break"), "non_productive")
        self.assertEqual(classify_activity("Inbound Call"), "productive")


class TestComputeObservedShrinkage(unittest.TestCase):
    """compute_observed_shrinkage() — full pipeline tests."""

    def _make_df(self, activities, staff_counts=None):
        """Helper: build a minimal staffing DataFrame."""
        data = {"activity": activities}
        if staff_counts is not None:
            data["available_staff"] = staff_counts
        return pd.DataFrame(data)

    # ── No activity data ──────────────────────────────────────────────────────

    def test_no_activity_column_returns_no_data(self):
        df = pd.DataFrame({"available_staff": [10, 10, 10]})
        result = compute_observed_shrinkage(df)
        self.assertFalse(result["has_activity_data"])
        self.assertEqual(result["coverage_pct"], 0.0)
        self.assertIsNone(result["observed_shrinkage_pct"])
        self.assertTrue(result["activity_breakdown"].empty)

    def test_all_null_activities_returns_no_data(self):
        df = self._make_df([None, None, None], [5, 5, 5])
        result = compute_observed_shrinkage(df)
        self.assertFalse(result["has_activity_data"])

    # ── All productive ────────────────────────────────────────────────────────

    def test_all_productive_zero_shrinkage(self):
        df = self._make_df(["Available", "Ready", "Talking"], [10, 10, 10])
        result = compute_observed_shrinkage(df)
        self.assertTrue(result["has_activity_data"])
        self.assertEqual(result["observed_shrinkage_pct"], 0.0)
        self.assertEqual(result["productive_pct"], 100.0)
        self.assertEqual(result["non_productive_pct"], 0.0)

    # ── All non-productive ────────────────────────────────────────────────────

    def test_all_non_productive_full_shrinkage(self):
        df = self._make_df(["Break", "Training", "Lunch"], [5, 5, 5])
        result = compute_observed_shrinkage(df)
        self.assertTrue(result["has_activity_data"])
        self.assertEqual(result["observed_shrinkage_pct"], 100.0)
        self.assertEqual(result["non_productive_pct"], 100.0)
        self.assertEqual(result["productive_pct"], 0.0)

    # ── Mixed activities ──────────────────────────────────────────────────────

    def test_mixed_correct_shrinkage(self):
        # 8 productive, 2 non-productive → shrinkage = 20 %
        df = self._make_df(
            ["Available", "Break"],
            [8, 2],
        )
        result = compute_observed_shrinkage(df)
        self.assertTrue(result["has_activity_data"])
        self.assertAlmostEqual(result["observed_shrinkage_pct"], 20.0, places=1)
        self.assertAlmostEqual(result["productive_pct"], 80.0, places=1)
        self.assertAlmostEqual(result["non_productive_pct"], 20.0, places=1)

    def test_weighted_by_available_staff(self):
        # 1 interval with 9 productive agents, 1 interval with 1 non-productive agent
        # → shrinkage = 1/10 = 10 %
        df = self._make_df(["Available", "Lunch"], [9, 1])
        result = compute_observed_shrinkage(df)
        self.assertAlmostEqual(result["observed_shrinkage_pct"], 10.0, places=1)

    def test_unweighted_fallback_when_no_staff_column(self):
        # Equal rows: 3 productive, 1 non-productive → shrinkage = 25 %
        df = self._make_df(["Available", "Available", "Available", "Break"])
        result = compute_observed_shrinkage(df)
        self.assertTrue(result["has_activity_data"])
        self.assertAlmostEqual(result["observed_shrinkage_pct"], 25.0, places=1)

    # ── Unknown activities ────────────────────────────────────────────────────

    def test_unknown_excluded_from_shrinkage_numerator(self):
        # 6 productive, 2 non-productive, 2 unknown
        # Shrinkage = 2 / (6+2) = 25 %; coverage = 8/10 = 80 %
        df = self._make_df(
            ["Available", "Break", "SomeCustomActivity"],
            [6, 2, 2],
        )
        result = compute_observed_shrinkage(df)
        self.assertAlmostEqual(result["observed_shrinkage_pct"], 25.0, places=1)
        self.assertAlmostEqual(result["coverage_pct"], 80.0, places=1)

    def test_null_activities_classified_as_unknown(self):
        # 8 available, 2 null → coverage = 80 %, shrinkage = 0 %
        df = self._make_df(["Available", None], [8, 2])
        result = compute_observed_shrinkage(df)
        self.assertTrue(result["has_activity_data"])
        self.assertAlmostEqual(result["coverage_pct"], 80.0, places=1)
        self.assertEqual(result["observed_shrinkage_pct"], 0.0)

    # ── Activity breakdown ────────────────────────────────────────────────────

    def test_activity_breakdown_has_required_columns(self):
        df = self._make_df(["Available", "Break", "Training"], [10, 3, 2])
        result = compute_observed_shrinkage(df)
        breakdown = result["activity_breakdown"]
        self.assertFalse(breakdown.empty)
        for col in ["activity", "classification", "staff_weight", "pct_of_total"]:
            self.assertIn(col, breakdown.columns)

    def test_activity_breakdown_classifications_correct(self):
        df = self._make_df(["Available", "Break"], [7, 3])
        result = compute_observed_shrinkage(df)
        breakdown = result["activity_breakdown"].set_index("activity")
        self.assertEqual(breakdown.loc["Available", "classification"], "productive")
        self.assertEqual(breakdown.loc["Break", "classification"], "non_productive")


if __name__ == "__main__":
    unittest.main()
