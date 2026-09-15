import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from gateway_ranker.config import load_settings
from tests.fixtures import colon_id, make_master, make_telemetry, silence, write_data_dir

GATEWAYS = [f"0E00000000{i:02d}" for i in range(20)]
DARK = GATEWAYS[5]  # silent for 144 of the 168 hours before 2026-02-09


def build_data(root):
    tel = silence(make_telemetry(GATEWAYS, start="2025-12-29", end="2026-04-01"), DARK, "2026-02-03", "2026-02-09")
    return write_data_dir(root / "data", tel, master=make_master(GATEWAYS))


def new_client(root, data_dir=None, ranker="improved"):
    settings = load_settings(data_dir=data_dir or root / "data", predictions_path=root / "predictions.csv",
                             results_path=root / "out" / "results.json", ranker=ranker,
                             first_week="2026-02-02", n_weeks="8")
    return TestClient(create_app(settings))


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("api")
    build_data(root)
    client = new_client(root)
    assert client.post("/run").status_code == 200
    return client


def test_health_and_rankings_are_503_before_the_first_run(tmp_path):
    build_data(tmp_path)
    client = new_client(tmp_path)
    health = client.get("/health")
    assert health.status_code == 503
    assert health.json()["checks"] == {"data_dir": True, "telemetry_files": True, "results": False}
    assert "POST /run" in client.get("/rankings").json()["detail"]


def test_results_file_from_an_older_version_is_reported_not_crashed_on(tmp_path):
    build_data(tmp_path)
    client = new_client(tmp_path)
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "results.json").write_text('{"summary": {"ranker": "improved"}, "weeks": {}}')
    assert client.get("/health").status_code == 503
    rankings = client.get("/rankings")
    assert rankings.status_code == 503 and "unexpected shape" in rankings.json()["detail"]
    assert client.post("/run").status_code == 200  # a run repairs it
    assert client.get("/health").status_code == 200


def test_health_notices_a_missing_data_folder(tmp_path):
    client = new_client(tmp_path, data_dir=tmp_path / "nowhere")
    assert client.get("/health").status_code == 503
    assert client.get("/health").json()["checks"]["data_dir"] is False


def test_health_is_ok_after_a_run(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["stale"] is False and body["last_run"]["ranker"] == "improved"


def test_weeks_lists_scored_weeks_and_the_latest_covered_week(client):
    body = client.get("/weeks").json()
    assert body["scored_weeks"][0] == "2026-02-02" and len(body["scored_weeks"]) == 8
    assert body["latest_week"] == "2026-03-30" == body["weeks"][-1]


def test_rankings_default_to_the_latest_week(client):
    body = client.get("/rankings").json()
    assert body["week_start"] == "2026-03-30"
    assert [g["rank"] for g in body["gateways"]] == list(range(1, 16))


def test_rankings_for_a_week_put_the_silent_gateway_first(client):
    top = client.get("/rankings", params={"week": "2026-02-09"}).json()["gateways"][0]
    assert top["gateway_id"] == DARK
    assert top["reason"].startswith("No data for 144 of the last 168 hours")


@pytest.mark.parametrize("week, status, message", [
    ("2026-02-10", 422, "not a Monday"),
    ("banana", 422, "not a date"),
    ("2025-01-06", 404, "available weeks are 2026-02-02 to 2026-03-30"),
])
def test_bad_or_unknown_weeks_are_rejected_clearly(client, week, status, message):
    response = client.get("/rankings", params={"week": week})
    assert response.status_code == status
    assert message in response.json()["detail"]


def test_gateway_explanation_accepts_both_id_formats(client):
    plain = client.get(f"/gateways/{DARK}", params={"week": "2026-02-09"}).json()
    colon = client.get(f"/gateways/{colon_id(DARK).lower()}", params={"week": "2026-02-09"}).json()
    assert plain == colon
    assert plain["rank"] == 1 and plain["summary"].startswith("Rank 1 of 15")
    assert plain["components"]["silent_hours"] == 144


def test_gateway_outside_the_15_says_how_far_off_it_is(client):
    top = {g["gateway_id"] for g in client.get("/rankings", params={"week": "2026-02-09"}).json()["gateways"]}
    outsider = next(g for g in GATEWAYS if g not in top)
    body = client.get(f"/gateways/{outsider}", params={"week": "2026-02-09"}).json()
    assert body["rank"] is None
    assert "position" in body["summary"] and "15th pick" in body["summary"]
    assert body["score"] <= body["cutoff_score"]


def test_unknown_gateway_is_404_and_malformed_id_is_422(client):
    unknown = client.get("/gateways/0F0000000000")
    assert unknown.status_code == 404 and "0F0000000000" in unknown.json()["detail"]
    malformed = client.get("/gateways/not-a-gateway")
    assert malformed.status_code == 422 and "12 hex" in malformed.json()["detail"]


def test_a_second_run_while_one_is_running_gets_409(tmp_path):
    build_data(tmp_path)
    client = new_client(tmp_path)
    lock = client.app.state.run_state.lock
    lock.acquire()
    try:
        response = client.post("/run")
    finally:
        lock.release()
    assert response.status_code == 409 and "already in progress" in response.json()["detail"]


def test_a_failed_run_keeps_serving_the_previous_rankings(tmp_path):
    data = build_data(tmp_path)
    client = new_client(tmp_path)
    assert client.post("/run").status_code == 200
    before = client.get("/rankings").json()

    broken = data / "telemetry" / "month=2026-04"
    broken.mkdir()
    make_telemetry(GATEWAYS, start="2026-04-01", end="2026-04-02").head(0).to_parquet(broken / "part-0.parquet")
    response = client.post("/run")

    assert response.status_code == 500
    assert response.json()["error"] == "data_error" and "no rows" in response.json()["detail"]
    assert client.get("/rankings").json() == before
    assert "no rows" in client.get("/health").json()["last_run_error"]


def test_ranker_is_swapped_by_settings_without_touching_the_api(tmp_path):
    build_data(tmp_path)
    client = new_client(tmp_path, ranker="baseline")
    assert client.post("/run").json()["ranker"] == "baseline"
    body = client.get("/rankings", params={"week": "2026-02-09"}).json()
    assert body["ranker"] == "baseline"
    assert DARK not in [g["gateway_id"] for g in body["gateways"]]  # the baseline cannot see silence
