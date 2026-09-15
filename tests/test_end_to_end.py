"""The whole path: data files on disk -> CLI -> predictions.csv -> official validator."""
import subprocess
import sys
from pathlib import Path

import pandas as pd

from gateway_ranker.config import load_settings
from gateway_ranker.pipeline import run_pipeline
from tests.fixtures import make_master, make_meter_reads, make_telemetry, silence, write_data_dir
from validate_submission import validate

REPO_ROOT = Path(__file__).resolve().parents[1]
GATEWAYS = [f"0B00000000{i:02d}" for i in range(20)]
BROKEN = GATEWAYS[7]


def _data_dir(root: Path) -> Path:
    tel = make_telemetry(GATEWAYS, start="2025-12-29", end="2026-03-30")
    tel = silence(tel, BROKEN, "2026-02-10", "2026-02-20")
    return write_data_dir(root / "data", tel, master=make_master(GATEWAYS), meter_reads=make_meter_reads(GATEWAYS))


def test_cli_writes_predictions_that_pass_the_official_validator(tmp_path):
    data = _data_dir(tmp_path)
    out = tmp_path / "predictions.csv"
    proc = subprocess.run(
        [sys.executable, "-m", "gateway_ranker.cli", "predict", "--data", str(data), "--out", str(out),
         "--results", str(tmp_path / "results.json")],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert validate(out) == []

    predictions = pd.read_csv(out)
    week = predictions[predictions["week_start"] == "2026-02-16"]
    assert week.iloc[0]["gateway_id"] == BROKEN            # silent 144 of 168 hours: ranked first
    assert BROKEN not in predictions[predictions["week_start"] == "2026-02-23"]["gateway_id"].tolist()


def test_cli_reports_bad_data_folder_with_exit_code_2(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "gateway_ranker.cli", "predict", "--data", str(tmp_path / "nope"),
         "--out", str(tmp_path / "p.csv"), "--results", str(tmp_path / "r.json")],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 2
    assert "data folder not found" in proc.stderr


def test_same_input_gives_byte_identical_predictions(tmp_path):
    data = _data_dir(tmp_path)
    outputs = []
    for i in range(2):
        settings = load_settings(data_dir=data, predictions_path=tmp_path / f"p{i}.csv",
                                 results_path=tmp_path / f"r{i}.json")
        run_pipeline(settings)
        outputs.append((tmp_path / f"p{i}.csv").read_bytes())
    assert outputs[0] == outputs[1]
    # Regression: atomic writes via mkstemp left the outputs readable by their owner only (0600).
    assert (tmp_path / "p0.csv").stat().st_mode & 0o777 == 0o644
