"""persistence/config_store.py

Named configuration profiles for the Workforce Simulator.

Each profile is a snapshot of all sidebar (sb_*) session-state keys saved as
a JSON file under configs/.  Profiles survive app restarts and can be shared
by copying the configs/ directory.

Public API
----------
list_configs()              -> list[str]          sorted list of saved config names
save_config(name, ss)       -> None               write current sb_* keys to disk
load_config(name)           -> dict[str, Any]     read a config by name
delete_config(name)         -> None               remove a config file
config_exists(name)         -> bool
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
CONFIGS_DIR = _PROJECT_ROOT / "configs"

# Only sb_* keys are snapshotted — they represent user-facing sidebar inputs.
_KEY_PREFIX = "sb_"

# Keys that hold date objects — serialised to ISO string and back.
_DATE_KEYS = {"sb_planning_start_date", "sb_opt_planning_start"}

# Regex: valid config name (letters, digits, spaces, hyphens, underscores).
_VALID_NAME = re.compile(r"^[\w\s\-]{1,64}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config_path(name: str) -> Path:
    safe = re.sub(r"[^\w\s\-]", "", name).strip()
    return CONFIGS_DIR / f"{safe}.json"


def _serialise(key: str, value: Any) -> Any:
    """Convert a session-state value to a JSON-safe type."""
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "isoformat"):          # datetime.date / datetime.datetime
        return value.isoformat()
    return value


def _deserialise(key: str, value: Any) -> Any:
    """Restore a JSON-loaded value to its expected Python type."""
    if key in _DATE_KEYS and isinstance(value, str):
        try:
            import datetime
            return datetime.date.fromisoformat(value)
        except ValueError:
            return None
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_configs() -> list[str]:
    """Return sorted list of saved config names (no extension)."""
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.json"))


def config_exists(name: str) -> bool:
    return _config_path(name).exists()


def save_config(name: str, session_state: Any) -> None:
    """Snapshot all sb_* keys from *session_state* to disk.

    Parameters
    ----------
    name:
        Human-readable profile name (max 64 chars, alphanumeric + space/hyphen).
    session_state:
        ``st.session_state`` or any mapping that supports iteration.
    """
    if not _VALID_NAME.match(name):
        raise ValueError(
            f"Config name '{name}' is invalid. "
            "Use letters, digits, spaces, hyphens or underscores (max 64 chars)."
        )

    snapshot: dict[str, Any] = {}
    for key in session_state:
        if key.startswith(_KEY_PREFIX):
            snapshot[key] = _serialise(key, session_state[key])

    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    path = _config_path(name)
    try:
        path.write_text(json.dumps({"name": name, "settings": snapshot}, indent=2))
        log.info("Config saved: %s → %s", name, path)
    except OSError as exc:
        log.warning("Config save failed for '%s': %s", name, exc)
        raise


def load_config(name: str) -> dict[str, Any]:
    """Load a named config and return a dict of ``{key: value}`` pairs.

    Raises FileNotFoundError if the config does not exist.
    """
    path = _config_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Config '{name}' not found at {path}")

    try:
        data = json.loads(path.read_text())
        raw = data.get("settings", data)       # backward-compat: plain dict
        return {k: _deserialise(k, v) for k, v in raw.items()}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Config load failed for '%s': %s", name, exc)
        raise


def delete_config(name: str) -> None:
    """Delete a saved config.  Silent no-op if it does not exist."""
    path = _config_path(name)
    try:
        path.unlink(missing_ok=True)
        log.info("Config deleted: %s", name)
    except OSError as exc:
        log.warning("Config delete failed for '%s': %s", name, exc)
