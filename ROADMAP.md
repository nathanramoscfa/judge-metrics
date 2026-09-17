# JudgeMetrics — Roadmap to a Reproducible Judicial-Outcomes Platform

> **Status:** Draft v2.1 (v2 supersedes v1, same day, after the full
> brief arrived; v2.1 adds the post-launch Phase 9)
> **Owner:** Nathan Ramos, founder and sole maintainer
> **Audience:** Maintainer and the AI coding agents executing phase steps;
> public once the repository is published
> **Target environment:** Local (Docker Compose) through Phase 7;
> vendor-neutral managed cloud from Phase 8
> **Last updated:** September 2026

This roadmap takes JudgeMetrics from a scaffolded repository with a
written brief to a public, reproducible analytics platform over public
criminal-court records: judicial assignments, case events, dispositions,
pretrial decisions, sentences, and documented subsequent justice-system
events, with every published statistic traceable to versioned source
records and code.

The product specification is the brief archived verbatim at
[`docs/brief/judgemetrics-master-project-specification.xml`](docs/brief/judgemetrics-master-project-specification.xml)
(authored with ChatGPT, September 2026). This roadmap executes it. Where
the roadmap departs from the brief, §2 "Changes from the original brief"
records the change and the reason, and §2 "Brief phases mapped to
roadmap phases" shows where each of the brief's thirteen development
phases landed. The brief's product principles, non-goals, canonical data
model, attribution model, outcome definitions, presentation rules,
security requirements, testing strategy, and statistical warnings apply
unchanged. The living status document the brief asks for is
[`docs/ROADMAP.md`](docs/ROADMAP.md).

---

## 1. Executive Summary

JudgeMetrics today is an empty application: a scaffolded Python 3.13
project managed by uv, a command interface, a planning kit, the archived
brief, and this roadmap. It needs to become a runnable platform that
ingests lawfully obtained public court data into an immutable raw lake,
normalizes it into a canonical event-level model with explicit actor
attribution, resolves judges, courts, cases, and pseudonymous persons,
computes descriptive and risk-adjusted outcome metrics with uncertainty,
and exposes all of it through a versioned API and a web interface that
shows numerators, denominators, coverage, and methodology on every
statistic. These constraints drive the work:

1. **Provenance or nothing.** Every canonical row carries a source
   record with a content hash, retrieval time, parser version, and
   ingest run; every metric carries a snapshot id, code version, and
   methodology version, and can be traced back to raw artifacts by a
   command. A number whose chain cannot be reconstructed is not
   published.
2. **Facts before inference.** Arrest, charge, conviction, dismissal,
   acquittal, release, sentence, and later events stay separate. Actor
   attribution (judge, prosecutor, jury, statute, unknown) is stored as
   data and gates every judge-level metric. Associations are never
   presented as causation, and no composite judge score exists.
3. **Demonstrable before real case data exists.** The brief's MVP is a
   complete local vertical slice on a deterministic synthetic justice
   dataset plus one genuine judge-data connector. Synthetic data with
   known truth is what lets entity resolution and every metric be
   golden-tested exactly; real data can only be sampled and audited.
4. **Data access is the critical path for real data.** The first real
   state-court corpus is one that is bulk-downloadable today under
   clear terms. Sources that need credentials, fees, or public-records
   requests (the Florida pilot, PACER) are workstreams with connector
   interfaces, runbooks, and operator wall-clock tasks; they never
   block the application from running.
5. **Privacy by default, solo builder plus AI agents.** Persons are
   pseudonymous in every public surface, sensitive attributes live in a
   restricted schema the public API cannot reach, small cohorts are
   suppressed, and a rapid suppression path exists before launch. Every
   phase is independently shippable, and each step is a fresh agent
   session with its own branch, security gate, and acceptance criteria.

The path: **scaffold → synthesize → measure → adjust → pilot → validate
→ expand → launch → sustain**. Phases 1–7 run locally with no cloud
spend; Phase 8 is the only cutover; Phase 9 is post-launch and funds
continued operation without paywalling anything the launch made free.

**First milestone.** The brief's seventeen-item first-milestone
checklist (one setup command, migrate, seed synthetic data, start API
and web, search a synthetic judge, open the profile, view metrics, open
an underlying case, view its timeline and provenance, compare against
the comparison cohort, read the methodology, run the full test suite) is
the exit condition of Phase 3. No production court data is required to
reach it.

### Scope by phase

