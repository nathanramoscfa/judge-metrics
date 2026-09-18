# src/judgemetrics/entity_resolution/candidates.py
"""The audited candidate rows: one per ordered pair per model version.

A row records what the brief's auditability clause asks for: the feature
vector (``PairFeatures.as_dict()`` plus a ``stage_trace`` naming what
each stage said), the score, the decision, the deciding stage, the
timestamp and actor of the decision (``system:<model version>`` or the
reviewer's label; a review item stays undecided until a person decides
it), the reason, and the ingest run. ``upsert_candidates`` arbitrates on
``uq_er_candidate_pair_version``: a system decision is rewritten when it
changed, a human decision (``decided_by`` not starting with ``system:``)
is never overwritten, and a new model version writes new rows beside the
old ones, which remain as history.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from judgemetrics.db.models import Base
from judgemetrics.db.models.enums import ResolutionDecision
from judgemetrics.entity_resolution.config import SYSTEM_ACTOR_PREFIX

CANDIDATE = Base.metadata.tables["entity_resolution_candidate"]
BATCH_SIZE = 500

Pair = tuple[uuid.UUID, uuid.UUID]


@dataclass(frozen=True, slots=True)
class CandidateRow:
    """One decision to store for an ordered pair under a model version."""

    entity_type: str
    left_id: uuid.UUID
    right_id: uuid.UUID
    model_version: str
    features: dict[str, Any]
    score: float
    decision: ResolutionDecision
    stage: str
    reason: str
    decided_at: datetime | None
    decided_by: str | None
    ingest_run_id: uuid.UUID | None

    def __post_init__(self) -> None:
        if not self.left_id < self.right_id:
            msg = "a candidate pair is stored with left_record_id < right_record_id"
            raise ValueError(msg)

    @property
    def pair(self) -> Pair:
        return (self.left_id, self.right_id)


@dataclass(frozen=True, slots=True)
class StoredCandidate:
    """A candidate row as it stands in the database."""

    id: uuid.UUID
    entity_type: str
    left_id: uuid.UUID
    right_id: uuid.UUID
    model_version: str
    features: dict[str, Any]
    score: Decimal | None
    decision: ResolutionDecision
    stage: str
    reason: str | None
    decided_at: datetime | None
    decided_by: str | None
    ingest_run_id: uuid.UUID | None
    created_at: datetime

    @property
    def pair(self) -> Pair:
        return (self.left_id, self.right_id)

    @property
    def human_decided(self) -> bool:
        return self.decided_by is not None and not self.decided_by.startswith(SYSTEM_ACTOR_PREFIX)


@dataclass(slots=True)
class UpsertCounts:
    created: int = 0
    updated: int = 0


def ordered_pair(a: uuid.UUID, b: uuid.UUID) -> Pair:
    return (a, b) if a < b else (b, a)


def upsert_candidates(session: Session, rows: Sequence[CandidateRow]) -> UpsertCounts:
    """Insert or refresh system decisions; leave human decisions untouched."""
    counts = UpsertCounts()
    if not rows:
        return counts
    inserted = sa.literal_column("(xmax = 0)", type_=sa.Boolean).label("inserted")
    for start in range(0, len(rows), BATCH_SIZE):
        values = [
            {
                "id": uuid.uuid4(),
                "entity_type": row.entity_type,
                "left_record_id": row.left_id,
                "right_record_id": row.right_id,
                "match_probability": Decimal(str(round(row.score, 4))),
                "decision": row.decision,
                "features": row.features,
                "model_version": row.model_version,
                "stage": row.stage,
                "decided_at": row.decided_at,
                "decided_by": row.decided_by,
                "reason": row.reason,
                "ingest_run_id": row.ingest_run_id,
            }
            for row in rows[start : start + BATCH_SIZE]
        ]
        stmt = insert(CANDIDATE).values(values)
        excluded = stmt.excluded
        upsert = stmt.on_conflict_do_update(
            index_elements=[
                CANDIDATE.c.entity_type,
                CANDIDATE.c.left_record_id,
                CANDIDATE.c.right_record_id,
                CANDIDATE.c.model_version,
            ],
            set_={
                "match_probability": excluded.match_probability,
                "decision": excluded.decision,
                "features": excluded.features,
                "stage": excluded.stage,
                "decided_at": excluded.decided_at,
                "decided_by": excluded.decided_by,
                "reason": excluded.reason,
                "ingest_run_id": excluded.ingest_run_id,
                "updated_at": sa.func.now(),
            },
            where=sa.and_(
                sa.or_(
                    CANDIDATE.c.decided_by.is_(None),
                    CANDIDATE.c.decided_by.like(f"{SYSTEM_ACTOR_PREFIX}%"),
                ),
                sa.or_(
                    CANDIDATE.c.match_probability.is_distinct_from(excluded.match_probability),
                    CANDIDATE.c.decision.is_distinct_from(excluded.decision),
                    CANDIDATE.c.features.is_distinct_from(excluded.features),
                    CANDIDATE.c.stage.is_distinct_from(excluded.stage),
                    CANDIDATE.c.reason.is_distinct_from(excluded.reason),
                ),
            ),
        ).returning(CANDIDATE.c.id, inserted)
        result = session.execute(upsert).all()
        created = sum(1 for row in result if row.inserted)
        counts.created += created
        counts.updated += len(result) - created
    return counts


def load_candidates(
    session: Session, pairs: Iterable[Pair], *, entity_type: str, model_version: str
) -> dict[Pair, StoredCandidate]:
    """The stored rows for ``pairs`` under ``model_version``."""
    wanted = set(pairs)
    if not wanted:
        return {}
    lefts = {left for left, _ in wanted}
    stmt = select(CANDIDATE).where(
        CANDIDATE.c.entity_type == entity_type,
        CANDIDATE.c.model_version == model_version,
        CANDIDATE.c.left_record_id.in_(lefts),
    )
    found: dict[Pair, StoredCandidate] = {}
    for row in session.execute(stmt).mappings().all():
        candidate = _stored(row)
        if candidate.pair in wanted:
            found[candidate.pair] = candidate
    return found


def get_candidate(session: Session, candidate_id: uuid.UUID) -> StoredCandidate | None:
    row = (
        session.execute(select(CANDIDATE).where(CANDIDATE.c.id == candidate_id)).mappings().first()
    )
    return _stored(row) if row is not None else None


def _stored(row: Any) -> StoredCandidate:
    return StoredCandidate(
        id=row["id"],
        entity_type=row["entity_type"],
        left_id=row["left_record_id"],
        right_id=row["right_record_id"],
        model_version=row["model_version"],
        features=dict(row["features"] or {}),
        score=row["match_probability"],
        decision=ResolutionDecision(row["decision"]),
        stage=row["stage"],
        reason=row["reason"],
        decided_at=row["decided_at"],
        decided_by=row["decided_by"],
        ingest_run_id=row["ingest_run_id"],
        created_at=row["created_at"],
    )
