from typing import Dict, List

import numpy as np
import plotly.express as px
import streamlit as st
import pandas as pd

from analysis.gap_analysis import compute_gap
from optimisation.greedy_shift_optimizer import optimise_shift_starts_v1
from optimisation.lp_shift_optimizer import optimise_shifts_lp
from roster.roster_engine import generate_roster_from_templates, parse_hhmm_to_minutes
from ui.date_view import apply_date_view, render_date_view_controls, ensure_x_col

def _build_roster_daily_summary(df: pd.DataFrame, req_col: str) -> pd.DataFrame:
    if "date_local" not in df.columns:
        return pd.DataFrame()

    agg = {
        "roster_net_agents": "max",
        req_col: "max",
    }

    if "calls_offered" in df.columns:
        agg["calls_offered"] = "sum"

    daily = df.groupby("date_local", as_index=False).agg(agg)

    daily = daily.rename(columns={
        "calls_offered": "total_calls",
        "roster_net_agents": "peak_roster",
        req_col: "peak_requirement",
    })

    # Coverage ratio (roster vs requirement)
    daily["coverage_ratio"] = np.where(
        daily["peak_requirement"] > 0,
        daily["peak_roster"] / daily["peak_requirement"],
        np.nan,
    )

    # Clean column order for display
    ordered_cols = ["date_local", "total_calls", "peak_requirement", "peak_roster", "coverage_ratio"]
    existing_cols = [c for c in ordered_cols if c in daily.columns]
    daily = daily[existing_cols]

    # Round for display
    daily["coverage_ratio"] = daily["coverage_ratio"].round(3)

    return daily

def _build_operational_comparison_df(
    comp_view: pd.DataFrame,
    staffing_df,
    view_mode: str,
    selected_day,
) -> pd.DataFrame:
    if staffing_df is None or staffing_df.empty:
        return pd.DataFrame()

    staffing_view = apply_date_view(staffing_df, view_mode, selected_day)

    if "interval" not in staffing_view.columns or "available_staff" not in staffing_view.columns:
        return pd.DataFrame()

    staffing_small = staffing_view[["interval", "available_staff"]].copy()
    staffing_small = staffing_small.groupby("interval", as_index=False)["available_staff"].sum()

    out = comp_view.copy().merge(staffing_small, on="interval", how="left")
    out["available_staff"] = out["available_staff"].fillna(0.0)

    if "erlang_required_net_agents" in out.columns:
        out["supply_under_requirement"] = (
            out["available_staff"].astype(float) < out["erlang_required_net_agents"].astype(float)
        )
        out["roster_under_requirement"] = (
            out["roster_net_agents"].astype(float) < out["erlang_required_net_agents"].astype(float)
        )
    else:
        out["supply_under_requirement"] = False
        out["roster_under_requirement"] = False

    return out

