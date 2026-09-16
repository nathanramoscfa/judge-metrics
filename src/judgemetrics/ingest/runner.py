# src/judgemetrics/ingest/runner.py
"""The fourteen-step idempotent ingest runner.

Brief step → function here:

 1. discover                      ``connector.discover()`` in ``_execute``
 2. download or retrieve          ``_retrieve`` (``connector.fetch`` or a fixture file)
 3. calculate cryptographic hash  ``RawArtifact`` sha256, re-verified in ``_retrieve``
 4. save immutable raw object     ``store.put`` with a hash-derived key
 5. create source_record          ``_retrieve`` (one record per artifact per hash)
 6. parse                         ``connector.parse``
 7. schema validate               ``connector.validate_raw`` — run before 6: a raw
                                  artifact is validated before it is parsed, and
                                  errors fail the run before anything is derived
 8. normalize                     ``connector.normalize`` per parsed row
 9. deduplicate                   ``_deduplicate`` by ``natural_key`` within the run
10. resolve entities              ``_resolve`` (exact external-id match for judges,
                                  exact (canonical_name, court_type) for courts)
11. run data-quality checks       ``judgemetrics.quality.checks.run_checks``
12. publish canonical rows        ``_publish``: ``INSERT … ON CONFLICT`` upserts that
                                  write only rows whose substantive columns changed
13. recompute affected metrics    ``recompute_metrics`` (no-op until Phase 3)
14. record lineage and run stats  issues linked to source records and entities;
                                  ``ingest_run`` counts, versions, status

Idempotency: an artifact whose ``(source, external_id, sha256)`` already
has a ``source_record`` is not parsed again unless ``force`` is set or the
connector's ``parser_version`` changed, and the upserts leave unchanged
rows untouched, so a rerun over unchanged files creates and updates zero
canonical rows. Transactions: the ``ingest_run`` row is committed first
(so a failed run is recorded), the whole publish — source records,
canonical rows, issues, run statistics — is one transaction, and a
failure rolls it back and records ``failed`` with the reason. The caller
opens the session with the ingest role (the CLI does).
"""

from __future__ import annotations

import asyncio
import dataclasses
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import (
    Base,
    DataQualityIssue,
    IngestRun,
    IngestRunStatus,
    IssueSeverity,
    IssueStatus,
    JurisdictionType,
    Source,
    SourceRecord,
)
from judgemetrics.ingest.base import (
    HEADER_CONTENT_TYPE,
    HEADER_ETAG,
    HEADER_FINAL_URL,
    HEADER_LAST_MODIFIED,
    PREVIOUS_ETAG,
    PREVIOUS_LAST_MODIFIED,
    PREVIOUS_SHA256,
    CanonicalRecord,
    Checkpoint,
    CourtDraft,
    IngestError,
    JudgeDraft,
    JudgeServiceDraft,
    JurisdictionDraft,
    NaturalKey,
    Provenance,
    RawArtifact,
    SourceArtifact,
    SourceConnector,
    SupportsCheckpoint,
    TaggedRecord,
    sha256_hex,
    utc_now,
)
from judgemetrics.ingest.http import parse_http_date
from judgemetrics.ingest.registry import get_connector
from judgemetrics.ingest.store import RawObjectStore, object_key
from judgemetrics.logging import get_logger
from judgemetrics.quality.checks import IssueDraft, run_checks

log = get_logger(__name__)

SYNTHETIC_SOURCE_TYPE = "synthetic"
MAX_REASON_LENGTH = 2000
NORMALIZE_FAILED = "normalize_failed"
UNRESOLVED_JUDGE = "unresolved_judge"
UNRESOLVED_COURT = "unresolved_court"
UNRESOLVED_JURISDICTION = "unresolved_jurisdiction"
JUDGE_IDENTITY_SYSTEMS = frozenset({"fjc_nid"})

_EXTENSION = re.compile(r"[^a-z0-9.]")
_INSERTED = sa.literal_column("(xmax = 0)", type_=sa.Boolean).label("inserted")

JURISDICTION = Base.metadata.tables["jurisdiction"]
COURT = Base.metadata.tables["court"]
JUDGE = Base.metadata.tables["judge"]
JUDGE_SERVICE = Base.metadata.tables["judge_service"]


class IngestFailed(IngestError):
    """The run cannot continue; recorded as ``failed`` with this message."""


@dataclass(slots=True)
class RunCounts:
    seen: int = 0
    created: int = 0
    updated: int = 0
    rejected: int = 0


@dataclass(slots=True)
class _ArtifactState:
    artifact: SourceArtifact
    raw: RawArtifact
    record: SourceRecord
    reparse: bool


