# Changelog
## 2026-03-17 (Phase 15 — Multi-Queue Comparison)

### Added
Multi-queue comparison tab (ui/tab_multiqueue.py):
- Up to 3 independent queues (Q1 enabled by default, Q2/Q3 disabled)
- Per-queue config: name, open/close times (HH:MM), volume % of base
  demand, AHT (s), SL target, SL threshold, shrinkage, occupancy cap
- Erlang C runs per queue on every render using the base demand shape
  scaled by each queue's volume %
- Operating hours: grey vrect shading on charts for inactive intervals
  (visual only — Erlang calculation unaffected)
- Stacked bar chart: per-queue net agent requirement + combined total line
- Two-panel SL%/occupancy% chart with per-queue SL target reference lines
- Peak combined headcount metric (sum of queue peaks, dedicated pools)
- Operating hours legend expander
- Per-queue Erlang interval CSV + combined summary CSV downloads
- 30 mq_q* widget keys pre-registered and persisted

app.py changes:
- import render_multiqueue_tab
- 30 Phase 15 session state keys added to _DEFAULTS
- Multi-Queue tab inserted at tabs[4]; Forecast→5, Planning→6,
  Optimisation→7, Cost→8, Report→9, Downloads→10

persistence/state_manager.py:
- 30 Phase 15 widget defaults added to _DEFAULT_SETTINGS

## 2026-03-17 (Phase 14 — Scenario Planning Overhaul)

### Changed
ui/tab_scenarios.py: complete rewrite of Scenario Compare tab.

Scenario editors:
- Up to 4 named scenarios (A, B, C, D) + customisable baseline name
- Each scenario: enable checkbox, name field, volume × slider, AHT × slider
- Optional config overrides per scenario: shrinkage, occupancy cap, SL target,
  SL threshold — unchecked = inherit live baseline cfg value
- Expander header shows ✅/○ and current scenario name for quick scan
- All 44 widget keys pre-registered in _init_session_state(); removed all
  value= args to prevent widget state conflicts

Erlang C (live):
- Baseline + all enabled scenarios re-computed on every render (sub-second)
- Side-by-side summary table: Peak net req, Peak paid req, Total calls,
  Avg SL%, Avg occ%, Δ Peak net, Δ SL pp, Δ Occ pp vs baseline
- Delta columns colour-coded: red = worse, green = better

DES (on-demand):
- "Run DES" button triggers DES v2 for baseline + active scenarios
- Progress bar + per-scenario status text during run
- DES settings expander: abandonment toggle, patience slider, patience dist
- Results stored in sc_des_results session state key
- DES summary table: Avg SL%, Avg ASA (s), Abandon rate%, Total calls,
  Abandoned, Δ SL pp, Δ Abandon pp vs baseline

Charts:
- Three-panel Erlang interval chart: agent requirement, SL%, occupancy%
- Optional DES interval charts (shown when DES was run): simulated SL%,
  abandon rate% by interval
- Consistent colour palette: Baseline=blue, A=orange, B=green, C=purple, D=red
- Baseline solid line; scenarios dotted for visual differentiation

Export:
- Download expander: Erlang comparison CSV + DES comparison CSV (if run)

app.py changes:
- 44 Phase 14 session state keys registered in _DEFAULTS

persistence/state_manager.py changes:
- 44 Phase 14 widget defaults added to _DEFAULT_SETTINGS

## 2026-03-17 (Phase 13 — Cost & Financial Analytics)

### Added
Cost model engine (models/cost_model.py):
- CostConfig dataclass: hourly_agent_cost, penalty_per_abandoned, idle_rate_fraction
- calculate_interval_costs(): per-interval labour, idle, and SLA breach costs;
  uses rostered headcount if available, else Erlang net requirement as basis;
  abandoned calls from DES daily_abandon_rate if available, else Erlang SL gap proxy