| Phase | Data added                                              | What becomes demonstrable                                      |
|-------|---------------------------------------------------------|----------------------------------------------------------------|
| 1     | Federal judges (FJC Biographical Directory)             | Judge identity, service history, court roster; full canonical schema |
| 2     | Deterministic synthetic justice dataset                 | Cases, charges, decisions, sentences, timelines, entity resolution |
| 3     | Same                                                    | Descriptive and longitudinal metrics, compare, methodology, coverage, corrections form; first milestone |
| 4     | Same (with planted effects)                             | Risk-adjusted observed/expected ratios with intervals and validation |
| 5     | Cook County, IL felony cases (State's Attorney data)    | First real state-court metrics; Florida acquisition plan       |
| 6     | None                                                    | Quantified error rates, admin tools, corrections and suppression, legal review |
| 7     | Florida pilot jurisdiction, federal dockets (CourtListener, PACER interface) | Multi-jurisdiction comparison, coverage map |
| 8     | None                                                    | Production operation and public launch                         |
| 9     | None                                                    | Legal home, data license, research snapshots, keyed API tier, onboarding service, funding channels (post-launch) |

### Long-term scaling stages

| Brief stage  | Definition                                                  | Roadmap phases        |
|--------------|-------------------------------------------------------------|-----------------------|
| Prototype    | One real judge directory plus synthetic court outcomes      | 1–4                   |
| Pilot        | One state-court jurisdiction analysed end to end            | 5–6                   |
| State        | Multiple Florida counties or circuits on a common schema    | 7 onward              |
| Multi-state  | Connector framework extended to other states                | after launch          |
| National     | State adapters feeding one canonical justice-event model    | after launch          |

---

## 2. Current State Assessment

### What works today

- Repository scaffolded on Python 3.13 with uv: `pyproject.toml`, a
  `src/judgemetrics` package placeholder, `tests/test_smoke.py`, ruff,
  mypy (strict), pytest, pytest-cov, and poethepoet in the `dev` group;
  `uv run poe check` (lint, format check, type check, tests) is green;
  a `Makefile` shim mirrors the poe tasks for environments with GNU
  make.
- roadmodel 0.2.33 in the `planning` dependency group; the planning kit
  (selector, cost scale, templates, operator context) is exported to
  `planning/` and drives per-step model selection.
- The brief archived under `docs/brief/`, this roadmap, the Phase 1
  execution roadmap (`docs/phase01-roadmap.md`), the status document
  (`docs/ROADMAP.md`), the data-source register (`docs/DATA_SOURCES.md`),
  and the agent operating instructions (`AGENTS.md`, imported by
  `CLAUDE.md`).
- Data-source verification performed on 2026-09-15 for the FJC export,
  the Cook County datasets, and CourtListener bulk data.

Nothing else exists: no application code, no database, no ingested
data, no synthetic generator, no web app, no CI, no remote repository.

### Gaps blocking the first milestone and beyond

| #  | Gap                                                                    | Severity | Phase |
|----|------------------------------------------------------------------------|----------|-------|
| 1  | No provenance core (source, source_record, ingest_run) or raw lake     | Critical | 1     |
| 2  | No canonical schema or migrations                                      | Critical | 1     |
| 3  | No ingested data of any kind                                           | Critical | 1–2   |
| 4  | No synthetic justice dataset or golden regression fixture              | Critical | 2     |
| 5  | No entity-resolution framework or review queue                         | Critical | 2     |
| 6  | No actor-attribution rules; judge metrics would be uninterpretable     | Critical | 2, 5  |
| 7  | No metric registry, computation engine, provenance trace, or golden metric tests | Critical | 3 |
| 8  | No public API or web interface                                         | High     | 1–3   |
| 9  | No exposure/censoring model for windowed outcomes                      | High     | 3     |
| 10 | No risk adjustment, intervals, or model validation                     | High     | 4     |
| 11 | No security gate, CI, container build, branch protection, or remote    | High     | 1     |
| 12 | No real state-court corpus; no Florida acquisition plan                | High     | 5     |
| 13 | No quantified error rates (linkage, attribution, missingness)          | High     | 6     |
| 14 | No admin tools, corrections workflow, or rapid suppression             | High     | 6     |
| 15 | No legal review of republication, privacy, defamation exposure         | High     | 6     |
| 16 | Single-jurisdiction coverage; no coverage map; no federal dockets      | Medium   | 7     |
| 17 | No production infrastructure, observability, or backups               | Medium   | 8     |

These gaps drive the phase ordering below.

### Changes from the original brief

| Brief said                                          | This roadmap does                                                              | Why                                                                                                      |
|-----------------------------------------------------|--------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------|
| `apps/api`, `apps/web`, `pipelines/*.py`, pnpm workspace | `src/judgemetrics` at the root, `web/` for Next.js, pipelines as CLI subcommands | One Python package and one web app need no workspace; loose scripts outside the package escape typing and tests |
| Thirteen development phases (0–12)                  | Eight build phases, each independently shippable, mapped below, plus a post-launch Phase 9 | The planning-kit template caps a build at eight phases; the brief's sequence is preserved inside them; Phase 9 sits after launch and outside the brief's sequence |
| No funding or sustainability plan                   | Phase 9 — Sustainability and Data Products, after launch                       | The brief names the dataset, not the website, as the strategic asset but never says how operation is funded; a solo maintainer needs a plan that keeps the public surface free while institutions pay for snapshots, service levels, and onboarding |
| Florida jurisdiction as the first real state pipeline | Cook County, IL first (verified bulk access today); Florida research runs in parallel from Phase 5 and the Florida pilot lands in Phase 7 | Florida court data needs credentials or agreements with unbounded lead time; Cook County is official, free, judge-attributed, and person-linkable now, and the brief's own selection rule is "strongest data, not population" |
| `Makefile` with `make <target>`                     | poethepoet tasks (`uv run poe <task>`) plus a `Makefile` shim with the same targets | The maintainer develops on Windows without GNU make; the brief permits equivalent documented scripts   |
| Bash verify scripts (`verify-phaseNN.sh`, kit template) | Python verify scripts (`scripts/verify_phaseNN.py`) with the same modes    | One script runs identically on Windows and Ubuntu CI                                                     |
| Fixed-window outcome rates                          | Fixed-window rates on adequately followed cohorts plus censoring-aware (Kaplan–Meier) estimates | Real corpora end on a date; ignoring right-censoring biases every window rate                   |
| Regularized logistic regression, then "complex ML"  | Regularized logistic baseline, then hierarchical partial pooling; no opaque models at v1 | Partial pooling addresses small-sample instability directly; interpretability is a product requirement |
| Notebooks as deliverables                           | Tested analytics modules over DuckDB/Parquet snapshots; notebooks optional and untracked | Notebooks resist review and CI; published numbers need headless, reproducible code paths        |
| `case` table                                        | Table named `court_case` (entity `Case`)                                       | `case` is a reserved word in SQL; the entity name and every field are unchanged                          |
| Python 3.12 or newer                                | Python 3.13 (pinned in `.python-version`)                                      | Newest release with full wheel coverage for the statistics and entity-resolution stack                   |

### Brief phases mapped to roadmap phases

| Brief phase                          | Roadmap phase and section                                              |
|--------------------------------------|------------------------------------------------------------------------|
| 0 Repository Bootstrap               | 1 (§1.1, §1.5)                                                         |
| 1 Database Foundation                | 1 (§1.2)                                                               |
| 2 Synthetic Justice Dataset          | 2 (§2.1–2.2, §2.5)                                                     |
| 3 First Real Data Connector (FJC)    | 1 (§1.3)                                                               |
| 4 Core API                           | 1 (§1.4), 2 (§2.4), 3 (§3.5)                                           |
| 5 Metrics Engine                     | 3 (descriptive, longitudinal), 4 (expected model, O/E, uncertainty)    |
| 6 Web Application                    | 1 (§1.5), 2 (§2.4), 3 (§3.5)                                           |
| 7 CourtListener Prototype            | 7 (§7.2)                                                               |
| 8 Florida Source Research            | 5 (§5.5)                                                               |
| 9 First Real State Court Pipeline    | 5 (Cook County, §5.1–5.4); Florida pilot in 7 (§7.1)                   |
| 10 Methodological Validation         | 4 (synthetic diagnostics), 6 (§6.1 on real data)                       |
| 11 Production Hardening              | 8                                                                      |
| 12 Geographic Expansion              | 7 (§7.4 jurisdiction-add playbook) and after launch                    |

---

## 3. Target Architecture

```
        ┌────────────────────────────────────────────┐
        │  Public internet (readers, researchers)    │
        └───────────────────────┬────────────────────┘
                                │ HTTPS via CDN — the only public ingress
                                ▼
   ┌────────────────────────────────────────────────────────┐
   │  Web tier — Next.js (SSR): search, judge, court, case, │
   │  jurisdiction, compare, methodology, coverage, corrections │
   └───────────────────────┬────────────────────────────────┘
                           │ HTTPS, versioned JSON (/api/v1), read-only
                           ▼
   ┌────────────────────────────────────────────────────────┐
   │  API tier — FastAPI: public routes · admin routes      │
   │  (authn + authz) · rate limits · JSON logs · /health   │
   └──────┬───────────────────────────┬────────────────┬────┘
          │ SQL, least-privilege role │ read           │ append
          ▼                           ▼                ▼
   ┌──────────────┐   ┌──────────────────────┐   ┌────────────┐
   │ PostgreSQL   │   │ Analytics snapshots  │   │ Audit log  │
   │ canonical ·  │◀──│ Parquet + DuckDB     │   │ (append-   │
   │ metrics ·    │   │ (snapshot id + hash) │   │  only)     │
   │ restricted   │   └──────────▲───────────┘   └────────────┘
   └──────▲───────┘              │ export
          │ publish              │
   ┌──────┴──────────────────────┴──────────────────────────┐
   │  Ingest + analytics workers (CLI, scheduled):          │
   │  connector → raw lake → normalize → resolve → validate │
   │  → publish → compute metrics → record lineage          │
   └──────┬──────────────────────────────────┬──────────────┘
          ▼                                  ▼
   ┌──────────────────┐            ┌─────────────────────────┐
   │ Raw lake (S3-    │            │ Sources: synthetic gen, │
   │ compatible,      │            │ FJC, Cook County SAO,   │
   │ immutable, sha256)│           │ CourtListener, Florida… │
   └──────────────────┘            └─────────────────────────┘
```

Everything runs locally under Docker Compose (PostgreSQL 17 with
`pg_trgm`, an S3-compatible object store, and optional `api` and `web`
containers) through Phase 7. In production the same containers run
behind a CDN with managed PostgreSQL and versioned object storage; the
web tier is the only public surface, the API is reachable only through
it, and the database accepts connections only from the API and the
workers under separate least-privilege roles. The restricted schema
(sensitive attributes, person identifiers, correction contacts) is never
granted to the public API role. The synthetic generator is just another
source behind the same connector interface; its records are labelled
synthetic end to end and are refused by the ingest runner in production.

---

## 4. Phased Roadmap

### Phase 1 — Foundation, Canonical Schema, and the FJC Judge Slice

**Goal:** Ship a governed repository and a runnable end-to-end slice —
the complete canonical schema behind reversible migrations, Federal
Judicial Center judge data flowing from source through an immutable raw
lake into canonical tables, out through a versioned API, and onto a web
judge page — with CI that builds and scans containers, a fail-closed
security gate, branch protection, and the command interface.

**Complexity:** High · **Risk:** Low · **Cloud cost:** none (local) ·
**Handles sensitive data:** Yes — local secrets in env files only;
public judicial biographies, no defendant data

Execution plan: [`docs/phase01-roadmap.md`](docs/phase01-roadmap.md).
Brief phases: 0, 1, 3, and the judge portions of 4 and 6.

#### 1.1 Repository bootstrap, command interface, and security gate
- Create the GitHub remote, push the scaffold as the initial commit,
  configure branch protection (`enforce_admins`, linear history,
  required checks, squash-only, delete-branch-on-merge).
- Choose and add the code license (Apache-2.0 recommended; operator
  confirms), `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`,
  issue and pull-request templates.
- Wire the local security gate with `pre-commit`: ruff, mypy, bandit,
  `detect-secrets`, and `pip-audit`; mirror it in CI with SHA-pinned
  actions and least-privilege permissions; `dependabot.yml`.
- Add `docker-compose.yml` (PostgreSQL 17 with `pg_trgm`, MinIO),
  `.env.example` with placeholders only, and the `up` and `down`
  targets of the command interface.

#### 1.2 Application core and the canonical schema
- `pydantic-settings` configuration, JSON structured logging with a
  scrubbing processor, a FastAPI application factory, `/api/v1/health`
  and `/api/v1/ready` reporting version, git SHA, and migration head.
- SQLAlchemy 2 models for every entity in the brief's canonical model:
  `jurisdiction`, `court`, `judge`, `judge_service`, `person`,
  `person_identifier`, `court_case`, `case_party`, `judge_assignment`,
  `charge`, `court_event`, `decision`, `pretrial_release`, `sentence`,
  `justice_event`, `source`, `source_record`, `ingest_run`,
  `entity_resolution_candidate`, `metric_definition`,
  `metric_observation`, `data_quality_issue`, `correction_request`;
  a reversible Alembic baseline with the performance-strategy indexes
  (court, judge, person, normalized case number, event time, external
  ids; trigram and JSONB GIN indexes).
- Typer CLI `judgemetrics` with `db`, `ingest`, and `serve` groups; an
  API container image, a compose `api` service, and a CI job that
  builds and vulnerability-scans the image; `migrate` and `dev-api`
  targets.

#### 1.3 Ingest framework and the FJC connector
- `SourceConnector` protocol (`discover`, `fetch`, `validate_raw`,
  `parse`, `normalize`), a `RawObjectStore` with filesystem and
  S3-compatible backends that never overwrite an object, sha256
  hashing, the fourteen-step idempotent runner, and `ingest_run`
  bookkeeping.
- FJC connector for `judges.csv` and `federal-judicial-service.csv`
  keyed on the FJC node id, producing judges, service records, and an
  Article III court roster; data-quality checks for service-date
  validity and overlapping service; the `ingest-fjc` target.

#### 1.4 Public API v1
- `GET /api/v1/judges`, `/judges/{id}`, `/judges/{id}/service`,
  `/courts`, `/courts/{id}`, `/jurisdictions`, `/jurisdictions/{id}`,
  and `/search` (trigram search, rate-limited).
- Pagination with strict maximum page sizes, strict filter validation,
  provenance metadata on every entity, an N+1 query guard, the
  generated OpenAPI document checked into `docs/openapi.json`, and
  `docs/API.md`.
- A request-identity middleware that resolves an optional API-key
  header to a rate-limit bucket. Anonymous is the only bucket until
  Phase 9 and no key is ever issued before then; the hook exists so
  keyed tiers (§9.3) add a lookup, not a re-plumbing. The OpenAPI
  document declares the security scheme as optional.

#### 1.5 Web foundation
- Next.js application in `web/` (TypeScript, Tailwind CSS, shadcn/ui,
  TanStack Table), a typed client generated from the OpenAPI document,
  light and dark mode, keyboard-accessible navigation, a web container
  image built in CI.
- Pages: home with global search and coverage summary, `/search`,
  `/judges/[judgeId]` (identity, service timeline, source panel),
  `/courts/[courtId]`, and a `/methodology` stub carrying the product
  principles and the association-is-not-causation statement.
- Vitest unit tests, frontend type check, and a Playwright smoke test
  against the local API; the `dev-web` target.

#### 1.6 QA and verification
- `scripts/verify_phase01.py` with `--fast`, `--py`, `--node`, `--e2e`,
  `--security`, `--all`, and `--post` modes;
  `docs/phase01-qa-findings.md`; `.github/workflows/phase-verify.yml`
  matrix entry `01`; status update in `docs/ROADMAP.md`.

**Acceptance criteria**
- `uv run poe up`, `uv run poe migrate`, and `uv run poe ingest-fjc`
  complete on a clean machine (or the `make` equivalents); the
  baseline creates every canonical table and downgrades cleanly; a
  second `ingest-fjc` run creates zero new canonical rows.
- `GET /api/v1/judges/{id}` returns an FJC judge with service records
  and provenance (source name, retrieved-at, sha256); `/search` returns
  429 after the configured burst in a test.
- `/judges/[judgeId]` renders identity, service timeline, and the
  source panel from the live local API; the Playwright smoke test
  passes.
- `uv run poe check`, `pnpm test`, `pnpm build`, and the frontend type
  check are green locally and in CI; the API and web images build and
  pass the vulnerability scan in CI; `main` is protected and a direct
  push is rejected.
- `scripts/verify_phase01.py --fast` (43 static checks) and
  `--security` (secret scan, SAST, dependency audits) exit 0 on Ubuntu
  CI under the `phase-verify.yml` matrix entry `01`, whose check
  `phase-verify (01)` is a required context on `main` beside `test`;
  `--post` reports the V1–V6 matrix of `docs/phase01-roadmap.md` green
  on the maintainer's machine before the phase is tagged
  `v0.1.0-phase-1`.
- **Deployed & verified:** no deployed surface in this phase; the local
  `/api/v1/health` endpoint reports the package version, git SHA, and
  Alembic head that match the merged commit.
- **Security:** the pre-commit gate is installed and was seen to block a
  commit containing a planted synthetic secret; CI's secret scan, SAST,
  dependency audit, and container scan are required checks;
  `.env.example` contains placeholders only and no `.env` is tracked.

---

### Phase 2 — Synthetic Justice Dataset, Entity Resolution, and Case Timelines

**Goal:** Generate a deterministic synthetic justice dataset with known
truth, load it through the same connector path real data will use,
resolve entities with an auditable framework and review queue, and
expose case timelines — so the whole pipeline is demonstrable and
golden-testable before any real case data exists.

**Complexity:** High · **Risk:** Medium · **Cloud cost:** none (local) ·
**Handles sensitive data:** No real defendant data — synthetic records
labelled as such on every surface

Brief phases: 2, the case portions of 4 and 6, and the testing
strategy's property tests and golden dataset.

#### 2.1 Deterministic synthetic generator
- `judgemetrics synthetic generate --seed <int> --scale golden|demo`
  writes source-format files under `data/synthetic/<seed>/` plus a
  `truth/` directory the canonical database never sees.
- The demo scale meets the brief's minimums (at least 5 courts, 20
  judges, 5,000 cases, 3,000 defendants) and models multiple judge
  assignments, offense categories, pretrial release and detention
  decisions with a deciding judge, dismissals attributed separately to
  judges and prosecutors, convictions, sentences, subsequent cases,
  failures to appear, revocations, and planted edge cases: duplicate
  source records, ambiguous person matches, and missing data.
