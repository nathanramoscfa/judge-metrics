# tests/integration/test_member_storage.py
"""Member families in the database: what is stored is what was computed, and nothing is lost.

Over the module's golden ingest and its committed ``metrics compute``: every current
observation's member multiset, read through the SQL projection, equals the multiset of the
draft the engine computed (the Polars filter of the same family), the stored rows hash to
the family's recorded digest, and the SQL and Polars projections agree for every observation
of every family. Revival (an observation a publish superseded that the same snapshot produces
again) points the row at its family without deleting or writing a member; a changed family is a
new row and the observations that cited the old one keep it. The last test round-trips the
golden data through migration 0013 both ways and requires every observation's multiset, and
every family's digest, to come back as it was (the hand-built shapes are in
``test_member_conversion``).
"""

from __future__ import annotations

import dataclasses
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterator
from typing import Any

import polars as pl
import pytest
from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.orm import Session

from judgemetrics.db.migrations import downgrade, upgrade
from judgemetrics.db.models import (
    MetricDefinition,
    MetricMember,
    MetricMemberFamily,
    MetricObservation,
)
from judgemetrics.db.session import make_engine
from judgemetrics.metrics.compute import ObservationDraft
from judgemetrics.metrics.member_store import observation_members, read_family
from judgemetrics.metrics.members import COUNTED, MemberFamily, mode_for, windows_for
from judgemetrics.metrics.publish import publish
from judgemetrics.metrics.registry import load_registry
from judgemetrics.metrics.snapshot import open_snapshot
from tests.golden.conftest import GoldenFixture, GoldenMetrics

pytestmark = [pytest.mark.golden, pytest.mark.integration]

REGISTRY = load_registry()


@pytest.fixture
def session(migrated_database: Engine, golden_fixture: GoldenFixture) -> Iterator[Session]:
    """A read-only session over the module's committed golden ingest."""
    del golden_fixture
    with Session(migrated_database) as session:
        yield session
        session.rollback()


