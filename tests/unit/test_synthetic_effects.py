# tests/unit/test_synthetic_effects.py
"""The planted effects (GENERATOR_VERSION 3) are recoverable in principle.

Over the demo world generated in memory once per module (seed 20260916)
and the golden world (seed 7): the initial judge's weights read observable
features only; the docket tilts confound the raw new-case rates (a
same-court judge pair ranks opposite to its planted effects); the oracle
ratios (observed / the court-centered oracle expectation) rank the
centered effects; the oracle's expected counts match the draws in total;
``effects.json``'s cohorts and observed counts equal ``metrics.json``'s;
and re-seeding the ``attributes`` stream moves ``synthetic_group`` and
nothing else. These are the properties Steps 2-4 fit, measure, and report
against; the thresholds are the Step 1 acceptance criteria.
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
from datetime import timedelta
from itertools import combinations
from typing import Any

import pytest

from judgemetrics.synthetic.config import DEMO, GOLDEN
from judgemetrics.synthetic.effects import (
    assignment_weights,
    risk_features,
    risk_index,
)
from judgemetrics.synthetic.generate import build_dataset
from judgemetrics.synthetic.model import Case, World
from judgemetrics.synthetic.rng import Streams, derive_stream
from judgemetrics.synthetic.truth import (
    WINDOWS_DAYS,
    build_timelines,
    compute_effects,
    compute_metrics,
)
from judgemetrics.synthetic.vocabulary import SYNTHETIC_GROUPS
from judgemetrics.synthetic.writer import render_source
from tests.golden.conftest import GOLDEN as GOLDEN_DIR

pytestmark = pytest.mark.unit

DEMO_SEED = 20260916
GOLDEN_SEED = 7
MINIMUM_MEMBERS = 30
TOTALS_TOLERANCE = 0.10
TARGET_EFFECTS = {"new_case": "new_case_effect", "failure_to_appear": "fta_effect"}


class Truth:
    """A world with its truth files computed in memory."""

    def __init__(self, seed: int, scale: Any) -> None:
        self.world, _ = build_dataset(seed, scale)
        timelines = build_timelines(self.world)
        self.metrics = compute_metrics(self.world, timelines)
        self.effects = compute_effects(self.world, timelines)


@pytest.fixture(scope="module")
def demo() -> Truth:
    return Truth(DEMO_SEED, DEMO)


@pytest.fixture(scope="module")
def golden() -> Truth:
    return Truth(GOLDEN_SEED, GOLDEN)


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            ranks[order[position]] = (start + end) / 2 + 1
        start = end + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float:
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    covariance = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    spread = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return covariance / spread


def _history(world: World, case: Case) -> list[Case]:
    return world.cases_of(case.person)


def test_assignment_weights_read_observable_features_only(demo: Truth) -> None:
    world = demo.world
    case = next(c for c in world.cases if c.ordinal >= 2 and c.draws is not None)
    history = _history(world, case)
    features = risk_features(case, history)
    judges = world.judges_serving(case.court_code, case.filed_date)
    weights = assignment_weights(judges, risk_index(features))
    for change in (
        {"propensity": 1.0 - case.person.propensity},
        {
            "date_of_birth": case.person.date_of_birth - timedelta(days=365 * 30),
            "age_band": "55+",
        },
        {"synthetic_group": next(g for g in SYNTHETIC_GROUPS if g != case.person.synthetic_group)},
    ):
        stub_person = dataclasses.replace(case.person, **change)
        stub = dataclasses.replace(case, person=stub_person)
        stub_history = [stub if other is case else other for other in history]
        stub_features = risk_features(stub, stub_history)
        assert stub_features == features, change
        assert assignment_weights(judges, risk_index(stub_features)) == weights, change
    # An observable difference does move the weights (the test has teeth).
    busier = dataclasses.replace(features, pending_case=not features.pending_case)
    assert assignment_weights(judges, risk_index(busier)) != weights or all(
        judge.docket_tilt == 0 for judge in judges
    )


def test_recorded_features_equal_a_recomputation_on_the_final_world(golden: Truth) -> None:
    """What the draws read is recomputable from the published rows (plants aside)."""
    for case in golden.world.cases:
        assert case.draws is not None
        if any(
            c.disposition is None for other in _history(golden.world, case) for c in other.charges
        ):
            continue  # a planted missing disposition can hide a prior conviction
        assert case.draws.features == risk_features(case, _history(golden.world, case))


def test_docket_tilt_confounds_raw_rates(demo: Truth) -> None:
    judges = demo.effects["judges"]
    raw = {
        code: block["pretrial"]["windows"]["365"]["new_case_rate"]
        for code, block in demo.metrics["judges"].items()
    }
    inverted = []
    for court in sorted({c for block in judges.values() for c in block["courts"]}):
        codes = [
            code
            for code, block in judges.items()
            if court in block["courts"] and raw[code]["denominator"] >= MINIMUM_MEMBERS
        ]
        for left, right in combinations(sorted(codes), 2):
            effect = judges[left]["new_case_effect"] - judges[right]["new_case_effect"]
            rate = raw[left]["value"] - raw[right]["value"]
            if effect * rate < 0:
                inverted.append((court, left, right))
    assert inverted, "no same-court judge pair ranks opposite to its planted new-case effects"


def test_oracle_ratios_rank_the_centered_effects(demo: Truth) -> None:
    judges = demo.effects["judges"]
    targets = demo.effects["targets"]
    release = targets["pretrial_release"]["judges"]
    kept = [code for code, entry in release.items() if entry["decisions"] >= MINIMUM_MEMBERS]
    assert len(kept) >= 15
    rho = spearman(
        [judges[code]["centered"]["leniency"] for code in kept],
        [release[code]["oracle_ratio"] for code in kept],
    )
    assert rho >= 0.9, rho
    for target, effect in TARGET_EFFECTS.items():
        entries = targets[target]["windows"]["365"]["judges"]
        kept = [code for code, entry in entries.items() if entry["followed"] >= MINIMUM_MEMBERS]
        assert len(kept) >= 15, target
        rho = spearman(
            [judges[code]["centered"][effect] for code in kept],
            [entries[code]["oracle_ratio"] for code in kept],
        )
        assert rho >= 0.8, (target, rho)


def test_oracle_totals_match_the_draws(demo: Truth) -> None:
    targets = demo.effects["targets"]
    release = targets["pretrial_release"]["judges"].values()
    observed = sum(entry["released"] for entry in release)
    expected = sum(entry["expected"] for entry in release)
    assert abs(observed - expected) <= TOTALS_TOLERANCE * expected, (observed, expected)
    for target in TARGET_EFFECTS:
        entries = targets[target]["windows"]["365"]["judges"].values()
        observed = sum(entry["observed"] for entry in entries)
        expected = sum(entry["expected"] for entry in entries)
        assert abs(observed - expected) <= TOTALS_TOLERANCE * expected, (target, observed, expected)


def _assert_cohorts_equal(metrics: dict[str, Any], effects: dict[str, Any]) -> None:
    for code, block in metrics["judges"].items():
        release = effects["targets"]["pretrial_release"]["judges"][code]
        assert release["decisions"] == block["pretrial"]["decisions"], code
        assert release["released"] == block["pretrial"]["released_count"], code
        windows = block["index_events"]["pretrial_release"]["windows"]
        for target in TARGET_EFFECTS:
            for window in WINDOWS_DAYS:
                entry = effects["targets"][target]["windows"][str(window)]["judges"][code]
                truth = windows[str(window)]
                assert entry["cohort"] == truth["cohort"], (code, target, window)
                assert entry["followed"] == truth["followed"], (code, target, window)
                assert entry["observed"] == truth[f"{target}_rate"]["numerator"], (
                    code,
                    target,
                    window,
                )


def test_effects_json_cohorts_equal_metrics_json(demo: Truth, golden: Truth) -> None:
    _assert_cohorts_equal(demo.metrics, demo.effects)
    _assert_cohorts_equal(golden.metrics, golden.effects)
    # The committed golden files agree with each other and hold no per-person row.
    committed_metrics = json.loads((GOLDEN_DIR / "truth" / "metrics.json").read_text("utf-8"))
    committed_effects = (GOLDEN_DIR / "truth" / "effects.json").read_text("utf-8")
    _assert_cohorts_equal(committed_metrics, json.loads(committed_effects))
    assert not re.search(r"\b(?:P|PT)-\d{6}\b|SYN-\d{4}-\d{6}", committed_effects)


def test_group_stream_is_independent() -> None:
    baseline, _ = build_dataset(GOLDEN_SEED, GOLDEN)
    streams = Streams(GOLDEN_SEED)
    streams.attributes = derive_stream(GOLDEN_SEED + 1, "attributes")
    reseeded, _ = build_dataset(GOLDEN_SEED, GOLDEN, streams=streams)
    before, after = render_source(baseline), render_source(reseeded)
    assert set(before) == set(after)
    for name in sorted(before):
        if name != "participants.csv":
            assert before[name] == after[name], name
    group = -1  # synthetic_group is the last participants.csv column
    rows_before, rows_after = before["participants.csv"], after["participants.csv"]
    assert [row[:group] for row in rows_before] == [row[:group] for row in rows_after]
    assert [row[group] for row in rows_before] != [row[group] for row in rows_after]
    # Nothing the truth computes moves either.
    for world in (baseline, reseeded):
        assert all(person.synthetic_group in SYNTHETIC_GROUPS for person in world.persons)
    timelines = build_timelines(baseline), build_timelines(reseeded)
    assert compute_metrics(baseline, timelines[0]) == compute_metrics(reseeded, timelines[1])
    assert compute_effects(baseline, timelines[0]) == compute_effects(reseeded, timelines[1])
