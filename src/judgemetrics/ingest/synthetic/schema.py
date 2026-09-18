# src/judgemetrics/ingest/synthetic/schema.py
"""Expected headers of the nine synthetic source files and the manifest.

Lifted from docs/SYNTHETIC_DATA.md "Source format" (the generator's
``writer.SOURCE_HEADERS`` is the same list; a unit test keeps them equal).
A file missing an expected header fails the run naming the header; a
header outside the expected set is a warning, so a future generator column
is noticed without breaking the connector. Every column is read; the
generator emits nothing the connector must project away, but the parser
projects to the expected set regardless so that stays true.

``participants.csv`` carries ``full_name`` and ``date_of_birth``. They are
read for hashing only (``judgemetrics.security.identifiers``) and never
enter a payload column that reaches a canonical row, a log line, or an
issue description.
"""

from __future__ import annotations

MANIFEST_FILE = "manifest.json"
SOURCE_DIR = "source"
TRUTH_DIR = "truth"

COURTS_FILE = "courts.csv"
JUDGES_FILE = "judges.csv"
CASES_FILE = "cases.csv"
PARTICIPANTS_FILE = "participants.csv"
CHARGES_FILE = "charges.csv"
ASSIGNMENTS_FILE = "assignments.csv"
EVENTS_FILE = "events.csv"
DECISIONS_FILE = "decisions.csv"
SENTENCES_FILE = "sentences.csv"

# Discovery order: reference files first, then the case files in dependency
# order, so a connector context built file by file is complete when needed.
SOURCE_FILES: tuple[str, ...] = (
    COURTS_FILE,
    JUDGES_FILE,
    CASES_FILE,
    PARTICIPANTS_FILE,
    CHARGES_FILE,
    ASSIGNMENTS_FILE,
    EVENTS_FILE,
    DECISIONS_FILE,
    SENTENCES_FILE,
)

EXPECTED_HEADERS: dict[str, tuple[str, ...]] = {
    COURTS_FILE: ("court_code", "name", "court_type", "jurisdiction", "state_code"),
    JUDGES_FILE: ("judge_code", "full_name", "court_code", "position", "start_date", "end_date"),
    CASES_FILE: (
        "case_number",
        "court_code",
        "case_type",
        "filed_date",
        "closed_date",
        "status",
        "related_case_number",
    ),
    PARTICIPANTS_FILE: (
        "participant_id",
        "case_number",
        "court_code",
        "party_type",
        "full_name",
        "date_of_birth",
        "age_at_filing",
    ),
    CHARGES_FILE: (
        "charge_id",
        "case_number",
        "court_code",
        "participant_id",
        "statute_code",
        "description",
        "offense_category",
        "severity",
        "violent_flag",
        "filed_at",
        "disposed_at",
        "disposition",
        "disposition_actor",
    ),
    ASSIGNMENTS_FILE: (
        "assignment_id",
        "case_number",
        "court_code",
        "judge_code",
        "assignment_type",
        "start_at",
        "end_at",
    ),
    EVENTS_FILE: (
        "event_id",
        "case_number",
        "court_code",
        "participant_id",
        "judge_code",
        "event_type",
        "event_at",
        "actor",
        "description",
    ),
    DECISIONS_FILE: (
        "decision_id",
        "case_number",
        "court_code",
        "participant_id",
        "judge_code",
        "decision_type",
        "decision_at",
        "actor",
        "discretion",
        "release_type",
        "bond_amount",
        "detained",
        "release_at",
        "conditions",
    ),
    SENTENCES_FILE: (
        "sentence_id",
        "case_number",
        "court_code",
        "participant_id",
        "judge_code",
        "sentence_at",
        "incarceration_days",
        "probation_days",
        "fine_amount",
        "components",
    ),
}

# The column of each file that identifies a row (``source_row_id``).
ROW_ID_COLUMNS: dict[str, str] = {
    COURTS_FILE: "court_code",
    JUDGES_FILE: "judge_code",
    CASES_FILE: "case_number",
    PARTICIPANTS_FILE: "participant_id",
    CHARGES_FILE: "charge_id",
    ASSIGNMENTS_FILE: "assignment_id",
    EVENTS_FILE: "event_id",
    DECISIONS_FILE: "decision_id",
    SENTENCES_FILE: "sentence_id",
}

# ``SourceRecordDraft.record_type`` is the file stem.
RECORD_TYPE_MANIFEST = "manifest"
RECORD_TYPE_COURT = "courts"
RECORD_TYPE_JUDGE = "judges"
RECORD_TYPE_CASE = "cases"
RECORD_TYPE_PARTICIPANT = "participants"
RECORD_TYPE_CHARGE = "charges"
RECORD_TYPE_ASSIGNMENT = "assignments"
RECORD_TYPE_EVENT = "events"
RECORD_TYPE_DECISION = "decisions"
RECORD_TYPE_SENTENCE = "sentences"

# Columns that name a person attribute: hashed in ``normalize``, never kept.
PERSON_ATTRIBUTE_COLUMNS: frozenset[str] = frozenset({"full_name", "date_of_birth"})

# Identity systems the connector writes into ``external_ids``.
JUDGE_IDENTITY_SYSTEM = "synthetic_judge_code"
COURT_IDENTITY_SYSTEM = "synthetic_court_code"

# Source values.
JURISDICTION_TYPE = "state"
TRUE = "true"
FALSE = "false"
LIST_SEPARATOR = ";"


def record_type_for(file_name: str) -> str:
    """``"charges.csv"`` → ``"charges"``; ``"manifest.json"`` → ``"manifest"``."""
    stem, _, _ = file_name.rpartition(".")
    return stem or file_name


def artifact_id(file_name: str) -> str:
    """The external id of a source file: its path under the dataset root."""
    return f"{SOURCE_DIR}/{file_name}"
