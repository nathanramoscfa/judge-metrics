# src/judgemetrics/metrics/adjustment/fit.py
"""Fitting the expected-outcome models: per source, target, and window.

``fit_frame(frame, spec, *, seed, source)`` fits, in memory, every model
the specification names over one source's frame (Step 3's recovery test
and Step 4's control test call it on ``frame_from_world`` frames). Per
target and window (``design_rows``):

- a design whose limiting class — the fewer of outcomes and non-outcomes —
  is below ``minimum_events_per_column`` times the design width is
  recorded with status ``insufficient_events`` and is not fitted;
- otherwise the **published fit** over every eligible index event
  (``fit_logistic`` with the specification's penalty and solver limits);
  a solver that does not converge is recorded as ``not_converged`` with no
  coefficients;
- the **temporal-split fit**: the same columns over the index events before
  the cutoff (columns without a training row dropped, a data level unseen
  in training re-scored by ``remap_unseen``), its test-set diagnostics
  (``diagnostics.evaluate``), under the same events-per-column gate;
- one **refit per bootstrap replicate** (``resample.replicates`` over the
  person clusters, the model's own stream, started from the published
  coefficients), whose coefficients the ``FittedModel`` carries for Step
  3's interval, and the stability summary over them.

An outcome the source cannot document yields no model. ``fit_models(snapshot,
spec, *, seed)`` builds each source's frame from an opened snapshot, calls
``fit_frame``, and writes every model's canonical artifact once under the
snapshot (``artifacts.write_artifact``); ``write=False`` renders without
writing (``models verify --refit``). Log lines name the source's register
name, the target, the window, the status, and counts only.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from judgemetrics import __version__
from judgemetrics.logging import get_logger
from judgemetrics.metrics.adjustment.artifacts import (
    ARTIFACT_VERSION,
    canonical,
    content_hash,
    render,
    write_artifact,
)
from judgemetrics.metrics.adjustment.diagnostics import (
    Evaluation,
    Stability,
    evaluate,
    split_cutoff,
    stability,
)
from judgemetrics.metrics.adjustment.features import (
    DesignColumn,
    DesignFrame,
    design_rows,
    encode,
    instant,
    remap_unseen,
)
from judgemetrics.metrics.adjustment.logistic import (
    FloatArray,
    LogisticFit,
    fit_logistic,
    predict,
)
from judgemetrics.metrics.adjustment.resample import replicate_stream, replicates
from judgemetrics.metrics.adjustment.spec import OutcomeModelSpec
from judgemetrics.metrics.frame import Frame
from judgemetrics.metrics.snapshot import Snapshot, SnapshotError
from judgemetrics.metrics.windows import NotObservable

log = get_logger(__name__)

FITTED = "fitted"
INSUFFICIENT_EVENTS = "insufficient_events"
NOT_CONVERGED = "not_converged"
STATUSES: tuple[str, ...] = (FITTED, INSUFFICIENT_EVENTS, NOT_CONVERGED)
NO_TEST_ROWS = "no_test_rows"

ModelKey = tuple[str, str, int | None]  # (source name, target, window)


class FitError(RuntimeError):
    """A snapshot's models cannot be fitted as specified (a snapshot or spec defect)."""


@dataclass(frozen=True, slots=True)
class SplitSummary:
    """The temporal split: the cutoff (UTC microseconds) and the rows and events on each side."""

    cutoff: int | None
    train_rows: int
    train_events: int
    test_rows: int
    test_events: int


@dataclass(frozen=True, slots=True)
class SplitResult:
    """The temporal-split fit and its test-set diagnostics (``status`` explains an absence)."""

    status: str
    columns: tuple[DesignColumn, ...] = ()
    fit: LogisticFit | None = None
    evaluation: Evaluation | None = None


