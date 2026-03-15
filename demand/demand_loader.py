from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


REQUIRED_DEMAND_A = {"interval", "calls_offered"}
REQUIRED_DEMAND_B = {"start_ts", "calls_offered"}


def _coerce_numeric(series: pd.Series, col: str) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    if out.isna().any():
        bad = series[out.isna()].head(5).tolist()
        raise ValueError(f"Column '{col}' has non-numeric values (examples): {bad}")
    return out


def load_demand_csv(file, input_tz: str = "UTC", model_tz: str = "Australia/Melbourne") -> pd.DataFrame:
    df = pd.read_csv(file)
    df.columns = [c.strip() for c in df.columns]
    cols = set(df.columns)

    if REQUIRED_DEMAND_A.issubset(cols):
        df = df.copy()
        df["interval"] = _coerce_numeric(df["interval"], "interval").astype(int)
        df["calls_offered"] = _coerce_numeric(df["calls_offered"], "calls_offered").astype(float)

        if "aht_seconds" in df.columns:
            df["aht_seconds"] = _coerce_numeric(df["aht_seconds"], "aht_seconds").astype(float)

        df = df.sort_values("interval").reset_index(drop=True)

        # Backward-compatible canonical time keys
        df["global_interval"] = df["interval"].astype(int)
        df["interval_in_day"] = df["interval"].astype(int)
        df["date_local"] = None
        return df

    if REQUIRED_DEMAND_B.issubset(cols):
        df = df.copy()
        df["start_ts"] = pd.to_datetime(df["start_ts"], errors="coerce", utc=False)

        if df["start_ts"].isna().any():
            bad = df.loc[df["start_ts"].isna(), "start_ts"].head(5).tolist()
            raise ValueError(f"Column 'start_ts' has invalid timestamps (examples): {bad}")

        if df["start_ts"].dt.tz is None:
            df["start_ts"] = df["start_ts"].dt.tz_localize(ZoneInfo(input_tz))
        else:
            df["start_ts"] = df["start_ts"].dt.tz_convert(ZoneInfo(input_tz))

        df["start_ts_local"] = df["start_ts"].dt.tz_convert(ZoneInfo(model_tz))
        df = df.sort_values("start_ts_local").reset_index(drop=True)
        if df["start_ts_local"].duplicated().any():
            raise ValueError("Duplicate start_ts values found after timezone conversion.")

        df["date_local"] = df["start_ts_local"].dt.date.astype(str)
        df["time_local"] = df["start_ts_local"].dt.strftime("%H:%M")
        df["interval_in_day"] = df.groupby("date_local").cumcount().astype(int)
        df["global_interval"] = np.arange(len(df), dtype=int)

        # Preserve compatibility with the rest of the app
        df["interval"] = df["global_interval"]

        df["calls_offered"] = _coerce_numeric(df["calls_offered"], "calls_offered").astype(float)

        if "aht_seconds" in df.columns:
            df["aht_seconds"] = _coerce_numeric(df["aht_seconds"], "aht_seconds").astype(float)

        return df

    raise ValueError(
        "Demand CSV must contain either:\n"
        "  - interval, calls_offered\n"
        "  - OR start_ts, calls_offered\n"
        "Optional: aht_seconds"
    )


def validate_demand(df: pd.DataFrame) -> None:
    if (df["calls_offered"] < 0).any():
        raise ValueError("calls_offered cannot be negative.")
    if "aht_seconds" in df.columns and (df["aht_seconds"] <= 0).any():
        raise ValueError("aht_seconds must be > 0 if provided.")
    if "start_ts_local" in df.columns:
        if df["start_ts_local"].duplicated().any():
            raise ValueError("Duplicate start_ts values found after timezone conversion.")
    else:
        if df["interval"].duplicated().any():
            raise ValueError("Duplicate interval values found.")


def build_synthetic_day(num_intervals: int, avg_calls: float) -> pd.DataFrame:
    x = np.arange(num_intervals)
    curve = avg_calls + 0.6 * avg_calls * np.sin((x - num_intervals * 0.25) / num_intervals * 2 * np.pi)
    curve = np.clip(curve, 0, None)

    out = pd.DataFrame({"interval": x, "calls_offered": curve})
    out["global_interval"] = out["interval"].astype(int)
    out["interval_in_day"] = out["interval"].astype(int)
    out["date_local"] = None
    return out