# src/judgemetrics/ingest/base.py
"""The connector protocol and the value types that flow through the pipeline.

The brief's ``SourceConnector`` interface is reproduced exactly (``discover``,
``fetch``, ``validate_raw``, ``parse``, ``normalize``); ``source_id``,
``parser_version``, and ``source_info`` identify the connector, the
optional ``SupportsCheckpoint`` protocol carries incremental state for
cursoring sources, and the optional ``SupportsCoverage`` protocol reports
the window the source's records cover (Phase 3: the instant the metrics
engine right-censors follow-up at). Everything a connector produces is a frozen dataclass:

- ``SourceArtifact`` — something discoverable at the source (one file, one
  API page); ``RawArtifact`` — the retrieved bytes with their sha256;
- ``SourceRecordDraft`` — one parsed source row (the database
  ``source_record`` is per *artifact*; rows are attributed to it);
- the ``CanonicalRecord`` drafts, each with a ``natural_key`` the runner
  deduplicates and upserts on: the reference drafts (jurisdiction, court,
  judge, judge service) and the case-level drafts (person, case, party,
  assignment, charge, court event, decision with its pretrial release,
  sentence, justice event).

Natural keys: a person is ``("person", <identifier kind>, <hash>)`` — the
peppered hash of its stable source identifier, never a name; a case is
``("case", <court name>, <court type>, <normalized case number>)``; every
row that belongs to a case is ``("<table>", *case_key[1:], source_row_id)``
where ``source_row_id`` is the source's own row identifier, so a re-export
of the same row upserts in place; a justice event is keyed on the person
hash, the event type, the instant, and the related case, because a
derived event has no source row of its own. ``describe_key`` renders a
key for issue descriptions and logs without the person hash.

Source-specific parsing stays in the connectors; the drafts speak the
canonical domain only.
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from judgemetrics.db.models.enums import ActorType

NaturalKey = tuple[str, ...]
Checkpoint = dict[str, Any]

# Keys the runner adds to ``SourceArtifact.metadata`` before ``fetch`` so a
# connector can issue a conditional request; the values come from the
# artifact's latest ``source_record``.
PREVIOUS_ETAG = "previous_etag"
PREVIOUS_LAST_MODIFIED = "previous_last_modified"
PREVIOUS_SHA256 = "previous_sha256"

# Keys of the ``RawArtifact.response_headers`` subset (lower-case).
HEADER_ETAG = "etag"
HEADER_LAST_MODIFIED = "last_modified"
HEADER_CONTENT_TYPE = "content_type"
HEADER_CONTENT_LENGTH = "content_length"
HEADER_FINAL_URL = "final_url"


class IngestError(Exception):
    """Base class for every error the ingest framework raises."""


class FetchError(IngestError):
    """An artifact could not be retrieved."""


class NormalizationError(IngestError):
    """A source row could not be mapped to canonical drafts (the row is rejected)."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True, slots=True)
class SourceArtifact:
    """One discoverable unit at the source, e.g. a downloadable file."""

    source_id: str
    external_id: str
    uri: str
    content_type: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def with_metadata(self, **extra: str) -> SourceArtifact:
        return dataclasses.replace(self, metadata={**self.metadata, **extra})


