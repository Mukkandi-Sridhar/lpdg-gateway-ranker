"""The ranking interface. The pipeline and the API only depend on this module.

To add a ranker: write a class with a `name` and a `score_week` method, then register it
in gateway_ranker/rankers/__init__.py. Nothing in api/ needs to change.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

from gateway_ranker.checks import DataError
from gateway_ranker.loading import Dataset

VISITS_PER_WEEK = 15
FILLER_REASON = "Low evidence: no warning signs found; fills slot {rank} of 15. Would not dispatch."


@dataclass(frozen=True)
class GatewayScore:
    """One gateway's score for one week. `components` are the parts that add up to `score`."""

    gateway_id: str
    score: float
    reason: str
    components: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RankedGateway(GatewayScore):
    rank: int = 0


class Ranker(Protocol):
    name: str

    def score_week(self, data: Dataset, monday: pd.Timestamp,
                   previous_picks: Mapping[pd.Timestamp, list[str]]) -> list[GatewayScore]:
        """Score every candidate gateway for the week starting `monday`.

        `data` is already cut to what was known before `monday` (Dataset.before).
        `previous_picks` holds the top 15 chosen in earlier scored weeks, oldest first.
        """
        ...


def select_top(scores: list[GatewayScore], n: int = VISITS_PER_WEEK) -> list[RankedGateway]:
    """Highest score first; ties broken by gateway_id so the output is deterministic.

    Picks with score <= 0 carry no evidence; their reason says so honestly.
    """
    if len(scores) < n:
        raise DataError(f"only {len(scores)} candidate gateways to rank; need at least {n}")
    ordered = sorted(scores, key=lambda s: (-s.score, s.gateway_id))[:n]
    return [
        RankedGateway(
            gateway_id=s.gateway_id,
            score=s.score,
            reason=s.reason if s.score > 0 else FILLER_REASON.format(rank=rank),
            components=s.components,
            rank=rank,
        )
        for rank, s in enumerate(ordered, start=1)
    ]
