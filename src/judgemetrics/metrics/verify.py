# src/judgemetrics/metrics/verify.py
"""Verification: every current observation recomputed from its own snapshot.

``verify(session, settings, snapshot=None)`` finds every current observation
(``superseded_at IS NULL``), or those of one snapshot hash, groups them by the
snapshot they cite, source, and subject, opens each snapshot from ``snapshot_dir``,
recomputes the observations' subjects with the registry version the observation
records — the current registry file must carry that ``registry_version`` and the
observation's ``(slug, version)``, otherwise the observation is reported
``unverifiable`` rather than compared against a different contract — and compares
every stored column of ``publish.VERIFIED_COLUMNS`` and the member multiset exactly.
The result lists every mismatch (observation id, slug, subject, window, dimension,
column, stored and recomputed values), every observation the recompute no longer
produces (``column = "observation"``), every recomputed observation the store lacks for
a subject it holds, and every unverifiable observation with its reason. ``ok`` is true
only when all four lists are empty; the CLI exits 1 otherwise. Log lines carry the
snapshot id and counts only.

Phase 4 Step 3: a snapshot's observations are recomputed for the kinds
they hold only (a snapshot an ingest's step 13 published from holds
descriptive kinds alone), and an observation the store lacks is reported
only for a subject that holds observations of the same kind there. An
``observed_expected`` observation is recomputed from the artifact of the
model it cites (``catalog.read_parameters``: the path rebuilt from the
configured snapshot directory, the bytes checked against the content
hash): a missing or altered artifact is reported by observation id with the
column ``outcome_model`` and that observation is not recomputed; a model
fitted under another specification version than the loaded file, or two
models cited for one target and window of a snapshot, make the
observation unverifiable.

Phase 5 Step 5: the recompute builds only the frames of the sources the
snapshot's observations belong to, and every snapshot verified — those the
current observations cite, and the latest snapshot holding coverage
statistics — has its ``coverage_statistic`` rows recomputed
(``coverage.compute_statistics``) and compared: a statistic that differs, one
the store lacks, or one the snapshot no longer produces is reported by source,
scope, and name (``coverage_mismatches``), and ``ok`` requires none.

Phase 5 Step 6: verification streams. The observations are found with one grouped
query and then handled one subject at a time — its stored observations and member
families are read, its drafts recomputed (``compute.iter_frame``: the adjusted kind
for all the source's judges first, then each subject in turn), compared, and dropped —
so memory is bounded by the largest subject, not by the corpus. An observation's
members are its family's rows: the stored rows of every family a verified observation
cites are read back and hashed (a stored family whose rows do not match its recorded
hash is a mismatch of column ``members_hash``), the recomputed family's hash is
compared with it, and only when they differ are the observation's member multisets
expanded and compared (column ``members``, with the two counts).
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import Base
from judgemetrics.logging import get_logger
from judgemetrics.metrics.attribution import Subject
from judgemetrics.metrics.compute import (
    ComputeError,
    ObservationDraft,
    SubjectResult,
    iter_frame,
)
from judgemetrics.metrics.coverage import (
    CoverageMismatch,
    compare_statistics,
    compute_statistics,
    load_statistics,
)
from judgemetrics.metrics.member_store import read_family
from judgemetrics.metrics.members import MemberFamily, mode_for, windows_for
from judgemetrics.metrics.publish import (
    MODEL_HASH,
    VERIFIED_COLUMNS,
    StoredObservation,
    load_observations,
    stored_columns,
)
from judgemetrics.metrics.registry import OBSERVED_EXPECTED, Registry, load_registry
from judgemetrics.metrics.snapshot import (
    Snapshot,
    SnapshotError,
    open_snapshot,
    validate_content_hash,
)

if TYPE_CHECKING:
    from judgemetrics.metrics.adjustment.expected import ModelParameters

log = get_logger(__name__)

SNAPSHOT = Base.metadata.tables["metric_snapshot"]
COVERAGE = Base.metadata.tables["coverage_statistic"]
OBSERVATION = Base.metadata.tables["metric_observation"]
DEFINITION = Base.metadata.tables["metric_definition"]
OBSERVATION_COLUMN = "observation"
MEMBERS_COLUMN = "members"
MEMBERS_HASH_COLUMN = "members_hash"
MODEL_COLUMN = "outcome_model"


@dataclass(frozen=True, slots=True)
class Mismatch:
    """One stored column (or the member set, or the observation itself) that differs."""

    observation_id: uuid.UUID | None
    snapshot: str
    slug: str
    subject_type: str
    subject_id: str
    window_days: int | None
    dimension_value: str | None
    column: str
    stored: Any
    recomputed: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "observation_id": None if self.observation_id is None else str(self.observation_id),
            "snapshot": self.snapshot,
            "slug": self.slug,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "window_days": self.window_days,
            "dimension_value": self.dimension_value,
            "column": self.column,
            "stored": _render(self.stored),
            "recomputed": _render(self.recomputed),
        }


@dataclass(frozen=True, slots=True)
class Unverifiable:
    observation_id: uuid.UUID
    snapshot: str
    slug: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "observation_id": str(self.observation_id),
            "snapshot": self.snapshot,
            "slug": self.slug,
            "reason": self.reason,
        }


@dataclass(slots=True)
class VerifyResult:
    observations: int = 0
    verified: int = 0
    snapshots: list[str] = field(default_factory=list)
    mismatches: list[Mismatch] = field(default_factory=list)
    unverifiable: list[Unverifiable] = field(default_factory=list)
    # Coverage statistics recomputed and compared (Phase 5 Step 5).
    coverage_statistics: int = 0
    coverage_mismatches: list[CoverageMismatch] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches and not self.unverifiable and not self.coverage_mismatches

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "observations": self.observations,
            "verified": self.verified,
            "snapshots": list(self.snapshots),
            "mismatches": [item.as_dict() for item in self.mismatches],
            "unverifiable": [item.as_dict() for item in self.unverifiable],
            "coverage_statistics": self.coverage_statistics,
            "coverage_mismatches": [item.as_dict() for item in self.coverage_mismatches],
        }


def _render(value: Any) -> Any:
    if isinstance(value, tuple | list):
        return [_render(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _render(v) for k, v in value.items()}
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def _latest_coverage_snapshot(session: Session) -> tuple[uuid.UUID, str] | None:
    """The latest snapshot holding coverage statistics (what ``metrics coverage`` prints)."""
    row = session.execute(
        select(SNAPSHOT.c.id, SNAPSHOT.c.content_hash)
        .where(SNAPSHOT.c.id.in_(select(COVERAGE.c.snapshot_id).distinct()))
        .order_by(SNAPSHOT.c.exported_at.desc(), SNAPSHOT.c.id)
        .limit(1)
    ).first()
    return None if row is None else (uuid.UUID(str(row.id)), str(row.content_hash))


def _snapshot_id(session: Session, content_hash: str) -> uuid.UUID | None:
    row = session.execute(
        select(SNAPSHOT.c.id).where(SNAPSHOT.c.content_hash == content_hash)
    ).first()
    return None if row is None else uuid.UUID(str(row.id))


def _mismatch(
    stored: StoredObservation | None,
    draft: ObservationDraft | None,
    content_hash: str,
    column: str,
    stored_value: Any,
    recomputed_value: Any,
) -> Mismatch:
    key = stored.key if stored is not None else (draft.key if draft is not None else ())
    return Mismatch(
        observation_id=None if stored is None else stored.id,
        snapshot=content_hash,
        slug=str(key[0]),
        subject_type=str(key[1]),
        subject_id=str(key[2]),
        window_days=key[6],
        dimension_value=key[7],
        column=column,
        stored=stored_value,
        recomputed=recomputed_value,
    )


def _multiset(family: MemberFamily, stored: StoredObservation) -> Counter[tuple[str, bool, bool]]:
    """The observation's member multiset ``{(id, counted, followed): copies}`` from its family."""
    projected = family.project(year=stored.key[8], window=stored.key[6], dimension=stored.key[7])
    return Counter(
        {
            (str(ident), bool(counted), bool(followed)): int(copies)
            for ident, counted, followed, copies in projected.group_by(
                "member_id", "counted", "followed"
            )
            .sum()
            .rename({"multiplicity": "copies"})
            .iter_rows()
        }
    )


