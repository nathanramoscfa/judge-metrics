# src/judgemetrics/metrics/snapshot.py
"""Snapshots: the hashed Parquet export every observation is computed from.

``export_snapshot(session, settings, label=None)`` reads the canonical
tables a metric reads — ``court_case`` (with its source through
``source_record``), ``judge_assignment``, ``charge``, ``decision`` joined
to ``pretrial_release``, ``sentence``, ``court_event``, ``justice_event``,
``person`` (id and ``merged_into_person_id`` only), ``judge`` (id),
``court`` (id, jurisdiction), and ``source`` (id, name, type, coverage,
observable outcomes) — through SQLAlchemy Core into Polars and writes one
Parquet file per table plus ``manifest.json`` (table → sha256 and row
count) under ``<snapshot_dir>/<content_hash>/``, where ``content_hash``
is the sha256 over the sorted ``<table>:<sha256>`` lines. The directory
is created with ``mkdir(exist_ok=False)`` and never overwritten: an
export whose hash already exists reuses the directory. No restricted
table is read (``person_identifier``, ``audit_log``,
``entity_resolution_candidate``, ``correction_request``), no table of the
``restricted`` schema is ever exported — ``refuse_restricted`` checks every
table the export reads by its schema, through ``RESTRICTED_SCHEMA`` from
``judgemetrics.db.models``, so this module never names one — the persons
file holds ids only, and every id is the canonical UUID rendered as text
(Polars has no UUID type; the frame is generic over the id dtype).

Every timestamp is stored as a naive UTC ``Datetime("us")`` — DuckDB
hands a timezone-aware timestamp back to Python only through ``pytz``,
which is not a dependency — and the loader re-attaches ``UTC``. Rows are
ordered by id, so the same data always yields the same bytes and the
same hash (Polars writes Parquet deterministically; a unit test asserts
it). Day-level facts are placed on their day the way the frame documents:
``filed_at`` at 00:00 UTC and ``closed_at`` at the last microsecond.

``open_snapshot(settings, content_hash)`` validates the hash as
64 hexadecimal characters before it becomes a path, checks every file
against the manifest, and registers each Parquet file as a view of an
in-memory DuckDB database through the relation API (``read_parquet`` over
a path this module built; the view names are the fixed table names; no
DuckDB extension is installed or loaded — the bundled Parquet reader is
part of the wheel). ``Snapshot.frame(source_id)`` runs parameterized
queries against those views and builds the Step 1 ``Frame`` for one
source: the cases of the source's records and their child rows, the
courts of those cases with their jurisdictions (Phase 4 Step 2), the
resolved persons those rows name (merge chains followed), the stored
justice events of those persons for the any-case outcomes
(``failure_to_appear``, ``release_violation``, ``revocation``,
``rearrest``), and the other-case outcomes derived here from the merged
person's cases and charges exactly as the truth's ``outcomes_of`` does —
``new_case`` at the earliest charge filing of each case (the case row
carries a date only), ``new_charge`` at every charge filing,
``reconviction`` at every convicted charge's disposition, each keyed by
its own case — because the synthetic connector derives ``new_case`` and
``reconviction`` per participant id before the rule stage merges the
planted split persons and never derives ``new_charge`` (docs/ARCHITECTURE.md
"Metrics engine"). Derived rows carry ids of the form
``derived:<type>:<case id>:<instant>`` and are never observation members.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self

import duckdb
import polars as pl
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics import __version__
from judgemetrics.capabilities import CapabilityError, SourceCapabilities
from judgemetrics.config import Settings
from judgemetrics.db.models import RESTRICTED_SCHEMA, Base
from judgemetrics.logging import get_logger
from judgemetrics.metrics.frame import SCHEMAS, Frame
from judgemetrics.metrics.windows import ANY_CASE_OUTCOMES

log = get_logger(__name__)

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UNKNOWN_GIT_SHA = "unknown"
SHORT_SHA_LENGTH = 7
DERIVED_PREFIX = "derived"
CONVICTED_DISPOSITIONS: frozenset[str] = frozenset({"convicted_plea", "convicted_verdict"})
NEW_CASE = "new_case"
NEW_CHARGE = "new_charge"
RECONVICTION = "reconviction"
# Rows per batch the export reads from the server-side cursor.
EXPORT_BATCH_ROWS = 100_000

NAIVE_US = pl.Datetime("us")
STRING = pl.String()
# The Parquet schema of every exported table (naive UTC timestamps, ids as text).
PARQUET_SCHEMAS: Mapping[str, Mapping[str, pl.DataType]] = MappingProxyType(
    {
        "cases": MappingProxyType(
            {
                "id": STRING,
                "court_id": STRING,
                "source_id": STRING,
                "filed_at": NAIVE_US,
                "closed_at": NAIVE_US,
                "status": STRING,
                "case_type": STRING,
            }
        ),
        "assignments": MappingProxyType(
            {
                "id": STRING,
                "case_id": STRING,
                "judge_id": STRING,
                "start_at": NAIVE_US,
                "end_at": NAIVE_US,
            }
        ),
        "charges": MappingProxyType(
            {
                "id": STRING,
                "case_id": STRING,
                "person_id": STRING,
                "filed_at": NAIVE_US,
                "disposed_at": NAIVE_US,
                "disposition": STRING,
                "disposition_actor": STRING,
                "offense_category": STRING,
                "severity": STRING,
                "source_row_id": STRING,
                "judge_id": STRING,
            }
        ),
        "decisions": MappingProxyType(
            {
                "id": STRING,
                "case_id": STRING,
                "person_id": STRING,
                "judge_id": STRING,
                "decision_type": STRING,
                "decision_at": NAIVE_US,
                "actor_type": STRING,
                "discretion": STRING,
                "release_at": NAIVE_US,
                "detained_flag": pl.Boolean(),
                "release_type": STRING,
            }
        ),
        "sentences": MappingProxyType(
            {
                "id": STRING,
                "case_id": STRING,
                "person_id": STRING,
                "judge_id": STRING,
                "sentence_at": NAIVE_US,
                "incarceration_days": pl.Int64(),
                "probation_days": pl.Int64(),
                "replaced": pl.Boolean(),
            }
        ),
        "events": MappingProxyType(
            {
                "id": STRING,
                "case_id": STRING,
                "person_id": STRING,
                "judge_id": STRING,
                "event_type": STRING,
                "event_at": NAIVE_US,
            }
        ),
        "justice_events": MappingProxyType(
            {
                "id": STRING,
                "person_id": STRING,
                "event_type": STRING,
                "event_at": NAIVE_US,
                "related_case_id": STRING,
            }
        ),
        "persons": MappingProxyType({"id": STRING, "merged_into_person_id": STRING}),
        "judges": MappingProxyType({"id": STRING}),
        "courts": MappingProxyType({"id": STRING, "jurisdiction_id": STRING}),
        "sources": MappingProxyType(
            {
                "id": STRING,
                "name": STRING,
                "source_type": STRING,
                "coverage_start": pl.Date(),
                "coverage_end": pl.Date(),
                "observable_outcomes": pl.List(pl.String()),
                "judge_gates": pl.List(pl.String()),
                "person_key_scope": STRING,
                "revocation_scopes": pl.List(pl.String()),
            }
        ),
    }
)
# sentence.sentence_components key a connector sets on a sentence a later correction
# replaced (Phase 5 Step 5): the frame drops it, so each sentencing decision counts once.
REPLACED_KEY = "replaced"
SNAPSHOT_TABLES: tuple[str, ...] = tuple(PARQUET_SCHEMAS)
# metric_observation_member.member_kind → the snapshot table that holds the id.
MEMBER_TABLES: Mapping[str, str] = MappingProxyType(
    {
        "decision": "decisions",
        "charge": "charges",
        "court_case": "cases",
        "sentence": "sentences",
        "court_event": "events",
        "justice_event": "justice_events",
    }
)
# The tables that must never be exported (a unit test greps this module for them too).
RESTRICTED_TABLES: tuple[str, ...] = (
    "person_identifier",
    "audit_log",
    "entity_resolution_candidate",
    "correction_request",
)

COURT_CASE = Base.metadata.tables["court_case"]
JUDGE_ASSIGNMENT = Base.metadata.tables["judge_assignment"]
CHARGE = Base.metadata.tables["charge"]
DECISION = Base.metadata.tables["decision"]
PRETRIAL_RELEASE = Base.metadata.tables["pretrial_release"]
SENTENCE = Base.metadata.tables["sentence"]
COURT_EVENT = Base.metadata.tables["court_event"]
JUSTICE_EVENT = Base.metadata.tables["justice_event"]
PERSON = Base.metadata.tables["person"]
JUDGE = Base.metadata.tables["judge"]
COURT = Base.metadata.tables["court"]
SOURCE = Base.metadata.tables["source"]
SOURCE_RECORD = Base.metadata.tables["source_record"]
# Every table ``_export_rows`` reads: ``refuse_restricted`` checks them all.
EXPORTED_TABLES: tuple[sa.Table, ...] = (
    COURT_CASE,
    JUDGE_ASSIGNMENT,
    CHARGE,
    DECISION,
    PRETRIAL_RELEASE,
    SENTENCE,
    COURT_EVENT,
    JUSTICE_EVENT,
    PERSON,
    JUDGE,
    COURT,
    SOURCE,
    SOURCE_RECORD,
)


class SnapshotError(RuntimeError):
    """A snapshot cannot be written, found, or read consistently."""


@dataclass(frozen=True, slots=True)
class TableDigest:
    sha256: str
    rows: int


@dataclass(frozen=True, slots=True)
class SourceRow:
    """One row of the ``sources`` table of a snapshot."""

    id: str
    name: str
    source_type: str
    coverage_start: date | None
    coverage_end: date | None
    observable_outcomes: frozenset[str]
    capabilities: SourceCapabilities = SourceCapabilities()

    @property
    def has_coverage(self) -> bool:
        return self.coverage_start is not None and self.coverage_end is not None


@dataclass(frozen=True, slots=True)
class SnapshotRef:
    """Where a snapshot lives and what it holds (the ``metric_snapshot`` row's facts)."""

    content_hash: str
    directory: Path
    exported_at: datetime
    code_version: str
    tables: Mapping[str, TableDigest]
    coverage: Mapping[str, Mapping[str, Any]]
    reused: bool = False

    @property
    def row_counts(self) -> dict[str, int]:
        return {name: digest.rows for name, digest in self.tables.items()}

    @property
    def storage_uri(self) -> str:
        return self.directory.as_uri()

    def manifest_json(self) -> dict[str, Any]:
        return {
            "manifest_version": MANIFEST_VERSION,
            "content_hash": self.content_hash,
            "exported_at": self.exported_at.isoformat(),
            "code_version": self.code_version,
            "tables": {
                name: {"file": f"{name}.parquet", "sha256": d.sha256, "rows": d.rows}
                for name, d in sorted(self.tables.items())
            },
            "coverage": {key: dict(value) for key, value in sorted(self.coverage.items())},
        }


# --- helpers ------------------------------------------------------------------------------


def code_version(settings: Settings) -> str:
    """The package version plus the short git SHA when it is known (``0.1.0+abc1234``)."""
    sha = settings.resolved_git_sha()
    if sha == UNKNOWN_GIT_SHA:
        return __version__
    return f"{__version__}+{sha[:SHORT_SHA_LENGTH]}"


def validate_content_hash(value: str) -> str:
    """``value`` when it is 64 lowercase hexadecimal characters; ``SnapshotError`` otherwise."""
    if not isinstance(value, str) or not HEX64.match(value):
        msg = "a snapshot id is a 64-character lowercase hexadecimal sha256"
        raise SnapshotError(msg)
    return value


def content_hash_of(tables: Mapping[str, TableDigest]) -> str:
    """sha256 over the sorted ``<table>:<sha256>`` lines."""
    lines = "".join(f"{name}:{tables[name].sha256}\n" for name in sorted(tables))
    return hashlib.sha256(lines.encode("ascii")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _batch_frame(name: str, rows: Sequence[Sequence[Any]]) -> pl.DataFrame:
    """One batch of a table's rows as a frame with the Parquet schema (the row-orient path)."""
    return pl.DataFrame(
        [tuple(row) for row in rows], schema=dict(PARQUET_SCHEMAS[name]), orient="row"
    )


# --- export ------------------------------------------------------------------------------


def _text_of(column: sa.ColumnElement[Any]) -> sa.ColumnElement[str]:
    """The column rendered as text in the database (a UUID or an enum as ``str(value)``)."""
    return sa.cast(column, sa.Text)


def _utc(column: sa.ColumnElement[Any]) -> sa.ColumnElement[datetime]:
    """A ``timestamptz`` as a naive UTC ``timestamp`` (``datetime.astimezone(UTC)`` without a zone)."""
    return sa.func.timezone("UTC", column)


# ``date`` + this interval is the day's last microsecond, the way ``time.max`` places ``closed_at``.
END_OF_DAY: sa.ColumnElement[Any] = sa.literal_column("INTERVAL '23:59:59.999999'")


def export_statements() -> dict[str, sa.Select[Any]]:
    """Every snapshot table's query, in ``SNAPSHOT_TABLES`` order: ids as text, times as naive UTC.

    The database does the conversions the Python export used to do cell by cell
    (``cast`` to text, ``timezone('UTC', …)``, a date placed at its day's start or last
    microsecond), so a batch reaches Polars as the very values the Parquet file holds.
    Every statement is ordered by the table's own ``id`` (the uuid, not its text, which
    sorts the same way), so the same data always yields the same rows in the same order.
    """
    return {
        "cases": select(
            _text_of(COURT_CASE.c.id),
            _text_of(COURT_CASE.c.court_id),
            _text_of(SOURCE_RECORD.c.source_id),
            sa.cast(COURT_CASE.c.filed_date, sa.DateTime),
            sa.cast(COURT_CASE.c.closed_date, sa.DateTime) + END_OF_DAY,
            _text_of(COURT_CASE.c.status),
            _text_of(COURT_CASE.c.case_type),
        )
        .join(SOURCE_RECORD, SOURCE_RECORD.c.id == COURT_CASE.c.source_record_id)
        .order_by(COURT_CASE.c.id),
        "assignments": select(
            _text_of(JUDGE_ASSIGNMENT.c.id),
            _text_of(JUDGE_ASSIGNMENT.c.case_id),
            _text_of(JUDGE_ASSIGNMENT.c.judge_id),
            _utc(JUDGE_ASSIGNMENT.c.start_at),
            _utc(JUDGE_ASSIGNMENT.c.end_at),
        ).order_by(JUDGE_ASSIGNMENT.c.id),
        "charges": select(
            _text_of(CHARGE.c.id),
            _text_of(CHARGE.c.case_id),
            _text_of(CHARGE.c.person_id),
            _utc(CHARGE.c.filed_at),
            _utc(CHARGE.c.disposed_at),
            _text_of(CHARGE.c.disposition),
            _text_of(CHARGE.c.disposition_actor),
            _text_of(CHARGE.c.offense_category),
            _text_of(CHARGE.c.severity),
            _text_of(CHARGE.c.source_row_id),
            _text_of(CHARGE.c.judge_id),
        ).order_by(CHARGE.c.id),
        "decisions": select(
            _text_of(DECISION.c.id),
            _text_of(DECISION.c.case_id),
            _text_of(DECISION.c.person_id),
            _text_of(DECISION.c.judge_id),
            _text_of(DECISION.c.decision_type),
            _utc(DECISION.c.decision_at),
            _text_of(DECISION.c.actor_type),
            _text_of(DECISION.c.judicial_discretion_classification),
            _utc(PRETRIAL_RELEASE.c.release_at),
            PRETRIAL_RELEASE.c.detained_flag,
            _text_of(PRETRIAL_RELEASE.c.release_type),
        )
        .join(PRETRIAL_RELEASE, PRETRIAL_RELEASE.c.decision_id == DECISION.c.id, isouter=True)
        .order_by(DECISION.c.id),
        "sentences": select(
            _text_of(SENTENCE.c.id),
            _text_of(SENTENCE.c.case_id),
            _text_of(SENTENCE.c.person_id),
            _text_of(SENTENCE.c.judge_id),
            _utc(SENTENCE.c.sentence_at),
            SENTENCE.c.incarceration_days,
            SENTENCE.c.probation_days,
            sa.func.coalesce(SENTENCE.c.sentence_components[REPLACED_KEY].as_boolean(), False),
        ).order_by(SENTENCE.c.id),
        "events": select(
            _text_of(COURT_EVENT.c.id),
            _text_of(COURT_EVENT.c.case_id),
            _text_of(COURT_EVENT.c.person_id),
            _text_of(COURT_EVENT.c.judge_id),
            _text_of(COURT_EVENT.c.event_type),
            _utc(COURT_EVENT.c.event_at),
        ).order_by(COURT_EVENT.c.id),
        "justice_events": select(
            _text_of(JUSTICE_EVENT.c.id),
            _text_of(JUSTICE_EVENT.c.person_id),
            _text_of(JUSTICE_EVENT.c.event_type),
            _utc(JUSTICE_EVENT.c.event_at),
            _text_of(JUSTICE_EVENT.c.related_case_id),
        ).order_by(JUSTICE_EVENT.c.id),
        "persons": select(_text_of(PERSON.c.id), _text_of(PERSON.c.merged_into_person_id)).order_by(
            PERSON.c.id
        ),
        "judges": select(_text_of(JUDGE.c.id)).order_by(JUDGE.c.id),
        "courts": select(_text_of(COURT.c.id), _text_of(COURT.c.jurisdiction_id)).order_by(
            COURT.c.id
        ),
    }


def read_table(session: Session, name: str, statement: sa.Select[Any]) -> pl.DataFrame:
    """One table streamed from the database in ``EXPORT_BATCH_ROWS`` batches into one frame.

    A server-side cursor hands the rows over in bounded batches, each turned into a
    columnar frame at once, so the Python tuples never outnumber one batch; the frame
    is rechunked so Polars writes the same Parquet bytes whatever the batch size.
    """
    result = session.execute(
        statement, execution_options={"stream_results": True, "yield_per": EXPORT_BATCH_ROWS}
    )
    batches = [_batch_frame(name, rows) for rows in result.partitions(EXPORT_BATCH_ROWS)]
    if not batches:
        return _batch_frame(name, [])
    return pl.concat(batches, how="vertical", rechunk=True)


def _sources_frame(session: Session) -> pl.DataFrame:
    sources = session.execute(
        select(
            SOURCE.c.id,
            SOURCE.c.name,
            SOURCE.c.source_type,
            SOURCE.c.coverage_start,
            SOURCE.c.coverage_end,
            SOURCE.c.observable_outcomes,
            SOURCE.c.capabilities,
        ).order_by(SOURCE.c.id)
    ).all()
    source_rows: list[tuple[Any, ...]] = []
    for row in sources:
        try:
            capabilities = SourceCapabilities.from_json(row.capabilities)
        except CapabilityError as exc:
            msg = f"source {row.name} declares invalid capabilities: {exc}"
            raise SnapshotError(msg) from exc
        source_rows.append(
            (
                _text(row.id),
                _text(row.name),
                _text(row.source_type),
                row.coverage_start,
                row.coverage_end,
                sorted(str(item) for item in (row.observable_outcomes or [])),
                list(capabilities.judge_gates),
                capabilities.person_key_scope,
                list(capabilities.revocation_scopes),
            )
        )
    return _batch_frame("sources", source_rows)


def _coverage_of(sources: pl.DataFrame) -> dict[str, dict[str, Any]]:
    coverage: dict[str, dict[str, Any]] = {}
    for row in sources.iter_rows(named=True):
        coverage[str(row["id"])] = {
            "name": row["name"],
            "coverage_start": None if row["coverage_start"] is None else str(row["coverage_start"]),
            "coverage_end": None if row["coverage_end"] is None else str(row["coverage_end"]),
        }
    return coverage


def _read_manifest(directory: Path) -> dict[str, Any]:
    path = directory / MANIFEST_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = f"snapshot manifest at {path} is unreadable ({exc.__class__.__name__})"
        raise SnapshotError(msg) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("tables"), dict):
        msg = f"snapshot manifest at {path} is malformed"
        raise SnapshotError(msg)
    return payload


def _ref_from_manifest(directory: Path, payload: Mapping[str, Any], *, reused: bool) -> SnapshotRef:
    tables = {
        str(name): TableDigest(sha256=str(entry["sha256"]), rows=int(entry["rows"]))
        for name, entry in payload["tables"].items()
    }
    return SnapshotRef(
        content_hash=validate_content_hash(str(payload["content_hash"])),
        directory=directory,
        exported_at=datetime.fromisoformat(str(payload["exported_at"])),
        code_version=str(payload["code_version"]),
        tables=MappingProxyType(tables),
        coverage=MappingProxyType(
            {str(k): dict(v) for k, v in dict(payload.get("coverage", {})).items()}
        ),
        reused=reused,
    )


def _check_files(directory: Path, tables: Mapping[str, TableDigest]) -> None:
    """Every table file exists with the manifest's digest; the table set is the fixed one."""
    if set(tables) != set(SNAPSHOT_TABLES):
        msg = (
            f"snapshot {directory.name} lists tables {sorted(tables)} != {sorted(SNAPSHOT_TABLES)}"
        )
        raise SnapshotError(msg)
    for name, digest in tables.items():
        path = directory / f"{name}.parquet"
        if not path.is_file():
            msg = f"snapshot {directory.name} lacks {path.name}"
            raise SnapshotError(msg)
        actual = sha256_file(path)
        if actual != digest.sha256:
            msg = f"snapshot {directory.name}: {path.name} does not match its manifest digest"
            raise SnapshotError(msg)


def snapshot_root(settings: Settings) -> Path:
    return Path(settings.snapshot_dir).resolve()


def refuse_restricted(tables: Iterable[sa.Table]) -> None:
    """Raise ``SnapshotError`` for any table of the ``restricted`` schema, by its schema."""
    for table in tables:
        if table.schema == RESTRICTED_SCHEMA:
            msg = f"the snapshot never exports a table of the {RESTRICTED_SCHEMA} schema"
            raise SnapshotError(msg)


def _write_tables(session: Session, staging: Path) -> tuple[dict[str, TableDigest], pl.DataFrame]:
    """Stream every table to ``staging`` one at a time; the digests and the sources table.

    Only one table's frame is in memory at a time: it is written, hashed, and dropped
    before the next is read.
    """
    statements = export_statements()
    tables: dict[str, TableDigest] = {}
    sources = _sources_frame(session)
    for name in SNAPSHOT_TABLES:
        frame = sources if name == "sources" else read_table(session, name, statements[name])
        path = staging / f"{name}.parquet"
        frame.write_parquet(path)
        tables[name] = TableDigest(sha256=sha256_file(path), rows=frame.height)
        del frame
    return tables, sources


def export_snapshot(session: Session, settings: Settings, label: str | None = None) -> SnapshotRef:
    """Export the canonical tables to Parquet under the content hash; reuse an existing hash.

    Reads through ``session`` (inside the ingest transaction at step 13,
    so the run's own rows are included), streaming each table from a server-side
    cursor in bounded batches (``read_table``). ``label`` is recorded on the
    ``metric_snapshot`` row by the publisher, never in the manifest, so a
    label never changes the hash. Every table read is checked against the
    ``restricted`` schema first (``refuse_restricted``).
    """
    del label  # the publisher records it on the metric_snapshot row
    refuse_restricted(EXPORTED_TABLES)
    root = snapshot_root(settings)
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        tables, sources = _write_tables(session, staging)
        content_hash = content_hash_of(tables)
        target = root / content_hash
        if target.is_dir():
            existing = _ref_from_manifest(target, _read_manifest(target), reused=True)
            if existing.content_hash != content_hash:
                msg = f"snapshot directory {target} does not carry its own hash"
                raise SnapshotError(msg)
            _check_files(target, existing.tables)
            log.info("metrics.snapshot.reused", snapshot=content_hash, rows=existing.row_counts)
            return existing
        ref = SnapshotRef(
            content_hash=content_hash,
            directory=target,
            exported_at=datetime.now(tz=UTC),
            code_version=code_version(settings),
            tables=MappingProxyType(tables),
            coverage=MappingProxyType(_coverage_of(sources)),
        )
        # Never overwritten: a second exporter racing for the same hash loses here
        # and reads the winner's directory back below.
        try:
            target.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            existing = _ref_from_manifest(target, _read_manifest(target), reused=True)
            _check_files(target, existing.tables)
            return existing
        for name in SNAPSHOT_TABLES:
            (staging / f"{name}.parquet").replace(target / f"{name}.parquet")
        manifest_text = json.dumps(ref.manifest_json(), indent=2, sort_keys=True) + "\n"
        (target / MANIFEST_NAME).write_text(manifest_text, encoding="utf-8", newline="\n")
        log.info("metrics.snapshot.exported", snapshot=content_hash, rows=ref.row_counts)
        return ref
    finally:
        for leftover in staging.glob("*"):
            leftover.unlink(missing_ok=True)
        staging.rmdir()


# --- open and load -------------------------------------------------------------------------


def open_snapshot(settings: Settings, content_hash: str) -> Snapshot:
    """The snapshot under ``<snapshot_dir>/<content_hash>/`` as DuckDB views (read-only use)."""
    validated = validate_content_hash(content_hash)
    directory = snapshot_root(settings) / validated
    if not directory.is_dir():
        msg = f"snapshot {validated} is not under {snapshot_root(settings)}"
        raise SnapshotError(msg)
    ref = _ref_from_manifest(directory, _read_manifest(directory), reused=True)
    if ref.content_hash != validated:
        msg = f"snapshot directory {directory} does not carry its own hash"
        raise SnapshotError(msg)
    _check_files(directory, ref.tables)
    return Snapshot(ref)


class Snapshot:
    """An opened snapshot: DuckDB views over its Parquet files and the frame loader.

    The small questions (the sources, which of them hold cases) go through the DuckDB
    views; the frame of a source is built with Polars lazy scans over the same files —
    columnar from the file to the frame, no Python object per cell — so building the
    full Cook County frame is a few joins, not a loop over its 1.3 million charges.
    """

    def __init__(self, ref: SnapshotRef) -> None:
        self.ref = ref
        self._connection = duckdb.connect(database=":memory:")
        for name in SNAPSHOT_TABLES:
            path = ref.directory / f"{name}.parquet"
            self._connection.read_parquet(str(path)).create_view(name)
        self._member_ids: dict[str, pl.Series] = {}
        self._merges: dict[str, str] | None = None
        self._survivor_frame: pl.DataFrame | None = None
        # One frame per source, built once per opened snapshot: the compute, the
        # coverage statistics, and the model fit of one call share it.
        self._frames: dict[str, Frame] = {}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    @property
    def content_hash(self) -> str:
        return self.ref.content_hash

    # --- reads ------------------------------------------------------------------------------

    def _rows(self, sql: str, parameters: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        return self._connection.execute(sql, list(parameters)).fetchall()

    def _scan(self, name: str) -> pl.LazyFrame:
        """A lazy scan of one table's Parquet file (the path is the validated snapshot's)."""
        return pl.scan_parquet(self.ref.directory / f"{name}.parquet")

    def _table(self, name: str, lazy: pl.LazyFrame) -> pl.DataFrame:
        """``lazy`` (selecting the frame columns of ``name`` in schema order) as a frame table."""
        columns = list(SCHEMAS[name])
        table = lazy.select(columns).collect()
        naive = [column for column in columns if PARQUET_SCHEMAS[name][column] == NAIVE_US]
        if naive:
            table = table.with_columns(
                pl.col(column).dt.replace_time_zone("UTC") for column in naive
            )
        return table

    def sources(self) -> list[SourceRow]:
        rows = self._rows(
            "SELECT id, name, source_type, coverage_start, coverage_end, observable_outcomes, "
            "judge_gates, person_key_scope, revocation_scopes FROM sources ORDER BY id"
        )
        return [
            SourceRow(
                id=str(row[0]),
                name=str(row[1]),
                source_type=str(row[2]),
                coverage_start=row[3],
                coverage_end=row[4],
                observable_outcomes=frozenset(str(item) for item in (row[5] or [])),
                capabilities=SourceCapabilities(
                    judge_gates=tuple(str(item) for item in (row[6] or [])),
                    person_key_scope=None if row[7] is None else str(row[7]),
                    revocation_scopes=tuple(str(item) for item in (row[8] or [])),
                ),
            )
            for row in rows
        ]

    def sources_with_cases(self) -> list[SourceRow]:
        """The sources at least one exported case belongs to."""
        with_cases = {str(row[0]) for row in self._rows("SELECT DISTINCT source_id FROM cases")}
        return [source for source in self.sources() if source.id in with_cases]

    def source(self, source_id: str) -> SourceRow:
        for source in self.sources():
            if source.id == source_id:
                return source
        msg = f"snapshot {self.content_hash} has no source {source_id}"
        raise SnapshotError(msg)

    def member_id_series(self, kind: str) -> pl.Series:
        """Every id of the snapshot table behind ``member_kind``: one sorted Polars series."""
        cached = self._member_ids.get(kind)
        if cached is not None:
            return cached
        table = MEMBER_TABLES.get(kind)
        if table is None:
            msg = f"unknown member kind {kind!r}"
            raise SnapshotError(msg)
        ids = self._scan(table).select("id").collect()["id"].sort()
        self._member_ids[kind] = ids
        return ids

    def member_ids(self, kind: str) -> frozenset[str]:
        """Every id of the snapshot table behind ``member_kind`` (the chain-completeness set)."""
        return frozenset(self.member_id_series(kind).to_list())

    def missing_member_ids(self, kind: str, ids: pl.Series) -> pl.Series:
        """The ids of ``ids`` that the snapshot's table for ``kind`` does not hold.

        A binary search of each id in the table's sorted ids (O(len(ids) log n)), so
        checking thousands of families against a table of millions of ids costs the
        families' size, not the table's.
        """
        known = self.member_id_series(kind)
        if known.len() == 0 or ids.len() == 0:
            return ids
        positions = known.search_sorted(ids).clip(upper_bound=known.len() - 1)
        present = known.gather(positions) == ids
        return ids.filter(~present)

    def _merge_map(self) -> dict[str, str]:
        """Each merged person's direct pointer (``merged_into_person_id``); unmerged persons absent."""
        if self._merges is None:
            merged = (
                self._scan("persons")
                .filter(pl.col("merged_into_person_id").is_not_null())
                .select("id", "merged_into_person_id")
                .collect()
            )
            self._merges = dict(zip(merged["id"], merged["merged_into_person_id"], strict=True))
        return self._merges

    def survivor(self, person_id: str) -> str:
        """The end of ``person_id``'s merge chain (itself when unmerged or unknown)."""
        merges = self._merge_map()
        current = person_id
        seen: set[str] = set()
        while current in merges and current not in seen:
            seen.add(current)
            current = merges[current]
        return current

    def _survivors(self) -> pl.DataFrame:
        """``(alias, survivor)`` for every merged person: the whole merge forest, as a table."""
        if self._survivor_frame is None:
            aliases = sorted(self._merge_map())
            self._survivor_frame = pl.DataFrame(
                {"alias": aliases, "survivor": [self.survivor(alias) for alias in aliases]},
                schema={"alias": STRING, "survivor": STRING},
            )
        return self._survivor_frame

    # --- the frame --------------------------------------------------------------------------

    def frame(self, source_id: str) -> Frame:
        """The Step 1 ``Frame`` of one source's rows (see the module docstring); cached."""
        cached = self._frames.get(source_id)
        if cached is not None:
            return cached
        built = self._build_frame(source_id)
        self._frames[source_id] = built
        return built

    def _build_frame(self, source_id: str) -> Frame:
        source = self.source(source_id)
        if source.coverage_start is None or source.coverage_end is None:
            msg = f"source {source.name} ({source_id}) declares no coverage window"
            raise SnapshotError(msg)
        cases_lazy = self._scan("cases").filter(pl.col("source_id") == source_id)
        case_ids = cases_lazy.select(pl.col("id").alias("case_id"))

        def of_the_cases(name: str, column: str = "case_id") -> pl.LazyFrame:
            """The table's rows whose case belongs to the source."""
            return self._scan(name).join(case_ids, left_on=column, right_on="case_id", how="semi")

        cases = self._table("cases", cases_lazy.sort("id"))
        assignments = self._table("assignments", of_the_cases("assignments").sort("id"))
        charges = self._table("charges", of_the_cases("charges").sort("id"))
        decisions = self._table("decisions", of_the_cases("decisions").sort("id"))
        # A sentence a later correction replaced is not a sentencing decision of its own.
        sentences = self._table(
            "sentences",
            of_the_cases("sentences").filter(~pl.col("replaced").fill_null(False)).sort("id"),
        )
        events = self._table("events", of_the_cases("events").sort("id"))
        # Resolved persons: every person the source's rows name, after merges.
        charges = self._resolve_persons(charges)
        decisions = self._resolve_persons(decisions)
        sentences = self._resolve_persons(sentences)
        events = self._resolve_persons(events)
        person_ids = (
            pl.concat(
                [
                    table.select(pl.col("person_id").alias("id"))
                    for table in (charges, decisions, sentences, events)
                ]
            )
            .drop_nulls()
            .unique()
            .sort("id")
        )
        persons = person_ids
        justice_events = self._justice_events(persons["id"], source.observable_outcomes)
        courts = self._table(
            "courts",
            self._scan("courts")
            .join(
                cases_lazy.select(pl.col("court_id").alias("id")).unique(),
                on="id",
                how="semi",
            )
            .sort("id"),
        )
        return Frame(
            cases=cases,
            assignments=assignments,
            charges=charges,
            decisions=decisions,
            sentences=sentences,
            events=events,
            justice_events=justice_events,
            persons=persons,
            courts=courts,
            coverage_start=source.coverage_start,
            coverage_end=source.coverage_end,
            observable_outcomes=source.observable_outcomes,
            capabilities=source.capabilities,
        )

    def _resolve_persons(self, table: pl.DataFrame) -> pl.DataFrame:
        """``person_id`` re-pointed at the survivor of each merge chain."""
        if table.height == 0 or not self._merge_map():
            return table
        survivors = self._survivors()
        mapping = dict(zip(survivors["alias"], survivors["survivor"], strict=True))
        return table.with_columns(
            pl.col("person_id")
            .replace_strict(mapping, default=pl.col("person_id"), return_dtype=pl.String)
            .alias("person_id")
        )

    def _family(self, person_ids: pl.Series) -> pl.Series:
        """``person_ids`` plus every person whose merge chain ends in one of them.

        ``merge_persons`` re-points every person-bearing row at the survivor,
        so the aliases normally carry no rows; reading by the whole family
        keeps a stale pointer from dropping an event or a charge.
        """
        if not self._merge_map():
            return person_ids
        survivors = self._survivors()
        aliases = survivors.filter(pl.col("survivor").is_in(person_ids.implode()))["alias"]
        return pl.concat([person_ids, aliases]).unique().sort()

    def _justice_events(self, person_ids: pl.Series, observable: frozenset[str]) -> pl.DataFrame:
        """Stored any-case events plus the derived other-case outcomes of the merged persons.

        Only the other-case outcomes the source observes are derived: for a source
        whose person is a case participation they would be meaningless rows.
        """
        family = self._family(person_ids)
        stored = self._table(
            "justice_events",
            self._scan("justice_events")
            .filter(
                pl.col("person_id").is_in(family.implode())
                & pl.col("event_type").is_in(sorted(ANY_CASE_OUTCOMES))
            )
            .sort("id"),
        )
        stored = self._resolve_persons(stored)
        wanted = frozenset({NEW_CASE, NEW_CHARGE, RECONVICTION}) & observable
        derived = self._derived_outcomes(family, wanted) if wanted else stored.clear()
        combined = pl.concat([stored, derived]) if derived.height else stored
        return combined.sort(["person_id", "event_type", "event_at", "related_case_id", "id"])

    def _derived_outcomes(self, family: pl.Series, wanted: frozenset[str]) -> pl.DataFrame:
        """``new_case``, ``new_charge``, ``reconviction`` (those ``wanted``) from the charges.

        Every charge of the family's persons, whatever its source: ``new_charge`` at each
        charge filing, ``new_case`` at the earliest filing of each (person, case), and
        ``reconviction`` at each convicted charge's disposition. The id of a derived row
        names its type, case, and instant the way ``datetime.isoformat`` writes them.
        """
        charges = (
            self._scan("charges")
            .filter(pl.col("person_id").is_in(family.implode()))
            .select("case_id", "person_id", "filed_at", "disposed_at", "disposition")
            .collect()
        )
        charges = self._resolve_persons(charges)
        parts: list[pl.DataFrame] = []

        def part(event_type: str, rows: pl.DataFrame, instant: str) -> None:
            parts.append(
                rows.select(
                    "person_id",
                    pl.lit(event_type).alias("event_type"),
                    pl.col(instant).alias("event_at"),
                    pl.col("case_id").alias("related_case_id"),
                )
            )

        if NEW_CHARGE in wanted:
            part(NEW_CHARGE, charges, "filed_at")
        if NEW_CASE in wanted:
            part(
                NEW_CASE,
                charges.group_by(["person_id", "case_id"]).agg(pl.col("filed_at").min()),
                "filed_at",
            )
        if RECONVICTION in wanted:
            convicted = charges.filter(
                pl.col("disposition").is_in(sorted(CONVICTED_DISPOSITIONS))
                & pl.col("disposed_at").is_not_null()
            )
            part(RECONVICTION, convicted, "disposed_at")
        if not parts:
            return pl.DataFrame(schema=dict(PARQUET_SCHEMAS["justice_events"]))
        events = pl.concat(parts).unique()
        identified = events.with_columns(
            pl.format(
                "{}:{}:{}:{}",
                pl.lit(DERIVED_PREFIX),
                pl.col("event_type"),
                pl.col("related_case_id"),
                _isoformat_utc(pl.col("event_at")),
            ).alias("id")
        )
        table = identified.select(*PARQUET_SCHEMAS["justice_events"]).cast(
            pl.Schema(PARQUET_SCHEMAS["justice_events"])
        )
        return table.with_columns(pl.col("event_at").dt.replace_time_zone("UTC"))


def _isoformat_utc(instant: pl.Expr) -> pl.Expr:
    """A naive UTC instant as ``datetime.isoformat`` writes it after ``replace(tzinfo=UTC)``.

    ``2020-01-01T09:00:00+00:00``, with ``.ffffff`` added when the microsecond is not zero.
    """
    micro = instant.dt.microsecond()
    fraction = (
        pl.when(micro != 0)
        .then(pl.format(".{}", micro.cast(pl.String).str.zfill(6)))
        .otherwise(pl.lit(""))
    )
    return pl.concat_str([instant.dt.strftime("%Y-%m-%dT%H:%M:%S"), fraction, pl.lit("+00:00")])
