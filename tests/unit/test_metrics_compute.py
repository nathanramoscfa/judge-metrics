# tests/unit/test_metrics_compute.py
"""The compute dispatch over an in-memory world equals the truth, without a database.

``compute_frame`` over ``frame_from_world`` (the golden world, seed 7)
reproduces every number of ``synthetic/truth.py`` through the same
truth-path table the golden suite uses (``tests/golden/truth_map.py``):
counts, shares, every fixed-window rate and Kaplan-Meier estimate of
every index kind, the distribution, and the medians — the two
implementations share no code beyond the standard library, so equality
is evidence for both. Also: suppression follows the registry thresholds,
not-observable outcomes yield records and never a zero, the lead
convicted charge is chosen by severity then the source's charge id,
``--subject`` parsing, and members name the population rows with the
right kinds and flags.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import polars as pl
import pytest

from judgemetrics.metrics.attribution import Subject
from judgemetrics.metrics.compute import (
    ComputeError,
    NotObservableRecord,
    ObservationDraft,
    compute_frame,
    compute_metric,
    lead_categories,
    parse_subject,
    subjects_of,
)
from judgemetrics.metrics.registry import load_registry
from judgemetrics.metrics.suppression import apply, is_suppressed
from judgemetrics.synthetic.config import GOLDEN
from judgemetrics.synthetic.truth import build_timelines, compute_metrics
from tests.golden.truth_map import NOT_OBSERVABLE_SLUGS, expectations, subject_blocks
from tests.property.support import build_world, frame_from_world

pytestmark = pytest.mark.unit

GOLDEN_SEED = 7
REGISTRY = load_registry()
SOURCE = "synthetic"
COLUMNS = {
    "observed_count": lambda d: d.observed_count,
    "cohort_size": lambda d: d.cohort_size,
    "eligible_count": lambda d: d.eligible_count,
    "observed_rate": lambda d: d.observed_rate,
    "value": lambda d: d.value,
    "distribution": lambda d: d.distribution,
    "lower_confidence_bound": lambda d: d.lower,
    "upper_confidence_bound": lambda d: d.upper,
}


@pytest.fixture(scope="module")
def golden() -> tuple[Any, Any, dict[str, Any]]:
    world = build_world(GOLDEN_SEED, GOLDEN)
    frame = frame_from_world(world, GOLDEN)
    truth = compute_metrics(world, build_timelines(world))
    return world, frame, truth


@pytest.fixture(scope="module")
def drafts(golden: tuple[Any, Any, dict[str, Any]]) -> dict[tuple[Any, ...], ObservationDraft]:
    _, frame, _ = golden
    result = compute_frame(frame, REGISTRY, SOURCE)
    assert result.sources_skipped == []
    return {
        (d.subject_type, d.subject_id, d.slug, d.window_days, d.dimension_value): d
        for d in result.drafts
    }


def test_every_truth_number_is_reproduced_on_the_golden_world(
    golden: tuple[Any, Any, dict[str, Any]], drafts: dict[tuple[Any, ...], ObservationDraft]
) -> None:
    _, _, truth = golden
    checked = 0
    for subject_type, code, block in subject_blocks(truth):
        for item in expectations(block, subject_type):
            draft = drafts.get(
                (subject_type, code, item.slug, item.window_days, item.dimension_value)
            )
            assert draft is not None, f"{code}: no draft for {item.label}"
            for column, expected in item.columns.items():
                actual = COLUMNS[column](draft)
                assert actual == expected, f"{code} {item.label} {column}: {actual} != {expected}"
                checked += 1
    assert checked > 4000


def test_subjects_are_every_judge_with_a_row_and_every_court_with_a_case(
    golden: tuple[Any, Any, dict[str, Any]],
) -> None:
    world, frame, truth = golden
    subjects = subjects_of(frame)
    assert {s.subject_id for s in subjects if s.subject_type == "judge"} == set(truth["judges"])
    assert {s.subject_id for s in subjects if s.subject_type == "court"} == set(truth["courts"])


def test_not_observable_outcomes_yield_records_and_never_a_zero(
    golden: tuple[Any, Any, dict[str, Any]],
) -> None:
    _, frame, truth = golden
    result = compute_frame(frame, REGISTRY, SOURCE)
    reported = {(r.subject_type, r.subject_id, r.slug, r.outcome) for r in result.not_observable}
    subjects = subjects_of(frame)
    assert reported == {
        (s.subject_type, s.subject_id, slug, outcome)
        for s in subjects
        for slug, outcome in NOT_OBSERVABLE_SLUGS.items()
    }
    assert not {d.slug for d in result.drafts} & set(NOT_OBSERVABLE_SLUGS)
    assert {r["outcome"] for r in truth["not_observable"]} == set(NOT_OBSERVABLE_SLUGS.values())
    for record in result.not_observable:
        assert isinstance(record, NotObservableRecord)
        assert "does not document" in record.reason


def test_suppression_follows_the_registry_thresholds(
    drafts: dict[tuple[Any, ...], ObservationDraft],
) -> None:
    for draft in drafts.values():
        definition = REGISTRY[draft.slug]
        assert draft.suppressed_flag == is_suppressed(
            draft.cohort_size, definition.suppression_threshold
        )
        if definition.kind in ("count", "distribution"):
            assert not draft.suppressed_flag
    some = next(d for d in drafts.values() if d.slug == "failure_to_appear_rate")
    forced = replace(some, cohort_size=REGISTRY[some.slug].suppression_threshold - 1)
    assert apply(forced, REGISTRY[some.slug]).suppressed_flag
    enough = replace(some, cohort_size=REGISTRY[some.slug].suppression_threshold)
    assert not apply(enough, REGISTRY[some.slug]).suppressed_flag
    with pytest.raises(ValueError, match="does not belong"):
        apply(some, REGISTRY["eligible_cases"])


def test_members_name_population_rows_with_kinds_and_flags(
    golden: tuple[Any, Any, dict[str, Any]], drafts: dict[tuple[Any, ...], ObservationDraft]
) -> None:
    world, frame, truth = golden
    judge = next(iter(truth["judges"]))
    cases = drafts[("judge", judge, "eligible_cases", None, None)]
    assert cases.observed_count == cases.cohort_size == len(cases.members)
    assert {m.kind for m in cases.members} == {"court_case"}
    assert all(m.counted and m.followed for m in cases.members)
    defendants = drafts[("judge", judge, "eligible_defendants", None, None)]
    assert {m.kind for m in defendants.members} == {"court_case"}  # never a person id
    share = drafts[("judge", judge, "pretrial_release_share", None, None)]
    assert {m.kind for m in share.members} == {"decision"}
    assert sum(m.counted for m in share.members) == share.observed_count
    assert len(share.members) == share.cohort_size
    rate = drafts[("judge", judge, "new_case_rate", 365, None)]
    assert {m.kind for m in rate.members} == {"decision"}
    assert sum(m.followed for m in rate.members) == rate.cohort_size
    assert sum(m.counted for m in rate.members) == rate.observed_count
    assert len(rate.members) == rate.eligible_count
    survival = drafts[("judge", judge, "new_case_survival", 365, None)]
    assert all(m.followed for m in survival.members)
    assert sum(m.counted for m in survival.members) == survival.observed_count
    after = drafts[("judge", judge, "new_case_rate_after_disposition", 365, None)]
    assert {m.kind for m in after.members} <= {"court_case"}
    sentence = drafts[("judge", judge, "new_case_rate_after_sentence", 365, None)]
    assert {m.kind for m in sentence.members} <= {"sentence"}
    median = drafts[("judge", judge, "incarceration_days_median", None, None)]
    assert {m.kind for m in median.members} <= {"sentence"}
    assert sum(m.followed for m in median.members) == median.cohort_size
    dismissal = drafts[("judge", judge, "judicial_dismissal_rate", None, None)]
    assert {m.kind for m in dismissal.members} <= {"charge"}
    for draft in drafts.values():
        assert draft.period_start == GOLDEN.corpus_start
        assert draft.period_end == GOLDEN.corpus_end
        assert draft.source_id == SOURCE
        assert draft.version == REGISTRY[draft.slug].version


def test_a_court_only_metric_is_refused_for_a_judge(
    golden: tuple[Any, Any, dict[str, Any]],
) -> None:
    _, frame, truth = golden
    judge = next(iter(truth["judges"]))
    with pytest.raises(ComputeError, match="not defined for a judge"):
        compute_metric(frame, REGISTRY["statutory_release_count"], Subject("judge", judge), SOURCE)


def test_lead_convicted_charge_breaks_severity_ties_by_the_source_charge_id(
    golden: tuple[Any, Any, dict[str, Any]],
) -> None:
    _, frame, _ = golden
    charges = pl.DataFrame(
        {
            "id": ["z", "y", "x", "w"],
            "case_id": ["C1", "C1", "C1", "C2"],
            "person_id": ["P1", "P1", "P1", "P2"],
            "filed_at": [frame.charges["filed_at"][0]] * 4,
            "disposed_at": [frame.charges["filed_at"][0]] * 4,
            "disposition": ["convicted_plea", "convicted_verdict", "dismissed", "convicted_plea"],
            "disposition_actor": ["judge"] * 4,
            "offense_category": ["drug", "property", "violent", "weapons"],
            "severity": ["felony_2", "felony_2", "felony_1", "misdemeanor_a"],
            "source_row_id": ["CH-000002", "CH-000001", "CH-000003", "CH-000004"],
        },
        schema=frame.charges.schema,
    )
    tied = frame.replace(charges=charges)
    leads = dict(lead_categories(tied).iter_rows())
    # The dismissed felony_1 is not convicted; the two felony_2 tie and CH-000001 wins.
    assert leads == {"C1": "property", "C2": "weapons"}


def test_parse_subject_accepts_judge_and_court_only() -> None:
    assert parse_subject("judge:abc") == Subject("judge", "abc")
    assert parse_subject("court:abc") == Subject("court", "abc")
    for text in ("abc", "person:abc", "judge:", ":abc", "jurisdiction:x"):
        with pytest.raises(ComputeError, match="judge:<uuid> or court:<uuid>"):
            parse_subject(text)


def test_compute_frame_filters_to_the_requested_subjects(
    golden: tuple[Any, Any, dict[str, Any]],
) -> None:
    _, frame, truth = golden
    judge = next(iter(truth["judges"]))
    result = compute_frame(
        frame, REGISTRY, SOURCE, [Subject("judge", judge), Subject("court", "?")]
    )
    assert result.subjects == [Subject("judge", judge)]
    assert {d.subject_id for d in result.drafts} == {judge}
