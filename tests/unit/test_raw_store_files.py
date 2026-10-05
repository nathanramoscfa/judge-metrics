# tests/unit/test_raw_store_files.py
"""``put_file`` and ``get_file`` on the filesystem backend: chunked, immutable, verified, tidy.

The S3 backend's managed transfer runs against MinIO in
``tests/integration/test_store_s3.py`` (CI's ``python`` job starts MinIO).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from judgemetrics.ingest.base import CHUNK_BYTES, sha256_hex
from judgemetrics.ingest.store import (
    FilesystemRawObjectStore,
    ImmutableObjectError,
    RawStoreError,
    key_sha256,
    object_key,
)

pytestmark = pytest.mark.unit

RETRIEVED = datetime(2026, 10, 5, 17, 0, tzinfo=UTC)
# Larger than one chunk, so the copy loops.
PAYLOAD = b"CASE_ID,CASE_PARTICIPANT_ID\n" + b"1,2\n" * (CHUNK_BYTES // 2)
OTHER = b"CASE_ID,CASE_PARTICIPANT_ID\n3,4\n"


def _key(data: bytes) -> str:
    return object_key("cook_sao", RETRIEVED, sha256_hex(data), ".csv")


def _source(tmp_path: Path, data: bytes, name: str = "export.csv") -> Path:
    source = tmp_path / "work" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)
    return source


def _lake_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def test_key_sha256_reads_the_digest_the_key_names() -> None:
    assert key_sha256(_key(PAYLOAD)) == sha256_hex(PAYLOAD)
    with pytest.raises(RawStoreError):
        key_sha256("cook_sao/2026/10/not-a-digest.csv")


def test_put_file_copies_the_file(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    store = FilesystemRawObjectStore(lake)
    key = _key(PAYLOAD)
    ref = store.put_file(_source(tmp_path, PAYLOAD), key)
    assert ref.key == key
    assert ref.sha256 == sha256_hex(PAYLOAD)
    assert ref.size_bytes == len(PAYLOAD)
    assert store.exists(key)
    target = lake / "cook_sao" / "2026" / "10" / f"{sha256_hex(PAYLOAD)}.csv"
    assert target.read_bytes() == PAYLOAD
    assert _lake_files(lake) == [target]


def test_put_file_with_the_same_digest_is_a_no_op(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    store = FilesystemRawObjectStore(lake)
    key = _key(PAYLOAD)
    first = store.put_file(_source(tmp_path, PAYLOAD), key)
    target = _lake_files(lake)[0]
    before = target.stat().st_mtime_ns
    second = store.put_file(_source(tmp_path, PAYLOAD, "again.csv"), key)
    assert second == first
    assert target.stat().st_mtime_ns == before
    assert _lake_files(lake) == [target]


def test_put_file_refuses_a_different_digest_at_an_existing_key(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    store = FilesystemRawObjectStore(lake)
    key = _key(PAYLOAD)
    store.put_file(_source(tmp_path, PAYLOAD), key)
    with pytest.raises(ImmutableObjectError, match="refusing to overwrite"):
        store.put_file(_source(tmp_path, OTHER, "other.csv"), key)
    assert store.get(key) == PAYLOAD
    assert len(_lake_files(lake)) == 1


def test_put_file_refuses_a_file_that_does_not_hash_to_its_key(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    store = FilesystemRawObjectStore(lake)
    with pytest.raises(RawStoreError, match="does not hash"):
        store.put_file(_source(tmp_path, OTHER), _key(PAYLOAD))
    assert _lake_files(lake) == []


def test_put_file_removes_its_temporary_file_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lake = tmp_path / "lake"
    store = FilesystemRawObjectStore(lake)

    def broken_replace(src: object, dst: object) -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError, match="disk gone"):
        store.put_file(_source(tmp_path, PAYLOAD), _key(PAYLOAD))
    assert _lake_files(lake) == []


def test_get_file_streams_the_object_back_verified(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    store = FilesystemRawObjectStore(lake)
    key = _key(PAYLOAD)
    store.put(PAYLOAD, key)
    dest_dir = tmp_path / "read"
    dest_dir.mkdir()
    ref = store.get_file(key, dest_dir / "intake.csv")
    assert ref.sha256 == sha256_hex(PAYLOAD) and ref.size_bytes == len(PAYLOAD)
    assert (dest_dir / "intake.csv").read_bytes() == PAYLOAD
    assert _lake_files(dest_dir) == [dest_dir / "intake.csv"]


def test_get_file_refuses_a_tampered_object_and_leaves_nothing(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    store = FilesystemRawObjectStore(lake)
    key = _key(PAYLOAD)
    store.put(PAYLOAD, key)
    target = _lake_files(lake)[0]
    os.chmod(target, 0o644)
    target.write_bytes(OTHER)
    dest_dir = tmp_path / "read"
    dest_dir.mkdir()
    with pytest.raises(RawStoreError, match="does not match its digest"):
        store.get_file(key, dest_dir / "intake.csv")
    assert _lake_files(dest_dir) == []


def test_get_file_of_a_missing_key_raises_key_error(tmp_path: Path) -> None:
    store = FilesystemRawObjectStore(tmp_path / "lake")
    with pytest.raises(KeyError):
        store.get_file(_key(PAYLOAD), tmp_path / "intake.csv")
    assert not (tmp_path / "intake.csv").exists()
