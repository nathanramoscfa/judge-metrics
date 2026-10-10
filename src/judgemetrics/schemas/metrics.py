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
for Kaplan-Meier estimates, ``bootstrap`` for an observed-to-expected ratio,
none otherwise.

Phase 4 Step 5 serves the ``observed_expected`` kind. Its figures are the
adjusted fields every observation and compare row carries (null for every
descriptive kind): ``expected`` (the model-expected count E), ``expected_rate``
(E / n), ``ratio`` (the pooled ratio (alpha + O) / (alpha + E)), ``ratio_lower``
and ``ratio_upper`` (its 95% bootstrap interval, unbounded above, where
``lower``/``upper`` stay shares in [0, 1] and are null for this kind), and
``pooling_weight`` (E / (E + alpha)). They are withheld with the other figures
when the row is suppressed; ``suppression_reason`` (why) and ``model`` (the
fitted model it cites, ``ModelRef``) survive suppression, so a reader can
always learn which model and which rule withheld the number.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from judgemetrics.schemas.common import Page
from judgemetrics.schemas.judges import SYNTHETIC_DESCRIPTION, CourtRef

MetricKind = Literal[
    "count", "share", "windowed_rate", "survival", "distribution", "median", "observed_expected"
]
MetricSubjectType = Literal["judge", "court"]
MetricUnit = Literal["count", "share", "days", "ratio"]
IntervalMethod = Literal["wilson", "greenwood", "bootstrap"]
CompareSort = Literal["rate", "numerator", "denominator", "value", "ratio", "name"]
SuppressionReason = Literal["below_threshold", "expected_below_minimum", "model_unavailable"]
ModelStatus = Literal["fitted", "insufficient_events", "not_converged"]
SortOrder = Literal["asc", "desc"]
CorrectionTargetType = Literal["judge", "court", "case", "metric_observation"]
CorrectionStatusOut = Literal["received"]
MemberKind = Literal["decision", "charge", "court_case", "sentence", "court_event", "justice_event"]

# The interval every rate of a kind publishes (docs/METHODOLOGY.md "How to read a number").
INTERVAL_METHOD_BY_KIND: dict[str, IntervalMethod] = {
    "share": "wilson",
    "windowed_rate": "wilson",
    "survival": "greenwood",
    "observed_expected": "bootstrap",
}
# The figures a suppressed observation never carries (the reason and the model survive).
SUPPRESSED_FIELDS: tuple[str, ...] = (
    "numerator",
    "denominator",
    "rate",
    "value",
    "distribution",
    "lower",
    "upper",
    "expected",
    "expected_rate",
    "ratio",
    "ratio_lower",
    "ratio_upper",
    "pooling_weight",
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
            "assigned_ever, sentencing_judge, disposing_judge, or court_of_case."
        )
    )