@dataclass(frozen=True, slots=True)
class RawArtifact:
    """Retrieved bytes (or a path to them) with their digest and retrieval facts."""

    artifact: SourceArtifact
    path_or_bytes: Path | bytes
    sha256: str
    retrieved_at: datetime
    size_bytes: int
    response_headers: Mapping[str, str] = field(default_factory=dict)
    # True when the server answered a conditional request with 304: the
    # bytes are the ones already in the lake under ``sha256``.
    not_modified: bool = False

    @classmethod
    def from_bytes(
        cls,
        artifact: SourceArtifact,
        data: bytes,
        *,
        retrieved_at: datetime,
        response_headers: Mapping[str, str] | None = None,
    ) -> RawArtifact:
        return cls(
            artifact=artifact,
            path_or_bytes=data,
            sha256=sha256_hex(data),
            retrieved_at=retrieved_at,
            size_bytes=len(data),
            response_headers=dict(response_headers or {}),
        )

    @classmethod
    def from_path(
        cls,
        artifact: SourceArtifact,
        path: Path,
        *,
        retrieved_at: datetime,
        response_headers: Mapping[str, str] | None = None,
    ) -> RawArtifact:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
                size += len(chunk)
        return cls(
            artifact=artifact,
            path_or_bytes=path,
            sha256=digest.hexdigest(),
            retrieved_at=retrieved_at,
            size_bytes=size,
            response_headers=dict(response_headers or {}),
        )

    @classmethod
    def unchanged(
        cls,
        artifact: SourceArtifact,
        *,
        sha256: str,
        retrieved_at: datetime,
        response_headers: Mapping[str, str] | None = None,
    ) -> RawArtifact:
        return cls(
            artifact=artifact,
            path_or_bytes=b"",
            sha256=sha256,
            retrieved_at=retrieved_at,
            size_bytes=0,
            response_headers=dict(response_headers or {}),
            not_modified=True,
        )

    def read_bytes(self) -> bytes:
        if isinstance(self.path_or_bytes, Path):
            return self.path_or_bytes.read_bytes()
        return self.path_or_bytes


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def passed(cls, warnings: Iterable[str] = ()) -> ValidationResult:
        return cls(ok=True, warnings=list(warnings))

    @classmethod
    def failed(cls, errors: Iterable[str], warnings: Iterable[str] = ()) -> ValidationResult:
        return cls(ok=False, errors=list(errors), warnings=list(warnings))


@dataclass(frozen=True, slots=True)
class SourceRecordDraft:
    """One parsed source row. ``record_type`` tells ``normalize`` which mapping applies."""

    external_record_id: str
    effective_at: datetime | None
    payload: Mapping[str, Any]
    record_type: str = ""


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """What the ``source`` row records about a connector's source.

    ``observable_outcomes`` lists the ``justice_event_type`` values the
    source can document (``source.observable_outcomes``): a metric whose
    outcome is not among them is not observable for the source and is
    never published for it, never as a zero (docs/METHODOLOGY.md). A
    reference-only source (FJC) documents none.
    """

    owner: str
    source_type: str
    access_method: str
    terms_metadata: Mapping[str, Any] = field(default_factory=dict)
    observable_outcomes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JurisdictionDraft:
    name: str
    type: str
    state_code: str | None = None
    fips_code: str | None = None

    @property
    def natural_key(self) -> NaturalKey:
        return ("jurisdiction", self.name, self.type)


@dataclass(frozen=True, slots=True)
class CourtDraft:
    canonical_name: str
    court_type: str
    jurisdiction_key: NaturalKey
    external_ids: Mapping[str, str] = field(default_factory=dict)
    state_code: str | None = None
    active_from: date | None = None
    active_to: date | None = None

    @property
    def natural_key(self) -> NaturalKey:
        return ("court", self.canonical_name, self.court_type)


@dataclass(frozen=True, slots=True)
class JudgeDraft:
    canonical_name: str
    normalized_name: str
    # (identifier system, value), e.g. ("fjc_nid", "1377101"); the pair must
    # also appear in ``external_ids`` and is the exact-match resolution key.
    identity_key: tuple[str, str]
    external_ids: Mapping[str, str] = field(default_factory=dict)
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def natural_key(self) -> NaturalKey:
        return ("judge", *self.identity_key)


@dataclass(frozen=True, slots=True)
class JudgeServiceDraft:
    judge_key: NaturalKey
    court_key: NaturalKey
    position_type: str
    start_date: date | None
    end_date: date | None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def natural_key(self) -> NaturalKey:
        start = self.start_date.isoformat() if self.start_date else ""
        return (
            "judge_service",
            *self.judge_key[1:],
            *self.court_key[1:],
            self.position_type,
            start,
        )


# --- case-level drafts (Phase 2) ------------------------------------------------


def _iso(value: datetime | date | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).isoformat()
    return value.isoformat()


def _case_key_parts(case_key: NaturalKey) -> tuple[str, ...]:
    return tuple(case_key[1:])