- calculate_cost_summary(): aggregate totals, cost-per-call, idle cost pct,
  overstaffed/understaffed interval percentages
- project_monthly_labour_cost(): overlays monthly_labour_cost, monthly_required_cost,
  monthly_cost_gap onto workforce planning projection (151.67 hr/month basis)

Cost Analytics tab (ui/tab_cost.py):
- 6 KPI metrics with staffing basis and abandon-source captions
- Chart 1: stacked bar — labour cost + SLA breach cost per interval
- Chart 2: cost per call line (left axis) + agents rostered dotted line (right axis)
- Chart 3 (expander): idle cost bar + surplus agents line (dual-axis)
- Monthly labour cost projection bar/line chart (requires Workforce Planning data)
- Raw interval cost data table (expander)
- Stores cost_interval_df and cost_monthly_df in session state

Sidebar Finance & operations section (ui/sidebar.py):
- Agent cost rate type selectbox: Hourly (£/hr) vs Annualised (£/year)
- Agent cost rate number input (label adapts to rate type)
- Annual working hours per FTE input (only shown for annualised mode)
- SLA breach penalty (£/abandoned call) input
- Idle time cost fraction slider (in Advanced cost settings expander)
- Return dict now includes hourly_agent_cost (with annualised→hourly conversion),
  penalty_per_abandoned, idle_rate_fraction

app.py changes:
- Imports render_cost_tab, CostConfig
- cost_interval_df and cost_monthly_df added to _DEFAULTS
- 5 new sb_cost_* sidebar widget defaults added to _DEFAULTS
- CostConfig constructed from sidebar_inputs after SimConfig
- "Cost Analytics" tab added at tabs[7]; Report → tabs[8]; Downloads → tabs[9]

state_manager.py changes:
- 5 new Phase 13 default settings: sb_cost_rate_type, sb_agent_cost_rate,
  sb_annual_working_hours, sb_penalty_per_abandoned, sb_idle_rate_fraction
- _deserialise guard added for sb_cost_rate_type to reject stale values

## 2026-03-17 (Phase 12 — PDF Report Export)

### Added
PDF report generation engine (reports/report_builder.py).

ReportConfig dataclass:
- org_name: organisation name on cover and document metadata
- report_date: date shown on cover (defaults to today)
- include_demand / include_des / include_roster / include_workforce:
  toggle each section independently

build_report(config, data) approach:
- Cover page: title, org name, report date, table of contents
- Section 1 — Demand & Erlang C: metrics table + calls/agents dual-axis
  chart + SL & occupancy line chart
- Section 2 — DES Results: metrics table + DES calls/wait bar+line chart
  + daily summary table
- Section 3 — Roster & Gaps: metrics table + grouped bar chart +
  daily summary table
- Section 4 — Workforce Planning & Hiring: headcount projection line
  chart + projection table + optimal hires bar chart + optimisation table
- Sections with no data include a placeholder note rather than crashing
- Uses matplotlib.figure.Figure (non-interactive, Agg-safe — no kaleido)
- reportlab Platypus (A4, 20 mm margins), navy/blue colour scheme

Report tab (ui/tab_report.py):
- Org name + report date inputs
- Section checkboxes
- Data readiness indicators for all five data sources
- Generate button with st.spinner, download button
- report_pdf_bytes stored in session state for the download button

app.py changes:
- import render_report_tab
- report_erlang_df and report_pdf_bytes added to _DEFAULTS
- df_erlang stored as st.session_state["report_erlang_df"] after every
  compute cycle
- "Report" tab added between Hiring Optimisation and Downloads (tabs[7])
- Downloads renumbered to tabs[8]

requirements.txt:
- reportlab==4.2.5 (PDF layout engine)
- matplotlib==3.9.4 (chart rendering, max stable for Python 3.9)

---

## 2026-03-17 (Phase 11 — Demand Forecasting)

### Added
STL demand forecasting engine (demand/demand_forecaster.py).

