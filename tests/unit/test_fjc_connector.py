# tests/unit/test_fjc_connector.py
"""The FJC connector: discovery, bounded fetch, header validation, parsing projection."""

from __future__ import annotations

import asyncio
import csv
import io
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from judgemetrics.ingest.base import (
    PREVIOUS_ETAG,
    PREVIOUS_LAST_MODIFIED,
    PREVIOUS_SHA256,
    FetchError,
    RawArtifact,
    SourceArtifact,
    sha256_hex,
)
from judgemetrics.ingest.fjc.connector import FjcConnector
from judgemetrics.ingest.fjc.parse import parse_judges, parse_service, read_headers
from judgemetrics.ingest.fjc.schema import (
    DEMOGRAPHIC_HEADERS,
    JUDGES_EXPECTED_HEADERS,
    JUDGES_VERIFIED_HEADERS,
    RECORD_TYPE_JUDGE,
    RECORD_TYPE_SERVICE,
    SERVICE_EXPECTED_HEADERS,
    SERVICE_VERIFIED_HEADERS,
)
from judgemetrics.ingest.fjc.sources import EXPORT_PAGE_URL, JUDGES_CSV_URL, SERVICE_CSV_URL
from judgemetrics.ingest.http import DownloadError, DownloadTooLargeError, InsecureUrlError
from judgemetrics.ingest.registry import get_connector, registered_sources

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fjc"
JUDGES = FIXTURES / "judges.csv"
SERVICE = FIXTURES / "federal-judicial-service.csv"
NOW = datetime(2026, 9, 16, 18, 0, tzinfo=UTC)

Handler = Callable[[httpx.Request], httpx.Response]


def _artifact(
    name: str = "judges.csv", uri: str = JUDGES_CSV_URL, **metadata: str
) -> SourceArtifact:
    return SourceArtifact("fjc", name, uri, "text/csv", metadata)


def _raw(name: str, data: bytes) -> RawArtifact:
    return RawArtifact.from_bytes(_artifact(name), data, retrieved_at=NOW)


def _connector(handler: Handler, **kwargs: object) -> FjcConnector:
    async def no_sleep(_: float) -> None:
        return None

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)

    return FjcConnector(factory, sleep=no_sleep, **kwargs)  # type: ignore[arg-type]


def _without_column(path: Path, column: str) -> bytes:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    index = rows[0].index(column)
    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
    for row in rows:
        writer.writerow(row[:index] + row[index + 1 :])
    return out.getvalue().encode("utf-8")


def _with_columns(path: Path, extra: dict[str, str]) -> bytes:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(rows[0] + list(extra))
    for row in rows[1:]:
        writer.writerow(row + list(extra.values()))
    return out.getvalue().encode("utf-8")


# --- registry and discovery -----------------------------------------------------


def test_fjc_is_registered_with_its_parser_version() -> None:
    assert isinstance(get_connector("fjc"), FjcConnector)
    assert any(
        s.source_id == "fjc" and s.parser_version == "2026.09.1" for s in registered_sources()
    )


def test_discover_yields_the_two_verified_files() -> None:
    artifacts = asyncio.run(FjcConnector().discover())
    assert [a.external_id for a in artifacts] == ["judges.csv", "federal-judicial-service.csv"]
    assert [a.uri for a in artifacts] == [JUDGES_CSV_URL, SERVICE_CSV_URL]
    for artifact in artifacts:
        assert artifact.source_id == "fjc"
        assert artifact.uri.startswith("https://www.fjc.gov/")
        assert artifact.content_type == "text/csv"
        assert artifact.metadata["export_page"] == EXPORT_PAGE_URL
    assert not any("demographics" in a.uri for a in artifacts)


def test_source_info_names_the_owner_and_terms() -> None:
    info = FjcConnector.source_info
    assert "Federal Judicial Center" in info.owner
    assert info.access_method == "https_download"
    assert info.terms_metadata["export_page"] == EXPORT_PAGE_URL


# --- fetch ----------------------------------------------------------------------


