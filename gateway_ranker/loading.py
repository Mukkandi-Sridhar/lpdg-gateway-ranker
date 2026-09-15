"""Read the LPDG data folder into clean DataFrames.

Every loader:
- normalises gateway IDs to 12 uppercase hex characters ("06:39:ea:.." -> "0639EA..")
- parses every date as a UTC timestamp, so all files are cut at the same instant
- checks its input and raises DataError when the input is wrong

The data folder is read fresh on every call. Nothing is cached at module level, so
a new telemetry month dropped into data/telemetry/ is picked up by the next load.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from gateway_ranker.checks import (
    DataError,
    parse_utc,
    require_columns,
    require_non_empty,
    require_non_negative,
    require_valid_ids,
)

log = logging.getLogger(__name__)

# Only the telemetry columns the rankers use are read, which keeps /run fast.
TELEMETRY_COLUMNS = ["gateway_id", "ts_utc", "offline_duration_sec", "disconnection_cnt", "reboot_cnt"]
MASTER_COLUMNS = ["gateway_id", "site_type", "region", "installed_on", "decommissioned_on", "n_meters_installed"]
METER_COLUMNS = ["week_start", "gateway_id", "meters_expected", "meters_read"]
VISIT_COLUMNS = ["visit_id", "gateway_id", "requested_on", "visited_on", "reason_reported", "outcome"]
REVIEW_COLUMNS = ["gateway_id", "Kategorie", "reviewed_on", "Bemerkung"]

_ID_RE = re.compile(r"^[0-9A-F]{12}$")


def normalize_gateway_id(raw: str) -> str:
    """Normalise one ID from user input. Raises ValueError if it is not a gateway ID."""
    cleaned = str(raw).strip().replace(":", "").replace("-", "").upper()
    if not _ID_RE.match(cleaned):
        raise ValueError(f"not a gateway id: {raw!r} (expected 12 hex characters, colons optional)")
    return cleaned


def normalize_gateway_ids(ids: pd.Series) -> pd.Series:
    """Vectorised version of normalize_gateway_id, without validation (see checks.require_valid_ids)."""
    return ids.astype("string").str.strip().str.replace(":", "", regex=False).str.upper()


def available_before(df: pd.DataFrame, date_col: str, monday: pd.Timestamp) -> pd.DataFrame:
    """Rows whose date_col is strictly before `monday` (a UTC timestamp).

    This is the single leakage guard used for every file.
    """
    if df[date_col].dt.tz is None or monday.tzinfo is None:
        raise TypeError("available_before needs UTC-aware timestamps on both sides")
    return df[df[date_col] < monday]


@dataclass
class Dataset:
    """All inputs, cleaned. `report` records what loading found and did."""

    telemetry: pd.DataFrame
    master: pd.DataFrame
    meter_reads: pd.DataFrame
    visits: pd.DataFrame
    review: pd.DataFrame
    report: dict[str, object] = field(default_factory=dict)

    def before(self, monday: pd.Timestamp) -> Dataset:
        """The data a ranker may see when predicting the week starting `monday`."""
        visits = available_before(self.visits, "requested_on", monday).copy()
        # A visit requested before Monday but done later has no known outcome yet.
        not_done = visits["visited_on"].isna() | (visits["visited_on"] >= monday)
        visits.loc[not_done, "outcome"] = pd.NA
        return Dataset(
            telemetry=available_before(self.telemetry, "ts", monday),
            master=self.master,
            meter_reads=available_before(self.meter_reads, "week_start", monday),
            visits=visits,
            review=available_before(self.review, "reviewed_on", monday),
            report=self.report,
        )


def load_dataset(data_dir: Path | str) -> Dataset:
    """Load every file in the data folder. Telemetry and gateway_master are required."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise DataError(f"data folder not found: {data_dir}")
    report: dict[str, object] = {"data_dir": str(data_dir)}
    telemetry = load_telemetry(data_dir, report)
    master = load_master(data_dir)
    unknown = sorted(set(telemetry["gateway_id"]) - set(master["gateway_id"]))
    report["telemetry_ids_not_in_master"] = len(unknown)
    if unknown:
        log.warning("%d telemetry gateways are missing from gateway_master, e.g. %s", len(unknown), unknown[:3])
    return Dataset(
        telemetry=telemetry,
        master=master,
        meter_reads=load_meter_reads(data_dir, report),
        visits=load_field_visits(data_dir, report),
        review=load_engineer_review(data_dir, report),
        report=report,
    )


def load_telemetry(data_dir: Path, report: dict[str, object] | None = None) -> pd.DataFrame:
    """Read every data/telemetry/month=YYYY-MM/*.parquet file, whatever months exist."""
    report = report if report is not None else {}
    files = sorted((data_dir / "telemetry").glob("month=*/*.parquet"))
    if not files:
        raise DataError(f"no telemetry files found under {data_dir / 'telemetry'} (expected month=YYYY-MM/*.parquet)")
    frames = []
    for path in files:
        source = str(path.relative_to(data_dir))
        missing = [c for c in TELEMETRY_COLUMNS if c not in pq.read_schema(path).names]
        if missing:
            raise DataError(f"{source}: missing required columns {missing}")
        part = pd.read_parquet(path, columns=TELEMETRY_COLUMNS)
        require_non_empty(part, source)
        frames.append(part)
    df = pd.concat(frames, ignore_index=True)
    rows_read = len(df)

    df["gateway_id"] = normalize_gateway_ids(df["gateway_id"])
    require_valid_ids(df["gateway_id"], "telemetry")
    df["ts"] = parse_utc(df["ts_utc"], "telemetry", "ts_utc")
    require_non_negative(df, ["offline_duration_sec", "disconnection_cnt", "reboot_cnt"], "telemetry")

    exact = df.duplicated(TELEMETRY_COLUMNS).sum()
    same_hour = df.duplicated(["gateway_id", "ts"]).sum()
    # Keep the first row per gateway-hour. Conflicting copies (same hour, different values)
    # are counted separately so a new kind of breakage shows up in the report.
    df = df.drop_duplicates(["gateway_id", "ts"], keep="first").drop(columns="ts_utc")
    df = df.sort_values(["gateway_id", "ts"], kind="stable").reset_index(drop=True)

    report.update(
        telemetry_files=len(files),
        telemetry_months=sorted({p.parent.name.removeprefix("month=") for p in files}),
        telemetry_rows_read=rows_read,
        telemetry_duplicates_dropped=int(same_hour),
        telemetry_conflicting_duplicates=int(same_hour - exact),
        telemetry_rows=len(df),
        telemetry_last_ts=df["ts"].max().isoformat(),
    )
    log.info("telemetry: %d files, %d rows, %d duplicates dropped", len(files), len(df), same_hour)
    if same_hour > exact:
        log.warning("telemetry: %d gateway-hours had conflicting duplicate rows; kept the first", same_hour - exact)
    return df


