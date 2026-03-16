# Workforce Simulator — Claude Briefing

Read this file at the start of every session. It is the single source of truth
for architectural decisions, conventions, and phase status. Update it when a
phase completes or a new convention is established.

---

## Project summary

A call centre workforce simulation and planning tool built in Python + Streamlit.
Models demand, staffing, queue behaviour, and workforce supply to support
operational and strategic workforce decisions. Personal project, currently
pre-deployment, running locally.

Full capability overview: see PROJECT_STATE.md
Change history: see CHANGELOG.md
Simulation design notes: see DES_NOTES.md

---

## Phase status

| Phase | Title | Status |
|---|---|---|
| 1–3 | Core model foundation | ✅ Complete |
| 4 | Simulation accuracy (DES v2) | ✅ Complete |
| 5 | Multi-day simulation | ✅ Complete |
| 6 | Workforce supply model | ✅ Complete |
| 7 | Strategic workforce planning | ✅ Complete |
| 8 | Optimisation engine | 🔜 Next |
| 9 | Platform development | ⬜ Pending |

Phase 7 delivered: monthly workforce projection engine with cohort-based
training/ramp modelling, proportional attrition, hiring plan CSV, required FTE
plan CSV, capacity gap analysis (surplus/deficit), Workforce Planning tab,
planning_projection export. 15 unit tests added.

---

## Architecture

### System flow

```
Demand Input
  → Workload Models (deterministic + Erlang C)
    → Roster Generation + Break Generation
      → DES Simulation (des_runner.py is the central entry point)
        → Solver Optimisation
          → Scenario Stress Testing
            → Diagnostics + Export
```

### Key file map

| Path | Role |
|---|---|
| `app.py` | Entry point, config construction, tab orchestration |
| `config/sim_config.py` | Frozen dataclass — all model parameters |
| `demand/demand_loader.py` | CSV ingestion + synthetic day builder |
| `supply/staffing_loader.py` | Staffing CSV ingestion, canonical schema |
| `models/deterministic.py` | Deterministic workload calculations |
| `models/erlang.py` | Erlang C queue model |
| `roster/roster_engine.py` | Shift template handling + roster generation |
| `simulation/des_runner.py` | **Central DES entry point** — use this, not des_simulation.py directly |
| `simulation/des_simulation.py` | Legacy DES + DES v2 engines |
| `simulation/break_generation.py` | Shift-based break schedule generation |
| `optimisation/staffing_solver.py` | DES-driven iterative staffing solver |
| `optimisation/lp_shift_optimizer.py` | PuLP LP solver for shift allocation |
| `optimisation/greedy_shift_optimizer.py` | Greedy heuristic for shift start placement |
| `analysis/gap_analysis.py` | Roster vs requirement gap computation |
| `analysis/scenario_runner.py` | Scenario shock application |
| `planning/workforce_planner.py` | **Phase 7 projection engine** — PlanningParams dataclass + project_workforce() |
| `planning/hiring_loader.py` | Loaders for hiring_plan.csv and required_fte_plan.csv |
| `ui/sidebar.py` | Global sidebar — returns dict of all inputs |
| `ui/tab_*.py` | One file per tab; tabs are rendered in app.py |
| `ui/tab_planning.py` | Workforce Planning tab (Phase 7) |
| `ui/date_view.py` | Shared date/interval view helpers + `ensure_x_col` |
| `utils/export.py` | CSV + ZIP export generation |

---

## Session state conventions

**Single source of truth:** `_init_session_state()` in `app.py`.

All session state keys are declared there with defaults. Called once, immediately
after `st.set_page_config`. No tab file may introduce a new key with an
`if key not in st.session_state` guard — add the key to `_init_session_state`
instead.

### Current keys

