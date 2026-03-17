"""demand/demand_forecaster.py

Demand forecasting engine for Phase 11.

Approach
--------
1.  Aggregate historical interval data to daily total call volumes.
2.  Run STL decomposition (period = stl_period, default 7) on the daily series
    to separate trend and weekly seasonal components.
3.  Forecast future daily totals using STLForecast + ETS (additive error + trend).
4.  Distribute each forecasted daily total across intervals using the historical
    average intraday profile (each interval's average fraction of the day's calls).
5.  Scale confidence bounds by the same intraday proportions.

Public API
----------
ForecastParams : dataclass
forecast_demand(params: ForecastParams) -> pd.DataFrame
"""

import datetime
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

try:
    from statsmodels.tsa.forecasting.stl import STLForecast
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel
    _STATSMODELS_AVAILABLE = True
except ImportError:
    _STATSMODELS_AVAILABLE = False

try:
    from scipy import stats as _scipy_stats
    _SCIPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SCIPY_AVAILABLE = False


@dataclass
class ForecastParams:
    """Parameters for the demand forecasting engine.

    Attributes
    ----------
    historical_df : pd.DataFrame
        Historical demand data in the canonical demand schema.  Must contain at
        minimum the columns ``calls_offered``, ``date_local``, and
        ``interval_in_day``.  Produced by ``demand_loader.load_demand_csv``.
    horizon_days : int
        Number of future days to forecast.  Default 7.
    intervals_per_day : int
        Number of equal-length intervals in a day, e.g. 96 for 15-minute
        intervals.  Default 96.
    confidence_level : float
        Coverage of the prediction interval (0–1 exclusive).  Default 0.90.
    stl_period : int
        Seasonal period in days for STL decomposition.  Default 7 (weekly).
    min_history_days : int
        Minimum distinct calendar days required in ``historical_df``.
        STL needs at least ``2 * stl_period + 1`` observations, so this
        should be >= 2 * stl_period.  Default 14.
    """

    historical_df: pd.DataFrame
    horizon_days: int = 7
    intervals_per_day: int = 96
    confidence_level: float = 0.90
    stl_period: int = 7
    min_history_days: int = 14


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_params(params: ForecastParams) -> None:
    """Raise ValueError / ImportError for invalid or unusable params."""
    # Validate data structure first (independent of statsmodels availability).
    required = {"calls_offered", "date_local", "interval_in_day"}
    missing = required - set(params.historical_df.columns)
    if missing:
        raise ValueError(
            f"Historical data is missing required columns: {sorted(missing)}.  "
            "Upload a multi-day demand CSV using the standard format."
        )

    if not _STATSMODELS_AVAILABLE:
        raise ImportError(
            "statsmodels is required for demand forecasting. "
            "Install it with: pip install statsmodels"
        )

    if params.horizon_days < 1:
        raise ValueError("horizon_days must be at least 1.")

    if params.intervals_per_day < 1:
        raise ValueError("intervals_per_day must be at least 1.")

    if not (0.0 < params.confidence_level < 1.0):
        raise ValueError("confidence_level must be between 0 and 1 exclusive.")

    if params.stl_period < 2:
        raise ValueError("stl_period must be at least 2.")

    n_days = int(pd.to_datetime(params.historical_df["date_local"]).dt.date.nunique())
    min_required = max(params.min_history_days, 2 * params.stl_period + 1)
    if n_days < min_required:
        raise ValueError(
            f"At least {min_required} days of history are required for STL "
            f"with period={params.stl_period} (got {n_days} days).  "
            "Provide more historical data or reduce stl_period."
        )


def _build_intraday_profile(df: pd.DataFrame) -> np.ndarray:
    """Compute average intraday call proportion per interval_in_day.

    For each historical day, computes the fraction of that day's calls in each
    interval.  Returns the cross-day average as a 1-D array (sorted by
    interval_in_day) that sums to 1.0.

    Falls back to a uniform distribution if all volumes are zero.
    """
    df = df.copy()
    df["date_local"] = pd.to_datetime(df["date_local"]).dt.date
    day_totals = df.groupby("date_local")["calls_offered"].transform("sum")
    df["_prop"] = np.where(day_totals > 0, df["calls_offered"] / day_totals, 0.0)

    profile = (
        df.groupby("interval_in_day")["_prop"]
        .mean()
        .sort_index()
        .values
        .astype(float)
    )

    total = profile.sum()
    if total > 0:
        profile = profile / total
    else:
        n = len(profile)
        profile = np.full(n, 1.0 / n if n > 0 else 1.0)

    return profile


def _daily_series(df: pd.DataFrame) -> pd.Series:
    """Aggregate historical interval data to daily totals.

    Returns a pandas Series with a DatetimeIndex (one entry per calendar day),
    sorted ascending.
    """
    df = df.copy()
    df["date_local"] = pd.to_datetime(df["date_local"]).dt.date
    daily = (
        df.groupby("date_local")["calls_offered"]
        .sum()
        .sort_index()
    )
    daily.index = pd.DatetimeIndex(daily.index)
    return daily.astype(float)


