"""Build the ranking for every week and write the outputs atomically.

Weeks ranked:
- the scored weeks from settings (FIRST_WEEK, N_WEEKS): these go into predictions.csv
- plus every later Monday whose previous 7 days the telemetry fully covers. When a new
  month is dropped into data/telemetry/, "this week's 15" moves forward with it, while
  predictions.csv keeps exactly the scored weeks the validator expects.

Outputs:
- predictions.csv: week_start, rank, gateway_id, score, reason (15 per scored week)
- results.json: every gateway's score, components and reason for every ranked week, plus a
  run summary (including warnings). The API serves this file, so GET requests never touch
  the raw data.

Both files are written to temporary files first and then renamed into place, so a run that
fails part-way leaves the previous outputs untouched.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from gateway_ranker.checks import DataError
from gateway_ranker.config import Settings
from gateway_ranker.loading import Dataset, load_dataset
from gateway_ranker.rankers import get_ranker
from gateway_ranker.rankers.base import GatewayScore, RankedGateway, select_top

log = logging.getLogger(__name__)

PREDICTION_COLUMNS = ["week_start", "rank", "gateway_id", "score", "reason"]
MAX_REASON_CHARS = 300
WEEK = pd.Timedelta(days=7)
# Warn when more than this share of reporting gateways lost at least half of a week's hours:
# that points at the mobile network or LPDG's monitoring, not at 15 separate gateway faults.
FLEET_SILENCE_SHARE = 0.5
HALF_WEEK_HOURS = 84


def run_pipeline(settings: Settings) -> dict[str, object]:
    """Load data, rank every week, write predictions.csv and results.json. Returns the run summary."""
    started = time.perf_counter()
    ranker = get_ranker(settings.ranker)
    data = load_dataset(settings.data_dir)
    check_coverage(data, settings.weeks)
    mondays = extend_to_latest_week(settings.weeks, data)
    scored = set(settings.weeks)

    previous_picks: dict[pd.Timestamp, list[str]] = {}
    rows: list[dict[str, object]] = []
    weeks: dict[str, list[dict[str, object]]] = {}
    warnings: list[str] = []
    for monday in mondays:
        scores = ranker.score_week(data.before(monday), monday, previous_picks)
        top = select_top(scores)
        previous_picks[monday] = [r.gateway_id for r in top]
        week = monday.date().isoformat()
        weeks[week] = week_entries(scores, top)
        if monday in scored:
            rows.extend(
                {"week_start": week, "rank": r.rank, "gateway_id": r.gateway_id,
                 "score": round(r.score, 2), "reason": _fit_reason(r.reason)}
                for r in top
            )
        warning = fleet_silence_warning(data, monday)
        if warning:
            warnings.append(warning)
            log.warning(warning)
        log.info("ranked week=%s scored=%s candidates=%d eligible=%d top_score=%.2f low_evidence_picks=%d",
                 week, monday in scored, len(scores), sum(s.eligible for s in scores), top[0].score,
                 sum(r.score < 10 for r in top))

    summary = {
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "duration_sec": round(time.perf_counter() - started, 2),
        "ranker": ranker.name,
        "weeks": list(weeks),
        "scored_weeks": [m.date().isoformat() for m in settings.weeks],
        "latest_week": list(weeks)[-1],
        "rows": len(rows),
        "warnings": warnings,
        "data": data.report,
    }
    _write_atomically({
        settings.predictions_path: pd.DataFrame(rows, columns=PREDICTION_COLUMNS).to_csv(index=False),
        settings.results_path: json.dumps({"summary": summary, "weeks": weeks}, indent=1, default=str),
    })
    log.info("run finished ranker=%s weeks_ranked=%d rows=%d latest_week=%s warnings=%d duration_sec=%.2f",
             ranker.name, len(weeks), len(rows), summary["latest_week"], len(warnings), summary["duration_sec"])
    return summary


def week_entries(scores: list[GatewayScore], top: list[RankedGateway]) -> list[dict[str, object]]:
    """Every gateway's result for one week, as stored in results.json, with the 15 picks first."""
    ranked = {r.gateway_id: r for r in top}
    entries = []
    for s in scores:
        pick = ranked.get(s.gateway_id)
        entries.append({
            "gateway_id": s.gateway_id,
            "rank": pick.rank if pick else None,
            "score": round(s.score, 2),
            "eligible": s.eligible,
            "reason": pick.reason if pick else s.reason,
            "components": s.components,
        })
    return sorted(entries, key=lambda e: (e["rank"] is None, e["rank"] or 0, -e["score"], e["gateway_id"]))


