# src/judgemetrics/schemas/metrics.py
"""Metric responses: the registry, observations, subject metrics, compare rows,
the provenance chain of an observation, and the corrections intake.

Every observation leaves the API with the brief's presentation fields —
numerator, denominator, eligible count (sample size), the period (date
range), the source's coverage window and whether the outcome is observable
in it, the interval and its method where one is defined, the suppression
flag and threshold, the methodology version, and a methodology link — and
never a person: members are entity ids and the rows carry subject ids only
(``tests/golden/test_public_contract.py`` walks every metrics route for a
person key or hash). Suppression is enforced here, at the schema layer:
whenever ``suppressed`` is true the validator nulls ``numerator``,
``denominator``, ``rate``, ``value``, ``distribution``, ``lower``, and
``upper`` whatever the caller passed, so a stored number below the
threshold cannot reach a client through any construction path; the
``eligible_count`` and the ``suppression_threshold`` stay, which is how a
reader learns why the number was withheld. ``interval_method`` follows the
metric's kind: ``wilson`` for shares and fixed-window rates, ``greenwood``
for Kaplan-Meier estimates, none otherwise.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from judgemetrics.schemas.common import Page
from judgemetrics.schemas.judges import SYNTHETIC_DESCRIPTION, CourtRef

MetricKind = Literal["count", "share", "windowed_rate", "survival", "distribution", "median"]
MetricSubjectType = Literal["judge", "court"]
IntervalMethod = Literal["wilson", "greenwood"]
CompareSort = Literal["rate", "numerator", "denominator", "value", "name"]
SortOrder = Literal["asc", "desc"]
CorrectionTargetType = Literal["judge", "court", "case", "metric_observation"]
CorrectionStatusOut = Literal["received"]
MemberKind = Literal["decision", "charge", "court_case", "sentence", "court_event", "justice_event"]

# The interval every rate of a kind publishes (docs/METHODOLOGY.md "How to read a number").
INTERVAL_METHOD_BY_KIND: dict[str, IntervalMethod] = {
    "share": "wilson",
    "windowed_rate": "wilson",
    "survival": "greenwood",
}
# The figures a suppressed observation never carries.
SUPPRESSED_FIELDS: tuple[str, ...] = (
    "numerator",
    "denominator",
    "rate",
    "value",
    "distribution",
    "lower",
    "upper",
)
METHODOLOGY_URL_DESCRIPTION = (
    "The methodology page anchored at the metric's slug: how the number is computed, "
    "its attribution rule, and the known limitations."
)
SHA256_PATTERN = r"^[0-9a-f]{64}$"


def interval_method_for(kind: str) -> IntervalMethod | None:
    return INTERVAL_METHOD_BY_KIND.get(kind)


# --- the registry ---------------------------------------------------------------------------


class AttributionOut(BaseModel):
    """A metric's structured inclusion rule (docs/METHODOLOGY.md \"Attribution\")."""

    decision_type: str | None = Field(description="The decision type a row must carry, if any.")
    actor_types: list[str] | None = Field(description="The actor types admitted, if restricted.")
    discretion: list[str] | None = Field(
        description="The discretion classifications admitted, if restricted."
    )
    assignment_gate: str = Field(
        description=(
            "How a row is tied to the subject: deciding_judge, assigned_at_time, "
            "assigned_ever, sentencing_judge, or court_of_case."
        )
    )


class MetricDefinitionOut(BaseModel):
    """One registry entry: what a number means and how it is computed."""

    slug: str
    name: str
    kind: MetricKind
    subject_types: list[MetricSubjectType]
    description: str
    numerator: str
    denominator: str
    eligibility: str
    attribution: AttributionOut
    index_event: str | None = Field(
        description="pretrial_release, disposition, or sentence for a windowed metric."
    )
    outcome: str | None = Field(description="The justice_event_type a windowed metric counts.")
    windows_days: list[int] | None = Field(description="The follow-up windows, in days.")
    dimension: str | None = Field(description="disposition or offense_category, when grouped.")
    suppression_threshold: int = Field(
        ge=0, description="The denominator below which an observation is suppressed."
    )
    unit: Literal["count", "share", "days"]
    version: str = Field(description="The definition's version; bumped when its semantics change.")
    methodology_url: str = Field(description=METHODOLOGY_URL_DESCRIPTION)