| Key | Type | Owner | Consumers |
|---|---|---|---|
| `demand_daily_summary` | DataFrame | tab_demand | tab_downloads |
| `roster_daily_summary` | DataFrame | tab_roster | tab_downloads |
| `des_daily_summary` | DataFrame | tab_des | tab_downloads |
| `staffing_daily_summary` | DataFrame | tab_demand | tab_downloads |
| `staffing_gap_export` | DataFrame | tab_demand | tab_downloads |
| `roster_scale` | float | tab_roster | tab_des |
| `planning_projection` | DataFrame | tab_planning | tab_downloads |
| `planning_hiring_plan` | DataFrame | tab_planning | tab_downloads |
| `planning_required_fte` | DataFrame | tab_planning | tab_downloads |

### Adding a key for a new phase

1. Add one entry to `_DEFAULTS` in `_init_session_state()` under the correct
   phase comment block.
2. Uncomment the pre-reserved lines if the key is already listed there.
3. Never add a guard in a tab file.

---

## Testing

**Framework:** pytest (install with `pip install pytest` in venv).
**Fallback:** all tests also run with `python -m unittest` since pytest is
imported with a try/except shim.

**Test files:**

| File | What it covers |
|---|---|
| `tests/test_erlang.py` | Erlang C engine — 24 tests |
| `tests/test_deterministic.py` | Deterministic staffing model — 15 tests |
| `tests/test_staffing_solver.py` | Staffing solver (DES mocked) — 9 tests |
| `tests/test_workforce_planner.py` | Phase 7 projection engine — 15 tests |

Run locally:
```bash
pytest tests/ -v
```

**Rule:** any change to `models/`, `optimisation/`, or `simulation/` must not
break the existing test suite. Add tests for new engine logic before shipping
a phase.

---

## Dependencies

Pinned in `requirements.txt`. Key direct dependencies:

| Package | Version | Purpose |
|---|---|---|
| streamlit | 1.50.0 | UI framework |
| pandas | 2.3.3 | Data manipulation |
| numpy | 2.0.2 | Numerical computation |
| plotly | 6.6.0 | Interactive charts |
| pulp | 3.3.0 | LP optimisation |
| simpy | 4.1.1 | Discrete event simulation |

Do not upgrade any of these without testing the full app. simpy 4.x and
pulp 3.x both had breaking API changes in recent major versions.

---

## Git conventions

- **Branch per phase:** `phase-7-workforce-planning`, `phase-8-optimisation`, etc.
- **Commit before asking Claude to make changes** — one clean commit = one restore point.
- **Never work directly on main** without a branch when Claude is making edits.
- Merge to main when a phase is stable and tests pass.

---

## Established architectural decisions

These were made deliberately. Do not change them without understanding the
rationale.

**`des_runner.py` is the only DES entry point.** The UI, solver, and scenario
runner all call `run_des_engine()` from `des_runner.py`. Never call
`simulate_day_des` or `simulate_day_des_v2` directly from tab code.

**`SimConfig` is frozen.** The dataclass uses `frozen=True`. Config is
constructed once in `app.py` from sidebar inputs and passed down. No tab
modifies config values.

**Tab functions receive data, they don't fetch it.** `render_*` functions
accept DataFrames as arguments. Data loading and model computation happen in
`app.py`, not inside tabs. This keeps tabs testable in isolation.

**Phase 7 uses a different time horizon than DES.** The intraday DES operates
on 15-minute intervals within a day. Phase 7 attrition/hiring projections
operate on monthly periods. These are fully separate execution paths —
`planning/workforce_planner.py` does not import or call `des_runner.py`.

**`tab_planning.py` owns its own inputs.** Unlike other tabs that receive
pre-computed DataFrames from `app.py`, the planning tab manages its own
file uploaders and parameter widgets internally. The computed projection is
stored in session state for `tab_downloads` to consume.

---

## Known limitations (current)

- Shrinkage is a static factor; activity-based dynamic shrinkage is pending (Phase 6 remainder).
- Scenario output comparison visuals are early-stage.
- No persistent storage; all state resets on app reload (Phase 9).
- No authentication (Phase 9).
- `staffing_loader.py` uses `"staffing_interval_input"` as a placeholder `date_local`
  when only interval-indexed staffing is provided — downstream code guards for this.
- Phase 7 attrition applies uniformly to all headcount including in-training and ramp
  agents (known simplification; tenure-banded attrition is not modelled).
