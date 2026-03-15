import pandas as pd
import pulp


def optimise_shifts_lp(requirement, interval_minutes, shift_lengths, allowed_starts):
    n_intervals = len(requirement)

    shift_vars = {}

    for start in allowed_starts:
        for length in shift_lengths:
            shift_vars[(start, length)] = pulp.LpVariable(
                f"shift_{start}_{length}",
                lowBound=0,
                cat="Integer"
            )

    model = pulp.LpProblem("shift_optimisation", pulp.LpMinimize)

    model += pulp.lpSum(shift_vars.values())

    for t in range(n_intervals):
        coverage = []

        for (start, length), var in shift_vars.items():
            start_interval = start // interval_minutes
            duration_intervals = length // interval_minutes

            if start_interval <= t < start_interval + duration_intervals:
                coverage.append(var)

        model += pulp.lpSum(coverage) >= requirement[t]

    model.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[model.status] != "Optimal":
        return pd.DataFrame(columns=["start_min", "shift_length", "heads"])

    results = []

    for (start, length), var in shift_vars.items():
        if var.value() > 0:
            results.append({
                "start_min": start,
                "shift_length": length,
                "heads": int(var.value())
            })

    return pd.DataFrame(results)