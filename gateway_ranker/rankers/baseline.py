"""Port of LPDG's baseline_3sigma.py behind the Ranker interface.

Same method and same numbers as the official script (tests/test_baseline_port.py checks this):
- mean and std per gateway over the 28 days before Monday, including the last 7 days
- an hour counts as a breach when a metric is more than 3 std above that mean; a std of 0
  means "no spread", so that metric cannot breach
- the score is the number of breaches in the last 7 days. An hour where two metrics breach
  counts twice, so the official "hour(s)" wording really means breaches.

Differences, all outside the method:
- runs on de-duplicated telemetry (the official script double-counts 6,547 repeated rows)
- ties are broken by gateway_id (the official sort leaves tie order to the sort algorithm)
- a gateway with no rows in the last 7 days is returned as not eligible with an explanation,
  where the official script silently leaves it out
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from gateway_ranker.loading import Dataset
from gateway_ranker.rankers.base import GatewayScore

METRICS = ["offline_duration_sec", "disconnection_cnt", "reboot_cnt"]  # order decides "first breach"
BASELINE_DAYS = 28
RECENT_DAYS = 7
SIGMA = 3.0


class BaselineRanker:
    name = "baseline"

    def score_week(self, data: Dataset, monday: pd.Timestamp,
                   previous_picks: Mapping[pd.Timestamp, list[str]]) -> list[GatewayScore]:
        tel = data.telemetry
        window = tel[(tel["ts"] >= monday - pd.Timedelta(days=BASELINE_DAYS)) & (tel["ts"] < monday)]
        grouped = window.groupby("gateway_id")[METRICS]
        mean, std = grouped.mean(), grouped.std().replace(0, np.nan)

        recent = window[window["ts"] >= monday - pd.Timedelta(days=RECENT_DAYS)]
        ids = recent["gateway_id"]
        exceeded = pd.DataFrame(
            {m: (recent[m] - ids.map(mean[m])) > SIGMA * ids.map(std[m]) for m in METRICS}, index=recent.index
        )
        breaches = exceeded.sum(axis=1).groupby(ids).sum()
        per_metric = exceeded.groupby(ids).sum()
        breach_rows = exceeded[exceeded.any(axis=1)]
        first_metric = breach_rows.idxmax(axis=1).groupby(ids[breach_rows.index]).first()

        known = sorted(set(data.master["gateway_id"]) | set(data.first_seen.index))
        scores = []
        for gateway_id in known:
            if gateway_id not in breaches.index:
                scores.append(GatewayScore(
                    gateway_id, 0.0,
                    "Not scored: no telemetry in the last 7 days, so the 3-sigma baseline has nothing to flag.",
                    eligible=False,
                ))
                continue
            n = int(breaches[gateway_id])
            metric = first_metric.get(gateway_id, "no metric over 3 sigma")
            reason = (f"{n} hour(s) beyond 3 sigma of this gateway's own 28-day baseline in the last 7 days; "
                      f"first breach on {metric}")
            components = {"breaches": float(n)}
            components.update({f"breaches_{m}": float(per_metric.at[gateway_id, m]) for m in METRICS})
            scores.append(GatewayScore(gateway_id, float(n), reason, components))
        return scores
