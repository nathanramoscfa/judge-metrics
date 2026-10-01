# src/judgemetrics/metrics/adjustment/features.py
"""The design rows of the expected-outcome model: one row per eligible index event.

``design_rows(frame, spec, target, window)`` returns a ``DesignFrame``:

1. **Index events** (``target_events``). The release target's rows are the
   pretrial decisions the population metric's rule attributes to any judge
   of the frame (``attribution.pretrial_decisions_for``, judge by judge, so
   the gate is exactly the published ``pretrial_decisions`` gate), its
   outcome ``released`` (``detained_flag`` false; a null flag is no row) and
   its index time the decision. A windowed target's rows are the
   pretrial-release cohort (``index_events``) with its exposure
   (``with_exposure``) and first outcome (``first_outcomes``), kept when
   followed for the window (``censoring.member_windows``), the outcome being
   the fixed-window rate's numerator membership. An outcome the source cannot
   document yields ``windows.NotObservable`` and no rows.
2. **Feature levels** (``feature_levels``), each computed only from rows
   strictly before its known-at instant: the index case's charges against
   the person filed before the pretrial decision (``lead_severity``,
   ``lead_category`` — ties on severity broken by the source's charge id —
   and ``charge_count``); the person's other cases, convictions, failures
   to appear, and pending cases strictly before the index case's filing
   (00:00 UTC of its filing date, the frame's ``cases.filed_at``), a case
   counting as pending when, among its charges filed before that instant,
   one was pending then (disposed at or after it, or still pending) or none
   was disposed before it — charges without a recorded disposition are
   ignored; ``history_truncated`` (the filing within ``lookback_days`` of
   the coverage start); the court and its jurisdiction; the index event's
   calendar year. A feature whose ``requires_outcome`` the source cannot
   document is dropped.
3. **The missing rule**: a null level drops the row (``missing: exclude``)
   or becomes the feature's ``missing_level`` (``missing: level``), and the
   row is flagged for Step 4's complete-case refit.
4. **Encoding**: fixed levels in the specification's order; data levels
   (court, jurisdiction, year) ordered by their number of rows and then by
   a source-assigned key — a court's earliest charge (filing time, then the
   source's charge id), a jurisdiction's earliest court key, the year
   itself — never by a canonical id, and labelled by rank (courts,
   jurisdictions) or year; the reference is the specification's (the
   busiest level for data levels) and is dropped, as is any column with no
   row (an unobserved level).
5. **Order**: rows sort by the index time, the index case's earliest charge
   (``source_row_id``), the person's cluster key — the merged person's
   earliest charge, ``<filing time>|<source_row_id>`` — the outcome, and the
   encoded labels, so the matrix (float64, the intercept first) depends on
   the data and the source's keys alone: relabelling every canonical id
   leaves it identical.

Every group-by is sorted explicitly afterwards (Polars does not keep group
order by default). No function reads a restricted table; the design rows,
the cluster keys, and the member ids exist in memory only, inside a fit,
and are never written or logged.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from types import MappingProxyType

import numpy as np
import numpy.typing as npt
import polars as pl

from judgemetrics.metrics.adjustment.spec import (
    DECISION,
    EXCLUDE,
    FEATURE_CONTRACTS,
    UNSEEN_LATEST,
    FeatureSpec,
    OutcomeModelSpec,
    TargetSpec,
)
from judgemetrics.metrics.attribution import JUDGE, AttributionRule, Subject, pretrial_decisions_for
from judgemetrics.metrics.censoring import member_windows
from judgemetrics.metrics.compute import subjects_of
from judgemetrics.metrics.exposure import with_exposure
from judgemetrics.metrics.frame import Frame
from judgemetrics.metrics.index_events import PRETRIAL_RELEASE, index_events
from judgemetrics.metrics.registry import load_registry
from judgemetrics.metrics.windows import MEMBER_KEY, NotObservable, first_outcomes, not_observable
from judgemetrics.normalization import vocabulary

FloatArray = npt.NDArray[np.float64]
ROW = "_row"
FILED = "_filed_at"
COURT = "_court_id"
CHARGE_FILED = "_charge_filed"
OTHER_CASE = "_other_case"
OTHER_FILED = "_other_filed"
RANK = "_rank"
VALUE = "value"
CASE_KEY = "_case_key"
CLUSTER_KEY = "_cluster_key"
SUBJECT = "_subject"
OUTCOME = "_outcome"
INTERCEPT = "intercept"
PENDING = "pending"
FAILURE_TO_APPEAR = "failure_to_appear"
CONVICTED_DISPOSITIONS: tuple[str, ...] = ("convicted_plea", "convicted_verdict")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%.6f"
# The columns every index-event table carries into the feature builders.
EVENT_COLUMNS: tuple[str, ...] = (
    "member_id",
    "case_id",
    "person_id",
    SUBJECT,
    "decision_at",
    "index_at",
    OUTCOME,
)


class FeatureError(ValueError):
    """A design cannot be built as the specification states (a frame or spec defect)."""


@dataclass(frozen=True, slots=True)
class DesignColumn:
    """One column of the design matrix: ``<feature>=<level>``, or the intercept."""

    name: str
    feature: str | None
    level: str | None


@dataclass(frozen=True, slots=True)
class DroppedFeature:
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class FeatureEncoding:
    """A feature's levels in design order, its reference, and (data levels) the raw values.

    ``keys`` maps a data level's label to the frame value it stands for (a
    court id): it lives in memory only and never enters an artifact.
    """

    feature: str
    levels: tuple[str, ...]
    reference: str
    keys: Mapping[str, str]
    unseen: str | None = None

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(level for level in self.levels if level != self.reference)


@dataclass(frozen=True, slots=True)
class DesignFrame:
    """The design of one target and window over one source's frame (in memory only)."""

    target: str
    window_days: int | None
    columns: tuple[DesignColumn, ...]
    matrix: FloatArray
    outcome: FloatArray
    index_at: npt.NDArray[np.int64]
    clusters: tuple[str, ...]
    missing: npt.NDArray[np.bool_]
    member_ids: tuple[str, ...]
    judge_ids: tuple[str, ...]
    levels: pl.DataFrame
    encodings: tuple[FeatureEncoding, ...]
    dropped: tuple[DroppedFeature, ...]
    unobserved: tuple[str, ...]
    eligible: int
    excluded_missing: int

    @property
    def rows(self) -> int:
        return int(self.matrix.shape[0])

    @property
    def width(self) -> int:
        return int(self.matrix.shape[1])

    @property
    def events(self) -> int:
        return int(self.outcome.sum())

    @property
    def persons(self) -> int:
        return len(set(self.clusters))

    def encoding(self, feature: str) -> FeatureEncoding:
        for encoding in self.encodings:
            if encoding.feature == feature:
                return encoding
        msg = f"the design has no feature {feature!r}"
        raise FeatureError(msg)


