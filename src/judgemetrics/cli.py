# src/judgemetrics/cli.py
"""The ``judgemetrics`` command-line interface (Typer).

Groups: ``db`` (migrations, run as the admin role), ``serve`` (uvicorn),
``ingest`` (``list-sources``, ``run <source>`` as the ingest role, ``runs``
as the read-only role), ``openapi`` (``export`` the API document),
``synthetic`` (``generate`` a deterministic synthetic dataset, ``verify``
one against its manifest), ``seed`` (generate the demo dataset and
ingest it through the ``synthetic`` connector as the ingest role), and
``er`` (entity resolution: ``run`` recomputes candidates, ``review list``
shows the manual-review queue, ``review decide`` records a reviewer's
decision; all as the ingest role).

Every command that hashes person identifiers (``ingest run``, ``seed``)
checks ``JUDGEMETRICS_IDENTIFIER_PEPPER`` first and exits with a named
error when it is unset.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from judgemetrics import __version__
from judgemetrics.db.models.enums import ResolutionDecision

app = typer.Typer(
    name="judgemetrics",
    help="JudgeMetrics: reproducible analytics over public criminal-court records.",
    no_args_is_help=True,
    add_completion=False,
)
db_app = typer.Typer(help="Database migrations (Alembic), run as the admin role.")
ingest_app = typer.Typer(help="Source connectors and ingest runs.")
openapi_app = typer.Typer(help="The generated OpenAPI document.")
synthetic_app = typer.Typer(
    help="The deterministic synthetic justice dataset (docs/SYNTHETIC_DATA.md)."
)
er_app = typer.Typer(help="Entity resolution: candidates, the review queue, decisions.")
er_review_app = typer.Typer(help="The manual-review queue.")
er_app.add_typer(er_review_app, name="review")
app.add_typer(db_app, name="db")
app.add_typer(ingest_app, name="ingest")
app.add_typer(openapi_app, name="openapi")
app.add_typer(synthetic_app, name="synthetic")
app.add_typer(er_app, name="er")

EXIT_RUN_NOT_SUCCEEDED = 1
EXIT_USAGE = 2

DEFAULT_SYNTHETIC_SEED = 20260916
SYNTHETIC_DATA_DIR = Path("data") / "synthetic"


class SyntheticScale(StrEnum):
    golden = "golden"
    demo = "demo"
    tiny = "tiny"


class ReviewDecision(StrEnum):
    """The two decisions a reviewer may record (validated before the database is touched)."""

    matched = "matched"
    rejected = "rejected"


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


def _require_pepper(settings: object) -> None:
    """Exit with a named error unless the identifier pepper is configured."""
    from judgemetrics.config import Settings
    from judgemetrics.security.identifiers import (
        IdentifierPepperMissingError,
        require_identifier_pepper,
    )

    if not isinstance(settings, Settings):  # pragma: no cover - defensive
        return
    try:
        require_identifier_pepper(settings)
    except IdentifierPepperMissingError as exc:
        typer.echo(f"error: {exc} (see .env.example)", err=True)
        raise typer.Exit(EXIT_USAGE) from exc


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
    _require_pepper(settings)
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
            summary = _run_summary(run, source_id)
            succeeded = run.status is IngestRunStatus.SUCCEEDED
    finally:
        engine.dispose()
    typer.echo(summary)
    if not succeeded:
        raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED)


def _run_summary(run: object, source_id: str) -> str:
    from judgemetrics.db.models import IngestRun

    if not isinstance(run, IngestRun):  # pragma: no cover - defensive
        return f"run ? source={source_id}"
    summary = _format_run(
        run.id,
        source_id,
        run.status.value,
        (run.records_seen, run.records_created, run.records_updated, run.records_rejected),
    )
    if run.failure_reason:
        summary += f" reason={run.failure_reason}"
    return summary


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


@openapi_app.command("export")
def openapi_export(
    out: Annotated[
        Path,
        typer.Option(
            "--out", help="Where to write the document.", dir_okay=False, resolve_path=True
        ),
    ] = Path("docs/openapi.json"),
) -> None:
    """Write the app's OpenAPI document to OUT (sorted keys, two-space indent, LF, trailing newline).

    The committed ``docs/openapi.json`` must equal this output
    (``tests/unit/test_openapi.py``), so regenerate it after any route change.
    """
    from judgemetrics.openapi import render_openapi

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(render_openapi().encode("utf-8"))
    typer.echo(f"wrote {out}")


@synthetic_app.command("generate")
def synthetic_generate(
    seed: Annotated[
        int, typer.Option("--seed", help="The seed every stream derives from.")
    ] = DEFAULT_SYNTHETIC_SEED,
    scale: Annotated[
        SyntheticScale, typer.Option("--scale", help="World size: golden, demo, or tiny.")
    ] = SyntheticScale.demo,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            help="Output directory (default data/synthetic/<seed>).",
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Regenerate over an existing manifest.")
    ] = False,
) -> None:
    """Write source/, truth/, and manifest.json for SEED at SCALE (byte-identical per seed)."""
    from judgemetrics.config import get_settings
    from judgemetrics.logging import configure_logging, get_logger
    from judgemetrics.synthetic.generate import DatasetExistsError, generate_dataset

    configure_logging(get_settings())
    log = get_logger("judgemetrics.synthetic")
    target = (SYNTHETIC_DATA_DIR / str(seed)).resolve() if out is None else out
    log.info("synthetic.generate.start", seed=seed, scale=scale.value, out=str(target))
    try:
        manifest = generate_dataset(seed, scale.value, target, force=force)
    except DatasetExistsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED) from exc
    log.info(
        "synthetic.generate.done",
        seed=seed,
        scale=scale.value,
        generator_version=manifest.generator_version,
        counts=manifest.counts,
    )
    for relative, count in sorted(manifest.counts.items()):
        typer.echo(f"{relative}\t{count}")
    typer.echo(f"wrote {manifest.path}")


@synthetic_app.command("verify")
def synthetic_verify(
    directory: Annotated[
        Path,
        typer.Argument(
            help="A generated dataset directory holding manifest.json.",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
    ],
) -> None:
    """Recompute every file hash in DIRECTORY against its manifest; exit 1 on any mismatch."""
    from judgemetrics.synthetic.generate import verify_dataset

    problems = verify_dataset(directory)
    if problems:
        for problem in problems:
            typer.echo(f"mismatch: {problem}", err=True)
        raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED)
    typer.echo(f"verified {directory}")


@app.command("seed")
def seed(
    seed: Annotated[
        int, typer.Option("--seed", help="The seed of the dataset to generate and ingest.")
    ] = DEFAULT_SYNTHETIC_SEED,
    scale: Annotated[
        SyntheticScale, typer.Option("--scale", help="World size: golden, demo, or tiny.")
    ] = SyntheticScale.demo,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Regenerate the dataset even when its manifest matches, and re-parse it.",
        ),
    ] = False,
) -> None:
    """Generate the synthetic dataset for SEED into data/synthetic/<seed> and ingest it.

    Generation is skipped when the manifest there already records the same
    seed, scale, and generator version (``--force`` regenerates). The ingest
    runs the ``synthetic`` connector against that directory as the ingest
    role and is refused, like any synthetic ingest, when
    ``JUDGEMETRICS_ENV=production``.
    """
    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.models import IngestRunStatus
    from judgemetrics.db.session import make_engine
    from judgemetrics.ingest.runner import run_ingest
    from judgemetrics.ingest.store import RawStoreError, open_raw_store
    from judgemetrics.ingest.synthetic.connector import SyntheticConnector
    from judgemetrics.logging import configure_logging, get_logger
    from judgemetrics.synthetic.generate import (
        DatasetExistsError,
        generate_dataset,
        manifest_matches,
    )

    settings = get_settings()
    configure_logging(settings)
    _require_pepper(settings)
    log = get_logger("judgemetrics.seed")
    target = (SYNTHETIC_DATA_DIR / str(seed)).resolve()
    if settings.env == "production":
        # Nothing is generated: the runner records the refusal and that is all.
        log.warning("seed.skipped_generation", reason="production environment", out=str(target))
    elif not force and manifest_matches(target, seed, scale.value):
        log.info("seed.generation_skipped", seed=seed, scale=scale.value, out=str(target))
        typer.echo(f"dataset up to date at {target}")
    else:
        log.info("seed.generate.start", seed=seed, scale=scale.value, out=str(target))
        try:
            manifest = generate_dataset(seed, scale.value, target, force=force)
        except DatasetExistsError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED) from exc
        log.info(
            "seed.generate.done",
            seed=seed,
            scale=scale.value,
            generator_version=manifest.generator_version,
            counts=manifest.counts,
        )
        typer.echo(f"generated {target}")

    try:
        store = open_raw_store(settings)
    except RawStoreError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    connector = SyntheticConnector(target, settings=settings)
    engine = make_engine(settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            run = run_ingest(
                connector.source_id,
                session=session,
                store=store,
                settings=settings,
                force=force,
                connector=connector,
            )
            summary = _run_summary(run, connector.source_id)
            succeeded = run.status is IngestRunStatus.SUCCEEDED
    finally:
        engine.dispose()
    typer.echo(summary)
    if not succeeded:
        raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED)


# --- er: entity resolution ---------------------------------------------------------------


@er_app.command("run")
def er_run(
    source: Annotated[
        str | None,
        typer.Option("--source", help="Only persons created from this source id (e.g. synthetic)."),
    ] = None,
) -> None:
    """Recompute person candidates under the current model version and apply system merges."""
    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.session import make_engine
    from judgemetrics.entity_resolution.config import MODEL_VERSION
    from judgemetrics.entity_resolution.pipeline import rerun
    from judgemetrics.logging import configure_logging

    settings = get_settings()
    configure_logging(settings)
    engine = make_engine(settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            stats = rerun(session, source=source)
            session.commit()
    finally:
        engine.dispose()
    typer.echo(
        f"model={MODEL_VERSION} pairs={stats.pairs} "
        f"candidates_created={stats.candidates.created} "
        f"candidates_updated={stats.candidates.updated} matched={stats.matched} "
        f"rejected={stats.rejected} review={stats.review} merges={stats.merges}"
    )


@er_review_app.command("list")
def er_review_list(
    entity_type: Annotated[
        str, typer.Option("--entity-type", help="The entity type to list (person).")
    ] = "person",
    limit: Annotated[
        int, typer.Option("--limit", min=1, max=1000, help="At most N items, oldest first.")
    ] = 50,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of a table.")] = False,
) -> None:
    """List undecided review candidates: ids, public person keys, stage, score, feature flags."""
    import json

    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.session import make_engine
    from judgemetrics.entity_resolution.queue import ReviewError, list_review

    settings = get_settings()
    engine = make_engine(settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            try:
                items = list_review(session, entity_type=entity_type, limit=limit)
            except ReviewError as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(EXIT_USAGE) from exc
    finally:
        engine.dispose()
    if as_json:
        typer.echo(json.dumps([item.as_dict() for item in items], indent=2, sort_keys=True))
        return
    for line in render_review_items([item.as_dict() for item in items]):
        typer.echo(line)


def render_review_items(items: list[dict[str, object]]) -> list[str]:
    """The table lines of ``er review list`` (public keys, stage, score, feature flags)."""
    if not items:
        return ["no review items"]
    lines = ["candidate_id\tleft\tright\tstage\tscore\tfeatures\tcreated_at"]
    for item in items:
        features = item.get("features")
        flags = (
            ",".join(name for name, value in features.items() if value)
            if isinstance(features, dict)
            else ""
        )
        lines.append(
            "\t".join(
                (
                    str(item.get("candidate_id")),
                    str(item.get("left_public_key")),
                    str(item.get("right_public_key")),
                    str(item.get("stage")),
                    "" if item.get("score") is None else f"{float(str(item['score'])):.2f}",
                    flags or "-",
                    str(item.get("created_at")),
                )
            )
        )
    return lines


@er_review_app.command("decide")
def er_review_decide(
    candidate_id: Annotated[
        uuid.UUID, typer.Argument(help="The candidate id from `er review list`.")
    ],
    decision: Annotated[
        ReviewDecision, typer.Option("--decision", help="matched merges; rejected records only.")
    ],
    reviewer: Annotated[
        str, typer.Option("--reviewer", help="An operator label for the audit log (not an e-mail).")
    ],
    reason: Annotated[str, typer.Option("--reason", help="Why, for the audit log.")],
) -> None:
    """Record a reviewer's decision on a review candidate (refused in production until Phase 6)."""
    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.session import make_engine
    from judgemetrics.entity_resolution.queue import ReviewError, decide
    from judgemetrics.logging import configure_logging

    settings = get_settings()
    configure_logging(settings)
    engine = make_engine(settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            try:
                result = decide(
                    session,
                    candidate_id,
                    decision=ResolutionDecision(decision.value),
                    reviewer=reviewer,
                    reason=reason,
                    settings=settings,
                )
            except ReviewError as exc:
                session.rollback()
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(EXIT_USAGE) from exc
            session.commit()
    finally:
        engine.dispose()
    summary = f"candidate {candidate_id} decision={result.decision.value} audit={result.audit_id}"
    if result.merge is not None:
        summary += (
            f" merged={result.merge.drop_id} into={result.merge.keep_id} "
            f"moved={sum(result.merge.moved.values())}"
        )
    typer.echo(summary)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
