# tests/integration/test_synthetic_ingest.py
"""End-to-end synthetic ingest of the golden fixture through the fourteen-step runner.

Inside the transactional test session: the first run creates exactly the
rows the source files describe (the manifest's counts minus the planted
duplicate copies), the second run creates and updates nothing, every
case-level row references a source record whose sha256 is the fixture
file's, the person table holds pseudonyms and hashes only, prosecutor
dismissals keep their actor, the planted data-quality issues exist, no
log line carries a participant attribute, and the real connector is
refused in production. The ``seed`` CLI tests commit nothing: in
production the run is refused before anything is generated.

Phase 3 Step 2: the run writes the source's coverage window and
observable outcomes (and an FJC run leaves them null and empty), and
pipeline step 13 — enabled per test through
``Settings(metrics_recompute_on_ingest=True)`` with a temporary snapshot
directory — publishes observations for every golden judge and court on
the first run, supersedes nothing and writes nothing on an identical
rerun, and after a run that moves one assignment from one judge to
another supersedes exactly those two judges' observations while every
other subject's rows stay in place; an FJC run computes nothing.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging as stdlib_logging
import re
import shutil
from collections import Counter
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import structlog
from pydantic import SecretStr
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from judgemetrics.cli import app
from judgemetrics.config import Settings
from judgemetrics.db.models import (
    Base,
    Case,
    Charge,
    CourtEvent,
    DataQualityIssue,
    Decision,
    IngestRun,
    IngestRunStatus,
    IssueSeverity,
    Judge,
    JusticeEvent,
    MetricObservation,
    Person,
    PersonIdentifier,
    PretrialRelease,
    Sentence,
    Source,
    SourceRecord,
)
from judgemetrics.db.models.enums import ActorType, SubjectType
from judgemetrics.ingest.runner import run_ingest
from judgemetrics.ingest.store import FilesystemRawObjectStore
from judgemetrics.ingest.synthetic.connector import SyntheticConnector
from judgemetrics.ingest.synthetic.schema import SOURCE_FILES
from judgemetrics.logging import configure_logging
from judgemetrics.security.identifiers import hash_identifier, name_dob_value
from tests.conftest import TEST_IDENTIFIER_PEPPER
from tests.integration.conftest import FJC_FIXTURES, purge_source

pytestmark = pytest.mark.integration

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden"
SOURCE_ID = "synthetic"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PEPPER = SecretStr(TEST_IDENTIFIER_PEPPER)

# Table → (source file, row-id column): how a row traces to its file.
CASE_LEVEL_FILES: dict[str, tuple[str, str]] = {
    "court_case": ("cases.csv", "case_number"),
    "case_party": ("participants.csv", "participant_id"),
    "judge_assignment": ("assignments.csv", "assignment_id"),
    "charge": ("charges.csv", "charge_id"),
    "court_event": ("events.csv", "event_id"),
    "decision": ("decisions.csv", "decision_id"),
    "sentence": ("sentences.csv", "sentence_id"),
}


def _rows(name: str) -> list[dict[str, str]]:
    with (GOLDEN / "source" / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _is_duplicate_copy(row: dict[str, str]) -> bool:
    return row["case_number"].startswith("syn ")


def _expected_counts() -> dict[str, int]:
    """Rows per table from the source files, duplicate copies counted once."""
    expected: dict[str, int] = {}
    for table, (name, column) in CASE_LEVEL_FILES.items():
        rows = _rows(name)
        if table == "court_case":
            expected[table] = len({r["case_number"].upper().replace(" ", "-") for r in rows})
        elif table == "case_party":
            expected[table] = len(
                {(r["participant_id"], r["case_number"].upper().replace(" ", "-")) for r in rows}
            )
        else:
            expected[table] = len({r[column] for r in rows})
    expected["person"] = len({r["participant_id"] for r in _rows("participants.csv")})
    expected["pretrial_release"] = len(
        {
            r["decision_id"]
            for r in _rows("decisions.csv")
            if r["decision_type"] == "pretrial_release"
        }
    )
    expected["judge"] = len({r["judge_code"] for r in _rows("judges.csv")})
    expected["judge_service"] = len(_rows("judges.csv"))
    expected["court"] = len(_rows("courts.csv"))
    expected["jurisdiction"] = 1
    return expected


@pytest.fixture
def clean_session(db_session: Session) -> Session:
    """The transactional session with every synthetic-derived row removed (rolled back afterwards)."""
    purge_source(db_session, SOURCE_ID)
    return db_session


@pytest.fixture
def store(tmp_path: Path) -> FilesystemRawObjectStore:
    return FilesystemRawObjectStore(tmp_path / "lake")


def _settings(env: str = "test", **overrides: Any) -> Settings:
    return Settings(env=env, identifier_pepper=PEPPER, **overrides)


def _run(
    session: Session,
    store: FilesystemRawObjectStore,
    *,
    fixture: Path = GOLDEN,
    force: bool = False,
    env: str = "test",
    settings: Settings | None = None,
) -> IngestRun:
    return run_ingest(
        SOURCE_ID,
        session=session,
        store=store,
        settings=settings if settings is not None else _settings(env),
        from_fixture=fixture,
        force=force,
    )


def _count(session: Session, table: str) -> int:
    return session.scalar(select(func.count()).select_from(Base.metadata.tables[table])) or 0


def _counts(session: Session) -> dict[str, int]:
    return {table: _count(session, table) for table in _expected_counts()}


def _issues(session: Session) -> list[DataQualityIssue]:
    records = select(SourceRecord.id).join(Source).where(Source.name == SOURCE_ID)
    stmt = (
        select(DataQualityIssue)
        .where(
            DataQualityIssue.source_record_id.in_(records)
            # Run-level issues (unknown-category counts) carry no source record.
            | DataQualityIssue.source_record_id.is_(None)
        )
        .order_by(DataQualityIssue.issue_code, DataQualityIssue.description)
    )
    return list(session.scalars(stmt))


def _expected_hashes() -> dict[str, set[tuple[str, str]]]:
    """The identifier rows the source implies, per participant id, computed independently."""
    expected: dict[str, set[tuple[str, str]]] = {}
    for participant in _rows("participants.csv"):
        pid = participant["participant_id"]
        name = participant["full_name"]
        dob = participant["date_of_birth"]
        hashes = expected.setdefault(pid, set())
        hashes.add(("source_participant_id", hash_identifier(PEPPER, "source_participant_id", pid)))
        hashes.add(("full_name", hash_identifier(PEPPER, "full_name", name)))
        if dob:
            hashes.add(("date_of_birth", hash_identifier(PEPPER, "date_of_birth", dob)))
            hashes.add(("name_dob", hash_identifier(PEPPER, "name_dob", name_dob_value(name, dob))))
    return expected


def _merged_groups() -> list[set[str]]:
    """Participant ids grouped as entity resolution merges them (the matched pairs of truth/)."""
    groups: dict[str, set[str]] = {pid: {pid} for pid in _expected_hashes()}
    with (GOLDEN / "truth" / "resolution_expectations.csv").open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["expected_decision"] != "matched":
                continue
            merged = groups[row["left_participant_id"]] | groups[row["right_participant_id"]]
            for pid in merged:
                groups[pid] = merged
    seen: list[set[str]] = []
    for group in groups.values():
        if group not in seen:
            seen.append(group)
    return seen


def _planted() -> list[dict[str, str]]:
    with (GOLDEN / "truth" / "planted.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def captured_logs() -> Iterator[io.StringIO]:
    """Every rendered log line of the runner and connector, scrubbed as in production."""
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


# --- the first run ---------------------------------------------------------------------


def test_first_run_creates_the_manifest_counts_minus_duplicates_with_provenance(
    clean_session: Session, store: FilesystemRawObjectStore, captured_logs: io.StringIO
) -> None:
    session = clean_session
    run = _run(session, store)
    assert run.status is IngestRunStatus.SUCCEEDED, run.failure_reason
    manifest = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    assert run.records_seen == sum(manifest["counts"][f"source/{name}"] for name in SOURCE_FILES)
    assert run.records_rejected == 0
    assert run.records_updated == 0
    assert run.parser_version == "1"

    expected = _expected_counts()
    assert _counts(session) == expected
    assert expected["court_case"] == manifest["counts"]["source/cases.csv"] - 3
    assert expected["person"] == 42
    justice_events = _count(session, "justice_event")
    assert justice_events > 0
    # Identifier rows as the source implies them: entity resolution then merges
    # the two planted split persons, which drops their duplicated name and
    # date-of-birth hashes (three per merge) from the live table.
    expected_identifiers = sum(len(hashes) for hashes in _expected_hashes().values())
    assert run.records_created == sum(expected.values()) + justice_events + expected_identifiers
    assert _count(session, "person_identifier") == expected_identifiers - 2 * 3

    source = session.scalar(select(Source).where(Source.name == SOURCE_ID))
    assert source is not None
    assert source.source_type == "synthetic"
    assert source.terms_metadata["synthetic"] is True
    records = {
        record.external_record_id: record
        for record in session.scalars(
            select(SourceRecord).where(SourceRecord.source_id == source.id)
        )
    }
    assert set(records) == {"manifest.json", *(f"source/{name}" for name in SOURCE_FILES)}
    for external_id, record in records.items():
        assert external_id is not None
        path = GOLDEN / Path(*external_id.split("/"))
        assert record.raw_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert hashlib.sha256(store.get(record.raw_object_path)).hexdigest() == record.raw_sha256
        assert record.ingest_run_id == run.id
    assert not any(key is not None and "truth" in key for key in records)

    # Every case-level row references the record of the file it came from.
    for table, (name, _) in CASE_LEVEL_FILES.items():
        model = Base.metadata.tables[table]
        record_ids = {
            row[0] for row in session.execute(select(model.c.source_record_id).distinct()).all()
        }
        assert record_ids == {records[f"source/{name}"].id}, table
    for event in session.scalars(select(JusticeEvent)):
        assert event.source_record_id in {
            records["source/charges.csv"].id,
            records["source/events.csv"].id,
        }
    for person in session.scalars(select(Person)):
        assert person.source_record_id == records["source/participants.csv"].id

    # Nothing about a participant reaches a log line.
    rendered = captured_logs.getvalue()
    assert "ingest.succeeded" in rendered
    for participant in _rows("participants.csv"):
        assert participant["full_name"].strip() not in rendered
        if participant["date_of_birth"]:
            assert participant["date_of_birth"] not in rendered
    for value_hash in session.scalars(select(PersonIdentifier.value_hash)):
        assert value_hash not in rendered
    assert TEST_IDENTIFIER_PEPPER not in rendered


def test_person_rows_hold_pseudonyms_and_hashes_only(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    assert _run(session, store).status is IngestRunStatus.SUCCEEDED
    columns = set(Base.metadata.tables["person"].c.keys())
    assert columns == {
        "id",
        "created_at",
        "updated_at",
        "public_person_key",
        "resolution_status",
        "resolution_confidence",
        "source_record_id",
        "merged_into_person_id",
    }
    live = {
        row[0]
        for row in session.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'person'")
        )
    }
    assert live == columns
    for person in session.scalars(select(Person)):
        assert re.fullmatch(r"[A-Za-z0-9_-]{16}", person.public_person_key)
        if person.merged_into_person_id is None:
            assert person.resolution_status in {"deterministic", "rule"}
            assert person.resolution_confidence is not None
        else:
            assert person.resolution_status == "merged"  # the planted split persons
    keys = list(session.scalars(select(Person.public_person_key)))
    assert len(keys) == len(set(keys)) == 42

    identifiers = list(session.scalars(select(PersonIdentifier)))
    assert all(HEX64.match(row.value_hash) for row in identifiers)
    assert all(row.encrypted_value is None for row in identifiers)
    by_person: dict[Any, set[tuple[str, str]]] = {}
    for identifier in identifiers:
        by_person.setdefault(identifier.person_id, set()).add(
            (identifier.identifier_type, identifier.value_hash)
        )
    # Exactly the hashes the source implies, computed independently, grouped the
    # way entity resolution merges the planted split persons (Step 3).
    expected = _expected_hashes()
    grouped = [set().union(*(expected[pid] for pid in group)) for group in _merged_groups()]
    assert Counter(frozenset(v) for v in by_person.values()) == Counter(
        frozenset(v) for v in grouped
    )
    # A stable identifier belongs to one person; name hashes may repeat (planted collisions).
    stable = [r.value_hash for r in identifiers if r.identifier_type == "source_participant_id"]
    assert len(stable) == len(set(stable)) == 42
    names = Counter(r.value_hash for r in identifiers if r.identifier_type == "full_name")
    assert max(names.values()) == 2  # the planted split and ambiguous pairs


def test_actors_attribution_and_children(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    assert _run(session, store).status is IngestRunStatus.SUCCEEDED
    prosecutor = list(
        session.scalars(select(Decision).where(Decision.actor_type == ActorType.PROSECUTOR))
    )
    assert len(prosecutor) == 15
    assert all(
        d.decision_type == "dismissal"
        and d.judge_id is None
        and d.judicial_discretion_classification == "non_judicial"
        for d in prosecutor
    )
    statutory = list(
        session.scalars(
            select(Decision).where(Decision.actor_type == ActorType.LEGISLATURE_OR_MANDATORY_RULE)
        )
    )
    assert len(statutory) == 8
    assert all(d.judicial_discretion_classification == "mandatory" for d in statutory)
    unknown = list(
        session.scalars(select(Decision).where(Decision.actor_type == ActorType.UNKNOWN))
    )
    assert {d.source_row_id for d in unknown} == {"DC-000025", "DC-000038", "DC-000062"}

    releases = list(session.scalars(select(PretrialRelease)))
    assert len(releases) == _expected_counts()["pretrial_release"]
    decision_ids = {r.decision_id for r in releases}
    assert len(decision_ids) == len(releases)
    pretrial_decisions = list(
        session.scalars(select(Decision).where(Decision.decision_type == "pretrial_release"))
    )
    assert {d.id for d in pretrial_decisions} == decision_ids
    bonded = [r for r in releases if r.bond_amount is not None]
    assert bonded and all(r.release_type == "monetary_bond" for r in bonded)

    prosecutor_charges = list(
        session.scalars(select(Charge).where(Charge.disposition_actor == ActorType.PROSECUTOR))
    )
    assert prosecutor_charges and all(c.disposition == "dismissed" for c in prosecutor_charges)
    pending = list(session.scalars(select(Charge).where(Charge.disposition == "pending")))
    assert pending and all(c.disposed_at is None and c.disposition_actor is None for c in pending)

    # The duplicate case keeps the original spelling and one set of children.
    duplicate = session.scalar(select(Case).where(Case.case_number_normalized == "SYN-2019-000005"))
    assert duplicate is not None
    assert duplicate.case_number == "SYN-2019-000005"
    assert len(duplicate.parties) == 1
    assert {c.source_row_id for c in duplicate.charges} == {
        r["charge_id"]
        for r in _rows("charges.csv")
        if r["case_number"].upper().replace(" ", "-") == "SYN-2019-000005"
    }
    linked = list(
        session.scalars(select(Case).where(Case.related_case_number_normalized.is_not(None)))
    )
    assert {c.related_case_number_normalized for c in linked} == {
        "SYN-2020-000005",
        "SYN-2021-000007",
    }

    events = Counter(e.event_type for e in session.scalars(select(JusticeEvent)))
    assert events["failure_to_appear"] == 2
    assert events["revocation"] == 1
    assert events["new_case"] > 0 and events["reconviction"] > 0
    assert all(e.related_case_id is not None for e in session.scalars(select(JusticeEvent)))


# --- idempotency ------------------------------------------------------------------------


def test_second_and_forced_runs_create_and_update_nothing(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    first = _run(session, store)
    assert first.status is IngestRunStatus.SUCCEEDED, first.failure_reason
    snapshot = _counts(session)
    snapshot["justice_event"] = _count(session, "justice_event")
    snapshot["person_identifier"] = _count(session, "person_identifier")
    keys = {p.id: p.public_person_key for p in session.scalars(select(Person))}
    updated_at = {c.id: c.updated_at for c in session.scalars(select(Charge))}
    issues = len(_issues(session))

    second = _run(session, store)
    assert second.status is IngestRunStatus.SUCCEEDED, second.failure_reason
    assert (second.records_seen, second.records_created, second.records_updated) == (0, 0, 0)
    assert second.records_rejected == 0
    assert _count(session, "source_record") == 10

    forced = _run(session, store, force=True)
    assert forced.status is IngestRunStatus.SUCCEEDED, forced.failure_reason
    assert forced.records_seen == first.records_seen
    assert (forced.records_created, forced.records_updated, forced.records_rejected) == (0, 0, 0)

    session.expire_all()
    after = _counts(session)
    after["justice_event"] = _count(session, "justice_event")
    after["person_identifier"] = _count(session, "person_identifier")
    assert after == snapshot
    assert {p.id: p.public_person_key for p in session.scalars(select(Person))} == keys
    assert {c.id: c.updated_at for c in session.scalars(select(Charge))} == updated_at
    assert len(_issues(session)) == issues


def test_a_changed_file_updates_only_its_changed_rows(
    clean_session: Session, store: FilesystemRawObjectStore, tmp_path: Path
) -> None:
    session = clean_session
    first = _run(session, store)
    assert first.status is IngestRunStatus.SUCCEEDED, first.failure_reason

    edited = tmp_path / "edited"
    shutil.copytree(GOLDEN, edited)
    sentences = edited / "source" / "sentences.csv"
    with sentences.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    header = rows[0]
    rows[1][header.index("probation_days")] = "999"
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    sentences.write_text(out.getvalue(), encoding="utf-8")
    manifest = json.loads((edited / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["source/sentences.csv"] = hashlib.sha256(sentences.read_bytes()).hexdigest()
    (edited / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    second = _run(session, store, fixture=edited)
    assert second.status is IngestRunStatus.SUCCEEDED, second.failure_reason
    assert second.records_seen == 21  # only sentences.csv was re-parsed
    assert (second.records_created, second.records_updated) == (0, 1)
    changed = session.scalar(select(Sentence).where(Sentence.source_row_id == rows[1][0]))
    assert changed is not None and changed.probation_days == 999
    record = session.get(SourceRecord, changed.source_record_id)
    assert record is not None and record.ingest_run_id == second.id
    untouched = session.scalar(select(Sentence).where(Sentence.source_row_id == rows[2][0]))
    assert untouched is not None
    assert session.get(SourceRecord, untouched.source_record_id).ingest_run_id == first.id  # type: ignore[union-attr]


def test_manifest_drift_fails_the_run_before_anything_is_published(
    clean_session: Session, store: FilesystemRawObjectStore, tmp_path: Path
) -> None:
    session = clean_session
    drifted = tmp_path / "drifted"
    shutil.copytree(GOLDEN, drifted)
    cases = drifted / "source" / "cases.csv"
    cases.write_bytes(cases.read_bytes() + b"\n")
    run = _run(session, store, fixture=drifted)
    assert run.status is IngestRunStatus.FAILED
    assert run.failure_reason is not None
    assert "manifest drift: source/cases.csv: sha256 does not match" in run.failure_reason
    assert _count(session, "court_case") == 0
    assert _count(session, "person") == 0


def test_missing_header_fails_the_run_naming_it(
    clean_session: Session, store: FilesystemRawObjectStore, tmp_path: Path
) -> None:
    session = clean_session
    broken = tmp_path / "broken"
    shutil.copytree(GOLDEN, broken)
    charges = broken / "source" / "charges.csv"
    with charges.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    column = rows[0].index("severity")
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(row[:column] + row[column + 1 :] for row in rows)
    charges.write_text(out.getvalue(), encoding="utf-8")
    manifest = json.loads((broken / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["source/charges.csv"] = hashlib.sha256(charges.read_bytes()).hexdigest()
    (broken / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    run = _run(session, store, fixture=broken)
    assert run.status is IngestRunStatus.FAILED
    assert run.failure_reason is not None
    assert "source/charges.csv: missing expected header 'severity'" in run.failure_reason
    assert _count(session, "court_case") == 0


# --- data-quality issues -----------------------------------------------------------------


def test_planted_items_produce_exactly_the_predicted_issues(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    assert _run(session, store).status is IngestRunStatus.SUCCEEDED
    issues = _issues(session)
    by_code = Counter(issue.issue_code for issue in issues)
    planted = Counter(row["kind"] for row in _planted())
    assert by_code["case_number_duplicate"] == planted["duplicate_source_record"] == 3
    assert by_code["missing_judge_on_decision"] == planted["missing_judge"] == 3
    assert by_code["missing_disposition"] == planted["missing_disposition"] == 2
    assert by_code["unknown_category_measured"] == 2  # actor_type, discretion of the planted 3
    assert set(by_code) == {
        "case_number_duplicate",
        "missing_judge_on_decision",
        "missing_disposition",
        "unknown_category_measured",
    }
    assert not [issue for issue in issues if issue.severity is IssueSeverity.ERROR]

    severities = {issue.issue_code: issue.severity for issue in issues}
    assert severities["case_number_duplicate"] is IssueSeverity.INFO
    assert severities["missing_judge_on_decision"] is IssueSeverity.WARNING
    assert severities["missing_disposition"] is IssueSeverity.INFO

    for row in _planted():
        ids = dict(pair.split("=", 1) for pair in row["ids"].split(";"))
        if row["kind"] == "duplicate_source_record":
            case = session.scalar(
                select(Case).where(Case.case_number_normalized == ids["case_number"])
            )
            assert case is not None
            matching = [
                i
                for i in issues
                if i.issue_code == "case_number_duplicate" and i.entity_id == case.id
            ]
            assert len(matching) == 1 and ids["duplicate_case_number"] in matching[0].description
        elif row["kind"] == "missing_judge":
            decision = session.scalar(
                select(Decision).where(Decision.source_row_id == ids["decision_id"])
            )
            assert decision is not None and decision.actor_type is ActorType.UNKNOWN
            assert decision.judge_id is None
            assert any(
                i.issue_code == "missing_judge_on_decision" and i.entity_id == decision.id
                for i in issues
            )
        elif row["kind"] == "missing_disposition":
            charge = session.scalar(select(Charge).where(Charge.source_row_id == ids["charge_id"]))
            assert charge is not None and charge.disposition is None
            assert any(
                i.issue_code == "missing_disposition" and i.entity_id == charge.id for i in issues
            )
        elif row["kind"] == "missing_description":
            event = session.scalar(
                select(CourtEvent).where(CourtEvent.source_row_id == ids["event_id"])
            )
            assert event is not None and event.description is None
            assert not any(i.entity_id == event.id for i in issues)
    for issue in issues:
        assert not HEX64.search(issue.description)
        for participant in _rows("participants.csv"):
            assert participant["full_name"].strip() not in issue.description


# --- coverage and pipeline step 13 -------------------------------------------------------


def test_the_run_writes_the_coverage_window_and_observable_outcomes(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    assert _run(session, store).status is IngestRunStatus.SUCCEEDED
    source = session.scalar(select(Source).where(Source.name == SOURCE_ID))
    assert source is not None
    assert (source.coverage_start, source.coverage_end) == (date(2019, 1, 1), date(2021, 12, 31))
    assert source.observable_outcomes == [
        "new_case",
        "new_charge",
        "reconviction",
        "failure_to_appear",
        "revocation",
    ]
    # An unchanged rerun rewrites neither column.
    updated_at = source.updated_at
    assert _run(session, store).status is IngestRunStatus.SUCCEEDED
    session.expire_all()
    source = session.scalar(select(Source).where(Source.name == SOURCE_ID))
    assert source is not None and source.updated_at == updated_at


def test_an_fjc_run_leaves_coverage_null_and_computes_nothing(
    clean_session: Session, store: FilesystemRawObjectStore, tmp_path: Path
) -> None:
    session = clean_session
    settings = _settings(metrics_recompute_on_ingest=True, snapshot_dir=tmp_path / "snapshots")
    run = run_ingest(
        "fjc", session=session, store=store, settings=settings, from_fixture=FJC_FIXTURES
    )
    assert run.status is IngestRunStatus.SUCCEEDED, run.failure_reason
    source = session.scalar(select(Source).where(Source.name == "fjc"))
    assert source is not None
    assert source.coverage_start is None and source.coverage_end is None
    assert source.observable_outcomes == []
    assert run.metrics_snapshot_id is None
    assert _count(session, "metric_observation") == 0
    assert not (tmp_path / "snapshots").exists()


def _current_by_subject(session: Session) -> dict[tuple[str, Any], set[Any]]:
    """Current observation ids per (subject type, subject id)."""
    grouped: dict[tuple[str, Any], set[Any]] = {}
    for row in session.execute(
        select(
            MetricObservation.subject_type, MetricObservation.subject_id, MetricObservation.id
        ).where(MetricObservation.superseded_at.is_(None))
    ).all():
        grouped.setdefault((row[0].value, row[1]), set()).add(row[2])
    return grouped


def _judge_id(session: Session, code: str) -> Any:
    judge_id = session.scalar(
        select(Judge.id).where(Judge.external_ids["synthetic_judge_code"].astext == code)
    )
    assert judge_id is not None, code
    return judge_id


def test_step_13_recomputes_only_the_subjects_a_run_changed(
    clean_session: Session,
    store: FilesystemRawObjectStore,
    tmp_path: Path,
    captured_logs: io.StringIO,
) -> None:
    session = clean_session
    settings = _settings(metrics_recompute_on_ingest=True, snapshot_dir=tmp_path / "snapshots")
    # 1. The golden ingest publishes observations for every golden judge and court.
    first = _run(session, store, settings=settings)
    assert first.status is IngestRunStatus.SUCCEEDED, first.failure_reason
    assert first.metrics_snapshot_id is not None
    before = _current_by_subject(session)
    judges = {row["judge_code"] for row in _rows("judges.csv")}
    courts = {row["court_code"] for row in _rows("courts.csv")}
    assert {key for key in before if key[0] == SubjectType.JUDGE.value} == {
        (SubjectType.JUDGE.value, _judge_id(session, code)) for code in judges
    }
    assert sum(1 for key in before if key[0] == SubjectType.COURT.value) == len(courts)
    assert all(ids for ids in before.values())
    assert _count(session, "metric_observation") == sum(len(ids) for ids in before.values())
    assert (tmp_path / "snapshots").is_dir()

    # 2. An identical rerun touches no subject: nothing is superseded or written.
    second = _run(session, store, settings=settings)
    assert second.status is IngestRunStatus.SUCCEEDED, second.failure_reason
    assert second.metrics_snapshot_id is None
    session.expire_all()
    assert _current_by_subject(session) == before
    assert _count(session, "metric_observation") == sum(len(ids) for ids in before.values())

    # 3. Moving one assignment from J-0001 to J-0002 supersedes exactly those two
    #    judges' observations; every other subject (the courts included) stays.
    edited = tmp_path / "edited"
    shutil.copytree(GOLDEN, edited)
    assignments = edited / "source" / "assignments.csv"
    with assignments.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    header = rows[0]
    judge_column = header.index("judge_code")
    target = next(row for row in rows[1:] if row[judge_column] == "J-0001")
    case_number = target[header.index("case_number")]
    assert all(
        row[judge_column] != "J-0002"
        for row in rows[1:]
        if row[header.index("case_number")] == case_number
    )
    target[judge_column] = "J-0002"
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    assignments.write_text(out.getvalue(), encoding="utf-8")
    manifest = json.loads((edited / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["source/assignments.csv"] = hashlib.sha256(
        assignments.read_bytes()
    ).hexdigest()
    (edited / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    third = _run(session, store, fixture=edited, settings=settings)
    assert third.status is IngestRunStatus.SUCCEEDED, third.failure_reason
    assert third.metrics_snapshot_id is not None
    assert third.metrics_snapshot_id != first.metrics_snapshot_id
    session.expire_all()
    after = _current_by_subject(session)
    changed = {key for key in before if before[key] != after.get(key)}
    assert changed == {
        (SubjectType.JUDGE.value, _judge_id(session, "J-0001")),
        (SubjectType.JUDGE.value, _judge_id(session, "J-0002")),
    }
    superseded = {
        row[0]
        for row in session.execute(
            select(MetricObservation.id).where(MetricObservation.superseded_at.is_not(None))
        ).all()
    }
    assert superseded == set().union(*(before[key] for key in changed))
    # Every touched case's subjects were recomputed (the impacted set is the
    # whole golden world here: every assignment row was re-parsed); only the
    # two judges' numbers changed.
    lines = [
        json.loads(line)
        for line in captured_logs.getvalue().splitlines()
        if '"ingest.metrics.recomputed"' in line
    ]
    assert [entry["impacted"] for entry in lines] == [len(judges) + len(courts)] * 2
    assert lines[-1]["subjects_published"] == 2
    assert lines[-1]["subjects_unchanged"] == len(judges) + len(courts) - 2


# --- refusals ---------------------------------------------------------------------------


def test_the_real_synthetic_connector_is_refused_in_production(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    run = run_ingest(
        SOURCE_ID,
        session=clean_session,
        store=store,
        settings=_settings("production"),
        connector=SyntheticConnector(GOLDEN, pepper=PEPPER),
    )
    assert run.status is IngestRunStatus.REFUSED
    assert run.failure_reason == "synthetic sources are refused in production"
    assert _count(clean_session, "court_case") == 0
    assert _count(clean_session, "source_record") == 0


def test_seed_is_refused_in_production_and_generates_nothing(
    test_settings: Settings,
    migrated_database: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = test_settings
    monkeypatch.chdir(tmp_path)
    env = {
        "JUDGEMETRICS_ENV": "production",
        "JUDGEMETRICS_DATABASE_URL": settings.database_url,
        "JUDGEMETRICS_INGEST_DATABASE_URL": settings.effective_ingest_database_url
        if settings.ingest_database_url
        else settings.effective_admin_database_url,
        "JUDGEMETRICS_RAW_STORE_URL": f"file://{(tmp_path / 'lake').as_posix()}",
        "JUDGEMETRICS_LOG_FORMAT": "json",
        "JUDGEMETRICS_IDENTIFIER_PEPPER": TEST_IDENTIFIER_PEPPER,
    }
    result = CliRunner().invoke(app, ["seed", "--scale", "tiny"], env=env)
    run_id = re.search(r"^run ([0-9a-f-]{36}) ", result.output, re.MULTILINE)
    try:
        assert result.exit_code == 1, result.output
        assert "status=refused" in result.output
        assert "synthetic sources are refused in production" in result.output
        assert not (tmp_path / "data").exists()
    finally:
        if run_id is not None:
            with Session(migrated_database) as session:
                session.execute(delete(IngestRun).where(IngestRun.id == run_id.group(1)))
                session.commit()


def test_seed_needs_the_pepper(
    test_settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    env = {
        "JUDGEMETRICS_ENV": "test",
        "JUDGEMETRICS_DATABASE_URL": test_settings.database_url,
        "JUDGEMETRICS_IDENTIFIER_PEPPER": "",
    }
    result = CliRunner().invoke(app, ["seed", "--scale", "tiny"], env=env)
    assert result.exit_code == 2, result.output
    assert "JUDGEMETRICS_IDENTIFIER_PEPPER is not configured" in result.output
    assert not (tmp_path / "data").exists()


# --- grants ------------------------------------------------------------------------------


def test_app_role_reads_the_new_public_columns_and_never_person_identifier(
    migrated_database: Engine, app_engine: Engine
) -> None:
    with app_engine.connect() as connection:
        if connection.execute(text("SELECT current_user")).scalar() != "judgemetrics_app":
            pytest.skip("JUDGEMETRICS_DATABASE_URL does not connect as judgemetrics_app")
        for table, column in (
            ("court_case", "related_case_number_normalized"),
            ("case_party", "source_row_id"),
            ("judge_assignment", "source_row_id"),
            ("charge", "source_row_id"),
            ("charge", "disposition_actor"),
            ("court_event", "source_row_id"),
            ("decision", "source_row_id"),
            ("sentence", "source_row_id"),
            ("person", "source_record_id"),
            ("justice_event", "event_type"),
        ):
            connection.execute(text(f"SELECT {column} FROM {table} LIMIT 1"))  # noqa: S608 - fixed names
        with pytest.raises(ProgrammingError, match="permission denied"):
            connection.execute(text("SELECT value_hash FROM person_identifier LIMIT 1"))
