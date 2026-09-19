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
``entity_resolution_candidate``, ``correction_request``), the persons
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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self

import duckdb
import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics import __version__
from judgemetrics.config import Settings
from judgemetrics.db.models import Base
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
            }
        ),
    }
)
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


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _start_of_day(day: date | None) -> datetime | None:
    return None if day is None else datetime.combine(day, time.min)


def _end_of_day(day: date | None) -> datetime | None:
    return None if day is None else datetime.combine(day, time.max)


def _frame(name: str, rows: Sequence[tuple[Any, ...]]) -> pl.DataFrame:
    schema = dict(PARQUET_SCHEMAS[name])
    return pl.DataFrame(list(rows), schema=schema, orient="row")


# --- export ------------------------------------------------------------------------------


def _export_rows(session: Session) -> dict[str, pl.DataFrame]:
    """Every snapshot table as a Polars frame, ordered by id, with the Parquet schema."""
    frames: dict[str, pl.DataFrame] = {}

    cases = session.execute(
        select(
            COURT_CASE.c.id,
            COURT_CASE.c.court_id,
            SOURCE_RECORD.c.source_id,
            COURT_CASE.c.filed_date,
            COURT_CASE.c.closed_date,
            COURT_CASE.c.status,
            COURT_CASE.c.case_type,
        )
        .join(SOURCE_RECORD, SOURCE_RECORD.c.id == COURT_CASE.c.source_record_id)
        .order_by(COURT_CASE.c.id)
    ).all()
    frames["cases"] = _frame(
        "cases",
        [
            (
                _text(row.id),
                _text(row.court_id),
                _text(row.source_id),
                _start_of_day(row.filed_date),
                _end_of_day(row.closed_date),
                _text(row.status),
                _text(row.case_type),
            )
            for row in cases
        ],
    )

    assignments = session.execute(
        select(
            JUDGE_ASSIGNMENT.c.id,
            JUDGE_ASSIGNMENT.c.case_id,
            JUDGE_ASSIGNMENT.c.judge_id,
            JUDGE_ASSIGNMENT.c.start_at,
            JUDGE_ASSIGNMENT.c.end_at,
        ).order_by(JUDGE_ASSIGNMENT.c.id)
    ).all()
    frames["assignments"] = _frame(
        "assignments",
        [
            (
                _text(row.id),
                _text(row.case_id),
                _text(row.judge_id),
                _naive_utc(row.start_at),
                _naive_utc(row.end_at),
            )
            for row in assignments
        ],
    )

    charges = session.execute(
        select(
            CHARGE.c.id,
            CHARGE.c.case_id,
            CHARGE.c.person_id,
            CHARGE.c.filed_at,
            CHARGE.c.disposed_at,
            CHARGE.c.disposition,
            CHARGE.c.disposition_actor,
            CHARGE.c.offense_category,
            CHARGE.c.severity,
            CHARGE.c.source_row_id,
        ).order_by(CHARGE.c.id)
    ).all()
    frames["charges"] = _frame(
        "charges",
        [
            (
                _text(row.id),
                _text(row.case_id),
                _text(row.person_id),
                _naive_utc(row.filed_at),
                _naive_utc(row.disposed_at),
                _text(row.disposition),
                _text(row.disposition_actor),
                _text(row.offense_category),
                _text(row.severity),
                _text(row.source_row_id),
            )
            for row in charges
        ],
    )

    decisions = session.execute(
        select(
            DECISION.c.id,
            DECISION.c.case_id,
            DECISION.c.person_id,
            DECISION.c.judge_id,
            DECISION.c.decision_type,
            DECISION.c.decision_at,
            DECISION.c.actor_type,
            DECISION.c.judicial_discretion_classification,
            PRETRIAL_RELEASE.c.release_at,
            PRETRIAL_RELEASE.c.detained_flag,
            PRETRIAL_RELEASE.c.release_type,
        )
        .join(PRETRIAL_RELEASE, PRETRIAL_RELEASE.c.decision_id == DECISION.c.id, isouter=True)
        .order_by(DECISION.c.id)
    ).all()
    frames["decisions"] = _frame(
        "decisions",
        [
            (
                _text(row.id),
                _text(row.case_id),
                _text(row.person_id),
                _text(row.judge_id),
                _text(row.decision_type),
                _naive_utc(row.decision_at),
                _text(row.actor_type),
                _text(row.judicial_discretion_classification),
                _naive_utc(row.release_at),
                row.detained_flag,
                _text(row.release_type),
            )
            for row in decisions
        ],
    )

    sentences = session.execute(
        select(
            SENTENCE.c.id,
            SENTENCE.c.case_id,
            SENTENCE.c.person_id,
            SENTENCE.c.judge_id,
            SENTENCE.c.sentence_at,
            SENTENCE.c.incarceration_days,
            SENTENCE.c.probation_days,
        ).order_by(SENTENCE.c.id)
    ).all()
    frames["sentences"] = _frame(
        "sentences",
        [
            (
                _text(row.id),
                _text(row.case_id),
                _text(row.person_id),
                _text(row.judge_id),
                _naive_utc(row.sentence_at),
                row.incarceration_days,
                row.probation_days,
            )
            for row in sentences
        ],
    )

    events = session.execute(
        select(
            COURT_EVENT.c.id,
            COURT_EVENT.c.case_id,
            COURT_EVENT.c.person_id,
            COURT_EVENT.c.judge_id,
            COURT_EVENT.c.event_type,
            COURT_EVENT.c.event_at,
        ).order_by(COURT_EVENT.c.id)
    ).all()
    frames["events"] = _frame(
        "events",
        [
            (
                _text(row.id),
                _text(row.case_id),
                _text(row.person_id),
                _text(row.judge_id),
                _text(row.event_type),
                _naive_utc(row.event_at),
            )
            for row in events
        ],
    )

    justice = session.execute(
        select(
            JUSTICE_EVENT.c.id,
            JUSTICE_EVENT.c.person_id,
            JUSTICE_EVENT.c.event_type,
            JUSTICE_EVENT.c.event_at,
            JUSTICE_EVENT.c.related_case_id,
        ).order_by(JUSTICE_EVENT.c.id)
    ).all()
    frames["justice_events"] = _frame(
        "justice_events",
        [
            (
                _text(row.id),
                _text(row.person_id),
                _text(row.event_type),
                _naive_utc(row.event_at),
                _text(row.related_case_id),
            )
            for row in justice
        ],
    )

    persons = session.execute(
        select(PERSON.c.id, PERSON.c.merged_into_person_id).order_by(PERSON.c.id)
    ).all()
    frames["persons"] = _frame(
        "persons", [(_text(row.id), _text(row.merged_into_person_id)) for row in persons]
    )

    judges = session.execute(select(JUDGE.c.id).order_by(JUDGE.c.id)).all()
    frames["judges"] = _frame("judges", [(_text(row.id),) for row in judges])

    courts = session.execute(select(COURT.c.id, COURT.c.jurisdiction_id).order_by(COURT.c.id)).all()
    frames["courts"] = _frame(
        "courts", [(_text(row.id), _text(row.jurisdiction_id)) for row in courts]
    )

    sources = session.execute(
        select(
            SOURCE.c.id,
            SOURCE.c.name,
            SOURCE.c.source_type,
            SOURCE.c.coverage_start,
            SOURCE.c.coverage_end,
            SOURCE.c.observable_outcomes,
        ).order_by(SOURCE.c.id)
    ).all()
    frames["sources"] = _frame(
        "sources",
        [
            (
                _text(row.id),
                _text(row.name),
                _text(row.source_type),
                row.coverage_start,
                row.coverage_end,
                sorted(str(item) for item in (row.observable_outcomes or [])),
            )
            for row in sources
        ],
    )
    return frames


