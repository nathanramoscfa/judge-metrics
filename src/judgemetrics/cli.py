# src/judgemetrics/cli.py
"""The ``judgemetrics`` command-line interface (Typer).

Groups: ``db`` (migrations, run as the admin role), ``serve`` (uvicorn),
and ``ingest`` (connector registry; empty until Phase 1 Step 3 adds the
framework and the FJC connector).
"""

from __future__ import annotations

from typing import Annotated

import typer

from judgemetrics import __version__

app = typer.Typer(
    name="judgemetrics",
    help="JudgeMetrics: reproducible analytics over public criminal-court records.",
    no_args_is_help=True,
    add_completion=False,
)
db_app = typer.Typer(help="Database migrations (Alembic), run as the admin role.")
ingest_app = typer.Typer(help="Source connectors and ingest runs.")
app.add_typer(db_app, name="db")
app.add_typer(ingest_app, name="ingest")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print the package version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """JudgeMetrics command-line interface."""


def _admin_url() -> str:
    from judgemetrics.config import get_settings

    return get_settings().effective_admin_database_url


@db_app.command("upgrade")
def db_upgrade(
    revision: Annotated[str, typer.Option("--revision", help="Target revision.")] = "head",
) -> None:
    """Apply migrations up to REVISION (default: head)."""
    from judgemetrics.db.migrations import upgrade

    upgrade(_admin_url(), revision)
    typer.echo(f"upgraded to {revision}")


@db_app.command("downgrade")
def db_downgrade(
    revision: Annotated[str, typer.Argument(help="Target revision, e.g. base or 0001.")],
) -> None:
    """Revert migrations down to REVISION."""
    from judgemetrics.db.migrations import downgrade

    downgrade(_admin_url(), revision)
    typer.echo(f"downgraded to {revision}")


@db_app.command("current")
def db_current() -> None:
    """Print the applied revision and the head the code expects."""
    from judgemetrics.db.migrations import current_revision, head_revision
    from judgemetrics.db.session import make_engine

    engine = make_engine(_admin_url())
    try:
        current = current_revision(engine)
    finally:
        engine.dispose()
    typer.echo(f"current: {current or '(none)'}")
    typer.echo(f"head:    {head_revision() or '(none)'}")


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option("--host", help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port.")] = 8000,
    reload: Annotated[bool, typer.Option("--reload", help="Auto-reload on code changes.")] = False,
) -> None:
    """Run the API with uvicorn (``judgemetrics.main:app``)."""
    import uvicorn

    from judgemetrics.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "judgemetrics.main:app",
        host=host,
        port=port,
        reload=reload,
        log_config=None,  # judgemetrics.logging owns the handlers
        log_level=settings.log_level.lower(),
        access_log=False,  # the app's access-log middleware replaces uvicorn's
    )


@ingest_app.command("list-sources")
def ingest_list_sources() -> None:
    """List the registered source connectors (empty until Step 3)."""
    from judgemetrics.ingest.registry import registered_sources

    sources = registered_sources()
    if not sources:
        typer.echo("no sources registered")
        return
    for name in sources:
        typer.echo(name)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
