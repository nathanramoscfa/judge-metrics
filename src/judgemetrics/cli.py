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
any mismatch; both as the ingest role), ``provenance`` (``trace
<observation id>`` prints the chain from a published number back to the
raw artifacts and exits 1 when it is incomplete; as the read-only role),
and ``models`` (Phase 4: ``fit`` fits and records every expected-outcome
model the latest or the named snapshot lacks and ``verify`` checks every
artifact against its row, refitting with ``--refit``, both as the ingest
role; ``list`` and ``show`` read the catalogue as the read-only role), and
``validation`` (Phase 4 Step 4: ``report`` renders docs/VALIDATION.md from
the latest snapshot's models, ``--check`` exits 1 with a diff when the file
differs; ``recovery`` prints the planted-effect recovery of the published
figures and exits 1 below a tolerance; both as the ingest role, because the
report's subgroup calibration reads the restricted schema), and ``sources``
(Phase 5 Step 1: ``profile cook_sao`` derives
``data/reference/cook_sao/profile.yaml`` from the stored exports and
``--check`` exits 1 with a diff when the file differs; ``excerpt cook_sao``
writes the stratified real-row fixture with the restricted and
quasi-identifying columns blanked; both read the raw lake as the ingest
role, or a directory of the five CSVs with ``--from-fixture``).

Every command that hashes person identifiers (``ingest run``, ``seed``)
checks ``JUDGEMETRICS_IDENTIFIER_PEPPER`` first and exits with a named
error when it is unset.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

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
models_app = typer.Typer(
    help="The expected-outcome models (risk adjustment): fit, list, show, verify."
)
validation_app = typer.Typer(
    help="The validation of the expected-outcome models (docs/VALIDATION.md)."
)
sources_app = typer.Typer(
    help="Source due diligence: the value-set profile and the real-row fixture excerpt."
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
app.add_typer(models_app, name="models")
app.add_typer(validation_app, name="validation")
app.add_typer(sources_app, name="sources")

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
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            help="Dataset directory (default data/synthetic/<seed>); CI uses data/synthetic/ci.",
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Regenerate the dataset even when its manifest matches, and re-parse it.",
        ),
    ] = False,
) -> None:
    """Generate the synthetic dataset for SEED into data/synthetic/<seed> (or OUT) and ingest it.

    Generation is skipped when the manifest there already records the same
    seed, scale, and generator version; a manifest from another generator
    version or scale is stale and is regenerated (``--force`` regenerates
    and re-parses regardless). The ingest runs the ``synthetic`` connector
    against that directory as the ingest role and is refused, like any
    synthetic ingest, when ``JUDGEMETRICS_ENV=production``. A second run
    over an unchanged dataset generates nothing and publishes nothing, which
    is what makes ``uv run poe bootstrap`` idempotent.
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
    target = (SYNTHETIC_DATA_DIR / str(seed)).resolve() if out is None else out
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
    """Export a snapshot, fit its missing outcome models, compute every metric, and publish.

    Runs as the ingest role in one transaction; the snapshot's missing
    expected-outcome models are fitted and recorded first (as `models fit`
    does), a subject whose numbers did not change is left in place, so a
    second run over unchanged data fits and publishes nothing. Refuses to
    publish, and rolls back, when an observation's members are not all in
    the snapshot.
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
        "models_fitted": result.models_fitted,
        "models_read": result.models_read,
        **{k: v for k, v in result.published.as_log().items() if k != "snapshot"},
    }
    if as_json:
        typer.echo(json.dumps(summary, indent=2, sort_keys=True))
        return
    typer.echo(f"snapshot {summary['snapshot']}" + (" (reused)" if result.snapshot.reused else ""))
    typer.echo(f"models fitted={result.models_fitted} read={result.models_read}")
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
                # The settings locate an adjusted observation's model artifact.
                traced = trace(session, oid, settings=settings)
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


# --- models: the expected-outcome models (Phase 4) -------------------------------------------


def _validated_snapshot(snapshot: str | None) -> str | None:
    """``--snapshot`` validated as a content hash before any connection is opened (exit 2)."""
    from judgemetrics.metrics.snapshot import SnapshotError, validate_content_hash

    if snapshot is None:
        return None
    try:
        return validate_content_hash(snapshot)
    except SnapshotError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc


