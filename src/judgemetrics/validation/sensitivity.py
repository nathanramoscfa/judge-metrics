# src/judgemetrics/validation/sensitivity.py
"""Missing-data sensitivity: the complete-case refit against the published fit.

``missing_data_sensitivity(model, spec=)`` refits the model without every
index event that has a feature at its ``missing`` level
(``diagnostics.refit_complete_cases``: same columns, same solver settings),
rounds its coefficients as an artifact rounds them, scores every row of the
design with both fits — so each judge's cohort is the same under both and
only the model differs — fits the pooling shape under each, and compares the
pooled ratios across the judges whose published ratio is not withheld (at
least ``minimum_cohort`` members and ``minimum_expected`` expected events
under the published fit): their Spearman correlation and the largest
absolute change. Index events excluded under a ``missing: exclude`` rule
never enter a design, so they are reported as excluded, not refitted. No
judge is named; the figures are aggregates over the judges.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from judgemetrics.metrics.adjustment.artifacts import round_significant
from judgemetrics.metrics.adjustment.diagnostics import refit_complete_cases
from judgemetrics.metrics.adjustment.expected import ModelParameters, expectations
from judgemetrics.metrics.adjustment.logistic import FloatArray
from judgemetrics.metrics.adjustment.pooling import fit_shape, pooled_ratio
from judgemetrics.metrics.adjustment.spec import OutcomeModelSpec, load_spec
from judgemetrics.metrics.suppression import adjusted_reason
from judgemetrics.validation.inputs import ModelInput
from judgemetrics.validation.statistics import spearman

FITTED = "compared"
NO_FIT = "model_unavailable"
NOT_CONVERGED = "not_converged"
TOO_FEW_JUDGES = "too_few_judges"
MINIMUM_JUDGES = 3


@dataclass(frozen=True, slots=True)
class Sensitivity:
    """One model's complete-case comparison (aggregates only)."""

    source: str
    target: str
    window_days: int | None
    status: str
    rows: int
    excluded_missing: int  # eligible events dropped under an exclude rule (never in the design)
    at_missing_level: int  # design rows the complete-case refit drops
    judges: int
    spearman: float | None
    max_abs_change: float | None


def kept_judges(
    size: np.ndarray, expected: FloatArray, *, minimum_cohort: int, minimum_expected: float
) -> np.ndarray:
    """The judges whose pooled ratio would be published (the suppression rule of the ratios)."""
    return np.array(
        [
            adjusted_reason(
                int(size[index]),
                float(expected[index]),
                threshold=minimum_cohort,
                minimum_expected=minimum_expected,
            )
            is None
            for index in range(size.size)
        ],
        dtype=np.bool_,
    )


def pooled_ratios(
    model: ModelInput, parameters: ModelParameters, spec: OutcomeModelSpec
) -> tuple[np.ndarray, FloatArray, FloatArray]:
    """Per judge (sorted ids): the members in the ratio, the expected count, the pooled ratio."""
    scored = expectations(model.design, parameters)
    if scored.expected is None:
        msg = f"model {model.label} of {model.source} has no fitted coefficients"
        raise ValueError(msg)
    shape = fit_shape(
        scored.observed,
        scored.expected,
        bounds=spec.pooling.shape_bounds,
        grid=spec.pooling.shape_grid,
    )
    ratios = pooled_ratio(scored.observed.astype(np.float64), scored.expected, shape.shape)
    return scored.size, scored.expected, ratios


def missing_data_sensitivity(
    model: ModelInput, spec: OutcomeModelSpec | None = None
) -> Sensitivity:
    """The complete-case comparison of one model (see the module docstring)."""
    spec = spec or load_spec()
    design = model.design
    base = Sensitivity(
        source=model.source,
        target=model.target.name,
        window_days=model.window_days,
        status=NO_FIT,
        rows=design.rows,
        excluded_missing=design.excluded_missing,
        at_missing_level=int(design.missing.sum()),
        judges=0,
        spearman=None,
        max_abs_change=None,
    )
    parameters = model.parameters
    if not parameters.fitted or parameters.coefficients is None:
        return base
    refit = refit_complete_cases(design, spec.model)
    if not refit.converged:
        return replace(base, status=NOT_CONVERGED)
    rounded = np.array([round_significant(float(value)) for value in refit.coefficients])
    complete = replace(parameters, coefficients=rounded, replicates=())
    size, expected, published = pooled_ratios(model, parameters, spec)
    _, _, alternative = pooled_ratios(model, complete, spec)
    kept = kept_judges(
        size,
        expected,
        minimum_cohort=spec.thresholds.minimum_cohort,
        minimum_expected=spec.thresholds.minimum_expected,
    )
    judges = int(kept.sum())
    if judges < MINIMUM_JUDGES:
        return replace(base, status=TOO_FEW_JUDGES, judges=judges)
    return replace(
        base,
        status=FITTED,
        judges=judges,
        spearman=spearman(published[kept], alternative[kept]),
        max_abs_change=float(np.max(np.abs(published[kept] - alternative[kept]))),
    )
