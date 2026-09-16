# src/judgemetrics/db/migrations.py
"""Alembic helpers shared by the CLI, the health endpoints, and the tests.

The Alembic configuration is built here, in code, so the migration
scripts are found regardless of the working directory (the CLI, the
container image, and pytest all resolve the same ``alembic/`` directory)
and so the database URL always comes from settings, never from
``alembic.ini``.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_DIR = REPO_ROOT / "alembic"
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def alembic_config(database_url: str | None = None) -> Config:
    """An Alembic ``Config`` pointing at ``alembic/`` with an optional URL override.

    ``env.py`` reads ``judgemetrics.database_url`` from the config attributes
    when set (tests and the CLI pass an explicit role URL) and falls back to
    ``get_settings().effective_admin_database_url``.
    """
    config = Config(str(ALEMBIC_INI)) if ALEMBIC_INI.is_file() else Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    if database_url is not None:
        config.attributes["judgemetrics.database_url"] = database_url
    return config


def head_revision() -> str | None:
    """The head revision of the migration scripts (no database access)."""
    script = ScriptDirectory.from_config(alembic_config())
    return script.get_current_head()


def current_revision(engine: Engine) -> str | None:
    """The revision applied to the database behind ``engine`` (``None`` if none)."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        return MigrationContext.configure(connection).get_current_revision()


def upgrade(database_url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade(database_url: str, revision: str) -> None:
    command.downgrade(alembic_config(database_url), revision)
