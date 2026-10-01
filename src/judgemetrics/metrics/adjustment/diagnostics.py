# src/judgemetrics/metrics/adjustment/diagnostics.py
"""Model diagnostics: the temporal split, calibration, discrimination, stability.

The brief's ``model_validation`` tests Step 2 computes (Step 4 reports them):

- ``split_cutoff`` — the temporal split: the test set is the index events
  at or after the ``test_quantile`` (nearest-rank) quantile of index time,
  the training set the ones before it.
- ``evaluate(predicted, outcome, base_rate)`` over the test set — the Brier
  score ``mean((p - y)^2)`` and its skill ``1 - Brier / Brier_ref`` against
  the training base rate; ROC AUC by the Mann–Whitney statistic with tied
  predictions sharing their average rank (a secondary diagnostic, never the
  only one); ten calibration bins — the test rows ordered by predicted
  probability (ties by row order) and cut into ten equal-count groups, the
  deciles — each with its count, mean prediction, and observed rate;
  calibration in the large, observed over expected; and the calibration
  slope, the coefficient of a one-feature unpenalized logistic fit of the
  outcome on the logit of the prediction (1 for a calibrated model).
- ``stability(estimate, replicates)`` — feature stability over the
  bootstrap replicates: each coefficient's mean, standard deviation, and
  the share of replicates agreeing with the published estimate in sign.

Missing-data sensitivity is Step 4's: ``refit_complete_cases`` is the refit
it compares with the published fit — the same design without every row
that has a feature at its missing level.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from judgemetrics.metrics.adjustment.features import DesignFrame
from judgemetrics.metrics.adjustment.logistic import FloatArray, LogisticFit, fit_logistic
from judgemetrics.metrics.adjustment.spec import ModelSettings

BINS = 10
# Predictions are clipped this far from 0 and 1 before the logit is taken.
LOGIT_CLIP = 1e-12


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    bin: int
    count: int
    mean_predicted: float | None
    observed_rate: float | None


@dataclass(frozen=True, slots=True)
class Evaluation:
    """The test-set diagnostics of one model (``None`` where a statistic is undefined)."""

    rows: int
    events: int
    base_rate_train: float
    brier: float | None
    brier_skill: float | None
    auc: float | None
    calibration_in_the_large: float | None
    calibration_slope: float | None
    bins: tuple[CalibrationBin, ...]


@dataclass(frozen=True, slots=True)
class Stability:
    """One coefficient over the converged bootstrap replicates."""

    column: str
    mean: float | None
    sd: float | None
    sign_agreement: float | None


def split_cutoff(index_at: npt.NDArray[np.int64], quantile: float) -> int | None:
    """The nearest-rank ``quantile`` of the index times (microseconds); ``None`` without rows.

    Rows at or after the cutoff form the test set.
    """
    if index_at.size == 0:
        return None
    ordered = np.sort(index_at, kind="stable")
    rank = max(1, math.ceil(quantile * ordered.size))
    return int(ordered[rank - 1])


def brier(predicted: FloatArray, outcome: FloatArray) -> float | None:
    if predicted.size == 0:
        return None
    return float(np.mean((predicted - outcome) ** 2))


def average_ranks(values: FloatArray) -> FloatArray:
    """1-based ranks with ties sharing their average rank."""
    order = np.argsort(values, kind="stable")
    ranks = np.empty(values.size, dtype=np.float64)
    position = 0
    while position < values.size:
        end = position
        while end + 1 < values.size and values[order[end + 1]] == values[order[position]]:
            end += 1
        ranks[order[position : end + 1]] = (position + end) / 2.0 + 1.0
        position = end + 1
    return ranks


def roc_auc(predicted: FloatArray, outcome: FloatArray) -> float | None:
    """The Mann–Whitney AUC with ties averaged; ``None`` unless both classes are present."""
    positives = int(outcome.sum())
    negatives = int(outcome.size - positives)
    if positives == 0 or negatives == 0:
        return None
    ranks = average_ranks(predicted)
    rank_sum = float(ranks[outcome == 1.0].sum())
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def calibration_bins(
    predicted: FloatArray, outcome: FloatArray, bins: int = BINS
) -> tuple[CalibrationBin, ...]:
    """Ten equal-count bins of the rows ordered by prediction (ties by row order)."""
    order = np.argsort(predicted, kind="stable")
    result: list[CalibrationBin] = []
    for number, members in enumerate(np.array_split(order, bins), start=1):
        if members.size == 0:
            result.append(CalibrationBin(number, 0, None, None))
            continue
        result.append(
            CalibrationBin(
                bin=number,
                count=int(members.size),
                mean_predicted=float(np.mean(predicted[members])),
                observed_rate=float(np.mean(outcome[members])),
            )
        )
    return tuple(result)


def logit(predicted: FloatArray) -> FloatArray:
    clipped = np.clip(predicted, LOGIT_CLIP, 1.0 - LOGIT_CLIP)
    result: FloatArray = np.log(clipped) - np.log1p(-clipped)
    return result


def calibration_slope(
    predicted: FloatArray, outcome: FloatArray, settings: ModelSettings
) -> float | None:
    """The slope of an unpenalized logistic fit of the outcome on the prediction's logit."""
    positives = int(outcome.sum())
    if positives == 0 or positives == outcome.size:
        return None
    design = np.column_stack([np.ones(predicted.size), logit(predicted)])
    fit = fit_logistic(
        design,
        outcome,
        lam=0.0,
        max_iterations=settings.max_iterations,
        tolerance=settings.tolerance,
        step_halvings=settings.step_halvings,
    )
    return float(fit.coefficients[1]) if fit.converged else None


