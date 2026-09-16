# src/judgemetrics/db/models/enums.py
"""Enumerations named by the brief's canonical data model and attribution model.

Each Python enum is mirrored by a PostgreSQL ``ENUM`` type of the same
``pg_name`` in the baseline migration; the values are the brief's, verbatim.
Vocabularies the brief leaves open (case status, charge disposition,
release type, position type, event type, discretion classification) stay
free text until the versioned rule registries of later phases define them.
"""

from __future__ import annotations

from enum import StrEnum


class JurisdictionType(StrEnum):
    FEDERAL = "federal"
    STATE = "state"
    COUNTY = "county"
    CITY = "city"
    DISTRICT = "district"
    CIRCUIT = "circuit"


class ActorType(StrEnum):
    """Who took an action; the basis of every judge-level inclusion rule."""

    JUDGE = "judge"
    PROSECUTOR = "prosecutor"
    DEFENSE = "defense"
    JURY = "jury"
    CLERK = "clerk"
    LAW_ENFORCEMENT = "law_enforcement"
    LEGISLATURE_OR_MANDATORY_RULE = "legislature_or_mandatory_rule"
    APPELLATE_COURT = "appellate_court"
    UNKNOWN = "unknown"


class ResolutionDecision(StrEnum):
    MATCHED = "matched"
    REJECTED = "rejected"
    REVIEW = "review"


class SubjectType(StrEnum):
    JUDGE = "judge"
    COURT = "court"
    JURISDICTION = "jurisdiction"


class IngestRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    # A synthetic source refused by the runner in production (domain rule).
    REFUSED = "refused"


class IssueSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class IssueStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    WONT_FIX = "wont_fix"


class CorrectionStatus(StrEnum):
    RECEIVED = "received"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CLOSED = "closed"


# PostgreSQL type names, shared by the models and the baseline migration.
PG_ENUM_NAMES: dict[type[StrEnum], str] = {
    JurisdictionType: "jurisdiction_type",
    ActorType: "actor_type",
    ResolutionDecision: "resolution_decision",
    SubjectType: "subject_type",
    IngestRunStatus: "ingest_run_status",
    IssueSeverity: "issue_severity",
    IssueStatus: "issue_status",
    CorrectionStatus: "correction_status",
}
