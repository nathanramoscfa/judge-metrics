# src/judgemetrics/metrics/adjustment/catalog.py
"""The ``outcome_model`` catalogue: fit a snapshot's missing models, list, show, verify.

``fit_snapshot(session, settings, snapshot_hash=None)`` takes the latest
snapshot (``exported_at`` descending, as ``/api/v1/ready`` reports it) or
the named one, works out which ``(source, target, window)`` models of the
current specification version and seed it lacks — a source's targets whose
outcome it cannot document are never wanted — fits only those
(``fit.fit_models``), writes their artifacts, and inserts one row per model
(``ON CONFLICT DO NOTHING``), so a second run fits nothing. The caller owns
the transaction (the CLI commits).

``snapshot_parameters`` (Phase 4 Step 3) reads the models of a snapshot's
current specification version and seed back from their artifacts
(``read_parameters``: the path rebuilt from the configured snapshot
directory and the two validated hashes, the bytes checked against the
content hash, parsed as JSON only) for ``metrics compute``; ``metrics
verify`` reads the models its observations cite the same way.

``list_models`` and ``model_card`` read the rows (the model card never
carries ``storage_uri``). ``verify_models`` checks that every artifact
exists at the path rebuilt from the configured snapshot directory and the
two validated hashes (never from the stored URI), hashes to its row's
``content_hash``, and agrees with the row's columns; with ``refit=True`` it
refits every model from its snapshot and seed — under the code version the
row records — and compares the bytes, naming the model and the first field
that differs.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import MetricSnapshot, OutcomeModel, Source
from judgemetrics.logging import get_logger
from judgemetrics.metrics.adjustment.artifacts import (
    HEX64,
    ArtifactError,
    artifact_path,
    content_hash,
    first_difference,
    read_artifact,
)
from judgemetrics.metrics.adjustment.expected import ExpectationError, ModelParameters
from judgemetrics.metrics.adjustment.features import instant
from judgemetrics.metrics.adjustment.fit import FittedModel, ModelKey, fit_models
from judgemetrics.metrics.adjustment.spec import DECISION, OutcomeModelSpec, load_spec
from judgemetrics.metrics.snapshot import (
    code_version,
    open_snapshot,
    snapshot_root,
    validate_content_hash,
)

log = get_logger(__name__)


class CatalogError(RuntimeError):
    """A snapshot or a model cannot be found, or a request cannot be served as asked."""


@dataclass(frozen=True, slots=True)
class FitSummary:
    snapshot: str
    fitted: tuple[FittedModel, ...]
    existing: int

    def as_dict(self) -> dict[str, Any]:
        statuses: dict[str, int] = {}
        for model in self.fitted:
            statuses[model.status] = statuses.get(model.status, 0) + 1
        return {
            "snapshot": self.snapshot,
            "fitted": len(self.fitted),
            "existing": self.existing,
            "statuses": dict(sorted(statuses.items())),
            "models": [
                {
                    "source": model.source,
                    "target": model.target,
                    "window_days": model.window_days,
                    "status": model.status,
                    "rows": model.design.rows,
                    "events": model.design.events,
                    "content_hash": model.content_hash,
                }
                for model in self.fitted
            ],
        }


@dataclass(frozen=True, slots=True)
class ModelRow:
    """One ``outcome_model`` row as ``models list`` shows it."""

    id: uuid.UUID
    content_hash: str
    snapshot: str
    source: str
    target: str
    window_days: int | None
    seed: int
    spec_version: int
    status: str
    n_train: int
    events_train: int
    n_test: int
    events_test: int
    fitted_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "content_hash": self.content_hash,
            "snapshot": self.snapshot,
            "source": self.source,
            "target": self.target,
            "window_days": self.window_days,
            "seed": self.seed,
            "spec_version": self.spec_version,
            "status": self.status,
            "n_train": self.n_train,
            "events_train": self.events_train,
            "n_test": self.n_test,
            "events_test": self.events_test,
            "fitted_at": self.fitted_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class Problem:
    """A verification failure: which model, which field, what was found."""

    model_id: uuid.UUID
    target: str
    window_days: int | None
    field: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": str(self.model_id),
            "target": self.target,
            "window_days": self.window_days,
            "field": self.field,
            "detail": self.detail,
        }


@dataclass(slots=True)
class VerifyResult:
    models: int = 0
    verified: int = 0
    refitted: int = 0
    problems: list[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, Any]:
        return {
            "models": self.models,
            "verified": self.verified,
            "refitted": self.refitted,
            "ok": self.ok,
            "problems": [problem.as_dict() for problem in self.problems],
        }


# --- snapshots ------------------------------------------------------------------------------


def resolve_snapshot(session: Session, snapshot_hash: str | None) -> MetricSnapshot:
    """The named snapshot (validated) or the latest one; ``CatalogError`` when there is none."""
    stmt = select(MetricSnapshot)
    if snapshot_hash is not None:
        stmt = stmt.where(MetricSnapshot.content_hash == validate_content_hash(snapshot_hash))
    else:
        stmt = stmt.order_by(MetricSnapshot.exported_at.desc(), MetricSnapshot.id).limit(1)
    row = session.scalars(stmt).first()
    if row is None:
        if snapshot_hash is not None:
            msg = f"no metric snapshot {snapshot_hash} is recorded"
        else:
            msg = "no metric snapshot is recorded: run `judgemetrics metrics compute` first"
        raise CatalogError(msg)
    return row


def _existing_keys(
    session: Session, snapshot_id: uuid.UUID, spec: OutcomeModelSpec
) -> set[ModelKey]:
    rows = session.execute(
        select(Source.name, OutcomeModel.target, OutcomeModel.window_days)
        .join(Source, Source.id == OutcomeModel.source_id)
        .where(
            OutcomeModel.snapshot_id == snapshot_id,
            OutcomeModel.spec_version == spec.version,
            OutcomeModel.seed == spec.seed,
        )
    ).all()
    return {(str(name), str(target), window) for name, target, window in rows}


def _row_values(
    model: FittedModel, snapshot: MetricSnapshot, settings: Settings, fitted_at: datetime
) -> dict[str, Any]:
    split = model.split
    path = artifact_path(snapshot_root(settings), snapshot.content_hash, model.content_hash)
    return {
        "content_hash": model.content_hash,
        "snapshot_id": snapshot.id,
        "source_id": uuid.UUID(model.source_id),
        "spec_version": model.spec_version,
        "model_version": model.model_version,
        "target": model.target,
        "window_days": model.window_days,
        "seed": model.seed,
        "status": model.status,
        "n_train": split.train_rows,
        "events_train": split.train_events,
        "n_test": split.test_rows,
        "events_test": split.test_events,
        "train_start": None if model.train_start is None else instant(model.train_start),
        "train_end": None if model.train_end is None else instant(model.train_end),
        "split_cutoff": None if split.cutoff is None else instant(split.cutoff),
        "diagnostics": model.diagnostics_row(),
        "coefficients": model.coefficient_rows(),
        "storage_uri": path.as_uri(),
        "code_version": code_version(settings),
        "fitted_at": fitted_at,
    }


def fit_snapshot(
    session: Session,
    settings: Settings,
    *,
    snapshot_hash: str | None = None,
    spec: OutcomeModelSpec | None = None,
) -> FitSummary:
    """Fit and record every model the snapshot lacks (see the module docstring)."""
    spec = spec or load_spec()
    snapshot_row = resolve_snapshot(session, snapshot_hash)
    existing = _existing_keys(session, snapshot_row.id, spec)
    with open_snapshot(settings, snapshot_row.content_hash) as snapshot:
        wanted: set[ModelKey] = set()
        for source in snapshot.sources_with_cases():
            if not source.has_coverage:
                continue
            for target in spec.targets:
                if target.index != DECISION and target.outcome not in source.observable_outcomes:
                    continue
                wanted.update((source.name, target.name, window) for window in target.windows)
        missing = wanted - existing
        if not missing:
            log.info(
                "models.fit.nothing_to_do",
                snapshot=snapshot_row.content_hash,
                existing=len(existing),
            )
            return FitSummary(snapshot=snapshot_row.content_hash, fitted=(), existing=len(existing))
        models = fit_models(
            snapshot,
            spec,
            seed=spec.seed,
            code_version=code_version(settings),
            only=missing,
        )
    fitted_at = datetime.now(tz=UTC)
    rows = [_row_values(model, snapshot_row, settings, fitted_at) for model in models]
    if rows:
        session.execute(insert(OutcomeModel).values(rows).on_conflict_do_nothing())
        session.flush()
    log.info(
        "models.fit.recorded",
        snapshot=snapshot_row.content_hash,
        fitted=len(models),
        existing=len(existing),
    )
    return FitSummary(
        snapshot=snapshot_row.content_hash, fitted=tuple(models), existing=len(existing)
    )


# --- model parameters for the adjusted figures ------------------------------------------------


def read_parameters(settings: Settings, snapshot_hash: str, model_hash: str) -> ModelParameters:
    """A model's parameters from its artifact; ``ArtifactError`` when it is missing or altered.

    The path is rebuilt from the configured snapshot directory and the two
    validated hashes (never from ``storage_uri``); the bytes must hash to
    ``model_hash`` before they are parsed, as JSON only.
    """
    path = artifact_path(snapshot_root(settings), snapshot_hash, model_hash)
    if not path.is_file():
        msg = f"the artifact of model {model_hash} is missing"
        raise ArtifactError(msg)
    data = path.read_bytes()
    if content_hash(data) != model_hash:
        msg = f"the artifact of model {model_hash} does not hash to its content hash"
        raise ArtifactError(msg)
    try:
        payload = _parsed(data)
    except ValueError as exc:
        msg = f"the artifact of model {model_hash} is not JSON"
        raise ArtifactError(msg) from exc
    if not isinstance(payload, dict) or payload.get("snapshot") != snapshot_hash:
        msg = f"the artifact of model {model_hash} names another snapshot"
        raise ArtifactError(msg)
    try:
        return ModelParameters.from_artifact(payload, model_hash)
    except ExpectationError as exc:
        raise ArtifactError(str(exc)) from exc


SourceParameters = dict[str, dict[tuple[str, int | None], ModelParameters]]


def snapshot_parameters(
    session: Session,
    settings: Settings,
    *,
    snapshot_id: uuid.UUID,
    snapshot_hash: str,
    spec: OutcomeModelSpec | None = None,
) -> SourceParameters:
    """Per source id, the snapshot's models of the current spec version and seed, by target."""
    spec = spec or load_spec()
    rows = session.execute(
        select(OutcomeModel.source_id, OutcomeModel.content_hash)
        .where(
            OutcomeModel.snapshot_id == snapshot_id,
            OutcomeModel.spec_version == spec.version,
            OutcomeModel.seed == spec.seed,
        )
        .order_by(OutcomeModel.source_id, OutcomeModel.target, OutcomeModel.window_days)
    ).all()
    parameters: SourceParameters = {}
    for source_id, model_hash in rows:
        model = read_parameters(settings, snapshot_hash, str(model_hash))
        parameters.setdefault(str(source_id), {})[(model.target, model.window_days)] = model
    return parameters