ForecastParams dataclass with fields:
- historical_df: multi-day demand DataFrame in canonical schema
- horizon_days: number of future days to forecast (default 7)
- intervals_per_day: intervals per day (default 96 for 15-min)
- confidence_level: prediction interval coverage (default 0.90)
- stl_period: seasonal period in days for STL (default 7 — weekly)
- min_history_days: minimum distinct days required (default 14)

forecast_demand() approach:
1. Aggregate historical interval data to daily totals
2. Run STLForecast + ETS (additive error + trend) from statsmodels
3. Compute interval-level forecast by applying historical average intraday
   profile (proportion of daily calls per interval) to each forecast day
4. Scale confidence bounds by same intraday proportions
5. Return DataFrame compatible with the existing simulation pipeline
   (date_local, interval_in_day, global_interval, calls_offered + CI columns)

Column validation runs before the statsmodels import check so missing-column
errors are always raised even when statsmodels is absent.

---

### Added
Demand Forecast tab (ui/tab_forecast.py).

New tab inserted between Scenario Compare and Workforce Planning:
- Historical demand CSV uploader (reuses load_demand_csv)
- Forecast horizon (1–90 days), confidence level (80/90/95%), intervals per day
- Advanced expander: STL seasonal period and minimum history controls
- Run Forecast button with spinner
- Summary metrics: total forecasted calls, avg daily volume, delta vs historical
- Interval-level forecast chart with confidence band and day boundary markers
- STL decomposition chart (trend, seasonal, residual) in expandable section
- Raw forecast data table
- "Use as demand input" button — pushes forecast into session state as
  forecast_demand_df; all simulation tabs immediately use forecasted demand
- "Download forecast CSV" export button
- "Discard preview" and "Clear forecast demand" controls

---

### Added
Forecast demand priority in app.py.

When forecast_demand_df is non-empty in session state, it is used as df_inputs
in preference to manual CSV upload or synthetic demand. A persistent blue info
banner marks the forecast as active. The existing manual demand path is unchanged
and takes over immediately when the forecast is cleared.

---

### Added
forecast_demand_df persistence in state_manager.py.

Added to PERSISTENT_DF_KEYS (saved as state/forecast_demand_df.parquet).
Uses None as the default (not empty DataFrame) — app.py checks is not None to
decide whether forecast mode is active. Restored on reload so an active forecast
survives browser refreshes.

---

### Added
requirements.txt updated with Phase 11 direct dependencies:
- statsmodels==0.14.4
- scipy==1.14.1

---

### Added
Test suite for forecasting engine (tests/test_demand_forecaster.py).

26 tests across TestValidateParams, TestIntradayProfile, TestDailySeries,
TestForecastDemand. 14 tests require statsmodels and skip gracefully when absent.
12 tests run without statsmodels (helpers + column validation).

---

## 2026-03-17 (Phase 10 — Authentication + Deployment)

### Added
RSA-signed deployment key system (auth/keygen.py + auth/key_validator.py).

Alex holds the RSA 2048-bit private key (auth/private_key.pem — git-ignored, never
distributed). The public key (auth/public_key.pem) is embedded in the repo and Docker
image. Deployment keys are issued per-organisation, optionally time-limited, and
verified entirely offline with no network calls.

Key format: base64url(RSA_PKCS1v15_SHA256_signature).base64url(JSON_payload)
Payload: {"org": "...", "issued_at": "YYYY-MM-DD", "expires_at": "YYYY-MM-DD"|null}

---

### Added
Login screen via streamlit-authenticator.

Users are managed in auth/credentials.yaml (git-ignored) with bcrypt-hashed passwords.
Each organisation controls their own user list — there is no central user database.
The login gate runs in app.py after the deployment key check and before any app content
is rendered.

---

### Added
Docker deployment (Dockerfile + docker-compose.yml).

