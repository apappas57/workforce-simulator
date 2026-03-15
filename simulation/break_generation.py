import math
from typing import Dict, List, Tuple


def parse_hhmm_to_minutes(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)


def minutes_to_interval(mins: int, interval_minutes: int) -> int:
    return int(math.floor(mins / interval_minutes))


def build_break_schedule_from_shifts(
    *,
    interval_minutes: int,
    num_intervals: int,
    shift_templates: List[Dict],
    break_rules: List[Dict],
) -> Tuple[List[Dict], List[int]]:
    """
    Build a simple interval-based break schedule from shift templates.

    shift_templates:
        [{"start": "08:00", "duration_min": 480, "heads": 50}, ...]

    break_rules:
        [
            {
                "name": "Tea",
                "duration_min": 15,
                "earliest_offset_min": 120,
                "latest_offset_min": 180,
                "unpaid": False,
            },
            ...
        ]
    """
    break_curve = [0] * num_intervals

    for shift in shift_templates:
        heads = int(shift["heads"])
        if heads <= 0:
            continue

        shift_start_min = parse_hhmm_to_minutes(shift["start"])
        shift_duration_min = int(shift["duration_min"])
        shift_end_min = shift_start_min + shift_duration_min

        for rule in break_rules:
            dur_min = int(rule["duration_min"])
            earliest = int(rule["earliest_offset_min"])
            latest = int(rule["latest_offset_min"])

            break_start_min = shift_start_min + int((earliest + latest) / 2)
            break_end_min = break_start_min + dur_min

            break_end_min = min(break_end_min, shift_end_min)
            break_start_min = max(shift_start_min, break_end_min - dur_min)

            start_interval = max(0, minutes_to_interval(break_start_min, interval_minutes))
            end_interval = min(num_intervals, int(math.ceil(break_end_min / interval_minutes)))

            for i in range(start_interval, end_interval):
                break_curve[i] += heads

    break_schedule = []
    current_val = 0
    block_start = None

    for i, val in enumerate(break_curve + [0]):
        if val != current_val:
            if current_val > 0 and block_start is not None:
                break_schedule.append(
                    {
                        "start_interval": block_start,
                        "end_interval": i,
                        "break_agents": current_val,
                    }
                )
            if val > 0:
                block_start = i
            else:
                block_start = None
            current_val = val

    return break_schedule, break_curve