@dataclass(slots=True)
class _Resolved:
    jurisdictions: list[TaggedRecord] = field(default_factory=list)
    courts: list[TaggedRecord] = field(default_factory=list)
    judges: list[TaggedRecord] = field(default_factory=list)
    services: list[TaggedRecord] = field(default_factory=list)
    rejections: list[IssueDraft] = field(default_factory=list)
    # Entities referenced by the run's drafts that already exist in the database.
    db_jurisdictions: dict[NaturalKey, uuid.UUID] = field(default_factory=dict)
    db_courts: dict[NaturalKey, uuid.UUID] = field(default_factory=dict)
    db_judges: dict[NaturalKey, uuid.UUID] = field(default_factory=dict)

    def all_tagged(self) -> list[TaggedRecord]:
        return [*self.jurisdictions, *self.courts, *self.judges, *self.services]


@dataclass(frozen=True, slots=True)
class PublishedIds:
    """Entity ids by entity type and natural key after the publish step."""

    ids: dict[str, dict[NaturalKey, uuid.UUID]]

    def get(self, entity_type: str, key: NaturalKey | None) -> uuid.UUID | None:
        if key is None:
            return None
        return self.ids.get(entity_type, {}).get(key)


def run_ingest(
    source_id: str,
    *,
    session: Session,
    store: RawObjectStore,
    settings: Settings,
    from_fixture: Path | None = None,
    force: bool = False,
) -> IngestRun:
    """Run the pipeline for ``source_id`` and return its ``IngestRun`` row.

    ``from_fixture`` reads each discovered artifact from ``<dir>/<external_id>``
    instead of fetching it; ``force`` re-parses artifacts whose hash is
    already recorded. The returned run is committed with its final status.
    """
    connector = get_connector(source_id)
    source = _upsert_source(session, connector)
    run = IngestRun(
        source_id=source.id,
        started_at=utc_now(),
        status=IngestRunStatus.RUNNING,
        code_version=settings.resolved_git_sha(),
        parser_version=connector.parser_version,
    )
    session.add(run)
    session.commit()
    bound = log.bind(source=source_id, run_id=str(run.id), force=force, fixture=bool(from_fixture))

    refusal = _refusal_reason(connector, settings, from_fixture)
    if refusal is not None:
        _finish(session, run, IngestRunStatus.REFUSED, reason=refusal)
        bound.warning("ingest.refused", reason=refusal)
        return run

    bound.info(
        "ingest.started", parser_version=connector.parser_version, code_version=run.code_version
    )
    try:
        counts, checkpoint = _execute(
            connector,
            source,
            run,
            session=session,
            store=store,
            from_fixture=from_fixture,
            force=force,
            bound=bound,
        )
    except Exception as exc:
        session.rollback()
        reason = f"{type(exc).__name__}: {exc}"[:MAX_REASON_LENGTH]
        _finish(session, run, IngestRunStatus.FAILED, reason=reason)
        bound.error("ingest.failed", error_type=type(exc).__name__, reason=reason, exc_info=True)
        return run

    run.records_seen = counts.seen
    run.records_created = counts.created
    run.records_updated = counts.updated
    run.records_rejected = counts.rejected
    run.checkpoint = checkpoint
    _finish(session, run, IngestRunStatus.SUCCEEDED)
    bound.info(
        "ingest.succeeded",
        seen=counts.seen,
        created=counts.created,
        updated=counts.updated,
        rejected=counts.rejected,
    )
    return run


def recompute_metrics(session: Session, run: IngestRun) -> None:
    """Step 13 hook. Phase 3 recomputes the observations affected by ``run`` here."""
    del session, run


# --- run bookkeeping -----------------------------------------------------------


def _refusal_reason(
    connector: SourceConnector, settings: Settings, from_fixture: Path | None
) -> str | None:
    if settings.env != "production":
        return None
    if connector.source_info.source_type == SYNTHETIC_SOURCE_TYPE:
        return "synthetic sources are refused in production"
    if from_fixture is not None:
        return "fixture ingests are refused in production"
    return None


def _finish(
    session: Session, run: IngestRun, status: IngestRunStatus, *, reason: str | None = None
) -> None:
    run.status = status
    run.failure_reason = reason
    run.completed_at = utc_now()
    session.add(run)
    session.commit()