# --- index events ------------------------------------------------------------------------


def _judges(frame: Frame) -> list[str]:
    return [str(s.subject_id) for s in subjects_of(frame) if s.subject_type == JUDGE]


def _empty_events(frame: Frame) -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "member_id": frame.id_dtype,
            "case_id": frame.id_dtype,
            "person_id": frame.id_dtype,
            SUBJECT: frame.id_dtype,
            "decision_at": pl.Datetime("us", "UTC"),
            "index_at": pl.Datetime("us", "UTC"),
            OUTCOME: pl.Int8(),
        }
    )


def _decision_events(frame: Frame, rule: AttributionRule) -> pl.DataFrame:
    parts = [
        pretrial_decisions_for(frame, JUDGE, judge, rule).with_columns(
            pl.lit(judge, dtype=frame.id_dtype).alias(SUBJECT)
        )
        for judge in _judges(frame)
    ]
    if not parts:
        return _empty_events(frame)
    rows = (
        pl.concat(parts)
        .unique(subset=["id"], keep="first", maintain_order=True)
        .filter(pl.col("detained_flag").is_not_null())
    )
    return rows.select(
        pl.col("id").alias("member_id"),
        "case_id",
        "person_id",
        SUBJECT,
        pl.col("decision_at").cast(pl.Datetime("us", "UTC")),
        pl.col("decision_at").cast(pl.Datetime("us", "UTC")).alias("index_at"),
        (~pl.col("detained_flag")).cast(pl.Int8).alias(OUTCOME),
    )