- `truth/` records the true person identity behind every source
  participant, every true subsequent event, and the expected value of
  every metric the registry will define, so tests compare against
  exact expectations.

#### 2.2 Synthetic connector
- A `synthetic` `SourceConnector` reads the generated files through
  the standard runner with full provenance and idempotency;
  `source.source_type = synthetic`; the runner refuses synthetic
  sources when `JUDGEMETRICS_ENV=production`; the web shows a demo-data
  banner whenever a synthetic source is present.
- `judgemetrics seed` generates and ingests the demo scale; the `seed`
  target.

#### 2.3 Entity-resolution framework v0
- `entity_resolution/` with the brief's stages: deterministic matching
  on source stable identifiers, rule-based matching on the brief's
  person signals (normalized name plus date of birth or age plus case
  linkage, never name alone), a scoring interface with the
  probabilistic stage stubbed for Phase 7, and a manual-review queue.
- `entity_resolution_candidate` rows store features, model version,
  score, decision, timestamp, and reviewer; thresholds are configured
  per entity type (deliberately high auto-match, deliberately low
  auto-reject); `judgemetrics er review list|decide`;
  `docs/ENTITY_RESOLUTION.md`.

#### 2.4 Case API and pages
- `GET /api/v1/cases/{id}`, `/cases/{id}/timeline`,
  `/judges/{id}/cases`, `/coverage` (v0); the case page (timeline,
  charges, judge assignments, attributed decisions with actor badges,
  disposition, sentence, source citations); judge pages gain case
  counts and coverage dates; a coverage page v0.
- An append-only audit log table for administrative and
  entity-resolution decisions.

#### 2.5 Property tests and the golden fixture
- Hypothesis property tests: a subsequent event never precedes its
  index event; rerunning an ingestion produces no duplicates; identical
  deterministic identifiers resolve consistently.
- The golden scale (a small seed with hand-checkable truth) is
  committed under `tests/fixtures/golden/` as the permanent regression
  fixture for entity resolution and, from Phase 3, analytics.

#### 2.6 QA and verification
- `scripts/verify_phase02.py`, `docs/phase02-qa-findings.md`, matrix
  entry `02`.

**Acceptance criteria**
- `uv run poe seed` populates a database meeting the brief's minimums
  from a fixed seed; a rerun creates zero new canonical rows; two runs
  from the same seed produce byte-identical source files.
- Golden entity-resolution expectations hold exactly: planted
  duplicates merge, planted ambiguous pairs land in the review queue,
  distinct persons never merge; every candidate row carries features,
  score, model version, and decision.
- A synthetic case page is reachable from a synthetic judge page and
  renders timeline, charges, attributed decisions, disposition,
  sentence, and source citations.
- Every public surface labels synthetic data; the ingest runner refuses
  a synthetic source in the production environment (test).
- Property tests and `scripts/verify_phase02.py --fast` are green in
  CI.
- **Security:** gate clean; synthetic names come from word lists, never
  from lists of real people; `person_identifier` is unreachable through
  any public route (contract test over the OpenAPI document and the
  database grants).

---

### Phase 3 — Metrics Engine and the Complete Local Demo (First Milestone)

**Goal:** Publish reproducible descriptive and longitudinal metrics from
a versioned registry with exact golden expectations, a provenance trace
from any published number back to raw artifacts, and every remaining
public page — so the brief's seventeen-item first milestone passes end
to end on synthetic data.

**Complexity:** High · **Risk:** Medium · **Cloud cost:** none (local) ·
**Handles sensitive data:** Yes — correction requester contacts
(encrypted at rest); aggregates over synthetic records

Brief phases: 5 (index events through suppression and methodology
versioning, excluding the expected-outcome model), 6, and the first
milestone.

#### 3.1 Metric registry and generated methodology
- Versioned YAML metric definitions (slug, numerator, denominator,
  eligibility, attribution inclusion rules, suppression threshold,
  version) loaded into `metric_definition`; `docs/METHODOLOGY.md` and
  the methodology page are generated from the registry, and the brief's
  statistical warnings are published verbatim as "Known limitations".

#### 3.2 Index events, observation windows, exposure, and censoring
- Index events: pretrial release decisions, dispositions, and
  sentences. Outcomes: new case, new charge, reconviction, failure to
  appear, release violation, revocation, and rearrest where a separate
  arrest source exists. Windows of 30, 90, 180, 365, 730, and 1095
  days. Time at risk starts at release; incarceration defers it.
  Right-censoring at the corpus end date; Kaplan–Meier estimates
  alongside fixed-window rates restricted to adequately followed
  cohorts.

#### 3.3 Computation engine
- Snapshot export from PostgreSQL to Parquet with a snapshot id and
  content hash; DuckDB and Polars computation; precomputed
  `metric_observation` rows with cohort size, observed count, rate,
  Wilson interval, suppressed flag, snapshot id, code version, and
  methodology version; incremental recompute of impacted subjects after
  ingest (pipeline step 13); nothing computed synchronously in web
  requests; `judgemetrics metrics compute|verify` and the
  `compute-metrics` target.
- Metric set: eligible cases and defendants; released and detained
  counts and shares; failure-to-appear and release-violation rates;
  new-case, new-charge, and reconviction rates per window; disposition
  distribution; judicial-dismissal rate (attribution-gated); median
  time to disposition; sentence distributions by offense cohort.

#### 3.4 Provenance trace
- `judgemetrics provenance trace <metric_observation_id>` and
  `GET /api/v1/metrics/{observation_id}/provenance` reconstruct the
  brief's chain: metric observation → eligible canonical events →
  cases, decisions, outcomes → source records → raw artifacts → source
  system, retrieval time, checksum, parser version. A test asserts
  every published observation traces completely; an observation whose
  chain breaks is not published.

#### 3.5 API and web
- `GET /api/v1/metrics`, `/judges/{id}/metrics`, `/courts/{id}/metrics`,
  `/metrics/compare`, `/coverage`, and `POST /api/v1/corrections`
  (requester contact encrypted at rest with a key from settings;
  readable only by the admin role).
- Judge pages gain pretrial, disposition, sentencing, and
  subsequent-outcome panels with the association statement, a
  comparison-cohort selector, and case drill-down; the compare page
  (one objective metric at a time, comparable filters, sortable table
  with sample size, interval, coverage warnings); the methodology page;
  the coverage page; the corrections page and form; the court page's
  comparable-judge table; a jurisdiction page v0.

#### 3.6 Golden metric tests and the first-milestone walkthrough
- Every registry metric matches the generator's `truth/` expectation
  exactly on the golden fixture; `metrics verify` reproduces stored
  observations byte-for-byte from their snapshot.
- A Playwright walkthrough automates the brief's seventeen-item
  checklist; `README.md` documents the one-command startup
  (`uv run poe bootstrap`, or `make bootstrap`).

#### 3.7 QA and verification
- `scripts/verify_phase03.py`, `docs/phase03-qa-findings.md`, matrix
  entry `03`.

**Acceptance criteria**
- The first-milestone walkthrough passes end to end on a clean machine
  from `bootstrap` alone.
- Golden metric expectations hold exactly; `metrics verify` reproduces
  every stored observation.
- Every metric on every page shows numerator, denominator, date range,
  coverage, sample size, and a methodology link (presentation-rule
  test); cohorts below threshold are suppressed in the API and the
  web.
- Every published observation has a complete provenance trace (test).
- A correction request round-trips through the form, is stored with an
  encrypted contact, and is unreadable by the public role.
- `scripts/verify_phase03.py --fast` exits 0 in CI.
- **Security:** gate clean; no per-person rows from any metrics
  endpoint (contract test); the encryption key is read from settings
  and absent from every log line.

