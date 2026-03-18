import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from config.sim_config import SimConfig
from demand.demand_loader import build_synthetic_day, load_demand_csv, validate_demand


def _hhmm_to_interval(hhmm: str, interval_minutes: int) -> int:
    """Convert 'HH:MM' string to a 0-based interval index from midnight.

    '08:00' with 15-min intervals → 32.  '18:00' → 72.  '00:00' → 0.
    Invalid strings silently return 0.
    """
    try:
        parts = hhmm.strip().split(":")
        total_minutes = int(parts[0]) * 60 + int(parts[1])
        return total_minutes // max(interval_minutes, 1)
    except Exception:
        return 0
from models.deterministic import deterministic_staffing as _deterministic_staffing
from models.erlang import solve_staffing_erlang as _solve_staffing_erlang


@st.cache_data(show_spinner=False)
def deterministic_staffing(df_inputs: pd.DataFrame, cfg) -> pd.DataFrame:
    """Cached wrapper — reruns only when df_inputs or cfg change."""
    return _deterministic_staffing(df_inputs, cfg)


@st.cache_data(show_spinner=False)
def solve_staffing_erlang(df_det: pd.DataFrame, cfg) -> pd.DataFrame:
    """Cached wrapper — reruns only when df_det or cfg change."""
    return _solve_staffing_erlang(df_det, cfg)
