"""Show, week by week, how our picks differ from baseline_3sigma.py, and why.

There is no ground truth in the bundle, so this does not claim either list is cheaper.
It shows what changed and the evidence behind each difference.

Run:
    python baseline_3sigma.py --data data --out predictions_baseline.csv
    python scripts/compare_to_baseline.py [--ours predictions.csv] [--baseline predictions_baseline.csv] [--data data]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway_ranker.config import parse_monday  # noqa: E402
from gateway_ranker.loading import load_dataset, normalize_gateway_ids  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ours", default="predictions.csv")
    parser.add_argument("--baseline", default="predictions_baseline.csv")
    parser.add_argument("--data", default="data")
    args = parser.parse_args()
    logging.disable(logging.WARNING)

    ours, base = pd.read_csv(args.ours), pd.read_csv(args.baseline)
    for frame in (ours, base):
        frame["gateway_id"] = normalize_gateway_ids(frame["gateway_id"])
    data = load_dataset(args.data)
    decommissioned = data.master.set_index("gateway_id")["decommissioned_on"].dropna()

    totals = {"same": 0, "base_dark": 0, "base_decom": 0, "base_repeat": 0, "ours_repeat": 0}
    previous: dict[str, set[str]] = {"ours": set(), "base": set()}
    for week in sorted(ours["week_start"].unique()):
        monday = parse_monday(week)
        o, b = ours[ours["week_start"] == week], base[base["week_start"] == week]
        both = set(o["gateway_id"]) & set(b["gateway_id"])
        tel = data.telemetry
        rows_last_7d = tel[(tel["ts"] >= monday - pd.Timedelta(days=7)) & (tel["ts"] < monday)].groupby("gateway_id").size()
        dark_in_ours = [g for g in o["gateway_id"] if rows_last_7d.get(g, 0) == 0]
        base_decom = [g for g in b["gateway_id"] if g in decommissioned and decommissioned[g] < monday + pd.Timedelta(days=7)]
        base_repeat = len(set(b["gateway_id"]) & previous["base"])
        ours_repeat = len(set(o["gateway_id"]) & previous["ours"])
        previous = {"ours": set(o["gateway_id"]), "base": set(b["gateway_id"])}

        totals["same"] += len(both)
        totals["base_dark"] += len(dark_in_ours)
        totals["base_decom"] += len(base_decom)
        totals["base_repeat"] += base_repeat
        totals["ours_repeat"] += ours_repeat
        print(f"\n{week}: {len(both)}/15 picks shared | ours picks {len(dark_in_ours)} fully dark gateways the baseline "
              f"cannot score | baseline picks decommissioned by week end: {len(base_decom)} | "
              f"repeats of last week: baseline {base_repeat}, ours {ours_repeat}")
        for row in o[~o["gateway_id"].isin(both)].itertuples():
            print(f"  + ours #{row.rank:>2} {row.gateway_id} rows in last 7 days={rows_last_7d.get(row.gateway_id, 0):>3} | {row.reason}")
        for row in b[~b["gateway_id"].isin(both)].itertuples():
            print(f"  - base #{row.rank:>2} {row.gateway_id} rows in last 7 days={rows_last_7d.get(row.gateway_id, 0):>3} | {row.reason}")

    print("\n=== Totals over 8 weeks (120 picks each) ===")
    print(f"shared picks: {totals['same']}")
    print(f"our picks of fully dark gateways (impossible for the baseline): {totals['base_dark']}")
    print(f"baseline picks decommissioned by the end of their week: {totals['base_decom']}")
    print(f"picks repeated from the previous week: baseline {totals['base_repeat']}, ours {totals['ours_repeat']}")
    print(f"distinct gateways picked: baseline {base['gateway_id'].nunique()}, ours {ours['gateway_id'].nunique()}")


if __name__ == "__main__":
    main()
