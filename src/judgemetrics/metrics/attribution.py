# src/judgemetrics/metrics/attribution.py
"""The inclusion gate: which rows of a frame a registry rule attributes to a subject.

Every judge-level metric uses only events whose attribution satisfies the
metric's documented inclusion rules (the brief's event attribution
model). A registry ``attribution`` block is applied here as an
``AttributionRule``: the row filters (``decision_type``, ``actor_types``,
``discretion``) and the assignment gate that ties a row to the subject:

- ``deciding_judge`` keeps decisions whose ``judge_id`` is the subject;
- ``assigned_at_time`` keeps rows whose event time falls in one of the
  subject's assignment intervals on that case, ``start_at <= t < end_at``
  with a null ``end_at`` open;
- ``assigned_ever`` keeps rows of cases with at least one assignment of
  the subject (the eligibility gate);
- ``sentencing_judge`` keeps sentences whose ``judge_id`` is the subject;
- ``court_of_case`` keeps rows of the court's cases.

A court subject always takes the ``court_of_case`` gate, whatever the
rule names: a court's metrics are computed over the cases filed in it. A
judge subject never receives a statutory release (``actor_type =
legislature_or_mandatory_rule``, ``discretion = mandatory``) or a decision
with an unknown actor or an unknown discretion, whatever the rule admits;
the court-level ``statutory_release_count`` and
``unknown_actor_pretrial_count`` count them explicitly through
``statutory_releases`` and ``unknown_actor_pretrial_decisions``.

Every function is pure over a ``Frame`` and returns a new DataFrame with
the input table's columns.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

import polars as pl

from judgemetrics.metrics.frame import Frame
from judgemetrics.metrics.registry import ASSIGNMENT_GATES, AttributionSpec

JUDGE = "judge"
COURT = "court"
SUBJECT_TYPES: tuple[str, ...] = (JUDGE, COURT)

GATE_DECIDING_JUDGE = "deciding_judge"
GATE_ASSIGNED_AT_TIME = "assigned_at_time"
GATE_ASSIGNED_EVER = "assigned_ever"
GATE_SENTENCING_JUDGE = "sentencing_judge"
GATE_COURT_OF_CASE = "court_of_case"

PRETRIAL_RELEASE = "pretrial_release"
STATUTORY_ACTOR = "legislature_or_mandatory_rule"
MANDATORY = "mandatory"
UNKNOWN = "unknown"
# Never attributed to a judge, whatever a rule admits.
JUDGE_EXCLUDED_ACTORS: frozenset[str] = frozenset({STATUTORY_ACTOR, UNKNOWN})
JUDGE_EXCLUDED_DISCRETION: frozenset[str] = frozenset({MANDATORY, UNKNOWN})

ROW = "_row"


class AttributionError(ValueError):
    """A rule and a subject cannot be combined (a registry or caller defect)."""


@dataclass(frozen=True, slots=True)
class AttributionRule:
    """A registry ``attribution`` block: row filters plus the assignment gate."""

    decision_type: str | None = None
    actor_types: frozenset[str] | None = None
    discretion: frozenset[str] | None = None
    assignment_gate: str = GATE_COURT_OF_CASE

    def __post_init__(self) -> None:
        if self.assignment_gate not in ASSIGNMENT_GATES:
            msg = f"unknown assignment gate {self.assignment_gate!r}"
            raise AttributionError(msg)

    @classmethod
    def from_spec(cls, spec: AttributionSpec) -> AttributionRule:
        return cls(
            decision_type=spec.decision_type,
            actor_types=None if spec.actor_types is None else frozenset(spec.actor_types),
            discretion=None if spec.discretion is None else frozenset(spec.discretion),
            assignment_gate=spec.assignment_gate,
        )

    @classmethod
    def from_mapping(cls, block: Mapping[str, Any]) -> AttributionRule:
        actors = block.get("actor_types")
        discretion = block.get("discretion")
        return cls(
            decision_type=block.get("decision_type"),
            actor_types=None if actors is None else frozenset(actors),
            discretion=None if discretion is None else frozenset(discretion),
            assignment_gate=str(block.get("assignment_gate", GATE_COURT_OF_CASE)),
        )


@dataclass(frozen=True, slots=True)
class Subject:
    """A judge or a court, by the id the frame uses."""

    subject_type: str
    subject_id: Any

    def __post_init__(self) -> None:
        if self.subject_type not in SUBJECT_TYPES:
            msg = f"unknown subject type {self.subject_type!r}"
            raise AttributionError(msg)


# --- gates ----------------------------------------------------------------------------


def court_case_ids(frame: Frame, court_id: Any) -> pl.DataFrame:
    """The ``case_id`` column of the court's cases."""
    return frame.cases.filter(pl.col("court_id") == court_id).select(pl.col("id").alias("case_id"))


