# src/judgemetrics/ingest/fjc/schema.py
"""Verified headers and vocabularies of the two FJC export files.

Read from the live files on 2026-09-16 (``HEADERS_VERIFIED_ON``) and
recorded in docs/DATA_SOURCES.md. Two header sets exist per file:

- ``*_VERIFIED_HEADERS`` — every column the file carried on that date,
  in order (201 in ``judges.csv``, 30 in ``federal-judicial-service.csv``);
  a header outside this set is reported as a validation *warning* so
  schema drift is noticed without breaking the run;
- ``*_EXPECTED_HEADERS`` — the columns the connector reads; a missing one
  is a validation *error* naming the header and the run fails.

``judges.csv`` carries ``Gender`` and ``Race or Ethnicity``. They are
verified (so their presence is not "drift") but they are never expected,
never parsed into a payload, and never published: the parser projects
each row to the expected columns before anything downstream sees it.
"""

from __future__ import annotations

from datetime import date

HEADERS_VERIFIED_ON = date(2026, 9, 16)

# ``SourceRecordDraft.record_type`` values the FJC connector emits.
RECORD_TYPE_JUDGE = "judge"
RECORD_TYPE_SERVICE = "judge_service"

NID = "nid"
JID = "jid"
SEQUENCE = "Sequence"

# --- judges.csv --------------------------------------------------------------

JUDGES_IDENTITY_HEADERS: tuple[str, ...] = (
    "nid",
    "jid",
    "Last Name",
    "First Name",
    "Middle Name",
    "Suffix",
    "Birth Month",
    "Birth Day",
    "Birth Year",
    "Birth City",
    "Birth State",
    "Death Month",
    "Death Day",
    "Death Year",
    "Death City",
    "Death State",
)
DEMOGRAPHIC_HEADERS: tuple[str, ...] = ("Gender", "Race or Ethnicity")

# One group of these per appointment, suffixed " (1)" … " (6)" in judges.csv;
# unsuffixed, one row per appointment, in federal-judicial-service.csv.
SERVICE_FIELDS: tuple[str, ...] = (
    "Court Type",
    "Court Name",
    "Appointment Title",
    "Appointing President",
    "Party of Appointing President",
    "Reappointing President",
    "Party of Reappointing President",
    "ABA Rating",
    "Seat ID",
    "Statute Authorizing New Seat",
    "Recess Appointment Date",
    "Nomination Date",
    "Committee Referral Date",
    "Hearing Date",
    "Judiciary Committee Action",
    "Committee Action Date",
    "Senate Vote Type",
    "Ayes/Nays",
    "Confirmation Date",
    "Commission Date",
    "Service as Chief Judge, Begin",
    "Service as Chief Judge, End",
    "2nd Service as Chief Judge, Begin",
    "2nd Service as Chief Judge, End",
    "Senior Status Date",
    "Termination",
    "Termination Date",
)
SERVICE_GROUP_COUNT = 6
OTHER_SERVICE_HEADERS: tuple[str, ...] = tuple(
    f"Other Federal Judicial Service ({n})" for n in range(1, 5)
)
EDUCATION_HEADERS: tuple[str, ...] = tuple(
    f"{field} ({n})" for n in range(1, 6) for field in ("School", "Degree", "Degree Year")
)
CAREER_HEADERS: tuple[str, ...] = ("Professional Career", "Other Nominations/Recess Appointments")


def group_header(field: str, group: int) -> str:
    """``"Court Name"``, 2 → ``"Court Name (2)"``."""
    return f"{field} ({group})"


JUDGES_VERIFIED_HEADERS: tuple[str, ...] = (
    *JUDGES_IDENTITY_HEADERS,
    *DEMOGRAPHIC_HEADERS,
    *(
        group_header(field, group)
        for group in range(1, SERVICE_GROUP_COUNT + 1)
        for field in SERVICE_FIELDS
    ),
    *OTHER_SERVICE_HEADERS,
    *EDUCATION_HEADERS,
    *CAREER_HEADERS,
)

# The per-appointment fields the connector reads from judges.csv groups.
JUDGES_SERVICE_FIELDS: tuple[str, ...] = (
    "Court Type",
    "Court Name",
    "Appointment Title",
    "Recess Appointment Date",
    "Commission Date",
    "Senior Status Date",
    "Termination",
    "Termination Date",
)
JUDGES_EXPECTED_HEADERS: tuple[str, ...] = (
    "nid",
    "jid",
    "Last Name",
    "First Name",
    "Middle Name",
    "Suffix",
    "Birth Year",
    *(
        group_header(field, group)
        for group in range(1, SERVICE_GROUP_COUNT + 1)
        for field in JUDGES_SERVICE_FIELDS
    ),
)

# --- federal-judicial-service.csv --------------------------------------------

SERVICE_VERIFIED_HEADERS: tuple[str, ...] = ("nid", "Sequence", "Judge Name", *SERVICE_FIELDS)
SERVICE_EXPECTED_HEADERS: tuple[str, ...] = (
    "nid",
    "Sequence",
    "Judge Name",
    "Court Type",
    "Court Name",
    "Appointment Title",
    "Recess Appointment Date",
    "Commission Date",
    "Senior Status Date",
    "Termination",
    "Termination Date",
)

EXPECTED_HEADERS: dict[str, tuple[str, ...]] = {
    "judges.csv": JUDGES_EXPECTED_HEADERS,
    "federal-judicial-service.csv": SERVICE_EXPECTED_HEADERS,
}
VERIFIED_HEADERS: dict[str, tuple[str, ...]] = {
    "judges.csv": JUDGES_VERIFIED_HEADERS,
    "federal-judicial-service.csv": SERVICE_VERIFIED_HEADERS,
}

# --- vocabularies (verified 2026-09-16, every distinct value) ----------------

# FJC "Court Type" → canonical court_type (district | appeals | supreme | other).
COURT_TYPES: dict[str, str] = {
    "U.S. District Court": "district",
    "U.S. Court of Appeals": "appeals",
    "Supreme Court": "supreme",
    "Other": "other",
    "U.S. Circuit Court (1869-1911)": "other",
    "U.S. Circuit Court (1801-1802)": "other",
    "U.S. Circuit Court (other)": "other",
}
DEFAULT_COURT_TYPE = "other"

APPOINTMENT_TITLES: frozenset[str] = frozenset(
    {
        "Judge",
        "Chief Judge",
        "Associate Judge",
        "Presiding Judge",
        "Associate Justice",
        "Chief Justice",
    }
)

# FJC "Termination" → judge status when it is the latest appointment.
TERMINATION_STATUSES: dict[str, str] = {
    "Death": "deceased",
    "Retirement": "retired",
    "Resignation": "resigned",
    "Impeachment & Conviction": "removed",
    "Appointment to Another Judicial Position": "inactive",
    "Reassignment": "inactive",
    "Abolition of Court": "inactive",
    "Recess Appointment-Not Confirmed": "inactive",
}
JUDGE_STATUSES: frozenset[str] = frozenset(
    {"active", "senior", "deceased", "retired", "resigned", "removed", "inactive", "unknown"}
)

# Dates are ISO ``YYYY-MM-DD``; "Birth Year" is ``YYYY`` or ``ca. YYYY``.
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
