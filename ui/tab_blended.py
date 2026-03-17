"""ui/tab_blended.py

Blended Queues tab — Phase 24B multi-skill blended routing.

Lets analysts configure 2–3 call queues and 1–3 skill groups, then compares:
  • Siloed staffing  — independent Erlang C per queue, no agent sharing.
  • Blended staffing — single fully-pooled agent group; shows the pooling
                       benefit (how many agents are saved by blending).
  • DES validation   — optional multi-queue SimPy simulation validates the
                       blended model under realistic routing conditions with
                       skill groups and partial blending.

Architecture notes
------------------
- Self-contained: receives only ``cfg`` from app.py; computes everything locally.
- Widget keys use ``bl_`` prefix; all registered in app._init_session_state().
- DES results stored in ``st.session_state["blended_des_results"]`` (a list of
  MultiQueueSimResult dicts) for the Downloads tab to consume if needed.
- Does NOT call des_runner.py — uses simulation.des_multi_queue directly.
  See CLAUDE.md for the architectural note on this deliberate exception.
"""

from __future__ import annotations

from typing import List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from config.sim_config import SimConfig
from models.multi_skill import QueueSpec, SkillGroup, solve_blended_erlang, pooling_benefit_agents
from ui.charts import apply_dark_theme, PALETTE, C_REQUIREMENT, C_SIMULATION

try:
    from simulation.des_multi_queue import simulate_multi_queue, MultiQueueSimResult
    _DES_AVAILABLE = True
except ImportError:
    _DES_AVAILABLE = False


# ---------------------------------------------------------------------------
# Queue configuration section
# ---------------------------------------------------------------------------

def _queue_editor(idx: int, prefix: str) -> QueueSpec:
    """Render inputs for one queue and return a QueueSpec."""
    label = st.session_state.get(f"{prefix}name", f"Queue {idx + 1}")

    with st.expander(f"**{label}**", expanded=(idx == 0)):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input(
                "Queue name", key=f"{prefix}name",
                help="Descriptive label for this queue.",
            )
            calls = st.number_input(
                "Calls per interval", min_value=0.0, step=1.0,
                key=f"{prefix}calls",
                help="Expected call volume in one interval (e.g. one 15-min slot).",
            )
            aht = st.number_input(
                "AHT (seconds)", min_value=1.0, step=5.0,
                key=f"{prefix}aht",
                help="Average handling time in seconds.",
            )
        with col2:
            sl_target = st.slider(
                "SL target %", 50, 99, step=1,
                key=f"{prefix}sl_target",
                help="Service level target (% of calls answered within threshold).",
            )
            sl_threshold = st.number_input(
                "Answer within (seconds)", min_value=1.0, step=5.0,
                key=f"{prefix}sl_threshold",
                help="Threshold for SL measurement (e.g. 20s for '80% in 20s').",
            )
            shrinkage = st.slider(
                "Shrinkage %", 0, 50, step=1,
                key=f"{prefix}shrinkage",
                help="Agent shrinkage to gross up net to paid headcount.",
            )
            patience = st.number_input(
                "Mean patience (seconds)", min_value=30.0, step=15.0,
                key=f"{prefix}patience",
                help="Mean customer patience before abandonment (used in DES only).",
            )

    interval_min = st.session_state.get("sb_interval_minutes", 15)
    return QueueSpec(
        name=name or f"Queue {idx + 1}",
        calls_per_interval=float(calls),
        aht_seconds=float(aht),
        sl_target_pct=float(sl_target),
        sl_threshold_sec=float(sl_threshold),
        shrinkage_pct=float(shrinkage),
        interval_minutes=float(interval_min),
        mean_patience_sec=float(patience),
    )


# ---------------------------------------------------------------------------
# Skill group configuration section
# ---------------------------------------------------------------------------

def _skill_group_editor(idx: int, prefix: str, queue_names: List[str]) -> SkillGroup:
    """Render inputs for one skill group and return a SkillGroup."""
    with st.container():
        col1, col2, col3 = st.columns([2, 3, 1])
        with col1:
            name = st.text_input(
                f"Group {idx + 1} name", key=f"{prefix}name",
            )
        with col2:
            served = st.multiselect(
                f"Queues served", options=queue_names,
                key=f"{prefix}queues",
                help="Which queues agents in this group can handle.",
            )
        with col3:
            headcount = st.number_input(
                "Agents", min_value=0, step=1,
                key=f"{prefix}headcount",
            )
    return SkillGroup(
        name=name or f"Group {idx + 1}",
        queues=served or [],
        headcount=int(headcount),
    )


# ---------------------------------------------------------------------------
# Results: Erlang C comparison table
# ---------------------------------------------------------------------------

