# Workforce Simulator — Claude Briefing

Read this file at the start of every session. It is the single source of truth
for architectural decisions, conventions, and phase status. Update it when a
phase completes or a new convention is established.

---

## Project summary

A call centre workforce simulation and planning tool built in Python + Streamlit.
Models demand, staffing, queue behaviour, and workforce supply to support
operational and strategic workforce decisions. Personal project; deployable via
Docker locally or to Railway / Render (see render.yaml / railway.toml).

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
| 6 | Workforce supply model + observed shrinkage | ✅ Complete |
| 7 | Strategic workforce planning | ✅ Complete |
| 8 | Optimisation engine | ✅ Complete |
| 9 | Platform development | ✅ Complete |
| 10 | Authentication + deployment | ✅ Complete |
| 11 | Demand forecasting | ✅ Complete |
| 12 | PDF report export | ✅ Complete |
| 13 | Cost & financial analytics | ✅ Complete |
| 14 | Scenario planning overhaul | ✅ Complete |
| 15 | Multi-queue comparison | ✅ Complete |
| 16 | Config save/load | ✅ Complete |
| 17 | Formatted Excel export | ✅ Complete |
| 18 | Overview dashboard | ✅ Complete |
| 19 | Gantt shift schedule visualisation | ✅ Complete |
| 20 | Caching layer | ✅ Complete |
| 21 | Chart consistency pass | ✅ Complete |
| 22 | Quick Erlang C calculator | ✅ Complete |
| 23 | Deployment hardening | ✅ Complete |
| 24A | Test coverage (phases 13–23) | ✅ Complete |
| 24B | Multi-skill blended routing | ✅ Complete |
| 25 | Production deployment (Railway) | ✅ Complete |
| 26 | Intraday reforecast | ✅ Complete |

Phase 26 (intraday reforecast) delivered: `ui/tab_intraday.py` — operational
real-time reforecasting tab. User inputs current interval (shown as HH:MM) and
actual calls received so far; engine computes a scale factor and applies it to
remaining intervals. Re-runs Erlang C on scaled demand. Four summary metrics:
demand vs plan %, projected day total, at-risk interval count, peak agent gap.
Two charts: demand plan vs reforecast (bar + line), agent requirement comparison
with shaded gap and "Now" marker. At-risk intervals table with gradient
highlighting. Collapsible SL%/occupancy projection for remaining intervals.
Auto-runs on load with plan defaults. Inserted at tabs[9]; downstream tabs
renumbered. Session state keys added under Phase 26 block in `_init_session_state()`.

Phase 23 (deployment hardening) delivered: end-to-end cloud deployment support
for Railway and Render. `render.yaml` and `railway.toml` platform config files
added. `app.py` extended with `_resolve_credentials_path()` — checks for
`auth/credentials.yaml` on disk first; falls back to `CREDENTIALS_YAML_B64` env
var (base64-encoded YAML) for cloud deployments where file mounts are unavailable.
Decoded file written once to `/tmp/wfsim_credentials.yaml` per container lifetime.
`Dockerfile` updated: `curl` installed via apt for the HEALTHCHECK, `mkdir -p
state configs` ensures writable directories exist in the image even without volume
mounts, `start-period` bumped to 30 s to give the app time to initialise before
first health probe. `docker-compose.yml` adds `./configs:/app/configs` volume mount
so named config snapshots survive container rebuilds. `.env.example` updated with
`CREDENTIALS_YAML_B64` variable and generation instructions. README updated with
Option C (Render) and Option D (Railway) deployment sections. Local Docker and
local Python flows are completely unchanged.

Phase 24A (test coverage) delivered: unit test modules added for four previously
untested phases. `tests/test_cost_model.py` — 31 tests covering `CostConfig`
defaults, `calculate_interval_costs()` (labour, idle, breach, DES override, edge
cases), `calculate_cost_summary()`, and `project_monthly_labour_cost()`.
`tests/test_config_store.py` — 18 tests covering list/save/load/delete round-trips,
name validation, date serialisation, and `config_exists()`, all using
`tempfile.TemporaryDirectory` + `patch.multiple`. `tests/test_excel_export.py` —
8 tests (skipped without openpyxl) verifying bytes output, valid .xlsx structure,
required sheets, and graceful empty-input handling; plus an always-run fallback test
checking `RuntimeError` is raised when openpyxl is absent. `tests/test_charts.py` —
26 tests covering `PALETTE` (length, format), semantic colour constants, and
`apply_dark_theme()` (bgcolor, grid colour, font, title colour); all chart test
classes use `@skipUnless` guards for both plotly and `ui.charts` importability.

