# API reference

Base URL: `http://localhost:8000`. Interactive docs are at `/docs`.
All responses are JSON. Errors always carry a human-readable `detail`.

Gateway IDs are accepted in either format, `0A00000000FF` or `0A:00:00:00:00:FF`, in any
case. Responses always use 12 uppercase hex characters. IDs in the examples below are
placeholders.

Weeks are Mondays written as `YYYY-MM-DD`. A week's ranking uses only data from before
that Monday, 00:00 UTC.

## How the data flows

```
data/ (files on disk) ──POST /run──▶ ranker ──▶ output/results.json + predictions.csv
                                                     │
                            GET /rankings, /gateways, /weeks, /health read this file
```

- GET requests never touch the raw data, so they are fast and consistent.
- `POST /run` re-reads the data folder. A month dropped into `data/telemetry/` shows up
  after the next run, with no restart.
- The rankings cover the 8 scored weeks (2026-02-02 to 2026-03-23) plus every later Monday
  the telemetry fully covers. With the delivered data the latest week is 2026-03-30.

---

## GET /rankings

The 15 gateways to visit in a week, strongest evidence first.

| Query | Required | Default |
|---|---|---|
| `week` | no | latest ranked week |

```bash
curl "localhost:8000/rankings?week=2026-02-02"
```

```json
{
  "week_start": "2026-02-02",
  "ranker": "improved",
  "generated_at": "2026-09-15T06:33:45+00:00",
  "gateways": [
    {"rank": 1, "gateway_id": "0A00000000FF", "score": 47.32,
     "reason": "No data for 159 of the last 168 hours."},
    {"rank": 2, "gateway_id": "0A00000000EE", "score": 44.64,
     "reason": "No data for 98 of the last 168 hours; also 52 hours of unusually long offline time vs its own normal."}
  ]
}
```

`score` runs from 0 to 100 risk points (see DECISIONS.md §2). A reason starting with
`Low evidence – filling slot:` marks a pick made only because 15 are required.

| Status | When |
|---|---|
| 200 | OK |
| 404 | the week is a Monday but has no ranking; `detail` lists the available range |
| 422 | `week` is not a date, or not a Monday |
| 503 | no run has finished yet, or the results file is unreadable; call `POST /run` |

## GET /gateways/{gateway_id}

Why a gateway is where it is in a week: its rank or its distance from the 15, the parts of
its score, and the reason.

| Query | Required | Default |
|---|---|---|
| `week` | no | latest ranked week |

```bash
curl "localhost:8000/gateways/0a:00:00:00:00:ff?week=2026-02-02"
```

```json
{
  "gateway_id": "0A00000000FF",
  "week_start": "2026-02-02",
  "summary": "Rank 1 of 15 for week 2026-02-02.",
  "rank": 1,
  "score": 47.32,
  "cutoff_score": 31.55,
  "eligible": true,
  "reason": "No data for 159 of the last 168 hours.",
  "components": {
    "silence_points": 47.32, "anomaly_points": 0.0,
    "silent_hours": 159.0, "expected_hours": 168.0,
    "flagged_hours": 0.0, "flagged_disconnection_hours": 0.0,
    "flagged_offline_hours": 0.0, "flagged_reboot_hours": 0.0
  },
  "ranker": "improved"
}
```

For a gateway outside the 15, `rank` is `null` and `summary` says how far off it is, e.g.
`"Not in the 15 for week 2026-02-02: position 42 of 290 eligible gateways, score 9.2 against 31.55 for the 15th pick."`

A gateway can be **not eligible**, and then `reason` says why:
- decommissioned on or before that Monday
- installed after that Monday
- already picked in an earlier week with no healthy week since (the same fault, so another visit would be wasted)

The contents of `components` depend on the ranker. `RANKER=baseline` returns breach counts.

| Status | When |
|---|---|
| 200 | OK |
| 404 | the ID is well-formed but not in the gateway register or the telemetry; or the week has no ranking |
| 422 | the ID is not 12 hex characters (colons optional); or `week` is not a Monday date |
| 503 | no rankings yet; call `POST /run` |

## POST /run

Re-reads the data folder, ranks every week again, and replaces `predictions.csv` and
`output/results.json`.

```bash
curl -X POST localhost:8000/run
```

```json
{
  "status": "ok",
  "ranker": "improved",
  "weeks_ranked": 9,
  "scored_weeks": ["2026-02-02", "…", "2026-03-23"],
  "latest_week": "2026-03-30",
  "rows": 120,
  "duration_sec": 3.8,
  "data_months": ["2025-08", "…", "2026-03"]
}
```

Behaviour worth knowing:
- **Synchronous.** It takes about 4 seconds on the full dataset, and the call returns when the run is done.
  GET requests keep being answered while it runs.
- **One run at a time.** A call while a run is in progress gets `409` straight away.
- **All or nothing.** Outputs are written to temporary files and renamed into place only
  after every week is ranked. A failed run leaves the previous rankings being served, and
  `GET /health` shows the error in `last_run_error`.
- **Refuses bad data** rather than ranking it. For example: an empty or column-less month file,
  malformed IDs or dates, or telemetry that does not reach the last scored week.

| Status | `error` | When |
|---|---|---|
| 200 | | OK |
| 409 | | a run is already in progress |
| 500 | `data_error` | the data folder has a problem; `detail` names the file and the problem |
| 500 | `config_error` | a setting is invalid, e.g. an unknown `RANKER` |
| 500 | `internal_error` | anything unexpected; details are in the server log |

## GET /weeks

```bash
curl localhost:8000/weeks
```

```json
{
  "weeks": ["2026-02-02", "…", "2026-03-30"],
  "scored_weeks": ["2026-02-02", "…", "2026-03-23"],
  "latest_week": "2026-03-30"
}
```

`scored_weeks` are the weeks written to `predictions.csv`. Returns 503 before the first run.

## GET /health

The status is 200 only if the data folder exists, it contains telemetry files, and a readable
set of rankings exists. Otherwise it is 503, and `checks` shows which part failed.

```bash
curl localhost:8000/health
```

```json
{
  "status": "ok",
  "checks": {"data_dir": true, "telemetry_files": true, "results": true},
  "run_in_progress": false,
  "last_run_error": null,
  "last_run": {"finished_at": "2026-09-15T06:33:45+00:00", "ranker": "improved",
               "latest_week": "2026-03-30", "duration_sec": 3.8},
  "stale": false
}
```

`stale: true` means the telemetry months on disk differ from the ones the last run used.
Call `POST /run`.

## Logs

The service writes one line per request and one per ranked week. For example:

```
INFO api request method=GET path=/rankings status=200 duration_ms=1.4
INFO gateway_ranker.pipeline ranked week=2026-02-02 scored=True candidates=332 eligible=290 top_score=47.32 low_evidence_picks=0
INFO gateway_ranker.pipeline run finished ranker=improved weeks_ranked=9 rows=120 latest_week=2026-03-30 duration_sec=3.82
```
