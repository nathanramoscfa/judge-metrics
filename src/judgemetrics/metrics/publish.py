# src/judgemetrics/metrics/publish.py
"""Publishing observations: the snapshot row, supersession, batched inserts, member families.

A ``Publisher`` writes in the caller's transaction (the CLI commits; pipeline step 13
runs inside the ingest transaction, which the runner commits or rolls back), one
subject's drafts at a time (``add``), so a compute over a whole corpus streams: no
more than one subject's drafts and member families are ever in memory.
``publish(session, snapshot, drafts, registry, settings, ...)`` is the same for a
list of drafts.

1. the chain-completeness rule — every member id of every draft's family must be
   present in the snapshot's own tables (a vectorized anti-join per family against the
   snapshot's sorted id column), otherwise ``ProvenanceError`` is raised before that
   subject's rows are written and the caller's transaction rolls back
   (``test_golden_provenance`` relies on it: an observation whose chain breaks is
   never published);
2. ``metric_snapshot`` upserted on ``content_hash`` (an existing row is
   reused; a label is recorded when the row has none; and — issue #42 — a
   compute that reuses the row under a newer registry records the registry
   and methodology versions it publishes under, so ``/ready`` and
   ``/coverage`` report the versions of the observations they describe);
3. ``sync_definitions``, then the ``metric_definition`` ids by
   ``(slug, version)``;
4. per subject and source: the current observations (``superseded_at IS
   NULL``) are loaded with the content hash of their member family and compared
   with the drafts — every stored column of ``VERIFIED_COLUMNS`` and the family's
   ``digest`` — and a subject whose drafts are unchanged is left in place (no
   supersede, no insert, no family read), so a recompute without data changes
   writes nothing; otherwise its current observations are superseded
   (``superseded_at = now()``) and the new observations are inserted in batches
   of 500 rows per statement, each pointing at its member family.

Member families (``members``, ``member_store``) are content-addressed: the family
of a draft is found by ``(definition, subject, source, snapshot, digest)`` or
created with its rows written by ``COPY``; a revived observation (one a previous
publish superseded and that the same snapshot and definition now produce again —
``uq_metric_observation_key`` spans superseded rows) is pointed at the matching
family and keeps whatever members it had. A family is never rewritten or deleted:
a changed one is a new row and the observations that cite the old one keep it.

Observations are inserted with one compiled statement executed over each batch
(executemany). Phase 5 Step 5: an observation's key carries its ``calendar_year``
(null for the whole window), stored beside the period it names.

Nothing is ever deleted: supersession keeps the history of every number
a subject has carried. ``stored_columns`` and ``row_columns`` are the two
halves of the comparison every equality in this package and in
``verify`` uses — both normalize to the database's own precision
(``Numeric(9, 6)`` rates, bounds, ratios, and weights, ``Numeric(14, 4)``
values and expected counts). Observation and member rows carry entity ids
only, never a person id; log lines carry the snapshot id, counts, and slugs
only.

Phase 4 Step 3: the verified columns include the ``observed_expected``
figures (``expected_count``, ``expected_rate``, ``standardized_ratio``,
``pooling_weight``), every row's ``suppression_reason``, and the content
hash of the model an adjusted observation cites (``outcome_model_hash``,
read through ``outcome_model_id``); a draft names its model by that hash
and ``publish`` resolves the id, refusing a hash the catalogue does not
hold. ``publish(..., kinds=)`` loads, compares, and supersedes only the
current observations of the kinds the run computed (every kind by default):
pipeline step 13 passes the descriptive kinds, so a judge it touches keeps
the adjusted observations the last full ``metrics compute`` published — the
one place a recompute leaves a subject's rows of two snapshots side by side
(docs/ARCHITECTURE.md "Risk adjustment").
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
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
from judgemetrics.metrics.compute import (
    NotAttributableRecord,
    NotObservableRecord,
    ObservationDraft,
)
from judgemetrics.metrics.member_store import create_family, existing_families
from judgemetrics.metrics.members import MemberFamily
from judgemetrics.metrics.registry import KINDS, OBSERVED_EXPECTED, Registry, sync_definitions
from judgemetrics.metrics.snapshot import Snapshot, code_version

log = get_logger(__name__)

BATCH_SIZE = 500
RATE_PLACES = Decimal("0.000001")
VALUE_PLACES = Decimal("0.0001")
# A Numeric(9, 6) column holds values below 1000 in magnitude.
SIX_PLACE_LIMIT = Decimal(1000)
# The pseudo-column naming the cited model by its content hash (read through
# outcome_model_id; never a column of metric_observation itself).
MODEL_HASH = "outcome_model_hash"
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
    "expected_count",
    "expected_rate",
    "standardized_ratio",
    "pooling_weight",
    "suppression_reason",
    MODEL_HASH,
)
GroupKey = tuple[str, str, str]

DEFINITION = Base.metadata.tables["metric_definition"]
SNAPSHOT = Base.metadata.tables["metric_snapshot"]
OBSERVATION = Base.metadata.tables["metric_observation"]
FAMILY = Base.metadata.tables["metric_member_family"]
OUTCOME_MODEL = Base.metadata.tables["outcome_model"]
INSERT_OBSERVATION = sa.insert(OBSERVATION)
FAMILY_HASH = "family_hash"


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
    # Rows written to ``metric_member`` (by COPY) and the families they belong to.
    members_written: int
    subjects_published: int
    subjects_unchanged: int
    not_attributable: int = 0
    families_written: int = 0

    def as_log(self) -> dict[str, Any]:
        return {
            "snapshot": self.content_hash,
            "observations": self.observations_published,
            "suppressed": self.suppressed,
            "not_observable": self.not_observable,
            "not_attributable": self.not_attributable,
            "superseded": self.superseded,
            "members": self.members_written,
            "families": self.families_written,
            "subjects_published": self.subjects_published,
            "subjects_unchanged": self.subjects_unchanged,
        }


# --- normalization -----------------------------------------------------------------------


def _rate(value: float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    quantized = Decimal(str(value)).quantize(RATE_PLACES, rounding=ROUND_HALF_EVEN)
    if abs(quantized) >= SIX_PLACE_LIMIT:
        msg = f"{value} does not fit a Numeric(9, 6) column"
        raise PublishError(msg)
    return quantized


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
        "expected_count": _value(draft.expected_count),
        "expected_rate": _rate(draft.expected_rate),
        "standardized_ratio": _rate(draft.standardized_ratio),
        "pooling_weight": _rate(draft.pooling_weight),
        "suppression_reason": draft.suppression_reason,
        MODEL_HASH: draft.model_hash,
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
        "expected_count": _value(row["expected_count"]),
        "expected_rate": _rate(row["expected_rate"]),
        "standardized_ratio": _rate(row["standardized_ratio"]),
        "pooling_weight": _rate(row["pooling_weight"]),
        "suppression_reason": row["suppression_reason"],
        MODEL_HASH: None if row[MODEL_HASH] is None else str(row[MODEL_HASH]),
    }


def _insert_columns(columns: Mapping[str, Any]) -> dict[str, Any]:
    """The stored columns of ``metric_observation`` itself (the model hash is not one)."""
    return {name: value for name, value in columns.items() if name != MODEL_HASH}


def draft_key(draft: ObservationDraft) -> tuple[Any, ...]:
    return draft.key


# --- chain completeness -------------------------------------------------------------------


def _where(draft: ObservationDraft) -> str:
    where = f"{draft.slug} {draft.subject_type}:{draft.subject_id}"
    if draft.window_days is not None:
        where += f"@{draft.window_days}"
    if draft.dimension_value is not None:
        where += f"[{draft.dimension_value}]"
    return where


def check_chain(snapshot: Snapshot, drafts: Sequence[ObservationDraft]) -> None:
    """``ProvenanceError`` unless every member id of every draft's family is in the snapshot.

    The drafts of one definition and subject share a family, so each family is checked
    once: its distinct ids against the snapshot's sorted id column of the family's kind
    (``Snapshot.missing_member_ids``). A family with a missing id breaks every observation
    that cites it.
    """
    missing_by_family: dict[int, int] = {}
    broken: list[str] = []
    for draft in drafts:
        family = draft.family
        if family is None:
            broken.append(f"{_where(draft)}: no member family")
            continue
        key = id(family)
        if key not in missing_by_family:
            missing_by_family[key] = snapshot.missing_member_ids(family.kind, family.ids()).len()
        if missing_by_family[key]:
            broken.append(
                f"{_where(draft)}: {missing_by_family[key]} member id(s) not in the snapshot"
            )
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
        select(
            SNAPSHOT.c.id,
            SNAPSHOT.c.label,
            SNAPSHOT.c.registry_version,
            SNAPSHOT.c.methodology_version,
        ).where(SNAPSHOT.c.content_hash == ref.content_hash)
    ).first()
    if existing is not None:
        changes: dict[str, Any] = {}
        if label and existing.label is None:
            changes["label"] = label
        # Issue #42: the row states the registry its latest publish used.
        if existing.registry_version != registry.version:
            changes["registry_version"] = registry.version
        if existing.methodology_version != registry.methodology_version:
            changes["methodology_version"] = registry.methodology_version
        if changes:
            session.execute(
                sa.update(SNAPSHOT)
                .where(SNAPSHOT.c.id == existing.id)
                .values(**changes, updated_at=sa.func.now())
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
    kind: str = ""
    # The member family the observation cites and its content hash (the members' identity).
    family_id: uuid.UUID | None = None
    family_hash: str | None = None


def load_observations(
    session: Session,
    *,
    current_only: bool = True,
    snapshot_id: uuid.UUID | None = None,
    subject: tuple[str, str] | None = None,
    source_id: uuid.UUID | None = None,
    kinds: Collection[str] | None = None,
) -> list[StoredObservation]:
    """Stored observations with their definition, normalized columns, and family hash.

    ``kinds`` keeps the observations of those registry kinds only (every kind
    when ``None``); the cited model's content hash is read through an outer
    join (``outcome_model_hash``, null for every kind but ``observed_expected``).
    Members are not loaded: an observation's members are its family's rows,
    compared by ``family_hash`` (``member_store`` reads them when a mismatch needs them).
    """
    stmt = (
        select(
            OBSERVATION,
            DEFINITION.c.slug.label("slug"),
            DEFINITION.c.version.label("definition_version"),
            DEFINITION.c.kind.label("kind"),
            OUTCOME_MODEL.c.content_hash.label(MODEL_HASH),
            FAMILY.c.members_hash.label(FAMILY_HASH),
        )
        .join(DEFINITION, DEFINITION.c.id == OBSERVATION.c.metric_definition_id)
        .join(FAMILY, FAMILY.c.id == OBSERVATION.c.member_family_id)
        .outerjoin(OUTCOME_MODEL, OUTCOME_MODEL.c.id == OBSERVATION.c.outcome_model_id)
        .order_by(OBSERVATION.c.id)
    )
    if kinds is not None:
        stmt = stmt.where(DEFINITION.c.kind.in_(sorted(kinds)))
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
    stored: list[StoredObservation] = []
    for row in (dict(item._mapping) for item in session.execute(stmt).all()):
        subject_type = row["subject_type"]
        subject_value = subject_type.value if hasattr(subject_type, "value") else str(subject_type)
        stored.append(
            StoredObservation(
                id=uuid.UUID(str(row["id"])),
                key=(
                    str(row["slug"]),
                    subject_value,
                    str(row["subject_id"]),
                    str(row["source_id"]),
                    row["period_start"],
                    row["period_end"],
                    row["window_days"],
                    row["dimension_value"],
                    row["calendar_year"],
                ),
                definition=(str(row["slug"]), str(row["definition_version"])),
                snapshot_id=uuid.UUID(str(row["snapshot_id"])),
                columns=row_columns(row),
                kind=str(row["kind"]),
                family_id=uuid.UUID(str(row["member_family_id"])),
                family_hash=str(row[FAMILY_HASH]),
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
        if draft.family is None or item.family_hash != draft.family.digest:
            return False
    return True


def _observation_row(
    draft: ObservationDraft,
    *,
    observation_id: uuid.UUID,
    definition_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    model_id: uuid.UUID | None,
    family_id: uuid.UUID,
    registry: Registry,
    version: str,
    computed_at: datetime,
) -> dict[str, Any]:
    return {
        "id": observation_id,
        "metric_definition_id": definition_id,
        "subject_type": SubjectType(draft.subject_type),
        "subject_id": uuid.UUID(draft.subject_id),
        "source_id": uuid.UUID(draft.source_id),
        "snapshot_id": snapshot_id,
        "computed_at": computed_at,
        "code_version": version,
        "outcome_model_id": model_id,
        "member_family_id": family_id,
        "superseded_at": None,
        "calendar_year": draft.calendar_year,
        **_insert_columns(stored_columns(draft, registry)),
    }


def model_ids(
    session: Session, drafts: Sequence[ObservationDraft], registry: Registry
) -> dict[str, uuid.UUID]:
    """``outcome_model.id`` by content hash for every model a draft cites.

    An ``observed_expected`` draft must cite a recorded model and no other
    kind may cite one; ``PublishError`` otherwise, before anything is written.
    """
    hashes: set[str] = set()
    for draft in drafts:
        adjusted = registry.metrics[draft.slug].kind == OBSERVED_EXPECTED
        if adjusted and draft.model_hash is None:
            msg = f"{draft.slug} {draft.subject_type}:{draft.subject_id} cites no outcome model"
            raise PublishError(msg)
        if not adjusted and draft.model_hash is not None:
            msg = f"{draft.slug} is not an {OBSERVED_EXPECTED} and cannot cite a model"
            raise PublishError(msg)
        if draft.model_hash is not None:
            hashes.add(draft.model_hash)
    if not hashes:
        return {}
    rows = session.execute(
        select(OUTCOME_MODEL.c.content_hash, OUTCOME_MODEL.c.id).where(
            OUTCOME_MODEL.c.content_hash.in_(sorted(hashes))
        )
    ).all()
    found = {str(row.content_hash): uuid.UUID(str(row.id)) for row in rows}
    missing = sorted(hashes - set(found))
    if missing:
        msg = f"{len(missing)} cited outcome model(s) are not recorded: {', '.join(missing[:3])}"
        raise PublishError(msg)
    return found


def _batches[T](rows: Sequence[T]) -> Iterable[Sequence[T]]:
    for start in range(0, len(rows), BATCH_SIZE):
        yield rows[start : start + BATCH_SIZE]


class Publisher:
    """Writes drafts subject by subject inside the caller's transaction (module docstring).

    ``kinds`` are the registry kinds the drafts were computed for (every kind by
    default): only current observations of those kinds are compared and superseded,
    and a draft of another kind is refused. ``finish`` returns the totals.
    """

    def __init__(
        self,
        session: Session,
        snapshot: Snapshot,
        registry: Registry,
        settings: Settings,
        *,
        label: str | None = None,
        kinds: Collection[str] | None = None,
    ) -> None:
        self.session = session
        self.snapshot = snapshot
        self.registry = registry
        self.scope = frozenset(KINDS) if kinds is None else frozenset(kinds)
        self.snapshot_id = upsert_snapshot(session, snapshot, registry, settings, label)
        self.ids = definition_ids(session, registry)
        self.version = code_version(settings)
        self.computed_at = datetime.now(tz=UTC)
        self.published = 0
        self.suppressed = 0
        self.superseded = 0
        self.members_written = 0
        self.families_written = 0
        self.subjects_published = 0
        self.subjects_unchanged = 0

    def add(self, drafts: Sequence[ObservationDraft]) -> None:
        """Validate every draft, then write each subject's group (nothing before all are valid)."""
        for draft in drafts:
            definition = self.registry.metrics.get(draft.slug)
            if definition is None or definition.kind not in self.scope:
                msg = f"{draft.slug} is not a registry metric of the kinds {sorted(self.scope)}"
                raise PublishError(msg)
            if (draft.slug, draft.version) not in self.ids:
                msg = f"{draft.slug} version {draft.version} is not in metric_definition"
                raise PublishError(msg)
        check_chain(self.snapshot, drafts)
        models = model_ids(self.session, drafts, self.registry)
        for (subject_type, subject_id, source_id), group in sorted(_group(drafts).items()):
            self._publish_subject(subject_type, subject_id, source_id, group, models)

    def _family_id(
        self,
        draft: ObservationDraft,
        known: dict[tuple[uuid.UUID, str], uuid.UUID],
    ) -> uuid.UUID:
        family = draft.family
        if family is None:
            msg = f"{_where(draft)} has no member family"
            raise PublishError(msg)
        definition_id = self.ids[(draft.slug, draft.version)]
        key = (definition_id, family.digest)
        found = known.get(key)
        if found is not None:
            return found
        created = create_family(
            self.session,
            definition_id=definition_id,
            subject_type=draft.subject_type,
            subject_id=uuid.UUID(draft.subject_id),
            source_id=uuid.UUID(draft.source_id),
            snapshot_id=self.snapshot_id,
            family=family,
        )
        known[key] = created
        self.members_written += family.row_count
        self.families_written += 1
        return created

    def _publish_subject(
        self,
        subject_type: str,
        subject_id: str,
        source_id: str,
        group: Sequence[ObservationDraft],
        models: Mapping[str, uuid.UUID],
    ) -> None:
        session = self.session
        current = load_observations(
            session,
            subject=(subject_type, subject_id),
            source_id=uuid.UUID(source_id),
            kinds=self.scope,
        )
        if _unchanged(group, current, self.registry):
            self.subjects_unchanged += 1
            return
        self.subjects_published += 1
        if current:
            session.execute(
                sa.update(OBSERVATION)
                .where(OBSERVATION.c.id.in_([item.id for item in current]))
                .values(superseded_at=self.computed_at, updated_at=sa.func.now())
            )
            self.superseded += len(current)
        # Superseded rows of this snapshot and definition that the drafts
        # reproduce are revived rather than re-inserted (the unique key spans
        # superseded rows).
        revivable = {
            item.key: item
            for item in load_observations(
                session,
                current_only=False,
                snapshot_id=self.snapshot_id,
                subject=(subject_type, subject_id),
                source_id=uuid.UUID(source_id),
                kinds=self.scope,
            )
        }
        known = existing_families(
            session,
            subject_type=subject_type,
            subject_id=uuid.UUID(subject_id),
            source_id=uuid.UUID(source_id),
            snapshot_id=self.snapshot_id,
        )
        rows: list[dict[str, Any]] = []
        for draft in group:
            model_id = None if draft.model_hash is None else models[draft.model_hash]
            family_id = self._family_id(draft, known)
            previous = revivable.get(draft.key)
            if previous is not None and previous.definition == (draft.slug, draft.version):
                self._revive(previous.id, draft, model_id, family_id)
            else:
                rows.append(
                    _observation_row(
                        draft,
                        observation_id=uuid.uuid4(),
                        definition_id=self.ids[(draft.slug, draft.version)],
                        snapshot_id=self.snapshot_id,
                        model_id=model_id,
                        family_id=family_id,
                        registry=self.registry,
                        version=self.version,
                        computed_at=self.computed_at,
                    )
                )
            self.published += 1
            self.suppressed += int(draft.suppressed_flag)
        # One compiled statement, executed over each batch (executemany): compiling a
        # multi-row VALUES per batch dominated large publishes.
        for batch in _batches(rows):
            session.execute(INSERT_OBSERVATION, list(batch))

    def _revive(
        self,
        observation_id: uuid.UUID,
        draft: ObservationDraft,
        model_id: uuid.UUID | None,
        family_id: uuid.UUID,
    ) -> None:
        """Bring a superseded row of the same snapshot and definition back as current.

        The row keeps its members: it is pointed at the family the draft computes, which is
        the family it already cites when the members are unchanged (nothing is deleted).
        """
        self.session.execute(
            sa.update(OBSERVATION)
            .where(OBSERVATION.c.id == observation_id)
            .values(
                superseded_at=None,
                computed_at=self.computed_at,
                code_version=self.version,
                outcome_model_id=model_id,
                member_family_id=family_id,
                updated_at=sa.func.now(),
                **_insert_columns(stored_columns(draft, self.registry)),
            )
        )

    def finish(self, *, not_observable: int = 0, not_attributable: int = 0) -> PublishResult:
        self.session.flush()
        result = PublishResult(
            snapshot_id=self.snapshot_id,
            content_hash=self.snapshot.content_hash,
            observations_published=self.published,
            suppressed=self.suppressed,
            not_observable=not_observable,
            superseded=self.superseded,
            members_written=self.members_written,
            subjects_published=self.subjects_published,
            subjects_unchanged=self.subjects_unchanged,
            not_attributable=not_attributable,
            families_written=self.families_written,
        )
        log.info("metrics.published", **result.as_log())
        return result


def publish(
    session: Session,
    snapshot: Snapshot,
    drafts: Sequence[ObservationDraft],
    registry: Registry,
    settings: Settings,
    *,
    not_observable: Sequence[NotObservableRecord] = (),
    not_attributable: Sequence[NotAttributableRecord] = (),
    label: str | None = None,
    kinds: Collection[str] | None = None,
) -> PublishResult:
    """Store the drafts (see the module docstring); the caller commits."""
    publisher = Publisher(session, snapshot, registry, settings, label=label, kinds=kinds)
    publisher.add(drafts)
    return publisher.finish(
        not_observable=len(not_observable), not_attributable=len(not_attributable)
    )


def family_of(draft: ObservationDraft) -> MemberFamily:
    """The draft's member family (every computed draft has one)."""
    if draft.family is None:
        msg = f"{_where(draft)} has no member family"
        raise PublishError(msg)
    return draft.family