def _release_events(
    frame: Frame, rule: AttributionRule, outcome: str, window_days: int
) -> pl.DataFrame:
    parts = [
        index_events(frame, PRETRIAL_RELEASE, rule, Subject(JUDGE, judge)).with_columns(
            pl.lit(judge, dtype=frame.id_dtype).alias(SUBJECT)
        )
        for judge in _judges(frame)
    ]
    if not parts:
        return _empty_events(frame)
    index = pl.concat(parts).unique(subset=list(MEMBER_KEY), keep="first", maintain_order=True)
    subjects = index.select(*MEMBER_KEY, SUBJECT)
    cohort = with_exposure(frame, index.drop(SUBJECT), PRETRIAL_RELEASE)
    firsts = first_outcomes(frame, cohort, outcome)
    flags = member_windows(firsts, frame.coverage_end_exclusive_at, (window_days,)).filter(
        pl.col("followed")
    )
    decisions = frame.decisions.select(pl.col("id").alias("member_id"), "decision_at")
    rows = (
        firsts.join(flags, on=list(MEMBER_KEY), how="inner")
        .join(subjects, on=list(MEMBER_KEY), how="left")
        .join(decisions, on="member_id", how="left")
    )
    return rows.select(
        "member_id",
        "case_id",
        "person_id",
        SUBJECT,
        pl.col("decision_at").cast(pl.Datetime("us", "UTC")),
        pl.col("index_at").cast(pl.Datetime("us", "UTC")),
        pl.col("counted").cast(pl.Int8).alias(OUTCOME),
    )


def target_events(
    frame: Frame, target: TargetSpec, window_days: int | None
) -> pl.DataFrame | NotObservable:
    """The eligible index events of a target (``EVENT_COLUMNS``), or ``NotObservable``."""
    rule = AttributionRule.from_spec(load_registry()[target.population].attribution)
    if target.index == DECISION:
        return _decision_events(frame, rule)
    blocked = not_observable(frame, target.outcome)
    if blocked is not None:
        return blocked
    if window_days is None:
        msg = f"target {target.name} needs a window"
        raise FeatureError(msg)
    return _release_events(frame, rule, target.outcome, window_days)


# --- feature levels ----------------------------------------------------------------------


def _band(feature: FeatureSpec, count: pl.Expr) -> pl.Expr:
    """``count`` as its band label (the largest lower bound at or below it)."""
    bands = feature.bands or ()
    labels = feature.band_labels
    expression = pl.lit(labels[0])
    for low, label in zip(bands[1:], labels[1:], strict=True):
        expression = pl.when(count >= low).then(pl.lit(label)).otherwise(expression)
    return expression


def _with_history_null(base: pl.DataFrame, values: pl.DataFrame) -> pl.DataFrame:
    """``(_row, value)`` for every base row: unknown (null) where the filing time is unknown."""
    joined = base.select(ROW, FILED).join(values, on=ROW, how="left")
    return joined.select(
        ROW, pl.when(pl.col(FILED).is_null()).then(None).otherwise(pl.col(VALUE)).alias(VALUE)
    )


def _index_charges(frame: Frame, base: pl.DataFrame) -> pl.DataFrame:
    """The index case's charges against the person filed strictly before the decision."""
    charges = frame.charges.select(
        "case_id",
        "person_id",
        pl.col("filed_at").alias(CHARGE_FILED),
        "severity",
        "offense_category",
        "source_row_id",
    )
    return (
        base.select(ROW, "case_id", "person_id", "decision_at")
        .join(charges, on=["case_id", "person_id"], how="inner")
        .filter(pl.col(CHARGE_FILED) < pl.col("decision_at"))
    )


