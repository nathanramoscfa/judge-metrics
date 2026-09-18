# tests/unit/test_logging.py
"""The logging scrubber and renderer selection."""

from __future__ import annotations

import io
import json
import logging as stdlib_logging
from typing import Any

import pytest
import structlog

from judgemetrics.config import Settings
from judgemetrics.logging import (
    REDACTED,
    SENSITIVE_KEYS,
    configure_logging,
    get_logger,
    is_sensitive_key,
    scrub_sensitive,
    scrub_value,
)

pytestmark = pytest.mark.unit

DENYLIST = {
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "api_key",
    "access_key",
    "cookie",
    "person_id",
    "case_participant_id",
    "identifier_value",
    "encrypted_value",
    "requester_contact",
    "pepper",
    "identifier_pepper",
    "value_hash",
    "date_of_birth",
    "full_name",
}


def test_documented_denylist_is_complete() -> None:
    assert SENSITIVE_KEYS == frozenset(DENYLIST)


@pytest.mark.parametrize("key", sorted(DENYLIST))
def test_every_denylisted_key_is_redacted(key: str) -> None:
    event = scrub_sensitive(None, "info", {"event": "x", key: "value"})
    assert event[key] == REDACTED


@pytest.mark.parametrize(
    "key",
    ["PASSWORD", "db_password", "X-API-Key", "aws.secret.access.key", "Authorization", "Cookie"],
)
def test_case_separator_and_compound_keys_match(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize("key", ["event", "request_id", "public_person_key", "judge_id", "path"])
def test_ordinary_keys_pass_through(key: str) -> None:
    assert not is_sensitive_key(key)


def test_scrubs_recursively_through_dicts_lists_and_tuples() -> None:
    payload: dict[str, Any] = {
        "event": "ingest",
        "request": {"headers": {"Authorization": "Bearer abc", "Accept": "*/*"}},
        "rows": [
            {"person_id": "p-1", "public_person_key": "k-1"},
            ({"token": "t"}, "plain"),
        ],
        "nested": {"deeper": {"identifier_value": "ssn"}},
    }
    scrubbed = scrub_sensitive(None, "info", payload)
    assert scrubbed["request"]["headers"] == {"Authorization": REDACTED, "Accept": "*/*"}
    assert scrubbed["rows"][0] == {"person_id": REDACTED, "public_person_key": "k-1"}
    assert scrubbed["rows"][1] == ({"token": REDACTED}, "plain")
    assert scrubbed["nested"]["deeper"]["identifier_value"] == REDACTED
    assert scrubbed["event"] == "ingest"


def test_scrub_value_leaves_scalars_alone() -> None:
    assert scrub_value("secret") == "secret"  # a value, not a key
    assert scrub_value(3) == 3


def _capture(settings: Settings) -> io.StringIO:
    configure_logging(settings)
    stream = io.StringIO()
    root = stdlib_logging.getLogger()
    ours = [h for h in root.handlers if type(h).__name__ == "_Handler"]
    assert len(ours) == 1, "configure_logging must install exactly one handler"
    handler = ours[0]
    assert isinstance(handler, stdlib_logging.StreamHandler)
    handler.setStream(stream)
    return stream


def test_json_renderer_emits_one_object_per_line_with_bound_context() -> None:
    stream = _capture(Settings(env="test", log_format="json"))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="req-123")
    try:
        get_logger("judgemetrics.test").info(
            "hello",
            password="hunter2",  # noqa: S106  # pragma: allowlist secret
            judge_id="j-1",
        )
    finally:
        structlog.contextvars.clear_contextvars()
    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "hello"
    assert record["level"] == "info"
    assert record["logger"] == "judgemetrics.test"
    assert record["request_id"] == "req-123"
    assert record["judge_id"] == "j-1"
    assert record["password"] == REDACTED
    assert record["timestamp"].endswith("Z") or "+00:00" in record["timestamp"]


def test_console_renderer_is_not_json() -> None:
    stream = _capture(Settings(env="test", log_format="console"))
    get_logger("judgemetrics.test").warning("console-line", token="abc")  # noqa: S106
    output = stream.getvalue()
    assert "console-line" in output
    assert "abc" not in output
    assert REDACTED in output
    with pytest.raises(json.JSONDecodeError):
        json.loads(output.strip())


def test_stdlib_loggers_are_scrubbed_too() -> None:
    stream = _capture(Settings(env="test", log_format="json"))
    stdlib_logging.getLogger("uvicorn.error").error("boom", extra={"api_key": "k"})
    record = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert record["event"] == "boom"
    assert record["logger"] == "uvicorn.error"
    assert record["api_key"] == REDACTED