python:3.11-slim base image, all pinned dependencies installed from requirements.txt.
docker-compose mounts ./state (persistence) and auth/credentials.yaml (read-only) as
volumes so secrets are never baked into the image. One-command startup:
  docker-compose up --build

---

### Added
Secret management pattern (.env.example).

DEPLOYMENT_KEY is read from the environment. .env.example documents the pattern.
.env is git-ignored.

---

### Added
README.md with 10-minute setup guide.

Covers: prerequisites, local setup (venv + manual env vars), Docker setup,
deployment key acquisition, user management, file structure, running tests.

---

### Added
requirements.txt updated with Phase 10 direct dependencies:
- streamlit-authenticator==0.3.3
- cryptography==42.0.5
- PyYAML==6.0.2
- bcrypt==4.2.1

---

### Added
auth/credentials.yaml.example — template for per-org user management with
instructions for bcrypt hash generation and cookie key setup.

---

### Architecture
app.py gate order: _gate_deployment_key() → _gate_login() → _init_session_state()
→ main app. Both gates call st.stop() on failure so no downstream code runs for
unauthenticated requests. Both degrade gracefully (allow access) when their
dependencies are not installed, keeping the dev workflow unaffected.

---

## 2026-03-17 (Phase 6 remainder — observed shrinkage)

### Added
Observed shrinkage calculator (supply/shrinkage_calculator.py).

classify_activity() classifies a free-text activity label as productive,
non_productive, or unknown using case-insensitive keyword matching against
two curated sets covering common WFM activity codes.

compute_observed_shrinkage() takes a canonical staffing DataFrame and returns:
- observed_shrinkage_pct: non-productive / classifiable staff-intervals × 100
- productive_pct, non_productive_pct, unknown_pct breakdowns
- coverage_pct: proportion of staff-weight with a known activity
- activity_breakdown: per-activity DataFrame sorted by staff weight

Weighted by available_staff where present; falls back to equal row weighting.

Demand tab updated: when activity data is present, shows four metric cards
(observed shrinkage, productive %, non-productive %, coverage %), an info banner
with the observed rate and a suggestion to apply it to the slider, an expandable
activity breakdown table, and a warning if > 10 % of intervals are unrecognised.
The existing manual activity shrinkage slider is retained unchanged.

17 unit tests added (tests/test_shrinkage_calculator.py).

---

## 2026-03-16 (Phase 9)

### Added
File-based persistence layer (persistence/state_manager.py).

Sidebar, planning tab, and optimisation tab widget values are now saved to
state/settings.json after every run and restored on app reload. No more
re-entering parameters after a browser refresh.

Computed DataFrames (planning_projection, planning_hiring_plan,
planning_required_fte, optimisation_result, optimisation_scenarios) are saved
to state/{key}.parquet after each successful run and reloaded on startup.

Persistence is best-effort and silent — the app is fully functional without the
state/ directory, which is git-ignored.

All sidebar widgets now carry key="sb_*" session state keys. _init_session_state()
pre-populates these from disk so Streamlit picks them up before any widget renders.

20 unit tests added (tests/test_state_manager.py). Parquet roundtrip test skips
gracefully when pyarrow is not present (pyarrow is a Streamlit transitive dep and
will be available in any normal install).

---

## 2026-03-16 (Phase 8)

### Fixed
Continuous attrition in project_workforce() for LP consistency.

project_workforce() previously used math.floor(hc × rate) for attrition, while
the Phase 8 LP optimiser expresses available_fte as a linear function using
geometric decay: cohort_size × (1 - a)^elapsed. The floor was removed so both
engines use the same continuous formula. Attrition column is now a float (1dp).
All 15 Phase 7 tests continue to pass.

---

### Added
LP-based hiring optimiser (optimisation/workforce_optimiser.py).

OptimisationParams dataclass added with fields:

