"""Print verified numbers for every data problem we handle.

Run:  python scripts/explore_data.py [--data PATH]

This script only reads and prints. It never writes dataset rows anywhere, so its
output is safe to quote in DECISIONS.md.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

FIRST_SCORED_MONDAY = pd.Timestamp("2026-02-02", tz="UTC")


def norm_id(s: pd.Series) -> pd.Series:
    """'06:39:ea:56:02:c1' or '0639EA5602C1' -> '0639EA5602C1'."""
    return s.astype(str).str.replace(":", "", regex=False).str.upper().str.strip()


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data")
    data = Path(parser.parse_args().data)

    section("1. Telemetry size, months, duplicates")
    tel = pd.read_parquet(data / "telemetry")
    print("rows:", len(tel), "| columns (incl. partition 'month'):", tel.shape[1])
    print("months found:", sorted(tel["month"].astype(str).unique()))
    full_dupes = tel.drop(columns="month").duplicated().sum()
    key_dupes = tel.duplicated(["gateway_id", "ts_utc"]).sum()
    print("fully identical duplicate rows:", full_dupes)
    print("duplicates on (gateway_id, ts_utc):", key_dupes,
          "-> conflicting (same key, different values):", key_dupes - full_dupes)
    tel = tel.drop_duplicates(["gateway_id", "ts_utc"])
    tel["ts"] = pd.to_datetime(tel["ts_utc"], utc=True)
    print("ts range:", tel["ts"].min(), "->", tel["ts"].max())

    section("2. Silence = absent rows, not nulls")
    n_gw = tel["gateway_id"].nunique()
    hours = int((tel["ts"].max() - tel["ts"].min()) / pd.Timedelta(hours=1)) + 1
    grid = n_gw * hours
    print(f"gateways in telemetry: {n_gw} | full hourly grid: {grid} | "
          f"rows present: {len(tel)} | absent: {grid - len(tel)} ({1 - len(tel) / grid:.1%})")
    nulls = tel.isna().sum()
    print("columns containing nulls:", dict(nulls[nulls > 0]) or "none")
    per_gw = tel.groupby("gateway_id").size()
    print("rows per gateway: min", per_gw.min(), "median", per_gw.median(), "max", per_gw.max())
    last7 = tel[(tel["ts"] >= FIRST_SCORED_MONDAY - pd.Timedelta(days=7)) & (tel["ts"] < FIRST_SCORED_MONDAY)]
    counts = last7.groupby("gateway_id").size().reindex(per_gw.index, fill_value=0)
    print(f"week before {FIRST_SCORED_MONDAY.date()}: gateways with 0 rows: {(counts == 0).sum()}, "
          f"with < 84 of 168 hours: {(counts < 84).sum()}")

    section("3. ID formats and encodings")
    for name in ["gateway_master.csv", "field_visits.csv", "meter_read_success.csv"]:
        try:
            pd.read_csv(data / name, encoding="utf-8")
            enc = "utf-8 OK"
        except UnicodeDecodeError as e:
            enc = f"utf-8 FAILS ({e.reason} at byte {e.start})"
        sample = pd.read_csv(data / name, encoding="latin1", nrows=1)["gateway_id"].iloc[0]
        print(f"{name}: {enc} | id example format: {'colon' if ':' in sample else 'plain hex'}")
    print("telemetry id format:", "colon" if ":" in tel["gateway_id"].iloc[0] else "plain hex")

    section("4. Gateway master: decommissioned / newly installed")
    master = pd.read_csv(data / "gateway_master.csv", encoding="latin1")
    master["gateway_id"] = norm_id(master["gateway_id"])
    tel_ids = set(tel["gateway_id"])
    print("gateways in master:", len(master), "| unique ids:", master["gateway_id"].nunique())
    decom = master[master["decommissioned_on"].notna()]
    print("decommissioned:", len(decom), "| dates:",
          decom["decommissioned_on"].min(), "->", decom["decommissioned_on"].max())
    print("master ids not in telemetry:", len(set(master["gateway_id"]) - tel_ids),
          "| telemetry ids not in master:", len(tel_ids - set(master["gateway_id"])))
    last_seen = tel.groupby("gateway_id")["ts"].max()
    d = decom.set_index("gateway_id")
    d["last_row"] = last_seen.reindex(d.index)
    print(d[["decommissioned_on", "last_row"]].sort_values("decommissioned_on").to_string())
    late = master[pd.to_datetime(master["installed_on"]) >= "2025-08-01"]
    print("installed on/after 2025-08-01:", len(late))
    print(late[["gateway_id", "installed_on"]].sort_values("installed_on").to_string(index=False))

    section("5. offline_duration_sec: per-hour or counter?")
    off = tel["offline_duration_sec"]
    print("hours with value > 3600:", (off > 3600).sum(), "| max:", off.max(),
          "| hours > 0:", (off > 0).sum())
    tel = tel.sort_values(["gateway_id", "ts"])
    prev = tel.groupby("gateway_id")["offline_duration_sec"].shift()
    big = tel[off.reindex(tel.index) > 3600]
    grew = (big["offline_duration_sec"] > prev.reindex(big.index)).mean()
    print(f"of hours > 3600, share larger than the previous row: {grew:.1%}")
    has_disc = (big["disconnection_cnt"] > 0).mean()
    print(f"of hours > 3600, share with disconnection_cnt > 0: {has_disc:.1%}")
    gap = tel.groupby("gateway_id")["ts"].diff().dt.total_seconds() / 3600
    print(f"of hours > 3600, median gap in hours since previous row: {gap.reindex(big.index).median()}")
    print("correlation of value with the preceding gap (hours):",
          round(off.reindex(tel.index).corr(gap), 3))

    section("6. rx_nr_pkts outliers")
    print(tel["rx_nr_pkts"].describe(percentiles=[0.5, 0.9, 0.99, 0.999]).round(1).to_string())

    section("7. avg_uptime unit")
    step = tel.groupby("gateway_id")["avg_uptime"].diff()
    one_hour = gap == 1
    print("median uptime increase over a 1-hour step:", step[one_hour].median(),
          "(360000 would mean centiseconds)")
    print("share of 1-hour steps where uptime drops:", round((step[one_hour] < 0).mean(), 4))

    section("8. Meter read success")
    mrs = pd.read_csv(data / "meter_read_success.csv")
    print("weeks:", mrs["week_start"].min(), "->", mrs["week_start"].max(), "| rows:", len(mrs))
    print("dupes on (week, gateway):", mrs.duplicated(["week_start", "gateway_id"]).sum(),
          "| meters_read > expected:", (mrs["meters_read"] > mrs["meters_expected"]).sum(),
          "| nulls:", int(mrs.isna().sum().sum()))
    print("read ratio:", (mrs["meters_read"] / mrs["meters_expected"]).describe().round(3).to_dict())
    print("weekday of week_start:", pd.to_datetime(mrs["week_start"]).dt.day_name().unique())

    section("9. Field visits (biased sample)")
    fv = pd.read_csv(data / "field_visits.csv")
    print("rows:", len(fv), "| requested:", fv["requested_on"].min(), "->", fv["requested_on"].max(),
          "| visited:", fv["visited_on"].min(), "->", fv["visited_on"].max())
    print(fv["outcome"].value_counts().to_string())
    print(fv["reason_reported"].value_counts().to_string())
    print("distinct gateways visited:", norm_id(fv["gateway_id"]).nunique())

    section("10. Engineer review")
    rev = pd.read_excel(data / "engineer_review_2026-02.xlsx")
    print("rows:", len(rev), "| reviewed_on:", rev["reviewed_on"].unique())
    print(rev["Kategorie"].value_counts().to_string())


if __name__ == "__main__":
    main()
