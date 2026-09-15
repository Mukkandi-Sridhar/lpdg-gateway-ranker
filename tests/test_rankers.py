import pytest

from gateway_ranker.checks import DataError
from gateway_ranker.rankers import get_ranker
from gateway_ranker.rankers.base import GatewayScore, select_top


def _scores(pairs):
    return [GatewayScore(gateway_id=g, score=s, reason=f"reason {g}") for g, s in pairs]


def test_select_top_orders_by_score_then_gateway_id():
    scores = _scores([("0A0000000003", 5), ("0A0000000002", 9), ("0A0000000001", 5), ("0A0000000004", 1)])
    top = select_top(scores, n=3)
    assert [(r.rank, r.gateway_id) for r in top] == [(1, "0A0000000002"), (2, "0A0000000001"), (3, "0A0000000003")]


def test_select_top_is_independent_of_input_order():
    scores = _scores([(f"0A00000000{i:02d}", i % 3) for i in range(20)])
    assert select_top(scores) == select_top(list(reversed(scores)))


def test_select_top_never_picks_ineligible_gateways():
    scores = _scores([("0A0000000001", 1), ("0A0000000003", 2)])
    scores.append(GatewayScore("0A0000000002", 99, "decommissioned", eligible=False))
    assert [r.gateway_id for r in select_top(scores, n=2)] == ["0A0000000003", "0A0000000001"]


def test_zero_score_picks_are_labelled_low_evidence():
    top = select_top(_scores([("0A0000000001", 2), ("0A0000000002", 0)]), n=2)
    assert top[0].reason == "reason 0A0000000001"
    assert top[1].reason.startswith("Low evidence – filling slot:")


def test_too_few_eligible_candidates_is_an_error():
    with pytest.raises(DataError, match="need at least 15"):
        select_top(_scores([("0A0000000001", 1)]))


def test_unknown_ranker_name_lists_the_options():
    with pytest.raises(ValueError, match="improved"):
        get_ranker("magic")
