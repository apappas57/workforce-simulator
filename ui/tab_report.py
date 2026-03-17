"""ui/tab_report.py

PDF Report Export tab — Phase 12.

Renders section toggles, data readiness indicators, a generate button,
and a download button. All heavy lifting is delegated to
reports/report_builder.py.
"""

import datetime

import pandas as pd
import streamlit as st

try:
    from reports.report_builder import ReportConfig, build_report
    _report_builder_available = True
except ImportError:
    _report_builder_available = False


def render_report_tab(df_erlang: pd.DataFrame, cfg) -> None:
    """Render the PDF Report Export tab.

    Parameters
    ----------
    df_erlang : pd.DataFrame
        Current Erlang C output (from ``solve_staffing_erlang``).
    cfg : SimConfig
        Current simulation config — used for ``sl_target`` and
        ``occupancy_cap`` metadata in the report.
    """
    st.header("PDF Report Export")

    if not _report_builder_available:
        st.error(
            "**Report builder unavailable.** Install the required packages:\n\n"
            "```\npip install reportlab matplotlib\n```"
        )
        return

    # ------------------------------------------------------------------
    # Report settings
    # ------------------------------------------------------------------
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Cover page")
        org_name    = st.text_input(
            "Organisation name",
            value="My Organisation",
            key="report_org_name",
        )
        report_date = st.date_input(
            "Report date",
            value=datetime.date.today(),
            key="report_date",
        )

    with col_right:
        st.subheader("Sections to include")
        inc_demand    = st.checkbox(
            "Demand & Erlang C Model",
            value=True,
            key="report_inc_demand",
        )
        inc_des       = st.checkbox(
            "DES Simulation Results",
            value=True,
            key="report_inc_des",
        )
        inc_roster    = st.checkbox(
            "Roster & Coverage Gaps",
            value=True,
            key="report_inc_roster",
        )
        inc_workforce = st.checkbox(
            "Workforce Planning & Hiring Optimisation",
            value=True,
            key="report_inc_workforce",
        )

    st.divider()

    # ------------------------------------------------------------------
    # Data readiness indicators
    # ------------------------------------------------------------------
    st.subheader("Data readiness")

    des_daily    = st.session_state.get("des_daily_summary",   pd.DataFrame())
    roster_daily = st.session_state.get("roster_daily_summary",pd.DataFrame())
    planning     = st.session_state.get("planning_projection",  pd.DataFrame())
    optimisation = st.session_state.get("optimisation_result",  pd.DataFrame())

    r1, r2, r3, r4, r5 = st.columns(5)
    r1.metric("Demand / Erlang", "✅ Ready"   if not df_erlang.empty    else "⚠️ No data")
    r2.metric("DES results",     "✅ Ready"   if not des_daily.empty    else "⚠️ Not run")
    r3.metric("Roster data",     "✅ Ready"   if not roster_daily.empty else "⚠️ Not run")
    r4.metric("WF Planning",     "✅ Ready"   if not planning.empty     else "⚠️ Not run")
    r5.metric("Hiring Opt.",     "✅ Ready"   if not optimisation.empty else "⚠️ Not run")

    st.caption(
        "Sections with no data will include a placeholder note instead of charts."
    )

    st.divider()

    # ------------------------------------------------------------------
    # Generate + download
    # ------------------------------------------------------------------
    gen_col, dl_col, _ = st.columns([1, 1, 3])

    with gen_col:
        generate = st.button(
            "Generate PDF",
            type="primary",
            use_container_width=True,
        )

    if generate:
        if not any([inc_demand, inc_des, inc_roster, inc_workforce]):
            st.warning("Select at least one section before generating.")
        else:
            with st.spinner("Building report…"):
                try:
                    report_config = ReportConfig(
                        org_name=str(org_name).strip() or "Organisation",
                        report_date=report_date,
                        include_demand=inc_demand,
                        include_des=inc_des,
                        include_roster=inc_roster,
                        include_workforce=inc_workforce,
                    )
                    data = {
                        "df_erlang":    df_erlang,
                        "des_daily":    des_daily,
                        "roster_daily": roster_daily,
                        "planning":     planning,
                        "optimisation": optimisation,
                        "sl_target":    float(cfg.sl_target),
                        "occupancy_cap":float(cfg.occupancy_cap),
                    }
                    pdf_bytes = build_report(report_config, data)
                    st.session_state["report_pdf_bytes"] = pdf_bytes
                    st.success("Report generated — click Download to save.")
                except Exception as exc:
                    st.error(f"Report generation failed: {exc}")
                    st.session_state["report_pdf_bytes"] = None

    pdf_bytes = st.session_state.get("report_pdf_bytes")

    with dl_col:
        if pdf_bytes:
            fname = (
                f"workforce_report_{datetime.date.today().isoformat()}.pdf"
            )
            st.download_button(
                label="Download PDF",
                data=pdf_bytes,
                file_name=fname,
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            st.button("Download PDF", disabled=True, use_container_width=True)
