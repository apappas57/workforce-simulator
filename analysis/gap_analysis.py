import pandas as pd


def compute_gap(df: pd.DataFrame, roster_col: str, req_col: str, interval_minutes: int) -> pd.DataFrame:
    out = df.copy()
    out["gap_agents"] = out[roster_col].astype(float) - out[req_col].astype(float)
    out["under_agents"] = (-out["gap_agents"]).clip(lower=0)
    out["over_agents"] = (out["gap_agents"]).clip(lower=0)

    hours_per_interval = interval_minutes / 60.0
    out["under_agent_hours"] = out["under_agents"] * hours_per_interval
    out["over_agent_hours"] = out["over_agents"] * hours_per_interval
    return out