from persistence import state_manager
from ui.sidebar import render_sidebar
from ui.tab_overview import render_overview_tab
from ui.tab_quickcalc import render_quickcalc_tab
from ui.tab_demand import render_demand_tab
from ui.tab_des import render_des_tab
from ui.tab_downloads import render_downloads_tab
from ui.tab_forecast import render_forecast_tab
from ui.tab_optimisation import render_optimisation_tab
from ui.tab_report import render_report_tab
from ui.tab_cost import render_cost_tab
from models.cost_model import CostConfig
from ui.tab_planning import render_planning_tab
from ui.tab_roster import render_roster_tab
from ui.tab_scenarios import render_scenarios_tab
from ui.tab_multiqueue import render_multiqueue_tab
from ui.tab_blended import render_blended_tab
from ui.tab_intraday import render_intraday_tab
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

        # --- Simulation overall metrics (populated by tab_des after each DES run) ---
        "des_overall_metrics":     {},

        # --- Phase 12: PDF report ---
        "report_erlang_df":        pd.DataFrame(),
        "report_pdf_bytes":        None,

        # --- Phase 15: multi-queue comparison ---
        # Queue 1 (enabled by default as a starting point)
        "mq_q1_enabled": True,  "mq_q1_name": "Queue 1", "mq_q1_open": "08:00", "mq_q1_close": "18:00",
        "mq_q1_vol_pct": 100.0, "mq_q1_aht": 360.0, "mq_q1_sl_target": 0.80, "mq_q1_sl_threshold": 20.0,
        "mq_q1_shrinkage": 0.35, "mq_q1_occ_cap": 0.85,
        # Queue 2
        "mq_q2_enabled": False, "mq_q2_name": "Queue 2", "mq_q2_open": "08:00", "mq_q2_close": "18:00",
        "mq_q2_vol_pct": 60.0,  "mq_q2_aht": 480.0, "mq_q2_sl_target": 0.80, "mq_q2_sl_threshold": 20.0,
        "mq_q2_shrinkage": 0.35, "mq_q2_occ_cap": 0.85,
        # Queue 3
        "mq_q3_enabled": False, "mq_q3_name": "Queue 3", "mq_q3_open": "09:00", "mq_q3_close": "17:00",
        "mq_q3_vol_pct": 40.0,  "mq_q3_aht": 240.0, "mq_q3_sl_target": 0.80, "mq_q3_sl_threshold": 20.0,
        "mq_q3_shrinkage": 0.35, "mq_q3_occ_cap": 0.85,

        # --- Phase 24B: blended queues tab ---
        "bl_n_queues":  2,
        "bl_n_groups":  2,
        # Queue 1 defaults
        "bl_q1_name": "Sales",       "bl_q1_calls": 80.0,  "bl_q1_aht": 300.0,
        "bl_q1_sl_target": 80,       "bl_q1_sl_threshold": 20.0,
        "bl_q1_shrinkage": 30,       "bl_q1_patience": 180.0,
        # Queue 2 defaults
        "bl_q2_name": "Support",     "bl_q2_calls": 50.0,  "bl_q2_aht": 420.0,
        "bl_q2_sl_target": 90,       "bl_q2_sl_threshold": 30.0,
        "bl_q2_shrinkage": 30,       "bl_q2_patience": 240.0,
        # Queue 3 defaults (used when n_queues=3)
        "bl_q3_name": "Complaints",  "bl_q3_calls": 20.0,  "bl_q3_aht": 600.0,
        "bl_q3_sl_target": 85,       "bl_q3_sl_threshold": 60.0,
        "bl_q3_shrinkage": 30,       "bl_q3_patience": 300.0,
        # Skill group defaults
        "bl_g1_name": "Dedicated",   "bl_g1_queues": [],   "bl_g1_headcount": 10,
        "bl_g2_name": "Blended",     "bl_g2_queues": [],   "bl_g2_headcount": 5,
        "bl_g3_name": "Group 3",     "bl_g3_queues": [],   "bl_g3_headcount": 0,
        # DES control
        "bl_num_intervals": 96,
        # DES results (non-persisted)
        "blended_des_results": [],

        # --- Phase 27: roster optimisation enhancement ---
        "lp_result":               None,

        # --- Phase 26: intraday reforecast ---
        "intraday_result":         None,
        "intraday_current_interval": 32,
        "intraday_actual_calls":   0.0,
        "intraday_override_aht":   False,
        "intraday_actual_aht":     360.0,

        # --- Phase 14: scenario planning ---
        "sc_des_results":          {},    # dict: scenario_name → DES summary
        "sc_baseline_name":        "Baseline",
        "sc_des_abandonment":      True,
        "sc_des_patience":         180,
        "sc_des_patience_dist":    "exponential",
        # Scenario A
        "scA_enabled": False, "scA_name": "Scenario A", "scA_vol": 1.0, "scA_aht": 1.0,
        "scA_ov_shrink": False, "scA_shrink": 0.35, "scA_ov_occ": False, "scA_occ": 0.85,
        "scA_ov_sl": False, "scA_sl": 0.60, "scA_ov_thr": False, "scA_thr": 180,
        # Scenario B
        "scB_enabled": False, "scB_name": "Scenario B", "scB_vol": 1.0, "scB_aht": 1.0,
        "scB_ov_shrink": False, "scB_shrink": 0.35, "scB_ov_occ": False, "scB_occ": 0.85,
        "scB_ov_sl": False, "scB_sl": 0.60, "scB_ov_thr": False, "scB_thr": 180,
        # Scenario C
        "scC_enabled": False, "scC_name": "Scenario C", "scC_vol": 1.0, "scC_aht": 1.0,
        "scC_ov_shrink": False, "scC_shrink": 0.35, "scC_ov_occ": False, "scC_occ": 0.85,
        "scC_ov_sl": False, "scC_sl": 0.60, "scC_ov_thr": False, "scC_thr": 180,
        # Scenario D
        "scD_enabled": False, "scD_name": "Scenario D", "scD_vol": 1.0, "scD_aht": 1.0,
        "scD_ov_shrink": False, "scD_shrink": 0.35, "scD_ov_occ": False, "scD_occ": 0.85,
        "scD_ov_sl": False, "scD_sl": 0.60, "scD_ov_thr": False, "scD_thr": 180,

        # --- Phase 13: cost analytics ---
        "cost_interval_df":        pd.DataFrame(),
        "cost_monthly_df":         pd.DataFrame(),
        # sidebar cost widget defaults (populated from state_manager on reload)
        "sb_cost_rate_type":       "Hourly ($/hr)",
        "sb_agent_cost_rate":      30.0,
        "sb_annual_working_hours": 1820,
        "sb_penalty_per_abandoned": 8.0,
        "sb_idle_rate_fraction":   1.0,

        # --- Phase 16: config save/load sidebar widget state ---
        "sb_config_save_name":     "",
        "sb_config_select":        None,

        # --- Operating hours (synthetic demand) ---
        "sb_operating_hours_enabled": False,
        "sb_centre_open":          "08:00",
        "sb_centre_close":         "18:00",

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