---

### Phase 4 — Risk Adjustment and Statistical Validation

**Goal:** Compare observed outcomes with model-expected outcomes for
comparable cohorts on synthetic data with planted effects, publish
observed/expected ratios with intervals and partial pooling, and
document validation before any adjusted statistic appears on a judge
page.

**Complexity:** High · **Risk:** High · **Cloud cost:** none (local) ·
**Handles sensitive data:** Yes — synthetic sensitive attributes
exercise the restricted-schema and fairness-analysis machinery

Brief phases: the expected-outcome model, O/E, and uncertainty portion
of 5; the calibration portion of 10.

#### 4.1 Planted effects and feature specification
- The generator gains planted case-mix confounding and a known
  per-judge effect so recovery can be tested; feature specification
  from the brief's candidate list (offense category and severity,
  charge count, prior qualifying cases and convictions, prior failures
  to appear, pending indicator, age band, jurisdiction, court, calendar
  period); sensitive attributes excluded from features; a written
  leakage review.

#### 4.2 Baseline model
- Regularized logistic regression with a temporal train/test split;
  calibration curves, Brier score, ROC AUC as a secondary diagnostic,
  feature stability, missing-data sensitivity; model artifacts
  versioned with the snapshot id and seed.

#### 4.3 Expected counts, ratios, intervals, and pooling
- Expected counts as the sum of predicted probabilities per subject;
  observed/expected ratios; bootstrap intervals; hierarchical partial
  pooling as the published estimator with shrinkage documented;
  per-metric minimum sample thresholds; recovery of the planted judge
  ranking within tolerance as a golden test.

#### 4.4 Validation report and methodology v1.0
- `docs/VALIDATION.md` with every diagnostic and subgroup calibration
  over synthetic restricted attributes in aggregate only; methodology
  version 1.0 with a changelog entry.

#### 4.5 API and web
- Risk-adjusted panel on judge pages (observed, expected, ratio,
  interval, cohort definition, methodology version) and the comparison
  cohort selector; compare page gains adjusted measures.

#### 4.6 QA and verification
- `scripts/verify_phase04.py`, `docs/phase04-qa-findings.md`, matrix
  entry `04`.

**Acceptance criteria**
- Model training, expected counts, and ratios are reproducible from a
  named snapshot and a pinned seed; the planted judge effect is
  recovered within the documented tolerance.
- Every adjusted statistic on the web links to the methodology version
  and shows its interval; suppressed subjects show the reason.
- `docs/VALIDATION.md` reports calibration, Brier, AUC, stability, and
  sensitivity for the published model version.
- `scripts/verify_phase04.py --fast` exits 0 in CI.
- **Security:** gate clean; model artifacts contain no person-level
  rows (artifact inspection test).

---

### Phase 5 — First Real State-Court Pipeline and the Florida Acquisition Plan

