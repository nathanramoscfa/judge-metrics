# src/judgemetrics/ingest/retire.py
"""``judgemetrics ingest retire``: remove a source's rows so it can be ingested afresh.

Some sources cannot be updated in place. The Cook County State's Attorney hashes
``CASE_ID`` and ``CASE_PARTICIPANT_ID`` independently for every release, so a
re-publication would re-key every case and participant; the synthetic generator
changes what a seed draws whenever ``GENERATOR_VERSION`` is bumped. Ingesting such a
source over its older rows leaves the old ones behind (issue #36). ``retire_source``
deletes, in the dependency order the test helper ``purge_source`` established, everything
derived from one registered source:

1. its metric observations, their member families (the family rows cascade), its fitted
   expected-outcome models,
   its coverage statistics, and the snapshot rows nothing cites any more;
2. its data-quality issues, then its case-level rows — justice events, pretrial releases,
   sentences, decisions, court events, charges, assignments, case parties (their restricted
   attributes go with them: the foreign key cascades), and cases;
3. the persons it created, with their identifier rows and resolution candidates (refused
   when a row of another source still points at one);
4. the reference rows nothing else references — judge services, judges, courts, and
   jurisdictions another source's rows do not cite;
5. its source records, except the ones a surviving row still cites.

It keeps the ``source`` row, the ``ingest_run`` history, the raw lake, and the audit log,
and appends one ``ingest.retire`` audit row with the counts. It runs as the ingest role,
takes a source id the registry knows (a name is never taken from data), deletes by bound
parameters only, and is refused when ``JUDGEMETRICS_ENV=production``. The caller commits;
any failure leaves the session to roll back, so a retire is all or nothing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import Base
from judgemetrics.entity_resolution.audit import write_audit
from judgemetrics.ingest.base import IngestError
from judgemetrics.ingest.registry import UnknownSourceError, registered_sources

ACTION_RETIRE = "ingest.retire"
ENTITY_SOURCE = "source"
DEFAULT_ACTOR = "cli:ingest-retire"

TABLES = Base.metadata.tables
SOURCE = TABLES["source"]
SOURCE_RECORD = TABLES["source_record"]
INGEST_RUN = TABLES["ingest_run"]
ISSUE = TABLES["data_quality_issue"]
PERSON = TABLES["person"]
CANDIDATE = TABLES["entity_resolution_candidate"]

# Case-level tables that carry ``source_record_id``, children first.
CASE_LEVEL = (
    "justice_event",
    "sentence",
    "decision",
    "court_event",
    "charge",
    "judge_assignment",
    "case_party",
    "court_case",
)
# Where each reference table is cited by another table's rows.
REFERENCED_BY: dict[str, tuple[tuple[str, str], ...]] = {
    "judge": (
        ("judge_service", "judge_id"),
        ("judge_assignment", "judge_id"),
        ("decision", "judge_id"),
        ("sentence", "judge_id"),
        ("court_event", "judge_id"),
        ("charge", "judge_id"),
    ),
    "court": (("judge_service", "court_id"), ("court_case", "court_id")),
    "jurisdiction": (
        ("court", "jurisdiction_id"),
        ("source", "jurisdiction_id"),
        ("jurisdiction", "parent_jurisdiction_id"),
    ),
}
PERSON_REFERENCES = (
    ("case_party", "person_id"),
    ("charge", "person_id"),
    ("court_event", "person_id"),
    ("decision", "person_id"),
    ("sentence", "person_id"),
    ("justice_event", "person_id"),
    ("person", "merged_into_person_id"),
)


class RetireError(IngestError):
    """The source cannot be retired (production, or a row of another source depends on it)."""


@dataclass(frozen=True, slots=True)
class RetireResult:
    """What a retire removed, by table (zero counts omitted), and the audit row's id."""

    source: str
    deleted: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.deleted.values())


def _count(deleted: dict[str, int], table: str, result: sa.Result[Any]) -> None:
    rows = cast("sa.CursorResult[Any]", result).rowcount
    if rows:
        deleted[table] = deleted.get(table, 0) + rows


def _cited_by_others(
    table: sa.Table, key: sa.Column[object], pairs: Iterable[tuple[str, str]]
) -> sa.ColumnElement[bool]:
    """True when no surviving row of ``pairs`` references ``table.c[key]``."""
    clauses: list[sa.ColumnElement[bool]] = []
    for name, column in pairs:
        referencing = TABLES[name]
        clauses.append(~exists().where(referencing.c[column] == key))
    return sa.and_(*clauses)


def _source_record_references() -> list[sa.Table]:
    """Every table with a foreign key to ``source_record.id``, the restricted schema included."""
    tables: list[sa.Table] = []
    for table in TABLES.values():
        if table is SOURCE_RECORD:
            continue
        if any(fk.column.table is SOURCE_RECORD for fk in table.foreign_keys):
            tables.append(table)
    return tables


