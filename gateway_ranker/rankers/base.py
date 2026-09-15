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
LOW_EVIDENCE_PREFIX = "Low evidence – filling slot: "


@dataclass(frozen=True)
class GatewayScore:
    """One gateway's score for one week.

    `components` are the numbers behind the score (shown by GET /gateways/{id}).
    `eligible=False` means the gateway must not be picked this week (for example
    decommissioned, or already visited in the same fault episode); `reason` says why.
    """

    gateway_id: str
    score: float
    reason: str
    components: dict[str, float] = field(default_factory=dict)
    eligible: bool = True


@dataclass(frozen=True)
class RankedGateway(GatewayScore):
    rank: int = 0


class Ranker(Protocol):
    name: str

    def score_week(self, data: Dataset, monday: pd.Timestamp,
                   previous_picks: Mapping[pd.Timestamp, list[str]]) -> list[GatewayScore]:
        """Score every known gateway for the week starting `monday`.

        `data` is already cut to what was known before `monday` (Dataset.before).
        `previous_picks` holds the top 15 chosen in earlier scored weeks, oldest first.
        """
        ...


def select_top(scores: list[GatewayScore], n: int = VISITS_PER_WEEK) -> list[RankedGateway]:
    """Pick the n highest-scoring eligible gateways.

    Ties are broken by gateway_id ascending, so the output never depends on input order.
    A pick with score <= 0 carries no evidence, and its reason says so.
    """
    eligible = [s for s in scores if s.eligible]
    if len(eligible) < n:
        raise DataError(f"only {len(eligible)} eligible gateways to rank; need at least {n}")
    ordered = sorted(eligible, key=lambda s: (-s.score, s.gateway_id))[:n]
    ranked = []
    for rank, s in enumerate(ordered, start=1):
        reason = s.reason
        if s.score <= 0 and not reason.startswith(LOW_EVIDENCE_PREFIX):
            reason = LOW_EVIDENCE_PREFIX + "no warning signs found. Would not dispatch."
        ranked.append(RankedGateway(s.gateway_id, s.score, reason, s.components, s.eligible, rank))
    return ranked
