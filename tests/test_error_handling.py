"""Regression tests from the code review: broken inputs and bad settings are reported clearly.

Each test is the smallest input that reproduced a finding:
- a half-copied parquet month, a non-Excel review file and a malformed CSV used to escape as raw
  pyarrow/pandas errors, with no file named, reported by POST /run as config_error
- a week with a UTC offset (Monday 05:00 UTC) was accepted as a Monday, moving the data cutoff
- a week where every gateway went silent ranked the 15 by gateway_id without any warning
"""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from gateway_ranker import cli
from gateway_ranker.checks import DataError
from gateway_ranker.config import ConfigError, load_settings, parse_monday
from gateway_ranker.loading import load_dataset
from gateway_ranker.pipeline import run_pipeline
from tests.fixtures import make_master, make_telemetry, silence, write_data_dir

GATEWAYS = [f"0C10000000{i:02d}" for i in range(20)]


def _data(root, telemetry=None):
    tel = telemetry if telemetry is not None else make_telemetry(GATEWAYS, start="2025-12-29", end="2026-04-01")
    return write_data_dir(root / "data", tel, master=make_master(GATEWAYS))


def _settings(root, **overrides):
    return load_settings(data_dir=root / "data", predictions_path=root / "p.csv", results_path=root / "r.json",
                         first_week="2026-02-02", n_weeks="8", **overrides)


def _half_copied_month(data):
    good = data / "telemetry" / "month=2026-03" / "part-0.parquet"
    folder = data / "telemetry" / "month=2026-04"
    folder.mkdir()
    (folder / "part-0.parquet").write_bytes(good.read_bytes()[: good.stat().st_size // 2])


def test_half_copied_parquet_names_the_file(tmp_path):
    _half_copied_month(_data(tmp_path))
    with pytest.raises(DataError, match=r"month=2026-04/part-0\.parquet: cannot be read as parquet"):
        load_dataset(tmp_path / "data")


def test_unreadable_review_file_names_the_file(tmp_path):
    (_data(tmp_path) / "engineer_review_2026-02.xlsx").write_text("not an Excel file")
    with pytest.raises(DataError, match=r"engineer_review_2026-02\.xlsx: cannot be read as Excel"):
        load_dataset(tmp_path / "data")


def test_malformed_csv_names_the_file(tmp_path):
    data = _data(tmp_path)
    (data / "field_visits.csv").write_text('visit_id,gateway_id\n"V1,unterminated\n')
    with pytest.raises(DataError, match=r"field_visits\.csv: cannot be read as CSV"):
        load_dataset(data)


def test_run_reports_data_problems_and_bad_settings_with_the_right_error_code(tmp_path):
    data = _data(tmp_path)
    _half_copied_month(data)
    broken_data = TestClient(create_app(_settings(tmp_path))).post("/run")
    assert broken_data.status_code == 500
    assert broken_data.json()["error"] == "data_error"
    assert "month=2026-04" in broken_data.json()["detail"]

    bad_setting = TestClient(create_app(_settings(tmp_path, ranker="magic"))).post("/run")
    assert bad_setting.status_code == 500 and bad_setting.json()["error"] == "config_error"


@pytest.mark.parametrize("value", ["2026-02-02T00:00:00-05:00", "2026-02-02T00:00:00+01:00"])
def test_week_with_a_utc_offset_is_refused(value):
    with pytest.raises(ValueError, match="not in UTC"):
        parse_monday(value)


def test_explicit_utc_is_accepted():
    assert parse_monday("2026-02-02T00:00:00Z") == pd.Timestamp("2026-02-02", tz="UTC")


def test_bad_first_week_setting_is_a_config_error():
    with pytest.raises(ConfigError, match="FIRST_WEEK"):
        load_settings(first_week="2026-02-03")


def test_fleet_wide_silence_is_reported_as_a_warning(tmp_path):
    tel = make_telemetry(GATEWAYS, start="2025-12-29", end="2026-04-01")
    for gateway_id in GATEWAYS:
        tel = silence(tel, gateway_id, "2026-02-02", "2026-02-09")
    _data(tmp_path, tel)

    summary = run_pipeline(_settings(tmp_path))

    assert len(summary["warnings"]) == 1
    assert summary["warnings"][0].startswith("week 2026-02-09: 100% of 20 reporting gateways")


def test_cli_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "configure_logging", lambda level: None)  # keep pytest's log capture intact
    _data(tmp_path)
    args = ["predict", "--data", str(tmp_path / "data"), "--out", str(tmp_path / "p.csv"),
            "--results", str(tmp_path / "r.json")]

    assert cli.main(args) == 0
    assert "wrote" in capsys.readouterr().out

    assert cli.main([*args, "--ranker", "magic"]) == 2
    assert "unknown ranker 'magic'" in capsys.readouterr().err