def _render_erlang_results(df: pd.DataFrame, benefit: int) -> None:
    """Render the siloed-vs-blended Erlang C comparison."""
    if df.empty:
        return

    # ── Summary metrics ──────────────────────────────────────────────────── #
    summary = df[df["queue"] == "── Blended total ──"]
    if not summary.empty:
        s = summary.iloc[0]
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Siloed total (net)", int(s["siloed_net_agents"]) if pd.notna(s["siloed_net_agents"]) else "—")
        col2.metric("Blended total (net)", int(s["blended_net_agents"]) if pd.notna(s["blended_net_agents"]) else "—")
        col3.metric("Pooling benefit", f"{benefit} agents", delta=f"−{benefit}" if benefit > 0 else "0")
        blended_sl = s["blended_sl_pct"]
        col4.metric("Blended combined SL%", f"{blended_sl:.1f}%" if pd.notna(blended_sl) else "—")

        if benefit > 0:
            st.info(
                f"Full pooling saves **{benefit} net agent(s)** compared to siloed queues. "
                "The blended SL reflects the combined weighted target — per-queue SL is "
                "validated by the DES below.",
                icon="ℹ️",
            )

    # ── Per-queue table ───────────────────────────────────────────────────── #
    st.subheader("Siloed requirements per queue")
    display_cols = {
        "queue":               "Queue",
        "calls_per_interval":  "Calls/interval",
        "traffic_erlangs":     "Traffic (Erl)",
        "siloed_net_agents":   "Siloed net agents",
        "siloed_paid_agents":  "Siloed paid agents",
        "siloed_sl_pct":       "Siloed SL%",
        "siloed_asa_sec":      "Siloed ASA (s)",
    }
    queue_rows = df[df["queue"] != "── Blended total ──"]
    if not queue_rows.empty:
        display = queue_rows[list(display_cols.keys())].rename(columns=display_cols)
        st.dataframe(display, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Results: DES comparison
# ---------------------------------------------------------------------------

def _render_des_results(sim_results: List["MultiQueueSimResult"], queues: List[QueueSpec]) -> None:
    """Render per-queue DES results as metrics + a bar chart."""
    if not sim_results:
        return

    st.subheader("DES validation — per-queue results")

    cols = st.columns(len(sim_results))
    for i, res in enumerate(sim_results):
        with cols[i]:
            q = next((q for q in queues if q.name == res.queue_name), None)
            sl_pct = res.service_level * 100
            target_pct = q.sl_target_pct if q else None
            delta_str = f"{sl_pct - target_pct:+.1f}pp vs target" if target_pct else None
            st.metric(
                res.queue_name,
                f"{sl_pct:.1f}% SL",
                delta=delta_str,
                delta_color="normal",
            )
            st.caption(
                f"Handled: {res.calls_handled:,} | "
                f"Abandoned: {res.calls_abandoned:,} | "
                f"ASA: {res.asa_seconds:.0f}s"
            )

    # ── Bar chart: SL% per queue vs target ───────────────────────────────── #
    queue_names = [r.queue_name for r in sim_results]
    sim_sl = [r.service_level * 100 for r in sim_results]
    targets = [next((q.sl_target_pct for q in queues if q.name == r.queue_name), 0) for r in sim_results]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Simulated SL%", x=queue_names, y=sim_sl,
        marker_color=C_SIMULATION, text=[f"{v:.1f}%" for v in sim_sl],
        textposition="outside",
    ))
    fig.add_trace(go.Scatter(
        name="Target SL%", x=queue_names, y=targets,
        mode="markers+lines", marker=dict(symbol="diamond", size=10),
        line=dict(dash="dash", color=C_REQUIREMENT),
    ))
    fig.update_layout(
        title="DES service level vs target by queue",
        xaxis_title="Queue",
        yaxis_title="Service level %",
        yaxis=dict(range=[0, 105]),
    )
    apply_dark_theme(fig)
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Results: Blended vs siloed comparison chart
# ---------------------------------------------------------------------------

