# src/judgemetrics/metrics/exposure.py
"""Exposure: when a cohort member's time at risk begins.

Exposure starts at the index time. For the ``disposition`` and ``sentence``
index kinds, when the sentence carries a positive ``incarceration_days``,
exposure starts at ``sentence_at + incarceration_days`` instead: time at
risk is deferred by the incarceration term, because a person who is
incarcerated cannot accrue a new case in the community. For the
``sentence`` kind the deferring sentence is the member itself; for the
``disposition`` kind it is the sentence of the same case and person (the
latest term end when there are several). The ``pretrial_release`` kind is
never deferred: its index time is the release itself.

Documented limitation: only the sentence of the index case defers
exposure. Other terms the same person serves — an earlier sentence still
running, a term in another case or jurisdiction — are not modelled, so
time at risk is overstated for such persons and their windowed rates are
biased downward. docs/METHODOLOGY.md states this beside the rule, and the
synthetic truth generator implements the same rule (``TRUTH_VERSION`` 2).

``with_exposure`` returns the index events with ``exposure_start`` (never
before ``index_at``) and ``deferral_days`` (the incarceration term applied,
null when none).
"""

from __future__ import annotations

import polars as pl

from judgemetrics.metrics.attribution import AttributionError
from judgemetrics.metrics.frame import Frame
from judgemetrics.metrics.index_events import (
    DISPOSITION,
    INDEX_COLUMNS,
    INDEX_KINDS,
    PRETRIAL_RELEASE,
    SENTENCE,
)

EXPOSURE_COLUMNS: tuple[str, ...] = (*INDEX_COLUMNS, "exposure_start", "deferral_days")
TERM_END = "_term_end"
TERM_DAYS = "_term_days"


def _incarcerating_sentences(frame: Frame) -> pl.DataFrame:
    """Sentences with a positive incarceration term and the instant the term ends."""
    return frame.sentences.filter(
        pl.col("incarceration_days").is_not_null() & (pl.col("incarceration_days") > 0)
    ).with_columns(
        (pl.col("sentence_at") + pl.duration(days=pl.col("incarceration_days"))).alias(TERM_END),
        pl.col("incarceration_days").alias(TERM_DAYS),
    )


def with_exposure(frame: Frame, index: pl.DataFrame, kind: str) -> pl.DataFrame:
    """The index events with ``exposure_start`` and ``deferral_days`` (``EXPOSURE_COLUMNS``)."""
    if kind not in INDEX_KINDS:
        msg = f"unknown index event kind {kind!r}"
        raise AttributionError(msg)
    if kind == PRETRIAL_RELEASE:
        return index.with_columns(
            pl.col("index_at").alias("exposure_start"),
            pl.lit(None, dtype=pl.Int64).alias("deferral_days"),
        ).select(EXPOSURE_COLUMNS)
    terms = _incarcerating_sentences(frame)
    if kind == SENTENCE:
        joined = index.join(
            terms.select(pl.col("id").alias("member_id"), TERM_END, TERM_DAYS),
            on="member_id",
            how="left",
        )
    elif kind == DISPOSITION:
        latest = (
            terms.select("case_id", "person_id", TERM_END, TERM_DAYS)
            .sort(TERM_END, descending=True)
            .unique(subset=["case_id", "person_id"], keep="first", maintain_order=True)
        )
        joined = index.join(latest, on=["case_id", "person_id"], how="left")
    else:  # pragma: no cover - INDEX_KINDS is exhausted above
        msg = f"unknown index event kind {kind!r}"
        raise AttributionError(msg)
    return joined.with_columns(
        pl.when(pl.col(TERM_END).is_not_null())
        .then(pl.col(TERM_END))
        .otherwise(pl.col("index_at"))
        .alias("exposure_start"),
        pl.col(TERM_DAYS).alias("deferral_days"),
    ).select(EXPOSURE_COLUMNS)
