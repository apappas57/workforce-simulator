"""Phase 14: Scenario planning overhaul — named scenarios, side-by-side comparison.

Architecture notes:
- Erlang C runs inline on every render (instant — sub-second per scenario).
- DES runs only on explicit button click; results stored in sc_des_results session
  state key so they survive re-renders.
- Widget keys follow sc<Label>_<param> pattern, all pre-registered in
  app._init_session_state() so no value=/key= conflict occurs.
- Tab receives df_inputs + cfg; computes its own df_det per scenario via
  deterministic_staffing() — no dependency on the DES tab's internal state.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from analysis.scenario_runner import run_scenario
from config.sim_config import SimConfig
from ui.charts import apply_dark_theme
from models.deterministic import deterministic_staffing
from models.erlang import solve_staffing_erlang

# ── Constants ──────────────────────────────────────────────────────────────────

_SCENARIO_LABELS = ["A", "B", "C", "D"]
_PALETTE = {
    "Baseline": "#2C6FAC",
    "A":        "#E67E22",
    "B":        "#27AE60",
    "C":        "#8E44AD",
    "D":        "#E74C3C",
}
_NAVY = "#1B2A4A"


# ── Small helpers ──────────────────────────────────────────────────────────────

def _color(name: str, label: str) -> str:
    """Return a chart color for a scenario; fall back to palette by label."""
    return _PALETTE.get(label, _PALETTE.get(name, "#888888"))


def _build_cfg(cfg, aht_mult: float, overrides: dict) -> SimConfig:
    return SimConfig(
        interval_minutes=cfg.interval_minutes,
        aht_seconds=float(cfg.aht_seconds) * float(aht_mult),
        shrinkage=float(overrides.get("shrinkage", cfg.shrinkage)),
        occupancy_cap=float(overrides.get("occupancy_cap", cfg.occupancy_cap)),
        sl_threshold_seconds=float(overrides.get("sl_threshold_seconds", cfg.sl_threshold_seconds)),
        sl_target=float(overrides.get("sl_target", cfg.sl_target)),
        seed=cfg.seed,
    )


def _apply_volume(df: pd.DataFrame, vol_mult: float) -> pd.DataFrame:
    out = df.copy()
    if "calls_offered" in out.columns:
        out["calls_offered"] = out["calls_offered"].astype(float) * float(vol_mult)
    return out


def _x_col(df: pd.DataFrame) -> str:
    """Prefer datetime column for a readable x-axis, fall back to interval."""
    for col in ("start_ts_local", "interval"):
        if col in df.columns:
            return col
    return df.columns[0]


def _erlang_row(name: str, label: str, df_erl: pd.DataFrame) -> dict:
    return {
        "Scenario":     name,
        "_label":       label,   # internal, stripped before display
        "Peak net req": int(df_erl["erlang_required_net_agents"].max()),
        "Peak paid req":int(df_erl["erlang_required_paid_agents_ceil"].max()),
        "Total calls":  int(df_erl["calls_offered"].sum()),
        "Avg SL%":      round(float(np.nanmean(df_erl["erlang_pred_service_level"])) * 100, 1),
        "Avg occ%":     round(float(np.nanmean(df_erl["erlang_pred_occupancy"])) * 100, 1),
    }


# ── Scenario editor ────────────────────────────────────────────────────────────

def _scenario_editor(label: str, cfg) -> dict:
    """Render one collapsible scenario editor; return a scenario config dict."""
    prefix = f"sc{label}"
    sc_name    = st.session_state.get(f"{prefix}_name", f"Scenario {label}")
    is_enabled = bool(st.session_state.get(f"{prefix}_enabled", False))

    with st.expander(
        f"{'✅' if is_enabled else '○'}  Scenario {label} — {sc_name}",
        expanded=is_enabled,
    ):
        col_en, col_name = st.columns([1, 5])
        col_en.markdown("&nbsp;", unsafe_allow_html=True)
        col_en.checkbox("Enable", key=f"{prefix}_enabled")
        col_name.text_input("Scenario name", key=f"{prefix}_name")

        c1, c2 = st.columns(2)
        vol_mult = c1.slider(
            "Volume ×", 0.5, 2.0, step=0.05, key=f"{prefix}_vol",
            help="Scale call volume relative to baseline.",
        )
        aht_mult = c2.slider(
            "AHT ×", 0.5, 2.0, step=0.05, key=f"{prefix}_aht",
            help="Scale average handle time relative to baseline.",
        )

        st.caption("Config overrides — unchecked = inherit baseline value")
        o1, o2, o3, o4 = st.columns(4)

        ov_shrink = o1.checkbox("Shrinkage", key=f"{prefix}_ov_shrink")
        if ov_shrink:
            o1.slider("", 0.0, 0.6, step=0.01,
                      key=f"{prefix}_shrink", label_visibility="collapsed")
            shrinkage = float(st.session_state[f"{prefix}_shrink"])
        else:
            shrinkage = float(cfg.shrinkage)

        ov_occ = o2.checkbox("Occ cap", key=f"{prefix}_ov_occ")
        if ov_occ:
            o2.slider("", 0.5, 1.0, step=0.01,
                      key=f"{prefix}_occ", label_visibility="collapsed")
            occupancy_cap = float(st.session_state[f"{prefix}_occ"])
        else:
            occupancy_cap = float(cfg.occupancy_cap)

        ov_sl = o3.checkbox("SL target", key=f"{prefix}_ov_sl")
        if ov_sl:
            o3.slider("", 0.0, 1.0, step=0.01,
                      key=f"{prefix}_sl", label_visibility="collapsed")
            sl_target = float(st.session_state[f"{prefix}_sl"])
        else:
            sl_target = float(cfg.sl_target)

        ov_thr = o4.checkbox("SL threshold", key=f"{prefix}_ov_thr")
        if ov_thr:
            o4.number_input("", min_value=5, max_value=3600, step=5,
                            key=f"{prefix}_thr", label_visibility="collapsed")
            sl_threshold = float(st.session_state[f"{prefix}_thr"])
        else:
            sl_threshold = float(cfg.sl_threshold_seconds)

    return {
        "label":               label,
        "enabled":             bool(st.session_state.get(f"{prefix}_enabled", False)),
        "name":                str(st.session_state.get(f"{prefix}_name", f"Scenario {label}")),
        "vol_mult":            float(vol_mult),
        "aht_mult":            float(aht_mult),
        "shrinkage":           shrinkage,
        "occupancy_cap":       occupancy_cap,
        "sl_target":           sl_target,
        "sl_threshold_seconds": sl_threshold,
    }


# ── Summary tables ─────────────────────────────────────────────────────────────

def _render_erlang_table(rows: list[dict]) -> None:
    """Side-by-side Erlang summary with Δ vs baseline columns."""
    if not rows:
        return
    baseline = rows[0]
    display_rows = []
    for i, row in enumerate(rows):
        d = {k: v for k, v in row.items() if k != "_label"}
        if i == 0:
            d["Δ Peak net"] = "—"
            d["Δ SL pp"]    = "—"
            d["Δ Occ pp"]   = "—"
        else:
            d["Δ Peak net"] = int(row["Peak net req"] - baseline["Peak net req"])
            d["Δ SL pp"]    = round(row["Avg SL%"]  - baseline["Avg SL%"],  1)
            d["Δ Occ pp"]   = round(row["Avg occ%"] - baseline["Avg occ%"], 1)
        display_rows.append(d)

    df = pd.DataFrame(display_rows)

    def _colour_delta(val, col):
        if val == "—" or not isinstance(val, (int, float)):
            return ""
        if col == "Δ Peak net":
            return "color: #E74C3C" if val > 0 else ("color: #27AE60" if val < 0 else "")
        if col == "Δ SL pp":
            return "color: #E74C3C" if val < 0 else ("color: #27AE60" if val > 0 else "")
        if col == "Δ Occ pp":
            return "color: #E74C3C" if val > 0 else ("color: #27AE60" if val < 0 else "")
        return ""

    styler = df.style
    for col in ("Δ Peak net", "Δ SL pp", "Δ Occ pp"):
        if col in df.columns:
            styler = styler.applymap(lambda v, c=col: _colour_delta(v, c), subset=[col])

    st.dataframe(styler, use_container_width=True, hide_index=True)


def _render_des_table(des_results: dict) -> None:
    """DES summary with Δ vs baseline columns."""
    if not des_results:
        return
    rows = []
    for name, r in des_results.items():
        rows.append({
            "Scenario":      name,
            "Avg SL%":       r.get("Avg SL%"),
            "Avg ASA (s)":   r.get("Avg ASA (s)"),
            "Abandon rate%": r.get("Abandon rate%"),
            "Total calls":   r.get("Total calls"),
            "Abandoned":     r.get("Abandoned"),
        })
    if not rows:
        return
    df = pd.DataFrame(rows)
    baseline = rows[0]
    deltas = []
    for i, row in enumerate(rows):
        if i == 0:
            deltas.append({"Δ SL pp": "—", "Δ Abandon pp": "—"})
        else:
            deltas.append({
                "Δ SL pp":      round((row.get("Avg SL%", 0) or 0) - (baseline.get("Avg SL%", 0) or 0), 1),
                "Δ Abandon pp": round((row.get("Abandon rate%", 0) or 0) - (baseline.get("Abandon rate%", 0) or 0), 2),
            })
    df = pd.concat([df, pd.DataFrame(deltas)], axis=1)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ── DES execution ──────────────────────────────────────────────────────────────

def _execute_des_scenarios(
    df_inputs: pd.DataFrame,
    cfg,
    baseline_name: str,
    active_sc_configs: list[dict],
) -> None:
    """Run DES for baseline + all active scenarios; store results in session state."""
    enable_abandonment = bool(st.session_state.get("sc_des_abandonment", True))
    patience           = float(st.session_state.get("sc_des_patience", 180))
    patience_dist      = str(st.session_state.get("sc_des_patience_dist", "exponential"))

    all_runs = [
        {"name": baseline_name, "label": "Baseline",
         "vol_mult": 1.0, "aht_mult": 1.0,
         "shrinkage": float(cfg.shrinkage), "occupancy_cap": float(cfg.occupancy_cap),
         "sl_target": float(cfg.sl_target), "sl_threshold_seconds": float(cfg.sl_threshold_seconds)},
    ] + active_sc_configs

    results: dict = {}
    progress = st.progress(0)
    status   = st.empty()

    for i, sc in enumerate(all_runs):
        status.text(f"Running DES: {sc['name']}  ({i + 1}/{len(all_runs)})")
        try:
            df_s   = _apply_volume(df_inputs, sc["vol_mult"])
            cfg_s  = _build_cfg(cfg, sc["aht_mult"], {
                "shrinkage":           sc["shrinkage"],
                "occupancy_cap":       sc["occupancy_cap"],
                "sl_target":           sc["sl_target"],
                "sl_threshold_seconds":sc["sl_threshold_seconds"],
            })
            df_det = deterministic_staffing(df_s, cfg_s)
            result = run_scenario(
                df_det=df_det,
                roster_df=None,
                roster_scale=1.0,
                cfg=cfg_s,
                des_engine="DES v2",
                service_time_dist="exponential",
                enable_abandonment=enable_abandonment,
                patience_dist=patience_dist,
                mean_patience_seconds=patience,
                enable_breaks=False,
                break_schedule=None,
                run_solver=False,
            )
            sim_out = result["scenario_sim_out"]
            overall = sim_out.get("overall", {})
            results[sc["name"]] = {
                "Avg SL%":        round(float(overall.get("sim_service_level", 0)) * 100, 1),
                "Avg ASA (s)":    round(float(overall.get("sim_asa_seconds", 0)), 1),
                "Abandon rate%":  round(float(overall.get("sim_abandon_rate", 0)) * 100, 2),
                "Total calls":    int(overall.get("sim_total_calls", 0)),
                "Abandoned":      int(overall.get("sim_abandoned_calls", 0)),
                "interval_kpis":  sim_out.get("interval_kpis", pd.DataFrame()),
            }
        except Exception as exc:  # noqa: BLE001
            st.warning(f"DES failed for **{sc['name']}**: {exc}")

        progress.progress((i + 1) / len(all_runs))

    status.empty()
    progress.empty()
    st.session_state["sc_des_results"] = results
    st.success(f"DES complete — {len(results)} scenario(s) simulated.")


# ── Charts ─────────────────────────────────────────────────────────────────────

def _add_traces(fig, curves: dict[str, pd.DataFrame], y_col: str, row: int, col: int = 1) -> None:
    """Add one line trace per scenario to a subplot."""
    for name, df_c in curves.items():
        if y_col not in df_c.columns:
            continue
        label = df_c.get("_label", pd.Series([name] * len(df_c))).iloc[0] if "_label" in df_c.columns else name
        x = df_c[_x_col(df_c)]
        fig.add_trace(
            go.Scatter(
                x=x, y=df_c[y_col],
                mode="lines",
                name=name,
                line=dict(color=_PALETTE.get(label, _PALETTE.get(name, "#888")), width=2),
                showlegend=(row == 1),
            ),
            row=row, col=col,
        )


def _render_interval_charts(
    erlang_curves: dict[str, pd.DataFrame],
    des_results: dict,
) -> None:
    """Three-panel Erlang chart, then optional DES charts."""
    if not erlang_curves:
        return

    n_rows = 3
    subplot_titles = (
        "Agent requirement (Erlang net)",
        "Service level % (Erlang)",
        "Occupancy % (Erlang)",
    )
    fig = make_subplots(
        rows=n_rows, cols=1,
        shared_xaxes=True,
        subplot_titles=subplot_titles,
        vertical_spacing=0.07,
    )

    cols_map = {
        1: "erlang_required_net_agents",
        2: "erlang_pred_service_level",
        3: "erlang_pred_occupancy",
    }
    scale_map = {2: 100.0, 3: 100.0}   # convert fraction → %

    for r, y_col in cols_map.items():
        for name, df_c in erlang_curves.items():
            if y_col not in df_c.columns:
                continue
            label = name if name not in ("Baseline",) else "Baseline"
            y_vals = df_c[y_col].astype(float)
            if r in scale_map:
                y_vals = y_vals * scale_map[r]
            x_vals = df_c[_x_col(df_c)]
            fig.add_trace(
                go.Scatter(
                    x=x_vals, y=y_vals,
                    mode="lines",
                    name=name,
                    line=dict(
                        color=_PALETTE.get(name, "#888"),
                        width=2,
                        dash="dot" if name != list(erlang_curves.keys())[0] else "solid",
                    ),
                    showlegend=(r == 1),
                    legendgroup=name,
                ),
                row=r, col=1,
            )

    fig.update_layout(
        height=600,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=80, b=40),
    )
    apply_dark_theme(fig)
    fig.update_xaxes(title_text="Interval", row=n_rows, col=1)
    fig.update_yaxes(title_text="Agents", row=1, col=1)
    fig.update_yaxes(title_text="SL %", row=2, col=1)
    fig.update_yaxes(title_text="Occ %", row=3, col=1)
    st.plotly_chart(fig, use_container_width=True)

    # ── Optional DES charts ── #
    if not des_results:
        return

    des_has_kpis = any(
        isinstance(r.get("interval_kpis"), pd.DataFrame) and not r["interval_kpis"].empty
        for r in des_results.values()
    )
    if not des_has_kpis:
        return

    st.markdown("#### DES interval detail")
    fig2 = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=("Simulated SL %", "Abandon rate %"),
        vertical_spacing=0.1,
    )
    for name, r in des_results.items():
        kpis = r.get("interval_kpis")
        if not isinstance(kpis, pd.DataFrame) or kpis.empty:
            continue
        x = kpis[_x_col(kpis)]
        if "sim_service_level" in kpis.columns:
            fig2.add_trace(
                go.Scatter(x=x, y=kpis["sim_service_level"] * 100,
                           mode="lines", name=name,
                           line=dict(color=_PALETTE.get(name, "#888"), width=2),
                           showlegend=True, legendgroup=f"des_{name}"),
                row=1, col=1,
            )
        if "sim_abandon_rate" in kpis.columns:
            fig2.add_trace(
                go.Scatter(x=x, y=kpis["sim_abandon_rate"] * 100,
                           mode="lines", name=name,
                           line=dict(color=_PALETTE.get(name, "#888"), width=2,
                                     dash="dot"),
                           showlegend=False, legendgroup=f"des_{name}"),
                row=2, col=1,
            )

    fig2.update_layout(
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=80, b=40),
    )
    apply_dark_theme(fig2)
    fig2.update_yaxes(title_text="SL %",      row=1, col=1)
    fig2.update_yaxes(title_text="Abandon %", row=2, col=1)
    st.plotly_chart(fig2, use_container_width=True)


# ── Export ─────────────────────────────────────────────────────────────────────

def _render_export(erlang_rows: list[dict], des_results: dict) -> None:
    """CSV download for the comparison summary."""
    if not erlang_rows:
        return
    with st.expander("Download comparison data"):
        erl_df = pd.DataFrame([{k: v for k, v in r.items() if k != "_label"}
                                for r in erlang_rows])
        st.download_button(
            "Download Erlang comparison (CSV)",
            data=erl_df.to_csv(index=False).encode(),
            file_name="scenario_erlang_comparison.csv",
            mime="text/csv",
            key="sc_dl_erlang",
        )
        if des_results:
            des_rows = [
                {
                    "Scenario":      name,
                    "Avg SL%":       r.get("Avg SL%"),
                    "Avg ASA (s)":   r.get("Avg ASA (s)"),
                    "Abandon rate%": r.get("Abandon rate%"),
                    "Total calls":   r.get("Total calls"),
                    "Abandoned":     r.get("Abandoned"),
                }
                for name, r in des_results.items()
            ]
            st.download_button(
                "Download DES comparison (CSV)",
                data=pd.DataFrame(des_rows).to_csv(index=False).encode(),
                file_name="scenario_des_comparison.csv",
                mime="text/csv",
                key="sc_dl_des",
            )


# ── Main entry point ───────────────────────────────────────────────────────────

def render_scenarios_tab(df_inputs: pd.DataFrame, cfg) -> None:
    st.subheader("Scenario Comparison")
    st.caption(
        "Compare up to 4 named scenarios against baseline. "
        "Erlang C updates live as you adjust sliders. "
        "Click **Run DES** to add abandon rate and ASA for active scenarios."
    )

    # ── Baseline ── #
    st.text_input("Baseline name", key="sc_baseline_name")
    baseline_name = str(st.session_state.get("sc_baseline_name", "Baseline"))

    st.markdown("---")

    # ── Scenario editors ── #
    sc_configs = [_scenario_editor(lbl, cfg) for lbl in _SCENARIO_LABELS]
    active = [s for s in sc_configs if s["enabled"]]

    st.markdown("---")

    # ── Erlang: baseline always runs ── #
    df_erl_base = solve_staffing_erlang(deterministic_staffing(df_inputs, cfg), cfg)
    erlang_curves: dict[str, pd.DataFrame] = {baseline_name: df_erl_base}
    erlang_rows = [_erlang_row(baseline_name, "Baseline", df_erl_base)]

    for sc in active:
        df_s   = _apply_volume(df_inputs, sc["vol_mult"])
        cfg_s  = _build_cfg(cfg, sc["aht_mult"], {
            "shrinkage":           sc["shrinkage"],
            "occupancy_cap":       sc["occupancy_cap"],
            "sl_target":           sc["sl_target"],
            "sl_threshold_seconds":sc["sl_threshold_seconds"],
        })
        df_erl_s = solve_staffing_erlang(deterministic_staffing(df_s, cfg_s), cfg_s)
        erlang_curves[sc["name"]] = df_erl_s
        erlang_rows.append(_erlang_row(sc["name"], sc["label"], df_erl_s))

    # ── Summary table ── #
    st.markdown("### Erlang C summary")
    if len(erlang_rows) == 1:
        st.info("Enable one or more scenarios above to compare against baseline.")
    _render_erlang_table(erlang_rows)

    # ── DES section ── #
    st.markdown("### DES simulation")
    with st.expander("DES settings", expanded=False):
        d1, d2, d3 = st.columns(3)
        d1.checkbox("Enable abandonment",   key="sc_des_abandonment")
        d2.slider("Mean patience (s)", 30, 600, step=10, key="sc_des_patience")
        d3.selectbox("Patience distribution", ["exponential", "lognormal"],
                     key="sc_des_patience_dist")

    run_disabled = len(active) == 0
    if st.button(
        "▶  Run DES for all active scenarios",
        type="primary",
        disabled=run_disabled,
        help="Runs DES v2 (no breaks) for baseline + each enabled scenario.",
    ):
        _execute_des_scenarios(df_inputs, cfg, baseline_name, active)

    if run_disabled:
        st.caption("Enable at least one scenario above to unlock DES comparison.")

    des_results: dict = st.session_state.get("sc_des_results", {})
    if des_results:
        st.markdown("#### DES results — last run")
        _render_des_table(des_results)

    # ── Interval charts ── #
    st.markdown("### Interval charts")
    _render_interval_charts(erlang_curves, des_results)

    # ── Export ── #
    st.markdown("---")
    _render_export(erlang_rows, des_results)