class SuppressionOut(BaseModel):
    default_threshold: int = Field(ge=0)
    rule: str
    rationale: str


class MethodologyTerm(BaseModel):
    """One term of the methodology prose: a heading and its text, rendered as text nodes."""

    term: str
    text: str


class MethodologyChange(BaseModel):
    """One methodology changelog entry."""

    version: str = Field(description="The methodology version the entry describes.")
    text: str


class Registry(BaseModel):
    """The versioned metric registry the methodology page is rendered from.

    The prose sections (``how_to_read``, ``semantics``, ``attribution_notes``,
    ``changelog``) are the same constants ``docs/METHODOLOGY.md`` is rendered
    from, so the web page and the committed document never diverge.
    """

    registry_version: int = Field(ge=1)
    methodology_version: str
    methodology_url: str = Field(description="The methodology page.")
    windows_days: list[int] = Field(
        description="The follow-up windows every windowed metric is computed over, in days."
    )
    known_limitations: list[str] = Field(
        description="The brief's statistical warnings, verbatim and never softened."
    )
    suppression: SuppressionOut
    how_to_read: list[MethodologyTerm] = Field(
        description="What each presentation field beside a number means."
    )
    semantics: list[MethodologyTerm] = Field(
        description="Index events, exposure, outcomes and windows, censoring, Kaplan-Meier."
    )
    attribution_notes: list[str] = Field(
        description="How rows are tied to a judge, and what is never attributed."
    )
    gate_descriptions: dict[str, str] = Field(
        description="Each assignment gate (`AttributionOut.assignment_gate`) in words."
    )
    changelog: list[MethodologyChange] = Field(description="Oldest version first.")
    definitions: list[MetricDefinitionOut] = Field(description="In registry order.")


# --- observations ---------------------------------------------------------------------------


class ObservationCoverage(BaseModel):
    """What the observation's source covers, and whether it can document the outcome."""

    coverage_start: date | None = Field(description="First day the source's records cover.")
    coverage_end: date | None = Field(
        description="Last day the source's records cover; follow-up is censored the day after."
    )
    observable: bool = Field(
        description=(
            "True when the source documents the metric's outcome (always true for a metric "
            "without an outcome); a metric that is not observable is never published."
        )
    )


class SuppressibleFigures(BaseModel):
    """The figures a suppressed row withholds; the validator nulls them whenever ``suppressed``."""

    numerator: int | None = Field(
        ge=0, description="The observed count: rows or members meeting the metric's condition."
    )
    denominator: int | None = Field(
        ge=0,
        description=(
            "The cohort size the numerator is divided by (the followed members of a "
            "fixed-window rate; the whole cohort of a survival estimate; the attributed rows "
            "of a share; the values a median is taken over; the population of a count)."
        ),
    )
    rate: float | None = Field(
        ge=0.0,
        le=1.0,
        description=(
            "numerator / denominator for a share or fixed-window rate; 1 - S(w) for a "
            "survival estimate; six decimals; null for counts, distributions, and medians."
        ),
    )
    value: float | None = Field(description="A median, in days; null for every other kind.")
    distribution: dict[str, int] | None = Field(
        description="The whole map of a distribution (vocabulary value → count); null otherwise."
    )
    lower: float | None = Field(ge=0.0, le=1.0, description="The 95% interval's lower bound.")
    upper: float | None = Field(ge=0.0, le=1.0, description="The 95% interval's upper bound.")
    suppressed: bool = Field(
        description=(
            "True when the denominator is below the metric's suppression threshold: the "
            "numerator, denominator, rate, value, distribution, and interval are withheld."
        )
    )
    suppression_threshold: int = Field(
        ge=0, description="The metric's threshold, stated so a reader knows why."
    )

    @model_validator(mode="after")
    def _withhold_when_suppressed(self) -> Self:
        if self.suppressed:
            for name in SUPPRESSED_FIELDS:
                setattr(self, name, None)
        return self


