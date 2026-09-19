# tests/unit/test_metrics_snapshot.py
"""The snapshot loader without a database: hashes, determinism, views, the frame.

A snapshot id is validated as 64 lowercase hexadecimal characters before
it becomes a path; the content hash is the sha256 over the sorted
``table:sha256`` lines; Polars writes the same bytes for the same rows,
so the same data yields the same hash; ``open_snapshot`` refuses a
directory whose manifest or files do not match. Over a hand-built
snapshot (two persons merged into one, two cases, one stored failure to
appear), ``Snapshot.frame`` re-points every person column at the merge
survivor, keeps the stored any-case events, derives ``new_case`` at the
earliest charge filing of each case, ``new_charge`` per charge, and
``reconviction`` per convicted charge — keyed by their own case — and
never carries a stored other-case row or a person beyond an id. The
module's source names no restricted table, installs or loads no DuckDB
extension, and nothing under ``metrics/`` names a restricted attribute.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from judgemetrics.config import REPO_ROOT, Settings
from judgemetrics.metrics import snapshot as snapshot_module
from judgemetrics.metrics.snapshot import (
    MANIFEST_NAME,
    PARQUET_SCHEMAS,
    RESTRICTED_TABLES,
    SNAPSHOT_TABLES,
    SnapshotError,
    SnapshotRef,
    TableDigest,
    code_version,
    content_hash_of,
    open_snapshot,
    validate_content_hash,
)

pytestmark = pytest.mark.unit

RESTRICTED_ATTRIBUTES = ("value_hash", "date_of_birth", "full_name", "encrypted_value")
METRICS_DIR = REPO_ROOT / "src" / "judgemetrics" / "metrics"
SOURCE_ID = "11111111-1111-1111-1111-111111111111"
SURVIVOR = "aaaaaaaa-0000-0000-0000-000000000001"
MERGED = "aaaaaaaa-0000-0000-0000-000000000002"
OTHER = "aaaaaaaa-0000-0000-0000-000000000003"


def _at(day: int, hour: int = 9) -> datetime:
    return datetime(2020, 1, day, hour, tzinfo=UTC)


def _naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _rows() -> dict[str, list[dict[str, Any]]]:
    """A tiny world: case C1 (survivor) and C2 (the merged alias), one court, one judge."""
    return {
        "cases": [
            {
                "id": "c1",
                "court_id": "court-1",
                "source_id": SOURCE_ID,
                "filed_at": _naive(_at(1, 0)),
                "closed_at": None,
                "status": "open",
                "case_type": "felony",
            },
            {
                "id": "c2",
                "court_id": "court-1",
                "source_id": SOURCE_ID,
                "filed_at": _naive(_at(10, 0)),
                "closed_at": None,
                "status": "open",
                "case_type": "felony",
            },
            {
                "id": "c9",
                "court_id": "court-2",
                "source_id": "22222222-2222-2222-2222-222222222222",
                "filed_at": _naive(_at(20, 0)),
                "closed_at": None,
                "status": "open",
                "case_type": "felony",
            },
        ],
        "assignments": [
            {
                "id": "a1",
                "case_id": "c1",
                "judge_id": "j1",
                "start_at": _naive(_at(1)),
                "end_at": None,
            },
            {
                "id": "a2",
                "case_id": "c2",
                "judge_id": "j1",
                "start_at": _naive(_at(10)),
                "end_at": None,
            },
        ],
        "charges": [
            {
                "id": "h1",
                "case_id": "c1",
                "person_id": SURVIVOR,
                "filed_at": _naive(_at(1, 11)),
                "disposed_at": _naive(_at(5)),
                "disposition": "convicted_plea",
                "disposition_actor": "judge",
                "offense_category": "drug",
                "severity": "felony_3",
                "source_row_id": "CH-1",
            },
            {
                "id": "h2",
                "case_id": "c1",
                "person_id": SURVIVOR,
                "filed_at": _naive(_at(1, 10)),
                "disposed_at": None,
                "disposition": "pending",
                "disposition_actor": None,
                "offense_category": "drug",
                "severity": "felony_3",
                "source_row_id": "CH-2",
            },
            {
                "id": "h3",
                "case_id": "c2",
                "person_id": MERGED,  # a stale pointer: the merged alias
                "filed_at": _naive(_at(10, 10)),
                "disposed_at": _naive(_at(15)),
                "disposition": "dismissed",
                "disposition_actor": "prosecutor",
                "offense_category": "property",
                "severity": "misdemeanor_a",
                "source_row_id": "CH-3",
            },
        ],
        "decisions": [
            {
                "id": "d1",
                "case_id": "c1",
                "person_id": SURVIVOR,
                "judge_id": "j1",
                "decision_type": "pretrial_release",
                "decision_at": _naive(_at(2)),
                "actor_type": "judge",
                "discretion": "discretionary",
                "release_at": _naive(_at(2, 12)),
                "detained_flag": False,
                "release_type": "recognizance",
            }
        ],
        "sentences": [],
        "events": [],
        "justice_events": [
            {
                "id": "e1",
                "person_id": MERGED,
                "event_type": "failure_to_appear",
                "event_at": _naive(_at(12)),
                "related_case_id": "c2",
            },
            {
                "id": "e2",
                "person_id": SURVIVOR,
                "event_type": "new_case",  # a stored other-case row: replaced by derivation
                "event_at": _naive(_at(10, 0)),
                "related_case_id": "c2",
            },
        ],
        "persons": [
            {"id": SURVIVOR, "merged_into_person_id": None},
            {"id": MERGED, "merged_into_person_id": SURVIVOR},
            {"id": OTHER, "merged_into_person_id": None},
        ],
        "judges": [{"id": "j1"}],
        "courts": [
            {"id": "court-1", "jurisdiction_id": "jur"},
            {"id": "court-2", "jurisdiction_id": "jur"},
        ],
        "sources": [
            {
                "id": SOURCE_ID,
                "name": "synthetic",
                "source_type": "synthetic",
                "coverage_start": date(2020, 1, 1),
                "coverage_end": date(2020, 12, 31),
                "observable_outcomes": ["failure_to_appear", "new_case"],
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "name": "other",
                "source_type": "court_records",
                "coverage_start": None,
                "coverage_end": None,
                "observable_outcomes": [],
            },
        ],
    }


def _write_snapshot(root: Path, rows: dict[str, list[dict[str, Any]]]) -> str:
    staging = root / "staging"
    staging.mkdir()
    tables: dict[str, TableDigest] = {}
    for name in SNAPSHOT_TABLES:
        frame = pl.DataFrame(rows[name], schema=dict(PARQUET_SCHEMAS[name]), orient="row")
        path = staging / f"{name}.parquet"
        frame.write_parquet(path)
        tables[name] = TableDigest(hashlib.sha256(path.read_bytes()).hexdigest(), frame.height)
    content_hash = content_hash_of(tables)
    target = root / content_hash
    staging.rename(target)
    ref = SnapshotRef(
        content_hash=content_hash,
        directory=target,
        exported_at=datetime(2026, 9, 19, tzinfo=UTC),
        code_version="test",
        tables=tables,
        coverage={},
    )
    (target / MANIFEST_NAME).write_text(json.dumps(ref.manifest_json()), encoding="utf-8")
    return content_hash


@pytest.fixture
def snapshot_dir(tmp_path: Path) -> tuple[Settings, str]:
    root = tmp_path / "snapshots"
    root.mkdir()
    content_hash = _write_snapshot(root, _rows())
    return Settings(env="test", snapshot_dir=root), content_hash


def test_content_hash_validation_and_derivation() -> None:
    valid = "a" * 64
    assert validate_content_hash(valid) == valid
    for bad in ("A" * 64, "a" * 63, "../" + "a" * 61, "", "a" * 64 + "/x"):
        with pytest.raises(SnapshotError, match="64-character"):
            validate_content_hash(bad)
    tables = {"b": TableDigest("2" * 64, 1), "a": TableDigest("1" * 64, 2)}
    expected = hashlib.sha256(f"a:{'1' * 64}\nb:{'2' * 64}\n".encode("ascii")).hexdigest()
    assert content_hash_of(tables) == expected


def test_polars_writes_the_same_bytes_for_the_same_rows() -> None:
    rows = _rows()["charges"]
    digests = set()
    for _ in range(3):
        buffer = io.BytesIO()
        pl.DataFrame(rows, schema=dict(PARQUET_SCHEMAS["charges"]), orient="row").write_parquet(
            buffer
        )
        digests.add(hashlib.sha256(buffer.getvalue()).hexdigest())
    assert len(digests) == 1


def test_open_snapshot_refuses_a_bad_id_a_missing_directory_and_drift(
    snapshot_dir: tuple[Settings, str],
) -> None:
    settings, content_hash = snapshot_dir
    with pytest.raises(SnapshotError, match="64-character"):
        open_snapshot(settings, "../etc")
    with pytest.raises(SnapshotError, match="is not under"):
        open_snapshot(settings, "f" * 64)
    directory = Path(settings.snapshot_dir) / content_hash
    (directory / "charges.parquet").write_bytes(b"tampered")
    with pytest.raises(SnapshotError, match="charges.parquet does not match"):
        open_snapshot(settings, content_hash)


def test_the_frame_of_a_source_resolves_merges_and_derives_other_case_outcomes(
    snapshot_dir: tuple[Settings, str],
) -> None:
    settings, content_hash = snapshot_dir
    with open_snapshot(settings, content_hash) as opened:
        assert opened.content_hash == content_hash
        assert sorted(s.name for s in opened.sources_with_cases()) == ["other", "synthetic"]
        assert opened.member_ids("charge") == {"h1", "h2", "h3"}
        assert opened.member_ids("justice_event") == {"e1", "e2"}
        assert opened.survivor(MERGED) == SURVIVOR and opened.survivor(OTHER) == OTHER
        with pytest.raises(SnapshotError, match="unknown member kind"):
            opened.member_ids("person")
        with pytest.raises(SnapshotError, match="declares no coverage window"):
            opened.frame("22222222-2222-2222-2222-222222222222")
        frame = opened.frame(SOURCE_ID)
    assert frame.cases["id"].to_list() == ["c1", "c2"]  # the other source's case is absent
    assert frame.cases["filed_at"].dtype == pl.Datetime("us", "UTC")
    assert frame.charges["person_id"].to_list() == [SURVIVOR] * 3  # the alias re-pointed
    assert frame.persons["id"].to_list() == [SURVIVOR]
    assert frame.persons.columns == ["id"]
    assert (frame.coverage_start, frame.coverage_end) == (date(2020, 1, 1), date(2020, 12, 31))
    assert frame.observable_outcomes == {"failure_to_appear", "new_case"}
    events = {
        (
            row["event_type"],
            row["event_at"],
            row["related_case_id"],
            row["id"].startswith("derived:"),
        )
        for row in frame.justice_events.iter_rows(named=True)
    }
    assert events == {
        ("failure_to_appear", _at(12), "c2", False),  # stored, any-case, re-pointed
        ("new_case", _at(1, 10), "c1", True),  # the earliest charge filing of c1
        ("new_case", _at(10, 10), "c2", True),
        ("new_charge", _at(1, 11), "c1", True),
        ("new_charge", _at(1, 10), "c1", True),
        ("new_charge", _at(10, 10), "c2", True),
        ("reconviction", _at(5), "c1", True),  # h1 convicted; h3 dismissed
    }
    assert frame.justice_events["person_id"].to_list() == [SURVIVOR] * len(events)
    assert "e2" not in frame.justice_events["id"].to_list()  # the stored new_case row is replaced


def test_code_version_carries_the_short_sha_when_known() -> None:
    sha = "0123456789abcdef0123456789abcdef01234567"  # pragma: allowlist secret
    assert code_version(Settings(env="test", git_sha=sha)).endswith("+0123456")
    assert "+" not in code_version(Settings(env="test", git_sha="unknown"))


def test_snapshot_module_loads_no_extension_and_names_no_restricted_table() -> None:
    source = Path(snapshot_module.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    body = code.split('"""', 2)[2]  # after the module docstring
    assert not re.search(r"\b(INSTALL|LOAD)\b", body)
    assert not re.search(
        r"\bduckdb\.(install|load)_extension\b|\.install_extension\(|\.load_extension\(", body
    )
    for table in RESTRICTED_TABLES:
        assert not re.search(rf"tables\[\"{table}\"\]", body), table
    assert set(SNAPSHOT_TABLES).isdisjoint(RESTRICTED_TABLES)


def test_no_module_under_metrics_names_a_restricted_attribute() -> None:
    for path in sorted(METRICS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for name in RESTRICTED_ATTRIBUTES:
            assert name not in text, f"{path.name} names {name}"
