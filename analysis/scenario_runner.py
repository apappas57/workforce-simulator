from typing import Dict, Optional
import pandas as pd

from simulation.des_runner import run_simulation
from optimisation.staffing_solver import solve_staffing_to_target


def run_scenario(
    *,
    df_det: pd.DataFrame,
    roster_df: Optional[pd.DataFrame],
    roster_scale: float,
    cfg,
    des_engine: str,
    service_time_dist: str,
    enable_abandonment: bool,
    patience_dist: str,
    mean_patience_seconds: float,
    enable_breaks: bool,
    break_schedule,
    staffing_df: Optional[pd.DataFrame] = None,
    staffing_source: str = "Generated roster",
    volume_multiplier: float = 1.0,
    aht_multiplier: float = 1.0,
    patience_multiplier: float = 1.0,
    run_solver: bool = True,
) -> Dict:
    """
    Runs a simulation scenario by applying demand shocks and optionally
    running the staffing solver.

    Scenario shocks include:
        volume multiplier
        AHT multiplier
        patience multiplier
    """

    scenario_df = df_det.copy()

    if "calls_offered" in scenario_df.columns:
        scenario_df["calls_offered"] = (
            scenario_df["calls_offered"].astype(float) * float(volume_multiplier)
        )

    if "aht_seconds_used" in scenario_df.columns:
        scenario_df["aht_seconds_used"] = (
            scenario_df["aht_seconds_used"].astype(float) * float(aht_multiplier)
        )
    elif "aht_seconds" in scenario_df.columns:
        scenario_df["aht_seconds"] = (
            scenario_df["aht_seconds"].astype(float) * float(aht_multiplier)
        )

    scenario_patience = mean_patience_seconds * patience_multiplier

    sim_run = run_simulation(
        df_det=scenario_df,
        roster_df=roster_df,
        roster_scale=roster_scale,
        des_engine=des_engine,
        cfg=cfg,
        service_time_dist=service_time_dist,
        enable_abandonment=enable_abandonment,
        patience_dist=patience_dist,
        mean_patience_seconds=scenario_patience,
        enable_breaks=enable_breaks,
        break_schedule=break_schedule,
        staffing_df=staffing_df,
        staffing_source=staffing_source,
    )

    validate_df = sim_run["validate_df"]
    sim_out = sim_run["sim_out"]

    if not run_solver:
        return {
            "scenario_validate_df": validate_df,
            "scenario_sim_out": sim_out,
            "solver_result": None,
        }

    solver_result = solve_staffing_to_target(
        base_validate_df=validate_df,
        cfg=cfg,
        service_time_dist=service_time_dist,
        enable_abandonment=enable_abandonment,
        patience_dist=patience_dist,
        mean_patience_seconds=scenario_patience,
        enable_breaks=enable_breaks,
        break_schedule=break_schedule,
        des_engine=des_engine,
    )

    return {
        "scenario_validate_df": validate_df,
        "scenario_sim_out": sim_out,
        "solver_result": solver_result,
    }