@dataclass(slots=True)
class _Families:
    """The stored families one subject's verified observations cite, read once each."""

    session: Session
    registry: Registry
    content_hash: str
    result: VerifyResult
    stored: dict[uuid.UUID, MemberFamily | None] = field(default_factory=dict)

    def of(self, item: StoredObservation) -> MemberFamily | None:
        """The stored family of ``item`` (``None`` when it cannot be read); read and checked once."""
        if item.family_id is None:  # pragma: no cover - the column is NOT NULL
            return None
        if item.family_id not in self.stored:
            definition = self.registry.metrics[item.definition[0]]
            family = read_family(
                self.session,
                item.family_id,
                kind=_member_kind(self.session, item.family_id),
                mode=mode_for(definition.kind, definition.dimension),
                windows=windows_for(definition.kind, definition.windows_days),
            )
            if family.digest != item.family_hash:
                self.result.mismatches.append(
                    _mismatch(
                        item,
                        None,
                        self.content_hash,
                        MEMBERS_HASH_COLUMN,
                        item.family_hash,
                        family.digest,
                    )
                )
            self.stored[item.family_id] = family
        return self.stored[item.family_id]


def _member_kind(session: Session, family_id: uuid.UUID) -> str:
    family = Base.metadata.tables["metric_member_family"]
    kind = session.scalar(select(family.c.member_kind).where(family.c.id == family_id))
    return str(kind)


