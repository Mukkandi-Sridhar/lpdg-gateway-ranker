"""Build a synthetic extra telemetry month, to rehearse the live session.

In the live session LPDG drops a month nobody has seen into data/telemetry/ and asks the
service to run on it. This makes a stand-in so that can be practised: it takes the tail of
the existing telemetry, shifts it forward by 28 days (so weekdays still line up), and writes
only the months that do not exist yet. Some gateways are made to go silent in the final week,
so the ranking visibly changes.

The result is invented data for a rehearsal. Do not hand it in, and delete it afterwards:

    python scripts/make_demo_month.py --data data --out /tmp   # writes /tmp/month=2026-04
    cp -R /tmp/month=2026-04 data/telemetry/                   # then POST /run
    rm -rf data/telemetry/month=2026-04                        # when you are done
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pandas as pd

SHIFT = pd.Timedelta(days=28)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data", help="data folder to read telemetry from")
    parser.add_argument("--out", default="/tmp", help="where to write the month=YYYY-MM folder")
    parser.add_argument("--silent", type=int, default=3, help="gateways that go silent in the final week")
    parser.add_argument("--force", action="store_true", help="overwrite an existing month folder")
    args = parser.parse_args()

    files = sorted((Path(args.data) / "telemetry").glob("month=*/*.parquet"))
    if not files:
        raise SystemExit(f"no telemetry under {args.data}/telemetry")
    df = pd.read_parquet(files[-1].parent)
    ts = pd.to_datetime(df["ts_utc"], utc=True)
    last = ts.max()

    shifted = ts + SHIFT
    keep = shifted > last  # only the part that lands after the data we already have
    df, shifted = df[keep].copy(), shifted[keep]
    df["ts_utc"] = shifted.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    local = shifted.dt.tz_convert("Europe/Berlin")
    if "DateDt" in df:
        df["DateDt"] = local.dt.strftime("%Y-%m-%d")
    if "hour" in df:
        df["hour"] = local.dt.hour.astype(df["hour"].dtype)

    silenced = sorted(df["gateway_id"].unique())[: args.silent]
    final_week = shifted >= shifted.max() - pd.Timedelta(days=7)
    df = df[~(df["gateway_id"].isin(silenced) & final_week)]

    written = []
    for month, part in df.groupby(df["ts_utc"].str[:7]):
        folder = Path(args.out) / f"month={month}"
        if folder.exists():
            if not args.force:
                raise SystemExit(f"{folder} already exists; pass --force to overwrite")
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        part.to_parquet(folder / "part-0.parquet", index=False)
        written.append(f"{folder} ({len(part)} rows)")

    print("synthetic telemetry for a rehearsal, not real data:")
    for line in written:
        print(" ", line)
    print(f"  {len(silenced)} gateways go silent in the last week: {', '.join(silenced)}")


if __name__ == "__main__":
    main()