def load_master(data_dir: Path) -> pd.DataFrame:
    """Read gateway_master.csv (Latin-1 in the delivered data)."""
    path = data_dir / "gateway_master.csv"
    df = _read_csv(path)
    require_columns(df, MASTER_COLUMNS, path.name)
    require_non_empty(df, path.name)
    df["gateway_id"] = normalize_gateway_ids(df["gateway_id"])
    require_valid_ids(df["gateway_id"], path.name)
    dupes = df["gateway_id"].duplicated()
    if dupes.any():
        raise DataError(f"{path.name}: gateway_id listed more than once, e.g. {df.loc[dupes, 'gateway_id'].head(3).tolist()}")
    df["installed_on"] = parse_utc(df["installed_on"], path.name, "installed_on")
    df["decommissioned_on"] = parse_utc(df["decommissioned_on"], path.name, "decommissioned_on", allow_blank=True)
    return df


def load_meter_reads(data_dir: Path, report: dict[str, object]) -> pd.DataFrame:
    """Read meter_read_success.csv. Optional: an absent file gives an empty frame."""
    path = data_dir / "meter_read_success.csv"
    if not path.exists():
        return _missing_optional(path, METER_COLUMNS, ["week_start"], report)
    df = _read_csv(path)
    require_columns(df, METER_COLUMNS, path.name)
    df["gateway_id"] = normalize_gateway_ids(df["gateway_id"])
    require_valid_ids(df["gateway_id"], path.name)
    df["week_start"] = parse_utc(df["week_start"], path.name, "week_start")
    require_non_negative(df, ["meters_expected", "meters_read"], path.name)
    dupes = df.duplicated(["week_start", "gateway_id"])
    if dupes.any():
        raise DataError(f"{path.name}: {int(dupes.sum())} repeated (week_start, gateway_id) rows")
    report["meter_reads_last_week"] = df["week_start"].max().date().isoformat() if len(df) else None
    return df


def load_field_visits(data_dir: Path, report: dict[str, object]) -> pd.DataFrame:
    """Read field_visits.csv. Optional: an absent file gives an empty frame."""
    path = data_dir / "field_visits.csv"
    if not path.exists():
        return _missing_optional(path, VISIT_COLUMNS, ["requested_on", "visited_on"], report)
    df = _read_csv(path)
    require_columns(df, VISIT_COLUMNS, path.name)
    df["gateway_id"] = normalize_gateway_ids(df["gateway_id"])
    require_valid_ids(df["gateway_id"], path.name)
    df["requested_on"] = parse_utc(df["requested_on"], path.name, "requested_on")
    df["visited_on"] = parse_utc(df["visited_on"], path.name, "visited_on", allow_blank=True)
    return df


def load_engineer_review(data_dir: Path, report: dict[str, object]) -> pd.DataFrame:
    """Read engineer_review_*.xlsx files. Optional: none present gives an empty frame."""
    paths = sorted(data_dir.glob("engineer_review_*.xlsx"))
    if not paths:
        return _missing_optional(data_dir / "engineer_review_*.xlsx", REVIEW_COLUMNS, ["reviewed_on"], report)
    frames = []
    for path in paths:
        part = pd.read_excel(path)
        require_columns(part, REVIEW_COLUMNS, path.name)
        part["gateway_id"] = normalize_gateway_ids(part["gateway_id"])
        require_valid_ids(part["gateway_id"], path.name)
        part["reviewed_on"] = parse_utc(part["reviewed_on"], path.name, "reviewed_on")
        frames.append(part[REVIEW_COLUMNS])
    return pd.concat(frames, ignore_index=True)


def _read_csv(path: Path) -> pd.DataFrame:
    """Read a CSV as UTF-8, falling back to Latin-1 (gateway_master.csv is Latin-1)."""
    if not path.exists():
        raise DataError(f"required file not found: {path}")
    try:
        return pd.read_csv(path, encoding="utf-8", dtype={"gateway_id": "string"})
    except UnicodeDecodeError:
        log.info("%s is not UTF-8; reading as Latin-1", path.name)
        return pd.read_csv(path, encoding="latin1", dtype={"gateway_id": "string"})


def _missing_optional(path: Path, columns: list[str], date_columns: list[str], report: dict[str, object]) -> pd.DataFrame:
    """Empty frame with the right columns and UTC dtypes for an optional file that is absent."""
    log.warning("optional input not found: %s; ranking continues without it", path.name)
    report.setdefault("missing_optional_files", []).append(path.name)  # type: ignore[union-attr]
    df = pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
    for c in date_columns:
        df[c] = pd.Series(dtype="datetime64[ns, UTC]")
    return df
