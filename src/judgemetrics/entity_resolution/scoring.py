# src/judgemetrics/entity_resolution/scoring.py
"""Stage 3: probabilistic record linkage behind the ``Scorer`` protocol.

A scorer turns a feature vector into a match probability; the versioned
thresholds then decide (``>= auto_match`` matched, ``< auto_reject``
rejected, otherwise review). ``StubScorer`` returns ``None`` — no model
exists before Phase 7 — and the pipeline records the stage as ``skipped``
in the candidate's stage trace, so every stored candidate says which
stages weighed in.
"""

from __future__ import annotations

from typing import Protocol

from judgemetrics.db.models.enums import ResolutionDecision
from judgemetrics.entity_resolution.config import STAGE_PROBABILISTIC, Thresholds
from judgemetrics.entity_resolution.features import PairFeatures
from judgemetrics.entity_resolution.stages import StageResult

REASON_SCORE_AUTO_MATCH = "score_at_or_above_auto_match"
REASON_SCORE_AUTO_REJECT = "score_below_auto_reject"
REASON_SCORE_AMBIGUOUS = "score_between_thresholds"
TRACE_SKIPPED = "skipped"


class Scorer(Protocol):
    """A model that scores a pair, or declines (``None``) when it has no opinion."""

    def score(self, features: PairFeatures) -> float | None: ...


class StubScorer:
    """The Phase 2 placeholder: declines every pair."""

    def score(self, features: PairFeatures) -> float | None:
        del features
        return None


def decide(features: PairFeatures, scorer: Scorer, thresholds: Thresholds) -> StageResult | None:
    """The thresholded decision for the scorer's probability, or ``None`` when it declines."""
    probability = scorer.score(features)
    if probability is None:
        return None
    if not 0.0 <= probability <= 1.0:
        msg = f"scorer returned {probability!r}, not a probability"
        raise ValueError(msg)
    if probability >= thresholds.auto_match:
        return StageResult(
            ResolutionDecision.MATCHED, probability, STAGE_PROBABILISTIC, REASON_SCORE_AUTO_MATCH
        )
    if probability < thresholds.auto_reject:
        return StageResult(
            ResolutionDecision.REJECTED, probability, STAGE_PROBABILISTIC, REASON_SCORE_AUTO_REJECT
        )
    return StageResult(
        ResolutionDecision.REVIEW, probability, STAGE_PROBABILISTIC, REASON_SCORE_AMBIGUOUS
    )
