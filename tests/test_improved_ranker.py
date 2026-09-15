import pandas as pd
import pytest

from gateway_ranker.loading import load_dataset
from gateway_ranker.rankers.improved import ImprovedRanker
from tests.fixtures import GATEWAYS, make_master, make_telemetry, silence, spike, write_data_dir

W1 = pd.Timestamp("2026-02-02", tz="UTC")
GW1, GW2, GW3, GW4, GW5, GW6 = GATEWAYS


def _score(tmp_path, telemetry, monday=W1, previous=None, master=None):
    data = load_dataset(write_data_dir(tmp_path, telemetry, master=master))
    scores = ImprovedRanker().score_week(data.before(monday), monday, previous or {})
    return {s.gateway_id: s for s in scores}


def test_silent_gateway_gets_silence_points_and_a_plain_reason(tmp_path):
    tel = silence(make_telemetry(end="2026-02-02"), GW1, "2026-01-29", "2026-02-02")
    s = _score(tmp_path, tel)[GW1]
    assert s.components["silent_hours"] == 96
    assert s.components["silence_points"] == pytest.approx(50 * 96 / 168, abs=0.01)
    assert s.reason.startswith("No data for 96 of the last 168 hours")


def test_fault_filling_the_whole_week_is_not_hidden_by_its_own_normal(tmp_path):
    tel = spike(make_telemetry(end="2026-02-02"), GW2, "2026-01-26", "2026-02-02", "reboot_cnt", 5)
    s = _score(tmp_path, tel)[GW2]
    assert s.components["flagged_reboot_hours"] == 168
    assert s.score >= 50
    assert "unusual reboots" in s.reason


def test_no_silence_counted_before_install_date(tmp_path):
    tel = silence(make_telemetry(end="2026-02-02"), GW3, "2026-01-01", "2026-01-30")
    master = make_master(installed_on={GW3: "2026-01-30"})
    s = _score(tmp_path, tel, master=master)[GW3]
    assert s.components["expected_hours"] == 72
    assert s.components["silent_hours"] == 0
    assert s.eligible


def test_decommissioned_and_future_gateways_are_not_eligible(tmp_path):
    tel = silence(make_telemetry(end="2026-02-02"), GW4, "2026-01-20", "2026-02-02")
    tel = silence(tel, GW5, "2026-01-01", "2026-02-02")
    master = make_master(decommissioned_on={GW4: "2026-01-20"}, installed_on={GW5: "2026-03-01"})
    scores = _score(tmp_path, tel, master=master)
    assert not scores[GW4].eligible and "decommissioned on 2026-01-20" in scores[GW4].reason
    assert not scores[GW5].eligible and "installed on 2026-03-01" in scores[GW5].reason


def test_gateway_that_never_reported_is_not_counted_silent(tmp_path):
    tel = silence(make_telemetry(end="2026-02-02"), GW6, "2026-01-01", "2026-02-02")
    s = _score(tmp_path, tel)[GW6]
    assert s.components["silent_hours"] == 0
    assert "never reported" in s.reason


def test_weak_evidence_is_labelled(tmp_path):
    tel = silence(make_telemetry(end="2026-02-02"), GW1, "2026-02-01", "2026-02-01 05:00")
    s = _score(tmp_path, tel)[GW1]
    assert s.score < 10
    # Random fixture noise also flags a few hours, so only the prefix and the silence wording are fixed.
    assert s.reason.startswith("Low evidence – filling slot: ")
    assert "no data for 5 of the last 168 hours" in s.reason


def test_same_fault_episode_is_not_picked_twice_but_a_new_one_is(tmp_path):
    tel = make_telemetry(end="2026-02-23")
    tel = silence(tel, GW1, "2026-01-29", "2026-02-09")   # episode 1: silent before W1 and during W1
    tel = silence(tel, GW1, "2026-02-17", "2026-02-23")   # healthy week 02-09..02-16, then episode 2
    data = load_dataset(write_data_dir(tmp_path, tel))
    ranker = ImprovedRanker()
    picked_w1 = {W1: [GW1]}

    w2 = pd.Timestamp("2026-02-09", tz="UTC")
    during = {s.gateway_id: s for s in ranker.score_week(data.before(w2), w2, picked_w1)}
    assert during[GW1].score >= 50 and not during[GW1].eligible
    assert "already chosen for week 2026-02-02" in during[GW1].reason

    w4 = pd.Timestamp("2026-02-23", tz="UTC")
    later = {s.gateway_id: s for s in ranker.score_week(data.before(w4), w4, picked_w1)}
    assert later[GW1].eligible and later[GW1].components["silent_hours"] == 144


def test_scores_are_deterministic(tmp_path):
    tel = silence(make_telemetry(end="2026-02-02"), GW1, "2026-01-29", "2026-02-02")
    data = load_dataset(write_data_dir(tmp_path, tel))
    ranker = ImprovedRanker()
    assert ranker.score_week(data.before(W1), W1, {}) == ranker.score_week(data.before(W1), W1, {})