@pytest.fixture
def ingest_session(golden_metrics: GoldenMetrics) -> Iterator[Session]:
    """A session as the ingest role, rolled back afterwards (nothing here is committed)."""
    engine = make_engine(golden_metrics.settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            yield session
            session.rollback()
    finally:
        engine.dispose()


def _current(session: Session) -> list[MetricObservation]:
    return list(
        session.scalars(
            select(MetricObservation)
            .where(MetricObservation.superseded_at.is_(None))
            .order_by(MetricObservation.id)
        )
    )


def _drafts_by_key(golden_metrics: GoldenMetrics) -> dict[tuple[Any, ...], ObservationDraft]:
    return {draft.key: draft for draft in golden_metrics.result.computed.drafts}


def _key(session: Session, observation: MetricObservation) -> tuple[Any, ...]:
    definition = observation.definition
    return (
        definition.slug,
        observation.subject_type.value,
        str(observation.subject_id),
        str(observation.source_id),
        observation.period_start,
        observation.period_end,
        observation.window_days,
        observation.dimension_value,
        observation.calendar_year,
    )


def test_every_stored_observation_has_the_members_the_engine_computed(
    session: Session, golden_metrics: GoldenMetrics
) -> None:
    drafts = _drafts_by_key(golden_metrics)
    observations = _current(session)
    assert len(observations) == len(drafts) > 100
    slug_of: dict[uuid.UUID, str] = {}
    for observation in observations:
        draft = drafts[_key(session, observation)]
        assert draft.family is not None
        stored = Counter(
            (m.kind, m.id, m.counted, m.followed)
            for m in observation_members(session, observation.id)
        )
        assert stored == Counter(m.as_tuple() for m in draft.members), observation.id
        family = session.get(MetricMemberFamily, observation.member_family_id)
        assert family is not None
        assert family.members_hash == draft.family.digest
        assert (family.member_kind, family.row_count, family.member_count) == (
            draft.family.kind,
            draft.family.row_count,
            draft.family.member_count,
        )
        slug_of[family.id] = observation.definition.slug
    # The stored rows hash to the recorded digest, once per family.
    for family_id, slug in slug_of.items():
        family = session.get(MetricMemberFamily, family_id)
        assert family is not None
        definition = REGISTRY.metrics[slug]
        restored = read_family(
            session,
            family_id,
            kind=family.member_kind,
            mode=mode_for(definition.kind, definition.dimension),
            windows=windows_for(definition.kind, definition.windows_days),
        )
        assert restored.digest == family.members_hash
        assert restored.row_count == family.row_count
    # One family serves every window, year, and dimension of a definition and subject.
    assert len(slug_of) < len(observations) / 3


def test_the_sql_projection_and_the_polars_projection_agree_for_every_observation(
    session: Session, golden_metrics: GoldenMetrics
) -> None:
    del golden_metrics
    cache: dict[uuid.UUID, MemberFamily] = {}
    checked = 0
    for observation in _current(session):
        slug = observation.definition.slug
        definition = REGISTRY.metrics[slug]
        family_row = session.get(MetricMemberFamily, observation.member_family_id)
        assert family_row is not None
        if family_row.id not in cache:
            cache[family_row.id] = read_family(
                session,
                family_row.id,
                kind=family_row.member_kind,
                mode=mode_for(definition.kind, definition.dimension),
                windows=windows_for(definition.kind, definition.windows_days),
            )
        in_memory = cache[family_row.id].members(
            year=observation.calendar_year,
            window=observation.window_days,
            dimension=observation.dimension_value,
        )
        in_sql = observation_members(session, observation.id)
        assert Counter(m.as_tuple() for m in in_memory) == Counter(m.as_tuple() for m in in_sql)
        checked += 1
    assert checked > 100


def _one_judge(session: Session) -> uuid.UUID:
    """A judge with observations of several kinds (descriptive and adjusted)."""
    rows = session.execute(
        select(MetricObservation.subject_id, func.count())
        .where(MetricObservation.superseded_at.is_(None), MetricObservation.subject_type == "judge")
        .group_by(MetricObservation.subject_id)
        .order_by(func.count().desc(), MetricObservation.subject_id)
    ).first()
    assert rows is not None
    return uuid.UUID(str(rows[0]))


def _subject_drafts(golden_metrics: GoldenMetrics, judge: uuid.UUID) -> list[ObservationDraft]:
    return [d for d in golden_metrics.result.computed.drafts if d.subject_id == str(judge)]


def test_a_revived_observation_keeps_its_members_and_nothing_is_deleted(
    ingest_session: Session, golden_metrics: GoldenMetrics
) -> None:
    session = ingest_session
    judge = _one_judge(session)
    drafts = _subject_drafts(golden_metrics, judge)
    before = {(o.id, o.member_family_id) for o in _current(session) if o.subject_id == judge}
    assert len(before) == len(drafts) > 20
    families_before = session.scalar(select(func.count()).select_from(MetricMemberFamily))
    rows_before = session.scalar(select(func.count()).select_from(MetricMember))
    # A previous publish superseded them (as a recompute that changed something would).
    session.execute(
        update(MetricObservation)
        .where(MetricObservation.subject_id == judge, MetricObservation.superseded_at.is_(None))
        .values(superseded_at=func.now())
    )
    with open_snapshot(
        golden_metrics.settings, golden_metrics.result.snapshot.content_hash
    ) as snapshot:
        result = publish(session, snapshot, drafts, REGISTRY, golden_metrics.settings)
    assert result.observations_published == len(drafts)
    assert result.members_written == 0 and result.families_written == 0
    # The same rows, current again and pointing at the families they had.
    after = {(o.id, o.member_family_id) for o in _current(session) if o.subject_id == judge}
    assert after == before
    assert session.scalar(select(func.count()).select_from(MetricMemberFamily)) == families_before
    assert session.scalar(select(func.count()).select_from(MetricMember)) == rows_before


def test_a_changed_family_is_a_new_row_and_the_old_one_stays_for_history(
    ingest_session: Session, golden_metrics: GoldenMetrics
) -> None:
    session = ingest_session
    judge = _one_judge(session)
    drafts = _subject_drafts(golden_metrics, judge)
    target = next(
        d
        for d in drafts
        if d.family is not None and d.family.row_count > 2 and d.family.kind == "decision"
    )
    assert target.family is not None
    old_family_id = session.scalar(
        select(MetricObservation.member_family_id)
        .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
        .where(
            MetricObservation.subject_id == judge,
            MetricObservation.superseded_at.is_(None),
            MetricDefinition.slug == target.slug,
            MetricObservation.window_days.is_not_distinct_from(target.window_days),
            MetricObservation.dimension_value.is_not_distinct_from(target.dimension_value),
            MetricObservation.calendar_year.is_not_distinct_from(target.calendar_year),
        )
    )
    assert old_family_id is not None
    rows = target.family.rows
    altered = rows.with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.col(COUNTED) ^ 1)
        .otherwise(pl.col(COUNTED))
        .alias(COUNTED)
    )
    changed = MemberFamily.from_stored(
        target.family.kind, target.family.mode, target.family.windows, altered
    )
    assert changed.digest != target.family.digest
    edited = [
        dataclasses.replace(d, family=changed) if d.family is target.family else d for d in drafts
    ]
    families_before = session.scalar(select(func.count()).select_from(MetricMemberFamily))
    with open_snapshot(
        golden_metrics.settings, golden_metrics.result.snapshot.content_hash
    ) as snapshot:
        result = publish(session, snapshot, edited, REGISTRY, golden_metrics.settings)
    # The definition's observations now cite one new family; the others still cite theirs.
    assert result.families_written == 1 and result.members_written == changed.row_count
    assert result.subjects_published == 1 and result.subjects_unchanged == 0
    assert (
        session.scalar(select(func.count()).select_from(MetricMemberFamily))
        == (families_before or 0) + 1
    )
    old = session.get(MetricMemberFamily, old_family_id)
    assert old is not None and old.members_hash == target.family.digest
    assert (
        session.scalar(
            select(func.count()).select_from(MetricMember).where(MetricMember.family_id == old.id)
        )
        == target.family.row_count
    )
    cited = set(
        session.scalars(
            select(MetricObservation.member_family_id).where(
                MetricObservation.subject_id == judge, MetricObservation.superseded_at.is_(None)
            )
        )
    )
    assert old_family_id not in cited


