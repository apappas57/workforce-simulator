import numpy as np
import pandas as pd
import streamlit as st

from config.sim_config import SimConfig
from demand.demand_loader import build_synthetic_day, load_demand_csv, validate_demand
from models.deterministic import deterministic_staffing
from models.erlang import solve_staffing_erlang
from ui.sidebar import render_sidebar
from ui.tab_demand import render_demand_tab
from ui.tab_des import render_des_tab
from ui.tab_downloads import render_downloads_tab
from ui.tab_planning import render_planning_tab
from ui.tab_roster import render_roster_tab
from ui.tab_scenarios import render_scenarios_tab
try:
    from supply.staffing_loader import load_staffing_csv, validate_staffing_data
    _staffing_loader_available = True
except ImportError:
    _staffing_loader_available = False


def _init_session_state() -> None:
    """Declare every session_state key used across the app with its default value.

    This is the single source of truth for session state.  All tab modules may
    write to these keys freely, but they must NOT introduce new keys without
    first registering them here.

    Convention:
      - DataFrame outputs (summaries, exports) default to pd.DataFrame().
      - Scalar controls default to their UI starting value.
      - Phase 7+ keys are grouped at the bottom with a comment.

    Adding a key for a new phase:
      1. Add one line below in the appropriate phase section.
      2. Never guard initialisation in a tab file with `if key not in session_state`
         — rely on this function to do that once, cleanly.
    """
    _DEFAULTS: dict = {
        # --- Phase 6: export summaries (consumed by tab_downloads) ---
        "demand_daily_summary":    pd.DataFrame(),
        "roster_daily_summary":    pd.DataFrame(),
        "des_daily_summary":       pd.DataFrame(),
        "staffing_daily_summary":  pd.DataFrame(),
        "staffing_gap_export":     pd.DataFrame(),

        # --- Phase 6: roster control (read cross-tab by tab_des) ---
        "roster_scale":            1.0,

        # --- Phase 7: strategic workforce planning ---
        "planning_projection":     pd.DataFrame(),
        "planning_hiring_plan":    pd.DataFrame(),
        "planning_required_fte":   pd.DataFrame(),

        # --- Phase 8: optimisation outputs (reserved) ---
        # "cost_model_output":       pd.DataFrame(),
        # "hiring_recommendations":  pd.DataFrame(),
    }

    for key, default in _DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default


st.set_page_config(page_title="Call Centre Workforce Simulator", layout="wide")
st.title("Call Centre Workforce Simulator — Interval Model + Erlang + Roster + DES")

_init_session_state()

sidebar_inputs = render_sidebar()

cfg = SimConfig(
    interval_minutes=sidebar_inputs["interval_minutes"],
    aht_seconds=sidebar_inputs["aht_seconds"],
    shrinkage=sidebar_inputs["shrinkage"],
    occupancy_cap=sidebar_inputs["occupancy_cap"],
    sl_threshold_seconds=sidebar_inputs["sl_threshold_seconds"],
    sl_target=sidebar_inputs["sl_target"],
    seed=sidebar_inputs["seed"],
)

try:
    if sidebar_inputs["use_synth"]:
        num_intervals = int(round(24 * 60 / cfg.interval_minutes))
        df_inputs = build_synthetic_day(
            num_intervals=num_intervals,
            avg_calls=sidebar_inputs["avg_calls"],
        )
    else:
        df_inputs = load_demand_csv(
            sidebar_inputs["uploaded"],
            input_tz=sidebar_inputs["input_tz"],
            model_tz=sidebar_inputs["model_tz"],
        )
        validate_demand(df_inputs)
        num_intervals = len(df_inputs)
except Exception as e:
    st.error(f"Demand input error: {e}")
    st.stop()

staffing_df = None

if sidebar_inputs["staffing_uploaded"] is not None:
    if not _staffing_loader_available:
        st.error("Staffing loader is not available in this build.")
        st.stop()

    try:
        staffing_df = load_staffing_csv(
            sidebar_inputs["staffing_uploaded"],
            input_tz=sidebar_inputs["input_tz"],
            model_tz=sidebar_inputs["model_tz"],
        )
        validate_staffing_data(staffing_df)
    except Exception as e:
        st.error(f"Staffing input error: {e}")
        st.stop()


df_det = deterministic_staffing(df_inputs, cfg)
df_erlang = solve_staffing_erlang(df_det, cfg)

tol_occ = 0.005
tol_sl = 0.01

occ = df_erlang["erlang_pred_occupancy"].astype(float)
sl = df_erlang["erlang_pred_service_level"].astype(float)

occ_binding_pct = float(np.nanmean(occ >= (cfg.occupancy_cap - tol_occ))) * 100.0
sl_binding_pct = float(np.nanmean(sl <= (cfg.sl_target + tol_sl))) * 100.0
avg_occ = float(np.nanmean(occ)) * 100.0
avg_sl = float(np.nanmean(sl)) * 100.0
avg_headroom_pp = float(np.nanmean((cfg.occupancy_cap - occ).clip(lower=0))) * 100.0

k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
k1.metric("Peak Erlang net", int(df_erlang["erlang_required_net_agents"].max()))
k2.metric("Peak Erlang paid", int(df_erlang["erlang_required_paid_agents_ceil"].max()))
k3.metric("Avg Erlang occupancy", f"{avg_occ:.1f}%")
k4.metric("Avg Erlang SL", f"{avg_sl:.1f}%")
k5.metric("Occ-binding intervals", f"{occ_binding_pct:.0f}%")
k6.metric("SL-binding intervals", f"{sl_binding_pct:.0f}%")
k7.metric("Avg occ headroom", f"{avg_headroom_pp:.1f}pp")

if sidebar_inputs["staffing_uploaded"] is not None and staffing_df is not None:
    s1, s2, s3 = st.columns(3)
    s1.metric("Staffing rows", len(staffing_df))
    s2.metric("Peak available staff", int(staffing_df["available_staff"].fillna(0).max()))
    s3.metric("Staffing days", staffing_df["date_local"].nunique())

tabs = st.tabs([
    "Demand + Requirement",
    "Roster + Gaps + Optimiser",
    "DES validation",
    "Scenario Compare",
    "Workforce Planning",
    "Downloads",
])

with tabs[0]:
    render_demand_tab(df_inputs, df_erlang, staffing_df=staffing_df)

with tabs[1]:
    roster_df = render_roster_tab(df_erlang, cfg, num_intervals, staffing_df=staffing_df)
with tabs[2]:
    render_des_tab(df_det, roster_df, cfg, staffing_df=staffing_df)

with tabs[3]:
    render_scenarios_tab(df_inputs, cfg)

with tabs[4]:
    render_planning_tab(shrinkage_pct=cfg.shrinkage * 100.0)

with tabs[5]:
    render_downloads_tab(df_inputs, df_erlang, roster_df)