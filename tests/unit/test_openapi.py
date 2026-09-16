# tests/unit/test_openapi.py
"""The committed OpenAPI document and what it promises.

`docs/openapi.json` must equal the rendered document (regenerate it with
`judgemetrics openapi export` after any route change: Step 5 generates
the web client from it). The document lists exactly the health probes and
the eight v1 paths, every route's strict query allow-list matches the
parameters the document declares, every error response is an `ErrorBody`,
and the API-key scheme is declared optional.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from typer.testing import CliRunner

from judgemetrics.api import API_PREFIX
from judgemetrics.api.deps import StrictQuery
from judgemetrics.api.routes import courts, judges, jurisdictions, search
from judgemetrics.cli import app as cli
from judgemetrics.openapi import openapi_document, render_openapi

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED = REPO_ROOT / "docs" / "openapi.json"
EXPECTED_PATHS = {
    "/api/v1/health",
    "/api/v1/ready",
    "/api/v1/judges",
    "/api/v1/judges/{judge_id}",
    "/api/v1/judges/{judge_id}/service",
    "/api/v1/courts",
    "/api/v1/courts/{court_id}",
    "/api/v1/jurisdictions",
    "/api/v1/jurisdictions/{jurisdiction_id}",
    "/api/v1/search",
}


def test_committed_document_equals_the_generated_one() -> None:
    rendered = render_openapi()
    assert rendered.endswith("\n") and not rendered.endswith("\n\n")
    assert "\r" not in rendered
    assert COMMITTED.read_bytes().decode("utf-8") == rendered, (
        "docs/openapi.json is stale: run `uv run judgemetrics openapi export`"
    )
    # Sorted keys at every level, so the diff of a change is minimal.
    parsed = json.loads(rendered)
    assert json.dumps(parsed, indent=2, sort_keys=True, ensure_ascii=False) + "\n" == rendered


def test_document_lists_exactly_the_health_and_v1_paths() -> None:
    document = openapi_document()
    assert set(document["paths"]) == EXPECTED_PATHS
    assert all(set(item) == {"get"} for item in document["paths"].values())
    assert document["info"]["title"] == "JudgeMetrics API"


def test_error_responses_are_the_error_envelope() -> None:
    document = openapi_document()
    error_ref = {"$ref": "#/components/schemas/ErrorBody"}
    for path, item in document["paths"].items():
        if path in {"/api/v1/health", "/api/v1/ready"}:
            continue
        for status, response in item["get"]["responses"].items():
            if status.startswith("2"):
                continue
            schema = response["content"]["application/json"]["schema"]
            assert schema == error_ref, (path, status)
    assert set(document["components"]["schemas"]["ErrorBody"]["required"]) == {
        "code",
        "message",
        "request_id",
    }


def test_strict_query_allow_lists_match_the_declared_parameters() -> None:
    """A parameter a route declares but the allow-list omits would be rejected as unknown."""
    document = openapi_document()
    checked = 0
    for router in (judges.router, courts.router, jurisdictions.router, search.router):
        for route in router.routes:
            assert isinstance(route, APIRoute)
            path = API_PREFIX + route.path
            assert path in EXPECTED_PATHS
            strict = [
                d.dependency for d in route.dependencies if isinstance(d.dependency, StrictQuery)
            ]
            assert len(strict) == 1, path
            declared = {
                parameter["name"]
                for parameter in document["paths"][path]["get"].get("parameters", [])
                if parameter["in"] == "query"
            }
            assert strict[0].allowed == declared, path
            checked += 1
    assert checked == 8


def test_api_key_scheme_is_declared_optional() -> None:
    document = openapi_document()
    scheme = document["components"]["securitySchemes"]["ApiKey"]
    assert scheme == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": scheme["description"],
    }
    # An empty requirement object means "no security" is acceptable.
    assert document["security"] == [{}, {"ApiKey": []}]


def test_page_sizes_are_capped_in_the_document() -> None:
    document = openapi_document()
    for path in ("/api/v1/judges", "/api/v1/courts", "/api/v1/jurisdictions", "/api/v1/search"):
        parameters: dict[str, dict[str, Any]] = {
            parameter["name"]: parameter["schema"]
            for parameter in document["paths"][path]["get"]["parameters"]
        }
        assert parameters["limit"]["maximum"] == 100, path
        assert parameters["limit"]["minimum"] == 1, path
        assert parameters["limit"]["default"] == 25, path
        if path != "/api/v1/search":
            assert parameters["offset"]["minimum"] == 0, path


def test_cli_export_writes_the_same_document(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "openapi.json"
    result = CliRunner().invoke(cli, ["openapi", "export", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == render_openapi().encode("utf-8")
