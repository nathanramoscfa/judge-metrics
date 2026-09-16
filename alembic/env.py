# alembic/env.py
"""Alembic environment.

The database URL is never read from ``alembic.ini``: it comes from the
``judgemetrics.database_url`` config attribute when the caller sets one
(``judgemetrics.db.migrations``) and otherwise from
``get_settings().effective_admin_database_url`` — the admin (DDL) role.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from judgemetrics.config import get_settings
from judgemetrics.db.models import Base

config = context.config

if config.config_file_name is not None and not config.attributes.get(
    "judgemetrics.skip_logging_config"
):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    override = config.attributes.get("judgemetrics.database_url")
    if isinstance(override, str) and override:
        return override
    return get_settings().effective_admin_database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a connection (`alembic upgrade head --sql`)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = dict(config.get_section(config.config_ini_section) or {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
