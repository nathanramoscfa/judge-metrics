# src/judgemetrics/metrics/index_events.py
"""Index events: the moments a person's follow-up is measured from.

An index event is ``(person, case, kind, index_at)`` — one cohort member
of a windowed metric — identified by the canonical row it comes from
(``member_kind``, ``member_id``):

- ``pretrial_release``: an attributed pretrial decision (the registry
  rule's filters and gate; a court takes the court's cases) with
  ``detained_flag = false`` and a non-null ``release_at``; ``index_at`` is
  the release time; the member is the decision.
- ``disposition``: a disposed case — one whose charges carry a disposition
  other than pending or missing with a disposition time — attributed by
  the rule's gate at the case disposition time, the latest ``disposed_at``
  among its disposed charges; one index event per person with a disposed
  charge in the case; the member is the case.
- ``sentence``: an attributed sentence; ``index_at`` is ``sentence_at``;
  the member is the sentence.

The same rules are stated in docs/METHODOLOGY.md "Index events, exposure,
and censoring" and implemented identically by the synthetic truth
generator (``synthetic/truth.py``, ``TRUTH_VERSION`` 2). Every function is
pure over a ``Frame``; the result carries exactly ``INDEX_COLUMNS``.
"""

from __future__ import annotations

import polars as pl

from judgemetrics.metrics.attribution import (
    AttributionError,
    AttributionRule,
    Subject,
    attributed_cases,
    attributed_sentences,
    pretrial_decisions_for,
)
from judgemetrics.metrics.frame import Frame

PRETRIAL_RELEASE = "pretrial_release"
DISPOSITION = "disposition"
SENTENCE = "sentence"
INDEX_KINDS: tuple[str, ...] = (PRETRIAL_RELEASE, DISPOSITION, SENTENCE)

MEMBER_DECISION = "decision"
MEMBER_CASE = "court_case"
MEMBER_SENTENCE = "sentence"
MEMBER_KIND_OF_INDEX: dict[str, str] = {
    PRETRIAL_RELEASE: MEMBER_DECISION,
    DISPOSITION: MEMBER_CASE,
    SENTENCE: MEMBER_SENTENCE,
}

PENDING = "pending"
INDEX_COLUMNS: tuple[str, ...] = ("member_kind", "member_id", "case_id", "person_id", "index_at")
DISPOSITION_AT = "disposition_at"


def disposed_charges(frame: Frame) -> pl.DataFrame:
    """Charges with a disposition other than pending or missing and a disposition time."""
    return frame.charges.filter(
        pl.col("disposition").is_not_null()
        & (pl.col("disposition") != PENDING)
        & pl.col("disposed_at").is_not_null()
    )


def case_dispositions(frame: Frame) -> pl.DataFrame:
    """``(case_id, disposition_at)``: the latest ``disposed_at`` among each case's disposed charges."""
    return (
        disposed_charges(frame)
        .group_by("case_id")
        .agg(pl.col("disposed_at").max().alias(DISPOSITION_AT))
    )


def disposed_cases(frame: Frame) -> pl.DataFrame:
    """The cases with a disposition time: the ``cases`` columns plus ``disposition_at``."""
    return frame.cases.join(case_dispositions(frame), left_on="id", right_on="case_id", how="inner")


def _select_index(
    rows: pl.DataFrame, member_kind: str, member_column: str, at: str
) -> pl.DataFrame:
    return rows.select(
        pl.lit(member_kind).alias("member_kind"),
        pl.col(member_column).alias("member_id"),
        pl.col("case_id"),
        pl.col("person_id"),
        pl.col(at).alias("index_at"),
    )


def pretrial_release_index(frame: Frame, rule: AttributionRule, subject: Subject) -> pl.DataFrame:
    decisions = pretrial_decisions_for(frame, subject.subject_type, subject.subject_id, rule)
    released = decisions.filter(
        pl.col("detained_flag").is_not_null()
        & ~pl.col("detained_flag")
        & pl.col("release_at").is_not_null()
    )
    return _select_index(released, MEMBER_DECISION, "id", "release_at")


def disposition_index(frame: Frame, rule: AttributionRule, subject: Subject) -> pl.DataFrame:
    cases = attributed_cases(
        frame, rule, subject, rows=disposed_cases(frame), time_column=DISPOSITION_AT
    ).select(pl.col("id").alias("case_id"), DISPOSITION_AT)
    persons = disposed_charges(frame).select("case_id", "person_id").unique()
    rows = cases.join(persons, on="case_id", how="inner").with_columns(
        pl.col("case_id").alias("member_id")
    )
    return _select_index(rows, MEMBER_CASE, "member_id", DISPOSITION_AT)


def sentence_index(frame: Frame, rule: AttributionRule, subject: Subject) -> pl.DataFrame:
    sentences = attributed_sentences(frame, rule, subject)
    return _select_index(sentences, MEMBER_SENTENCE, "id", "sentence_at")


def index_events(frame: Frame, kind: str, rule: AttributionRule, subject: Subject) -> pl.DataFrame:
    """The index events of ``kind`` the rule attributes to the subject (``INDEX_COLUMNS``)."""
    if kind == PRETRIAL_RELEASE:
        return pretrial_release_index(frame, rule, subject)
    if kind == DISPOSITION:
        return disposition_index(frame, rule, subject)
    if kind == SENTENCE:
        return sentence_index(frame, rule, subject)
    msg = f"unknown index event kind {kind!r}"
    raise AttributionError(msg)