def _run_stl_forecast(
    daily: pd.Series,
    horizon: int,
    period: int,
    confidence_level: float,
) -> pd.DataFrame:
    """Fit STLForecast + ETS and return horizon-step-ahead daily predictions.

    Returns a DataFrame with columns:
        date (datetime.date), forecast_daily, lower_daily, upper_daily.
    """
    alpha = 1.0 - confidence_level

    stlf = STLForecast(
        daily,
        ETSModel,
        model_kwargs={"error": "add", "trend": "add"},
        period=period,
    )
    import inspect as _inspect
    _fit_kwargs = {}
    if "disp" in _inspect.signature(stlf.fit).parameters:
        _fit_kwargs["disp"] = False
    result = stlf.fit(**_fit_kwargs)

    try:
        pred = result.get_prediction(
            start=len(daily),
            end=len(daily) + horizon - 1,
        )
        summary = pred.summary_frame(alpha=alpha)
        forecast_mean = summary["mean"].values
        lower = summary["mean_ci_lower"].values
        upper = summary["mean_ci_upper"].values
    except Exception:
        # Fallback: use forecast() + residual-based symmetric CI
        forecast_mean = result.forecast(horizon)
        residuals = daily.values - result.fittedvalues.values
        std_resid = float(np.nanstd(residuals))
        # z-score for two-sided CI — use scipy if available, else hardcoded approximations
        if _SCIPY_AVAILABLE:
            z = float(_scipy_stats.norm.ppf(0.5 + confidence_level / 2.0))
        else:
            _z_approx = {0.80: 1.2816, 0.90: 1.6449, 0.95: 1.9600, 0.99: 2.5758}
            z = _z_approx.get(float(confidence_level), 1.6449)
        lower = forecast_mean - z * std_resid
        upper = forecast_mean + z * std_resid

    last_date = daily.index[-1]
    forecast_dates = pd.date_range(
        start=last_date + pd.Timedelta(days=1),
        periods=horizon,
        freq="D",
    )

    return pd.DataFrame({
        "date": [d.date() for d in forecast_dates],
        "forecast_daily": np.clip(forecast_mean, 0, None),
        "lower_daily":    np.clip(lower,          0, None),
        "upper_daily":    np.clip(upper,          0, None),
    })


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def forecast_demand(params: ForecastParams) -> pd.DataFrame:
    """Forecast interval-level call demand over a future horizon.

    Parameters
    ----------
    params : ForecastParams
        Forecast configuration and historical demand data.

    Returns
    -------
    pd.DataFrame
        One row per forecast interval.  Columns:

        - ``date_local``      (datetime.date)
        - ``interval_in_day`` (int, 0-based)
        - ``global_interval`` (int, 0-based from start of forecast window)
        - ``calls_offered``   (float, point forecast — plugs directly into
                               the simulation pipeline)
        - ``calls_lower``     (float, lower confidence bound)
        - ``calls_upper``     (float, upper confidence bound)

        The ``calls_offered`` column uses the point forecast so that the
        DataFrame is a drop-in replacement for the ``df_inputs`` produced by
        ``demand_loader.load_demand_csv``.
    """
    _validate_params(params)

    df = params.historical_df.copy()
    df["date_local"] = pd.to_datetime(df["date_local"]).dt.date

    # Intraday profile from history
    profile = _build_intraday_profile(df)
    n_hist_intervals = len(profile)

    # If historical data has a different interval count than requested,
    # interpolate the profile to the requested resolution.
    if n_hist_intervals != params.intervals_per_day:
        old_x = np.linspace(0.0, 1.0, n_hist_intervals)
        new_x = np.linspace(0.0, 1.0, params.intervals_per_day)
        profile = np.interp(new_x, old_x, profile)
        total = profile.sum()
        if total > 0:
            profile = profile / total

    # Daily forecast
    daily = _daily_series(df)
    daily_fc = _run_stl_forecast(
        daily,
        horizon=params.horizon_days,
        period=params.stl_period,
        confidence_level=params.confidence_level,
    )

    # Expand to interval level
    rows = []
    for day_idx, row in enumerate(daily_fc.itertuples(index=False)):
        for interval_idx in range(params.intervals_per_day):
            p = float(profile[interval_idx])
            rows.append({
                "date_local":      row.date,
                "interval_in_day": interval_idx,
                "global_interval": day_idx * params.intervals_per_day + interval_idx,
                "calls_offered":   max(0.0, row.forecast_daily * p),
                "calls_lower":     max(0.0, row.lower_daily * p),
                "calls_upper":     max(0.0, row.upper_daily * p),
            })

    result = pd.DataFrame(rows)
    result["calls_offered"] = result["calls_offered"].round(2)
    result["calls_lower"]   = result["calls_lower"].round(2)
    result["calls_upper"]   = result["calls_upper"].round(2)

    return result
