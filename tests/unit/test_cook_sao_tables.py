# tests/unit/test_cook_sao_tables.py
"""Every bond, sentence, offense, court, and restricted value of the Cook County profile maps.

The pretrial rules cover every bond type under both regimes and never claim a
release for a deposit or cash bond; the sentence rules cover every phase,
sentence type, commitment type, and unit, and convert a term to days exactly
as ``sentence_rules.yaml`` states; the offense map covers every category and
class with no catch-all; the court table covers every court name and
courthouse; and every race and gender label normalizes onto vocabulary 3
without being recoded.
"""

from __future__ import annotations

from datetime import date

import pytest
import yaml

from judgemetrics.ingest.cook_sao.rules import (
    IMPLAUSIBLE_TERM,
    MISSING_TERM,
    MONETARY_BAIL,
    NO_BOND_DATE,
    NO_BOND_TYPE,
    PRETRIAL_FAIRNESS_ACT,
    TABLES_DIR,
    UNLISTED_BOND_TYPE,
    UNPARSEABLE_TERM,
    load_rules,
    restricted_category,
)
from judgemetrics.normalization import vocabulary

pytestmark = pytest.mark.unit

PROFILE = yaml.safe_load((TABLES_DIR / "profile.yaml").read_text(encoding="utf-8"))
DATASETS = PROFILE["datasets"]
RULES = load_rules()
BEFORE = date(2023, 9, 17)
FROM = date(2023, 9, 18)


def _values(*columns: str) -> set[str]:
    found: set[str] = set()
    for dataset in DATASETS.values():
        for column in columns:
            entry = dataset["columns"].get(column)
            if entry and "values" in entry:
                found.update(
                    str(item[0]) if isinstance(item, list) else str(item)
                    for item in entry["values"]
                )
    return found


# --- pretrial ------------------------------------------------------------------------------


def test_every_bond_type_maps_under_both_regimes() -> None:
    bond_types = _values("BOND_TYPE_INITIAL", "BOND_TYPE_CURRENT")
    assert bond_types == {"D Bond", "I Bond", "C Bond", "No Bond"}
    for bond_type in bond_types:
        for when, regime in ((BEFORE, MONETARY_BAIL), (FROM, PRETRIAL_FAIRNESS_ACT)):
            match = RULES.pretrial_rule(bond_type, when)
            assert match.rule is not None and match.reason is None, (bond_type, regime)
            assert match.rule.regime == regime == RULES.regime(when)
            assert vocabulary.is_known("release_type", match.rule.release_type)
            assert vocabulary.is_known("actor_type", match.rule.actor_type)


def test_a_null_bond_drafts_no_decision_and_is_counted() -> None:
    assert RULES.pretrial_rule(None, BEFORE).reason == NO_BOND_TYPE
    assert RULES.pretrial_rule("", BEFORE).reason == NO_BOND_TYPE
    assert RULES.pretrial_rule("D Bond", None).reason == NO_BOND_DATE
    assert RULES.pretrial_rule("Q Bond", BEFORE).reason == UNLISTED_BOND_TYPE
    for reason in (NO_BOND_TYPE, NO_BOND_DATE, UNLISTED_BOND_TYPE):
        assert (
            RULES.pretrial_rule(
                *{
                    NO_BOND_TYPE: (None, BEFORE),
                    NO_BOND_DATE: ("I Bond", None),
                    UNLISTED_BOND_TYPE: ("Q Bond", FROM),
                }[reason]
            ).rule
            is None
        )