def _upsert_source(session: Session, connector: SourceConnector) -> Source:
    """The ``source`` row for the connector, created or brought up to date by name."""
    info = connector.source_info
    source = session.scalar(select(Source).where(Source.name == connector.source_id))
    if source is None:
        source = Source(
            name=connector.source_id,
            owner=info.owner,
            source_type=info.source_type,
            access_method=info.access_method,
            terms_metadata=dict(info.terms_metadata),
        )
        session.add(source)
    else:
        source.owner = info.owner
        source.source_type = info.source_type
        source.access_method = info.access_method
        if source.terms_metadata != dict(info.terms_metadata):
            source.terms_metadata = dict(info.terms_metadata)
    session.flush()
    return source


def _last_checkpoint(session: Session, source_id: uuid.UUID) -> Checkpoint | None:
    stmt = (
        select(IngestRun.checkpoint)
        .where(
            IngestRun.source_id == source_id,
            IngestRun.status == IngestRunStatus.SUCCEEDED,
            IngestRun.checkpoint.is_not(None),
        )
        .order_by(IngestRun.started_at.desc())
        .limit(1)
    )
    return session.scalar(stmt)


# --- the pipeline ----------------------------------------------------------------


def _execute(
    connector: SourceConnector,
    source: Source,
    run: IngestRun,
    *,
    session: Session,
    store: RawObjectStore,
    from_fixture: Path | None,
    force: bool,
    bound: Any,
) -> tuple[RunCounts, Checkpoint | None]:
    if isinstance(connector, SupportsCheckpoint):
        connector.restore_checkpoint(_last_checkpoint(session, source.id))

    artifacts = asyncio.run(connector.discover())  # step 1
    if not artifacts:
        msg = "the connector discovered no artifacts"
        raise IngestFailed(msg)
    states = [
        _retrieve(
            connector,
            source,
            run,
            artifact,
            session=session,
            store=store,
            from_fixture=from_fixture,
            force=force,
            bound=bound,
        )
        for artifact in artifacts
    ]

    counts = RunCounts()
    tagged: list[TaggedRecord] = []
    issues: list[IssueDraft] = []
    for state in states:
        if not state.reparse:
            continue
        validation = connector.validate_raw(state.raw)  # step 7
        for warning in validation.warnings:
            bound.warning(
                "ingest.validation.warning", external_id=state.artifact.external_id, detail=warning
            )
        if not validation.ok:
            msg = "validation failed: " + "; ".join(validation.errors)
            raise IngestFailed(msg)
        provenance = Provenance(
            source_record_id=state.record.id, raw_sha256=state.record.raw_sha256
        )
        rows = 0
        for row in connector.parse(state.raw):  # step 6
            rows += 1
            counts.seen += 1
            try:
                drafts = list(connector.normalize(row))  # step 8
            except IngestError as exc:
                counts.rejected += 1
                issues.append(
                    IssueDraft(
                        entity_type=row.record_type or "source_record",
                        entity_key=None,
                        severity=IssueSeverity.ERROR,
                        issue_code=NORMALIZE_FAILED,
                        description=str(exc)[:MAX_REASON_LENGTH],
                        source_record_id=state.record.id,
                    )
                )
                continue
            tagged.extend(TaggedRecord(record=draft, provenance=provenance) for draft in drafts)
        bound.info("ingest.artifact.parsed", external_id=state.artifact.external_id, rows=rows)

    deduplicated = _deduplicate(tagged, bound)  # step 9
    resolved = _resolve(session, deduplicated)  # step 10
    counts.rejected += len(resolved.rejections)
    issues.extend(resolved.rejections)
    issues.extend(run_checks(resolved.all_tagged()))  # step 11
    published = _publish(session, resolved, counts, bound)  # step 12
    recompute_metrics(session, run)  # step 13
    _persist_issues(session, issues, published, bound)  # step 14 (lineage)
    checkpoint = connector.checkpoint() if isinstance(connector, SupportsCheckpoint) else None
    return counts, checkpoint


# --- steps 2–5: retrieve, hash, store, record ------------------------------------


