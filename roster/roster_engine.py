import math
import random
from typing import Dict, List

import numpy as np
import pandas as pd


def parse_hhmm_to_minutes(hhmm: str) -> int:
    s = hhmm.strip()
    h, m = s.split(":")
    h = int(h)
    m = int(m)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Time must be valid HH:MM (24-hour).")
    return h * 60 + m


def minutes_to_interval(mins: int, interval_minutes: int) -> int:
    return int(math.floor(mins / interval_minutes))


def _spread_integer_load(total: int, buckets: int) -> List[int]:
    if buckets <= 0:
        return []
    base = total // buckets
    rem = total % buckets
    arr = [base] * buckets
    for i in range(rem):
        arr[i] += 1
    return arr


def _bucket_order(strategy: str, n: int, rng: random.Random) -> List[int]:
    idx = list(range(n))
    if strategy == "Random":
        rng.shuffle(idx)
        return idx
    if strategy == "Back-loaded":
        return list(reversed(idx))
    return idx


def pick_break_rules_for_shift_length(shift_len_min: int, ruleset: List[Dict]) -> List[Dict]:
    for r in ruleset:
        if int(r["min_len"]) <= shift_len_min <= int(r["max_len"]):
            return r["breaks"]
    return []


def _apply_breaks_for_shift(
    *,
    paid_breaks_arr: np.ndarray,
    unpaid_breaks_arr: np.ndarray,
    num_intervals: int,
    interval_minutes: int,
    rng: random.Random,
    shift_start_min: int,
    shift_end_min: int,
    shift_heads: int,
    break_rules: List[Dict],
    stagger_strategy: str,
):
    for rule in break_rules:
        dur = int(rule["duration_min"])
        earliest = int(rule["earliest_offset_min"])
        latest = int(rule["latest_offset_min"])
        unpaid = bool(rule.get("unpaid", False))

        win_start = shift_start_min + max(0, earliest)
        win_end = shift_start_min + max(0, latest)
        win_end = min(win_end, shift_end_min - dur)

        if win_end <= win_start:
            continue

        start_int = max(0, minutes_to_interval(win_start, interval_minutes))
        end_int = min(num_intervals - 1, minutes_to_interval(win_end, interval_minutes))
        candidates = list(range(start_int, end_int + 1))
        if not candidates:
            continue

        load = _spread_integer_load(shift_heads, len(candidates))
        order = _bucket_order(stagger_strategy, len(candidates), rng)

        dur_slots = max(1, int(math.ceil(dur / interval_minutes)))
        for j, bucket_idx in enumerate(order):
            n_breaking = load[j] if j < len(load) else 0
            if n_breaking <= 0:
                continue
            start_interval = candidates[bucket_idx]
            for k in range(dur_slots):
                idx = start_interval + k
                if 0 <= idx < num_intervals:
                    if unpaid:
                        unpaid_breaks_arr[idx] += n_breaking
                    else:
                        paid_breaks_arr[idx] += n_breaking

