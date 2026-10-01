# src/judgemetrics/validation/stability.py
"""Feature stability and the bootstrap stability of the judge-level estimates.

``coefficient_stability(model)`` reads the published coefficients' summary
over the bootstrap replicates from the model's catalogue row: per design
column (``<feature>=<level>``, a data level by its rank label, never the
canonical id it stands for) the estimate, the replicates' standard
deviation, and the share of replicates agreeing with the estimate in sign.

``bootstrap_stability(model, spec=)`` replays the published estimator on the
model's design — the expected counts, the pooling shape, and the percentile
interval over the stored replicate coefficients (``bootstrap.interval``, the
very computation the published bounds come from) — and summarizes, over the
judges whose ratio is published (at least ``minimum_cohort`` members and
``minimum_expected`` expected events), three distributions: the interval
widths (bounds rounded to six decimals, as published), the share of
intervals that exclude 1, and the widths of each judge's 95% rank interval
(per replicate the judges' pooled ratios ranked with ties averaged, then the
2.5% and 97.5% quantiles of each judge's ranks). Medians and quartiles only:
no judge is named and no judge-level figure is returned.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from judgemetrics.metrics.adjustment.bootstrap import interval
from judgemetrics.metrics.adjustment.diagnostics import average_ranks
from judgemetrics.metrics.adjustment.expected import expectations
from judgemetrics.metrics.adjustment.spec import OutcomeModelSpec, load_spec
from judgemetrics.metrics.intervals import round6
from judgemetrics.validation.inputs import ModelInput
from judgemetrics.validation.sensitivity import MINIMUM_JUDGES, kept_judges
from judgemetrics.validation.statistics import quantile

SUMMARIZED = "summarized"
NO_FIT = "model_unavailable"
TOO_FEW_JUDGES = "too_few_judges"


@dataclass(frozen=True, slots=True)
class CoefficientStability:
    """One design column over the bootstrap replicates."""

    column: str
    estimate: float | None
    sd: float | None
    sign_agreement: float | None


@dataclass(frozen=True, slots=True)
class Spread:
    """A distribution as its quartiles."""

    p25: float
    median: float
    p75: float


@dataclass(frozen=True, slots=True)
class BootstrapStability:
    """One model's judge-level bootstrap stability, as distributions over judges."""

    source: str
    target: str
    window_days: int | None
    status: str
    replicates: int  # the converged replicates the intervals are taken over
    requested: int
    judges: int
    interval_width: Spread | None
    share_excluding_one: float | None
    rank_width: Spread | None


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def coefficient_stability(model: ModelInput) -> tuple[CoefficientStability, ...]:
    """The catalogue row's coefficient summary, by rank label (never a canonical id)."""

    def one(row: Mapping[str, Any]) -> CoefficientStability:
        return CoefficientStability(
            column=str(row["column"]),
            estimate=_float(row.get("estimate")),
            sd=_float(row.get("sd")),
            sign_agreement=_float(row.get("sign_agreement")),
        )

    return tuple(one(row) for row in model.coefficients)


def _spread(values: np.ndarray) -> Spread | None:
    p25, median, p75 = (quantile(values, q) for q in (0.25, 0.5, 0.75))
    if p25 is None or median is None or p75 is None:
        return None
    return Spread(p25=p25, median=median, p75=p75)


def bootstrap_stability(
    model: ModelInput, spec: OutcomeModelSpec | None = None
) -> BootstrapStability:
    """The bootstrap stability summary of one model (see the module docstring)."""
    spec = spec or load_spec()
    parameters = model.parameters
    base = BootstrapStability(
        source=model.source,
        target=model.target.name,
        window_days=model.window_days,
        status=NO_FIT,
        replicates=0,
        requested=len(parameters.replicates),
        judges=0,
        interval_width=None,
        share_excluding_one=None,
        rank_width=None,
    )
    design = model.design
    scored = expectations(design, parameters)
    if not parameters.fitted or scored.expected is None or not scored.judges:
        return base
    bounds = spec.pooling.shape_bounds
    boot = interval(
        scored,
        design,
        parameters.replicates,
        seed=parameters.seed,
        bounds=bounds,
        grid=spec.pooling.shape_grid,
        level=spec.bootstrap.level,
    )
    kept = kept_judges(
        scored.size,
        scored.expected,
        minimum_cohort=spec.thresholds.minimum_cohort,
        minimum_expected=spec.thresholds.minimum_expected,
    )
    judges = int(kept.sum())
    counted = BootstrapStability(
        source=base.source,
        target=base.target,
        window_days=base.window_days,
        status=TOO_FEW_JUDGES,
        replicates=boot.replicates,
        requested=boot.requested,
        judges=judges,
        interval_width=None,
        share_excluding_one=None,
        rank_width=None,
    )
    if judges < MINIMUM_JUDGES or boot.replicates == 0:
        return counted
    lower = np.array([round6(float(value)) for value in boot.lower[kept]])
    upper = np.array([round6(float(value)) for value in boot.upper[kept]])
    excluding = (lower > 1.0) | (upper < 1.0)
    ranks = np.vstack([average_ranks(row) for row in boot.ratios[:, kept]])
    tail = (1.0 - spec.bootstrap.level) / 2.0
    rank_bounds = np.quantile(ranks, [tail, 1.0 - tail], axis=0, method="linear")
    return BootstrapStability(
        source=base.source,
        target=base.target,
        window_days=base.window_days,
        status=SUMMARIZED,
        replicates=boot.replicates,
        requested=boot.requested,
        judges=judges,
        interval_width=_spread(upper - lower),
        share_excluding_one=float(np.mean(excluding)),
        rank_width=_spread(rank_bounds[1] - rank_bounds[0]),
    )
