# tests/property/test_cook_sao_matchers.py
"""Every Cook County matcher is total and deterministic and returns vocabulary values.

Over arbitrary strings — blanks, the profile's own values, near-misses, and
noise — each matcher of ``judgemetrics.ingest.cook_sao.rules`` returns
without raising, returns the same result for the same input, and every
canonical value it returns is a value of case vocabulary 3 (or ``None``
where the matcher documents it: no value recorded, or a value the source
never wrote, which the connector rejects).
"""

from __future__ import annotations

from datetime import date

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from judgemetrics.ingest.cook_sao.rules import (
    AMBIGUOUS,
    RESOLVED,
    TABLES_DIR,
    UNRESOLVED,
    load_rules,
    restricted_category,
)
from judgemetrics.normalization import vocabulary

pytestmark = pytest.mark.property

RULES = load_rules()
_PROFILE = yaml.safe_load((TABLES_DIR / "profile.yaml").read_text(encoding="utf-8"))


def _profiled() -> list[str]:
    values: set[str] = set()
    for dataset in _PROFILE["datasets"].values():
        for entry in dataset["columns"].values():
            for item in entry.get("values", ()):
                values.add(str(item[0]) if isinstance(item, list) else str(item))
    return sorted(values)


# Arbitrary text, blanks, and the source's own values (so matches are exercised too).
texts = st.one_of(
    st.none(),
    st.text(max_size=40),
    st.sampled_from(["", " ", "\t", "*", "null"]),
    st.sampled_from(_profiled()),
)
dates = st.one_of(st.none(), st.dates(min_value=date(1900, 1, 1), max_value=date(2999, 12, 31)))


def _known(kind: str, value: str | None, *, nullable: bool = True) -> bool:
    return (nullable and value is None) or (value is not None and vocabulary.is_known(kind, value))


@given(texts, texts)
def test_the_disposition_matcher_is_total(disposition: str | None, reason: str | None) -> None:
    rule = RULES.disposition(disposition, reason)
    assert rule == RULES.disposition(disposition, reason)
    assert _known("charge_disposition", rule.disposition, nullable=False)
    assert rule.final == vocabulary.is_known("final_charge_disposition", rule.disposition)
    assert _known("actor_type", rule.actor_type, nullable=False)
    assert _known(
        "judicial_discretion_classification",
        rule.judicial_discretion_classification,
        nullable=False,
    )
    assert _known("judicial_ruling", rule.judicial_ruling)
    assert _known("event_type", rule.event_type)


@given(texts, texts, texts, texts)
def test_the_review_diversion_and_event_matchers_are_total(
    result: str | None, program: str | None, outcome: str | None, event: str | None
) -> None:
    review = RULES.felony_review(result)
    assert review == RULES.felony_review(result)
    if review is not None:
        assert _known("charging_outcome", review.outcome)
        assert _known("actor_type", review.actor_type, nullable=False)
    referral = RULES.diversion_program(program)
    assert referral == RULES.diversion_program(program)
    assert _known("diversion_stage", referral.stage)
    assert _known("actor_type", referral.actor_type, nullable=False)
    closed = RULES.diversion_result(outcome)
    assert closed == RULES.diversion_result(outcome) and _known("event_type", closed.event_type)
    charging = RULES.initiation_event(event)
    assert charging == RULES.initiation_event(event)
    assert charging is None or _known("event_type", charging.event_type)
    finding = RULES.no_probable_cause(event)
    assert finding is None or _known("judicial_ruling", finding.judicial_ruling, nullable=False)


@given(texts, dates, texts)
def test_the_pretrial_matcher_is_total(
    bond_type: str | None, bond_date: date | None, flag: str | None
) -> None:
    match = RULES.pretrial_rule(bond_type, bond_date)
    assert match == RULES.pretrial_rule(bond_type, bond_date)
    assert (match.rule is None) != (match.reason is None)
    if match.rule is not None:
        assert _known("release_type", match.rule.release_type, nullable=False)
        assert _known("actor_type", match.rule.actor_type, nullable=False)
        assert not (match.rule.releases and match.rule.release_type == "monetary_bond")
    assert _known("release_condition", RULES.electronic_monitoring(flag))


@given(texts, texts, texts, texts, texts)
def test_the_sentence_matcher_is_total(
    phase: str | None,
    sentence_type: str | None,
    commitment_type: str | None,
    term: str | None,
    unit: str | None,
) -> None:
    row = RULES.sentence_row(phase, sentence_type, commitment_type, term, unit)
    assert row == RULES.sentence_row(phase, sentence_type, commitment_type, term, unit)
    assert _known("sentence_phase", row.phase)
    assert all(_known("sentence_component", c, nullable=False) for c in row.components)
    assert all(_known("sentence_term_flag", f, nullable=False) for f in row.flags)
    assert row.days is None or 0 <= row.days <= RULES.sentence.maximum_days
    converted = RULES.term_days(term, unit)
    assert (converted.days is None) != (converted.flag is None)
    assert _known("sentence_term_flag", converted.flag)


@given(texts, texts, texts)
def test_the_offense_court_judge_and_restricted_matchers_are_total(
    value: str | None, other: str | None, label: str | None
) -> None:
    assert _known("offense_category", RULES.offense_category(value))
    assert _known("severity", RULES.severity(value))
    court = RULES.court_of_row(value, other)
    assert court == RULES.court_of_row(value, other)
    assert court is None or court.court_key in RULES.courts.courts
    judge = RULES.judge(value)
    assert judge == RULES.judge(value)
    if judge is not None:
        assert judge.status in (RESOLVED, AMBIGUOUS, UNRESOLVED)
        assert (judge.judge_key is not None) == (judge.status == RESOLVED)
        assert judge.judge_key is None or judge.judge_key in RULES.judges.judges
    for kind in ("race", "gender"):
        assert _known(kind, restricted_category(kind, label))
