# Workforce Simulator – Project State

## Purpose

This project is a call centre workforce simulation and planning tool.

The system models demand, staffing, queue behaviour, and workforce supply to evaluate operational strategies and workforce decisions.

The application currently runs locally using Python and Streamlit.

---

# Architecture Overview

The simulator is organised into layered components.

## System Flow

Demand Input  
↓  
Workload Models  
↓  
Roster Generation  
↓  
Break Generation  
↓  
DES Simulation  
↓  
Solver Optimisation  
↓  
Scenario Stress Testing  
↓  
Diagnostics and Export

---

# Key Files

## Application Entry

app.py  
Main Streamlit application orchestrating the UI and loading all tabs.

---

## Configuration

config/sim_config.py  
Simulation configuration dataclass containing model parameters such as interval length, service targets, shrinkage, and thresholds.

---

## Demand Layer

demand/demand_loader.py  
Loads and prepares demand input from CSV or synthetic generation.

---

## Workforce Models

models/deterministic.py  
Deterministic workload calculations used for baseline staffing.

models/erlang.py  
Erlang C implementation used for analytical queue modelling.

---

## Roster Engine

roster/roster_engine.py  
Shift template handling and roster generation.

---

## Optimisation

optimisation/greedy_shift_optimizer.py  
Greedy heuristic for identifying optimal shift start placements.

optimisation/lp_shift_optimizer.py  
Linear programming optimiser using PuLP for shift allocation.

optimisation/staffing_solver.py  
DES-driven staffing optimisation engine that iteratively adjusts staffing to meet operational targets.

---

## Simulation Layer

simulation/des_simulation.py  
Discrete Event Simulation engines including Legacy DES and DES v2.

simulation/des_runner.py  
Central simulation entry point used to build DES-ready inputs and execute the selected DES engine.

simulation/break_generation.py  
Shift-based break schedule generation and break curve creation.

---

## Analysis

analysis/gap_analysis.py  
Compares staffing supply against required workload.

analysis/scenario_runner.py  
Applies scenario shocks to demand inputs and optionally runs the staffing solver.

---

## UI Layer

ui/sidebar.py  
Global sidebar controls for simulation parameters.

ui/tab_demand.py  
Demand configuration and visualisation tab.

ui/tab_roster.py  
Roster generation and optimisation interface.

ui/tab_des.py  
DES simulation controls, break modelling, solver configuration, scenario stress testing, and diagnostics.

ui/tab_scenarios.py  
Scenario modelling interface.

ui/tab_downloads.py  
Export utilities for CSV and ZIP outputs.

ui/date_view.py  
Now also contains a shared ensure_x_col helper used across Demand, Roster, and DES tabs for timestamp/interval-safe plotting.

---

## Utilities

utils/export.py  
Handles CSV and ZIP export generation.

---

# Current Capabilities

Demand modelling  
Deterministic staffing estimation  
Erlang C queue modelling  
Roster generation from shift templates  
Roster scaling optimisation  
Greedy shift start optimisation  
Linear programming shift optimisation  
Discrete event simulation (DES)  
Customer abandonment modelling  
Manual break modelling  
Shift-based break generation  
DES staffing solver  
Scenario stress testing  
Operational diagnostics  
CSV and ZIP export
Staffing supply import foundation  
Staffing supply preview and comparison  
Staffing daily summary output  
Staffing gap export output  
Shared date-aware x-axis handling  
UI startup and rendering hardening

# Workforce Supply Capabilities

Early-stage workforce supply functionality has now been introduced.

Current supply-related capabilities include:

staffing CSV ingestion foundation  
canonical staffing schema  
flexible column mapping support  
staffing validation  
staffing supply preview in the Demand tab  
comparison of available_staff vs erlang_required_net_agents  
staffing daily summary generation  
staffing gap export generation

This layer is intended as the foundation for future:

activity modelling  
dynamic shrinkage calculation  
supply-aware operational comparison  
workforce planning extensions

---

Additional capabilities added during Phase 6 development:

Multi-day demand modelling support using:

- start_ts_local
- date_local
- interval_in_day
- global_interval

Date-aware charting across Demand, Roster, and DES tabs.

View controls allow switching between:

- full horizon view
- selected day view

Daily operational summaries implemented across:

Demand tab  
Roster tab  
DES tab  

Summaries include operational metrics such as:

total calls  
peak requirement  
peak roster  
service level  
ASA  
abandon rate  

Executive KPI panel added to DES tab using Streamlit metric cards.

Export system extended to include operational summaries through the Downloads tab.

Validation layer introduced to warn users about:

missing timestamp metadata  
empty selected-day views  
scenario multiplier activation  
missing date metadata for summaries

# DES Capabilities

Legacy DES  
Token-based capacity model retained for comparison.

DES v2  
Explicit call lifecycle model with:

arrival generation  
waiting queue  
abandonment deadlines  
service start events  
service completion events  
time-weighted queue metrics  
time-weighted busy agent metrics  
time-weighted idle agent metrics  
break-aware agent availability

DES diagnostics include:

service level  
ASA  
abandonment rate  
occupancy  
queue length  
busy agents  
idle agents  
break agents

---

# Solver Capabilities

The staffing solver currently:

starts from a base staffing curve  
runs DES  
identifies failing intervals  
adds staffing adaptively  
smooths uplift into neighbouring intervals  
checks service level and abandonment constraints  
stops on target met, stagnation, or iteration cap

Solver diagnostics include:

target met  
iterations used  
peak staff delta  
max interval uplift  
total staff added  
final DES service level  
final DES abandonment  
stop reason

---

# Scenario Stress Test Capabilities

Scenario runner currently supports:

volume multiplier  
AHT multiplier  
patience multiplier  

Scenario runner can:

apply shocks to base demand  
run DES on the shocked scenario  
run the staffing solver on the shocked scenario  
return scenario staffing and performance outcomes

---

# Known Limitations

Single-day simulation model.

Friendly staffing import foundation now exists, but external WFM-specific integrations and richer activity modelling are not yet implemented.

Shrinkage remains a static factor. Activity-based supply modelling and dynamic shrinkage are still pending.

Scenario output comparison visuals are still early-stage.

Multi-day forecasting not yet implemented.

Attrition and hiring models not yet implemented.

---

# Current Development Phase

Phase 4 completed in practice for core DES accuracy improvements.

Current focus is in Phase 6 workforce supply development, including:

staffing import foundation  
supply preview and export workflows  
UI stability hardening  
preparation for activity modelling  
preparation for dynamic shrinkage calculation

