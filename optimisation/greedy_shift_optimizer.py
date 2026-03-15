import math
from typing import List, Tuple

import numpy as np
import pandas as pd


def optimise_shift_starts_v1(
    requirement: np.ndarray,
    interval_minutes: int,
    allowed_start_minutes: List[int],
    shift_duration_min: int,
    max_heads_total: int,
    over_penalty: float = 0.25,
) -> Tuple[pd.DataFrame, np.ndarray]:
    """
    Greedy optimiser:
      - Adds 1 head to the start time that reduces understaffing the most
        net of overstaff penalty
      - Repeats until max_heads_total placed or no improvement
    Returns:
      - start_plan dataframe: start_min, start_hhmm, heads
      - coverage array (net heads without breaks; breaks can be layered later)
    """
    n = len(requirement)
    dur_slots = int(math.ceil(shift_duration_min / interval_minutes))

    cover_vectors = []
    for smin in allowed_start_minutes:
        s = int(smin // interval_minutes)
        vec = np.zeros(n, dtype=float)
        e = min(n, s + dur_slots)
        if s < n:
            vec[s:e] = 1.0
        cover_vectors.append(vec)

    cover_vectors = np.vstack(cover_vectors)
    m = cover_vectors.shape[0]

    heads = np.zeros(m, dtype=int)
    coverage = np.zeros(n, dtype=float)

    for _ in range(int(max_heads_total)):
        gap = coverage - requirement
        under = (-gap).clip(min=0)
        over = gap.clip(min=0)

        best_j = None
        best_score = -1e18

        for j in range(m):
            new_cov = coverage + cover_vectors[j]
            new_gap = new_cov - requirement
            new_under = (-new_gap).clip(min=0)
            new_over = new_gap.clip(min=0)

            score = (under.sum() - new_under.sum()) - over_penalty * (new_over.sum() - over.sum())

            if score > best_score:
                best_score = score
                best_j = j

        if best_j is None or best_score <= 0:
            break

        heads[best_j] += 1
        coverage += cover_vectors[best_j]

    def to_hhmm(mins: int) -> str:
        h = mins // 60
        m_ = mins % 60
        return f"{h:02d}:{m_:02d}"

    plan = pd.DataFrame({
        "start_min": allowed_start_minutes,
        "start_hhmm": [to_hhmm(x) for x in allowed_start_minutes],
        "heads": heads,
    })
    plan = plan[plan["heads"] > 0].sort_values("start_min").reset_index(drop=True)

    return plan, coverage