# --- reading ------------------------------------------------------------------------------


def _target_order(spec: OutcomeModelSpec) -> dict[str, int]:
    return {target.name: index for index, target in enumerate(spec.targets)}


def list_models(
    session: Session, *, snapshot_hash: str | None = None
) -> tuple[str, list[ModelRow]]:
    """The models of the named or the latest snapshot, by source, target, and window."""
    snapshot = resolve_snapshot(session, snapshot_hash)
    rows = session.execute(
        select(OutcomeModel, Source.name)
        .join(Source, Source.id == OutcomeModel.source_id)
        .where(OutcomeModel.snapshot_id == snapshot.id)
    ).all()
    order = _target_order(load_spec())
    result = [
        ModelRow(
            id=model.id,
            content_hash=model.content_hash,
            snapshot=snapshot.content_hash,
            source=str(name),
            target=model.target,
            window_days=model.window_days,
            seed=model.seed,
            spec_version=model.spec_version,
            status=model.status,
            n_train=model.n_train,
            events_train=model.events_train,
            n_test=model.n_test,
            events_test=model.events_test,
            fitted_at=model.fitted_at,
        )
        for model, name in rows
    ]
    result.sort(
        key=lambda row: (
            row.source,
            order.get(row.target, len(order)),
            row.target,
            -1 if row.window_days is None else row.window_days,
            row.seed,
            row.spec_version,
        )
    )
    return snapshot.content_hash, result


