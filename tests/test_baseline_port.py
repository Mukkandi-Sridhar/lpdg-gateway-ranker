"""The port in gateway_ranker/rankers/baseline.py must give the official script's numbers.

Both are fed the same de-duplicated telemetry, and every gateway's breach count and
reason must match exactly.
"""
from pathlib import Path

import pandas as pd
import pytest

import baseline_3sigma as official
from gateway_ranker.config import parse_monday, scored_weeks
from gateway_ranker.loading import Dataset, load_dataset
from gateway_ranker.rankers.baseline import BaselineRanker
from tests.fixtures import make_master, make_telemetry, silence, spike, write_data_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
W1 = pd.Timestamp("2026-02-02", tz="UTC")
GATEWAYS = [f"0D00000000{i:02d}" for i in range(20)]


def assert_port_matches_official(data: Dataset, monday: pd.Timestamp) -> None:
    ours = {s.gateway_id: s for s in BaselineRanker().score_week(data.before(monday), monday, {})}
    theirs = official.rank_week(data.telemetry, monday.date()).set_index("gateway_id")

    assert {g for g, s in ours.items() if s.eligible} == set(theirs.index)
    for gateway_id, row in theirs.iterrows():
        metric = row.worst_metric or "no metric over 3 sigma"
        assert ours[gateway_id].score == row.flagged_hours, gateway_id
        assert ours[gateway_id].reason == (
            f"{row.flagged_hours} hour(s) beyond 3 sigma of this gateway's own 28-day baseline "
            f"in the last 7 days; first breach on {metric}"
        )


def test_port_matches_official_on_synthetic_data(tmp_path):
    tel = make_telemetry(GATEWAYS, start="2026-01-01", end="2026-02-02")
    tel = spike(tel, GATEWAYS[1], "2026-01-30", "2026-01-30 06:00", "reboot_cnt", 4)
    tel = spike(tel, GATEWAYS[2], "2026-01-29", "2026-02-02", "disconnection_cnt", 6)
    tel = spike(tel, GATEWAYS[4], "2026-01-01", "2026-02-02", "reboot_cnt", 0)  # zero spread: cannot breach
    tel = silence(tel, GATEWAYS[3], "2026-01-26", "2026-02-02")                  # dark: not scored at all
    data = load_dataset(write_data_dir(tmp_path, tel, master=make_master(GATEWAYS)))
    assert_port_matches_official(data, W1)


@pytest.mark.skipif(not (REPO_ROOT / "data" / "telemetry").is_dir(), reason="full dataset not in ./data")
def test_port_matches_official_on_the_real_data_for_all_weeks():
    data = load_dataset(REPO_ROOT / "data")
    for monday in scored_weeks(parse_monday("2026-02-02"), 8):
        assert_port_matches_official(data, monday)
