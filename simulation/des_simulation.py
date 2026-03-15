import math
import random
import heapq
from typing import Dict, List, Optional
from collections import deque

import numpy as np
import pandas as pd
import simpy

from config.sim_config import SimConfig


def _arrival_times_for_interval(rng: random.Random, start_t: float, interval_seconds: float, calls: float) -> List[float]:
    n = np.random.poisson(max(calls, 0.0))
    return sorted(start_t + rng.random() * interval_seconds for _ in range(n))

def _add_busy_time_to_intervals(
    busy_seconds_by_interval: np.ndarray,
    start_t: float,
    end_t: float,
    busy_agents: int,
    interval_seconds: float,
    num_intervals: int,
) -> None:
    """
    Allocates busy-agent time across interval buckets.
    """
    if end_t <= start_t or busy_agents <= 0:
        return

    t = start_t
    while t < end_t:
        interval_idx = int(t // interval_seconds)
        if interval_idx >= num_intervals:
            break

        interval_end = min((interval_idx + 1) * interval_seconds, end_t)
        dur = interval_end - t
        if dur > 0:
            busy_seconds_by_interval[interval_idx] += dur * busy_agents
        t = interval_end

def simulate_day_des(
    df: pd.DataFrame,
    cfg: SimConfig,
    staff_col: str,
    service_time_dist: str = "exponential",
    enable_abandonment: bool = True,
    patience_dist: str = "exponential",
    mean_patience_seconds: float = 180.0,
) -> Dict:
    rng = random.Random(cfg.seed)
    np.random.seed(cfg.seed)

    interval_seconds = cfg.interval_minutes * 60
    num_intervals = len(df)

    staff = df[staff_col].astype(int).to_list()
    max_staff = max(1, max(staff))

    env = simpy.Environment()
    free_agents = simpy.Container(env, capacity=max_staff, init=max(0, staff[0]))
    on_duty = {"count": max(0, staff[0])}

    waits = []
    answered_within = []
    arrival_interval_idx = []
    abandoned_flags = []
    service_seconds_by_interval = np.zeros(num_intervals, dtype=float)
    offered_by_interval = np.zeros(num_intervals, dtype=int)

    def sample_service_time(mean_aht: float) -> float:
        mean_aht = max(float(mean_aht), 1.0)
        if service_time_dist == "lognormal":
            sigma = 0.6
            mu = math.log(mean_aht) - 0.5 * sigma**2
            return max(1.0, rng.lognormvariate(mu, sigma))
        return max(1.0, rng.expovariate(1.0 / mean_aht))

    def sample_patience_time(mean_pat: float) -> float:
        mean_pat = max(float(mean_pat), 1.0)
        if patience_dist == "lognormal":
            sigma = 0.8
            mu = math.log(mean_pat) - 0.5 * sigma**2
            return max(1.0, rng.lognormvariate(mu, sigma))
        return max(1.0, rng.expovariate(1.0 / mean_pat))

    def staffing_controller():
        for i in range(num_intervals):
            target = max(0, int(staff[i]))
            current_total = on_duty["count"]

            if target > current_total:
                add = target - current_total
                yield free_agents.put(add)
                on_duty["count"] = target
            elif target < current_total:
                remove = current_total - target
                while remove > 0:
                    yield free_agents.get(1)
                    remove -= 1
                on_duty["count"] = target

            if i < num_intervals - 1:
                yield env.timeout(interval_seconds)

    def handle_call(arrival_t: float, i_interval: int, mean_aht: float):
        yield env.timeout(arrival_t - env.now)

        t0 = env.now
        offered_by_interval[i_interval] += 1

        if enable_abandonment:
            patience = sample_patience_time(mean_patience_seconds)
            req = free_agents.get(1)
            timeout_evt = env.timeout(patience)

            result = yield simpy.events.AnyOf(env, [req, timeout_evt])

            if timeout_evt in result.events and req not in result.events:
                req.cancel()
                waits.append(float(patience))
                answered_within.append(False)
                arrival_interval_idx.append(i_interval)
                abandoned_flags.append(True)
                return

            t1 = env.now
        else:
            yield free_agents.get(1)
            t1 = env.now

        wait = t1 - t0
        waits.append(wait)
        answered_within.append(wait <= cfg.sl_threshold_seconds)
        arrival_interval_idx.append(i_interval)
        abandoned_flags.append(False)

        svc = sample_service_time(mean_aht)
        svc_start_interval = min(int(t1 // interval_seconds), num_intervals - 1)
        service_seconds_by_interval[svc_start_interval] += svc

        yield env.timeout(svc)
        yield free_agents.put(1)

    env.process(staffing_controller())

    arrivals = []
    for i in range(num_intervals):
        start_t = i * interval_seconds
        calls = float(df.iloc[i]["calls_offered"])
        mean_aht = float(df.iloc[i]["aht_seconds_used"])
        times = _arrival_times_for_interval(rng, start_t, interval_seconds, calls)
        arrivals.extend((t, i, mean_aht) for t in times)

    for t, i, mean_aht in arrivals:
        env.process(handle_call(t, i, mean_aht))

    drain_seconds = max(
        3600,
        int(8 * float(cfg.aht_seconds)),
        int(8 * float(mean_patience_seconds)) if enable_abandonment else 0,
    )
    sim_end = num_intervals * interval_seconds
    env.run(until=sim_end + drain_seconds)

    interval_df = df.copy()
    interval_df["staff_sim"] = staff

    waits_arr = np.array(waits, dtype=float) if waits else np.array([], dtype=float)
    answered_arr = np.array(answered_within, dtype=bool) if answered_within else np.array([], dtype=bool)
    idx_arr = np.array(arrival_interval_idx, dtype=int) if arrival_interval_idx else np.array([], dtype=int)
    abandoned_arr = np.array(abandoned_flags, dtype=bool) if abandoned_flags else np.array([], dtype=bool)

    sl_by_interval = np.zeros(num_intervals, dtype=float)
    asa_by_interval = np.zeros(num_intervals, dtype=float)
    aband_by_interval = np.zeros(num_intervals, dtype=float)

    for i in range(num_intervals):
        mask = idx_arr == i
        resolved = int(mask.sum())

        if resolved > 0:
            sl_by_interval[i] = float(answered_arr[mask].mean())
            asa_by_interval[i] = float(waits_arr[mask].mean())
            aband_by_interval[i] = float(abandoned_arr[mask].mean())
        else:
            sl_by_interval[i] = 0.0
            asa_by_interval[i] = 0.0
            aband_by_interval[i] = 0.0
  


    interval_df["sim_calls"] = offered_by_interval
    interval_df["sim_service_level"] = sl_by_interval
    interval_df["sim_asa_seconds"] = asa_by_interval
    interval_df["sim_abandon_rate"] = aband_by_interval

    denom = np.maximum(1, interval_df["staff_sim"].to_numpy()) * interval_seconds
    interval_df["sim_busy_seconds"] = service_seconds_by_interval
    interval_df["sim_occupancy"] = np.clip(service_seconds_by_interval / denom, 0, 1)

    total_calls = int(offered_by_interval.sum())
    total_abandoned = int(abandoned_arr.sum()) if len(abandoned_arr) else 0
    total_answered = int((~abandoned_arr).sum()) if len(abandoned_arr) else 0

    overall = {
        "sim_total_calls": total_calls,
        "sim_answered_calls": total_answered,
        "sim_abandoned_calls": total_abandoned,
        "sim_abandon_rate": (total_abandoned / total_calls) if total_calls else 0.0,
        "sim_service_level": float(answered_arr.mean()) if len(answered_arr) else 0.0,
        "sim_asa_seconds": float(waits_arr.mean()) if len(waits_arr) else 0.0,
        "sim_avg_occupancy": float(np.nanmean(interval_df["sim_occupancy"])) if num_intervals else 0.0,
        "sim_peak_staff": int(max(staff)),
    }
    return {"interval_kpis": interval_df, "overall": overall}

def simulate_day_des_v2(
    df: pd.DataFrame,
    cfg: SimConfig,
    staff_col: str,
    service_time_dist: str = "exponential",
    enable_abandonment: bool = True,
    patience_dist: str = "exponential",
    mean_patience_seconds: float = 180.0,
    enable_breaks: bool = False,
    break_schedule: Optional[List[Dict]] = None,
) -> Dict:
    """
    DES v2:
    - explicit call queue
    - explicit abandonment deadlines
    - explicit service completion tracking
    - interval KPIs built from call records
    - occupancy built from integrated busy-agent time
    """

    rng = random.Random(cfg.seed)
    np.random.seed(cfg.seed)

    interval_seconds = cfg.interval_minutes * 60
    num_intervals = len(df)

    staff = df[staff_col].astype(int).fillna(0).clip(lower=0).astype(int).to_list()
    break_agents_curve = np.zeros(num_intervals, dtype=int)

    if enable_breaks and break_schedule:
        for item in break_schedule:
            start_interval = max(0, int(item.get("start_interval", 0)))
            end_interval = min(num_intervals, int(item.get("end_interval", 0)))
            break_agents = max(0, int(item.get("break_agents", 0)))

            if end_interval > start_interval and break_agents > 0:
                break_agents_curve[start_interval:end_interval] += break_agents
    def sample_service_time(mean_aht: float) -> float:
        mean_aht = max(float(mean_aht), 1.0)
        if service_time_dist == "lognormal":
            sigma = 0.6
            mu = math.log(mean_aht) - 0.5 * sigma**2
            return max(1.0, rng.lognormvariate(mu, sigma))
        return max(1.0, rng.expovariate(1.0 / mean_aht))

    def sample_patience_time(mean_pat: float) -> float:
        mean_pat = max(float(mean_pat), 1.0)
        if patience_dist == "lognormal":
            sigma = 0.8
            mu = math.log(mean_pat) - 0.5 * sigma**2
            return max(1.0, rng.lognormvariate(mu, sigma))
        return max(1.0, rng.expovariate(1.0 / mean_pat))

    # -----------------------------
    # Build arrival events
    # -----------------------------
    arrivals = []
    call_id = 0
    for i in range(num_intervals):
        start_t = i * interval_seconds
        calls = float(df.loc[i, "calls_offered"])
        mean_aht = float(df.loc[i, "aht_seconds_used"])
        times = _arrival_times_for_interval(rng, start_t, interval_seconds, calls)

        for t in times:
            arrivals.append((t, call_id, i, mean_aht))
            call_id += 1

    arrivals.sort(key=lambda x: x[0])

    # -----------------------------
    # State
    # -----------------------------
    calls = {}
    waiting_queue = deque()
    abandon_heap = []  # (deadline, call_id)
    service_heap = []  # (end_service_time, call_id)

    busy_seconds_by_interval = np.zeros(num_intervals, dtype=float)

    # Time-weighted state accumulators
    sim_queue_time = np.zeros(num_intervals, dtype=float)
    sim_busy_time = np.zeros(num_intervals, dtype=float)
    sim_idle_time = np.zeros(num_intervals, dtype=float)
    sim_break_time = np.zeros(num_intervals, dtype=float)

    answered_calls = 0
    abandoned_calls = 0
    active_count = 0

    current_time = 0.0
    current_staff_target = staff[0] if num_intervals > 0 else 0
    current_break_agents = int(break_agents_curve[0]) if num_intervals > 0 else 0

    arrival_ptr = 0
    next_staff_change_idx = 1  # interval boundary index

    # -----------------------------
    # Helpers
    # -----------------------------
    def next_staff_change_time():
        if next_staff_change_idx >= num_intervals:
            return float("inf")
        return next_staff_change_idx * interval_seconds

    def integrate_state_over_time(start_t: float, end_t: float):
        """
        Integrate queue and agent state across time to produce
        time-weighted interval averages.
        """

        if end_t <= start_t:
            return

        waiting_count = sum(1 for cid in waiting_queue if calls[cid]["status"] == "waiting")
        busy_count = active_count
        available_agents = max(0, current_staff_target - current_break_agents)
        idle_count = max(0, available_agents - busy_count)
        break_count = current_break_agents

        t = start_t

        while t < end_t:

            interval_idx = int(t // interval_seconds)

            if interval_idx >= num_intervals:
                break

            interval_end = min((interval_idx + 1) * interval_seconds, end_t)

            dur = interval_end - t

            if dur > 0:
                sim_queue_time[interval_idx] += waiting_count * dur
                sim_busy_time[interval_idx] += busy_count * dur
                sim_idle_time[interval_idx] += idle_count * dur
                sim_break_time[interval_idx] += break_count * dur

            t = interval_end

    def dispatch_calls(now: float):
        nonlocal active_count, answered_calls

        available_agents = max(0, current_staff_target - current_break_agents)

        while waiting_queue and active_count < available_agents:
            cid = waiting_queue[0]
            rec = calls[cid]

            # Skip anything no longer waiting
            if rec["status"] != "waiting":
                waiting_queue.popleft()
                continue

            # If abandonment enabled and patience already expired, abandon now
            if enable_abandonment and rec["abandon_deadline"] is not None and rec["abandon_deadline"] <= now:
                rec["status"] = "abandoned"
                rec["abandoned_flag"] = True
                rec["wait_seconds"] = rec["abandon_deadline"] - rec["arrival_time"]
                waiting_queue.popleft()
                continue

            waiting_queue.popleft()

            rec["status"] = "in_service"
            rec["answer_time"] = now
            rec["answer_interval"] = min(int(now // interval_seconds), num_intervals - 1)
            rec["wait_seconds"] = now - rec["arrival_time"]
            rec["answered_within_sl_flag"] = rec["wait_seconds"] <= cfg.sl_threshold_seconds

            svc = sample_service_time(rec["aht_seconds"])
            rec["service_seconds"] = svc
            rec["end_service_time"] = now + svc
            rec["service_interval"] = min(int(now // interval_seconds), num_intervals - 1)

            active_count += 1
            answered_calls += 1
            heapq.heappush(service_heap, (rec["end_service_time"], cid))

    # -----------------------------
    # Main event loop
    # -----------------------------
    sim_end = num_intervals * interval_seconds
    hard_stop = sim_end + max(
        3600.0,
        8.0 * float(cfg.aht_seconds),
        8.0 * float(mean_patience_seconds) if enable_abandonment else 0.0,
    )

    while True:
        next_arrival_time = arrivals[arrival_ptr][0] if arrival_ptr < len(arrivals) else float("inf")
        next_service_time = service_heap[0][0] if service_heap else float("inf")

        while abandon_heap and calls[abandon_heap[0][1]]["status"] != "waiting":
            heapq.heappop(abandon_heap)
        next_abandon_time = abandon_heap[0][0] if abandon_heap else float("inf")

        next_staff_time = next_staff_change_time()

        next_event_time = min(next_arrival_time, next_service_time, next_abandon_time, next_staff_time)

        if next_event_time == float("inf"):
            break

        if next_event_time > hard_stop:
            break

        _add_busy_time_to_intervals(
            busy_seconds_by_interval=busy_seconds_by_interval,
            start_t=current_time,
            end_t=next_event_time,
            busy_agents=active_count,
            interval_seconds=interval_seconds,
            num_intervals=num_intervals,
        )

        integrate_state_over_time(current_time, next_event_time)

        current_time = next_event_time

        # 1. Service completions
        while service_heap and service_heap[0][0] <= current_time:
            _, cid = heapq.heappop(service_heap)
            rec = calls[cid]
            if rec["status"] == "in_service":
                rec["status"] = "completed"
                active_count -= 1

        # 2. Staff changes
        while next_staff_change_idx < num_intervals and (next_staff_change_idx * interval_seconds) <= current_time:
            current_staff_target = staff[next_staff_change_idx]
            current_break_agents = int(break_agents_curve[next_staff_change_idx])
            next_staff_change_idx += 1

        # 3. Arrivals
        while arrival_ptr < len(arrivals) and arrivals[arrival_ptr][0] <= current_time:
            arrival_t, cid, arrival_interval, mean_aht = arrivals[arrival_ptr]
            patience = sample_patience_time(mean_patience_seconds) if enable_abandonment else None

            calls[cid] = {
                "call_id": cid,
                "arrival_time": arrival_t,
                "arrival_interval": arrival_interval,
                "aht_seconds": float(mean_aht),
                "patience_seconds": float(patience) if patience is not None else np.nan,
                "abandon_deadline": (arrival_t + patience) if patience is not None else None,
                "answer_time": np.nan,
                "answer_interval": np.nan,
                "end_service_time": np.nan,
                "service_interval": np.nan,
                "status": "waiting",
                "abandoned_flag": False,
                "answered_within_sl_flag": False,
                "wait_seconds": np.nan,
                "service_seconds": np.nan,
            }

            waiting_queue.append(cid)
            if enable_abandonment:
                heapq.heappush(abandon_heap, (arrival_t + patience, cid))

            arrival_ptr += 1

        # 4. Abandonments
        while abandon_heap:
            deadline, cid = abandon_heap[0]
            rec = calls[cid]
            if rec["status"] != "waiting":
                heapq.heappop(abandon_heap)
                continue
            if deadline > current_time:
                break

            heapq.heappop(abandon_heap)
            rec["status"] = "abandoned"
            rec["abandoned_flag"] = True
            rec["wait_seconds"] = deadline - rec["arrival_time"]
            abandoned_calls += 1

        # 5. Dispatch waiting calls into service
        dispatch_calls(current_time)
    

        done_arrivals = arrival_ptr >= len(arrivals)
        no_waiting = all(calls[cid]["status"] != "waiting" for cid in waiting_queue) if waiting_queue else True
        no_services = len(service_heap) == 0

        if done_arrivals and no_waiting and no_services and current_time >= sim_end:
            break

    # Final busy time allocation not needed because loop allocates before each event.
    # Build call log
    if calls:
        call_log_df = pd.DataFrame(list(calls.values())).sort_values("call_id").reset_index(drop=True)
    else:
        call_log_df = pd.DataFrame(columns=[
            "call_id", "arrival_time", "arrival_interval", "aht_seconds", "patience_seconds",
            "abandon_deadline", "answer_time", "answer_interval", "end_service_time",
            "service_interval", "status", "abandoned_flag", "answered_within_sl_flag",
            "wait_seconds", "service_seconds"
        ])

    # -----------------------------
    # Build interval KPIs
    # -----------------------------
    interval_df = df.copy()
    interval_df["staff_sim"] = staff

    sim_calls = np.zeros(num_intervals, dtype=int)
    sim_answered_calls = np.zeros(num_intervals, dtype=int)
    sim_abandoned_calls = np.zeros(num_intervals, dtype=int)
    sim_service_level = np.full(num_intervals, np.nan, dtype=float)
    sim_abandon_rate = np.full(num_intervals, np.nan, dtype=float)
    sim_asa_seconds = np.full(num_intervals, np.nan, dtype=float)

    if not call_log_df.empty:
        for i in range(num_intervals):
            arr_mask = call_log_df["arrival_interval"] == i
            sub = call_log_df.loc[arr_mask]

            offered = len(sub)
            answered = int((sub["status"].isin(["in_service", "completed"])).sum())
            abandoned = int((sub["status"] == "abandoned").sum())

            sim_calls[i] = offered
            sim_answered_calls[i] = answered
            sim_abandoned_calls[i] = abandoned

            if offered > 0:
                sim_service_level[i] = float(sub["answered_within_sl_flag"].fillna(False).mean())
                sim_abandon_rate[i] = abandoned / offered

                answered_sub = sub.loc[sub["status"].isin(["in_service", "completed"]), "wait_seconds"]
                sim_asa_seconds[i] = float(answered_sub.mean()) if len(answered_sub) > 0 else np.nan

    interval_df["sim_calls"] = sim_calls
    interval_df["sim_answered_calls"] = sim_answered_calls
    interval_df["sim_abandoned_calls"] = sim_abandoned_calls
    interval_df["sim_service_level"] = sim_service_level
    interval_df["sim_abandon_rate"] = sim_abandon_rate
    interval_df["sim_asa_seconds"] = sim_asa_seconds

    interval_df["sim_busy_seconds"] = busy_seconds_by_interval
    denom = np.maximum(1, interval_df["staff_sim"].to_numpy()) * interval_seconds
    interval_df["sim_occupancy"] = np.clip(interval_df["sim_busy_seconds"] / denom, 0, 1)

    interval_df["sim_queue_length"] = sim_queue_time / interval_seconds
    interval_df["sim_busy_agents"] = sim_busy_time / interval_seconds
    interval_df["sim_idle_agents"] = sim_idle_time / interval_seconds
    interval_df["sim_break_agents"] = sim_break_time / interval_seconds

    interval_df["sim_queue_length"] = interval_df["sim_queue_length"].fillna(0.0)
    interval_df["sim_busy_agents"] = interval_df["sim_busy_agents"].fillna(0.0)
    interval_df["sim_idle_agents"] = interval_df["sim_idle_agents"].fillna(0.0)
    interval_df["sim_break_agents"] = interval_df["sim_break_agents"].fillna(0.0)
    total_calls = int(sim_calls.sum())
    total_answered = int(sim_answered_calls.sum())
    total_abandoned = int(sim_abandoned_calls.sum())

    overall = {
        "sim_total_calls": total_calls,
        "sim_answered_calls": total_answered,
        "sim_abandoned_calls": total_abandoned,
        "sim_abandon_rate": (total_abandoned / total_calls) if total_calls else 0.0,
        "sim_service_level": float(
            call_log_df.loc[
                call_log_df["status"].isin(["in_service", "completed"]),
                "answered_within_sl_flag"
            ].mean()
        ) if not call_log_df.empty and (call_log_df["status"].isin(["in_service", "completed"])).any() else 0.0,
        "sim_asa_seconds": float(
            call_log_df.loc[call_log_df["status"].isin(["in_service", "completed"]), "wait_seconds"].mean()
        ) if not call_log_df.empty else 0.0,
        "sim_avg_occupancy": float(np.nanmean(interval_df["sim_occupancy"])) if num_intervals else 0.0,
        "sim_peak_staff": int(max(staff)) if staff else 0,
    }

    return {
        "interval_kpis": interval_df,
        "overall": overall,
        "call_log": call_log_df,
    }