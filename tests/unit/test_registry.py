# tests/unit/test_registry.py
"""The connector registry and the `ingest list-sources` command."""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from typer.testing import CliRunner

from judgemetrics.cli import app
from judgemetrics.ingest import registry
from judgemetrics.ingest.base import (
    CanonicalRecord,
    RawArtifact,
    SourceArtifact,
    SourceInfo,
    SourceRecordDraft,
    ValidationResult,
)
from judgemetrics.ingest.registry import (
    UnknownSourceError,
    get_connector,
    register,
    registered_sources,
)

pytestmark = pytest.mark.unit


class _Stub:
    source_id = "stub-source"
    parser_version = "1"
    source_info = SourceInfo(owner="tests", source_type="fixture", access_method="in-memory")

    async def discover(self) -> list[SourceArtifact]:
        return []

    async def fetch(self, artifact: SourceArtifact) -> RawArtifact:
        raise NotImplementedError

    def validate_raw(self, artifact: RawArtifact) -> ValidationResult:
        return ValidationResult.passed()

    def parse(self, artifact: RawArtifact) -> Iterable[SourceRecordDraft]:
        return []

    def normalize(self, record: SourceRecordDraft) -> Iterable[CanonicalRecord]:
        return []


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))  # noqa: SLF001


def test_register_returns_the_class_and_lists_it() -> None:
    assert register(_Stub) is _Stub
    assert isinstance(get_connector("stub-source"), _Stub)
    assert any(
        s.source_id == "stub-source" and s.parser_version == "1" for s in registered_sources()
    )


def test_register_is_idempotent_for_the_same_class() -> None:
    register(_Stub)
    register(_Stub)
    assert sum(1 for s in registered_sources() if s.source_id == "stub-source") == 1


def test_register_rejects_a_duplicate_id_from_another_class() -> None:
    register(_Stub)

    class Other(_Stub):
        pass

    with pytest.raises(ValueError, match="already registered"):
        register(Other)


def test_register_requires_source_id_and_parser_version() -> None:
    class NoId(_Stub):
        source_id = ""

    class NoVersion(_Stub):
        source_id = "another"
        parser_version = ""

    with pytest.raises(ValueError, match="source_id"):
        register(NoId)
    with pytest.raises(ValueError, match="parser_version"):
        register(NoVersion)


def test_unknown_source_raises() -> None:
    with pytest.raises(UnknownSourceError):
        get_connector("nope")


def test_builtin_fjc_connector_is_registered() -> None:
    assert [s.source_id for s in registered_sources() if s.source_id == "fjc"] == ["fjc"]


def test_cli_list_sources_prints_ids_with_parser_versions() -> None:
    result = CliRunner().invoke(app, ["ingest", "list-sources"])
    assert result.exit_code == 0, result.output
    assert "fjc\t2026.09.1" in result.output