def evaluate(
    predicted: FloatArray, outcome: FloatArray, base_rate_train: float, settings: ModelSettings
) -> Evaluation:
    """Every test-set diagnostic of ``predicted`` against ``outcome``."""
    score = brier(predicted, outcome)
    reference = brier(np.full(outcome.size, base_rate_train), outcome)
    skill = (
        None if score is None or reference is None or reference == 0.0 else 1.0 - score / reference
    )
    expected = float(predicted.sum())
    return Evaluation(
        rows=int(outcome.size),
        events=int(outcome.sum()),
        base_rate_train=base_rate_train,
        brier=score,
        brier_skill=skill,
        auc=roc_auc(predicted, outcome),
        calibration_in_the_large=None if expected == 0.0 else float(outcome.sum()) / expected,
        calibration_slope=calibration_slope(predicted, outcome, settings),
        bins=calibration_bins(predicted, outcome) if outcome.size else (),
    )


def stability(
    columns: Sequence[str],
    estimate: FloatArray,
    replicates: Sequence[FloatArray | None],
) -> tuple[Stability, ...]:
    """Each coefficient's mean, sample standard deviation, and sign agreement over replicates."""
    converged = [replicate for replicate in replicates if replicate is not None]
    if not converged:
        return tuple(Stability(column, None, None, None) for column in columns)
    stacked = np.vstack(converged)
    result: list[Stability] = []
    for index, column in enumerate(columns):
        values = stacked[:, index]
        sd = float(np.std(values, ddof=1)) if values.size > 1 else None
        agreement = float(np.mean(np.sign(values) == np.sign(estimate[index])))
        result.append(Stability(column, float(np.mean(values)), sd, agreement))
    return tuple(result)


def refit_complete_cases(design: DesignFrame, settings: ModelSettings) -> LogisticFit:
    """The published model refitted without every row that has a feature at its missing level.

    Same columns, same solver settings; ``design.missing`` flags the rows.
    """
    keep = ~design.missing
    return fit_logistic(
        design.matrix[keep],
        design.outcome[keep],
        lam=settings.lam,
        max_iterations=settings.max_iterations,
        tolerance=settings.tolerance,
        step_halvings=settings.step_halvings,
    )