class DefinitionAdjustmentOut(BaseModel):
    """An ``observed_expected`` metric's model target and minimum expected count."""

    target: str = Field(description="The outcome model specification's target the ratio reads.")
    minimum_expected: float = Field(
        ge=0.0, description="The model-expected count below which the ratio is withheld."
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
    unit: MetricUnit
    version: str = Field(description="The definition's version; bumped when its semantics change.")
    methodology_url: str = Field(description=METHODOLOGY_URL_DESCRIPTION)
    adjustment: DefinitionAdjustmentOut | None = Field(
        description="An observed-to-expected metric's model target; null for every other kind."
    )


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


class AdjustmentFeatureOut(BaseModel):
    """One feature of the expected-outcome model, as the methodology states it."""

    name: str
    description: str
    levels: str = Field(description="The levels in design order, the reference marked.")
    known_at: str = Field(description="The instant before which every value is read.")
    missing: str = Field(description="What happens to an index event without a value.")
    leakage: str = Field(description="Why the feature cannot carry the outcome.")


class AdjustmentOut(BaseModel):
    """The adjusted statistics' methodology (methodology 1.0), from the model specification.

    The same text ``docs/METHODOLOGY.md`` renders under "Adjusted statistics".
    """

    specification_version: int = Field(ge=1, description="The outcome model specification.")
    model_version: str
    intro: str
    interpretation: str = Field(description="The brief's reading of an O/E ratio, verbatim.")
    model: str = Field(description="The model, its penalty, and what it is fitted over.")
    targets: list[MethodologyTerm] = Field(description="The modelled outcomes, by target name.")
    features: list[AdjustmentFeatureOut] = Field(description="In specification order.")
    exclusions: list[MethodologyTerm] = Field(
        description="What the model never reads, each with its reason."
    )
    expected_count: str
    pooling: str = Field(description="The gamma-Poisson partial pooling: formula and weight.")
    interval: str = Field(description="The bootstrap interval and what it describes.")
    thresholds: list[MethodologyTerm] = Field(description="Each threshold and its reason.")
    controls: list[MethodologyTerm] = Field(description="The temporal and jurisdiction controls.")
    limitations: list[str] = Field(description="The limitations of adjustment.")
    validation: str = Field(description="Where the model's validation is published.")


class Registry(BaseModel):
    """The versioned metric registry the methodology page is rendered from.

    The prose sections (``how_to_read``, ``semantics``, ``attribution_notes``,
    ``changelog``, ``adjustment``) are the same constants ``docs/METHODOLOGY.md``
    is rendered from, so the web page and the committed document never diverge.
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
    adjustment: AdjustmentOut = Field(
        description="The adjusted statistics' methodology: the model, its features, "
        "the pooling, the interval, the thresholds, and the limitations of adjustment."
    )
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


class ModelRef(BaseModel):
    """The fitted outcome model an adjusted figure was computed with."""

    id: uuid.UUID
    content_hash: str = Field(
        min_length=64,
        max_length=64,
        pattern=SHA256_PATTERN,
        description="The sha256 of the model's canonical artifact: its identity.",
    )
    model_version: str
    spec_version: int = Field(ge=1, description="The outcome model specification version.")
    url: str = Field(description="The model card: `GET /api/v1/models/{id}`.")


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
    lower: float | None = Field(
        ge=0.0,
        le=1.0,
        description="The 95% interval's lower bound of a rate; null for an adjusted ratio.",
    )
    upper: float | None = Field(
        ge=0.0,
        le=1.0,
        description="The 95% interval's upper bound of a rate; null for an adjusted ratio.",
    )
    expected: float | None = Field(
        ge=0.0,
        description="The model-expected count E of an adjusted ratio; null for other kinds.",
    )
    expected_rate: float | None = Field(
        ge=0.0, le=1.0, description="E / n: the expected count over the members in the ratio."
    )
    ratio: float | None = Field(
        ge=0.0,
        description=(
            "The pooled observed-to-expected ratio (alpha + O) / (alpha + E), partially "
            "pooled toward 1; null for other kinds."
        ),
    )
    ratio_lower: float | None = Field(
        ge=0.0, description="The pooled ratio's 95% bootstrap interval, lower bound."
    )
    ratio_upper: float | None = Field(
        ge=0.0, description="The pooled ratio's 95% bootstrap interval, upper bound (unbounded)."
    )
    pooling_weight: float | None = Field(
        ge=0.0,
        le=1.0,
        description="E / (E + alpha): the weight the subject's own data carries in the ratio.",
    )
    model: ModelRef | None = Field(
        description="The outcome model an adjusted ratio cites (kept when suppressed)."
    )
    suppressed: bool = Field(
        description=(
            "True when the number is withheld (a denominator below the metric's threshold; for "
            "an adjusted ratio also too few expected events or no fitted model): every figure "
            "is withheld."
        )
    )
    suppression_threshold: int = Field(
        ge=0, description="The metric's threshold, stated so a reader knows why."
    )
    suppression_reason: SuppressionReason | None = Field(
        description=(
            "Why a suppressed row is withheld: below_threshold, expected_below_minimum, or "
            "model_unavailable; null when the row is published."
        )
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
    unit: MetricUnit
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
        description=(
            "wilson for shares and fixed-window rates, greenwood for survival estimates, "
            "bootstrap for an adjusted ratio."
        )
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


class TrainingOut(BaseModel):
    """What a model was fitted on: the index events, their outcomes, and their time range."""

    index_events: int = Field(ge=0, description="Index events (design rows) the fit is over.")
    events: int = Field(ge=0, description="Of those, the events of the target outcome.")
    start: datetime | None = Field(description="The earliest index time; null without rows.")
    end: datetime | None = Field(description="The latest index time; null without rows.")


class ProvenanceModel(ModelRef):
    """The outcome model in an adjusted observation's chain, with its artifact check."""

    target: str
    window_days: int | None
    status: ModelStatus
    training: TrainingOut
    artifact_ok: bool = Field(
        description="The artifact exists under the snapshot and hashes to the content hash."
    )


class ObservationProvenance(BaseModel):
    """The brief's chain, top-down: observation → snapshot → members → cases → records → sources."""

    observation: TracedObservation
    snapshot: SnapshotOut
    model: ProvenanceModel | None = Field(
        description="The fitted model of an adjusted observation; null for a descriptive one."
    )
    members: list[MemberGroup] = Field(description="By member kind.")
    source_records: list[SourceRecordOut] = Field(
        description="The distinct artifacts behind every member, newest retrieval first."
    )
    sources: list[SourceOut] = Field(description="The distinct source systems, by key.")
    complete: bool = Field(
        description=(
            "True when every member resolved to a canonical row and every row to a source "
            "record with its artifact digest (and, adjusted, the model's artifact holds)."
        )
    )


# --- the model card -----------------------------------------------------------------------


class CalibrationBinOut(BaseModel):
    """One decile of predicted probability on the temporal test set."""

    bin: int = Field(ge=0)
    count: int = Field(ge=0)
    mean_predicted: float | None
    observed_rate: float | None


class ModelValidationOut(BaseModel):
    """The temporal-split diagnostics: fitted before the cutoff, scored after it."""

    split_cutoff: datetime | None = Field(
        description="Index events at or after it are the test set; null without a split."
    )
    train_index_events: int = Field(ge=0)
    train_events: int = Field(ge=0)
    test_index_events: int = Field(ge=0)
    test_events: int = Field(ge=0)
    base_rate_train: float | None
    brier: float | None = Field(description="Brier score on the test set.")
    brier_skill: float | None = Field(description="1 - Brier / the base rate's Brier.")
    auc: float | None
    calibration_in_the_large: float | None
    calibration_slope: float | None
    bins: list[CalibrationBinOut] = Field(description="Ten calibration bins; empty when unfitted.")


class CoefficientOut(BaseModel):
    """One design column of the published fit."""

    column: str = Field(description="The design column's name (a data level by its rank label).")
    feature: str | None = Field(description="Null for the intercept.")
    level: str | None = Field(description="The level the column encodes.")
    reference: str | None = Field(description="The feature's reference level.")
    estimate: float | None = Field(description="The penalized log-odds coefficient.")
    sd: float | None = Field(description="Its standard deviation over the bootstrap replicates.")
    sign_agreement: float | None = Field(
        description="The share of converged replicates whose sign agrees with the estimate."
    )


class ModelCard(BaseModel):
    """One fitted outcome model, from the catalogue (never its storage location)."""

    id: uuid.UUID
    content_hash: str = Field(min_length=64, max_length=64, pattern=SHA256_PATTERN)
    snapshot_hash: str = Field(min_length=64, max_length=64, pattern=SHA256_PATTERN)
    source: str = Field(description="Source register key.")
    synthetic: bool = Field(description=SYNTHETIC_DESCRIPTION)
    target: str
    window_days: int | None = Field(description="Null for the release target.")
    spec_version: int = Field(ge=1)
    model_version: str
    seed: int
    status: ModelStatus
    fitted_at: datetime
    code_version: str
    training: TrainingOut
    validation: ModelValidationOut
    coefficients: list[CoefficientOut] = Field(description="In design order; empty when unfitted.")
    methodology_url: str = Field(description="The methodology's adjusted statistics section.")


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
    "CalibrationBinOut",
    "CoefficientOut",
    "CompareCohort",
    "ComparePage",
    "CompareRow",
    "CompareSort",
    "CorrectionAccepted",
    "CorrectionIn",
    "CorrectionTargetType",
    "DefinitionAdjustmentOut",
    "IntervalMethod",
    "MemberGroup",
    "MethodologyChange",
    "MethodologyTerm",
    "MetricDefinitionOut",
    "MetricKind",
    "MetricSubjectType",
    "MetricUnit",
    "ModelCard",
    "ModelRef",
    "ModelStatus",
    "ModelValidationOut",
    "Observation",
    "ObservationCoverage",
    "ObservationProvenance",
    "ProvenanceModel",
    "Registry",
    "SnapshotOut",
    "SortOrder",
    "SourceOut",
    "SourceRecordOut",
    "SubjectMetrics",
    "SubjectSummary",
    "SuppressibleFigures",
    "SuppressionOut",
    "SuppressionReason",
    "TracedObservation",
    "TrainingOut",
    "interval_method_for",
]
