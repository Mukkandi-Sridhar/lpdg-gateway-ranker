"""Regression: silence is invisible to baseline_3sigma.py.

The baseline only scores telemetry rows that exist. A gateway dark for the whole week has
no rows, so it cannot be picked at all. A gateway dark for most of the week is scored only
on the few hours it did report. In the delivered data, no in-service gateway went fully
dark in a scored week, but 14-17 a week missed at least 84 of 168 hours. This test uses
the fully dark case because it is the smallest deterministic input that shows the blind spot.
"""
import pandas as pd

from gateway_ranker.loading import load_dataset
from gateway_ranker.rankers.base import select_top
from gateway_ranker.rankers.baseline import BaselineRanker
from gateway_ranker.rankers.improved import ImprovedRanker
from tests.fixtures import make_master, make_telemetry, silence, write_data_dir

W1 = pd.Timestamp("2026-02-02", tz="UTC")
GATEWAYS = [f"0C00000000{i:02d}" for i in range(20)]
DARK = GATEWAYS[3]


def _top15(tmp_path, ranker):
    tel = silence(make_telemetry(GATEWAYS, end="2026-02-02"), DARK, "2026-01-26", "2026-02-02")
    data = load_dataset(write_data_dir(tmp_path, tel, master=make_master(GATEWAYS)))
    return select_top(ranker.score_week(data.before(W1), W1, {}))


def test_baseline_cannot_pick_a_silent_gateway(tmp_path):
    assert DARK not in [r.gateway_id for r in _top15(tmp_path, BaselineRanker())]


def test_improved_ranker_puts_the_silent_gateway_first(tmp_path):
    top = _top15(tmp_path, ImprovedRanker())
    assert top[0].gateway_id == DARK
    assert top[0].reason.startswith("No data for 168 of the last 168 hours")
