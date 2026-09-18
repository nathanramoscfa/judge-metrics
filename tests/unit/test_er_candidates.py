# tests/unit/test_er_candidates.py
"""Candidate rows: ordered pairs, system versus human decisions, and the queue rendering."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from judgemetrics.cli import render_review_items
from judgemetrics.db.models.enums import ResolutionDecision
from judgemetrics.entity_resolution.candidates import (
    CandidateRow,
    StoredCandidate,
    ordered_pair,
)
from judgemetrics.entity_resolution.config import MODEL_VERSION, SYSTEM_ACTOR
from judgemetrics.entity_resolution.queue import ReviewItem

pytestmark = pytest.mark.unit

LOW = uuid.UUID(int=1)
HIGH = uuid.UUID(int=2)
NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def _stored(decided_by: str | None, decision: ResolutionDecision) -> StoredCandidate:
    return StoredCandidate(
        id=uuid.uuid4(),
        entity_type="person",
        left_id=LOW,
        right_id=HIGH,
        model_version=MODEL_VERSION,
        features={"same_name": True},
        score=Decimal("0.5000"),
        decision=decision,
        stage="review",
        reason=None,
        decided_at=None if decided_by is None else NOW,
        decided_by=decided_by,
        ingest_run_id=None,
        created_at=NOW,
    )


def test_ordered_pair_puts_the_smaller_id_left() -> None:
    assert ordered_pair(HIGH, LOW) == (LOW, HIGH)
    assert ordered_pair(LOW, HIGH) == (LOW, HIGH)
    row = CandidateRow(
        entity_type="person",
        left_id=LOW,
        right_id=HIGH,
        model_version=MODEL_VERSION,
        features={},
        score=0.98,
        decision=ResolutionDecision.MATCHED,
        stage="rule",
        reason="name_dob_case_link",
        decided_at=NOW,
        decided_by=SYSTEM_ACTOR,
        ingest_run_id=None,
    )
    assert row.pair == (LOW, HIGH)
    with pytest.raises(ValueError, match="left_record_id < right_record_id"):
        CandidateRow(
            entity_type="person",
            left_id=HIGH,
            right_id=LOW,
            model_version=MODEL_VERSION,
            features={},
            score=0.98,
            decision=ResolutionDecision.MATCHED,
            stage="rule",
            reason="x",
            decided_at=None,
            decided_by=None,
            ingest_run_id=None,
        )


def test_human_decisions_are_told_apart_from_system_ones() -> None:
    assert not _stored(None, ResolutionDecision.REVIEW).human_decided
    assert not _stored(SYSTEM_ACTOR, ResolutionDecision.MATCHED).human_decided
    assert _stored("reviewer-a", ResolutionDecision.REJECTED).human_decided


def test_review_rendering_shows_public_keys_and_flags_only() -> None:
    item = ReviewItem(
        candidate_id=uuid.UUID(int=7),
        left_public_key="AbCdEfGhIjKlMnOp",
        right_public_key="QrStUvWxYz012345",
        stage="review",
        score=Decimal("0.5000"),
        reason="no_decisive_stage",
        features={
            "same_source_id": False,
            "same_name": True,
            "same_dob": True,
            "dob_missing_either": False,
            "same_name_dob": True,
            "shared_case": False,
            "related_case_link": False,
            "same_court": False,
        },
        created_at=NOW,
    )
    payload = item.as_dict()
    assert set(payload) == {
        "candidate_id",
        "left_public_key",
        "right_public_key",
        "stage",
        "score",
        "reason",
        "features",
        "created_at",
    }
    assert payload["score"] == 0.5
    lines = render_review_items([payload])
    assert lines[0].startswith("candidate_id\t")
    assert (
        "AbCdEfGhIjKlMnOp\tQrStUvWxYz012345\treview\t0.50\tsame_name,same_dob,same_name_dob"
        in (lines[1])
    )
    assert render_review_items([]) == ["no review items"]
