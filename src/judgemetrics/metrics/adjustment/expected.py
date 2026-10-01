# src/judgemetrics/metrics/adjustment/expected.py
"""Expected counts: every judge's members scored by one model fitted over the whole source.

An ``observed_expected`` figure reads a fitted model through
``ModelParameters``: its identity (target, window, status, seed, the
specification and model versions, the artifact's content hash), its design
columns, the published coefficients, and every bootstrap replicate's
coefficients. ``ModelParameters.from_artifact`` reads them from a stored
artifact (``metrics compute`` and ``metrics verify`` — so both compute from
the very bytes the catalogue records); ``ModelParameters.from_fitted`` takes
an in-memory ``FittedModel`` (the recovery test) and applies the artifact's
rounding (twelve significant digits) to every coefficient, so the two give
identical floats for the same fit.

``expectations(design, parameters)`` scores the design — every eligible
index event of the source, the rows ``features.design_rows`` builds once for
all judges, so every judge is scored by the same model — and sums per judge
(the judge the published gate attributed the row to): ``n`` the members in
the ratio, ``O`` their outcomes, and ``E`` the sum of their predicted
probabilities from the published coefficients (``None`` without a fitted
model). The design must carry exactly the model's columns: a design built
under another specification is refused. Per-judge sums are ``np.bincount``
over the rows in design order — an order the source's keys fix — so they do
not depend on a canonical id. The predicted probabilities and the member
ids exist in memory only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from judgemetrics.metrics.adjustment.artifacts import round_significant
from judgemetrics.metrics.adjustment.features import DesignFrame
from judgemetrics.metrics.adjustment.fit import FITTED, STATUSES, FittedModel
from judgemetrics.metrics.adjustment.logistic import FloatArray, predict

IntArray = npt.NDArray[np.int64]


class ExpectationError(ValueError):
    """A model cannot score a design (another specification's columns, a malformed artifact)."""


def _rounded(values: Sequence[float] | FloatArray) -> FloatArray:
    """Coefficients as an artifact stores them: twelve significant digits."""
    return np.array([round_significant(float(value)) for value in values], dtype=np.float64)


@dataclass(frozen=True, slots=True)
class ModelParameters:
    """What an adjusted figure reads from one fitted model (an artifact's fields, or a fit's)."""

    target: str
    window_days: int | None
    status: str
    seed: int
    spec_version: int
    model_version: str
    columns: tuple[str, ...]
    coefficients: FloatArray | None
    replicates: tuple[FloatArray | None, ...]
    content_hash: str | None = None

    @property
    def fitted(self) -> bool:
        return self.status == FITTED and self.coefficients is not None

    @classmethod
    def from_fitted(cls, model: FittedModel) -> ModelParameters:
        """An in-memory fit, rounded as its artifact rounds it (``content_hash`` when rendered)."""
        coefficients = model.coefficients
        return cls(
            target=model.target,
            window_days=model.window_days,
            status=model.status,
            seed=model.seed,
            spec_version=model.spec_version,
            model_version=model.model_version,
            columns=model.column_names,
            coefficients=None if coefficients is None else _rounded(coefficients),
            replicates=(
                ()
                if coefficients is None
                else tuple(
                    None if draw is None else _rounded(draw)
                    for draw in model.replicate_coefficients
                )
            ),
            content_hash=model.content_hash if model.artifact_data else None,
        )

    @classmethod
    def from_artifact(cls, payload: Mapping[str, Any], content_hash: str) -> ModelParameters:
        """A stored artifact's fields (``artifacts.read_artifact``), checked for shape."""
        try:
            status = str(payload["status"])
            columns = tuple(str(column["name"]) for column in payload["design"]["columns"])
            raw = payload["coefficients"]
            replicates = payload["replicates"]
            window = payload["window_days"]
            seed = int(payload["seed"])
            spec_version = int(payload["spec_version"])
            model_version = str(payload["model_version"])
            target = str(payload["target"])
        except (KeyError, TypeError, ValueError) as exc:
            msg = f"artifact {content_hash} lacks a field an adjusted figure reads ({exc})"
            raise ExpectationError(msg) from exc
        if status not in STATUSES:
            msg = f"artifact {content_hash} has an unknown status {status!r}"
            raise ExpectationError(msg)
        coefficients = None if raw is None else _array(raw, len(columns), content_hash)
        draws: tuple[FloatArray | None, ...] = ()
        if coefficients is not None:
            if not isinstance(replicates, Mapping) or not isinstance(
                replicates.get("coefficients"), list
            ):
                msg = f"artifact {content_hash} has coefficients but no replicates"
                raise ExpectationError(msg)
            draws = tuple(
                None if draw is None else _array(draw, len(columns), content_hash)
                for draw in replicates["coefficients"]
            )
        return cls(
            target=target,
            window_days=None if window is None else int(window),
            status=status,
            seed=seed,
            spec_version=spec_version,
            model_version=model_version,
            columns=columns,
            coefficients=coefficients,
            replicates=draws,
            content_hash=content_hash,
        )


def _array(values: Any, width: int, content_hash: str) -> FloatArray:
    if not isinstance(values, list) or len(values) != width:
        msg = f"artifact {content_hash}: a coefficient vector must have {width} values"
        raise ExpectationError(msg)
    if any(isinstance(value, bool) or not isinstance(value, int | float) for value in values):
        msg = f"artifact {content_hash}: a coefficient must be a number"
        raise ExpectationError(msg)
    return np.array([float(value) for value in values], dtype=np.float64)


@dataclass(frozen=True, slots=True)
class Expectations:
    """One design scored by one model: per row and per judge (in memory only)."""

    judges: tuple[str, ...]  # sorted judge ids
    rows: IntArray  # per design row: the position of its judge in ``judges``
    outcome: FloatArray  # per design row
    predicted: FloatArray | None  # per design row, None without a fitted model
    size: IntArray  # per judge: n, the members in the ratio
    observed: IntArray  # per judge: O
    expected: FloatArray | None  # per judge: E

    def position(self, judge: str) -> int | None:
        try:
            return self.judges.index(judge)
        except ValueError:
            return None


def expectations(design: DesignFrame, parameters: ModelParameters) -> Expectations:
    """Score ``design`` with ``parameters`` and sum per judge (see the module docstring)."""
    names = tuple(column.name for column in design.columns)
    if parameters.fitted and names != parameters.columns:
        msg = (
            f"the {design.target}@{design.window_days} design's columns differ from the "
            f"model's: the model was fitted under another specification or snapshot"
        )
        raise ExpectationError(msg)
    judges = tuple(sorted(set(design.judge_ids)))
    position = {judge: index for index, judge in enumerate(judges)}
    rows = np.fromiter(
        (position[judge] for judge in design.judge_ids), dtype=np.int64, count=design.rows
    )
    count = len(judges)
    size = np.bincount(rows, minlength=count).astype(np.int64)
    observed = np.rint(np.bincount(rows, weights=design.outcome, minlength=count)).astype(np.int64)
    predicted: FloatArray | None = None
    expected: FloatArray | None = None
    if parameters.fitted and parameters.coefficients is not None:
        predicted = predict(parameters.coefficients, design.matrix)
        expected = np.bincount(rows, weights=predicted, minlength=count).astype(np.float64)
    return Expectations(
        judges=judges,
        rows=rows,
        outcome=design.outcome,
        predicted=predicted,
        size=size,
        observed=observed,
        expected=expected,
    )
