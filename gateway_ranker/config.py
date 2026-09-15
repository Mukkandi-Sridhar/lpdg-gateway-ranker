"""Settings from environment variables, with defaults that work from the repo root.

| Variable          | Default           | Meaning                                         |
|-------------------|-------------------|-------------------------------------------------|
| DATA_DIR          | data              | folder holding telemetry/, gateway_master.csv.. |
| PREDICTIONS_PATH  | predictions.csv   | where the pipeline writes the 120-row CSV       |
| RANKER            | improved          | improved or baseline                            |
| FIRST_WEEK        | 2026-02-02        | first Monday to predict (UTC)                   |
| N_WEEKS           | 8                 | number of consecutive Mondays to predict        |
| LOG_LEVEL         | INFO              | Python logging level                            |
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    predictions_path: Path
    ranker: str
    first_week: pd.Timestamp
    n_weeks: int
    log_level: str

    @property
    def weeks(self) -> list[pd.Timestamp]:
        return scored_weeks(self.first_week, self.n_weeks)


def load_settings(**overrides: object) -> Settings:
    """Read settings from the environment; keyword overrides (e.g. from CLI flags) win."""
    env = {
        "data_dir": os.environ.get("DATA_DIR", "data"),
        "predictions_path": os.environ.get("PREDICTIONS_PATH", "predictions.csv"),
        "ranker": os.environ.get("RANKER", "improved"),
        "first_week": os.environ.get("FIRST_WEEK", "2026-02-02"),
        "n_weeks": os.environ.get("N_WEEKS", "8"),
        "log_level": os.environ.get("LOG_LEVEL", "INFO"),
    }
    env.update({k: v for k, v in overrides.items() if v is not None})
    try:
        n_weeks = int(env["n_weeks"])
    except ValueError:
        raise ValueError(f"N_WEEKS must be a whole number, got {env['n_weeks']!r}") from None
    if n_weeks < 1:
        raise ValueError(f"N_WEEKS must be at least 1, got {n_weeks}")
    return Settings(
        data_dir=Path(str(env["data_dir"])),
        predictions_path=Path(str(env["predictions_path"])),
        ranker=str(env["ranker"]),
        first_week=parse_monday(str(env["first_week"])),
        n_weeks=n_weeks,
        log_level=str(env["log_level"]).upper(),
    )


def parse_monday(value: str) -> pd.Timestamp:
    """'2026-02-02' -> Timestamp('2026-02-02 00:00 UTC'). Raises ValueError if not a Monday date."""
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):
        raise ValueError(f"not a date: {value!r} (expected YYYY-MM-DD)") from None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    if ts != ts.normalize() or ts.dayofweek != 0:
        raise ValueError(f"{value!r} is not a Monday at 00:00 UTC")
    return ts


def scored_weeks(first_week: pd.Timestamp, n_weeks: int) -> list[pd.Timestamp]:
    return [first_week + pd.Timedelta(weeks=i) for i in range(n_weeks)]
