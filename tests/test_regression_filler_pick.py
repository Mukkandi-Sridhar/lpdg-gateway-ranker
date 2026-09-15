"""Regression: a low-evidence filler pick must not block a real fault that starts later.

Found by tests/test_end_to_end.py. With only 20 gateways, a healthy gateway was picked as
filler for week 2026-02-09 and then went silent. still_in_episode() only looked at weeks
after the pick, saw the silence, and treated it as the fault already visited, so the real
fault was never picked. Fix: the week that led to the pick is checked too.
"""
import pandas as pd

from gateway_ranker.loading import load_dataset
from gateway_ranker.rankers.improved import ImprovedRanker
from tests.fixtures import GATEWAYS, make_telemetry, silence, write_data_dir

W1 = pd.Timestamp("2026-02-02", tz="UTC")
W2 = pd.Timestamp("2026-02-09", tz="UTC")
GW1 = GATEWAYS[0]


def test_filler_pick_does_not_suppress_a_fault_that_starts_the_next_week(tmp_path):
    tel = silence(make_telemetry(end="2026-02-09"), GW1, "2026-02-02", "2026-02-09")  # healthy before W1, dark after
    data = load_dataset(write_data_dir(tmp_path, tel))

    scores = {s.gateway_id: s for s in ImprovedRanker().score_week(data.before(W2), W2, {W1: [GW1]})}

    assert scores[GW1].score >= 50
    assert scores[GW1].eligible, scores[GW1].reason