def render_roster_tab(df_erlang, cfg, num_intervals, staffing_df=None):
    st.subheader("Roster generator v3 + Gap analysis + Auto-scale optimiser (v0)")


    if "roster_scale" not in st.session_state:
        st.session_state["roster_scale"] = 1.0

    rg1, rg2, rg3 = st.columns(3)
    with rg1:
        stagger_strategy = st.selectbox("Break staggering", ["Even spread", "Random", "Front-loaded", "Back-loaded"], index=0)
    with rg2:
        roster_seed = st.number_input("Roster seed", min_value=0, max_value=999999, value=int(cfg.seed), step=1)
    with rg3:
        show_paid_after_shrink = st.toggle("Show paid-after-shrinkage curve", value=True)

    st.markdown("### Shift templates")
    st.caption("Default: 486 min (8.1h elapsed), with 30 min unpaid lunch = 456 min (7.6h paid).")

    templates: List[Dict] = []
    template_rows = [
        ("08:00", 486, 60, True),
        ("09:00", 486, 80, True),
        ("10:00", 486, 70, True),
        ("12:00", 300, 40, False),
        ("14:00", 240, 30, False),
        ("16:00", 486, 20, False),
    ]

    hdr = st.columns(4)
    hdr[0].markdown("**Start**")
    hdr[1].markdown("**Duration (min)**")
    hdr[2].markdown("**Heads**")
    hdr[3].markdown("**Use**")

    for i in range(6):
        c0, c1, c2, c3 = st.columns(4)
        s0, d0, h0, u0 = template_rows[i]
        start = c0.text_input(f"Start {i+1}", value=s0, key=f"tpl_start_{i}")
        dur = c1.number_input(f"Dur {i+1}", min_value=30, max_value=720, value=int(d0), step=15, key=f"tpl_dur_{i}")
        heads = c2.number_input(f"Heads {i+1}", min_value=0, max_value=5000, value=int(h0), step=1, key=f"tpl_heads_{i}")
        use = c3.checkbox("Use", value=bool(u0), key=f"tpl_use_{i}")
        if use and int(heads) > 0:
            templates.append({"start": start, "duration_min": int(dur), "heads": int(heads)})

    st.markdown("### Break rules by shift length")
    default_ruleset = [
        {
            "min_len": 0, "max_len": 240,
            "breaks": [
                {"name": "Tea1", "duration_min": 15, "earliest_offset_min": 60, "latest_offset_min": 150, "unpaid": False},
            ],
        },
        {
            "min_len": 241, "max_len": 360,
            "breaks": [
                {"name": "Tea1", "duration_min": 15, "earliest_offset_min": 60, "latest_offset_min": 150, "unpaid": False},
                {"name": "Tea2", "duration_min": 15, "earliest_offset_min": 180, "latest_offset_min": 300, "unpaid": False},
            ],
        },
        {
            "min_len": 361, "max_len": 720,
            "breaks": [
                {"name": "Tea1", "duration_min": 15, "earliest_offset_min": 90, "latest_offset_min": 180, "unpaid": False},
                {"name": "Lunch", "duration_min": 30, "earliest_offset_min": 180, "latest_offset_min": 330, "unpaid": True},
                {"name": "Tea2", "duration_min": 15, "earliest_offset_min": 330, "latest_offset_min": 480, "unpaid": False},
            ],
        },
    ]

    ruleset: List[Dict] = []
    for ridx, rr in enumerate(default_ruleset):
        with st.expander(f"Rule: {rr['min_len']}–{rr['max_len']} min", expanded=(ridx == 2)):
            min_len = st.number_input("Min shift length", min_value=0, max_value=720, value=int(rr["min_len"]), step=15, key=f"r_min_{ridx}")
            max_len = st.number_input("Max shift length", min_value=0, max_value=720, value=int(rr["max_len"]), step=15, key=f"r_max_{ridx}")

            b_rows = []
            for bidx, b in enumerate(rr["breaks"]):
                bc1, bc2, bc3, bc4, bc5 = st.columns([1.2, 1, 1, 1, 0.8])
                name = bc1.text_input("Name", value=b["name"], key=f"r{ridx}_b{bidx}_name")
                dur = bc2.number_input("Dur (min)", min_value=5, max_value=90, value=int(b["duration_min"]), step=5, key=f"r{ridx}_b{bidx}_dur")
                ear = bc3.number_input("Earliest offset", min_value=0, max_value=720, value=int(b["earliest_offset_min"]), step=15, key=f"r{ridx}_b{bidx}_ear")
                lat = bc4.number_input("Latest offset", min_value=0, max_value=720, value=int(b["latest_offset_min"]), step=15, key=f"r{ridx}_b{bidx}_lat")
                unpaid = bc5.checkbox("Unpaid", value=bool(b.get("unpaid", False)), key=f"r{ridx}_b{bidx}_unpaid")
                b_rows.append({
                    "name": name,
                    "duration_min": int(dur),
                    "earliest_offset_min": int(ear),
                    "latest_offset_min": int(lat),
                    "unpaid": bool(unpaid),
                })
            ruleset.append({"min_len": int(min_len), "max_len": int(max_len), "breaks": b_rows})

    roster_df = None

    if len(templates) == 0:
        st.warning("Add at least one shift template with heads > 0.")
    else:
        date_values = None
        if "date_local" in df_erlang.columns and df_erlang["date_local"].notna().any():
            date_values = df_erlang["date_local"].tolist()

        interval_in_day_values = None
        if "interval_in_day" in df_erlang.columns and date_values is not None:
            interval_in_day_values = df_erlang["interval_in_day"].tolist()

        start_ts_local_values = None
        if "start_ts_local" in df_erlang.columns and df_erlang["start_ts_local"].notna().any():
            start_ts_local_values = df_erlang["start_ts_local"].tolist()

        roster_df = generate_roster_from_templates(
            interval_minutes=cfg.interval_minutes,
            num_intervals=num_intervals,
            templates=templates,
            ruleset=ruleset,
            stagger_strategy=stagger_strategy,
            seed=int(roster_seed),
            date_values=date_values,
            interval_in_day_values=interval_in_day_values,
            start_ts_local_values=start_ts_local_values,
        )

        paid_hours_total = float(roster_df.attrs.get("roster_paid_hours_total", float("nan")))
        c1, c2, c3 = st.columns(3)
        c1.metric("Roster paid hours", f"{paid_hours_total:.1f}h")
        c2.metric("Roster paid FTE equiv (7.6h)", f"{paid_hours_total / 7.6:.2f}")
        c3.metric("Roster peak net", int(roster_df["roster_net_agents"].max()))

        has_ts = "start_ts_local" in roster_df.columns and roster_df["start_ts_local"].notna().any()
        has_date = "date_local" in roster_df.columns and roster_df["date_local"].notna().any()

        x_axis_options = ["Timestamp", "Interval"] if has_ts else ["Interval"]

        roster_x_mode = st.radio(
            "Roster chart x-axis",
            x_axis_options,
            horizontal=True,
            key="roster_x_axis_mode",
        )

        use_ts = has_ts and roster_x_mode == "Timestamp"
        x_col = "start_ts_local" if use_ts else "interval"
        view_mode, selected_day = render_date_view_controls(roster_df, "roster")
        roster_df_view = apply_date_view(roster_df, view_mode, selected_day)
        roster_df_view = ensure_x_col(roster_df_view, x_col)

        st.plotly_chart(
            px.line(
                roster_df_view,
                x=x_col,
                y="roster_heads_on_shift",
                color="date_local" if (use_ts and has_date) else None,
                title="Heads on shift (before breaks)",
            ),
            use_container_width=True,
        )
        st.plotly_chart(
            px.line(
                roster_df_view,
                x=x_col,
                y="roster_net_agents",
                color="date_local" if (use_ts and has_date) else None,
                title="Roster NET (after breaks)",
            ),
            use_container_width=True,
        )

        if show_paid_after_shrink:
            tmp = apply_date_view(roster_df, view_mode, selected_day)
            tmp = ensure_x_col(tmp, x_col)
            tmp["roster_paid_after_shrink"] = tmp["roster_net_agents"] / max((1 - cfg.shrinkage), 1e-9)
            st.plotly_chart(
                px.line(
                    tmp,
                    x=x_col,
                    y="roster_paid_after_shrink",
                    color="date_local" if (use_ts and has_date) else None,
                    title="Roster paid after shrinkage (derived)",
                ),
                use_container_width=True,
            )

        merge_cols = ["interval", "date_local", "erlang_required_net_agents", "det_required_net_ceil", "calls_offered"]
        for c in ["date_local", "interval_in_day", "start_ts_local"]:
            if c in df_erlang.columns and c not in merge_cols:
                merge_cols.append(c)

        merge_erlang = df_erlang[merge_cols].copy()
        if "date_local" in merge_erlang.columns and "date_local" in roster_df.columns:
            merge_erlang = merge_erlang.drop(columns=["date_local"])

        comp = roster_df.merge(
            merge_erlang,
            on="interval",
            how="left",
        ).fillna(0)

        comp_view = apply_date_view(comp, view_mode, selected_day)
        comp_view = ensure_x_col(comp_view, x_col)
        # ---------- validation / warnings ----------
        if comp_view.empty:
            st.warning("No roster data available for the selected day.")

        if "date_local" not in comp_view.columns:
            st.info("Daily roster summary unavailable because 'date_local' metadata is missing.")

        st.markdown("### Requirement vs roster")
        if staffing_df is not None and not staffing_df.empty:
            operational_view = _build_operational_comparison_df(
                comp_view=comp_view,
                staffing_df=staffing_df,
                view_mode=view_mode,
                selected_day=selected_day,
            )
            operational_view = ensure_x_col(operational_view, x_col)

            if not operational_view.empty:
                st.markdown("### Operational workforce comparison")

                oc1, oc2, oc3, oc4, oc5 = st.columns(5)
                oc1.metric("Peak available staff", int(operational_view["available_staff"].fillna(0).max()))
                oc2.metric("Peak roster", int(operational_view["roster_net_agents"].fillna(0).max()))
                oc3.metric("Peak requirement", int(operational_view["erlang_required_net_agents"].fillna(0).max()))
                oc4.metric(
                    "Intervals supply < requirement",
                    int(operational_view["supply_under_requirement"].fillna(False).sum()),
                )
                oc5.metric(
                    "Intervals roster < requirement",
                    int(operational_view["roster_under_requirement"].fillna(False).sum()),
                )

                operational_plot = operational_view.melt(
                    id_vars=[c for c in [x_col, "date_local"] if c in operational_view.columns],
                    value_vars=["available_staff", "roster_net_agents", "erlang_required_net_agents"],
                    var_name="series",
                    value_name="agents",
                )
                operational_plot = ensure_x_col(operational_plot, x_col)

                st.plotly_chart(
                    px.line(
                        operational_plot,
                        x=x_col,
                        y="agents",
                        color="series",
                        title="Available staff vs Roster NET vs Erlang requirement",
                    ),
                    use_container_width=True,
                )

                operational_view = operational_view.copy()
                operational_view["roster_minus_supply"] = (
                    operational_view["roster_net_agents"].astype(float)
                    - operational_view["available_staff"].astype(float)
                )
                operational_view["roster_minus_requirement"] = (
                    operational_view["roster_net_agents"].astype(float)
                    - operational_view["erlang_required_net_agents"].astype(float)
                )
                operational_view["supply_minus_requirement"] = (
                    operational_view["available_staff"].astype(float)
                    - operational_view["erlang_required_net_agents"].astype(float)
                )
                operational_view["roster_over_supply"] = operational_view["roster_minus_supply"].clip(lower=0.0)
                operational_view["supply_over_roster"] = (-operational_view["roster_minus_supply"]).clip(lower=0.0)

                rc1, rc2, rc3, rc4 = st.columns(4)
                rc1.metric("Peak roster minus supply", f"{operational_view['roster_minus_supply'].max():.1f}")
                rc2.metric("Peak supply minus roster", f"{operational_view['supply_over_roster'].max():.1f}")
                rc3.metric(
                    "Intervals roster > supply",
                    int((operational_view["roster_minus_supply"] > 0).sum()),
                )
                rc4.metric(
                    "Intervals supply > roster",
                    int((operational_view["roster_minus_supply"] < 0).sum()),
                )

                st.plotly_chart(
                    px.bar(
                        operational_view,
                        x=x_col,
                        y="roster_minus_supply",
                        color="date_local" if (use_ts and "date_local" in operational_view.columns) else None,
                        title="Roster NET minus imported staffing supply",
                    ),
                    use_container_width=True,
                )

                comparison_cols = list(dict.fromkeys([
                    c for c in [
                        x_col,
                        "date_local",
                        "start_ts_local",
                        "interval_in_day",
                        "erlang_required_net_agents",
                        "available_staff",
                        "roster_net_agents",
                        "supply_minus_requirement",
                        "roster_minus_requirement",
                        "roster_minus_supply",
                        "supply_under_requirement",
                        "roster_under_requirement",
                    ] if c in operational_view.columns
                ]))

                st.markdown("#### Roster vs imported supply detail")
                st.dataframe(operational_view[comparison_cols].round(3), use_container_width=True)

        req_plot = comp_view.melt(
            id_vars=[c for c in ["interval", "date_local", "start_ts_local"] if c in comp_view.columns],
            value_vars=["roster_net_agents", "erlang_required_net_agents"],
            var_name="series",
            value_name="agents",
        )
        req_plot = ensure_x_col(req_plot, x_col)

        st.plotly_chart(
            px.line(
                req_plot,
                x=x_col,
                y="agents",
                color="series",
                title="Roster NET vs Erlang net requirement",
            ),
            use_container_width=True,
        )

        st.markdown("## Gap analysis (Roster vs Requirement)")
        req_source = st.selectbox(
            "Requirement curve",
            options=[
                "Erlang net (erlang_required_net_agents)",
                "Deterministic net (det_required_net_ceil)",
            ],
            index=0,
        )
       
        req_col = "erlang_required_net_agents" if "Erlang" in req_source else "det_required_net_ceil"
        if req_col not in comp_view.columns:
            st.warning("Requirement column not found. Requirement vs roster comparison may be incomplete.")       


        roster_daily_summary = _build_roster_daily_summary(comp_view, req_col)
        st.session_state["roster_daily_summary"] = roster_daily_summary.copy()

        if not roster_daily_summary.empty:
            st.markdown("### Daily roster summary")
            st.dataframe(roster_daily_summary.round(3), use_container_width=True)


        gap_df = compute_gap(comp_view, roster_col="roster_net_agents", req_col=req_col, interval_minutes=cfg.interval_minutes)
        total_under_hrs = float(gap_df["under_agent_hours"].sum())
        total_over_hrs = float(gap_df["over_agent_hours"].sum())
        peak_under = float(gap_df["under_agents"].max())
        peak_over = float(gap_df["over_agents"].max())
        pct_under_intervals = float((gap_df["under_agents"] > 0).mean()) * 100.0

        g1, g2, g3, g4, g5 = st.columns(5)
        g1.metric("Understaffed agent-hours", f"{total_under_hrs:,.1f}")
        g2.metric("Overstaffed agent-hours", f"{total_over_hrs:,.1f}")
        g3.metric("Peak understaff (agents)", f"{peak_under:,.0f}")
        g4.metric("Peak overstaff (agents)", f"{peak_over:,.0f}")
        g5.metric("Intervals understaffed", f"{pct_under_intervals:,.0f}%")

        late_req_mask = gap_df[req_col].astype(float) > 0
        late_roster_mask = gap_df["roster_net_agents"].astype(float) > 0

        last_req_interval = int(gap_df.loc[late_req_mask, "interval"].max()) if late_req_mask.any() else None
        last_roster_interval = int(gap_df.loc[late_roster_mask, "interval"].max()) if late_roster_mask.any() else None

        demand_end_label = "N/A"
        roster_end_label = "N/A"
        late_gap_label = "N/A"

        if last_req_interval is not None:
            if "start_ts_local" in gap_df.columns:
                demand_end_label = str(gap_df.loc[gap_df["interval"] == last_req_interval, "start_ts_local"].iloc[0])
            else:
                demand_end_label = str(last_req_interval)

        if last_roster_interval is not None:
            if "start_ts_local" in gap_df.columns:
                roster_end_label = str(gap_df.loc[gap_df["interval"] == last_roster_interval, "start_ts_local"].iloc[0])
            else:
                roster_end_label = str(last_roster_interval)

        if last_req_interval is not None and last_roster_interval is not None:
            late_gap_intervals = max(0, last_req_interval - last_roster_interval)
            late_gap_hours = late_gap_intervals * cfg.interval_minutes / 60.0
            late_gap_label = f"{late_gap_hours:.2f}h"

        st.markdown("### Coverage diagnostics")
        d1, d2, d3 = st.columns(3)
        d1.metric("Demand ends at", demand_end_label)
        d2.metric("Roster ends at", roster_end_label)
        d3.metric("Late coverage gap", late_gap_label)

        plot_df = gap_df[["interval", "roster_net_agents", req_col, "under_agents"]].copy()
        if "date_local" in gap_df.columns:
            plot_df["date_local"] = gap_df["date_local"]
        if "start_ts_local" in gap_df.columns:
            plot_df["start_ts_local"] = gap_df["start_ts_local"]

        plot_df = ensure_x_col(plot_df, x_col)
        plot_df = plot_df.rename(columns={req_col: "requirement_agents"})

        st.plotly_chart(
            px.line(
                plot_df,
                x=x_col,
                y=["requirement_agents", "roster_net_agents"],
                color="date_local" if (use_ts and has_date and "date_local" in plot_df.columns) else None,
                title="Roster vs requirement",
            ),
            use_container_width=True,
        )
        st.plotly_chart(
            px.bar(
                plot_df,
                x=x_col,
                y="under_agents",
                color="date_local" if (use_ts and has_date and "date_local" in plot_df.columns) else None,
                title="Understaffing by interval (agents)",
            ),
            use_container_width=True,
        )

        st.markdown("## Auto-scale roster (v0 optimiser)")
        roster_net = gap_df["roster_net_agents"].astype(float).clip(lower=0.0)
        req_net = gap_df[req_col].astype(float).clip(lower=0.0)

        ratio = np.where(roster_net > 0, req_net / roster_net, np.nan)
        ratio = ratio[np.isfinite(ratio)]
        needed_scale_peak = float(np.nanmax(ratio)) if len(ratio) else 1.0
        needed_scale_p95 = float(np.nanpercentile(ratio, 95)) if len(ratio) else 1.0

        o1, o2, o3 = st.columns(3)
        o1.metric("Scale to meet peak", f"{needed_scale_peak:.2f}x")
        o2.metric("Scale to meet P95", f"{needed_scale_p95:.2f}x")
        o3.metric("Current roster peak net", f"{int(roster_net.max())}")

        target_mode = st.radio("Optimiser target", ["Meet peak", "Meet P95"], horizontal=True)
        suggested = needed_scale_peak if target_mode == "Meet peak" else needed_scale_p95

        a1, a2 = st.columns([1, 2])
        with a1:
            if st.button("Apply suggested scale"):
                st.session_state["roster_scale"] = max(0.1, min(3.0, suggested))
        with a2:
            st.session_state["roster_scale"] = st.slider("Roster scale multiplier", 0.10, 3.00, float(st.session_state["roster_scale"]), 0.05)

        gap_df["roster_net_scaled"] = np.floor(gap_df["roster_net_agents"] * float(st.session_state["roster_scale"])).astype(int)

        scaled_plot_df = gap_df.rename(columns={req_col: "requirement_agents"}).copy()
        scaled_plot_df = ensure_x_col(scaled_plot_df, x_col)

        st.plotly_chart(
            px.line(
                scaled_plot_df,
                x=x_col,
                y=["requirement_agents", "roster_net_agents", "roster_net_scaled"],
                color="date_local" if (use_ts and has_date and "date_local" in scaled_plot_df.columns) else None,
                title="Requirement vs Roster vs Scaled Roster",
            ),
            use_container_width=True,
        )
        st.markdown("## Advanced optimisation tools")
    st.markdown("### Shift optimisation engine (LP solver)")

    req_choice_lp = st.selectbox(
        "Optimise against (LP)",
        ["Erlang net (erlang_required_net_agents)", "Deterministic net (det_required_net_ceil)"],
        index=0,
        key="lp_req_choice",
    )

    req_col_lp = "erlang_required_net_agents" if "Erlang" in req_choice_lp else "det_required_net_ceil"
    req_curve_lp = df_erlang[req_col_lp].astype(float).to_numpy()

    shift_lengths = st.multiselect(
        "Allowed shift lengths (minutes)",
        [240, 300, 360, 420, 486],
        default=[486],
    )

    start_window = st.slider(
        "Allowed shift start window (minutes from midnight)",
        0,
        24 * 60,
        (420, 720),
    )

    allowed_starts = list(range(start_window[0], start_window[1], cfg.interval_minutes))

    st.caption(
        f"LP start window: {start_window[0] // 60:02d}:{start_window[0] % 60:02d} to "
        f"{start_window[1] // 60:02d}:{start_window[1] % 60:02d}"
    )

    if st.button("Run shift optimisation"):
        plan_lp = optimise_shifts_lp(
            req_curve_lp,
            cfg.interval_minutes,
            shift_lengths,
            allowed_starts,
        )
        if plan_lp.empty:
            st.warning("LP solver found no feasible solution with the current shift lengths and start window.")
        else:
            st.dataframe(plan_lp, use_container_width=True)

    st.markdown("## Shift start-time optimiser v1 (coverage)")

    req_choice = st.selectbox(
        "Optimise against",
        ["Erlang net (erlang_required_net_agents)", "Deterministic net (det_required_net_ceil)"],
        index=0,
        key="opt_req_choice",
    )

    req_col_opt = "erlang_required_net_agents" if "Erlang" in req_choice else "det_required_net_ceil"
    req_curve = df_erlang[req_col_opt].astype(float).to_numpy()

    opt1, opt2, opt3, opt4 = st.columns(4)
    with opt1:
        opt_start = st.text_input("Allowed start window (start)", "07:00")
    with opt2:
        opt_end = st.text_input("Allowed start window (end)", "12:00")
    with opt3:
        opt_shift_dur = st.number_input("Shift duration (min)", 120, 720, 486, 15)
    with opt4:
        max_heads = st.number_input("Max heads to place", 1, 5000, 300, 10)

    if st.button("Run shift start-time optimiser"):
        start_min = parse_hhmm_to_minutes(opt_start)
        end_min = parse_hhmm_to_minutes(opt_end)

        if end_min <= start_min:
            st.error("End time must be after start time.")
        else:
            allowed_start_minutes = list(range(start_min, end_min, cfg.interval_minutes))
            plan_greedy, coverage_greedy = optimise_shift_starts_v1(
                requirement=req_curve,
                interval_minutes=cfg.interval_minutes,
                allowed_start_minutes=allowed_start_minutes,
                shift_duration_min=int(opt_shift_dur),
                max_heads_total=int(max_heads),
            )

            st.dataframe(plan_greedy, use_container_width=True)

            greedy_plot = df_erlang[["interval"]].copy()
            greedy_plot["requirement_agents"] = req_curve
            greedy_plot["greedy_coverage"] = coverage_greedy

            st.plotly_chart(
                px.line(
                    greedy_plot,
                    x="interval",
                    y=["requirement_agents", "greedy_coverage"],
                    title="Greedy optimiser coverage vs requirement",
                ),
                use_container_width=True,
            )

    return roster_df