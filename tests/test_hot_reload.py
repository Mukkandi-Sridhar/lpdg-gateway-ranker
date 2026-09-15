"""A month dropped into the data folder is picked up by POST /run without a restart.

This is exactly what the live session does (FAQ round 2, 6.5 and 7.1).
"""
from fastapi.testclient import TestClient

from api.main import create_app
from gateway_ranker.config import load_settings
from tests.fixtures import make_master, make_telemetry, silence, write_data_dir
from validate_submission import validate

GATEWAYS = [f"0F00000000{i:02d}" for i in range(20)]
NEW_FAULT = GATEWAYS[2]


def test_new_month_is_picked_up_by_run_without_restarting(tmp_path):
    data = write_data_dir(tmp_path / "data", make_telemetry(GATEWAYS, start="2025-12-29", end="2026-04-01"),
                          master=make_master(GATEWAYS))
    settings = load_settings(data_dir=data, predictions_path=tmp_path / "predictions.csv",
                             results_path=tmp_path / "results.json", first_week="2026-02-02", n_weeks="8")
    client = TestClient(create_app(settings))
    assert client.post("/run").status_code == 200
    assert client.get("/rankings").json()["week_start"] == "2026-03-30"

    april = make_telemetry(GATEWAYS, start="2026-04-01", end="2026-05-01", seed=1)
    write_data_dir(data, silence(april, NEW_FAULT, "2026-04-21", "2026-04-27"), master=make_master(GATEWAYS))
    assert client.get("/health").json()["stale"] is True

    run = client.post("/run").json()
    assert run["data_months"][-1] == "2026-04"
    latest = client.get("/rankings").json()
    assert latest["week_start"] == "2026-04-27"
    assert latest["gateways"][0]["gateway_id"] == NEW_FAULT
    assert client.get("/health").json()["stale"] is False
    assert validate(tmp_path / "predictions.csv") == []  # the hand-in file still holds the 8 scored weeks
