# src/judgemetrics/entity_resolution/queue.py
"""The manual-review queue: listing undecided candidates and recording a decision.

``list_review`` returns what a reviewer may see — candidate id, the two
public person keys, stage, score, the feature booleans, and the created
time — never a hash, a name, a date of birth, or a participant id.
``decide`` records a reviewer's ``matched`` (merge) or ``rejected``
(candidate only) decision with an ``er.decide`` audit row; it refuses a
candidate that is not in review, one already decided, one whose persons
are no longer both unmerged, and every invocation in the production
environment until Phase 6 ships administrative authentication.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import Base
from judgemetrics.db.models.enums import ResolutionDecision
from judgemetrics.entity_resolution.audit import (
    ACTION_DECIDE,
    ENTITY_CANDIDATE,
    write_audit,
)
from judgemetrics.entity_resolution.candidates import CANDIDATE, StoredCandidate, get_candidate
from judgemetrics.entity_resolution.config import ENTITY_PERSON, SYSTEM_ACTOR_PREFIX
from judgemetrics.entity_resolution.features import FEATURE_BOOLEANS
from judgemetrics.entity_resolution.merge import MergeResult, merge_persons
from judgemetrics.ingest.base import IngestError, utc_now

PERSON = Base.metadata.tables["person"]

HUMAN_DECISIONS = frozenset({ResolutionDecision.MATCHED, ResolutionDecision.REJECTED})
MAX_REVIEWER_LENGTH = 128
MAX_REASON_LENGTH = 2000


class ReviewError(IngestError):
    """The decision cannot be recorded; the message says why."""


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """One undecided candidate as the queue shows it (public keys and booleans only)."""

    candidate_id: uuid.UUID
    left_public_key: str
    right_public_key: str
    stage: str
    score: Decimal | None
    reason: str | None
    features: dict[str, bool | None]
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": str(self.candidate_id),
            "left_public_key": self.left_public_key,
            "right_public_key": self.right_public_key,
            "stage": self.stage,
            "score": None if self.score is None else float(self.score),
            "reason": self.reason,
            "features": dict(self.features),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class DecisionResult:
    candidate: StoredCandidate
    decision: ResolutionDecision
    audit_id: uuid.UUID
    merge: MergeResult | None


def list_review(
    session: Session, *, entity_type: str = ENTITY_PERSON, limit: int = 50
) -> list[ReviewItem]:
    """Undecided review candidates whose persons are both still unmerged, oldest first."""
    if entity_type != ENTITY_PERSON:
        msg = f"entity type {entity_type!r} has no review queue yet"
        raise ReviewError(msg)
    left = PERSON.alias("left_person")
    right = PERSON.alias("right_person")
    stmt = (
        select(
            CANDIDATE.c.id,
            left.c.public_person_key,
            right.c.public_person_key,
            CANDIDATE.c.stage,
            CANDIDATE.c.match_probability,
            CANDIDATE.c.reason,
            CANDIDATE.c.features,
            CANDIDATE.c.created_at,
        )
        .join(left, left.c.id == CANDIDATE.c.left_record_id)
        .join(right, right.c.id == CANDIDATE.c.right_record_id)
        .where(
            CANDIDATE.c.entity_type == entity_type,
            CANDIDATE.c.decision == ResolutionDecision.REVIEW,
            CANDIDATE.c.decided_by.is_(None),
            left.c.merged_into_person_id.is_(None),
            right.c.merged_into_person_id.is_(None),
        )
        .order_by(CANDIDATE.c.created_at, CANDIDATE.c.id)
        .limit(max(1, limit))
    )
    items: list[ReviewItem] = []
    for row in session.execute(stmt).all():
        features = dict(row[6] or {})
        items.append(
            ReviewItem(
                candidate_id=row[0],
                left_public_key=row[1],
                right_public_key=row[2],
                stage=row[3],
                score=row[4],
                reason=row[5],
                features={name: features.get(name) for name in FEATURE_BOOLEANS},
                created_at=row[7],
            )
        )
    return items


def decide(
    session: Session,
    candidate_id: uuid.UUID,
    *,
    decision: ResolutionDecision,
    reviewer: str,
    reason: str,
    settings: Settings,
    request_id: str | None = None,
) -> DecisionResult:
    """Record a reviewer's decision: merge on ``matched``, candidate and audit row on ``rejected``."""
    if settings.env == "production":
        msg = (
            "review decisions are refused in production until Phase 6 ships administrative "
            "authentication"
        )
        raise ReviewError(msg)
    if decision not in HUMAN_DECISIONS:
        msg = f"a reviewer decides matched or rejected, not {decision.value!r}"
        raise ReviewError(msg)
    label = reviewer.strip()
    if not label or len(label) > MAX_REVIEWER_LENGTH or label.startswith(SYSTEM_ACTOR_PREFIX):
        msg = "the reviewer is a non-empty operator label of at most 128 characters"
        raise ReviewError(msg)
    text = reason.strip()
    if not text or len(text) > MAX_REASON_LENGTH:
        msg = "a decision needs a reason of at most 2000 characters"
        raise ReviewError(msg)

    candidate = get_candidate(session, candidate_id)
    if candidate is None:
        msg = f"no candidate {candidate_id}"
        raise ReviewError(msg)
    if candidate.decision is not ResolutionDecision.REVIEW or candidate.decided_by is not None:
        msg = (
            f"candidate {candidate_id} is not awaiting review "
            f"(decision {candidate.decision.value}, decided by {candidate.decided_by or 'nobody'})"
        )
        raise ReviewError(msg)
    if candidate.entity_type != ENTITY_PERSON:
        msg = (
            f"candidate {candidate_id} is a {candidate.entity_type} pair; only persons are decided"
        )
        raise ReviewError(msg)
    persons = {
        row.id: row
        for row in session.execute(
            select(PERSON.c.id, PERSON.c.merged_into_person_id, PERSON.c.created_at).where(
                PERSON.c.id.in_([candidate.left_id, candidate.right_id])
            )
        ).all()
    }
    if len(persons) != 2 or any(row.merged_into_person_id is not None for row in persons.values()):
        msg = f"candidate {candidate_id}: a person of the pair was merged elsewhere"
        raise ReviewError(msg)

    decided_at = utc_now()
    merge: MergeResult | None = None
    payload: dict[str, Any] = {
        "candidate_id": str(candidate.id),
        "model_version": candidate.model_version,
        "decision": decision.value,
        "reason": text,
        "stage": candidate.stage,
        "score": None if candidate.score is None else float(candidate.score),
    }
    if decision is ResolutionDecision.MATCHED:
        ordered = sorted(persons.values(), key=lambda row: (row.created_at, row.id))
        merge = merge_persons(
            session,
            ordered[0].id,
            ordered[1].id,
            actor=label,
            reason=text,
            stage=candidate.stage,
            confidence=candidate.score,
            action=ACTION_DECIDE,
            payload=payload,
            request_id=request_id,
        )
        audit_id = merge.audit_id
    else:
        audit_id = write_audit(
            session,
            actor=label,
            action=ACTION_DECIDE,
            entity_type=ENTITY_CANDIDATE,
            entity_id=candidate.id,
            payload=payload,
            request_id=request_id,
        )
    session.execute(
        update(CANDIDATE)
        .where(CANDIDATE.c.id == candidate.id)
        .values(
            decision=decision,
            decided_at=decided_at,
            decided_by=label,
            reason=text,
            updated_at=sa.func.now(),
        )
    )
    updated = get_candidate(session, candidate.id)
    if updated is None:  # pragma: no cover - the row was just updated
        msg = f"candidate {candidate_id} vanished"
        raise ReviewError(msg)
    return DecisionResult(candidate=updated, decision=decision, audit_id=audit_id, merge=merge)