def generate_roster_from_templates(
    *,
    interval_minutes: int,
    num_intervals: int,
    templates: List[Dict],
    ruleset: List[Dict],
    stagger_strategy: str,
    seed: int,
    date_values: List[str] = None,
    interval_in_day_values: List[int] = None,
    start_ts_local_values: List = None,
) -> pd.DataFrame:
    rng = random.Random(seed)

    heads_on_shift = np.zeros(num_intervals, dtype=int)
    paid_breaks = np.zeros(num_intervals, dtype=int)
    unpaid_breaks = np.zeros(num_intervals, dtype=int)

    use_multi_day = (
        date_values is not None
        and interval_in_day_values is not None
        and len(date_values) == num_intervals
        and len(interval_in_day_values) == num_intervals
        and pd.Series(date_values).notna().any()
    )

    if not use_multi_day:
        day_minutes = num_intervals * interval_minutes

        for t in templates:
            start_min = parse_hhmm_to_minutes(t["start"])
            duration_min = int(t["duration_min"])
            heads = int(t["heads"])
            if heads <= 0 or duration_min <= 0:
                continue

            end_min = min(start_min + duration_min, day_minutes)

            s_int = max(0, minutes_to_interval(start_min, interval_minutes))
            e_int = min(num_intervals, int(math.ceil(end_min / interval_minutes)))
            if e_int <= s_int:
                continue

            heads_on_shift[s_int:e_int] += heads

            break_rules = pick_break_rules_for_shift_length(duration_min, ruleset)
            _apply_breaks_for_shift(
                paid_breaks_arr=paid_breaks,
                unpaid_breaks_arr=unpaid_breaks,
                num_intervals=num_intervals,
                interval_minutes=interval_minutes,
                rng=rng,
                shift_start_min=start_min,
                shift_end_min=end_min,
                shift_heads=heads,
                break_rules=break_rules,
                stagger_strategy=stagger_strategy,
            )
    else:
        idx_df = pd.DataFrame({
            "interval": np.arange(num_intervals, dtype=int),
            "date_local": list(date_values),
            "interval_in_day": list(interval_in_day_values),
        })

        unique_dates = idx_df["date_local"].drop_duplicates().tolist()

        for day in unique_dates:
            day_rows = idx_df[idx_df["date_local"] == day].copy()
            if day_rows.empty:
                continue

            day_interval_map = dict(
                zip(day_rows["interval_in_day"].astype(int), day_rows["interval"].astype(int))
            )

            max_interval_in_day = int(day_rows["interval_in_day"].max())
            day_num_intervals = max_interval_in_day + 1
            day_minutes = day_num_intervals * interval_minutes

            for t in templates:
                start_min = parse_hhmm_to_minutes(t["start"])
                duration_min = int(t["duration_min"])
                heads = int(t["heads"])
                if heads <= 0 or duration_min <= 0:
                    continue

                end_min = min(start_min + duration_min, day_minutes)

                s_day = max(0, minutes_to_interval(start_min, interval_minutes))
                e_day = min(day_num_intervals, int(math.ceil(end_min / interval_minutes)))
                if e_day <= s_day:
                    continue

                for local_i in range(s_day, e_day):
                    global_i = day_interval_map.get(local_i)
                    if global_i is not None:
                        heads_on_shift[global_i] += heads

                break_rules = pick_break_rules_for_shift_length(duration_min, ruleset)

                day_paid_breaks = np.zeros(day_num_intervals, dtype=int)
                day_unpaid_breaks = np.zeros(day_num_intervals, dtype=int)

                _apply_breaks_for_shift(
                    paid_breaks_arr=day_paid_breaks,
                    unpaid_breaks_arr=day_unpaid_breaks,
                    num_intervals=day_num_intervals,
                    interval_minutes=interval_minutes,
                    rng=rng,
                    shift_start_min=start_min,
                    shift_end_min=end_min,
                    shift_heads=heads,
                    break_rules=break_rules,
                    stagger_strategy=stagger_strategy,
                )

                for local_i, val in enumerate(day_paid_breaks):
                    if val > 0:
                        global_i = day_interval_map.get(local_i)
                        if global_i is not None:
                            paid_breaks[global_i] += val

                for local_i, val in enumerate(day_unpaid_breaks):
                    if val > 0:
                        global_i = day_interval_map.get(local_i)
                        if global_i is not None:
                            unpaid_breaks[global_i] += val

    roster_net = np.maximum(heads_on_shift - paid_breaks - unpaid_breaks, 0)

    paid_heads = np.maximum(heads_on_shift - unpaid_breaks, 0)
    paid_minutes_total = int(paid_heads.sum() * interval_minutes)
    paid_hours_total = paid_minutes_total / 60.0

    out = pd.DataFrame({
        "interval": np.arange(num_intervals, dtype=int),
        "roster_heads_on_shift": heads_on_shift,
        "roster_breaks_paid": paid_breaks,
        "roster_breaks_unpaid": unpaid_breaks,
        "roster_net_agents": roster_net,
        "roster_paid_heads": paid_heads,
    })

    if use_multi_day:
        out["date_local"] = list(date_values)
        out["interval_in_day"] = list(interval_in_day_values)

    if start_ts_local_values is not None and len(start_ts_local_values) == num_intervals:
        out["start_ts_local"] = list(start_ts_local_values)
    

    out.attrs["roster_paid_minutes_total"] = paid_minutes_total
    out.attrs["roster_paid_hours_total"] = paid_hours_total
    return out
