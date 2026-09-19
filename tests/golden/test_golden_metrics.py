# tests/golden/test_golden_metrics.py
"""Every registry metric equals its truth expectation on the golden fixture.

After the module's golden ingest, ``metrics compute`` runs through the
Python API (the shared ``golden_metrics`` fixture: ``compute_and_publish``
as the ingest role, the snapshot under a temporary directory): for every
judge and court of ``truth/metrics.json``
and every registry metric, the current observation's ``observed_count``,
``cohort_size``, ``eligible_count``, ``observed_rate`` (six decimals),
``value``, ``distribution``, and the Kaplan-Meier bounds equal the truth
entry through the table in ``truth_map.py`` (one test per subject and
slug; the assertion names the truth path, window, dimension, and column);
every metric under the truth's ``not_observable`` has no observation and
is reported not observable; ``verify()`` returns zero mismatches;
tampering one observation's ``observed_count`` inside a rolled-back
session makes ``verify()`` report exactly that observation and column;
every member id exists in the canonical tables; a second compute
publishes nothing; the snapshot exports no restricted table.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import polars as pl
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from judgemetrics.db.models import Base, MetricObservation, MetricObservationMember, MetricSnapshot
from judgemetrics.db.models.enums import SubjectType
from judgemetrics.db.session import make_engine
from judgemetrics.metrics.engine import compute_and_publish
from judgemetrics.metrics.registry import load_registry
from judgemetrics.metrics.snapshot import (
    MEMBER_TABLES,
    RESTRICTED_TABLES,
    SNAPSHOT_TABLES,
    open_snapshot,
)
from judgemetrics.metrics.verify import verify
from tests.golden.conftest import GOLDEN, GoldenFixture, GoldenMetrics
from tests.golden.truth_map import (
    COURT_ONLY_SLUGS,
    NOT_OBSERVABLE_SLUGS,
    Expectation,
    expectations,
    subject_blocks,
)

pytestmark = [pytest.mark.golden, pytest.mark.integration]

TRUTH: dict[str, Any] = json.loads((GOLDEN / "truth" / "metrics.json").read_text(encoding="utf-8"))
REGISTRY = load_registry()
SUBJECTS: list[tuple[str, str]] = [(kind, code) for kind, code, _ in subject_blocks(TRUTH)]
CASES: list[tuple[str, str, str]] = [
    (kind, code, definition.slug)
    for kind, code in SUBJECTS
    for definition in REGISTRY.for_subject(kind)
    if definition.slug not in NOT_OBSERVABLE_SLUGS
]
COLUMNS: dict[str, str] = {
    "observed_count": "observed_count",
    "cohort_size": "cohort_size",
    "eligible_count": "eligible_count",
    "observed_rate": "observed_rate",
    "value": "value",
    "distribution": "distribution",
    "lower_confidence_bound": "lower_confidence_bound",
    "upper_confidence_bound": "upper_confidence_bound",
}


@pytest.fixture
def ingest_session(golden_metrics: GoldenMetrics) -> Iterator[Session]:
    """A session as the ingest role, rolled back afterwards (tampering stays local)."""
    engine = make_engine(golden_metrics.settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            yield session
            session.rollback()
    finally:
        engine.dispose()


def _subject_id(golden_fixture: GoldenFixture, kind: str, code: str) -> uuid.UUID:
    return golden_fixture.judge_ids[code] if kind == "judge" else golden_fixture.court_ids[code]


def _current(session: Session, subject_type: str, subject_id: uuid.UUID) -> list[MetricObservation]:
    return list(
        session.scalars(
            select(MetricObservation).where(
                MetricObservation.subject_type == SubjectType(subject_type),
                MetricObservation.subject_id == subject_id,
                MetricObservation.superseded_at.is_(None),
            )
        )
    )


def _normalize(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in ("observed_rate", "lower_confidence_bound", "upper_confidence_bound"):
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    if column == "value":
        return Decimal(str(value)).quantize(Decimal("0.0001"))
    if column == "distribution":
        return {str(k): int(v) for k, v in dict(value).items()}
    return int(value)


def _expectations_for(kind: str, code: str, slug: str) -> list[Expectation]:
    block = TRUTH["judges" if kind == "judge" else "courts"][code]
    return [item for item in expectations(block, kind) if item.slug == slug]


@pytest.mark.parametrize(("kind", "code", "slug"), CASES, ids=[f"{k}-{c}-{s}" for k, c, s in CASES])
def test_every_observation_equals_its_truth_expectation(
    session: Session,
    golden_fixture: GoldenFixture,
    golden_metrics: GoldenMetrics,
    kind: str,
    code: str,
    slug: str,
) -> None:
    del golden_metrics
    expected = _expectations_for(kind, code, slug)
    subject_id = _subject_id(golden_fixture, kind, code)
    observations = {
        (row.window_days, row.dimension_value): row
        for row in _current(session, kind, subject_id)
        if row.definition.slug == slug
    }
    if not expected:
        # A subject without an incarcerating sentence has no category to group by.
        assert slug == "incarceration_days_median_by_offense_category", (
            f"{kind} {code}: the truth file has no entry for {slug}"
        )
        assert not observations, f"{kind} {code}: {slug} published without a truth entry"
        return
    for item in expected:
        observation = observations.get((item.window_days, item.dimension_value))
        assert observation is not None, f"{kind} {code}: no observation for {item.label}"
        for column, truth_value in item.columns.items():
            stored = getattr(observation, COLUMNS[column])
            assert _normalize(column, stored) == _normalize(column, truth_value), (
                f"{kind} {code} {item.label} column {column}: stored {stored!r}, "
                f"truth {truth_value!r}"
            )
        assert observation.definition.version == REGISTRY[slug].version
        assert observation.registry_version == REGISTRY.version
        assert observation.methodology_version == REGISTRY.methodology_version
        assert observation.period_start.isoformat() == TRUTH["corpus"]["start"]
        assert observation.period_end.isoformat() == TRUTH["corpus"]["end"]
        assert observation.suppressed_flag == (
            observation.cohort_size < REGISTRY[slug].suppression_threshold
        )
    # Nothing beyond the truth's windows and dimensions was published for this slug.
    assert set(observations) == {(item.window_days, item.dimension_value) for item in expected}


@pytest.mark.parametrize(("kind", "code"), SUBJECTS, ids=[f"{k}-{c}" for k, c in SUBJECTS])
@pytest.mark.parametrize("slug", sorted(NOT_OBSERVABLE_SLUGS))
def test_not_observable_metrics_have_no_observation_and_are_reported(
    session: Session,
    golden_fixture: GoldenFixture,
    golden_metrics: GoldenMetrics,
    kind: str,
    code: str,
    slug: str,
) -> None:
    subject_id = _subject_id(golden_fixture, kind, code)
    assert not [
        row for row in _current(session, kind, subject_id) if row.definition.slug == slug
    ], f"{kind} {code}: {slug} must not be published for the synthetic source"
    outcome = NOT_OBSERVABLE_SLUGS[slug]
    assert {item["outcome"] for item in TRUTH["not_observable"]} >= {outcome}
    reported = [
        item
        for item in golden_metrics.result.computed.not_observable
        if item.slug == slug and item.subject_type == kind and item.subject_id == str(subject_id)
    ]
    assert len(reported) == 1 and reported[0].outcome == outcome


def test_court_only_metrics_are_never_published_for_a_judge(
    session: Session, golden_fixture: GoldenFixture, golden_metrics: GoldenMetrics
) -> None:
    del golden_metrics
    for judge_id in golden_fixture.judge_ids.values():
        slugs = {row.definition.slug for row in _current(session, "judge", judge_id)}
        assert not slugs & COURT_ONLY_SLUGS


def test_every_golden_subject_has_current_observations(
    session: Session, golden_fixture: GoldenFixture, golden_metrics: GoldenMetrics
) -> None:
    for kind, code in SUBJECTS:
        rows = _current(session, kind, _subject_id(golden_fixture, kind, code))
        assert rows, f"{kind} {code} has no current observation"
        assert {row.snapshot.content_hash for row in rows} == {
            golden_metrics.result.snapshot.content_hash
        }


def test_verify_reports_zero_mismatches(
    ingest_session: Session, golden_metrics: GoldenMetrics
) -> None:
    result = verify(ingest_session, golden_metrics.settings)
    assert result.ok, [m.as_dict() for m in result.mismatches[:5]] + [
        u.as_dict() for u in result.unverifiable[:5]
    ]
    assert result.observations == result.verified > 0
    assert result.snapshots == [golden_metrics.result.snapshot.content_hash]


def test_tampering_one_observation_is_reported_by_id_and_column(
    ingest_session: Session, golden_metrics: GoldenMetrics
) -> None:
    session = ingest_session
    target = session.scalar(
        select(MetricObservation)
        .join(MetricObservation.definition)
        .where(MetricObservation.superseded_at.is_(None))
        .order_by(MetricObservation.id)
        .limit(1)
    )
    assert target is not None
    session.execute(
        update(MetricObservation)
        .where(MetricObservation.id == target.id)
        .values(observed_count=MetricObservation.observed_count + 1)
    )
    result = verify(session, golden_metrics.settings)
    assert not result.unverifiable
    assert [(m.observation_id, m.column) for m in result.mismatches] == [
        (target.id, "observed_count")
    ]
    mismatch = result.mismatches[0]
    assert mismatch.slug == target.definition.slug
    assert int(mismatch.stored) == int(mismatch.recomputed) + 1
    assert result.verified == result.observations - 1


def test_every_member_id_exists_in_the_canonical_tables(
    session: Session, golden_metrics: GoldenMetrics
) -> None:
    del golden_metrics
    kinds = {
        row[0]
        for row in session.execute(select(MetricObservationMember.member_kind).distinct()).all()
    }
    assert kinds and kinds <= set(MEMBER_TABLES)
    for kind in sorted(kinds):
        table = Base.metadata.tables[
            {
                "court_case": "court_case",
                "decision": "decision",
                "charge": "charge",
                "sentence": "sentence",
                "court_event": "court_event",
                "justice_event": "justice_event",
            }[kind]
        ]
        member_ids = set(
            session.scalars(
                select(MetricObservationMember.member_id)
                .where(MetricObservationMember.member_kind == kind)
                .distinct()
            )
        )
        assert member_ids
        existing = set(session.scalars(select(table.c.id).where(table.c.id.in_(member_ids))))
        assert member_ids == existing, kind
    # Every current observation with a non-zero eligible count has members.
    without = session.scalar(
        select(func.count())
        .select_from(MetricObservation)
        .where(
            MetricObservation.superseded_at.is_(None),
            MetricObservation.eligible_count > 0,
            ~MetricObservation.id.in_(select(MetricObservationMember.observation_id)),
        )
    )
    assert without == 0


def test_a_second_compute_publishes_nothing(golden_metrics: GoldenMetrics) -> None:
    engine = make_engine(golden_metrics.settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            again = compute_and_publish(session, golden_metrics.settings)
            session.rollback()
    finally:
        engine.dispose()
    assert again.snapshot.reused
    assert again.snapshot.content_hash == golden_metrics.result.snapshot.content_hash
    assert again.published.observations_published == 0
    assert again.published.superseded == 0
    assert again.published.members_written == 0
    assert again.published.subjects_unchanged == len(SUBJECTS)


def test_the_snapshot_exports_no_restricted_table_and_persons_are_ids_only(
    session: Session, golden_metrics: GoldenMetrics
) -> None:
    content_hash = golden_metrics.result.snapshot.content_hash
    directory = golden_metrics.snapshot_dir / content_hash
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["tables"]) == set(SNAPSHOT_TABLES)
    assert not set(manifest["tables"]) & set(RESTRICTED_TABLES)
    assert not [p for p in directory.iterdir() if p.stem in RESTRICTED_TABLES]
    persons = pl.read_parquet(directory / "persons.parquet")
    assert persons.columns == ["id", "merged_into_person_id"]
    row = session.scalar(select(MetricSnapshot).where(MetricSnapshot.content_hash == content_hash))
    assert row is not None and row.label == "golden test"
    assert row.row_counts["cases"] == manifest["tables"]["cases"]["rows"] > 0
    with open_snapshot(golden_metrics.settings, content_hash) as opened:
        assert [source.name for source in opened.sources_with_cases()] == ["synthetic"]
        source = opened.sources_with_cases()[0]
        assert source.coverage_start is not None and source.coverage_end is not None
        assert (source.coverage_start.isoformat(), source.coverage_end.isoformat()) == (
            TRUTH["corpus"]["start"],
            TRUTH["corpus"]["end"],
        )
        assert source.observable_outcomes == set(TRUTH["observable_outcomes"])
