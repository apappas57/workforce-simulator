from typing import Dict, Optional

import numpy as np
import pandas as pd

from simulation.des_simulation import simulate_day_des, simulate_day_des_v2


def _prepare_staffing_supply(staffing_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if staffing_df is None or staffing_df.empty:
        return pd.DataFrame(columns=["interval", "available_staff"])

    if "interval" not in staffing_df.columns or "available_staff" not in staffing_df.columns:
        return pd.DataFrame(columns=["interval", "available_staff"])

    out = staffing_df.copy()
    out["interval"] = pd.to_numeric(out["interval"], errors="coerce")
    out["available_staff"] = pd.to_numeric(out["available_staff"], errors="coerce").fillna(0.0)
    out = out.dropna(subset=["interval"]).copy()
    out["interval"] = out["interval"].astype(int)

    out = (
        out.groupby("interval", as_index=False)["available_staff"]
        .sum()
        .sort_values("interval")
        .reset_index(drop=True)
    )
    return out


def build_validate_df(
    *,
    df_det: pd.DataFrame,
    roster_df: Optional[pd.DataFrame],
    roster_scale: float,
    staffing_df: Optional[pd.DataFrame] = None,
    staffing_source: str = "Generated roster",
    activity_shrinkage_pct: float = 0.0,
) -> pd.DataFrame:
    validate_df = df_det.copy()

    if roster_df is not None and "interval" in roster_df.columns and "roster_net_agents" in roster_df.columns:
        validate_df = validate_df.merge(
            roster_df[["interval", "roster_net_agents"]],
            on="interval",
            how="left",
        )
    else:
        validate_df["roster_net_agents"] = 0.0

    validate_df["roster_net_agents"] = (
        pd.to_numeric(validate_df["roster_net_agents"], errors="coerce").fillna(0.0)
    )

    staffing_supply = _prepare_staffing_supply(staffing_df)

    if not staffing_supply.empty:
        validate_df = validate_df.merge(
            staffing_supply,
            on="interval",
            how="left",
        )
    else:
        validate_df["available_staff"] = 0.0

    validate_df["available_staff"] = (
        pd.to_numeric(validate_df["available_staff"], errors="coerce").fillna(0.0)
    )

    validate_df["activity_shrinkage_pct"] = float(activity_shrinkage_pct)
    validate_df["activity_loss_agents"] = (
        validate_df["available_staff"].astype(float) * validate_df["activity_shrinkage_pct"].astype(float)
    )
    validate_df["effective_available_staff"] = (
        validate_df["available_staff"].astype(float) - validate_df["activity_loss_agents"].astype(float)
    ).clip(lower=0.0)

    if staffing_source == "Imported staffing availability":
        source_curve = validate_df["available_staff"]
    elif staffing_source == "Imported effective staffing availability":
        source_curve = validate_df["effective_available_staff"]
    elif staffing_source == "Tighter of the two":
        source_curve = np.minimum(
            validate_df["roster_net_agents"].astype(float),
            validate_df["available_staff"].astype(float),
        )
    else:
        source_curve = validate_df["roster_net_agents"]

    validate_df["des_source_agents_raw"] = source_curve.astype(float)
    validate_df["des_staffing_source"] = staffing_source
    validate_df["staff_for_des"] = np.maximum(
        0,
        np.floor(validate_df["des_source_agents_raw"] * float(roster_scale))
    ).astype(int)

    keep_meta_cols = ["global_interval", "date_local", "interval_in_day", "start_ts_local"]
    for c in keep_meta_cols:
        if c in df_det.columns and c not in validate_df.columns:
            validate_df[c] = df_det[c].values

    return validate_df


def run_des_engine(
    *,
    des_engine: str,
    validate_df: pd.DataFrame,
    cfg,
    service_time_dist: str,
    enable_abandonment: bool,
    patience_dist: str,
    mean_patience_seconds: float,
    enable_breaks: bool = False,
    break_schedule: Optional[list] = None,
) -> Dict:
    if des_engine == "DES v2":
        return simulate_day_des_v2(
            validate_df,
            cfg=cfg,
            staff_col="staff_for_des",
            service_time_dist=service_time_dist,
            enable_abandonment=enable_abandonment,
            patience_dist=patience_dist,
            mean_patience_seconds=float(mean_patience_seconds),
            enable_breaks=enable_breaks,
            break_schedule=break_schedule,
        )

    return simulate_day_des(
        validate_df,
        cfg=cfg,
        staff_col="staff_for_des",
        service_time_dist=service_time_dist,
        enable_abandonment=enable_abandonment,
        patience_dist=patience_dist,
        mean_patience_seconds=float(mean_patience_seconds),
    )


def run_simulation(
    *,
    df_det: pd.DataFrame,
    roster_df: Optional[pd.DataFrame],
    roster_scale: float,
    des_engine: str,
    cfg,
    service_time_dist: str,
    enable_abandonment: bool,
    patience_dist: str,
    mean_patience_seconds: float,
    enable_breaks: bool = False,
    break_schedule: Optional[list] = None,
    staffing_df: Optional[pd.DataFrame] = None,
    staffing_source: str = "Generated roster",
    activity_shrinkage_pct: float = 0.0,
) -> Dict:
    """
    Central simulation wrapper.

    Responsibilities:
    1. Build the DES-ready validation dataframe
    2. Run the selected DES engine
    3. Return both the input dataframe used for simulation and the simulation output
    """

    validate_df = build_validate_df(
        df_det=df_det,
        roster_df=roster_df,
        roster_scale=roster_scale,
        staffing_df=staffing_df,
        staffing_source=staffing_source,
        activity_shrinkage_pct=float(activity_shrinkage_pct),
    )

    sim_out = run_des_engine(
        des_engine=des_engine,
        validate_df=validate_df,
        cfg=cfg,
        service_time_dist=service_time_dist,
        enable_abandonment=enable_abandonment,
        patience_dist=patience_dist,
        mean_patience_seconds=float(mean_patience_seconds),
        enable_breaks=enable_breaks,
        break_schedule=break_schedule,
    )

    return {
        "validate_df": validate_df,
        "sim_out": sim_out,
    }