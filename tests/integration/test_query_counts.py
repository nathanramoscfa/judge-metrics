# tests/integration/test_query_counts.py
"""The N+1 guard: statements per request, counted at the cursor.

A `before_cursor_execute` listener on the app's engine counts every
statement the driver runs. Budgets (ROADMAP.md §5 "Performance rules"):
judge detail at most three (judge, service records with their courts,
provenance), any list at most two (the page with its window count, plus
the similarity-threshold `set_config` when `q` is given), search at most
two (`set_config` and the union).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from judgemetrics.config import Settings
from tests.integration.conftest import FjcFixture, make_app

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
def counted(fjc_fixture: FjcFixture) -> Iterator[tuple[TestClient, StatementCounter]]:
    app = make_app(Settings())
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


def test_judge_detail_needs_at_most_three_statements(
    counted: tuple[TestClient, StatementCounter], fjc_fixture: FjcFixture
) -> None:
    judge_id = fjc_fixture.judge_ids[ALITO]
    assert _count(counted, f"/api/v1/judges/{judge_id}") <= 3
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