def _lead_charges(frame: Frame, base: pl.DataFrame) -> pl.DataFrame:
    order = {severity: rank for rank, severity in enumerate(vocabulary.values("severity"))}
    ranked = _index_charges(frame, base).with_columns(
        pl.col("severity").replace_strict(order, default=len(order)).alias(RANK)
    )
    return ranked.sort([ROW, RANK, "source_row_id"], nulls_last=True).unique(
        subset=[ROW], keep="first", maintain_order=True
    )


def lead_severity(frame: Frame, feature: FeatureSpec, base: pl.DataFrame) -> pl.DataFrame:
    return _lead_charges(frame, base).select(ROW, pl.col("severity").alias(VALUE))


def lead_category(frame: Frame, feature: FeatureSpec, base: pl.DataFrame) -> pl.DataFrame:
    return _lead_charges(frame, base).select(ROW, pl.col("offense_category").alias(VALUE))


def charge_count(frame: Frame, feature: FeatureSpec, base: pl.DataFrame) -> pl.DataFrame:
    counts = _index_charges(frame, base).group_by(ROW).agg(pl.len().alias("_count")).sort(ROW)
    return counts.select(ROW, _band(feature, pl.col("_count")).alias(VALUE))


def _earlier_cases(frame: Frame, base: pl.DataFrame) -> pl.DataFrame:
    """Per row, the person's other cases filed strictly before the index case's filing."""
    person_cases = (
        frame.charges.select("person_id", pl.col("case_id").alias(OTHER_CASE))
        .unique()
        .sort(["person_id", OTHER_CASE])
    )
    filings = frame.cases.select(
        pl.col("id").alias(OTHER_CASE), pl.col("filed_at").alias(OTHER_FILED)
    )
    return (
        base.select(ROW, "case_id", "person_id", FILED)
        .join(person_cases, on="person_id", how="inner")
        .filter(pl.col(OTHER_CASE) != pl.col("case_id"))
        .join(filings, on=OTHER_CASE, how="inner")
        .filter(pl.col(OTHER_FILED) < pl.col(FILED))
    )


def _counted(base: pl.DataFrame, counts: pl.DataFrame, feature: FeatureSpec) -> pl.DataFrame:
    """Band every row's count (zero when the row has none), unknown without a filing time."""
    full = (
        base.select(ROW)
        .join(counts, on=ROW, how="left")
        .with_columns(pl.col("_count").fill_null(0))
    )
    return _with_history_null(base, full.select(ROW, _band(feature, pl.col("_count")).alias(VALUE)))


def prior_cases(frame: Frame, feature: FeatureSpec, base: pl.DataFrame) -> pl.DataFrame:
    counts = (
        _earlier_cases(frame, base)
        .group_by(ROW)
        .agg(pl.col(OTHER_CASE).n_unique().alias("_count"))
        .sort(ROW)
    )
    return _counted(base, counts, feature)


def _earlier_charges(frame: Frame, base: pl.DataFrame) -> pl.DataFrame:
    """The person's charges in those earlier cases, filed strictly before the filing."""
    charges = frame.charges.select(
        "person_id",
        pl.col("case_id").alias(OTHER_CASE),
        pl.col("filed_at").alias(CHARGE_FILED),
        "disposition",
        "disposed_at",
    )
    return (
        _earlier_cases(frame, base)
        .join(charges, on=["person_id", OTHER_CASE], how="inner")
        .filter(pl.col(CHARGE_FILED) < pl.col(FILED))
    )


def prior_convictions(frame: Frame, feature: FeatureSpec, base: pl.DataFrame) -> pl.DataFrame:
    convicted = _earlier_charges(frame, base).filter(
        pl.col("disposition").is_in(list(CONVICTED_DISPOSITIONS))
        & pl.col("disposed_at").is_not_null()
        & (pl.col("disposed_at") < pl.col(FILED))
    )
    counts = convicted.group_by(ROW).agg(pl.col(OTHER_CASE).n_unique().alias("_count")).sort(ROW)
    return _counted(base, counts, feature)


