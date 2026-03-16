"""optimisation/workforce_optimiser.py

Phase 8 — LP-based workforce hiring optimiser.

Finds the monthly hiring plan that minimises total cost across a planning
horizon, subject to a per-month hiring capacity constraint.

Mathematical formulation
------------------------
Decision variables
  h[t]        integer hires in period t,  0 ≤ h[t] ≤ max_hires_per_month
  surplus[t]  continuous FTE above target, ≥ 0
  deficit[t]  continuous FTE below target, ≥ 0

Available FTE in period t (linear in h[t'])
  available_fte[t] = (1 - shrinkage) ×
      [ H₀ × (1-a)^t                                  ← existing workforce
        + Σ_{t'≤t} h[t'] × (1-a)^(t-t') × pm(t-t')  ← hire cohort contributions
      ]

  pm(elapsed) = productivity multiplier from _cohort_contribution() in
  planning/workforce_planner.py — the same function used by project_workforce(),
  ensuring exact formula consistency between optimiser and simulation.

Surplus / deficit linearisation
  surplus[t] - deficit[t] = available_fte[t] - required_fte[t]

Objective
  Minimise Σ_t [ c_hire × h[t] + c_surplus × surplus[t] + c_deficit × deficit[t] ]

Solver: PuLP (already a project dependency).

Scenario comparison
-------------------
optimise_scenarios() runs the optimiser under three attrition rates:
  low    = base_attrition - variance_pp
  base   = base_attrition
  high   = base_attrition + variance_pp

Returns a summary DataFrame comparing total hires and costs across scenarios.
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd
import pulp

from planning.workforce_planner import PlanningParams, _cohort_contribution, project_workforce


# ---------------------------------------------------------------------------
# Parameter dataclass
# ---------------------------------------------------------------------------

@dataclass
class OptimisationParams:
    """Parameters for the LP hiring optimiser.

    Workforce projection parameters are passed as a PlanningParams instance.
    The optimiser uses the same attrition / training / ramp / shrinkage values
    so that its internal available_fte calculation is consistent with
    project_workforce().

    Attributes
    ----------
    planning : PlanningParams
        Full workforce projection parameters.
    required_fte_df : pd.DataFrame
        DataFrame with columns [period_start, required_fte].  Must cover the
        full planning horizon; periods not present default to required_fte = 0.
    cost_per_hire : float
        One-off cost per new hire (e.g. 5000.0).
    cost_per_surplus_fte_month : float
        Cost of carrying one FTE above the required level for one month.
    cost_per_deficit_fte_month : float
        Penalty for one FTE below the required level for one month.
        Set higher than cost_per_surplus_fte_month to penalise understaffing.
    max_hires_per_month : int
        Hard upper bound on hires per period (recruiter / onboarding capacity).
    """
    planning: PlanningParams
    required_fte_df: pd.DataFrame
    cost_per_hire: float
    cost_per_surplus_fte_month: float
    cost_per_deficit_fte_month: float
    max_hires_per_month: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _productivity_multiplier(elapsed: int, planning: PlanningParams) -> float:
    """Return the FTE productivity fraction for a cohort at integer months_elapsed.

    Delegates to _cohort_contribution() with size=1 so the LP uses exactly
    the same formula as project_workforce().
    """
    fte, _ = _cohort_contribution(1.0, float(elapsed), planning)
    return fte


def _build_required_fte_array(
    params: OptimisationParams,
    period_keys: List[Tuple[int, int]],
) -> List[float]:
    """Return required_fte[t] for each period t, defaulting to 0.0."""
    lookup: dict = {}
    if params.required_fte_df is not None and not params.required_fte_df.empty:
        for _, row in params.required_fte_df.iterrows():
            ts = pd.Timestamp(row["period_start"])
            lookup[(ts.year, ts.month)] = float(row["required_fte"])
    return [lookup.get(pk, 0.0) for pk in period_keys]


def _build_coeff_matrix(
    T: int,
    attrition_rate: float,
    planning: PlanningParams,
    shrinkage: float,
) -> List[List[float]]:
    """Precompute coeff[t_hire][t_eval]: FTE from 1 hire in t_hire at period t_eval.

    coeff[t'][t] = (1-a)^(t-t') × pm(t-t') × (1-s)   for t ≥ t'
                 = 0                                    for t < t'
    """
    coeff = [[0.0] * T for _ in range(T)]
    for t_hire in range(T):
        for t_eval in range(t_hire, T):
            elapsed = t_eval - t_hire
            decay = (1.0 - attrition_rate) ** elapsed
            pm = _productivity_multiplier(elapsed, planning)
            coeff[t_hire][t_eval] = decay * pm * (1.0 - shrinkage)
    return coeff


def _baseline_fte_array(
    T: int,
    opening_hc: float,
    attrition_rate: float,
    shrinkage: float,
) -> List[float]:
    """FTE contributed by the existing workforce in each period (no new hires)."""
    return [
        opening_hc * ((1.0 - attrition_rate) ** t) * (1.0 - shrinkage)
        for t in range(T)
    ]


# ---------------------------------------------------------------------------
# Core optimiser
# ---------------------------------------------------------------------------

def optimise_hiring_plan(
    params: OptimisationParams,
    attrition_rate_override: Optional[float] = None,
) -> Tuple[pd.DataFrame, str]:
    """Run the LP and return (result_df, solver_status).

    Parameters
    ----------
    params : OptimisationParams
    attrition_rate_override : float | None
        If provided, overrides params.planning.monthly_attrition_rate_pct / 100.
        Used internally by optimise_scenarios().

    Returns
    -------
    result_df : DataFrame
        One row per period with columns:
        period_start, period_label, optimal_hires, available_fte,
        required_fte, surplus, deficit,
        hire_cost, surplus_cost, deficit_cost, period_total_cost
    status : str
        PuLP solver status string ('Optimal', 'Infeasible', etc.)
    """
    planning = params.planning
    T = planning.planning_horizon_months
    a = attrition_rate_override if attrition_rate_override is not None \
        else planning.monthly_attrition_rate_pct / 100.0
    s = planning.shrinkage_pct / 100.0

    # Build period metadata
    period_ts_list = [
        pd.Timestamp(planning.planning_start_date + pd.DateOffset(months=m))
        for m in range(T)
    ]
    period_keys = [(ts.year, ts.month) for ts in period_ts_list]
    period_labels = [ts.strftime("%b %Y") for ts in period_ts_list]

    # Precompute FTE coefficients and required FTE
    coeff = _build_coeff_matrix(T, a, planning, s)
    baseline = _baseline_fte_array(T, float(planning.opening_headcount), a, s)
    required = _build_required_fte_array(params, period_keys)

    # -------------------------------------------------------------------
    # Build PuLP model
    # -------------------------------------------------------------------
    prob = pulp.LpProblem("workforce_hiring_optimiser", pulp.LpMinimize)

    # Decision variables
    h = [
        pulp.LpVariable(f"hires_{t}", lowBound=0, upBound=params.max_hires_per_month,
                        cat="Integer")
        for t in range(T)
    ]
    surplus = [pulp.LpVariable(f"surplus_{t}", lowBound=0, cat="Continuous") for t in range(T)]
    deficit = [pulp.LpVariable(f"deficit_{t}", lowBound=0, cat="Continuous") for t in range(T)]

    # Objective
    prob += pulp.lpSum(
        params.cost_per_hire * h[t]
        + params.cost_per_surplus_fte_month * surplus[t]
        + params.cost_per_deficit_fte_month * deficit[t]
        for t in range(T)
    )

    # Constraints: surplus[t] - deficit[t] = available_fte[t] - required[t]
    for t in range(T):
        available_fte_expr = baseline[t] + pulp.lpSum(coeff[t_hire][t] * h[t_hire]
                                                       for t_hire in range(t + 1))
        prob += surplus[t] - deficit[t] == available_fte_expr - required[t]

    # Solve (suppress PuLP console output)
    solver = pulp.PULP_CBC_CMD(msg=False)
    prob.solve(solver)

    status = pulp.LpStatus[prob.status]

    # -------------------------------------------------------------------
    # Extract results
    # -------------------------------------------------------------------
    if status != "Optimal":
        # Return empty result with status
        return pd.DataFrame(), status

    optimal_hires = [int(round(pulp.value(h[t]) or 0)) for t in range(T)]

    # Re-run project_workforce with the optimal hiring plan so the simulation
    # result is authoritative (uses the same continuous attrition model).
    hiring_plan_df = pd.DataFrame({
        "period_start": [period_ts_list[t] for t in range(T) if optimal_hires[t] > 0],
        "planned_hires": [optimal_hires[t] for t in range(T) if optimal_hires[t] > 0],
    })

    # Build a modified PlanningParams with the attrition override if needed
    if attrition_rate_override is not None:
        import dataclasses
        sim_planning = dataclasses.replace(
            planning,
            monthly_attrition_rate_pct=attrition_rate_override * 100.0,
        )
    else:
        sim_planning = planning

    projection = project_workforce(
        sim_planning,
        hiring_plan_df=hiring_plan_df if not hiring_plan_df.empty else None,
        required_fte_df=params.required_fte_df,
    )

    # Build cost breakdown
    rows = []
    for t in range(T):
        s_val = float(pulp.value(surplus[t]) or 0)
        d_val = float(pulp.value(deficit[t]) or 0)
        hc = optimal_hires[t]
        h_cost = hc * params.cost_per_hire
        s_cost = s_val * params.cost_per_surplus_fte_month
        d_cost = d_val * params.cost_per_deficit_fte_month

        proj_row = projection.iloc[t] if t < len(projection) else {}

        rows.append({
            "period_start":      period_ts_list[t],
            "period_label":      period_labels[t],
            "optimal_hires":     hc,
            "available_fte":     round(proj_row.get("available_fte", 0.0), 1),
            "required_fte":      required[t],
            "surplus":           round(s_val, 1),
            "deficit":           round(d_val, 1),
            "hire_cost":         round(h_cost, 2),
            "surplus_cost":      round(s_cost, 2),
            "deficit_cost":      round(d_cost, 2),
            "period_total_cost": round(h_cost + s_cost + d_cost, 2),
        })

    return pd.DataFrame(rows), status


# ---------------------------------------------------------------------------
# Scenario comparison
# ---------------------------------------------------------------------------

def optimise_scenarios(
    params: OptimisationParams,
    attrition_variance_pp: float,
) -> pd.DataFrame:
    """Run the optimiser under low / base / high attrition scenarios.

    Parameters
    ----------
    params : OptimisationParams
    attrition_variance_pp : float
        Number of percentage points to add/subtract for high/low scenarios
        (e.g. 2.0 → low = base-2pp, high = base+2pp).

    Returns
    -------
    DataFrame with one row per scenario and columns:
        scenario, attrition_rate_pct, solver_status,
        total_hires, total_hire_cost, total_surplus_cost,
        total_deficit_cost, total_cost, avg_surplus_fte, months_in_deficit
    """
    base_rate = params.planning.monthly_attrition_rate_pct
    variance = attrition_variance_pp

    scenarios = [
        ("Low attrition",  max(0.0, base_rate - variance) / 100.0),
        ("Base attrition", base_rate / 100.0),
        ("High attrition", (base_rate + variance) / 100.0),
    ]

    rows = []
    for label, rate in scenarios:
        result_df, status = optimise_hiring_plan(params, attrition_rate_override=rate)

        if status != "Optimal" or result_df.empty:
            rows.append({
                "scenario":            label,
                "attrition_rate_pct":  round(rate * 100, 2),
                "solver_status":       status,
                "total_hires":         None,
                "total_hire_cost":     None,
                "total_surplus_cost":  None,
                "total_deficit_cost":  None,
                "total_cost":          None,
                "avg_surplus_fte":     None,
                "months_in_deficit":   None,
            })
        else:
            rows.append({
                "scenario":            label,
                "attrition_rate_pct":  round(rate * 100, 2),
                "solver_status":       status,
                "total_hires":         int(result_df["optimal_hires"].sum()),
                "total_hire_cost":     round(result_df["hire_cost"].sum(), 2),
                "total_surplus_cost":  round(result_df["surplus_cost"].sum(), 2),
                "total_deficit_cost":  round(result_df["deficit_cost"].sum(), 2),
                "total_cost":          round(result_df["period_total_cost"].sum(), 2),
                "avg_surplus_fte":     round(result_df["surplus"].mean(), 1),
                "months_in_deficit":   int((result_df["deficit"] > 0.05).sum()),
            })

    return pd.DataFrame(rows)
