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

Pre-alpha. Phase 1 (canonical schema and the judge vertical slice) is
complete (`v0.1.0-phase-1`): the governance chassis (license, security gate, CI, branch
protection, Compose services) and the application core (settings, JSON
logging, the FastAPI app with health probes, the twenty-three canonical
tables behind a reversible Alembic baseline, the `judgemetrics` CLI, and
the scanned API container image), the ingest framework with its first
real connector (`uv run poe ingest-fjc` loads the Federal Judicial
Center's judges, courts, and service records into an immutable raw lake
and the canonical tables, idempotently, with provenance down to the
stored bytes), the public API v1 (paginated, strictly validated,
rate-limited search, provenance on every entity), and the web
foundation (`web/`: Next.js pages for home, search, judge, court, and
methodology over a client generated from the OpenAPI document, with a
Playwright smoke test and a scanned web image) are in place, verified
by `scripts/verify_phase01.py` (43 static checks, the tool suites, and
the V1–V6 matrix; `docs/phase01-qa-findings.md`) under the required
`phase-verify (01)` check. Phase 2 (the synthetic justice dataset,
entity resolution, and case timelines) is in progress: Step 1 shipped
the deterministic synthetic generator (`uv run judgemetrics synthetic
generate`, [`docs/SYNTHETIC_DATA.md`](docs/SYNTHETIC_DATA.md)) and its
golden fixture; Step 2 the `synthetic` connector, case-level publishing
with natural keys (migration `0003`), the versioned case vocabulary,
peppered person-identifier hashing, the case-level data-quality checks,
and `uv run poe seed`, which loads the demo dataset (5 courts, 24
judges, 5,200 cases, 3,225 persons) idempotently; Step 3 the staged
person-resolution framework with its review queue, merges, and
append-only audit log (`judgemetrics er run|review list|review decide`,
[`docs/ENTITY_RESOLUTION.md`](docs/ENTITY_RESOLUTION.md)); Step 4 the
case, timeline, judge-cases, and coverage endpoints with a `synthetic`
flag on every response, the case page, the judge cases panel and list,
the coverage page, and the site-wide demo-data banner. Phase 3 (the
metrics engine and the complete local demo) is in progress: Step 1
shipped the versioned metric registry, the analytic frame, and the
generated methodology ([`docs/METHODOLOGY.md`](docs/METHODOLOGY.md));
Step 2 the computation engine — `uv run poe compute-metrics` exports a
hashed Parquet snapshot, computes every registry metric for every judge
and court with its members, and publishes observations that
`uv run judgemetrics metrics verify` reproduces exactly, with pipeline
step 13 recomputing the subjects an ingest touched; Step 3 the
provenance trace (`uv run judgemetrics provenance trace <observation
id>` and `GET /api/v1/metrics/{id}/provenance` walk from a published
number to the raw artifacts, [`docs/PROVENANCE.md`](docs/PROVENANCE.md)),
the metrics API (the registry, every observation of a judge or court
with numerator, denominator, date range, coverage, sample size,
interval, suppression, and methodology link, the compare table,
coverage v1), and the corrections intake (`POST /api/v1/corrections`,
the contact encrypted at rest under a key the API can never read
back). See:

- [`ROADMAP.md`](ROADMAP.md) — the eight-phase plan.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — current phase, completed
  items, unresolved data-access questions, next milestones.