@dataclass(frozen=True, slots=True)
class PersonDraft:
    """A person as one source knows it: hashes only, never a name or a date.

    ``identity`` is ``(identifier kind, hash)`` for the source's stable
    identifier (``source_participant_id``) and is the deterministic
    resolution key; ``identifier_hashes`` holds every kind the source
    offers (``source_participant_id``, ``full_name``, ``date_of_birth``, and
    ``name_dob`` when both exist), each a 64-character hex digest from
    ``judgemetrics.security.identifiers.hash_identifier``.
    """

    identity: tuple[str, str]
    identifier_hashes: Mapping[str, str]
    birth_year_known: bool = False

    @property
    def natural_key(self) -> NaturalKey:
        return ("person", *self.identity)


@dataclass(frozen=True, slots=True)
class CaseDraft:
    court_key: NaturalKey
    case_number: str
    case_number_normalized: str
    case_type: str
    filed_date: date | None
    closed_date: date | None
    status: str
    source_row_id: str
    related_case_number_normalized: str | None = None

    @property
    def natural_key(self) -> NaturalKey:
        return ("case", *self.court_key[1:], self.case_number_normalized)


@dataclass(frozen=True, slots=True)
class CasePartyDraft:
    case_key: NaturalKey
    person_key: NaturalKey | None
    party_type: str
    source_party_label: str | None
    source_row_id: str

    @property
    def natural_key(self) -> NaturalKey:
        return ("case_party", *_case_key_parts(self.case_key), self.source_row_id)


@dataclass(frozen=True, slots=True)
class JudgeAssignmentDraft:
    case_key: NaturalKey
    judge_key: NaturalKey
    assignment_type: str
    start_at: datetime
    end_at: datetime | None
    source_row_id: str
    confidence: Decimal | None = None

    @property
    def natural_key(self) -> NaturalKey:
        return ("judge_assignment", *_case_key_parts(self.case_key), self.source_row_id)


@dataclass(frozen=True, slots=True)
class ChargeDraft:
    case_key: NaturalKey
    person_key: NaturalKey
    statute_code: str | None
    description: str
    offense_category: str
    severity: str
    violent_flag: bool | None
    filed_at: datetime
    disposed_at: datetime | None
    disposition: str | None
    # Who disposed of the charge: the basis of the judicial-dismissal rule
    # (a dismissal by the prosecutor is not a judicial dismissal).
    disposition_actor: ActorType | None
    source_row_id: str

    @property
    def natural_key(self) -> NaturalKey:
        return ("charge", *_case_key_parts(self.case_key), self.source_row_id)


@dataclass(frozen=True, slots=True)
class CourtEventDraft:
    case_key: NaturalKey
    person_key: NaturalKey | None
    judge_key: NaturalKey | None
    event_type: str
    event_at: datetime
    description: str | None
    actor_type: ActorType | None
    source_row_id: str

    @property
    def natural_key(self) -> NaturalKey:
        return ("court_event", *_case_key_parts(self.case_key), self.source_row_id)


@dataclass(frozen=True, slots=True)
class PretrialReleaseDraft:
    """The release terms of a pretrial decision (one child row per decision)."""

    release_type: str
    bond_amount: Decimal | None
    conditions: Mapping[str, Any]
    release_at: datetime | None
    detained_flag: bool


@dataclass(frozen=True, slots=True)
class DecisionDraft:
    case_key: NaturalKey
    person_key: NaturalKey
    judge_key: NaturalKey | None
    decision_type: str
    decision_at: datetime
    decision_value: Mapping[str, Any]
    actor_type: ActorType
    judicial_discretion_classification: str
    pretrial: PretrialReleaseDraft | None
    source_row_id: str

    @property
    def natural_key(self) -> NaturalKey:
        return ("decision", *_case_key_parts(self.case_key), self.source_row_id)


@dataclass(frozen=True, slots=True)
class SentenceDraft:
    case_key: NaturalKey
    person_key: NaturalKey
    judge_key: NaturalKey | None
    sentence_at: datetime
    incarceration_days: int | None
    probation_days: int | None
    fine_amount: Decimal | None
    components: Mapping[str, Any]
    source_row_id: str

    @property
    def natural_key(self) -> NaturalKey:
        return ("sentence", *_case_key_parts(self.case_key), self.source_row_id)