def _coverage_of(frames: Mapping[str, pl.DataFrame]) -> dict[str, dict[str, Any]]:
    coverage: dict[str, dict[str, Any]] = {}
    for row in frames["sources"].iter_rows(named=True):
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


def export_snapshot(session: Session, settings: Settings, label: str | None = None) -> SnapshotRef:
    """Export the canonical tables to Parquet under the content hash; reuse an existing hash.

    Reads through ``session`` (inside the ingest transaction at step 13,
    so the run's own rows are included). ``label`` is recorded on the
    ``metric_snapshot`` row by the publisher, never in the manifest, so a
    label never changes the hash.
    """
    del label  # the publisher records it on the metric_snapshot row
    root = snapshot_root(settings)
    root.mkdir(parents=True, exist_ok=True)
    frames = _export_rows(session)
    staging = root / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        tables: dict[str, TableDigest] = {}
        for name in SNAPSHOT_TABLES:
            path = staging / f"{name}.parquet"
            frames[name].write_parquet(path)
            tables[name] = TableDigest(sha256=sha256_file(path), rows=frames[name].height)
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
            coverage=MappingProxyType(_coverage_of(frames)),
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


def _naive_columns(name: str) -> list[str]:
    return [column for column, dtype in PARQUET_SCHEMAS[name].items() if dtype == NAIVE_US]