def rows_of_court(
    frame: Frame, court_id: Any, rows: pl.DataFrame, case_column: str
) -> pl.DataFrame:
    """``rows`` whose case belongs to the court (the ``court_of_case`` gate)."""
    cases = court_case_ids(frame, court_id).rename({"case_id": case_column})
    return rows.join(cases, on=case_column, how="semi")


def rows_assigned_at_time(
    frame: Frame, judge_id: Any, rows: pl.DataFrame, case_column: str, time_column: str
) -> pl.DataFrame:
    """``rows`` whose time falls in one of the judge's assignment intervals on the case.

    ``start_at <= t < end_at``; a null ``end_at`` is open-ended. A row with a
    null time never matches.
    """
    intervals = frame.assignments.filter(pl.col("judge_id") == judge_id).select(
        pl.col("case_id").alias(case_column), "start_at", "end_at"
    )
    indexed = rows.with_row_index(ROW)
    joined = indexed.select(ROW, case_column, time_column).join(
        intervals, on=case_column, how="inner"
    )
    hits = joined.filter(
        (pl.col("start_at") <= pl.col(time_column))
        & (pl.col("end_at").is_null() | (pl.col(time_column) < pl.col("end_at")))
    ).select(ROW)
    return indexed.join(hits.unique(), on=ROW, how="semi").drop(ROW)


def rows_assigned_ever(
    frame: Frame, judge_id: Any, rows: pl.DataFrame, case_column: str
) -> pl.DataFrame:
    """``rows`` of cases with at least one assignment of the judge."""
    cases = (
        frame.assignments.filter(pl.col("judge_id") == judge_id)
        .select(pl.col("case_id").alias(case_column))
        .unique()
    )
    return rows.join(cases, on=case_column, how="semi")


def gate_rows(
    frame: Frame,
    rule: AttributionRule,
    subject: Subject,
    rows: pl.DataFrame,
    *,
    case_column: str = "case_id",
    time_column: str | None = None,
    judge_column: str = "judge_id",
) -> pl.DataFrame:
    """Apply the rule's assignment gate for ``subject`` to ``rows``.

    A court subject takes the court's cases. For a judge subject the gate
    decides: ``deciding_judge`` and ``sentencing_judge`` compare
    ``judge_column``; ``assigned_at_time`` needs ``time_column``;
    ``assigned_ever`` needs only the case; ``court_of_case`` cannot
    attribute rows to a judge and raises ``AttributionError``.
    """
    if subject.subject_type == COURT:
        return rows_of_court(frame, subject.subject_id, rows, case_column)
    gate = rule.assignment_gate
    if gate in (GATE_DECIDING_JUDGE, GATE_SENTENCING_JUDGE):
        if judge_column not in rows.columns:
            msg = f"gate {gate} needs column {judge_column!r}"
            raise AttributionError(msg)
        return rows.filter(pl.col(judge_column) == subject.subject_id)
    if gate == GATE_ASSIGNED_AT_TIME:
        if time_column is None or time_column not in rows.columns:
            msg = f"gate {gate} needs a time column; got {time_column!r}"
            raise AttributionError(msg)
        return rows_assigned_at_time(frame, subject.subject_id, rows, case_column, time_column)
    if gate == GATE_ASSIGNED_EVER:
        return rows_assigned_ever(frame, subject.subject_id, rows, case_column)
    msg = f"gate {gate} cannot attribute rows to a judge"
    raise AttributionError(msg)


