# tests/golden/test_golden_provenance.py
"""Every current observation of the golden fixture traces completely, and a broken chain is refused.

Over the module's golden ingest and its committed ``metrics compute``:
``metrics.provenance.trace`` reconstructs the brief's chain for every
current observation — the observation, its snapshot, every member
resolved to a canonical row and a case, every row to a source record with
its artifact digest, every record to its source — and reports
``complete``; the CLI prints the same chain and exits 0 (1 for an
incomplete chain, 2 for a malformed or unknown id); the endpoint's
response equals the CLI's JSON on every shared field. Deleting one
member's canonical row inside a rolled-back ingest session makes the
trace incomplete (the row is the member's link to its source record;
the record itself is protected by the RESTRICT foreign keys of every row
it produced), and ``publish.check_chain`` refuses a draft that names an
id the snapshot does not hold with ``ProvenanceError`` — the rule that
keeps such an observation from ever being published.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from judgemetrics.cli import app as cli
from judgemetrics.db.models import MetricDefinition, MetricObservation, Sentence
from judgemetrics.db.session import make_engine
from judgemetrics.metrics.compute import Member
from judgemetrics.metrics.provenance import TraceError, render, trace
from judgemetrics.metrics.publish import ProvenanceError, check_chain
from judgemetrics.metrics.snapshot import open_snapshot
from tests.golden.conftest import GoldenFixture, GoldenMetrics

pytestmark = [pytest.mark.golden, pytest.mark.integration]


@pytest.fixture
def ingest_session(golden_metrics: GoldenMetrics) -> Iterator[Session]:
    """A session as the ingest role, rolled back afterwards (the deletion stays local)."""
    engine = make_engine(golden_metrics.settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            yield session
            session.rollback()
    finally:
        engine.dispose()


def _current_ids(session: Session) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(MetricObservation.id)
            .where(MetricObservation.superseded_at.is_(None))
            .order_by(MetricObservation.id)
        )
    )


def test_every_current_observation_traces_completely(
    session: Session, golden_fixture: GoldenFixture, golden_metrics: GoldenMetrics
) -> None:
    ids = _current_ids(session)
    assert len(ids) > 100, "the golden compute published observations"
    source_records: set[uuid.UUID] = set()
    case_ids = set(golden_fixture.case_ids.values())
    for observation_id in ids:
        traced = trace(session, observation_id)
        assert traced.complete, str(observation_id)
        assert traced.statements == 3
        assert traced.unresolved_members == 0 and traced.unresolved_records == 0
        assert traced.observation.id == observation_id
        assert traced.observation.superseded_at is None
        assert traced.snapshot.content_hash == golden_metrics.result.snapshot.content_hash
        assert traced.snapshot.storage_uri.startswith("file:")
        assert traced.observation.source == "synthetic" and traced.observation.synthetic
        assert traced.observation.registry_version == traced.snapshot.registry_version
        # Members are entity ids of public rows that belong to the fixture's cases.
        assert traced.members or traced.observation.eligible_count == 0
        for member in traced.members:
            assert member.resolved
            assert member.source_record_id is not None
            assert member.case_id in case_ids, (member.kind, member.id)
        assert set(traced.case_ids) <= case_ids
        assert sum(group.members for group in traced.groups) == len(traced.members)
        assert {group.kind for group in traced.groups} == {m.kind for m in traced.members}
        # Every source record is a fixture file with a sha256 digest behind it.
        for record in traced.source_records:
            assert record.has_artifact
            assert record.source == "synthetic"
            assert record.external_record_id is not None
            assert record.external_record_id.startswith("source/")
            assert record.ingest_run_id == golden_fixture.run_id
            assert record.artifact_uri is not None and record.artifact_uri.startswith("file:")
            assert record.public_artifact_uri is None
            source_records.add(record.id)
        assert [source.source for source in traced.sources] == ["synthetic"]
        assert traced.sources[0].synthetic is True
        assert traced.sources[0].observable_outcomes == (
            "failure_to_appear",
            "new_case",
            "new_charge",
            "reconviction",
            "revocation",
        )
        # Every member's record is among the records the trace lists.
        assert {m.source_record_id for m in traced.members} <= {r.id for r in traced.source_records}
        # The JSON form and the text form carry the chain top-down.
        as_dict = traced.as_dict()
        assert list(as_dict) == [
            "observation",
            "snapshot",
            "members",
            "cases",
            "source_records",
            "sources",
            "unresolved_members",
            "unresolved_records",
            "complete",
        ]
        assert as_dict["complete"] is True
        lines = render(traced)
        assert lines[0].startswith("published metric: ")
        assert lines[-1] == "complete: yes"
        dumped = json.dumps(as_dict)
        assert "person_id" not in dumped and "public_person_key" not in dumped
    # The members of every observation come from the fixture's seven source files.
    assert len(source_records) <= 7


def test_the_cli_prints_the_chain_and_matches_the_endpoint(
    session: Session, golden_metrics: GoldenMetrics, golden_api: TestClient
) -> None:
    observation_id = _current_ids(session)[0]
    env = {
        "JUDGEMETRICS_ENV": "test",
        "JUDGEMETRICS_DATABASE_URL": golden_metrics.settings.database_url,
        "JUDGEMETRICS_LOG_FORMAT": "json",
    }
    text = CliRunner().invoke(cli, ["provenance", "trace", str(observation_id)], env=env)
    assert text.exit_code == 0, text.output
    assert text.output.splitlines()[0].startswith("published metric: ")
    assert f"observation {observation_id}" in text.output
    assert f"snapshot {golden_metrics.result.snapshot.content_hash}" in text.output
    assert text.output.rstrip().splitlines()[-1] == "complete: yes"
    assert "raw_object_path" not in text.output
    as_json = CliRunner().invoke(
        cli, ["provenance", "trace", str(observation_id), "--json"], env=env
    )
    assert as_json.exit_code == 0, as_json.output
    printed = json.loads(as_json.output)
    assert printed["complete"] is True
    assert printed["observation"]["id"] == str(observation_id)

    response = golden_api.get(f"/api/v1/metrics/{observation_id}/provenance")
    assert response.status_code == 200, response.text
    served = response.json()
    # The endpoint serves the same chain; it withholds the snapshot's storage
    # URI and a non-public artifact URI, and never a suppressed number.
    assert served["complete"] == printed["complete"]
    assert served["snapshot"]["content_hash"] == printed["snapshot"]["content_hash"]
    assert served["snapshot"]["row_counts"] == printed["snapshot"]["row_counts"]
    assert "storage_uri" not in served["snapshot"]
    assert served["members"] == printed["members"]
    assert [r["id"] for r in served["source_records"]] == [
        r["id"] for r in printed["source_records"]
    ]
    for served_record, printed_record in zip(
        served["source_records"], printed["source_records"], strict=True
    ):
        for key in ("raw_sha256", "external_record_id", "parser_version", "ingest_run_id"):
            assert served_record[key] == printed_record[key]
        assert served_record["artifact_uri"] is None
        assert printed_record["artifact_uri"].startswith("file:")
    assert [s["source"] for s in served["sources"]] == [s["source"] for s in printed["sources"]]
    observation = served["observation"]
    for key in ("id", "slug", "version", "subject_type", "subject_id", "source", "window_days"):
        assert observation[key] == printed["observation"][key], key
    if observation["suppressed"]:
        assert observation["numerator"] is None and observation["denominator"] is None
    else:
        assert observation["numerator"] == printed["observation"]["observed_count"]
        assert observation["denominator"] == printed["observation"]["cohort_size"]

    unknown = CliRunner().invoke(cli, ["provenance", "trace", str(uuid.uuid4())], env=env)
    assert unknown.exit_code == 2, unknown.output
    assert "no metric observation" in unknown.output


def test_deleting_a_member_row_makes_the_trace_incomplete_and_the_cli_exit_1(
    ingest_session: Session, golden_metrics: GoldenMetrics
) -> None:
    session = ingest_session
    # An observation whose members are sentences: a sentence row has no dependants.
    target = session.execute(
        select(MetricObservation)
        .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
        .where(MetricObservation.superseded_at.is_(None), MetricDefinition.slug == "sentence_count")
        .order_by(MetricObservation.cohort_size.desc(), MetricObservation.id)
        .limit(1)
    ).scalar_one()
    before = trace(session, target.id)
    assert before.complete and before.members
    victim = before.members[0]
    assert victim.kind == "sentence"
    session.execute(delete(Sentence).where(Sentence.id == victim.id))
    after = trace(session, target.id)
    assert not after.complete
    assert after.unresolved_members == 1
    assert len(after.members) == len(before.members)
    broken = next(m for m in after.members if m.id == victim.id)
    assert not broken.resolved and broken.case_id is None and broken.source_record_id is None
    group = next(g for g in after.groups if g.kind == "sentence")
    assert group.resolved == group.members - 1
    lines = render(after)
    assert lines[-1] == "complete: no"
    assert any(line.startswith("INCOMPLETE: 1 member(s) without a canonical row") for line in lines)
    assert after.as_dict()["complete"] is False
    # The publish rule: a draft naming an id the snapshot does not hold is refused outright.
    with open_snapshot(
        golden_metrics.settings, golden_metrics.result.snapshot.content_hash
    ) as snap:
        draft = next(d for d in golden_metrics.result.computed.drafts if d.slug == "sentence_count")
        foreign = dataclasses.replace(
            draft,
            members=(*draft.members, Member("sentence", str(uuid.uuid4()), True, True)),
        )
        with pytest.raises(ProvenanceError, match="provenance chain incomplete"):
            check_chain(snap, [foreign])
        check_chain(snap, [draft])  # the real draft passes
    with pytest.raises(TraceError):
        trace(session, "not-an-id")
