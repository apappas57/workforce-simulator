import pandas as pd
import numpy as np
import plotly.express as px
from ui.charts import apply_dark_theme, PALETTE
import streamlit as st

from simulation.break_generation import build_break_schedule_from_shifts
from simulation.des_runner import build_validate_df, run_simulation
from optimisation.staffing_solver import solve_staffing_to_target
from analysis.scenario_runner import run_scenario
from ui.date_view import apply_date_view, render_date_view_controls, ensure_x_col

def _build_des_daily_summary(interval_kpis: pd.DataFrame) -> pd.DataFrame:
    if "date_local" not in interval_kpis.columns:
        return pd.DataFrame()

    daily = interval_kpis.groupby("date_local", as_index=False).agg(
        sim_calls=("sim_calls", "sum"),
        sim_answered_calls=("sim_answered_calls", "sum"),
        sim_abandoned_calls=("sim_abandoned_calls", "sum"),
        sim_asa_seconds=("sim_asa_seconds", "mean"),
        staff_sim=("staff_sim", "max"),
    )

    interval_tmp = interval_kpis.copy()
    interval_tmp["sim_answered_within_sl_calls"] = (
        interval_tmp["sim_service_level"].fillna(0.0).astype(float)
        * interval_tmp["sim_calls"].fillna(0.0).astype(float)
    )

    weighted = interval_tmp.groupby("date_local", as_index=False).agg(
        sim_answered_within_sl_calls=("sim_answered_within_sl_calls", "sum"),
        sim_calls=("sim_calls", "sum"),
        sim_abandoned_calls=("sim_abandoned_calls", "sum"),
    )

    daily = daily.merge(
        weighted[["date_local", "sim_answered_within_sl_calls"]],
        on="date_local",
        how="left",
    )

    daily["daily_service_level"] = np.where(
        daily["sim_calls"] > 0,
        daily["sim_answered_within_sl_calls"] / daily["sim_calls"],
        0.0,
    )

    daily["daily_abandon_rate"] = np.where(
        daily["sim_calls"] > 0,
        daily["sim_abandoned_calls"] / daily["sim_calls"],
        0.0,
    )

    daily = daily.rename(columns={
        "sim_calls": "total_calls",
        "staff_sim": "peak_roster",
        "sim_asa_seconds": "daily_asa_seconds",
    })

    return daily

