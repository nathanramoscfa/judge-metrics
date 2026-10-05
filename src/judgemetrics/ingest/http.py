# src/judgemetrics/ingest/http.py
"""Bounded HTTPS downloads for connectors.

Every download is HTTPS-only (including after redirects), has a request
timeout, retries transport errors and retryable status codes with
exponential backoff, enforces a size cap while streaming, and sends
``If-None-Match`` / ``If-Modified-Since`` when the caller has validators
from a previous retrieval. A ``304`` comes back as ``Download.not_modified``
with no body.

Two forms: ``download`` holds the body in memory (small files: the FJC
export, a portal's metadata), and ``download_to_file`` (Phase 5) streams it
to a temporary file in a directory the caller owns, hashing while it
writes, so an export of any size costs one chunk of memory. A body over
the cap, a failed attempt, or any exception removes the partial file
before the error propagates. ``make_client`` refuses a non-HTTPS request
before it is sent, redirects included.
"""

from __future__ import annotations

import asyncio
import email.utils
import hashlib
import os
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from judgemetrics.ingest.base import (
    HEADER_CONTENT_LENGTH,
    HEADER_CONTENT_TYPE,
    HEADER_ETAG,
    HEADER_FINAL_URL,
    HEADER_LAST_MODIFIED,
    FetchError,
)

# Prefix of the temporary files ``download_to_file`` creates.
DOWNLOAD_PREFIX = "download-"

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_RETRIES = 3
DEFAULT_MAX_BYTES = 200 * 1024 * 1024
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
BACKOFF_SECONDS = (0.5, 1.0, 2.0)
USER_AGENT = "JudgeMetrics/0.1 (+https://github.com/nathanramoscfa/judge-metrics)"

Sleep = Callable[[float], Awaitable[None]]


class DownloadError(FetchError):
    """The download failed after every retry or with a non-retryable status."""


class DownloadTooLargeError(DownloadError):
    """The response exceeded the size cap."""


class InsecureUrlError(DownloadError):
    """The URL (or a redirect target) is not HTTPS."""


