# src/judgemetrics/metrics/verify.py
"""Verification: every current observation recomputed from its own snapshot.

``verify(session, settings, snapshot=None)`` loads every current
observation (``superseded_at IS NULL``), or those of one snapshot hash,
groups them by snapshot, opens each snapshot from ``snapshot_dir``,
recomputes the observations' subjects with the registry version the
observation records — the current registry file must carry that
``registry_version`` and the observation's ``(slug, version)``, otherwise
the observation is reported ``unverifiable`` rather than compared against
a different contract — and compares every stored column of
``publish.VERIFIED_COLUMNS`` and the member multiset exactly. The result
lists every mismatch (observation id, slug, subject, window, dimension,
column, stored and recomputed values), every observation the recompute
no longer produces (``column = "observation"``), every recomputed
observation the store lacks for a subject it holds, and every
unverifiable observation with its reason. ``ok`` is true only when all
four lists are empty; the CLI exits 1 otherwise. Log lines carry the
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
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import Base
from judgemetrics.logging import get_logger
from judgemetrics.metrics.attribution import Subject
from judgemetrics.metrics.compute import ComputeError, ObservationDraft, compute_all
from judgemetrics.metrics.coverage import (
    CoverageMismatch,
    compare_statistics,
    compute_statistics,
    load_statistics,
)
from judgemetrics.metrics.publish import (
    MODEL_HASH,
    VERIFIED_COLUMNS,
    StoredObservation,
    load_observations,
    member_tuples,
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
OBSERVATION_COLUMN = "observation"
MEMBERS_COLUMN = "members"
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


def _snapshot_hashes(session: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = session.execute(
        select(SNAPSHOT.c.id, SNAPSHOT.c.content_hash).where(SNAPSHOT.c.id.in_(ids))
    ).all()
    return {uuid.UUID(str(row.id)): str(row.content_hash) for row in rows}


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


def _compare(
    stored: StoredObservation, draft: ObservationDraft, registry: Registry, content_hash: str
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
    recomputed_members = member_tuples(draft.members)
    if stored.members != recomputed_members:
        found.append(
            _mismatch(
                stored,
                draft,
                content_hash,
                MEMBERS_COLUMN,
                {"members": len(stored.members)},
                {"members": len(recomputed_members)},
            )
        )
    return found


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
    stored = load_observations(session, snapshot_id=snapshot_id)
    result.observations = len(stored)
    hashes = _snapshot_hashes(session, {item.snapshot_id for item in stored})
    by_snapshot: dict[str, list[StoredObservation]] = {}
    ids: dict[str, uuid.UUID] = {}
    for item in stored:
        by_snapshot.setdefault(hashes[item.snapshot_id], []).append(item)
        ids[hashes[item.snapshot_id]] = item.snapshot_id
    if wanted_hash is None:
        latest = _latest_coverage_snapshot(session)
        if latest is not None:
            by_snapshot.setdefault(latest[1], [])
            ids[latest[1]] = latest[0]
    elif snapshot_id is not None:
        by_snapshot.setdefault(wanted_hash, [])
        ids[wanted_hash] = snapshot_id
    for content_hash in sorted(by_snapshot):
        items = by_snapshot[content_hash]
        result.snapshots.append(content_hash)
        _verify_snapshot(
            session, settings, registry, content_hash, ids[content_hash], items, result
        )
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
        if item.kind != OBSERVED_EXPECTED:
            kept.append(item)
            continue
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


def _verify_snapshot(
    session: Session,
    settings: Settings,
    registry: Registry,
    content_hash: str,
    snapshot_id: uuid.UUID,
    items: Sequence[StoredObservation],
    result: VerifyResult,
) -> None:
    verifiable: list[StoredObservation] = []
    for item in items:
        slug, version = item.definition
        reason: str | None = None
        if item.columns["registry_version"] != registry.version:
            reason = (
                f"registry version {item.columns['registry_version']} is not the current "
                f"{registry.version}"
            )
        elif slug not in registry.metrics or registry.metrics[slug].version != version:
            reason = f"definition {slug} version {version} is not in the current registry"
        if reason is not None:
            result.unverifiable.append(Unverifiable(item.id, content_hash, slug, reason))
        else:
            verifiable.append(item)
    kinds = {item.kind for item in verifiable}
    models: ModelsBySource | None = None
    if OBSERVED_EXPECTED in kinds:
        verifiable, models = _cited_models(settings, content_hash, verifiable, result)
        kinds = {item.kind for item in verifiable}
    try:
        opened = open_snapshot(settings, content_hash)
    except SnapshotError as exc:
        for item in verifiable:
            result.unverifiable.append(
                Unverifiable(item.id, content_hash, item.definition[0], f"snapshot: {exc}")
            )
        return
    with opened as snapshot_view:
        _verify_coverage(session, snapshot_view, snapshot_id, content_hash, result)
        if not verifiable:
            return
        subjects = sorted({(item.key[1], item.key[2]) for item in verifiable})
        try:
            computed = compute_all(
                snapshot_view,
                registry,
                [Subject(kind, sid) for kind, sid in subjects],
                kinds=kinds,
                models=models,
                sources={str(item.key[3]) for item in verifiable},
            )
        except ComputeError as exc:
            for item in verifiable:
                result.unverifiable.append(
                    Unverifiable(item.id, content_hash, item.definition[0], f"compute: {exc}")
                )
            return
    drafts = {draft.key: draft for draft in computed.drafts}
    seen: set[tuple[Any, ...]] = set()
    for item in verifiable:
        draft = drafts.get(item.key)
        if draft is None:
            result.mismatches.append(
                _mismatch(item, None, content_hash, OBSERVATION_COLUMN, "present", "absent")
            )
            continue
        seen.add(item.key)
        found = _compare(item, draft, registry, content_hash)
        result.mismatches.extend(found)
        if not found:
            result.verified += 1
    # An observation the store lacks counts only where the subject holds that kind here.
    stored_subjects = {(item.key[1], item.key[2], item.key[3], item.kind) for item in verifiable}
    for key, draft in sorted(drafts.items(), key=lambda pair: str(pair[0])):
        kind = registry.metrics[draft.slug].kind
        if (
            key in seen
            or (draft.subject_type, draft.subject_id, draft.source_id, kind) not in stored_subjects
        ):
            continue
        result.mismatches.append(
            _mismatch(None, draft, content_hash, OBSERVATION_COLUMN, "absent", "present")
        )
