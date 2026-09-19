# tests/property/test_frame_invariants.py
"""The analytic frame's invariants over in-memory ``TINY`` worlds (no database).

For a Hypothesis-drawn seed the world is built in memory and turned into
a ``Frame`` (``support.frame_from_world``); every judge and court is a
subject. The invariants Step 2 and Phase 4 rely on: no outcome is counted
before its exposure start; a followed member is a cohort member and
``numerator <= followed <= eligible``; the fixed-window numerator is
monotone non-decreasing in the window for a fixed cohort; ``1 - S(w)`` is
in ``[0, 1]``, monotone non-decreasing in ``w``, and equals the
fixed-window rate when every member is followed for ``w``; the exposure
start is never before the index time and equals ``sentence_at +
incarceration_days`` when the sentence incarcerates; a statutory release
never appears in a judge's attributed decisions; and, against
``synthetic/truth.py`` on the same world, the pretrial-release cohort,
followed counts, and the ``failure_to_appear`` / ``new_case`` /
``reconviction`` numerators per subject and window are equal (the truth
is the oracle). A world builds in about a millisecond, so every example
builds its own; the window invariants are checked in one pass per cohort
because computing the cohorts dominates; the oracle test is derandomized
so CI is reproducible.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl
import pytest
from hypothesis import given, settings

from judgemetrics.metrics.attribution import (
    AttributionRule,
    Subject,
    attributed_decisions,
    statutory_releases,
    unknown_actor_pretrial_decisions,
)
from judgemetrics.metrics.censoring import (
    fixed_window_rates,
    kaplan_meier,
    member_windows,
)
from judgemetrics.metrics.exposure import with_exposure
from judgemetrics.metrics.frame import Frame
from judgemetrics.metrics.index_events import (
    DISPOSITION,
    INDEX_KINDS,
    PRETRIAL_RELEASE,
    SENTENCE,
    index_events,
)
from judgemetrics.metrics.registry import WINDOWS_DAYS, load_registry
from judgemetrics.metrics.windows import (
    ANY_CASE_OUTCOMES,
    MEMBER_KEY,
    OTHER_CASE_OUTCOMES,
    first_outcomes,
)
from judgemetrics.synthetic.config import TINY
from judgemetrics.synthetic.model import World
from judgemetrics.synthetic.truth import build_timelines, court_metrics, judge_metrics
from tests.property.support import SYNTHETIC_OBSERVABLE, build_world, frame_from_world, seeds

pytestmark = pytest.mark.property

REGISTRY = load_registry()
PRETRIAL_RULE = AttributionRule.from_spec(REGISTRY["failure_to_appear_rate"].attribution)
RULE_OF_KIND = {
    PRETRIAL_RELEASE: PRETRIAL_RULE,
    DISPOSITION: AttributionRule.from_spec(REGISTRY["new_case_rate_after_disposition"].attribution),
    SENTENCE: AttributionRule.from_spec(REGISTRY["new_case_rate_after_sentence"].attribution),
}
OUTCOMES = sorted(SYNTHETIC_OBSERVABLE)
TRUTH_OUTCOMES = ("failure_to_appear", "new_case", "reconviction")
KEY = list(MEMBER_KEY)


def _world_and_frame(seed: int) -> tuple[World, Frame]:
    world = build_world(seed, TINY)
    return world, frame_from_world(world, TINY)


def _subjects(world: World) -> list[Subject]:
    judges = [Subject("judge", judge.code) for judge in world.judges]
    courts = [Subject("court", court.code) for court in world.courts]
    return judges + courts


def _cohort(frame: Frame, kind: str, subject: Subject) -> pl.DataFrame:
    return with_exposure(frame, index_events(frame, kind, RULE_OF_KIND[kind], subject), kind)


@given(seed=seeds)
def test_no_outcome_is_counted_before_its_exposure_start(seed: int) -> None:
    world, frame = _world_and_frame(seed)
    for subject in _subjects(world):
        for kind in INDEX_KINDS:
            cohort = _cohort(frame, kind, subject)
            for outcome in OUTCOMES:
                firsts = first_outcomes(frame, cohort, outcome)
                found = firsts.filter(pl.col("first_outcome_at").is_not_null())
                assert (found["first_outcome_at"] > found["exposure_start"]).all(), (
                    seed,
                    subject,
                    kind,
                    outcome,
                )
                # The first outcome is a real event of the person: the earliest
                # qualifying event strictly after the exposure start, in another
                # case for the other-case outcomes.
                events = frame.justice_events.filter(pl.col("event_type") == outcome)
                for row in found.iter_rows(named=True):
                    own = events.filter(pl.col("person_id") == row["person_id"])
                    if outcome in OTHER_CASE_OUTCOMES:
                        own = own.filter(pl.col("related_case_id") != row["case_id"])
                    qualifying = own.filter(pl.col("event_at") > row["exposure_start"])
                    assert qualifying.height > 0
                    assert row["first_outcome_at"] == qualifying["event_at"].min()


@given(seed=seeds)
def test_window_and_survival_invariants_hold_for_every_cohort(seed: int) -> None:
    """Ordered counts, monotone numerators, bounded monotone survival equal to the rate."""
    world, frame = _world_and_frame(seed)
    end = frame.coverage_end_exclusive_at
    for subject in _subjects(world):
        for kind in INDEX_KINDS:
            cohort = _cohort(frame, kind, subject)
            keys = set(cohort.select(KEY).iter_rows())
            for outcome in OUTCOMES:
                firsts = first_outcomes(frame, cohort, outcome)
                flags = member_windows(firsts, end)
                # A followed member is a cohort member.
                assert set(flags.filter(pl.col("followed")).select(KEY).iter_rows()) <= keys
                # Numerator <= followed <= eligible, with the value and interval to match.
                rates = fixed_window_rates(firsts, end)
                for rate in rates:
                    assert 0 <= rate.numerator <= rate.followed <= rate.eligible == cohort.height
                    if rate.followed == 0:
                        assert rate.value is None and rate.lower is None and rate.upper is None
                    else:
                        assert rate.value == round(rate.numerator / rate.followed, 6)
                        assert rate.lower is not None and rate.upper is not None
                        assert 0.0 <= rate.lower <= rate.value <= rate.upper <= 1.0
                # The fixed-window numerator over the whole cohort is monotone in w,
                # in total and per member (an empty cohort pivots to no window columns).
                totals = [
                    int(flags.filter(pl.col("window_days") == window)["has_outcome"].sum())
                    for window in WINDOWS_DAYS
                ]
                assert totals == sorted(totals), (seed, subject, kind, outcome, totals)
                if cohort.height > 0:
                    wide = flags.pivot(on="window_days", index=KEY, values="has_outcome")
                    for row in wide.select([str(w) for w in WINDOWS_DAYS]).iter_rows():
                        assert list(row) == sorted(row), (seed, subject, kind, outcome)
                # 1 - S(w) is in [0, 1], monotone, and equals the rate when fully followed.
                previous = 0.0
                for rate, point in zip(rates, kaplan_meier(firsts, end), strict=True):
                    assert point.window_days == rate.window_days
                    assert point.eligible == rate.eligible
                    if point.eligible == 0:
                        assert point.cumulative_incidence is None
                        continue
                    assert point.cumulative_incidence is not None
                    assert 0.0 <= point.cumulative_incidence <= 1.0
                    assert point.cumulative_incidence >= previous
                    previous = point.cumulative_incidence
                    assert point.lower is not None and point.upper is not None
                    assert 0.0 <= point.lower <= point.cumulative_incidence <= point.upper <= 1.0
                    if rate.followed == rate.eligible:
                        assert point.censored == 0
                        assert point.cumulative_incidence == rate.value
                        assert point.events == rate.numerator


@given(seed=seeds)
def test_exposure_starts_at_the_index_unless_a_sentence_incarcerates(seed: int) -> None:
    world, frame = _world_and_frame(seed)
    terms = frame.sentences.select(
        "id", "case_id", "person_id", "sentence_at", "incarceration_days"
    )
    for subject in _subjects(world):
        for kind in INDEX_KINDS:
            cohort = _cohort(frame, kind, subject)
            assert (cohort["exposure_start"] >= cohort["index_at"]).all(), (seed, subject, kind)
            for row in cohort.iter_rows(named=True):
                if kind == PRETRIAL_RELEASE:
                    assert row["exposure_start"] == row["index_at"]
                    assert row["deferral_days"] is None
                    continue
                if kind == SENTENCE:
                    own = terms.filter(pl.col("id") == row["member_id"])
                else:
                    own = terms.filter(
                        (pl.col("case_id") == row["case_id"])
                        & (pl.col("person_id") == row["person_id"])
                    )
                incarcerating = own.filter(
                    pl.col("incarceration_days").is_not_null() & (pl.col("incarceration_days") > 0)
                )
                if incarcerating.height == 0:
                    assert row["exposure_start"] == row["index_at"]
                    assert row["deferral_days"] is None
                else:
                    ends = [
                        sentence_at + timedelta(days=days)
                        for sentence_at, days in incarcerating.select(
                            "sentence_at", "incarceration_days"
                        ).iter_rows()
                    ]
                    assert row["exposure_start"] == max(ends)
                    assert row["deferral_days"] in incarcerating["incarceration_days"].to_list()


@given(seed=seeds)
def test_a_statutory_release_never_appears_in_a_judges_attributed_decisions(seed: int) -> None:
    world, frame = _world_and_frame(seed)
    admitting = AttributionRule(decision_type="pretrial_release", assignment_gate="deciding_judge")
    statutory = sum(statutory_releases(frame, court.code).height for court in world.courts)
    unknown = sum(
        unknown_actor_pretrial_decisions(frame, court.code).height for court in world.courts
    )
    judicial = 0
    for judge in world.judges:
        rows = attributed_decisions(frame, admitting, Subject("judge", judge.code))
        judicial += rows.height
        assert "legislature_or_mandatory_rule" not in rows["actor_type"].to_list()
        assert "unknown" not in rows["actor_type"].to_list()
        assert "mandatory" not in rows["discretion"].to_list()
        assert "unknown" not in rows["discretion"].to_list()
    pretrial = frame.decisions.filter(pl.col("decision_type") == "pretrial_release")
    assert judicial + statutory + unknown == pretrial.height, seed


@settings(derandomize=True)
@given(seed=seeds)
def test_pretrial_release_windows_equal_the_truth_on_the_same_world(seed: int) -> None:
    world, frame = _world_and_frame(seed)
    end = frame.coverage_end_exclusive_at
    timelines = build_timelines(world)
    for subject in _subjects(world):
        expected = (
            judge_metrics(world, timelines, subject.subject_id)
            if subject.subject_type == "judge"
            else court_metrics(world, timelines, subject.subject_id)
        )["pretrial"]
        cohort = _cohort(frame, PRETRIAL_RELEASE, subject)
        assert cohort.height == expected["released_count"], (seed, subject)
        decisions = attributed_decisions(frame, PRETRIAL_RULE, subject)
        assert decisions.height == expected["decisions"], (seed, subject)
        assert decisions.filter(pl.col("detained_flag")).height == expected["detained_count"]
        for outcome in TRUTH_OUTCOMES:
            firsts = first_outcomes(frame, cohort, outcome)
            for rate in fixed_window_rates(firsts, end):
                window = expected["windows"][str(rate.window_days)]
                assert rate.eligible == window["cohort"], (seed, subject, outcome, rate)
                assert rate.followed == window["followed"], (seed, subject, outcome, rate)
                truth_rate = window[f"{outcome}_rate"]
                assert rate.numerator == truth_rate["numerator"], (seed, subject, outcome, rate)
                assert rate.followed == truth_rate["denominator"]
                assert rate.value == truth_rate["value"], (seed, subject, outcome, rate)
        if subject.subject_type == "court":
            assert (
                statutory_releases(frame, subject.subject_id).height
                == (expected["statutory_release_count"])
            )
            assert (
                unknown_actor_pretrial_decisions(frame, subject.subject_id).height
                == (expected["unknown_actor_count"])
            )


def test_every_outcome_type_is_classified_once() -> None:
    assert OTHER_CASE_OUTCOMES.isdisjoint(ANY_CASE_OUTCOMES)
    assert SYNTHETIC_OBSERVABLE <= OTHER_CASE_OUTCOMES | ANY_CASE_OUTCOMES