def _compare(
    stored: StoredObservation,
    draft: ObservationDraft,
    registry: Registry,
    content_hash: str,
    families: _Families,
) -> list[Mismatch]:
    found: list[Mismatch] = []
    expected = stored_columns(draft, registry)
    for column in VERIFIED_COLUMNS:
        if stored.columns[column] != expected[column]:
            found.append(
                _mismatch(
                    stored, draft, content_hash, column, stored.columns[column], expected[column]
                )
            )
    if stored.definition != (draft.slug, draft.version):
        found.append(
            _mismatch(
                stored, draft, content_hash, "definition_version", stored.definition, draft.version
            )
        )
    recomputed = draft.family
    if recomputed is None or stored.family_hash != recomputed.digest:
        # The hashes differ: expand the two multisets and compare them for this observation
        # (the families may differ elsewhere, in observations that are not this one).
        stored_family = families.of(stored)
        stored_members = (
            Counter[tuple[str, bool, bool]]()
            if stored_family is None
            else _multiset(stored_family, stored)
        )
        recomputed_members = (
            Counter[tuple[str, bool, bool]]()
            if recomputed is None
            else _multiset(recomputed, stored)
        )
        if stored_members != recomputed_members:
            found.append(
                _mismatch(
                    stored,
                    draft,
                    content_hash,
                    MEMBERS_COLUMN,
                    {"members": sum(stored_members.values())},
                    {"members": sum(recomputed_members.values())},
                )
            )
    else:
        families.of(stored)  # the stored rows are read and hashed against the recorded hash
    return found


# --- the observations to verify, grouped ---------------------------------------------------------


@dataclass(slots=True)
class _Group:
    """The current observations citing one snapshot, by source, and the subjects they belong to."""

    snapshot_id: uuid.UUID
    content_hash: str
    # source id -> subject (type, id) -> the (slug, definition version, registry version, kind) held
    subjects: dict[str, dict[tuple[str, str], set[tuple[str, str, int, str]]]] = field(
        default_factory=dict
    )


