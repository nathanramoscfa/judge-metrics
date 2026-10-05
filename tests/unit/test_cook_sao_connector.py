# tests/unit/test_cook_sao_connector.py
"""The Cook County connector at parser version 0: discovery, portal metadata, the
rows-updated short-circuit, the streamed export, header validation, no parsing."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from judgemetrics.ingest.base import (
    PREVIOUS_ROWS_UPDATED_AT,
    PREVIOUS_SHA256,
    FetchError,
    RawArtifact,
    SourceArtifact,
    SourceRecordDraft,
    SupportsContext,
    SupportsWorkDir,
    sha256_hex,
)
from judgemetrics.ingest.cook_sao import sources
from judgemetrics.ingest.cook_sao.connector import (
    META_COLUMNS,
    CookSaoConnector,
    parse_portal_metadata,
)
from judgemetrics.ingest.cook_sao.schema import (
    BLANKED_COLUMNS,
    CODED_COLUMNS,
    JUDGE_COLUMNS,
    RESTRICTED_COLUMNS,
    VERIFIED_HEADERS,
)
from judgemetrics.ingest.http import DownloadTooLargeError
from judgemetrics.ingest.registry import get_connector, registered_sources

pytestmark = pytest.mark.unit

ROWS_UPDATED = 1775139822  # 2026-04-02T14:23:42Z, Diversion's rowsUpdatedAt
ROWS_UPDATED_ISO = "2026-04-02T14:23:42+00:00"
DIVERSION = sources.DIVERSION

Handler = Callable[[httpx.Request], httpx.Response]


def _metadata(
    dataset: sources.Dataset = DIVERSION,
    *,
    rows_updated: int = ROWS_UPDATED,
    columns: tuple[str, ...] | None = None,
) -> bytes:
    names = columns if columns is not None else VERIFIED_HEADERS[dataset.external_id]
    document = {
        "id": dataset.portal_id,
        "name": dataset.name,
        "rowsUpdatedAt": rows_updated,
        "license": {"name": "Public Domain"},
        "licenseId": "PUBLIC_DOMAIN",
        "attribution": "Cook County State's Attorney's Office",
        "columns": [
            {"name": ":id", "fieldName": ":id"},
            *({"name": name, "fieldName": name.lower()} for name in names),
        ],
    }
    return json.dumps(document).encode()


def _export(headers: tuple[str, ...]) -> bytes:
    return (",".join(headers) + "\n" + "," * (len(headers) - 1) + "\n").encode()


EXPORT = _export(VERIFIED_HEADERS[DIVERSION.external_id])


def _connector(handler: Handler, work_dir: Path | None, **kwargs: object) -> CookSaoConnector:
    async def no_sleep(_: float) -> None:
        return None

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)

    return CookSaoConnector(factory, sleep=no_sleep, work_dir=work_dir, **kwargs)  # type: ignore[arg-type]


def _portal(
    metadata: bytes = _metadata(), export: bytes = EXPORT, seen: list[str] | None = None
) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.url.path)
        if request.url.path.endswith(".json"):
            return httpx.Response(200, content=metadata)
        return httpx.Response(200, content=export, headers={"ETag": '"e1"'})

    return handler


def _artifact(**metadata: str) -> SourceArtifact:
    artifacts = asyncio.run(CookSaoConnector().discover())
    found = next(a for a in artifacts if a.external_id == DIVERSION.external_id)
    return found.with_metadata(**metadata)


def _raw(name: str, data: bytes, headers: dict[str, str] | None = None) -> RawArtifact:
    artifact = SourceArtifact("cook_sao", name, "https://example.org", "text/csv")
    return RawArtifact.from_bytes(
        artifact, data, retrieved_at=datetime(2026, 10, 5, tzinfo=UTC), response_headers=headers
    )


# --- registry and discovery -------------------------------------------------------


def test_the_registry_lists_the_connector_at_parser_version_0() -> None:
    assert isinstance(get_connector("cook_sao"), CookSaoConnector)
    assert any(s.source_id == "cook_sao" and s.parser_version == "0" for s in registered_sources())
    assert isinstance(CookSaoConnector(), SupportsWorkDir)
    assert not isinstance(CookSaoConnector(), SupportsContext)


def test_discover_lists_the_five_datasets_in_dependency_order_without_a_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("discover must not touch the network")

    artifacts = asyncio.run(_connector(handler, None).discover())
    assert [a.external_id for a in artifacts] == [
        "intake.csv",
        "initiation.csv",
        "dispositions.csv",
        "sentencing.csv",
        "diversion.csv",
    ]
    for artifact, dataset in zip(artifacts, sources.DATASETS, strict=True):
        assert artifact.uri == (
            "https://datacatalog.cookcountyil.gov/api/views/"
            f"{dataset.portal_id}/rows.csv?accessType=DOWNLOAD"
        )
        assert dataset.metadata_url.startswith("https://datacatalog.cookcountyil.gov/api/views/")
        assert artifact.metadata["portal_id"] == dataset.portal_id
    assert {d.portal_id for d in sources.DATASETS} == {
        "3k7z-hchi",
        "7mck-ehwz",
        "apwk-dzx8",
        "tg8v-tm6u",
        "gpu3-5dfh",
    }
    # The archived 2018 releases are recorded, never fetched.
    assert {a.uri for a in artifacts}.isdisjoint(d.export_url for d in sources.ARCHIVED_DATASETS)


def test_source_info_names_the_owner_terms_and_no_observable_outcome() -> None:
    info = CookSaoConnector.source_info
    assert info.owner == "Cook County State's Attorney's Office"
    assert info.source_type == "government_open_data"
    assert info.access_method == "socrata_bulk_export"
    assert info.observable_outcomes == ()
    assert info.terms_metadata["terms"] == "https://www.cookcountyil.gov/terms-use"
    assert info.terms_metadata["license"] == "Public Domain"
    assert info.terms_metadata["attribution"] == "Cook County State's Attorney's Office"
    assert set(info.terms_metadata["redistribution"]) == {
        "aggregates",
        "record_level",
        "commercial",
    }


# --- portal metadata and the rows-updated short-circuit ---------------------------


def test_parse_portal_metadata_reads_rows_updated_license_and_columns() -> None:
    portal = parse_portal_metadata(_metadata(), portal_id=DIVERSION.portal_id)
    assert portal.rows_updated_at == ROWS_UPDATED_ISO
    assert portal.license == "Public Domain"
    assert portal.attribution == "Cook County State's Attorney's Office"
    assert portal.columns == VERIFIED_HEADERS["diversion.csv"]


@pytest.mark.parametrize(
    "data",
    [b"not json", json.dumps({"id": "gpu3-5dfh"}).encode(), _metadata(sources.INTAKE)],
)
def test_parse_portal_metadata_refuses_an_unreadable_or_foreign_document(data: bytes) -> None:
    with pytest.raises(FetchError):
        parse_portal_metadata(data, portal_id=DIVERSION.portal_id)


def test_fetch_records_the_metadata_and_streams_the_export(tmp_path: Path) -> None:
    raw = asyncio.run(_connector(_portal(), tmp_path).fetch(_artifact()))
    assert isinstance(raw.path_or_bytes, Path)
    assert raw.path_or_bytes.parent == tmp_path
    assert raw.path_or_bytes.read_bytes() == EXPORT
    assert raw.sha256 == sha256_hex(EXPORT) and raw.size_bytes == len(EXPORT)
    assert not raw.not_modified
    headers = raw.response_headers
    assert headers["rows_updated_at"] == ROWS_UPDATED_ISO
    assert headers["license"] == "Public Domain"
    assert headers["portal_id"] == DIVERSION.portal_id
    assert headers[META_COLUMNS].split(",") == list(VERIFIED_HEADERS["diversion.csv"])
    assert headers["etag"] == '"e1"'


def test_an_unchanged_rows_updated_time_downloads_nothing(tmp_path: Path) -> None:
    seen: list[str] = []
    artifact = _artifact(**{PREVIOUS_SHA256: "a" * 64, PREVIOUS_ROWS_UPDATED_AT: ROWS_UPDATED_ISO})
    raw = asyncio.run(_connector(_portal(seen=seen), tmp_path).fetch(artifact))
    assert raw.not_modified
    assert raw.sha256 == "a" * 64 and raw.size_bytes == 0
    assert raw.response_headers["rows_updated_at"] == ROWS_UPDATED_ISO
    assert seen == [f"/api/views/{DIVERSION.portal_id}.json"]
    assert list(tmp_path.iterdir()) == []


def test_a_changed_rows_updated_time_downloads_the_export(tmp_path: Path) -> None:
    seen: list[str] = []
    artifact = _artifact(
        **{PREVIOUS_SHA256: "a" * 64, PREVIOUS_ROWS_UPDATED_AT: "2025-01-01T00:00:00+00:00"}
    )
    raw = asyncio.run(_connector(_portal(seen=seen), tmp_path).fetch(artifact))
    assert not raw.not_modified and raw.sha256 == sha256_hex(EXPORT)
    assert seen[-1] == f"/api/views/{DIVERSION.portal_id}/rows.csv"


def test_a_304_on_the_export_is_unchanged(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".json"):
            return httpx.Response(200, content=_metadata(rows_updated=ROWS_UPDATED + 60))
        assert request.headers["if-none-match"] == '"e0"'
        return httpx.Response(304)

    artifact = _artifact(
        **{
            PREVIOUS_SHA256: "b" * 64,
            PREVIOUS_ROWS_UPDATED_AT: ROWS_UPDATED_ISO,
            "previous_etag": '"e0"',
        }
    )
    raw = asyncio.run(_connector(handler, tmp_path).fetch(artifact))
    assert raw.not_modified and raw.sha256 == "b" * 64
    assert list(tmp_path.iterdir()) == []


def test_the_export_cap_is_enforced_and_leaves_no_file(tmp_path: Path) -> None:
    with pytest.raises(DownloadTooLargeError):
        asyncio.run(_connector(_portal(), tmp_path, max_bytes=10).fetch(_artifact()))
    assert list(tmp_path.iterdir()) == []


def test_fetch_needs_a_work_directory() -> None:
    with pytest.raises(FetchError, match="work directory"):
        asyncio.run(_connector(_portal(), None).fetch(_artifact()))


def test_fetch_refuses_an_unknown_artifact(tmp_path: Path) -> None:
    artifact = SourceArtifact("cook_sao", "other.csv", "https://example.org/x", "text/csv")
    with pytest.raises(FetchError, match="not a Cook County"):
        asyncio.run(_connector(_portal(), tmp_path).fetch(artifact))


# --- validation -------------------------------------------------------------------


def test_validate_raw_passes_the_verified_header_from_a_file(tmp_path: Path) -> None:
    raw = asyncio.run(_connector(_portal(), tmp_path).fetch(_artifact()))
    result = CookSaoConnector().validate_raw(raw)
    assert result.ok and result.errors == [] and result.warnings == []


@pytest.mark.parametrize("dataset", sources.DATASETS, ids=lambda d: d.external_id)
def test_validate_raw_passes_every_verified_header_set(dataset: sources.Dataset) -> None:
    raw = _raw(dataset.external_id, _export(VERIFIED_HEADERS[dataset.external_id]))
    assert CookSaoConnector().validate_raw(raw).ok


def test_a_missing_verified_header_fails_naming_it() -> None:
    headers = tuple(h for h in VERIFIED_HEADERS["diversion.csv"] if h != "DIVERSION_RESULT")
    result = CookSaoConnector().validate_raw(_raw("diversion.csv", _export(headers)))
    assert not result.ok
    assert result.errors == [
        "diversion.csv: verified header 'DIVERSION_RESULT' is missing from the export"
    ]


def test_an_extra_header_is_a_warning() -> None:
    headers = (*VERIFIED_HEADERS["diversion.csv"], "NEW_COLUMN")
    result = CookSaoConnector().validate_raw(_raw("diversion.csv", _export(headers)))
    assert result.ok
    assert result.warnings == [
        "diversion.csv: export header 'NEW_COLUMN' is not in the verified set"
    ]


def test_the_metadata_column_list_is_checked_too() -> None:
    columns = ",".join(h for h in VERIFIED_HEADERS["diversion.csv"] if h != "STATUTE")
    result = CookSaoConnector().validate_raw(
        _raw("diversion.csv", EXPORT, {META_COLUMNS: columns + ",EXTRA"})
    )
    assert not result.ok
    assert result.errors == [
        "diversion.csv: verified header 'STATUTE' is missing from the portal metadata"
    ]
    assert result.warnings == [
        "diversion.csv: portal metadata header 'EXTRA' is not in the verified set"
    ]


@pytest.mark.parametrize("data", [b"", b"\n"])
def test_an_empty_export_fails(data: bytes) -> None:
    assert not CookSaoConnector().validate_raw(_raw("diversion.csv", data)).ok


def test_an_unknown_artifact_fails_validation() -> None:
    assert not CookSaoConnector().validate_raw(_raw("other.csv", EXPORT)).ok


def test_an_unchanged_artifact_passes_without_a_payload() -> None:
    artifact = SourceArtifact("cook_sao", "diversion.csv", "https://example.org", "text/csv")
    raw = RawArtifact.unchanged(artifact, sha256="c" * 64, retrieved_at=datetime.now(tz=UTC))
    assert CookSaoConnector().validate_raw(raw).ok


# --- parser version 0 ---------------------------------------------------------------


def test_parse_and_normalize_yield_nothing() -> None:
    connector = CookSaoConnector()
    assert list(connector.parse(_raw("diversion.csv", EXPORT))) == []
    record = SourceRecordDraft(external_record_id="x", effective_at=None, payload={})
    assert list(connector.normalize(record)) == []


def test_the_column_classes_name_verified_headers_only() -> None:
    every = {header for headers in VERIFIED_HEADERS.values() for header in headers}
    for name, coded in CODED_COLUMNS.items():
        assert set(coded) <= set(VERIFIED_HEADERS[name]), name
    for name, column in JUDGE_COLUMNS.items():
        assert column in VERIFIED_HEADERS[name]
    assert set(BLANKED_COLUMNS) <= every
    assert set(RESTRICTED_COLUMNS) <= set(BLANKED_COLUMNS)
    assert {"RACE", "GENDER", "AGE_AT_INCIDENT"} == set(RESTRICTED_COLUMNS)
    assert not set(BLANKED_COLUMNS) & {c for coded in CODED_COLUMNS.values() for c in coded}
