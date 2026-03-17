"""persistence/state_manager.py

Lightweight file-based persistence for the Workforce Simulator.

Saves and loads:
  - Settings (sidebar + planning + optimisation params) → state/settings.json
  - Computed DataFrames → state/{key}.parquet

The state/ directory sits at the project root and is git-ignored.
Data survives app reloads but is local to the machine — no cloud sync.

Public API
----------
load_settings()             -> dict[str, Any]
save_settings(session_state) -> None
save_dataframe(key, df)     -> None
load_dataframes()           -> dict[str, pd.DataFrame]
"""

import datetime
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent
STATE_DIR = _PROJECT_ROOT / "state"
_SETTINGS_FILE = STATE_DIR / "settings.json"

# ── DataFrame keys that are persisted to disk ──────────────────────────────────
PERSISTENT_DF_KEYS: list = [
    "planning_projection",
    "planning_hiring_plan",
    "planning_required_fte",
    "optimisation_result",
    "optimisation_scenarios",
    "forecast_demand_df",          # Phase 11 — active demand forecast
]

# ── Selectbox option validation ────────────────────────────────────────────────
_TZ_OPTIONS = {"UTC", "Australia/Melbourne"}

# ── Keys that hold date values and need ISO serialisation ─────────────────────
_DATE_KEYS = {"planning_start_date", "opt_planning_start"}

# ── Default settings ───────────────────────────────────────────────────────────
# These match the key= args on every widget that should be persisted.
# Prefixes:
#   sb_       → sidebar widgets
#   planning_ → tab_planning.py widget keys
#   opt_      → tab_optimisation.py widget keys
_DEFAULT_SETTINGS: dict = {
    # Sidebar
    "sb_interval_minutes":      15,
    "sb_aht_seconds":           360.0,
    "sb_shrinkage":             0.35,
    "sb_occupancy_cap":         0.85,
    "sb_sl_target":             0.60,
    "sb_sl_threshold_seconds":  180.0,
    "sb_avg_calls":             120.0,
    "sb_seed":                  42,
    "sb_input_tz":              "UTC",
    "sb_model_tz":              "Australia/Melbourne",
    # Planning tab (key= values in tab_planning.py)
    "planning_start_date":              None,   # datetime.date, None → default to month-start
    "planning_horizon_months":          12,
    "planning_opening_hc":              100,
    "planning_attrition_rate":          3.0,
    "planning_training_duration":       2.0,
    "planning_training_productivity":   0.0,
    "planning_ramp_duration":           3.0,
    "planning_ramp_start_pct":          60.0,
    # Optimisation tab (key= values in tab_optimisation.py)
    "opt_planning_start":           None,   # datetime.date
    "opt_horizon":                  12,
    "opt_opening_hc":               100,
    "opt_attrition_rate":           3.0,
    "opt_training_duration":        2.0,
    "opt_training_productivity":    0.0,
    "opt_ramp_duration":            3.0,
    "opt_ramp_start":               60.0,
    "opt_cost_hire":                5000.0,
    "opt_cost_surplus":             200.0,
    "opt_cost_deficit":             1500.0,
    "opt_max_hires":                20,
    "opt_attrition_variance":       2.0,
    # Demand tab (key= values in tab_demand.py)
    "demand_activity_shrinkage_pct": 0.15,
    # Phase 13: cost analytics sidebar inputs
    "sb_cost_rate_type":        "Hourly (£/hr)",
    "sb_agent_cost_rate":       30.0,
    "sb_annual_working_hours":  1820,
    "sb_penalty_per_abandoned": 8.0,
    "sb_idle_rate_fraction":    1.0,
}


# ── Serialisation helpers ──────────────────────────────────────────────────────

def _default_month_start() -> datetime.date:
    return datetime.date.today().replace(day=1)


def _deserialise(key: str, value: Any) -> Any:
    """Convert a JSON-loaded value to the Python type Streamlit widgets expect."""
    if key in _DATE_KEYS:
        if value is None:
            return _default_month_start()
        if isinstance(value, str):
            try:
                return datetime.date.fromisoformat(value)
            except ValueError:
                return _default_month_start()
        if isinstance(value, datetime.date):
            return value
        return _default_month_start()

    # Guard selectbox values against stale / unknown options
    if key == "sb_input_tz" and value not in _TZ_OPTIONS:
        return "UTC"
    if key == "sb_model_tz" and value not in _TZ_OPTIONS:
        return "Australia/Melbourne"
    if key == "sb_cost_rate_type" and value not in ("Hourly (£/hr)", "Annualised (£/year)"):
        return "Hourly (£/hr)"

    return value


def _serialise(value: Any) -> Any:
    """Convert a Python value to a JSON-safe representation."""
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    # pandas Timestamp
    if hasattr(value, "date") and callable(value.date):
        try:
            return value.date().isoformat()
        except Exception:
            pass
    return value


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


# ── Public API ─────────────────────────────────────────────────────────────────

def load_settings() -> dict:
    """Return all settings as a dict, merging disk values over defaults.

    Always succeeds — falls back to defaults on any error.
    Returned values are typed correctly for Streamlit widget initialisation.
    """
    base = {k: _deserialise(k, v) for k, v in _DEFAULT_SETTINGS.items()}

    if not _SETTINGS_FILE.exists():
        return base

    try:
        raw: dict = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Could not load %s: %s", _SETTINGS_FILE, exc)
        return base

    for key, raw_value in raw.items():
        if key in base:
            base[key] = _deserialise(key, raw_value)

    return base


def save_settings(session_state) -> None:
    """Persist all known settings keys from session_state to disk.

    Silent on failure — persistence is best-effort for a local tool.

    Parameters
    ----------
    session_state : streamlit.runtime.state.SessionStateProxy or dict-like
        Typically st.session_state.
    """
    _ensure_state_dir()
    data: dict = {}
    for key in _DEFAULT_SETTINGS:
        try:
            val = session_state.get(key)
        except Exception:
            continue
        if val is not None:
            data[key] = _serialise(val)
    try:
        _SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning("Could not save settings to %s: %s", _SETTINGS_FILE, exc)


def save_dataframe(key: str, df: pd.DataFrame) -> None:
    """Write a DataFrame to state/{key}.parquet.

    No-op if df is None or empty — avoids storing blank artefacts.
    """
    if df is None or (hasattr(df, "empty") and df.empty):
        return
    _ensure_state_dir()
    path = STATE_DIR / f"{key}.parquet"
    try:
        df.to_parquet(path, index=False)
    except Exception as exc:
        log.warning("Could not save DataFrame '%s': %s", key, exc)


# Keys that default to None rather than an empty DataFrame when absent.
# app.py checks `is not None` for these to decide whether to use them.
_NONE_DEFAULT_DF_KEYS = {"forecast_demand_df"}


def load_dataframes() -> dict:
    """Load all persisted DataFrames from disk.

    Missing or unreadable files silently yield empty DataFrames (or None for
    keys listed in _NONE_DEFAULT_DF_KEYS).
    """
    result: dict = {}
    for key in PERSISTENT_DF_KEYS:
        path = STATE_DIR / f"{key}.parquet"
        if path.exists():
            try:
                df = pd.read_parquet(path)
                result[key] = df if not df.empty else (None if key in _NONE_DEFAULT_DF_KEYS else pd.DataFrame())
            except Exception as exc:
                log.warning("Could not load DataFrame '%s': %s", key, exc)
                result[key] = None if key in _NONE_DEFAULT_DF_KEYS else pd.DataFrame()
        else:
            result[key] = None if key in _NONE_DEFAULT_DF_KEYS else pd.DataFrame()
    return result
