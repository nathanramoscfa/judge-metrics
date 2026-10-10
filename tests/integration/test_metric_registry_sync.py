# tests/integration/test_metric_registry_sync.py
"""``sync_definitions`` mirrors the registry into ``metric_definition`` idempotently.

The first sync inserts one row per registry metric; a second sync inserts
and updates nothing; a changed entry updates exactly its row; a new
version inserts beside the old one and never deletes it. Every example
runs inside the root conftest's rolled-back ``db_session`` on the scratch
database, so nothing persists.
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.db.models import MetricDefinition
from judgemetrics.metrics.registry import load_registry, sync_definitions

pytestmark = pytest.mark.integration


def _rows(session: Session) -> dict[tuple[str, str], MetricDefinition]:
    return {
        (row.slug, row.version): row
        for row in session.scalars(select(MetricDefinition)).all()
        if row.registry_version >= 1
    }


def test_sync_inserts_every_metric_once_and_is_idempotent(db_session: Session) -> None:
    registry = load_registry()
    before = {(row.slug, row.version) for row in db_session.scalars(select(MetricDefinition))}
    first = sync_definitions(db_session)
    keys = {(metric.slug, metric.version) for metric in registry.metrics.values()}
    assert first.inserted == len(keys - before)
    assert first.updated == 0
    rows = _rows(db_session)
    for metric in registry.metrics.values():
        row = rows[(metric.slug, metric.version)]
        assert row.kind == metric.kind
        assert row.subject_types == list(metric.subject_types)
        assert row.attribution == metric.attribution.as_dict()
        assert row.index_event == metric.index_event and row.outcome == metric.outcome
        assert row.windows_days == (
            None if metric.windows_days is None else list(metric.windows_days)
        )
        assert row.dimension == metric.dimension
        assert row.suppression_threshold == metric.suppression_threshold
        assert row.unit == metric.unit
        assert row.registry_version == registry.version
        assert row.methodology_version == registry.methodology_version
        assert row.numerator_definition == metric.numerator
        assert row.denominator_definition == metric.denominator
        assert row.eligibility_definition == metric.eligibility
    second = sync_definitions(db_session)
    assert (second.inserted, second.updated) == (0, 0)
    assert second.unchanged == len(registry.metrics)
    assert second.total == first.total == len(registry.metrics)


def test_sync_updates_only_changed_rows_and_never_deletes(db_session: Session) -> None:
    registry = load_registry()
    sync_definitions(db_session, registry)
    metrics = dict(registry.metrics)
    assert metrics["eligible_cases"].version == "1"
    changed = replace(metrics["eligible_cases"], description="A different description.")
    metrics["eligible_cases"] = changed
    edited = replace(registry, metrics=MappingProxyType(metrics))
    result = sync_definitions(db_session, edited)
    assert (result.inserted, result.updated, result.unchanged) == (0, 1, len(metrics) - 1)
    row = _rows(db_session)[("eligible_cases", "1")]
    assert row.description == "A different description."

    bumped = dict(metrics)
    bumped["eligible_cases"] = replace(changed, version="2", name="Eligible cases (v2)")
    kept = (metrics["probation_days_median"].slug, metrics["probation_days_median"].version)
    del bumped["probation_days_median"]
    result = sync_definitions(db_session, replace(edited, metrics=MappingProxyType(bumped)))
    assert (result.inserted, result.updated) == (1, 0)
    rows = _rows(db_session)
    assert ("eligible_cases", "1") in rows and ("eligible_cases", "2") in rows
    assert kept in rows, "a sync never deletes a definition"
