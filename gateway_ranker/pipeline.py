"""Build the ranking for every week and write the outputs atomically.

Weeks ranked:
- the scored weeks from settings (FIRST_WEEK, N_WEEKS): these go into predictions.csv
- plus every later Monday whose previous 7 days the telemetry fully covers. When a new
  month is dropped into data/telemetry/, "this week's 15" moves forward with it, while
  predictions.csv keeps exactly the scored weeks the validator expects.

Outputs:
- predictions.csv: week_start, rank, gateway_id, score, reason (15 per scored week)
- results.json: every gateway's score, components and reason for every ranked week, plus a
  run summary. The API serves this file, so GET requests never touch the raw data.

Both files are written to temporary files first and then renamed into place, so a run that
fails part-way leaves the previous outputs untouched.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from gateway_ranker.checks import DataError
from gateway_ranker.config import Settings
from gateway_ranker.loading import Dataset, load_dataset
from gateway_ranker.rankers import get_ranker
from gateway_ranker.rankers.base import select_top

log = logging.getLogger(__name__)

PREDICTION_COLUMNS = ["week_start", "rank", "gateway_id", "score", "reason"]
MAX_REASON_CHARS = 300
WEEK = pd.Timedelta(days=7)


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
    for monday in mondays:
        scores = ranker.score_week(data.before(monday), monday, previous_picks)
        top = select_top(scores)
        previous_picks[monday] = [r.gateway_id for r in top]
        week = monday.date().isoformat()
        ranked = {r.gateway_id: r for r in top}
        if monday in scored:
            rows.extend({"week_start": week, "rank": r.rank, "gateway_id": r.gateway_id,
                         "score": round(r.score, 2), "reason": _fit_reason(r.reason)} for r in top)
        weeks[week] = sorted(
            ({"gateway_id": s.gateway_id,
              "rank": ranked[s.gateway_id].rank if s.gateway_id in ranked else None,
              "score": round(s.score, 2),
              "eligible": s.eligible,
              "reason": ranked[s.gateway_id].reason if s.gateway_id in ranked else s.reason,
              "components": s.components} for s in scores),
            key=lambda g: (g["rank"] is None, g["rank"] or 0, -g["score"], g["gateway_id"]),
        )
        log.info("ranked week=%s scored=%s candidates=%d eligible=%d top_score=%.2f low_evidence_picks=%d",
                 week, monday in scored, len(scores), sum(s.eligible for s in scores), top[0].score,
                 sum(r.score < 10 for r in top))

    summary = {
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_sec": round(time.perf_counter() - started, 2),
        "ranker": ranker.name,
        "weeks": list(weeks),
        "scored_weeks": [m.date().isoformat() for m in settings.weeks],
        "latest_week": list(weeks)[-1],
        "rows": len(rows),
        "data": data.report,
    }
    _write_atomically({
        settings.predictions_path: pd.DataFrame(rows, columns=PREDICTION_COLUMNS).to_csv(index=False),
        settings.results_path: json.dumps({"summary": summary, "weeks": weeks}, indent=1, default=str),
    })
    log.info("run finished ranker=%s weeks_ranked=%d rows=%d latest_week=%s duration_sec=%.2f",
             ranker.name, len(weeks), len(rows), summary["latest_week"], summary["duration_sec"])
    return summary


def check_coverage(data: Dataset, weeks: list[pd.Timestamp]) -> None:
    """Refuse to rank a scored week the telemetry does not reach: every gateway would look silent."""
    if weeks[-1] > latest_covered_monday(data):
        raise DataError(
            f"telemetry ends at {data.telemetry['ts'].max().isoformat()}, but week {weeks[-1].date()} needs "
            f"the full 7 days before it; add the missing month or choose earlier weeks (FIRST_WEEK / N_WEEKS)"
        )
    if data.telemetry["ts"].min() > weeks[0] - 4 * WEEK:
        log.warning("less than 28 days of telemetry before week %s", weeks[0].date())


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