- [`docs/phase01-roadmap.md`](docs/phase01-roadmap.md) — the Phase 1
  execution plan and its post-implementation verification.
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
uv run poe seed         # generate data/synthetic/20260916 (demo scale) and ingest it through the synthetic connector
uv run judgemetrics synthetic generate   # the generator alone → data/synthetic/20260916/{source,truth,manifest.json}
uv run poe dev-api      # http://127.0.0.1:8000/api/v1/docs (Swagger UI over the API below)
uv run poe dev-web      # http://localhost:3000 (the web app, against the API above)
uv run poe check        # lint, format check, type check, tests
uv run poe gate         # the fail-closed security gate, on demand
uv run poe down         # stop the services
uv run judgemetrics er run   # recompute person candidates and apply system merges (also: er review list|decide)
uv run judgemetrics methodology render --check   # docs/METHODOLOGY.md equals the metric registry render (omit --check to rewrite it)
uv run poe compute-metrics   # export a snapshot under data/snapshots/<hash>/ and publish every registry metric for every judge and court
uv run judgemetrics metrics verify   # recompute every current observation from its snapshot; exit 1 on any mismatch
uv run judgemetrics provenance trace <observation id> [--json]   # the chain from a published number to the raw artifacts; exit 1 when incomplete
uv run judgemetrics --help   # db upgrade|downgrade|current, serve, ingest list-sources|run|runs, openapi export, synthetic generate|verify, seed, er run|review, methodology render, metrics compute|verify, provenance trace
```

`ingest run` and `seed` need `JUDGEMETRICS_IDENTIFIER_PEPPER` in `.env`
(any long random string; it peppers the sha256 hashes under which person
identifiers are stored, and changing it orphans every hash — back it up
with the database). The API (`uv run poe dev-api`) needs
`JUDGEMETRICS_CORRECTION_CONTACT_KEY`, a Fernet key that encrypts every
correction request's contact at rest; it refuses to start without one
outside the test environment (generate one with the command in
`.env.example` and back it up with the database).

## API v1

The API ([`docs/API.md`](docs/API.md); OpenAPI document committed at
[`docs/openapi.json`](docs/openapi.json)) serves the canonical tables and
the published metrics with pagination (`limit` ≤ 100), strict filter
validation (unknown parameters are 422), a uniform error envelope,
`Cache-Control` on lists and details, provenance on every entity, a
rate-limited trigram search, and one rate-limited write path:

| Endpoint                                   | Purpose                                   |
|--------------------------------------------|-------------------------------------------|
| `GET /api/v1/health`, `/ready`             | liveness and readiness probes             |
| `GET /api/v1/judges`                       | list; filters `q`, `court_id`, `active_on`, `status` |
| `GET /api/v1/judges/{id}`                  | detail with service records and provenance |
| `GET /api/v1/judges/{id}/service`          | service records, oldest first             |
| `GET /api/v1/judges/{id}/cases`            | the judge's cases; filters `filed_from`, `filed_to`, `status`, `case_type` |
| `GET /api/v1/courts`                       | list; filters `jurisdiction_id`, `court_type` |
| `GET /api/v1/courts/{id}`                  | detail with provenance                    |
| `GET /api/v1/jurisdictions`                | list                                      |
| `GET /api/v1/jurisdictions/{id}`           | detail with provenance                    |
| `GET /api/v1/cases/{id}`                   | parties (public keys), assignments, charges, attributed decisions, sentences, provenance |
| `GET /api/v1/cases/{id}/timeline`          | every dated fact of the case, chronological, each citing its artifact |
| `GET /api/v1/search?q=`                    | judges and courts by name similarity, cases by exact number (rate limited) |
| `GET /api/v1/coverage`                     | per-source counts, filing and coverage windows, observable outcomes, last run, latest snapshot, `synthetic_present` |
| `GET /api/v1/metrics`                      | the metric registry: definitions, versions, thresholds, the known limitations verbatim |
| `GET /api/v1/judges/{id}/metrics`, `/courts/{id}/metrics` | every current observation with numerator, denominator, date range, coverage, sample size, interval, suppression, methodology link |
| `GET /api/v1/metrics/compare`              | one metric and window for the judges of a court or jurisdiction, sorted and paginated, with coverage warnings |
| `GET /api/v1/metrics/{id}/provenance`      | the chain from the observation to the raw artifacts ([`docs/PROVENANCE.md`](docs/PROVENANCE.md)) |
| `POST /api/v1/corrections`                 | a data-correction request; the contact is encrypted at rest (rate limited) |

Every summary, detail, search result, provenance block, and observation
carries `synthetic: bool`; persons appear only as pseudonymous public
keys, and never in a metrics response. A suppressed observation (a
denominator below the metric's threshold) leaves the API with its
numbers null.

The API image builds with `docker build -f infra/docker/api.Dockerfile .`
and runs beside the services with `docker compose --profile app up`
(port 8000; CI builds and vulnerability-scans it on every pull request).

## Web

The web application in [`web/`](web/) (Next.js App Router, TypeScript,
Tailwind CSS, shadcn/ui, TanStack Table; light and dark mode) renders
the home page with global search and coverage tiles, `/search` (judges,
courts, exact case numbers), `/judges/[judgeId]` (identity, service
timeline, cases panel, source coverage panel with each artifact's
sha256), `/judges/[judgeId]/cases` (filtered, paginated case list),
`/cases/[caseId]` (timeline, charges, judge assignments, attributed
decisions with actor badges, disposition, sentence, sources),
`/courts/[courtId]` (judges serving on a chosen date), `/compare` (one
objective metric across the judges of a court or jurisdiction: a
sortable table with numerator and denominator, interval, sample size,
coverage warnings, suppressed rows marked, the state in the query
string), `/methodology` (rendered from `GET /api/v1/metrics`: how to
read a number, the index-event semantics, one anchored section per
metric definition, suppression, the eight known limitations verbatim,
the changelog), and `/coverage` (the snapshot card and, per source, the
coverage window, observable and not-observable outcomes, the latest
snapshot, and the methodology version). The judge page carries the
association statement above its Cases, Pretrial, Outcomes after
qualifying release (window selector), Disposition, and Sentencing
panels; every number renders through one component that always shows
the numerator, denominator, date range, coverage, sample size, the
interval, and the methodology link, beside the court's pooled value and
the judge's position in the comparison cohort (same court or
jurisdiction, same period). A persistent demo-data banner (its coverage
read cached in-process for sixty seconds) appears whenever a synthetic
source is present and every synthetic record carries a badge. Its API client is generated from
`docs/openapi.json` and it reads one variable, `NEXT_PUBLIC_API_BASE_URL`.

```sh
cd web
cp .env.example .env.local          # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
corepack enable                     # pnpm at the version package.json pins
pnpm install --frozen-lockfile
pnpm dev                            # or, from the repo root: uv run poe dev-web
pnpm lint && pnpm typecheck && pnpm test && pnpm build
pnpm generate:api                   # after any API route or schema change
pnpm exec playwright install chromium
pnpm e2e                            # against a running API and web server
```

Node 22 (`.node-version`) and pnpm via corepack are the only tooling.
The web image builds with `docker build -f infra/docker/web.Dockerfile
web` and runs as the Compose `web` service (profile `app`, port 3000)
next to the API.

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
│   ├── openapi.json        the generated OpenAPI document (judgemetrics openapi export); the web client is generated from it
│   ├── DATA_MODEL.md       the twenty-six tables, natural keys, indexes, grants
│   ├── METHODOLOGY.md      rendered from the metric registry (judgemetrics methodology render); the semantics behind every number
│   ├── SYNTHETIC_DATA.md   the synthetic dataset: world model, source format, planted edge cases, truth/, determinism
│   ├── phaseNN-roadmap.md  executable per-phase plans
│   └── brief/              the product specification, verbatim
├── alembic/                migration environment and versions (0001–0005)
├── data/                   reference tables (tracked: us_states, synthetic_offenses, case_vocabulary, entity_resolution_thresholds, metric_registry); raw lake and synthetic data (untracked)
├── alembic.ini             Alembic config (the URL comes from settings, never the ini)
├── infra/docker/           api.Dockerfile, web.Dockerfile, and postgres/ init scripts (extensions, roles)
├── planning/               roadmodel planning kit (selector, catalog, templates)
├── scripts/                cross-platform helper and verify scripts
├── src/judgemetrics/       config, logging, main (FastAPI), cli, api/, schemas/, services/, repositories/, db/, ingest/, quality/, normalization/, synthetic/, entity_resolution/, metrics/
├── tests/unit/, tests/integration/, tests/property/, tests/golden/, tests/fixtures/
├── web/                    Next.js app: app/ (pages), components/, lib/api/ (generated client), tests/unit, tests/e2e
├── .node-version           Node 22 for web/
├── pyproject.toml          uv project; dev and planning groups; poe tasks
└── uv.lock
```

## Data

Sources enter only through the due-diligence register in
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md). The first ingested
source is the Federal Judicial Center's biographical directory export
(Phase 1: `uv run poe ingest-fjc`, see `docs/ARCHITECTURE.md`),
followed by a deterministic synthetic justice dataset (Phase 2:
`uv run judgemetrics synthetic generate`, `docs/SYNTHETIC_DATA.md`); the
first real state-court corpus is the Cook County State's Attorney's
case-level datasets (Phase 5), with the Florida pilot following once
lawful access is secured (Phase 7).

## License

The code is licensed under the [Apache License 2.0](LICENSE). The data
license follows the legal review in Phase 6.