@dataclass(frozen=True, slots=True)
class FittedModel:
    """One source's model of one target and window, with everything its artifact records.

    ``design`` (the rows, clusters, and member ids) and ``source_id`` live in
    memory only; the artifact carries the source's register name.
    ``artifact_data`` is set by ``fit_models`` (the canonical bytes).
    """

    source: str
    target: str
    window_days: int | None
    seed: int
    spec_version: int
    model_version: str
    status: str
    design: DesignFrame
    split: SplitSummary
    published: LogisticFit | None
    temporal: SplitResult
    replicate_coefficients: tuple[FloatArray | None, ...]
    replicates_requested: int
    stability: tuple[Stability, ...]
    source_id: str = ""
    artifact_data: bytes = field(default=b"", repr=False)

    @property
    def key(self) -> ModelKey:
        return (self.source, self.target, self.window_days)

    @property
    def coefficients(self) -> FloatArray | None:
        if self.status != FITTED or self.published is None:
            return None
        return self.published.coefficients

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.design.columns)

    @property
    def content_hash(self) -> str:
        if not self.artifact_data:
            msg = "the model has no rendered artifact"
            raise FitError(msg)
        return content_hash(self.artifact_data)

    @property
    def train_start(self) -> int | None:
        return int(self.design.index_at.min()) if self.design.rows else None

    @property
    def train_end(self) -> int | None:
        return int(self.design.index_at.max()) if self.design.rows else None

    def predict(self, design: FloatArray | None = None) -> FloatArray:
        """The published model's probabilities for ``design`` (default: its own rows)."""
        coefficients = self.coefficients
        if coefficients is None:
            msg = f"model {self.target}@{self.window_days} has status {self.status}: no fit"
            raise FitError(msg)
        return predict(coefficients, self.design.matrix if design is None else design)

    # --- the artifact and the database summaries -------------------------------------------

    def _design_payload(self) -> dict[str, Any]:
        dropped = {item.name: item.reason for item in self.design.dropped}
        features = []
        for encoding in self.design.encodings:
            features.append(
                {
                    "name": encoding.feature,
                    "levels": list(encoding.levels),
                    "reference": encoding.reference,
                    "unseen": encoding.unseen,
                    "dropped": dropped.get(encoding.feature),
                    "unobserved": [
                        name
                        for name in self.design.unobserved
                        if name.partition("=")[0] == encoding.feature
                    ],
                }
            )
        encoded = {encoding.feature for encoding in self.design.encodings}
        features.extend(
            {
                "name": name,
                "levels": [],
                "reference": None,
                "unseen": None,
                "dropped": reason,
                "unobserved": [],
            }
            for name, reason in dropped.items()
            if name not in encoded
        )
        return {
            "columns": [
                {"name": column.name, "feature": column.feature, "level": column.level}
                for column in self.design.columns
            ],
            "features": sorted(features, key=lambda item: str(item["name"])),
        }

    def _solver_payload(self, fit: LogisticFit | None) -> dict[str, Any] | None:
        if fit is None:
            return None
        return {
            "converged": fit.converged,
            "iterations": fit.iterations,
            "gradient_norm": fit.gradient_norm,
            "objective": fit.objective,
            "trace": [
                {
                    "iteration": record.iteration,
                    "objective": record.objective,
                    "gradient_norm": record.gradient_norm,
                    "step": record.step,
                }
                for record in fit.trace
            ],
        }

    def diagnostics_payload(self) -> dict[str, Any]:
        """The temporal-split diagnostics: summary, bins, and the split fit's columns."""
        result = self.temporal
        payload: dict[str, Any] = {"status": result.status}
        if result.evaluation is None:
            return payload
        evaluation = result.evaluation
        payload.update(
            base_rate_train=evaluation.base_rate_train,
            brier=evaluation.brier,
            brier_skill=evaluation.brier_skill,
            auc=evaluation.auc,
            calibration_in_the_large=evaluation.calibration_in_the_large,
            calibration_slope=evaluation.calibration_slope,
            bins=[
                {
                    "bin": item.bin,
                    "count": item.count,
                    "mean_predicted": item.mean_predicted,
                    "observed_rate": item.observed_rate,
                }
                for item in evaluation.bins
            ],
        )
        return payload

    def payload(self, *, snapshot: str, code_version: str) -> dict[str, Any]:
        """Everything the artifact records (see ``artifacts`` for the canonical form)."""
        design = self.design
        split = self.split
        coefficients = self.coefficients
        temporal = self.temporal
        return {
            "artifact_version": ARTIFACT_VERSION,
            "spec_version": self.spec_version,
            "model_version": self.model_version,
            "code_version": code_version,
            "snapshot": snapshot,
            "source": self.source,
            "target": self.target,
            "window_days": self.window_days,
            "seed": self.seed,
            "status": self.status,
            "design": self._design_payload(),
            "training": {
                "rows": design.rows,
                "events": design.events,
                "clusters": design.persons,
                "eligible": design.eligible,
                "excluded_missing": design.excluded_missing,
                "at_missing_level": int(design.missing.sum()),
                "start": None if self.train_start is None else instant(self.train_start),
                "end": None if self.train_end is None else instant(self.train_end),
            },
            "split": {
                "cutoff": None if split.cutoff is None else instant(split.cutoff),
                "train_rows": split.train_rows,
                "train_events": split.train_events,
                "test_rows": split.test_rows,
                "test_events": split.test_events,
            },
            "coefficients": None if coefficients is None else coefficients,
            "solver": self._solver_payload(self.published),
            "diagnostics": {
                **self.diagnostics_payload(),
                "columns": [column.name for column in temporal.columns],
                "coefficients": (
                    None
                    if temporal.fit is None or not temporal.fit.converged
                    else temporal.fit.coefficients
                ),
                "solver": self._solver_payload(temporal.fit),
            },
            "stability": (
                None
                if coefficients is None
                else [
                    {
                        "column": item.column,
                        "mean": item.mean,
                        "sd": item.sd,
                        "sign_agreement": item.sign_agreement,
                    }
                    for item in self.stability
                ]
            ),
            "replicates": (
                None
                if coefficients is None
                else {
                    "requested": self.replicates_requested,
                    "converged": sum(1 for r in self.replicate_coefficients if r is not None),
                    "coefficients": list(self.replicate_coefficients),
                }
            ),
        }

    def render(self, *, snapshot: str, code_version: str) -> bytes:
        return render(self.payload(snapshot=snapshot, code_version=code_version))

    def coefficient_rows(self) -> list[dict[str, Any]] | None:
        """Per design column, for ``outcome_model.coefficients``: level, estimate, sd, sign.

        A data level's ``level`` and ``reference`` are the frame values they
        stand for (a court id, a year), so a model card names the court; the
        artifact keeps the rank label (``column``).
        """
        coefficients = self.coefficients
        if coefficients is None:
            return None
        by_column = {item.column: item for item in self.stability}
        rows: list[dict[str, Any]] = []
        for index, column in enumerate(self.design.columns):
            level: str | None = column.level
            reference: str | None = None
            if column.feature is not None:
                encoding = self.design.encoding(column.feature)
                level = encoding.keys.get(column.level or "", column.level)
                reference = encoding.keys.get(encoding.reference, encoding.reference)
            summary = by_column.get(column.name)
            rows.append(
                {
                    "column": column.name,
                    "feature": column.feature,
                    "level": level,
                    "reference": reference,
                    "estimate": coefficients[index],
                    "sd": None if summary is None else summary.sd,
                    "sign_agreement": None if summary is None else summary.sign_agreement,
                }
            )
        result: list[dict[str, Any]] = canonical(rows)
        return result

    def diagnostics_row(self) -> dict[str, Any]:
        """``outcome_model.diagnostics``: the summary and the ten calibration bins."""
        result: dict[str, Any] = canonical(self.diagnostics_payload())
        return result