- planning: PlanningParams (reuses Phase 7 projection parameters)
- required_fte_df: DataFrame with monthly FTE targets
- cost_per_hire: one-off cost per new hire
- cost_per_surplus_fte_month: cost of carrying excess FTE
- cost_per_deficit_fte_month: penalty for understaffing
- max_hires_per_month: hard hiring capacity constraint

optimise_hiring_plan() formulates and solves a MILP using PuLP:

- Decision variables: integer hires per month, surplus and deficit auxiliaries
- Available FTE expressed as a linear function of hire decisions using the same
  geometric decay and productivity multiplier as project_workforce()
- Post-solve, project_workforce() is called with the optimal plan to produce
  the authoritative simulation output (consistent rounding, cohort tracking)

optimise_scenarios() runs the optimiser under low / base / high attrition rates
(base ± configurable variance in pp) and returns a comparison DataFrame.

---

### Added
Hiring Optimisation tab (ui/tab_optimisation.py).

New tab added between Workforce Planning and Downloads:

- Workforce parameter inputs (independent from planning tab)
- Cost and constraint parameters: cost per hire, surplus cost, deficit cost,
  max hires per month
- Scenario variance input (±pp from base attrition)
- Required FTE plan CSV uploader (required to run optimiser)
- Summary metrics: total hires, total cost, cost breakdown, months in deficit
- Four charts: optimal hiring plan, available vs required FTE, cost breakdown
  by period, scenario comparison (hires + cost dual-axis)
- Scenario comparison table
- Period detail data table

---

### Added
Phase 8 session state keys registered in app.py:

- optimisation_result (DataFrame)
- optimisation_scenarios (DataFrame)

---

### Added
Optimisation exports in Downloads tab.

- optimisation_result.csv
- optimisation_scenarios.csv

Both added to individual download buttons and included in the ZIP pack.

---

### Added
Test suite for optimisation engine (tests/test_workforce_optimiser.py).

12 unit tests covering:

- Optimal solver status for feasible problem
- Output column presence
- One row per planning period
- Zero opening headcount forces hires when FTE target exists
- Hire cap respected: optimal_hires never exceeds max_hires_per_month
- No hires recommended when existing surplus makes hiring uneconomical
- Total cost equals sum of component costs
- High deficit penalty drives more hiring
- Scenario comparison returns three rows
- Scenario attrition rates correctly offset from base
- High attrition scenario requires >= hires vs low attrition
- Cap=0 handled gracefully

---

### Impact
The simulator now supports:

- Cost-optimal hiring plan generation across a planning horizon
- Per-month hiring capacity constraints
- Scenario robustness analysis under attrition uncertainty
- Export of optimal plans and scenario comparisons

---

## 2026-03-16 (Phase 7)

### Added
Phase 7 strategic workforce planning foundation.

A monthly workforce projection engine was introduced to model headcount and
effective FTE over a configurable planning horizon.

Core projection engine (planning/workforce_planner.py):

- Cohort-based tracking of new hire cohorts through training and ramp states
- Monthly attrition applied proportionally across all headcount
- Training phase: configurable duration and productivity contribution
- Ramp phase: linear interpolation from ramp_start_pct to 100 % FTE
- Shrinkage applied from the existing operational model to produce available_fte
- surplus_deficit column derived from available_fte vs required_fte

---

### Added
Planning CSV loaders (planning/hiring_loader.py).

Two new CSV formats supported:

- hiring_plan.csv — columns: period_start (YYYY-MM-DD), planned_hires
- required_fte_plan.csv — columns: period_start (YYYY-MM-DD), required_fte

Both loaders validate column presence, date parsing, no duplicate periods,
and non-negative values. Months absent from the hiring plan default to zero
hires in the projection.

---

### Added
Workforce Planning tab (ui/tab_planning.py).

New tab added between Scenario Compare and Downloads:

- Planning parameter inputs: horizon, opening headcount, attrition rate,
  training duration and productivity, ramp duration and start productivity
