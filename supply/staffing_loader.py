from zoneinfo import ZoneInfo
from typing import Dict, Optional

import numpy as np
import pandas as pd


CANONICAL_REQUIRED_INTERVAL = {"interval", "available_staff"}
CANONICAL_REQUIRED_TS = {"start_ts", "available_staff"}

COLUMN_SYNONYMS = {
    "interval": [
        "interval",
        "interval_index",
        "timeslot",
        "slot",
    ],
    "start_ts": [
        "start_ts",
        "timestamp",
        "start_time",
        "datetime",
        "interval_start",
    ],
    "available_staff": [
        "available_staff",
        "staff",
        "staff_available",
        "agents",
        "available_agents",
        "fte",
        "heads",
    ],
    "team": [
        "team",
        "department",
        "business_unit",
    ],
    "queue": [
        "queue",
        "skill",
        "channel",
    ],
    "activity": [
        "activity",
        "work_type",
        "state",
    ],
    "paid_hours": [
        "paid_hours",
        "hours_paid",
    ],
    "notes": [
        "notes",
        "comment",
        "comments",
    ],
}


def _normalise_colname(name: str) -> str:
    return str(name).strip().lower().replace(" ", "_")


def _coerce_numeric(series: pd.Series, col: str) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    if out.isna().any():
        bad = series[out.isna()].head(5).tolist()
        raise ValueError(f"Column '{col}' has non-numeric values (examples): {bad}")
    return out


def infer_staffing_column_mapping(df: pd.DataFrame) -> Dict[str, str]:
    normalised_lookup = {_normalise_colname(c): c for c in df.columns}
    mapping: Dict[str, str] = {}

    for canonical, candidates in COLUMN_SYNONYMS.items():
        for candidate in candidates:
            if candidate in normalised_lookup:
                mapping[canonical] = normalised_lookup[candidate]
                break

    return mapping


def apply_staffing_column_mapping(
    df: pd.DataFrame,
    mapping: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    mapping = mapping or infer_staffing_column_mapping(df)

    rename_map = {}
    for canonical, source_col in mapping.items():
        if source_col in df.columns:
            rename_map[source_col] = canonical

    out = df.rename(columns=rename_map).copy()
    return out


def validate_staffing_columns(df: pd.DataFrame) -> None:
    cols = set(df.columns)

    has_interval = CANONICAL_REQUIRED_INTERVAL.issubset(cols)
    has_ts = CANONICAL_REQUIRED_TS.issubset(cols)

    if not has_interval and not has_ts:
        raise ValueError(
            "Staffing CSV must contain either:\n"
            "  - interval + available_staff\n"
            "  - OR start_ts + available_staff"
        )


def load_staffing_csv(
    file,
    input_tz: str = "UTC",
    model_tz: str = "Australia/Melbourne",
    column_mapping: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    df = pd.read_csv(file)
    df.columns = [str(c).strip() for c in df.columns]

    df = apply_staffing_column_mapping(df, mapping=column_mapping)
    validate_staffing_columns(df)

    if "available_staff" in df.columns:
        df["available_staff"] = _coerce_numeric(df["available_staff"], "available_staff").astype(float)

    if "paid_hours" in df.columns:
        df["paid_hours"] = _coerce_numeric(df["paid_hours"], "paid_hours").astype(float)

    if "interval" in df.columns:
        out = df.copy()
        out["interval"] = _coerce_numeric(out["interval"], "interval").astype(int)
        out = out.sort_values("interval").reset_index(drop=True)

        out["global_interval"] = out["interval"].astype(int)
        out["interval_in_day"] = out["interval"].astype(int)
        out["date_local"] = "staffing_interval_input"
        out["start_ts_local"] = pd.NaT

    else:
        out = df.copy()
        out["start_ts"] = pd.to_datetime(out["start_ts"], errors="coerce", utc=False)

        if out["start_ts"].isna().any():
            bad = out.loc[out["start_ts"].isna(), "start_ts"].head(5).tolist()
            raise ValueError(f"Column 'start_ts' has invalid timestamps (examples): {bad}")

        if out["start_ts"].dt.tz is None:
            out["start_ts"] = out["start_ts"].dt.tz_localize(ZoneInfo(input_tz))
        else:
            out["start_ts"] = out["start_ts"].dt.tz_convert(ZoneInfo(input_tz))

        out["start_ts_local"] = out["start_ts"].dt.tz_convert(ZoneInfo(model_tz))
        out = out.sort_values("start_ts_local").reset_index(drop=True)

        if out["start_ts_local"].duplicated().any():
            raise ValueError("Duplicate start_ts values found after timezone conversion.")

        out["date_local"] = out["start_ts_local"].dt.date.astype(str)
        out["interval_in_day"] = out.groupby("date_local").cumcount().astype(int)
        out["global_interval"] = np.arange(len(out), dtype=int)
        out["interval"] = out["global_interval"]

    canonical_cols = [
        "interval",
        "global_interval",
        "interval_in_day",
        "date_local",
        "start_ts_local",
        "available_staff",
        "team",
        "queue",
        "activity",
        "paid_hours",
        "notes",
    ]

    for col in canonical_cols:
        if col not in out.columns:
            out[col] = pd.NA

    out["source_file"] = getattr(file, "name", "uploaded_staffing_file.csv")

    return out[canonical_cols + ["source_file"]]


def validate_staffing_data(df: pd.DataFrame) -> None:
    if (df["available_staff"].astype(float) < 0).any():
        raise ValueError("available_staff cannot be negative.")

    if "start_ts_local" in df.columns and df["start_ts_local"].notna().any():
        if df["start_ts_local"].duplicated().any():
            raise ValueError("Duplicate start_ts values found after timezone conversion.")
    else:
        if df["interval"].duplicated().any():
            raise ValueError("Duplicate interval values found in staffing input.")