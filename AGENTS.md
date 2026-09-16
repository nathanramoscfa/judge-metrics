<!-- AGENTS.md -->
# JudgeMetrics — operating instructions for AI coding agents

JudgeMetrics is a transparent, reproducible analytics platform over
public criminal-court records: judicial assignments, case events,
dispositions, sentences, and documented subsequent justice-system
events, with every published statistic traceable to versioned source
records and code. Python 3.13, uv, FastAPI, SQLAlchemy 2, Alembic,
PostgreSQL, Polars, DuckDB; Next.js and TypeScript in `web/`.

## Where the plan lives

- `docs/brief/judgemetrics-master-project-specification.xml` — the
  product specification (do not edit; it is the source of truth for
  the canonical data model, attribution model, outcome definitions,
  presentation rules, security requirements, and testing strategy).
- `ROADMAP.md` — the project roadmap (phases, architecture, branch,
  security, release, and operations strategy). Read §5 before any work.
- `docs/phaseNN-roadmap.md` — the executable plan for one phase, one
  step per agent session. Start from the step you were given.
- `docs/ROADMAP.md` — the living status document: current phase,
  completed items, unresolved data-access questions, next milestones.
  Update it at the end of every step; record a data-access question
  there instead of inventing an answer.
- `docs/DATA_SOURCES.md` — the source register. A connector may depend
  only on facts marked verified there.
- `planning/` — the roadmodel planning kit. When asked to recommend a
  model for a step, run `planning/model-selector.txt` yourself against
  `planning/user-context.md`; do not call an external API or MCP tool
  (`planning/HOW-TO-USE.md`, "you are the engine"). Re-export the kit
  at the start of each phase: `uv run poe kit`.

## Step discipline (binding)

1. First action of every step: `git checkout -b <branch>` using the
   step's `**Branch:**` line, from a clean, up-to-date `main`.
2. Pass the security gate before every commit (pre-commit: secret scan,
   SAST, dependency audit, sensitive-data diff review). It is
   fail-closed; fix findings in the step, never defer them.
3. One PR per step; Conventional Commits title; body references the
   roadmap step and acceptance criteria; wait for green; squash-merge;
   retire the branch; update `docs/ROADMAP.md`; declare completion with
   the verbatim line "Step N is complete. You can now move on to
   Step N+1." only when every acceptance criterion is met; then a new
   conversation.
4. Classify every finding before acting on it (spec rot, upstream gap,
   implementation bug, architectural question, process improvement,
   security finding, data-semantics finding, data-access question) per
   `ROADMAP.md` §5 "Defect handling & triage".

## Definition of done for any feature (from the brief)

Feature implemented; types added; database migration added if
required; unit tests added; integration tests added when relevant;
relevant documentation updated; lint passes; type checking passes;
tests pass; frontend production build passes when the frontend is
affected; no credentials committed; data lineage preserved when data is
affected.

## Working rules (from the brief)

- Build working software; do not spend a session writing architecture
  documents, and do not build national-scale infrastructure before the
  vertical slice works.
- Never create fake production integrations. When external access is
  unavailable, create the adapter interface plus fixtures and document
  exactly what credential or access step remains.
- Prefer explicit, readable code over abstraction during the MVP.
- Use migrations from the beginning. Use deterministic random seeds for
  synthetic data.
- Keep source-specific parsing separate from canonical-domain logic,
  and statistical methodology separate from presentation logic.
- Never overwrite a raw source artifact. Every transformation from
  source record to published metric must be reproducible.
- Update this file whenever an architectural decision matters for
  future sessions.

## Domain rules (non-negotiable)

- An arrest never proves a crime. Arrest, charge, conviction, dismissal,
  acquittal, release, sentence, and later events are separate concepts
  and separate rows.
- Every judge-level metric uses only events whose actor attribution
  satisfies the metric's documented inclusion rules. A prosecutor's
  dismissal is not a judicial dismissal; a statutory release is not a
  discretionary decision.