# --- fitting ----------------------------------------------------------------------------


def _limiting(events: int, rows: int) -> int:
    return min(events, rows - events)


def _split_summary(design: DesignFrame, quantile: float) -> tuple[SplitSummary, np.ndarray]:
    cutoff = split_cutoff(design.index_at, quantile)
    if cutoff is None:
        return SplitSummary(None, 0, 0, 0, 0), np.zeros(0, dtype=np.bool_)
    train = design.index_at < cutoff
    outcome = design.outcome
    return (
        SplitSummary(
            cutoff=cutoff,
            train_rows=int(train.sum()),
            train_events=int(outcome[train].sum()),
            test_rows=int((~train).sum()),
            test_events=int(outcome[~train].sum()),
        ),
        train,
    )


def _temporal(design: DesignFrame, spec: OutcomeModelSpec, train: np.ndarray) -> SplitResult:
    if not train.any() or train.all():
        return SplitResult(status=NO_TEST_ROWS if train.all() else INSUFFICIENT_EVENTS)
    matrix = design.matrix[train]
    keep = [0, *(index for index in range(1, design.width) if matrix[:, index].any())]
    columns = tuple(design.columns[index] for index in keep)
    outcome = design.outcome[train]
    events = int(outcome.sum())
    if _limiting(events, outcome.size) < spec.thresholds.minimum_events_per_column * len(keep):
        return SplitResult(status=INSUFFICIENT_EVENTS, columns=columns)
    settings = spec.model
    fit = fit_logistic(
        matrix[:, keep],
        outcome,
        lam=settings.lam,
        max_iterations=settings.max_iterations,
        tolerance=settings.tolerance,
        step_halvings=settings.step_halvings,
    )
    if not fit.converged:
        return SplitResult(status=NOT_CONVERGED, columns=columns, fit=fit)
    test_levels = remap_unseen(
        design.levels.filter(~train), design.levels.filter(train), design.encodings
    )
    predicted = predict(fit, encode(test_levels, columns))
    evaluation = evaluate(predicted, design.outcome[~train], events / outcome.size, settings)
    return SplitResult(status=FITTED, columns=columns, fit=fit, evaluation=evaluation)


