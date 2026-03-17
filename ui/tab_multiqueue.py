"""Phase 15: Multi-queue comparison tab.

Models up to 3 independent queues, each with its own demand volume, AHT,
SL target, shrinkage, and operating hours.  Erlang C runs per queue on every
render.  Operating hours are visual-only: inactive intervals are shaded grey
on charts — the Erlang calculation is unaffected.

Architecture notes:
- Tab is self-contained: receives df_inputs + cfg, computes everything locally.
- Demand per queue = base df_inputs["calls_offered"] × (vol_pct / 100).
  This preserves the intraday shape from the primary demand input.
- All widget keys use the mq_q<N>_<param> prefix and are pre-registered in
  app._init_session_state().
- No DES execution — Erlang C only (multi-queue DES is a future phase).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from config.sim_config import SimConfig
from models.deterministic import deterministic_staffing
from models.erlang import solve_staffing_erlang

# ── Constants ──────────────────────────────────────────────────────────────────

_QUEUE_LABELS = ["1", "2", "3"]
_PALETTE = ["#2C6FAC", "#E67E22", "#27AE60"]   # Q1 blue, Q2 orange, Q3 green
_NAVY = "#1B2A4A"
_GREY_FILL = "rgba(180,180,180,0.18)"


# ── Time helpers ───────────────────────────────────────────────────────────────

def _parse_hhmm(s: str, default_minutes: int = 0) -> int:
    """Parse 'HH:MM' → total minutes from midnight; return default on error."""
    try:
        parts = str(s).strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return default_minutes


def _minutes_to_interval(minutes: int, interval_minutes: int) -> int:
    return int(minutes // max(interval_minutes, 1))


def _add_operating_hours_shading(
    fig: go.Figure,
    open_min: int,
    close_min: int,
    interval_minutes: int,
    n_intervals: int,
    rows: int = 1,
) -> None:
    """Add grey vrects before open and after close on every subplot row."""
    open_idx  = _minutes_to_interval(open_min,  interval_minutes)
    close_idx = _minutes_to_interval(close_min, interval_minutes)

    regions = []
    if open_idx > 0:
        regions.append((0, open_idx - 0.5))
    if close_idx < n_intervals - 1:
        regions.append((close_idx + 0.5, n_intervals - 1))

    for x0, x1 in regions:
        for row in range(1, rows + 1):
            fig.add_vrect(
                x0=x0, x1=x1,
                fillcolor=_GREY_FILL,
                line_width=0,
                layer="below",
                row=row, col=1,
            )


# ── Queue editor ───────────────────────────────────────────────────────────────

def _queue_editor(label: str, cfg) -> dict:
    """Render one queue config expander; return queue config dict."""
    prefix     = f"mq_q{label}"
    q_name     = st.session_state.get(f"{prefix}_name",    f"Queue {label}")
    is_enabled = bool(st.session_state.get(f"{prefix}_enabled", False))
    color      = _PALETTE[int(label) - 1]

    header = f"{'✅' if is_enabled else '○'}  Queue {label} — {q_name}"
    with st.expander(header, expanded=is_enabled):
        col_en, col_name = st.columns([1, 5])
        col_en.markdown("&nbsp;", unsafe_allow_html=True)
        col_en.checkbox("Enable", key=f"{prefix}_enabled")
        col_name.text_input("Queue name", key=f"{prefix}_name")

        st.markdown("**Operating hours** — used for chart shading only")
        t1, t2 = st.columns(2)
        t1.text_input("Open (HH:MM)",  key=f"{prefix}_open",
                      help="Intervals before this time are shaded on charts.")
        t2.text_input("Close (HH:MM)", key=f"{prefix}_close",
                      help="Intervals after this time are shaded on charts.")

        st.markdown("**Demand & handling**")
        d1, d2 = st.columns(2)
        d1.slider(
            "Volume % of base demand", 10, 300, step=5, key=f"{prefix}_vol_pct",
            help="Scale the base demand shape. 100% = same call volume as base.",
        )
        d2.number_input(
            "AHT (seconds)", min_value=30, max_value=3600, step=10,
            key=f"{prefix}_aht",
            help="Average handle time for this queue.",
        )

        st.markdown("**Service level & staffing**")
        s1, s2, s3, s4 = st.columns(4)
        s1.slider("SL target",      0.0,  1.0,  step=0.01, key=f"{prefix}_sl_target")
        s2.number_input("SL threshold (s)", min_value=5, max_value=600, step=5,
                        key=f"{prefix}_sl_threshold")
        s3.slider("Shrinkage",      0.0,  0.6,  step=0.01, key=f"{prefix}_shrinkage")
        s4.slider("Occupancy cap",  0.5,  1.0,  step=0.01, key=f"{prefix}_occ_cap")

    return {
        "label":        label,
        "enabled":      bool(st.session_state.get(f"{prefix}_enabled", False)),
        "name":         str(st.session_state.get(f"{prefix}_name",     f"Queue {label}")),
        "color":        color,
        "open_str":     str(st.session_state.get(f"{prefix}_open",     "08:00")),
        "close_str":    str(st.session_state.get(f"{prefix}_close",    "18:00")),
        "vol_pct":      float(st.session_state.get(f"{prefix}_vol_pct",   100.0)),
        "aht":          float(st.session_state.get(f"{prefix}_aht",       360.0)),
        "sl_target":    float(st.session_state.get(f"{prefix}_sl_target", 0.80)),
        "sl_threshold": float(st.session_state.get(f"{prefix}_sl_threshold", 20.0)),
        "shrinkage":    float(st.session_state.get(f"{prefix}_shrinkage", 0.35)),
        "occ_cap":      float(st.session_state.get(f"{prefix}_occ_cap",   0.85)),
    }


# ── Erlang runner per queue ────────────────────────────────────────────────────

def _run_queue_erlang(q: dict, df_inputs: pd.DataFrame, base_cfg) -> pd.DataFrame:
    """Scale demand and run Erlang C for one queue config."""
    df_q = df_inputs.copy()
    df_q["calls_offered"] = df_q["calls_offered"].astype(float) * (q["vol_pct"] / 100.0)

    cfg_q = SimConfig(
        interval_minutes=base_cfg.interval_minutes,
        aht_seconds=q["aht"],
        shrinkage=q["shrinkage"],
        occupancy_cap=q["occ_cap"],
        sl_threshold_seconds=q["sl_threshold"],
        sl_target=q["sl_target"],
        seed=base_cfg.seed,
    )
    df_det_q = deterministic_staffing(df_q, cfg_q)
    return solve_staffing_erlang(df_det_q, cfg_q)


# ── Summary table ──────────────────────────────────────────────────────────────

def _render_summary_table(queue_results: list[dict]) -> None:
    rows = []
    for r in queue_results:
        df_e = r["df_erlang"]
        rows.append({
            "Queue":          r["name"],
            "Vol %":          f"{r['vol_pct']:.0f}%",
            "AHT (s)":        int(r["aht"]),
            "SL target":      f"{r['sl_target']*100:.0f}%",
            "Peak net req":   int(df_e["erlang_required_net_agents"].max()),
            "Peak paid req":  int(df_e["erlang_required_paid_agents_ceil"].max()),
            "Total calls":    int(df_e["calls_offered"].sum()),
            "Avg SL%":        round(float(np.nanmean(df_e["erlang_pred_service_level"])) * 100, 1),
            "Avg occ%":       round(float(np.nanmean(df_e["erlang_pred_occupancy"])) * 100, 1),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Charts ─────────────────────────────────────────────────────────────────────

def _render_charts(
    queue_results: list[dict],
    interval_minutes: int,
) -> None:
    if not queue_results:
        return

    n_intervals = len(queue_results[0]["df_erlang"])

    # ── Chart 1: stacked net agent requirement + combined total ── #
    fig1 = go.Figure()

    combined = np.zeros(n_intervals)
    x = list(range(n_intervals))

    for r in queue_results:
        net = r["df_erlang"]["erlang_required_net_agents"].astype(float).values
        combined += net
        fig1.add_trace(go.Bar(
            x=x, y=net,
            name=r["name"],
            marker_color=r["color"],
            opacity=0.85,
        ))

    fig1.add_trace(go.Scatter(
        x=x, y=combined,
        mode="lines",
        name="Combined total",
        line=dict(color=_NAVY, width=2, dash="dot"),
    ))

    # Shading per queue (first enabled queue drives shading, or union of all)
    for r in queue_results:
        open_min  = _parse_hhmm(r["open_str"],  default_minutes=0)
        close_min = _parse_hhmm(r["close_str"], default_minutes=24 * 60)
        _add_operating_hours_shading(fig1, open_min, close_min, interval_minutes, n_intervals, rows=1)
        break  # one shading layer is enough visually; use first queue's hours

    fig1.update_layout(
        barmode="stack",
        title="Net agent requirement by queue (stacked)",
        xaxis_title="Interval",
        yaxis_title="Agents required",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(t=80, b=40),
        height=380,
    )
    fig1.update_yaxes(gridcolor="#F0F0F0")
    fig1.update_xaxes(gridcolor="#F0F0F0")
    st.plotly_chart(fig1, use_container_width=True)

    # ── Chart 2: SL% and occupancy per queue (2-panel) ── #
    fig2 = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=("Service level % by queue", "Occupancy % by queue"),
        vertical_spacing=0.1,
    )

    for r in queue_results:
        df_e = r["df_erlang"]
        sl_vals  = df_e["erlang_pred_service_level"].astype(float) * 100
        occ_vals = df_e["erlang_pred_occupancy"].astype(float) * 100

        fig2.add_trace(go.Scatter(
            x=x, y=sl_vals, mode="lines",
            name=r["name"], line=dict(color=r["color"], width=2),
            showlegend=True, legendgroup=r["name"],
        ), row=1, col=1)

        fig2.add_trace(go.Scatter(
            x=x, y=occ_vals, mode="lines",
            name=r["name"], line=dict(color=r["color"], width=2, dash="dot"),
            showlegend=False, legendgroup=r["name"],
        ), row=2, col=1)

    # SL target reference lines
    for r in queue_results:
        fig2.add_hline(
            y=r["sl_target"] * 100,
            line_dash="dash", line_color=r["color"], opacity=0.4,
            row=1, col=1,
        )

    # Operating hours shading
    for r in queue_results:
        open_min  = _parse_hhmm(r["open_str"],  default_minutes=0)
        close_min = _parse_hhmm(r["close_str"], default_minutes=24 * 60)
        _add_operating_hours_shading(fig2, open_min, close_min, interval_minutes, n_intervals, rows=2)
        break

    fig2.update_layout(
        height=480,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(t=80, b=40),
    )
    fig2.update_yaxes(gridcolor="#F0F0F0")
    fig2.update_xaxes(gridcolor="#F0F0F0", row=2, col=1, title_text="Interval")
    fig2.update_yaxes(title_text="SL %",  row=1, col=1)
    fig2.update_yaxes(title_text="Occ %", row=2, col=1)
    st.plotly_chart(fig2, use_container_width=True)


# ── Export ─────────────────────────────────────────────────────────────────────

def _render_export(queue_results: list[dict]) -> None:
    with st.expander("Download queue data"):
        for r in queue_results:
            df_e = r["df_erlang"].copy()
            df_e.insert(0, "queue", r["name"])
            st.download_button(
                f"Download {r['name']} — Erlang interval data (CSV)",
                data=df_e.to_csv(index=False).encode(),
                file_name=f"multiqueue_{r['name'].lower().replace(' ', '_')}.csv",
                mime="text/csv",
                key=f"mq_dl_{r['label']}",
            )

        # Combined summary CSV
        rows = []
        for r in queue_results:
            df_e = r["df_erlang"]
            rows.append({
                "Queue":         r["name"],
                "Peak net req":  int(df_e["erlang_required_net_agents"].max()),
                "Peak paid req": int(df_e["erlang_required_paid_agents_ceil"].max()),
                "Total calls":   int(df_e["calls_offered"].sum()),
                "Avg SL%":       round(float(np.nanmean(df_e["erlang_pred_service_level"])) * 100, 1),
                "Avg occ%":      round(float(np.nanmean(df_e["erlang_pred_occupancy"])) * 100, 1),
            })
        st.download_button(
            "Download combined summary (CSV)",
            data=pd.DataFrame(rows).to_csv(index=False).encode(),
            file_name="multiqueue_summary.csv",
            mime="text/csv",
            key="mq_dl_summary",
        )


# ── Main entry point ───────────────────────────────────────────────────────────

def render_multiqueue_tab(df_inputs: pd.DataFrame, cfg) -> None:
    st.subheader("Multi-Queue Comparison")
    st.caption(
        "Model up to 3 independent queues, each with its own demand volume, AHT, and "
        "service level config. Operating hours are shown as grey shading on charts — "
        "they do not affect the Erlang calculation."
    )

    if df_inputs is None or df_inputs.empty:
        st.info("Load demand data in the sidebar to use multi-queue comparison.")
        return

    # ── Queue editors ── #
    q_configs = [_queue_editor(lbl, cfg) for lbl in _QUEUE_LABELS]
    active    = [q for q in q_configs if q["enabled"]]

    if not active:
        st.info("Enable at least one queue above to see comparison charts.")
        return

    st.markdown("---")

    # ── Run Erlang per active queue ── #
    queue_results = []
    for q in active:
        with st.spinner(f"Computing {q['name']}…"):
            try:
                df_erl = _run_queue_erlang(q, df_inputs, cfg)
                queue_results.append({**q, "df_erlang": df_erl})
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Erlang failed for **{q['name']}**: {exc}")

    if not queue_results:
        return

    # ── Summary table ── #
    st.markdown("### Queue summary")
    _render_summary_table(queue_results)

    # ── Combined headcount callout ── #
    peak_combined = sum(
        int(r["df_erlang"]["erlang_required_net_agents"].max())
        for r in queue_results
    )
    st.metric(
        "Peak combined net headcount (all queues)",
        peak_combined,
        help="Sum of peak net agents across all active queues. "
             "Assumes dedicated staffing pools — no multi-skilling.",
    )

    # ── Charts ── #
    st.markdown("### Interval charts")
    _render_charts(queue_results, cfg.interval_minutes)

    # ── Operating hours legend ── #
    with st.expander("Operating hours reference"):
        for q in active:
            st.markdown(
                f"**{q['name']}** — "
                f"open `{q['open_str']}` → close `{q['close_str']}`  "
                f"· Vol {q['vol_pct']:.0f}% · AHT {q['aht']:.0f}s · "
                f"SL {q['sl_target']*100:.0f}% in {q['sl_threshold']:.0f}s"
            )

    # ── Export ── #
    st.markdown("---")
    _render_export(queue_results)
