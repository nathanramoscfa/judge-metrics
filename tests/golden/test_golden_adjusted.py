# tests/golden/test_golden_adjusted.py
"""The golden fixture's observed-to-expected observations: exact, reasoned, reproducible.

After the module's golden ingest and its committed ``metrics compute`` (the
shared ``golden_metrics`` fixture, which since Phase 4 Step 3 fits the
snapshot's outcome models first): every golden judge has exactly one
observation of each adjusted metric and window; its observed count equals
the descriptive metric's numerator for the same judge and window and
``truth/effects.json``'s observed count, its cohort and eligible counts the
truth's followed (or decided) and cohort counts; it cites the golden
snapshot's model for its target and window, and — every golden model being
``insufficient_events`` — carries no expected count, ratio, weight, or
interval; every suppression reason is the one the golden cohorts and models
imply; every member is an existing decision of the judge's cohort; no court
has an adjusted observation. ``metrics verify`` reproduces every adjusted
observation, reports a tampered ``standardized_ratio`` by id and column and
an altered model artifact by id and ``outcome_model``; a second compute fits
and publishes nothing; and the provenance trace of an adjusted observation
names its model and reports ``complete``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from judgemetrics.cli import app as cli
from judgemetrics.config import get_settings
from judgemetrics.db.models import (
    Decision,
    MetricDefinition,
    MetricObservation,
    OutcomeModel,
)
from judgemetrics.db.models.enums import SubjectType
from judgemetrics.db.session import make_engine
from judgemetrics.metrics.adjustment.artifacts import artifact_path
from judgemetrics.metrics.adjustment.spec import load_spec
from judgemetrics.metrics.engine import compute_and_publish
from judgemetrics.metrics.member_store import observation_members
from judgemetrics.metrics.registry import OBSERVED_EXPECTED, load_registry
from judgemetrics.metrics.verify import verify
from tests.golden.conftest import GOLDEN, GoldenFixture, GoldenMetrics

pytestmark = [pytest.mark.golden, pytest.mark.integration]

EFFECTS: dict[str, Any] = json.loads((GOLDEN / "truth" / "effects.json").read_text("utf-8"))
REGISTRY = load_registry()
SPEC = load_spec()
ADJUSTED = REGISTRY.of_kind(OBSERVED_EXPECTED)
# Each adjusted metric → the descriptive metric whose numerator it shares.
DESCRIPTIVE = {
    "pretrial_release_observed_expected": "pretrial_release_share",
    "new_case_observed_expected": "new_case_rate",
    "failure_to_appear_observed_expected": "failure_to_appear_rate",
}
JUDGES = sorted(EFFECTS["judges"])
CASES = [
    (code, metric.slug, window)
    for code in JUDGES
    for metric in ADJUSTED
    for window in (metric.windows_days or (None,))
]


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


def _current(session: Session, judge_id: uuid.UUID, slug: str) -> list[MetricObservation]:
    return list(
        session.scalars(
            select(MetricObservation)
            .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
            .where(
                MetricObservation.subject_type == SubjectType.JUDGE,
                MetricObservation.subject_id == judge_id,
                MetricObservation.superseded_at.is_(None),
                MetricDefinition.slug == slug,
            )
        )
    )


def _truth(slug: str, code: str, window: int | None) -> dict[str, Any]:
    target = REGISTRY[slug].adjustment
    assert target is not None
    block = EFFECTS["targets"][target.target]
    entry: dict[str, Any] = (
        block["judges"][code] if window is None else block["windows"][str(window)]["judges"][code]
    )
    return entry


def _expected_reason(cohort: int, model_status: str, expected: Decimal | None) -> str | None:
    if cohort < SPEC.thresholds.minimum_cohort:
        return "below_threshold"
    if expected is not None and expected < Decimal(str(SPEC.thresholds.minimum_expected)):
        return "expected_below_minimum"
    if model_status != "fitted":
        return "model_unavailable"
    return None


@pytest.mark.parametrize(
    ("code", "slug", "window"), CASES, ids=[f"{c}-{s}-{w}" for c, s, w in CASES]
)
def test_every_adjusted_observation_equals_its_descriptive_numerator_and_the_truth(
    session: Session,
    golden_fixture: GoldenFixture,
    golden_metrics: GoldenMetrics,
    code: str,
    slug: str,
    window: int | None,
) -> None:
    judge_id = golden_fixture.judge_ids[code]
    observations = [row for row in _current(session, judge_id, slug) if row.window_days == window]
    assert len(observations) == 1, f"{code} {slug}@{window}"
    observation = observations[0]
    descriptive = [
        row
        for row in _current(session, judge_id, DESCRIPTIVE[slug])
        if row.window_days == window and row.calendar_year is None
    ]
    assert len(descriptive) == 1
    truth = _truth(slug, code, window)
    # The observed count is the descriptive numerator and the truth's.
    assert observation.observed_count == descriptive[0].observed_count
    if window is None:
        assert observation.observed_count == truth["released"]
        assert observation.cohort_size == observation.eligible_count == truth["decisions"]
    else:
        assert observation.observed_count == truth["observed"]
        assert observation.cohort_size == truth["followed"] == descriptive[0].cohort_size
        assert observation.eligible_count == truth["cohort"] == descriptive[0].eligible_count
    # It cites the golden snapshot's model of its target and window.
    model = session.get(OutcomeModel, observation.outcome_model_id)
    assert model is not None
    adjustment = REGISTRY[slug].adjustment
    assert adjustment is not None
    assert (model.target, model.window_days) == (adjustment.target, window)
    assert model.snapshot_id == observation.snapshot_id
    assert observation.snapshot.content_hash == golden_metrics.result.snapshot.content_hash
    # The golden models are all insufficient_events: no expected count, ratio, or interval.
    assert model.status == "insufficient_events"
    for column in (
        "expected_count",
        "expected_rate",
        "standardized_ratio",
        "pooling_weight",
        "lower_confidence_bound",
        "upper_confidence_bound",
    ):
        assert getattr(observation, column) is None, column
    if observation.cohort_size:
        rate = Decimal(observation.observed_count) / Decimal(observation.cohort_size)
        assert observation.observed_rate == rate.quantize(Decimal("0.000001"))
    reason = _expected_reason(observation.cohort_size, model.status, observation.expected_count)
    assert observation.suppression_reason == reason
    assert observation.suppressed_flag is (reason is not None)
    assert observation.registry_version == REGISTRY.version == 3
    assert observation.methodology_version == REGISTRY.methodology_version == "1.1"


def test_members_are_the_judges_existing_cohort_decisions(
    session: Session, golden_fixture: GoldenFixture, golden_metrics: GoldenMetrics
) -> None:
    del golden_metrics
    for code in JUDGES:
        judge_id = golden_fixture.judge_ids[code]
        for metric in ADJUSTED:
            for observation in _current(session, judge_id, metric.slug):
                members = observation_members(session, observation.id)
                assert len(members) == observation.eligible_count
                assert {m.kind for m in members} <= {"decision"}
                assert sum(m.followed for m in members) == observation.cohort_size
                assert sum(m.counted for m in members) == observation.observed_count
                assert all(m.followed for m in members if m.counted)
                decisions = {uuid.UUID(m.id) for m in members}
                found = set(
                    session.scalars(
                        select(Decision.id).where(
                            Decision.id.in_(decisions), Decision.judge_id == judge_id
                        )
                    )
                )
                assert found == decisions, (code, metric.slug, observation.window_days)


def test_no_court_has_an_adjusted_observation(
    session: Session, golden_fixture: GoldenFixture, golden_metrics: GoldenMetrics
) -> None:
    del golden_metrics
    rows = session.scalars(
        select(MetricObservation.id)
        .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
        .where(
            MetricDefinition.kind == OBSERVED_EXPECTED,
            MetricObservation.subject_type == SubjectType.COURT,
        )
    ).all()
    assert not rows
    assert set(golden_fixture.court_ids)


def test_metrics_verify_reproduces_and_reports_a_tampered_ratio(
    ingest_session: Session, golden_metrics: GoldenMetrics
) -> None:
    session = ingest_session
    clean = verify(session, golden_metrics.settings)
    assert clean.ok, [m.as_dict() for m in clean.mismatches[:5]]
    adjusted_ids = list(
        session.scalars(
            select(MetricObservation.id)
            .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
            .where(
                MetricDefinition.kind == OBSERVED_EXPECTED,
                MetricObservation.superseded_at.is_(None),
            )
            .order_by(MetricObservation.id)
        )
    )
    assert len(adjusted_ids) == len(CASES)
    assert clean.verified == clean.observations >= len(adjusted_ids)
    target = adjusted_ids[0]
    session.execute(
        update(MetricObservation)
        .where(MetricObservation.id == target)
        .values(standardized_ratio=Decimal("1.5"))
    )
    tampered = verify(session, golden_metrics.settings)
    assert not tampered.unverifiable
    assert [(m.observation_id, m.column) for m in tampered.mismatches] == [
        (target, "standardized_ratio")
    ]
    assert tampered.verified == tampered.observations - 1


def test_an_altered_model_artifact_is_reported_by_observation_and_field(
    ingest_session: Session, golden_metrics: GoldenMetrics
) -> None:
    session = ingest_session
    snapshot = golden_metrics.result.snapshot.content_hash
    model = session.scalars(
        select(OutcomeModel).where(
            OutcomeModel.target == "new_case", OutcomeModel.window_days == 365
        )
    ).one()
    citing = set(
        session.scalars(
            select(MetricObservation.id).where(
                MetricObservation.outcome_model_id == model.id,
                MetricObservation.superseded_at.is_(None),
            )
        )
    )
    assert len(citing) == len(JUDGES)
    path = artifact_path(golden_metrics.snapshot_dir, snapshot, model.content_hash)
    original = path.read_bytes()
    try:
        path.write_bytes(original.replace(b'"target"', b' "target"', 1))
        result = verify(session, golden_metrics.settings)
    finally:
        path.write_bytes(original)
    assert not result.ok
    assert {(m.observation_id, m.column) for m in result.mismatches} == {
        (observation_id, "outcome_model") for observation_id in citing
    }
    assert all("does not hash" in str(m.recomputed) for m in result.mismatches)
    assert verify(session, golden_metrics.settings).ok


def test_a_second_compute_fits_and_publishes_nothing(golden_metrics: GoldenMetrics) -> None:
    engine = make_engine(golden_metrics.settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            again = compute_and_publish(session, golden_metrics.settings)
            session.rollback()
    finally:
        engine.dispose()
    assert again.snapshot.reused
    assert again.models_fitted == 0 and again.models_read == 13
    assert again.published.observations_published == 0
    assert again.published.superseded == 0


def _trace(env: dict[str, str], *args: str) -> Any:
    """``provenance trace`` with ``env`` (the settings cache is cleared around the call)."""
    get_settings.cache_clear()
    try:
        return CliRunner().invoke(cli, ["provenance", "trace", *args], env=env)
    finally:
        get_settings.cache_clear()


def test_the_trace_of_an_adjusted_observation_names_its_model_and_is_complete(
    session: Session, golden_metrics: GoldenMetrics
) -> None:
    row = session.execute(
        select(MetricObservation.id, OutcomeModel.content_hash)
        .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
        .join(OutcomeModel, OutcomeModel.id == MetricObservation.outcome_model_id)
        .where(
            MetricDefinition.slug == "failure_to_appear_observed_expected",
            MetricObservation.superseded_at.is_(None),
        )
        .order_by(MetricObservation.cohort_size.desc(), MetricObservation.id)
        .limit(1)
    ).one()
    observation_id, model_hash = row
    env = {
        "JUDGEMETRICS_ENV": "test",
        "JUDGEMETRICS_DATABASE_URL": golden_metrics.settings.database_url,
        "JUDGEMETRICS_SNAPSHOT_DIR": str(golden_metrics.snapshot_dir),
        "JUDGEMETRICS_LOG_FORMAT": "json",
    }
    text = _trace(env, str(observation_id))
    assert text.exit_code == 0, text.output
    assert f"outcome model {model_hash}" in text.stdout
    assert "artifact: ok" in text.stdout
    assert "reason below_threshold" in text.stdout
    assert text.stdout.rstrip().splitlines()[-1] == "complete: yes"
    printed = json.loads(_trace(env, str(observation_id), "--json").stdout)
    assert printed["complete"] is True
    model = printed["model"]
    assert model["content_hash"] == model_hash and model["artifact_ok"] is True
    assert (model["target"], model["window_days"], model["seed"]) == (
        "failure_to_appear",
        model["window_days"],
        SPEC.seed,
    )
    assert model["spec_version"] == SPEC.version and model["model_version"] == SPEC.model_version
    assert printed["observation"]["suppression_reason"] == "below_threshold"
    # Without the snapshot directory the artifact cannot be checked: the chain is incomplete.
    elsewhere = {**env, "JUDGEMETRICS_SNAPSHOT_DIR": str(golden_metrics.snapshot_dir / "none")}
    missing = _trace(elsewhere, str(observation_id))
    assert missing.exit_code == 1
    assert "the model's artifact is missing" in missing.stdout
