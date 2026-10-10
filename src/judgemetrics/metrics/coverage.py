# src/judgemetrics/metrics/coverage.py
"""Coverage statistics: how completely a source's records support the metrics (Phase 5 Step 5).

The brief's six coverage statistics (``<coverage_metrics>``) and the
unknown-actor share, computed from a snapshot's frames on every ``metrics
compute`` — for every source the snapshot holds with case data and a coverage
window, whatever ``--source`` scopes — and stored in ``coverage_statistic``
per source, per jurisdiction of the source's courts, and per court
(``SCOPES``). ``metrics verify`` recomputes them from the snapshot and reports a
stored statistic that differs by scope and name; ``judgemetrics metrics
coverage`` prints the latest snapshot's. Every definition is ``DEFINITIONS``,
rendered verbatim into docs/METHODOLOGY.md "Coverage statistics":

- ``cases_with_identified_judge``: cases on which the source names a judge —
  an assignment, or a decision, charge disposition, sentence, or court event
  carrying a judge — over all cases;
- ``cases_with_final_disposition``: cases with a charge whose disposition is
  final (dismissed, acquitted, a conviction) and dated — the disposed cases
  the disposition metrics read — over all cases;
- ``cases_with_person_resolution``: cases whose charges, decisions, or
  sentences name a resolved defendant (the person after entity resolution)
  over all cases; the source's person-key scope (``cross_case`` or ``case``,
  ``source.capabilities``) is published beside it and states what the
  resolution is usable for;
- ``cases_with_adequate_follow_up``: cases whose follow-up anchor — the case
  disposition time when the case is disposed, else its filing — lies at
  least ``ADEQUATE_FOLLOW_UP_DAYS`` days before the coverage end, over all
  cases;
- ``cases_with_complete_charge_classification``: cases every charge of which
  carries a classified offense category and severity (neither
  ``unclassified``), over the cases with a charge;
- ``records_with_provenance``: the case-level rows (the case, its charges,
  decisions, sentences, and court events) attributed to a retrieved source
  record, over the same rows;
- ``unknown_actor_share``: the decisions whose actor is ``unknown`` and the
  final dispositions whose actor is ``unknown`` or not recorded, over all
  decisions and final dispositions.

Every statistic is a numerator, a denominator, and their share rounded to six
decimals (null without a denominator) — aggregates only: no person id, no case
list, and nothing computed over a restricted attribute (the frame holds none).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from types import MappingProxyType
from typing import Any

import polars as pl
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from judgemetrics.db.models import (
    COVERAGE_SCOPES,
    COVERAGE_STATISTICS,
    Base,
    Court,
    Jurisdiction,
    MetricSnapshot,
    Source,
)
from judgemetrics.logging import get_logger
from judgemetrics.metrics.frame import Frame
from judgemetrics.metrics.index_events import case_dispositions, disposed_charges
from judgemetrics.metrics.snapshot import Snapshot

log = get_logger(__name__)

SOURCE_SCOPE = "source"
JURISDICTION_SCOPE = "jurisdiction"
COURT_SCOPE = "court"
SCOPES: tuple[str, ...] = COVERAGE_SCOPES
STATISTICS: tuple[str, ...] = COVERAGE_STATISTICS
# The follow-up a case needs before the coverage end to count as adequately followed:
# one year, the first of the brief's windows to span a whole year of outcomes.
ADEQUATE_FOLLOW_UP_DAYS = 365
UNKNOWN = "unknown"
UNCLASSIFIED = "unclassified"
SHARE_PLACES = Decimal("0.000001")

DEFINITIONS: Mapping[str, str] = MappingProxyType(
    {
        "cases_with_identified_judge": (
            "Cases on which the source names a judge - an assignment, or a decision, a "
            "charge disposition, a sentence, or a court event carrying a judge - over all "
            "cases. A case without one can enter only court-level metrics."
        ),
        "cases_with_final_disposition": (
            "Cases with a charge whose disposition is final (dismissed, acquitted, or a "
            "conviction) and dated - the disposed cases the disposition metrics read - over "
            "all cases. A pending, superseded, or transferred charge disposes of nothing."
        ),
        "cases_with_person_resolution": (
            "Cases whose charges, decisions, or sentences name a resolved defendant (the "
            "person after entity resolution) over all cases. The source's person-key scope "
            "is published beside it: cross_case when one person is followed across the "
            "source's cases, case when a person is a case participation and nothing can be "
            "followed beyond the case."
        ),
        "cases_with_adequate_follow_up": (
            "Cases whose follow-up anchor - the case disposition time when the case is "
            f"disposed, else its filing - lies at least {ADEQUATE_FOLLOW_UP_DAYS} days before "
            "the coverage end, over all cases: the cases whose one-year outcomes the source "
            "can observe in full."
        ),
        "cases_with_complete_charge_classification": (
            "Cases every charge of which carries a classified offense category and severity "
            "(neither unclassified), over the cases with at least one charge."
        ),
        "records_with_provenance": (
            "The case-level rows of the scope - the case, its charges, decisions, sentences, "
            "and court events - attributed to a retrieved source record with a sha256 digest, "
            "over the same rows. The schema requires a source record for every row, so a "
            "value below one is a defect."
        ),
        "unknown_actor_share": (
            "The decisions whose actor is unknown and the final dispositions whose actor is "
            "unknown or not recorded, over all decisions and final dispositions: the share of "
            "decisions no metric can attribute to a judge or anyone else."
        ),
    }
)

# Per-case flag columns (summed per scope).
CASE = "case_id"
COURT_ID = "court_id"
JURISDICTION_ID = "jurisdiction_id"
FLAGS: tuple[str, ...] = (
    "_cases",
    "_judge",
    "_final",
    "_person",
    "_adequate",
    "_charged",
    "_complete",
    "_rows",
    "_unknown",
    "_actors",
)
# statistic → (numerator flag, denominator flag)
COLUMNS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "cases_with_identified_judge": ("_judge", "_cases"),
        "cases_with_final_disposition": ("_final", "_cases"),
        "cases_with_person_resolution": ("_person", "_cases"),
        "cases_with_adequate_follow_up": ("_adequate", "_cases"),
        "cases_with_complete_charge_classification": ("_complete", "_charged"),
        "records_with_provenance": ("_rows", "_rows"),
        "unknown_actor_share": ("_unknown", "_actors"),
    }
)


class CoverageError(RuntimeError):
    """The statistics cannot be computed, stored, or read as asked."""


@dataclass(frozen=True, slots=True)
class CoverageDraft:
    """One statistic of one source and scope before it is stored."""

    source_id: str
    scope_type: str
    scope_id: str
    statistic: str
    numerator: int
    denominator: int

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.source_id, self.scope_type, self.scope_id, self.statistic)

    @property
    def share(self) -> Decimal | None:
        return share(self.numerator, self.denominator)


def share(numerator: int, denominator: int) -> Decimal | None:
    """``numerator / denominator`` at six decimals (``Numeric(9, 6)``); null without one."""
    if denominator == 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        SHARE_PLACES, rounding=ROUND_HALF_EVEN
    )


# --- computation ---------------------------------------------------------------------------


def _case_ids(rows: pl.DataFrame, condition: pl.Expr | None = None) -> pl.DataFrame:
    selected = rows if condition is None else rows.filter(condition)
    return selected.select(pl.col(CASE)).unique()


def _flag(cases: pl.DataFrame, ids: pl.DataFrame, name: str) -> pl.DataFrame:
    marked = ids.with_columns(pl.lit(1, dtype=pl.Int64).alias(name))
    return cases.join(marked, on=CASE, how="left").with_columns(pl.col(name).fill_null(0))


def _counts(rows: pl.DataFrame, name: str, condition: pl.Expr | None = None) -> pl.DataFrame:
    selected = rows if condition is None else rows.filter(condition)
    return selected.group_by(CASE).agg(pl.len().cast(pl.Int64).alias(name))


def case_flags(frame: Frame) -> pl.DataFrame:
    """One row per case of the frame: its court, its jurisdiction, and the ``FLAGS``."""
    cases = frame.cases.select(pl.col("id").alias(CASE), COURT_ID, "filed_at").join(
        frame.courts.select(pl.col("id").alias(COURT_ID), JURISDICTION_ID),
        on=COURT_ID,
        how="left",
    )
    cases = cases.with_columns(pl.lit(1, dtype=pl.Int64).alias("_cases"))

    named = pl.col("judge_id").is_not_null()
    judged = pl.concat(
        [
            _case_ids(frame.assignments),
            _case_ids(frame.decisions, named),
            _case_ids(frame.charges, named),
            _case_ids(frame.sentences, named),
            _case_ids(frame.events, named),
        ]
    ).unique()
    cases = _flag(cases, judged, "_judge")

    dispositions = case_dispositions(frame).select(CASE, "disposition_at")
    cases = cases.join(dispositions, on=CASE, how="left").with_columns(
        pl.col("disposition_at").is_not_null().cast(pl.Int64).alias("_final")
    )

    persons = frame.persons.select(pl.col("id").alias("person_id"))
    resolved = pl.concat(
        [
            table.select(CASE, "person_id").join(persons, on="person_id", how="semi")
            for table in (frame.charges, frame.decisions, frame.sentences)
        ]
    ).select(CASE)
    cases = _flag(cases, resolved.unique(), "_person")

    horizon = frame.coverage_end_exclusive_at - timedelta(days=ADEQUATE_FOLLOW_UP_DAYS)
    anchor = pl.coalesce(pl.col("disposition_at"), pl.col("filed_at"))
    cases = cases.with_columns(
        (anchor.is_not_null() & (anchor <= pl.lit(horizon))).cast(pl.Int64).alias("_adequate")
    )

    classified = (pl.col("offense_category") != UNCLASSIFIED) & (pl.col("severity") != UNCLASSIFIED)
    charges = frame.charges.group_by(CASE).agg(
        pl.len().cast(pl.Int64).alias("_n"),
        classified.fill_null(False).sum().cast(pl.Int64).alias("_classified"),
    )
    cases = cases.join(charges, on=CASE, how="left").with_columns(
        (pl.col("_n").fill_null(0) > 0).cast(pl.Int64).alias("_charged"),
        (
            (pl.col("_n").fill_null(0) > 0)
            & (pl.col("_classified").fill_null(0) == pl.col("_n").fill_null(0))
        )
        .cast(pl.Int64)
        .alias("_complete"),
    )

    children = [
        _counts(frame.charges, "_charges"),
        _counts(frame.decisions, "_decisions"),
        _counts(frame.sentences, "_sentences"),
        _counts(frame.events, "_events"),
    ]
    for counts in children:
        cases = cases.join(counts, on=CASE, how="left")
    cases = cases.with_columns(
        (
            pl.lit(1, dtype=pl.Int64)
            + pl.col("_charges").fill_null(0)
            + pl.col("_decisions").fill_null(0)
            + pl.col("_sentences").fill_null(0)
            + pl.col("_events").fill_null(0)
        ).alias("_rows")
    )

    finals = disposed_charges(frame)
    unknown_actor = pl.col("actor_type") == UNKNOWN
    unknown_disposer = pl.col("disposition_actor").is_null() | (
        pl.col("disposition_actor") == UNKNOWN
    )
    actor_counts = [
        _counts(frame.decisions, "_d_all"),
        _counts(frame.decisions, "_d_unknown", unknown_actor),
        _counts(finals, "_f_all"),
        _counts(finals, "_f_unknown", unknown_disposer),
    ]
    for counts in actor_counts:
        cases = cases.join(counts, on=CASE, how="left")
    cases = cases.with_columns(
        (pl.col("_d_unknown").fill_null(0) + pl.col("_f_unknown").fill_null(0)).alias("_unknown"),
        (pl.col("_d_all").fill_null(0) + pl.col("_f_all").fill_null(0)).alias("_actors"),
    )
    return cases.select(CASE, COURT_ID, JURISDICTION_ID, *FLAGS)


def _drafts(source_id: str, scope_type: str, totals: pl.DataFrame, key: str) -> list[CoverageDraft]:
    drafts: list[CoverageDraft] = []
    for row in totals.sort(key).iter_rows(named=True):
        scope_id = row[key]
        if scope_id is None:
            continue
        for statistic in STATISTICS:
            numerator, denominator = COLUMNS[statistic]
            drafts.append(
                CoverageDraft(
                    source_id=source_id,
                    scope_type=scope_type,
                    scope_id=str(scope_id),
                    statistic=statistic,
                    numerator=int(row[numerator]),
                    denominator=int(row[denominator]),
                )
            )
    return drafts


def frame_statistics(frame: Frame, source_id: str) -> list[CoverageDraft]:
    """Every statistic of one source's frame: the source, each jurisdiction, each court."""
    flags = case_flags(frame)
    sums = [pl.col(name).sum().cast(pl.Int64).alias(name) for name in FLAGS]
    whole = flags.select(*sums).with_columns(pl.lit(source_id).alias("_scope"))
    drafts = _drafts(source_id, SOURCE_SCOPE, whole, "_scope")
    by_jurisdiction = flags.group_by(JURISDICTION_ID).agg(*sums)
    drafts.extend(_drafts(source_id, JURISDICTION_SCOPE, by_jurisdiction, JURISDICTION_ID))
    by_court = flags.group_by(COURT_ID).agg(*sums)
    drafts.extend(_drafts(source_id, COURT_SCOPE, by_court, COURT_ID))
    return drafts


