# tests/unit/test_settings.py
"""Settings: the JUDGEMETRICS_ prefix, SecretStr handling, and `.env` gating."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from judgemetrics.config import Settings, get_settings

pytestmark = pytest.mark.unit

APP_URL = "postgresql+psycopg://judgemetrics_app:placeholder@db.example:5432/judgemetrics"  # pragma: allowlist secret
ADMIN_URL = "postgresql+psycopg://judgemetrics_admin:placeholder@db.example:5432/judgemetrics"  # pragma: allowlist secret
LEGACY_DRIVER_URL = "postgresql://u:p@h/d"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run in an empty directory (no `.env`) with no JUDGEMETRICS_* variables."""
    monkeypatch.chdir(tmp_path)
    for name in list(__import__("os").environ):
        if name.startswith("JUDGEMETRICS_"):
            monkeypatch.delenv(name)


def test_defaults_are_local_and_placeholder_free() -> None:
    settings = Settings()
    assert settings.env == "local"
    assert settings.log_format == "console"
    assert settings.database_url.startswith("postgresql+psycopg://judgemetrics_app@")
    assert settings.effective_admin_database_url == settings.database_url
    assert settings.s3_secret_access_key is None


def test_prefixed_environment_variables_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGEMETRICS_ENV", "test")
    monkeypatch.setenv("JUDGEMETRICS_DATABASE_URL", APP_URL)
    monkeypatch.setenv("JUDGEMETRICS_ADMIN_DATABASE_URL", ADMIN_URL)
    monkeypatch.setenv("JUDGEMETRICS_LOG_FORMAT", "json")
    monkeypatch.setenv("JUDGEMETRICS_RAW_STORE_URL", "s3://judgemetrics-raw")
    # An unprefixed variable is not a setting.
    monkeypatch.setenv("LOG_FORMAT", "console")
    settings = Settings()
    assert settings.env == "test"
    assert settings.database_url == APP_URL
    assert settings.effective_admin_database_url == ADMIN_URL
    assert settings.log_format == "json"
    assert settings.raw_store_url == "s3://judgemetrics-raw"


def test_secret_values_never_appear_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGEMETRICS_S3_SECRET_ACCESS_KEY", "placeholder-secret-value")
    monkeypatch.setenv("JUDGEMETRICS_CORRECTION_CONTACT_KEY", "placeholder-key-value")
    settings = Settings()
    assert isinstance(settings.s3_secret_access_key, SecretStr)
    assert settings.s3_secret_access_key.get_secret_value() == "placeholder-secret-value"
    rendered = repr(settings) + str(settings) + settings.model_dump_json()
    assert "placeholder-secret-value" not in rendered
    assert "placeholder-key-value" not in rendered


def test_dotenv_is_read_only_when_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        f"JUDGEMETRICS_DATABASE_URL={APP_URL}\nJUDGEMETRICS_LOG_FORMAT=json\nPOSTGRES_USER=x\n",
        encoding="utf-8",
    )
    local = Settings()
    assert local.env == "local"
    assert local.database_url == APP_URL
    assert local.log_format == "json"

    monkeypatch.setenv("JUDGEMETRICS_ENV", "test")
    test = Settings()
    assert test.env == "test"
    assert test.database_url != APP_URL
    assert test.log_format == "console"

    monkeypatch.setenv("JUDGEMETRICS_ENV", "production")
    assert Settings().log_format == "console"


def test_env_value_itself_is_not_taken_from_dotenv(tmp_path: Path) -> None:
    dotenv = "JUDGEMETRICS_ENV=production\n"  # pragma: allowlist secret
    (tmp_path / ".env").write_text(dotenv, encoding="utf-8")
    # The file is opened because the process is local; the file cannot flip that.
    assert Settings().env == "local"


def test_invalid_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGEMETRICS_ENV", "staging")
    with pytest.raises(ValidationError):
        Settings()


def test_database_urls_must_use_psycopg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGEMETRICS_DATABASE_URL", LEGACY_DRIVER_URL)
    with pytest.raises(ValidationError, match="postgresql\\+psycopg"):
        Settings()


def test_test_database_url_is_optional_and_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGEMETRICS_ENV", "test")
    assert Settings().test_database_url is None
    monkeypatch.setenv("JUDGEMETRICS_TEST_DATABASE_URL", LEGACY_DRIVER_URL)
    with pytest.raises(ValidationError, match="postgresql\\+psycopg"):
        Settings()
    scratch = (
        "postgresql+psycopg://owner:pw@localhost:5432/judgemetrics_test"  # pragma: allowlist secret
    )
    monkeypatch.setenv("JUDGEMETRICS_TEST_DATABASE_URL", scratch)
    assert Settings().test_database_url == scratch


def test_git_sha_prefers_configured_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGEMETRICS_GIT_SHA", "a" * 40)
    assert Settings().resolved_git_sha() == "a" * 40


def test_git_sha_falls_back_to_checkout_or_unknown() -> None:
    sha = Settings().resolved_git_sha()
    assert sha == "unknown" or re.fullmatch(r"[0-9a-f]{40}", sha)


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGEMETRICS_ENV", "test")
    first = get_settings()
    assert get_settings() is first
    get_settings.cache_clear()
    assert get_settings() is not first


def test_search_rate_limit_is_off_under_test_unless_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings(env="local").effective_search_rate_limit_enabled is True
    assert Settings(env="production").effective_search_rate_limit_enabled is True
    assert Settings(env="test").effective_search_rate_limit_enabled is False
    assert Settings(env="test", search_rate_limit_enabled=True).effective_search_rate_limit_enabled
    monkeypatch.setenv("JUDGEMETRICS_SEARCH_RATE_LIMIT_ENABLED", "false")
    assert Settings(env="production").effective_search_rate_limit_enabled is False
    defaults = Settings(env="test")
    assert (defaults.search_rate_limit_per_minute, defaults.search_rate_limit_burst) == (60, 10)
    assert defaults.search_similarity_threshold == 0.3
    assert defaults.trust_proxy is False
    with pytest.raises(ValidationError):
        Settings(env="test", search_similarity_threshold=0)
    with pytest.raises(ValidationError):
        Settings(env="test", search_rate_limit_burst=0)
