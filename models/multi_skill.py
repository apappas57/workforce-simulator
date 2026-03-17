"""models/multi_skill.py

Multi-skill blended staffing model — Phase 24B.

Models the impact of agent blending (skill pooling) on call centre efficiency.

Two staffing strategies are compared analytically via Erlang C:

  Siloed     — each queue has a dedicated, independent agent pool.
               Standard Erlang C per queue; no sharing.

  Blended    — all agents serve all queues (full pooling).
               Combined offered load on a single Erlang C model.
               Produces the minimum total headcount to meet a combined
               weighted SL target; individual queue SL from simulation only.

For partial blending (some agents shared, some dedicated) the DES in
simulation/des_multi_queue.py is the authoritative model.

Public API
----------
QueueSpec                       : dataclass  — per-interval queue definition
SkillGroup                      : dataclass  — named agent group + skill coverage

solve_blended_erlang(queues, interval_minutes) -> pd.DataFrame
    Returns a DataFrame with one row per queue (siloed metrics) plus an
    aggregate "Blended pool" summary row.

pooling_benefit_agents(df)      -> int
    Siloed total minus blended total required agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import pandas as pd

from models.erlang import (
    erlang_c_prob_wait,
    erlang_c_service_level,
    erlang_c_asa_seconds,
    solve_staffing_erlang_for_interval,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class QueueSpec:
    """Per-interval specification for a single queue.

    Attributes
    ----------
    name : str
        Human-readable queue label (e.g. "Sales", "Support").
    calls_per_interval : float
        Expected call volume for one interval (e.g. one 15-min slot).
    aht_seconds : float
        Average handling time in seconds.
    sl_target_pct : float
        Service level target expressed as a percentage (0–100).
    sl_threshold_sec : float
        Answer-within threshold in seconds (e.g. 20 for "80% in 20s").
    shrinkage_pct : float
        Agent shrinkage as a percentage (0–100).  Used to gross up net agents
        to paid (scheduled) agents.
    interval_minutes : float
        Duration of this interval in minutes.  Defaults to 15.
    mean_patience_sec : float
        Mean customer patience for abandonment modelling in the DES.
    """

    name: str
    calls_per_interval: float
    aht_seconds: float
    sl_target_pct: float
    sl_threshold_sec: float
    shrinkage_pct: float = 0.0
    interval_minutes: float = 15.0
    mean_patience_sec: float = 180.0

    @property
    def interval_seconds(self) -> float:
        return self.interval_minutes * 60.0

    @property
    def traffic_intensity(self) -> float:
        """Offered load in Erlangs (λ / μ)."""
        lam = self.calls_per_interval / max(self.interval_seconds, 1.0)
        mu = 1.0 / max(self.aht_seconds, 1e-9)
        return lam / mu

    @property
    def sl_target_fraction(self) -> float:
        return self.sl_target_pct / 100.0

    @property
    def shrinkage_fraction(self) -> float:
        return self.shrinkage_pct / 100.0


@dataclass
class SkillGroup:
    """A named group of agents with a defined skill set.

    Attributes
    ----------
    name : str
        Human-readable group label (e.g. "Sales-only", "Blended").
    queues : list[str]
        Names of queues this group is qualified to handle.
    headcount : int
        Number of agents in this group (net agents on shift).
    """

    name: str
    queues: List[str]
    headcount: int = 0

    def can_serve(self, queue_name: str) -> bool:
        return queue_name in self.queues


# ---------------------------------------------------------------------------
# Blended Erlang C model
# ---------------------------------------------------------------------------

def _net_to_paid(net: int, shrinkage_fraction: float) -> int:
    """Convert net (on-phone) agents to paid (scheduled) headcount."""
    if shrinkage_fraction >= 1.0:
        return net
    return int(round(net / max(1.0 - shrinkage_fraction, 0.01)))


def _solve_queue(q: QueueSpec) -> dict:
    """Run Erlang C for a single QueueSpec and return a result dict."""
    net, sl, asa, occ = solve_staffing_erlang_for_interval(
        calls_offered=q.calls_per_interval,
        interval_seconds=q.interval_seconds,
        aht_seconds=q.aht_seconds,
        sl_target=q.sl_target_fraction,
        sl_threshold_seconds=q.sl_threshold_sec,
        occupancy_cap=1.0,  # no occupancy cap in blended model — let pooling decide
    )
    paid = _net_to_paid(net, q.shrinkage_fraction)
    return {
        "queue":            q.name,
        "calls_per_interval": q.calls_per_interval,
        "aht_seconds":      q.aht_seconds,
        "sl_target_pct":    q.sl_target_pct,
        "sl_threshold_sec": q.sl_threshold_sec,
        "traffic_erlangs":  round(q.traffic_intensity, 3),
        "siloed_net_agents":  net,
        "siloed_paid_agents": paid,
        "siloed_sl_pct":    round(sl * 100, 1),
        "siloed_asa_sec":   round(asa, 1),
        "siloed_occupancy_pct": round(occ * 100, 1),
    }


def solve_blended_erlang(
    queues: List[QueueSpec],
) -> pd.DataFrame:
    """Compute siloed and blended Erlang C staffing requirements.

    For the siloed model each queue is solved independently.
    For the blended model all agents form one pool, calls arrive at the
    combined rate, and AHT is traffic-weighted.

    Parameters
    ----------
    queues : list[QueueSpec]
        At least two QueueSpecs sharing the same ``interval_minutes``.

    Returns
    -------
    pd.DataFrame
        One row per queue (siloed metrics) plus an "── Blended total ──" row
        with combined and blended-pool metrics.  Key columns:

        queue, calls_per_interval, aht_seconds, traffic_erlangs,
        siloed_net_agents, siloed_paid_agents, siloed_sl_pct,
        blended_net_agents (blank for individual rows),
        blended_paid_agents (blank for individual rows),
        blended_sl_pct (blank for individual rows).
    """
    if not queues:
        return pd.DataFrame()

    rows = []
    for q in queues:
        rows.append(_solve_queue(q))

    # ── Blended pool ──────────────────────────────────────────────────────── #
    # Combined offered load (Erlangs) = sum of individual loads
    total_erlangs = sum(q.traffic_intensity for q in queues)

    # Traffic-weighted effective AHT for the combined pool
    total_calls = sum(q.calls_per_interval for q in queues)
    if total_calls > 0:
        effective_aht = sum(q.calls_per_interval * q.aht_seconds for q in queues) / total_calls
    else:
        effective_aht = queues[0].aht_seconds

    # Combined weighted SL target (traffic-weighted)
    combined_sl_target = (
        sum(q.calls_per_interval * q.sl_target_fraction for q in queues) / total_calls
        if total_calls > 0 else queues[0].sl_target_fraction
    )

    # Weighted threshold — use the most demanding (shortest) threshold as the
    # conservative combined target
    combined_threshold = min(q.sl_threshold_sec for q in queues)

    # Mean shrinkage across queues (traffic-weighted)
    combined_shrinkage = (
        sum(q.calls_per_interval * q.shrinkage_fraction for q in queues) / total_calls
        if total_calls > 0 else 0.0
    )

    interval_seconds = queues[0].interval_seconds  # assume same for all queues

    blended_net, blended_sl, blended_asa, blended_occ = solve_staffing_erlang_for_interval(
        calls_offered=total_calls,
        interval_seconds=interval_seconds,
        aht_seconds=effective_aht,
        sl_target=combined_sl_target,
        sl_threshold_seconds=combined_threshold,
        occupancy_cap=1.0,
    )
    blended_paid = _net_to_paid(blended_net, combined_shrinkage)

    siloed_total_net  = sum(r["siloed_net_agents"]  for r in rows)
    siloed_total_paid = sum(r["siloed_paid_agents"] for r in rows)

    # Add blended columns to individual rows (blank — only meaningful in aggregate)
    for r in rows:
        r["blended_net_agents"]  = None
        r["blended_paid_agents"] = None
        r["blended_sl_pct"]      = None
        r["blended_asa_sec"]     = None
        r["pooling_benefit_net"] = None

    summary_row = {
        "queue":               "── Blended total ──",
        "calls_per_interval":  round(total_calls, 1),
        "aht_seconds":         round(effective_aht, 1),
        "sl_target_pct":       round(combined_sl_target * 100, 1),
        "sl_threshold_sec":    combined_threshold,
        "traffic_erlangs":     round(total_erlangs, 3),
        "siloed_net_agents":   siloed_total_net,
        "siloed_paid_agents":  siloed_total_paid,
        "siloed_sl_pct":       None,
        "siloed_asa_sec":      None,
        "siloed_occupancy_pct": None,
        "blended_net_agents":  blended_net,
        "blended_paid_agents": blended_paid,
        "blended_sl_pct":      round(blended_sl * 100, 1),
        "blended_asa_sec":     round(blended_asa, 1),
        "pooling_benefit_net": max(0, siloed_total_net - blended_net),
    }
    rows.append(summary_row)

    return pd.DataFrame(rows)


def pooling_benefit_agents(df: pd.DataFrame) -> int:
    """Extract the pooling benefit (siloed total − blended total) from results.

    Parameters
    ----------
    df : pd.DataFrame
        Output of ``solve_blended_erlang()``.

    Returns
    -------
    int
        Number of agents saved by full blending, or 0 if not computable.
    """
    if df.empty or "pooling_benefit_net" not in df.columns:
        return 0
    val = df["pooling_benefit_net"].dropna()
    if val.empty:
        return 0
    return int(val.iloc[-1])
