#!/usr/bin/env sh
# One command: build, rank every week, validate predictions, serve the API on :8000.
#   ./run.sh                          uses ./data
#   ./run.sh --data /somewhere/else   uses another data folder
set -e
while [ $# -gt 0 ]; do
  case "$1" in
    --data) DATA_DIR="$2"; shift 2 ;;
    --data=*) DATA_DIR="${1#*=}"; shift ;;
    *) echo "usage: ./run.sh [--data PATH]" >&2; exit 2 ;;
  esac
done
DATA_DIR="${DATA_DIR:-./data}"
if [ ! -d "$DATA_DIR/telemetry" ]; then
  echo "error: no telemetry folder in $DATA_DIR (expected $DATA_DIR/telemetry/month=YYYY-MM/)" >&2
  exit 2
fi
export DATA_DIR
cd "$(dirname "$0")"
exec docker compose up --build
