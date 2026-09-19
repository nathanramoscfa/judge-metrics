# src/judgemetrics/metrics/provenance.py
"""The provenance trace: from a published number back to the raw artifacts.

``trace(session, observation_id)`` reconstructs the brief's chain
(``<provenance_requirement>``; ROADMAP.md §5 "Provenance chain") for one
``metric_observation`` in three statements, whatever the observation
holds:

1. the observation with its definition (slug, version, kind, threshold),
   its snapshot (content hash, label, export time, code version, storage
   URI, row counts), and its source (key, type, coverage window,
   observable outcomes);
2. its members, each resolved through an outer join to the canonical row
   its ``member_kind`` names — ``decision``, ``charge``, ``court_case``,
   ``sentence``, ``court_event``, ``justice_event`` — for the case the row
   belongs to (a justice event's ``related_case_id``) and the row's
   ``source_record_id``; a member whose row no longer exists resolves to
   nothing and is counted as unresolved;
3. the distinct source records behind those rows, joined to their source:
   external id, sha256, retrieval time, parser version, run, and the
   artifact URI the run recorded. The source systems listed are the
   observation's own source plus any other source a member's record
   belongs to.

The trace is ``complete`` when every member resolved to a row, every row
resolved to a source record, and every source record carries a sha256
digest of the stored artifact — the rule ``publish.check_chain`` enforces
before an observation is written, re-checked here against the live
tables (``tests/golden/test_golden_provenance.py`` asserts both). Members
are entity ids and the trace names no person, no hash of a person
identifier, and never the lake's storage key (``raw_object_path`` is not
selected). ``render`` prints the chain top-down in the brief's order for
``judgemetrics provenance trace``; ``as_dict`` is its ``--json`` form and
what the API's ``ObservationProvenance`` is built from.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, case, select
from sqlalchemy.orm import Session

from judgemetrics.db.models import SYNTHETIC_SOURCE_TYPE, Base
from judgemetrics.metrics.snapshot import HEX64

DEFINITION = Base.metadata.tables["metric_definition"]
SNAPSHOT = Base.metadata.tables["metric_snapshot"]
OBSERVATION = Base.metadata.tables["metric_observation"]
MEMBER = Base.metadata.tables["metric_observation_member"]
SOURCE = Base.metadata.tables["source"]
SOURCE_RECORD = Base.metadata.tables["source_record"]
DECISION = Base.metadata.tables["decision"]
CHARGE = Base.metadata.tables["charge"]
COURT_CASE = Base.metadata.tables["court_case"]
SENTENCE = Base.metadata.tables["sentence"]
COURT_EVENT = Base.metadata.tables["court_event"]
JUSTICE_EVENT = Base.metadata.tables["justice_event"]

# member_kind → (the canonical table, its case column). The order is the
# brief's chain order for the rendered output.
MEMBER_TABLES: tuple[tuple[str, Any, Any], ...] = (
    ("decision", DECISION, DECISION.c.case_id),
    ("charge", CHARGE, CHARGE.c.case_id),
    ("court_case", COURT_CASE, COURT_CASE.c.id),
    ("sentence", SENTENCE, SENTENCE.c.case_id),
    ("court_event", COURT_EVENT, COURT_EVENT.c.case_id),
    ("justice_event", JUSTICE_EVENT, JUSTICE_EVENT.c.related_case_id),
)
STATEMENTS = 3
PUBLIC_URI_SCHEMES = ("http://", "https://")


class TraceError(RuntimeError):
    """The observation id is malformed or names no observation."""


@dataclass(frozen=True, slots=True)
class TracedObservation:
    id: uuid.UUID
    slug: str
    name: str
    version: str
    kind: str
    unit: str
    subject_type: str
    subject_id: uuid.UUID
    source: str
    synthetic: bool
    period_start: date
    period_end: date
    window_days: int | None
    dimension_value: str | None
    eligible_count: int
    cohort_size: int
    observed_count: int
    observed_rate: Decimal | None
    value: Decimal | None
    distribution: dict[str, int] | None
    lower: Decimal | None
    upper: Decimal | None
    suppressed: bool
    suppression_threshold: int
    outcome: str | None
    methodology_version: str
    registry_version: int
    code_version: str
    computed_at: datetime
    superseded_at: datetime | None


@dataclass(frozen=True, slots=True)
class TracedSnapshot:
    id: uuid.UUID
    content_hash: str
    label: str | None
    exported_at: datetime
    code_version: str
    registry_version: int
    methodology_version: str
    storage_uri: str
    row_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class TracedMember:
    kind: str
    id: uuid.UUID
    counted: bool
    followed: bool
    case_id: uuid.UUID | None
    source_record_id: uuid.UUID | None

    @property
    def resolved(self) -> bool:
        return self.source_record_id is not None


@dataclass(frozen=True, slots=True)
class MemberGroup:
    kind: str
    members: int
    counted: int
    followed: int
    resolved: int
    case_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class TracedSourceRecord:
    id: uuid.UUID
    source: str
    external_record_id: str | None
    raw_sha256: str
    retrieved_at: datetime
    parser_version: str
    ingest_run_id: uuid.UUID
    artifact_uri: str | None

    @property
    def has_artifact(self) -> bool:
        return bool(HEX64.match(self.raw_sha256))

    @property
    def public_artifact_uri(self) -> str | None:
        """The URI when it is a public http(s) URL; a local path is the operator's."""
        if self.artifact_uri and self.artifact_uri.startswith(PUBLIC_URI_SCHEMES):
            return self.artifact_uri
        return None