@models_app.command("fit")
def models_fit(
    snapshot: Annotated[
        str | None,
        typer.Option("--snapshot", help="The snapshot hash (default: the latest snapshot)."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of text.")] = False,
) -> None:
    """Fit and record every model of the specification the snapshot lacks (ingest role).

    Writes each model's artifact once under the snapshot directory and one
    outcome_model row per source, target, and window; a second run fits
    nothing. Exits 1 when the snapshot cannot be read or a model cannot be
    recorded, 2 for a malformed or unknown snapshot.
    """
    import json

    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.session import make_engine
    from judgemetrics.logging import configure_logging
    from judgemetrics.metrics.adjustment.artifacts import ArtifactError
    from judgemetrics.metrics.adjustment.catalog import CatalogError, fit_snapshot
    from judgemetrics.metrics.adjustment.fit import FitError
    from judgemetrics.metrics.adjustment.spec import SpecError
    from judgemetrics.metrics.snapshot import SnapshotError

    wanted = _validated_snapshot(snapshot)
    settings = get_settings()
    configure_logging(settings)
    engine = make_engine(settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            try:
                summary = fit_snapshot(session, settings, snapshot_hash=wanted)
            except CatalogError as exc:
                session.rollback()
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(EXIT_USAGE if wanted else EXIT_RUN_NOT_SUCCEEDED) from exc
            except (SpecError, SnapshotError, FitError, ArtifactError) as exc:
                session.rollback()
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED) from exc
            session.commit()
    finally:
        engine.dispose()
    payload = summary.as_dict()
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(f"snapshot {summary.snapshot}")
    typer.echo(
        f"fitted={payload['fitted']} existing={payload['existing']} "
        + " ".join(f"{status}={count}" for status, count in payload["statuses"].items())
    )
    for model in payload["models"]:
        window = "-" if model["window_days"] is None else model["window_days"]
        typer.echo(
            f"{model['source']}\t{model['target']}\t{window}\t{model['status']}\t"
            f"rows={model['rows']}\tevents={model['events']}"
        )


@models_app.command("list")
def models_list(
    snapshot: Annotated[
        str | None,
        typer.Option("--snapshot", help="The snapshot hash (default: the latest snapshot)."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of a table.")] = False,
) -> None:
    """List the models of the latest or the named snapshot with their status (read-only role)."""
    import json

    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.session import make_engine
    from judgemetrics.metrics.adjustment.catalog import CatalogError, list_models

    wanted = _validated_snapshot(snapshot)
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        with Session(engine) as session:
            try:
                content_hash, rows = list_models(session, snapshot_hash=wanted)
            except CatalogError as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(EXIT_USAGE) from exc
            session.rollback()
    finally:
        engine.dispose()
    if as_json:
        payload = {"snapshot": content_hash, "models": [row.as_dict() for row in rows]}
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(f"snapshot {content_hash}")
    if not rows:
        typer.echo("no models: run `judgemetrics models fit`")
        return
    typer.echo("id\tsource\ttarget\twindow\tstatus\tn_train\tevents_train\tn_test\tevents_test")
    for row in rows:
        window = "-" if row.window_days is None else str(row.window_days)
        typer.echo(
            f"{row.id}\t{row.source}\t{row.target}\t{window}\t{row.status}\t"
            f"{row.n_train}\t{row.events_train}\t{row.n_test}\t{row.events_test}"
        )


def render_model_card(card: dict[str, Any]) -> list[str]:
    """The text lines of ``models show``: header, counts, diagnostics, coefficients."""
    window = "-" if card.get("window_days") is None else card["window_days"]
    lines = [
        f"model {card['id']} ({card['content_hash']})",
        f"target {card['target']} window {window} status {card['status']}",
        f"source {card['source']} snapshot {card['snapshot']}",
        f"specification {card['spec_version']} {card['model_version']} seed {card['seed']} "
        f"code {card['code_version']}",
        f"training {card['train_start']} .. {card['train_end']} cutoff {card['split_cutoff']}",
        f"train rows={card['n_train']} events={card['events_train']} "
        f"test rows={card['n_test']} events={card['events_test']}",
    ]
    diagnostics = card.get("diagnostics")
    if isinstance(diagnostics, dict):
        summary = " ".join(
            f"{name}={diagnostics[name]}"
            for name in (
                "status",
                "brier",
                "brier_skill",
                "auc",
                "calibration_in_the_large",
                "calibration_slope",
            )
            if name in diagnostics
        )
        lines.append(f"diagnostics {summary}")
        for item in diagnostics.get("bins") or []:
            lines.append(
                f"  bin {item['bin']}: n={item['count']} predicted={item['mean_predicted']} "
                f"observed={item['observed_rate']}"
            )
    coefficients = card.get("coefficients")
    if isinstance(coefficients, list):
        lines.append("column\tlevel\testimate\tsd\tsign_agreement")
        for item in coefficients:
            lines.append(
                f"{item['column']}\t{item['level']}\t{item['estimate']}\t{item['sd']}\t"
                f"{item['sign_agreement']}"
            )
    else:
        lines.append("no coefficients")
    return lines


@models_app.command("show")
def models_show(
    identifier: Annotated[str, typer.Argument(help="A model id (UUID) or its content hash.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of text.")] = False,
) -> None:
    """Print a model card: columns and coefficients, counts, diagnostics (read-only role)."""
    import json

    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.session import make_engine
    from judgemetrics.metrics.adjustment.catalog import (
        CatalogError,
        model_card,
        parse_model_identifier,
    )

    try:
        parsed = parse_model_identifier(identifier)
    except CatalogError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        with Session(engine) as session:
            try:
                card = model_card(session, parsed)
            except CatalogError as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(EXIT_USAGE) from exc
            session.rollback()
    finally:
        engine.dispose()
    if as_json:
        typer.echo(json.dumps(card, indent=2, sort_keys=True))
        return
    for line in render_model_card(card):
        typer.echo(line)


@models_app.command("verify")
def models_verify(
    snapshot: Annotated[
        str | None, typer.Option("--snapshot", help="Only the models of this snapshot hash.")
    ] = None,
    refit: Annotated[
        bool, typer.Option("--refit", help="Refit every model and compare the artifact bytes.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of text.")] = False,
) -> None:
    """Check every artifact against its row (and reproduce it with --refit); exit 1 on a mismatch."""
    import json

    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.session import make_engine
    from judgemetrics.logging import configure_logging
    from judgemetrics.metrics.adjustment.artifacts import ArtifactError
    from judgemetrics.metrics.adjustment.catalog import verify_models
    from judgemetrics.metrics.adjustment.fit import FitError
    from judgemetrics.metrics.adjustment.spec import SpecError
    from judgemetrics.metrics.snapshot import SnapshotError

    wanted = _validated_snapshot(snapshot)
    settings = get_settings()
    configure_logging(settings)
    engine = make_engine(settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            try:
                result = verify_models(session, settings, snapshot_hash=wanted, refit=refit)
            except (SnapshotError, SpecError, FitError, ArtifactError) as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(EXIT_USAGE) from exc
            session.rollback()
    finally:
        engine.dispose()
    if as_json:
        typer.echo(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        typer.echo(
            f"models={result.models} verified={result.verified} refitted={result.refitted} "
            f"problems={len(result.problems)}"
        )
        lines = [
            f"mismatch: model {problem.model_id} {problem.target}"
            + ("" if problem.window_days is None else f"@{problem.window_days}")
            + f" field={problem.field}: {problem.detail}"
            for problem in result.problems
        ]
        for line in lines[:VERIFY_REPORT_LINES]:
            typer.echo(line, err=True)
        if len(lines) > VERIFY_REPORT_LINES:
            typer.echo(f"... {len(lines) - VERIFY_REPORT_LINES} more", err=True)
    if not result.ok:
        raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED)


# --- validation: the model validation report -------------------------------------------


@validation_app.command("report")
def validation_report(
    out: Annotated[
        Path,
        typer.Option(
            "--out",
            help="Where to write (a relative path is under the repository root).",
            dir_okay=False,
        ),
    ] = Path("docs") / "VALIDATION.md",
    check: Annotated[
        bool,
        typer.Option("--check", help="Compare with the file instead of writing; exit 1 on a diff."),
    ] = False,
    truth: Annotated[
        Path | None,
        typer.Option(
            "--truth",
            help="The synthetic dataset directory holding manifest.json and truth/ "
            "(default: JUDGEMETRICS_SYNTHETIC_DIR, skipped when it does not exist).",
            file_okay=False,
        ),
    ] = None,
) -> None:
    """Render docs/VALIDATION.md from the latest snapshot's expected-outcome models.

    Runs as the ingest role (the subgroup calibration reads the restricted
    schema in aggregate). Exits 1 with a unified diff when --check finds the
    file differs, 2 when no snapshot or model can be read or the truth
    directory is unreadable or describes another dataset.
    """
    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.session import make_engine
    from judgemetrics.logging import configure_logging
    from judgemetrics.metrics.methodology import resolve_output
    from judgemetrics.metrics.snapshot import SnapshotError
    from judgemetrics.validation.fairness import FairnessError
    from judgemetrics.validation.report import (
        ReportError,
        build_report,
        check_report,
        render_report,
        write_report,
    )

    settings = get_settings()
    configure_logging(settings)
    if truth is not None and not truth.is_dir():
        typer.echo("error: --truth is not a directory", err=True)
        raise typer.Exit(EXIT_USAGE)
    truth_dir = truth if truth is not None else settings.synthetic_dir
    target = resolve_output(out)
    engine = make_engine(settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            try:
                report = build_report(session, settings, truth_dir=truth_dir)
            except (ReportError, FairnessError, SnapshotError) as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(EXIT_USAGE) from exc
            finally:
                session.rollback()
    finally:
        engine.dispose()
    rendered = render_report(report)
    if check:
        diff = check_report(target, rendered)
        if diff:
            typer.echo(f"{target} differs from the validation render:", err=True)
            for line in diff[:METHODOLOGY_DIFF_LINES]:
                typer.echo(line, err=True)
            if len(diff) > METHODOLOGY_DIFF_LINES:
                typer.echo(f"... {len(diff) - METHODOLOGY_DIFF_LINES} more lines", err=True)
            raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED)
        typer.echo(f"{target} is up to date")
        return
    write_report(target, rendered)
    typer.echo(f"wrote {target}")


@validation_app.command("recovery")
def validation_recovery(
    truth: Annotated[
        Path,
        typer.Option(
            "--truth",
            help="The synthetic dataset directory holding manifest.json and truth/.",
            file_okay=False,
        ),
    ],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of text.")] = False,
) -> None:
    """The planted-effect recovery of the latest snapshot's published adjusted figures.

    Exits 1 when a figure is below the specification's recovery tolerance,
    2 when no snapshot is recorded or the truth directory is unreadable or
    describes no ingested synthetic source.
    """
    import json

    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.session import make_engine
    from judgemetrics.logging import configure_logging
    from judgemetrics.metrics.adjustment.catalog import CatalogError
    from judgemetrics.metrics.adjustment.spec import load_spec
    from judgemetrics.metrics.registry import load_registry
    from judgemetrics.validation.recovery import TruthError, read_truth, recovery_for_truth

    settings = get_settings()
    configure_logging(settings)
    engine = make_engine(settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            try:
                results = recovery_for_truth(
                    session, read_truth(truth), spec=load_spec(), registry=load_registry()
                )
            except (TruthError, CatalogError) as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(EXIT_USAGE) from exc
            finally:
                session.rollback()
    finally:
        engine.dispose()
    passed = all(result.passed for result in results)
    if as_json:
        typer.echo(
            json.dumps(
                {"passed": passed, "fits": [result.as_dict() for result in results]},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for r in results:
            window = "-" if r.window_days is None else r.window_days

            def num(value: float | None) -> str:
                return "-" if value is None else f"{value:.3f}"

            typer.echo(
                f"{r.target}	{window}	judges={r.judges}	"
                f"spearman={num(r.spearman)} (min {r.spearman_minimum:g})	"
                f"raw={num(r.raw_spearman)}	sign={r.sign_agreed}/{r.sign_checked}	"
                f"expected_r={num(r.expected_correlation)} (min {r.expected_minimum:g})	"
                f"coverage={num(r.coverage)} (min {r.coverage_minimum:g})	"
                + ("met" if r.passed else "NOT MET")
            )
    if not passed:
        raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED)


# --- sources: the Cook County profile and fixture excerpt -------------------------------

PROFILED_SOURCES = ("cook_sao",)


def _profiled_source(source_id: str) -> None:
    if source_id not in PROFILED_SOURCES:
        typer.echo(
            f"error: no profile or excerpt exists for source {source_id!r} "
            f"(supported: {', '.join(PROFILED_SOURCES)})",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)


def _source_artifacts(from_fixture: Path | None, work_dir: Path) -> list[Any]:
    """The five Cook County exports: a fixture directory, or the raw lake as the ingest role."""
    from sqlalchemy.orm import Session

    from judgemetrics.config import get_settings
    from judgemetrics.db.session import make_engine
    from judgemetrics.ingest.cook_sao.stored import (
        ArtifactsError,
        fixture_artifacts,
        lake_artifacts,
    )
    from judgemetrics.ingest.store import RawStoreError, open_raw_store
    from judgemetrics.logging import configure_logging

    try:
        if from_fixture is not None:
            return list(fixture_artifacts(from_fixture))
        settings = get_settings()
        configure_logging(settings)
        store = open_raw_store(settings)
        engine = make_engine(settings.effective_ingest_database_url)
        try:
            with Session(engine) as session:
                try:
                    return list(lake_artifacts(session, store, work_dir))
                finally:
                    session.rollback()
        finally:
            engine.dispose()
    except (ArtifactsError, RawStoreError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc


@sources_app.command("profile")
def sources_profile(
    source_id: Annotated[str, typer.Argument(help="The source to profile (cook_sao).")],
    out: Annotated[
        Path,
        typer.Option(
            "--out",
            help="Where to write (a relative path is under the repository root).",
            dir_okay=False,
        ),
    ] = Path("data") / "reference" / "cook_sao" / "profile.yaml",
    check: Annotated[
        bool,
        typer.Option("--check", help="Compare with the file instead of writing; exit 1 on a diff."),
    ] = False,
    from_fixture: Annotated[
        Path | None,
        typer.Option(
            "--from-fixture",
            help="Profile a directory of the five CSVs instead of the stored artifacts.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Derive the value-set profile from SOURCE_ID's stored exports (the ingest role).

    Reads the latest stored export of each dataset from the raw lake,
    streamed to a temporary directory and verified against its digest;
    the same artifacts always render the same bytes. Exits 1 with a
    unified diff when --check finds the file differs, 2 when the artifacts
    cannot be read.
    """
    import tempfile

    from judgemetrics.ingest.cook_sao.profile import (
        ProfileError,
        build_profile,
        check_profile,
        render_profile,
        write_profile,
    )
    from judgemetrics.metrics.methodology import resolve_output

    _profiled_source(source_id)
    target = resolve_output(out)
    with tempfile.TemporaryDirectory(prefix="judgemetrics-profile-") as work:
        artifacts = _source_artifacts(from_fixture, Path(work))
        try:
            rendered = render_profile(build_profile(artifacts))
        except ProfileError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(EXIT_USAGE) from exc
    if check:
        diff = check_profile(target, rendered)
        if diff:
            typer.echo(f"{target} differs from the profile render:", err=True)
            for line in diff[:METHODOLOGY_DIFF_LINES]:
                typer.echo(line, err=True)
            if len(diff) > METHODOLOGY_DIFF_LINES:
                typer.echo(f"... {len(diff) - METHODOLOGY_DIFF_LINES} more lines", err=True)
            raise typer.Exit(EXIT_RUN_NOT_SUCCEEDED)
        typer.echo(f"{target} is up to date")
        return
    write_profile(target, rendered)
    typer.echo(f"wrote {target}")


@sources_app.command("excerpt")
def sources_excerpt(
    source_id: Annotated[str, typer.Argument(help="The source to excerpt (cook_sao).")],
    out: Annotated[
        Path,
        typer.Option(
            "--out",
            help="The directory to write the five CSVs and the README into.",
            file_okay=False,
            resolve_path=True,
        ),
    ],
    from_fixture: Annotated[
        Path | None,
        typer.Option(
            "--from-fixture",
            help="Excerpt a directory of the five CSVs instead of the stored artifacts.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Write the stratified real-row fixture of SOURCE_ID (restricted columns blanked).

    The strata come from the committed profile
    (data/reference/cook_sao/profile.yaml), which must describe the stored
    exports; excerpting the committed fixture itself writes identical bytes.
    Exits 2 when the profile or the artifacts cannot be read.
    """
    import tempfile

    from judgemetrics.config import REPO_ROOT
    from judgemetrics.ingest.cook_sao.excerpt import (
        ExcerptError,
        check_profile_matches,
        write_excerpt,
    )
    from judgemetrics.ingest.cook_sao.profile import PROFILE_PATH, ProfileError, load_profile

    _profiled_source(source_id)
    if from_fixture is not None and from_fixture.resolve() == out.resolve():
        typer.echo("error: --out must differ from --from-fixture", err=True)
        raise typer.Exit(EXIT_USAGE)
    try:
        profile = load_profile(REPO_ROOT / PROFILE_PATH)
    except ProfileError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    with tempfile.TemporaryDirectory(prefix="judgemetrics-excerpt-") as work:
        artifacts = _source_artifacts(from_fixture, Path(work))
        try:
            if from_fixture is None:
                check_profile_matches(profile, artifacts)
            excerpt = write_excerpt(artifacts, profile, out)
        except (ExcerptError, ProfileError) as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(EXIT_USAGE) from exc
    typer.echo(f"wrote {out}: {len(excerpt.chosen)} cases")
    for stratum in excerpt.unsatisfied:
        typer.echo(f"no case satisfies: {stratum.label}")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
