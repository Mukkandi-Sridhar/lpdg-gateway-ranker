"""Improved ranker: risk points from 0 to 100, built from two plain signals.

    score = SILENCE_WEIGHT * silence + ANOMALY_WEIGHT * anomaly

- silence: hours with no telemetry row in the last 7 days, divided by 168. Counted only
  for gateways that are in service and have reported before, and only from their install
  date onward. baseline_3sigma.py never sees these hours because it scores rows that exist.
- anomaly: hours in the last 7 days where disconnections, offline time or reboots rose
  more than 3 standard deviations above the gateway's own normal, divided by 168, capped
  at 1. "Normal" is measured on days 8-28 before Monday, so a fault filling the whole last
  week cannot raise its own normal and hide itself.

Repeat picks are suppressed per fault episode. LPDG's scorer credits only the first visit
in an episode, so a gateway picked in an earlier week is not picked again until some week
from its pick onward scores below LOW_EVIDENCE_BELOW (a healthy week ends the episode). The
week that led to the pick counts, so a low-evidence filler pick never blocks a later fault.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping

import pandas as pd

from gateway_ranker.loading import Dataset
from gateway_ranker.rankers.base import LOW_EVIDENCE_PREFIX, GatewayScore

SILENCE_WEIGHT = 50.0
ANOMALY_WEIGHT = 50.0
LOW_EVIDENCE_BELOW = 10.0  # points; a week scoring below this also counts as healthy
SIGMA = 3.0
RECENT_DAYS = 7
REFERENCE_DAYS = 28  # reference window = days 8-28 before Monday
HOURS_PER_WEEK = RECENT_DAYS * 24
WEEK = pd.Timedelta(days=RECENT_DAYS)

# Metric -> plain words for reasons. Dict order breaks ties when naming the main metric.
METRICS = {
    "disconnection_cnt": "unusual disconnections",
    "offline_duration_sec": "unusually long offline time",
    "reboot_cnt": "unusual reboots",
}


class ImprovedRanker:
    """Scores one week at a time.

    The episode check needs the scores of earlier weeks, which the pipeline has usually just
    computed. They are cached per loaded dataset: a Dataset from a new load_dataset() call
    (a new `report` object) empties the cache, so a new run never sees old signals.
    """

    name = "improved"

    def __init__(self) -> None:
        self._cache: dict[pd.Timestamp, pd.DataFrame] = {}
        self._source: object | None = None

    def score_week(self, data: Dataset, monday: pd.Timestamp,
                   previous_picks: Mapping[pd.Timestamp, list[str]]) -> list[GatewayScore]:
        signals = self._signals_for(data, monday)
        in_episode = still_in_episode(monday, previous_picks, lambda week: self._signals_for(data, week)["score"])
        return [_to_score(row, in_episode.get(row.Index)) for row in signals.itertuples()]

    def _signals_for(self, data: Dataset, monday: pd.Timestamp) -> pd.DataFrame:
        if data.report is not self._source:
            self._cache, self._source = {}, data.report
        if monday not in self._cache:
            self._cache[monday] = week_signals(data.before(monday), monday)
        return self._cache[monday]


def week_signals(data: Dataset, monday: pd.Timestamp) -> pd.DataFrame:
    """One row per known gateway with its silence and anomaly numbers for the week before `monday`."""
    recent_start = monday - WEEK
    reference_start = monday - pd.Timedelta(days=REFERENCE_DAYS)
    telemetry = data.telemetry[data.telemetry["ts"] >= reference_start]
    recent = telemetry[telemetry["ts"] >= recent_start]
    reference = telemetry[telemetry["ts"] < recent_start]

    reported = data.first_seen.index  # gateways with any telemetry before Monday
    master = data.master.set_index("gateway_id")[["installed_on", "decommissioned_on"]]
    ids = master.index.union(reported)
    out = master.reindex(ids)  # gateways missing from the master get blank dates: treated as in service
    out.index.name = "gateway_id"

    out["status"] = "in_service"
    out.loc[out["installed_on"] >= monday, "status"] = "not_installed"
    out.loc[out["decommissioned_on"] <= monday, "status"] = "decommissioned"
    out["has_history"] = ids.isin(reported)

    # Silence: expected hours start at the install date if it falls inside the window.
    window_start = out["installed_on"].where(out["installed_on"] > recent_start, recent_start)
    expected = ((monday - window_start) / pd.Timedelta(hours=1)).clip(lower=0, upper=HOURS_PER_WEEK)
    present = recent.groupby("gateway_id").size().reindex(ids, fill_value=0)
    counts = (out["status"] == "in_service") & out["has_history"]
    out["expected_hours"] = expected
    out["silent_hours"] = (expected - present).clip(lower=0).where(counts, 0.0)

    # Anomaly: an hour is flagged if any metric exceeds mean + 3 std of the reference window.
    # A gateway with fewer than 2 reference rows has no std, so nothing is flagged for it.
    metrics = list(METRICS)
    stats = reference.groupby("gateway_id")[metrics]
    limit = stats.mean() + SIGMA * stats.std()
    over = recent[metrics].to_numpy() > limit.reindex(recent["gateway_id"]).to_numpy()
    flagged = pd.DataFrame(over, columns=metrics, index=recent.index)
    per_metric = flagged.groupby(recent["gateway_id"]).sum().reindex(ids, fill_value=0).astype(int)
    any_metric = flagged.any(axis=1).groupby(recent["gateway_id"]).sum()
    out["flagged_hours"] = any_metric.reindex(ids, fill_value=0).astype(int)
    for metric in metrics:
        out[f"flagged_{metric}"] = per_metric[metric]
    out["main_metric"] = per_metric[metrics].idxmax(axis=1)

    out["silence_points"] = SILENCE_WEIGHT * out["silent_hours"] / HOURS_PER_WEEK
    out["anomaly_points"] = ANOMALY_WEIGHT * (out["flagged_hours"] / HOURS_PER_WEEK).clip(upper=1.0)
    out["score"] = (out["silence_points"] + out["anomaly_points"]).round(2)
    return out.sort_index()


def still_in_episode(monday: pd.Timestamp, previous_picks: Mapping[pd.Timestamp, list[str]],
                     scores_at: Callable[[pd.Timestamp], pd.Series]) -> dict[str, pd.Timestamp]:
    """Gateways picked in an earlier week with no healthy week since -> the week they were picked.

    `scores_at(m)` returns every gateway's score for the week before Monday `m`.
    """
    last_pick: dict[str, pd.Timestamp] = {}
    for week, gateway_ids in previous_picks.items():
        if week < monday:
            for gateway_id in gateway_ids:
                last_pick[gateway_id] = max(week, last_pick.get(gateway_id, week))

    in_episode = {}
    for gateway_id, picked in sorted(last_pick.items()):
        # Start with the week that led to the pick. If that week was already healthy, the pick
        # was low-evidence filler and no fault episode was running (tests/test_regression_filler_pick.py).
        week_end = picked
        healthy = False
        while week_end <= monday and not healthy:
            healthy = scores_at(week_end).get(gateway_id, 0.0) < LOW_EVIDENCE_BELOW
            week_end += WEEK
        if not healthy:
            in_episode[gateway_id] = picked
    return in_episode


def _to_score(row, picked_week: pd.Timestamp | None) -> GatewayScore:
    components = {
        "silence_points": round(float(row.silence_points), 2),
        "anomaly_points": round(float(row.anomaly_points), 2),
        "silent_hours": float(row.silent_hours),
        "expected_hours": float(row.expected_hours),
        "flagged_hours": float(row.flagged_hours),
        "flagged_disconnection_hours": float(row.flagged_disconnection_cnt),
        "flagged_offline_hours": float(row.flagged_offline_duration_sec),
        "flagged_reboot_hours": float(row.flagged_reboot_cnt),
    }
    score = float(row.score)
    if row.status == "decommissioned":
        reason = f"Not a candidate: decommissioned on {row.decommissioned_on:%Y-%m-%d}."
        return GatewayScore(row.Index, score, reason, components, eligible=False)
    if row.status == "not_installed":
        reason = f"Not a candidate: installed on {row.installed_on:%Y-%m-%d}, after this Monday."
        return GatewayScore(row.Index, score, reason, components, eligible=False)
    if picked_week is not None:
        reason = (f"Not re-picked: already chosen for week {picked_week:%Y-%m-%d} with no healthy week since, "
                  f"so likely the same fault. {describe(row)}")
        return GatewayScore(row.Index, score, reason, components, eligible=False)
    return GatewayScore(row.Index, score, describe(row), components)


def describe(row) -> str:
    """Plain-words reason naming the bigger driver first, e.g. 'No data for 61 of the last 168 hours.'"""
    parts = []
    if row.silent_hours > 0:
        parts.append((row.silence_points, f"no data for {round(row.silent_hours)} of the last {HOURS_PER_WEEK} hours"))
    if row.flagged_hours > 0:
        hours = f"{row.flagged_hours} hour" + ("" if row.flagged_hours == 1 else "s")
        parts.append((row.anomaly_points, f"{hours} of {METRICS[row.main_metric]} vs its own normal"))
    parts.sort(key=lambda part: -part[0])  # stable: silence stays first on a tie
    text = "; also ".join(text for _, text in parts) or "no silence or unusual behaviour in the last 7 days"
    if row.status == "in_service" and not row.has_history:
        text += " (never reported, so silence is not counted)"
    if row.score < LOW_EVIDENCE_BELOW:
        return f"{LOW_EVIDENCE_PREFIX}{text}."
    return f"{text[0].upper()}{text[1:]}."