**Goal:** Ingest the first real state criminal-court corpus (Cook
County, IL State's Attorney datasets) end to end with actor attribution,
conservative person resolution, real timelines, coverage statistics, and
the first real metrics, while completing the Florida source inventory
and a lawful acquisition plan.

**Complexity:** High · **Risk:** High · **Cloud cost:** none (local) ·
**Handles sensitive data:** Yes — real defendant-level records
(pseudonymous), restricted demographic attributes

Brief phases: 8 and 9 (with Cook County standing in for the first real
pipeline until Florida access is secured), and the Florida pilot
selection process. Source facts verified on 2026-09-15 are in
`docs/DATA_SOURCES.md`: five bulk datasets, judge attribution on
dispositions and sentences, bond type and amount at initiation without
a deciding judge, a pseudonymous participant id linking a person across
cases, and a corpus frozen at 2024-12-30.

#### 5.1 Source due diligence
- Complete the source-policy record; confirm portal terms permit
  republication of derived aggregates and pseudonymous case-level
  views; read the published value sets for dispositions, reasons, bond
  types, and sentence fields into versioned reference tables; confirm
  participant-id stability across datasets.

#### 5.2 Cook County connector and the restricted schema
- Bulk export per dataset, immutable raw storage, parser versioning,
  normalization into the canonical model; persons from the participant
  id (confidence 1.0 within source, never merged across sources by
  name); age band, race, and gender into a `restricted` schema granted
  only to the ingest and admin roles; public views excluding every
  restricted column and a test that fails if a public route exposes
  one.

#### 5.3 Attribution rules and judge resolution
- Versioned attribution rule table mapping every disposition value and
  reason to an actor type and judicial-discretion classification with
  `unknown` as the explicit fallback and its share published; judge
  name resolution with a curated alias table and the review queue;
  court and facility resolution.

#### 5.4 Real timelines, coverage, and the first real metrics
- Justice events from cross-case linkage on the participant id;
  coverage statistics per the brief (share with identified judge, with
  disposition, with usable person resolution, with adequate follow-up,
  with complete charge classification, with provenance); the first
  real metric follows the brief's preference — new criminal case after
  a clearly identified qualifying pretrial release event — at the court
  level, plus judge-attributed disposition and sentencing metrics;
  outcomes the source cannot support (rearrest, failure to appear,
  release violation) reported as unavailable, never as zero.

#### 5.5 Florida source research and acquisition plan
- `docs/florida-data-inventory.md`: inventory of Florida Courts
  Judicial Data Management Services, the Uniform Case Reporting
  specification, and county clerk systems; the brief's nine-step
  selection process applied to candidate jurisdictions (Broward and
  Miami-Dade among others, none assumed); access method, fields,
  history, limits, terms, cost, and whether public-records requests are
  preferable to any scraping; a selected pilot jurisdiction and a
  written lawful acquisition plan; the operator submits the requests
  (operator wall-clock work that overlaps Phase 6).
- Every request and agreement asks explicitly for redistribution
  rights — derived aggregates, pseudonymous case-level views, and
  commercial redistribution — so the answer is a term of the
  agreement rather than an afterthought, and is recorded in the
  source's **Redistribution** field in `docs/DATA_SOURCES.md`. Phase 9
  excludes any source whose field is not verified as permitting a
  product's tier.

#### 5.6 QA and verification
- `scripts/verify_phase05.py`, `docs/phase05-qa-findings.md`, matrix
  entry `05`.

**Acceptance criteria**
- A full Cook County ingest completes and a rerun creates zero new
  canonical rows.
- Every disposition value present in the data maps to a rule or to
  `unknown`; the unknown share appears on the coverage page.
- No restricted column is reachable through any public route
  (automated test over the OpenAPI document and database grants).
- The first real metric is published with provenance, coverage, and
  the corpus end date on every surface; real-data observations pass
  `metrics verify`.
- `docs/florida-data-inventory.md` names the selected pilot
  jurisdiction and its acquisition plan; requests are logged in
  `docs/ROADMAP.md` with dates.
- `scripts/verify_phase05.py --fast` exits 0 in CI.
- **Security:** gate clean; the restricted schema is granted only to
  the ingest and admin roles; no defendant identifier appears in logs
  (scrubbing test).

---

### Phase 6 — Methodological Validation, Admin Tools, and Trust

**Goal:** Quantify the platform's error rates on real data instead of
assuming correctness, ship the administrative surface behind
authentication, complete the corrections and rapid-suppression process,
and pass an external legal review.

**Complexity:** High · **Risk:** High · **Cloud cost:** none (local);
external legal review cost TBD · **Handles sensitive data:** Yes —
admin credentials, correction requester contacts, suppression lists

Brief phases: 10, the admin tools, the privacy and legal design, and
the security requirements for admin permissions and admin change
logging.

#### 6.1 Methodological validation on real data
- A written audit protocol; manual audit of random case samples;
  estimated person-linkage false-positive and false-negative rates;
  judicial-attribution validation against source documents; missingness
  analysis; observation-period completeness; calibration diagnostics on
  real data; results in `docs/VALIDATION.md` with a methodology
  changelog entry and, where warranted, revised thresholds.

#### 6.2 Administrative surface
- Authenticated admin routes and pages with separate permissions:
  ingestion-run dashboard, failed-record queue, entity-resolution
  review queue, duplicate judge and duplicate person review,
  data-quality alerts, correction-request queue, source coverage
  dashboard, and metric recomputation controls; every administrative
  change written to the append-only audit log.

#### 6.3 Corrections, suppression, and restricted records
- Correction triage and resolution with an immutable audit trail; a
  suppression mechanism that removes an entity or record from every
  public surface within minutes while preserving the internal record;
  sealed, expunged, and juvenile exclusion lists re-applied on every
  refresh; `docs/PRIVACY.md`; a test that a suppressed record never
  reappears after re-ingest.

#### 6.4 Legal review gate
- External counsel review covering defamation, privacy, public-record
  republication, source terms, data licensing, commercial data
  licensing (whether pseudonymous event-level snapshots and a keyed
  API tier may be sold, source by source, per the **Redistribution**
  field in `docs/DATA_SOURCES.md`), and state-specific law; the data
  license decision covering free and paid tiers so Phase 9 needs no
  second engagement; a written go/no-go for publishing aggregate
  fairness analyses; `docs/SECURITY.md` threat-model refresh.

#### 6.5 QA and verification
- `scripts/verify_phase06.py`, `docs/phase06-qa-findings.md`, matrix
  entry `06`.

**Acceptance criteria**
- `docs/VALIDATION.md` reports linkage false-positive and
  false-negative estimates, attribution accuracy, missingness, and
  completeness with sample sizes and the audit protocol.
- Every admin tool is reachable only with admin authentication (authz
  test) and every admin action is audit-logged.
- A suppression propagates to every public surface within the
  documented time in a drill and survives re-ingest (test).
- Legal review is complete with no open blocking findings, and the
  license files reflect its outcome.
- `scripts/verify_phase06.py --fast` exits 0 in CI.
- **Security:** gate clean; requester contacts encrypted at rest and
  absent from logs; admin sessions expire per policy (test).

---

### Phase 7 — Expansion: Florida Pilot, Federal Dockets, and the Coverage Map

**Goal:** Add the Florida pilot jurisdiction and the federal docket
layer through the same connector framework, introduce probabilistic
entity resolution across sources, and ship jurisdiction pages with a
coverage map and a repeatable jurisdiction-add playbook.

**Complexity:** High · **Risk:** Medium · **Cloud cost:** none beyond
metered PACER requests under a hard cap (TBD) · **Handles sensitive
data:** Yes — source credentials, defendant-level records

Brief phases: 7, 9 (Florida), and 12.

#### 7.1 Florida pilot connector
- The connector for the jurisdiction selected in §5.5, gated on the
  access secured there: a limited historical sample, normalization,
  judge resolution, conservative defendant resolution, timelines,
  coverage statistics, and a methodology compatibility review. If
  access is still pending when Phase 7 starts, the next-best verified
  state source enters through the due-diligence gate and Florida lands
  when access arrives.

#### 7.2 CourtListener prototype and PACER interface
- CourtListener quarterly bulk snapshots (courts, dockets, judges) and
  the REST API under a rate-limit budget; judge linkage to FJC node
  ids; a measured coverage report for federal criminal dockets before
  any metric uses them; a PACER authentication and case-locator
  connector behind a feature flag with a spend ledger, a hard cap, a
  dry-run mode, and no uncontrolled paid requests.

#### 7.3 Probabilistic entity resolution
- `splink`-based linkage for judges and courts across sources with
  stored features, model version, score, decision, and reviewer;
  person resolution stays within-source unless lawful stable
  identifiers exist; the Phase 6 review queue handles the ambiguous
  band.

#### 7.4 Jurisdiction pages, coverage map, and the playbook
- `/jurisdictions/[jurisdictionId]` with trends, courts, years, and
  completeness; a MapLibre coverage map with self-hosted static tiles;
  `docs/ADDING_A_JURISDICTION.md`: every new source gets a dedicated
  connector, mapping tests, a coverage report, a provenance record, and
  a methodology compatibility review.

#### 7.5 QA and verification
- `scripts/verify_phase07.py`, `docs/phase07-qa-findings.md`, matrix
  entry `07`.

**Acceptance criteria**
- Two real jurisdictions are ingested, resolved, and comparable on the
  compare page only within their own legal regime by default.
- The PACER connector cannot exceed its cap in a staged test that
  attempts to.
- Every cross-source judge match has stored features, score, and
  disposition; a reviewed sample shows zero false merges.
- The coverage map and jurisdiction pages render from the coverage
  tables; the playbook was followed for the newest source.
- `scripts/verify_phase07.py --fast` exits 0 in CI.
- **Security:** gate clean; source credentials live only in the
  secrets store; the PACER ledger is append-only.

---

### Phase 8 — Production Hardening, Observability, and Launch

**Goal:** Operate JudgeMetrics as a public service: vendor-neutral
managed infrastructure, observability with owned alarms, edge rate
limits and caching, a codebase-wide security and accessibility audit, a
rehearsed release and rollback path, a readiness gate, and a staged
public launch.

**Complexity:** Medium · **Risk:** High · **Cloud cost:** TBD (managed
PostgreSQL, object storage, hosting, CDN, error tracking) · **Handles
sensitive data:** Yes — production secrets and the full dataset

Brief phase: 11.

#### 8.1 Infrastructure
- Containerized API and web, managed PostgreSQL, S3-compatible object
  storage with versioning enabled, HTTPS with a CDN, a secrets manager,
  encrypted automated backups with a tested restore, all described as
  code under `infra/production/`; `docs/DEPLOYMENT.md`.

#### 8.2 Observability
- OpenTelemetry traces and metrics, Sentry-compatible error tracking,
  uptime probes, an ingest heartbeat, and a spend ledger for metered
  sources, each with an owner and a runbook.

#### 8.3 Hardening and audits
- Edge rate limiting, response caching for stable public metrics,
  performance indexes and materialized aggregates for dashboard
  queries, dependency and container scanning as deploy gates, security
  headers, an incident runbook; a codebase-wide security and privacy
  audit iterated until two consecutive passes surface no critical or
  high findings; a WCAG 2.1 AA accessibility audit and automated
  presentation-rule conformance tests.

#### 8.4 Release pipeline
- OIDC-authenticated deploys from protected environments, staging to
  production promotion, migrations on the deploy path, a rehearsed
  rollback.

#### 8.5 Readiness gate and launch
- Checklist: legal sign-off from Phase 6, methodology and coverage
  pages published, corrections channel live, robots and indexing
  policy, attribution and licensing, monitoring alarms seen to fire; a
  staged launch limited to the covered jurisdictions and a 72-hour
  watch.

#### 8.6 QA and verification
- `scripts/verify_phase08.py`, `docs/phase08-qa-findings.md`, matrix
  entry `08`.

**Acceptance criteria**
- Production `/api/v1/health` reports the released version and
  migration head; a backup restore drill completes within the
  documented time.
- Every alarm in the observability table has fired at least once in a
  drill and has an owner and a runbook.
- The security audit reports zero open critical or high findings across
  two consecutive passes; the accessibility audit passes on every
  public page.
- Rollback of a deploy is executed in a drill within the documented
  time.
- **Deployed & verified:** the released commit serves the judge, case,
  compare, methodology, and coverage pages in production, exercised by
  the Playwright suite against the public domain.
- **Security:** gate clean; secrets exist only in the secrets manager;
  the pre-launch security scan of the production surface is clean.

---

### Phase 9 — Sustainability and Data Products

**Goal:** Fund continued operation without compromising the public
surface: a legal home for the project, a data license that inherits
each source's redistribution terms, versioned research snapshots, a
keyed API tier, a priced jurisdiction-onboarding service, and grant,
sponsorship, and donation channels — with the free website and every
judge-level aggregate unchanged and never paywalled.

**Complexity:** Medium · **Risk:** Medium · **Cloud cost:** payment
processor fees and snapshot storage egress (TBD) · **Handles sensitive
data:** Yes — customer contacts and billing identifiers; never card
data

Brief phases: none. Implements the brief's future features
"Downloadable research datasets subject to source restrictions" and
"Public read-only API" and its strategic-moat statement (the dataset
and its provenance graph, not the website, are the asset). Starts only
after the Phase 8 launch watch closes and the Phase 6 legal opinion on
commercial licensing is in hand.

**Standing rule.** Nothing free before Phase 9 becomes paid in
Phase 9. Paid products are additive — bulk event-level snapshots,
service levels, and engineering time — and change limits, never
content. No advertising on any surface; no funder influence over
methodology, attribution rules, or suppression.

#### 9.1 Legal entity and licensing
- Operator decision recorded in `docs/GOVERNANCE.md`: fiscal
  sponsorship (lowest overhead for a solo maintainer), a 501(c)(3), or
  a public-benefit company; most grant funders require one of the
  first two.
- Code stays Apache-2.0. Published aggregates, the methodology, and
  the coverage data are released under CC BY 4.0. Event-level
  snapshots carry a data-product license that inherits each source's
  redistribution terms: a source whose **Redistribution** field is not
  verified as permitting a tier is excluded from that tier by
  configuration, with a test.
- Counsel's Phase 6.4 opinion on commercial licensing is a
  precondition; if it was deferred, this step reopens it before any
  paid product ships.

#### 9.2 Versioned research snapshots
- The DuckDB/Parquet analytics snapshots from Phase 3 become
  downloadable artifacts: `judgemetrics snapshot publish` writes a
  versioned, sha256-signed bundle (Parquet tables, data dictionary,
  provenance manifest with source ids, ingest runs, code and
  methodology versions, and the suppression applied) to versioned
  object storage; `docs/DATASETS.md`.
- Tiers: free for academic and non-commercial use on registration;
  paid for commercial use. The restricted schema never enters any
  bundle (test); small cohorts are suppressed exactly as on the web
  (shared code path, test).

#### 9.3 Keyed API tier
- API keys over the §1.4 hook, without user accounts: a key is an
  opaque credential mapped to an organisation record; only its hash is
  stored. Anonymous access keeps the free limit; keyed tiers raise
  limits and add a service level; a usage ledger per key; a revocation
  path; `docs/API.md` gains a tiers section. A keyed and an anonymous
  response for the same request are identical (test).

#### 9.4 Jurisdiction onboarding service
- `docs/ADDING_A_JURISDICTION.md` (§7.4) priced as a fixed-fee
  engagement: due-diligence record, connector, mapping tests, coverage
  report, methodology compatibility review, jurisdiction page. The
  engagement terms state that the funder has no influence over
  methodology, attribution rules, suppression, or publication timing,
  and the jurisdiction page discloses the funding.

#### 9.5 Grants, sponsorship, and donations
- A funder register in `docs/FUNDING.md` (criminal-justice data,
  court-transparency, and open-data funders); a public sponsors page
  listing every funder above a disclosed threshold; recurring
  donations through the fiscal sponsor; a conflict-of-interest policy
  in `docs/GOVERNANCE.md`: no funding from a party to cases in a
  covered jurisdiction, no funder-directed analyses.

#### 9.6 Billing and ledgers
- Hosted checkout (Stripe or equivalent) for keys and snapshots; the
  application stores a customer id and subscription state, never card
  data; a revenue ledger beside the Phase 8 spend ledger; invoices and
  receipts come from the processor; webhook signature verification and
  idempotent handling tested.

#### 9.7 QA and verification
- `scripts/verify_phase09.py`, `docs/phase09-qa-findings.md`, matrix
  entry `09`.

**Acceptance criteria**
- Every public page and every anonymous API response is byte-identical
  before and after Phase 9 for the same snapshot (golden comparison).
- A published snapshot bundle verifies its signature, excludes every
  source whose **Redistribution** field is not verified for the
  bundle's tier, contains no restricted-schema column, and traces
  through `judgemetrics provenance trace` to raw artifacts.
- A keyed and an anonymous request for the same resource return the
  same body (test); a revoked key stops working within the documented
  time (test).
- The sponsors page lists every funder above the threshold; the
  conflict-of-interest policy and the license files are published and
  match counsel's opinion.
- `scripts/verify_phase09.py --fast` exits 0 in CI.
- **Security:** gate clean; key hashes and customer contacts encrypted
  at rest and absent from logs; webhook signatures verified; no card
  data reaches the application.

---

## 5. Cross-Cutting Concerns

### Command interface

The brief's `make <target>` interface is provided by poethepoet tasks
in `pyproject.toml` (`uv run poe <task>`, cross-platform, no extra
binary) and mirrored by a `Makefile` shim for environments with GNU
make. Targets appear when the thing they run exists.

| Target            | Runs                                                      | Available from |
|-------------------|-----------------------------------------------------------|----------------|
| `install`         | `uv sync` (`make install` only; poe runs inside the env)  | now            |
| `check`           | lint, format check, type check, tests                     | now            |
| `test`, `lint`, `fmt`, `typecheck` | the individual tools                      | now            |
| `kit`             | re-export the roadmodel planning kit                      | now            |
| `up`, `down`      | Docker Compose services                                   | Phase 1        |
| `migrate`         | `judgemetrics db upgrade`                                 | Phase 1        |
| `dev-api`, `dev-web` | API with reload; web dev server                        | Phase 1        |
| `ingest-fjc`      | `judgemetrics ingest run fjc`                             | Phase 1        |
| `seed`            | generate and ingest the synthetic demo dataset            | Phase 2        |
| `compute-metrics` | `judgemetrics metrics compute`                            | Phase 3        |
| `bootstrap`       | install, up, migrate, seed — the one-command startup      | Phase 3        |

### Provenance chain (standing rule)

Every published metric must trace: metric observation → eligible
canonical events → canonical cases, decisions, and outcomes → source
records → raw artifacts → source system, retrieval time, checksum, and
parser version. `judgemetrics provenance trace` (Phase 3) reconstructs
the chain and a test enforces it for every published observation. If
the chain cannot be reconstructed, the metric is not published.

### Performance rules

Indexes on court, judge, person, normalized case number, event time,
and source external ids from the baseline; composite indexes follow the
metric filters that exist; materialized aggregates only for measured
expensive dashboard queries; partitioning only when scale requires it;
Polars and DuckDB for batch transformations; longitudinal metrics are
never computed synchronously in web requests; observations are
precomputed and versioned, and only impacted subjects are recomputed
after ingest; stable public metric responses are cached; case lists
paginate with strict maximum page sizes; an automated query-count guard
catches N+1 access patterns.

### Definition of done

The brief's definition of done for any feature is reproduced in
`AGENTS.md` and applies to every step: implemented, typed, migrated if
required, unit-tested, integration-tested when relevant, documented,
lint and type check and tests green, frontend build green when the
frontend changed, no credentials committed, data lineage preserved when
data changed.

### Cost projection (monthly, USD)

| Service                                         | Phases 1–7      | Phase 8 (production) |
|-------------------------------------------------|-----------------|----------------------|
| Compute, database, object storage (local Docker) | none            | TBD                  |
| CDN, domain, TLS                                 | none            | TBD                  |
| Error tracking, uptime monitoring                | none            | TBD                  |
| Data sources (FJC, Cook County, CourtListener)   | none            | none                 |
| Florida data acquisition (requests, fees)        | TBD             | TBD                  |
| PACER (metered, capped, feature-flagged)         | capped, TBD     | capped, TBD          |
| External legal review (one-time, Phase 6)        | TBD             | —                    |
| AI assistance (existing flat subscriptions)      | no marginal     | no marginal          |
| **Total**                                        | **TBD**         | **TBD**              |

Phase 9 adds payment-processor fees and snapshot egress on the cost
side and is the first phase with an inflow; its revenue ledger (§9.6)
reports both.

### Sequencing & dependencies

```
Phase 1 ──▶ Phase 2 ──▶ Phase 3 ──▶ Phase 4 ──▶ Phase 5 ──▶ Phase 6 ──▶ Phase 7 ──▶ Phase 8 ──▶ Phase 9
                                                   │
                                                   └─ §5.5 Florida requests (operator wall-clock,
                                                      overlaps Phases 6–7)
```

- Phases 1–4 are strictly sequential and run entirely on synthetic and
  FJC data: each consumes the prior phase's schema, data, and pages.
  Phase 3's exit is the brief's first milestone.
- Phase 5 is the first real-data phase and depends on the metrics and
  risk-adjustment machinery being golden-tested first.
- The Florida acquisition requests start in Phase 5 and run as operator
  wall-clock work; Phase 7's Florida connector is gated on their
  outcome and has a documented fallback.
- Phases 6 and 7 are sequential: the admin review tools of Phase 6 are
  what Phase 7's cross-source resolution relies on.
- Phases 1–7 run locally with no cloud spend.
- Phase 8 is the cutover phase; its readiness gate (§8.5) is a separate
  sub-step from the launch itself.
- Phase 9 is post-launch and depends on three earlier decisions: the
  §1.4 request-identity hook, the **Redistribution** field verified per
  source (§5.5 for Florida agreements), and the §6.4 legal opinion on
  commercial licensing.

### Branch management strategy

#### Branching model

`main` is the single source of truth. All work happens on short-lived
branches (≤ 1 week) that merge into `main` via pull request. `main`
must always be:

- Green on CI.
- Runnable locally with `uv run poe up` plus the documented commands;
  deployable from Phase 8 onward.
- Tagged with semver on every release.

#### Branch naming convention

| Prefix     | Purpose                           | Example                              |
|------------|-----------------------------------|--------------------------------------|
| `feature/` | Phase work or new feature         | `feature/phase01-step3-fjc-ingest`   |
| `fix/`     | Non-urgent bug fix                | `fix/service-date-overlap`           |
| `hotfix/`  | Urgent fix from `main`            | `hotfix/suppression-leak`            |
| `chore/`   | Tooling, deps, housekeeping       | `chore/bump-ruff`                    |
| `docs/`    | Documentation-only changes        | `docs/methodology-v1`                |
| `perf/`    | Performance work                  | `perf/metric-snapshot-export`        |
| `release/` | Pre-release stabilisation         | `release/v1.0.0`                     |

#### Pull request rules
1. **Scope discipline.** One PR per phase step.
2. **PR template.** Roadmap reference, summary, test plan, screenshots
   for UI, breaking-change notes, rollback plan.
3. **CI green required.** Lint, type-check, tests, the container
   build, and the security scans (secret scan, SAST, dependency audit,
   image scan) all pass before merge. CI re-runs the same gate the
   pre-commit hook ran locally.
4. **No force-push to `main`.** Allowed on personal branches only
   before review opens.
5. **Squash-merge** to `main` so each step reads as one clean commit.
6. **Conventional Commits** on the squash message.
7. **No direct pushes to `main` — for anyone, including the owner.**
   Branch protection is configured with `enforce_admins: true`, so AI
   agents running with the maintainer's credentials cannot bypass the
   PR workflow.

#### Step lifecycle

Every step of every phase follows the same six-stage lifecycle, in
order, with no exceptions. Each stage is a hard checkpoint. AI coding
agents executing a step MUST complete all six stages before declaring
the step done.

1. **Create the branch.** Before any Read / Edit / Bash, run
   `git checkout -b <prefix>/<slug>` from a clean, up-to-date `main`.
   The branch name comes from the step's `**Branch:**` line. When the
   step runs in its own working tree (see "Worktree strategy"), the
   equivalent is `git fetch origin && git worktree add -b <branch>
   .worktrees/<slug> origin/main`, followed by that worktree's
   bootstrap (`uv sync`, `pnpm install` in `web/`, `.env` copied).

2. **Work on the branch, and pass the security gate before every
   commit.** Never push to `main` directly. Before each `git commit`,
   the local security gate (secret scan, SAST, dependency audit,
   sensitive-data diff review) runs from the pre-commit hook and is
   fail-closed.

3. **Open the PR.** `gh pr create --base main --head <branch>` with a
   Conventional Commits title and a body referencing the roadmap step
   and its acceptance criteria. One PR per step.

4. **Wait for green checks, then squash-merge.** If the PR falls behind
   `main`, refresh with `gh pr update-branch --rebase` — never merge
   `main` into the branch (linear history is required). Once green:

   ```sh
   gh pr merge <PR_NUMBER> --squash --delete-branch
   ```

   For a step whose `**Deploys:**` line names a surface, complete the
   post-deploy verification named in its acceptance criteria before
   Stage 6.

5. **Retire the branch (remote + local).**

   ```sh
   git switch main
   git pull --ff-only origin main
   git fetch --prune origin
   git branch -vv | grep ': gone]' | awk '{print $1}' \
     | xargs -r git branch -D
   ```

   If the step ran in its own worktree, remove it first
   (`git worktree remove .worktrees/<slug>`, then
   `git worktree prune`).

6. **New conversation, next step.** Update `docs/ROADMAP.md` (status,
   open questions), close the agent session, and open a fresh one
   before starting the next step. No work straddles two steps.

#### Worktree strategy

The default is one working tree — the primary checkout — and one step
in flight at a time. A second working tree is created only with
`git worktree add` (never a second clone) and only in these cases:

| Case                         | Rule                                                                                                 |
|------------------------------|------------------------------------------------------------------------------------------------------|
| Hotfix interrupting a step   | A Critical/High finding gets its `hotfix/` branch in a worktree cut from `origin/main`; the in-flight step's tree is untouched. |
| Declared-independent steps   | Only steps a phase roadmap's Execution Order draws in parallel. Each gets its own worktree and its own conversation. |
| Subagent isolation in a step | Multi-agent runs inside one step work in throwaway worktrees; results merge into the step branch locally; every subagent worktree is removed before the PR opens. |

Rules for every worktree:

1. **Location.** `.worktrees/<branch-slug>/` inside the repository,
   git-ignored. Never nest a worktree under a tracked path.
2. **Bootstrap before use.** A new worktree has none of the primary
   tree's untracked state. Run `uv sync` (which creates a
   worktree-local `.venv`), `pnpm install` in `web/`, and copy `.env`
   before any test or build. Never point a worktree at the primary
   tree's environment.
