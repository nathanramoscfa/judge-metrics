# src/judgemetrics/metrics/publish.py
"""Publishing observations: the snapshot row, supersession, batched inserts, members.

``publish(session, snapshot, drafts, registry, settings, ...)`` writes in
the caller's transaction (the CLI commits; pipeline step 13 runs inside
the ingest transaction, which the runner commits or rolls back):

1. the chain-completeness rule — every member id of every draft must be
   present in the snapshot's own tables, otherwise ``ProvenanceError`` is
   raised before anything is written (Step 3's trace test relies on it:
   an observation whose chain breaks is never published);
2. ``metric_snapshot`` upserted on ``content_hash`` (an existing row is
   reused; a label is recorded when the row has none);
3. ``sync_definitions``, then the ``metric_definition`` ids by
   ``(slug, version)``;
4. per subject and source: the current observations (``superseded_at IS
   NULL``) and their members are loaded and compared with the drafts —
   every stored column of ``VERIFIED_COLUMNS`` and the member multiset —
   and a subject whose drafts are unchanged is left in place (no
   supersede, no insert), so a recompute without data changes writes
   nothing; otherwise its current observations are superseded
   (``superseded_at = now()``) and the new observations and members are
   inserted in batches of 500 rows per statement. An observation that a
   previous publish superseded and that the same snapshot and definition
   now produce again is revived rather than inserted, because
   ``uq_metric_observation_key`` spans superseded rows too.

Nothing is ever deleted: supersession keeps the history of every number
a subject has carried. ``stored_columns`` and ``row_columns`` are the two
halves of the comparison every equality in this package and in
``verify`` uses — both normalize to the database's own precision
(``Numeric(9, 6)`` rates and bounds, ``Numeric(14, 4)`` values).
Observation and member rows carry entity ids only, never a person id;
log lines carry the snapshot id, counts, and slugs only.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import Base
from judgemetrics.db.models.enums import SubjectType
from judgemetrics.logging import get_logger
from judgemetrics.metrics.compute import Member, NotObservableRecord, ObservationDraft
from judgemetrics.metrics.registry import Registry, sync_definitions
from judgemetrics.metrics.snapshot import Snapshot, code_version

log = get_logger(__name__)

BATCH_SIZE = 500
RATE_PLACES = Decimal("0.000001")
VALUE_PLACES = Decimal("0.0001")
# The stored columns a recompute must reproduce (and that decide "unchanged").
VERIFIED_COLUMNS: tuple[str, ...] = (
    "period_start",
    "period_end",
    "window_days",
    "dimension_value",
    "eligible_count",
    "cohort_size",
    "observed_count",
    "observed_rate",
    "lower_confidence_bound",
    "upper_confidence_bound",
    "value",
    "distribution",
    "suppressed_flag",
    "registry_version",
    "methodology_version",
)
MemberTuple = tuple[str, str, bool, bool]
GroupKey = tuple[str, str, str]

DEFINITION = Base.metadata.tables["metric_definition"]
SNAPSHOT = Base.metadata.tables["metric_snapshot"]
OBSERVATION = Base.metadata.tables["metric_observation"]
MEMBER = Base.metadata.tables["metric_observation_member"]


class PublishError(RuntimeError):
    """The drafts cannot be stored as given (a definition or engine defect)."""


class ProvenanceError(PublishError):
    """An observation names a member the snapshot does not hold: nothing is published."""


@dataclass(frozen=True, slots=True)
class PublishResult:
    snapshot_id: uuid.UUID
    content_hash: str
    observations_published: int
    suppressed: int
    not_observable: int
    superseded: int
    members_written: int
    subjects_published: int
    subjects_unchanged: int

    def as_log(self) -> dict[str, Any]:
        return {
            "snapshot": self.content_hash,
            "observations": self.observations_published,
            "suppressed": self.suppressed,
            "not_observable": self.not_observable,
            "superseded": self.superseded,
            "members": self.members_written,
            "subjects_published": self.subjects_published,
            "subjects_unchanged": self.subjects_unchanged,
        }


# --- normalization -----------------------------------------------------------------------


def _rate(value: float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(RATE_PLACES, rounding=ROUND_HALF_EVEN)


def _value(value: float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(VALUE_PLACES, rounding=ROUND_HALF_EVEN)


def stored_columns(draft: ObservationDraft, registry: Registry) -> dict[str, Any]:
    """The draft's ``VERIFIED_COLUMNS`` at the database's precision."""
    return {
        "period_start": draft.period_start,
        "period_end": draft.period_end,
        "window_days": draft.window_days,
        "dimension_value": draft.dimension_value,
        "eligible_count": int(draft.eligible_count),
        "cohort_size": int(draft.cohort_size),
        "observed_count": int(draft.observed_count),
        "observed_rate": _rate(draft.observed_rate),
        "lower_confidence_bound": _rate(draft.lower),
        "upper_confidence_bound": _rate(draft.upper),
        "value": _value(draft.value),
        "distribution": None
        if draft.distribution is None
        else {str(k): int(v) for k, v in draft.distribution.items()},
        "suppressed_flag": bool(draft.suppressed_flag),
        "registry_version": int(registry.version),
        "methodology_version": str(registry.methodology_version),
    }


def row_columns(row: Mapping[str, Any]) -> dict[str, Any]:
    """A stored observation's ``VERIFIED_COLUMNS``, normalized the same way."""
    return {
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "window_days": row["window_days"],
        "dimension_value": row["dimension_value"],
        "eligible_count": int(row["eligible_count"]),
        "cohort_size": int(row["cohort_size"]),
        "observed_count": int(row["observed_count"]),
        "observed_rate": _rate(row["observed_rate"]),
        "lower_confidence_bound": _rate(row["lower_confidence_bound"]),
        "upper_confidence_bound": _rate(row["upper_confidence_bound"]),
        "value": _value(row["value"]),
        "distribution": None
        if row["distribution"] is None
        else {str(k): int(v) for k, v in dict(row["distribution"]).items()},
        "suppressed_flag": bool(row["suppressed_flag"]),
        "registry_version": int(row["registry_version"]),
        "methodology_version": str(row["methodology_version"]),
    }


