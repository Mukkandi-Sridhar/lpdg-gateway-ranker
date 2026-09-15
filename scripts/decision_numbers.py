"""Reproduce the numbers quoted in DECISIONS.md and LIMITATIONS.md.

explore_data.py covers the basic data problems and compare_to_baseline.py covers the
comparison with the baseline. This script prints everything else those documents quote.

Run:  python scripts/decision_numbers.py [--data PATH]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway_ranker.config import load_settings
from gateway_ranker.loading import load_dataset, normalize_gateway_ids
from gateway_ranker.pipeline import run_pipeline
from gateway_ranker.rankers.improved import week_signals

WEEK = pd.Timedelta(days=7)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data")
    args = parser.parse_args()
    logging.disable(logging.WARNING)
    data = load_dataset(args.data)

    with tempfile.TemporaryDirectory() as tmp:
        settings = load_settings(data_dir=args.data, predictions_path=Path(tmp) / "p.csv",
                                 results_path=Path(tmp) / "r.json")
        run_pipeline(settings)
        results = json.loads((Path(tmp) / "r.json").read_text())

    print("=== Silence per scored week (DECISIONS §2, LIMITATIONS 3)")
    tel = data.telemetry
    for monday in settings.weeks:
        s = week_signals(data.before(monday), monday)
        rows = tel[(tel["ts"] >= monday - WEEK) & (tel["ts"] < monday)].groupby("gateway_id").size()
        zero = s[rows.reindex(s.index, fill_value=0) == 0]
        live = s[(s["status"] == "in_service") & s["has_history"]]
        print(f"{monday.date()}: gateways with no rows {len(zero)} "
              f"(not installed {int((zero['status'] == 'not_installed').sum())}, "
              f"decommissioned {int((zero['status'] == 'decommissioned').sum())}, "
              f"in service {int((zero['status'] == 'in_service').sum())}) | in service: "
              f"median silent hours {live['silent_hours'].median():.0f}, "
              f"share >= 34 h {(live['silent_hours'] >= 34).mean():.0%}, "
              f"count >= 84 h {int((live['silent_hours'] >= 84).sum())}")

    print("\n=== Our picks per scored week (DECISIONS §2-3, LIMITATIONS 3-4)")
    for week in results["summary"]["scored_weeks"]:
        entries = results["weeks"][week]
        top = [g for g in entries if g["rank"] is not None]
        silence_driven = sum(g["components"]["silence_points"] > g["components"]["anomaly_points"] for g in top)
        held_back = sum(g["reason"].startswith("Not re-picked") for g in entries)
        low = sum(g["score"] < 10 for g in top)
        print(f"{week}: silence-driven {silence_driven}/15 | 15th pick score {top[-1]['score']} | "
              f"picks under 10 points {low} | held back as the same fault {held_back}")

    print("\n=== Region-days Jan-Mar 2026 with under half the region's usual rows (DECISIONS §2)")
    region = data.master.set_index("gateway_id")["region"]
    recent = tel[(tel["ts"] >= "2026-01-01") & (tel["ts"] < "2026-04-01")]
    per_day = recent.assign(region=recent["gateway_id"].map(region), day=recent["ts"].dt.floor("D"))
    counts = per_day.groupby(["region", "day"]).size().unstack(0)
    share = counts / counts.median()
    print(f"{int((share < 0.5).sum().sum())} of {share.size} region-days")

    print("\n=== offline_duration_sec vs disconnection_cnt x avg_offline_duration (DECISIONS data table)")
    raw = pd.read_parquet(Path(args.data) / "telemetry",
                          columns=["gateway_id", "ts_utc", "offline_duration_sec", "disconnection_cnt",
                                   "avg_offline_duration", "avg_uptime"])
    raw = raw.drop_duplicates(["gateway_id", "ts_utc"])
    pos = raw[raw["offline_duration_sec"] > 0]
    ratio = pos["offline_duration_sec"] / (pos["disconnection_cnt"] * pos["avg_offline_duration"])
    print(f"rows with offline time: {len(pos)} | ratio min {ratio.min():.3f}, max {ratio.max():.3f} | "
          f"max in one hour: {raw['offline_duration_sec'].max()}")

    print("\n=== avg_uptime step per hour, by firmware (DECISIONS data table)")
    raw["gateway_id"] = normalize_gateway_ids(raw["gateway_id"])
    raw["ts"] = pd.to_datetime(raw["ts_utc"], utc=True)
    raw = raw.sort_values(["gateway_id", "ts"])
    one_hour = raw.groupby("gateway_id")["ts"].diff() == pd.Timedelta(hours=1)
    step = raw["avg_uptime"].groupby(raw["gateway_id"]).diff()[one_hour].groupby(raw["gateway_id"]).median()
    unit = step.map(lambda v: "seconds" if abs(v - 3600) < 50 else "centiseconds" if abs(v - 360000) < 500 else "other")
    firmware = data.master.set_index("gateway_id")["fw_version"] if "fw_version" in data.master else None
    print(unit.value_counts().to_string())
    if firmware is not None:
        print(pd.crosstab(firmware.reindex(unit.index), unit).to_string())


if __name__ == "__main__":
    main()