3. **Hooks and config carry over.** The pre-commit gate is installed
   per repository; confirm once per worktree with
   `uv run pre-commit run --all-files`.
4. **One conversation, one worktree.**
5. **Merge from the primary tree.**
6. **Retire with the branch.** No worktree outlives its PR.

#### Release & tagging

| Milestone tag       | Marker                                                   |
|---------------------|----------------------------------------------------------|
| `v0.1.0-phase-1`    | Canonical schema and judge slice runnable end to end     |
| `v0.2.0-phase-2`    | Synthetic dataset, entity resolution, case timelines     |
| `v0.3.0-phase-3`    | Metrics engine; first milestone passes                   |
| `v0.4.0-phase-4`    | Risk-adjusted ratios with validation report              |
| `v0.5.0-phase-5`    | First real state-court pipeline; Florida acquisition plan |
| `v0.6.0-phase-6`    | Quantified error rates, admin tools, corrections, legal review |
| `v0.7.0-phase-7`    | Florida pilot, federal dockets, coverage map             |
| `v1.0.0`            | Public launch                                            |

### Release & deployment strategy

**Merged is not deployed, and deployed is not released.** Through
Phase 7 the only environment is the maintainer's machine, and "deployed"
means the merged commit runs under `uv run poe up` with migrations
applied. From Phase 8, three distinct events with three distinct
triggers apply to every surface below.

