<!-- README.md -->
# JudgeMetrics

A transparent, reproducible analytics platform over public criminal-court
records. JudgeMetrics connects judicial assignments, case events,
dispositions, pretrial decisions, sentences, and documented subsequent
justice-system events so that judicial outcomes can be measured and
compared — with every statistic traceable to versioned source records
and a published methodology.

It is not a judge-review site and it does not produce a "good judge" or
"bad judge" score. It reports documented outcomes, comparative
statistics with their uncertainty, and the coverage and limitations of
the data behind them.

## Status

Pre-alpha. Phase 1 (canonical schema and the judge vertical slice) is in
progress: the governance chassis (license, security gate, CI, branch
protection, Compose services) and the application core (settings, JSON
logging, the FastAPI app with health probes, the twenty-three canonical
tables behind a reversible Alembic baseline, the `judgemetrics` CLI, and
the scanned API container image) are in place; the ingest framework and
the FJC connector are next. See:

- [`ROADMAP.md`](ROADMAP.md) — the eight-phase plan.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — current phase, completed
  items, unresolved data-access questions, next milestones.
- [`docs/phase01-roadmap.md`](docs/phase01-roadmap.md) — the next
  executable step.
- [`docs/brief/`](docs/brief/) — the product specification.

## Principles

1. Source every material claim.
2. Preserve raw source records immutably.
3. Separate facts from derived statistics.
4. Separate observed outcomes from causal claims.
5. Separate judicial actions from prosecutor, legislature, jury, clerk,
   and law-enforcement actions.
6. Show uncertainty, sample size, and missing-data limitations.
7. Make methodology inspectable and reproducible.
8. Prefer APIs and bulk public data over brittle scraping.
9. Minimize public exposure of personally identifying defendant
   information.
10. Treat data lineage as a first-class feature.

## Quick start

Requirements: [uv](https://docs.astral.sh/uv/) (Python 3.13 is fetched
automatically) and Git. Docker and Node 22 with pnpm are needed from
Phase 1 onward.

```sh
uv sync                 # creates .venv with the dev and planning groups
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
cp .env.example .env    # then replace every change-me
uv run poe up           # PostgreSQL 17 (pg_trgm, roles) + MinIO, healthy
uv run poe migrate      # Alembic baseline: every canonical table, as the admin role
uv run poe dev-api      # http://127.0.0.1:8000/api/v1/health and /api/v1/ready
uv run poe check        # lint, format check, type check, tests
uv run poe gate         # the fail-closed security gate, on demand
uv run poe down         # stop the services
uv run judgemetrics --help   # db upgrade|downgrade|current, serve, ingest list-sources
```

The API image builds with `docker build -f infra/docker/api.Dockerfile .`
and runs beside the services with `docker compose --profile app up`
(port 8000; CI builds and vulnerability-scans it on every pull request).

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the command interface, the
security gate, branch naming, and the step lifecycle.

`uv run poe <task>` is the cross-platform command interface; the
`Makefile` mirrors every target (`make check`, `make test`, …) where GNU
make is installed. From Phase 3 a single `uv run poe bootstrap` brings
up the database, migrates it, and seeds the synthetic demo dataset.

## Planning with roadmodel

Roadmaps are authored with the
[roadmodel](https://github.com/nathanramoscfa/roadmodel) planning kit
exported to `planning/`. The AI in the editor runs the model selector
itself against the operator context; nothing calls a paid API. The
operator context file is not tracked; regenerate the kit from your own
`~/.config/roadmodel/user-context.md` with:

```sh
uv run poe kit
```

Re-export at the start of every phase so the catalog is current.

## Repository layout

```
judge-metrics/
├── ROADMAP.md              project roadmap
├── AGENTS.md               operating instructions for AI agents (CLAUDE.md imports it)
├── CONTRIBUTING.md         command interface, security gate, step lifecycle
├── SECURITY.md             private vulnerability disclosure
├── Makefile                shim over the poe task interface
├── docker-compose.yml      PostgreSQL 17 (pg_trgm, three roles) and MinIO
├── .env.example            every environment variable, placeholders only
├── .pre-commit-config.yaml the fail-closed local security gate
├── .github/                CI workflow, Dependabot, issue and PR templates
├── docs/
│   ├── ROADMAP.md          status, open questions, next milestones
│   ├── DATA_SOURCES.md     source register with verification status
│   ├── phase01-roadmap.md  executable Phase 1 plan
│   └── brief/              the product specification, verbatim
├── alembic/                migration environment and versions (0001_baseline)
├── alembic.ini             Alembic config (the URL comes from settings, never the ini)
├── infra/docker/           api.Dockerfile and postgres/ init scripts (extensions, roles)
├── planning/               roadmodel planning kit (selector, catalog, templates)
├── scripts/                cross-platform helper and verify scripts
├── src/judgemetrics/       config, logging, main (FastAPI), cli, api/, db/, normalization/
├── tests/unit/, tests/integration/
├── pyproject.toml          uv project; dev and planning groups; poe tasks
└── uv.lock
```

Planned from later Phase 1 steps: `web/` (Next.js), `data/` (reference
tables and fixtures; the raw lake and generated synthetic data are
untracked).

## Data

Sources enter only through the due-diligence register in
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md). The first ingested
sources are the Federal Judicial Center's biographical directory export
(Phase 1) and a deterministic synthetic justice dataset (Phase 2); the
first real state-court corpus is the Cook County State's Attorney's
case-level datasets (Phase 5), with the Florida pilot following once
lawful access is secured (Phase 7).

## License

The code is licensed under the [Apache License 2.0](LICENSE). The data
license follows the legal review in Phase 6.
