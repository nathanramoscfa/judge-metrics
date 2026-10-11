# src/judgemetrics/metrics/adjustment/ratios.py
"""``observed_expected`` observations: expected counts, pooled ratios, intervals, members.

``adjusted_observations(frame, definition, source_id=, models=, judges=)``
computes one registry ``observed_expected`` metric for every judge of one
source's frame at once and returns the drafts of the requested judges, plus a
not-observable record per judge when the source cannot document the
target's outcome. Per window (one, ``None``, for the release target):

1. **The design** of the specification target the entry names
   (``features.design_rows``) — every eligible index event of the source,
   built once — scored by the source's model for that target and window
   (``expected.expectations``): per judge ``n`` (members in the ratio), ``O``,
   and ``E``.
2. **Pooling** (``pooling``): the shape fitted over every judge with
   ``E > 0`` — suppressed or not — then per judge the pooled ratio
   ``(alpha + O) / (alpha + E)`` and the weight ``E / (E + alpha)``.
3. **The interval** (``bootstrap.interval``) from the model's replicate
   coefficients.
4. **The draft** per requested judge, laid out as docs/DATA_MODEL.md
   "metric_observation by kind" states: ``observed_count`` O,
   ``cohort_size`` n, ``eligible_count`` the judge's cohort before the
   follow-up restriction (every attributed decision of the release target;
   the whole pretrial-release cohort of a windowed one), ``observed_rate``
   O / n, ``expected_count`` E, ``expected_rate`` E / n,
   ``standardized_ratio`` the pooled ratio, the bounds its interval,
   ``pooling_weight``, and the model's content hash; suppression applied
   (``suppression.apply``: below the cohort threshold, below the minimum
   expected count, or without a fitted model). Members are the cohort's
   decisions — public entity ids, never a person — with ``followed`` for a
   member in the ratio and ``counted`` for one with the outcome.

The entry's attribution must equal its target population's (the gate the
design applies), and a windowed entry's outcome and windows the target's;
otherwise ``RatioError``. A model whose specification version is not the
loaded specification's, or whose columns differ from the design's, is
refused the same way: an observation is only ever computed with the model it
cites. Figures are rounded at the boundary (six decimals; ``E`` keeps its
full precision until the database stores it to four).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

import numpy as np
import polars as pl

from judgemetrics.metrics.adjustment.bootstrap import interval
from judgemetrics.metrics.adjustment.expected import (
    ExpectationError,
    Expectations,
    ModelParameters,
    expectations,
)
from judgemetrics.metrics.adjustment.features import DesignFrame, design_rows
from judgemetrics.metrics.adjustment.logistic import FloatArray
from judgemetrics.metrics.adjustment.pooling import (
    ShapeFit,
    fit_shape,
    pooled_ratio,
    pooling_weight,
)
from judgemetrics.metrics.adjustment.spec import (
    DECISION,
    OutcomeModelSpec,
    SpecError,
    TargetSpec,
    load_spec,
)
from judgemetrics.metrics.attribution import (
    JUDGE,
    AttributionRule,
    Subject,
    pretrial_decisions_for,
)
from judgemetrics.metrics.compute import NotObservableRecord, ObservationDraft
from judgemetrics.metrics.frame import Frame
from judgemetrics.metrics.index_events import MEMBER_DECISION, PRETRIAL_RELEASE, index_events
from judgemetrics.metrics.intervals import round6
from judgemetrics.metrics.members import PLAIN, MemberFamily, atoms
from judgemetrics.metrics.registry import (
    OBSERVED_EXPECTED,
    MetricDefinitionSpec,
    load_registry,
)
from judgemetrics.metrics.suppression import apply
from judgemetrics.metrics.windows import NotObservable, not_observable

ModelKey = tuple[str, int | None]


class RatioError(ValueError):
    """An adjusted metric cannot be computed as defined (a registry, spec, or model mismatch)."""


def _target(definition: MetricDefinitionSpec, spec: OutcomeModelSpec) -> TargetSpec:
    """The specification target an adjusted entry reads, checked against the entry."""
    adjustment = definition.adjustment
    if definition.kind != OBSERVED_EXPECTED or adjustment is None:
        msg = f"{definition.slug} is not an {OBSERVED_EXPECTED} metric"
        raise RatioError(msg)
    try:
        target = spec.target(adjustment.target)
    except SpecError as exc:
        raise RatioError(f"{definition.slug}: {exc}") from exc
    population = load_registry()[target.population]
    if population.attribution != definition.attribution:
        msg = (
            f"{definition.slug}: its attribution differs from the gate of {target.population}, "
            f"the population of target {target.name}"
        )
        raise RatioError(msg)
    windows = None if target.index == DECISION else target.windows_days
    if definition.windows_days != windows or (
        target.index != DECISION and definition.outcome != target.outcome
    ):
        msg = f"{definition.slug}: its outcome and windows differ from target {target.name}'s"
        raise RatioError(msg)
    return target


def _cohorts(
    frame: Frame, target: TargetSpec, rule: AttributionRule, judges: Sequence[str]
) -> dict[str, list[str]]:
    """Per judge, the decision ids of its cohort before the follow-up restriction (sorted)."""
    cohorts: dict[str, list[str]] = {}
    for judge in judges:
        if target.index == DECISION:
            rows = pretrial_decisions_for(frame, JUDGE, judge, rule).select(pl.col("id"))
        else:
            rows = index_events(frame, PRETRIAL_RELEASE, rule, Subject(JUDGE, judge)).select(
                pl.col("member_id").alias("id")
            )
        cohorts[judge] = sorted({str(value) for value in rows["id"].to_list()})
    return cohorts


def _model(
    models: Mapping[ModelKey, ModelParameters],
    target: TargetSpec,
    window: int | None,
    spec: OutcomeModelSpec,
) -> ModelParameters:
    parameters = models.get((target.name, window))
    if parameters is None:
        msg = f"no outcome model for target {target.name} window {window} was given"
        raise RatioError(msg)
    if parameters.target != target.name or parameters.window_days != window:
        msg = f"the model given for {target.name}@{window} is {parameters.target}@{window}"
        raise RatioError(msg)
    if parameters.spec_version != spec.version:
        msg = (
            f"the {target.name}@{window} model was fitted under specification "
            f"{parameters.spec_version}; the file is {spec.version}"
        )
        raise RatioError(msg)
    return parameters


def _finite(value: float) -> float | None:
    return None if not math.isfinite(value) else round6(value)


@dataclass(frozen=True, slots=True)
class Estimates:
    """One design scored, pooled, and bootstrapped: per judge in ``scored.judges`` order.

    ``ratio``, ``weight``, ``lower``, and ``upper`` are NaN without a fitted
    model (and the bounds where no replicate converged); ``shape`` is ``None``
    then. Unrounded: the drafts round at the boundary.
    """

    scored: Expectations
    shape: ShapeFit | None
    ratio: FloatArray
    weight: FloatArray
    lower: FloatArray
    upper: FloatArray


def estimate(design: DesignFrame, parameters: ModelParameters, spec: OutcomeModelSpec) -> Estimates:
    """Expected counts, the pooled ratios and weights, and the bootstrap interval of a design."""
    try:
        scored = expectations(design, parameters)
    except ExpectationError as exc:
        raise RatioError(str(exc)) from exc
    count = len(scored.judges)
    blank = np.full(count, np.nan, dtype=np.float64)
    if not parameters.fitted or scored.expected is None or count == 0:
        return Estimates(scored, None, blank, blank.copy(), blank.copy(), blank.copy())
    bounds = spec.pooling.shape_bounds
    shape = fit_shape(scored.observed, scored.expected, bounds=bounds, grid=spec.pooling.shape_grid)
    bootstrap = interval(
        scored,
        design,
        parameters.replicates,
        seed=parameters.seed,
        bounds=bounds,
        grid=spec.pooling.shape_grid,
        level=spec.bootstrap.level,
    )
    return Estimates(
        scored=scored,
        shape=shape,
        ratio=pooled_ratio(scored.observed.astype(np.float64), scored.expected, shape.shape),
        weight=pooling_weight(scored.expected, shape.shape),
        lower=bootstrap.lower,
        upper=bootstrap.upper,
    )


def _window_drafts(
    frame: Frame,
    definition: MetricDefinitionSpec,
    *,
    source_id: str,
    window: int | None,
    design: DesignFrame,
    estimates: Estimates,
    parameters: ModelParameters,
    cohorts: Mapping[str, Sequence[str]],
) -> tuple[list[ObservationDraft], dict[str, dict[str, bool]]]:
    """One draft per requested judge for one window, and each judge's members in the ratio.

    The second value maps a judge to ``{member: had the outcome}`` for the members the
    design scored (the drafts carry no members of their own: ``_judge_family`` builds one
    family per judge from every window's flags).
    """
    scored = estimates.scored
    ratios, weights = estimates.ratio, estimates.weight
    lower, upper = estimates.lower, estimates.upper
    outcomes: dict[str, dict[str, bool]] = {judge: {} for judge in scored.judges}
    for member, row, outcome in zip(
        design.member_ids, scored.rows.tolist(), scored.outcome.tolist(), strict=True
    ):
        outcomes[scored.judges[row]][member] = outcome == 1.0
    drafts: list[ObservationDraft] = []
    for judge, cohort in cohorts.items():
        position = scored.position(judge)
        in_ratio = outcomes.get(judge, {})
        stray = set(in_ratio) - set(cohort)
        if stray:
            msg = f"{definition.slug}: {len(stray)} design member(s) outside the judge's cohort"
            raise RatioError(msg)
        n = len(in_ratio)
        observed = sum(1 for flag in in_ratio.values() if flag)
        expected: float | None = None
        if parameters.fitted:
            expected = (
                0.0
                if position is None or scored.expected is None
                else float(scored.expected[position])
            )
        has_ratio = position is not None and parameters.fitted and n > 0
        draft = ObservationDraft(
            slug=definition.slug,
            version=definition.version,
            subject_type=JUDGE,
            subject_id=judge,
            source_id=source_id,
            period_start=frame.coverage_start,
            period_end=frame.coverage_end,
            window_days=window,
            dimension_value=None,
            eligible_count=len(cohort),
            cohort_size=n,
            observed_count=observed,
            observed_rate=None if n == 0 else round6(observed / n),
            value=None,
            distribution=None,
            lower=_finite(float(lower[position])) if has_ratio and position is not None else None,
            upper=_finite(float(upper[position])) if has_ratio and position is not None else None,
            expected_count=expected,
            expected_rate=None if expected is None or n == 0 else round6(expected / n),
            standardized_ratio=(
                _finite(float(ratios[position])) if has_ratio and position is not None else None
            ),
            pooling_weight=(
                _finite(float(weights[position])) if has_ratio and position is not None else None
            ),
            model_hash=parameters.content_hash,
        )
        drafts.append(apply(draft, definition))
    return drafts, outcomes


def _judge_family(
    cohort: Sequence[str], flags: Sequence[Mapping[str, bool]], windows: Sequence[int | None]
) -> MemberFamily:
    """One judge's family: the cohort's decisions, a flag slot per window.

    ``flags[i]`` maps the cohort members in the ratio of window ``i`` to whether they
    had the outcome: ``followed`` is membership, ``counted`` the outcome. Adjusted
    observations cover the whole coverage window, so no row carries an anchor year.
    """
    members = pl.DataFrame({"member_id": list(cohort)}, schema={"member_id": pl.String})
    counted: list[pl.Expr] = []
    followed: list[pl.Expr] = []
    for in_ratio in flags:
        counted.append(pl.col("member_id").is_in([m for m, outcome in in_ratio.items() if outcome]))
        followed.append(pl.col("member_id").is_in(list(in_ratio)))
    return MemberFamily(
        MEMBER_DECISION,
        PLAIN,
        tuple(windows),
        atoms(members, member_id="member_id", anchor=None, counted=counted, followed=followed),
    )


def adjusted_observations(
    frame: Frame,
    definition: MetricDefinitionSpec,
    *,
    source_id: str,
    models: Mapping[ModelKey, ModelParameters],
    judges: Sequence[Subject],
    spec: OutcomeModelSpec | None = None,
) -> tuple[list[ObservationDraft], list[NotObservableRecord]]:
    """Every requested judge's observations of one adjusted metric (see the module docstring)."""
    spec = spec or load_spec()
    target = _target(definition, spec)
    wanted = sorted(
        {str(subject.subject_id) for subject in judges if subject.subject_type == JUDGE}
    )
    if target.index != DECISION:
        blocked = not_observable(frame, target.outcome)
        if blocked is not None:
            return [], [
                NotObservableRecord(
                    slug=definition.slug,
                    version=definition.version,
                    subject_type=JUDGE,
                    subject_id=judge,
                    source_id=source_id,
                    outcome=blocked.outcome,
                    reason=blocked.reason,
                )
                for judge in wanted
            ]
    rule = AttributionRule.from_spec(definition.attribution)
    cohorts = _cohorts(frame, target, rule, wanted)
    drafts: list[ObservationDraft] = []
    per_window: list[dict[str, dict[str, bool]]] = []
    for window in target.windows:
        parameters = _model(models, target, window, spec)
        design = design_rows(frame, spec, target, window)
        if isinstance(design, NotObservable):  # pragma: no cover - checked above
            msg = f"{definition.slug}: {design.reason}"
            raise RatioError(msg)
        try:
            estimates = estimate(design, parameters, spec)
        except RatioError as exc:
            raise RatioError(f"{definition.slug}: {exc}") from exc
        window_drafts, outcomes = _window_drafts(
            frame,
            definition,
            source_id=source_id,
            window=window,
            design=design,
            estimates=estimates,
            parameters=parameters,
            cohorts=cohorts,
        )
        drafts.extend(window_drafts)
        per_window.append(outcomes)
    families = {
        judge: _judge_family(
            cohort, [outcomes.get(judge, {}) for outcomes in per_window], tuple(target.windows)
        )
        for judge, cohort in cohorts.items()
    }
    return [replace(draft, family=families[draft.subject_id]) for draft in drafts], []
