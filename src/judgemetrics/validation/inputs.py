# src/judgemetrics/validation/inputs.py
"""The validation's inputs: a snapshot's fitted models with their designs, in memory only.

``load_inputs(session, settings, snapshot, snapshot_id, spec=)`` reads the
``outcome_model`` rows of the snapshot under the loaded specification's
version and seed (the models ``metrics compute`` publishes from), reads each
model's parameters back from its artifact (``catalog.read_parameters``: the
path rebuilt from the configured snapshot directory, the bytes checked
against the content hash), and rebuilds its design from the snapshot's frame
of the source (``features.design_rows``) — the very rows the published
ratios were computed over. Sources come in register-name order and models
in the specification's target and window order, so every list the report
renders has an order the data alone fixes. The designs, their member ids,
and the frame never leave memory.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import OutcomeModel
from judgemetrics.metrics.adjustment.catalog import read_parameters
from judgemetrics.metrics.adjustment.expected import ModelParameters
from judgemetrics.metrics.adjustment.features import DesignFrame, design_rows
from judgemetrics.metrics.adjustment.spec import OutcomeModelSpec, TargetSpec, load_spec
from judgemetrics.metrics.frame import Frame
from judgemetrics.metrics.snapshot import Snapshot, SourceRow
from judgemetrics.metrics.windows import NotObservable


class InputError(RuntimeError):
    """The snapshot has no model to validate, or a model cannot be read back."""


@dataclass(frozen=True, slots=True)
class ModelInput:
    """One fitted model of one source, with the design it scores (in memory only)."""

    source: str  # the source's register name
    target: TargetSpec
    window_days: int | None
    status: str
    n_train: int
    events_train: int
    n_test: int
    events_test: int
    diagnostics: Mapping[str, Any]  # outcome_model.diagnostics
    coefficients: tuple[Mapping[str, Any], ...]  # outcome_model.coefficients (empty: no fit)
    parameters: ModelParameters
    design: DesignFrame

    @property
    def label(self) -> str:
        window = "" if self.window_days is None else f", {self.window_days} days"
        return f"{self.target.name}{window}"


@dataclass(frozen=True, slots=True)
class SourceInput:
    """One source of the snapshot with its frame and its models."""

    source: SourceRow
    frame: Frame
    models: tuple[ModelInput, ...]


def _target_order(spec: OutcomeModelSpec) -> dict[str, int]:
    return {target.name: index for index, target in enumerate(spec.targets)}


def load_inputs(
    session: Session,
    settings: Settings,
    snapshot: Snapshot,
    snapshot_id: uuid.UUID,
    *,
    spec: OutcomeModelSpec | None = None,
) -> list[SourceInput]:
    """Every source of the snapshot with fitted-model rows, its frame, and its models."""
    spec = spec or load_spec()
    rows = session.scalars(
        select(OutcomeModel).where(
            OutcomeModel.snapshot_id == snapshot_id,
            OutcomeModel.spec_version == spec.version,
            OutcomeModel.seed == spec.seed,
        )
    ).all()
    by_source: dict[str, list[OutcomeModel]] = {}
    for row in rows:
        by_source.setdefault(str(row.source_id), []).append(row)
    if not by_source:
        msg = (
            f"snapshot {snapshot.content_hash} has no outcome model of specification "
            f"{spec.version}: run `judgemetrics metrics compute` first"
        )
        raise InputError(msg)
    order = _target_order(spec)
    sources = sorted(
        (source for source in snapshot.sources_with_cases() if source.id in by_source),
        key=lambda source: source.name,
    )
    if not sources:
        msg = f"snapshot {snapshot.content_hash} holds no case data for its models' sources"
        raise InputError(msg)
    result: list[SourceInput] = []
    for source in sources:
        frame = snapshot.frame(source.id)
        models: list[ModelInput] = []
        ordered = sorted(
            by_source[source.id],
            key=lambda row: (
                order.get(row.target, len(order)),
                -1 if row.window_days is None else row.window_days,
            ),
        )
        for row in ordered:
            target = spec.target(row.target)
            design = design_rows(frame, spec, target, row.window_days)
            if isinstance(design, NotObservable):
                msg = f"model {row.target}@{row.window_days} of {source.name}: {design.reason}"
                raise InputError(msg)
            parameters = read_parameters(settings, snapshot.content_hash, row.content_hash)
            models.append(
                ModelInput(
                    source=source.name,
                    target=target,
                    window_days=row.window_days,
                    status=row.status,
                    n_train=row.n_train,
                    events_train=row.events_train,
                    n_test=row.n_test,
                    events_test=row.events_test,
                    diagnostics=dict(row.diagnostics or {}),
                    coefficients=_coefficients(row.coefficients),
                    parameters=parameters,
                    design=design,
                )
            )
        result.append(SourceInput(source=source, frame=frame, models=tuple(models)))
    return result


def _coefficients(rows: Sequence[Mapping[str, Any]] | None) -> tuple[Mapping[str, Any], ...]:
    return tuple(dict(row) for row in rows or ())