def parse_model_identifier(text: str) -> uuid.UUID | str:
    """A model id (UUID) or a 64-hex content hash; ``CatalogError`` otherwise."""
    value = text.strip().lower()
    if HEX64.match(value):
        return value
    try:
        return uuid.UUID(value)
    except ValueError:
        msg = "a model is named by its id (a UUID) or its 64-character content hash"
        raise CatalogError(msg) from None


def model_card(session: Session, identifier: uuid.UUID | str) -> dict[str, Any]:
    """The model card: versions, counts, range, diagnostics, coefficients (never storage_uri)."""
    condition = (
        OutcomeModel.id == identifier
        if isinstance(identifier, uuid.UUID)
        else OutcomeModel.content_hash == identifier
    )
    row = session.execute(
        select(OutcomeModel, Source.name, MetricSnapshot.content_hash)
        .join(Source, Source.id == OutcomeModel.source_id)
        .join(MetricSnapshot, MetricSnapshot.id == OutcomeModel.snapshot_id)
        .where(condition)
    ).first()
    if row is None:
        msg = f"no outcome model {identifier}"
        raise CatalogError(msg)
    model, source, snapshot = row

    def stamp(value: datetime | None) -> str | None:
        return None if value is None else value.astimezone(UTC).isoformat()

    return {
        "id": str(model.id),
        "content_hash": model.content_hash,
        "snapshot": snapshot,
        "source": source,
        "spec_version": model.spec_version,
        "model_version": model.model_version,
        "target": model.target,
        "window_days": model.window_days,
        "seed": model.seed,
        "status": model.status,
        "n_train": model.n_train,
        "events_train": model.events_train,
        "n_test": model.n_test,
        "events_test": model.events_test,
        "train_start": stamp(model.train_start),
        "train_end": stamp(model.train_end),
        "split_cutoff": stamp(model.split_cutoff),
        "diagnostics": model.diagnostics,
        "coefficients": model.coefficients,
        "code_version": model.code_version,
        "fitted_at": stamp(model.fitted_at),
    }


