# src/judgemetrics/db/models/__init__.py
"""Every canonical entity of the brief, exported so Alembic autogenerate and
the application see one complete ``Base.metadata``.

Twenty-four tables: the brief's twenty-three — jurisdiction, court, judge,
judge_service, person, person_identifier, court_case, case_party,
judge_assignment, charge, court_event, decision, pretrial_release,
sentence, justice_event, source, source_record, ingest_run,
entity_resolution_candidate, metric_definition, metric_observation,
data_quality_issue, correction_request — and the append-only audit_log
the brief's security requirements ask for (revision 0004).
"""

from judgemetrics.db.base import Base
from judgemetrics.db.models.audit import AuditLog
from judgemetrics.db.models.cases import (
    Case,
    CaseParty,
    Charge,
    CourtEvent,
    Decision,
    JudgeAssignment,
    PretrialRelease,
    Sentence,
)
from judgemetrics.db.models.corrections import CorrectionRequest
from judgemetrics.db.models.enums import (
    PG_ENUM_NAMES,
    ActorType,
    CorrectionStatus,
    IngestRunStatus,
    IssueSeverity,
    IssueStatus,
    JurisdictionType,
    ResolutionDecision,
    SubjectType,
)
from judgemetrics.db.models.metrics import MetricDefinition, MetricObservation
from judgemetrics.db.models.persons import JusticeEvent, Person, PersonIdentifier
from judgemetrics.db.models.provenance import (
    SYNTHETIC_SOURCE_TYPE,
    DataQualityIssue,
    IngestRun,
    Source,
    SourceRecord,
)
from judgemetrics.db.models.reference import Court, Judge, JudgeService, Jurisdiction
from judgemetrics.db.models.resolution import EntityResolutionCandidate

CANONICAL_TABLES: tuple[str, ...] = (
    "jurisdiction",
    "court",
    "judge",
    "judge_service",
    "person",
    "person_identifier",
    "court_case",
    "case_party",
    "judge_assignment",
    "charge",
    "court_event",
    "decision",
    "pretrial_release",
    "sentence",
    "justice_event",
    "source",
    "source_record",
    "ingest_run",
    "entity_resolution_candidate",
    "metric_definition",
    "metric_observation",
    "data_quality_issue",
    "correction_request",
    "audit_log",
)

# Tables the public API role must never read (ROADMAP.md §5 data classification):
# hashed identifiers, requester contacts, the resolution candidates that
# reference them, and the administrative audit trail.
RESTRICTED_TABLES: frozenset[str] = frozenset(
    {"person_identifier", "correction_request", "entity_resolution_candidate", "audit_log"}
)

__all__ = [
    "CANONICAL_TABLES",
    "PG_ENUM_NAMES",
    "RESTRICTED_TABLES",
    "SYNTHETIC_SOURCE_TYPE",
    "ActorType",
    "AuditLog",
    "Base",
    "Case",
    "CaseParty",
    "Charge",
    "CorrectionRequest",
    "CorrectionStatus",
    "Court",
    "CourtEvent",
    "DataQualityIssue",
    "Decision",
    "EntityResolutionCandidate",
    "IngestRun",
    "IngestRunStatus",
    "IssueSeverity",
    "IssueStatus",
    "Judge",
    "JudgeAssignment",
    "JudgeService",
    "Jurisdiction",
    "JurisdictionType",
    "JusticeEvent",
    "MetricDefinition",
    "MetricObservation",
    "Person",
    "PersonIdentifier",
    "PretrialRelease",
    "ResolutionDecision",
    "Sentence",
    "Source",
    "SourceRecord",
    "SubjectType",
]
