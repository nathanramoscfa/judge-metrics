# src/judgemetrics/ingest/cook_sao/schema.py
"""Verified export headers and column classes of the five Cook County datasets.

Read from each dataset's portal metadata (``columns[].name``) and from the
first line of each bulk export on 2026-10-05 (``HEADERS_VERIFIED_ON``). The
export's header row carries the portal's column *display names*
(``CASE_ID``, ``PRIMARY_CHARGE_FLAG``, ``DISPOSITION_COURT_NAME``,
``LENGTH_OF_CASE_in_Days``), not the API field names (``case_id``,
``primary_charge``, ``court_name``, ``length_of_case_in_days``), so every
constant here uses the export's spelling, misspellings included
(``BOND_ELECTROINIC_MONITOR_FLAG_CURRENT``; Intake's
``UPDATE_OFFENSE_CATEGORY`` beside the other datasets'
``UPDATED_OFFENSE_CATEGORY``). A verified header missing from an export
or from the metadata fails validation naming the header; an extra one is
a warning (schema drift).

The column classes drive ``judgemetrics sources profile`` and ``excerpt``:

- ``CODED_COLUMNS`` — the value sets the attribution, pretrial, sentence,
  offense, and court tables of Phase 5 Step 3 map; the profile lists each
  one's distinct values with counts.
- ``JUDGE_COLUMNS`` — the free-text judge names, listed with counts.
- ``RESTRICTED_COLUMNS`` — race, gender, and age, destined for the
  restricted schema: the profile lists race and gender values without a
  count and age as a range; the excerpt blanks them.
- ``BLANKED_COLUMNS`` — the restricted columns plus the quasi-identifiers
  the canonical model never reads (the incident's city and dates, the
  arresting agency and unit), emptied in every committed fixture row.
- ``DATE_COLUMNS`` and ``NUMERIC_COLUMNS`` — parsed for ranges and for the
  unparseable values the profile reports; every other column gets its
  distinct count only.
"""

from __future__ import annotations

from datetime import date

HEADERS_VERIFIED_ON = date(2026, 10, 5)

CASE_ID = "CASE_ID"
PARTICIPANT_ID = "CASE_PARTICIPANT_ID"
RECEIVED_DATE = "RECEIVED_DATE"
CHARGE_ID = "CHARGE_ID"
CHARGE_VERSION_ID = "CHARGE_VERSION_ID"
CHARGE_DISPOSITION = "CHARGE_DISPOSITION"
CHARGE_DISPOSITION_REASON = "CHARGE_DISPOSITION_REASON"
JUDGE = "JUDGE"
SENTENCE_JUDGE = "SENTENCE_JUDGE"
BOND_TYPE_INITIAL = "BOND_TYPE_INITIAL"
BOND_TYPE_CURRENT = "BOND_TYPE_CURRENT"
SENTENCE_PHASE = "SENTENCE_PHASE"
SENTENCE_TYPE = "SENTENCE_TYPE"
RACE = "RACE"
GENDER = "GENDER"
AGE_AT_INCIDENT = "AGE_AT_INCIDENT"

# The exports write a date in one of two formats, month first: with a
# 12-hour time (``MM/DD/YYYY hh:mm:ss AM``; a real time on the arrest dates
# and on some bond and event dates, midnight elsewhere) or without one
# (``MM/DD/YYYY``: Intake's received, felony-review, and incident dates, and
# Dispositions' ``INCIDENT_BEGIN_DATE``). The profile counts each column's
# values per format and reports any value in neither.
DATE_FORMATS: dict[str, str] = {
    "%m/%d/%Y %I:%M:%S %p": r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} [AP]M$",
    "%m/%d/%Y": r"^\d{2}/\d{2}/\d{4}$",
}

