# src/judgemetrics/ingest/store.py
"""The immutable, content-addressed raw object lake.

Keys are ``<source_id>/<yyyy>/<mm>/<sha256><ext>`` (year and month of the
retrieval, UTC), so a key names exactly one payload: ``put`` refuses to
write a different payload to an existing key (``ImmutableObjectError``)
and treats the same payload as a no-op that returns the existing
reference. The key is derived from the hash, never from a source-supplied
file name, so nothing in a source can steer a write elsewhere.

Two backends implement ``RawObjectStore``: ``FilesystemRawObjectStore``
(``file://``, atomic write-then-rename) and ``S3RawObjectStore``
(``s3://bucket[/prefix]`` through the configured endpoint — MinIO locally).
``open_raw_store(settings)`` picks one from ``JUDGEMETRICS_RAW_STORE_URL``.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from judgemetrics.config import Settings
from judgemetrics.ingest.base import sha256_hex

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXT = re.compile(r"^(\.[a-z0-9]{1,16}){0,3}$")
_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}/\d{4}/\d{2}/[0-9a-f]{64}(\.[a-z0-9]{1,16}){0,3}$")
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_DRIVE_PATH = re.compile(r"^/[A-Za-z]:")
_CONTENT_TYPES = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".xml": "application/xml",
    ".txt": "text/plain",
    ".parquet": "application/vnd.apache.parquet",
}


class RawStoreError(RuntimeError):
    """Configuration or backend failure of the raw store."""


class ImmutableObjectError(RawStoreError):
    """A different payload was written to an existing key."""


@dataclass(frozen=True, slots=True)
class ObjectRef:
    key: str
    sha256: str
    size_bytes: int


def object_key(source_id: str, retrieved_at: datetime, sha256: str, ext: str = "") -> str:
    """``<source_id>/<yyyy>/<mm>/<sha256><ext>`` for a retrieval instant (UTC)."""
    if not _SOURCE_ID.match(source_id):
        msg = f"invalid source id for an object key: {source_id!r}"
        raise RawStoreError(msg)
    if not _SHA256.match(sha256):
        msg = "object keys need a lower-case hex sha256"
        raise RawStoreError(msg)
    if not _EXT.match(ext):
        msg = f"invalid object extension: {ext!r}"
        raise RawStoreError(msg)
    if retrieved_at.tzinfo is None:
        msg = "retrieved_at must be timezone-aware"
        raise RawStoreError(msg)
    moment = retrieved_at.astimezone(UTC)
    return f"{source_id}/{moment.year:04d}/{moment.month:02d}/{sha256}{ext}"


def check_key(key: str) -> None:
    if not _KEY.match(key):
        msg = f"malformed object key: {key!r}"
        raise RawStoreError(msg)


def content_type_for_key(key: str) -> str:
    return _CONTENT_TYPES.get(Path(key).suffix, "application/octet-stream")


class RawObjectStore(Protocol):
    def put(self, data: bytes, key: str) -> ObjectRef: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...


class FilesystemRawObjectStore:
    """Objects under ``root``; a write is a temp file renamed into place."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        check_key(key)
        path = (self.root / Path(*key.split("/"))).resolve()
        if self.root not in path.parents:
            msg = f"object key escapes the store root: {key!r}"
            raise RawStoreError(msg)
        return path

    def put(self, data: bytes, key: str) -> ObjectRef:
        digest = sha256_hex(data)
        path = self._path(key)
        if path.exists():
            existing = path.read_bytes()
            if sha256_hex(existing) == digest:
                return ObjectRef(key=key, sha256=digest, size_bytes=len(existing))
            msg = f"refusing to overwrite raw object {key!r} with different content"
            raise ImmutableObjectError(msg)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return ObjectRef(key=key, sha256=digest, size_bytes=len(data))

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise KeyError(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


class S3RawObjectStore:
    """Objects in an S3-compatible bucket; the sha256 travels as object metadata."""

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "",
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        region_name: str = "us-east-1",
        client: S3Client | None = None,
    ) -> None:
        if not _BUCKET.match(bucket):
            msg = f"invalid bucket name: {bucket!r}"
            raise RawStoreError(msg)
        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self._endpoint_url = endpoint_url
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._region_name = region_name
        self._client = client

    @property
    def client(self) -> S3Client:
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint_url,
                aws_access_key_id=self._access_key_id,
                aws_secret_access_key=self._secret_access_key,
                region_name=self._region_name,
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    connect_timeout=5,
                    read_timeout=60,
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
        return self._client

    def _object_key(self, key: str) -> str:
        check_key(key)
        return f"{self.prefix}{key}"

    def _existing_sha256(self, key: str) -> str | None:
        """The stored object's sha256, or ``None`` when the key does not exist."""
        from botocore.exceptions import ClientError

        try:
            head = self.client.head_object(Bucket=self.bucket, Key=self._object_key(key))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        recorded = head.get("Metadata", {}).get("sha256")
        if recorded and _SHA256.match(recorded):
            return recorded
        return sha256_hex(self.get(key))

    def put(self, data: bytes, key: str) -> ObjectRef:
        digest = sha256_hex(data)
        existing = self._existing_sha256(key)
        if existing is not None:
            if existing == digest:
                return ObjectRef(key=key, sha256=digest, size_bytes=len(data))
            msg = f"refusing to overwrite raw object {key!r} with different content"
            raise ImmutableObjectError(msg)
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._object_key(key),
            Body=data,
            ContentType=content_type_for_key(key),
            Metadata={"sha256": digest},
        )
        return ObjectRef(key=key, sha256=digest, size_bytes=len(data))

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._object_key(key))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                raise KeyError(key) from exc
            raise
        return response["Body"].read()

    def exists(self, key: str) -> bool:
        return self._existing_sha256(key) is not None


def path_from_file_url(url: str) -> Path:
    """``file://./data/lake`` → ``./data/lake``; ``file:///E:/lake`` → ``E:/lake``."""
    rest = url.removeprefix("file://")
    if _DRIVE_PATH.match(rest):
        rest = rest[1:]
    if not rest:
        msg = "file:// raw store URL needs a path"
        raise RawStoreError(msg)
    return Path(rest)


def open_raw_store(settings: Settings) -> RawObjectStore:
    """The store named by ``settings.raw_store_url``."""
    url = settings.raw_store_url.strip()
    if url.startswith("file://"):
        return FilesystemRawObjectStore(path_from_file_url(url))
    if url.startswith("s3://"):
        bucket, _, prefix = url.removeprefix("s3://").partition("/")
        endpoint = settings.s3_endpoint_url
        if settings.env == "production" and endpoint and not endpoint.startswith("https://"):
            msg = "the S3 endpoint must use https in production"
            raise RawStoreError(msg)
        secret = settings.s3_secret_access_key
        return S3RawObjectStore(
            bucket,
            prefix=prefix,
            endpoint_url=endpoint,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=secret.get_secret_value() if secret is not None else None,
        )
    msg = "JUDGEMETRICS_RAW_STORE_URL must start with file:// or s3://"
    raise RawStoreError(msg)
