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