def _retrieve(
    connector: SourceConnector,
    source: Source,
    run: IngestRun,
    artifact: SourceArtifact,
    *,
    session: Session,
    store: RawObjectStore,
    from_fixture: Path | None,
    force: bool,
    bound: Any,
) -> _ArtifactState:
    previous = _latest_record(session, source.id, artifact.external_id)
    enriched = _with_validators(artifact, previous)
    if from_fixture is not None:
        raw = _read_fixture(enriched, from_fixture)
    else:
        raw = asyncio.run(connector.fetch(enriched))  # step 2

    data: bytes | None
    if raw.not_modified:
        if previous is None or previous.raw_sha256 != raw.sha256:
            msg = (
                f"{artifact.external_id}: not modified per the server, but no prior record matches"
            )
            raise IngestFailed(msg)
        data = None
        digest = previous.raw_sha256
        existing: SourceRecord | None = previous
    else:
        data = raw.read_bytes()
        digest = sha256_hex(data)  # step 3, re-verified
        if digest != raw.sha256:
            msg = f"{artifact.external_id}: connector sha256 does not match the payload"
            raise IngestFailed(msg)
        existing = _find_record(session, source.id, artifact.external_id, digest)

    if existing is not None:
        if data is not None and not store.exists(existing.raw_object_path):
            store.put(data, existing.raw_object_path)
        reparse = force or existing.parser_version != connector.parser_version
        if existing.parser_version != connector.parser_version:
            existing.parser_version = connector.parser_version
            session.flush()
        if reparse and raw.not_modified:
            # The server confirmed the bytes are unchanged: re-parse them from the lake.
            stored = store.get(existing.raw_object_path)
            if sha256_hex(stored) != existing.raw_sha256:
                msg = f"{artifact.external_id}: stored raw object does not match its record"
                raise IngestFailed(msg)
            raw = dataclasses.replace(
                raw, path_or_bytes=stored, size_bytes=len(stored), not_modified=False
            )
        bound.info(
            "ingest.artifact.unchanged",
            external_id=artifact.external_id,
            sha256=digest,
            reparse=reparse,
            not_modified=raw.not_modified,
        )
        return _ArtifactState(artifact=enriched, raw=raw, record=existing, reparse=reparse)

    if data is None:  # pragma: no cover - guarded above
        msg = f"{artifact.external_id}: no payload to store"
        raise IngestFailed(msg)
    key = object_key(
        connector.source_id, raw.retrieved_at, digest, _extension(artifact.external_id)
    )
    ref = store.put(data, key)  # step 4
    record = SourceRecord(
        source_id=source.id,
        external_record_id=artifact.external_id,
        retrieved_at=raw.retrieved_at,
        effective_at=parse_http_date(raw.response_headers.get(HEADER_LAST_MODIFIED)),
        raw_object_path=ref.key,
        raw_sha256=digest,
        parser_version=connector.parser_version,
        ingest_run_id=run.id,
        metadata_=_record_metadata(artifact, raw),
    )
    session.add(record)  # step 5
    session.flush()
    bound.info(
        "ingest.artifact.stored",
        external_id=artifact.external_id,
        sha256=digest,
        size_bytes=ref.size_bytes,
        key=ref.key,
    )
    return _ArtifactState(artifact=enriched, raw=raw, record=record, reparse=True)