#### Deployable surfaces

| Surface            | Environments                | Deploy trigger                                  | "Released" means                                  | Verify with                                                  |
|--------------------|-----------------------------|-------------------------------------------------|---------------------------------------------------|--------------------------------------------------------------|
| Web app (`web/`)   | local; staging, production  | local: `dev-web`; prod: promotion after CI      | production build serves the tagged commit         | page footer and `/api/v1/health` report the same SHA         |
| API service        | local; staging, production  | local: `dev-api`; prod: promotion               | `/api/v1/health` reports the new version          | authenticated admin probe plus public smoke suite            |
| Database           | local; staging, production  | `migrate` on the deploy path                    | Alembic head matches the code's head              | `judgemetrics db current`                                    |
| Ingest jobs        | local; production           | scheduled run definition merged to `main`       | next scheduled run succeeds                       | `ingest_run` row plus heartbeat alarm green                  |
| Analytics snapshot | local; production           | `compute-metrics` after ingest                  | `metric_observation` rows carry the new snapshot  | `judgemetrics metrics verify`                                |
| Container images   | CI; production registry     | CI build on every PR; tagged release            | image tag matches the release                     | image scan clean; `/api/v1/health` reports the tag          |

#### Promotion path and cutovers

- Changes move local → staging → production from Phase 8; promotion is
  gated on CI green plus the phase's verification checks passing
  against staging.
- **Staged rollout.** Schema → workers → API → web, each verified
  before the next.
- **Readiness gate before an irreversible cutover.** The DNS cut and
  public launch (§8.5), any data migration with no down path, and any
  key rotation each get an explicit readiness sub-step with a
  checklist, separate from the cutover itself.

#### Configuration and secrets provisioning

- A step that introduces a required environment variable or secret
  verifies at kickoff that the value exists in every target
  environment.
- A shared secret is proven by an authenticated round-trip, never by
  listing environment names.
- Sensitive values never transit chat or a PR; the operator receives a
  command to run, never a value to paste.

#### Data and schema migrations

- Migrations run on the deploy path in expand → deploy code → contract
  order; each migration has a tested downgrade or a documented restore.
- A merged migration not yet applied to production is a tracked gap.

#### Post-deploy verification

A step that touches a deployed surface is not done at merge: its
acceptance criteria name the environment check, and Stage 4 of the step
lifecycle runs it — the health endpoint reports the expected build, and
the changed behaviour is exercised end to end with the hands-off recipe
the step names.

#### Rollback

| Surface        | Rollback                                              | Time to execute |
|----------------|-------------------------------------------------------|-----------------|
| Web app        | promote the previous build                            | minutes         |
| API service    | redeploy the previous image tag                       | minutes         |
| Database       | Alembic downgrade or restore from the last snapshot   | TBD (drilled)   |
| Ingest jobs    | disable the schedule; re-run the prior connector version | minutes      |
| Public launch  | restore the pre-launch indexing policy and gate       | minutes         |

#### Versioning

Releases are tagged per the table above; the Python package version and
the web build version are bumped in the release PR, and
`/api/v1/health` reports both.

### Security & privacy strategy

#### Data classification

| Data class                              | Present? | Handling requirement                                                                         |
|-----------------------------------------|----------|----------------------------------------------------------------------------------------------|
| Synthetic justice records               | Yes (Phases 2–4 onward) | Labelled synthetic on every surface; refused by the runner in production; names from word lists only. |
| Defendant-level court records           | Yes (Phase 5 onward) | Pseudonymous public keys only in public surfaces; source identifiers hashed; never in logs. |
| Restricted demographic attributes       | Yes (Phase 5 onward) | `restricted` schema; ingest and admin roles only; aggregate fairness analysis only; never a model feature by default. |
| Judge biographical data (public officials) | Yes   | Public, with source citation; corrections path applies.                                      |
| Correction requester contacts           | Yes (Phase 3 onward) | Encrypted at rest; admin role only; retention limit.                                 |
| Authentication secrets / admin credentials | Yes   | Secrets manager (production) or untracked `.env` (local); never in source or client bundles. |
| Source API keys / tokens (CourtListener, PACER, Florida) | Yes | Server-side only; scoped minimally; spend ledger for metered sources.                  |
| Sealed, expunged, juvenile records      | Must not be | Exclusion lists re-applied on every refresh; suppression drill; takedown runbook.          |
| Payment / financial data                | No       | —                                                                                            |

#### The brief's security requirements

| Requirement                                          | Where it is met                                                       |
|------------------------------------------------------|-----------------------------------------------------------------------|
| No secrets committed to Git                          | Per-step gate (`detect-secrets`, `gitleaks` in CI); Phase 1           |
| `.env.example` contains placeholders only            | Phase 1 test `test_env_example_has_only_placeholders`                 |
| Parameterized database access                        | SQLAlchemy constructs only; `bandit` SAST; Phase 1 onward             |
| Validate all user input                              | Pydantic models and strict query validation; Phase 1 onward           |
| Rate-limit expensive search endpoints                | In-process limiter on `/search` (Phase 1); edge limits (Phase 8)      |
| Separate public and administrative permissions       | Database roles (Phase 1); admin authn and authz (Phase 6)             |
| Encrypt sensitive administrative/contact information | Correction contacts encrypted at rest (Phase 3)                       |
| HTTPS in production                                  | Phase 8                                                                |
| Log administrative changes                           | Append-only audit log (Phase 2); admin actions (Phase 6)              |
| Automated database backups                           | Phase 8, with a restore drill                                          |
| Object-store versioning for raw data                 | Content-addressed immutable objects (Phase 1); bucket versioning (Phase 8) |
| Dependency and container vulnerability scanning in CI | `pip-audit`, `pnpm audit`, image scan as required checks (Phase 1)   |

#### Threat model

The assets are the canonical dataset (whose public value depends on its
integrity), the restricted schema, the raw lake, source credentials, and
the platform's credibility. Trust boundaries are the CDN edge, the web
tier to API tier hop, the API role versus the ingest and admin roles in
PostgreSQL, and the CI pipeline. Realistic adversaries: an external
attacker probing for restricted records or seeking to alter published
statistics; a malicious or careless contributor; a compromised
dependency or CI action; a leaked coding-agent transcript containing
credentials; and a legitimate but adversarial data subject. The top
abuse cases the design resists: exfiltration of restricted attributes
through the public API, re-identification of a pseudonymous person via
joins on public fields, tampering with metric observations, poisoning
the raw lake with forged source files, and denial of service through
expensive search or compare queries.

#### Per-step security gate

Every step of every phase runs the same local, fail-closed security
gate before any commit, wired into the repository's `pre-commit`
configuration and re-run in CI as required status checks:

| Check                 | What it catches                                                      | Tooling                                                     |
|-----------------------|----------------------------------------------------------------------|-------------------------------------------------------------|
| Secret / PII scan     | Committed credentials, tokens, real person identifiers               | `detect-secrets` locally; `gitleaks` action in CI           |
| SAST                  | Injection, unsafe deserialization, weak crypto, path traversal       | `bandit` (Python); `eslint-plugin-security` (TypeScript)    |
| Dependency audit      | Known-vulnerable, yanked, or typo-squatted dependencies              | `pip-audit`; `pnpm audit --audit-level=high`                |
| Container scan        | Vulnerable base images and system packages                           | image scanner in the CI container job                       |
| Sensitive-data review | Restricted columns in public paths, PII in logs, over-broad grants   | Diff review against the data-classification table          |

Rules for the gate:

1. **Fail-closed.** Any finding blocks the commit; a bypass is for
   genuine emergencies only and is recorded in the PR body.
2. **Runs per commit, not per phase.**
3. **Mirrored in CI.**
4. **Owned by acceptance criteria.** Every phase's acceptance criteria
   name the concrete security check for its surface.
5. **The pipeline is a trust boundary.** Third-party actions are pinned
   to a commit SHA; each workflow declares minimum `permissions:`;
   secrets are never exposed to workflows triggered by untrusted pull
   requests; deploy jobs run behind protected environments with OIDC.

#### Security controls by layer

| Layer               | Control                                                                                     |
|---------------------|---------------------------------------------------------------------------------------------|
| Identity / auth     | Admin surfaces behind authenticated sessions with short lifetimes; least-privilege roles.    |
| Transport           | TLS everywhere from Phase 8; HSTS; certificates managed by the platform.                     |
| Data at rest        | Encrypted managed database and object storage; encrypted backups; restricted schema grants.  |
| Secrets             | Secrets manager in production; untracked `.env` locally; rotation runbook.                   |
| Network / edge      | CDN in front of the only public ingress; rate limits on search, compare, corrections.        |
| Dependencies        | Pinned by `uv.lock` and `pnpm-lock.yaml`; audited per commit; scheduled update PRs.          |
| Containers          | Minimal base images; scanned on every PR; rebuilt on base-image advisories.                  |
| CI/CD pipeline      | SHA-pinned actions; least-privilege permissions; OIDC deploys; protected environments.       |
| Logging / audit     | No person identifiers or secrets in logs (scrubbing test); append-only audit tables.         |
| Incident response   | Runbooks for credential leak, restricted-data exposure, suppression request, source outage.  |

#### Vulnerability handling

Security findings follow the same discover → triage → track → fix →
verify loop as any defect but jump the queue by severity: Critical and
High are fixed on a `hotfix/` or `fix/` branch before new feature work
continues; Medium and Low are tracked as issues with an owner and a due
date. A finding is never silenced without a recorded justification.

### Defect handling & triage

Executing a step surfaces findings that are not the step. Every finding
is classified before it is acted on, and each class has exactly one
destination.

