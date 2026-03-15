import plotly.express as px
import numpy as np
import streamlit as st
import pandas as pd
from ui.date_view import apply_date_view, render_date_view_controls, ensure_x_col

def _build_demand_daily_summary(df: pd.DataFrame) -> pd.DataFrame:
    if "date_local" not in df.columns:
        return pd.DataFrame()

    agg = {
        "calls_offered": "sum",
    }

    if "erlang_required_net_agents" in df.columns:
        agg["erlang_required_net_agents"] = "max"
    if "det_required_net_ceil" in df.columns:
        agg["det_required_net_ceil"] = "max"
    if "erlang_pred_service_level" in df.columns:
        agg["erlang_pred_service_level"] = "mean"
    if "erlang_pred_occupancy" in df.columns:
        agg["erlang_pred_occupancy"] = "mean"

    daily = df.groupby("date_local", as_index=False).agg(agg)

    rename_map = {
        "calls_offered": "total_calls",
        "erlang_required_net_agents": "peak_requirement_erlang",
        "det_required_net_ceil": "peak_requirement_det",
        "erlang_pred_service_level": "avg_erlang_sl",
        "erlang_pred_occupancy": "avg_erlang_occupancy",
    }
    daily = daily.rename(columns={k: v for k, v in rename_map.items() if k in daily.columns})
    return daily


def _build_staffing_preview_df(df_erlang_view: pd.DataFrame, staffing_df_view: pd.DataFrame) -> pd.DataFrame:
    base_cols = ["interval", "erlang_required_net_agents"]
    optional_cols = ["date_local", "start_ts_local", "interval_in_day"]

    keep_cols = [c for c in base_cols + optional_cols if c in df_erlang_view.columns]
    preview = df_erlang_view[keep_cols].copy()

    staffing_keep = ["interval", "available_staff"]
    staffing_keep = [c for c in staffing_keep if c in staffing_df_view.columns]

    if "interval" not in staffing_keep or "available_staff" not in staffing_keep:
        preview["available_staff"] = 0.0
    else:
        staffing_small = staffing_df_view[staffing_keep].copy()
        staffing_small = staffing_small.groupby("interval", as_index=False)["available_staff"].sum()
        preview = preview.merge(staffing_small, on="interval", how="left")
        preview["available_staff"] = preview["available_staff"].fillna(0.0)

    preview["supply_gap_agents"] = (
        preview["available_staff"].astype(float)
        - preview["erlang_required_net_agents"].astype(float)
    )
    preview["under_supply_agents"] = (-preview["supply_gap_agents"]).clip(lower=0.0)

    return preview

def _build_staffing_daily_summary(staffing_preview: pd.DataFrame) -> pd.DataFrame:
    if staffing_preview.empty or "date_local" not in staffing_preview.columns:
        return pd.DataFrame()

    daily = staffing_preview.groupby("date_local", as_index=False).agg(
        total_available_staff=("available_staff", "sum"),
        peak_available_staff=("available_staff", "max"),
        peak_erlang_requirement=("erlang_required_net_agents", "max"),
        total_under_supply_agents=("under_supply_agents", "sum"),
    )

    daily["intervals_below_requirement"] = (
        staffing_preview.assign(is_under=staffing_preview["under_supply_agents"].astype(float) > 0)
        .groupby("date_local")["is_under"]
        .sum()
        .values
    )

    if "activity_loss_agents" in staffing_preview.columns:
        daily["total_activity_loss_agents"] = (
            staffing_preview.groupby("date_local")["activity_loss_agents"].sum().values
        )

    if "effective_available_staff" in staffing_preview.columns:
        daily["peak_effective_available_staff"] = (
            staffing_preview.groupby("date_local")["effective_available_staff"].max().values
        )

    if "effective_under_supply_agents" in staffing_preview.columns:
        daily["total_effective_under_supply_agents"] = (
            staffing_preview.groupby("date_local")["effective_under_supply_agents"].sum().values
        )

    daily["coverage_ratio"] = np.where(
        daily["peak_erlang_requirement"] > 0,
        daily["peak_available_staff"] / daily["peak_erlang_requirement"],
        np.nan,
    )

    if "peak_effective_available_staff" in daily.columns:
        daily["effective_coverage_ratio"] = np.where(
            daily["peak_erlang_requirement"] > 0,
            daily["peak_effective_available_staff"] / daily["peak_erlang_requirement"],
            np.nan,
        )
        daily["effective_coverage_ratio"] = daily["effective_coverage_ratio"].round(3)

    daily["coverage_ratio"] = daily["coverage_ratio"].round(3)

    return daily