- File uploaders for hiring_plan.csv and required_fte_plan.csv
- Summary metrics: closing headcount, total hires, peak attrition,
  avg surplus FTE, months below FTE target
- Three charts: headcount over time, workforce pipeline breakdown (stacked),
  available FTE vs required FTE with surplus/deficit band
- Projection data table

---

### Added
Phase 7 session state keys registered in app.py:

- planning_projection (DataFrame)
- planning_hiring_plan (DataFrame)
- planning_required_fte (DataFrame)

---

### Added
Planning projection export in Downloads tab.

planning_projection.csv added to individual download buttons and included
in the ZIP pack.

---

### Added
Test suite for projection engine (tests/test_workforce_planner.py).

15 unit tests covering:

- Output shape and column presence
- Stable state (no attrition, no hires)
- Attrition-driven headcount decay
- Headcount flow identity
- Training pipeline: new hires invisible until training elapses
- Ramp partial FTE calculation
- Zero training and ramp: immediate full productivity
- Shrinkage applied to effective FTE
- Required FTE and surplus/deficit
- No hiring plan defaults to zero hires
- No required FTE produces NaN columns
- Period label correctness
- Attrition clamp prevents negative headcount
- Future-period hires not visible in earlier periods

---

### Impact
The simulator now supports:

- Multi-month workforce planning distinct from the intraday DES layer
- Cohort-level training and ramp pipeline visibility
- FTE capacity gap analysis against a configurable demand plan
- Export of planning projections alongside operational outputs

---

## 2026-03-13

### Added
Phase 6 staffing supply import foundation.

A staffing supply input path was introduced to support:

- staffing CSV upload
- canonical staffing schema
- flexible source column mapping
- staffing validation

This establishes the base for future workforce supply modelling and activity-based shrinkage development.

---

### Added
Staffing supply preview in Demand tab.

Demand tab now supports comparison between:

- available_staff
- erlang_required_net_agents

Additional outputs include:

- staffing supply vs requirement chart
- under-supply interval chart
- staffing daily summary table
- staffing gap export dataset

---

### Added
Additional supply-related exports.

Downloads flow was extended to support:

- staffing_daily_summary.csv
- staffing_gap_export.csv

These outputs are stored in session state in the same pattern as demand, roster, and DES summary exports.

---

### Improvements
Shared x-axis helper introduced.

A central ensure_x_col helper was added to the date view utility and adopted across Demand, Roster, and DES tabs.

This removes duplicated helper logic and improves timestamp/interval plotting safety.

---

### Improvements
UI stability and debug fixes.

Multiple runtime and rendering fixes were applied including:

- guarded staffing loader import in app startup
- corrected num_intervals handling for timestamp-based demand
- cleaned schema-aware date_local handling for interval-based demand
- duplicate timestamp validation after timezone conversion
- safer roster/requirement merge behaviour
- infeasible LP solver handling
- Legacy DES indexing fix (.iloc)
- Erlang iteration cleanup using array iteration
- duplicate Streamlit key fixes
- x-axis radio option fixes in Roster and DES tabs
- removal of stale helper references after shared-helper migration

---

### Impact
The simulator now supports:

- early-stage workforce supply ingestion
- supply vs requirement operational comparison
- supply-related exports
- stronger tab stability
- cleaner shared plotting behaviour

## 2026-03-09

### Added
Multi-day operational modelling support.

Demand ingestion now supports:
- start_ts_local
- date_local
- interval_in_day
- global_interval

These allow demand modelling across multiple days while preserving compatibility with interval-based models.

---

### Added
Date-aware visualisation layer.

Demand, roster, and DES charts now support:

- timestamp x-axis
- interval x-axis fallback
- full horizon view
- selected day view

Date view controls allow filtering of multi-day datasets safely without affecting modelling logic.

---

### Added
Daily operational summaries.

Daily summary tables were introduced across key modules:

Demand summary includes:
- total calls
- peak requirement
- predicted service level
- predicted occupancy