def test_no_deposit_or_cash_bond_claims_a_release() -> None:
    for (bond_type, regime), rule in RULES.pretrial.bonds.items():
        if rule.release_type == "monetary_bond":
            assert not rule.releases and not rule.detained_flag, (bond_type, regime)
        if rule.releases:
            assert rule.release_type == "recognizance" and bond_type == "I Bond"
        assert rule.detained_flag == (bond_type == "No Bond")
    for bond_type in ("D Bond", "C Bond"):
        for when in (date(2012, 1, 1), BEFORE, FROM, date(2024, 6, 1)):
            monetary = RULES.pretrial_rule(bond_type, when).rule
            assert monetary is not None and not monetary.releases
    # Before the Act a bond court's decision is the judge's; after it, a release
    # absent a detention petition is not settled, and a monetary bond contradicts it.
    expected = {
        ("I Bond", BEFORE): ("judge", "discretionary"),
        ("I Bond", FROM): ("judge", "unknown"),
        ("D Bond", FROM): ("unknown", "unknown"),
        ("No Bond", FROM): ("judge", "discretionary"),
    }
    for (bond_type, when), attribution in expected.items():
        decided = RULES.pretrial_rule(bond_type, when).rule
        assert decided is not None
        assert (decided.actor_type, decided.judicial_discretion_classification) == attribution


def test_the_electronic_monitoring_flag_is_a_release_condition() -> None:
    for column in ("BOND_ELECTRONIC_MONITOR_FLAG_INITIAL", "BOND_ELECTROINIC_MONITOR_FLAG_CURRENT"):
        for value in _values(column):
            assert RULES.electronic_monitoring(value) == "electronic_monitoring"
    assert RULES.electronic_monitoring(None) is None
    assert RULES.electronic_monitoring("false") is None


def test_released_is_defined_for_the_source() -> None:
    document = yaml.safe_load((TABLES_DIR / "pretrial_rules.yaml").read_text(encoding="utf-8"))
    text = " ".join(document["released_means"].split())
    assert "not a release from custody" in text and "release_at" in text
    assert RULES.pretrial.act_effective == FROM


# --- sentences -----------------------------------------------------------------------------


def test_every_sentence_value_of_the_profile_maps() -> None:
    assert _values("SENTENCE_PHASE") == set(RULES.sentence.phases)
    assert _values("SENTENCE_TYPE") == set(RULES.sentence.sentence_types)
    assert _values("COMMITMENT_TYPE") == set(RULES.sentence.commitment_types)
    assert _values("COMMITMENT_UNIT") == set(RULES.sentence.units)
    for phase in RULES.sentence.phases.values():
        assert phase.ignored == (phase.phase is None)
    assert RULES.sentence.phases["Summary Charge Info"].ignored
    violation = RULES.sentence.phases["Probation Violation Sentencing"]
    assert violation.revocation and violation.supersedes_earlier
    assert [name for name, phase in RULES.sentence.phases.items() if phase.revocation] == [
        "Probation Violation Sentencing"
    ]
    for name in ("Amended/Corrected Sentencing", "Resentenced", "Remanded Sentencing"):
        assert RULES.sentence.phases[name].supersedes_earlier, name


@pytest.mark.parametrize(
    ("term", "unit", "days", "flag"),
    [
        ("30", "Days", 30, None),
        ("2", "Weeks", 14, None),
        ("6", "Months", 183, None),  # 182.625 rounds half up
        ("12", "Months", 365, None),  # 365.25
        ("1", "Year(s)", 365, None),  # 365.25
        ("2", "Year(s)", 731, None),  # 730.5 rounds half up
        ("3.5", "Year(s)", 1278, None),  # 1278.375
        ("100", "Year(s)", 36525, None),  # the longest finite term on one count
        ("0", "Year(s)", 0, None),
        ("00", "Days", 0, None),
        ("101", "Year(s)", None, IMPLAUSIBLE_TERM),
        ("7122023", "Months", None, IMPLAUSIBLE_TERM),
        ("1", "Natural Life", None, "life"),
        ("30", "Natural Life", None, "life"),
        ("1", "Term", None, "term_unstated"),
        ("24", "Hours", None, "unit_not_a_term"),
        ("364", "Dollars", None, "unit_not_a_term"),
        ("2", "Pounds", None, "unit_not_a_term"),
        ("18 months", "Months", None, UNPARSEABLE_TERM),
        ("24 wrap", "Months", None, UNPARSEABLE_TERM),
        ("two", "Year(s)", None, UNPARSEABLE_TERM),
        ("2`", "Year(s)", None, UNPARSEABLE_TERM),
        (None, "Days", None, MISSING_TERM),
        ("3", None, None, MISSING_TERM),
        (None, None, None, MISSING_TERM),
    ],
)
def test_the_term_conversion_is_exact(
    term: str | None, unit: str | None, days: int | None, flag: str | None
) -> None:
    converted = RULES.term_days(term, unit)
    assert (converted.days, converted.flag) == (days, flag)