def _groups(
    session: Session, registry: Registry, snapshot_id: uuid.UUID | None
) -> tuple[int, dict[uuid.UUID, _Group]]:
    """The count of current observations and, per snapshot they cite, who holds what."""
    statement = (
        select(
            OBSERVATION.c.snapshot_id,
            SNAPSHOT.c.content_hash,
            OBSERVATION.c.source_id,
            OBSERVATION.c.subject_type,
            OBSERVATION.c.subject_id,
            DEFINITION.c.slug,
            DEFINITION.c.version,
            OBSERVATION.c.registry_version,
            DEFINITION.c.kind,
            sa.func.count().label("held"),
        )
        .join(SNAPSHOT, SNAPSHOT.c.id == OBSERVATION.c.snapshot_id)
        .join(DEFINITION, DEFINITION.c.id == OBSERVATION.c.metric_definition_id)
        .where(OBSERVATION.c.superseded_at.is_(None))
        .group_by(
            OBSERVATION.c.snapshot_id,
            SNAPSHOT.c.content_hash,
            OBSERVATION.c.source_id,
            OBSERVATION.c.subject_type,
            OBSERVATION.c.subject_id,
            DEFINITION.c.slug,
            DEFINITION.c.version,
            OBSERVATION.c.registry_version,
            DEFINITION.c.kind,
        )
    )
    if snapshot_id is not None:
        statement = statement.where(OBSERVATION.c.snapshot_id == snapshot_id)
    total = 0
    groups: dict[uuid.UUID, _Group] = {}
    for row in session.execute(statement).all():
        sid = uuid.UUID(str(row.snapshot_id))
        group = groups.setdefault(sid, _Group(sid, str(row.content_hash)))
        subject_type = getattr(row.subject_type, "value", str(row.subject_type))
        held = group.subjects.setdefault(str(row.source_id), {}).setdefault(
            (str(subject_type), str(row.subject_id)), set()
        )
        held.add((str(row.slug), str(row.version), int(row.registry_version), str(row.kind)))
        total += int(row.held)
    del registry
    return total, groups


def verify(
    session: Session,
    settings: Settings,
    snapshot: str | None = None,
    registry: Registry | None = None,
) -> VerifyResult:
    """Recompute every current observation (or one snapshot's) and compare (module docstring)."""
    registry = registry or load_registry()
    result = VerifyResult()
    snapshot_id: uuid.UUID | None = None
    wanted_hash: str | None = None
    if snapshot is not None:
        wanted_hash = validate_content_hash(snapshot)
        snapshot_id = _snapshot_id(session, wanted_hash)
        if snapshot_id is None:
            log.warning("metrics.verify.unknown_snapshot", snapshot=wanted_hash)
            return result
    result.observations, groups = _groups(session, registry, snapshot_id)
    if wanted_hash is None:
        latest = _latest_coverage_snapshot(session)
        if latest is not None and latest[0] not in groups:
            groups[latest[0]] = _Group(latest[0], latest[1])
    elif snapshot_id is not None and snapshot_id not in groups:
        groups[snapshot_id] = _Group(snapshot_id, wanted_hash)
    for group in sorted(groups.values(), key=lambda item: item.content_hash):
        result.snapshots.append(group.content_hash)
        _verify_snapshot(session, settings, registry, group, result)
    log.info(
        "metrics.verified",
        snapshots=len(result.snapshots),
        observations=result.observations,
        verified=result.verified,
        mismatches=len(result.mismatches),
        unverifiable=len(result.unverifiable),
        coverage_statistics=result.coverage_statistics,
        coverage_mismatches=len(result.coverage_mismatches),
        ok=result.ok,
    )
    return result


ModelsBySource = dict[str, dict[tuple[str, int | None], "ModelParameters"]]


def _cited_models(
    settings: Settings,
    content_hash: str,
    items: Sequence[StoredObservation],
    result: VerifyResult,
) -> tuple[list[StoredObservation], ModelsBySource]:
    """The adjusted observations' models read from their artifacts (module docstring).

    Returns the observations that remain verifiable and the models by source
    and ``(target, window)``; every other observation is reported here.
    """
    from judgemetrics.metrics.adjustment.artifacts import ArtifactError
    from judgemetrics.metrics.adjustment.catalog import read_parameters
    from judgemetrics.metrics.adjustment.spec import SpecError, load_spec

    try:
        spec_version: int | None = load_spec().version
    except SpecError:
        spec_version = None
    loaded: dict[str, ModelParameters | str] = {}
    cited: list[tuple[StoredObservation, ModelParameters]] = []
    kept: list[StoredObservation] = []
    for item in items:
        model_hash = item.columns[MODEL_HASH]
        if model_hash is None:
            result.mismatches.append(
                _mismatch(item, None, content_hash, MODEL_COLUMN, None, "a cited model")
            )
            continue
        if model_hash not in loaded:
            try:
                loaded[model_hash] = read_parameters(settings, content_hash, model_hash)
            except ArtifactError as exc:
                loaded[model_hash] = str(exc)
        parameters = loaded[model_hash]
        if isinstance(parameters, str):
            result.mismatches.append(
                _mismatch(item, None, content_hash, MODEL_COLUMN, model_hash, parameters)
            )
        elif parameters.spec_version != spec_version:
            reason = (
                f"model {model_hash} was fitted under specification {parameters.spec_version}; "
                f"the file is {spec_version}"
            )
            result.unverifiable.append(Unverifiable(item.id, content_hash, item.key[0], reason))
        else:
            cited.append((item, parameters))
    hashes: dict[tuple[str, str, int | None], set[str | None]] = {}
    for item, parameters in cited:
        key = (str(item.key[3]), parameters.target, parameters.window_days)
        hashes.setdefault(key, set()).add(parameters.content_hash)
    models: ModelsBySource = {}
    for item, parameters in cited:
        source, target, window = str(item.key[3]), parameters.target, parameters.window_days
        if len(hashes[(source, target, window)]) > 1:
            reason = "the snapshot's observations cite two models for one target and window"
            result.unverifiable.append(Unverifiable(item.id, content_hash, item.key[0], reason))
            continue
        models.setdefault(source, {})[(target, window)] = parameters
        kept.append(item)
    return kept, models


