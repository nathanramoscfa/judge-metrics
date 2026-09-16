# tests/integration/test_store_s3.py
"""The S3 raw-store backend against MinIO: the same immutability contract as the
filesystem backend (tests/unit/test_store.py).

Skipped unless `JUDGEMETRICS_RAW_STORE_URL` is an `s3://` bucket and the
endpoint and keys are configured (`.env` locally with `uv run poe up`; the
MinIO step in CI). Objects are written under the `contract-test` source id
and removed afterwards.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from judgemetrics.config import Settings
from judgemetrics.ingest.base import sha256_hex
from judgemetrics.ingest.store import (
    ImmutableObjectError,
    S3RawObjectStore,
    object_key,
    open_raw_store,
)

pytestmark = pytest.mark.integration

SOURCE_ID = "contract-test"
RETRIEVED = datetime(2026, 9, 16, 18, 0, tzinfo=UTC)
SKIP_REASON = (
    "S3 raw store not configured: set JUDGEMETRICS_RAW_STORE_URL=s3://<bucket>, "
    "JUDGEMETRICS_S3_ENDPOINT_URL, JUDGEMETRICS_S3_ACCESS_KEY_ID, "
    "JUDGEMETRICS_S3_SECRET_ACCESS_KEY (`uv run poe up` with a `.env`)"
)


def _payload() -> bytes:
    return f"contract-test,{uuid.uuid4()}\n".encode()


@pytest.fixture
def s3_store() -> Iterator[S3RawObjectStore]:
    settings = Settings()
    if not settings.raw_store_url.startswith("s3://") or not (
        settings.s3_endpoint_url and settings.s3_access_key_id and settings.s3_secret_access_key
    ):
        pytest.skip(SKIP_REASON)
    store = open_raw_store(settings)
    assert isinstance(store, S3RawObjectStore)
    from botocore.exceptions import ClientError

    try:
        store.client.head_bucket(Bucket=store.bucket)
    except ClientError:
        store.client.create_bucket(Bucket=store.bucket)
    yield store
    prefix = f"{store.prefix}{SOURCE_ID}/"
    listing = store.client.list_objects_v2(Bucket=store.bucket, Prefix=prefix)
    for item in listing.get("Contents", []):
        if "Key" in item:
            store.client.delete_object(Bucket=store.bucket, Key=item["Key"])


def test_put_get_exists_round_trip(s3_store: S3RawObjectStore) -> None:
    data = _payload()
    key = object_key(SOURCE_ID, RETRIEVED, sha256_hex(data), ".csv")
    assert not s3_store.exists(key)
    ref = s3_store.put(data, key)
    assert ref.key == key
    assert ref.sha256 == sha256_hex(data)
    assert ref.size_bytes == len(data)
    assert s3_store.exists(key)
    assert s3_store.get(key) == data
    head = s3_store.client.head_object(Bucket=s3_store.bucket, Key=f"{s3_store.prefix}{key}")
    assert head["Metadata"]["sha256"] == ref.sha256
    assert head["ContentType"] == "text/csv"


def test_same_payload_is_a_no_op(s3_store: S3RawObjectStore) -> None:
    data = _payload()
    key = object_key(SOURCE_ID, RETRIEVED, sha256_hex(data), ".csv")
    first = s3_store.put(data, key)
    second = s3_store.put(data, key)
    assert first == second
    assert s3_store.get(key) == data


def test_different_payload_is_refused(s3_store: S3RawObjectStore) -> None:
    data = _payload()
    key = object_key(SOURCE_ID, RETRIEVED, sha256_hex(data), ".csv")
    s3_store.put(data, key)
    with pytest.raises(ImmutableObjectError, match="refusing to overwrite"):
        s3_store.put(_payload(), key)
    assert s3_store.get(key) == data


def test_missing_key(s3_store: S3RawObjectStore) -> None:
    key = object_key(SOURCE_ID, RETRIEVED, sha256_hex(_payload()), ".csv")
    assert not s3_store.exists(key)
    with pytest.raises(KeyError):
        s3_store.get(key)