@dataclass(frozen=True, slots=True)
class TracedSource:
    source: str
    owner: str
    source_type: str
    synthetic: bool
    coverage_start: date | None
    coverage_end: date | None
    observable_outcomes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObservationTrace:
    """The chain, top-down. ``complete`` is the publishability rule re-checked."""

    observation: TracedObservation
    snapshot: TracedSnapshot
    members: tuple[TracedMember, ...]
    source_records: tuple[TracedSourceRecord, ...]
    sources: tuple[TracedSource, ...]
    unresolved_members: int = 0
    unresolved_records: int = 0
    statements: int = STATEMENTS
    groups: tuple[MemberGroup, ...] = field(default_factory=tuple)

    @property
    def complete(self) -> bool:
        return (
            self.unresolved_members == 0
            and self.unresolved_records == 0
            and all(record.has_artifact for record in self.source_records)
        )

    @property
    def case_ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(sorted({m.case_id for m in self.members if m.case_id is not None}, key=str))

    def as_dict(self) -> dict[str, Any]:
        """The JSON form of the chain (``--json``), in the brief's order."""
        observation = self.observation
        return {
            "observation": {
                "id": str(observation.id),
                "slug": observation.slug,
                "name": observation.name,
                "version": observation.version,
                "kind": observation.kind,
                "unit": observation.unit,
                "subject_type": observation.subject_type,
                "subject_id": str(observation.subject_id),
                "source": observation.source,
                "synthetic": observation.synthetic,
                "period_start": observation.period_start.isoformat(),
                "period_end": observation.period_end.isoformat(),
                "window_days": observation.window_days,
                "dimension_value": observation.dimension_value,
                "eligible_count": observation.eligible_count,
                "cohort_size": observation.cohort_size,
                "observed_count": observation.observed_count,
                "observed_rate": _number(observation.observed_rate),
                "value": _number(observation.value),
                "distribution": observation.distribution,
                "lower": _number(observation.lower),
                "upper": _number(observation.upper),
                "suppressed": observation.suppressed,
                "suppression_threshold": observation.suppression_threshold,
                "methodology_version": observation.methodology_version,
                "registry_version": observation.registry_version,
                "code_version": observation.code_version,
                "computed_at": observation.computed_at.isoformat(),
                "superseded_at": (
                    None
                    if observation.superseded_at is None
                    else observation.superseded_at.isoformat()
                ),
            },
            "snapshot": {
                "content_hash": self.snapshot.content_hash,
                "label": self.snapshot.label,
                "exported_at": self.snapshot.exported_at.isoformat(),
                "code_version": self.snapshot.code_version,
                "registry_version": self.snapshot.registry_version,
                "methodology_version": self.snapshot.methodology_version,
                "storage_uri": self.snapshot.storage_uri,
                "row_counts": dict(self.snapshot.row_counts),
            },
            "members": [
                {
                    "member_kind": group.kind,
                    "members": group.members,
                    "counted": group.counted,
                    "followed": group.followed,
                    "resolved": group.resolved,
                    "case_ids": [str(case_id) for case_id in group.case_ids],
                }
                for group in self.groups
            ],
            "cases": [str(case_id) for case_id in self.case_ids],
            "source_records": [
                {
                    "id": str(record.id),
                    "source": record.source,
                    "external_record_id": record.external_record_id,
                    "raw_sha256": record.raw_sha256,
                    "retrieved_at": record.retrieved_at.isoformat(),
                    "parser_version": record.parser_version,
                    "ingest_run_id": str(record.ingest_run_id),
                    "artifact_uri": record.artifact_uri,
                }
                for record in self.source_records
            ],
            "sources": [
                {
                    "source": source.source,
                    "owner": source.owner,
                    "source_type": source.source_type,
                    "synthetic": source.synthetic,
                    "coverage_start": _day(source.coverage_start),
                    "coverage_end": _day(source.coverage_end),
                    "observable_outcomes": list(source.observable_outcomes),
                }
                for source in self.sources
            ],
            "unresolved_members": self.unresolved_members,
            "unresolved_records": self.unresolved_records,
            "complete": self.complete,
        }


