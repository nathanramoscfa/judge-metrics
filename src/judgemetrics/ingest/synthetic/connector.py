# src/judgemetrics/ingest/synthetic/connector.py
"""``SyntheticConnector``: the generated justice dataset through the standard runner.

``discover`` lists ``manifest.json`` first and then the nine source files
under ``Settings.synthetic_dir`` (the directory ``judgemetrics synthetic
generate`` wrote: ``manifest.json``, ``source/``, and ``truth/``, of which
``truth/`` is never discovered); ``fetch`` reads bytes from disk with
``RawArtifact.from_path`` after checking that every discovered name is a
plain relative path inside that directory. ``load_context`` (the runner
calls it with every artifact of the run before anything is parsed) checks
each source file's sha256 against the manifest and fails the run on
drift, then builds the cross-row lookups ``normalize`` needs.
``validate_raw`` checks the manifest's ``generator_version`` and that it
lists every source file, and each CSV's header row against the expected
set (missing → error naming the header, extra → warning).

The connector hashes person identifiers with the pepper from settings; it
refuses to be constructed without one (``IdentifierPepperMissingError``),
which is how the ingest CLI fails at startup when the pepper is unset.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import polars as pl
from pydantic import SecretStr

from judgemetrics.config import Settings, get_settings
from judgemetrics.ingest.base import (
    HEADER_CONTENT_TYPE,
    HEADER_FINAL_URL,
    CanonicalRecord,
    FetchError,
    IngestError,
    RawArtifact,
    SourceArtifact,
    SourceRecordDraft,
    ValidationResult,
    utc_now,
)
from judgemetrics.ingest.registry import register
from judgemetrics.ingest.synthetic import sources
from judgemetrics.ingest.synthetic.normalize import (
    SyntheticContext,
    build_context,
    normalize_record,
)
from judgemetrics.ingest.synthetic.parse import iter_rows, parse_file, read_frame, read_headers
from judgemetrics.ingest.synthetic.schema import (
    CHARGES_FILE,
    COURTS_FILE,
    EXPECTED_HEADERS,
    JUDGES_FILE,
    MANIFEST_FILE,
    RECORD_TYPE_MANIFEST,
    SOURCE_DIR,
    SOURCE_FILES,
    artifact_id,
)
from judgemetrics.security.identifiers import require_identifier_pepper
from judgemetrics.synthetic.config import GENERATOR_VERSION

CONTENT_TYPE_CSV = "text/csv"
CONTENT_TYPE_JSON = "application/json"


class ManifestDriftError(IngestError):
    """A source file no longer matches the manifest that describes the dataset."""


def check_relative_name(name: str) -> PurePosixPath:
    """``name`` as a plain relative POSIX path (no drive, root, or ``..``), else ``FetchError``."""
    path = PurePosixPath(name)
    if (
        not name
        or name != path.as_posix()
        or path.is_absolute()
        or "\\" in name
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        msg = f"artifact id is not a plain relative path: {name!r}"
        raise FetchError(msg)
    return path


def resolve_inside(root: Path, name: str) -> Path:
    """``root / name`` resolved, after checking it stays inside ``root``."""
    relative = check_relative_name(name)
    base = root.resolve()
    path = (base / Path(*relative.parts)).resolve()
    if base != path and base not in path.parents:
        msg = f"artifact {name!r} escapes the dataset directory"
        raise FetchError(msg)
    return path


@register
class SyntheticConnector:
    source_id = sources.SOURCE_ID
    parser_version = "1"
    source_info = sources.SOURCE_INFO

    def __init__(
        self,
        dataset_dir: Path | None = None,
        *,
        pepper: SecretStr | None = None,
        settings: Settings | None = None,
    ) -> None:
        resolved = settings if settings is not None else get_settings()
        self.dataset_dir = Path(dataset_dir if dataset_dir is not None else resolved.synthetic_dir)
        self._pepper = pepper if pepper is not None else require_identifier_pepper(resolved)
        self._context = SyntheticContext()
        self._context_loaded = False

    @property
    def context(self) -> SyntheticContext:
        return self._context

    # --- discovery and retrieval ----------------------------------------------------

    def _artifact(self, name: str, content_type: str) -> SourceArtifact:
        return SourceArtifact(
            source_id=self.source_id,
            external_id=name,
            uri=(self.dataset_dir.resolve() / Path(*PurePosixPath(name).parts)).as_uri(),
            content_type=content_type,
            metadata={"dataset_dir": str(self.dataset_dir)},
        )

    async def discover(self) -> list[SourceArtifact]:
        artifacts = [self._artifact(MANIFEST_FILE, CONTENT_TYPE_JSON)]
        artifacts.extend(
            self._artifact(artifact_id(name), CONTENT_TYPE_CSV) for name in SOURCE_FILES
        )
        return artifacts

    async def fetch(self, artifact: SourceArtifact) -> RawArtifact:
        path = resolve_inside(self.dataset_dir, artifact.external_id)
        if not path.is_file():
            msg = f"{artifact.external_id}: not found under {self.dataset_dir}"
            raise FetchError(msg)
        return RawArtifact.from_path(
            artifact,
            path,
            retrieved_at=utc_now(),
            response_headers={
                HEADER_CONTENT_TYPE: artifact.content_type,
                HEADER_FINAL_URL: path.as_uri(),
            },
        )

    # --- context: manifest drift and cross-row lookups -------------------------------

    def load_context(self, artifacts: Sequence[RawArtifact]) -> None:
        by_id = {raw.artifact.external_id: raw for raw in artifacts}
        manifest = by_id.get(MANIFEST_FILE)
        if manifest is None:
            msg = f"{MANIFEST_FILE} was not retrieved"
            raise ManifestDriftError(msg)
        listed = _manifest_files(_load_manifest(manifest.read_bytes()))
        drift: list[str] = []
        for name in SOURCE_FILES:
            external_id = artifact_id(name)
            raw = by_id.get(external_id)
            expected = listed.get(external_id)
            if raw is None:
                drift.append(f"{external_id}: not retrieved")
            elif expected is None:
                drift.append(f"{external_id}: not listed in the manifest")
            elif raw.sha256 != expected:
                drift.append(f"{external_id}: sha256 does not match the manifest")
        if drift:
            msg = "manifest drift: " + "; ".join(drift)
            raise ManifestDriftError(msg)
        self._context = build_context(
            _rows(by_id[artifact_id(COURTS_FILE)], COURTS_FILE),
            _rows(by_id[artifact_id(JUDGES_FILE)], JUDGES_FILE),
            _rows(by_id[artifact_id(CHARGES_FILE)], CHARGES_FILE),
        )
        self._context_loaded = True

    # --- validation, parsing, normalization --------------------------------------------

    def validate_raw(self, artifact: RawArtifact) -> ValidationResult:
        name = artifact.artifact.external_id
        if name == MANIFEST_FILE:
            return self._validate_manifest(artifact)
        file_name = _source_file_name(name)
        if file_name is None:
            return ValidationResult.failed([f"{name}: not a synthetic artifact"])
        data = artifact.read_bytes()
        if not data.strip():
            return ValidationResult.failed([f"{name}: the file is empty"])
        try:
            headers = read_headers(data)
        except pl.exceptions.PolarsError as exc:
            return ValidationResult.failed([f"{name}: no readable CSV header row ({exc})"])
        expected = EXPECTED_HEADERS[file_name]
        present = set(headers)
        errors = [
            f"{name}: missing expected header {header!r}"
            for header in expected
            if header not in present
        ]
        warnings = [
            f"{name}: header {header!r} is not in the expected set"
            for header in headers
            if header not in expected
        ]
        if errors:
            return ValidationResult.failed(errors, warnings)
        return ValidationResult.passed(warnings)

    def _validate_manifest(self, artifact: RawArtifact) -> ValidationResult:
        name = artifact.artifact.external_id
        try:
            payload = _load_manifest(artifact.read_bytes())
        except ManifestDriftError as exc:
            return ValidationResult.failed([f"{name}: {exc}"])
        errors: list[str] = []
        version = str(payload.get("generator_version", ""))
        if version != GENERATOR_VERSION:
            errors.append(
                f"{name}: generator_version {version!r} is not the connector's "
                f"{GENERATOR_VERSION!r}"
            )
        listed = _manifest_files(payload)
        errors.extend(
            f"{name}: source file {artifact_id(file)!r} is not listed"
            for file in SOURCE_FILES
            if artifact_id(file) not in listed
        )
        warnings = [
            f"{name}: lists {relative!r}, which the connector does not ingest"
            for relative in sorted(listed)
            if relative.startswith(f"{SOURCE_DIR}/")
            and relative not in {artifact_id(file) for file in SOURCE_FILES}
        ]
        if errors:
            return ValidationResult.failed(errors, warnings)
        return ValidationResult.passed(warnings)

    def parse(self, artifact: RawArtifact) -> Iterable[SourceRecordDraft]:
        name = artifact.artifact.external_id
        if name == MANIFEST_FILE:
            return []
        file_name = _source_file_name(name)
        if file_name is None:
            msg = f"{name}: not a synthetic artifact"
            raise FetchError(msg)
        return parse_file(file_name, artifact.read_bytes())

    def normalize(self, record: SourceRecordDraft) -> Iterable[CanonicalRecord]:
        if record.record_type == RECORD_TYPE_MANIFEST:
            return []
        return normalize_record(self._context, self._pepper, record)


def _source_file_name(external_id: str) -> str | None:
    prefix = f"{SOURCE_DIR}/"
    if not external_id.startswith(prefix):
        return None
    name = external_id[len(prefix) :]
    return name if name in EXPECTED_HEADERS else None


def _load_manifest(data: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        msg = f"unreadable manifest ({exc.__class__.__name__})"
        raise ManifestDriftError(msg) from exc
    if not isinstance(payload, dict):
        msg = "the manifest is not a JSON object"
        raise ManifestDriftError(msg)
    return payload


def _manifest_files(payload: dict[str, Any]) -> dict[str, str]:
    files = payload.get("files")
    if not isinstance(files, dict):
        msg = "the manifest has no `files` mapping"
        raise ManifestDriftError(msg)
    return {str(key): str(value) for key, value in files.items()}


def _rows(raw: RawArtifact, file_name: str) -> list[dict[str, str]]:
    try:
        frame = read_frame(raw.read_bytes())
    except pl.exceptions.PolarsError:
        return []
    return list(iter_rows(frame, EXPECTED_HEADERS[file_name]))
