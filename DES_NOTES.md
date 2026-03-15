# DES Simulation Notes

## Call Lifecycle

Each call progresses through states:

arrival → waiting → in_service → completed

or

arrival → waiting → abandoned

---

## Arrival Generation

Calls are generated using a Poisson process within each interval.

Arrival timestamps are uniformly distributed across the interval.

---

## Service Time

Service times can follow:

exponential  
lognormal

Mean AHT is taken from demand input.

---

## Abandonment

If abandonment is enabled:

Each call is assigned a patience time.

If the patience deadline is reached before service begins, the call abandons.

---

## Queue Discipline

Queue currently uses FIFO behaviour.

Calls are dispatched when agents become available.

---

## Agent Capacity

Agents represent available service tokens.

When a call begins service:  
An agent token is acquired.

When service completes:  
The token is released.

Break modelling temporarily removes available tokens from the system.

---

## Break Modelling

Break modelling supports two modes.

### Manual Interval Breaks

Agents are removed between specified intervals.

Example:

interval 36–40  
20 agents unavailable

---

### Shift-Based Break Generation

Break schedules can be generated from:

shift templates  
break rules

Example shift template:

start: 08:00  
duration: 480 minutes  
heads: 80

Break rules define windows within shifts where breaks may occur.

Example rule:

Lunch  
duration: 30 minutes  
earliest offset: 240 minutes  
latest offset: 330 minutes

The system generates a break curve representing agents unavailable due to breaks.

---

## Interval Metrics

Metrics recorded per interval include:

sim_calls  
sim_answered_calls  
sim_abandoned_calls  
sim_service_level  
sim_abandon_rate  
sim_asa_seconds  
sim_busy_seconds  
sim_queue_length  
sim_busy_agents  
sim_idle_agents  
sim_break_agents  

Queue and agent metrics use time-weighted averaging.

---

## Service Level Definition

Service level is currently calculated as:

answered within threshold / total arrivals

Abandoned calls remain in the denominator.

This allows the model to expose scenarios where answered calls are fast but abandonment remains high.

---

## Solver Integration

The DES engine is used by the staffing solver.

The solver iteratively:

1. Runs DES
2. Identifies failing intervals
3. Adds agents to those intervals
4. Applies neighbour smoothing
5. Re-runs simulation

Stopping conditions:

service level ≥ target  
abandonment ≤ threshold  
or solver stagnation  
or iteration cap

---

## Solver Failure Logic

An interval is considered failing when:

service level < target  
or abandonment > threshold

This prevents the solver from stopping early in cases where:

service level appears strong  
but abandonment remains operationally unacceptable

---

## Solver Diagnostics

The solver reports:

target met  
iterations used  
peak staff delta  
max interval uplift  
total staff added  
final overall service level  
final overall abandonment  
stop reason

---

## Central Simulation Entry Point

Simulation execution is now wrapped through:

simulation/des_runner.py

This module is intended to be the common entry point for:

UI simulation runs  
solver runs  
future scenario runs  
future multi-day runs

## Multi-Day and Date-Aware Execution

The simulator now supports date-aware visualisation and filtering across DES outputs.

Where available, DES input/output data may include:

- start_ts_local
- date_local
- interval_in_day
- global_interval

These fields are used for:

- timestamp x-axis plotting
- interval fallback plotting
- selected day filtering
- full horizon viewing

Date filtering is a UI/view concern only and does not modify DES engine behaviour.

---

## Shared X-Axis Handling

A shared helper now ensures chart x-axis compatibility when timestamp fields are not present.

If the requested x-axis column is unavailable but interval exists, the system falls back safely to interval-based plotting.

This reduces duplication across Demand, Roster, and DES tabs and prevents plotting failures caused by missing timestamp metadata.

---

## Current UI Diagnostics

The DES interface now includes additional defensive behaviour such as:

- warning when selected-day views return no rows
- interval fallback when timestamp metadata is unavailable
- daily summary generation when date metadata exists
- solver diagnostics and executive summary panels
- scenario stress test controls integrated into the DES tab
