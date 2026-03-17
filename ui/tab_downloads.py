"""ui/tab_downloads.py

Exports tab — CSV packs, individual CSVs, and formatted Excel workbook.

Phase 17: adds a formatted .xlsx workbook download via utils/excel_export.py.
          Falls back gracefully when openpyxl is not installed.
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from utils.export import build_zip_bytes, to_csv_bytes

try:
    from utils.excel_export import build_simulation_workbook
    _EXCEL_AVAILABLE = True
    _EXCEL_ERROR = ""
except ImportError as _exc:
    _EXCEL_AVAILABLE = False
    _EXCEL_ERROR = str(_exc)


def render_downloads_tab(df_inputs, df_erlang, roster_df):
    st.subheader("Exports")

    # ── Readiness check ──────────────────────────────────────────────────────
    demand_daily_summary   = st.session_state.get("demand_daily_summary",   pd.DataFrame())
    roster_daily_summary   = st.session_state.get("roster_daily_summary",   pd.DataFrame())
    des_daily_summary      = st.session_state.get("des_daily_summary",      pd.DataFrame())
    staffing_daily_summary = st.session_state.get("staffing_daily_summary", pd.DataFrame())
    staffing_gap_export    = st.session_state.get("staffing_gap_export",    pd.DataFrame())
    planning_projection    = st.session_state.get("planning_projection",    pd.DataFrame())
    planning_hiring_plan   = st.session_state.get("planning_hiring_plan",   pd.DataFrame())
    optimisation_result    = st.session_state.get("optimisation_result",    pd.DataFrame())
    optimisation_scenarios = st.session_state.get("optimisation_scenarios", pd.DataFrame())
    cost_interval_df       = st.session_state.get("cost_interval_df",       pd.DataFrame())
    cost_monthly_df        = st.session_state.get("cost_monthly_df",        pd.DataFrame())

    _ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Excel workbook ───────────────────────────────────────────────────────
    st.markdown("#### Formatted Excel workbook")
    st.caption(
        "Multi-sheet workbook with styled headers, number formatting, and a KPI summary. "
        "Includes all available data — open tabs generate their data on first load."
    )

    if not _EXCEL_AVAILABLE:
        st.warning(
            f"openpyxl is required for Excel export. "
            f"Run `pip install openpyxl` in your venv and restart the app.\n\n"
            f"Import error: `{_EXCEL_ERROR}`"
        )
    else:
        try:
            xlsx_bytes = build_simulation_workbook(
                df_inputs=df_inputs,
                df_erlang=df_erlang,
                roster_df=roster_df if (roster_df is not None and not roster_df.empty) else None,
                planning_df=planning_projection if not planning_projection.empty else None,
                optimisation_df=optimisation_result if not optimisation_result.empty else None,
                cost_interval_df=cost_interval_df if not cost_interval_df.empty else None,
                cost_monthly_df=cost_monthly_df if not cost_monthly_df.empty else None,
                des_daily_df=des_daily_summary if not des_daily_summary.empty else None,
            )
            st.download_button(
                "Download workbook (.xlsx)",
                data=xlsx_bytes,
                file_name=f"workforce_simulator_{_ts}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )
        except Exception as exc:
            st.error(f"Excel build failed: {exc}")

    st.divider()

    # ── Individual CSV downloads ─────────────────────────────────────────────
    st.markdown("#### Individual CSV files")

    pack: dict = {}

    # Always available
    st.download_button(
        "Demand intervals",
        data=to_csv_bytes(df_inputs),
        file_name="demand.csv",
        mime="text/csv",
    )
    pack["demand.csv"] = to_csv_bytes(df_inputs)

    st.download_button(
        "Erlang C results",
        data=to_csv_bytes(df_erlang),
        file_name="erlang_results.csv",
        mime="text/csv",
    )
    pack["erlang_results.csv"] = to_csv_bytes(df_erlang)

    # Conditionally available
    if isinstance(demand_daily_summary, pd.DataFrame) and not demand_daily_summary.empty:
        st.download_button(
            "Demand daily summary",
            data=to_csv_bytes(demand_daily_summary),
            file_name="demand_daily_summary.csv",
            mime="text/csv",
        )
        pack["demand_daily_summary.csv"] = to_csv_bytes(demand_daily_summary)

    if isinstance(staffing_daily_summary, pd.DataFrame) and not staffing_daily_summary.empty:
        st.download_button(
            "Staffing daily summary",
            data=to_csv_bytes(staffing_daily_summary),
            file_name="staffing_daily_summary.csv",
            mime="text/csv",
        )
        pack["staffing_daily_summary.csv"] = to_csv_bytes(staffing_daily_summary)

    if isinstance(staffing_gap_export, pd.DataFrame) and not staffing_gap_export.empty:
        st.download_button(
            "Staffing gap analysis",
            data=to_csv_bytes(staffing_gap_export),
            file_name="staffing_gap.csv",
            mime="text/csv",
        )
        pack["staffing_gap.csv"] = to_csv_bytes(staffing_gap_export)

    if isinstance(roster_daily_summary, pd.DataFrame) and not roster_daily_summary.empty:
        st.download_button(
            "Roster daily summary",
            data=to_csv_bytes(roster_daily_summary),
            file_name="roster_daily_summary.csv",
            mime="text/csv",
        )
        pack["roster_daily_summary.csv"] = to_csv_bytes(roster_daily_summary)

    if roster_df is not None and not roster_df.empty:
        roster_curve_cols = ["interval", "roster_net_agents"]
        optional_cols = ["date_local", "interval_in_day", "start_ts_local"]
        roster_curve_cols.extend([c for c in optional_cols if c in roster_df.columns])
        roster_curve = roster_df[roster_curve_cols].rename(
            columns={"roster_net_agents": "net_agents"}
        )
        st.download_button(
            "Roster curve",
            data=to_csv_bytes(roster_curve),
            file_name="roster_curve.csv",
            mime="text/csv",
        )
        pack["roster_full.csv"]  = to_csv_bytes(roster_df)
        pack["roster_curve.csv"] = to_csv_bytes(roster_curve)

    if isinstance(des_daily_summary, pd.DataFrame) and not des_daily_summary.empty:
        st.download_button(
            "Simulation daily summary",
            data=to_csv_bytes(des_daily_summary),
            file_name="simulation_daily_summary.csv",
            mime="text/csv",
        )
        pack["simulation_daily_summary.csv"] = to_csv_bytes(des_daily_summary)

    if isinstance(planning_projection, pd.DataFrame) and not planning_projection.empty:
        plan_export = planning_projection.copy()
        if "period_start" in plan_export.columns:
            plan_export["period_start"] = plan_export["period_start"].dt.strftime("%Y-%m-%d")
        st.download_button(
            "Workforce planning projection",
            data=to_csv_bytes(plan_export),
            file_name="planning_projection.csv",
            mime="text/csv",
        )
        pack["planning_projection.csv"] = to_csv_bytes(plan_export)

    if isinstance(planning_hiring_plan, pd.DataFrame) and not planning_hiring_plan.empty:
        hire_export = planning_hiring_plan.copy()
        if "period_start" in hire_export.columns:
            hire_export["period_start"] = hire_export["period_start"].dt.strftime("%Y-%m-%d")
        st.download_button(
            "Hiring plan",
            data=to_csv_bytes(hire_export),
            file_name="hiring_plan.csv",
            mime="text/csv",
        )
        pack["hiring_plan.csv"] = to_csv_bytes(hire_export)

    if isinstance(optimisation_result, pd.DataFrame) and not optimisation_result.empty:
        opt_export = optimisation_result.copy()
        if "period_start" in opt_export.columns:
            opt_export["period_start"] = opt_export["period_start"].dt.strftime("%Y-%m-%d")
        st.download_button(
            "Optimised hiring plan",
            data=to_csv_bytes(opt_export),
            file_name="optimisation_result.csv",
            mime="text/csv",
        )
        pack["optimisation_result.csv"] = to_csv_bytes(opt_export)

    if isinstance(optimisation_scenarios, pd.DataFrame) and not optimisation_scenarios.empty:
        st.download_button(
            "Scenario comparison",
            data=to_csv_bytes(optimisation_scenarios),
            file_name="optimisation_scenarios.csv",
            mime="text/csv",
        )
        pack["optimisation_scenarios.csv"] = to_csv_bytes(optimisation_scenarios)

    if isinstance(cost_interval_df, pd.DataFrame) and not cost_interval_df.empty:
        cost_iv_export = cost_interval_df.copy()
        for col in cost_iv_export.select_dtypes(include=["datetimetz"]).columns:
            cost_iv_export[col] = cost_iv_export[col].dt.strftime("%Y-%m-%d %H:%M")
        st.download_button(
            "Cost analytics — interval",
            data=to_csv_bytes(cost_iv_export),
            file_name="cost_interval.csv",
            mime="text/csv",
        )
        pack["cost_interval.csv"] = to_csv_bytes(cost_iv_export)

    if isinstance(cost_monthly_df, pd.DataFrame) and not cost_monthly_df.empty:
        cost_m_export = cost_monthly_df.copy()
        if "period_start" in cost_m_export.columns:
            cost_m_export["period_start"] = cost_m_export["period_start"].dt.strftime("%Y-%m-%d")
        st.download_button(
            "Cost analytics — monthly",
            data=to_csv_bytes(cost_m_export),
            file_name="cost_monthly.csv",
            mime="text/csv",
        )
        pack["cost_monthly.csv"] = to_csv_bytes(cost_m_export)

    # ── ZIP pack ─────────────────────────────────────────────────────────────
    if len(pack) > 2:
        st.divider()
        st.markdown("#### Full CSV pack")
        st.caption("All available CSVs bundled into a single ZIP file.")
        st.download_button(
            "Download all CSVs (.zip)",
            data=build_zip_bytes(pack),
            file_name=f"sim_pack_{_ts}.zip",
            mime="application/zip",
        )
    else:
        st.info(
            "Open and run the Demand, Roster, Simulation, Planning, Optimisation, and Cost "
            "tabs to generate additional export data."
        )
