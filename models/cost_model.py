"""models/cost_model.py

Per-interval and aggregate cost model — Phase 13.

Converts the outputs of the Erlang C, roster, DES, and planning engines
into financial metrics: labour cost, idle cost, SLA breach cost, cost per
call, and a monthly labour cost projection aligned with the planning engine.

Public API
----------
CostConfig                            : dataclass
calculate_interval_costs(...)         -> pd.DataFrame
calculate_cost_summary(...)           -> dict
project_monthly_labour_cost(...)      -> pd.DataFrame
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class CostConfig:
    """Financial parameters for the cost model.

    Attributes
    ----------
    hourly_agent_cost : float
        Effective all-in hourly cost per productive agent (local currency).
        Always in hourly terms — the sidebar converts annualised rates before
        constructing this object, so no conversion is needed here.
    penalty_per_abandoned : float
        Cost assigned to each abandoned call (SLA breach proxy / escalation
        cost). Set to 0.0 to exclude breach costs from totals.
    idle_rate_fraction : float
        Fraction of ``hourly_agent_cost`` applied to idle agent-time (surplus
        over the Erlang requirement). Default 1.0 — idle agents still earn
        their wage. Set < 1.0 if idle time has a partially productive use
        (back-office tasks, training, etc.).
    """

    hourly_agent_cost: float = 30.0
    penalty_per_abandoned: float = 8.0
    idle_rate_fraction: float = 1.0


# ---------------------------------------------------------------------------
# Per-interval cost calculation
# ---------------------------------------------------------------------------

def calculate_interval_costs(
    df_erlang: pd.DataFrame,
    cost_cfg: CostConfig,
    interval_minutes: float,
    roster_df: Optional[pd.DataFrame] = None,
    des_daily: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Compute a per-interval cost breakdown.

    Parameters
    ----------
    df_erlang : pd.DataFrame
        Output of ``solve_staffing_erlang()``.  Required columns:
        ``calls_offered``, ``erlang_required_net_agents``,
        ``erlang_pred_service_level``.
    cost_cfg : CostConfig
        Financial parameters.
    interval_minutes : float
        Duration of each simulation interval in minutes.
    roster_df : pd.DataFrame, optional
        Roster output containing ``roster_net_agents`` per ``interval``.
        When provided, rostered headcount drives labour cost; otherwise the
        Erlang net requirement is used as the staffing basis.
    des_daily : pd.DataFrame, optional
        DES daily summary (``st.session_state["des_daily_summary"]``). When
        present and contains ``daily_abandon_rate``, the empirical average
        abandon rate is used to estimate abandoned calls per interval.

    Returns
    -------
    pd.DataFrame
        One row per interval with columns:
        interval, [date_local, interval_in_day, start_ts_local if present],
        calls_offered, agents_required, agents_rostered,
        overstaffing, understaffing,
        abandoned_calls, labour_cost, idle_cost, sla_breach_cost,
        total_cost, cost_per_call.
    """
    if df_erlang.empty:
        return pd.DataFrame()

    df = df_erlang.copy()
    interval_hours = interval_minutes / 60.0

    # --- Staffing basis --------------------------------------------------- #
    df["agents_required"] = df["erlang_required_net_agents"].astype(float)

    roster_merged = False
    if (
        roster_df is not None
        and not roster_df.empty
        and "roster_net_agents" in roster_df.columns
        and "interval" in roster_df.columns
    ):
        r = roster_df[["interval", "roster_net_agents"]].copy()
        r = r.groupby("interval", as_index=False)["roster_net_agents"].sum()
        df = df.merge(r, on="interval", how="left")
        df["agents_rostered"] = df["roster_net_agents"].fillna(df["agents_required"])
        roster_merged = True

    if not roster_merged:
        df["agents_rostered"] = df["agents_required"]

    # --- Gap metrics ------------------------------------------------------ #
    df["overstaffing"]  = (df["agents_rostered"] - df["agents_required"]).clip(lower=0)
    df["understaffing"] = (df["agents_required"] - df["agents_rostered"]).clip(lower=0)

    # --- Abandoned call estimate ------------------------------------------ #
    # Prefer empirical DES abandon rate; fall back to Erlang SL gap.
    if (
        des_daily is not None
        and not des_daily.empty
        and "daily_abandon_rate" in des_daily.columns
    ):
        avg_abandon_rate = float(des_daily["daily_abandon_rate"].mean())
        df["abandoned_calls"] = df["calls_offered"] * avg_abandon_rate
    else:
        sl_gap = (1.0 - df["erlang_pred_service_level"].astype(float)).clip(lower=0)
        df["abandoned_calls"] = df["calls_offered"] * sl_gap

    # --- Cost components -------------------------------------------------- #
    df["labour_cost"] = (
        df["agents_rostered"] * cost_cfg.hourly_agent_cost * interval_hours
    ).round(4)

    df["idle_cost"] = (
        df["overstaffing"]
        * cost_cfg.hourly_agent_cost
        * cost_cfg.idle_rate_fraction
        * interval_hours
    ).round(4)

    df["sla_breach_cost"] = (
        df["abandoned_calls"] * cost_cfg.penalty_per_abandoned
    ).round(4)

    # Total cost = labour + SLA breach (idle is already embedded in labour)
    df["total_cost"] = (df["labour_cost"] + df["sla_breach_cost"]).round(4)

    # Cost per call handled (labour only — excludes breach penalty to avoid
    # double-counting the SLA effect in the per-unit metric)
    df["cost_per_call"] = np.where(
        df["calls_offered"] > 0,
        df["labour_cost"] / df["calls_offered"],
        0.0,
    ).round(4)

    keep_cols = [
        c for c in [
            "interval", "date_local", "interval_in_day", "start_ts_local",
            "calls_offered", "agents_required", "agents_rostered",
            "overstaffing", "understaffing",
            "abandoned_calls", "labour_cost", "idle_cost",
            "sla_breach_cost", "total_cost", "cost_per_call",
        ] if c in df.columns
    ]
    return df[keep_cols].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------