st.set_page_config(
    page_title="Workforce Simulator",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)


def _inject_css() -> None:
    """Inject global dark-professional CSS overrides."""
    st.markdown("""
<style>
/* ── Palette ──────────────────────────────────────────────────────────────── */
:root {
    --bg:        #09090B;
    --bg2:       #18181B;
    --bg3:       #232329;
    --navy:      #18181B;
    --blue:      #6366F1;
    --blue-lt:   #818CF8;
    --border:    #3F3F46;
    --text:      #FAFAFA;
    --text-mute: #A1A1AA;
    --green:     #22C55E;
    --red:       #EF4444;
    --amber:     #F59E0B;
}

/* ── Global font & background ─────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
}

/* Main content area */
.main .block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
    max-width: 1400px;
}

/* ── Sidebar ──────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: var(--bg2) !important;
    border-right: 1px solid var(--border);
}
[data-testid="stSidebar"] .block-container {
    padding-top: 1.5rem;
}
[data-testid="stSidebar"] hr {
    border-color: var(--border);
    margin: 0.8rem 0;
}
/* Sidebar section headers */
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: var(--blue-lt) !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    margin-bottom: 0.3rem !important;
}

/* ── Tab bar ──────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background-color: var(--bg2);
    border-bottom: 1px solid var(--border);
    padding: 0 0.5rem;
    gap: 2px;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    background-color: transparent;
    color: var(--text-mute);
    border-radius: 4px 4px 0 0;
    font-size: 0.8rem;
    font-weight: 500;
    padding: 0.55rem 0.9rem;
    border-bottom: 2px solid transparent;
    transition: color 0.15s, border-color 0.15s;
}
[data-testid="stTabs"] [aria-selected="true"] {
    color: var(--blue-lt) !important;
    border-bottom: 2px solid var(--blue-lt) !important;
    background-color: rgba(44, 111, 172, 0.10) !important;
}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {
    color: var(--text) !important;
    background-color: rgba(255,255,255,0.04) !important;
}
[data-testid="stTabs"] [data-baseweb="tab-panel"] {
    padding-top: 1.2rem;
}

/* ── Metric cards ─────────────────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background-color: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.85rem 1rem;
}
[data-testid="stMetricLabel"] {
    font-size: 0.7rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.05em !important;
    text-transform: uppercase !important;
    color: var(--text-mute) !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    color: var(--text) !important;
    line-height: 1.2 !important;
}
[data-testid="stMetricDelta"] svg { display: none; }

/* ── Buttons ──────────────────────────────────────────────────────────────── */
[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, var(--blue), #4F46E5);
    border: none;
    border-radius: 6px;
    color: #fff;
    font-weight: 600;
    letter-spacing: 0.02em;
    padding: 0.45rem 1.2rem;
    transition: opacity 0.15s, box-shadow 0.15s;
    box-shadow: 0 2px 8px rgba(99, 102, 241, 0.4);
}
[data-testid="stButton"] > button[kind="primary"]:hover {
    opacity: 0.9;
    box-shadow: 0 4px 14px rgba(99, 102, 241, 0.6);
}
[data-testid="stButton"] > button[kind="secondary"] {
    background-color: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-weight: 500;
}
[data-testid="stButton"] > button[kind="secondary"]:hover {
    border-color: var(--blue);
    color: var(--blue-lt);
}

/* ── Dataframes / tables ──────────────────────────────────────────────────── */
[data-testid="stDataFrame"] > div,
[data-testid="stDataFrameResizable"] {
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    overflow: hidden;
}

/* ── Expanders ────────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    background-color: var(--bg2) !important;
    margin-bottom: 0.4rem;
}
[data-testid="stExpander"] summary {
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--text-mute);
    padding: 0.6rem 0.8rem;
}
[data-testid="stExpander"] summary:hover {
    color: var(--text);
}

/* ── Alerts / info boxes ──────────────────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 6px;
    border-left-width: 3px;
}

/* ── Dividers ─────────────────────────────────────────────────────────────── */
hr {
    border-color: var(--border) !important;
    margin: 1rem 0;
}

/* ── Subheaders ───────────────────────────────────────────────────────────── */
h2 {
    font-size: 1.1rem !important;
    font-weight: 700 !important;
    color: var(--text) !important;
    letter-spacing: -0.01em;
    padding-bottom: 0.3rem;
    border-bottom: 1px solid var(--border);
    margin-bottom: 1rem !important;
}
h3 {
    font-size: 0.92rem !important;
    font-weight: 600 !important;
    color: var(--text-mute) !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-top: 1.2rem !important;
    margin-bottom: 0.5rem !important;
}

/* ── Captions ─────────────────────────────────────────────────────────────── */
[data-testid="stCaptionContainer"] p {
    color: var(--text-mute) !important;
    font-size: 0.75rem !important;
}

/* ── Input widgets ────────────────────────────────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    background-color: var(--bg3) !important;
    border: 1px solid var(--border) !important;
    border-radius: 5px !important;
    color: var(--text) !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus {
    border-color: var(--blue) !important;
    box-shadow: 0 0 0 2px rgba(44,111,172,0.25) !important;
}
[data-baseweb="select"] {
    background-color: var(--bg3) !important;
    border-color: var(--border) !important;
}

/* ── Scrollbar ────────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--bg2); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--blue); }

/* ── Top bar (hamburger area) ─────────────────────────────────────────────── */
[data-testid="stHeader"] {
    background-color: var(--bg) !important;
    border-bottom: 1px solid var(--border);
}
</style>
""", unsafe_allow_html=True)


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

