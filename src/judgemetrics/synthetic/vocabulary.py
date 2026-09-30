# src/judgemetrics/synthetic/vocabulary.py
"""The case-level vocabulary the synthetic source files use.

These are the values Phase 2 Step 2 fixes in
``data/reference/case_vocabulary.yaml`` (``version: 2`` since Phase 4 Step 1
added the restricted vocabularies); that file must equal these constants
(Step 2's unit test), and Phase 5's real connectors map onto the same
vocabulary. ``actor_type`` repeats the brief's
``ActorType`` enum values verbatim (``judgemetrics.db.models.enums``); a
unit test asserts the two agree so this package stays independent of the
database layer.
"""

from __future__ import annotations

CASE_VOCABULARY_VERSION = 2

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
)
DECISION_TYPES: tuple[str, ...] = ("pretrial_release", "dismissal", "disposition", "sentencing")
JUDICIAL_DISCRETION_CLASSIFICATIONS: tuple[str, ...] = (
    "discretionary",
    "mandatory",
    "non_judicial",
    "unknown",
)
RELEASE_TYPES: tuple[str, ...] = ("recognizance", "monetary_bond", "detained", "statutory")
CHARGE_DISPOSITIONS: tuple[str, ...] = (
    "dismissed",
    "acquitted",
    "convicted_plea",
    "convicted_verdict",
    "pending",
)
SEVERITIES: tuple[str, ...] = (
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
POSITIONS: tuple[str, ...] = ("circuit_judge", "associate_judge")
SENTENCE_COMPONENTS: tuple[str, ...] = ("incarceration", "probation", "fine")
RELEASE_CONDITIONS: tuple[str, ...] = (
    "check_in",
    "no_contact",
    "travel_restriction",
    "drug_testing",
    "electronic_monitoring",
)

# The restricted vocabularies (version 2, Phase 4 Step 1): attributes that live
# only in the database's ``restricted`` schema, are never a model feature, and
# are read only by the aggregate fairness analysis (docs/DATA_MODEL.md).
RESTRICTED_ATTRIBUTES: tuple[str, ...] = ("age_band", "synthetic_group")
AGE_BAND_VALUES: tuple[str, ...] = ("18-24", "25-34", "35-44", "45-54", "55+", "unknown")
SYNTHETIC_GROUPS: tuple[str, ...] = ("group_a", "group_b", "group_c")
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
    "severity": SEVERITIES,
    "offense_category": OFFENSE_CATEGORIES,
    "justice_event_type": JUSTICE_EVENT_TYPES,
    "actor_type": ACTOR_TYPES,
    "position": POSITIONS,
    "sentence_component": SENTENCE_COMPONENTS,
    "release_condition": RELEASE_CONDITIONS,
    "restricted_attribute": RESTRICTED_ATTRIBUTES,
    "age_band": AGE_BAND_VALUES,
    "synthetic_group": SYNTHETIC_GROUPS,
}

# Severity rank for choosing a case's lead charge (lower is more severe).
SEVERITY_RANK: dict[str, int] = {severity: rank for rank, severity in enumerate(SEVERITIES)}
FELONY_SEVERITIES: tuple[str, ...] = tuple(s for s in SEVERITIES if s.startswith("felony"))
MISDEMEANOR_SEVERITIES: tuple[str, ...] = tuple(
    s for s in SEVERITIES if s.startswith("misdemeanor")
)