def compute_statistics(snapshot: Snapshot) -> list[CoverageDraft]:
    """The statistics of every source of the snapshot with case data and a coverage window."""
    drafts: list[CoverageDraft] = []
    for source in snapshot.sources_with_cases():
        if not source.has_coverage:
            continue
        drafts.extend(frame_statistics(snapshot.frame(source.id), source.id))
    return drafts


# --- storage -----------------------------------------------------------------------------

TABLE = Base.metadata.tables["coverage_statistic"]
UPDATED_COLUMNS: tuple[str, ...] = ("numerator", "denominator", "share", "methodology_version")
BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class CoverageResult:
    statistics: int
    written: int

    def as_log(self) -> dict[str, Any]:
        return {"coverage_statistics": self.statistics, "coverage_written": self.written}


def _row(draft: CoverageDraft, snapshot_id: uuid.UUID, methodology: str) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot_id,
        "source_id": uuid.UUID(draft.source_id),
        "scope_type": draft.scope_type,
        "scope_id": uuid.UUID(draft.scope_id),
        "statistic": draft.statistic,
        "numerator": draft.numerator,
        "denominator": draft.denominator,
        "share": draft.share,
        "methodology_version": methodology,
    }


def publish_statistics(
    session: Session,
    snapshot_id: uuid.UUID,
    drafts: Sequence[CoverageDraft],
    methodology_version: str,
) -> CoverageResult:
    """Upsert the statistics of one snapshot; a row whose values did not change is not written."""
    statement = insert(TABLE)
    excluded = statement.excluded
    upsert = statement.on_conflict_do_update(
        constraint="uq_coverage_statistic_key",
        set_={
            **{column: excluded[column] for column in UPDATED_COLUMNS},
            "updated_at": sa.func.now(),
        },
        where=sa.or_(
            *(TABLE.c[column].is_distinct_from(excluded[column]) for column in UPDATED_COLUMNS)
        ),
    )
    rows = [_row(draft, snapshot_id, methodology_version) for draft in drafts]
    written = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        result = session.execute(upsert.returning(TABLE.c.id), batch)
        written += len(result.all())
    log.info("metrics.coverage.published", statistics=len(rows), written=written)
    return CoverageResult(statistics=len(rows), written=written)


