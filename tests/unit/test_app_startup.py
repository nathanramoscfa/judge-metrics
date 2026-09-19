# tests/unit/test_app_startup.py
"""``create_app`` and the contact key: required outside the test environment, lazy module app.

An API that cannot encrypt a correction must not start: outside
``env == test``, ``create_app`` raises ``ContactKeyMissingError`` naming
``JUDGEMETRICS_CORRECTION_CONTACT_KEY`` when the key is unset or is not a
Fernet key (the ``.env.example`` placeholder), and never echoes the value.
Under ``env == test`` the app builds without a key (the route answers 503
instead, ``tests/integration/test_api_corrections.py``). The module
attribute ``judgemetrics.main.app`` is built lazily, so importing the
module for ``create_app`` never constructs the process app. The
corrections limiter follows the same on/off rule as the search limiter.
"""

from __future__ import annotations

import importlib

import pytest
from cryptography.fernet import Fernet

from judgemetrics.api.ratelimit import TokenBucketLimiter
from judgemetrics.config import Settings
from judgemetrics.main import create_app
from judgemetrics.security.crypto import (
    CONTACT_KEY_VARIABLE,
    ContactKeyMissingError,
    require_contact_key,
)

pytestmark = pytest.mark.unit

UNREACHABLE_URL = (
    "postgresql+psycopg://nobody:placeholder@127.0.0.1:1/judgemetrics"  # pragma: allowlist secret
)


def _settings(env: str, **overrides: object) -> Settings:
    return Settings(env=env, database_url=UNREACHABLE_URL, log_format="json", **overrides)


@pytest.mark.parametrize("env", ["local", "production"])
def test_create_app_fails_fast_without_a_key_outside_test(
    env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(CONTACT_KEY_VARIABLE, raising=False)
    with pytest.raises(ContactKeyMissingError, match=CONTACT_KEY_VARIABLE):
        create_app(_settings(env, correction_contact_key=None))


@pytest.mark.parametrize("value", ["change-me", "", "not base64 at all", "YWJj"])
def test_create_app_rejects_an_unusable_key_without_echoing_it(value: str) -> None:
    with pytest.raises(ContactKeyMissingError) as caught:
        create_app(_settings("local", correction_contact_key=value))
    assert CONTACT_KEY_VARIABLE in str(caught.value)
    if value:
        assert value not in str(caught.value)


def test_create_app_builds_with_a_valid_key_and_without_one_under_test() -> None:
    key = Fernet.generate_key().decode("ascii")
    app = create_app(_settings("local", correction_contact_key=key))
    try:
        assert app.state.corrections_limiter is not None
        assert isinstance(app.state.corrections_limiter, TokenBucketLimiter)
        assert app.state.corrections_limiter.per_hour == 5
        assert app.state.corrections_limiter.burst == 5
    finally:
        app.state.engine.dispose()
    under_test = create_app(_settings("test", correction_contact_key=None))
    try:
        assert under_test.state.corrections_limiter is None
        assert under_test.state.search_limiter is None
    finally:
        under_test.state.engine.dispose()
    enabled = create_app(_settings("test", corrections_rate_limit_enabled=True))
    try:
        assert enabled.state.corrections_limiter is not None
    finally:
        enabled.state.engine.dispose()


def test_require_contact_key_accepts_a_fernet_key_only() -> None:
    require_contact_key(_settings("test", correction_contact_key=Fernet.generate_key().decode()))
    with pytest.raises(ContactKeyMissingError, match="not configured"):
        require_contact_key(_settings("test", correction_contact_key=None))
    with pytest.raises(ContactKeyMissingError, match="not a valid Fernet key"):
        require_contact_key(_settings("test", correction_contact_key="change-me"))


def test_module_app_is_built_lazily() -> None:
    main = importlib.import_module("judgemetrics.main")
    assert "app" not in vars(main)
    assert "app" in main.__all__
    with pytest.raises(AttributeError):
        _ = main.no_such_attribute