def test_the_migration_converts_the_golden_data_both_ways(
    migrated_database: Engine, golden_metrics: GoldenMetrics
) -> None:
    """Down to 0012 and back up: every multiset and every family digest is what it was."""
    url = migrated_database.url.render_as_string(hide_password=False)
    del golden_metrics
    with Session(migrated_database) as session:
        ids = [
            o.id for o in session.scalars(select(MetricObservation).order_by(MetricObservation.id))
        ]
        before = {
            oid: Counter(
                (m.kind, m.id, m.counted, m.followed) for m in observation_members(session, oid)
            )
            for oid in ids
        }
        hashes = {
            oid: session.scalar(
                select(MetricMemberFamily.members_hash)
                .join(
                    MetricObservation, MetricObservation.member_family_id == MetricMemberFamily.id
                )
                .where(MetricObservation.id == oid)
            )
            for oid in ids
        }
    assert len(ids) > 100
    downgrade(url, "0012")
    try:
        old: dict[uuid.UUID, Counter[Any]] = defaultdict(Counter)
        with migrated_database.connect() as connection:
            for observation_id, kind, member, counted, followed in connection.execute(
                text(
                    "SELECT observation_id, member_kind, member_id::text, counted, followed "
                    "FROM metric_observation_member"
                )
            ):
                old[observation_id][(kind, member, counted, followed)] += 1
        assert {oid: old.get(oid, Counter()) for oid in ids} == before
    finally:
        upgrade(url, "head")
    with Session(migrated_database) as session:
        after = {
            oid: Counter(
                (m.kind, m.id, m.counted, m.followed) for m in observation_members(session, oid)
            )
            for oid in ids
        }
        again = {
            oid: session.scalar(
                select(MetricMemberFamily.members_hash)
                .join(
                    MetricObservation, MetricObservation.member_family_id == MetricMemberFamily.id
                )
                .where(MetricObservation.id == oid)
            )
            for oid in ids
        }
    assert after == before
    # The family is the one the engine would build, with one exception the history cannot
    # settle: a median by dimension publishes a (dimension, year) observation only when it has
    # a value, so a member without a value in a year that has no observation of its dimension
    # appears in the whole window's observation alone and its year is unknown (null).
    with Session(migrated_database) as session:
        differing = {oid for oid in ids if again[oid] != hashes[oid]}
        kinds = {
            (o.definition.kind, o.definition.dimension)
            for o in session.scalars(
                select(MetricObservation).where(MetricObservation.id.in_(differing))
            )
        }
    assert kinds <= {("median", "offense_category")}, kinds
    assert len(differing) < len(ids) / 10
