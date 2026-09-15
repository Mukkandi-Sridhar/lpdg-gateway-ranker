"""Settings from environment variables, with defaults that work from the repo root.

| Variable          | Default              | Meaning                                          |
|-------------------|----------------------|--------------------------------------------------|
| DATA_DIR          | data                 | folder holding telemetry/, gateway_master.csv... |
| PREDICTIONS_PATH  | predictions.csv      | the 120-row CSV the pipeline writes              |
| RESULTS_PATH      | output/results.json  | every gateway's score parts, served by the API   |
| RANKER            | improved             | name of a ranker in gateway_ranker/rankers       |
| FIRST_WEEK        | 2026-02-02           | first Monday to predict (UTC)                    |
| N_WEEKS           | 8                    | number of consecutive Mondays to predict         |
| LOG_LEVEL         | INFO                 | Python logging level                             |
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


class ConfigError(ValueError):
    """A setting (environment variable or CLI flag) has an invalid value."""


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    predictions_path: Path
    results_path: Path
    ranker: str
    first_week: pd.Timestamp
    n_weeks: int
    log_level: str

    @property
    def weeks(self) -> list[pd.Timestamp]:
        return scored_weeks(self.first_week, self.n_weeks)


def load_settings(**overrides: object) -> Settings:
    """Read settings from the environment; keyword overrides that are not None win (CLI flags).

    Raises ConfigError for an invalid value.
    """
    values = {
        "data_dir": os.environ.get("DATA_DIR", "data"),
        "predictions_path": os.environ.get("PREDICTIONS_PATH", "predictions.csv"),
        "results_path": os.environ.get("RESULTS_PATH", "output/results.json"),
        "ranker": os.environ.get("RANKER", "improved"),
        "first_week": os.environ.get("FIRST_WEEK", "2026-02-02"),
        "n_weeks": os.environ.get("N_WEEKS", "8"),
        "log_level": os.environ.get("LOG_LEVEL", "INFO"),
    }
    values.update({k: v for k, v in overrides.items() if v is not None})
    try:
        n_weeks = int(str(values["n_weeks"]))
    except ValueError:
        raise ConfigError(f"N_WEEKS must be a whole number, got {values['n_weeks']!r}") from None
    if n_weeks < 1:
        raise ConfigError(f"N_WEEKS must be at least 1, got {n_weeks}")
    try:
        first_week = parse_monday(str(values["first_week"]))
    except ValueError as error:
        raise ConfigError(f"FIRST_WEEK: {error}") from None
    return Settings(
        data_dir=Path(str(values["data_dir"])),
        predictions_path=Path(str(values["predictions_path"])),
        results_path=Path(str(values["results_path"])),
        ranker=str(values["ranker"]),
        first_week=first_week,
        n_weeks=n_weeks,
        log_level=str(values["log_level"]).upper(),
    )


def parse_monday(value: str) -> pd.Timestamp:
    """'2026-02-02' -> Timestamp('2026-02-02 00:00 UTC').

    Raises ValueError unless the value is a Monday at 00:00 UTC. A timestamp with a non-zero
    UTC offset is refused rather than converted: '2026-02-02T00:00-05:00' is Monday 05:00 UTC,
    and accepting it would move the data cutoff into the week being predicted.
    """
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):
        raise ValueError(f"not a date: {value!r} (expected YYYY-MM-DD)") from None
    if ts is pd.NaT:
        raise ValueError(f"not a date: {value!r} (expected YYYY-MM-DD)")
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    elif ts.utcoffset() != pd.Timedelta(0):
        raise ValueError(f"{value!r} is not in UTC; give a plain date (YYYY-MM-DD)")
    else:
        ts = ts.tz_convert("UTC")
    if ts != ts.normalize() or ts.dayofweek != 0:
        raise ValueError(f"{value!r} is not a Monday at 00:00 UTC")
    return ts


def scored_weeks(first_week: pd.Timestamp, n_weeks: int) -> list[pd.Timestamp]:
    return [first_week + pd.Timedelta(weeks=i) for i in range(n_weeks)]


def configure_logging(level: str) -> None:
    """One line per event: time, level, module, message."""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True)
