# src/judgemetrics/entity_resolution/stages.py
"""The value a stage returns: a decision, a score, a stage label, and a reason."""

from __future__ import annotations

from dataclasses import dataclass

from judgemetrics.db.models.enums import ResolutionDecision


@dataclass(frozen=True, slots=True)
class StageResult:
    """What one stage decided about a pair (``None`` from a stage means "no decision")."""

    decision: ResolutionDecision
    score: float
    stage: str
    reason: str

    @property
    def decisive(self) -> bool:
        """Matched or rejected ends the pipeline; review lets later stages weigh in."""
        return self.decision is not ResolutionDecision.REVIEW