# The columns every case-level row of every dataset begins with.
_CASE_KEYS = (CASE_ID, PARTICIPANT_ID, RECEIVED_DATE, "OFFENSE_CATEGORY")
# The incident, arrest, and felony-review columns several datasets share.
_INCIDENT = (
    "INCIDENT_CITY",
    "INCIDENT_BEGIN_DATE",
    "INCIDENT_END_DATE",
    "LAW_ENFORCEMENT_AGENCY",
    "LAW_ENFORCEMENT_UNIT",
    "ARREST_DATE",
    "FELONY_REVIEW_DATE",
    "FELONY_REVIEW_RESULT",
)
_DISPOSED_CHARGE = (
    "PRIMARY_CHARGE_FLAG",
    CHARGE_ID,
    CHARGE_VERSION_ID,
    "DISPOSITION_CHARGED_OFFENSE_TITLE",
    "CHARGE_COUNT",
    "DISPOSITION_DATE",
    "DISPOSITION_CHARGED_CHAPTER",
    "DISPOSITION_CHARGED_ACT",
    "DISPOSITION_CHARGED_SECTION",
    "DISPOSITION_CHARGED_CLASS",
    "DISPOSITION_CHARGED_AOIC",
    CHARGE_DISPOSITION,
    CHARGE_DISPOSITION_REASON,
)

INTAKE_HEADERS: tuple[str, ...] = (
    *_CASE_KEYS,
    "PARTICIPANT_STATUS",
    AGE_AT_INCIDENT,
    RACE,
    GENDER,
    *_INCIDENT,
    "UPDATE_OFFENSE_CATEGORY",
)
INITIATION_HEADERS: tuple[str, ...] = (
    *_CASE_KEYS,
    "PRIMARY_CHARGE_FLAG",
    CHARGE_ID,
    CHARGE_VERSION_ID,
    "CHARGE_OFFENSE_TITLE",
    "CHARGE_COUNT",
    "CHAPTER",
    "ACT",
    "SECTION",
    "CLASS",
    "AOIC",
    "EVENT",
    "EVENT_DATE",
    "FINDING_NO_PROBABLE_CAUSE",
    "ARRAIGNMENT_DATE",
    "BOND_DATE_INITIAL",
    "BOND_DATE_CURRENT",
    BOND_TYPE_INITIAL,
    BOND_TYPE_CURRENT,
    "BOND_AMOUNT_INITIAL",
    "BOND_AMOUNT_CURRENT",
    "BOND_ELECTRONIC_MONITOR_FLAG_INITIAL",
    "BOND_ELECTROINIC_MONITOR_FLAG_CURRENT",
    AGE_AT_INCIDENT,
    RACE,
    GENDER,
    *_INCIDENT,
    "UPDATED_OFFENSE_CATEGORY",
)
DISPOSITIONS_HEADERS: tuple[str, ...] = (
    *_CASE_KEYS,
    *_DISPOSED_CHARGE,
    JUDGE,
    "DISPOSITION_COURT_NAME",
    "DISPOSITION_COURT_FACILITY",
    AGE_AT_INCIDENT,
    RACE,
    GENDER,
    *_INCIDENT,
    "ARRAIGNMENT_DATE",
    "UPDATED_OFFENSE_CATEGORY",
)
SENTENCING_HEADERS: tuple[str, ...] = (
    *_CASE_KEYS,
    *_DISPOSED_CHARGE,
    SENTENCE_JUDGE,
    "SENTENCE_COURT_NAME",
    "SENTENCE_COURT_FACILITY",
    SENTENCE_PHASE,
    "SENTENCE_DATE",
    SENTENCE_TYPE,
    "CURRENT_SENTENCE_FLAG",
    "COMMITMENT_TYPE",
    "COMMITMENT_TERM",
    "COMMITMENT_UNIT",
    "LENGTH_OF_CASE_in_Days",
    AGE_AT_INCIDENT,
    RACE,
    GENDER,
    *_INCIDENT,
    "ARRAIGNMENT_DATE",
    "UPDATED_OFFENSE_CATEGORY",
)
DIVERSION_HEADERS: tuple[str, ...] = (
    *_CASE_KEYS,
    "DIVERSION_PROGRAM",
    "REFERRAL_DATE",
    "DIVERSION_COUNT",
    "PRIMARY_CHARGE_OFFENSE_TITLE",
    "STATUTE",
    RACE,
    GENDER,
    "DIVERSION_RESULT",
    "DIVERSION_CLOSED_DATE",
)

VERIFIED_HEADERS: dict[str, tuple[str, ...]] = {
    "intake.csv": INTAKE_HEADERS,
    "initiation.csv": INITIATION_HEADERS,
    "dispositions.csv": DISPOSITIONS_HEADERS,
    "sentencing.csv": SENTENCING_HEADERS,
    "diversion.csv": DIVERSION_HEADERS,
}