def _number(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _optional_uuid(value: Any) -> uuid.UUID | None:
    return None if value is None else _uuid(value)


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def parse_observation_id(text: str) -> uuid.UUID:
    """The observation id as a UUID, or ``TraceError`` naming the problem (never the database)."""
    try:
        return uuid.UUID(str(text).strip())
    except ValueError as exc:
        msg = f"an observation id is a UUID; got {text!r}"
        raise TraceError(msg) from exc


# --- statements --------------------------------------------------------------------------


def observation_statement(observation_id: uuid.UUID) -> Select[Any]:
    """The observation with its definition, snapshot, and source: one statement."""
    return (
        select(
            OBSERVATION,
            DEFINITION.c.slug.label("slug"),
            DEFINITION.c.name.label("name"),
            DEFINITION.c.version.label("definition_version"),
            DEFINITION.c.kind.label("kind"),
            DEFINITION.c.unit.label("unit"),
            DEFINITION.c.outcome.label("outcome"),
            DEFINITION.c.suppression_threshold.label("suppression_threshold"),
            SNAPSHOT.c.content_hash.label("snapshot_hash"),
            SNAPSHOT.c.label.label("snapshot_label"),
            SNAPSHOT.c.exported_at.label("snapshot_exported_at"),
            SNAPSHOT.c.code_version.label("snapshot_code_version"),
            SNAPSHOT.c.registry_version.label("snapshot_registry_version"),
            SNAPSHOT.c.methodology_version.label("snapshot_methodology_version"),
            SNAPSHOT.c.storage_uri.label("snapshot_storage_uri"),
            SNAPSHOT.c.row_counts.label("snapshot_row_counts"),
            SOURCE.c.name.label("source_name"),
            SOURCE.c.owner.label("source_owner"),
            SOURCE.c.source_type.label("source_type"),
            SOURCE.c.coverage_start.label("source_coverage_start"),
            SOURCE.c.coverage_end.label("source_coverage_end"),
            SOURCE.c.observable_outcomes.label("source_observable_outcomes"),
        )
        .join(DEFINITION, DEFINITION.c.id == OBSERVATION.c.metric_definition_id)
        .join(SNAPSHOT, SNAPSHOT.c.id == OBSERVATION.c.snapshot_id)
        .join(SOURCE, SOURCE.c.id == OBSERVATION.c.source_id)
        .where(OBSERVATION.c.id == observation_id)
    )


def resolved_members_statement(observation_id: uuid.UUID) -> Select[Any]:
    """Every member with the case and source record its canonical row names: one statement.

    Each member table is outer-joined on ``member_kind`` and ``member_id``,
    so a member whose row was deleted yields null ``case_id`` and
    ``source_record_id`` rather than vanishing from the count.
    """
    stmt = select(
        MEMBER.c.member_kind,
        MEMBER.c.member_id,
        MEMBER.c.counted,
        MEMBER.c.followed,
        case(
            *(
                (MEMBER.c.member_kind == kind, case_column)
                for kind, _, case_column in MEMBER_TABLES
            ),
            else_=None,
        ).label("case_id"),
        case(
            *(
                (MEMBER.c.member_kind == kind, table.c.source_record_id)
                for kind, table, _ in MEMBER_TABLES
            ),
            else_=None,
        ).label("source_record_id"),
    ).select_from(MEMBER)
    for kind, table, _ in MEMBER_TABLES:
        stmt = stmt.outerjoin(
            table, and_(MEMBER.c.member_kind == kind, table.c.id == MEMBER.c.member_id)
        )
    return stmt.where(MEMBER.c.observation_id == observation_id).order_by(
        MEMBER.c.member_kind, MEMBER.c.member_id
    )


def source_records_statement(observation_id: uuid.UUID) -> Select[Any]:
    """The distinct source records behind the members with their sources: one statement.

    Built over ``resolved_members_statement`` as a subquery rather than an
    ``IN`` list of record ids, so an observation with thousands of members
    never exceeds the bind-parameter limit. ``raw_object_path`` — the
    lake's internal storage key — is not selected.
    """
    resolved = resolved_members_statement(observation_id).order_by(None).subquery("resolved")
    return (
        select(
            SOURCE_RECORD.c.id,
            SOURCE.c.name.label("source_name"),
            SOURCE_RECORD.c.external_record_id,
            SOURCE_RECORD.c.raw_sha256,
            SOURCE_RECORD.c.retrieved_at,
            SOURCE_RECORD.c.parser_version,
            SOURCE_RECORD.c.ingest_run_id,
            SOURCE_RECORD.c.metadata["uri"].astext.label("artifact_uri"),
            SOURCE.c.owner.label("source_owner"),
            SOURCE.c.source_type,
            SOURCE.c.coverage_start,
            SOURCE.c.coverage_end,
            SOURCE.c.observable_outcomes,
        )
        .select_from(resolved)
        .join(SOURCE_RECORD, SOURCE_RECORD.c.id == resolved.c.source_record_id)
        .join(SOURCE, SOURCE.c.id == SOURCE_RECORD.c.source_id)
        .distinct()
        .order_by(
            SOURCE_RECORD.c.retrieved_at.desc(),
            SOURCE_RECORD.c.external_record_id,
            SOURCE_RECORD.c.id,
        )
    )


# --- the trace ---------------------------------------------------------------------------


def _group(members: Sequence[TracedMember]) -> tuple[MemberGroup, ...]:
    order = [kind for kind, _, _ in MEMBER_TABLES]
    groups: list[MemberGroup] = []
    for kind in order:
        of_kind = [m for m in members if m.kind == kind]
        if not of_kind:
            continue
        groups.append(
            MemberGroup(
                kind=kind,
                members=len(of_kind),
                counted=sum(1 for m in of_kind if m.counted),
                followed=sum(1 for m in of_kind if m.followed),
                resolved=sum(1 for m in of_kind if m.resolved),
                case_ids=tuple(
                    sorted({m.case_id for m in of_kind if m.case_id is not None}, key=str)
                ),
            )
        )
    return tuple(groups)


def trace(session: Session, observation_id: uuid.UUID | str) -> ObservationTrace:
    """The chain behind ``observation_id`` (superseded observations trace too); ``TraceError`` if none."""
    oid = (
        observation_id
        if isinstance(observation_id, uuid.UUID)
        else parse_observation_id(observation_id)
    )
    row = session.execute(observation_statement(oid)).mappings().first()
    if row is None:
        msg = f"no metric observation has id {oid}"
        raise TraceError(msg)
    subject_type = row["subject_type"]
    observation = TracedObservation(
        id=_uuid(row["id"]),
        slug=str(row["slug"]),
        name=str(row["name"]),
        version=str(row["definition_version"]),
        kind=str(row["kind"]),
        unit=str(row["unit"]),
        subject_type=str(getattr(subject_type, "value", subject_type)),
        subject_id=_uuid(row["subject_id"]),
        source=str(row["source_name"]),
        synthetic=str(row["source_type"]) == SYNTHETIC_SOURCE_TYPE,
        period_start=row["period_start"],
        period_end=row["period_end"],
        window_days=row["window_days"],
        dimension_value=row["dimension_value"],
        eligible_count=int(row["eligible_count"]),
        cohort_size=int(row["cohort_size"]),
        observed_count=int(row["observed_count"]),
        observed_rate=_decimal(row["observed_rate"]),
        value=_decimal(row["value"]),
        distribution=(
            None
            if row["distribution"] is None
            else {str(k): int(v) for k, v in dict(row["distribution"]).items()}
        ),
        lower=_decimal(row["lower_confidence_bound"]),
        upper=_decimal(row["upper_confidence_bound"]),
        suppressed=bool(row["suppressed_flag"]),
        suppression_threshold=int(row["suppression_threshold"]),
        outcome=row["outcome"],
        methodology_version=str(row["methodology_version"]),
        registry_version=int(row["registry_version"]),
        code_version=str(row["code_version"]),
        computed_at=row["computed_at"],
        superseded_at=row["superseded_at"],
    )
    snapshot = TracedSnapshot(
        id=_uuid(row["snapshot_id"]),
        content_hash=str(row["snapshot_hash"]),
        label=row["snapshot_label"],
        exported_at=row["snapshot_exported_at"],
        code_version=str(row["snapshot_code_version"]),
        registry_version=int(row["snapshot_registry_version"]),
        methodology_version=str(row["snapshot_methodology_version"]),
        storage_uri=str(row["snapshot_storage_uri"]),
        row_counts={str(k): int(v) for k, v in dict(row["snapshot_row_counts"] or {}).items()},
    )
    members = tuple(
        TracedMember(
            kind=str(item["member_kind"]),
            id=_uuid(item["member_id"]),
            counted=bool(item["counted"]),
            followed=bool(item["followed"]),
            case_id=_optional_uuid(item["case_id"]),
            source_record_id=_optional_uuid(item["source_record_id"]),
        )
        for item in session.execute(resolved_members_statement(oid)).mappings()
    )
    records: list[TracedSourceRecord] = []
    # The observation's own source system first; the members' records may add
    # others (a metric over one source never does today) or, for an
    # observation with no member, none at all.
    sources: dict[str, TracedSource] = {
        observation.source: TracedSource(
            source=observation.source,
            owner=str(row["source_owner"]),
            source_type=str(row["source_type"]),
            synthetic=observation.synthetic,
            coverage_start=row["source_coverage_start"],
            coverage_end=row["source_coverage_end"],
            observable_outcomes=tuple(
                sorted(str(o) for o in (row["source_observable_outcomes"] or []))
            ),
        )
    }
    for item in session.execute(source_records_statement(oid)).mappings():
        records.append(
            TracedSourceRecord(
                id=_uuid(item["id"]),
                source=str(item["source_name"]),
                external_record_id=item["external_record_id"],
                raw_sha256=str(item["raw_sha256"]),
                retrieved_at=item["retrieved_at"],
                parser_version=str(item["parser_version"]),
                ingest_run_id=_uuid(item["ingest_run_id"]),
                artifact_uri=item["artifact_uri"],
            )
        )
        sources.setdefault(
            str(item["source_name"]),
            TracedSource(
                source=str(item["source_name"]),
                owner=str(item["source_owner"]),
                source_type=str(item["source_type"]),
                synthetic=str(item["source_type"]) == SYNTHETIC_SOURCE_TYPE,
                coverage_start=item["coverage_start"],
                coverage_end=item["coverage_end"],
                observable_outcomes=tuple(
                    sorted(str(o) for o in (item["observable_outcomes"] or []))
                ),
            ),
        )
    found_records = {record.id for record in records}
    referenced = {m.source_record_id for m in members if m.source_record_id is not None}
    return ObservationTrace(
        observation=observation,
        snapshot=snapshot,
        members=members,
        source_records=tuple(records),
        sources=tuple(sources[key] for key in sorted(sources)),
        unresolved_members=sum(1 for m in members if not m.resolved),
        unresolved_records=len(referenced - found_records),
        groups=_group(members),
    )


# --- rendering ---------------------------------------------------------------------------


def _fmt(value: Decimal | None) -> str:
    return "—" if value is None else f"{value:.6f}".rstrip("0").rstrip(".")


def render(traced: ObservationTrace) -> list[str]:
    """The chain as text lines, top-down: published metric → observation → members →
    cases → source records → raw artifacts → source systems."""
    o = traced.observation
    where = f"{o.slug} (version {o.version}) — {o.name}"
    window = "—" if o.window_days is None else f"{o.window_days} days"
    interval = "—" if o.lower is None or o.upper is None else f"[{_fmt(o.lower)}, {_fmt(o.upper)}]"
    lines = [
        f"published metric: {where}",
        f"observation {o.id}",
        f"  subject: {o.subject_type} {o.subject_id}",
        f"  source: {o.source} ({'synthetic' if o.synthetic else o.source})",
        f"  period: {o.period_start} to {o.period_end}; window: {window}; "
        f"dimension: {o.dimension_value or '—'}",
        f"  numerator / denominator: {o.observed_count} / {o.cohort_size}; "
        f"eligible: {o.eligible_count}; rate: {_fmt(o.observed_rate)}; interval: {interval}; "
        f"value: {_fmt(o.value)}",
        f"  suppressed: {'yes' if o.suppressed else 'no'} (threshold {o.suppression_threshold})",
        f"  versions: methodology {o.methodology_version}; registry {o.registry_version}; "
        f"code {o.code_version}",
        f"  computed: {o.computed_at.isoformat()}; superseded: "
        f"{o.superseded_at.isoformat() if o.superseded_at else 'no'}",
    ]
    if o.distribution is not None:
        lines.append(
            "  distribution: "
            + ", ".join(f"{key}={value}" for key, value in sorted(o.distribution.items()))
        )
    s = traced.snapshot
    rows = ", ".join(f"{name}={count}" for name, count in sorted(s.row_counts.items()))
    lines += [
        f"snapshot {s.content_hash}",
        f"  label: {s.label or '—'}; exported: {s.exported_at.isoformat()}; code {s.code_version}; "
        f"registry {s.registry_version}; methodology {s.methodology_version}",
        f"  storage: {s.storage_uri}",
        f"  rows: {rows}",
        f"eligible canonical events: {len(traced.members)} member(s)",
    ]
    for group in traced.groups:
        lines.append(
            f"  {group.kind}: {group.members} (counted {group.counted}, followed "
            f"{group.followed}); resolved {group.resolved}; cases {len(group.case_ids)}"
        )
    lines.append(f"canonical cases: {len(traced.case_ids)}")
    lines.extend(f"  {case_id}" for case_id in traced.case_ids)
    lines.append(f"source records: {len(traced.source_records)}")
    for record in traced.source_records:
        lines.append(
            f"  {record.id} {record.source} {record.external_record_id or '—'} "
            f"sha256={record.raw_sha256} retrieved={record.retrieved_at.isoformat()} "
            f"parser={record.parser_version} run={record.ingest_run_id}"
        )
        lines.append(f"    raw artifact: {record.artifact_uri or '—'}")
    lines.append(f"source systems: {len(traced.sources)}")
    for source in traced.sources:
        coverage = (
            "—"
            if source.coverage_start is None or source.coverage_end is None
            else f"{source.coverage_start} to {source.coverage_end}"
        )
        lines.append(
            f"  {source.source}: {source.owner}; type {source.source_type}; synthetic "
            f"{'yes' if source.synthetic else 'no'}; coverage {coverage}; observable outcomes "
            f"{', '.join(source.observable_outcomes) or '—'}"
        )
    if not traced.complete:
        lines.append(
            f"INCOMPLETE: {traced.unresolved_members} member(s) without a canonical row, "
            f"{traced.unresolved_records} row(s) without a source record"
        )
    lines.append(f"complete: {'yes' if traced.complete else 'no'}")
    return lines
