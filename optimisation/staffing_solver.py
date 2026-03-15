from typing import Dict, Optional

import numpy as np
import pandas as pd

from simulation.des_runner import run_des_engine


def solve_staffing_to_target(
    *,
    base_validate_df: pd.DataFrame,
    cfg,
    service_time_dist: str,
    enable_abandonment: bool,
    patience_dist: str,
    mean_patience_seconds: float,
    enable_breaks: bool = False,
    break_schedule: Optional[list] = None,
    des_engine: str = "DES v2",
    target_service_level: Optional[float] = None,
    max_iterations: int = 25,
    add_step: int = 1,
    max_abandon_rate: float = 0.05,
    stagnation_rounds: int = 3,
    min_improvement: float = 0.002,
) -> Dict:
    """
    Iteratively adds staffing to intervals where service level is weak until the
    overall target service level is reached or iteration limit is hit.

    Returns:
        {
            "solved_validate_df": pd.DataFrame,
            "final_sim_out": dict,
            "iterations_used": int,
            "target_met": bool,
            "staffing_curve": pd.DataFrame,
        }
    """

    if target_service_level is None:
        target_service_level = float(cfg.sl_target)

    target_abandon_rate = float(max_abandon_rate)

    work_df = base_validate_df.copy()
    work_df["staff_for_des"] = work_df["staff_for_des"].fillna(0).astype(int)

    final_sim_out = None
    target_met = False
    iterations_used = 0

    prev_overall_sl = None
    stagnant_count = 0

    for iteration in range(1, max_iterations + 1):
        sim_out = run_des_engine(
            des_engine=des_engine,
            validate_df=work_df,
            cfg=cfg,
            service_time_dist=service_time_dist,
            enable_abandonment=enable_abandonment,
            patience_dist=patience_dist,
            mean_patience_seconds=float(mean_patience_seconds),
            enable_breaks=enable_breaks,
            break_schedule=break_schedule,
        )

        interval_kpis = sim_out["interval_kpis"].copy()
        overall = sim_out["overall"]

        final_sim_out = sim_out
        iterations_used = iteration

        overall_sl = float(overall.get("sim_service_level", 0.0))
        overall_abandon = float(overall.get("sim_abandon_rate", 1.0))

        if overall_sl >= target_service_level and overall_abandon <= max_abandon_rate:
            target_met = True
            break

        if prev_overall_sl is not None:
            improvement = overall_sl - prev_overall_sl
            if improvement < float(min_improvement):
                stagnant_count += 1
            else:
                stagnant_count = 0

            if stagnant_count >= int(stagnation_rounds):
                break

        prev_overall_sl = overall_sl

        # Identify weak intervals using both SL and abandonment
        interval_sl = interval_kpis["sim_service_level"].fillna(0.0).astype(float)
        interval_calls = interval_kpis["sim_calls"].fillna(0).astype(float)
        interval_abandon = interval_kpis["sim_abandon_rate"].fillna(0.0).astype(float)

        failing_mask = (interval_calls > 0) & (
            (interval_sl < target_service_level) |
            (interval_abandon > target_abandon_rate)
        )

        if not failing_mask.any():
            fallback_mask = interval_calls > 0
            if fallback_mask.any():
                work_df.loc[fallback_mask, "staff_for_des"] += int(add_step)
            else:
                break
        else:
            failing_idx = np.where(failing_mask.to_numpy())[0]

            increments = np.zeros(len(work_df), dtype=int)

            interval_sl_gap = (float(target_service_level) - interval_sl).clip(lower=0.0)

            for idx in failing_idx:
                gap = float(interval_sl_gap.iloc[idx])
                aband = float(interval_abandon.iloc[idx])
                calls = float(interval_calls.iloc[idx])

                # adaptive main step:
                # bigger uplift for larger SL gap, high abandon, and heavier volume
                dynamic_step = int(add_step)

                if gap >= 0.30:
                    dynamic_step += 3
                elif gap >= 0.15:
                    dynamic_step += 2
                elif gap >= 0.05:
                    dynamic_step += 1

                if aband >= 0.20:
                    dynamic_step += 2
                elif aband >= 0.10:
                    dynamic_step += 1

                if calls >= 150:
                    dynamic_step += 2
                elif calls >= 75:
                    dynamic_step += 1

                increments[idx] += dynamic_step

                neighbour_step = max(1, int(np.ceil(dynamic_step / 3)))

                if idx - 1 >= 0:
                    increments[idx - 1] += neighbour_step
                if idx + 1 < len(increments):
                    increments[idx + 1] += neighbour_step

            work_df["staff_for_des"] = work_df["staff_for_des"] + increments

    staffing_curve = work_df[["interval", "staff_for_des"]].copy()
    staffing_curve = staffing_curve.rename(columns={"staff_for_des": "required_staff_for_des"})

    return {
        "solved_validate_df": work_df,
        "final_sim_out": final_sim_out,
        "iterations_used": iterations_used,
        "target_met": target_met,
        "staffing_curve": staffing_curve,
        "final_overall_service_level": float(final_sim_out["overall"].get("sim_service_level", 0.0)) if final_sim_out else 0.0,
        "final_overall_abandon_rate": float(final_sim_out["overall"].get("sim_abandon_rate", 1.0)) if final_sim_out else 1.0,
        "stagnated": stagnant_count >= int(stagnation_rounds),
    }