def render_des_tab(df_det, roster_df, cfg, staffing_df=None):
    st.subheader("DES validation (SimPy)")

    des_engine = st.selectbox(
        "DES engine",
        ["Legacy DES", "DES v2"],
        index=1,
        help="DES v2 uses explicit queue, call lifecycle tracking, and improved occupancy calculation."
    )

    st.markdown("### Abandonment / Patience")
    enable_abandonment = st.toggle("Enable abandonment (patience)", value=True)
    patience_dist = st.selectbox("Patience distribution", ["exponential", "lognormal"], index=0)
    mean_patience_seconds = st.slider("Mean patience (seconds)", 10, 1200, 180, 10)

    st.markdown("### Break modelling")

    enable_breaks = st.toggle(
        "Enable deterministic breaks",
        value=False,
        help="Temporarily remove agents from service capacity during specified intervals."
    )

    break_mode = "Manual interval breaks"
    if enable_breaks:
        break_mode = st.radio(
            "Break input mode",
            ["Manual interval breaks", "Shift-based breaks"],
            horizontal=True,
        )

    break_start_interval = 36
    break_end_interval = 40
    break_agents = 20

    shift_break_templates = []
    shift_break_rules = []
    break_schedule = None
    break_curve_df = None

    if enable_breaks and break_mode == "Manual interval breaks":
        b1, b2, b3 = st.columns(3)

        with b1:
            break_start_interval = st.number_input(
                "Break start interval",
                min_value=0,
                max_value=max(0, len(df_det) - 1),
                value=36,
                step=1,
            )

        with b2:
            break_end_interval = st.number_input(
                "Break end interval",
                min_value=0,
                max_value=len(df_det),
                value=40,
                step=1,
            )

        with b3:
            break_agents = st.number_input(
                "Agents on break",
                min_value=0,
                max_value=5000,
                value=20,
                step=1,
            )

    if enable_breaks and break_mode == "Shift-based breaks":
        st.markdown("#### Shift templates for break generation")

        template_defaults = [
            ("08:00", 480, 60),
            ("09:00", 480, 80),
            ("10:00", 480, 70),
        ]

        h1, h2, h3 = st.columns(3)
        h1.markdown("**Start**")
        h2.markdown("**Duration (min)**")
        h3.markdown("**Heads**")

        for i in range(len(template_defaults)):
            c1, c2, c3 = st.columns(3)
            start = c1.text_input(f"Shift start {i+1}", key=f"des_break_shift_start_{i}")
            dur = c2.number_input(
                f"Shift duration {i+1}",
                min_value=30,
                max_value=720,
                step=15,
                key=f"des_break_shift_dur_{i}",
            )
            heads = c3.number_input(
                f"Shift heads {i+1}",
                min_value=0,
                max_value=5000,
                step=1,
                key=f"des_break_shift_heads_{i}",
            )

            if int(heads) > 0:
                shift_break_templates.append(
                    {
                        "start": start,
                        "duration_min": int(dur),
                        "heads": int(heads),
                    }
                )

        st.markdown("#### Break rules")

        default_break_rules = [
            {
                "name": "Tea 1",
                "duration_min": 15,
                "earliest_offset_min": 120,
                "latest_offset_min": 180,
                "unpaid": False,
            },
            {
                "name": "Lunch",
                "duration_min": 30,
                "earliest_offset_min": 240,
                "latest_offset_min": 330,
                "unpaid": True,
            },
            {
                "name": "Tea 2",
                "duration_min": 15,
                "earliest_offset_min": 360,
                "latest_offset_min": 450,
                "unpaid": False,
            },
        ]

        for i in range(len(default_break_rules)):
            c1, c2, c3, c4 = st.columns(4)

            name = c1.text_input("Rule name", key=f"des_break_rule_name_{i}")
            dur = c2.number_input(
                "Duration",
                min_value=5,
                max_value=90,
                step=5,
                key=f"des_break_rule_dur_{i}",
            )
            earliest = c3.number_input(
                "Earliest offset",
                min_value=0,
                max_value=720,
                step=15,
                key=f"des_break_rule_earliest_{i}",
            )
            latest = c4.number_input(
                "Latest offset",
                min_value=0,
                max_value=720,
                step=15,
                key=f"des_break_rule_latest_{i}",
            )

            _rule_unpaid = default_break_rules[i].get("unpaid", False)
            shift_break_rules.append(
                {
                    "name": name,
                    "duration_min": int(dur),
                    "earliest_offset_min": int(earliest),
                    "latest_offset_min": int(latest),
                    "unpaid": bool(_rule_unpaid),
                }
            )

    if enable_breaks:
        if break_mode == "Manual interval breaks":
            break_schedule = [
                {
                    "start_interval": int(break_start_interval),
                    "end_interval": int(break_end_interval),
                    "break_agents": int(break_agents),
                }
            ]
        elif break_mode == "Shift-based breaks":
            break_schedule, break_curve = build_break_schedule_from_shifts(
                interval_minutes=cfg.interval_minutes,
                num_intervals=len(df_det),
                shift_templates=shift_break_templates,
                break_rules=shift_break_rules,
            )

            break_curve_df = pd.DataFrame(
                {
                    "interval": list(range(len(break_curve))),
                    "break_agents_curve": break_curve,
                }
            )

    if break_curve_df is not None:
        _fig_break_curve = px.line(
            break_curve_df,
            x="interval",
            y="break_agents_curve",
            title="Generated break curve from shift-based rules",
        )
        apply_dark_theme(_fig_break_curve)
        st.plotly_chart(_fig_break_curve, use_container_width=True)

    has_roster = roster_df is not None
    has_staffing = staffing_df is not None and not staffing_df.empty

    if not has_roster and not has_staffing:
        st.info("Generate a roster or upload staffing supply first.")
        return

    staffing_source_options = []
    if has_roster:
        staffing_source_options.append("Generated roster")
    if has_staffing:
        staffing_source_options.append("Imported staffing availability")
        staffing_source_options.append("Imported effective staffing availability")
    if has_roster and has_staffing:
        staffing_source_options.append("Tighter of the two")

    st.markdown("### Simulation setup")

    c1, c2 = st.columns(2)
    with c1:
        des_dist = st.selectbox(
            "Service time distribution",
            ["exponential", "lognormal"],
            index=0,
        )
    with c2:
        des_multiplier = st.slider(
            "DES multiplier (stress test)",
            0.50,
            1.50,
            1.00,
            0.05,
        )

    staffing_source = st.selectbox(
        "DES staffing source",
        staffing_source_options,
        index=0,
        help="Choose whether DES uses generated roster supply, imported staffing availability, imported effective staffing availability, or the tighter of the two.",
    )

    activity_shrinkage_pct = 0.0
    if staffing_source == "Imported effective staffing availability":
        activity_shrinkage_pct = st.slider(
            "Imported staffing activity shrinkage %",
            min_value=0.0,
            max_value=0.6,
            value=0.15,
            step=0.01,
            key="des_activity_shrinkage_pct",
            help="Reduces imported staffing availability before DES capacity is built.",
        )

    st.markdown("### Execution")
    run_des_now = st.toggle(
        "Run DES now",
        value=False,
        help="Prevents DES and solver work from running on every page rerun.",
    )

    if not run_des_now:
        st.info("Enable 'Run DES now' to execute simulation and solver logic.")
        return

    effective_mult = float(des_multiplier) * float(st.session_state["roster_scale"])
    st.caption(
        f"Effective multiplier = DES ({des_multiplier:.2f}) × roster scale ({st.session_state['roster_scale']:.2f}) = {effective_mult:.2f}"
    )

    base_validate_df = build_validate_df(
        df_det=df_det,
        roster_df=roster_df,
        roster_scale=effective_mult,
        staffing_df=staffing_df,
        staffing_source=staffing_source,
        activity_shrinkage_pct=float(activity_shrinkage_pct),
    ).copy()

    p1, p2, p3 = st.columns(3)
    p1.metric("DES staffing source", staffing_source)
    p2.metric("Peak source staff", int(base_validate_df["staff_for_des"].max()))
    p3.metric("Total source staff", int(base_validate_df["staff_for_des"].sum()))

    st.markdown("### DES staffing solver")

    solver_enabled = st.toggle(
        "Run staffing solver to target service level",
        value=False,
        help="Iteratively adds staffing in weak intervals until overall DES service level target is met.",
    )

    solver_max_iterations = 25
    solver_add_step = 1

    if solver_enabled:
        s1, s2 = st.columns(2)
        with s1:
            solver_max_iterations = st.number_input(
                "Max solver iterations",
                min_value=1,
                max_value=200,
                value=25,
                step=1,
            )
        with s2:
            solver_add_step = st.number_input(
                "Agents added per failing interval per iteration",
                min_value=1,
                max_value=20,
                value=1,
                step=1,
            )

    solver_result = None

    if solver_enabled:
        solver_result = solve_staffing_to_target(
            base_validate_df=base_validate_df,
            cfg=cfg,
            service_time_dist=des_dist,
            enable_abandonment=enable_abandonment,
            patience_dist=patience_dist,
            mean_patience_seconds=float(mean_patience_seconds),
            enable_breaks=enable_breaks,
            break_schedule=break_schedule,
            des_engine=des_engine,
            target_service_level=float(cfg.sl_target),
            max_iterations=int(solver_max_iterations),
            add_step=int(solver_add_step),
        )

        sim_out = solver_result["final_sim_out"]
        validate_df = solver_result["solved_validate_df"]
    else:
        sim_run = run_simulation(
            df_det=df_det,
            roster_df=roster_df,
            roster_scale=effective_mult,
            des_engine=des_engine,
            cfg=cfg,
            service_time_dist=des_dist,
            enable_abandonment=enable_abandonment,
            patience_dist=patience_dist,
            mean_patience_seconds=float(mean_patience_seconds),
            enable_breaks=enable_breaks,
            break_schedule=break_schedule,
            staffing_df=staffing_df,
            staffing_source=staffing_source,
            activity_shrinkage_pct=float(activity_shrinkage_pct),
        )
        validate_df = sim_run["validate_df"]
        sim_out = sim_run["sim_out"]

    overall = sim_out["overall"]
    interval_kpis = sim_out["interval_kpis"]
    peak_requirement = None
    if "erlang_required_net_agents" in interval_kpis.columns:
        peak_requirement = int(interval_kpis["erlang_required_net_agents"].max())
    elif "det_required_net_ceil" in interval_kpis.columns:
        peak_requirement = int(interval_kpis["det_required_net_ceil"].max())

    st.markdown("### Executive summary")
    s1, s2, s3, s4, s5, s6 = st.columns(6)

    s1.metric("Total calls", f"{int(overall.get('sim_total_calls', 0)):,}")
    s2.metric("Peak requirement", f"{peak_requirement:,}" if peak_requirement is not None else "N/A")
    s3.metric("Peak roster", f"{int(overall.get('sim_peak_staff', 0)):,}")
    s4.metric("Service level", f"{float(overall.get('sim_service_level', 0.0)) * 100:.1f}%")
    s5.metric("ASA", f"{float(overall.get('sim_asa_seconds', 0.0)):.1f}s")
    s6.metric("Abandon rate", f"{float(overall.get('sim_abandon_rate', 0.0)) * 100:.1f}%")
   

    has_ts = "start_ts_local" in interval_kpis.columns and interval_kpis["start_ts_local"].notna().any()
    has_date = "date_local" in interval_kpis.columns and interval_kpis["date_local"].notna().any()

    x_axis_options = ["Timestamp", "Interval"] if has_ts else ["Interval"]

    x_axis_mode = st.radio(
        "DES chart x-axis",
        x_axis_options,
        horizontal=True,
        key="des_chart_x_axis_mode_main",
    )
    use_ts = has_ts and x_axis_mode == "Timestamp"
    x_col = "start_ts_local" if use_ts else "interval"
    view_mode, selected_day = render_date_view_controls(interval_kpis, "des")
    interval_kpis_view = apply_date_view(interval_kpis, view_mode, selected_day)
    interval_kpis_view = ensure_x_col(interval_kpis_view, x_col)
    # ---------- validation / warnings ----------
    if interval_kpis_view.empty:
        st.warning("No simulation results available for the selected day.")

    if "start_ts_local" not in interval_kpis_view.columns:
        st.info("Timestamp metadata not available. Using interval-based DES plots.")

    if solver_result is not None:
        st.markdown("### Staffing solver results")

        solved_curve = solver_result["staffing_curve"]
        target_met = solver_result["target_met"]
        iterations_used = solver_result["iterations_used"]
        final_overall_sl = float(solver_result.get("final_overall_service_level", 0.0))
        final_overall_abandon = float(solver_result.get("final_overall_abandon_rate", 1.0))
        stagnated = bool(solver_result.get("stagnated", False))

        base_staff = int(base_validate_df["staff_for_des"].max())
        final_staff = int(validate_df["staff_for_des"].max())
        peak_staff_delta = final_staff - base_staff

        interval_staff_added = (
            validate_df["staff_for_des"].astype(int)
            - base_validate_df["staff_for_des"].astype(int)
        )

        max_interval_uplift = int(interval_staff_added.max())
        total_staff_added = int(interval_staff_added.clip(lower=0).sum())

        stop_reason = "Target met" if target_met else ("Stagnated" if stagnated else "Iteration cap")
        st.markdown("### Staffing solver diagnostics")
        m1, m2, m3, m4, m5, m6, m7, m8 = st.columns(8)
        m1.metric("Solver target met", "Yes" if target_met else "No")
        m2.metric("Iterations used", str(iterations_used))
        m3.metric("Peak staff delta", str(peak_staff_delta))
        m4.metric("Max interval uplift", str(max_interval_uplift))
        m5.metric("Total staff added", str(total_staff_added))
        m6.metric("Final DES SL", f"{final_overall_sl*100:.1f}%")
        m7.metric("Final abandon", f"{final_overall_abandon*100:.1f}%")
        m8.metric("Stop reason", stop_reason)

        
        st.caption(f"Solver target: SL ≥ {cfg.sl_target*100:.1f}% and abandon ≤ 5.0% (fixed).")

        compare_df = interval_kpis[["interval"]].copy()
        

        if has_ts:
            compare_df["start_ts_local"] = interval_kpis["start_ts_local"]
        if has_date:
            compare_df["date_local"] = interval_kpis["date_local"]

        compare_df = compare_df.merge(
            base_validate_df[["interval", "staff_for_des"]].rename(columns={"staff_for_des": "base_staff_for_des"}),
            on="interval",
            how="left",
        )
        compare_df = compare_df.merge(
            solved_curve.rename(columns={"required_staff_for_des": "solver_required_staff"}),
            on="interval",
            how="left",
        )

        compare_df["staff_added"] = compare_df["solver_required_staff"] - compare_df["base_staff_for_des"]

        compare_df_view = apply_date_view(compare_df, view_mode, selected_day)
        compare_df_view = ensure_x_col(compare_df_view, x_col)

        compare_plot = compare_df_view.melt(
            id_vars=[c for c in [x_col, "date_local"] if c in compare_df_view.columns],
            value_vars=["base_staff_for_des", "solver_required_staff"],
            var_name="series",
            value_name="agents",
        )
        compare_plot = ensure_x_col(compare_plot, x_col)

        _fig_solver_compare = px.line(
            compare_plot,
            x=x_col,
            y="agents",
            color="series",
            title="Base staffing vs solver-required staffing",
        )
        apply_dark_theme(_fig_solver_compare)
        st.plotly_chart(_fig_solver_compare, use_container_width=True)

        _fig_staff_added = px.bar(
            compare_df_view,
            x=x_col,
            y="staff_added",
            color="date_local" if (use_ts and has_date) else None,
            title="Staff added by solver",
        )
        apply_dark_theme(_fig_staff_added)
        st.plotly_chart(_fig_staff_added, use_container_width=True)

    with st.expander("Scenario stress test", expanded=False):
        enable_scenario = st.toggle(
            "Run scenario stress test",
            value=False,
            help="Apply demand shocks and evaluate staffing requirements."
        )

    if enable_scenario:
        c1, c2, c3 = st.columns(3)

        with c1:
            volume_mult = st.slider(
                "Volume multiplier",
                0.5,
                2.0,
                1.0,
                0.05
            )

        with c2:
            aht_mult = st.slider(
                "AHT multiplier",
                0.5,
                2.0,
                1.0,
                0.05
            )

        with c3:
            patience_mult = st.slider(
                "Patience multiplier",
                0.3,
                2.0,
                1.0,
                0.05
            )

        run_scenario_now = st.button("Run scenario stress test")

        if not run_scenario_now:
            st.info("Adjust scenario multipliers, then click 'Run scenario stress test'.")
        else:
            scenario = run_scenario(
                df_det=df_det,
                roster_df=roster_df,
                roster_scale=effective_mult,
                cfg=cfg,
                des_engine=des_engine,
                service_time_dist=des_dist,
                enable_abandonment=enable_abandonment,
                patience_dist=patience_dist,
                mean_patience_seconds=float(mean_patience_seconds),
                enable_breaks=enable_breaks,
                break_schedule=break_schedule,
                staffing_df=staffing_df,
                staffing_source=staffing_source,
                volume_multiplier=volume_mult,
                aht_multiplier=aht_mult,
                patience_multiplier=patience_mult,
                run_solver=True,
            )

            if volume_mult != 1.0 or aht_mult != 1.0:
                st.info(
                    f"Scenario multipliers active — Volume x{volume_mult:.2f}, "
                    f"AHT x{aht_mult:.2f}"
                )

            scenario_solver = scenario["solver_result"]

            if scenario_solver is not None:
                sc_sl = scenario_solver["final_overall_service_level"]
                sc_abandon = scenario_solver["final_overall_abandon_rate"]

                sc_peak = int(
                    scenario_solver["solved_validate_df"]["staff_for_des"].max()
                )

                base_peak = int(validate_df["staff_for_des"].max())

                st.markdown("#### Scenario results")

                s1, s2, s3 = st.columns(3)

                s1.metric(
                    "Scenario peak staff",
                    sc_peak,
                    delta=sc_peak - base_peak
                )

                s2.metric(
                    "Scenario SL",
                    f"{sc_sl*100:.1f}%"
                )

                s3.metric(
                    "Scenario abandon",
                    f"{sc_abandon*100:.1f}%"
                )

    with st.expander("DES debug preview", expanded=False):
        preview_cols = [
            "interval",
            "date_local",
            "interval_in_day",
            "start_ts_local",
            "staff_sim",
            "sim_calls",
            "sim_answered_calls",
            "sim_abandoned_calls",
            "sim_service_level",
            "sim_abandon_rate",
            "sim_asa_seconds",
            "sim_busy_seconds",
            "sim_occupancy",
            "sim_queue_length",
            "sim_busy_agents",
            "sim_idle_agents",
            "sim_break_agents",
            "sim_break_agents_target",
        ]
        existing_cols = [c for c in preview_cols if c in interval_kpis_view.columns]
        st.dataframe(interval_kpis_view[existing_cols].round(3), use_container_width=True)

        if "call_log" in sim_out:
            st.markdown("**Call log preview**")
            st.dataframe(sim_out["call_log"].head(50), use_container_width=True)

    if has_date:
        daily_summary = _build_des_daily_summary(interval_kpis)
        st.session_state["des_daily_summary"] = daily_summary.copy()

        if not daily_summary.empty:
            st.markdown("### Daily DES summary")
            st.dataframe(daily_summary.round(3), use_container_width=True)
    else:
        st.session_state["des_daily_summary"] = pd.DataFrame()

    st.markdown("### DES charts")
    _color_arg = "date_local" if (use_ts and has_date) else None

    _fig_sl = px.line(interval_kpis_view, x=x_col, y="sim_service_level", color=_color_arg, title="DES SL by interval")
    apply_dark_theme(_fig_sl)
    st.plotly_chart(_fig_sl, use_container_width=True)

    _fig_asa = px.line(interval_kpis_view, x=x_col, y="sim_asa_seconds", color=_color_arg, title="DES ASA by interval (sec)")
    apply_dark_theme(_fig_asa)
    st.plotly_chart(_fig_asa, use_container_width=True)

    _fig_occ = px.line(interval_kpis_view, x=x_col, y="sim_occupancy", color=_color_arg, title="DES occupancy by interval")
    apply_dark_theme(_fig_occ)
    st.plotly_chart(_fig_occ, use_container_width=True)

    _fig_abandon = px.line(interval_kpis_view, x=x_col, y="sim_abandon_rate", color=_color_arg, title="DES Abandon rate by interval")
    apply_dark_theme(_fig_abandon)
    st.plotly_chart(_fig_abandon, use_container_width=True)

    if "sim_queue_length" in interval_kpis_view.columns:
        _fig_queue = px.line(interval_kpis_view, x=x_col, y="sim_queue_length", color=_color_arg, title="DES queue length by interval")
        apply_dark_theme(_fig_queue)
        st.plotly_chart(_fig_queue, use_container_width=True)

    agent_state_cols = [c for c in ["sim_busy_agents", "sim_idle_agents", "staff_sim"] if c in interval_kpis_view.columns]
    if len(agent_state_cols) > 0:
        agent_state_plot = interval_kpis_view.melt(
            id_vars=[c for c in [x_col, "date_local"] if c in interval_kpis_view.columns],
            value_vars=agent_state_cols,
            var_name="series",
            value_name="agents",
        )
        agent_state_plot = ensure_x_col(agent_state_plot, x_col)

        _fig_agent_state = px.line(
            agent_state_plot,
            x=x_col,
            y="agents",
            color="series",
            title="DES agent state by interval",
        )
        apply_dark_theme(_fig_agent_state)
        st.plotly_chart(_fig_agent_state, use_container_width=True)

    break_cols = [c for c in ["sim_break_agents", "sim_break_agents_target"] if c in interval_kpis_view.columns]
    if len(break_cols) > 0:
        break_plot = interval_kpis_view.melt(
            id_vars=[c for c in [x_col, "date_local"] if c in interval_kpis_view.columns],
            value_vars=break_cols,
            var_name="series",
            value_name="agents",
        )
        break_plot = ensure_x_col(break_plot, x_col)

        _fig_break_state = px.line(
            break_plot,
            x=x_col,
            y="agents",
            color="series",
            title="DES break state by interval",
        )
        apply_dark_theme(_fig_break_state)
        st.plotly_chart(_fig_break_state, use_container_width=True)

    with st.expander("Full interval KPI table", expanded=False):
        st.dataframe(interval_kpis_view.round(3), use_container_width=True)
