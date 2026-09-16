# tests/unit/test_store.py
"""The raw object store: key shape, immutability, same-payload no-op, URL parsing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from judgemetrics.config import Settings
from judgemetrics.ingest.base import sha256_hex
from judgemetrics.ingest.store import (
    FilesystemRawObjectStore,
    ImmutableObjectError,
    RawStoreError,
    S3RawObjectStore,
    check_key,
    content_type_for_key,
    object_key,
    open_raw_store,
    path_from_file_url,
)

pytestmark = pytest.mark.unit

RETRIEVED = datetime(2026, 9, 16, 18, 11, 38, tzinfo=UTC)
PAYLOAD = b'"nid","jid"\n"1","2"\n'
OTHER = b'"nid","jid"\n"3","4"\n'
SHA = sha256_hex(PAYLOAD)


def _key(data: bytes = PAYLOAD, ext: str = ".csv") -> str:
    return object_key("fjc", RETRIEVED, sha256_hex(data), ext)


def test_object_key_shape() -> None:
    key = _key()
    assert key == f"fjc/2026/09/{SHA}.csv"
    check_key(key)
    assert content_type_for_key(key) == "text/csv"


def test_object_key_uses_the_utc_month() -> None:
    east = timezone(timedelta(hours=5))
    key = object_key("fjc", datetime(2026, 10, 1, 1, 0, tzinfo=east), SHA, ".csv")
    assert key.startswith("fjc/2026/09/")


@pytest.mark.parametrize(
    ("source_id", "sha", "ext"),
    [
        ("Fjc", SHA, ".csv"),
        ("../fjc", SHA, ".csv"),
        ("fjc", "abc", ".csv"),
        ("fjc", SHA.upper(), ".csv"),
        ("fjc", SHA, ".CSV"),
        ("fjc", SHA, "/../x"),
    ],
)
def test_object_key_rejects_unsafe_parts(source_id: str, sha: str, ext: str) -> None:
    with pytest.raises(RawStoreError):
        object_key(source_id, RETRIEVED, sha, ext)


def test_object_key_rejects_naive_datetimes() -> None:
    with pytest.raises(RawStoreError, match="timezone-aware"):
        object_key("fjc", datetime(2026, 9, 16), SHA, ".csv")  # noqa: DTZ001


@pytest.mark.parametrize(
    "key",
    ["fjc/2026/09/../../etc/passwd", f"../{SHA}.csv", f"fjc/2026/9/{SHA}.csv", ""],
)
def test_check_key_rejects_malformed_keys(key: str) -> None:
    with pytest.raises(RawStoreError):
        check_key(key)


def test_filesystem_put_get_exists(tmp_path: Path) -> None:
    store = FilesystemRawObjectStore(tmp_path)
    key = _key()
    assert not store.exists(key)
    ref = store.put(PAYLOAD, key)
    assert ref.key == key
    assert ref.sha256 == SHA
    assert ref.size_bytes == len(PAYLOAD)
    assert store.exists(key)
    assert store.get(key) == PAYLOAD
    assert (tmp_path / "fjc" / "2026" / "09" / f"{SHA}.csv").read_bytes() == PAYLOAD


def test_filesystem_same_payload_is_a_no_op(tmp_path: Path) -> None:
    store = FilesystemRawObjectStore(tmp_path)
    key = _key()
    first = store.put(PAYLOAD, key)
    written = tmp_path / "fjc" / "2026" / "09" / f"{SHA}.csv"
    before = written.stat().st_mtime_ns
    second = store.put(PAYLOAD, key)
    assert second == first
    assert written.stat().st_mtime_ns == before
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == [written]


def test_filesystem_refuses_a_different_payload(tmp_path: Path) -> None:
    store = FilesystemRawObjectStore(tmp_path)
    key = _key()
    store.put(PAYLOAD, key)
    with pytest.raises(ImmutableObjectError, match="refusing to overwrite"):
        store.put(OTHER, key)
    assert store.get(key) == PAYLOAD
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == [f"{SHA}.csv"]


def test_filesystem_get_missing_key_raises(tmp_path: Path) -> None:
    store = FilesystemRawObjectStore(tmp_path)
    with pytest.raises(KeyError):
        store.get(_key())


def test_filesystem_rejects_malformed_keys(tmp_path: Path) -> None:
    store = FilesystemRawObjectStore(tmp_path)
    with pytest.raises(RawStoreError):
        store.put(PAYLOAD, "fjc/2026/09/../../escape.csv")
    assert not list(tmp_path.rglob("*.csv"))


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("file://./data/lake", Path("./data/lake")),
        ("file:///E:/lake", Path("E:/lake")),
        ("file:///var/lib/judgemetrics/lake", Path("/var/lib/judgemetrics/lake")),
        ("file://relative/dir", Path("relative/dir")),
    ],
)
def test_path_from_file_url(url: str, expected: Path) -> None:
    assert path_from_file_url(url) == expected


def test_path_from_file_url_needs_a_path() -> None:
    with pytest.raises(RawStoreError):
        path_from_file_url("file://")


def test_open_raw_store_filesystem(tmp_path: Path) -> None:
    settings = Settings(env="test", raw_store_url=f"file://{tmp_path.as_posix()}")
    store = open_raw_store(settings)
    assert isinstance(store, FilesystemRawObjectStore)
    assert store.root == tmp_path.resolve()


def test_open_raw_store_s3_parses_bucket_and_prefix() -> None:
    settings = Settings(
        env="test",
        raw_store_url="s3://judgemetrics-raw/lake/",
        s3_endpoint_url="http://localhost:9000",
        s3_access_key_id="placeholder",
        s3_secret_access_key="placeholder",  # noqa: S106 # pragma: allowlist secret
    )
    store = open_raw_store(settings)
    assert isinstance(store, S3RawObjectStore)
    assert store.bucket == "judgemetrics-raw"
    assert store.prefix == "lake/"
    # Nothing connects until the first operation.
    assert store._client is None  # noqa: SLF001


def test_open_raw_store_s3_requires_https_in_production() -> None:
    settings = Settings(
        env="production",
        raw_store_url="s3://judgemetrics-raw",
        s3_endpoint_url="http://minio:9000",
        s3_access_key_id="placeholder",
        s3_secret_access_key="placeholder",  # noqa: S106 # pragma: allowlist secret
    )
    with pytest.raises(RawStoreError, match="https"):
        open_raw_store(settings)


def test_open_raw_store_rejects_other_schemes() -> None:
    with pytest.raises(RawStoreError, match="file:// or s3://"):
        open_raw_store(Settings(env="test", raw_store_url="gs://bucket"))


def test_s3_store_rejects_bad_bucket_names() -> None:
    with pytest.raises(RawStoreError, match="bucket"):
        S3RawObjectStore("Bad_Bucket")
