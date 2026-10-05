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

Files (Phase 5): ``put_file`` stores a file without loading it — a chunked
copy to a temporary file beside the target, fsynced and renamed, on the
filesystem; boto3's managed multipart transfer with the sha256 in the
object metadata on S3 — and ``get_file`` streams an object back to a
local file and verifies it against the digest its key names, so a corpus
of gigabyte exports is stored and re-read in bounded memory. Both refuse a
file that does not hash to its key's digest, and both compare an existing
object by its stored digest (the key's on the filesystem, the metadata on
S3), never by reading it whole. Every temporary file is removed on success
and on failure.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from judgemetrics.config import Settings
from judgemetrics.ingest.base import CHUNK_BYTES, sha256_file, sha256_hex

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXT = re.compile(r"^(\.[a-z0-9]{1,16}){0,3}$")
_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}/\d{4}/\d{2}/[0-9a-f]{64}(\.[a-z0-9]{1,16}){0,3}$")
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_DRIVE_PATH = re.compile(r"^/[A-Za-z]:")
# Part size of the S3 managed transfer (boto3 switches to multipart above it).
S3_PART_BYTES = 64 * 1024 * 1024
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


def key_sha256(key: str) -> str:
    """The sha256 a well-formed key names (``<source>/<yyyy>/<mm>/<sha256><ext>``)."""
    check_key(key)
    return key.rsplit("/", 1)[1][:64]


def _require_key_digest(digest: str, key: str) -> None:
    if digest != key_sha256(key):
        msg = f"the file does not hash to the digest its key names: {key!r}"
        raise RawStoreError(msg)


def _temporary_beside(target: Path) -> Path:
    return target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")


def _verified_replace(temp: Path, dest: Path, key: str) -> ObjectRef:
    """Move ``temp`` to ``dest`` when it hashes to ``key``'s digest; remove it otherwise."""
    digest, size = sha256_file(temp)
    if digest != key_sha256(key):
        temp.unlink(missing_ok=True)
        msg = f"stored raw object {key!r} does not match its digest"
        raise RawStoreError(msg)
    os.replace(temp, dest)
    return ObjectRef(key=key, sha256=digest, size_bytes=size)


class RawObjectStore(Protocol):
    def put(self, data: bytes, key: str) -> ObjectRef: ...

    def put_file(self, path: Path, key: str) -> ObjectRef: ...

    def get(self, key: str) -> bytes: ...

    def get_file(self, key: str, dest: Path) -> ObjectRef: ...

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

    def put_file(self, path: Path, key: str) -> ObjectRef:
        """Copy ``path`` to ``key`` in chunks; the same digest is a no-op, another refused.

        An existing object's digest is the one its key names (the store
        writes nothing that does not hash to its key), so it is never read.
        """
        target = self._path(key)
        if target.exists():
            digest, _ = sha256_file(path)
            if digest == key_sha256(key):
                return ObjectRef(key=key, sha256=digest, size_bytes=target.stat().st_size)
            msg = f"refusing to overwrite raw object {key!r} with different content"
            raise ImmutableObjectError(msg)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = _temporary_beside(target)
        hasher = hashlib.sha256()
        size = 0
        try:
            with path.open("rb") as source, temp.open("wb") as handle:
                for chunk in iter(lambda: source.read(CHUNK_BYTES), b""):
                    hasher.update(chunk)
                    size += len(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            _require_key_digest(hasher.hexdigest(), key)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return ObjectRef(key=key, sha256=hasher.hexdigest(), size_bytes=size)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise KeyError(key)
        return path.read_bytes()

    def get_file(self, key: str, dest: Path) -> ObjectRef:
        """Copy the object at ``key`` to ``dest`` in chunks, verified against its digest."""
        path = self._path(key)
        if not path.is_file():
            raise KeyError(key)
        temp = _temporary_beside(dest)
        try:
            with path.open("rb") as source, temp.open("wb") as handle:
                for chunk in iter(lambda: source.read(CHUNK_BYTES), b""):
                    handle.write(chunk)
            return _verified_replace(temp, dest, key)
        finally:
            temp.unlink(missing_ok=True)

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

    def put_file(self, path: Path, key: str) -> ObjectRef:
        """Upload ``path`` with boto3's managed (multipart) transfer, sha256 in the metadata."""
        from boto3.s3.transfer import TransferConfig

        digest, size = sha256_file(path)
        existing = self._existing_sha256(key)
        if existing is not None:
            if existing == digest:
                return ObjectRef(key=key, sha256=digest, size_bytes=size)
            msg = f"refusing to overwrite raw object {key!r} with different content"
            raise ImmutableObjectError(msg)
        _require_key_digest(digest, key)
        self.client.upload_file(
            Filename=str(path),
            Bucket=self.bucket,
            Key=self._object_key(key),
            ExtraArgs={"ContentType": content_type_for_key(key), "Metadata": {"sha256": digest}},
            Config=TransferConfig(multipart_chunksize=S3_PART_BYTES, max_concurrency=4),
        )
        return ObjectRef(key=key, sha256=digest, size_bytes=size)

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._object_key(key))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                raise KeyError(key) from exc
            raise
        return response["Body"].read()

    def get_file(self, key: str, dest: Path) -> ObjectRef:
        """Download the object at ``key`` to ``dest`` (managed transfer), verified by digest."""
        from boto3.s3.transfer import TransferConfig
        from botocore.exceptions import ClientError

        temp = _temporary_beside(dest)
        try:
            try:
                self.client.download_file(
                    Bucket=self.bucket,
                    Key=self._object_key(key),
                    Filename=str(temp),
                    Config=TransferConfig(multipart_chunksize=S3_PART_BYTES, max_concurrency=4),
                )
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                    raise KeyError(key) from exc
                raise
            return _verified_replace(temp, dest, key)
        finally:
            temp.unlink(missing_ok=True)

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