def check_coverage(data: Dataset, weeks: list[pd.Timestamp]) -> None:
    """Refuse to rank a scored week the telemetry does not reach: every gateway would look silent."""
    if weeks[-1] > latest_covered_monday(data):
        raise DataError(
            f"telemetry ends at {data.telemetry['ts'].max().isoformat()}, but week {weeks[-1].date()} needs "
            f"the full 7 days before it; add the missing month or choose earlier weeks (FIRST_WEEK / N_WEEKS)"
        )
    if data.telemetry["ts"].min() > weeks[0] - 4 * WEEK:
        log.warning("less than 28 days of telemetry before week %s", weeks[0].date())


def fleet_silence_warning(data: Dataset, monday: pd.Timestamp) -> str | None:
    """A warning when most gateways lost at least half of the week before `monday`, else None.

    Silence-based picks are unreliable in such a week: the 15 highest silence scores are then
    decided by tiny differences, or by gateway_id when every gateway is equally silent.
    """
    week_start = monday - WEEK
    decommissioned = data.master.loc[data.master["decommissioned_on"] <= monday, "gateway_id"]
    reporting = data.first_seen.index[data.first_seen < week_start].difference(pd.Index(decommissioned))
    if reporting.empty:
        return None
    tel = data.telemetry
    rows = tel[(tel["ts"] >= week_start) & (tel["ts"] < monday)].groupby("gateway_id").size()
    share = float((rows.reindex(reporting, fill_value=0) < HALF_WEEK_HOURS).mean())
    if share <= FLEET_SILENCE_SHARE:
        return None
    return (f"week {monday.date()}: {share:.0%} of {len(reporting)} reporting gateways lost at least half of "
            "the week's telemetry; this looks like a network or monitoring outage, so silence-based picks "
            "for this week are unreliable")


def latest_covered_monday(data: Dataset) -> pd.Timestamp:
    """The last Monday whose previous 7 days fall inside the telemetry."""
    end = (data.telemetry["ts"].max() + pd.Timedelta(hours=1)).normalize()
    return end - pd.Timedelta(days=end.dayofweek)


def extend_to_latest_week(weeks: list[pd.Timestamp], data: Dataset) -> list[pd.Timestamp]:
    """The scored weeks plus every later Monday the telemetry covers."""
    mondays = list(weeks)
    while mondays[-1] + WEEK <= latest_covered_monday(data):
        mondays.append(mondays[-1] + WEEK)
    return mondays


def _fit_reason(reason: str) -> str:
    if len(reason) <= MAX_REASON_CHARS:
        return reason
    log.warning("reason longer than %d characters was shortened: %r", MAX_REASON_CHARS, reason)
    return reason[: MAX_REASON_CHARS - 1] + "…"


def _write_atomically(contents: dict[Path, str]) -> None:
    """Write every file to a temp file in its own folder first, then rename all into place."""
    staged = []
    try:
        for path, text in contents.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            os.chmod(tmp, 0o644)  # mkstemp creates owner-only files; outputs must be readable by others
            staged.append((tmp, path))
        for tmp, path in staged:
            os.replace(tmp, path)
    finally:
        for tmp, _ in staged:
            if os.path.exists(tmp):
                os.remove(tmp)
