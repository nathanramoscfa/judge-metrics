# src/judgemetrics/cli.py
"""The ``judgemetrics`` command-line interface (Typer).

Groups: ``db`` (migrations, run as the admin role), ``serve`` (uvicorn),
and ``ingest`` (``list-sources``, ``run <source>`` as the ingest role,
``runs`` as the read-only role).
"""

from __future__ import annotations

from pathlib import Path
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

EXIT_RUN_NOT_SUCCEEDED = 1
EXIT_USAGE = 2


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
    """List the registered source connectors with their parser versions."""
    from judgemetrics.ingest.registry import registered_sources

    sources = registered_sources()
    if not sources:
        typer.echo("no sources registered")
        return
    for source in sources:
        typer.echo(f"{source.source_id}\t{source.parser_version}")


def _format_run(run_id: object, source: str, status: str, counts: tuple[int, int, int, int]) -> str:
    seen, created, updated, rejected = counts
    return (
        f"run {run_id} source={source} status={status} seen={seen} "
        f"created={created} updated={updated} rejected={rejected}"
    )


@ingest_app.command("run")
def ingest_run(
    source_id: Annotated[str, typer.Argument(help="A source id from `ingest list-sources`.")],
    from_fixture: Annotated[
        Path | None,
        typer.Option(
            "--from-fixture",
            help="Read the connector's artifacts from DIR instead of fetching them.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-parse artifacts whose hash is already recorded.")
    ] = False,
) -> None:
    """Run the fourteen-step ingest pipeline for SOURCE_ID as the ingest role."""
    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.models import IngestRunStatus
    from judgemetrics.db.session import make_engine
    from judgemetrics.ingest.registry import UnknownSourceError
    from judgemetrics.ingest.runner import run_ingest
    from judgemetrics.ingest.store import RawStoreError, open_raw_store
    from judgemetrics.logging import configure_logging

    settings = get_settings()
    configure_logging(settings)
    try:
        store = open_raw_store(settings)
    except RawStoreError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    engine = make_engine(settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            try:
                run = run_ingest(
                    source_id,
                    session=session,
                    store=store,
                    settings=settings,
                    from_fixture=from_fixture,
                    force=force,
                )
            except UnknownSourceError as exc:
                typer.echo(
                    f"error: unknown source {source_id!r}; see `judgemetrics ingest list-sources`",
                    err=True,
                )
                raise typer.Exit(EXIT_USAGE) from exc
            summary = _format_run(
                run.id,
                source_id,
                run.status.value,
                (run.records_seen, run.records_created, run.records_updated, run.records_rejected),
            )
            if run.failure_reason:
                summary += f" reason={run.failure_reason}"
            succeeded = run.status is IngestRunStatus.SUCCEEDED
    finally:
        engine.dispose()
    typer.echo(summary)
    if not succeeded:
        raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED)


@ingest_app.command("runs")
def ingest_runs(
    source: Annotated[
        str | None, typer.Option("--source", help="Only runs of this source id.")
    ] = None,
    limit: Annotated[
        int, typer.Option("--limit", min=1, max=1000, help="Most recent N runs.")
    ] = 20,
) -> None:
    """Print a table of ingest runs (most recent first) with counts and status."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.models import IngestRun, Source
    from judgemetrics.db.session import make_engine

    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        with Session(engine) as session:
            stmt = (
                select(IngestRun, Source.name)
                .join(Source, Source.id == IngestRun.source_id)
                .order_by(IngestRun.started_at.desc())
                .limit(limit)
            )
            if source:
                stmt = stmt.where(Source.name == source)
            rows = [
                (
                    str(run.id),
                    name,
                    run.status.value,
                    run.started_at.strftime("%Y-%m-%d %H:%M:%SZ"),
                    run.records_seen,
                    run.records_created,
                    run.records_updated,
                    run.records_rejected,
                    run.parser_version,
                )
                for run, name in session.execute(stmt).all()
            ]
    finally:
        engine.dispose()
    if not rows:
        typer.echo("no ingest runs")
        return
    header = (
        "run_id",
        "source",
        "status",
        "started_at",
        "seen",
        "created",
        "updated",
        "rejected",
        "parser",
    )
    widths = [
        max(len(str(value)) for value in column) for column in zip(header, *rows, strict=True)
    ]
    typer.echo(
        "  ".join(str(value).ljust(width) for value, width in zip(header, widths, strict=True))
    )
    for row in rows:
        typer.echo(
            "  ".join(str(value).ljust(width) for value, width in zip(row, widths, strict=True))
        )


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
