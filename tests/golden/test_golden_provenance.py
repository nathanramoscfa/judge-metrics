# tests/golden/test_golden_provenance.py
"""Every current observation of the golden fixture traces completely, and a broken chain is refused.

Over the module's golden ingest and its committed ``metrics compute``:
``metrics.provenance.trace`` reconstructs the brief's chain
(``<provenance_requirement>``) for every current observation — the observation, its
snapshot, its members (the totals over all of them and one page of ids), each resolved
to a canonical row and a case, every row to a source record with its artifact digest,
every record to its source, and an adjusted observation's outcome model with its
artifact (Phase 4 Step 3) — and reports ``complete``; the CLI prints the same chain
and exits 0 (1 for an incomplete chain, 2 for a malformed or unknown id); the endpoint's
response equals the CLI's JSON on every shared field. Phase 5 Step 6: the totals equal
the observation's member multiset read through the SQL projection, a trace pages its
members (the pages tile the set, a page past the end still carries the totals and costs
a fourth statement, the limit is bounded), and the page of the CLI and the endpoint
agree. Deleting one member's canonical row inside a rolled-back ingest session makes the
trace incomplete (the row is the member's link to its source record; the record itself
is protected by the RESTRICT foreign keys of every row it produced), and
``publish.check_chain`` refuses a draft whose family names an id the snapshot does not
hold with ``ProvenanceError`` — the rule that keeps such an observation from ever being
published.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections import Counter
from collections.abc import Iterator

import polars as pl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from judgemetrics.cli import app as cli
from judgemetrics.db.models import MetricDefinition, MetricObservation, Sentence
from judgemetrics.db.session import make_engine
from judgemetrics.metrics.member_store import observation_members
from judgemetrics.metrics.members import SCHEMA, MemberFamily
from judgemetrics.metrics.provenance import MAX_LIMIT, TraceError, render, trace
from judgemetrics.metrics.publish import ProvenanceError, check_chain
from judgemetrics.metrics.snapshot import open_snapshot
from judgemetrics.services.metrics import SERVED_KINDS
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


def _current_ids(session: Session, *, kind: str | None = None) -> list[uuid.UUID]:
    """Current observation ids (every kind is served since Phase 4 Step 5), or one kind's."""
    stmt = (
        select(MetricObservation.id)
        .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
        .where(
            MetricObservation.superseded_at.is_(None),
            MetricDefinition.kind.in_(sorted(SERVED_KINDS)),
        )
        .order_by(MetricObservation.id)
    )
    if kind is not None:
        stmt = stmt.where(MetricDefinition.kind == kind)
    return list(session.scalars(stmt))


def test_every_current_observation_traces_completely(
    session: Session, golden_fixture: GoldenFixture, golden_metrics: GoldenMetrics
) -> None:
    ids = _current_ids(session)
    assert len(ids) > 100, "the golden compute published observations"
    source_records: set[uuid.UUID] = set()
    case_ids = set(golden_fixture.case_ids.values())
    adjusted = 0
    for observation_id in ids:
        # The settings locate an adjusted observation's model artifact (Phase 4 Step 3).
        traced = trace(session, observation_id, settings=golden_metrics.settings)
        assert traced.complete, str(observation_id)
        if traced.observation.kind == "observed_expected":
            adjusted += 1
            assert traced.model is not None and traced.model.artifact_ok
            assert {group.kind for group in traced.groups} <= {"decision"}
        else:
            assert traced.model is None
        assert traced.statements == 3
        assert traced.unresolved_members == 0 and traced.unresolved_records == 0
        assert traced.observation.id == observation_id
        assert traced.observation.superseded_at is None
        assert traced.snapshot.content_hash == golden_metrics.result.snapshot.content_hash
        assert traced.snapshot.storage_uri.startswith("file:")
        assert traced.observation.source == "synthetic" and traced.observation.synthetic
        assert traced.observation.registry_version == traced.snapshot.registry_version
        # The totals are the observation's member multiset, read through the SQL projection.
        every = observation_members(session, observation_id)
        assert traced.member_total == len(every)
        assert sum(group.counted for group in traced.groups) == sum(m.counted for m in every)
        assert sum(group.followed for group in traced.groups) == sum(m.followed for m in every)
        assert sum(group.resolved for group in traced.groups) == len(every)
        assert traced.case_total == (
            0 if not every else len({case for case in _cases_of(session, every)})
        )
        assert traced.limit == 100 and traced.offset == 0
        assert len(traced.members) <= 100
        # Members are entity ids of public rows that belong to the fixture's cases.
        assert traced.members or traced.observation.eligible_count == 0
        for member in traced.members:
            assert member.resolved
            assert member.source_record_id is not None
            assert member.case_id in case_ids, (member.kind, member.id)
        assert set(traced.case_ids) <= case_ids
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
            "model",
            "members",
            "cases",
            "page",
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
    assert adjusted > 0, "the golden compute published adjusted observations"


