# src/judgemetrics/synthetic/vocabulary.py
"""The case-level vocabulary the synthetic source files use.

These are the values Phase 2 Step 2 fixes in
``data/reference/case_vocabulary.yaml`` (``version: 2`` since Phase 4 Step 1
added the restricted vocabularies, ``version: 3`` since Phase 5 Step 3 added
the values the Cook County rule tables use); that file must equal these
constants (Step 2's unit test), and Phase 5's real connectors map onto the
same vocabulary. ``actor_type`` repeats the brief's
``ActorType`` enum values verbatim (``judgemetrics.db.models.enums``); a
unit test asserts the two agree so this package stays independent of the
database layer.

The generator draws, ranks, and codes only the values the synthetic world
was built with (``SYNTHETIC_SEVERITIES`` and the synthetic offense table), so
a value added for a real source moves no draw: the golden fixture and the
demo seed are byte-identical across vocabulary versions 2 and 3.
"""

from __future__ import annotations

CASE_VOCABULARY_VERSION = 3

CASE_TYPES: tuple[str, ...] = ("felony", "misdemeanor")
CASE_STATUSES: tuple[str, ...] = ("open", "closed")
PARTY_TYPES: tuple[str, ...] = ("defendant",)
ASSIGNMENT_TYPES: tuple[str, ...] = ("initial", "reassignment")
EVENT_TYPES: tuple[str, ...] = (
    "arraignment",
    "hearing",
    "failure_to_appear",
    "bench_warrant",
    "trial",
    "plea_hearing",
    "sentencing_hearing",
    "revocation",
    # Version 3: the court events of the Cook County source's timelines.
    "preliminary_hearing",
    "indictment",
    "mistrial",
    "transfer",
    "appeal",
    "diversion_completed",
    "diversion_failed",
)
DECISION_TYPES: tuple[str, ...] = (
    "pretrial_release",
    "dismissal",
    "disposition",
    "sentencing",
    # Version 3: the prosecutor's charging (felony review) and diversion decisions.
    "charging",
    "diversion",
)
JUDICIAL_DISCRETION_CLASSIFICATIONS: tuple[str, ...] = (
    "discretionary",
    "mandatory",
    "non_judicial",
    "unknown",
)
RELEASE_TYPES: tuple[str, ...] = ("recognizance", "monetary_bond", "detained", "statutory")
# The dispositions that end a charge on its merits: the only ones the engine
# counts as disposed (the disposition distribution lists these alone).
FINAL_CHARGE_DISPOSITIONS: tuple[str, ...] = (
    "dismissed",
    "acquitted",
    "convicted_plea",
    "convicted_verdict",
)
CHARGE_DISPOSITIONS: tuple[str, ...] = (
    *FINAL_CHARGE_DISPOSITIONS,
    "pending",
    # Version 3: a charge that left the case without an outcome on its merits.
    "superseded",
    "transferred",
)
# Most severe first (index 0): version 3 adds the Illinois classes the Cook
# County source records around the synthetic five, which keep their order.
SEVERITIES: tuple[str, ...] = (
    "felony_m",
    "felony_x",
    "felony_1",
    "felony_2",
    "felony_3",
    "felony_4",
    "misdemeanor_a",
    "misdemeanor_b",
    "misdemeanor_c",
    "petty_offense",
    "unclassified",
)
# The severities the synthetic offense table uses, in the vocabulary's order.
SYNTHETIC_SEVERITIES: tuple[str, ...] = (
    "felony_1",
    "felony_2",
    "felony_3",
    "misdemeanor_a",
    "misdemeanor_b",
)
OFFENSE_CATEGORIES: tuple[str, ...] = (
    "drug",
    "property",
    "person",
    "weapon",
    "public_order",
    "traffic",
    "financial",
    # Version 3: the source's own catch-all, and a case it never categorized.
    "other",
    "unclassified",
)
JUSTICE_EVENT_TYPES: tuple[str, ...] = (
    "new_case",
    "new_charge",
    "reconviction",
    "failure_to_appear",
    "release_violation",
    "revocation",
    "rearrest",
)
# The brief's actor types, verbatim (event_attribution_model).
ACTOR_TYPES: tuple[str, ...] = (
    "judge",
    "prosecutor",
    "defense",
    "jury",
    "clerk",
    "law_enforcement",
    "legislature_or_mandatory_rule",
    "appellate_court",
    "unknown",
)
# Version 3: ``unstated`` is the position of a judge whose source names no rank.
POSITIONS: tuple[str, ...] = ("circuit_judge", "associate_judge", "unstated")
SENTENCE_COMPONENTS: tuple[str, ...] = (
    "incarceration",
    "probation",
    "fine",
    "conditional_discharge",
    "supervision",
    "death",
    "treatment",
    "program",
    "home_detention",
)
SENTENCE_PHASES: tuple[str, ...] = (
    "original",
    "probation_violation",
    "amended",
    "resentenced",
    "remanded",
)
SENTENCE_TERM_FLAGS: tuple[str, ...] = (
    "life",
    "death",
    "term_unstated",
    "unit_not_a_term",
    "unparseable_term",
    "missing_term",
    "implausible_term",
)
RELEASE_CONDITIONS: tuple[str, ...] = (
    "check_in",
    "no_contact",
    "travel_restriction",
    "drug_testing",
    "electronic_monitoring",
)
CHARGING_OUTCOMES: tuple[str, ...] = ("approved", "rejected", "continued")
DIVERSION_STAGES: tuple[str, ...] = ("pre_plea", "post_plea")
JUDICIAL_RULINGS: tuple[str, ...] = (
    "suppression_granted",
    "no_probable_cause",
    "conviction_vacated",
    "warrant_quashed",
)