def prior_failures_to_appear(
    frame: Frame, feature: FeatureSpec, base: pl.DataFrame
) -> pl.DataFrame:
    events = frame.justice_events.filter(pl.col("event_type") == FAILURE_TO_APPEAR).select(
        "person_id", "event_at"
    )
    counts = (
        base.select(ROW, "person_id", FILED)
        .join(events, on="person_id", how="inner")
        .filter(pl.col("event_at") < pl.col(FILED))
        .group_by(ROW)
        .agg(pl.len().alias("_count"))
        .sort(ROW)
    )
    return _counted(base, counts, feature)


def pending_case(frame: Frame, feature: FeatureSpec, base: pl.DataFrame) -> pl.DataFrame:
    recorded = pl.col("disposition").is_not_null() & (pl.col("disposition") != PENDING)
    disposed_before = (
        recorded & pl.col("disposed_at").is_not_null() & (pl.col("disposed_at") < pl.col(FILED))
    )
    open_then = (pl.col("disposition") == PENDING) | (
        recorded & pl.col("disposed_at").is_not_null() & (pl.col("disposed_at") >= pl.col(FILED))
    )
    per_case = (
        _earlier_charges(frame, base)
        .group_by([ROW, OTHER_CASE])
        .agg(
            disposed_before.any().alias("_disposed"),
            open_then.fill_null(False).any().alias("_open"),
        )
        .sort([ROW, OTHER_CASE])
    )
    pending = (
        per_case.with_columns((~pl.col("_disposed") | pl.col("_open")).alias("_pending"))
        .group_by(ROW)
        .agg(pl.col("_pending").any())
        .sort(ROW)
    )
    full = (
        base.select(ROW)
        .join(pending, on=ROW, how="left")
        .select(
            ROW,
            pl.when(pl.col("_pending").fill_null(False))
            .then(pl.lit("true"))
            .otherwise(pl.lit("false"))
            .alias(VALUE),
        )
    )
    return _with_history_null(base, full)


def history_truncated(frame: Frame, feature: FeatureSpec, base: pl.DataFrame) -> pl.DataFrame:
    start = datetime.combine(frame.coverage_start, time.min, UTC)
    limit = start + timedelta(days=feature.lookback_days or 0)
    values = base.select(
        ROW,
        pl.when(pl.col(FILED) < pl.lit(limit, dtype=pl.Datetime("us", "UTC")))
        .then(pl.lit("true"))
        .otherwise(pl.lit("false"))
        .alias(VALUE),
    )
    return _with_history_null(base, values)


def court(frame: Frame, feature: FeatureSpec, base: pl.DataFrame) -> pl.DataFrame:
    return base.select(ROW, pl.col(COURT).cast(pl.String).alias(VALUE))


def jurisdiction(frame: Frame, feature: FeatureSpec, base: pl.DataFrame) -> pl.DataFrame:
    courts = frame.courts.select(pl.col("id").alias(COURT), "jurisdiction_id")
    return (
        base.select(ROW, COURT)
        .join(courts, on=COURT, how="left")
        .select(ROW, pl.col("jurisdiction_id").cast(pl.String).alias(VALUE))
    )


def calendar_year(frame: Frame, feature: FeatureSpec, base: pl.DataFrame) -> pl.DataFrame:
    return base.select(ROW, pl.col("index_at").dt.year().cast(pl.String).alias(VALUE))


Builder = Callable[[Frame, FeatureSpec, pl.DataFrame], pl.DataFrame]
FEATURE_BUILDERS: Mapping[str, Builder] = MappingProxyType(
    {
        "lead_severity": lead_severity,
        "lead_category": lead_category,
        "charge_count": charge_count,
        "prior_cases": prior_cases,
        "prior_convictions": prior_convictions,
        "prior_failures_to_appear": prior_failures_to_appear,
        "pending_case": pending_case,
        "history_truncated": history_truncated,
        "court": court,
        "jurisdiction": jurisdiction,
        "calendar_year": calendar_year,
    }
)
if set(FEATURE_BUILDERS) != set(FEATURE_CONTRACTS):  # pragma: no cover - an import-time defect
    raise FeatureError("every feature contract needs a builder and every builder a contract")