# --- verification -----------------------------------------------------------------------------

# Row column → the artifact field it must equal.
ROW_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("status", ("status",)),
    ("target", ("target",)),
    ("window_days", ("window_days",)),
    ("seed", ("seed",)),
    ("spec_version", ("spec_version",)),
    ("model_version", ("model_version",)),
    ("code_version", ("code_version",)),
    ("n_train", ("split", "train_rows")),
    ("events_train", ("split", "train_events")),
    ("n_test", ("split", "test_rows")),
    ("events_test", ("split", "test_events")),
)


def _dig(payload: dict[str, Any], path: Sequence[str]) -> Any:
    value: Any = payload
    for part in path:
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _check_row(
    model: OutcomeModel, source: str, snapshot: str, settings: Settings, result: VerifyResult
) -> bytes | None:
    def problem(field_name: str, detail: str) -> None:
        result.problems.append(
            Problem(model.id, model.target, model.window_days, field_name, detail)
        )

    try:
        path = artifact_path(snapshot_root(settings), snapshot, model.content_hash)
    except ArtifactError as exc:
        problem("content_hash", str(exc))
        return None
    if not path.is_file():
        problem("artifact", "the artifact file is missing")
        return None
    data = path.read_bytes()
    if content_hash(data) != model.content_hash:
        problem("content_hash", "the artifact does not hash to the row's content_hash")
        return data
    try:
        payload = read_artifact(path)
    except ArtifactError as exc:
        problem("artifact", str(exc))
        return data
    mismatched = False
    for column, artifact_field in ROW_FIELDS:
        if getattr(model, column) != _dig(payload, artifact_field):
            problem(column, f"the row differs from the artifact's {'.'.join(artifact_field)}")
            mismatched = True
    for name, expected in (("snapshot", snapshot), ("source", source)):
        if payload.get(name) != expected:
            problem(name, f"the artifact names another {name}")
            mismatched = True
    if not mismatched:
        result.verified += 1
    return data