def _verify_coverage(
    session: Session,
    snapshot_view: Snapshot,
    snapshot_id: uuid.UUID,
    content_hash: str,
    result: VerifyResult,
) -> None:
    """The snapshot's stored coverage statistics against a recompute from the snapshot."""
    stored = load_statistics(session, snapshot_id)
    if not stored:
        return
    result.coverage_statistics += len(stored)
    drafts = compute_statistics(snapshot_view)
    result.coverage_mismatches.extend(compare_statistics(content_hash, stored, drafts))


def _unverifiable_reason(registry: Registry, held: tuple[str, str, int, str]) -> str | None:
    slug, version, registry_version, _ = held
    if registry_version != registry.version:
        return f"registry version {registry_version} is not the current {registry.version}"
    if slug not in registry.metrics or registry.metrics[slug].version != version:
        return f"definition {slug} version {version} is not in the current registry"
    return None


def _verify_snapshot(
    session: Session,
    settings: Settings,
    registry: Registry,
    group: _Group,
    result: VerifyResult,
) -> None:
    content_hash = group.content_hash
    # The adjusted observations first: their models are read from artifacts, and an
    # observation whose model is missing or altered is reported and not recomputed.
    adjusted_ok: set[uuid.UUID] = set()
    models: ModelsBySource = {}
    adjusted_held = any(
        held[3] == OBSERVED_EXPECTED
        for sources in group.subjects.values()
        for held_set in sources.values()
        for held in held_set
        if _unverifiable_reason(registry, held) is None
    )
    if adjusted_held:
        adjusted = [
            item
            for item in load_observations(
                session, snapshot_id=group.snapshot_id, kinds={OBSERVED_EXPECTED}
            )
            if _unverifiable_reason(
                registry,
                (
                    item.definition[0],
                    item.definition[1],
                    int(item.columns["registry_version"]),
                    item.kind,
                ),
            )
            is None
        ]
        kept, models = _cited_models(settings, content_hash, adjusted, result)
        adjusted_ok = {item.id for item in kept}
    try:
        opened = open_snapshot(settings, content_hash)
    except SnapshotError as exc:
        for sources in group.subjects.values():
            for subject_type, subject_id in sources:
                for item in load_observations(
                    session, snapshot_id=group.snapshot_id, subject=(subject_type, subject_id)
                ):
                    result.unverifiable.append(
                        Unverifiable(item.id, content_hash, item.definition[0], f"snapshot: {exc}")
                    )
        return
    with opened as snapshot_view:
        _verify_coverage(session, snapshot_view, group.snapshot_id, content_hash, result)
        for source_id, subjects in sorted(group.subjects.items()):
            _verify_source(
                session,
                registry,
                snapshot_view,
                group,
                source_id,
                subjects,
                models,
                adjusted_ok,
                result,
            )