Roster summary includes:
- total calls
- peak requirement
- peak roster
- coverage ratio

DES summary includes:
- total calls
- service level
- ASA
- abandonment rate

---

### Added
Executive summary panel in DES tab.

High-level KPI cards now display:

- Total calls
- Peak requirement
- Peak roster
- Service level
- ASA
- Abandon rate

These metrics are derived directly from existing DES outputs.

---

### Added
Validation and warning layer.

User-facing warnings now appear when:

- timestamp mode unavailable
- selected day contains no rows
- daily summaries unavailable
- scenario multipliers active
- roster/requirement metadata mismatch

This improves usability without modifying modelling behaviour.

---

### Added
Exportable operational summaries.

Downloads tab now supports exporting:

- demand_daily_summary.csv
- roster_daily_summary.csv
- des_daily_summary.csv

Summaries are stored in session state and exported without recomputation.

---

### Improvements
Simulator stability improvements.

Multiple fixes applied during development including:

- scope corrections for req_col
- scenario multiplier variable corrections
- defensive checks for missing timestamp metadata
- solver result safety checks
- prevention of stale session state summaries

---

### Impact
The simulator now supports:

- multi-day operational modelling
- scenario testing
- executive KPI dashboards
- operational summary exports
- improved UI validation

## 2026-03-07

### Added
DES v2 simulation engine.

### Improvements
Explicit call lifecycle modelling.
Queue length diagnostics.
Agent busy/idle metrics.
DES engine selector in UI.

### Notes
Legacy DES retained for comparison.

---

## 2026-03-08

### Improvements
Time-weighted queue and agent state metrics added to DES v2.

Queue length now computed using time-weighted integration rather than snapshot sampling.

Agent busy and idle metrics converted to interval averages.

### Impact
Improves simulation accuracy and stability of operational diagnostics.

---

## 2026-03-08 (later)

### Added
Break modelling framework.

Two break modelling modes:
Manual interval break blocks.
Shift-based break generation using shift templates and break rules.

Break curve visualisation added to DES tab.

Break schedules now dynamically reduce available agents during simulation.

### Added
DES staffing solver.

Solver iteratively adjusts staffing per interval to reach operational targets.

Solver outputs include:
Base staffing vs solver-required staffing chart.
Staff added per interval chart.
Solver diagnostics metrics.

### Improvements
Solver now evaluates both:
Service level performance
Abandonment rate

Intervals are flagged as failing when:

Service level < target  
OR  
Abandonment rate > target

### Diagnostics
Solver now reports:

Final service level
Final abandonment rate
Stop reason:
Target met
Stagnated
Iteration cap reached

---

## 2026-03-08 (latest)

### Added
Central simulation wrapper.

simulation/des_runner.py now acts as the common simulation entry point.

### Added
Scenario stress testing engine.

analysis/scenario_runner.py introduced to:

apply scenario shocks  
run DES  
run staffing solver on shocked conditions

### Added
Scenario controls in DES tab.

Current scenario inputs include:

Volume multiplier  
AHT multiplier  
Patience multiplier

### Improvements
Staffing solver diagnostics expanded.

New solver outputs include:

Peak staff delta  
Max interval uplift  
Total staff added  
Final DES SL  
Final abandon  
Stop reason

### Improvements
Solver convergence improved through:

adaptive interval uplift  
neighbour smoothing  
abandonment-aware failing interval logic  
stagnation handling

---

## 2026-03-08 (late development session)

### Added
Interval-based workforce simulation framework.

The simulator now models contact centre demand using fixed-length time intervals
(default 15 minutes) rather than daily aggregates.

Core interval metrics now include:

Calls offered  
Average handle time  
Workload seconds  
Workload hours  
Required concurrent agents

### Added
Deterministic workforce model.

Deterministic staffing calculation introduced to estimate required agents per interval using workload mathematics.

Outputs include:

