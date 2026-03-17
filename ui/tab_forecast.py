"""ui/tab_forecast.py

Phase 11 — Demand Forecasting tab.

Allows the analyst to upload historical demand data, configure STL forecasting
parameters, preview the forecast with confidence intervals and decomposition
charts, and push the forecast into the simulation pipeline as the active demand
input.

Architecture note
-----------------
This tab owns its own file uploader and parameters (same pattern as
tab_planning / tab_optimisation).  Results are stored in session state:

    st.session_state["forecast_demand_df"]  — forecast DataFrame (or None)

app.py checks this key before the manual demand block; if it contains a
non-empty DataFrame it is used as df_inputs, bypassing the manual upload.
"""

import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:
    from demand.demand_forecaster import ForecastParams, forecast_demand
    from demand.demand_loader import load_demand_csv, validate_demand
    _FORECASTER_AVAILABLE = True
except ImportError:
    _FORECASTER_AVAILABLE = False

try:
    from persistence import state_manager
    _PERSIST_AVAILABLE = True
except ImportError:
    _PERSIST_AVAILABLE = False


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

def _forecast_chart(fc_df: pd.DataFrame) -> go.Figure:
    """Multi-day interval-level forecast with confidence band."""
    fig = go.Figure()

    x = fc_df["global_interval"]

    fig.add_trace(go.Scatter(
        x=x,
        y=fc_df["calls_upper"],
        mode="lines",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip",
        name="upper",
    ))
    fig.add_trace(go.Scatter(
        x=x,
        y=fc_df["calls_lower"],
        fill="tonexty",
        fillcolor="rgba(99, 110, 250, 0.15)",
        mode="lines",
        line=dict(width=0),
        showlegend=True,
        name="Confidence band",
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=x,
        y=fc_df["calls_offered"],
        mode="lines",
        line=dict(color="#636EFA", width=2),
        name="Forecast",
        hovertemplate="Interval %{x}<br>Forecast: %{y:.1f}<extra></extra>",
    ))

    # Day boundary lines
    intervals_per_day = int(fc_df.groupby("date_local").size().mode().iloc[0])
    days = fc_df["date_local"].unique()
    for i, day in enumerate(sorted(days)):
        if i == 0:
            continue
        x_boundary = i * intervals_per_day
        fig.add_vline(
            x=x_boundary,
            line_dash="dot",
            line_color="rgba(150,150,150,0.5)",
            annotation_text=str(day),
            annotation_position="top",
            annotation_font_size=10,
        )

    fig.update_layout(
        title="Interval-level demand forecast",
        xaxis_title="Global interval (0 = start of forecast window)",
        yaxis_title="Calls offered",
        height=380,
        legend=dict(orientation="h", y=-0.2),
        hovermode="x unified",
    )
    return fig


def _decomposition_chart(daily_series: pd.Series, stl_period: int) -> go.Figure:
    """Show STL decomposition of the historical daily series."""
    try:
        from statsmodels.tsa.seasonal import STL
        stl = STL(daily_series, period=stl_period)
        res = stl.fit()
    except Exception:
        return go.Figure().update_layout(title="Decomposition unavailable")

    x = daily_series.index

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=daily_series.values, name="Observed", line=dict(color="#636EFA")))
    fig.add_trace(go.Scatter(x=x, y=res.trend,   name="Trend",    line=dict(color="#EF553B", dash="dash")))
    fig.add_trace(go.Scatter(x=x, y=res.seasonal, name="Seasonal", line=dict(color="#00CC96", dash="dot")))
    fig.add_trace(go.Scatter(x=x, y=res.resid,    name="Residual", line=dict(color="#AAAAAA")))

    fig.update_layout(
        title="STL decomposition of historical daily call volumes",
        xaxis_title="Date",
        yaxis_title="Calls per day",
        height=360,
        legend=dict(orientation="h", y=-0.25),
    )
    return fig


# ---------------------------------------------------------------------------
# Tab renderer
# ---------------------------------------------------------------------------

