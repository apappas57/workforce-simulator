"""tests/test_demand_forecaster.py

Unit tests for demand/demand_forecaster.py — Phase 11 STL demand forecasting.

Tests are divided into:
  - TestValidateParams    — parameter validation before computation
  - TestIntradayProfile   — intraday proportion calculation
  - TestDailySeries       — daily aggregation helper
  - TestForecastDemand    — full forecast integration (requires statsmodels)

Tests requiring statsmodels are skipped gracefully when it is not installed.
"""

import datetime
import unittest

import numpy as np
import pandas as pd

try:
    from demand.demand_forecaster import (
        ForecastParams,
        _build_intraday_profile,
        _daily_series,
        _validate_params,
        forecast_demand,
    )
    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False

try:
    import statsmodels  # noqa: F401
    _STATSMODELS_AVAILABLE = True
except ImportError:
    _STATSMODELS_AVAILABLE = False


def _make_historical_df(n_days: int = 21, intervals_per_day: int = 96) -> pd.DataFrame:
    """Build a synthetic multi-day demand DataFrame with a simple weekly pattern."""
    rng = np.random.default_rng(42)
    rows = []
    base_date = datetime.date(2025, 1, 1)
    for day_idx in range(n_days):
        d = base_date + datetime.timedelta(days=day_idx)
        # Day-of-week multiplier (Mon=highest, Sun=lowest)
        dow_mult = 1.0 - 0.05 * d.weekday()
        daily_total = 1000 * dow_mult
        for i in range(intervals_per_day):
            # Simple bell-curve intraday profile
            prop = np.exp(-0.5 * ((i - intervals_per_day * 0.5) / (intervals_per_day * 0.15)) ** 2)
            calls = max(0.0, daily_total * prop / intervals_per_day + rng.normal(0, 0.5))
            rows.append({"date_local": d, "interval_in_day": i, "calls_offered": calls})
    return pd.DataFrame(rows)


@unittest.skipUnless(_MODULE_AVAILABLE, "demand_forecaster module not available")
class TestValidateParams(unittest.TestCase):

    def _base_params(self, n_days=21):
        return ForecastParams(
            historical_df=_make_historical_df(n_days),
            horizon_days=7,
            intervals_per_day=96,
        )

    @unittest.skipUnless(_STATSMODELS_AVAILABLE, "statsmodels not installed")
    def test_valid_params_do_not_raise(self):
        _validate_params(self._base_params())

    def test_missing_calls_offered_raises(self):
        df = _make_historical_df().drop(columns=["calls_offered"])
        params = ForecastParams(historical_df=df)
        with self.assertRaises(ValueError) as ctx:
            _validate_params(params)
        self.assertIn("calls_offered", str(ctx.exception))

    def test_missing_date_local_raises(self):
        df = _make_historical_df().drop(columns=["date_local"])
        params = ForecastParams(historical_df=df)
        with self.assertRaises(ValueError):
            _validate_params(params)

    def test_missing_interval_in_day_raises(self):
        df = _make_historical_df().drop(columns=["interval_in_day"])
        params = ForecastParams(historical_df=df)
        with self.assertRaises(ValueError):
            _validate_params(params)

    @unittest.skipUnless(_STATSMODELS_AVAILABLE, "statsmodels not installed")
    def test_insufficient_history_raises(self):
        params = ForecastParams(
            historical_df=_make_historical_df(n_days=5),
            min_history_days=14,
        )
        with self.assertRaises(ValueError) as ctx:
            _validate_params(params)
        self.assertIn("history", str(ctx.exception).lower())

    @unittest.skipUnless(_STATSMODELS_AVAILABLE, "statsmodels not installed")
    def test_horizon_zero_raises(self):
        params = ForecastParams(
            historical_df=_make_historical_df(),
            horizon_days=0,
        )
        with self.assertRaises(ValueError):
            _validate_params(params)

    @unittest.skipUnless(_STATSMODELS_AVAILABLE, "statsmodels not installed")
    def test_invalid_confidence_level_raises(self):
        params = ForecastParams(
            historical_df=_make_historical_df(),
            confidence_level=1.5,
        )
        with self.assertRaises(ValueError):
            _validate_params(params)