@dataclass(frozen=True, slots=True)
class StoredStatistic:
    source_id: str
    scope_type: str
    scope_id: str
    statistic: str
    numerator: int
    denominator: int
    share: Decimal | None
    methodology_version: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.source_id, self.scope_type, self.scope_id, self.statistic)


def load_statistics(session: Session, snapshot_id: uuid.UUID) -> list[StoredStatistic]:
    """The stored statistics of one snapshot."""
    rows = session.execute(
        select(
            TABLE.c.source_id,
            TABLE.c.scope_type,
            TABLE.c.scope_id,
            TABLE.c.statistic,
            TABLE.c.numerator,
            TABLE.c.denominator,
            TABLE.c.share,
            TABLE.c.methodology_version,
        )
        .where(TABLE.c.snapshot_id == snapshot_id)
        .order_by(TABLE.c.source_id, TABLE.c.scope_type, TABLE.c.scope_id, TABLE.c.statistic)
    ).all()
    return [
        StoredStatistic(
            source_id=str(row.source_id),
            scope_type=str(row.scope_type),
            scope_id=str(row.scope_id),
            statistic=str(row.statistic),
            numerator=int(row.numerator),
            denominator=int(row.denominator),
            share=None if row.share is None else Decimal(row.share),
            methodology_version=str(row.methodology_version),
        )
        for row in rows
    ]