# --- column classes ------------------------------------------------------------

_DISPOSITION_CODED = (
    "OFFENSE_CATEGORY",
    "PRIMARY_CHARGE_FLAG",
    "DISPOSITION_CHARGED_CLASS",
    CHARGE_DISPOSITION,
    CHARGE_DISPOSITION_REASON,
    "FELONY_REVIEW_RESULT",
    "UPDATED_OFFENSE_CATEGORY",
)
CODED_COLUMNS: dict[str, tuple[str, ...]] = {
    "intake.csv": (
        "OFFENSE_CATEGORY",
        "PARTICIPANT_STATUS",
        "FELONY_REVIEW_RESULT",
        "UPDATE_OFFENSE_CATEGORY",
    ),
    "initiation.csv": (
        "OFFENSE_CATEGORY",
        "PRIMARY_CHARGE_FLAG",
        "CLASS",
        "EVENT",
        "FINDING_NO_PROBABLE_CAUSE",
        BOND_TYPE_INITIAL,
        BOND_TYPE_CURRENT,
        "BOND_ELECTRONIC_MONITOR_FLAG_INITIAL",
        "BOND_ELECTROINIC_MONITOR_FLAG_CURRENT",
        "FELONY_REVIEW_RESULT",
        "UPDATED_OFFENSE_CATEGORY",
    ),
    "dispositions.csv": (
        *_DISPOSITION_CODED,
        "DISPOSITION_COURT_NAME",
        "DISPOSITION_COURT_FACILITY",
    ),
    "sentencing.csv": (
        *_DISPOSITION_CODED,
        "SENTENCE_COURT_NAME",
        "SENTENCE_COURT_FACILITY",
        SENTENCE_PHASE,
        SENTENCE_TYPE,
        "CURRENT_SENTENCE_FLAG",
        "COMMITMENT_TYPE",
        "COMMITMENT_UNIT",
    ),
    "diversion.csv": ("OFFENSE_CATEGORY", "DIVERSION_PROGRAM", "DIVERSION_RESULT"),
}
JUDGE_COLUMNS: dict[str, str] = {"dispositions.csv": JUDGE, "sentencing.csv": SENTENCE_JUDGE}

RESTRICTED_COLUMNS: tuple[str, ...] = (RACE, GENDER, AGE_AT_INCIDENT)
# Listed without counts in the profile (values only); age is a range.
RESTRICTED_VALUE_COLUMNS: tuple[str, ...] = (RACE, GENDER)
QUASI_IDENTIFIER_COLUMNS: tuple[str, ...] = (
    "INCIDENT_CITY",
    "INCIDENT_BEGIN_DATE",
    "INCIDENT_END_DATE",
    "LAW_ENFORCEMENT_AGENCY",
    "LAW_ENFORCEMENT_UNIT",
)
BLANKED_COLUMNS: tuple[str, ...] = (*RESTRICTED_COLUMNS, *QUASI_IDENTIFIER_COLUMNS)

DATE_COLUMNS: tuple[str, ...] = (
    RECEIVED_DATE,
    "INCIDENT_BEGIN_DATE",
    "INCIDENT_END_DATE",
    "ARREST_DATE",
    "FELONY_REVIEW_DATE",
    "EVENT_DATE",
    "ARRAIGNMENT_DATE",
    "BOND_DATE_INITIAL",
    "BOND_DATE_CURRENT",
    "DISPOSITION_DATE",
    "SENTENCE_DATE",
    "REFERRAL_DATE",
    "DIVERSION_CLOSED_DATE",
)
NUMERIC_COLUMNS: tuple[str, ...] = (
    CASE_ID,
    PARTICIPANT_ID,
    CHARGE_ID,
    CHARGE_VERSION_ID,
    "CHARGE_COUNT",
    "BOND_AMOUNT_INITIAL",
    "BOND_AMOUNT_CURRENT",
    "COMMITMENT_TERM",
    "LENGTH_OF_CASE_in_Days",
    "DIVERSION_COUNT",
    AGE_AT_INCIDENT,
)
# Identifier columns: never echoed as an example of an unparseable value.
IDENTIFIER_COLUMNS: tuple[str, ...] = (CASE_ID, PARTICIPANT_ID, CHARGE_ID, CHARGE_VERSION_ID)
