# tests/integration/test_query_counts.py
"""The N+1 guard: statements per request, counted at the cursor.

A `before_cursor_execute` listener on the app's engine counts every
statement the driver runs. Budgets (ROADMAP.md §5 "Performance rules"):
judge detail at most four (judge with its synthetic flag, service records
with their courts, the case window, provenance), any list at most two
(the page with its window count, plus the similarity-threshold
`set_config` when `q` is given), search at most two (`set_config` and
the union), a judge's cases at most two, coverage at most three (the
counts, the latest runs, the latest snapshots), a case detail or
timeline at most eight (one statement per case-level table plus the
provenance rows — a constant, whatever the case holds), and (Phase 3
Step 3) a subject's metrics at most two (the subject, the observations),
compare at most two (the page; the fallback that settles the cohort's
existence on an empty page), an observation's provenance at most six
(three today: the observation, the resolved members, the source
records), and a correction at most two (the target lookup, the insert —
with no `RETURNING`).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, event
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import CorrectionRequest
from tests.integration.conftest import FjcFixture, GoldenFixture, GoldenMetrics, make_app

pytestmark = pytest.mark.integration

ALITO = "1377101"


class StatementCounter:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, *args: Any) -> None:
        # (conn, cursor, statement, parameters, context, executemany)
        self.statements.append(str(args[2]))

    def reset(self) -> None:
        self.statements.clear()


@pytest.fixture(scope="module")
def counted(
    fjc_fixture: FjcFixture, test_settings: Settings
) -> Iterator[tuple[TestClient, StatementCounter]]:
    app = make_app(test_settings)
    counter = StatementCounter()
    event.listen(app.state.engine, "before_cursor_execute", counter)
    with TestClient(app) as client:
        # The first connection runs the dialect's setup queries; warm the
        # pool so only the request's own statements are counted.
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/jurisdictions").status_code == 200
        yield client, counter
    event.remove(app.state.engine, "before_cursor_execute", counter)
    app.state.engine.dispose()


def _count(counted: tuple[TestClient, StatementCounter], path: str, **params: str) -> int:
    client, counter = counted
    counter.reset()
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return len(counter.statements)


def test_judge_detail_needs_at_most_four_statements(
    counted: tuple[TestClient, StatementCounter], fjc_fixture: FjcFixture
) -> None:
    judge_id = fjc_fixture.judge_ids[ALITO]
    assert _count(counted, f"/api/v1/judges/{judge_id}") <= 4
    # The provenance query selects the public columns only: the lake's
    # storage key never even leaves the database.
    _, counter = counted
    assert all("raw_object_path" not in statement for statement in counter.statements)
    assert _count(counted, f"/api/v1/judges/{judge_id}/service") <= 2


def test_judges_list_needs_at_most_two_statements(
    counted: tuple[TestClient, StatementCounter], fjc_fixture: FjcFixture
) -> None:
    assert _count(counted, "/api/v1/judges", limit="100") <= 2
    assert _count(counted, "/api/v1/judges", q="alito") <= 2
    assert _count(counted, "/api/v1/judges", active_on="2010-01-01", status="active") <= 2
    court_id = str(fjc_fixture.court_ids["Supreme Court of the United States"])
    assert _count(counted, "/api/v1/judges", court_id=court_id, active_on="2010-01-01") <= 2
    # An empty page (offset past the end) falls back to a plain count: still two.
    assert _count(counted, "/api/v1/judges", offset="1000000") <= 2


def test_courts_and_jurisdictions_lists_need_at_most_two_statements(
    counted: tuple[TestClient, StatementCounter], fjc_fixture: FjcFixture
) -> None:
    assert _count(counted, "/api/v1/courts", limit="100") <= 2
    assert _count(counted, "/api/v1/courts", court_type="district") <= 2
    supreme = fjc_fixture.court_ids["Supreme Court of the United States"]
    assert _count(counted, f"/api/v1/courts/{supreme}") <= 2
    assert _count(counted, "/api/v1/jurisdictions") <= 2
    assert _count(counted, f"/api/v1/jurisdictions/{fjc_fixture.jurisdiction_id}") <= 2


def test_search_needs_at_most_two_statements(
    counted: tuple[TestClient, StatementCounter],
) -> None:
    assert _count(counted, "/api/v1/search", q="alito") <= 2
    assert _count(counted, "/api/v1/search", q="supreme court", limit="50") <= 2
    _, counter = counted
    assert any("set_config" in statement for statement in counter.statements)


# --- Phase 2 Step 4: cases, judge cases, coverage ------------------------------------

CASE_DETAIL_BUDGET = 8
GOLDEN_CASE = "SYN-2020-000005"


def test_case_detail_and_timeline_need_at_most_eight_statements(
    counted: tuple[TestClient, StatementCounter], golden_fixture: GoldenFixture
) -> None:
    case_id = golden_fixture.case_ids[GOLDEN_CASE]
    assert _count(counted, f"/api/v1/cases/{case_id}") <= CASE_DETAIL_BUDGET
    _, counter = counted
    assert all("raw_object_path" not in statement for statement in counter.statements)
    assert all("person_identifier" not in statement for statement in counter.statements)
    assert _count(counted, f"/api/v1/cases/{case_id}/timeline") <= CASE_DETAIL_BUDGET
    # A case with more rows costs the same number of statements.
    busiest = max(
        golden_fixture.case_ids.values(),
        key=lambda cid: len(counted[0].get(f"/api/v1/cases/{cid}/timeline").json()["entries"]),
    )
    assert _count(counted, f"/api/v1/cases/{busiest}") <= CASE_DETAIL_BUDGET


def test_judge_cases_need_at_most_two_statements(
    counted: tuple[TestClient, StatementCounter], golden_fixture: GoldenFixture
) -> None:
    judge_id = golden_fixture.judge_ids["J-0003"]
    assert _count(counted, f"/api/v1/judges/{judge_id}/cases", limit="100") <= 2
    assert _count(counted, f"/api/v1/judges/{judge_id}/cases", status="open") <= 2
    assert (
        _count(
            counted,
            f"/api/v1/judges/{judge_id}/cases",
            filed_from="2020-01-01",
            filed_to="2020-12-31",
            case_type="felony",
        )
        <= 2
    )
    # An empty page settles the total and the judge's existence in one more statement.
    assert _count(counted, f"/api/v1/judges/{judge_id}/cases", offset="1000") <= 2
    assert _count(counted, f"/api/v1/judges/{judge_id}") <= 4


def test_coverage_needs_at_most_three_statements(
    counted: tuple[TestClient, StatementCounter], golden_fixture: GoldenFixture
) -> None:
    assert _count(counted, "/api/v1/coverage") <= 3
    _, counter = counted
    assert all("person_identifier" not in statement for statement in counter.statements)
    assert _count(counted, "/api/v1/search", q=GOLDEN_CASE) <= 2
    # A one-word query costs the same two: the word threshold and the union.
    assert _count(counted, "/api/v1/search", q="wingnut") <= 2
    # The setting name is a bound parameter; the union itself names the function and operator.
    assert any("set_config" in s for s in counter.statements)
    assert any("word_similarity(" in s and "<%" in s for s in counter.statements)
    assert _count(counted, "/api/v1/judges", q="wingnut") <= 2


# --- Phase 3 Step 3: metrics, compare, provenance, corrections --------------------------

SUBJECT_METRICS_BUDGET = 2
COMPARE_BUDGET = 2
PROVENANCE_BUDGET = 6
CORRECTIONS_BUDGET = 2


@pytest.fixture(scope="module")
def counted_metrics(
    golden_metrics: GoldenMetrics, test_settings: Settings
) -> Iterator[tuple[TestClient, StatementCounter]]:
    """The API over the golden ingest with its observations, with a Fernet key for corrections."""
    app = make_app(
        golden_metrics.settings, correction_contact_key=Fernet.generate_key().decode("ascii")
    )
    counter = StatementCounter()
    event.listen(app.state.engine, "before_cursor_execute", counter)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/jurisdictions").status_code == 200
        yield client, counter
    event.remove(app.state.engine, "before_cursor_execute", counter)
    app.state.engine.dispose()


def test_subject_metrics_need_at_most_two_statements(
    counted_metrics: tuple[TestClient, StatementCounter], golden_fixture: GoldenFixture
) -> None:
    judge_id = golden_fixture.judge_ids["J-0003"]
    assert _count(counted_metrics, f"/api/v1/judges/{judge_id}/metrics") <= SUBJECT_METRICS_BUDGET
    _, counter = counted_metrics
    assert all("person" not in statement for statement in counter.statements)
    court_id = golden_fixture.court_ids["C-0003"]
    assert _count(counted_metrics, f"/api/v1/courts/{court_id}/metrics") <= SUBJECT_METRICS_BUDGET
    # The registry needs no statement at all.
    assert _count(counted_metrics, "/api/v1/metrics") == 0


def test_compare_needs_at_most_two_statements(
    counted_metrics: tuple[TestClient, StatementCounter], golden_fixture: GoldenFixture
) -> None:
    court_id = str(golden_fixture.court_ids["C-0003"])
    jurisdiction_id = str(golden_fixture.jurisdiction_id)
    assert (
        _count(
            counted_metrics, "/api/v1/metrics/compare", metric="eligible_cases", court_id=court_id
        )
        <= COMPARE_BUDGET
    )
    _, counter = counted_metrics
    assert len(counter.statements) == 1, "a non-empty page is one statement"
    assert all("person" not in statement for statement in counter.statements)
    assert (
        _count(
            counted_metrics,
            "/api/v1/metrics/compare",
            metric="new_case_rate",
            window="365",
            jurisdiction_id=jurisdiction_id,
            sort="rate",
            order="asc",
            limit="100",
        )
        <= COMPARE_BUDGET
    )
    # An empty page settles the total and the cohort's existence in one more statement.
    assert (
        _count(
            counted_metrics,
            "/api/v1/metrics/compare",
            metric="eligible_cases",
            court_id=court_id,
            offset="1000",
        )
        <= COMPARE_BUDGET
    )


def test_provenance_needs_at_most_six_statements(
    counted_metrics: tuple[TestClient, StatementCounter], golden_fixture: GoldenFixture
) -> None:
    client, counter = counted_metrics
    judge_id = golden_fixture.judge_ids["J-0003"]
    body = client.get(f"/api/v1/judges/{judge_id}/metrics").json()
    observations = [item for group in body["observations"].values() for item in group]
    # The observation with the most members costs the same number of statements.
    for item in sorted(observations, key=lambda o: o["eligible_count"])[-3:]:
        assert (
            _count(counted_metrics, f"/api/v1/metrics/{item['id']}/provenance") <= PROVENANCE_BUDGET
        )
        assert len(counter.statements) == 3
        assert all("raw_object_path" not in statement for statement in counter.statements)
        assert all("person_identifier" not in statement for statement in counter.statements)


def test_corrections_need_at_most_two_statements_and_no_returning(
    counted_metrics: tuple[TestClient, StatementCounter],
    golden_fixture: GoldenFixture,
    migrated_database: Engine,
) -> None:
    client, counter = counted_metrics
    counter.reset()
    response = client.post(
        "/api/v1/corrections",
        json={
            "target_type": "case",
            "target_id": str(golden_fixture.case_ids[GOLDEN_CASE]),
            "reason": "The filing date of this case is a month later than the docket shows.",
            "contact": "requester@example.invalid",
        },
    )
    assert response.status_code == 202, response.text
    try:
        assert len(counter.statements) <= CORRECTIONS_BUDGET
        assert not any("RETURNING" in statement.upper() for statement in counter.statements)
        assert not any(
            "SELECT" in s.upper() and "correction_request" in s for s in counter.statements
        )
    finally:
        with Session(migrated_database) as session:
            session.execute(
                delete(CorrectionRequest).where(CorrectionRequest.id == response.json()["id"])
            )
            session.commit()
