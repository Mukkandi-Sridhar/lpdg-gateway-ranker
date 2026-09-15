"""Ranker registry. Add a new ranker here; the pipeline and API pick it up by name (RANKER=...)."""
from __future__ import annotations

from gateway_ranker.config import ConfigError
from gateway_ranker.rankers.base import Ranker
from gateway_ranker.rankers.baseline import BaselineRanker
from gateway_ranker.rankers.improved import ImprovedRanker

RANKERS: dict[str, type] = {
    "improved": ImprovedRanker,
    "baseline": BaselineRanker,
}


def get_ranker(name: str) -> Ranker:
    """Build a ranker by name. Raises ConfigError listing the valid names."""
    try:
        return RANKERS[name]()
    except KeyError:
        raise ConfigError(f"unknown ranker {name!r}; choose one of {sorted(RANKERS)}") from None
