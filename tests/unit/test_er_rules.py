# tests/unit/test_er_rules.py
"""The stages: each rule and each negative, the stub scorer, and the pipeline order."""

from __future__ import annotations

from typing import Any

import pytest

from judgemetrics.db.models.enums import ResolutionDecision
from judgemetrics.entity_resolution import deterministic, rules, scoring
from judgemetrics.entity_resolution.config import (
    STAGE_DETERMINISTIC,
    STAGE_PROBABILISTIC,
    STAGE_REVIEW,
    STAGE_RULE,
    Thresholds,
)
from judgemetrics.entity_resolution.features import PairFeatures
from judgemetrics.entity_resolution.pipeline import (
    REASON_AMBIGUOUS,
    SCORE_AMBIGUOUS,
    TRACE_NO_DECISION,
    TRACE_NO_SIGNAL,
    evaluate,
)
from judgemetrics.entity_resolution.scoring import TRACE_SKIPPED, StubScorer

pytestmark = pytest.mark.unit


def _features(**overrides: Any) -> PairFeatures:
    values: dict[str, Any] = {
        "same_source_id": False,
        "same_name": True,
        "same_dob": True,
        "dob_missing_either": False,
        "same_name_dob": True,
        "shared_case": False,
        "related_case_link": False,
        "same_court": False,
        "filing_gap_days": 100,
        "age_consistent": True,
    }
    values.update(overrides)
    return PairFeatures(**values)


class FixedScorer:
    def __init__(self, value: float | None) -> None:
        self.value = value

    def score(self, features: PairFeatures) -> float | None:
        del features
        return self.value


# --- deterministic ------------------------------------------------------------------------


def test_deterministic_matches_on_a_shared_stable_identifier() -> None:
    result = deterministic.decide(_features(same_source_id=True, same_name=False))
    assert result is not None
    assert (result.decision, result.score, result.stage) == (
        ResolutionDecision.MATCHED,
        1.0,
        STAGE_DETERMINISTIC,
    )
    assert deterministic.decide(_features()) is None


# --- rules ---------------------------------------------------------------------------------


def test_name_dob_with_a_shared_case_or_link_matches() -> None:
    for linkage in ({"shared_case": True}, {"related_case_link": True}):
        result = rules.decide(_features(**linkage))
        assert result is not None
        assert result.decision is ResolutionDecision.MATCHED
        assert result.score == 0.98 and result.stage == STAGE_RULE
        assert result.reason == rules.REASON_NAME_DOB_CASE_LINK


def test_name_dob_same_court_queues_for_review_below_auto_match() -> None:
    result = rules.decide(_features(same_court=True))
    assert result is not None
    assert result.decision is ResolutionDecision.REVIEW
    assert result.score == 0.70 < Thresholds().auto_match
    assert result.reason == rules.REASON_NAME_DOB_SAME_COURT


def test_name_only_never_matches() -> None:
    result = rules.decide(
        _features(same_dob=False, dob_missing_either=True, same_name_dob=False, age_consistent=None)
    )
    assert result is not None
    assert result.decision is ResolutionDecision.REJECTED
    assert result.score == 0.10 and result.reason == rules.REASON_NAME_ONLY
    # Even with every linkage signal present, a missing date of birth is name-only.
    linked = rules.decide(
        _features(
            same_dob=False,
            dob_missing_either=True,
            same_name_dob=False,
            age_consistent=None,
            shared_case=True,
            related_case_link=True,
            same_court=True,
        )
    )
    assert linked is not None and linked.decision is ResolutionDecision.REJECTED


def test_differing_dob_rejects() -> None:
    result = rules.decide(_features(same_dob=False, same_name_dob=False, age_consistent=False))
    assert result is not None
    assert result.decision is ResolutionDecision.REJECTED
    assert result.score == 0.02 and result.reason == rules.REASON_DOB_DIFFERS


def test_name_dob_without_linkage_or_court_is_no_rule_decision() -> None:
    assert rules.decide(_features()) is None
    assert rules.decide(_features(same_name=False, same_name_dob=False, same_dob=False)) is None


# --- scoring ---------------------------------------------------------------------------------


def test_stub_scorer_declines_and_thresholds_decide_real_scores() -> None:
    thresholds = Thresholds(auto_match=0.95, auto_reject=0.20)
    assert StubScorer().score(_features()) is None
    assert scoring.decide(_features(), StubScorer(), thresholds) is None
    matched = scoring.decide(_features(), FixedScorer(0.95), thresholds)
    assert matched is not None and matched.decision is ResolutionDecision.MATCHED
    assert matched.stage == STAGE_PROBABILISTIC and matched.score == 0.95
    rejected = scoring.decide(_features(), FixedScorer(0.19), thresholds)
    assert rejected is not None and rejected.decision is ResolutionDecision.REJECTED
    review = scoring.decide(_features(), FixedScorer(0.20), thresholds)
    assert review is not None and review.decision is ResolutionDecision.REVIEW
    with pytest.raises(ValueError, match="not a probability"):
        scoring.decide(_features(), FixedScorer(1.5), thresholds)


# --- the pipeline ---------------------------------------------------------------------------


def test_pipeline_stops_at_the_first_decisive_stage_and_records_the_trace() -> None:
    outcome = evaluate(_features(same_source_id=True, related_case_link=True))
    assert outcome.decision is ResolutionDecision.MATCHED
    assert outcome.stage == STAGE_DETERMINISTIC
    assert outcome.trace == {STAGE_DETERMINISTIC: "matched:same_source_id"}

    outcome = evaluate(_features(related_case_link=True))
    assert outcome.stage == STAGE_RULE and outcome.score == 0.98
    assert outcome.trace == {
        STAGE_DETERMINISTIC: TRACE_NO_SIGNAL,
        STAGE_RULE: "matched:name_dob_case_link",
    }


def test_pipeline_records_the_stub_scorer_as_skipped_and_defaults_to_review() -> None:
    outcome = evaluate(_features())
    assert outcome.decision is ResolutionDecision.REVIEW
    assert outcome.stage == STAGE_REVIEW
    assert outcome.score == SCORE_AMBIGUOUS and outcome.reason == REASON_AMBIGUOUS
    assert outcome.trace == {
        STAGE_DETERMINISTIC: TRACE_NO_SIGNAL,
        STAGE_RULE: TRACE_NO_DECISION,
        STAGE_PROBABILISTIC: TRACE_SKIPPED,
    }
    payload = outcome.features_payload(_features())
    assert payload["stage_trace"][STAGE_PROBABILISTIC] == TRACE_SKIPPED


def test_pipeline_keeps_a_rule_review_over_a_scorer_review_and_lets_a_scorer_decide() -> None:
    rule_review = evaluate(_features(same_court=True), scorer=FixedScorer(0.5))
    assert rule_review.decision is ResolutionDecision.REVIEW
    assert rule_review.stage == STAGE_RULE and rule_review.score == 0.70
    assert rule_review.trace[STAGE_PROBABILISTIC] == "review:score_between_thresholds"

    scored = evaluate(_features(), scorer=FixedScorer(0.99))
    assert scored.decision is ResolutionDecision.MATCHED and scored.stage == STAGE_PROBABILISTIC
    rejected = evaluate(_features(), scorer=FixedScorer(0.01))
    assert rejected.decision is ResolutionDecision.REJECTED and rejected.score == 0.01