@dataclass(frozen=True, slots=True)
class CoverageMismatch:
    """A stored statistic that the snapshot no longer reproduces (or one it lacks)."""

    snapshot: str
    source_id: str
    scope_type: str
    scope_id: str
    statistic: str
    column: str
    stored: Any
    recomputed: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot,
            "source_id": self.source_id,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "statistic": self.statistic,
            "column": self.column,
            "stored": None if self.stored is None else str(self.stored),
            "recomputed": None if self.recomputed is None else str(self.recomputed),
        }


def compare_statistics(
    content_hash: str, stored: Iterable[StoredStatistic], drafts: Iterable[CoverageDraft]
) -> list[CoverageMismatch]:
    """Every difference between the stored statistics and a recompute, by scope and name."""
    recomputed = {draft.key: draft for draft in drafts}
    found: list[CoverageMismatch] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in stored:
        seen.add(item.key)
        draft = recomputed.get(item.key)
        if draft is None:
            found.append(
                CoverageMismatch(content_hash, *item.key, "statistic", "present", "absent")
            )
            continue
        for column, stored_value, value in (
            ("numerator", item.numerator, draft.numerator),
            ("denominator", item.denominator, draft.denominator),
            ("share", item.share, draft.share),
        ):
            if stored_value != value:
                found.append(CoverageMismatch(content_hash, *item.key, column, stored_value, value))
    for key, draft in sorted(recomputed.items()):
        if key not in seen:
            found.append(
                CoverageMismatch(content_hash, *draft.key, "statistic", "absent", "present")
            )
    return found