def retire_source(
    session: Session,
    source_name: str,
    *,
    settings: Settings,
    actor: str = DEFAULT_ACTOR,
) -> RetireResult:
    """Delete everything derived from ``source_name`` (see the module docstring); the caller commits."""
    if settings.env == "production":
        msg = "retiring a source is refused when JUDGEMETRICS_ENV=production"
        raise RetireError(msg)
    if source_name not in {source.source_id for source in registered_sources()}:
        raise UnknownSourceError(source_name)
    deleted: dict[str, int] = {}
    source_id = session.scalar(select(SOURCE.c.id).where(SOURCE.c.name == source_name))
    if source_id is None:
        return RetireResult(source=source_name)
    records = select(SOURCE_RECORD.c.id).where(SOURCE_RECORD.c.source_id == source_id)

    # 1. Metrics: observations (members cascade), models, coverage statistics, and the
    #    snapshots nothing cites.
    observation = TABLES["metric_observation"]
    family = TABLES["metric_member_family"]
    model = TABLES["outcome_model"]
    coverage = TABLES["coverage_statistic"]
    snapshot = TABLES["metric_snapshot"]
    _count(
        deleted,
        "metric_observation",
        session.execute(delete(observation).where(observation.c.source_id == source_id)),
    )
    # The observations cited the families (RESTRICT): the families, and their rows, go after.
    _count(
        deleted,
        "metric_member_family",
        session.execute(delete(family).where(family.c.source_id == source_id)),
    )
    _count(
        deleted,
        "outcome_model",
        session.execute(delete(model).where(model.c.source_id == source_id)),
    )
    _count(
        deleted,
        "coverage_statistic",
        session.execute(delete(coverage).where(coverage.c.source_id == source_id)),
    )
    session.execute(
        update(INGEST_RUN)
        .where(INGEST_RUN.c.source_id == source_id)
        .values(metrics_snapshot_id=None)
    )
    cited_snapshots = sa.union(
        select(observation.c.snapshot_id),
        select(family.c.snapshot_id),
        select(model.c.snapshot_id),
        select(coverage.c.snapshot_id),
        select(INGEST_RUN.c.metrics_snapshot_id).where(
            INGEST_RUN.c.metrics_snapshot_id.is_not(None)
        ),
    )
    _count(
        deleted,
        "metric_snapshot",
        session.execute(delete(snapshot).where(~snapshot.c.id.in_(cited_snapshots))),
    )

    # 2. Issues, then the case-level rows (pretrial releases hang off decisions).
    _count(
        deleted,
        "data_quality_issue",
        session.execute(delete(ISSUE).where(ISSUE.c.source_record_id.in_(records))),
    )
    decision = TABLES["decision"]
    pretrial = TABLES["pretrial_release"]
    decisions = select(decision.c.id).where(decision.c.source_record_id.in_(records))
    for name in CASE_LEVEL:
        if name == "decision":
            _count(
                deleted,
                "pretrial_release",
                session.execute(delete(pretrial).where(pretrial.c.decision_id.in_(decisions))),
            )
        table = TABLES[name]
        _count(
            deleted,
            name,
            session.execute(delete(table).where(table.c.source_record_id.in_(records))),
        )

    # 3. Persons the source created: identifiers, candidates, merge pointers, then the rows.
    persons = select(PERSON.c.id).where(PERSON.c.source_record_id.in_(records))
    identifier = TABLES["person_identifier"]
    _count(
        deleted,
        "person_identifier",
        session.execute(delete(identifier).where(identifier.c.person_id.in_(persons))),
    )
    _count(
        deleted,
        "entity_resolution_candidate",
        session.execute(
            delete(CANDIDATE).where(
                CANDIDATE.c.left_record_id.in_(persons) | CANDIDATE.c.right_record_id.in_(persons)
            )
        ),
    )
    session.execute(
        update(PERSON)
        .where(PERSON.c.source_record_id.in_(records))
        .values(merged_into_person_id=None)
    )
    _count(
        deleted,
        "person",
        session.execute(
            delete(PERSON).where(
                PERSON.c.source_record_id.in_(records),
                _cited_by_others(PERSON, PERSON.c.id, PERSON_REFERENCES),
            )
        ),
    )
    remaining = session.scalar(
        select(sa.func.count()).select_from(PERSON).where(PERSON.c.source_record_id.in_(records))
    )
    if remaining:
        msg = f"{remaining} persons of {source_name} are still referenced by rows of another source"
        raise RetireError(msg)

    # 4. Reference rows nothing else cites (services first: they cite judges and courts).
    service = TABLES["judge_service"]
    _count(
        deleted,
        "judge_service",
        session.execute(delete(service).where(service.c.source_record_id.in_(records))),
    )
    for name in ("judge", "court", "jurisdiction"):
        table = TABLES[name]
        _count(
            deleted,
            name,
            session.execute(
                delete(table).where(
                    table.c.source_record_id.in_(records),
                    _cited_by_others(table, table.c.id, REFERENCED_BY[name]),
                )
            ),
        )

    # 5. The source's records, except the ones a surviving row still cites.
    uncited = [
        ~exists().where(table.c.source_record_id == SOURCE_RECORD.c.id)
        for table in _source_record_references()
    ]
    _count(
        deleted,
        "source_record",
        session.execute(
            delete(SOURCE_RECORD).where(SOURCE_RECORD.c.source_id == source_id, *uncited)
        ),
    )

    write_audit(
        session,
        actor=actor,
        action=ACTION_RETIRE,
        entity_type=ENTITY_SOURCE,
        entity_id=source_id,
        payload={"source": source_name, "deleted": dict(sorted(deleted.items()))},
    )
    return RetireResult(source=source_name, deleted=dict(sorted(deleted.items())))