@unittest.skipUnless(_MODULE_AVAILABLE, "demand_forecaster module not available")
class TestIntradayProfile(unittest.TestCase):

    def _df_uniform(self, intervals_per_day=8, n_days=7) -> pd.DataFrame:
        """DataFrame where all intervals have equal calls — profile should be uniform."""
        rows = []
        base = datetime.date(2025, 1, 1)
        for d in range(n_days):
            for i in range(intervals_per_day):
                rows.append({
                    "date_local": base + datetime.timedelta(days=d),
                    "interval_in_day": i,
                    "calls_offered": 10.0,
                })
        return pd.DataFrame(rows)

    def test_profile_sums_to_one(self):
        df = _make_historical_df(n_days=7, intervals_per_day=96)
        profile = _build_intraday_profile(df)
        self.assertAlmostEqual(float(profile.sum()), 1.0, places=6)

    def test_uniform_calls_give_uniform_profile(self):
        df = self._df_uniform(intervals_per_day=8)
        profile = _build_intraday_profile(df)
        expected = 1.0 / 8
        for p in profile:
            self.assertAlmostEqual(float(p), expected, places=6)

    def test_profile_length_matches_intervals(self):
        for n in [24, 48, 96]:
            df = _make_historical_df(intervals_per_day=n, n_days=7)
            profile = _build_intraday_profile(df)
            self.assertEqual(len(profile), n)

    def test_zero_volume_fallback_is_uniform(self):
        df = _make_historical_df(n_days=7)
        df["calls_offered"] = 0.0
        profile = _build_intraday_profile(df)
        self.assertAlmostEqual(float(profile.sum()), 1.0, places=6)
        # All values should be equal
        self.assertAlmostEqual(float(profile.std()), 0.0, places=6)

    def test_profile_values_non_negative(self):
        df = _make_historical_df(n_days=14)
        profile = _build_intraday_profile(df)
        self.assertTrue((profile >= 0).all())


@unittest.skipUnless(_MODULE_AVAILABLE, "demand_forecaster module not available")
class TestDailySeries(unittest.TestCase):

    def test_output_is_series(self):
        df = _make_historical_df(n_days=14)
        result = _daily_series(df)
        self.assertIsInstance(result, pd.Series)

    def test_one_entry_per_day(self):
        df = _make_historical_df(n_days=14)
        result = _daily_series(df)
        self.assertEqual(len(result), 14)

    def test_index_is_datetime(self):
        df = _make_historical_df(n_days=7)
        result = _daily_series(df)
        self.assertIsInstance(result.index, pd.DatetimeIndex)

    def test_daily_totals_correct(self):
        """Manual 2-day dataset: verify totals sum correctly."""
        d1 = datetime.date(2025, 1, 1)
        d2 = datetime.date(2025, 1, 2)
        df = pd.DataFrame([
            {"date_local": d1, "interval_in_day": 0, "calls_offered": 100.0},
            {"date_local": d1, "interval_in_day": 1, "calls_offered": 200.0},
            {"date_local": d2, "interval_in_day": 0, "calls_offered": 50.0},
            {"date_local": d2, "interval_in_day": 1, "calls_offered": 75.0},
        ])
        result = _daily_series(df)
        self.assertAlmostEqual(float(result.iloc[0]), 300.0)
        self.assertAlmostEqual(float(result.iloc[1]), 125.0)


@unittest.skipUnless(_MODULE_AVAILABLE, "demand_forecaster module not available")
@unittest.skipUnless(_STATSMODELS_AVAILABLE, "statsmodels not installed")
class TestForecastDemand(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.hist_df = _make_historical_df(n_days=28, intervals_per_day=24)
        cls.params = ForecastParams(
            historical_df=cls.hist_df,
            horizon_days=7,
            intervals_per_day=24,
            confidence_level=0.90,
            stl_period=7,
            min_history_days=14,
        )
        cls.result = forecast_demand(cls.params)

    def test_returns_dataframe(self):
        self.assertIsInstance(self.result, pd.DataFrame)

    def test_correct_row_count(self):
        expected = self.params.horizon_days * self.params.intervals_per_day
        self.assertEqual(len(self.result), expected)

    def test_required_columns_present(self):
        for col in ("date_local", "interval_in_day", "global_interval",
                    "calls_offered", "calls_lower", "calls_upper"):
            self.assertIn(col, self.result.columns, f"Missing column: {col}")

    def test_calls_offered_non_negative(self):
        self.assertTrue((self.result["calls_offered"] >= 0).all())

    def test_lower_bound_lte_point_forecast(self):
        self.assertTrue((self.result["calls_lower"] <= self.result["calls_offered"] + 1e-6).all())

    def test_upper_bound_gte_point_forecast(self):
        self.assertTrue((self.result["calls_upper"] >= self.result["calls_offered"] - 1e-6).all())

    def test_global_interval_sequential(self):
        expected = list(range(self.params.horizon_days * self.params.intervals_per_day))
        self.assertEqual(list(self.result["global_interval"]), expected)

    def test_correct_number_of_distinct_days(self):
        self.assertEqual(self.result["date_local"].nunique(), self.params.horizon_days)

    def test_interval_in_day_range(self):
        self.assertEqual(int(self.result["interval_in_day"].min()), 0)
        self.assertEqual(
            int(self.result["interval_in_day"].max()),
            self.params.intervals_per_day - 1,
        )

    def test_daily_totals_reasonable(self):
        """Point forecast daily totals should be in a plausible range vs history."""
        hist_daily_avg = float(
            self.hist_df.groupby("date_local")["calls_offered"].sum().mean()
        )
        fc_daily = self.result.groupby("date_local")["calls_offered"].sum()
        fc_daily_avg = float(fc_daily.mean())
        # Forecast should be within 3× of historical average (very loose sanity check)
        self.assertLess(fc_daily_avg, hist_daily_avg * 3)
        self.assertGreater(fc_daily_avg, 0)


if __name__ == "__main__":
    unittest.main()