def _verify_source(
    session: Session,
    registry: Registry,
    snapshot_view: Snapshot,
    group: _Group,
    source_id: str,
    subjects: dict[tuple[str, str], set[tuple[str, str, int, str]]],
    models: ModelsBySource,
    adjusted_ok: set[uuid.UUID],
    result: VerifyResult,
) -> None:
    content_hash = group.content_hash
    kinds = {
        held[3]
        for held_set in subjects.values()
        for held in held_set
        if _unverifiable_reason(registry, held) is None
        and (held[3] != OBSERVED_EXPECTED or source_id in models)
    }
    # Every subject's unverifiable observations are reported; the rest are recomputed.
    verifiable_subjects: list[Subject] = []
    pending: dict[tuple[str, str], list[StoredObservation]] = {}
    for (subject_type, subject_id), held_set in sorted(subjects.items()):
        items = load_observations(
            session,
            snapshot_id=group.snapshot_id,
            subject=(subject_type, subject_id),
            source_id=uuid.UUID(source_id),
        )
        verifiable: list[StoredObservation] = []
        for item in items:
            reason = _unverifiable_reason(
                registry,
                (
                    item.definition[0],
                    item.definition[1],
                    int(item.columns["registry_version"]),
                    item.kind,
                ),
            )
            if reason is not None:
                result.unverifiable.append(
                    Unverifiable(item.id, content_hash, item.definition[0], reason)
                )
            elif item.kind == OBSERVED_EXPECTED and item.id not in adjusted_ok:
                continue  # already reported with its model
            else:
                verifiable.append(item)
        del held_set
        if verifiable:
            pending[(subject_type, subject_id)] = verifiable
            verifiable_subjects.append(Subject(subject_type, subject_id))
    if not verifiable_subjects:
        return
    frame = _frame(snapshot_view, source_id, pending, content_hash, result)
    if frame is None:
        return
    try:
        for computed in iter_frame(
            frame,
            registry,
            source_id,
            verifiable_subjects,
            kinds=kinds,
            models=models.get(source_id),
        ):
            key = (computed.subject.subject_type, str(computed.subject.subject_id))
            items = pending.pop(key, [])
            if items:
                _verify_subject(session, registry, content_hash, items, computed, result)
    except ComputeError as exc:
        # The recompute itself failed (a model missing, say): nothing not yet compared
        # can be, and each such observation is reported with the reason.
        for items in pending.values():
            for item in items:
                result.unverifiable.append(
                    Unverifiable(item.id, content_hash, item.definition[0], f"compute: {exc}")
                )
        return
    # A subject the frame no longer holds at all: every observation of it is gone.
    for items in pending.values():
        for item in items:
            result.mismatches.append(
                _mismatch(item, None, content_hash, OBSERVATION_COLUMN, "present", "absent")
            )


def _frame(
    snapshot_view: Snapshot,
    source_id: str,
    pending: dict[tuple[str, str], list[StoredObservation]],
    content_hash: str,
    result: VerifyResult,
) -> Any:
    try:
        return snapshot_view.frame(source_id)
    except SnapshotError as exc:
        reason = f"compute: cannot build the frame of source {source_id}: {exc}"
        for items in pending.values():
            for item in items:
                result.unverifiable.append(
                    Unverifiable(item.id, content_hash, item.definition[0], reason)
                )
        return None


def _verify_subject(
    session: Session,
    registry: Registry,
    content_hash: str,
    items: list[StoredObservation],
    computed: SubjectResult,
    result: VerifyResult,
) -> None:
    drafts = {draft.key: draft for draft in computed.drafts}
    families = _Families(session, registry, content_hash, result)
    seen: set[tuple[Any, ...]] = set()
    for item in items:
        draft = drafts.get(item.key)
        if draft is None:
            result.mismatches.append(
                _mismatch(item, None, content_hash, OBSERVATION_COLUMN, "present", "absent")
            )
            continue
        seen.add(item.key)
        found = _compare(item, draft, registry, content_hash, families)
        result.mismatches.extend(found)
        if not found:
            result.verified += 1
    # An observation the store lacks counts only where the subject holds that kind here.
    held_kinds = {item.kind for item in items}
    for key, draft in sorted(drafts.items(), key=lambda pair: str(pair[0])):
        if key in seen or registry.metrics[draft.slug].kind not in held_kinds:
            continue
        result.mismatches.append(
            _mismatch(None, draft, content_hash, OBSERVATION_COLUMN, "absent", "present")
        )


__all__ = [
    "ComputeError",
    "Mismatch",
    "Unverifiable",
    "VerifyResult",
    "verify",
]
