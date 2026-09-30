# src/judgemetrics/metrics/exposure.py
"""Exposure: when a cohort member's time at risk begins.

Exposure starts at the index time, then is deferred by incarceration,
because a person who is incarcerated cannot accrue a new case in the
community (methodology 0.2, Phase 3 finding 1.4):

1. For the ``disposition`` kind the start is first moved to the end of the
   index case's own term — ``sentence_at + incarceration_days`` of the
   sentence of the same case and person with a positive
   ``incarceration_days``, the latest term end when there are several —
   because the sentence always follows the disposition.
2. Then, for every kind (``pretrial_release`` included), while an
   incarceration term ``[sentence_at, sentence_at + incarceration_days)``
   of the same person — in any case; the frame's persons are the merged
   persons — contains the start, the start moves to the end of the
   containing term that ends last (ties: the longer term). The result is
   the first instant at or after the index time that no term of the
   person covers. For the ``sentence`` kind the member's own term is the
   first such term.

``deferral_days`` is the total of the ``incarceration_days`` of every term
applied (null when none). Terms in another jurisdiction, or not recorded by
the source, are still not modelled: that remains a documented limitation.
The synthetic truth generator implements the same rule independently
(``TRUTH_VERSION`` 3), and the frame property test compares the two.

``with_exposure`` returns the index events with ``exposure_start`` (never
before ``index_at``) and ``deferral_days``.
"""

from __future__ import annotations

import polars as pl

from judgemetrics.metrics.attribution import AttributionError
from judgemetrics.metrics.frame import Frame
from judgemetrics.metrics.index_events import (
    DISPOSITION,
    INDEX_COLUMNS,
    INDEX_KINDS,
)

EXPOSURE_COLUMNS: tuple[str, ...] = (*INDEX_COLUMNS, "exposure_start", "deferral_days")
ROW = "_row"
START = "_start"
DEFERRAL = "_deferral"
TERM_START = "_term_start"
TERM_END = "_term_end"
TERM_DAYS = "_term_days"


class ExposureError(AttributionError):
    """A deferral chain did not end (a defect: every step moves the start forward)."""


def incarceration_terms(frame: Frame) -> pl.DataFrame:
    """Every positive incarceration term: ``case_id``, ``person_id``, start, end, days."""
    return frame.sentences.filter(
        pl.col("incarceration_days").is_not_null() & (pl.col("incarceration_days") > 0)
    ).select(
        "case_id",
        "person_id",
        pl.col("sentence_at").alias(TERM_START),
        (pl.col("sentence_at") + pl.duration(days=pl.col("incarceration_days"))).alias(TERM_END),
        pl.col("incarceration_days").cast(pl.Int64).alias(TERM_DAYS),
    )


def _own_terms(rows: pl.DataFrame, terms: pl.DataFrame) -> pl.DataFrame:
    """The disposition kind's first step: the latest term of the index case's own sentence."""
    latest = (
        terms.select("case_id", "person_id", TERM_END, TERM_DAYS)
        .sort([TERM_END, TERM_DAYS], descending=True)
        .unique(subset=["case_id", "person_id"], keep="first", maintain_order=True)
    )
    joined = rows.join(latest, on=["case_id", "person_id"], how="left")
    return joined.with_columns(
        pl.coalesce(TERM_END, "index_at").alias(START),
        pl.col(TERM_DAYS).fill_null(0).alias(DEFERRAL),
    ).drop(TERM_END, TERM_DAYS)


def _defer(current: pl.DataFrame, terms: pl.DataFrame) -> pl.DataFrame:
    """Move every start past each term of its person that contains it, until none does."""
    by_person = terms.select("person_id", TERM_START, TERM_END, TERM_DAYS)
    for _ in range(by_person.height + 1):
        hits = (
            current.select(ROW, "person_id", START)
            .join(by_person, on="person_id", how="inner")
            .filter((pl.col(TERM_START) <= pl.col(START)) & (pl.col(START) < pl.col(TERM_END)))
        )
        if hits.height == 0:
            return current
        best = (
            hits.sort([ROW, TERM_END, TERM_DAYS], descending=[False, True, True])
            .unique(subset=[ROW], keep="first", maintain_order=True)
            .select(ROW, TERM_END, TERM_DAYS)
        )
        current = (
            current.join(best, on=ROW, how="left")
            .with_columns(
                pl.coalesce(TERM_END, START).alias(START),
                (pl.col(DEFERRAL) + pl.col(TERM_DAYS).fill_null(0)).alias(DEFERRAL),
            )
            .drop(TERM_END, TERM_DAYS)
        )
    msg = "an exposure deferral chain did not end"
    raise ExposureError(msg)


def with_exposure(frame: Frame, index: pl.DataFrame, kind: str) -> pl.DataFrame:
    """The index events with ``exposure_start`` and ``deferral_days`` (``EXPOSURE_COLUMNS``)."""
    if kind not in INDEX_KINDS:
        msg = f"unknown index event kind {kind!r}"
        raise AttributionError(msg)
    terms = incarceration_terms(frame)
    rows = index.with_row_index(ROW)
    if kind == DISPOSITION:
        current = _own_terms(rows, terms)
    else:
        current = rows.with_columns(
            pl.col("index_at").alias(START), pl.lit(0, dtype=pl.Int64).alias(DEFERRAL)
        )
    current = _defer(current, terms)
    return (
        current.sort(ROW)
        .with_columns(
            pl.col(START).alias("exposure_start"),
            pl.when(pl.col(DEFERRAL) > 0)
            .then(pl.col(DEFERRAL))
            .otherwise(None)
            .cast(pl.Int64)
            .alias("deferral_days"),
        )
        .select(EXPOSURE_COLUMNS)
    )