def test_fetch_records_hash_size_and_validators() -> None:
    body = JUDGES.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "If-None-Match" not in request.headers
        return httpx.Response(
            200,
            content=body,
            headers={"ETag": '"abc"', "Last-Modified": "Wed, 16 Sep 2026 05:05:19 GMT"},
        )

    raw = asyncio.run(_connector(handler).fetch(_artifact()))
    assert raw.sha256 == sha256_hex(body)
    assert raw.size_bytes == len(body)
    assert raw.read_bytes() == body
    assert not raw.not_modified
    assert raw.response_headers["etag"] == '"abc"'
    assert raw.response_headers["last_modified"] == "Wed, 16 Sep 2026 05:05:19 GMT"
    assert raw.response_headers["final_url"] == JUDGES_CSV_URL
    assert raw.retrieved_at.tzinfo is not None


def test_fetch_sends_conditional_headers_and_honours_304() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(304, headers={"ETag": '"abc"'})

    artifact = _artifact(
        **{
            PREVIOUS_ETAG: '"abc"',
            PREVIOUS_LAST_MODIFIED: "Wed, 16 Sep 2026 05:05:19 GMT",
            PREVIOUS_SHA256: "f" * 64,
        }
    )
    raw = asyncio.run(_connector(handler).fetch(artifact))
    assert seen["if-none-match"] == '"abc"'
    assert seen["if-modified-since"] == "Wed, 16 Sep 2026 05:05:19 GMT"
    assert raw.not_modified
    assert raw.sha256 == "f" * 64
    assert raw.size_bytes == 0


def test_fetch_rejects_304_without_a_previous_hash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(304)

    with pytest.raises(FetchError, match="previous sha256"):
        asyncio.run(_connector(handler).fetch(_artifact(**{PREVIOUS_ETAG: '"abc"'})))


def test_fetch_enforces_the_size_cap_while_streaming() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 11)

    with pytest.raises(DownloadTooLargeError):
        asyncio.run(_connector(handler, max_bytes=10).fetch(_artifact()))


def test_fetch_enforces_the_size_cap_from_content_length() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5, headers={"Content-Length": "999999"})

    with pytest.raises(DownloadTooLargeError, match="declared size"):
        asyncio.run(_connector(handler, max_bytes=10).fetch(_artifact()))


def test_fetch_retries_transient_failures_with_backoff() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, content=b"ok")

    raw = asyncio.run(_connector(handler).fetch(_artifact()))
    assert raw.read_bytes() == b"ok"
    assert len(calls) == 3


def test_fetch_gives_up_after_the_retries() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(DownloadError, match="503"):
        asyncio.run(_connector(handler, retries=2).fetch(_artifact()))
    assert len(calls) == 3


def test_fetch_does_not_retry_client_errors() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    with pytest.raises(DownloadError, match="404"):
        asyncio.run(_connector(handler).fetch(_artifact()))
    assert len(calls) == 1


def test_fetch_retries_transport_errors() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, content=b"ok")

    raw = asyncio.run(_connector(handler).fetch(_artifact()))
    assert raw.read_bytes() == b"ok"
    assert len(calls) == 2


def test_fetch_refuses_plain_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        return httpx.Response(200, content=b"ok")

    with pytest.raises(InsecureUrlError):
        asyncio.run(_connector(handler).fetch(_artifact(uri="http://www.fjc.gov/judges.csv")))


def test_fetch_refuses_a_redirect_to_plain_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.scheme == "https":
            return httpx.Response(302, headers={"Location": "http://www.fjc.gov/judges.csv"})
        return httpx.Response(200, content=b"ok")

    with pytest.raises(InsecureUrlError):
        asyncio.run(_connector(handler).fetch(_artifact()))


# --- validate_raw -----------------------------------------------------------------


def test_validate_raw_accepts_the_fixture_files() -> None:
    connector = FjcConnector()
    for name, path in (("judges.csv", JUDGES), ("federal-judicial-service.csv", SERVICE)):
        result = connector.validate_raw(_raw(name, path.read_bytes()))
        assert result.ok, result.errors
        assert result.errors == []
        assert result.warnings == []


