# LPDG gateway visit ranker

This ranks the 15 gateways the field team should visit each week, with a plain-words
reason for each, and serves the result through a REST API.

**Part 2 area: B — Software development.**

📹 **Recording (7 min):** TODO: add the unlisted link. It shows the API, a new month picked up by
`POST /run` without a restart, and the week of 2026-02-02 compared with the baseline.

| Document | What is in it |
|---|---|
| [DECISIONS.md](DECISIONS.md) | Five choices, the alternatives, and why; what the score means |
| [LIMITATIONS.md](LIMITATIONS.md) | What it cannot do, and what two more weeks would fix |
| [API.md](API.md) | Every endpoint, with curl examples and error codes |
| [AI-USAGE.md](AI-USAGE.md) | What AI tools were used for, and what they got wrong |

## Quick start

Put LPDG's `data` folder at `./data`. It is not in this repository. Then use one of these.

**With Docker** (nothing else needed):

```bash
docker compose up --build
```

The first build takes about 1.5 minutes. The container then:
1. ranks every week (about 20 seconds)
2. checks `output/predictions.csv` with LPDG's `validate_submission.py` (look for `OK` in the log)
3. serves the API on http://localhost:8000

To use another data folder, run `DATA_DIR=/path/to/data docker compose up --build`. To use another port, add `PORT=9000`.

**Without Docker** (Python 3.11 or newer, macOS or Linux):

```bash
make install
make run
```

`make run` ranks all weeks, validates `predictions.csv`, and starts the API on port 8000.
The same steps without make:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m gateway_ranker.cli predict --data /path/to/data
.venv/bin/python validate_submission.py predictions.csv
DATA_DIR=/path/to/data .venv/bin/python -m uvicorn api.main:create_app --factory --port 8000
```

## Using the API

```bash
curl localhost:8000/rankings                                  # this week's 15 (latest week the data covers)
curl "localhost:8000/rankings?week=2026-02-02"                # a specific week
curl "localhost:8000/gateways/0A:00:00:00:00:FF?week=2026-02-02"  # why this gateway is where it is
curl -X POST localhost:8000/run                               # re-read ./data and rebuild everything
curl localhost:8000/health
```

New data arrives as files: drop a `month=YYYY-MM/` folder into `data/telemetry/` and call
`POST /run`. No restart is needed. Interactive docs are at http://localhost:8000/docs.
The full reference is in [API.md](API.md).

## What it produces

- `predictions.csv`: the hand-in file. It holds 15 gateways for each of the 8 scored weeks
  (2026-02-02 to 2026-03-23), 120 rows. The copy committed here was produced by `make predict`
  and is byte-identical to what Docker writes to `output/predictions.csv`.
- `output/results.json`: every gateway's score, score parts and reason for every ranked week.
  It also covers weeks after the scored window when the data reaches them. The API serves this file.

## Settings

Everything comes from environment variables. CLI flags override them.

| Variable | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `data` | Data folder (`--data`) |
| `PREDICTIONS_PATH` | `predictions.csv` | Output CSV (`--out`) |
| `RESULTS_PATH` | `output/results.json` | Output served by the API (`--results`) |
| `RANKER` | `improved` | `improved` or `baseline` (`--ranker`) |
| `FIRST_WEEK` / `N_WEEKS` | `2026-02-02` / `8` | The weeks written to the CSV |
| `LOG_LEVEL` | `INFO` | Logging level |

`RANKER=baseline` serves a faithful port of LPDG's `baseline_3sigma.py` through the same API,
with no code changes.

## Tests

```bash
make test
```

This runs 61 tests in about 20 seconds. They use small synthetic data built in
`tests/fixtures.py` and never real dataset rows, so they run without `./data`. The one
exception checks the baseline port against LPDG's script on the real data, and it skips
cleanly when `./data` is absent.

| Test file | What it proves |
|---|---|
| `test_end_to_end.py` | Files on disk → CLI → `predictions.csv` → LPDG's validator; the same input gives byte-identical output |
| `test_api.py` | Every endpoint, including bad input (422), unknown week or gateway (404), a second `/run` (409), a failed run that keeps serving old results, and swapping the ranker |
| `test_hot_reload.py` | A new month dropped into the data folder is picked up by `POST /run` without a restart |
| `test_regression_filler_pick.py` | A bug we found: a low-evidence pick blocked a real fault the following week |
| `test_regression_silent_gateway.py` | The baseline's blind spot: a silent gateway cannot be picked |
| `test_baseline_port.py` | The ported baseline gives the official script's numbers exactly |
| `test_loading.py`, `test_improved_ranker.py`, `test_rankers.py`, `test_config.py` | Unit tests |

## Run times

Measured on an Apple-silicon laptop:

| What | Time |
|---|---|
| `predict` (all weeks, full dataset) | about 4 s; about 20 s in Docker on the same machine |
| `POST /run` | about 4 s. It is synchronous; a second call during a run gets 409 |
| Any GET | under 30 ms. It reads the materialised results, not the raw data |

## Layout

```
gateway_ranker/
  config.py        settings from environment variables
  loading.py       read files, normalise IDs, drop duplicates, one cutoff rule for every file
  checks.py        stop with a clear error when input is wrong
  rankers/
    base.py        the Ranker interface and deterministic top-15 selection
    improved.py    silence + anomaly ranker (the default)
    baseline.py    port of baseline_3sigma.py
  pipeline.py      rank every week, write outputs atomically
  cli.py           python -m gateway_ranker.cli predict
api/main.py        FastAPI app
scripts/           explore_data.py (data findings), compare_to_baseline.py
tests/             unit, API, end-to-end and regression tests
baseline_3sigma.py, validate_submission.py   LPDG's scripts, unchanged
```

To add a ranker, write a class with `score_week()` in `gateway_ranker/rankers/`, add
it to `RANKERS` in `gateway_ranker/rankers/__init__.py`, and set `RANKER=<name>`.
Nothing in `api/` changes.
