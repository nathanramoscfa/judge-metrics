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
decision; all as the ingest role), ``methodology`` (``render`` writes
``docs/METHODOLOGY.md`` from the metric registry; ``--check`` exits 1 when
the committed file differs), and ``metrics`` (``compute`` exports a
snapshot, computes every registry metric for every subject — or the
``--subject`` ones — and publishes the observations; ``verify``
recomputes every current observation from its snapshot and exits 1 on
any mismatch; both as the ingest role), and ``provenance`` (``trace
<observation id>`` prints the chain from a published number back to the
raw artifacts and exits 1 when it is incomplete; as the read-only role).

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
methodology_app = typer.Typer(
    help="The methodology document rendered from the metric registry (docs/METHODOLOGY.md)."
)
metrics_app = typer.Typer(help="The metrics engine: compute and verify observations.")
provenance_app = typer.Typer(
    help="The provenance chain from a published number back to the raw artifacts."
)
er_app.add_typer(er_review_app, name="review")
app.add_typer(db_app, name="db")
app.add_typer(ingest_app, name="ingest")
app.add_typer(openapi_app, name="openapi")
app.add_typer(synthetic_app, name="synthetic")
app.add_typer(er_app, name="er")
app.add_typer(methodology_app, name="methodology")
app.add_typer(metrics_app, name="metrics")
app.add_typer(provenance_app, name="provenance")

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
    seed, scale, and generator version; a manifest from another generator
    version or scale is stale and is regenerated (``--force`` regenerates
    and re-parses regardless). The ingest
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
        log.warning("seed.skipped_generation", because="production environment", out=str(target))
    elif not force and manifest_matches(target, seed, scale.value):
        log.info("seed.generation_skipped", seed=seed, scale=scale.value, out=str(target))
        typer.echo(f"dataset up to date at {target}")
    else:
        # A dataset this command generated earlier under an older generator
        # version (or another scale) is stale: regenerate over it.
        stale = (target / "manifest.json").is_file()
        log.info("seed.generate.start", seed=seed, scale=scale.value, out=str(target), stale=stale)
        try:
            manifest = generate_dataset(seed, scale.value, target, force=force or stale)
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


# --- methodology: the registry-rendered document ----------------------------------------

# How many diff lines `--check` prints before truncating.
METHODOLOGY_DIFF_LINES = 60


@methodology_app.command("render")
def methodology_render(
    out: Annotated[
        Path,
        typer.Option(
            "--out",
            help="Where to write (a relative path is under the repository root).",
            dir_okay=False,
        ),
    ] = Path("docs") / "METHODOLOGY.md",
    check: Annotated[
        bool,
        typer.Option("--check", help="Compare with the file instead of writing; exit 1 on a diff."),
    ] = False,
) -> None:
    """Render docs/METHODOLOGY.md from data/reference/metric_registry.yaml.

    The committed document must equal this output (the unit test and
    ``--check`` compare them), so re-render after any registry change.
    """
    from judgemetrics.metrics.methodology import (
        check_methodology,
        resolve_output,
        write_methodology,
    )
    from judgemetrics.metrics.registry import RegistryError

    target = resolve_output(out)
    try:
        if check:
            diff = check_methodology(target)
            if diff:
                typer.echo(f"{target} differs from the registry render:", err=True)
                for line in diff[:METHODOLOGY_DIFF_LINES]:
                    typer.echo(line, err=True)
                if len(diff) > METHODOLOGY_DIFF_LINES:
                    typer.echo(f"... {len(diff) - METHODOLOGY_DIFF_LINES} more lines", err=True)
                raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED)
            typer.echo(f"{target} is up to date")
            return
        write_methodology(target)
    except RegistryError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    typer.echo(f"wrote {target}")


# --- metrics: compute and verify ---------------------------------------------------------

# How many verification problems the text output prints before truncating.
VERIFY_REPORT_LINES = 40