def verify_models(
    session: Session,
    settings: Settings,
    *,
    snapshot_hash: str | None = None,
    refit: bool = False,
    spec: OutcomeModelSpec | None = None,
) -> VerifyResult:
    """Check every model's artifact (and, with ``refit``, reproduce it byte for byte)."""
    spec = spec or load_spec()
    stmt = (
        select(OutcomeModel, Source.name, MetricSnapshot.content_hash)
        .join(Source, Source.id == OutcomeModel.source_id)
        .join(MetricSnapshot, MetricSnapshot.id == OutcomeModel.snapshot_id)
        .order_by(
            MetricSnapshot.content_hash, Source.name, OutcomeModel.target, OutcomeModel.window_days
        )
    )
    if snapshot_hash is not None:
        stmt = stmt.where(MetricSnapshot.content_hash == validate_content_hash(snapshot_hash))
    rows = session.execute(stmt).all()
    result = VerifyResult(models=len(rows))
    stored: dict[uuid.UUID, bytes | None] = {}
    for model, source, snapshot in rows:
        stored[model.id] = _check_row(model, str(source), str(snapshot), settings, result)
    if not refit:
        return result
    groups: dict[tuple[str, str, int, int], list[tuple[OutcomeModel, str]]] = defaultdict(list)
    for model, source, snapshot in rows:
        if model.spec_version != spec.version:
            result.problems.append(
                Problem(
                    model.id,
                    model.target,
                    model.window_days,
                    "spec_version",
                    f"fitted under specification {model.spec_version}; the file is {spec.version}",
                )
            )
            continue
        groups[(str(snapshot), model.code_version, model.seed, model.spec_version)].append(
            (model, str(source))
        )
    for (snapshot, version, seed, _), members in sorted(groups.items()):
        keys = {(source, model.target, model.window_days) for model, source in members}
        with open_snapshot(settings, snapshot) as opened:
            fresh = {
                model.key: model
                for model in fit_models(
                    opened, spec, seed=seed, code_version=version, write=False, only=keys
                )
            }
        for model, source in members:
            result.refitted += 1
            again = fresh.get((source, model.target, model.window_days))
            if again is None:
                result.problems.append(
                    Problem(model.id, model.target, model.window_days, "refit", "no model refitted")
                )
                continue
            data = stored.get(model.id)
            if data is None or data == again.artifact_data:
                continue
            try:
                where = first_difference(_parsed(data), _parsed(again.artifact_data))
            except ValueError:
                where = None
            result.problems.append(
                Problem(
                    model.id,
                    model.target,
                    model.window_days,
                    where or "(bytes)",
                    "a fresh fit does not reproduce the artifact",
                )
            )
    return result


def _parsed(data: bytes) -> Any:
    """Artifact bytes parsed as JSON (``ValueError`` when they are not)."""
    return json.loads(data.decode("ascii"))
