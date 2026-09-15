"""Command line entry point.

    python -m gateway_ranker.cli predict [--data PATH] [--out PATH] [--ranker NAME]

Flags override environment variables (see gateway_ranker/config.py).
Exit codes: 0 success, 2 bad input or bad data.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from gateway_ranker.checks import DataError
from gateway_ranker.config import configure_logging, load_settings
from gateway_ranker.pipeline import run_pipeline

log = logging.getLogger("gateway_ranker.cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gateway_ranker.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    predict = commands.add_parser("predict", help="rank every scored week and write predictions.csv")
    predict.add_argument("--data", help="data folder (default: $DATA_DIR or ./data)")
    predict.add_argument("--out", help="predictions CSV path (default: $PREDICTIONS_PATH or predictions.csv)")
    predict.add_argument("--results", help="results JSON path (default: $RESULTS_PATH or output/results.json)")
    predict.add_argument("--ranker", help="ranker name (default: $RANKER or improved)")
    predict.add_argument("--first-week", help="first Monday to predict, YYYY-MM-DD (default: 2026-02-02)")
    predict.add_argument("--weeks", help="number of weeks to predict (default: 8)")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(data_dir=args.data, predictions_path=args.out, results_path=args.results,
                                 ranker=args.ranker, first_week=args.first_week, n_weeks=args.weeks)
        configure_logging(settings.log_level)
        summary = run_pipeline(settings)
    except (DataError, ValueError) as error:
        log.error("run failed: %s", error)
        print(f"error: {error}", file=sys.stderr)
        return 2
    shown = ["ranker", "scored_weeks", "latest_week", "rows", "duration_sec", "warnings"]
    print(json.dumps({k: summary[k] for k in shown}, indent=1))
    print(f"wrote {settings.predictions_path} and {settings.results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
