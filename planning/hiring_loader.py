"""planning/hiring_loader.py

Loaders for Phase 7 planning CSV inputs:
  - hiring_plan.csv        (period_start, planned_hires)
  - required_fte_plan.csv  (period_start, required_fte)

Both files use monthly granularity.  period_start should be the first day of
each month in YYYY-MM-DD format, but the loader only requires a parseable date
— it does not enforce day=1 so that partial-month overrides remain possible
in future phases.
"""

import pandas as pd


def _normalise_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def _parse_and_sort_period_start(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Parse period_start to Timestamp, validate, sort, and reset index."""
    df = df.copy()
    df["period_start"] = pd.to_datetime(df["period_start"], errors="coerce")
    if df["period_start"].isna().any():
        raise ValueError(
            f"{source}: some period_start values could not be parsed as dates. "
            "Use YYYY-MM-DD format (e.g. 2026-01-01)."
        )
    if df["period_start"].duplicated().any():
        dupes = df.loc[df["period_start"].duplicated(keep=False), "period_start"].unique()
        raise ValueError(
            f"{source}: duplicate period_start values found: "
            + ", ".join(str(d) for d in sorted(dupes))
        )
    return df.sort_values("period_start").reset_index(drop=True)


def load_hiring_plan(file) -> pd.DataFrame:
    """Load and validate a hiring_plan.csv file.

    Expected columns
    ----------------
    period_start  – first day of the planning month (YYYY-MM-DD)
    planned_hires – non-negative integer; months absent from the file default
                    to zero hires in the projection engine.

    Returns
    -------
    DataFrame with columns: period_start (Timestamp), planned_hires (int).
    Sorted ascending by period_start, no duplicates.
    """
    df = pd.read_csv(file)
    df = _normalise_cols(df)

    required = {"period_start", "planned_hires"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"hiring_plan.csv is missing required columns: {sorted(missing)}. "
            "File must contain: period_start, planned_hires"
        )

    df = _parse_and_sort_period_start(df, "hiring_plan.csv")

    df["planned_hires"] = pd.to_numeric(df["planned_hires"], errors="coerce")
    if df["planned_hires"].isna().any():
        raise ValueError(
            "hiring_plan.csv: planned_hires contains non-numeric values."
        )
    if (df["planned_hires"] < 0).any():
        raise ValueError(
            "hiring_plan.csv: planned_hires cannot be negative."
        )
    df["planned_hires"] = df["planned_hires"].astype(int)

    return df[["period_start", "planned_hires"]]


def load_required_fte_plan(file) -> pd.DataFrame:
    """Load and validate a required_fte_plan.csv file.

    Expected columns
    ----------------
    period_start  – first day of the planning month (YYYY-MM-DD)
    required_fte  – non-negative float representing the minimum available FTE
                    needed to meet demand in that period.

    Returns
    -------
    DataFrame with columns: period_start (Timestamp), required_fte (float).
    Sorted ascending by period_start, no duplicates.
    """
    df = pd.read_csv(file)
    df = _normalise_cols(df)

    required = {"period_start", "required_fte"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"required_fte_plan.csv is missing required columns: {sorted(missing)}. "
            "File must contain: period_start, required_fte"
        )

    df = _parse_and_sort_period_start(df, "required_fte_plan.csv")

    df["required_fte"] = pd.to_numeric(df["required_fte"], errors="coerce")
    if df["required_fte"].isna().any():
        raise ValueError(
            "required_fte_plan.csv: required_fte contains non-numeric values."
        )
    if (df["required_fte"] < 0).any():
        raise ValueError(
            "required_fte_plan.csv: required_fte cannot be negative."
        )

    return df[["period_start", "required_fte"]]