class Observation(SuppressibleFigures):
    """One current metric observation with every presentation field."""

    id: uuid.UUID
    slug: str
    name: str = Field(description="The metric's name from the registry.")
    kind: MetricKind
    unit: Literal["count", "share", "days"]
    version: str = Field(description="The definition version the observation was computed under.")
    subject_type: MetricSubjectType
    subject_id: uuid.UUID
    source: str = Field(description="Source register key (docs/DATA_SOURCES.md).")
    synthetic: bool = Field(description=SYNTHETIC_DESCRIPTION)
    period_start: date = Field(description="The observation's date range: the source's window.")
    period_end: date
    window_days: int | None = Field(description="The follow-up window of a windowed metric.")
    dimension_value: str | None = Field(description="The group of a dimensioned metric.")
    eligible_count: int = Field(
        ge=0,
        description=(
            "Sample size: the whole cohort before any follow-up restriction, published even "
            "when the number is suppressed."
        ),
    )
    interval_method: IntervalMethod | None = Field(
        description="wilson for shares and fixed-window rates, greenwood for survival estimates."
    )
    coverage: ObservationCoverage
    methodology_version: str
    methodology_url: str = Field(description=METHODOLOGY_URL_DESCRIPTION)
    snapshot_hash: str = Field(
        min_length=64,
        max_length=64,
        pattern=SHA256_PATTERN,
        description="The content hash of the exported tables the number was computed from.",
    )
    computed_at: datetime


class SubjectSummary(BaseModel):
    subject_type: MetricSubjectType
    id: uuid.UUID
    canonical_name: str
    synthetic: bool = Field(description=SYNTHETIC_DESCRIPTION)


class SubjectMetrics(BaseModel):
    """Every current observation of a judge or court, grouped by metric slug."""

    subject: SubjectSummary
    registry_version: int
    methodology_version: str
    methodology_url: str = Field(description="The methodology page.")
    total: int = Field(ge=0, description="Observations across every slug.")
    observations: dict[str, list[Observation]] = Field(
        description=(
            "By metric slug, each list ordered by window, dimension value, and source; a "
            "metric the source cannot observe has no entry."
        )
    )


# --- compare ---------------------------------------------------------------------------------


class CompareCohort(BaseModel):
    """What the rows are compared within."""

    metric: str = Field(description="The metric slug.")
    version: str = Field(description="The definition version compared.")
    window_days: int | None
    court_id: uuid.UUID | None
    jurisdiction_id: uuid.UUID | None
    name: str = Field(description="The court's or jurisdiction's name.")
    period_start: date | None = Field(
        description=(
            "The cohort's reference period: the requested one, else the period most rows of "
            "the whole cohort share; null when the cohort has no row."
        )
    )
    period_end: date | None
    sort: CompareSort
    order: SortOrder


class CompareRow(SuppressibleFigures):
    """One judge's observation of the compared metric."""

    subject_id: uuid.UUID
    name: str = Field(description="The judge's canonical name.")
    court: CourtRef = Field(description="The judge's court within the cohort.")
    synthetic: bool = Field(description=SYNTHETIC_DESCRIPTION)
    observation_id: uuid.UUID
    source: str
    period_start: date
    period_end: date
    window_days: int | None
    dimension_value: str | None
    eligible_count: int = Field(ge=0, description="Sample size before any follow-up restriction.")
    interval_method: IntervalMethod | None
    coverage_warning: str | None = Field(
        description=(
            "Set when the judge's coverage window differs from the cohort's reference period, "
            "or the source cannot document the metric's outcome."
        )
    )


class ComparePage(Page[CompareRow]):
    """A sorted, paginated compare table with its cohort and methodology metadata."""

    cohort: CompareCohort
    methodology_version: str
    methodology_url: str = Field(description=METHODOLOGY_URL_DESCRIPTION)


# --- provenance ---------------------------------------------------------------------------


class TracedObservation(Observation):
    """The observation at the top of a provenance chain, with its versions."""

    registry_version: int
    code_version: str = Field(description="The package version and git SHA that computed it.")
    superseded_at: datetime | None = Field(
        description="Null for a current observation (the only kind the API traces)."
    )


class SnapshotOut(BaseModel):
    """The hashed export the observation was computed from."""

    content_hash: str = Field(min_length=64, max_length=64, pattern=SHA256_PATTERN)
    label: str | None
    exported_at: datetime
    code_version: str
    registry_version: int
    methodology_version: str
    row_counts: dict[str, int] = Field(description="Rows per exported table.")