@metrics_app.command("compute")
def metrics_compute(
    label: Annotated[
        str | None, typer.Option("--label", help="A label recorded on the snapshot row.")
    ] = None,
    subject: Annotated[
        list[str] | None,
        typer.Option(
            "--subject",
            help="Only these subjects (judge:<uuid> or court:<uuid>; repeatable).",
        ),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of text.")] = False,
) -> None:
    """Export a snapshot, compute every registry metric, and publish the observations.

    Runs as the ingest role in one transaction; a subject whose numbers did
    not change is left in place, so a second run over unchanged data
    publishes nothing. Refuses to publish, and rolls back, when an
    observation's members are not all in the snapshot.
    """
    import json

    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.session import make_engine
    from judgemetrics.logging import configure_logging
    from judgemetrics.metrics.compute import ComputeError, parse_subject
    from judgemetrics.metrics.engine import compute_and_publish
    from judgemetrics.metrics.publish import PublishError
    from judgemetrics.metrics.registry import RegistryError
    from judgemetrics.metrics.snapshot import SnapshotError

    settings = get_settings()
    configure_logging(settings)
    try:
        subjects = None if not subject else [parse_subject(text) for text in subject]
    except ComputeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    engine = make_engine(settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            try:
                result = compute_and_publish(session, settings, subjects=subjects, label=label)
            except (PublishError, SnapshotError, ComputeError, RegistryError) as exc:
                session.rollback()
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED) from exc
            session.commit()
    finally:
        engine.dispose()
    summary = {
        "snapshot": result.snapshot.content_hash,
        "snapshot_reused": result.snapshot.reused,
        "subjects": len(result.computed.subjects),
        "sources_skipped": list(result.computed.sources_skipped),
        **{k: v for k, v in result.published.as_log().items() if k != "snapshot"},
    }
    if as_json:
        typer.echo(json.dumps(summary, indent=2, sort_keys=True))
        return
    typer.echo(f"snapshot {summary['snapshot']}" + (" (reused)" if result.snapshot.reused else ""))
    typer.echo(
        f"subjects={summary['subjects']} observations={summary['observations']} "
        f"suppressed={summary['suppressed']} not_observable={summary['not_observable']} "
        f"superseded={summary['superseded']} members={summary['members']} "
        f"subjects_published={summary['subjects_published']} "
        f"subjects_unchanged={summary['subjects_unchanged']}"
    )
    if summary["sources_skipped"]:
        typer.echo(f"sources skipped (no coverage window): {len(summary['sources_skipped'])}")


@metrics_app.command("verify")
def metrics_verify(
    snapshot: Annotated[
        str | None, typer.Option("--snapshot", help="Only the observations of this snapshot hash.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of text.")] = False,
) -> None:
    """Recompute every current observation from its snapshot; exit 1 on any mismatch."""
    import json

    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.session import make_engine
    from judgemetrics.logging import configure_logging
    from judgemetrics.metrics.registry import RegistryError
    from judgemetrics.metrics.snapshot import SnapshotError
    from judgemetrics.metrics.verify import verify

    settings = get_settings()
    configure_logging(settings)
    engine = make_engine(settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            try:
                result = verify(session, settings, snapshot=snapshot)
            except (SnapshotError, RegistryError) as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(EXIT_USAGE) from exc
            session.rollback()
    finally:
        engine.dispose()
    if as_json:
        typer.echo(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        typer.echo(
            f"snapshots={len(result.snapshots)} observations={result.observations} "
            f"verified={result.verified} mismatches={len(result.mismatches)} "
            f"unverifiable={len(result.unverifiable)}"
        )
        lines = [
            f"mismatch: {m.slug} {m.subject_type}:{m.subject_id}"
            + ("" if m.window_days is None else f"@{m.window_days}")
            + ("" if m.dimension_value is None else f"[{m.dimension_value}]")
            + f" column={m.column} stored={m.as_dict()['stored']} "
            f"recomputed={m.as_dict()['recomputed']} observation={m.observation_id}"
            for m in result.mismatches
        ] + [
            f"unverifiable: {u.slug} observation={u.observation_id} snapshot={u.snapshot}: "
            f"{u.reason}"
            for u in result.unverifiable
        ]
        for line in lines[:VERIFY_REPORT_LINES]:
            typer.echo(line, err=True)
        if len(lines) > VERIFY_REPORT_LINES:
            typer.echo(f"... {len(lines) - VERIFY_REPORT_LINES} more", err=True)
    if not result.ok:
        raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED)


# --- provenance: the chain behind one observation ----------------------------------------


@provenance_app.command("trace")
def provenance_trace(
    observation_id: Annotated[str, typer.Argument(help="A metric_observation id (UUID).")],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of text.")] = False,
) -> None:
    """Print the chain observation → snapshot → members → cases → source records → artifacts.

    Reads as the read-only role; exits 1 when the chain is incomplete (a
    member without a canonical row, a row without a source record, a
    record without its artifact digest) and 2 for a malformed or unknown id.
    """
    import json

    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.session import make_engine
    from judgemetrics.logging import configure_logging
    from judgemetrics.metrics.provenance import TraceError, parse_observation_id, render, trace

    settings = get_settings()
    configure_logging(settings)
    try:
        oid = parse_observation_id(observation_id)
    except TraceError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    engine = make_engine(settings.database_url)
    try:
        with Session(engine) as session:
            try:
                traced = trace(session, oid)
            except TraceError as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(EXIT_USAGE) from exc
            session.rollback()
    finally:
        engine.dispose()
    if as_json:
        typer.echo(json.dumps(traced.as_dict(), indent=2, sort_keys=True))
    else:
        for line in render(traced):
            typer.echo(line)
    if not traced.complete:
        raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