def render_demand_tab(df_inputs, df_erlang, staffing_df=None):

    if "staffing_daily_summary" not in st.session_state:
        st.session_state["staffing_daily_summary"] = pd.DataFrame()

    if "staffing_gap_export" not in st.session_state:
        st.session_state["staffing_gap_export"] = pd.DataFrame()
    st.subheader("Demand and requirements")
    
    if staffing_df is None or staffing_df.empty:
        st.session_state["staffing_daily_summary"] = pd.DataFrame()
        st.session_state["staffing_gap_export"] = pd.DataFrame()

    has_ts = "start_ts_local" in df_inputs.columns and df_inputs["start_ts_local"].notna().any()
    has_date = "date_local" in df_inputs.columns and df_inputs["date_local"].notna().any()

    x_axis_options = ["Timestamp", "Interval"] if has_ts else ["Interval"]

    x_axis_mode = st.radio(
        "Demand chart x-axis",
        x_axis_options,
        horizontal=True,
        key="demand_x_axis_mode",
    )

    use_ts = has_ts and x_axis_mode == "Timestamp"
    x_col = "start_ts_local" if use_ts else "interval"
    view_mode, selected_day = render_date_view_controls(df_erlang, "demand")
    df_inputs_view = apply_date_view(df_inputs, view_mode, selected_day)
    df_erlang_view = apply_date_view(df_erlang, view_mode, selected_day)

    # ---------- validation / warnings ----------
    if df_erlang_view.empty:
        st.warning("No rows available for the selected day.")

    if not has_ts:
        st.info("Timestamp metadata not available. Using interval-based plotting.")

    if "date_local" not in df_erlang.columns:
        st.info("Daily summaries unavailable because 'date_local' metadata is missing.")

    df_inputs_view = ensure_x_col(df_inputs_view, x_col)

    st.plotly_chart(
        px.line(df_inputs_view, x=x_col, y="calls_offered", color="date_local" if (use_ts and has_date) else None, title="Calls offered"),
        use_container_width=True,
    )

    req_id_vars = [x_col]
    if "date_local" in df_erlang.columns and "date_local" not in req_id_vars:
        req_id_vars.append("date_local")

    req_melt = df_erlang_view.melt(
        id_vars=req_id_vars,
        value_vars=["det_required_net_ceil", "erlang_required_net_agents", "erlang_required_paid_agents"],
        var_name="series",
        value_name="agents",
    )
    
    req_melt = ensure_x_col(req_melt, x_col)
    
    
    st.plotly_chart(
        px.line(
            req_melt,
            x=x_col,
            y="agents",
            color="series",
            line_group="date_local" if (use_ts and "date_local" in req_melt.columns) else None,
            title="Deterministic vs Erlang net and paid requirement",
        ),
        use_container_width=True,
    )

    if staffing_df is not None and not staffing_df.empty:
        st.markdown("### Staffing supply preview")

        staffing_df_view = apply_date_view(staffing_df, view_mode, selected_day)
        staffing_preview = _build_staffing_preview_df(df_erlang_view, staffing_df_view)
        staffing_preview = ensure_x_col(staffing_preview, x_col)

        st.markdown("#### Activity modelling")
        activity_shrinkage_pct = st.slider(
            "Activity shrinkage %",
            min_value=0.0,
            max_value=0.6,
            value=0.15,
            step=0.01,
            key="demand_activity_shrinkage_pct",
            help="Applies an activity-based capacity reduction to imported available staff for comparison only.",
        )
        st.caption("Raw imported available_staff is unchanged. Effective capacity below is a derived comparison layer only.")

        staffing_preview["activity_shrinkage_pct"] = float(activity_shrinkage_pct)
        staffing_preview["activity_loss_agents"] = (
            staffing_preview["available_staff"].astype(float) * staffing_preview["activity_shrinkage_pct"].astype(float)
        )
        staffing_preview["effective_available_staff"] = (
            staffing_preview["available_staff"].astype(float) - staffing_preview["activity_loss_agents"].astype(float)
        ).clip(lower=0.0)
        staffing_preview["dynamic_shrinkage_pct"] = np.where(
            staffing_preview["available_staff"].astype(float) > 0,
            staffing_preview["activity_loss_agents"].astype(float) / staffing_preview["available_staff"].astype(float),
            0.0,
        )
        staffing_preview["effective_supply_gap_agents"] = (
            staffing_preview["effective_available_staff"].astype(float)
            - staffing_preview["erlang_required_net_agents"].astype(float)
        )
        staffing_preview["effective_under_supply_agents"] = (
            -staffing_preview["effective_supply_gap_agents"]
        ).clip(lower=0.0)

        st.session_state["staffing_gap_export"] = staffing_preview.copy()

        staffing_daily_summary = _build_staffing_daily_summary(staffing_preview)
        st.session_state["staffing_daily_summary"] = staffing_daily_summary.copy()

        if staffing_preview.empty:
            st.warning("No staffing rows available for the selected day.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Peak raw available staff", int(staffing_preview["available_staff"].fillna(0).max()))
            c2.metric("Peak effective available staff", int(staffing_preview["effective_available_staff"].fillna(0).max()))
            c3.metric(
                "Effective intervals below requirement",
                int((staffing_preview["effective_under_supply_agents"] > 0).sum()),
            )

            supply_plot = staffing_preview.melt(
                id_vars=[c for c in [x_col, "date_local"] if c in staffing_preview.columns],
                value_vars=["available_staff", "effective_available_staff", "erlang_required_net_agents"],
                var_name="series",
                value_name="agents",
            )
            supply_plot = ensure_x_col(supply_plot, x_col)

            st.plotly_chart(
                px.line(
                    supply_plot,
                    x=x_col,
                    y="agents",
                    color="series",
                    line_group="date_local" if (use_ts and "date_local" in supply_plot.columns) else None,
                    title="Raw and effective staffing supply vs Erlang requirement",
                ),
                use_container_width=True,
            )

            st.plotly_chart(
                px.bar(
                    staffing_preview,
                    x=x_col,
                    y="effective_under_supply_agents",
                    color="date_local" if (use_ts and "date_local" in staffing_preview.columns) else None,
                    title="Intervals where effective supply is below requirement",
                ),
                use_container_width=True,
            )

            preview_cols = list(dict.fromkeys([
                c for c in [
                    x_col,
                    "date_local",
                    "start_ts_local",
                    "interval_in_day",
                    "erlang_required_net_agents",
                    "available_staff",
                    "activity_loss_agents",
                    "effective_available_staff",
                    "supply_gap_agents",
                    "effective_supply_gap_agents",
                    "under_supply_agents",
                    "effective_under_supply_agents",
                ] if c in staffing_preview.columns
            ]))

            st.markdown("#### Staffing preview detail")
            st.dataframe(staffing_preview[preview_cols].round(3), use_container_width=True)

            if not staffing_daily_summary.empty:
                st.markdown("#### Staffing daily summary")
                st.dataframe(staffing_daily_summary.round(3), use_container_width=True)

    daily_summary = _build_demand_daily_summary(df_erlang_view)
    st.session_state["demand_daily_summary"] = daily_summary.copy()

    if not daily_summary.empty:
        st.markdown("### Daily summary")
        st.dataframe(daily_summary.round(3), use_container_width=True)

    st.dataframe(df_erlang_view.round(3), use_container_width=True)