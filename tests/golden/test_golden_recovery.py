# tests/golden/test_golden_recovery.py
"""The published estimator recovers the planted judge effects on the demo world.

The demo world is built in memory from seed 20260916
(``tests/property/support.frame_from_world``), fitted with Step 2's
``fit_frame`` and the specification for the targets and windows its
``recovery`` block names, and estimated with the very function the compute
publishes from (``adjustment.ratios.estimate``: expected counts, the pooled
ratio, the pooling weight, the bootstrap interval). The planted answer is
``synthetic/truth.compute_effects`` on the same world. Over the judges with
at least the block's minimum members in the ratio, per fit:

- the Spearman correlation between the log pooled ratio and the
  court-centered planted effect meets the block's tolerance;
- the sign of the log pooled ratio agrees with the effect for every judge
  whose centered effect exceeds the block's magnitude;
- the raw rates (O / n) rank the same effects worse than the adjusted ratios;
- the model's expected counts correlate with the oracle's ``sum(p0)`` (the
  expected count with the court's mean effect) at the block's minimum
  (Pearson);
- at least the block's share of the published intervals (six decimals)
  cover each judge's true ratio ``sum(p) / sum(p0)``.

The tolerances were set by running this test once and are recorded with the
measured values in ``data/reference/outcome_model.yaml``; nothing is written
anywhere, and no person-level value leaves memory.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from judgemetrics.metrics.adjustment.expected import ModelParameters
from judgemetrics.metrics.adjustment.fit import FITTED, fit_frame
from judgemetrics.metrics.adjustment.ratios import Estimates, estimate
from judgemetrics.metrics.adjustment.spec import RecoveryFit, load_spec
from judgemetrics.metrics.intervals import round6
from judgemetrics.synthetic.config import DEMO
from judgemetrics.synthetic.truth import build_timelines, compute_effects
from tests.property.support import build_world, frame_from_world
from tests.unit.test_synthetic_effects import spearman

pytestmark = pytest.mark.golden

DEMO_SEED = 20260916
SOURCE = "synthetic"
SPEC = load_spec()
RECOVERY = SPEC.recovery
FITS = RECOVERY.fits


class Recovery:
    """One fit's estimates over the kept judges, with the planted answer beside them."""

    def __init__(self, fit: RecoveryFit, estimates: Estimates, effects: dict[str, Any]) -> None:
        scored = estimates.scored
        block = effects["targets"][fit.target]
        truth = (
            block["judges"]
            if fit.window_days is None
            else block["windows"][str(fit.window_days)]["judges"]
        )
        effect = block["effect"]
        self.fit = fit
        self.judges = [
            judge
            for index, judge in enumerate(scored.judges)
            if scored.size[index] >= RECOVERY.minimum_followed_cohort
        ]
        position = {judge: index for index, judge in enumerate(scored.judges)}
        rows = [position[judge] for judge in self.judges]
        assert scored.expected is not None
        self.centered = [float(effects["judges"][j]["centered"][effect]) for j in self.judges]
        self.log_ratio = [math.log(float(estimates.ratio[i])) for i in rows]
        self.raw = [float(scored.observed[i]) / float(scored.size[i]) for i in rows]
        self.expected = [float(scored.expected[i]) for i in rows]
        self.oracle_expected = [float(truth[j]["expected_centered"]) for j in self.judges]
        self.true_ratio = [float(truth[j]["true_ratio"]) for j in self.judges]
        self.lower = [round6(float(estimates.lower[i])) for i in rows]
        self.upper = [round6(float(estimates.upper[i])) for i in rows]

    @property
    def label(self) -> str:
        return f"{self.fit.target}@{self.fit.window_days}"


@pytest.fixture(scope="module")
def recovered() -> list[Recovery]:
    world = build_world(DEMO_SEED, DEMO)
    frame = frame_from_world(world, DEMO)
    keys = {(SOURCE, fit.target, fit.window_days) for fit in FITS}
    models = {
        (model.target, model.window_days): model
        for model in fit_frame(frame, SPEC, seed=SPEC.seed, source=SOURCE, only=keys)
    }
    effects = compute_effects(world, build_timelines(world))
    results: list[Recovery] = []
    for fit in FITS:
        model = models[(fit.target, fit.window_days)]
        assert model.status == FITTED, fit
        estimates = estimate(model.design, ModelParameters.from_fitted(model), SPEC)
        results.append(Recovery(fit, estimates, effects))
    return results


def test_enough_judges_are_kept_for_every_fit(recovered: list[Recovery]) -> None:
    assert [(r.fit.target, r.fit.window_days) for r in recovered] == [
        (fit.target, fit.window_days) for fit in FITS
    ]
    for result in recovered:
        assert len(result.judges) >= 15, result.label


def test_the_log_pooled_ratio_ranks_the_centered_effects(recovered: list[Recovery]) -> None:
    for result in recovered:
        rho = spearman(result.centered, result.log_ratio)
        assert rho >= RECOVERY.spearman_minimum[result.fit.target], (result.label, rho)


def test_the_sign_agrees_for_every_judge_with_a_large_effect(recovered: list[Recovery]) -> None:
    for result in recovered:
        checked = 0
        for judge, effect, log_ratio in zip(
            result.judges, result.centered, result.log_ratio, strict=True
        ):
            if abs(effect) > RECOVERY.sign_agreement_above:
                checked += 1
                assert math.copysign(1.0, effect) == math.copysign(1.0, log_ratio), (
                    result.label,
                    judge,
                    effect,
                    log_ratio,
                )
        assert checked >= 3, result.label


def test_raw_rates_rank_the_effects_worse_than_the_adjusted_ratios(
    recovered: list[Recovery],
) -> None:
    for result in recovered:
        adjusted = spearman(result.centered, result.log_ratio)
        raw = spearman(result.centered, result.raw)
        assert raw < adjusted, (result.label, raw, adjusted)


def test_the_expected_counts_track_the_oracle(recovered: list[Recovery]) -> None:
    for result in recovered:
        correlation = float(np.corrcoef(result.expected, result.oracle_expected)[0, 1])
        assert correlation >= RECOVERY.expected_correlation_minimum, (result.label, correlation)


def test_the_intervals_cover_the_true_ratios_at_the_specified_share(
    recovered: list[Recovery],
) -> None:
    for result in recovered:
        covered = [
            lower <= truth <= upper
            for lower, truth, upper in zip(
                result.lower, result.true_ratio, result.upper, strict=True
            )
        ]
        assert all(lower <= upper for lower, upper in zip(result.lower, result.upper, strict=True))
        share = sum(covered) / len(covered)
        assert share >= RECOVERY.interval_coverage_minimum, (result.label, share)
