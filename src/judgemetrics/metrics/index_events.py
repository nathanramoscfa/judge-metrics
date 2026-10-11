# src/judgemetrics/metrics/index_events.py
"""Index events: the moments a person's follow-up is measured from.

An index event is ``(person, case, kind, index_at)`` — one cohort member
of a windowed metric — identified by the canonical row it comes from
(``member_kind``, ``member_id``):

- ``pretrial_release``: an attributed pretrial decision (the registry
  rule's filters and gate; a court takes the court's cases) with
  ``detained_flag = false`` and a non-null ``release_at``; ``index_at`` is
  the release time; the member is the decision.
- ``disposition``: a disposed case — one with a charge whose disposition is
  final (the vocabulary's ``final_charge_disposition``: dismissed,
  acquitted, a conviction; never pending, superseded, or transferred) and
  carries a disposition time — at the case disposition time, the latest
  ``disposed_at`` among its disposed charges, attributed by the rule's gate:
  ``disposing_judge`` (registry version 3) takes the judge on the charge
  whose disposal sets that time, ties broken by the source's charge id and
  then the canonical id; one index event per person with a disposed charge
  in the case; the member is the case.
- ``sentence``: an attributed sentence; ``index_at`` is ``sentence_at``;
  the member is the sentence.

An index event whose ``index_at`` falls outside the source's coverage window
is no cohort member (``periods.within_coverage``). The same rules are stated
in docs/METHODOLOGY.md "Index events, exposure, and censoring" and
implemented identically by the synthetic truth generator
(``synthetic/truth.py``, ``TRUTH_VERSION`` 2). Every function is pure over a
``Frame``; the result carries exactly ``INDEX_COLUMNS``.
"""

from __future__ import annotations

import polars as pl

from judgemetrics.metrics.attribution import (
    DISPOSING_JUDGE,
    AttributionError,
    AttributionRule,
    Subject,
    attributed_cases,
    attributed_sentences,
    pretrial_decisions_for,
)
from judgemetrics.metrics.frame import Frame
from judgemetrics.metrics.periods import within_coverage
from judgemetrics.normalization import vocabulary

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

INDEX_COLUMNS: tuple[str, ...] = ("member_kind", "member_id", "case_id", "person_id", "index_at")
DISPOSITION_AT = "disposition_at"
FINAL_DISPOSITION_KIND = "final_charge_disposition"


def final_dispositions() -> tuple[str, ...]:
    """The dispositions that end a charge on its merits (vocabulary finality)."""
    return vocabulary.values(FINAL_DISPOSITION_KIND)


def disposed_charges(frame: Frame) -> pl.DataFrame:
    """Charges with a final disposition and a disposition time (never a non-final one)."""
    return frame.derived(
        "disposed_charges",
        lambda: frame.charges.filter(
            pl.col("disposition").is_in(list(final_dispositions()))
            & pl.col("disposed_at").is_not_null()
        ),
    )


def case_dispositions(frame: Frame) -> pl.DataFrame:
    """``(case_id, disposition_at, disposing_judge_id)`` for every disposed case.

    The case disposition time is the latest ``disposed_at`` among the case's
    disposed charges; its disposing judge is the ``judge_id`` of the charge
    whose disposal sets that time, ties broken by the source's charge id
    (``source_row_id``) and then the canonical id.
    """
    return frame.derived(
        "case_dispositions",
        lambda: (
            disposed_charges(frame)
            .sort(
                ["case_id", "disposed_at", "source_row_id", "id"],
                descending=[False, True, False, False],
                nulls_last=True,
            )
            .unique(subset=["case_id"], keep="first", maintain_order=True)
            .select(
                "case_id",
                pl.col("disposed_at").alias(DISPOSITION_AT),
                pl.col("judge_id").alias(DISPOSING_JUDGE),
            )
        ),
    )


def disposed_cases(frame: Frame) -> pl.DataFrame:
    """The disposed cases: ``cases`` columns, ``disposition_at``, the disposing judge."""
    return frame.derived(
        "disposed_cases",
        lambda: frame.cases.join(
            case_dispositions(frame), left_on="id", right_on="case_id", how="inner"
        ),
    )


def disposed_case_persons(frame: Frame) -> pl.DataFrame:
    """``(case_id, person_id)`` of every person with a disposed charge in a case, distinct."""
    return frame.derived(
        "disposed_case_persons",
        lambda: disposed_charges(frame).select("case_id", "person_id").unique(),
    )


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
    persons = disposed_case_persons(frame)
    rows = cases.join(persons, on="case_id", how="inner").with_columns(
        pl.col("case_id").alias("member_id")
    )
    return _select_index(rows, MEMBER_CASE, "member_id", DISPOSITION_AT)


def sentence_index(frame: Frame, rule: AttributionRule, subject: Subject) -> pl.DataFrame:
    sentences = attributed_sentences(frame, rule, subject)
    return _select_index(sentences, MEMBER_SENTENCE, "id", "sentence_at")


def index_events(frame: Frame, kind: str, rule: AttributionRule, subject: Subject) -> pl.DataFrame:
    """The index events of ``kind`` the rule attributes to the subject (``INDEX_COLUMNS``).

    Only those whose ``index_at`` lies inside the coverage window.
    """
    if kind == PRETRIAL_RELEASE:
        events = pretrial_release_index(frame, rule, subject)
    elif kind == DISPOSITION:
        events = disposition_index(frame, rule, subject)
    elif kind == SENTENCE:
        events = sentence_index(frame, rule, subject)
    else:
        msg = f"unknown index event kind {kind!r}"
        raise AttributionError(msg)
    return within_coverage(frame, events, "index_at")
