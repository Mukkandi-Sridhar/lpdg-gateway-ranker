"""REST API over the weekly rankings. Full reference with curl examples: API.md.

    GET  /health                               is it working, and are the rankings stale?
    GET  /weeks                                which weeks have a ranking
    GET  /rankings?week=YYYY-MM-DD             the 15 gateways to visit (default: latest week)
    GET  /gateways/{gateway_id}?week=...       why a gateway is where it is
    POST /run                                  re-read the data folder and rebuild everything

Start it with:  uvicorn api.main:create_app --factory --port 8000

GET requests serve the results file written by the last successful run, so they are fast
and never touch the raw data. POST /run re-reads the data folder from disk, so a new month
dropped into data/telemetry/ is picked up without restarting the service.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from gateway_ranker.checks import DataError
from gateway_ranker.config import Settings, configure_logging, load_settings, parse_monday
from gateway_ranker.loading import normalize_gateway_id
from gateway_ranker.pipeline import run_pipeline

log = logging.getLogger("api")


REQUIRED_SUMMARY_KEYS = {"finished_at", "ranker", "weeks", "scored_weeks", "latest_week", "duration_sec", "data"}


class ResultsStore:
    """Reads results.json, and reads it again only when the file on disk has changed."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._key: tuple[int, int, int] | None = None
        self._results: dict[str, Any] | None = None
        self._lock = threading.Lock()

    def get(self) -> dict[str, Any] | None:
        """The latest results, or None if no run has finished yet.

        Raises ValueError for a file that is not valid JSON or has the wrong shape
        (for example one written by an older version of this service).
        """
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return None
        key = (stat.st_mtime_ns, stat.st_ino, stat.st_size)
        with self._lock:
            if key != self._key:
                results = json.loads(self.path.read_text(encoding="utf-8"))
                summary = results.get("summary") if isinstance(results, dict) else None
                missing = REQUIRED_SUMMARY_KEYS - set(summary or {})
                if missing or not results.get("weeks"):
                    raise ValueError(f"results file has an unexpected shape (missing {sorted(missing) or ['weeks']})")
                self._results, self._key = results, key
            return self._results