class _RetryableStatus(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(status_code)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class Download:
    status_code: int
    data: bytes
    headers: dict[str, str]

    @property
    def not_modified(self) -> bool:
        return self.status_code == 304


@dataclass(frozen=True, slots=True)
class FileDownload:
    """A body streamed to ``path`` (``None`` after a ``304``) with its sha256 and size."""

    status_code: int
    path: Path | None
    sha256: str | None
    size_bytes: int
    headers: dict[str, str]

    @property
    def not_modified(self) -> bool:
        return self.status_code == 304


def require_https(url: str) -> None:
    if urlsplit(url).scheme != "https":
        msg = f"refusing a non-HTTPS URL: {url!r}"
        raise InsecureUrlError(msg)


def conditional_headers(etag: str | None, last_modified: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers


def parse_http_date(value: str | None) -> datetime | None:
    """An RFC 7231 date (``Last-Modified``) as an aware UTC datetime, else ``None``."""
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def _refuse_insecure(request: httpx.Request) -> None:
    """Request hook: every request, each redirect hop included, must be HTTPS."""
    require_https(str(request.url))


def make_client(timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        event_hooks={"request": [_refuse_insecure]},
    )


def _header_subset(response: httpx.Response) -> dict[str, str]:
    subset = {HEADER_FINAL_URL: str(response.url)}
    for key, header in (
        (HEADER_ETAG, "etag"),
        (HEADER_LAST_MODIFIED, "last-modified"),
        (HEADER_CONTENT_TYPE, "content-type"),
        (HEADER_CONTENT_LENGTH, "content-length"),
    ):
        value = response.headers.get(header)
        if value:
            subset[key] = value
    return subset


async def download(
    client: httpx.AsyncClient,
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    retries: int = DEFAULT_RETRIES,
    sleep: Sleep = asyncio.sleep,
) -> Download:
    """GET ``url`` with the safeguards described in the module docstring."""
    require_https(url)
    request_headers = conditional_headers(etag, last_modified)
    attempt = 0
    while True:
        try:
            return await _download_once(client, url, request_headers, max_bytes)
        except (httpx.TransportError, _RetryableStatus) as exc:
            if attempt >= retries:
                detail = (
                    f"HTTP {exc.status_code}"
                    if isinstance(exc, _RetryableStatus)
                    else type(exc).__name__
                )
                msg = f"download failed after {attempt + 1} attempts ({detail}): {url}"
                raise DownloadError(msg) from exc
            await sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
            attempt += 1
        except httpx.HTTPStatusError as exc:
            msg = f"download failed (HTTP {exc.response.status_code}): {url}"
            raise DownloadError(msg) from exc


async def _download_once(
    client: httpx.AsyncClient, url: str, request_headers: dict[str, str], max_bytes: int
) -> Download:
    async with client.stream("GET", url, headers=request_headers) as response:
        require_https(str(response.url))
        if response.status_code == 304:
            return Download(304, b"", _header_subset(response))
        if response.status_code in RETRYABLE_STATUS:
            raise _RetryableStatus(response.status_code)
        response.raise_for_status()
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            msg = f"declared size {declared} exceeds the {max_bytes}-byte cap: {url}"
            raise DownloadTooLargeError(msg)
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > max_bytes:
                msg = f"response exceeds the {max_bytes}-byte cap: {url}"
                raise DownloadTooLargeError(msg)
        return Download(response.status_code, bytes(body), _header_subset(response))


async def download_to_file(
    client: httpx.AsyncClient,
    url: str,
    *,
    directory: Path,
    etag: str | None = None,
    last_modified: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    retries: int = DEFAULT_RETRIES,
    sleep: Sleep = asyncio.sleep,
) -> FileDownload:
    """GET ``url`` into a new temporary file under ``directory``, hashing while writing.

    The same safeguards as ``download``; the cap is checked against
    ``Content-Length`` before the body and against the bytes written while
    streaming. A ``304`` creates no file. The caller owns the returned file
    (the ingest runner's work directory removes it with the run).
    """
    require_https(url)
    if not directory.is_dir():
        msg = f"the download directory does not exist: {directory}"
        raise DownloadError(msg)
    request_headers = conditional_headers(etag, last_modified)
    attempt = 0
    while True:
        try:
            return await _download_file_once(client, url, request_headers, max_bytes, directory)
        except (httpx.TransportError, _RetryableStatus) as exc:
            if attempt >= retries:
                detail = (
                    f"HTTP {exc.status_code}"
                    if isinstance(exc, _RetryableStatus)
                    else type(exc).__name__
                )
                msg = f"download failed after {attempt + 1} attempts ({detail}): {url}"
                raise DownloadError(msg) from exc
            await sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
            attempt += 1
        except httpx.HTTPStatusError as exc:
            msg = f"download failed (HTTP {exc.response.status_code}): {url}"
            raise DownloadError(msg) from exc


async def _download_file_once(
    client: httpx.AsyncClient,
    url: str,
    request_headers: dict[str, str],
    max_bytes: int,
    directory: Path,
) -> FileDownload:
    async with client.stream("GET", url, headers=request_headers) as response:
        require_https(str(response.url))
        if response.status_code == 304:
            return FileDownload(304, None, None, 0, _header_subset(response))
        if response.status_code in RETRYABLE_STATUS:
            raise _RetryableStatus(response.status_code)
        response.raise_for_status()
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            msg = f"declared size {declared} exceeds the {max_bytes}-byte cap: {url}"
            raise DownloadTooLargeError(msg)
        descriptor, name = tempfile.mkstemp(prefix=DOWNLOAD_PREFIX, suffix=".part", dir=directory)
        path = Path(name)
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(descriptor, "wb") as handle:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        msg = f"response exceeds the {max_bytes}-byte cap: {url}"
                        raise DownloadTooLargeError(msg)
                    digest.update(chunk)
                    handle.write(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return FileDownload(
            response.status_code, path, digest.hexdigest(), size, _header_subset(response)
        )
