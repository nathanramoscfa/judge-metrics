# tests/unit/test_streaming_download.py
"""The streamed download: a body to a temporary file, hashed while written, bounded, cleaned up."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest

from judgemetrics.ingest.base import sha256_hex
from judgemetrics.ingest.http import (
    DOWNLOAD_PREFIX,
    DownloadError,
    DownloadTooLargeError,
    FileDownload,
    InsecureUrlError,
    download_to_file,
    make_client,
)

pytestmark = pytest.mark.unit

URL = "https://data.example.org/export.csv"
BODY = b"CASE_ID,CASE_PARTICIPANT_ID\n1,2\n3,4\n" * 50

Handler = Callable[[httpx.Request], httpx.Response]


async def _no_sleep(_: float) -> None:
    return None


class _Chunks(httpx.AsyncByteStream):
    """A response body in chunks; raises ``fail`` after ``fail_after`` chunks."""

    def __init__(
        self, chunks: list[bytes], *, fail_after: int | None = None, fail: Exception | None = None
    ) -> None:
        self._chunks = chunks
        self._fail_after = fail_after
        self._fail = fail

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for index, chunk in enumerate(self._chunks):
            if self._fail is not None and index == self._fail_after:
                raise self._fail
            yield chunk


def _client(handler: Handler, *, hooked: bool = False) -> httpx.AsyncClient:
    hooks = make_client().event_hooks if hooked else {}
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True, event_hooks=hooks
    )


def _run(handler: Handler, directory: Path, **kwargs: object) -> FileDownload:
    async def go() -> FileDownload:
        async with _client(handler, hooked=bool(kwargs.pop("hooked", False))) as client:
            return await download_to_file(
                client,
                str(kwargs.pop("url", URL)),
                directory=directory,
                sleep=_no_sleep,
                **kwargs,  # type: ignore[arg-type]
            )

    return asyncio.run(go())


def _files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*") if path.is_file())


def test_the_body_streams_to_a_file_with_its_digest_and_size(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Chunks([BODY[:100], BODY[100:700], BODY[700:]]))

    result = _run(handler, tmp_path)
    assert result.path is not None
    assert result.path.parent == tmp_path
    assert result.path.name.startswith(DOWNLOAD_PREFIX)
    assert result.path.read_bytes() == BODY
    assert result.sha256 == sha256_hex(BODY)
    assert result.size_bytes == len(BODY)
    assert not result.not_modified
    assert result.headers["final_url"] == URL
    assert _files(tmp_path) == [result.path]


def test_a_body_over_the_cap_fails_mid_stream_and_leaves_no_file(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Chunks([b"x" * 6, b"x" * 6, b"x" * 6]))

    with pytest.raises(DownloadTooLargeError, match="10-byte cap"):
        _run(handler, tmp_path, max_bytes=10)
    assert _files(tmp_path) == []


def test_a_declared_size_over_the_cap_fails_before_any_file(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5, headers={"Content-Length": "999999"})

    with pytest.raises(DownloadTooLargeError, match="declared size"):
        _run(handler, tmp_path, max_bytes=10)
    assert _files(tmp_path) == []


def test_validators_are_sent_and_a_304_creates_no_file(tmp_path: Path) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(304, headers={"ETag": '"abc"'})

    result = _run(handler, tmp_path, etag='"abc"', last_modified="Thu, 02 Apr 2026 14:23:39 GMT")
    assert seen["if-none-match"] == '"abc"'
    assert seen["if-modified-since"] == "Thu, 02 Apr 2026 14:23:39 GMT"
    assert result.not_modified
    assert result.path is None and result.sha256 is None and result.size_bytes == 0
    assert _files(tmp_path) == []


def test_a_failed_attempt_is_removed_and_the_retry_succeeds(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            broken = _Chunks([b"partial", b"never"], fail_after=1, fail=httpx.ReadError("cut"))
            return httpx.Response(200, stream=broken)
        return httpx.Response(200, content=BODY)

    result = _run(handler, tmp_path)
    assert len(calls) == 2
    assert result.path is not None and result.path.read_bytes() == BODY
    assert _files(tmp_path) == [result.path]


def test_retries_are_bounded_and_leave_no_file(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        broken = _Chunks([b"partial", b"never"], fail_after=1, fail=httpx.ReadError("cut"))
        return httpx.Response(200, stream=broken)

    with pytest.raises(DownloadError, match="after 3 attempts"):
        _run(handler, tmp_path, retries=2)
    assert _files(tmp_path) == []


def test_an_unexpected_exception_mid_stream_removes_the_file(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        broken = _Chunks([b"partial", b"never"], fail_after=1, fail=RuntimeError("boom"))
        return httpx.Response(200, stream=broken)

    with pytest.raises(RuntimeError, match="boom"):
        _run(handler, tmp_path)
    assert _files(tmp_path) == []


def test_a_client_error_is_not_retried(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    with pytest.raises(DownloadError, match="404"):
        _run(handler, tmp_path)
    assert len(calls) == 1
    assert _files(tmp_path) == []


def test_a_plain_http_url_is_refused(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        return httpx.Response(200, content=BODY)

    with pytest.raises(InsecureUrlError):
        _run(handler, tmp_path, url="http://data.example.org/export.csv")
    assert _files(tmp_path) == []


def test_a_non_https_redirect_is_refused_before_it_is_requested(tmp_path: Path) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.scheme == "https":
            return httpx.Response(302, headers={"Location": "http://data.example.org/x.csv"})
        return httpx.Response(200, content=BODY)  # pragma: no cover - the hook refuses first

    with pytest.raises(InsecureUrlError):
        _run(handler, tmp_path, hooked=True)
    assert requested == [URL]
    assert _files(tmp_path) == []


def test_a_non_https_final_url_is_refused_without_the_hook(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.scheme == "https":
            return httpx.Response(302, headers={"Location": "http://data.example.org/x.csv"})
        return httpx.Response(200, content=BODY)

    with pytest.raises(InsecureUrlError):
        _run(handler, tmp_path)
    assert _files(tmp_path) == []


def test_the_directory_must_exist(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        return httpx.Response(200, content=BODY)

    with pytest.raises(DownloadError, match="does not exist"):
        _run(handler, tmp_path / "missing")