def _latest_record(session: Session, source_id: uuid.UUID, external_id: str) -> SourceRecord | None:
    stmt = (
        select(SourceRecord)
        .where(SourceRecord.source_id == source_id, SourceRecord.external_record_id == external_id)
        .order_by(SourceRecord.retrieved_at.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def _find_record(
    session: Session, source_id: uuid.UUID, external_id: str, sha256: str
) -> SourceRecord | None:
    stmt = select(SourceRecord).where(
        SourceRecord.source_id == source_id,
        SourceRecord.external_record_id == external_id,
        SourceRecord.raw_sha256 == sha256,
    )
    return session.scalar(stmt)


def _with_validators(artifact: SourceArtifact, previous: SourceRecord | None) -> SourceArtifact:
    if previous is None:
        return artifact
    extra = {PREVIOUS_SHA256: previous.raw_sha256}
    for header, key in (
        (HEADER_ETAG, PREVIOUS_ETAG),
        (HEADER_LAST_MODIFIED, PREVIOUS_LAST_MODIFIED),
    ):
        value = previous.metadata_.get(header)
        if isinstance(value, str) and value:
            extra[key] = value
    return artifact.with_metadata(**extra)


def _read_fixture(artifact: SourceArtifact, directory: Path) -> RawArtifact:
    name = artifact.external_id
    if not name or Path(name).name != name or name in {".", ".."}:
        msg = f"fixture artifact id is not a plain file name: {name!r}"
        raise IngestFailed(msg)
    path = directory / name
    if not path.is_file():
        msg = f"fixture file missing: {path}"
        raise IngestFailed(msg)
    return RawArtifact.from_path(
        artifact,
        path,
        retrieved_at=utc_now(),
        response_headers={
            HEADER_CONTENT_TYPE: artifact.content_type,
            HEADER_FINAL_URL: path.resolve().as_uri(),
        },
    )


def _record_metadata(artifact: SourceArtifact, raw: RawArtifact) -> dict[str, Any]:
    metadata: dict[str, Any] = {"uri": artifact.uri}
    metadata.update(
        {key: value for key, value in artifact.metadata.items() if not key.startswith("previous_")}
    )
    metadata.update(raw.response_headers)
    return metadata


def _extension(external_id: str) -> str:
    suffixes = "".join(Path(external_id).suffixes).lower()
    return _EXTENSION.sub("", suffixes)


# --- steps 9–10: deduplicate, resolve ---------------------------------------------


def _deduplicate(tagged: Iterable[TaggedRecord], bound: Any) -> list[TaggedRecord]:
    kept: dict[NaturalKey, TaggedRecord] = {}
    dropped = 0
    conflicting = 0
    for item in tagged:
        key = item.record.natural_key
        first = kept.get(key)
        if first is None:
            kept[key] = item
            continue
        dropped += 1
        if first.record != item.record:
            conflicting += 1
    if dropped:
        bound.info("ingest.deduplicated", dropped=dropped, conflicting=conflicting)
    return list(kept.values())


def _resolve(session: Session, tagged: Sequence[TaggedRecord]) -> _Resolved:
    resolved = _Resolved()
    services: list[TaggedRecord] = []
    courts: list[TaggedRecord] = []
    for item in tagged:
        record = item.record
        if isinstance(record, JurisdictionDraft):
            resolved.jurisdictions.append(item)
        elif isinstance(record, CourtDraft):
            courts.append(item)
        elif isinstance(record, JudgeDraft):
            resolved.judges.append(item)
        else:
            services.append(item)

    jurisdiction_keys = {item.record.natural_key for item in resolved.jurisdictions}
    court_keys = {item.record.natural_key for item in courts}
    judge_keys = {item.record.natural_key for item in resolved.judges}

    wanted_jurisdictions = {
        item.record.jurisdiction_key
        for item in courts
        if isinstance(item.record, CourtDraft)
        and item.record.jurisdiction_key not in jurisdiction_keys
    }
    resolved.db_jurisdictions = _lookup_jurisdictions(session, wanted_jurisdictions)
    for item in courts:
        court = _record_as(CourtDraft, item)
        if (
            court.jurisdiction_key in jurisdiction_keys
            or court.jurisdiction_key in resolved.db_jurisdictions
        ):
            resolved.courts.append(item)
        else:
            resolved.rejections.append(
                _rejection(
                    item, UNRESOLVED_JURISDICTION, f"unknown jurisdiction {court.jurisdiction_key}"
                )
            )
    court_keys = {item.record.natural_key for item in resolved.courts}

    wanted_courts = {
        item.record.court_key
        for item in services
        if isinstance(item.record, JudgeServiceDraft) and item.record.court_key not in court_keys
    }
    wanted_judges = {
        item.record.judge_key
        for item in services
        if isinstance(item.record, JudgeServiceDraft) and item.record.judge_key not in judge_keys
    }
    resolved.db_courts = _lookup_courts(session, wanted_courts)
    resolved.db_judges = _lookup_judges(session, wanted_judges)
    for item in services:
        service = _record_as(JudgeServiceDraft, item)
        if service.judge_key not in judge_keys and service.judge_key not in resolved.db_judges:
            resolved.rejections.append(
                _rejection(
                    item, UNRESOLVED_JUDGE, f"unknown judge {':'.join(service.judge_key[1:])}"
                )
            )
        elif service.court_key not in court_keys and service.court_key not in resolved.db_courts:
            resolved.rejections.append(
                _rejection(item, UNRESOLVED_COURT, f"unknown court {service.court_key[1:]}")
            )
        else:
            resolved.services.append(item)
    return resolved


def _record_as[R: CanonicalRecord](kind: type[R], item: TaggedRecord) -> R:
    """The draft of ``item`` as ``kind``; the runner partitions drafts by type first."""
    if not isinstance(item.record, kind):
        msg = f"expected a {kind.__name__}, got {type(item.record).__name__}"
        raise IngestFailed(msg)
    return item.record


def _rejection(item: TaggedRecord, code: str, detail: str) -> IssueDraft:
    key = item.record.natural_key
    return IssueDraft(
        entity_type=key[0],
        entity_key=key,
        severity=IssueSeverity.ERROR,
        issue_code=code,
        description=f"{key[0]} {':'.join(key[1:])}: {detail}",
        source_record_id=item.provenance.source_record_id if item.provenance else None,
    )


def _enum_value(value: object) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _lookup_jurisdictions(
    session: Session, keys: Iterable[NaturalKey]
) -> dict[NaturalKey, uuid.UUID]:
    wanted = set(keys)
    names = {key[1] for key in wanted if len(key) == 3}
    if not names:
        return {}
    rows = session.execute(
        select(JURISDICTION.c.id, JURISDICTION.c.name, JURISDICTION.c.type).where(
            JURISDICTION.c.name.in_(names)
        )
    ).all()
    found: dict[NaturalKey, uuid.UUID] = {}
    for row_id, name, kind in rows:
        key = ("jurisdiction", name, _enum_value(kind))
        if key in wanted:
            found[key] = row_id
    return found


def _lookup_courts(session: Session, keys: Iterable[NaturalKey]) -> dict[NaturalKey, uuid.UUID]:
    wanted = set(keys)
    names = {key[1] for key in wanted if len(key) == 3}
    if not names:
        return {}
    rows = session.execute(
        select(COURT.c.id, COURT.c.canonical_name, COURT.c.court_type).where(
            COURT.c.canonical_name.in_(names)
        )
    ).all()
    found: dict[NaturalKey, uuid.UUID] = {}
    for row_id, name, court_type in rows:
        key = ("court", name, court_type)
        if key in wanted:
            found[key] = row_id
    return found


def _lookup_judges(session: Session, keys: Iterable[NaturalKey]) -> dict[NaturalKey, uuid.UUID]:
    wanted = set(keys)
    found: dict[NaturalKey, uuid.UUID] = {}
    for system in {key[1] for key in wanted if len(key) == 3}:
        values = {key[2] for key in wanted if key[1] == system}
        rows = session.execute(
            select(JUDGE.c.id, JUDGE.c.external_ids[system].astext).where(
                JUDGE.c.external_ids[system].astext.in_(values)
            )
        ).all()
        for row_id, value in rows:
            key = ("judge", system, str(value))
            if key in wanted:
                found[key] = row_id
    return found


# --- step 12: publish ---------------------------------------------------------------


def _publish(session: Session, resolved: _Resolved, counts: RunCounts, bound: Any) -> PublishedIds:
    jurisdiction_ids = dict(resolved.db_jurisdictions)
    jurisdiction_ids.update(_upsert_jurisdictions(session, resolved.jurisdictions, counts))
    court_ids = dict(resolved.db_courts)
    court_ids.update(_upsert_courts(session, resolved.courts, jurisdiction_ids, counts))
    judge_ids = dict(resolved.db_judges)
    judge_ids.update(_upsert_judges(session, resolved.judges, counts))
    service_ids = _upsert_services(session, resolved.services, judge_ids, court_ids, counts)
    bound.info(
        "ingest.published",
        jurisdictions=len(resolved.jurisdictions),
        courts=len(resolved.courts),
        judges=len(resolved.judges),
        services=len(resolved.services),
        created=counts.created,
        updated=counts.updated,
    )
    return PublishedIds(
        {
            "jurisdiction": jurisdiction_ids,
            "court": court_ids,
            "judge": judge_ids,
            "judge_service": service_ids,
        }
    )


def _provenance_id(item: TaggedRecord) -> uuid.UUID:
    if item.provenance is None:
        msg = f"{item.record.natural_key}: cannot publish a draft without provenance"
        raise IngestFailed(msg)
    return item.provenance.source_record_id


def _count(result: sa.Result[Any], counts: RunCounts) -> None:
    rows = result.all()
    created = sum(1 for row in rows if row.inserted)
    counts.created += created
    counts.updated += len(rows) - created


def _jurisdiction_type(value: str) -> JurisdictionType:
    try:
        return JurisdictionType(value)
    except ValueError as exc:
        msg = f"unknown jurisdiction type {value!r}"
        raise IngestFailed(msg) from exc


def _upsert_jurisdictions(
    session: Session, items: Sequence[TaggedRecord], counts: RunCounts
) -> dict[NaturalKey, uuid.UUID]:
    if not items:
        return {}
    rows: list[dict[str, Any]] = []
    for item in items:
        draft = _record_as(JurisdictionDraft, item)
        rows.append(
            {
                "id": uuid.uuid4(),
                "name": draft.name,
                "type": _jurisdiction_type(draft.type),
                "state_code": draft.state_code,
                "fips_code": draft.fips_code,
                "source_record_id": _provenance_id(item),
            }
        )
    stmt = insert(JURISDICTION).values(rows)
    excluded = stmt.excluded
    upsert = stmt.on_conflict_do_update(
        index_elements=[JURISDICTION.c.name, JURISDICTION.c.type],
        set_={
            "state_code": excluded.state_code,
            "fips_code": excluded.fips_code,
            "source_record_id": excluded.source_record_id,
            "updated_at": sa.func.now(),
        },
        where=sa.or_(
            JURISDICTION.c.state_code.is_distinct_from(excluded.state_code),
            JURISDICTION.c.fips_code.is_distinct_from(excluded.fips_code),
        ),
    ).returning(JURISDICTION.c.id, _INSERTED)
    _count(session.execute(upsert), counts)
    return _lookup_jurisdictions(session, [item.record.natural_key for item in items])


def _upsert_courts(
    session: Session,
    items: Sequence[TaggedRecord],
    jurisdiction_ids: dict[NaturalKey, uuid.UUID],
    counts: RunCounts,
) -> dict[NaturalKey, uuid.UUID]:
    if not items:
        return {}
    rows: list[dict[str, Any]] = []
    for item in items:
        draft = _record_as(CourtDraft, item)
        rows.append(
            {
                "id": uuid.uuid4(),
                "jurisdiction_id": jurisdiction_ids[draft.jurisdiction_key],
                "canonical_name": draft.canonical_name,
                "court_type": draft.court_type,
                "external_ids": dict(draft.external_ids),
                "state_code": draft.state_code,
                "active_from": draft.active_from,
                "active_to": draft.active_to,
                "source_record_id": _provenance_id(item),
            }
        )
    stmt = insert(COURT).values(rows)
    excluded = stmt.excluded
    merged_ids = COURT.c.external_ids.op("||")(excluded.external_ids)
    upsert = stmt.on_conflict_do_update(
        index_elements=[COURT.c.canonical_name, COURT.c.court_type],
        set_={
            "jurisdiction_id": excluded.jurisdiction_id,
            "external_ids": merged_ids,
            "state_code": excluded.state_code,
            "active_from": excluded.active_from,
            "active_to": excluded.active_to,
            "source_record_id": excluded.source_record_id,
            "updated_at": sa.func.now(),
        },
        where=sa.or_(
            COURT.c.jurisdiction_id.is_distinct_from(excluded.jurisdiction_id),
            merged_ids.is_distinct_from(COURT.c.external_ids),
            COURT.c.state_code.is_distinct_from(excluded.state_code),
            COURT.c.active_from.is_distinct_from(excluded.active_from),
            COURT.c.active_to.is_distinct_from(excluded.active_to),
        ),
    ).returning(COURT.c.id, _INSERTED)
    _count(session.execute(upsert), counts)
    return _lookup_courts(session, [item.record.natural_key for item in items])


def _upsert_judges(
    session: Session, items: Sequence[TaggedRecord], counts: RunCounts
) -> dict[NaturalKey, uuid.UUID]:
    if not items:
        return {}
    rows: list[dict[str, Any]] = []
    for item in items:
        draft = _record_as(JudgeDraft, item)
        system, value = draft.identity_key
        if system not in JUDGE_IDENTITY_SYSTEMS:
            msg = f"judge identity system {system!r} has no resolution index yet"
            raise IngestFailed(msg)
        if draft.external_ids.get(system) != value:
            msg = f"judge {value}: identity key is not among its external ids"
            raise IngestFailed(msg)
        rows.append(
            {
                "id": uuid.uuid4(),
                "canonical_name": draft.canonical_name,
                "normalized_name": draft.normalized_name,
                "external_ids": dict(draft.external_ids),
                "status": draft.status,
                "metadata": dict(draft.metadata),
                "source_record_id": _provenance_id(item),
            }
        )
    stmt = insert(JUDGE).values(rows)
    excluded = stmt.excluded
    merged_ids = JUDGE.c.external_ids.op("||")(excluded.external_ids)
    merged_metadata = JUDGE.c.metadata.op("||")(excluded.metadata)
    upsert = stmt.on_conflict_do_update(
        index_elements=[sa.literal_column("(external_ids ->> 'fjc_nid')")],
        index_where=sa.text("external_ids ? 'fjc_nid'"),
        set_={
            "canonical_name": excluded.canonical_name,
            "normalized_name": excluded.normalized_name,
            "external_ids": merged_ids,
            "status": excluded.status,
            "metadata": merged_metadata,
            "source_record_id": excluded.source_record_id,
            "updated_at": sa.func.now(),
        },
        where=sa.or_(
            JUDGE.c.canonical_name.is_distinct_from(excluded.canonical_name),
            JUDGE.c.normalized_name.is_distinct_from(excluded.normalized_name),
            merged_ids.is_distinct_from(JUDGE.c.external_ids),
            JUDGE.c.status.is_distinct_from(excluded.status),
            merged_metadata.is_distinct_from(JUDGE.c.metadata),
        ),
    ).returning(JUDGE.c.id, _INSERTED)
    _count(session.execute(upsert), counts)
    return _lookup_judges(session, [item.record.natural_key for item in items])


def _service_key(
    judge_key: NaturalKey, court_key: NaturalKey, position_type: str, start: date | None
) -> NaturalKey:
    return (
        "judge_service",
        *judge_key[1:],
        *court_key[1:],
        position_type,
        start.isoformat() if start else "",
    )


def _upsert_services(
    session: Session,
    items: Sequence[TaggedRecord],
    judge_ids: dict[NaturalKey, uuid.UUID],
    court_ids: dict[NaturalKey, uuid.UUID],
    counts: RunCounts,
) -> dict[NaturalKey, uuid.UUID]:
    if not items:
        return {}
    rows: list[dict[str, Any]] = []
    for item in items:
        draft = _record_as(JudgeServiceDraft, item)
        rows.append(
            {
                "id": uuid.uuid4(),
                "judge_id": judge_ids[draft.judge_key],
                "court_id": court_ids[draft.court_key],
                "position_type": draft.position_type,
                "start_date": draft.start_date,
                "end_date": draft.end_date,
                "metadata": dict(draft.metadata),
                "source_record_id": _provenance_id(item),
            }
        )
    stmt = insert(JUDGE_SERVICE).values(rows)
    excluded = stmt.excluded
    merged_metadata = JUDGE_SERVICE.c.metadata.op("||")(excluded.metadata)
    upsert = stmt.on_conflict_do_update(
        index_elements=[
            JUDGE_SERVICE.c.judge_id,
            JUDGE_SERVICE.c.court_id,
            JUDGE_SERVICE.c.position_type,
            JUDGE_SERVICE.c.start_date,
        ],
        set_={
            "end_date": excluded.end_date,
            "metadata": merged_metadata,
            "source_record_id": excluded.source_record_id,
            "updated_at": sa.func.now(),
        },
        where=sa.or_(
            JUDGE_SERVICE.c.end_date.is_distinct_from(excluded.end_date),
            merged_metadata.is_distinct_from(JUDGE_SERVICE.c.metadata),
        ),
    ).returning(JUDGE_SERVICE.c.id, _INSERTED)
    _count(session.execute(upsert), counts)

    judge_keys_by_id = {value: key for key, value in judge_ids.items()}
    court_keys_by_id = {value: key for key, value in court_ids.items()}
    involved = {row["judge_id"] for row in rows}
    lookup = session.execute(
        select(
            JUDGE_SERVICE.c.id,
            JUDGE_SERVICE.c.judge_id,
            JUDGE_SERVICE.c.court_id,
            JUDGE_SERVICE.c.position_type,
            JUDGE_SERVICE.c.start_date,
        ).where(JUDGE_SERVICE.c.judge_id.in_(involved))
    ).all()
    wanted = {item.record.natural_key for item in items}
    found: dict[NaturalKey, uuid.UUID] = {}
    for row_id, judge_id, court_id, position_type, start in lookup:
        judge_key = judge_keys_by_id.get(judge_id)
        court_key = court_keys_by_id.get(court_id)
        if judge_key is None or court_key is None:
            continue
        key = _service_key(judge_key, court_key, position_type, start)
        if key in wanted:
            found[key] = row_id
    return found


# --- step 14: lineage ---------------------------------------------------------------


def _persist_issues(
    session: Session, issues: Sequence[IssueDraft], published: PublishedIds, bound: Any
) -> None:
    if not issues:
        return
    record_ids = {issue.source_record_id for issue in issues if issue.source_record_id is not None}
    existing: set[tuple[Any, ...]] = set()
    if record_ids:
        rows = session.execute(
            select(
                DataQualityIssue.source_record_id,
                DataQualityIssue.entity_type,
                DataQualityIssue.entity_id,
                DataQualityIssue.issue_code,
                DataQualityIssue.description,
            ).where(DataQualityIssue.source_record_id.in_(record_ids))
        ).all()
        existing = {tuple(row) for row in rows}
    created = 0
    by_severity: dict[str, int] = {}
    for issue in issues:
        entity_id = published.get(issue.entity_type, issue.entity_key)
        signature = (
            issue.source_record_id,
            issue.entity_type,
            entity_id,
            issue.issue_code,
            issue.description,
        )
        by_severity[issue.severity.value] = by_severity.get(issue.severity.value, 0) + 1
        if signature in existing:
            continue
        existing.add(signature)
        session.add(
            DataQualityIssue(
                source_record_id=issue.source_record_id,
                entity_type=issue.entity_type,
                entity_id=entity_id,
                severity=issue.severity,
                issue_code=issue.issue_code,
                description=issue.description,
                status=IssueStatus.OPEN,
            )
        )
        created += 1
    session.flush()
    bound.info("ingest.quality_issues", found=len(issues), created=created, by_severity=by_severity)
