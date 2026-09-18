# src/judgemetrics/entity_resolution/deterministic.py
"""Stage 1: exact matching on a trustworthy stable identifier.

Two records that carry the same ``source_participant_id`` hash from one
source are the same person: ``matched`` at score 1.0. The same rule is
what finds a person for an incoming draft (``lookup_by_identity``): the
partial unique index ``uq_person_identifier_stable`` guarantees one person
per stable identifier, so a draft either finds exactly that person or is
new. Cross-source identifiers arrive with Phase 7 and will need a source
qualifier before this stage may fire across sources.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.db.models import Base
from judgemetrics.db.models.enums import ResolutionDecision
from judgemetrics.entity_resolution.config import STAGE_DETERMINISTIC
from judgemetrics.entity_resolution.features import PairFeatures
from judgemetrics.entity_resolution.stages import StageResult
from judgemetrics.ingest.base import NaturalKey
from judgemetrics.security.identifiers import STABLE_KINDS

PERSON_IDENTIFIER = Base.metadata.tables["person_identifier"]

REASON_SAME_SOURCE_ID = "same_source_id"
SCORE_SAME_SOURCE_ID = 1.0


def decide(features: PairFeatures) -> StageResult | None:
    """``matched`` on a shared stable identifier; otherwise no decision."""
    if features.same_source_id:
        return StageResult(
            decision=ResolutionDecision.MATCHED,
            score=SCORE_SAME_SOURCE_ID,
            stage=STAGE_DETERMINISTIC,
            reason=REASON_SAME_SOURCE_ID,
        )
    return None


def lookup_by_identity(session: Session, keys: Iterable[NaturalKey]) -> dict[NaturalKey, uuid.UUID]:
    """Persons by ``("person", <stable kind>, <hash>)`` through their identifier rows."""
    wanted = {key for key in set(keys) if len(key) == 3 and key[1] in STABLE_KINDS}
    found: dict[NaturalKey, uuid.UUID] = {}
    for kind in {key[1] for key in wanted}:
        hashes = {key[2] for key in wanted if key[1] == kind}
        rows = session.execute(
            select(PERSON_IDENTIFIER.c.person_id, PERSON_IDENTIFIER.c.value_hash).where(
                PERSON_IDENTIFIER.c.identifier_type == kind,
                PERSON_IDENTIFIER.c.value_hash.in_(hashes),
            )
        ).all()
        for person_id, value_hash in rows:
            key = ("person", kind, str(value_hash))
            if key in wanted:
                found[key] = person_id
    return found