class RunState:
    """Makes sure only one run happens at a time, and remembers the last failure."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.started_at: str | None = None
        self.last_error: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings; the server reads them from the environment."""
    if settings is None:
        settings = load_settings()
        configure_logging(settings.log_level)
    store = ResultsStore(settings.results_path)
    run_state = RunState()

    app = FastAPI(
        title="LPDG gateway visit ranker",
        version="1.0.0",
        description="Which 15 gateways the field team should visit each week, and why. See API.md.",
    )
    app.state.settings = settings
    app.state.run_state = run_state

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        log.info("request method=%s path=%s status=%d duration_ms=%.1f", request.method, request.url.path,
                 response.status_code, (time.perf_counter() - started) * 1000)
        return response

    def results_or_503() -> dict[str, Any]:
        try:
            results = store.get()
        except (OSError, ValueError) as error:
            raise HTTPException(503, f"results file is unreadable ({error}); call POST /run to rebuild it") from None
        if results is None:
            raise HTTPException(503, "no rankings yet: call POST /run to build them")
        return results

    def pick_week(results: dict[str, Any], week: str | None) -> str:
        available = list(results["weeks"])
        if week is None:
            return available[-1]
        try:
            key = parse_monday(week).date().isoformat()
        except ValueError as error:
            raise HTTPException(422, f"week: {error}") from None
        if key not in results["weeks"]:
            raise HTTPException(404, f"no ranking for week {key}; available weeks are {available[0]} to {available[-1]}")
        return key

    @app.get("/health")
    def health() -> JSONResponse:
        """200 when data, telemetry and rankings are all in place; 503 otherwise, with the failing check."""
        telemetry_dir = settings.data_dir / "telemetry"
        months_on_disk = sorted(
            p.name.removeprefix("month=") for p in telemetry_dir.glob("month=*") if any(p.glob("*.parquet"))
        ) if telemetry_dir.is_dir() else []
        try:
            results = store.get()
        except (OSError, ValueError):
            results = None
        checks = {"data_dir": settings.data_dir.is_dir(), "telemetry_files": bool(months_on_disk),
                  "results": results is not None}
        healthy = all(checks.values())
        body: dict[str, Any] = {"status": "ok" if healthy else "unhealthy", "checks": checks,
                                "run_in_progress": run_state.lock.locked(), "last_run_error": run_state.last_error}
        if results is not None:
            summary = results["summary"]
            body["last_run"] = {k: summary[k] for k in ["finished_at", "ranker", "latest_week", "duration_sec"]}
            body["stale"] = months_on_disk != summary["data"]["telemetry_months"]
        return JSONResponse(body, status_code=200 if healthy else 503)

    @app.get("/weeks")
    def weeks() -> dict[str, Any]:
        """Every week with a ranking. scored_weeks are the ones written to predictions.csv."""
        results = results_or_503()
        summary = results["summary"]
        return {"weeks": list(results["weeks"]), "scored_weeks": summary["scored_weeks"],
                "latest_week": summary["latest_week"]}

    @app.get("/rankings")
    def rankings(week: str | None = None) -> dict[str, Any]:
        """The 15 gateways to visit in a week (YYYY-MM-DD, a Monday), strongest first. Default: latest week."""
        results = results_or_503()
        key = pick_week(results, week)
        top = [g for g in results["weeks"][key] if g["rank"] is not None]
        return {
            "week_start": key,
            "ranker": results["summary"]["ranker"],
            "generated_at": results["summary"]["finished_at"],
            "gateways": [{k: g[k] for k in ["rank", "gateway_id", "score", "reason"]} for g in top],
        }

    @app.get("/gateways/{gateway_id}")
    def explain_gateway(gateway_id: str, week: str | None = None) -> dict[str, Any]:
        """Why a gateway is where it is in a week: rank or distance from the 15, score parts, reason."""
        try:
            gid = normalize_gateway_id(gateway_id)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        results = results_or_503()
        key = pick_week(results, week)
        entries = results["weeks"][key]
        entry = next((g for g in entries if g["gateway_id"] == gid), None)
        if entry is None:
            raise HTTPException(404, f"gateway {gid} is not in the gateway register or the telemetry")

        cutoff = min(g["score"] for g in entries if g["rank"] is not None)
        if entry["rank"] is not None:
            summary = f"Rank {entry['rank']} of 15 for week {key}."
        elif entry["eligible"]:
            eligible = sorted((g for g in entries if g["eligible"]), key=lambda g: (-g["score"], g["gateway_id"]))
            position = next(i for i, g in enumerate(eligible, start=1) if g["gateway_id"] == gid)
            summary = (f"Not in the 15 for week {key}: position {position} of {len(eligible)} eligible gateways, "
                       f"score {entry['score']} against {cutoff} for the 15th pick.")
        else:
            summary = f"Not eligible for week {key}; see reason."
        return {"gateway_id": gid, "week_start": key, "summary": summary, "rank": entry["rank"],
                "score": entry["score"], "cutoff_score": cutoff, "eligible": entry["eligible"],
                "reason": entry["reason"], "components": entry["components"],
                "ranker": results["summary"]["ranker"]}

    @app.post("/run")
    def run() -> Any:
        """Re-read the data folder and rebuild all rankings. 409 if a run is already going.

        Takes a few seconds on the full dataset. If it fails, the previous rankings keep being served.
        """
        if not run_state.lock.acquire(blocking=False):
            raise HTTPException(409, f"a run is already in progress (started {run_state.started_at}); retry when it finishes")
        run_state.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            summary = run_pipeline(settings)
        except DataError as error:
            return _run_failed(run_state, "data_error", str(error))
        except ValueError as error:
            return _run_failed(run_state, "config_error", str(error))
        except Exception as error:  # noqa: BLE001 - report, keep serving the old results
            log.exception("run failed unexpectedly")
            return _run_failed(run_state, "internal_error", f"{type(error).__name__}; see the server log")
        finally:
            run_state.lock.release()
        run_state.last_error = None
        return {"status": "ok", "ranker": summary["ranker"], "weeks_ranked": len(summary["weeks"]),
                "scored_weeks": summary["scored_weeks"], "latest_week": summary["latest_week"],
                "rows": summary["rows"], "duration_sec": summary["duration_sec"],
                "data_months": summary["data"]["telemetry_months"]}

    return app


def _run_failed(run_state: RunState, code: str, message: str) -> JSONResponse:
    run_state.last_error = f"{code}: {message}"
    log.error("run failed error=%s message=%s", code, message)
    return JSONResponse(status_code=500, content={
        "error": code, "detail": f"run failed; the previous rankings are still served. {message}"})