Phase 25 (production deployment) delivered: live Railway deployment for AA Limited.
`railway.toml` corrected: `restartPolicyType` changed to `"ON_FAILURE"` (uppercase,
Railway's current API requirement); `startCommand` added as `sh -c 'streamlit run
app.py --server.port=$PORT ...'` to ensure Railway's injected `PORT` env var is
shell-expanded before being passed to Streamlit (direct exec form does not expand
vars); `healthcheckTimeout` bumped to 300 s to accommodate cold-start import time.
`auth/keygen.py` and `tests/test_key_validator.py` fixed for Python 3.9
compatibility: `int | None` union syntax (3.10+) replaced with `Optional[int]` from
`typing`. Deployment key generated for AA Limited (expires 2027-03-18).
`auth/credentials.yaml` created from example with bcrypt-hashed credentials (git-
ignored). `DEPLOYMENT_KEY` and `CREDENTIALS_YAML_B64` set as Railway environment
variables. Persistent volume mounted at `/app/state`. App live and health-check
passing on Railway us-east4.

Phase 24B (multi-skill blended routing) delivered: analytical and simulation models
for comparing siloed vs. fully-blended agent pool staffing. `models/multi_skill.py`
— `QueueSpec` dataclass (per-interval queue definition with derived `traffic_intensity`,
`interval_seconds`, `sl_target_fraction`, `shrinkage_fraction`), `SkillGroup`
dataclass (`can_serve()` method), `solve_blended_erlang(queues)` (returns DataFrame
with per-queue siloed Erlang C rows + "── Blended total ──" summary showing
`blended_net_agents`, `blended_paid_agents`, `blended_sl_pct`, `pooling_benefit_net`),
and `pooling_benefit_agents(df)` scalar extractor. Blended pool uses combined offered
load, traffic-weighted AHT, traffic-weighted SL target, and most-demanding threshold
(conservative). `simulation/des_multi_queue.py` — standalone multi-queue multi-skill
DES (intentionally bypasses `des_runner.py` — see architectural note below). One
`simpy.Resource` per skill group; calls race eligible groups via `simpy.AnyOf`;
dedicated-first routing (ascending queue-count sort); abandonment via `env.timeout`
race; untriggered requests cancelled via `resource.release(req)` (correct simpy 4.1.1
pattern). Returns `list[MultiQueueSimResult]`. `ui/tab_blended.py` — Blended Queues
tab with queue editors (2–3 queues), Erlang C siloed vs. blended summary metrics and
table, comparison bar chart, skill group editors (1–3 groups), DES run button (disabled
without simpy or zero headcount), per-queue DES results (metrics + SL vs target bar
chart). `tests/test_multi_skill.py` — 33 tests covering `QueueSpec`, `SkillGroup`,
`solve_blended_erlang()`, and `pooling_benefit_agents()`. `app.py` updated: import,
`bl_*` session state defaults, "Blended Queues" tab at index 7, tabs 8–13 renumbered.

Phase 22 (quick Erlang C calculator) delivered: `ui/tab_quickcalc.py` —
self-contained single-interval calculator tab (no sidebar dependency, no CSV
required). Three-column input panel: Demand (calls, AHT, interval), Service
Level (SL target %, answer-within threshold), Staffing (shrinkage %, max
occupancy %). Results row: net agents, paid agents (shrinkage-adjusted),
predicted SL%, predicted ASA, predicted occupancy, traffic intensity in
Erlangs. Sensitivity section: `±8 agents` sweep chart (SL% + occupancy on
dual y-axis, SL target reference line, required-agents marker) plus
collapsible sensitivity table. Inserted at `tabs[1]` — immediately after
Overview. Existing tabs shifted +1 in `app.py`.

Phase 21 (chart consistency pass) delivered: `ui/charts.py` created as shared
chart utilities module. Contains `PALETTE` (8-colour indigo/zinc palette),
semantic colour constants (`C_REQUIREMENT`, `C_ROSTER`, `C_SIMULATION`,
`C_FORECAST`, `C_COST`), and `apply_dark_theme(fig)` which sets
`paper_bgcolor`/`plot_bgcolor` to transparent, `gridcolor="#27272A"`, font to
Inter, and title colour `#FAFAFA`. Applied to every `go.Figure` and `px.*`
chart across all tabs: tab_demand, tab_des, tab_planning, tab_forecast,
tab_optimisation, tab_cost, tab_scenarios, tab_multiqueue, tab_roster. All
tabs now render with the unified zinc/indigo dark theme.

Phase 20 (caching layer) delivered: `@st.cache_data` wrappers added in
`app.py` for both expensive model calls — `deterministic_staffing()` and
`solve_staffing_erlang()`. Cache keyed on DataFrame content + frozen
`SimConfig`; reruns only when inputs change. Zero changes to model files.

Phase 19 (Gantt shift schedule visualisation) delivered: `_render_shift_gantt()`
added to ui/tab_roster.py. Plotly horizontal bar chart — one bar per active shift
template showing start time, duration, and head count. Break windows overlaid as
hatched zinc bands per ruleset. Coverage vs requirement line chart below Gantt.
Both charts share a HH:MM time-of-day x-axis. Displayed in an expander immediately
after the 3 roster summary metrics.

Phase 18 (overview dashboard) delivered: ui/tab_overview.py — read-only landing
tab inserted at tabs[0]. Five sections: Demand & Staffing (total calls, peak agents
required, avg SL%, avg occ%), Roster & Coverage (peak roster, coverage %, understaffed
intervals, paid hours), Simulation (sim SL%, abandon rate, utilisation, calls handled),
Cost (labour, idle, breach, cost per call), Workforce Planning (opening/closing HC,
deficit months, total hires). Module status strip shows 🟢/⚪ per module. Three
mini sparkline charts: agents required, SL%, and labour cost by interval. All data
from session state — graceful "run tab X to populate" captions when unavailable.
Overview tab inserted at tabs[0]; all existing tabs renumbered +1.

Phase 7 delivered: monthly workforce projection engine with cohort-based
training/ramp modelling, proportional attrition, hiring plan CSV, required FTE
plan CSV, capacity gap analysis (surplus/deficit), Workforce Planning tab,
planning_projection export. 15 unit tests added.

Phase 8 delivered: LP-based hiring optimiser (PuLP MILP), cost model (hire /
surplus / deficit costs), monthly hire cap constraint, three-scenario attrition
comparison, Hiring Optimisation tab, optimisation exports. 12 unit tests added.
Continuous attrition fix applied to project_workforce() for LP consistency.

Phase 9 (persistent state) delivered: file-based persistence layer
(persistence/state_manager.py). Sidebar, planning, and optimisation widget
values saved to state/settings.json on every run and restored on reload.
Computed DataFrames (planning_projection, optimisation_result, etc.) saved as
Parquet in state/ after each run. 20 unit tests added. state/ is git-ignored.

Phase 12 (PDF report export) delivered: reportlab Platypus PDF engine
(reports/report_builder.py). ReportConfig dataclass controls cover page
(title, date, org name) and four toggleable sections: Demand & Erlang C,
DES Simulation Results, Roster & Coverage Gaps, Workforce Planning &
Hiring Optimisation. Each section renders metric summary tables and
matplotlib Agg charts (no kaleido/Plotly dependency). Report tab added
(ui/tab_report.py) with data readiness indicators, generate button, and
download button. df_erlang stored as report_erlang_df in session state
after every compute cycle. reportlab==4.2.5 + matplotlib==3.9.4 added to
requirements.txt.

Phase 17 (formatted Excel export) delivered: openpyxl-based workbook builder
(utils/excel_export.py). Multi-sheet .xlsx with styled headers (indigo fill, white
text), alternating row shading, auto-sized columns, per-column number formats, freeze
panes, and a KPI Summary sheet. Sheets: Summary, Demand, Erlang C, Roster, Simulation,
Planning, Optimisation, Cost — Interval, Cost — Monthly. tab_downloads.py rewritten:
Excel download as primary action, individual CSV downloads below, ZIP pack at bottom.
Falls back gracefully when openpyxl is absent. openpyxl==3.1.5 added to requirements.txt.

Phase 16 (config save/load) delivered: persistence/config_store.py stores named
snapshots of all sb_* sidebar keys as JSON files in configs/. Public API:
list_configs(), save_config(), load_config(), delete_config(), config_exists().
Sidebar "Saved configs" section added: Save expander (name input + Save button),
Load/Delete expander (selectbox + Load/Delete buttons). Load restores all sb_* keys
to session state and calls st.rerun(). 2 widget keys pre-registered in _init_session_state().

Phase 15 (multi-queue comparison) delivered: up to 3 independent queues modelled
simultaneously (ui/tab_multiqueue.py). Each queue configures name, operating hours
(open/close HH:MM), volume % of base demand, AHT, SL target, SL threshold, shrinkage,
and occupancy cap. Erlang C runs per queue on every render. Operating hours are visual-
only: grey vrect shading on charts marks inactive intervals. Stacked bar chart shows
per-queue net agent requirement + combined total line. Two-panel SL%/occ% chart with
per-queue SL target reference lines. Peak combined headcount metric. Operating hours
legend expander + per-queue and summary CSV exports. 30 widget keys pre-registered in
_init_session_state() and persisted via state_manager. Multi-Queue tab inserted at
tabs[4]; subsequent tabs renumbered.

Phase 14 (scenario planning overhaul) delivered: complete rewrite of ui/tab_scenarios.py.
Up to 4 named scenarios (A–D) + baseline. Erlang C runs live on every render.
"Run DES" button triggers DES v2 for baseline + all active scenarios (no breaks,
configurable abandonment + patience). Side-by-side summary table with Δ vs baseline
columns (colour-coded red/green). Three-panel interval chart (agent req, SL%, occ%).
Optional DES interval charts (simulated SL%, abandon rate%). CSV export for both
Erlang and DES comparisons. All 44 widget keys pre-registered in _init_session_state()
and persisted via state_manager. sc_des_results stored in session state (not persisted).

Phase 13 (cost & financial analytics) delivered: CostConfig dataclass and per-interval
cost engine (models/cost_model.py). Per-interval labour, idle, and SLA breach cost
calculations; cost-per-call trend; idle/overstaffing breakdown; monthly labour cost
projection overlaid on workforce planning output. Sidebar Finance & operations section
added with agent cost rate (hourly or annualised — conversion to hourly happens in
sidebar return dict), SLA breach penalty, and idle cost fraction. Cost Analytics tab
added (ui/tab_cost.py) with 6 KPI metrics, 3 Plotly charts, and monthly projection
chart. cost_interval_df and cost_monthly_df stored in session state. 5 new default
settings added to state_manager.py.

Phase 11 (demand forecasting) delivered: STL-based demand forecasting engine
(demand/demand_forecaster.py). Aggregates historical interval data to daily
totals, runs STLForecast + ETS (statsmodels), distributes forecast across
intervals using historical average intraday profile. Confidence intervals at
80/90/95%. Demand Forecast tab added. Forecast pushes into the simulation
pipeline with one click (forecast_demand_df session state key). 26 unit tests
(12 pass without statsmodels; 14 run on full install). statsmodels + scipy added
to requirements.txt.

Phase 10 (authentication + deployment) delivered: RSA-signed deployment keys
(auth/keygen.py + auth/key_validator.py), streamlit-authenticator login screen
with bcrypt-hashed credentials in auth/credentials.yaml, Dockerfile +
docker-compose.yml for one-command startup, .env pattern for secrets,
README.md with 10-minute setup guide. auth/private_key.pem and
auth/credentials.yaml are git-ignored.

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
| `demand/demand_forecaster.py` | **Phase 11 forecasting engine** — ForecastParams dataclass + forecast_demand() |
| `ui/tab_forecast.py` | Demand Forecast tab (Phase 11) |
| `reports/report_builder.py` | **Phase 12 PDF engine** — ReportConfig dataclass + build_report() |
| `ui/tab_report.py` | Report tab (Phase 12) |
| `models/cost_model.py` | **Phase 13 cost engine** — CostConfig dataclass + calculate_interval_costs() + calculate_cost_summary() + project_monthly_labour_cost() |
| `ui/tab_cost.py` | Cost Analytics tab (Phase 13) |
| `planning/workforce_planner.py` | **Phase 7 projection engine** — PlanningParams dataclass + project_workforce() |
| `planning/hiring_loader.py` | Loaders for hiring_plan.csv and required_fte_plan.csv |
| `optimisation/workforce_optimiser.py` | **Phase 8 LP engine** — OptimisationParams + optimise_hiring_plan() + optimise_scenarios() |
| `persistence/state_manager.py` | **Phase 9 persistence** — load_settings(), save_settings(), save_dataframe(), load_dataframes() |
| `ui/sidebar.py` | Global sidebar — returns dict of all inputs |
| `ui/tab_*.py` | One file per tab; tabs are rendered in app.py |
| `ui/tab_planning.py` | Workforce Planning tab (Phase 7) |
| `ui/tab_optimisation.py` | Hiring Optimisation tab (Phase 8) |
| `ui/date_view.py` | Shared date/interval view helpers + `ensure_x_col` |
| `ui/charts.py` | **Phase 21 chart utilities** — `apply_dark_theme()`, `PALETTE`, semantic colour constants |
| `ui/tab_quickcalc.py` | **Phase 22 quick calculator** — self-contained single-interval Erlang C calculator |
| `ui/tab_overview.py` | **Phase 18 overview dashboard** — read-only KPI landing tab |
| `models/multi_skill.py` | **Phase 24B** — `QueueSpec`, `SkillGroup`, `solve_blended_erlang()`, `pooling_benefit_agents()` |
| `simulation/des_multi_queue.py` | **Phase 24B** — standalone multi-queue multi-skill DES; `MultiQueueSimResult` + `simulate_multi_queue()` |
| `ui/tab_blended.py` | **Phase 24B** — Blended Queues tab; queue editors, Erlang C comparison, skill group editors, DES validation |
| `render.yaml` | **Phase 23** — Render.com deployment blueprint (Docker, persistent disk, env vars) |
| `railway.toml` | **Phase 23** — Railway deployment config (Dockerfile build, healthcheck, restart policy) |
| `utils/export.py` | CSV + ZIP export generation |
| `utils/excel_export.py` | **Phase 17 Excel engine** — build_simulation_workbook() → formatted .xlsx bytes |
| `persistence/config_store.py` | **Phase 16 config store** — save/load/delete named sb_* snapshots in configs/ |

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
| `optimisation_result` | DataFrame | tab_optimisation | tab_downloads |
| `optimisation_scenarios` | DataFrame | tab_optimisation | tab_downloads |
| `forecast_demand_df` | DataFrame or None | tab_forecast | app.py demand block |
| `report_erlang_df` | DataFrame | app.py | tab_report |
| `report_pdf_bytes` | bytes or None | tab_report | tab_report download button |
| `cost_interval_df` | DataFrame | tab_cost | tab_downloads |
| `cost_monthly_df` | DataFrame | tab_cost | tab_downloads |

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
| `tests/test_workforce_optimiser.py` | Phase 8 LP optimiser — 12 tests (requires pulp) |
| `tests/test_state_manager.py` | Phase 9 persistence layer — 20 tests (parquet test skipped without pyarrow) |
| `tests/test_shrinkage_calculator.py` | Phase 6 remainder — observed shrinkage — 17 tests |
| `tests/test_key_validator.py` | Phase 10 deployment key validation — 11 tests |
| `tests/test_demand_forecaster.py` | Phase 11 forecasting engine — 26 tests (14 skip without statsmodels) |
| `tests/test_cost_model.py` | Phase 13 cost engine — 31 tests |
| `tests/test_config_store.py` | Phase 16 config store — 18 tests |
| `tests/test_excel_export.py` | Phase 17 Excel export — 8 tests (openpyxl required; fallback test always runs) |
| `tests/test_charts.py` | Phase 21 chart utilities — 26 tests (22 skip without plotly) |
| `tests/test_multi_skill.py` | Phase 24B blended staffing model — 33 tests |

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

**`des_runner.py` is the only DES entry point** for single-queue simulations. The UI,
solver, and scenario runner all call `run_des_engine()` from `des_runner.py`. Never
call `simulate_day_des` or `simulate_day_des_v2` directly from tab code.

**`des_multi_queue.py` is a deliberate exception to the above rule.** The Phase 24B
multi-queue simulation (`simulation/des_multi_queue.py`) does NOT route through
`des_runner.py`. Multi-queue routing requires per-group `simpy.Resource` objects,
`simpy.AnyOf` racing, and cross-queue competition — fundamentally different process
topology from the single-queue DES interface. Forcing it through `des_runner.py`
would distort the model. `ui/tab_blended.py` calls `simulate_multi_queue()` directly.

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

**`tab_planning.py` and `tab_optimisation.py` own their own inputs.** Unlike
other tabs that receive pre-computed DataFrames from `app.py`, these tabs manage
their own file uploaders and parameter widgets internally. Results are stored in
session state for `tab_downloads` to consume.

**The LP optimiser and project_workforce() use the same attrition model.**
Both use continuous geometric decay: `cohort_size × (1 - attrition_rate)^elapsed`.
`project_workforce()` was updated in Phase 8 to drop `math.floor` rounding so the
simulation result is consistent with the LP's internal FTE calculation. Any future
change to attrition modelling must keep both in sync.

**Phase 9 persistence layer is best-effort and silent.** `state_manager` catches
all IO exceptions and logs warnings — it never raises. The app is fully functional
without the state/ directory. If state appears stale or corrupt, delete state/ and
the app will rebuild it from defaults on the next run.

**Phase 10 auth is two-layer.** The deployment key gate (Alex-controlled) runs first;
the login screen (org-controlled) runs second. Both are bypassed gracefully when their
dependencies are absent, which means the app runs without auth in development. The key
validator never makes network calls — validation is fully offline using the embedded
public_key.pem. Private key and credentials.yaml are git-ignored and never baked into
the Docker image (mounted as a volume at runtime).

**app.py gate order is intentional.** `_gate_deployment_key()` then `_gate_login()` are
called before `_init_session_state()` and before any sidebar or tab code runs. Both call
`st.stop()` on failure, so downstream code never executes for unauthenticated requests.

**Deployment key format.** `base64url(RSA_signature).base64url(JSON_payload)` where
payload = `{"org": ..., "issued_at": "YYYY-MM-DD", "expires_at": "YYYY-MM-DD"|null}`.
The key is opaque to the end user — they just paste it into .env.

**Sidebar widgets use `sb_` prefixed session state keys.** All sidebar widgets
now carry `key="sb_*"`. `_init_session_state()` pre-populates these from
`state_manager.load_settings()` before widgets render. The return dict from
`render_sidebar()` reads from `st.session_state[key]` — do not add a `value=`
path that bypasses this.

**Widget state keys are the persistence keys.** The `key=` argument on every
planning and optimisation tab widget matches the key in `_DEFAULT_SETTINGS` in
`state_manager.py`. If a widget key is renamed in a tab, the corresponding
entry in `_DEFAULT_SETTINGS` must be updated to match.

---

## Known limitations (current)

- Scenario output comparison visuals are early-stage.
- `staffing_loader.py` uses `"staffing_interval_input"` as a placeholder `date_local`
  when only interval-indexed staffing is provided — downstream code guards for this.
- Attrition applies uniformly to all headcount including in-training and ramp agents
  (known simplification; tenure-banded attrition is not modelled).
- LP optimiser uses continuous relaxation for available_fte then rounds h[t] to
  integer hires; post-solve project_workforce() run is the authoritative output.