def _render_comparison_chart(df: pd.DataFrame) -> None:
    """Bar chart comparing siloed and blended agent requirements."""
    queue_rows = df[df["queue"] != "── Blended total ──"].copy()
    if queue_rows.empty:
        return

    summary = df[df["queue"] == "── Blended total ──"]
    if summary.empty:
        return

    s = summary.iloc[0]

    queue_names = list(queue_rows["queue"])
    siloed_vals = list(queue_rows["siloed_net_agents"].fillna(0).astype(int))
    blended_total = int(s["blended_net_agents"]) if pd.notna(s.get("blended_net_agents")) else 0
    siloed_total  = int(s["siloed_net_agents"])   if pd.notna(s.get("siloed_net_agents"))  else 0

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=("Per-queue siloed requirements", "Siloed total vs blended total"),
        column_widths=[0.6, 0.4],
    )

    # Left: per-queue siloed bars
    for i, (name, val) in enumerate(zip(queue_names, siloed_vals)):
        fig.add_trace(
            go.Bar(name=name, x=[name], y=[val], marker_color=PALETTE[i % len(PALETTE)],
                   text=[str(val)], textposition="outside", showlegend=False),
            row=1, col=1,
        )

    # Right: siloed total vs blended total
    fig.add_trace(
        go.Bar(
            x=["Siloed", "Blended"],
            y=[siloed_total, blended_total],
            marker_color=[PALETTE[0], C_SIMULATION],
            text=[str(siloed_total), str(blended_total)],
            textposition="outside",
            name="Total agents",
            showlegend=False,
        ),
        row=1, col=2,
    )

    fig.update_layout(title="Staffing comparison: siloed vs blended")
    apply_dark_theme(fig)
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render_blended_tab(cfg: SimConfig) -> None:
    """Render the Blended Queues tab."""
    st.header("Blended Queues")
    st.caption(
        "Compare siloed staffing (independent agent pools per queue) against "
        "fully blended staffing (shared pool). Configure skill groups to model "
        "partial blending and validate with a multi-queue DES."
    )

    # ── Queue count ────────────────────────────────────────────────────────── #
    n_queues = st.selectbox(
        "Number of queues", options=[2, 3], index=0,
        key="bl_n_queues",
        help="How many queues to model.",
    )

    # ── Queue editors ──────────────────────────────────────────────────────── #
    st.subheader("Queue definitions")
    queues: List[QueueSpec] = []
    for i in range(int(n_queues)):
        queues.append(_queue_editor(i, prefix=f"bl_q{i + 1}_"))

    # ── Erlang C: siloed vs blended ────────────────────────────────────────── #
    active_queues = [q for q in queues if q.calls_per_interval > 0]
    if len(active_queues) < 2:
        st.info("Set call volume > 0 for at least 2 queues to see the blended analysis.")
        return

    blended_df = solve_blended_erlang(active_queues)
    benefit = pooling_benefit_agents(blended_df)

    st.divider()
    st.subheader("Erlang C: siloed vs fully blended")
    _render_erlang_results(blended_df, benefit)
    _render_comparison_chart(blended_df)

    # ── Skill groups ───────────────────────────────────────────────────────── #
    st.divider()
    st.subheader("Skill groups (for DES validation)")
    st.caption(
        "Define agent groups and the queues each group can handle. "
        "The DES uses these groups to model partial blending and show per-queue SL. "
        "For a fully blended pool, assign all queues to a single group."
    )

    queue_names = [q.name for q in active_queues]
    n_groups = st.selectbox(
        "Number of skill groups", options=[1, 2, 3], index=1,
        key="bl_n_groups",
    )

    skill_groups: List[SkillGroup] = []
    for i in range(int(n_groups)):
        skill_groups.append(_skill_group_editor(i, prefix=f"bl_g{i + 1}_", queue_names=queue_names))

    # ── DES run ────────────────────────────────────────────────────────────── #
    total_hc = sum(g.headcount for g in skill_groups)

    col_run, col_intervals = st.columns([2, 1])
    with col_intervals:
        num_intervals = st.number_input(
            "Intervals to simulate", min_value=1, max_value=672, step=1,
            key="bl_num_intervals",
            help="Number of intervals per simulation run. 96 = full 24-hr day at 15min.",
        )

    with col_run:
        run_des = st.button(
            "▶  Run blended DES",
            disabled=(not _DES_AVAILABLE or total_hc == 0),
            help=(
                "Simulate multi-queue routing with the skill groups above. "
                "Requires simpy."
            ) if _DES_AVAILABLE else "simpy is required for DES simulation.",
        )

    if not _DES_AVAILABLE:
        st.warning("simpy is not installed — DES simulation unavailable. `pip install simpy`")

    if run_des and _DES_AVAILABLE and total_hc > 0:
        eligible = [g for g in skill_groups if g.headcount > 0 and g.queues]
        if not eligible:
            st.warning("Assign at least one queue to each skill group with headcount > 0.")
        else:
            with st.spinner("Running multi-queue simulation…"):
                sim_results = simulate_multi_queue(
                    queues=active_queues,
                    skill_groups=eligible,
                    num_intervals=int(num_intervals),
                    seed=int(cfg.seed) if hasattr(cfg, "seed") else 42,
                    enable_abandonment=True,
                )
            st.session_state["blended_des_results"] = [
                {
                    "queue":        r.queue_name,
                    "calls_offered": r.calls_offered,
                    "calls_handled": r.calls_handled,
                    "calls_abandoned": r.calls_abandoned,
                    "abandon_rate": r.abandon_rate,
                    "service_level": r.service_level,
                    "asa_seconds": r.asa_seconds,
                }
                for r in sim_results
            ]
            st.success("DES run complete.")

    # ── Show DES results if available ──────────────────────────────────────── #
    stored = st.session_state.get("blended_des_results", [])
    if stored:
        from dataclasses import fields as _fields
        try:
            results_objs = [
                MultiQueueSimResult(**r) for r in stored
            ]
        except Exception:
            results_objs = []
        if results_objs:
            _render_des_results(results_objs, active_queues)
