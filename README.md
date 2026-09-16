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
the scanned API container image), the ingest framework with its first
real connector (`uv run poe ingest-fjc` loads the Federal Judicial
Center's judges, courts, and service records into an immutable raw lake
and the canonical tables, idempotently, with provenance down to the
stored bytes), and the public API v1 (paginated, strictly validated,
rate-limited search, provenance on every entity) are in place; the web
foundation is next. See:

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
uv run poe migrate      # Alembic migrations: every canonical table, as the admin role
uv run poe ingest-fjc   # FJC judges → raw lake (MinIO) + canonical tables, as the ingest role
uv run poe dev-api      # http://127.0.0.1:8000/api/v1/docs (Swagger UI over the API below)
uv run poe check        # lint, format check, type check, tests
uv run poe gate         # the fail-closed security gate, on demand
uv run poe down         # stop the services
uv run judgemetrics --help   # db upgrade|downgrade|current, serve, ingest list-sources|run|runs, openapi export
```

## API v1

The read-only API ([`docs/API.md`](docs/API.md); OpenAPI document
committed at [`docs/openapi.json`](docs/openapi.json)) serves the
canonical tables with pagination (`limit` ≤ 100), strict filter
validation (unknown parameters are 422), a uniform error envelope,
`Cache-Control` on lists and details, provenance on every entity, and a
rate-limited trigram search:

| Endpoint                                   | Purpose                                   |
|--------------------------------------------|-------------------------------------------|
| `GET /api/v1/health`, `/ready`             | liveness and readiness probes             |
| `GET /api/v1/judges`                       | list; filters `q`, `court_id`, `active_on`, `status` |
| `GET /api/v1/judges/{id}`                  | detail with service records and provenance |
| `GET /api/v1/judges/{id}/service`          | service records, oldest first             |
| `GET /api/v1/courts`                       | list; filters `jurisdiction_id`, `court_type` |
| `GET /api/v1/courts/{id}`                  | detail with provenance                    |
| `GET /api/v1/jurisdictions`                | list                                      |
| `GET /api/v1/jurisdictions/{id}`           | detail with provenance                    |
| `GET /api/v1/search?q=`                    | judges and courts by name similarity (rate limited) |

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
│   ├── ARCHITECTURE.md     ingest pipeline, raw lake, idempotency rules, roles, API layering
│   ├── API.md              the API contract: pagination, filters, errors, rate limits, provenance
│   ├── openapi.json        the generated OpenAPI document (judgemetrics openapi export)
│   ├── DATA_MODEL.md       the twenty-three tables, natural keys, indexes, grants
│   ├── phase01-roadmap.md  executable Phase 1 plan
│   └── brief/              the product specification, verbatim
├── alembic/                migration environment and versions (0001, 0002)
├── data/                   reference tables (tracked); raw lake and synthetic data (untracked)
├── alembic.ini             Alembic config (the URL comes from settings, never the ini)
├── infra/docker/           api.Dockerfile and postgres/ init scripts (extensions, roles)
├── planning/               roadmodel planning kit (selector, catalog, templates)
├── scripts/                cross-platform helper and verify scripts
├── src/judgemetrics/       config, logging, main (FastAPI), cli, api/, schemas/, services/, repositories/, db/, ingest/, quality/, normalization/
├── tests/unit/, tests/integration/, tests/fixtures/
├── pyproject.toml          uv project; dev and planning groups; poe tasks
└── uv.lock
```

Planned from later Phase 1 steps: `web/` (Next.js).

## Data

Sources enter only through the due-diligence register in
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md). The first ingested
source is the Federal Judicial Center's biographical directory export
(Phase 1: `uv run poe ingest-fjc`, see `docs/ARCHITECTURE.md`),
followed by a deterministic synthetic justice dataset (Phase 2); the
first real state-court corpus is the Cook County State's Attorney's
case-level datasets (Phase 5), with the Florida pilot following once
lawful access is secured (Phase 7).

## License

The code is licensed under the [Apache License 2.0](LICENSE). The data
license follows the legal review in Phase 6.