def _resolve_credentials_path() -> "Path | None":
    """Return the path to a usable credentials.yaml, or None if not configured.

    Resolution order
    ----------------
    1. ``auth/credentials.yaml`` on disk  — local dev / Docker volume mount.
    2. ``CREDENTIALS_YAML_B64`` env var   — base64-encoded YAML content, for
       cloud deployments (Railway, Render) where volume mounts are unavailable.
       The decoded file is written once to ``/tmp/wfsim_credentials.yaml`` and
       reused for the lifetime of the container process.
    3. ``None``                            — no credentials configured; the app
       allows unrestricted access (development mode).
    """
    # 1. Local file
    local = Path(__file__).parent / "auth" / "credentials.yaml"
    if local.exists():
        return local

    # 2. Env-var base64 payload
    b64 = os.environ.get("CREDENTIALS_YAML_B64", "").strip()
    if b64:
        import base64 as _b64
        import tempfile
        tmp = Path(tempfile.gettempdir()) / "wfsim_credentials.yaml"
        # Only decode once per container lifetime (content never changes at runtime).
        if not tmp.exists():
            tmp.write_bytes(_b64.b64decode(b64))
        return tmp

    # 3. Not configured
    return None


def _gate_login() -> None:
    """Render the login screen and halt until the user authenticates.

    Reads credentials from auth/credentials.yaml (or CREDENTIALS_YAML_B64 env
    var for cloud deployments). Skipped gracefully if streamlit-authenticator
    is not installed or no credentials source is available (local dev mode).
    """
    if not _stauth_available:
        return  # streamlit-authenticator not installed — allow access

    creds_path = _resolve_credentials_path()
    if creds_path is None:
        # No credentials configured — allow access silently (local dev mode).
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
_inject_css()

# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

st.markdown("""
<div style="margin-bottom:0.25rem;">
    <div style="font-size:1.35rem;font-weight:800;letter-spacing:-0.02em;
                color:#FAFAFA;line-height:1.1;">
        Workforce Simulator
    </div>
    <div style="font-size:0.7rem;color:#A1A1AA;letter-spacing:0.08em;
                text-transform:uppercase;font-weight:600;margin-top:2px;">
        Call Centre Planning &amp; Optimisation
    </div>
</div>
""", unsafe_allow_html=True)

