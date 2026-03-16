from datetime import datetime

import streamlit as st
import pandas as pd

from utils.export import build_zip_bytes, to_csv_bytes


def render_downloads_tab(df_inputs, df_erlang, roster_df):
    st.subheader("Downloads")

    st.download_button(
        "Download demand CSV",
        data=to_csv_bytes(df_inputs),
        file_name="demand.csv",
        mime="text/csv",
    )

    st.download_button(
        "Download interval results (det + erlang) CSV",
        data=to_csv_bytes(df_erlang),
        file_name="interval_results_det_erlang.csv",
        mime="text/csv",
    )

    pack = {
        "demand.csv": to_csv_bytes(df_inputs),
        "interval_results_det_erlang.csv": to_csv_bytes(df_erlang),
    }

    demand_daily_summary = st.session_state.get("demand_daily_summary", pd.DataFrame())
    roster_daily_summary = st.session_state.get("roster_daily_summary", pd.DataFrame())
    des_daily_summary = st.session_state.get("des_daily_summary", pd.DataFrame())
    staffing_daily_summary = st.session_state.get("staffing_daily_summary", pd.DataFrame())
    staffing_gap_export = st.session_state.get("staffing_gap_export", pd.DataFrame())
    planning_projection = st.session_state.get("planning_projection", pd.DataFrame())

    if (
        demand_daily_summary.empty
        and roster_daily_summary.empty
        and des_daily_summary.empty
        and staffing_daily_summary.empty
        and staffing_gap_export.empty
        and planning_projection.empty
    ):
        st.info("Daily summary exports will appear after the relevant tabs have been opened and summaries have been generated.")

    if isinstance(demand_daily_summary, pd.DataFrame) and not demand_daily_summary.empty:
        st.download_button(
            "Download demand daily summary CSV",
            data=to_csv_bytes(demand_daily_summary),
            file_name="demand_daily_summary.csv",
            mime="text/csv",
        )
        pack["demand_daily_summary.csv"] = to_csv_bytes(demand_daily_summary)

    if isinstance(roster_daily_summary, pd.DataFrame) and not roster_daily_summary.empty:
        st.download_button(
            "Download roster daily summary CSV",
            data=to_csv_bytes(roster_daily_summary),
            file_name="roster_daily_summary.csv",
            mime="text/csv",
        )
        pack["roster_daily_summary.csv"] = to_csv_bytes(roster_daily_summary)

    if isinstance(des_daily_summary, pd.DataFrame) and not des_daily_summary.empty:
        st.download_button(
            "Download DES daily summary CSV",
            data=to_csv_bytes(des_daily_summary),
            file_name="des_daily_summary.csv",
            mime="text/csv",
        )
        pack["des_daily_summary.csv"] = to_csv_bytes(des_daily_summary)

    if isinstance(staffing_daily_summary, pd.DataFrame) and not staffing_daily_summary.empty:
        st.download_button(
            "Download staffing daily summary CSV",
            data=to_csv_bytes(staffing_daily_summary),
            file_name="staffing_daily_summary.csv",
            mime="text/csv",
        )
        pack["staffing_daily_summary.csv"] = to_csv_bytes(staffing_daily_summary)

    if isinstance(staffing_gap_export, pd.DataFrame) and not staffing_gap_export.empty:
        st.download_button(
            "Download staffing gap export CSV",
            data=to_csv_bytes(staffing_gap_export),
            file_name="staffing_gap_export.csv",
            mime="text/csv",
        )
        pack["staffing_gap_export.csv"] = to_csv_bytes(staffing_gap_export)

    if isinstance(planning_projection, pd.DataFrame) and not planning_projection.empty:
        # Flatten period_start to string for clean CSV output
        planning_export = planning_projection.copy()
        if "period_start" in planning_export.columns:
            planning_export["period_start"] = planning_export["period_start"].dt.strftime("%Y-%m-%d")

        st.download_button(
            "Download workforce planning projection CSV",
            data=to_csv_bytes(planning_export),
            file_name="planning_projection.csv",
            mime="text/csv",
        )
        pack["planning_projection.csv"] = to_csv_bytes(planning_export)

    if roster_df is not None and not roster_df.empty:
        roster_curve_cols = ["interval", "roster_net_agents"]
        optional_cols = ["date_local", "interval_in_day", "start_ts_local"]
        roster_curve_cols.extend([c for c in optional_cols if c in roster_df.columns])

        roster_curve = roster_df[roster_curve_cols].rename(
            columns={"roster_net_agents": "net_agents"}
        )

        st.download_button(
            "Download roster curve CSV",
            data=to_csv_bytes(roster_curve),
            file_name="roster_curve.csv",
            mime="text/csv",
        )

        pack["roster_full.csv"] = to_csv_bytes(roster_df)
        pack["roster_curve.csv"] = to_csv_bytes(roster_curve)
    else:
        st.info("Roster outputs are not available yet. ZIP will include demand and interval results only.")

    st.download_button(
        "Download pack (ZIP)",
        data=build_zip_bytes(pack),
        file_name=f"sim_pack_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
        mime="application/zip",
    )