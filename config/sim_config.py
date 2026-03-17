from dataclasses import dataclass


@dataclass(frozen=True)
class SimConfig:
    interval_minutes: int = 15
    aht_seconds: float = 360.0
    shrinkage: float = 0.35
    occupancy_cap: float = 0.85
    sl_threshold_seconds: float = 180.0
    sl_target: float = 0.60
    seed: int = 42
    # Operating hours (synthetic demand only).
    # centre_close_interval == 0 means "full day" (feature disabled).
    # Both are 0-based interval indices relative to midnight.
    # open is inclusive, close is exclusive (half-open interval [open, close)).
    centre_open_interval: int = 0
    centre_close_interval: int = 0