_init_session_state()

sidebar_inputs = render_sidebar()

# Operating hours: derive interval indices from HH:MM strings.
# close == 0 is the "full day / disabled" sentinel; both fields stay 0
# when the feature is off so SimConfig hashing remains stable.
_oh_enabled = sidebar_inputs.get("operating_hours_enabled", False)
_interval_min = sidebar_inputs["interval_minutes"]
_open_i  = _hhmm_to_interval(sidebar_inputs.get("centre_open",  "08:00"), _interval_min) if _oh_enabled else 0
_close_i = _hhmm_to_interval(sidebar_inputs.get("centre_close", "18:00"), _interval_min) if _oh_enabled else 0
# Guard: if open >= close when enabled, treat as disabled (avoids zeroing everything).
if _oh_enabled and _close_i <= _open_i:
    _open_i, _close_i = 0, 0

cfg = SimConfig(
    interval_minutes=sidebar_inputs["interval_minutes"],
    aht_seconds=sidebar_inputs["aht_seconds"],
    shrinkage=sidebar_inputs["shrinkage"],
    occupancy_cap=sidebar_inputs["occupancy_cap"],
    sl_threshold_seconds=sidebar_inputs["sl_threshold_seconds"],
    sl_target=sidebar_inputs["sl_target"],
    seed=sidebar_inputs["seed"],
    centre_open_interval=_open_i,
    centre_close_interval=_close_i,
)

# Phase 13: build cost config from sidebar inputs (rate already in hourly terms).
cost_cfg = CostConfig(
    hourly_agent_cost=sidebar_inputs["hourly_agent_cost"],
    penalty_per_abandoned=sidebar_inputs["penalty_per_abandoned"],
    idle_rate_fraction=sidebar_inputs["idle_rate_fraction"],
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
            # Apply operating hours: zero calls outside [open, close).
            if cfg.centre_close_interval > cfg.centre_open_interval:
                _oh_mask = (
                    (df_inputs["interval"] < cfg.centre_open_interval) |
                    (df_inputs["interval"] >= cfg.centre_close_interval)
                )
                df_inputs = df_inputs.copy()
                df_inputs.loc[_oh_mask, "calls_offered"] = 0.0
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
    "Overview",
    "Quick Calc",
    "Demand",
    "Roster",
    "Simulation",
    "Scenarios",
    "Multi-Queue",
    "Blended Queues",
    "Forecast",
    "Intraday",
    "Planning",
    "Optimisation",
    "Cost",
    "Report",
    "Exports",
])

with tabs[0]:
    render_overview_tab(df_inputs, df_erlang, roster_df=None)

with tabs[1]:
    render_quickcalc_tab()

with tabs[2]:
    render_demand_tab(df_inputs, df_erlang, staffing_df=staffing_df, cfg=cfg)

with tabs[3]:
    roster_df = render_roster_tab(df_erlang, cfg, num_intervals, staffing_df=staffing_df)

with tabs[4]:
    render_des_tab(df_det, roster_df, cfg, staffing_df=staffing_df)

with tabs[5]:
    render_scenarios_tab(df_inputs, cfg)

with tabs[6]:
    render_multiqueue_tab(df_inputs, cfg)

with tabs[7]:
    render_blended_tab(cfg)

with tabs[8]:
    render_forecast_tab()

with tabs[9]:
    render_intraday_tab(df_erlang, cfg)

with tabs[10]:
    render_planning_tab(shrinkage_pct=cfg.shrinkage * 100.0)

with tabs[11]:
    render_optimisation_tab(shrinkage_pct=cfg.shrinkage * 100.0)

with tabs[12]:
    render_cost_tab(df_erlang, cost_cfg, cfg, roster_df=roster_df)

with tabs[13]:
    render_report_tab(df_erlang, cfg)

with tabs[14]:
    render_downloads_tab(df_inputs, df_erlang, roster_df)
