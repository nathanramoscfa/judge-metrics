# tests/property/test_effects_invariants.py
"""The planted-effects oracle's invariants over in-memory ``TINY`` worlds.

For a Hypothesis-drawn seed: every probability a draw used — the judicial
release probability (with the judge's leniency and with the court's mean),
the failure-to-appear probability, and the release's chance of taking
effect before the corpus end, where positive — lies strictly inside
(0, 1), and every window probability of ``effects.json`` inside [0, 1] (a
window can hold certainly none or all of a draw's days: a member without a
next case has ``p = 0`` by construction); zeroing every judge effect makes
``p`` equal ``p0`` for every target, judge, and window; and the risk index
of a case never changes when a later case, event, or sentence of the
person — or the case's own later events and sentence — changes. Strategies
draw seeds only; a failure prints the seed and nothing restricted.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from hypothesis import given

from judgemetrics.synthetic.config import TINY
from judgemetrics.synthetic.effects import logistic, risk_features, risk_index
from judgemetrics.synthetic.model import Event, Sentence
from judgemetrics.synthetic.truth import (
    build_timelines,
    compute_effects,
    court_means,
)
from tests.property.support import build_world, seeds

pytestmark = pytest.mark.property


@given(seed=seeds)
def test_every_oracle_probability_lies_strictly_inside_zero_and_one(seed: int) -> None:
    world = build_world(seed, TINY)
    means = court_means(world)
    for case in world.cases:
        draws = case.draws
        assert draws is not None, seed
        if draws.release is not None:
            judge = world.judge(draws.release.judge_code)
            for shift in (judge.leniency, means.mean(case.court_code, "leniency")):
                assert 0.0 < logistic(draws.release.base_logit + shift) < 1.0, seed
            assert 0.0 <= draws.release.observed_share <= 1.0, seed
        if draws.fta is not None:
            effects = [0.0]
            if draws.fta.judge_code is not None:
                effects = [
                    world.judge(draws.fta.judge_code).fta_effect,
                    means.mean(case.court_code, "fta_effect"),
                ]
            for effect in effects:
                assert 0.0 < logistic(draws.fta.base_logit + effect) < 1.0, seed
    effects_json = compute_effects(world, build_timelines(world))
    for code, entry in effects_json["targets"]["pretrial_release"]["judges"].items():
        assert 0.0 <= entry["expected"] <= entry["decisions"], (seed, code)
        assert 0.0 <= entry["expected_centered"] <= entry["decisions"], (seed, code)
    for target in ("new_case", "failure_to_appear"):
        for window, block in effects_json["targets"][target]["windows"].items():
            for code, entry in block["judges"].items():
                for key in ("expected", "expected_centered"):
                    assert 0.0 <= entry[key] <= entry["followed"], (seed, target, window, code)


@given(seed=seeds)
def test_zeroing_every_judge_effect_makes_p_equal_p0(seed: int) -> None:
    world = build_world(seed, TINY)
    for judge in world.judges:
        judge.leniency = judge.new_case_effect = judge.fta_effect = 0.0
    effects_json = compute_effects(world, build_timelines(world))
    for code, block in effects_json["judges"].items():
        assert set(block["centered"].values()) == {0.0}, (seed, code)
    entries = list(effects_json["targets"]["pretrial_release"]["judges"].values())
    for target in ("new_case", "failure_to_appear"):
        for block in effects_json["targets"][target]["windows"].values():
            entries.extend(block["judges"].values())
    for entry in entries:
        assert entry["expected"] == entry["expected_centered"], (seed, entry)
        assert entry["true_ratio"] in (None, 1.0), (seed, entry)


@given(seed=seeds)
def test_a_cases_risk_index_ignores_everything_at_or_after_its_filing(seed: int) -> None:
    world = build_world(seed, TINY)
    for person in world.persons:
        cases = world.cases_of(person)
        for position, case in enumerate(cases):
            features = risk_features(case, cases)
            index = risk_index(features)
            later = cases[position + 1 :]
            # Rewrite everything that happens at or after the case's filing: the
            # case's own later events and sentence, and every later case.
            for other in [case, *later]:
                at = other.filed_at + timedelta(hours=1)
                other.events.append(Event("failure_to_appear", at, "defense", None, None))
                other.sentence = Sentence("J-0001", at, 365, None, None, ("incarceration",))
            for other in later:
                for charge in other.charges:
                    charge.disposition = "convicted_plea"
                    charge.disposed_at = other.filed_at + timedelta(hours=2)
            assert risk_features(case, cases) == features, (seed, person.true_id, position)
            assert risk_index(risk_features(case, cases)) == index, seed
