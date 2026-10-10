# src/judgemetrics/metrics/windows.py
"""Observation windows: which cohort members have an outcome within ``w`` days.

An outcome counts for a window ``w`` when an event of the outcome type
occurs in ``(exposure_start, exposure_start + w days]`` — strictly after
the exposure start, at or before the window's end. Outcomes are read from
the frame's ``justice_events`` (the person's derived later events):
``new_case``, ``new_charge``, and ``reconviction`` count only when the
event's ``related_case_id`` is another case of the same person (an event
whose related case is unknown cannot be shown to be another case and
does not count); ``failure_to_appear``, ``release_violation``,
``revocation``, and ``rearrest`` count in any case. Because a member has
an outcome within ``w`` exactly when its first qualifying outcome after
the exposure start is within ``w``, ``first_outcomes`` computes that
first time once and ``outcome_flags`` evaluates every window from it;
the same first time is what the Kaplan-Meier estimator uses.

The six windows are the brief's (``WINDOWS_DAYS``: 30, 90, 180, 365, 730,
1095 days). A metric whose outcome is not among the source's
``observable_outcomes`` is not observable for that source and yields no
rows — a ``NotObservable`` marker the engine records — never a zero. A
revocation is observable only in the scopes the source documents
(``Frame.capabilities.revocation_scopes``; the registry's ``revocation_scopes``
gives each index event's scope): a revoked pretrial release after a pretrial
release, a revoked supervision after a disposition or a sentence.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from judgemetrics.metrics.frame import Frame
from judgemetrics.metrics.registry import WINDOWS_DAYS

# Outcomes counted only in another case of the same person.
OTHER_CASE_OUTCOMES: frozenset[str] = frozenset({"new_case", "new_charge", "reconviction"})
# Outcomes counted in any case.
ANY_CASE_OUTCOMES: frozenset[str] = frozenset(
    {"failure_to_appear", "release_violation", "revocation", "rearrest"}
)
FIRST_OUTCOME_AT = "first_outcome_at"
MEMBER_KEY: tuple[str, ...] = ("member_kind", "member_id", "person_id")
ROW = "_row"

__all__ = [
    "ANY_CASE_OUTCOMES",
    "FIRST_OUTCOME_AT",
    "MEMBER_KEY",
    "OTHER_CASE_OUTCOMES",
    "WINDOWS_DAYS",
    "NotObservable",
    "first_outcomes",
    "is_observable",
    "not_observable",
    "outcome_flags",
]


@dataclass(frozen=True, slots=True)
class NotObservable:
    """The source cannot document ``outcome``: the metric yields no observation for it."""

    outcome: str
    reason: str


def is_observable(frame: Frame, outcome: str, revocation_scope: str | None = None) -> bool:
    """Whether the source documents ``outcome`` (of ``revocation_scope``, for a revocation)."""
    if outcome not in frame.observable_outcomes:
        return False
    return revocation_scope is None or revocation_scope in frame.capabilities.revocation_scopes


def not_observable(
    frame: Frame, outcome: str, revocation_scope: str | None = None
) -> NotObservable | None:
    """``NotObservable`` when the frame's source cannot document ``outcome``, else ``None``.

    A revocation metric passes its ``revocation_scope`` (registry version 3): a
    source that documents revocations of another scope only (a revoked
    supervision, not a revoked pretrial release) cannot observe it.
    """
    if is_observable(frame, outcome, revocation_scope):
        return None
    if outcome in frame.observable_outcomes and revocation_scope is not None:
        reason = f"the source does not document {outcome} events of scope {revocation_scope}"
    else:
        reason = f"the source does not document {outcome} events"
    return NotObservable(outcome=outcome, reason=reason)


def first_outcomes(frame: Frame, cohort: pl.DataFrame, outcome: str) -> pl.DataFrame:
    """The cohort (``exposure.EXPOSURE_COLUMNS``) plus ``first_outcome_at``.

    The first ``outcome`` event of the member's person strictly after its
    exposure start, respecting the other-case rule; null when there is
    none.
    """
    if outcome not in OTHER_CASE_OUTCOMES | ANY_CASE_OUTCOMES:
        msg = f"unknown outcome {outcome!r}"
        raise ValueError(msg)
    events = frame.justice_events.filter(pl.col("event_type") == outcome).select(
        "person_id", "event_at", "related_case_id"
    )
    keyed = cohort.with_row_index(ROW)
    joined = keyed.select(ROW, "person_id", "case_id", "exposure_start").join(
        events, on="person_id", how="inner"
    )
    after = joined.filter(pl.col("event_at") > pl.col("exposure_start"))
    if outcome in OTHER_CASE_OUTCOMES:
        after = after.filter(pl.col("related_case_id") != pl.col("case_id"))
    firsts = after.group_by(ROW).agg(pl.col("event_at").min().alias(FIRST_OUTCOME_AT))
    return keyed.join(firsts, on=ROW, how="left").drop(ROW)


def outcome_flags(cohort: pl.DataFrame, windows: tuple[int, ...] = WINDOWS_DAYS) -> pl.DataFrame:
    """One row per member and window: ``(member key, window_days, has_outcome)``.

    ``has_outcome`` is whether the member's first outcome lies in
    ``(exposure_start, exposure_start + w days]``; ``cohort`` is the output
    of ``first_outcomes``.
    """
    frames = [
        cohort.select(
            *MEMBER_KEY,
            pl.lit(window, dtype=pl.Int64).alias("window_days"),
            (
                pl.col(FIRST_OUTCOME_AT).is_not_null()
                & (pl.col(FIRST_OUTCOME_AT) <= pl.col("exposure_start") + pl.duration(days=window))
            )
            .fill_null(False)
            .alias("has_outcome"),
        )
        for window in windows
    ]
    return pl.concat(frames)
