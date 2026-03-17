import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from config.sim_config import SimConfig
from demand.demand_loader import build_synthetic_day, load_demand_csv, validate_demand
from models.deterministic import deterministic_staffing
from models.erlang import solve_staffing_erlang
from persistence import state_manager
from ui.sidebar import render_sidebar
from ui.tab_demand import render_demand_tab
from ui.tab_des import render_des_tab
from ui.tab_downloads import render_downloads_tab
from ui.tab_forecast import render_forecast_tab
from ui.tab_optimisation import render_optimisation_tab
from ui.tab_report import render_report_tab
from ui.tab_planning import render_planning_tab
from ui.tab_roster import render_roster_tab
from ui.tab_scenarios import render_scenarios_tab
try:
    from supply.staffing_loader import load_staffing_csv, validate_staffing_data
    _staffing_loader_available = True
except ImportError:
    _staffing_loader_available = False

# --- Phase 10: optional auth imports ---
try:
    from auth.key_validator import validate_deployment_key
    _key_validator_available = True
except ImportError:
    _key_validator_available = False

try:
    import streamlit_authenticator as stauth
    import yaml
    from yaml.loader import SafeLoader
    _stauth_available = True
except ImportError:
    _stauth_available = False


def _init_session_state() -> None:
    """Declare every session_state key used across the app with its default value.

    This is the single source of truth for session state.  All tab modules may
    write to these keys freely, but they must NOT introduce new keys without
    first registering them here.

    Convention:
      - DataFrame outputs (summaries, exports) default to pd.DataFrame().
      - Scalar controls default to their UI starting value.
      - Phase 7+ keys are grouped at the bottom with a comment.
      - Phase 9: widget keys (sb_*, planning_*, opt_*) are pre-populated from
        disk via state_manager so Streamlit widgets pick up saved values.

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

        # --- Phase 8: optimisation outputs ---
        "optimisation_result":     pd.DataFrame(),
        "optimisation_scenarios":  pd.DataFrame(),

        # --- Phase 11: demand forecast ---
        "forecast_demand_df":      None,

        # --- Phase 12: PDF report ---
        "report_erlang_df":        pd.DataFrame(),
        "report_pdf_bytes":        None,

        # --- Roster template widget defaults (tab_roster.py, fixed 6-row grid) ---
        # Pre-registered here so widgets never receive both value= and key= simultaneously.
        "tpl_start_0": "08:00", "tpl_dur_0": 486, "tpl_heads_0": 60, "tpl_use_0": True,
        "tpl_start_1": "09:00", "tpl_dur_1": 486, "tpl_heads_1": 80, "tpl_use_1": True,
        "tpl_start_2": "10:00", "tpl_dur_2": 486, "tpl_heads_2": 70, "tpl_use_2": True,
        "tpl_start_3": "12:00", "tpl_dur_3": 300, "tpl_heads_3": 40, "tpl_use_3": False,
        "tpl_start_4": "14:00", "tpl_dur_4": 240, "tpl_heads_4": 30, "tpl_use_4": False,
        "tpl_start_5": "16:00", "tpl_dur_5": 486, "tpl_heads_5": 20, "tpl_use_5": False,

        # --- DES break widget defaults (tab_des.py, fixed 3-shift + 3-rule grid) ---
        "des_break_shift_start_0": "08:00", "des_break_shift_dur_0": 480, "des_break_shift_heads_0": 60,
        "des_break_shift_start_1": "09:00", "des_break_shift_dur_1": 480, "des_break_shift_heads_1": 80,
        "des_break_shift_start_2": "10:00", "des_break_shift_dur_2": 480, "des_break_shift_heads_2": 70,
        "des_break_rule_name_0": "Tea 1", "des_break_rule_dur_0": 15, "des_break_rule_earliest_0": 120, "des_break_rule_latest_0": 180,
        "des_break_rule_name_1": "Lunch",  "des_break_rule_dur_1": 30, "des_break_rule_earliest_1": 240, "des_break_rule_latest_1": 330,
        "des_break_rule_name_2": "Tea 2",  "des_break_rule_dur_2": 15, "des_break_rule_earliest_2": 360, "des_break_rule_latest_2": 450,
    }

    for key, default in _DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default

    # --- Phase 9: load persisted settings and widget state from disk ---
    # load_settings() merges saved values over defaults; load_dataframes()
    # restores previously computed results so they appear on reload.
    saved_settings = state_manager.load_settings()
    for key, value in saved_settings.items():
        if key not in st.session_state:
            st.session_state[key] = value

    saved_dfs = state_manager.load_dataframes()
    for key, df in saved_dfs.items():
        if key not in st.session_state:
            st.session_state[key] = df


st.set_page_config(page_title="Call Centre Workforce Simulator", layout="wide")


# ---------------------------------------------------------------------------
# Phase 10: Deployment key gate
# ---------------------------------------------------------------------------
# Reads DEPLOYMENT_KEY from the environment (set in .env / docker-compose env).
# If the key is missing or invalid the app stops here with a clear message.
# Bypassed automatically when the key_validator module is not importable
# (e.g. during unit testing without the auth package installed).

def _gate_deployment_key() -> None:
    """Halt with a user-facing error if the deployment key is absent or invalid."""
    if not _key_validator_available:
        return  # auth package not installed — allow access (dev/test mode)

    key = os.environ.get("DEPLOYMENT_KEY", "").strip()
    if not key:
        st.error(
            "**Deployment key required.**\n\n"
            "Set `DEPLOYMENT_KEY` in your `.env` file or environment variables. "
            "Contact your administrator to obtain a key."
        )
        st.stop()

    valid, msg = validate_deployment_key(key)
    if not valid:
        st.error(f"**Invalid deployment key:** {msg}\n\nContact your administrator to obtain a valid key.")
        st.stop()


# ---------------------------------------------------------------------------
# Phase 10: Login screen
# ---------------------------------------------------------------------------

def _gate_login() -> None:
    """Render the login screen and halt until the user authenticates.

    Reads credentials from auth/credentials.yaml. Skipped gracefully if
    streamlit-authenticator is not installed or credentials.yaml does not exist
    (local dev without auth configured).
    """
    if not _stauth_available:
        return  # streamlit-authenticator not installed — allow access

    creds_path = Path(__file__).parent / "auth" / "credentials.yaml"
    if not creds_path.exists():
        # credentials.yaml not configured — allow access silently (local dev mode)
        return

    with open(creds_path) as f:
        config = yaml.load(f, Loader=SafeLoader)

    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
    )

    authenticator.login()

    status = st.session_state.get("authentication_status")
    if status is False:
        st.error("Incorrect username or password.")
        st.stop()
    elif status is None:
        st.info("Enter your credentials to access the Workforce Simulator.")
        st.stop()
    else:
        # Authenticated — add logout button and welcome message to sidebar.
        authenticator.logout("Logout", "sidebar")
        name = st.session_state.get("name", "")
        if name:
            st.sidebar.markdown(f"Logged in as **{name}**")


_gate_deployment_key()
_gate_login()

# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

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

# Phase 9: persist sidebar settings after every render (fast JSON write).
state_manager.save_settings(st.session_state)

# Phase 11: forecasted demand takes priority when active.
_forecast_df = st.session_state.get("forecast_demand_df")
_using_forecast = _forecast_df is not None and not (
    isinstance(_forecast_df, pd.DataFrame) and _forecast_df.empty
)

if _using_forecast:
    try:
        df_inputs = _forecast_df.copy()
        num_intervals = len(df_inputs)
    except Exception as e:
        st.error(f"Forecast demand error: {e}")
        st.stop()
else:
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

# Phase 12: keep the current Erlang output accessible to the report tab.
st.session_state["report_erlang_df"] = df_erlang

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
    "Demand Forecast",
    "Workforce Planning",
    "Hiring Optimisation",
    "Report",
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
    render_forecast_tab()

with tabs[5]:
    render_planning_tab(shrinkage_pct=cfg.shrinkage * 100.0)

with tabs[6]:
    render_optimisation_tab(shrinkage_pct=cfg.shrinkage * 100.0)

with tabs[7]:
    render_report_tab(df_erlang, cfg)

with tabs[8]:
    render_downloads_tab(df_inputs, df_erlang, roster_df)
