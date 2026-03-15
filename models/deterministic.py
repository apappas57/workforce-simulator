import numpy as np
import pandas as pd

from config.sim_config import SimConfig


def deterministic_staffing(df: pd.DataFrame, cfg: SimConfig) -> pd.DataFrame:
    interval_seconds = cfg.interval_minutes * 60
    out = df.copy()

    if "aht_seconds" in out.columns:
        out["aht_seconds_used"] = out["aht_seconds"].astype(float)
    else:
        out["aht_seconds_used"] = float(cfg.aht_seconds)

    out["interval_seconds"] = interval_seconds
    out["workload_seconds"] = out["calls_offered"] * out["aht_seconds_used"]
    out["workload_hours"] = out["workload_seconds"] / 3600.0

    out["raw_concurrent_agents"] = out["workload_seconds"] / interval_seconds
    out["required_net_after_occ"] = out["raw_concurrent_agents"] / max(cfg.occupancy_cap, 1e-9)
    out["required_paid_after_shrink"] = out["required_net_after_occ"] / max((1 - cfg.shrinkage), 1e-9)

    out["det_required_net_ceil"] = np.ceil(out["required_net_after_occ"]).astype(int)
    out["det_required_paid_ceil"] = np.ceil(out["required_paid_after_shrink"]).astype(int)
    return out