# The restricted vocabularies (version 2, Phase 4 Step 1): attributes that live
# only in the database's ``restricted`` schema, are never a model feature, and
# are read only by the aggregate fairness analysis (docs/DATA_MODEL.md).
# Version 3 adds the Cook County source's race and gender, the source's own
# labels normalized but not recoded, ``unknown`` naming a blank (or "Unknown").
RESTRICTED_ATTRIBUTES: tuple[str, ...] = ("age_band", "synthetic_group", "race", "gender")
AGE_BAND_VALUES: tuple[str, ...] = ("18-24", "25-34", "35-44", "45-54", "55+", "unknown")
SYNTHETIC_GROUPS: tuple[str, ...] = ("group_a", "group_b", "group_c")
RACE_VALUES: tuple[str, ...] = (
    "albino",
    "american_indian",
    "asian",
    "biracial",
    "black",
    "caucasian",
    "hispanic",
    "latinx",
    "middle_eastern_north_african",
    "native_hawaiian_or_other_pacific_islander",
    "other",
    "white",
    "white_black_hispanic_or_latino",
    "white_hispanic_or_latino",
    "unknown",
)
GENDER_VALUES: tuple[str, ...] = (
    "female",
    "male",
    "male_name_no_gender_given",
    "unknown_gender",
    "unknown",
)
UNKNOWN_AGE_BAND = "unknown"
# The youngest age (whole years at filing) of each band; below the first
# floor, or without an age, the band is ``unknown``.
AGE_BAND_FLOORS: tuple[tuple[str, int], ...] = (
    ("55+", 55),
    ("45-54", 45),
    ("35-44", 35),
    ("25-34", 25),
    ("18-24", 18),
)


def age_band_of(age: int | None) -> str:
    """The ``age_band`` of an age in whole years at filing (``unknown`` without one)."""
    if age is None:
        return UNKNOWN_AGE_BAND
    for band, floor in AGE_BAND_FLOORS:
        if age >= floor:
            return band
    return UNKNOWN_AGE_BAND


# Every vocabulary kind by the name the YAML file will use.
VOCABULARY: dict[str, tuple[str, ...]] = {
    "case_type": CASE_TYPES,
    "case_status": CASE_STATUSES,
    "party_type": PARTY_TYPES,
    "assignment_type": ASSIGNMENT_TYPES,
    "event_type": EVENT_TYPES,
    "decision_type": DECISION_TYPES,
    "judicial_discretion_classification": JUDICIAL_DISCRETION_CLASSIFICATIONS,
    "release_type": RELEASE_TYPES,
    "charge_disposition": CHARGE_DISPOSITIONS,
    "final_charge_disposition": FINAL_CHARGE_DISPOSITIONS,
    "severity": SEVERITIES,
    "offense_category": OFFENSE_CATEGORIES,
    "justice_event_type": JUSTICE_EVENT_TYPES,
    "actor_type": ACTOR_TYPES,
    "position": POSITIONS,
    "sentence_component": SENTENCE_COMPONENTS,
    "sentence_phase": SENTENCE_PHASES,
    "sentence_term_flag": SENTENCE_TERM_FLAGS,
    "release_condition": RELEASE_CONDITIONS,
    "charging_outcome": CHARGING_OUTCOMES,
    "diversion_stage": DIVERSION_STAGES,
    "judicial_ruling": JUDICIAL_RULINGS,
    "restricted_attribute": RESTRICTED_ATTRIBUTES,
    "age_band": AGE_BAND_VALUES,
    "synthetic_group": SYNTHETIC_GROUPS,
    "race": RACE_VALUES,
    "gender": GENDER_VALUES,
}

# Severity rank for choosing a case's lead charge (lower is more severe), over
# the synthetic severities alone: the generator's bond schedule and risk code
# read the rank, so the real-source classes must not shift it.
SEVERITY_RANK: dict[str, int] = {
    severity: rank for rank, severity in enumerate(SYNTHETIC_SEVERITIES)
}
FELONY_SEVERITIES: tuple[str, ...] = tuple(
    s for s in SYNTHETIC_SEVERITIES if s.startswith("felony")
)
MISDEMEANOR_SEVERITIES: tuple[str, ...] = tuple(
    s for s in SYNTHETIC_SEVERITIES if s.startswith("misdemeanor")
)