class MemberGroup(BaseModel):
    """The observation's members of one kind: the eligible canonical rows behind the number."""

    member_kind: MemberKind
    members: int = Field(ge=0, description="Rows of this kind behind the observation.")
    counted: int = Field(ge=0, description="Members in the numerator.")
    followed: int = Field(ge=0, description="Members in the denominator after censoring.")
    resolved: int = Field(
        ge=0,
        description="Members whose canonical row still exists; equals `members` when complete.",
    )
    case_ids: list[uuid.UUID] = Field(
        description="The distinct cases the members belong to (`/cases/{id}`), sorted."
    )


class SourceRecordOut(BaseModel):
    """One retrieved raw artifact behind the members."""

    id: uuid.UUID
    source: str = Field(description="Source register key.")
    external_record_id: str | None = Field(description="The artifact's id at the source.")
    raw_sha256: str = Field(min_length=64, max_length=64, pattern=SHA256_PATTERN)
    retrieved_at: datetime
    parser_version: str
    ingest_run_id: uuid.UUID
    artifact_uri: str | None = Field(
        description=(
            "Where the artifact was fetched from, when that is a public http(s) URL; null "
            "for an artifact read from the operator's filesystem (a fixture or the synthetic "
            "dataset)."
        )
    )


class SourceOut(BaseModel):
    """The source system a record came from."""

    source: str = Field(description="Source register key.")
    owner: str
    source_type: str
    synthetic: bool = Field(description=SYNTHETIC_DESCRIPTION)
    coverage_start: date | None
    coverage_end: date | None
    observable_outcomes: list[str]


class ObservationProvenance(BaseModel):
    """The brief's chain, top-down: observation → snapshot → members → cases → records → sources."""

    observation: TracedObservation
    snapshot: SnapshotOut
    members: list[MemberGroup] = Field(description="By member kind.")
    source_records: list[SourceRecordOut] = Field(
        description="The distinct artifacts behind every member, newest retrieval first."
    )
    sources: list[SourceOut] = Field(description="The distinct source systems, by key.")
    complete: bool = Field(
        description=(
            "True when every member resolved to a canonical row and every row to a source "
            "record with its artifact digest."
        )
    )


# --- corrections ----------------------------------------------------------------------------


class CorrectionIn(BaseModel):
    """A public data-correction request. The contact is encrypted before it is stored."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    target_type: CorrectionTargetType
    target_id: uuid.UUID
    reason: str = Field(
        min_length=20, max_length=4000, description="What is wrong and what the record should say."
    )
    contact: str = Field(
        min_length=3,
        max_length=320,
        description="How to reach the requester about this request; stored encrypted.",
    )
    supporting_material: HttpUrl | None = Field(
        default=None, description="An optional http(s) link to supporting material."
    )

    @field_validator("supporting_material")
    @classmethod
    def _bounded_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and len(str(value)) > 2000:
            msg = "must be at most 2000 characters"
            raise ValueError(msg)
        return value

    @field_validator("reason", "contact")
    @classmethod
    def _printable(cls, value: str) -> str:
        if any(ch.isspace() and ch not in " \n\r\t" for ch in value) or any(
            ord(ch) < 32 and ch not in "\n\r\t" for ch in value
        ):
            msg = "must not contain control characters"
            raise ValueError(msg)
        return value


class CorrectionAccepted(BaseModel):
    """The acknowledgement: the request's id and status, nothing the requester submitted."""

    id: uuid.UUID
    status: CorrectionStatusOut
    received_at: datetime


__all__ = [
    "INTERVAL_METHOD_BY_KIND",
    "SUPPRESSED_FIELDS",
    "AttributionOut",
    "CompareCohort",
    "ComparePage",
    "CompareRow",
    "CompareSort",
    "CorrectionAccepted",
    "CorrectionIn",
    "CorrectionTargetType",
    "IntervalMethod",
    "MemberGroup",
    "MethodologyChange",
    "MethodologyTerm",
    "MetricDefinitionOut",
    "MetricKind",
    "MetricSubjectType",
    "Observation",
    "ObservationCoverage",
    "ObservationProvenance",
    "Registry",
    "SnapshotOut",
    "SortOrder",
    "SourceOut",
    "SourceRecordOut",
    "SubjectMetrics",
    "SubjectSummary",
    "SuppressibleFigures",
    "SuppressionOut",
    "TracedObservation",
    "interval_method_for",
]