def member_tuples(members: Iterable[Member]) -> tuple[MemberTuple, ...]:
    return tuple(sorted(member.as_tuple() for member in members))


def draft_key(draft: ObservationDraft) -> tuple[Any, ...]:
    return draft.key


# --- chain completeness -------------------------------------------------------------------


def check_chain(snapshot: Snapshot, drafts: Sequence[ObservationDraft]) -> None:
    """``ProvenanceError`` unless every member id of every draft is in the snapshot's tables."""
    broken: list[str] = []
    for draft in drafts:
        missing = 0
        for member in draft.members:
            if member.id not in snapshot.member_ids(member.kind):
                missing += 1
        if missing:
            where = f"{draft.slug} {draft.subject_type}:{draft.subject_id}"
            if draft.window_days is not None:
                where += f"@{draft.window_days}"
            if draft.dimension_value is not None:
                where += f"[{draft.dimension_value}]"
            broken.append(f"{where}: {missing} member id(s) not in the snapshot")
    if broken:
        shown = "; ".join(broken[:10])
        more = f" (+{len(broken) - 10} more)" if len(broken) > 10 else ""
        msg = f"provenance chain incomplete for {len(broken)} observation(s): {shown}{more}"
        raise ProvenanceError(msg)


# --- snapshot and definitions --------------------------------------------------------------


def upsert_snapshot(
    session: Session, snapshot: Snapshot, registry: Registry, settings: Settings, label: str | None
) -> uuid.UUID:
    """The ``metric_snapshot`` row for the snapshot's hash, inserted when missing."""
    ref = snapshot.ref
    existing = session.execute(
        select(SNAPSHOT.c.id, SNAPSHOT.c.label).where(SNAPSHOT.c.content_hash == ref.content_hash)
    ).first()
    if existing is not None:
        if label and existing.label is None:
            session.execute(
                sa.update(SNAPSHOT)
                .where(SNAPSHOT.c.id == existing.id)
                .values(label=label, updated_at=sa.func.now())
            )
        return uuid.UUID(str(existing.id))
    snapshot_id = uuid.uuid4()
    session.execute(
        sa.insert(SNAPSHOT).values(
            id=snapshot_id,
            content_hash=ref.content_hash,
            label=label,
            exported_at=ref.exported_at,
            code_version=ref.code_version,
            registry_version=registry.version,
            methodology_version=registry.methodology_version,
            row_counts=ref.row_counts,
            coverage={key: dict(value) for key, value in ref.coverage.items()},
            storage_uri=ref.storage_uri,
        )
    )
    return snapshot_id


def definition_ids(session: Session, registry: Registry) -> dict[tuple[str, str], uuid.UUID]:
    sync_definitions(session, registry)
    rows = session.execute(select(DEFINITION.c.id, DEFINITION.c.slug, DEFINITION.c.version)).all()
    return {(str(row.slug), str(row.version)): uuid.UUID(str(row.id)) for row in rows}


# --- current observations -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredObservation:
    id: uuid.UUID
    key: tuple[Any, ...]
    definition: tuple[str, str]
    snapshot_id: uuid.UUID
    columns: dict[str, Any]
    members: tuple[MemberTuple, ...]


