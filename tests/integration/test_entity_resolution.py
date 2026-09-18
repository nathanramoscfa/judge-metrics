# tests/integration/test_entity_resolution.py
"""Entity resolution over the golden fixture, inside the transactional test session.

Every row of ``truth/resolution_expectations.csv`` matches the stored
candidate's decision; split persons are merged under one public key;
ambiguous pairs wait in review; distinct persons keep distinct ids; every
candidate carries features, a score, the model version, a stage, and a
decision, and no feature carries a restricted value; a second ingest
writes no candidate and merges nothing; ``rerun`` is idempotent; a
reviewer's decision merges or rejects with an audit row that cannot be
altered; an already-decided candidate is refused; the resolution log
lines carry no name, date of birth, or hash.
"""

from __future__ import annotations

import csv
import io
import json
import logging as stdlib_logging
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog
from pydantic import SecretStr
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from judgemetrics.cli import app
from judgemetrics.config import Settings, get_settings
from judgemetrics.db.models import (
    AuditLog,
    CaseParty,
    EntityResolutionCandidate,
    IngestRun,
    IngestRunStatus,
    Person,
    PersonIdentifier,
)
from judgemetrics.db.models.enums import ResolutionDecision
from judgemetrics.entity_resolution.config import MODEL_VERSION, STAGES, SYSTEM_ACTOR
from judgemetrics.entity_resolution.features import FEATURE_BOOLEANS
from judgemetrics.entity_resolution.pipeline import rerun
from judgemetrics.entity_resolution.queue import ReviewError, decide, list_review
from judgemetrics.ingest.runner import run_ingest
from judgemetrics.ingest.store import FilesystemRawObjectStore
from judgemetrics.logging import configure_logging
from judgemetrics.security.identifiers import KIND_SOURCE_PARTICIPANT_ID, hash_identifier
from tests.conftest import TEST_IDENTIFIER_PEPPER
from tests.integration.conftest import purge_source

pytestmark = pytest.mark.integration

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden"
SOURCE_ID = "synthetic"
PEPPER = SecretStr(TEST_IDENTIFIER_PEPPER)
HEX64 = re.compile(r"[0-9a-f]{64}")


def _expectations() -> list[dict[str, str]]:
    with (GOLDEN / "truth" / "resolution_expectations.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _participants() -> list[dict[str, str]]:
    with (GOLDEN / "source" / "participants.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _person_of(session: Session, participant_id: str) -> Person:
    """The (unmerged or merged) person that carries a participant id's hash."""
    value_hash = hash_identifier(PEPPER, KIND_SOURCE_PARTICIPANT_ID, participant_id)
    person = session.scalar(
        select(Person)
        .join(PersonIdentifier, PersonIdentifier.person_id == Person.id)
        .where(
            PersonIdentifier.identifier_type == KIND_SOURCE_PARTICIPANT_ID,
            PersonIdentifier.value_hash == value_hash,
        )
    )
    assert person is not None, participant_id
    return person


def _canonical(session: Session, person: Person) -> Person:
    current = person
    while current.merged_into_person_id is not None:
        nxt = session.get(Person, current.merged_into_person_id)
        assert nxt is not None
        current = nxt
    return current


def _family(session: Session, person: Person) -> set[uuid.UUID]:
    """The survivor of ``person`` and every person merged into it."""
    keep = _canonical(session, person)
    merged = set(session.scalars(select(Person.id).where(Person.merged_into_person_id == keep.id)))
    return {keep.id, *merged}


def _candidate_for(session: Session, left: Person, right: Person) -> EntityResolutionCandidate:
    """The stored candidate between the two persons, looked up through their merge families."""
    family = _family(session, left) | _family(session, right)
    candidates = list(
        session.scalars(
            select(EntityResolutionCandidate).where(
                EntityResolutionCandidate.left_record_id.in_(family),
                EntityResolutionCandidate.right_record_id.in_(family),
                EntityResolutionCandidate.model_version == MODEL_VERSION,
            )
        )
    )
    assert len(candidates) == 1, (left.id, right.id, [c.id for c in candidates])
    return candidates[0]


@pytest.fixture
def clean_session(db_session: Session) -> Session:
    purge_source(db_session, SOURCE_ID)
    return db_session


@pytest.fixture
def store(tmp_path: Path) -> FilesystemRawObjectStore:
    return FilesystemRawObjectStore(tmp_path / "lake")


@pytest.fixture
def captured_logs() -> Iterator[io.StringIO]:
    configure_logging(Settings(env="test", log_format="json", identifier_pepper=PEPPER))
    stream = io.StringIO()
    handler = stdlib_logging.StreamHandler(stream)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(sort_keys=True),
            ]
        )
    )
    root = stdlib_logging.getLogger()
    root.addHandler(handler)
    try:
        yield stream
    finally:
        root.removeHandler(handler)