def fit_design(
    design: DesignFrame, spec: OutcomeModelSpec, *, seed: int, source: str
) -> FittedModel:
    """The published fit, the temporal split, and the bootstrap of one design."""
    settings = spec.model
    split, train = _split_summary(design, spec.temporal_split.test_quantile)
    base: dict[str, Any] = {
        "source": source,
        "target": design.target,
        "window_days": design.window_days,
        "seed": seed,
        "spec_version": spec.version,
        "model_version": spec.model_version,
        "design": design,
        "split": split,
        "replicates_requested": spec.bootstrap.replicates,
    }
    gate = spec.thresholds.minimum_events_per_column * design.width
    if _limiting(design.events, design.rows) < gate:
        return FittedModel(
            status=INSUFFICIENT_EVENTS,
            published=None,
            temporal=SplitResult(status=INSUFFICIENT_EVENTS),
            replicate_coefficients=(),
            stability=(),
            **base,
        )
    published = fit_logistic(
        design.matrix,
        design.outcome,
        lam=settings.lam,
        max_iterations=settings.max_iterations,
        tolerance=settings.tolerance,
        step_halvings=settings.step_halvings,
    )
    if not published.converged:
        return FittedModel(
            status=NOT_CONVERGED,
            published=published,
            temporal=SplitResult(status=NOT_CONVERGED),
            replicate_coefficients=(),
            stability=(),
            **base,
        )
    temporal = _temporal(design, spec, train)
    draws: list[FloatArray | None] = []
    stream = replicate_stream(design.target, design.window_days)
    for weights in replicates(
        design.clusters, seed=seed, stream=stream, count=spec.bootstrap.replicates
    ):
        refit = fit_logistic(
            design.matrix,
            design.outcome,
            lam=settings.lam,
            max_iterations=settings.max_iterations,
            tolerance=settings.tolerance,
            step_halvings=settings.step_halvings,
            weights=weights,
            start=published.coefficients,
        )
        draws.append(refit.coefficients if refit.converged else None)
    names = tuple(column.name for column in design.columns)
    return FittedModel(
        status=FITTED,
        published=published,
        temporal=temporal,
        replicate_coefficients=tuple(draws),
        stability=stability(names, published.coefficients, draws),
        **base,
    )


def _wanted(only: Collection[ModelKey] | None, key: ModelKey) -> bool:
    return only is None or key in only


def fit_frame(
    frame: Frame,
    spec: OutcomeModelSpec,
    *,
    seed: int,
    source: str,
    only: Collection[ModelKey] | None = None,
) -> list[FittedModel]:
    """Every model of the specification over one source's frame, in memory.

    ``only`` restricts the fit to the given ``(source, target, window)``
    keys (``models fit`` fits the missing ones). A target whose outcome the
    source cannot document is skipped and logged.
    """
    models: list[FittedModel] = []
    for target in spec.targets:
        for window in target.windows:
            if not _wanted(only, (source, target.name, window)):
                continue
            design = design_rows(frame, spec, target, window)
            if isinstance(design, NotObservable):
                log.info(
                    "models.fit.not_observable",
                    source=source,
                    target=target.name,
                    window=window,
                    outcome=design.outcome,
                )
                continue
            model = fit_design(design, spec, seed=seed, source=source)
            log.info(
                "models.fit.model",
                source=source,
                target=target.name,
                window=window,
                status=model.status,
                rows=design.rows,
                events=design.events,
                width=design.width,
            )
            models.append(model)
    return models


def fit_models(
    snapshot: Snapshot,
    spec: OutcomeModelSpec,
    *,
    seed: int,
    code_version: str = __version__,
    write: bool = True,
    only: Collection[ModelKey] | None = None,
) -> list[FittedModel]:
    """Fit every model of every source of the snapshot and render (and write) the artifacts.

    A source without case data or without a declared coverage window has
    no model (nothing can be right-censored for it). Artifacts land under
    ``<snapshot_dir>/<snapshot hash>/models/<content hash>.json``.
    """
    root = artifact_root(snapshot)
    fitted: list[FittedModel] = []
    for source in snapshot.sources_with_cases():
        if not source.has_coverage:
            log.warning(
                "models.fit.source_skipped", source=source.name, because="no coverage window"
            )
            continue
        if only is not None and not any(key[0] == source.name for key in only):
            continue
        try:
            frame = snapshot.frame(source.id)
        except SnapshotError as exc:
            msg = f"cannot build the frame of source {source.name}: {exc}"
            raise FitError(msg) from exc
        for model in fit_frame(frame, spec, seed=seed, source=source.name, only=only):
            data = model.render(snapshot=snapshot.content_hash, code_version=code_version)
            if write:
                write_artifact(root, snapshot.content_hash, data)
            fitted.append(replace(model, source_id=source.id, artifact_data=data))
    return fitted


def artifact_root(snapshot: Snapshot) -> Path:
    """The snapshot directory's parent: the configured ``snapshot_dir``."""
    return snapshot.ref.directory.parent