@dataclass(frozen=True, slots=True)
class JusticeEventDraft:
    """A documented later justice-system event of a person (derived, no row of its own)."""

    person_key: NaturalKey
    event_type: str
    event_at: datetime
    related_case_key: NaturalKey | None
    description: str | None = None
    confidence: Decimal | None = None

    @property
    def natural_key(self) -> NaturalKey:
        related = _case_key_parts(self.related_case_key) if self.related_case_key else ()
        return (
            "justice_event",
            *self.person_key[1:],
            self.event_type,
            _iso(self.event_at),
            *related,
        )


ReferenceRecord = JurisdictionDraft | CourtDraft | JudgeDraft | JudgeServiceDraft
CaseLevelRecord = (
    PersonDraft
    | CaseDraft
    | CasePartyDraft
    | JudgeAssignmentDraft
    | ChargeDraft
    | CourtEventDraft
    | DecisionDraft
    | SentenceDraft
    | JusticeEventDraft
)
CanonicalRecord = ReferenceRecord | CaseLevelRecord


def describe_key(key: NaturalKey) -> str:
    """A natural key for an issue description or a log line, without any person hash.

    ``("person", "source_participant_id", <hash>)`` → ``"person by source_participant_id"``;
    ``("justice_event", <kind>, <hash>, "new_case", <at>, <court>, <type>, <number>)`` →
    ``"justice_event new_case at <at> for case <court>:<type>:<number>"``;
    every other key → ``"<type> <parts joined by :>"``.
    """
    if not key:
        return "?"
    kind = key[0]
    if kind == "person":
        return f"person by {key[1]}" if len(key) > 1 else "person"
    if kind == "justice_event":
        parts = key[3:]
        event_type = parts[0] if parts else "?"
        at = parts[1] if len(parts) > 1 else "?"
        case = ":".join(parts[2:])
        suffix = f" for case {case}" if case else ""
        return f"justice_event {event_type} at {at}{suffix}"
    return f"{kind} {':'.join(key[1:])}"


@dataclass(frozen=True, slots=True)
class Provenance:
    """The source record a draft was derived from."""

    source_record_id: uuid.UUID
    raw_sha256: str


@dataclass(frozen=True, slots=True)
class TaggedRecord:
    """A canonical draft together with its provenance (assigned by the runner)."""

    record: CanonicalRecord
    provenance: Provenance | None


class SourceConnector(Protocol):
    """The brief's connector interface, plus the identifying attributes."""

    source_id: str
    parser_version: str
    source_info: SourceInfo

    async def discover(self) -> list[SourceArtifact]: ...

    async def fetch(self, artifact: SourceArtifact) -> RawArtifact: ...

    def validate_raw(self, artifact: RawArtifact) -> ValidationResult: ...

    def parse(self, artifact: RawArtifact) -> Iterable[SourceRecordDraft]: ...

    def normalize(self, record: SourceRecordDraft) -> Iterable[CanonicalRecord]: ...


@runtime_checkable
class SupportsCheckpoint(Protocol):
    """Optional hook for incremental sources (cursors, modified timestamps).

    The runner calls ``restore_checkpoint`` with the checkpoint recorded by
    the source's last successful run before ``discover`` and stores the
    value of ``checkpoint()`` on the run afterwards.
    """

    def restore_checkpoint(self, checkpoint: Checkpoint | None) -> None: ...

    def checkpoint(self) -> Checkpoint | None: ...


@runtime_checkable
class SupportsCoverage(Protocol):
    """Optional hook for sources whose records cover a known window.

    The runner calls ``coverage_window`` once per run after
    ``load_context`` (so a connector may read it from the export itself,
    as the synthetic connector reads the manifest's corpus dates) and
    writes ``source.coverage_start`` and ``coverage_end`` when they differ.
    ``None`` leaves the columns untouched.
    """

    def coverage_window(self) -> tuple[date, date] | None: ...


@runtime_checkable
class SupportsContext(Protocol):
    """Optional hook for multi-file sources whose rows reference other files.

    The runner calls ``load_context`` once per run with the raw artifact of
    *every* discovered artifact — changed or not — before any artifact is
    validated or parsed, so a connector can build the lookup tables its
    ``normalize`` needs (a court-code index, a participant's other cases)
    from the complete export even when only one file changed. A
    connector raises ``IngestError`` here to fail the run (for example on
    a manifest whose hashes no longer match the files).
    """

    def load_context(self, artifacts: Sequence[RawArtifact]) -> None: ...
