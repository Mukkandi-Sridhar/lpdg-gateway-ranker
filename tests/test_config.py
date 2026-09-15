from pathlib import Path

import pandas as pd
import pytest

from gateway_ranker.config import load_settings, parse_monday


def test_defaults_give_the_eight_scored_mondays(monkeypatch):
    for var in ["DATA_DIR", "PREDICTIONS_PATH", "RANKER", "FIRST_WEEK", "N_WEEKS", "LOG_LEVEL"]:
        monkeypatch.delenv(var, raising=False)
    s = load_settings()
    assert s.data_dir == Path("data")
    assert [w.date().isoformat() for w in s.weeks] == [
        "2026-02-02", "2026-02-09", "2026-02-16", "2026-02-23",
        "2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23",
    ]


def test_env_is_read_and_overrides_win(monkeypatch):
    monkeypatch.setenv("DATA_DIR", "/env/data")
    monkeypatch.setenv("RANKER", "baseline")
    s = load_settings(data_dir="/flag/data")
    assert s.data_dir == Path("/flag/data")
    assert s.ranker == "baseline"


def test_parse_monday():
    assert parse_monday("2026-02-02") == pd.Timestamp("2026-02-02", tz="UTC")
    with pytest.raises(ValueError, match="not a Monday"):
        parse_monday("2026-02-03")
    with pytest.raises(ValueError, match="not a date"):
        parse_monday("02/02/2026x")


def test_bad_n_weeks_is_rejected(monkeypatch):
    monkeypatch.setenv("N_WEEKS", "eight")
    with pytest.raises(ValueError, match="N_WEEKS"):
        load_settings()
