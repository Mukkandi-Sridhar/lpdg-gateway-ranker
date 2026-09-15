"""Tiny hand-built synthetic datasets for tests.

Nothing here is copied from the LPDG dataset: IDs, values and dates are invented.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

GATEWAYS = [f"0A00000000{i:02d}" for i in range(1, 7)]


def colon_id(gateway_id: str) -> str:
    """'0A0000000001' -> '0A:00:00:00:00:01' (the format used by master, visits, review)."""
    return ":".join(gateway_id[i : i + 2] for i in range(0, 12, 2))


def make_telemetry(gateways: list[str] = GATEWAYS, start: str = "2026-01-01", end: str = "2026-02-09",
                   seed: int = 0) -> pd.DataFrame:
    """One row per gateway per hour in [start, end), with small random noise."""
    hours = pd.date_range(start, end, freq="h", tz="UTC", inclusive="left")
    df = pd.MultiIndex.from_product([gateways, hours], names=["gateway_id", "ts"]).to_frame(index=False)
    rng = np.random.default_rng(seed)
    n = len(df)
    df["ts_utc"] = df["ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    df["disconnection_cnt"] = rng.poisson(0.2, n).astype("int32")
    df["offline_duration_sec"] = (df["disconnection_cnt"] * rng.integers(10, 60, n)).astype("int32")
    df["reboot_cnt"] = rng.poisson(0.05, n).astype("int32")
    return df.drop(columns="ts")[["gateway_id", "ts_utc", "offline_duration_sec", "disconnection_cnt", "reboot_cnt"]]


def silence(telemetry: pd.DataFrame, gateway_id: str, start: str, end: str) -> pd.DataFrame:
    """Remove a gateway's rows in [start, end): the gateway stops reporting."""
    ts = pd.to_datetime(telemetry["ts_utc"], utc=True)
    in_window = (ts >= pd.Timestamp(start, tz="UTC")) & (ts < pd.Timestamp(end, tz="UTC"))
    gone = (telemetry["gateway_id"] == gateway_id) & in_window
    return telemetry[~gone].reset_index(drop=True)


def spike(telemetry: pd.DataFrame, gateway_id: str, start: str, end: str, column: str, value: int) -> pd.DataFrame:
    """Set `column` to `value` for a gateway's rows in [start, end)."""
    out = telemetry.copy()
    ts = pd.to_datetime(out["ts_utc"], utc=True)
    hit = (out["gateway_id"] == gateway_id) & (ts >= pd.Timestamp(start, tz="UTC")) & (ts < pd.Timestamp(end, tz="UTC"))
    out.loc[hit, column] = value
    return out


def make_master(gateways: list[str] = GATEWAYS, installed_on: dict[str, str] | None = None,
                decommissioned_on: dict[str, str] | None = None) -> pd.DataFrame:
    """Asset register in the delivered format: colon IDs, German site type."""
    installed_on = installed_on or {}
    decommissioned_on = decommissioned_on or {}
    return pd.DataFrame({
        "gateway_id": [colon_id(g) for g in gateways],
        "tenant": "tenant_x",
        "site_type": "Außenmast",
        "region": "Testland",
        "hw_model": "GW-TEST",
        "antenna_type": "Omni",
        "fw_version": "1.0.0",
        "fw_updated_on": "",
        "installed_on": [installed_on.get(g, "2024-01-01") for g in gateways],
        "decommissioned_on": [decommissioned_on.get(g, "") for g in gateways],
        "n_meters_installed": 100,
    })


def make_meter_reads(gateways: list[str] = GATEWAYS, weeks: list[str] | None = None,
                     ratio: dict[str, float] | None = None) -> pd.DataFrame:
    """Weekly meter reads; 90% read unless `ratio` overrides a gateway."""
    weeks = weeks or ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"]
    ratio = ratio or {}
    rows = [{"week_start": w, "gateway_id": g, "meters_expected": 100, "meters_read": round(100 * ratio.get(g, 0.9))}
            for w in weeks for g in gateways]
    return pd.DataFrame(rows)


def write_data_dir(root: Path, telemetry: pd.DataFrame, master: pd.DataFrame | None = None,
                   meter_reads: pd.DataFrame | None = None, visits: pd.DataFrame | None = None,
                   review: pd.DataFrame | None = None) -> Path:
    """Write a data folder laid out like the real one. Optional files are skipped when None."""
    for month, part in telemetry.groupby(telemetry["ts_utc"].str[:7]):
        folder = root / "telemetry" / f"month={month}"
        folder.mkdir(parents=True, exist_ok=True)
        part.to_parquet(folder / "part-0.parquet", index=False)
    master = master if master is not None else make_master()
    master.to_csv(root / "gateway_master.csv", index=False, encoding="latin1")
    if meter_reads is not None:
        meter_reads.to_csv(root / "meter_read_success.csv", index=False)
    if visits is not None:
        visits.to_csv(root / "field_visits.csv", index=False)
    if review is not None:
        review.to_excel(root / "engineer_review_2026-02.xlsx", index=False)
    return root