def test_every_unparseable_term_of_the_profile_gets_no_day_count() -> None:
    examples = PROFILE["anomalies"]["sentencing.csv"]["unparseable"]["COMMITMENT_TERM"]["examples"]
    for term, _ in examples:
        for unit in ("Days", "Months", "Year(s)"):
            assert RULES.term_days(str(term), unit).days is None, term


def test_a_sentencing_row_maps_to_its_components() -> None:
    violation = RULES.sentence_row(
        "Probation Violation Sentencing",
        "Prison",
        "Illinois Department of Corrections",
        "3",
        "Year(s)",
    )
    assert violation.matched and violation.phase == "probation_violation" and violation.revocation
    assert violation.components == ("incarceration",) and violation.days == 1096
    # A probation with a jail term as its condition lists both components; the
    # term belongs to the commitment type's.
    split = RULES.sentence_row(
        "Original Sentencing", "Probation", "Cook County Department of Corrections", "30", "Days"
    )
    assert split.components == ("probation", "incarceration")
    assert (split.term_component, split.days) == ("incarceration", 30)
    ended = RULES.sentence_row(
        "Probation Violation Sentencing",
        "Probation Terminated Unsatisfactorily",
        "Probation",
        "2",
        "Year(s)",
    )
    assert ended.terminates_probation == "unsatisfactory"
    assert ended.components == () and ended.days is None
    life = RULES.sentence_row(
        "Original Sentencing", "Prison", "Illinois Department of Corrections", "1", "Natural Life"
    )
    assert life.components == ("incarceration",) and life.days is None and life.flags == ("life",)
    death = RULES.sentence_row("Original Sentencing", "Death", "Death", "0", "Term")
    assert "death" in death.components and set(death.flags) >= {"death", "term_unstated"}
    summary = RULES.sentence_row("Summary Charge Info", "Prison", None, "2", "Year(s)")
    assert summary.matched and summary.ignored and summary.phase is None
    conversion = RULES.sentence_row(
        "Original Sentencing", "Conversion", "Probation", "2", "Year(s)"
    )
    assert conversion.components == ("probation",) and conversion.days == 731
    unlisted = RULES.sentence_row("Original Sentencing", "Flogging", None, "1", "Days")
    assert not unlisted.matched and unlisted.components == ()
    for row in (violation, split, ended, life, death, summary, conversion):
        for component in row.components:
            assert vocabulary.is_known("sentence_component", component)
        for flag in row.flags:
            assert vocabulary.is_known("sentence_term_flag", flag)


# --- offenses ------------------------------------------------------------------------------


def test_every_offense_category_and_class_maps_without_a_catch_all() -> None:
    categories = _values("OFFENSE_CATEGORY", "UPDATED_OFFENSE_CATEGORY", "UPDATE_OFFENSE_CATEGORY")
    assert len(categories) == 88
    for category in categories:
        canonical = RULES.offense_category(category)
        assert canonical is not None and vocabulary.is_known("offense_category", canonical)
    classes = _values("CLASS", "DISPOSITION_CHARGED_CLASS")
    assert classes == {"1", "2", "3", "4", "A", "B", "C", "M", "O", "P", "U", "X", "Z"}
    for value in classes:
        severity = RULES.severity(value)
        assert severity is not None and vocabulary.is_known("severity", severity)
    assert RULES.severity("M") == "felony_m" and RULES.severity("X") == "felony_x"
    assert RULES.severity("4") == "felony_4" and RULES.severity("C") == "misdemeanor_c"
    assert RULES.severity(None) == RULES.severity("") == "unclassified"
    # An unmapped value is an error (None), never a catch-all.
    assert RULES.offense_category("Jaywalking") is None
    assert RULES.offense_category(None) is None
    assert RULES.severity("Q") is None
    # The table lists exactly the profiled values (and the blank class).
    listed = {value for field, value in RULES.offense if field == "offense_category"}
    assert listed == categories
    assert {value for field, value in RULES.offense if field == "class"} == classes | {""}