def calculate_cost_summary(cost_df: pd.DataFrame) -> dict:
    """Aggregate a per-interval cost DataFrame to a flat summary dict.

    Returns
    -------
    dict
        total_labour_cost, total_sla_breach_cost, total_idle_cost,
        total_cost, avg_cost_per_call, peak_interval_cost,
        idle_cost_pct, overstaffed_intervals_pct, understaffed_intervals_pct.
    """
    if cost_df.empty:
        return {}

    total_labour = float(cost_df["labour_cost"].sum())
    total_breach = float(cost_df["sla_breach_cost"].sum())
    total_idle   = float(cost_df["idle_cost"].sum())
    total_cost   = float(cost_df["total_cost"].sum())
    total_calls  = float(cost_df["calls_offered"].sum())
    n            = len(cost_df)

    return {
        "total_labour_cost":          round(total_labour, 2),
        "total_sla_breach_cost":      round(total_breach, 2),
        "total_idle_cost":            round(total_idle, 2),
        "total_cost":                 round(total_cost, 2),
        "avg_cost_per_call":          round(total_labour / total_calls, 4) if total_calls > 0 else 0.0,
        "peak_interval_cost":         round(float(cost_df["total_cost"].max()), 2),
        "idle_cost_pct":              round(total_idle / total_labour * 100, 1) if total_labour > 0 else 0.0,
        "overstaffed_intervals_pct":  round((cost_df["overstaffing"] > 0).mean() * 100, 1),
        "understaffed_intervals_pct": round((cost_df["understaffing"] > 0).mean() * 100, 1),
    }


# ---------------------------------------------------------------------------
# Monthly projection overlay
# ---------------------------------------------------------------------------

_WORKING_HOURS_PER_MONTH = 151.67  # 1,820 h/yr ÷ 12 (standard 35-hour week)


def project_monthly_labour_cost(
    planning_projection: pd.DataFrame,
    cost_cfg: CostConfig,
    working_hours_per_month: float = _WORKING_HOURS_PER_MONTH,
) -> pd.DataFrame:
    """Overlay monthly labour cost onto the workforce planning projection.

    Parameters
    ----------
    planning_projection : pd.DataFrame
        Output of ``project_workforce()``.  Requires ``available_fte`` and
        optionally ``required_fte``.
    cost_cfg : CostConfig
        Financial parameters — only ``hourly_agent_cost`` is used here.
    working_hours_per_month : float
        Productive hours per FTE per month.  Default 151.67 (1,820 h/yr ÷ 12).
        To use a custom annual figure pass ``annual_hours / 12``.

    Returns
    -------
    pd.DataFrame
        Input DataFrame with three additional columns:
        ``monthly_labour_cost``, ``monthly_required_cost``,
        ``monthly_cost_gap`` (positive = over-spend vs requirement).
    """
    if planning_projection.empty:
        return planning_projection

    df = planning_projection.copy()
    rate = cost_cfg.hourly_agent_cost * working_hours_per_month

    if "available_fte" in df.columns:
        df["monthly_labour_cost"] = (df["available_fte"] * rate).round(2)
    if "required_fte" in df.columns:
        df["monthly_required_cost"] = (df["required_fte"] * rate).round(2)
    if "monthly_labour_cost" in df.columns and "monthly_required_cost" in df.columns:
        df["monthly_cost_gap"] = (
            df["monthly_labour_cost"] - df["monthly_required_cost"]
        ).round(2)

    return df