def load_members(
    session: Session, observation_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[MemberTuple]]:
    members: dict[uuid.UUID, list[MemberTuple]] = {oid: [] for oid in observation_ids}
    for start in range(0, len(observation_ids), BATCH_SIZE):
        batch = observation_ids[start : start + BATCH_SIZE]
        rows = session.execute(
            select(
                MEMBER.c.observation_id,
                MEMBER.c.member_kind,
                MEMBER.c.member_id,
                MEMBER.c.counted,
                MEMBER.c.followed,
            ).where(MEMBER.c.observation_id.in_(batch))
        ).all()
        for row in rows:
            members[uuid.UUID(str(row.observation_id))].append(
                (str(row.member_kind), str(row.member_id), bool(row.counted), bool(row.followed))
            )
    return {oid: sorted(items) for oid, items in members.items()}


def load_observations(
    session: Session,
    *,
    current_only: bool = True,
    snapshot_id: uuid.UUID | None = None,
    subject: tuple[str, str] | None = None,
    source_id: uuid.UUID | None = None,
    with_members: bool = True,
) -> list[StoredObservation]:
    """Stored observations with their definition, normalized columns, and members."""
    stmt = (
        select(
            OBSERVATION,
            DEFINITION.c.slug.label("slug"),
            DEFINITION.c.version.label("definition_version"),
        )
        .join(DEFINITION, DEFINITION.c.id == OBSERVATION.c.metric_definition_id)
        .order_by(OBSERVATION.c.id)
    )
    if current_only:
        stmt = stmt.where(OBSERVATION.c.superseded_at.is_(None))
    if snapshot_id is not None:
        stmt = stmt.where(OBSERVATION.c.snapshot_id == snapshot_id)
    if subject is not None:
        stmt = stmt.where(
            OBSERVATION.c.subject_type == SubjectType(subject[0]),
            OBSERVATION.c.subject_id == uuid.UUID(subject[1]),
        )
    if source_id is not None:
        stmt = stmt.where(OBSERVATION.c.source_id == source_id)
    rows = [dict(row._mapping) for row in session.execute(stmt).all()]
    ids = [uuid.UUID(str(row["id"])) for row in rows]
    members = load_members(session, ids) if with_members and ids else {}
    stored: list[StoredObservation] = []
    for row in rows:
        oid = uuid.UUID(str(row["id"]))
        subject_type = row["subject_type"]
        subject_value = subject_type.value if hasattr(subject_type, "value") else str(subject_type)
        stored.append(
            StoredObservation(
                id=oid,
                key=(
                    str(row["slug"]),
                    subject_value,
                    str(row["subject_id"]),
                    str(row["source_id"]),
                    row["period_start"],
                    row["period_end"],
                    row["window_days"],
                    row["dimension_value"],
                ),
                definition=(str(row["slug"]), str(row["definition_version"])),
                snapshot_id=uuid.UUID(str(row["snapshot_id"])),
                columns=row_columns(row),
                members=tuple(members.get(oid, [])),
            )
        )
    return stored


# --- publish -------------------------------------------------------------------------------


def _group(drafts: Sequence[ObservationDraft]) -> dict[GroupKey, list[ObservationDraft]]:
    groups: dict[GroupKey, list[ObservationDraft]] = {}
    for draft in drafts:
        groups.setdefault((draft.subject_type, draft.subject_id, draft.source_id), []).append(draft)
    return groups


def _unchanged(
    drafts: Sequence[ObservationDraft], stored: Sequence[StoredObservation], registry: Registry
) -> bool:
    if len(drafts) != len(stored):
        return False
    by_key = {item.key: item for item in stored}
    if len(by_key) != len(stored):
        return False
    for draft in drafts:
        item = by_key.get(draft.key)
        if item is None or item.definition != (draft.slug, draft.version):
            return False
        if item.columns != stored_columns(draft, registry):
            return False
        if item.members != member_tuples(draft.members):
            return False
    return True


def _observation_row(
    draft: ObservationDraft,
    *,
    observation_id: uuid.UUID,
    definition_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    registry: Registry,
    version: str,
    computed_at: datetime,
) -> dict[str, Any]:
    columns = stored_columns(draft, registry)
    return {
        "id": observation_id,
        "metric_definition_id": definition_id,
        "subject_type": SubjectType(draft.subject_type),
        "subject_id": uuid.UUID(draft.subject_id),
        "source_id": uuid.UUID(draft.source_id),
        "snapshot_id": snapshot_id,
        "computed_at": computed_at,
        "code_version": version,
        "expected_count": None,
        "expected_rate": None,
        "standardized_ratio": None,
        "superseded_at": None,
        **columns,
    }


