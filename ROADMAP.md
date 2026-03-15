# Workforce Simulator – Development Roadmap

## Phase 4 – Simulation Accuracy

Goal: Improve the reliability and realism of the DES model.

Tasks:

- Implement time-weighted queue length metrics
- Implement time-weighted agent utilisation metrics
- Add explicit agent state tracking
- Add break modelling
- Improve queue discipline modelling

---

## Phase 5 – Multi-Day Simulation

Goal: Move from single-day simulation to multi-day planning.

Tasks:

- Replace interval index with datetime timestamps
- Support multi-day demand files
- Enable week and month simulations
- Implement demand forecasting tools
- Allow representative-day DES simulation

---

## Phase 6 – Workforce Supply Model

Goal: Improve operational usability and reporting.

Tasks:

- Friendly staffing file upload ✅
- canonical staffing schema ✅
- flexible staffing column mapping foundation ✅
- staffing preview and supply gap export ✅
- activity modelling
- dynamic shrinkage calculation
- supply-aware roster vs requirement comparison

Additional Phase 6 enhancements implemented:

- multi-day demand support
- date-aware visualisation controls
- daily operational summaries
- executive KPI dashboard
- validation and warning layer
- operational summary exports
- session-safe download architecture
- staffing supply preview in Demand tab
- staffing daily summary output
- staffing gap export output
- shared x-axis compatibility helper
- startup and UI debug hardening

## Phase 7 – Strategic Workforce Planning

Goal: Support long-term workforce planning.

Tasks:

- attrition modelling
- hiring pipeline simulation
- training ramp modelling
- capacity projections
- annual planning scenarios

---

## Phase 8 – Optimisation Engine

Goal: automate workforce planning decisions.

Tasks:

- roster optimisation against service targets
- cost modelling
- hiring recommendations
- service risk analysis

---

## Phase 9 – Platform Development

Goal: turn the simulator into a full workforce platform.

Tasks:

- persistent data storage
- saved scenarios
- project management
- API integrations