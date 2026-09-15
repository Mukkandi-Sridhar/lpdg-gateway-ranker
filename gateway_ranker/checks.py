"""Data checks that stop with a clear message instead of guessing.

Rule of thumb used throughout the project:
- *Wrong* data (missing columns, unparseable dates, malformed IDs, empty files) raises
  DataError, because any ranking built on it would be silently wrong.
- *Missing* data that has a known meaning (absent telemetry hours, an optional file that
  is not there) is handled by the caller and recorded in the load report.
"""
from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

ID_PATTERN = r"[0-9A-F]{12}"


class DataError(Exception):
    """Input data is wrong in a way we refuse to guess about."""


def require_columns(df: pd.DataFrame, required: Iterable[str], source: str) -> None:
    """Raise if any required column is missing."""
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataError(f"{source}: missing required columns {missing}")


def require_non_empty(df: pd.DataFrame, source: str) -> None:
    """Raise if a file that must contain rows has none."""
    if df.empty:
        raise DataError(f"{source}: file has no rows")


def require_valid_ids(ids: pd.Series, source: str) -> None:
    """Raise if any (already normalised) gateway ID is not 12 uppercase hex characters."""
    bad = ids[~ids.str.fullmatch(ID_PATTERN).fillna(False).astype(bool)]
    if not bad.empty:
        examples = bad.drop_duplicates().head(3).tolist()
        raise DataError(f"{source}: {len(bad)} malformed gateway_id values, e.g. {examples}")


def parse_utc(values: pd.Series, source: str, column: str, allow_blank: bool = False) -> pd.Series:
    """Parse dates/timestamps as UTC. Blank cells are allowed only when allow_blank is True."""
    blank = values.isna() | (values.astype("string").str.strip() == "")
    parsed = pd.to_datetime(values.where(~blank), utc=True, errors="coerce", format="ISO8601")
    unparseable = parsed.isna() & ~blank
    if unparseable.any():
        examples = values[unparseable].head(3).tolist()
        raise DataError(f"{source}: {int(unparseable.sum())} unparseable values in {column}, e.g. {examples}")
    if blank.any() and not allow_blank:
        raise DataError(f"{source}: {int(blank.sum())} blank values in required column {column}")
    return parsed


def require_non_negative(df: pd.DataFrame, columns: Iterable[str], source: str) -> None:
    """Raise if a count column holds negative values."""
    for column in columns:
        values = pd.to_numeric(df[column], errors="coerce")
        if values.isna().any():
            raise DataError(f"{source}: non-numeric values in {column}")
        if (values < 0).any():
            raise DataError(f"{source}: {int((values < 0).sum())} negative values in {column}")