def active_features(
    frame: Frame, spec: OutcomeModelSpec
) -> tuple[list[FeatureSpec], list[DroppedFeature]]:
    """The features this frame can carry and those dropped for an unobservable outcome."""
    active: list[FeatureSpec] = []
    dropped: list[DroppedFeature] = []
    for feature in spec.features:
        required = feature.requires_outcome
        if required is not None and required not in frame.observable_outcomes:
            dropped.append(
                DroppedFeature(feature.name, f"the source does not document {required} events")
            )
        else:
            active.append(feature)
    return active, dropped


def feature_levels(frame: Frame, spec: OutcomeModelSpec, events: pl.DataFrame) -> pl.DataFrame:
    """``_row`` plus one String column per active feature: its level, null where unknown.

    ``events`` carries ``_row``, ``case_id``, ``person_id``, ``decision_at``,
    and ``index_at``; every value is computed from rows strictly before the
    feature's known-at instant (see the module docstring).
    """
    cases = frame.cases.select(
        pl.col("id").alias("case_id"),
        pl.col("filed_at").alias(FILED),
        pl.col("court_id").alias(COURT),
    )
    base = events.select(ROW, "case_id", "person_id", "decision_at", "index_at").join(
        cases, on="case_id", how="left"
    )
    result = base.select(ROW).sort(ROW)
    active, _ = active_features(frame, spec)
    for feature in active:
        values = FEATURE_BUILDERS[feature.name](frame, feature, base)
        result = result.join(
            values.select(ROW, pl.col(VALUE).cast(pl.String).alias(feature.name)),
            on=ROW,
            how="left",
        )
    return result.sort(ROW)


# --- the missing rule, encoding, order -----------------------------------------------------


def _source_keys(frame: Frame) -> tuple[dict[str, str], dict[str, str]]:
    """Per court and per jurisdiction: the earliest charge's ``<filing time>|<charge id>``."""
    charges = frame.charges.select(
        "case_id",
        pl.format(
            "{}|{}",
            pl.col("filed_at").dt.to_string(TIME_FORMAT),
            pl.col("source_row_id").fill_null(""),
        ).alias("_key"),
    )
    court_keys = (
        frame.cases.select(pl.col("id").alias("case_id"), "court_id")
        .join(charges, on="case_id", how="inner")
        .group_by("court_id")
        .agg(pl.col("_key").min())
        .sort("court_id")
    )
    courts = {str(row[0]): str(row[1]) for row in court_keys.iter_rows()}
    jurisdictions: dict[str, str] = {}
    for court_id, jurisdiction_id in frame.courts.select("id", "jurisdiction_id").iter_rows():
        key = courts.get(str(court_id))
        if key is None or jurisdiction_id is None:
            continue
        current = jurisdictions.get(str(jurisdiction_id))
        if current is None or key < current:
            jurisdictions[str(jurisdiction_id)] = key
    return courts, jurisdictions


def _data_encoding(
    feature: FeatureSpec, values: pl.Series, source_keys: Mapping[str, str]
) -> tuple[FeatureEncoding, dict[str, str]]:
    """Order a data-level feature's values by count and source key; label them."""
    missing = feature.missing_level
    counts: dict[str, int] = {}
    for value in values.to_list():
        if value is None or value == missing:
            continue
        counts[str(value)] = counts.get(str(value), 0) + 1
    ordered_year = feature.unseen == UNSEEN_LATEST

    def sort_key(value: str) -> tuple[int, int, str]:
        if ordered_year:
            return (-counts[value], int(value), "")
        return (-counts[value], 0, source_keys.get(value, ""))

    ranked = sorted(counts, key=sort_key)
    labels = {value: (value if ordered_year else str(rank)) for rank, value in enumerate(ranked, 1)}
    levels = tuple(labels[value] for value in ranked)
    if missing is not None:
        levels = (*levels, missing)
        labels[missing] = missing
    reference = levels[0] if levels else ""
    keys = {label: value for value, label in labels.items() if value != missing}
    encoding = FeatureEncoding(
        feature=feature.name,
        levels=levels,
        reference=reference,
        keys=MappingProxyType(keys),
        unseen=feature.unseen,
    )
    return encoding, labels


