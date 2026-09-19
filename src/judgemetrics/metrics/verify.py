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
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import Base
from judgemetrics.logging import get_logger
from judgemetrics.metrics.attribution import Subject
from judgemetrics.metrics.compute import ComputeError, ObservationDraft, compute_all
from judgemetrics.metrics.publish import (
    VERIFIED_COLUMNS,
    StoredObservation,
    load_observations,
    member_tuples,
    stored_columns,
)
from judgemetrics.metrics.registry import Registry, load_registry
from judgemetrics.metrics.snapshot import SnapshotError, open_snapshot, validate_content_hash

log = get_logger(__name__)

SNAPSHOT = Base.metadata.tables["metric_snapshot"]
OBSERVATION_COLUMN = "observation"
MEMBERS_COLUMN = "members"


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

    @property
    def ok(self) -> bool:
        return not self.mismatches and not self.unverifiable

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "observations": self.observations,
            "verified": self.verified,
            "snapshots": list(self.snapshots),
            "mismatches": [item.as_dict() for item in self.mismatches],
            "unverifiable": [item.as_dict() for item in self.unverifiable],
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
    if snapshot is not None:
        content_hash = validate_content_hash(snapshot)
        snapshot_id = _snapshot_id(session, content_hash)
        if snapshot_id is None:
            log.warning("metrics.verify.unknown_snapshot", snapshot=content_hash)
            return result
    stored = load_observations(session, snapshot_id=snapshot_id)
    result.observations = len(stored)
    hashes = _snapshot_hashes(session, {item.snapshot_id for item in stored})
    by_snapshot: dict[str, list[StoredObservation]] = {}
    for item in stored:
        by_snapshot.setdefault(hashes[item.snapshot_id], []).append(item)
    for content_hash in sorted(by_snapshot):
        items = by_snapshot[content_hash]
        result.snapshots.append(content_hash)
        _verify_snapshot(settings, registry, content_hash, items, result)
    log.info(
        "metrics.verified",
        snapshots=len(result.snapshots),
        observations=result.observations,
        verified=result.verified,
        mismatches=len(result.mismatches),
        unverifiable=len(result.unverifiable),
        ok=result.ok,
    )
    return result


def _verify_snapshot(
    settings: Settings,
    registry: Registry,
    content_hash: str,
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
    if not verifiable:
        return
    try:
        opened = open_snapshot(settings, content_hash)
    except SnapshotError as exc:
        for item in verifiable:
            result.unverifiable.append(
                Unverifiable(item.id, content_hash, item.definition[0], f"snapshot: {exc}")
            )
        return
    with opened as snapshot_view:
        subjects = sorted({(item.key[1], item.key[2]) for item in verifiable})
        try:
            computed = compute_all(
                snapshot_view, registry, [Subject(kind, sid) for kind, sid in subjects]
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
    stored_subjects = {(item.key[1], item.key[2], item.key[3]) for item in verifiable}
    for key, draft in sorted(drafts.items(), key=lambda pair: str(pair[0])):
        if (
            key in seen
            or (draft.subject_type, draft.subject_id, draft.source_id) not in stored_subjects
        ):
            continue
        result.mismatches.append(
            _mismatch(None, draft, content_hash, OBSERVATION_COLUMN, "absent", "present")
        )