- Associations are never presented as causation. There is no composite,
  ideological, partisan, or "best/worst judge" score. The brief's
  statistical warnings are published as known limitations on the
  methodology page and are never softened for presentation.
- Persons are pseudonymous in every public surface. Never merge persons
  on name alone. Restricted attributes never leave the restricted
  schema, are never model features by default, and never appear in
  logs.
- Synthetic data is labelled synthetic on every surface and is refused
  by the ingest runner in production.
- Never scrape a source against its terms, robots rules, or law. Never
  fabricate a data-source capability.
- Every published number shows numerator, denominator, date range,
  coverage, sample size, and (for adjusted statistics) an interval and
  a methodology version, and traces to raw artifacts through
  `judgemetrics provenance trace`. Suppress small cohorts.

## Conventions

- Prose in Markdown wraps at 80 columns; Python line length is 100.
- Every new source file starts with its repo-relative path as a comment
  on the first line (`# src/judgemetrics/x.py`, `// web/lib/x.ts`,
  `<!-- docs/x.md -->`, `-- infra/docker/x.sql`).
- `uv sync` installs everything; `uv run <tool>` runs it. Never
  `pip install` into the environment by hand.
- ruff (lint and format), mypy `--strict`, pytest, hypothesis for
  property tests. Tests live in `tests/`; integration tests need the
  Compose services (`uv run poe up`).
- Verify scripts are Python (`scripts/verify_phaseNN.py`) so they run
  identically on Windows and Ubuntu CI.
- Line endings are LF everywhere (`.gitattributes`).

## Commands

`uv run poe <task>` is the primary interface (cross-platform); the
`Makefile` mirrors every target for environments with GNU make.

```sh
uv sync                    # environment (make install)
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
uv run poe check           # lint + format check + type check + tests
uv run poe test            # tests only
uv run poe lint            # ruff check
uv run poe fmt             # ruff format
uv run poe typecheck       # mypy --strict
uv run poe gate            # the security gate: all hooks + pre-push stage
uv run poe up              # docker compose: postgres + minio healthy, bucket
uv run poe down            # docker compose down
uv run poe kit             # refresh the planning kit
uv run judgemetrics        # CLI (placeholder until Phase 1 Step 2)
```

Later steps add `migrate`, `dev-api`, `dev-web`, `ingest-fjc`, `seed`,
`compute-metrics`, and `bootstrap`.

## Architectural decisions that matter for future sessions

- The dependency audit runs `pip-audit --strict --require-hashes` over
  an export of `uv.lock` (`scripts/audit_deps.py`), not over the live
  environment: the editable `judgemetrics` project is not on PyPI, so
  a raw `pip-audit --strict` fails for the wrong reason.
- `up` is a sequence task: `docker compose up -d --wait postgres minio`
  and then `docker compose run --rm minio-init`, because `--wait`
  treats a cleanly exited one-shot job as a failure.
- MinIO images are pulled from `quay.io/minio` (the Docker Hub
  repository is no longer served) and pinned to a release tag.
- Host ports are overridable in `.env` (`POSTGRES_PORT`,
  `MINIO_API_PORT`, `MINIO_CONSOLE_PORT`); the maintainer's machine has
  a native PostgreSQL on 5432 and Windows reserves 9000.
- Database roles: `judgemetrics_app` (read-only), `judgemetrics_ingest`
  (DML), `judgemetrics_admin` (DDL, not superuser); default privileges
  are set for objects created by the admin role or the Compose
  superuser, so migrations may run as either.
- `detect-secrets` false positives are allowlisted inline with
  `# pragma: allowlist secret`; the hygiene test strips ` #` inline
  comments from `.env.example` values the way Docker Compose does.

## End-of-session report (from the brief)

Every implementation session ends with: files created or changed;
architecture implemented; commands executed; test results; what
currently works; known issues; external access still needed; and the
next concrete development milestone.