Workload hours per interval  
Required concurrent agents  
Required agents after occupancy cap  
Required agents after shrinkage  
Peak staffing requirement  
Average staffing requirement

### Added
Erlang-C staffing model.

Queueing theory model added to estimate:

Required staffing  
Predicted service level  
Predicted ASA  
Predicted occupancy

Erlang solver now operates at the interval level to support realistic demand curves.

### Added
Roster generation engine.

Shift-based roster generation implemented with configurable:

Shift start times  
Shift durations  
Paid vs unpaid lunch handling  
Shift template definitions

Roster output produces a coverage curve representing available agents per interval.

### Added
Roster coverage gap analysis.

Gap analysis compares roster coverage to required staffing.

Diagnostics now include:

Understaffed intervals  
Overstaffed intervals  
Coverage vs requirement chart

### Added
Roster scaling optimiser.

Roster scaling introduced to allow rapid testing of staffing changes.

Scaling adjusts roster headcount proportionally to observe impact on service levels.

### Added
Shift start optimisation (greedy algorithm).

Greedy optimiser introduced to place heads across allowed shift start times.

Optimisation objective:

Reduce understaffing  
Minimise overstaffing penalties

Outputs include:

Recommended shift start plan  
Coverage curve generated from optimiser

### Added
Linear programming shift optimisation engine.

Integer programming solver implemented using PuLP.

The solver determines the optimal mix of shift start times and shift lengths that:

Minimise total staffing  
Ensure coverage meets interval requirements

Outputs include:

Optimal shift schedule  
Shift start times  
Shift lengths  
Headcount allocation

### Added
Discrete Event Simulation (DES) validation framework.

DES simulation introduced using SimPy to replicate real call centre behaviour.

Simulation models:

Call arrivals  
Queue waiting  
Agent availability  
Service completion

DES produces operational metrics including:

Service level  
Average speed of answer  
Agent occupancy

### Added
Customer abandonment modelling.

Customer patience distributions added to DES simulation.

Supported distributions:

Exponential  
Lognormal

Simulation now tracks:

Abandon rate  
Answered calls  
Abandoned calls  
Queue delays

### Added
DES validation tab in UI.

Simulation validation interface introduced to compare predicted vs simulated performance.

DES tab includes:

Service time distribution selector  
Staffing multiplier testing  
Patience distribution controls

Outputs include interval-level charts for:

Service level  
ASA  
Occupancy  
Abandonment

### Added
Scenario comparison framework.

Scenario testing introduced to allow multiple demand or operational shocks to be evaluated.

Scenario engine supports:

Baseline scenario  
Scenario A  
Scenario B  
Scenario C

Each scenario may apply:

Volume multiplier  
AHT multiplier  
Shrinkage override  
Occupancy cap override  
Service level target override

Scenario results display:

Peak staffing  
Average service level  
Average occupancy

Scenario curves allow interval comparison between scenarios.

### Added
Timezone-aware demand ingestion.

Demand CSV loader updated to support timestamp-based inputs.

The system now supports:

Input timezone selection  
Model / display timezone selection

Timestamps are converted using:

Input timezone → modelling timezone

Additional derived fields include:

start_ts_local  
date_local  
time_local

This ensures demand intervals align with operational time zones such as Australia/Melbourne.

### Improvements
Demand ingestion flexibility.

Demand files now support two schemas:

Interval-based demand tables  
Timestamp-based demand tables

Timestamp-based datasets are automatically sorted and converted to interval indices.

### Improvements
Simulator architecture stability.

Multiple debugging fixes were applied during development including:

Variable scope fixes  
Indentation corrections  
Removal of duplicate optimiser implementations  
Correction of undefined variable references in Streamlit execution flow

### Notes
These changes collectively establish the first fully functional version of the
Call Centre Workforce Simulator, integrating deterministic staffing,
Erlang queueing theory, roster modelling, optimisation engines,
and discrete event simulation validation into a unified tool.