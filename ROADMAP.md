# Workforce Simulator – Development Roadmap

## Phase 4 – Simulation Accuracy ✅

Goal: Improve the reliability and realism of the DES model.

- Time-weighted queue length metrics
- Time-weighted agent utilisation metrics
- Explicit agent state tracking
- Break modelling
- Improved queue discipline modelling

---

## Phase 5 – Multi-Day Simulation ✅

Goal: Move from single-day simulation to multi-day planning.

- Replace interval index with datetime timestamps
- Support multi-day demand files
- Enable week and month simulations
- Date-aware visualisation controls
- Representative-day DES simulation

---

## Phase 6 – Workforce Supply Model ✅

Goal: Model and analyse workforce supply alongside demand.

- Friendly staffing file upload ✅
- Canonical staffing schema ✅
- Flexible staffing column mapping ✅
- Staffing preview and supply gap export ✅
- Observed shrinkage from activity data ✅
- Activity classification engine ✅
- Upload format guidance in UI ✅

---

## Phase 7 – Strategic Workforce Planning ✅

Goal: Support long-term workforce planning.

- Cohort-based attrition modelling ✅
- Hiring pipeline simulation ✅
- Training and ramp modelling ✅
- Monthly capacity projections ✅
- Hiring plan and required FTE CSV ingestion ✅

---

## Phase 8 – Optimisation Engine ✅

Goal: Automate workforce planning decisions.

- LP-based optimal hiring plan (PuLP MILP) ✅
- Cost modelling (hire / surplus / deficit) ✅
- Monthly hire cap constraint ✅
- Three-scenario attrition comparison ✅

---

## Phase 9 – Platform Development ✅

Goal: Make the app persistent and resilient across sessions.

- File-based persistence (settings.json + Parquet DataFrames) ✅
- All widget values survive app reload ✅
- Computed results restored on startup ✅

---

## Phase 10 – Authentication + Deployment ✅

Goal: Distribute the tool securely to analysts in any organisation.

- RSA-signed deployment keys (Alex controls who can run the app) ✅
- Offline key generation script (no server required) ✅
- streamlit-authenticator login screen with bcrypt-hashed credentials ✅
- Per-organisation local user management via YAML ✅
- Dockerfile and docker-compose.yml for one-command startup ✅
- .env pattern for secrets ✅
- README with 10-minute setup guide ✅

---

## Phase 11 – Demand Forecasting (Tier 1)

Goal: Make the tool self-contained by forecasting demand from historical data.

**Why this matters:** Currently users must supply their own demand curve. This is
the single biggest gap for a standalone planning tool. Filling it means an analyst
can go from raw historical data to a full simulation without leaving the app.

Planned scope:
- Upload historical call volume CSV (date + interval + calls)
- Seasonal decomposition (STL) to separate trend, seasonality, and residual
- Rolling average and weighted average forecasting options
- Confidence interval bands on forecast output
- Forecast output feeds directly into the existing simulation pipeline
- Forecast export (CSV) alongside existing Downloads tab exports

---

## Phase 12 – PDF Report Export (Tier 1)

Goal: Generate client-ready reports directly from simulation results.

**Why this matters:** For consulting use, results need to be presentable to
stakeholders without manual copy-paste into PowerPoint or Word. Low effort,
disproportionately high value.

Planned scope:
- Auto-generate a structured PDF from whatever has been run in the current session
- Sections: demand summary, Erlang/DES results, roster analysis, workforce
  projection, hiring optimisation, scenario comparison
- Charts embedded as images
- Configurable: user selects which sections to include
- Branding placeholder (org name/logo on cover page)

---

## Phase 13 – Multi-Queue / Multi-Skill Modelling (Tier 2)

Goal: Model real contact centres accurately — most have multiple queues with
shared or blended agents.

**Why this matters:** Single-queue Erlang C is a known simplification. Centres
with priority queues, overflow routing, or multi-skilled agents behave
differently. This is technically the most differentiating feature on the roadmap
— nothing in the accessible WFM space models this well.

Planned scope:
- Multiple queue definitions (name, volume, AHT, SL target per queue)
- Agent skill groups (which queues each group can handle)
- Overflow and blending rules (e.g. queue A overflows to queue B after N seconds)
- DES extended to route calls across queues with priority logic
- Per-queue and aggregate SL / ASA / abandon reporting
- Erlang C extended to multi-server approximation for blended queues
- Workforce planning and optimisation updated to model multi-skill staffing

---

## Phase 14 – Scenario Comparison Polish (Tier 3)

Goal: Make the Scenario Compare tab a first-class analysis surface.

Currently early-stage. Planned improvements:
- Side-by-side metric cards across scenarios
- Overlay charts (SL, ASA, abandon rate across scenarios on one chart)
- Waterfall showing impact of each shock individually
- Scenario save/load (persist named scenarios to state/)
- Export scenario comparison to PDF (links to Phase 12)

---

## Notes on prioritisation

The sequencing above reflects value vs effort:

- Phase 11 (forecasting) fills the biggest capability gap and makes the tool
  self-contained for a planning workflow
- Phase 12 (PDF export) has low effort and high impact for the consulting use case
- Phase 13 (multi-queue) is the most technically differentiating feature but
  requires the most work — worth doing after the tool has real users providing
  feedback on what routing logic they actually need
- Phase 14 (scenario polish) is incremental improvement on existing functionality
