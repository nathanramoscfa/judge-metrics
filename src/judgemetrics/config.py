# src/judgemetrics/config.py
"""Application settings (pydantic-settings, ``JUDGEMETRICS_`` prefix).

Every value is read from the environment. ``.env`` is consulted only when
``JUDGEMETRICS_ENV`` is ``local`` (the default), so test and production
processes never pick up a developer's local file by accident. Secrets are
``SecretStr`` so they cannot leak through ``repr`` or a serialized settings
object; the logging scrubber (``judgemetrics.logging``) is the second line of
defence.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404 - fixed argv `git rev-parse`, see _git_sha_from_checkout
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "JUDGEMETRICS_"
REPO_ROOT = Path(__file__).resolve().parents[2]
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")

Environment = Literal["local", "test", "production"]
LogFormat = Literal["json", "console"]


def _env_name() -> str:
    return os.environ.get(f"{ENV_PREFIX}ENV", "local").strip().lower()


def _git_sha_from_checkout() -> str:
    """Return ``git rev-parse HEAD`` for the source checkout, else ``unknown``."""
    git = shutil.which("git")
    if git is None or not (REPO_ROOT / ".git").exists():
        return "unknown"
    try:
        # Fixed argv (absolute git path from PATH lookup), no shell, no user input.
        completed = subprocess.run(  # noqa: S603 # nosec B603
            [git, "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = completed.stdout.strip()
    return sha if completed.returncode == 0 and _GIT_SHA.match(sha) else "unknown"


class Settings(BaseSettings):
    """Runtime configuration. See ``.env.example`` for every variable."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file_encoding="utf-8",
        # `.env` also holds the Compose variables (POSTGRES_*, MINIO_*);
        # they are not settings and must not fail validation.
        extra="ignore",
    )

    def __init__(self, **values: Any) -> None:
        # `.env` (in the working directory) is read only for the local
        # environment; `JUDGEMETRICS_ENV` itself therefore comes from the
        # process environment or the constructor, never from the file.
        env = str(values.get("env") or _env_name())
        values.setdefault("env", env)
        values.setdefault("_env_file", ".env" if env == "local" else None)
        super().__init__(**values)

    env: Environment = "local"
    # The API connects as the read-only application role. Migrations use
    # `admin_database_url` and the ingest runner (Step 3) `ingest_database_url`;
    # each falls back to `database_url` when unset (CI runs everything as
    # the service container's owner).
    database_url: str = Field(
        default="postgresql+psycopg://judgemetrics_app@localhost:5432/judgemetrics",
        description="SQLAlchemy URL for the API's read-only role.",
    )
    admin_database_url: str | None = Field(
        default=None, description="SQLAlchemy URL for the migration (DDL) role."
    )
    ingest_database_url: str | None = Field(
        default=None, description="SQLAlchemy URL for the ingest (DML) role."
    )
    # The scratch database the test suite migrates, fills, and empties
    # (`judgemetrics_test`, created by infra/docker/postgres/03-test-database.sql;
    # CI points it at the service database). Only tests/conftest.py reads it:
    # `test_settings` runs migrations through it as the owner and retargets the
    # app and ingest URLs above at its database. Unset, the suite falls back
    # to the URLs above and warns once (a live ingest is then emptied).
    test_database_url: str | None = Field(
        default=None, description="SQLAlchemy URL (owner) for the scratch test database."
    )
    raw_store_url: str = Field(
        default="file://./data/lake",
        description="Raw object lake: `file://<dir>` or `s3://<bucket>`.",
    )
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
    log_format: LogFormat = "console"
    log_level: str = "INFO"
    git_sha: str | None = Field(
        default=None,
        description="Build SHA; falls back to `git rev-parse HEAD`, else `unknown`.",
    )
    # Application-level key (urlsafe base64, 32 bytes: `Fernet.generate_key()`)
    # that encrypts `correction_request.requester_contact` at rest. Only the
    # admin tooling that answers corrections needs it; the API never decrypts.
    correction_contact_key: SecretStr | None = None
    # Per-deployment pepper for the sha256 hashes in `person_identifier`
    # (`judgemetrics.security.identifiers`). Required by every process that
    # hashes person identifiers — the ingest CLI refuses to start without it
    # (`IdentifierPepperMissingError`); the API never hashes and never needs it.
    identifier_pepper: SecretStr | None = None
    # The generated synthetic dataset the `synthetic` connector reads: the
    # directory holding `manifest.json` and `source/` (docs/SYNTHETIC_DATA.md);
    # `truth/` beside them is never discovered.
    synthetic_dir: Path = Path("data") / "synthetic" / "20260916"
    # Public API (judgemetrics.api). `trust_proxy` lets the rate limiter key
    # on the address a trusted reverse proxy appended to `X-Forwarded-For`;
    # without it the header is ignored (a client could otherwise spoof its
    # bucket). The limiter is the in-process layer beneath the Phase 8 edge
    # limits; `search_rate_limit_enabled` unset means "on, except under the
    # test environment", so integration tests opt in explicitly.
    trust_proxy: bool = False
    search_rate_limit_per_minute: int = Field(default=60, ge=1)
    search_rate_limit_burst: int = Field(default=10, ge=1)
    search_rate_limit_enabled: bool | None = None
    # pg_trgm similarity threshold for `/search` and the judges `q` filter,
    # set per request with `set_config` (never interpolated into SQL).
    search_similarity_threshold: float = Field(default=0.3, gt=0.0, le=1.0)

    @field_validator(
        "database_url", "admin_database_url", "ingest_database_url", "test_database_url"
    )
    @classmethod
    def _require_psycopg_driver(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("postgresql+psycopg://"):
            msg = "database URLs must use the `postgresql+psycopg://` driver"
            raise ValueError(msg)
        return value

    @property
    def effective_admin_database_url(self) -> str:
        return self.admin_database_url or self.database_url

    @property
    def effective_ingest_database_url(self) -> str:
        return self.ingest_database_url or self.database_url

    @property
    def effective_search_rate_limit_enabled(self) -> bool:
        if self.search_rate_limit_enabled is not None:
            return self.search_rate_limit_enabled
        return self.env != "test"

    def resolved_git_sha(self) -> str:
        """The configured SHA, else the checkout's HEAD, else ``unknown``."""
        if self.git_sha and self.git_sha.strip():
            return self.git_sha.strip()
        return _git_sha_from_checkout()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings; `get_settings.cache_clear()` resets it in tests."""
    return Settings()