def _cases_of(session: Session, members: tuple[object, ...]) -> set[uuid.UUID]:
    """The distinct cases of an observation's members, from the canonical tables."""
    from judgemetrics.metrics.provenance import MEMBER_TABLES

    where = {kind: (table, case) for kind, table, case in MEMBER_TABLES}
    cases: set[uuid.UUID] = set()
    by_kind: dict[str, set[uuid.UUID]] = {}
    for member in members:
        by_kind.setdefault(member.kind, set()).add(uuid.UUID(member.id))  # type: ignore[attr-defined]
    for kind, ids in by_kind.items():
        table, case = where[kind]
        cases.update(session.scalars(select(case).where(table.c.id.in_(ids))))
    return cases


def _largest_observation(session: Session) -> uuid.UUID:
    """The current observation with the most members (so the pages are many)."""
    best = max(_current_ids(session), key=lambda oid: len(observation_members(session, oid)))
    assert len(observation_members(session, best)) > 20, "the golden world has a cohort to page"
    return best


def test_a_trace_pages_its_members_and_the_pages_tile_the_set(
    session: Session, golden_metrics: GoldenMetrics
) -> None:
    observation_id = _largest_observation(session)
    whole = trace(session, observation_id, limit=MAX_LIMIT, settings=golden_metrics.settings)
    total = whole.member_total
    assert sum(member.copies for member in whole.members) == total
    expected = Counter(
        (m.id, m.counted, m.followed) for m in observation_members(session, observation_id)
    )
    pages: list[tuple[str, bool, bool]] = []
    seen_totals = set()
    offset = 0
    while offset < total:
        page = trace(
            session,
            observation_id,
            limit=7,
            offset=offset,
            settings=golden_metrics.settings,
        )
        assert page.statements == 3 and page.complete
        assert page.limit == 7 and page.offset == offset
        seen_totals.add((page.member_total, page.case_total, page.unresolved_members))
        assert 0 < len(page.members) <= 7
        for member in page.members:
            pages.extend([(str(member.id), member.counted, member.followed)] * member.copies)
        # Whatever the page, the chain's source records are those of every member.
        assert {r.id for r in page.source_records} == {r.id for r in whole.source_records}
        offset += 7
    assert len(seen_totals) == 1, "the totals do not depend on the page"
    assert Counter(pages) == expected
    # A page past the end lists nothing, still reports the totals, and costs a fourth statement.
    beyond = trace(
        session, observation_id, limit=10, offset=total + 5, settings=golden_metrics.settings
    )
    assert beyond.members == () and beyond.member_total == total and beyond.statements == 4
    assert beyond.complete
    for bad in (0, MAX_LIMIT + 1):
        with pytest.raises(TraceError, match="limit"):
            trace(session, observation_id, limit=bad)
    with pytest.raises(TraceError, match="offset"):
        trace(session, observation_id, offset=-1)


