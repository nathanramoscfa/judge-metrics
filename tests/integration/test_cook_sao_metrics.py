# tests/integration/test_cook_sao_metrics.py
"""Cook County's real rows through the metrics engine (Phase 5 Step 5).

The 73-case real-row fixture (``tests/fixtures/cook_sao``) is ingested into the
scratch database and ``metrics compute --source cook_sao`` runs over it, committed.
Under registry version 3 the source records the disposing and the sentencing judge
only, keys persons per case, and documents revoked supervision only, so:

- its judges carry the sentencing and the disposition families (at least one
  observation published unsuppressed), and no pretrial metric, case count, or
  adjusted ratio — each reported ``NotAttributable`` with its gate;
- its courts carry the bond decisions' pretrial counts;
- every cross-case outcome and a revoked pretrial release are ``NotObservable``
  for judges and courts alike, while the revocation rates after a sentence are
  published;
- the catalogue records every target ``unavailable`` with the specification's
  reason, and nothing is fitted;
- the coverage statistics cover the source, its jurisdiction, and its courts;
- ``judgemetrics metrics verify`` exits 0 over the snapshot, then 1 — naming the
  scope and the statistic — once a stored statistic is tampered with.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from judgemetrics.cli import app as cli
from judgemetrics.config import Settings, get_settings
from judgemetrics.db.models import (
    COVERAGE_STATISTICS,
    Court,
    CoverageStatistic,
    MetricDefinition,
    MetricObservation,
    OutcomeModel,
    Source,
)
from judgemetrics.db.models.enums import SubjectType
from judgemetrics.db.session import make_engine
from judgemetrics.ingest.cook_sao.connector import CookSaoConnector
from judgemetrics.ingest.cook_sao.sources import SOURCE_ID
from judgemetrics.ingest.runner import run_ingest
from judgemetrics.ingest.store import FilesystemRawObjectStore
from judgemetrics.metrics.adjustment.spec import load_spec
from judgemetrics.metrics.engine import EngineResult, compute_and_publish
from tests.conftest import TEST_IDENTIFIER_PEPPER
from tests.integration.conftest import purge_source

pytestmark = pytest.mark.integration

COOK_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cook_sao"
PRETRIAL_SLUGS = {
    "pretrial_decisions",
    "pretrial_released",
    "pretrial_detained",
    "pretrial_release_share",
}
SENTENCING_FAMILY = {
    "sentence_count",
    "incarceration_days_median",
    "probation_days_median",
    "incarceration_days_median_by_offense_category",
}
DISPOSITION_FAMILY = {
    "disposition_distribution",
    "judicial_dismissal_rate",
    "median_days_to_disposition",
}
CROSS_CASE = {
    "new_case_rate_after_sentence",
    "new_charge_rate_after_sentence",
    "reconviction_rate_after_sentence",
    "new_case_rate_after_disposition",
}


@dataclass(frozen=True)
class CookMetrics:
    settings: Settings
    result: EngineResult
    snapshot_dir: Path
    source_id: uuid.UUID


@pytest.fixture(scope="module")
def cook_metrics(
    migrated_database: Engine, test_settings: Settings, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[CookMetrics]:
    """The fixture ingested once and ``metrics compute --source cook_sao`` over it, committed."""
    with Session(migrated_database) as cleanup:
        purge_source(cleanup, SOURCE_ID)
        cleanup.commit()
    snapshot_dir = tmp_path_factory.mktemp("cook-snapshots")
    settings = test_settings.model_copy(update={"env": "test", "snapshot_dir": snapshot_dir})
    store = FilesystemRawObjectStore(tmp_path_factory.mktemp("cook-lake"))
    with Session(migrated_database) as session:
        run_ingest(
            SOURCE_ID,
            session=session,
            store=store,
            settings=settings,
            from_fixture=COOK_FIXTURES,
            connector=CookSaoConnector(pepper=SecretStr(TEST_IDENTIFIER_PEPPER)),
        )
        session.commit()
        source_id = session.scalar(select(Source.id).where(Source.name == SOURCE_ID))
        assert source_id is not None
    engine = make_engine(settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            result = compute_and_publish(
                session, settings, sources=frozenset({SOURCE_ID}), label="cook test"
            )
            session.commit()
        yield CookMetrics(settings, result, snapshot_dir, source_id)
    finally:
        engine.dispose()
        with Session(migrated_database) as session:
            purge_source(session, SOURCE_ID)
            session.commit()


def _observations(
    engine: Engine, source_id: uuid.UUID, subject_type: str
) -> list[tuple[str, MetricObservation]]:
    with Session(engine) as session:
        rows = session.execute(
            select(MetricDefinition.slug, MetricObservation)
            .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
            .where(
                MetricObservation.source_id == source_id,
                MetricObservation.subject_type == SubjectType(subject_type),
                MetricObservation.superseded_at.is_(None),
                MetricObservation.calendar_year.is_(None),
            )
        ).all()
        session.expunge_all()
    return [(str(slug), observation) for slug, observation in rows]


def test_the_source_declares_its_capabilities(
    migrated_database: Engine, cook_metrics: CookMetrics
) -> None:
    with Session(migrated_database) as session:
        source = session.get(Source, cook_metrics.source_id)
        assert source is not None
        assert source.capabilities == {
            "judge_gates": ["sentencing_judge", "disposing_judge"],
            "person_key_scope": "case",
            "revocation_scopes": ["supervision"],
        }


def test_judges_carry_the_sentencing_and_disposition_families_and_nothing_else(
    migrated_database: Engine, cook_metrics: CookMetrics
) -> None:
    rows = _observations(migrated_database, cook_metrics.source_id, "judge")
    slugs = {slug for slug, _ in rows}
    assert SENTENCING_FAMILY & slugs and DISPOSITION_FAMILY & slugs
    assert not slugs & PRETRIAL_SLUGS
    assert not slugs & {"eligible_cases", "eligible_defendants"}
    assert not any(slug.endswith("_observed_expected") for slug in slugs)
    families = SENTENCING_FAMILY | DISPOSITION_FAMILY
    assert any(not o.suppressed_flag for slug, o in rows if slug in families)
    # A judge with dispositions carries both families when the source names them.
    by_judge: dict[uuid.UUID, set[str]] = {}
    for slug, observation in rows:
        by_judge.setdefault(observation.subject_id, set()).add(slug)
    assert any(
        "sentence_count" in judged and "judicial_dismissal_rate" in judged
        for judged in by_judge.values()
    )


def test_judge_pretrial_metrics_are_not_attributable(cook_metrics: CookMetrics) -> None:
    computed = cook_metrics.result.computed
    unattributed = {(r.slug, r.gate) for r in computed.not_attributable}
    for slug in PRETRIAL_SLUGS:
        assert (slug, "deciding_judge") in unattributed, slug
    assert ("eligible_cases", "assigned_ever") in unattributed
    assert ("pretrial_release_observed_expected", "deciding_judge") in unattributed
    assert all(r.subject_type == "judge" for r in computed.not_attributable)
    assert cook_metrics.result.published.not_attributable == len(computed.not_attributable)


def test_courts_carry_the_bond_decisions_pretrial_counts(
    migrated_database: Engine, cook_metrics: CookMetrics
) -> None:
    rows = _observations(migrated_database, cook_metrics.source_id, "court")
    counts = [o.observed_count for slug, o in rows if slug == "pretrial_decisions"]
    assert counts and sum(counts) > 0
    assert {"pretrial_release_share", "sentence_count", "disposition_distribution"} <= {
        slug for slug, _ in rows
    }


def test_cross_case_outcomes_and_a_revoked_release_are_not_observable(
    migrated_database: Engine, cook_metrics: CookMetrics
) -> None:
    blocked = {(r.slug, r.subject_type): r for r in cook_metrics.result.computed.not_observable}
    for slug in CROSS_CASE:
        for subject_type in ("judge", "court"):
            assert (slug, subject_type) in blocked, (slug, subject_type)
    for slug in ("new_case_rate", "failure_to_appear_rate", "revocation_rate"):
        assert (slug, "court") in blocked, slug
    assert "scope release" in blocked[("revocation_rate", "court")].reason
    published = {
        slug
        for subject_type in ("judge", "court")
        for slug, _ in _observations(migrated_database, cook_metrics.source_id, subject_type)
    }
    assert not published & (CROSS_CASE | {"revocation_rate", "new_case_rate"})


def test_the_revocation_rates_after_a_sentence_are_published(
    migrated_database: Engine, cook_metrics: CookMetrics
) -> None:
    rows = _observations(migrated_database, cook_metrics.source_id, "court")
    after_sentence = [o for slug, o in rows if slug == "revocation_rate_after_sentence"]
    assert after_sentence and all(o.window_days is not None for o in after_sentence)
    assert any(o.eligible_count > 0 for o in after_sentence)


def test_every_target_is_unavailable_with_its_reason(
    migrated_database: Engine, cook_metrics: CookMetrics
) -> None:
    spec = load_spec()
    with Session(migrated_database) as session:
        models = session.scalars(
            select(OutcomeModel).where(OutcomeModel.source_id == cook_metrics.source_id)
        ).all()
        assert len(models) == sum(len(target.windows) for target in spec.targets)
        for model in models:
            assert model.status == "unavailable"
            assert model.diagnostics == {"status": "unavailable", "reason": spec.availability.gate}
            assert model.coefficients is None and model.n_train == model.n_test == 0
    assert cook_metrics.result.models_read == len(models)


def test_coverage_statistics_cover_the_source_its_jurisdiction_and_courts(
    migrated_database: Engine, cook_metrics: CookMetrics
) -> None:
    with Session(migrated_database) as session:
        rows = session.scalars(
            select(CoverageStatistic).where(CoverageStatistic.source_id == cook_metrics.source_id)
        ).all()
        courts = session.scalars(
            select(Court.id).where(Court.id.in_({r.scope_id for r in rows}))
        ).all()
    scopes = {(r.scope_type, r.scope_id) for r in rows}
    assert {scope_type for scope_type, _ in scopes} == {"source", "jurisdiction", "court"}
    assert len(rows) == len(scopes) * len(COVERAGE_STATISTICS)
    assert len(courts) == sum(1 for scope_type, _ in scopes if scope_type == "court")
    source = {r.statistic: r for r in rows if r.scope_type == "source"}
    assert set(source) == set(COVERAGE_STATISTICS)
    assert source["cases_with_identified_judge"].denominator == 73
    assert (
        source["records_with_provenance"].numerator == source["records_with_provenance"].denominator
    )
    for row in rows:
        assert 0 <= row.numerator <= row.denominator
        assert row.methodology_version == "1.1"
    assert cook_metrics.result.coverage is not None
    assert cook_metrics.result.coverage.statistics >= len(rows)


def _verify(cook_metrics: CookMetrics) -> tuple[int, str]:
    settings = cook_metrics.settings
    env = {
        "JUDGEMETRICS_ENV": "test",
        "JUDGEMETRICS_DATABASE_URL": settings.database_url,
        "JUDGEMETRICS_INGEST_DATABASE_URL": settings.effective_ingest_database_url,
        "JUDGEMETRICS_SNAPSHOT_DIR": str(cook_metrics.snapshot_dir),
        "JUDGEMETRICS_LOG_FORMAT": "json",
    }
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(
            cli,
            ["metrics", "verify", "--snapshot", cook_metrics.result.snapshot.content_hash],
            env=env,
        )
    finally:
        get_settings.cache_clear()
    return result.exit_code, result.output


def test_metrics_verify_passes_then_names_a_tampered_statistic(
    migrated_database: Engine, cook_metrics: CookMetrics
) -> None:
    code, output = _verify(cook_metrics)
    assert code == 0, output
    with Session(migrated_database) as session:
        target = session.scalars(
            select(CoverageStatistic).where(
                CoverageStatistic.source_id == cook_metrics.source_id,
                CoverageStatistic.scope_type == "source",
                CoverageStatistic.statistic == "cases_with_final_disposition",
            )
        ).one()
        target_id, numerator = target.id, target.numerator
        session.execute(
            update(CoverageStatistic)
            .where(CoverageStatistic.id == target_id)
            .values(numerator=CoverageStatistic.numerator - 1)
        )
        session.commit()
    try:
        code, output = _verify(cook_metrics)
        assert code == 1, output
        assert "coverage mismatch: cases_with_final_disposition source:" in output
        assert "column=numerator" in output
    finally:
        with Session(migrated_database) as session:
            session.execute(
                update(CoverageStatistic)
                .where(CoverageStatistic.id == target_id)
                .values(numerator=numerator)
            )
            session.commit()