def _member_rows(observation_id: uuid.UUID, members: Iterable[Member]) -> list[dict[str, Any]]:
    return [
        {
            "observation_id": observation_id,
            "member_kind": member.kind,
            "member_id": uuid.UUID(member.id),
            "counted": member.counted,
            "followed": member.followed,
        }
        for member in members
    ]


def _batches[T](rows: Sequence[T]) -> Iterable[Sequence[T]]:
    for start in range(0, len(rows), BATCH_SIZE):
        yield rows[start : start + BATCH_SIZE]


def publish(
    session: Session,
    snapshot: Snapshot,
    drafts: Sequence[ObservationDraft],
    registry: Registry,
    settings: Settings,
    *,
    not_observable: Sequence[NotObservableRecord] = (),
    label: str | None = None,
) -> PublishResult:
    """Store the drafts (see the module docstring); the caller commits."""
    check_chain(snapshot, drafts)
    snapshot_id = upsert_snapshot(session, snapshot, registry, settings, label)
    ids = definition_ids(session, registry)
    for draft in drafts:
        if (draft.slug, draft.version) not in ids:
            msg = f"{draft.slug} version {draft.version} is not in metric_definition"
            raise PublishError(msg)
    version = code_version(settings)
    computed_at = datetime.now(tz=UTC)
    published = 0
    suppressed = 0
    superseded = 0
    members_written = 0
    subjects_published = 0
    subjects_unchanged = 0
    for (subject_type, subject_id, source_id), group in sorted(_group(drafts).items()):
        current = load_observations(
            session, subject=(subject_type, subject_id), source_id=uuid.UUID(source_id)
        )
        if _unchanged(group, current, registry):
            subjects_unchanged += 1
            continue
        subjects_published += 1
        if current:
            session.execute(
                sa.update(OBSERVATION)
                .where(OBSERVATION.c.id.in_([item.id for item in current]))
                .values(superseded_at=computed_at, updated_at=sa.func.now())
            )
            superseded += len(current)
        # Superseded rows of this snapshot and definition that the drafts
        # reproduce are revived rather than re-inserted (the unique key spans
        # superseded rows).
        revivable = {
            item.key: item
            for item in load_observations(
                session,
                current_only=False,
                snapshot_id=snapshot_id,
                subject=(subject_type, subject_id),
                source_id=uuid.UUID(source_id),
                with_members=False,
            )
        }
        observation_rows: list[dict[str, Any]] = []
        member_rows: list[dict[str, Any]] = []
        for draft in group:
            previous = revivable.get(draft.key)
            if previous is not None and previous.definition == (draft.slug, draft.version):
                _revive(session, previous.id, draft, registry, version, computed_at)
                member_rows.extend(_member_rows(previous.id, draft.members))
            else:
                observation_id = uuid.uuid4()
                observation_rows.append(
                    _observation_row(
                        draft,
                        observation_id=observation_id,
                        definition_id=ids[(draft.slug, draft.version)],
                        snapshot_id=snapshot_id,
                        registry=registry,
                        version=version,
                        computed_at=computed_at,
                    )
                )
                member_rows.extend(_member_rows(observation_id, draft.members))
            published += 1
            suppressed += int(draft.suppressed_flag)
        for batch in _batches(observation_rows):
            session.execute(sa.insert(OBSERVATION).values(list(batch)))
        for batch in _batches(member_rows):
            session.execute(sa.insert(MEMBER).values(list(batch)))
        members_written += len(member_rows)
    session.flush()
    result = PublishResult(
        snapshot_id=snapshot_id,
        content_hash=snapshot.content_hash,
        observations_published=published,
        suppressed=suppressed,
        not_observable=len(not_observable),
        superseded=superseded,
        members_written=members_written,
        subjects_published=subjects_published,
        subjects_unchanged=subjects_unchanged,
    )
    log.info("metrics.published", **result.as_log())
    return result


def _revive(
    session: Session,
    observation_id: uuid.UUID,
    draft: ObservationDraft,
    registry: Registry,
    version: str,
    computed_at: datetime,
) -> None:
    """Bring a superseded row of the same snapshot and definition back as current."""
    session.execute(sa.delete(MEMBER).where(MEMBER.c.observation_id == observation_id))
    session.execute(
        sa.update(OBSERVATION)
        .where(OBSERVATION.c.id == observation_id)
        .values(
            superseded_at=None,
            computed_at=computed_at,
            code_version=version,
            updated_at=sa.func.now(),
            **stored_columns(draft, registry),
        )
    )
