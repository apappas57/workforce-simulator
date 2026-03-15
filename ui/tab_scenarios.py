import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from config.sim_config import SimConfig
from models.deterministic import deterministic_staffing
from models.erlang import solve_staffing_erlang


def render_scenarios_tab(df_inputs, cfg):
    st.subheader("Scenario Compare (Baseline vs A/B/C)")
    st.caption("Scenarios apply multipliers/overrides to demand + config, then re-run deterministic + Erlang.")

    baseline_name = st.text_input("Baseline name", "Baseline", key="sc_baseline_name")

    def scenario_editor(prefix: str, default_name: str):
        with st.expander(f"{default_name}", expanded=False):
            enabled = st.checkbox("Enable", value=False, key=f"{prefix}_enabled")
            name = st.text_input("Scenario name", value=default_name, key=f"{prefix}_name")

            c1, c2 = st.columns(2)
            with c1:
                vol_mult = st.slider("Volume multiplier", 0.5, 2.0, 1.0, 0.05, key=f"{prefix}_vol")
            with c2:
                aht_mult = st.slider("AHT multiplier", 0.5, 2.0, 1.0, 0.05, key=f"{prefix}_aht")

            st.markdown("Overrides (optional)")
            o1, o2, o3, o4 = st.columns(4)
            with o1:
                override_shrink = st.checkbox("Override shrinkage", value=False, key=f"{prefix}_ov_shrink")
                shrink_val = st.slider("Shrinkage", 0.0, 0.6, float(cfg.shrinkage), 0.01, key=f"{prefix}_shrink")
            with o2:
                override_occ = st.checkbox("Override occupancy cap", value=False, key=f"{prefix}_ov_occ")
                occ_val = st.slider("Occupancy cap", 0.5, 1.0, float(cfg.occupancy_cap), 0.01, key=f"{prefix}_occ")
            with o3:
                override_sl = st.checkbox("Override SL target", value=False, key=f"{prefix}_ov_sl")
                sl_val = st.slider("SL target", 0.0, 1.0, float(cfg.sl_target), 0.01, key=f"{prefix}_sl")
            with o4:
                override_thr = st.checkbox("Override SL threshold", value=False, key=f"{prefix}_ov_thr")
                thr_val = st.number_input("SL threshold (sec)", 5, 3600, int(cfg.sl_threshold_seconds), 5, key=f"{prefix}_thr")

            overrides = {}
            if override_shrink:
                overrides["shrinkage"] = float(shrink_val)
            if override_occ:
                overrides["occupancy_cap"] = float(occ_val)
            if override_sl:
                overrides["sl_target"] = float(sl_val)
            if override_thr:
                overrides["sl_threshold_seconds"] = float(thr_val)

            return enabled, name, float(vol_mult), float(aht_mult), overrides

    scenarios = []
    scenarios.append(("A",) + scenario_editor("scA", "Scenario A"))
    scenarios.append(("B",) + scenario_editor("scB", "Scenario B"))
    scenarios.append(("C",) + scenario_editor("scC", "Scenario C"))

    def run_one_scenario(name: str, vol_mult: float, aht_mult: float, overrides: dict):
        df_s = df_inputs.copy()
        df_s["calls_offered"] = df_s["calls_offered"].astype(float) * float(vol_mult)

        cfg_s = SimConfig(
            interval_minutes=cfg.interval_minutes,
            aht_seconds=float(cfg.aht_seconds) * float(aht_mult),
            shrinkage=float(overrides.get("shrinkage", cfg.shrinkage)),
            occupancy_cap=float(overrides.get("occupancy_cap", cfg.occupancy_cap)),
            sl_threshold_seconds=float(overrides.get("sl_threshold_seconds", cfg.sl_threshold_seconds)),
            sl_target=float(overrides.get("sl_target", cfg.sl_target)),
            seed=cfg.seed,
        )

        df_det_s = deterministic_staffing(df_s, cfg_s)
        df_erlang_s = solve_staffing_erlang(df_det_s, cfg_s)

        out = {
            "Scenario": name,
            "Peak Erlang net": int(df_erlang_s["erlang_required_net_agents"].max()),
            "Peak Erlang paid": int(df_erlang_s["erlang_required_paid_agents_ceil"].max()),
            "Avg Erlang occ %": float(np.nanmean(df_erlang_s["erlang_pred_occupancy"])) * 100.0,
            "Avg Erlang SL %": float(np.nanmean(df_erlang_s["erlang_pred_service_level"])) * 100.0,
        }
        return out, df_erlang_s

    results = []
    curves = {}

    base_out, base_curve = run_one_scenario(baseline_name, 1.0, 1.0, {})
    results.append(base_out)
    curves[baseline_name] = base_curve

    for label, enabled, name, vol_mult, aht_mult, overrides in scenarios:
        if enabled:
            out, curve = run_one_scenario(name, vol_mult, aht_mult, overrides)
            results.append(out)
            curves[name] = curve

    res_df = pd.DataFrame(results)
    st.dataframe(res_df, use_container_width=True)

    if len(curves) >= 2:
        series = []
        for nm, dfc in curves.items():
            tmp = dfc[["interval", "erlang_required_net_agents"]].copy()
            tmp["scenario"] = nm
            series.append(tmp)
        plot_df = pd.concat(series, ignore_index=True)
        st.plotly_chart(
            px.line(
                plot_df,
                x="interval",
                y="erlang_required_net_agents",
                color="scenario",
                title="Erlang net requirement by scenario",
            ),
            use_container_width=True,
        )
    else:
        st.info("Enable Scenario A/B/C to see curve comparisons.")