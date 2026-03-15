import math
from typing import List, Tuple

import numpy as np
import pandas as pd

from config.sim_config import SimConfig


def _logsumexp(log_terms: List[float]) -> float:
    m = max(log_terms)
    return m + math.log(sum(math.exp(t - m) for t in log_terms))


def erlang_c_prob_wait(a: float, c: int) -> float:
    if c <= 0:
        return 1.0
    if a <= 0:
        return 0.0
    if a >= c:
        return 1.0

    log_a = math.log(a)

    def log_term(k: int) -> float:
        return k * log_a - math.lgamma(k + 1)

    logs = [log_term(k) for k in range(c)]
    log_sum = _logsumexp(logs)

    log_ac_over_cfact = log_term(c)
    log_tail = log_ac_over_cfact + math.log(c / (c - a))

    m = max(log_sum, log_tail)
    denom = math.exp(log_sum - m) + math.exp(log_tail - m)
    log_denom = m + math.log(denom)

    pw = math.exp(log_tail - log_denom)
    return float(max(0.0, min(1.0, pw)))


def erlang_c_service_level(a: float, c: int, aht_seconds: float, t_seconds: float) -> float:
    if c <= 0:
        return 0.0
    if a <= 0:
        return 1.0
    if a >= c:
        return 0.0
    pw = erlang_c_prob_wait(a, c)
    return 1.0 - pw * math.exp(-((c - a) * t_seconds / max(aht_seconds, 1e-9)))


def erlang_c_asa_seconds(a: float, c: int, aht_seconds: float) -> float:
    if c <= 0:
        return float("inf")
    if a <= 0:
        return 0.0
    if a >= c:
        return float("inf")
    pw = erlang_c_prob_wait(a, c)
    return pw * (aht_seconds / (c - a))


def solve_staffing_erlang_for_interval(
    calls_offered: float,
    interval_seconds: float,
    aht_seconds: float,
    sl_target: float,
    sl_threshold_seconds: float,
    occupancy_cap: float,
    max_agents: int = 5000,
) -> Tuple[int, float, float, float]:

    lam = max(float(calls_offered), 0.0) / max(float(interval_seconds), 1.0)
    mu = 1.0 / max(float(aht_seconds), 1e-9)
    a = lam / mu

    if a <= 1e-9:
        return 0, 1.0, 0.0, 0.0

    c_min_occ = int(math.ceil(a / max(occupancy_cap, 1e-9)))
    c = max(1, c_min_occ, int(math.floor(a)) + 1)

    for _ in range(max_agents):
        occ = a / c
        if occ <= occupancy_cap:
            sl = erlang_c_service_level(a, c, aht_seconds, sl_threshold_seconds)
            if sl >= sl_target:
                asa = erlang_c_asa_seconds(a, c, aht_seconds)
                return c, sl, asa, occ
        c += 1

    c = max_agents
    occ = a / c
    sl = erlang_c_service_level(a, c, aht_seconds, sl_threshold_seconds) if a < c else 0.0
    asa = erlang_c_asa_seconds(a, c, aht_seconds) if a < c else float("inf")
    return c, sl, asa, occ


def solve_staffing_erlang(df: pd.DataFrame, cfg: SimConfig) -> pd.DataFrame:
    out = df.copy()
    interval_seconds = cfg.interval_minutes * 60

    req_net, pred_sl, pred_asa, pred_occ = [], [], [], []
    calls_arr = out["calls_offered"].to_numpy()
    aht_arr = out["aht_seconds_used"].to_numpy()
    interval_seconds = cfg.interval_minutes * 60

    for calls, aht in zip(calls_arr, aht_arr):
        c, sl, asa, occ = solve_staffing_erlang_for_interval(
            calls_offered=calls,
            interval_seconds=interval_seconds,
            aht_seconds=aht,
            sl_target=cfg.sl_target,
            sl_threshold_seconds=cfg.sl_threshold_seconds,
            occupancy_cap=cfg.occupancy_cap,
        )
        req_net.append(c)
        pred_sl.append(sl)
        pred_asa.append(asa)
        pred_occ.append(occ)

    out["erlang_required_net_agents"] = req_net
    out["erlang_pred_service_level"] = pred_sl
    out["erlang_pred_asa_seconds"] = pred_asa
    out["erlang_pred_occupancy"] = pred_occ

    out["erlang_required_paid_agents"] = out["erlang_required_net_agents"] / max((1 - cfg.shrinkage), 1e-9)
    out["erlang_required_paid_agents_ceil"] = np.ceil(out["erlang_required_paid_agents"]).astype(int)
    return out