class Snapshot:
    """An opened snapshot: DuckDB views over its Parquet files and the frame loader."""

    def __init__(self, ref: SnapshotRef) -> None:
        self.ref = ref
        self._connection = duckdb.connect(database=":memory:")
        for name in SNAPSHOT_TABLES:
            path = ref.directory / f"{name}.parquet"
            self._connection.read_parquet(str(path)).create_view(name)
        self._member_ids: dict[str, frozenset[str]] = {}
        self._persons: dict[str, str | None] | None = None

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

    def _table(self, name: str, sql: str, parameters: Sequence[Any] = ()) -> pl.DataFrame:
        """``sql`` (selecting the frame columns of ``name`` in schema order) as a frame table."""
        columns = list(SCHEMAS[name])
        schema = {column: PARQUET_SCHEMAS[name][column] for column in columns}
        table = pl.DataFrame(self._rows(sql, parameters), schema=schema, orient="row")
        naive = [column for column in columns if schema[column] == NAIVE_US]
        if naive:
            table = table.with_columns(
                pl.col(column).dt.replace_time_zone("UTC") for column in naive
            )
        return table

    def sources(self) -> list[SourceRow]:
        rows = self._rows(
            "SELECT id, name, source_type, coverage_start, coverage_end, observable_outcomes "
            "FROM sources ORDER BY id"
        )
        return [
            SourceRow(
                id=str(row[0]),
                name=str(row[1]),
                source_type=str(row[2]),
                coverage_start=row[3],
                coverage_end=row[4],
                observable_outcomes=frozenset(str(item) for item in (row[5] or [])),
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

    def member_ids(self, kind: str) -> frozenset[str]:
        """Every id of the snapshot table behind ``member_kind`` (the chain-completeness set)."""
        cached = self._member_ids.get(kind)
        if cached is not None:
            return cached
        table = MEMBER_TABLES.get(kind)
        if table is None:
            msg = f"unknown member kind {kind!r}"
            raise SnapshotError(msg)
        # The relation API over the fixed view name: no SQL text is assembled.
        rows = self._connection.table(table).select("id").fetchall()
        ids = frozenset(str(row[0]) for row in rows)
        self._member_ids[kind] = ids
        return ids

    def _merge_map(self) -> dict[str, str | None]:
        if self._persons is None:
            self._persons = {
                str(row[0]): (None if row[1] is None else str(row[1]))
                for row in self._rows("SELECT id, merged_into_person_id FROM persons")
            }
        return self._persons

    def survivor(self, person_id: str) -> str:
        """The end of ``person_id``'s merge chain (itself when unmerged or unknown)."""
        merges = self._merge_map()
        current = person_id
        seen: set[str] = set()
        while current in merges and merges[current] is not None and current not in seen:
            seen.add(current)
            following = merges[current]
            if following is None:  # pragma: no cover - guarded by the loop condition
                break
            current = following
        return current

    # --- the frame --------------------------------------------------------------------------

    def frame(self, source_id: str) -> Frame:
        """The Step 1 ``Frame`` of one source's rows (see the module docstring)."""
        source = self.source(source_id)
        if source.coverage_start is None or source.coverage_end is None:
            msg = f"source {source.name} ({source_id}) declares no coverage window"
            raise SnapshotError(msg)
        cases = self._table(
            "cases",
            "SELECT id, court_id, filed_at, closed_at, status, case_type "
            "FROM cases WHERE source_id = ? ORDER BY id",
            [source_id],
        )
        assignments = self._table(
            "assignments",
            "SELECT a.case_id, a.judge_id, a.start_at, a.end_at FROM assignments a "
            "JOIN cases c ON c.id = a.case_id WHERE c.source_id = ? ORDER BY a.id",
            [source_id],
        )
        charges = self._table(
            "charges",
            "SELECT ch.id, ch.case_id, ch.person_id, ch.filed_at, ch.disposed_at, "
            "ch.disposition, ch.disposition_actor, ch.offense_category, ch.severity, "
            "ch.source_row_id FROM charges ch JOIN cases c ON c.id = ch.case_id "
            "WHERE c.source_id = ? ORDER BY ch.id",
            [source_id],
        )
        decisions = self._table(
            "decisions",
            "SELECT d.id, d.case_id, d.person_id, d.judge_id, d.decision_type, d.decision_at, "
            "d.actor_type, d.discretion, d.release_at, d.detained_flag, d.release_type "
            "FROM decisions d JOIN cases c ON c.id = d.case_id WHERE c.source_id = ? "
            "ORDER BY d.id",
            [source_id],
        )
        sentences = self._table(
            "sentences",
            "SELECT s.id, s.case_id, s.person_id, s.judge_id, s.sentence_at, "
            "s.incarceration_days, s.probation_days FROM sentences s "
            "JOIN cases c ON c.id = s.case_id WHERE c.source_id = ? ORDER BY s.id",
            [source_id],
        )
        events = self._table(
            "events",
            "SELECT e.id, e.case_id, e.person_id, e.judge_id, e.event_type, e.event_at "
            "FROM events e JOIN cases c ON c.id = e.case_id WHERE c.source_id = ? ORDER BY e.id",
            [source_id],
        )
        # Resolved persons: every person the source's rows name, after merges.
        charges = self._resolve_persons(charges)
        decisions = self._resolve_persons(decisions)
        sentences = self._resolve_persons(sentences)
        events = self._resolve_persons(events)
        person_ids = sorted(
            set(charges["person_id"].drop_nulls().to_list())
            | set(decisions["person_id"].drop_nulls().to_list())
            | set(sentences["person_id"].drop_nulls().to_list())
            | set(events["person_id"].drop_nulls().to_list())
        )
        persons = pl.DataFrame({"id": person_ids}, schema={"id": STRING})
        justice_events = self._justice_events(person_ids)
        return Frame(
            cases=cases,
            assignments=assignments,
            charges=charges,
            decisions=decisions,
            sentences=sentences,
            events=events,
            justice_events=justice_events,
            persons=persons,
            coverage_start=source.coverage_start,
            coverage_end=source.coverage_end,
            observable_outcomes=source.observable_outcomes,
        )

    def _resolve_persons(self, table: pl.DataFrame) -> pl.DataFrame:
        """``person_id`` re-pointed at the survivor of each merge chain."""
        if table.height == 0:
            return table
        merges = self._merge_map()
        mapping = {
            pid: self.survivor(pid)
            for pid in set(table["person_id"].drop_nulls().to_list())
            if merges.get(pid) is not None
        }
        if not mapping:
            return table
        return table.with_columns(
            pl.col("person_id")
            .replace_strict(mapping, default=pl.col("person_id"), return_dtype=pl.String)
            .alias("person_id")
        )

    def _family(self, person_ids: Sequence[str]) -> list[str]:
        """``person_ids`` plus every person whose merge chain ends in one of them.

        ``merge_persons`` re-points every person-bearing row at the survivor,
        so the aliases normally carry no rows; reading by the whole family
        keeps a stale pointer from dropping an event or a charge.
        """
        wanted = set(person_ids)
        family = set(wanted)
        for pid in self._merge_map():
            if pid not in family and self.survivor(pid) in wanted:
                family.add(pid)
        return sorted(family)

    def _justice_events(self, person_ids: Sequence[str]) -> pl.DataFrame:
        """Stored any-case events plus the derived other-case outcomes of the merged persons."""
        stored = self._table(
            "justice_events",
            "SELECT id, person_id, event_type, event_at, related_case_id FROM justice_events "
            "WHERE person_id IN (SELECT unnest(?::VARCHAR[])) "
            "AND event_type IN (SELECT unnest(?::VARCHAR[])) ORDER BY id",
            [self._family(person_ids), sorted(ANY_CASE_OUTCOMES)],
        )
        stored = self._resolve_persons(stored)
        derived = self._derived_outcomes(person_ids)
        combined = pl.concat([stored, derived]) if derived.height else stored
        return combined.sort(["person_id", "event_type", "event_at", "related_case_id", "id"])

    def _derived_outcomes(self, person_ids: Sequence[str]) -> pl.DataFrame:
        """``new_case``, ``new_charge``, ``reconviction`` from every charge of the persons."""
        rows = self._rows(
            "SELECT ch.case_id, ch.person_id, ch.filed_at, ch.disposed_at, ch.disposition "
            "FROM charges ch WHERE ch.person_id IN (SELECT unnest(?::VARCHAR[])) "
            "ORDER BY ch.id",
            [self._family(person_ids)],
        )
        earliest: dict[tuple[str, str], datetime] = {}
        derived: set[tuple[str, str, datetime, str]] = set()
        for case_id, person_id, filed_at, disposed_at, disposition in rows:
            case = str(case_id)
            person = self.survivor(str(person_id))
            filed = filed_at.replace(tzinfo=UTC)
            key = (person, case)
            if key not in earliest or filed < earliest[key]:
                earliest[key] = filed
            derived.add((person, NEW_CHARGE, filed, case))
            if disposition in CONVICTED_DISPOSITIONS and disposed_at is not None:
                derived.add((person, RECONVICTION, disposed_at.replace(tzinfo=UTC), case))
        for (person, case), filed in earliest.items():
            derived.add((person, NEW_CASE, filed, case))
        ordered = sorted(derived)
        table = pl.DataFrame(
            [
                (
                    f"{DERIVED_PREFIX}:{event_type}:{case}:{at.isoformat()}",
                    person,
                    event_type,
                    at.replace(tzinfo=None),
                    case,
                )
                for person, event_type, at, case in ordered
            ],
            schema=dict(PARQUET_SCHEMAS["justice_events"]),
            orient="row",
        )
        return table.with_columns(pl.col("event_at").dt.replace_time_zone("UTC"))