# --- attributed rows -------------------------------------------------------------------


def _filter_values(rows: pl.DataFrame, column: str, values: frozenset[str] | None) -> pl.DataFrame:
    if values is None:
        return rows
    return rows.filter(pl.col(column).is_in(sorted(values)))


def attributed_decisions(frame: Frame, rule: AttributionRule, subject: Subject) -> pl.DataFrame:
    """The decisions the rule attributes to the subject.

    Filters ``decision_type``, ``actor_type``, and ``discretion`` as the
    rule states, then applies the gate at ``decision_at``. A judge subject
    never receives a statutory release or an unknown actor or discretion.
    """
    rows = frame.decisions
    if rule.decision_type is not None:
        rows = rows.filter(pl.col("decision_type") == rule.decision_type)
    rows = _filter_values(rows, "actor_type", rule.actor_types)
    rows = _filter_values(rows, "discretion", rule.discretion)
    if subject.subject_type == JUDGE:
        rows = rows.filter(
            ~pl.col("actor_type").is_in(sorted(JUDGE_EXCLUDED_ACTORS))
            & ~pl.col("discretion").is_in(sorted(JUDGE_EXCLUDED_DISCRETION))
        )
    return gate_rows(frame, rule, subject, rows, time_column="decision_at")


def attributed_charges(frame: Frame, rule: AttributionRule, subject: Subject) -> pl.DataFrame:
    """The charges the rule attributes to the subject (gate at ``disposed_at``).

    ``actor_types``, when given, filters ``disposition_actor``; a charge
    without a disposition time never passes ``assigned_at_time``.
    """
    rows = _filter_values(frame.charges, "disposition_actor", rule.actor_types)
    return gate_rows(frame, rule, subject, rows, time_column="disposed_at")


def attributed_sentences(frame: Frame, rule: AttributionRule, subject: Subject) -> pl.DataFrame:
    """The sentences the rule attributes to the subject (gate at ``sentence_at``)."""
    return gate_rows(frame, rule, subject, frame.sentences, time_column="sentence_at")


def attributed_cases(
    frame: Frame,
    rule: AttributionRule,
    subject: Subject,
    *,
    rows: pl.DataFrame | None = None,
    time_column: str | None = None,
) -> pl.DataFrame:
    """The cases the rule attributes to the subject.

    ``rows`` defaults to ``frame.cases``; a caller gating at a time (the
    case disposition time) passes cases joined with that column and names
    it in ``time_column``.
    """
    cases = frame.cases if rows is None else rows
    return gate_rows(
        frame, rule, subject, cases, case_column="id", time_column=time_column, judge_column="_"
    )


def pretrial_decisions_for(
    frame: Frame, subject_type: str, subject_id: Any, rule: AttributionRule
) -> pl.DataFrame:
    """The pretrial-release decisions the rule attributes to the subject."""
    if rule.decision_type not in (None, PRETRIAL_RELEASE):
        msg = f"rule decision_type {rule.decision_type!r} is not pretrial_release"
        raise AttributionError(msg)
    pretrial_rule = replace(rule, decision_type=PRETRIAL_RELEASE)
    return attributed_decisions(frame, pretrial_rule, Subject(subject_type, subject_id))


def statutory_releases(frame: Frame, court_id: Any) -> pl.DataFrame:
    """The court's pretrial releases required by statute (never a judge's)."""
    rows = frame.decisions.filter(
        (pl.col("decision_type") == PRETRIAL_RELEASE)
        & (pl.col("actor_type") == STATUTORY_ACTOR)
        & (pl.col("discretion") == MANDATORY)
    )
    return rows_of_court(frame, court_id, rows, "case_id")


def unknown_actor_pretrial_decisions(frame: Frame, court_id: Any) -> pl.DataFrame:
    """The court's pretrial decisions whose actor the source does not identify."""
    rows = frame.decisions.filter(
        (pl.col("decision_type") == PRETRIAL_RELEASE) & (pl.col("actor_type") == UNKNOWN)
    )
    return rows_of_court(frame, court_id, rows, "case_id")