def encode(levels: pl.DataFrame, columns: Sequence[DesignColumn]) -> FloatArray:
    """The design matrix of encoded ``levels`` for ``columns`` (the intercept is ones)."""
    if not columns:
        return np.zeros((levels.height, 0), dtype=np.float64)
    expressions = [
        pl.lit(1.0).alias(column.name)
        if column.feature is None
        else (pl.col(column.feature) == column.level)
        .fill_null(False)
        .cast(pl.Float64)
        .alias(column.name)
        for column in columns
    ]
    matrix = levels.select(expressions).to_numpy()
    return np.ascontiguousarray(matrix, dtype=np.float64).reshape(levels.height, len(columns))


def _keys(frame: Frame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Per case its earliest charge's source id; per person the cluster key."""
    ordered = frame.charges.select(
        "case_id",
        "person_id",
        "filed_at",
        pl.col("source_row_id").fill_null(""),
    ).sort(["filed_at", "source_row_id"], nulls_last=True)
    case_keys = ordered.unique(subset=["case_id"], keep="first", maintain_order=True).select(
        "case_id", pl.col("source_row_id").alias(CASE_KEY)
    )
    cluster_keys = ordered.unique(subset=["person_id"], keep="first", maintain_order=True).select(
        "person_id",
        pl.format(
            "{}|{}", pl.col("filed_at").dt.to_string(TIME_FORMAT), pl.col("source_row_id")
        ).alias(CLUSTER_KEY),
    )
    return case_keys, cluster_keys


def _microseconds(column: pl.Series) -> npt.NDArray[np.int64]:
    values = column.cast(pl.Datetime("us", "UTC")).dt.epoch("us").fill_null(0)
    return np.ascontiguousarray(values.to_numpy(), dtype=np.int64)


def instant(microseconds: int) -> datetime:
    """A design row's index time back as an aware UTC datetime."""
    return EPOCH + timedelta(microseconds=int(microseconds))


def design_rows(
    frame: Frame, spec: OutcomeModelSpec, target: TargetSpec, window_days: int | None
) -> DesignFrame | NotObservable:
    """The design of ``target`` (and ``window_days``) over the frame (see the module docstring)."""
    events = target_events(frame, target, window_days)
    if isinstance(events, NotObservable):
        return events
    events = events.with_row_index(ROW)
    levels = feature_levels(frame, spec, events)
    active, dropped = active_features(frame, spec)
    eligible = levels.height

    # The missing rule: exclude the row, or take the feature's missing level.
    keep = pl.lit(True)
    flagged = pl.lit(False)
    for feature in active:
        if feature.missing == EXCLUDE:
            keep = keep & pl.col(feature.name).is_not_null()
        else:
            flagged = flagged | pl.col(feature.name).is_null()
    levels = levels.with_columns(flagged.alias("_missing")).filter(keep)
    levels = levels.with_columns(
        pl.col(feature.name).fill_null(pl.lit(feature.missing_level))
        for feature in active
        if feature.missing_level is not None
    )

    # Encoding: fixed levels from the specification, data levels from the rows.
    court_keys, jurisdiction_keys = _source_keys(frame)
    encodings: list[FeatureEncoding] = []
    for feature in active:
        if feature.data_levels:
            source_keys = court_keys if feature.name == "court" else jurisdiction_keys
            encoding, labels = _data_encoding(feature, levels[feature.name], source_keys)
            levels = levels.with_columns(
                pl.col(feature.name).replace_strict(labels, default=None, return_dtype=pl.String)
            )
        else:
            encoding = FeatureEncoding(
                feature=feature.name,
                levels=feature.fixed_levels,
                reference=feature.reference,
                keys=MappingProxyType({}),
            )
            unknown = set(levels[feature.name].drop_nulls().unique().to_list()) - set(
                encoding.levels
            )
            if unknown:
                msg = (
                    f"feature {feature.name}: levels {sorted(unknown)} are not in the specification"
                )
                raise FeatureError(msg)
        encodings.append(encoding)

    # Order: index time, the case's and the person's source keys, outcome, labels.
    case_keys, cluster_keys = _keys(frame)
    rows = (
        events.join(levels, on=ROW, how="inner")
        .join(case_keys, on="case_id", how="left")
        .join(cluster_keys, on="person_id", how="left")
        .with_columns(pl.col(CASE_KEY).fill_null(""), pl.col(CLUSTER_KEY).fill_null(""))
    )
    rows = rows.sort(
        ["index_at", CASE_KEY, CLUSTER_KEY, OUTCOME, *(feature.name for feature in active)],
        nulls_last=True,
        maintain_order=True,
    )

    candidates = [DesignColumn(INTERCEPT, None, None)] + [
        DesignColumn(f"{encoding.feature}={level}", encoding.feature, level)
        for encoding in encodings
        for level in encoding.columns
    ]
    feature_names = [feature.name for feature in active]
    full = encode(rows.select(feature_names), candidates)
    observed = [index for index in range(len(candidates)) if index == 0 or full[:, index].any()]
    columns = tuple(candidates[index] for index in observed)
    unobserved = tuple(
        candidates[index].name for index in range(len(candidates)) if index not in observed
    )
    for encoding in encodings:
        if not any(column.feature == encoding.feature for column in columns):
            dropped.append(
                DroppedFeature(encoding.feature, "one level in the data: the reference alone")
            )
    return DesignFrame(
        target=target.name,
        window_days=window_days,
        columns=columns,
        matrix=np.ascontiguousarray(full[:, observed], dtype=np.float64),
        outcome=np.ascontiguousarray(rows[OUTCOME].to_numpy(), dtype=np.float64),
        index_at=_microseconds(rows["index_at"]),
        clusters=tuple(str(key) for key in rows[CLUSTER_KEY].to_list()),
        missing=np.ascontiguousarray(rows["_missing"].to_numpy(), dtype=np.bool_),
        member_ids=tuple(str(value) for value in rows["member_id"].to_list()),
        judge_ids=tuple(str(value) for value in rows[SUBJECT].to_list()),
        levels=rows.select(feature_names),
        encodings=tuple(encodings),
        dropped=tuple(dropped),
        unobserved=unobserved,
        eligible=eligible,
        excluded_missing=eligible - rows.height,
    )


def remap_unseen(
    test: pl.DataFrame, train: pl.DataFrame, encodings: Sequence[FeatureEncoding]
) -> pl.DataFrame:
    """Test-set levels with every data level unseen in ``train`` re-scored.

    A level absent from the training rows takes the latest training level
    for an ordered feature (``unseen: latest`` — the calendar year: the last
    training year's level) and the reference otherwise.
    """
    for encoding in encodings:
        if encoding.unseen is None or encoding.feature not in test.columns:
            continue
        seen = {str(value) for value in train[encoding.feature].drop_nulls().to_list()}
        if not seen:
            continue
        if encoding.unseen == UNSEEN_LATEST:
            replacement = max(
                seen,
                key=lambda value: (value.isdigit(), int(value) if value.isdigit() else 0, value),
            )
        else:
            replacement = encoding.reference
        test = test.with_columns(
            pl.when(pl.col(encoding.feature).is_in(sorted(seen)))
            .then(pl.col(encoding.feature))
            .otherwise(pl.lit(replacement))
            .alias(encoding.feature)
        )
    return test