def _ingest(session: Session, store: FilesystemRawObjectStore, *, force: bool = False) -> IngestRun:
    run = run_ingest(
        SOURCE_ID,
        session=session,
        store=store,
        settings=Settings(env="test", identifier_pepper=PEPPER),
        from_fixture=GOLDEN,
        force=force,
    )
    assert run.status is IngestRunStatus.SUCCEEDED, run.failure_reason
    return run


def _count(session: Session, model: type[EntityResolutionCandidate | AuditLog | Person]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


# --- the golden expectations --------------------------------------------------------------


def test_every_planted_pair_resolves_as_the_truth_predicts(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    run = _ingest(session, store)
    expectations = _expectations()
    assert len(expectations) == 4
    for row in expectations:
        left = _person_of(session, row["left_participant_id"])
        right = _person_of(session, row["right_participant_id"])
        candidate = _candidate_for(session, left, right)
        assert candidate.decision.value == row["expected_decision"], row
        assert candidate.ingest_run_id == run.id
        if row["expected_decision"] == "matched":
            # Both participant ids now hash to the survivor: one person, one family of two.
            assert left.id == right.id
            assert len(_family(session, left)) == 2
            assert candidate.stage == "rule" and candidate.decided_by == SYSTEM_ACTOR
            assert candidate.decided_at is not None
            assert candidate.features["related_case_link"] is True
        elif row["expected_decision"] == "review":
            assert left.merged_into_person_id is None and right.merged_into_person_id is None
            assert candidate.decided_at is None and candidate.decided_by is None
            assert candidate.features["same_name_dob"] is True
            assert candidate.features["shared_case"] is False
        else:
            assert left.merged_into_person_id is None and right.merged_into_person_id is None
            assert candidate.reason == "name_only"
            assert candidate.features["dob_missing_either"] is True
            assert candidate.decided_by == SYSTEM_ACTOR
    # The planted pairs are the only candidates: names are unique otherwise.
    assert _count(session, EntityResolutionCandidate) == 4
    assert (
        session.scalar(
            select(func.count())
            .select_from(Person)
            .where(Person.merged_into_person_id.is_not(None))
        )
        == 2
    )
    assert _count(session, Person) == 42


def test_split_persons_share_one_public_key_and_distinct_persons_keep_their_ids(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    _ingest(session, store)
    for row in _expectations():
        left = _person_of(session, row["left_participant_id"])
        right = _person_of(session, row["right_participant_id"])
        if row["expected_decision"] == "matched":
            keep = _canonical(session, left)
            assert right.id == keep.id
            drop = session.scalar(select(Person).where(Person.merged_into_person_id == keep.id))
            assert drop is not None
            assert drop.merged_into_person_id == keep.id
            assert drop.resolution_status == "merged"
            assert keep.resolution_status == "rule"
            assert (
                keep.resolution_confidence is not None and float(keep.resolution_confidence) == 0.98
            )
            parties = list(session.scalars(select(CaseParty).where(CaseParty.person_id == keep.id)))
            assert {p.case_id for p in parties} >= {
                p.case_id
                for p in session.scalars(select(CaseParty).where(CaseParty.person_id == drop.id))
            }
            assert not list(
                session.scalars(select(CaseParty).where(CaseParty.person_id == drop.id))
            )
            hashes = {
                (i.identifier_type, i.value_hash)
                for i in session.scalars(
                    select(PersonIdentifier).where(PersonIdentifier.person_id == keep.id)
                )
            }
            assert len([h for kind, h in hashes if kind == KIND_SOURCE_PARTICIPANT_ID]) == 2
            assert not list(
                session.scalars(
                    select(PersonIdentifier).where(PersonIdentifier.person_id == drop.id)
                )
            )
        else:
            assert left.id != right.id
            assert left.public_person_key != right.public_person_key
    # Every person that is not merged still owns its parties; no party points at a merged person.
    merged_ids = set(
        session.scalars(select(Person.id).where(Person.merged_into_person_id.is_not(None)))
    )
    assert merged_ids
    assert not list(session.scalars(select(CaseParty).where(CaseParty.person_id.in_(merged_ids))))
    # Audit rows are append-only, so earlier committed merges (the demo seed,
    # the API tests' golden ingests) remain: count the merges of this ingest,
    # keyed by the persons kept.
    kept_ids = set(
        session.scalars(
            select(Person.merged_into_person_id).where(Person.merged_into_person_id.is_not(None))
        )
    )
    audits = list(
        session.scalars(
            select(AuditLog).where(AuditLog.action == "er.merge", AuditLog.entity_id.in_(kept_ids))
        )
    )
    assert len(audits) == 2
    for audit in audits:
        assert audit.actor == SYSTEM_ACTOR
        assert audit.entity_type == "person"
        assert audit.payload["moved"]["case_party"] >= 1
        assert not HEX64.search(json.dumps(audit.payload))


def test_every_candidate_is_auditable_and_free_of_restricted_values(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    _ingest(session, store)
    names = {row["full_name"].strip() for row in _participants()}
    dobs = {row["date_of_birth"] for row in _participants()} - {""}
    pids = {row["participant_id"] for row in _participants()}
    for candidate in session.scalars(select(EntityResolutionCandidate)):
        assert candidate.features, "non-empty features"
        assert candidate.match_probability is not None
        assert candidate.model_version == MODEL_VERSION
        assert candidate.stage in STAGES
        assert candidate.decision in set(ResolutionDecision)
        assert candidate.left_record_id < candidate.right_record_id
        rendered = json.dumps(candidate.features)
        assert not HEX64.search(rendered)
        assert not any(name in rendered for name in names)
        assert not any(dob in rendered for dob in dobs)
        assert not any(pid in rendered for pid in pids)
        assert set(candidate.features) >= {*FEATURE_BOOLEANS, "stage_trace"}
        trace = candidate.features["stage_trace"]
        assert trace["deterministic"] == "no_signal"
        if candidate.stage == "rule":
            assert "probabilistic" not in trace  # the pipeline stopped at the rule stage
        else:
            assert trace["probabilistic"] == "skipped"  # the stub scorer declined


# --- idempotency ---------------------------------------------------------------------------


def test_second_ingest_and_rerun_create_no_candidates_and_merge_nothing(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    _ingest(session, store)
    candidates = _count(session, EntityResolutionCandidate)
    audits = _count(session, AuditLog)
    merged = set(
        session.scalars(select(Person.id).where(Person.merged_into_person_id.is_not(None)))
    )
    snapshot = {
        c.id: (c.decision, c.decided_at, c.decided_by, c.updated_at)
        for c in session.scalars(select(EntityResolutionCandidate))
    }

    second = _ingest(session, store)
    assert (second.records_created, second.records_updated) == (0, 0)
    assert _count(session, EntityResolutionCandidate) == candidates
    assert _count(session, AuditLog) == audits

    forced = _ingest(session, store, force=True)
    assert (forced.records_created, forced.records_updated) == (0, 0)
    assert _count(session, EntityResolutionCandidate) == candidates
    assert _count(session, AuditLog) == audits

    stats = rerun(session, source=SOURCE_ID)
    assert stats.merges == 0
    assert stats.candidates.created == 0 and stats.candidates.updated == 0
    assert stats.pairs == 2  # the review and the name-only pair; the merged pairs are gone
    assert _count(session, AuditLog) == audits
    assert (
        set(session.scalars(select(Person.id).where(Person.merged_into_person_id.is_not(None))))
        == merged
    )
    session.expire_all()
    assert {
        c.id: (c.decision, c.decided_at, c.decided_by, c.updated_at)
        for c in session.scalars(select(EntityResolutionCandidate))
    } == snapshot
    everything = rerun(session)
    assert everything.merges == 0 and everything.candidates.created == 0


# --- the review queue -------------------------------------------------------------------------


def test_review_queue_lists_public_keys_and_a_decision_merges_with_an_immutable_audit_row(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    _ingest(session, store)
    items = list_review(session)
    assert len(items) == 1
    item = items[0]
    rendered = json.dumps(item.as_dict())
    assert not HEX64.search(rendered)
    assert item.stage == "review" and item.score is not None
    assert item.features["same_name_dob"] is True and item.features["shared_case"] is False
    ambiguous = next(r for r in _expectations() if r["expected_decision"] == "review")
    left = _person_of(session, ambiguous["left_participant_id"])
    right = _person_of(session, ambiguous["right_participant_id"])
    assert {item.left_public_key, item.right_public_key} == {
        left.public_person_key,
        right.public_person_key,
    }

    settings = Settings(env="test", identifier_pepper=PEPPER)
    result = decide(
        session,
        item.candidate_id,
        decision=ResolutionDecision.MATCHED,
        reviewer="reviewer-a",
        reason="same name and date of birth confirmed against the docket",
        settings=settings,
    )
    assert result.merge is not None
    session.expire_all()
    assert _canonical(session, left).id == _canonical(session, right).id
    candidate = session.get(EntityResolutionCandidate, item.candidate_id)
    assert candidate is not None
    assert candidate.decision is ResolutionDecision.MATCHED
    assert candidate.decided_by == "reviewer-a" and candidate.decided_at is not None
    audit = session.get(AuditLog, result.audit_id)
    assert audit is not None
    assert audit.action == "er.decide" and audit.actor == "reviewer-a"
    assert audit.payload["candidate_id"] == str(item.candidate_id)
    assert not HEX64.search(json.dumps(audit.payload))
    assert list_review(session) == []

    # The audit row cannot be altered or removed, even inside this transaction.
    with pytest.raises(DBAPIError, match="append-only"), session.begin_nested():
        session.execute(update(AuditLog).where(AuditLog.id == audit.id).values(actor="x"))
    with pytest.raises(DBAPIError, match="append-only"), session.begin_nested():
        session.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": audit.id})

    # An already-decided candidate is refused; so is a rerun overwrite.
    with pytest.raises(ReviewError, match="not awaiting review"):
        decide(
            session,
            item.candidate_id,
            decision=ResolutionDecision.REJECTED,
            reviewer="reviewer-b",
            reason="second thoughts",
            settings=settings,
        )
    stats = rerun(session, source=SOURCE_ID)
    assert stats.merges == 0 and stats.candidates.updated == 0
    session.expire_all()
    assert session.get(EntityResolutionCandidate, item.candidate_id).decided_by == "reviewer-a"  # type: ignore[union-attr]


def test_a_rejection_records_the_candidate_and_survives_reruns(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    _ingest(session, store)
    (item,) = list_review(session)
    settings = Settings(env="test", identifier_pepper=PEPPER)
    audits = _count(session, AuditLog)
    result = decide(
        session,
        item.candidate_id,
        decision=ResolutionDecision.REJECTED,
        reviewer="reviewer-a",
        reason="different middle names on the dockets",
        settings=settings,
    )
    assert result.merge is None
    assert _count(session, AuditLog) == audits + 1
    assert (
        session.scalar(
            select(func.count())
            .select_from(Person)
            .where(Person.merged_into_person_id.is_not(None))
        )
        == 2
    )
    stats = rerun(session, source=SOURCE_ID)
    assert stats.candidates.updated == 0 and stats.merges == 0
    session.expire_all()
    candidate = session.get(EntityResolutionCandidate, item.candidate_id)
    assert candidate is not None and candidate.decision is ResolutionDecision.REJECTED
    assert candidate.decided_by == "reviewer-a"


def test_decide_validates_inputs_and_is_refused_in_production(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    _ingest(session, store)
    (item,) = list_review(session)
    production = Settings(env="production", identifier_pepper=PEPPER)
    with pytest.raises(ReviewError, match="refused in production"):
        decide(
            session,
            item.candidate_id,
            decision=ResolutionDecision.MATCHED,
            reviewer="reviewer-a",
            reason="x",
            settings=production,
        )
    test_settings = Settings(env="test", identifier_pepper=PEPPER)
    with pytest.raises(ReviewError, match="matched or rejected"):
        decide(
            session,
            item.candidate_id,
            decision=ResolutionDecision.REVIEW,
            reviewer="reviewer-a",
            reason="x",
            settings=test_settings,
        )
    with pytest.raises(ReviewError, match="operator label"):
        decide(
            session,
            item.candidate_id,
            decision=ResolutionDecision.MATCHED,
            reviewer="system:person-rules-v0",
            reason="x",
            settings=test_settings,
        )
    with pytest.raises(ReviewError, match="reason"):
        decide(
            session,
            item.candidate_id,
            decision=ResolutionDecision.MATCHED,
            reviewer="reviewer-a",
            reason="   ",
            settings=test_settings,
        )
    with pytest.raises(ReviewError, match="no candidate"):
        decide(
            session,
            uuid.uuid4(),
            decision=ResolutionDecision.MATCHED,
            reviewer="reviewer-a",
            reason="x",
            settings=test_settings,
        )
    assert list_review(session)[0].candidate_id == item.candidate_id


# --- logs ----------------------------------------------------------------------------------------


def test_resolution_log_lines_carry_no_restricted_values(
    clean_session: Session, store: FilesystemRawObjectStore, captured_logs: io.StringIO
) -> None:
    session = clean_session
    _ingest(session, store)
    rerun(session, source=SOURCE_ID)
    rendered = captured_logs.getvalue()
    assert "er.resolved" in rendered and "er.merged" in rendered
    for row in _participants():
        assert row["full_name"].strip() not in rendered
        if row["date_of_birth"]:
            assert row["date_of_birth"] not in rendered
        assert row["participant_id"] not in rendered
    for value_hash in session.scalars(select(PersonIdentifier.value_hash)):
        assert value_hash not in rendered
    assert TEST_IDENTIFIER_PEPPER not in rendered


# --- the CLI -------------------------------------------------------------------------------------


def test_cli_validates_the_candidate_id_and_decision_before_touching_the_database(
    settings: Settings,
) -> None:
    env = {
        "JUDGEMETRICS_ENV": "test",
        "JUDGEMETRICS_DATABASE_URL": settings.database_url,
        "JUDGEMETRICS_INGEST_DATABASE_URL": settings.effective_ingest_database_url
        if settings.ingest_database_url
        else settings.effective_admin_database_url,
        "JUDGEMETRICS_LOG_FORMAT": "json",
    }
    runner = CliRunner()
    bad_id = runner.invoke(
        app,
        [
            "er",
            "review",
            "decide",
            "not-a-uuid",
            "--decision",
            "matched",
            "--reviewer",
            "r",
            "--reason",
            "x",
        ],
        env=env,
    )
    assert bad_id.exit_code == 2, bad_id.output
    bad_decision = runner.invoke(
        app,
        [
            "er",
            "review",
            "decide",
            str(uuid.uuid4()),
            "--decision",
            "maybe",
            "--reviewer",
            "r",
            "--reason",
            "x",
        ],
        env=env,
    )
    assert bad_decision.exit_code == 2, bad_decision.output
    missing = runner.invoke(
        app,
        [
            "er",
            "review",
            "decide",
            str(uuid.uuid4()),
            "--decision",
            "matched",
            "--reviewer",
            "reviewer-a",
            "--reason",
            "x",
        ],
        env=env,
    )
    assert missing.exit_code == 2, missing.output
    assert "no candidate" in missing.output
    get_settings.cache_clear()  # the CLI caches settings per process; the environment changes
    refused = runner.invoke(
        app,
        [
            "er",
            "review",
            "decide",
            str(uuid.uuid4()),
            "--decision",
            "matched",
            "--reviewer",
            "reviewer-a",
            "--reason",
            "x",
        ],
        env={**env, "JUDGEMETRICS_ENV": "production"},
    )
    get_settings.cache_clear()
    assert refused.exit_code == 2, refused.output
    assert "refused in production" in refused.output
    listing = runner.invoke(app, ["er", "review", "list", "--entity-type", "judge"], env=env)
    assert listing.exit_code == 2 and "no review queue" in listing.output