def render_forecast_tab() -> None:
    """Render the Demand Forecasting tab (Phase 11)."""
    st.header("Demand Forecasting")

    if not _FORECASTER_AVAILABLE:
        st.error(
            "Forecasting module could not be loaded. "
            "Ensure statsmodels is installed: `pip install statsmodels`"
        )
        return

    # --- Active forecast notice ---
    active_fc = st.session_state.get("forecast_demand_df")
    if active_fc is not None and not active_fc.empty:
        n_days = int(active_fc["date_local"].nunique())
        n_rows = len(active_fc)
        st.success(
            f"📈 **Forecast active as demand input** — {n_days} days, "
            f"{n_rows:,} intervals. All tabs are using this forecast. "
            "Upload new historical data and re-run to replace it, or click "
            "**Clear forecast** below to return to manual demand."
        )
        if st.button("Clear forecast demand", type="secondary"):
            st.session_state["forecast_demand_df"] = None
            if _PERSIST_AVAILABLE:
                state_manager.save_dataframe("forecast_demand_df", pd.DataFrame())
            st.rerun()

    st.divider()

    # -----------------------------------------------------------------------
    # Step 1 — Upload historical data
    # -----------------------------------------------------------------------
    st.subheader("1. Upload historical demand data")

    with st.expander("Expected CSV format", expanded=False):
        st.markdown(
            "Use the same format as the main demand CSV upload. "
            "The file must cover **multiple days** (minimum 14 days recommended, "
            "at least 2 × the seasonal period).\n\n"
            "**Required columns:**\n"
            "- `calls_offered` — call volume per interval\n"
            "- `date_local` — calendar date (YYYY-MM-DD)\n"
            "- `interval_in_day` — 0-based interval index within the day\n\n"
            "**Timestamp-based format (also accepted):**\n"
            "- `start_ts_local` — interval start timestamp (timezone-aware)\n\n"
            "The file is read with the same loader as the main demand upload, "
            "so timezone conversion settings in the sidebar apply here too."
        )

    hist_file = st.file_uploader(
        "Historical demand CSV",
        type="csv",
        key="forecast_hist_upload",
        help="Multi-day demand history — minimum 14 days for reliable STL.",
    )

    # -----------------------------------------------------------------------
    # Step 2 — Forecast parameters
    # -----------------------------------------------------------------------
    st.subheader("2. Forecast parameters")

    col1, col2, col3 = st.columns(3)
    with col1:
        horizon_days = st.number_input(
            "Forecast horizon (days)",
            min_value=1,
            max_value=90,
            value=7,
            step=1,
            key="fc_horizon_days",
            help="Number of future days to forecast.",
        )
    with col2:
        confidence_pct = st.selectbox(
            "Confidence interval",
            options=[80, 90, 95],
            index=1,
            key="fc_confidence_pct",
            help="Coverage probability for the prediction interval band.",
        )
    with col3:
        intervals_per_day = st.number_input(
            "Intervals per day",
            min_value=4,
            max_value=288,
            value=96,
            step=4,
            key="fc_intervals_per_day",
            help="Number of intervals per day (96 = 15-min, 48 = 30-min).",
        )

    with st.expander("Advanced STL settings", expanded=False):
        stl_period = st.number_input(
            "Seasonal period (days)",
            min_value=2,
            max_value=30,
            value=7,
            step=1,
            key="fc_stl_period",
            help=(
                "Number of days in one seasonal cycle. "
                "7 captures the weekly pattern (recommended). "
                "Increase to 28 to also capture monthly patterns "
                "(requires ≥ 56 days of history)."
            ),
        )
        min_history = st.number_input(
            "Minimum history (days)",
            min_value=4,
            max_value=365,
            value=14,
            step=1,
            key="fc_min_history",
            help="Raise a validation error if fewer distinct days are provided.",
        )

    # -----------------------------------------------------------------------
    # Step 3 — Run
    # -----------------------------------------------------------------------
    st.subheader("3. Generate forecast")

    run_disabled = hist_file is None
    if st.button("Run forecast", type="primary", disabled=run_disabled):
        if hist_file is None:
            st.warning("Upload a historical demand CSV first.")
        else:
            with st.spinner("Loading historical data and running STL forecast…"):
                try:
                    hist_df = load_demand_csv(hist_file)
                    validate_demand(hist_df)

                    params = ForecastParams(
                        historical_df=hist_df,
                        horizon_days=int(horizon_days),
                        intervals_per_day=int(intervals_per_day),
                        confidence_level=float(confidence_pct) / 100.0,
                        stl_period=int(stl_period),
                        min_history_days=int(min_history),
                    )
                    fc_df = forecast_demand(params)

                    # Store in session state so results survive re-runs
                    st.session_state["_fc_preview"] = fc_df
                    st.session_state["_fc_hist_df"] = hist_df
                    st.session_state["_fc_stl_period"] = int(stl_period)
                    st.success("Forecast generated. Review results below.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Forecast failed: {e}")

    # -----------------------------------------------------------------------
    # Results
    # -----------------------------------------------------------------------
    fc_preview = st.session_state.get("_fc_preview")
    if fc_preview is None or fc_preview.empty:
        st.info("Upload historical data and click **Run forecast** to see results.")
        return

    st.divider()
    st.subheader("Forecast results")

    # Summary metrics
    total_fc  = float(fc_preview["calls_offered"].sum())
    avg_daily = total_fc / max(fc_preview["date_local"].nunique(), 1)
    hist_df_stored = st.session_state.get("_fc_hist_df")
    if hist_df_stored is not None and not hist_df_stored.empty:
        hist_df_stored = hist_df_stored.copy()
        hist_df_stored["date_local"] = pd.to_datetime(hist_df_stored["date_local"]).dt.date
        hist_avg_daily = float(
            hist_df_stored.groupby("date_local")["calls_offered"].sum().mean()
        )
        delta_pct = (avg_daily - hist_avg_daily) / max(hist_avg_daily, 1) * 100
        delta_str = f"{delta_pct:+.1f}% vs historical avg"
    else:
        delta_str = None

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total forecasted calls", f"{total_fc:,.0f}")
    m2.metric("Avg daily volume", f"{avg_daily:,.0f}", delta=delta_str)
    m3.metric("Forecast horizon", f"{fc_preview['date_local'].nunique()} days")
    ci_range_pct = int(st.session_state.get("fc_confidence_pct", 90))
    m4.metric("Confidence interval", f"{ci_range_pct}%")

    # Forecast chart
    st.plotly_chart(_forecast_chart(fc_preview), use_container_width=True)

    # STL decomposition chart (on historical daily data)
    if hist_df_stored is not None and not hist_df_stored.empty:
        daily_hist = (
            hist_df_stored.groupby("date_local")["calls_offered"]
            .sum()
            .sort_index()
        )
        daily_hist.index = pd.DatetimeIndex(daily_hist.index)
        stl_period_stored = int(st.session_state.get("_fc_stl_period", 7))
        with st.expander("STL decomposition (historical data)", expanded=False):
            st.plotly_chart(
                _decomposition_chart(daily_hist, stl_period_stored),
                use_container_width=True,
            )

    # Raw forecast table
    with st.expander("Forecast data table", expanded=False):
        st.dataframe(
            fc_preview[["date_local", "interval_in_day", "calls_offered",
                         "calls_lower", "calls_upper"]],
            use_container_width=True,
            height=300,
        )

    # -----------------------------------------------------------------------
    # Action buttons
    # -----------------------------------------------------------------------
    st.divider()
    act1, act2, act3 = st.columns(3)

    with act1:
        if st.button("✅ Use as demand input", type="primary"):
            st.session_state["forecast_demand_df"] = fc_preview.copy()
            if _PERSIST_AVAILABLE:
                state_manager.save_dataframe("forecast_demand_df", fc_preview)
                state_manager.save_settings(st.session_state)
            st.success(
                "Forecast set as active demand input. "
                "Switch to any simulation tab to run with forecasted demand."
            )
            st.rerun()

    with act2:
        export_csv = fc_preview[
            ["date_local", "interval_in_day", "calls_offered", "calls_lower", "calls_upper"]
        ].to_csv(index=False)
        st.download_button(
            label="⬇️ Download forecast CSV",
            data=export_csv,
            file_name="demand_forecast.csv",
            mime="text/csv",
        )

    with act3:
        if st.button("🗑️ Discard preview", type="secondary"):
            st.session_state.pop("_fc_preview", None)
            st.session_state.pop("_fc_hist_df", None)
            st.session_state.pop("_fc_stl_period", None)
            st.rerun()
