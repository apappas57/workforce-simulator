"""simulation/des_multi_queue.py

Multi-queue multi-skill discrete event simulation — Phase 24B.

Simulates a call centre with multiple call queues and agent skill groups.
Each skill group can serve one or more queues; agents route to the best
available skill-matched agent on arrival.

Architectural note
------------------
This module is a standalone simulation and does NOT route through des_runner.py.
That is an intentional design exception: the existing single-queue DES
(des_runner → des_simulation) models one call type and one agent pool.
Multi-queue routing requires a fundamentally different process topology
(per-group resources, AnyOf race, cross-queue competition) that cannot be
cleanly expressed through the existing single-queue interface.
See CLAUDE.md for the architectural note on this exception.

Public API
----------
MultiQueueSimResult             : dataclass  — per-queue simulation results
simulate_multi_queue(...)       -> list[MultiQueueSimResult]
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

try:
    import simpy
    _SIMPY_AVAILABLE = True
except ImportError:
    _SIMPY_AVAILABLE = False

from models.multi_skill import QueueSpec, SkillGroup


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class MultiQueueSimResult:
    """Per-queue results from a multi-queue DES run.

    Attributes
    ----------
    queue_name : str
    calls_offered : int
    calls_handled : int
    calls_abandoned : int
    abandon_rate : float        0–1
    service_level : float       fraction answered within sl_threshold_sec
    asa_seconds : float         average speed of answer for handled calls
    """

    queue_name:       str
    calls_offered:    int = 0
    calls_handled:    int = 0
    calls_abandoned:  int = 0
    abandon_rate:     float = 0.0
    service_level:    float = 0.0
    asa_seconds:      float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _poisson_arrivals(
    rng: random.Random,
    start_t: float,
    interval_seconds: float,
    mean_calls: float,
) -> List[float]:
    """Return sorted arrival times within [start_t, start_t + interval_seconds)."""
    n = np.random.poisson(max(0.0, mean_calls))
    return sorted(start_t + rng.random() * interval_seconds for _ in range(n))


def _sample_exp(rng: random.Random, mean: float) -> float:
    mean = max(float(mean), 1e-6)
    return rng.expovariate(1.0 / mean)


# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------

def simulate_multi_queue(
    queues: List[QueueSpec],
    skill_groups: List[SkillGroup],
    num_intervals: int = 96,
    seed: int = 42,
    enable_abandonment: bool = True,
) -> List[MultiQueueSimResult]:
    """Run a multi-queue multi-skill DES simulation.

    Parameters
    ----------
    queues : list[QueueSpec]
        Queue definitions — each provides per-interval call volume, AHT,
        SL target/threshold, and mean patience.
    skill_groups : list[SkillGroup]
        Agent groups with their skill coverage and headcount.
        Each group is modelled as a ``simpy.Resource`` of capacity
        ``headcount``.  A call for queue Q is routed to any group whose
        ``queues`` list includes Q; the first available group wins.
    num_intervals : int
        Number of intervals to simulate.  Defaults to 96 (15-min intervals
        across a full 24-hour day).
    seed : int
        Random seed for reproducibility.
    enable_abandonment : bool
        When True, calls abandon after ``queue.mean_patience_sec`` (Erlang
        distributed).  When False, calls wait indefinitely.

    Returns
    -------
    list[MultiQueueSimResult]
        One result per queue, in the same order as *queues*.

    Notes
    -----
    Routing rule — **first-available, dedicated-first**:
        For each call, the eligible groups are ordered by ascending queue
        count (groups that serve fewer queues first, i.e. dedicated agents
        before blended agents).  This mimics the common operational rule of
        preserving blended agents as a buffer.

    Abandonment is modelled via ``simpy.AnyOf``; untriggered resource
    requests are cancelled by calling ``resource.release(req)`` — the
    correct simpy 4.1.1 pattern for releasing a pending (not yet triggered)
    request without waiting.
    """
    if not _SIMPY_AVAILABLE:
        raise RuntimeError(
            "simpy is required for multi-queue simulation. "
            "Run: pip install simpy"
        )

    if not queues:
        return []
    if not skill_groups or all(g.headcount == 0 for g in skill_groups):
        # No agents — all calls abandon
        return [
            MultiQueueSimResult(
                queue_name=q.name,
                calls_offered=int(np.random.poisson(q.calls_per_interval) * num_intervals),
                calls_abandoned=int(np.random.poisson(q.calls_per_interval) * num_intervals),
                abandon_rate=1.0,
            )
            for q in queues
        ]

    rng = random.Random(seed)
    np.random.seed(seed)

    env = simpy.Environment()
    interval_seconds = queues[0].interval_seconds   # assume all queues share interval duration

    # ── Build per-group simpy Resources ────────────────────────────────────── #
    # Capacity = group headcount.  Resources represent agent pools.
    resources: Dict[str, simpy.Resource] = {
        g.name: simpy.Resource(env, capacity=max(1, g.headcount))
        for g in skill_groups
        if g.headcount > 0
    }

    # For each queue, order the eligible groups: dedicated first, then blended
    # (ascending number of queues served → dedicated groups before blended).
    eligible_groups: Dict[str, List[SkillGroup]] = {}
    for q in queues:
        eg = [g for g in skill_groups if g.can_serve(q.name) and g.headcount > 0]
        eg.sort(key=lambda g: len(g.queues))
        eligible_groups[q.name] = eg

    # ── Tracking accumulators ───────────────────────────────────────────────── #
    stats: Dict[str, Dict] = {
        q.name: {
            "offered":    0,
            "handled":    0,
            "abandoned":  0,
            "wait_total": 0.0,
            "within_sl":  0,
        }
        for q in queues
    }

    # ── Call-handling process ───────────────────────────────────────────────── #
    def handle_call(
        q: QueueSpec,
        arrival_t: float,
        aht: float,
        patience: float,
    ):
        yield env.timeout(max(0.0, arrival_t - env.now))

        stats[q.name]["offered"] += 1
        t0 = env.now

        groups = eligible_groups.get(q.name, [])
        if not groups:
            # No skill match — call immediately abandoned
            stats[q.name]["abandoned"] += 1
            return

        # Create one request per eligible group and race them
        reqs = [(g.name, resources[g.name].request()) for g in groups]

        if enable_abandonment:
            timeout_evt = env.timeout(patience)
            race_events = [req for _, req in reqs] + [timeout_evt]
            results = yield simpy.AnyOf(env, race_events)

            # Find which (if any) resource request fired
            served_group = None
            served_req = None
            for g_name, req in reqs:
                if req in results:
                    if served_group is None:
                        # First triggered request wins
                        served_group = g_name
                        served_req = req
                    else:
                        # Duplicate trigger (rare) — release the extra immediately
                        resources[g_name].release(req)

            # Cancel all untriggered requests
            for g_name, req in reqs:
                if req is not served_req and req.triggered is False:
                    resources[g_name].release(req)

            if served_group is not None:
                wait = env.now - t0
                stats[q.name]["handled"]    += 1
                stats[q.name]["wait_total"] += wait
                if wait <= q.sl_threshold_sec:
                    stats[q.name]["within_sl"] += 1
                yield env.timeout(aht)
                resources[served_group].release(served_req)
            else:
                # Timed out — call abandoned
                stats[q.name]["abandoned"] += 1

        else:
            # No abandonment — wait indefinitely for the first available group
            result = yield simpy.AnyOf(env, [req for _, req in reqs])

            served_group = None
            served_req = None
            for g_name, req in reqs:
                if req in result:
                    if served_group is None:
                        served_group = g_name
                        served_req = req
                    else:
                        resources[g_name].release(req)

            for g_name, req in reqs:
                if req is not served_req and req.triggered is False:
                    resources[g_name].release(req)

            if served_group is not None:
                wait = env.now - t0
                stats[q.name]["handled"]    += 1
                stats[q.name]["wait_total"] += wait
                if wait <= q.sl_threshold_sec:
                    stats[q.name]["within_sl"] += 1
                yield env.timeout(aht)
                resources[served_group].release(served_req)

    # ── Generate all call processes ─────────────────────────────────────────── #
    for interval_idx in range(num_intervals):
        start_t = interval_idx * interval_seconds
        for q in queues:
            arrivals = _poisson_arrivals(rng, start_t, interval_seconds, q.calls_per_interval)
            for arrival_t in arrivals:
                aht     = _sample_exp(rng, q.aht_seconds)
                patience = _sample_exp(rng, q.mean_patience_sec) if enable_abandonment else float("inf")
                env.process(handle_call(q, arrival_t, aht, patience))

    env.run()

    # ── Assemble results ─────────────────────────────────────────────────────── #
    results = []
    for q in queues:
        s = stats[q.name]
        offered   = s["offered"]
        handled   = s["handled"]
        abandoned = s["abandoned"]

        abandon_rate    = abandoned / offered if offered > 0 else 0.0
        service_level   = s["within_sl"] / offered if offered > 0 else 0.0
        asa             = s["wait_total"] / handled if handled > 0 else 0.0

        results.append(MultiQueueSimResult(
            queue_name      = q.name,
            calls_offered   = offered,
            calls_handled   = handled,
            calls_abandoned = abandoned,
            abandon_rate    = round(abandon_rate, 4),
            service_level   = round(service_level, 4),
            asa_seconds     = round(asa, 1),
        ))

    return results