def test_severities_keep_the_illinois_order() -> None:
    order = vocabulary.values("severity")
    ranked = [RULES.severity(value) for value in ("M", "X", "1", "2", "3", "4", "A", "B", "C")]
    assert [order.index(str(severity)) for severity in ranked] == sorted(
        order.index(str(severity)) for severity in ranked
    )


# --- courts --------------------------------------------------------------------------------


def test_every_court_name_and_facility_maps() -> None:
    courts = RULES.courts
    assert courts.jurisdiction.fips_code == "17031" and courts.jurisdiction.state_code == "IL"
    assert courts.jurisdiction.jurisdiction_type == "county"
    districts = [court for court in courts.courts.values() if court.district is not None]
    assert sorted(court.district for court in districts) == [1, 2, 3, 4, 5, 6]  # type: ignore[type-var]
    assert courts.courts[courts.parent_key].parent is None
    for name in _values("DISPOSITION_COURT_NAME", "SENTENCE_COURT_NAME"):
        match = RULES.court_of_row(name, None)
        assert match is not None, name
        if name.startswith("District "):
            assert courts.courts[match.court_key].district == int(name.split()[1])
        else:
            assert match.court_key == courts.parent_key, name
    for facility in _values("DISPOSITION_COURT_FACILITY", "SENTENCE_COURT_FACILITY"):
        assert facility in courts.facilities, facility
        match = RULES.court_of_row("District 1 - Chicago", facility)
        assert match is not None and match.facility == facility
    for blank in (None, ""):
        match = RULES.court_of_row(blank, blank)
        assert match is not None and match.court_key == courts.parent_key
    assert RULES.court_of_row(None, "Skokie Courthouse").court_key == "cook-district-2"  # type: ignore[union-attr]
    assert RULES.court_of_row(None, "PROMIS").court_key == courts.parent_key  # type: ignore[union-attr]
    assert RULES.court_of_row("District 9 - Nowhere", None) is None


def test_a_case_takes_its_one_district_or_the_parent_court() -> None:
    parent = RULES.courts.parent_key
    assert RULES.case_court(["cook-district-2", "cook-district-2", parent]) == "cook-district-2"
    assert RULES.case_court(["cook-district-1", "cook-district-5"]) == parent
    assert RULES.case_court([]) == parent
    assert RULES.case_court([parent]) == parent


# --- restricted categories -----------------------------------------------------------------


def test_every_race_and_gender_label_normalizes_without_recoding() -> None:
    for kind, column in (("race", "RACE"), ("gender", "GENDER")):
        labels = _values(column)
        assert labels
        mapped = {label: restricted_category(kind, label) for label in labels}
        assert all(value is not None for value in mapped.values()), mapped
        assert set(mapped.values()) <= set(vocabulary.values(kind))
        assert restricted_category(kind, None) == restricted_category(kind, "") == "unknown"
        assert restricted_category(kind, "A label the source never wrote") is None
    # Letter case and punctuation only: distinct source labels stay distinct.
    assert restricted_category("race", "ASIAN") == restricted_category("race", "Asian") == "asian"
    assert restricted_category("race", "White [Hispanic or Latino]") == "white_hispanic_or_latino"
    assert restricted_category("race", "CAUCASIAN") != restricted_category("race", "White")
    assert restricted_category("race", "HISPANIC") != restricted_category("race", "Latinx")
    assert restricted_category("gender", "Unknown Gender") == "unknown_gender"
    assert (
        restricted_category("gender", "Male name, no gender given") == "male_name_no_gender_given"
    )
    with pytest.raises(ValueError, match="not a restricted kind"):
        restricted_category("age_band", "18-24")