| Class                  | Definition                                                              | Destination                                                                                 |
|------------------------|-------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| Spec rot               | The step's own prompt was wrong                                         | Edit the step's `<task>` block in the phase roadmap now.                                     |
| Upstream gap           | An earlier step missed something that belonged to it                    | Patch the earlier step's prompt; add it to the phase's carry-over checklist.                 |
| Implementation bug     | The code is wrong                                                       | Fix in-step only if it blocks this step's acceptance criteria; otherwise an issue and its own branch. |
| Architectural question | A broader product or design decision was exposed                        | An issue for a future phase; never folded into the immediate fix.                            |
| Process improvement    | A lesson about how the work is done                                     | Record it in this roadmap or `AGENTS.md`; if it is a rule, make it a check.                  |
| Security finding       | Any gate check or threat-model abuse case                               | Jumps the queue by severity — see "Vulnerability handling".                                  |
| Data-semantics finding | A source value, attribution rule, or metric definition was misread      | Edit the versioned rule or registry entry, bump its version, and re-run `metrics verify`.    |
| Data-access question   | A source needs credentials, fees, agreements, or a public-records request | Record it in `docs/ROADMAP.md` "Unresolved data-access questions"; never invent an answer. |

Rules: scope discipline (a step's PR contains the step plus blocking
fixes only); track before you defer; verify the close in the target
environment; prevent the class, not the instance — every escaped defect
gets a guard (a test, a lint rule, a CI check, a verify-script check)
recorded next to the finding in the phase's QA findings document.

### Operations & observability strategy

Every runtime surface is observable before it is considered live, and
every signal has an owner and a response.

#### Health signals

| Surface            | Signal                                           | Checked by                                  | Alerts     |
|--------------------|--------------------------------------------------|---------------------------------------------|------------|
| API service        | `/api/v1/health` version, status, migration head | uptime probe + post-deploy check            | maintainer |
| Web app            | error rate, latency, build status                | platform dashboard + alert rule             | maintainer |
| Ingest jobs        | last successful `ingest_run` within cadence      | heartbeat workflow that fails loudly        | maintainer |
| Analytics snapshot | `metrics verify` green on the latest snapshot    | scheduled verify run                        | maintainer |
| Metered sources    | PACER spend ledger vs cap                        | daily ledger check + hard cap               | maintainer |
| Suppression list   | every suppressed id absent from public surfaces  | scheduled conformance query                 | maintainer |

#### Rules

1. **Version + health on every deployed surface.**
2. **Scheduled automation has a heartbeat.** An ingest that has not
   succeeded within its cadence raises an alarm.
3. **Metered dependencies have a ledger and a cap.** PACER is the only
   metered source; the cap is enforced in code before every request.
4. **Logs are safe by construction.** Structured fields, no person
   identifiers, no secrets.
5. **Every alert has a runbook.**

#### Runbooks

| Scenario                      | Runbook                                                         |
|-------------------------------|-----------------------------------------------------------------|
| Deploy regressed              | Rollback per "Release & deployment strategy".                    |
| Ingest silent                 | Check the run log; re-run manually; fix the schedule trigger.    |
| Secret leaked / rotated       | Rotate in the secrets manager; authenticated round-trip to confirm; audit access. |
| Source changed or withdrawn   | Freeze at the last good snapshot; mark coverage; open a source issue. |
| Suppression request           | Apply the suppression; verify absence on every surface; record the audit entry; notify. |
| Restricted-data exposure      | Disable the affected route; rotate credentials; assess scope; document; notify per legal advice. |

**Acceptance.** A phase that adds a runtime surface is not done until
the surface's health signal and alarm exist and have been seen to fire
once, or a synthetic failure was injected to prove they do.

### Risks & mitigations

| Risk                                                             | Mitigation                                                                                          |
|------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| Misattributing prosecutorial or statutory outcomes to judges     | Attribution rules are versioned data with tests; judge metrics include only attributed events; unknown share published. |
| Readers treat associations as causation, or raw rates as judge quality | Association statement on every judge surface; raw rates shown with case-mix context; O/E framed as model comparison; no composite score; the brief's statistical warnings published as known limitations. |
| Selection effects and non-random assignment                      | Comparisons default to same court and period; risk adjustment documents what it can and cannot remove. |
| False-positive person merges                                     | Within-source identifiers first; rule-based stage never on name alone; probabilistic linkage gated by high thresholds and review; features stored; error rates measured in Phase 6. |
| Small-sample instability                                         | Suppression thresholds; intervals on every rate; partial pooling for adjusted estimates.            |
| Missing events outside the covered jurisdiction                  | Coverage page states what is observable; longitudinal metrics carry a downward-bias note.           |
| Synthetic data mistaken for real                                 | Labelled on every surface; refused in production; separate source type.                             |
| The first real corpus is frozen at 2024-12-30                    | Documented coverage end date; censoring-aware rates; expansion phase adds maintained sources.       |
| Pretrial decisions lack judge attribution in the first real corpus | Court-level pretrial metrics only; Phase 7 adds a source with attribution after verification.     |
| Florida access never materializes on schedule                    | Cook County proves the state pipeline first; documented fallback source for Phase 7.                |
| Legal exposure (defamation, republication, privacy)              | Pseudonymity, suppression, corrections, and an external legal review before launch.                 |
| PACER spend                                                      | Feature flag, dry-run mode, ledger, hard cap tested to hold.                                        |
| Solo-maintainer bandwidth                                        | Independently shippable phases; one step per session; verify scripts make progress auditable.       |
| A source's terms forbid commercial redistribution                | **Redistribution** is a verified field per source; paid tiers exclude unverified sources by configuration (test); free tiers are unaffected. |
| Funding is seen to buy influence or access                       | Public surface byte-identical across tiers (test); sponsors page; conflict-of-interest policy; funders never direct analyses. |

---

## 6. Out of Scope

Deliberately deferred to a future version:

- Any composite, ideological, partisan, or "best/worst judge" score.
- Nationwide coverage at v1; the launch covers the ingested
  jurisdictions only.
- Public display of defendant identities; person timelines stay
  pseudonymous and admin-only.
- Scraping court websites against their terms; sources enter only
  through the due-diligence gate.
- Civil, family, juvenile, and appellate case analytics.
- Real-time or near-real-time ingestion; batch cadence only.
- Opaque machine-learning models for expected outcomes at v1.
- User accounts, comments, or community features beyond the admin
  surface and the corrections form.
- Native mobile applications; the web app is responsive, desktop-first.

Excluded permanently, not deferred: advertising on any surface, paid
access to the website or to any judge-level aggregate, and selling
judge-selection or judge-shopping products. Phase 9 funds the project
by licensing the dataset and services to institutions, never by
charging the public for the accountability surface.

The brief's future-feature list is the post-launch backlog: downloadable
research datasets subject to source restrictions and a public read-only
API (both land in Phase 9), historical judge trend analysis, a
prosecutorial-outcome module kept analytically distinct from judicial
metrics, sentencing and pretrial explorers, failure-to-appear
analytics, appellate reversal analytics with careful attribution,
researcher methodology notebooks, automated source-change detection,
and source completeness scoring. The national coverage map and
court-level comparison arrive with Phase 7.

---

## 7. Glossary

| Term      | Meaning                                                                 |
|-----------|-------------------------------------------------------------------------|
| CI        | Continuous integration (GitHub Actions) — never a confidence interval in this document; intervals are called "intervals" |
| ER        | Entity resolution                                                        |
| FJC       | Federal Judicial Center                                                  |
| FTA       | Failure to appear                                                        |
| JDMS      | Florida Courts Judicial Data Management Services                        |
| KM        | Kaplan–Meier estimator (censoring-aware time-to-event rate)              |
| O/E       | Observed count divided by model-expected count                           |
| OCA       | New York State Office of Court Administration                            |
| PACER     | Public Access to Court Electronic Records (federal)                      |
| RECAP     | Free Law Project's archive of PACER documents and dockets                |
| SAO       | Cook County State's Attorney's Office                                    |
| UCR       | Florida Uniform Case Reporting specification                             |
| WCAG      | Web Content Accessibility Guidelines                                     |

---

## 8. Phase Complexity Summary

| Phase | Description                                          | Complexity | Default model (platform)                                        |
|-------|------------------------------------------------------|------------|-----------------------------------------------------------------|
| 1     | Foundation, canonical schema, FJC judge slice        | High       | Claude Opus 5 (Claude Code); Fable 5.1 for the ingest-framework design step |
| 2     | Synthetic dataset, entity resolution, case timelines | High       | Fable 5.1 (Claude Code) for the generator-with-truth and resolution-framework steps; Opus 5 elsewhere |
| 3     | Metrics engine and the complete local demo           | High       | Fable 5.1 (Claude Code) for index events, exposure, and censoring design; Opus 5 elsewhere |
| 4     | Risk adjustment and validation                       | High       | Fable 5.1 (Claude Code) for methodology and validation; Opus 5 implementation |
| 5     | First real state-court pipeline; Florida plan        | High       | Claude Opus 5 (Claude Code); Fable 5.1 for attribution rules    |
| 6     | Validation on real data, admin tools, trust          | High       | Claude Opus 5 (Claude Code); Fable 5.1 for the audit protocol   |
| 7     | Florida pilot, federal dockets, coverage map         | High       | Claude Opus 5 (Claude Code)                                     |
| 8     | Production hardening and launch                      | Medium     | Claude Opus 5 (Claude Code); Fable 5.1 at Ultracode for the codebase-wide audit |
| 9     | Sustainability and data products (post-launch)       | Medium     | Claude Opus 5 (Claude Code); operator for entity, funder, and pricing decisions |

Model selections come from the roadmodel planning kit in `planning/`
(selector algorithm, catalog, cost scale) run against the operator's
context: Claude models run on Claude Code funded by the flat claude.ai
Max subscription (top useful effort, thinking on); GPT-family backups
(GPT-5.6 Sol for design-heavy steps, GPT-5.3 Codex for implementation
steps) run on Codex funded by ChatGPT Plus. Per-step tables, rationales,
and selection blocks live in each phase roadmap, beginning with
[`docs/phase01-roadmap.md`](docs/phase01-roadmap.md). Re-export the kit
at the start of every phase (`uv run poe kit`) so the catalog is current
before the phase roadmap is written.