@pytest.mark.parametrize("kind", ["share", "observed_expected"])
def test_the_cli_prints_the_chain_and_matches_the_endpoint(
    session: Session, golden_metrics: GoldenMetrics, golden_api: TestClient, kind: str
) -> None:
    observation_id = _current_ids(session, kind=kind)[0]
    env = {
        "JUDGEMETRICS_ENV": "test",
        "JUDGEMETRICS_DATABASE_URL": golden_metrics.settings.database_url,
        "JUDGEMETRICS_SNAPSHOT_DIR": str(golden_metrics.snapshot_dir),
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
    assert printed["page"] == {"limit": 100, "offset": 0}

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
    assert (served["limit"], served["offset"]) == (100, 0)
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
    assert observation["suppression_reason"] == printed["observation"]["suppression_reason"]
    # The endpoint names the same model as the CLI (an adjusted observation only).
    if printed["model"] is None:
        assert served["model"] is None and observation["model"] is None
    else:
        for key in ("id", "content_hash", "spec_version", "model_version", "target", "window_days"):
            assert served["model"][key] == printed["model"][key], key
        assert served["model"]["artifact_ok"] is printed["model"]["artifact_ok"] is True
        assert served["model"]["training"]["index_events"] == printed["model"]["index_events"]
        assert served["model"]["training"]["events"] == printed["model"]["events"]
        assert observation["model"]["content_hash"] == printed["model"]["content_hash"]

    unknown = CliRunner().invoke(cli, ["provenance", "trace", str(uuid.uuid4())], env=env)
    assert unknown.exit_code == 2, unknown.output
    assert "no metric observation" in unknown.output


def test_the_cli_and_the_endpoint_agree_on_a_page(
    session: Session, golden_metrics: GoldenMetrics, golden_api: TestClient
) -> None:
    observation_id = _largest_observation(session)
    env = {
        "JUDGEMETRICS_ENV": "test",
        "JUDGEMETRICS_DATABASE_URL": golden_metrics.settings.database_url,
        "JUDGEMETRICS_SNAPSHOT_DIR": str(golden_metrics.snapshot_dir),
        "JUDGEMETRICS_LOG_FORMAT": "json",
    }
    arguments = ["provenance", "trace", str(observation_id), "--limit", "5", "--offset", "10"]
    text = CliRunner().invoke(cli, arguments, env=env)
    assert text.exit_code == 0, text.output
    assert "members 11-15 of " in text.output and "--limit 5 --offset 10" in text.output
    assert text.output.rstrip().splitlines()[-1] == "complete: yes"
    printed = json.loads(CliRunner().invoke(cli, [*arguments, "--json"], env=env).output)
    assert printed["page"] == {"limit": 5, "offset": 10}
    assert len(printed["members"][0]["member_ids"]) == 5
    response = golden_api.get(
        f"/api/v1/metrics/{observation_id}/provenance", params={"limit": 5, "offset": 10}
    )
    assert response.status_code == 200, response.text
    served = response.json()
    assert served["members"] == printed["members"]
    assert (served["limit"], served["offset"]) == (5, 10)
    # The page is bounded, the counts are not.
    group = served["members"][0]
    assert len(group["member_ids"]) == 5 and group["members"] > 20 and group["cases"] > 0
    for params in ({"limit": 0}, {"limit": MAX_LIMIT + 1}, {"offset": -1}, {"page": 2}):
        rejected = golden_api.get(f"/api/v1/metrics/{observation_id}/provenance", params=params)
        assert rejected.status_code == 422, params
    bad = CliRunner().invoke(
        cli, ["provenance", "trace", str(observation_id), "--limit", str(MAX_LIMIT + 1)], env=env
    )
    assert bad.exit_code == 2, bad.output


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
    before = trace(session, target.id, limit=MAX_LIMIT)
    assert before.complete and before.members
    victim = before.members[0]
    assert victim.kind == "sentence"
    session.execute(delete(Sentence).where(Sentence.id == victim.id))
    after = trace(session, target.id, limit=MAX_LIMIT)
    assert not after.complete
    assert after.unresolved_members == 1
    assert after.member_total == before.member_total
    assert len(after.members) == len(before.members)
    broken = next(m for m in after.members if m.id == victim.id)
    assert not broken.resolved and broken.case_id is None and broken.source_record_id is None
    group = next(g for g in after.groups if g.kind == "sentence")
    assert group.resolved == group.members - 1
    lines = render(after)
    assert lines[-1] == "complete: no"
    assert any(line.startswith("INCOMPLETE: 1 member(s) without a canonical row") for line in lines)
    assert after.as_dict()["complete"] is False
    # The page need not contain the broken member: the rule is judged over all of them.
    first_page = trace(session, target.id, limit=1, offset=max(0, before.member_total - 1))
    assert not first_page.complete and first_page.unresolved_members == 1
    # The publish rule: a draft naming an id the snapshot does not hold is refused outright.
    with open_snapshot(
        golden_metrics.settings, golden_metrics.result.snapshot.content_hash
    ) as snap:
        draft = next(d for d in golden_metrics.result.computed.drafts if d.slug == "sentence_count")
        assert draft.family is not None
        stranger = pl.DataFrame(
            [(str(uuid.uuid4()), None, None, 1, 1, 1)], schema=SCHEMA, orient="row"
        )
        rows = pl.concat([draft.family.rows, stranger])
        foreign = dataclasses.replace(
            draft,
            family=MemberFamily.from_stored(
                draft.family.kind, draft.family.mode, draft.family.windows, rows
            ),
        )
        with pytest.raises(ProvenanceError, match="provenance chain incomplete"):
            check_chain(snap, [foreign])
        check_chain(snap, [draft])  # the real draft passes
    with pytest.raises(TraceError):
        trace(session, "not-an-id")