# --- reading (the CLI) -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoverageRow:
    """One statistic as ``metrics coverage`` prints it (names, never a person or a case)."""

    source: str
    person_key_scope: str | None
    scope_type: str
    scope_id: str
    scope_name: str
    statistic: str
    numerator: int
    denominator: int
    share: Decimal | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "person_key_scope": self.person_key_scope,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "scope_name": self.scope_name,
            "statistic": self.statistic,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "share": None if self.share is None else float(self.share),
        }


SCOPE_ORDER: Mapping[str, int] = MappingProxyType({name: i for i, name in enumerate(SCOPES)})
STATISTIC_ORDER: Mapping[str, int] = MappingProxyType(
    {name: i for i, name in enumerate(STATISTICS)}
)


def latest_statistics(
    session: Session, *, sources: Sequence[str] | None = None
) -> tuple[str | None, list[CoverageRow]]:
    """The latest snapshot holding statistics and its rows (of ``sources``, by register name).

    Three statements: the snapshot, its statistics joined to their sources, and
    the names of the courts and jurisdictions they scope.
    """
    latest = session.execute(
        select(MetricSnapshot.id, MetricSnapshot.content_hash)
        .where(MetricSnapshot.id.in_(select(TABLE.c.snapshot_id).distinct()))
        .order_by(MetricSnapshot.exported_at.desc(), MetricSnapshot.id)
        .limit(1)
    ).first()
    if latest is None:
        return None, []
    statement = (
        select(
            Source.name,
            Source.capabilities,
            TABLE.c.scope_type,
            TABLE.c.scope_id,
            TABLE.c.statistic,
            TABLE.c.numerator,
            TABLE.c.denominator,
            TABLE.c.share,
        )
        .join(Source, Source.id == TABLE.c.source_id)
        .where(TABLE.c.snapshot_id == latest.id)
    )
    if sources is not None:
        statement = statement.where(Source.name.in_(sorted(sources)))
    rows = session.execute(statement).all()
    court_ids = {row.scope_id for row in rows if row.scope_type == COURT_SCOPE}
    jurisdiction_ids = {row.scope_id for row in rows if row.scope_type == JURISDICTION_SCOPE}
    names: dict[str, str] = {}
    if court_ids or jurisdiction_ids:
        names_statement = (
            select(Court.id, Court.canonical_name)
            .where(Court.id.in_(sorted(court_ids, key=str)))
            .union_all(
                select(Jurisdiction.id, Jurisdiction.name).where(
                    Jurisdiction.id.in_(sorted(jurisdiction_ids, key=str))
                )
            )
        )
        names = {str(row[0]): str(row[1]) for row in session.execute(names_statement).all()}
    result = [
        CoverageRow(
            source=str(row.name),
            person_key_scope=(row.capabilities or {}).get("person_key_scope"),
            scope_type=str(row.scope_type),
            scope_id=str(row.scope_id),
            scope_name=str(row.name)
            if row.scope_type == SOURCE_SCOPE
            else names.get(str(row.scope_id), str(row.scope_id)),
            statistic=str(row.statistic),
            numerator=int(row.numerator),
            denominator=int(row.denominator),
            share=None if row.share is None else Decimal(row.share),
        )
        for row in rows
    ]
    result.sort(
        key=lambda item: (
            item.source,
            SCOPE_ORDER.get(item.scope_type, len(SCOPE_ORDER)),
            item.scope_name,
            item.scope_id,
            STATISTIC_ORDER.get(item.statistic, len(STATISTIC_ORDER)),
        )
    )
    return str(latest.content_hash), result