@pytest.mark.parametrize(
    ("name", "path", "column"),
    [
        ("judges.csv", JUDGES, "Commission Date (1)"),
        ("judges.csv", JUDGES, "nid"),
        ("federal-judicial-service.csv", SERVICE, "Commission Date"),
        ("federal-judicial-service.csv", SERVICE, "Termination"),
    ],
)
def test_validate_raw_fails_loudly_on_a_missing_expected_header(
    name: str, path: Path, column: str
) -> None:
    result = FjcConnector().validate_raw(_raw(name, _without_column(path, column)))
    assert not result.ok
    assert result.errors == [f"{name}: missing expected header {column!r}"]


def test_validate_raw_warns_about_unverified_headers() -> None:
    data = _with_columns(SERVICE, {"Brand New Column": "x"})
    result = FjcConnector().validate_raw(_raw("federal-judicial-service.csv", data))
    assert result.ok
    assert result.warnings == [
        "federal-judicial-service.csv: header 'Brand New Column' is not in the verified set"
    ]


@pytest.mark.parametrize("data", [b"", b"   \n\n", b"\n"])
def test_validate_raw_rejects_empty_files(data: bytes) -> None:
    result = FjcConnector().validate_raw(_raw("judges.csv", data))
    assert not result.ok
    assert result.errors == ["judges.csv: the file is empty"]


def test_validate_raw_rejects_a_file_without_the_header_row() -> None:
    result = FjcConnector().validate_raw(_raw("judges.csv", b'"1377101","42","Alito"\n'))
    assert not result.ok
    assert any("missing expected header 'nid'" in error for error in result.errors)


def test_validate_raw_rejects_unknown_artifacts() -> None:
    result = FjcConnector().validate_raw(_raw("demographics.csv", b"nid\n1\n"))
    assert not result.ok
    assert result.errors == ["demographics.csv: not an FJC artifact"]


def test_validate_raw_passes_unchanged_artifacts() -> None:
    raw = RawArtifact.unchanged(_artifact(), sha256="a" * 64, retrieved_at=NOW)
    assert FjcConnector().validate_raw(raw).ok
    assert list(FjcConnector().parse(raw)) == []


# --- parse ------------------------------------------------------------------------


def test_read_headers_matches_the_verified_sets_minus_demographics() -> None:
    assert read_headers(SERVICE.read_bytes()) == list(SERVICE_VERIFIED_HEADERS)
    judges_headers = read_headers(JUDGES.read_bytes())
    assert judges_headers == [h for h in JUDGES_VERIFIED_HEADERS if h not in DEMOGRAPHIC_HEADERS]
    assert len(JUDGES_VERIFIED_HEADERS) == 201
    assert len(SERVICE_VERIFIED_HEADERS) == 30


def test_parse_judges_projects_rows_to_expected_headers() -> None:
    drafts = list(parse_judges(JUDGES.read_bytes()))
    assert len(drafts) == 25
    first = drafts[0]
    assert first.record_type == RECORD_TYPE_JUDGE
    assert first.external_record_id == first.payload["nid"] == "13761857"
    assert set(first.payload) == set(JUDGES_EXPECTED_HEADERS)
    assert all(isinstance(value, str) for value in first.payload.values())
    assert first.payload["Suffix"] == ""  # trimmed


def test_parse_service_keys_rows_by_nid_and_sequence() -> None:
    drafts = list(parse_service(SERVICE.read_bytes()))
    assert len(drafts) == 42
    assert drafts[0].record_type == RECORD_TYPE_SERVICE
    assert drafts[0].external_record_id == "13761857:1"
    assert set(drafts[0].payload) == set(SERVICE_EXPECTED_HEADERS)
    assert len({d.external_record_id for d in drafts}) == 42


def test_demographic_columns_never_reach_a_payload() -> None:
    assert not set(DEMOGRAPHIC_HEADERS) & set(JUDGES_EXPECTED_HEADERS)
    data = _with_columns(JUDGES, {"Gender": "Female", "Race or Ethnicity": "White"})
    for draft in parse_judges(data):
        assert not set(DEMOGRAPHIC_HEADERS) & set(draft.payload)
        assert "Female" not in draft.payload.values()
