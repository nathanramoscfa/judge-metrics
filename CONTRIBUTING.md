<!-- CONTRIBUTING.md -->
# Contributing to JudgeMetrics

JudgeMetrics is built one roadmap step at a time, mostly by AI coding
agents executing `docs/phaseNN-roadmap.md` under the rules in
`AGENTS.md` and `ROADMAP.md` §5. Human contributors follow the same
rules. This file is the short operating version; the roadmap is the
source of truth where they differ.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (it fetches Python 3.13 itself)
- Git, with the [GitHub CLI](https://cli.github.com/) (`gh auth login`)
- Docker with Compose v2 (for `uv run poe up`)
- Node 22 with pnpm (from Phase 1 Step 5, for `web/`)

```sh
uv sync                                   # environment (.venv, all groups)
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
cp .env.example .env                      # then replace every change-me
```

`.env` is untracked and must stay that way. `.env.example` carries
placeholders only.

## Command interface

`uv run poe <task>` is the cross-platform interface; the `Makefile`
mirrors every target for environments with GNU make (`make check`).

| Task            | Runs                                                   |
|-----------------|--------------------------------------------------------|
| `check`         | lint, format check, type check, tests                  |
| `test`          | pytest (`tests/unit`, `tests/integration`, `tests/property`, `tests/golden`) |
| `lint`, `fmt`, `fmt-check`, `typecheck` | ruff check, ruff format, ruff format --check, mypy --strict |
| `gate`          | the full security gate: every pre-commit hook plus the pre-push stage |
| `up`, `down`    | Docker Compose services (PostgreSQL 17, MinIO) up / down; `up` also creates the scratch test database (`up-test-db`) |
| `kit`           | re-export the roadmodel planning kit                   |
| `migrate`       | Alembic migrations to head, as the admin role          |
| `dev-api`       | the API with auto-reload                               |
| `ingest-fjc`    | `judgemetrics ingest run fjc`: the FJC connector, as the ingest role, into the raw lake and canonical tables |
| `seed`          | `judgemetrics seed`: generate the demo-scale synthetic dataset into `data/synthetic/20260916` (skipped when its manifest is current) and ingest it through the `synthetic` connector, as the ingest role; refused in production |

`ingest run` and `seed` refuse to start without
`JUDGEMETRICS_IDENTIFIER_PEPPER` (see `.env.example`): it peppers the
hashes under which person identifiers are stored. Later steps add
`compute-metrics` and `bootstrap`. The web
app has its own scripts (`pnpm lint|typecheck|test|build|e2e`, see
`web/package.json`); `uv run poe dev-web` starts its dev server.

## The security gate

Every commit passes a local, fail-closed gate wired into `pre-commit`
(`.pre-commit-config.yaml`) and re-run in CI (`.github/workflows/ci.yml`):

| Check              | Tool                                             | Stage      |
|--------------------|--------------------------------------------------|------------|
| Lint and format    | `ruff check` (incl. flake8-bandit rules), `ruff format --check` | pre-commit |
| Types              | `mypy --strict`                                  | pre-commit |
| SAST               | `bandit -c pyproject.toml -r src alembic`        | pre-commit |
| Secret scan        | `detect-secrets-hook --baseline .secrets.baseline` (CI: gitleaks) | pre-commit |
| Dependency audit   | `pip-audit --strict` over `uv.lock` (`scripts/audit_deps.py`) | pre-push   |
| Hygiene            | trailing whitespace, EOF newline, YAML/TOML syntax, large files | pre-commit |

Run it on demand with `uv run poe gate`. A finding blocks the commit:
fix it in the step, never defer it. A `bandit` finding may be
suppressed only with an inline `# nosec` plus a justification comment;
a `detect-secrets` false positive is added to the baseline with
`uv run detect-secrets scan --baseline .secrets.baseline <file>` after
you have confirmed it is not a secret (scan the one file, and keep the
recorded filenames with forward slashes; the baseline itself is
allowlisted for the CI gitleaks scan in `.gitleaks.toml`). Workflow
files are a trust boundary:
pin every action to a full commit SHA, declare minimum `permissions:`,
and never expose a secret to a workflow triggered by an untrusted pull
request.

## Branch naming

| Prefix     | Purpose                     | Example                              |
|------------|-----------------------------|--------------------------------------|
| `feature/` | Roadmap step or new feature | `feature/phase01-step3-fjc-ingest`   |
| `fix/`     | Non-urgent bug fix          | `fix/service-date-overlap`           |
| `hotfix/`  | Urgent fix from `main`      | `hotfix/suppression-leak`            |
| `chore/`   | Tooling, deps, housekeeping | `chore/bump-ruff`                    |
| `docs/`    | Documentation only          | `docs/methodology-v1`                |
| `perf/`    | Performance work            | `perf/metric-snapshot-export`        |
| `release/` | Pre-release stabilisation   | `release/v1.0.0`                     |

## The step lifecycle

Every roadmap step follows six stages, in order, no exceptions:

1. **Create the branch** from a clean, up-to-date `main`, before any
   other action: `git checkout -b <branch>` using the step's
   `**Branch:**` line.
2. **Work on the branch**; the gate runs before every commit. Never
   push to `main` — it is protected with `enforce_admins: true`.
3. **Open the PR**: `gh pr create --base main --head <branch>` with a
   Conventional Commits title and a body that references the roadmap
   step and its acceptance criteria. One PR per step.
4. **Wait for green, then squash-merge**: `gh pr merge <PR> --squash
   --delete-branch`. If the branch falls behind, `gh pr update-branch
   --rebase` — never merge `main` into the branch (linear history).
   Run any post-deploy verification the step names.
5. **Retire the branch**: `git switch main && git pull --ff-only origin
   main && git fetch --prune origin`, then delete local `[gone]`
   branches (and any worktree first).
6. **Declare completion** after updating `docs/ROADMAP.md`, then start
   the next step in a fresh session.

Classify every finding that is not the step itself (spec rot, upstream
gap, implementation bug, architectural question, process improvement,
security finding, data-semantics finding, data-access question) per
`ROADMAP.md` §5 "Defect handling & triage" before acting on it.

## Tests

```sh
uv run poe test                  # unit + integration + property + golden
                                 # (database tests skip unless a database
                                 # URL is configured: `uv run poe up`)
uv run pytest -m unit            # unit only
uv run pytest -m integration     # everything that needs the database
uv run pytest -m property        # the Hypothesis property tests
uv run pytest -m golden          # the golden fixture regression suite
uv run pytest --cov              # with coverage
```

Tests live in `tests/unit/`, `tests/integration/`, `tests/property/`,
and `tests/golden/` and carry the markers `unit`, `integration`,
`property`, and `golden` (`pyproject.toml`; `--strict-markers`). A
property or golden test that needs the database also carries
`integration`. Verify scripts are Python (`scripts/verify_phaseNN.py`)
so they run identically on Windows and Ubuntu CI.

**The scratch test database.** Every database test runs through the
`test_settings` fixture (`tests/conftest.py`). With
`JUDGEMETRICS_TEST_DATABASE_URL` set — `uv run poe up` creates
`judgemetrics_test` beside the main database, owned by the Compose
superuser, with `pg_trgm` and the same role grants
(`infra/docker/postgres/03-test-database.sql`; the one-shot
`postgres-test-init` job brings an older volume up to date) — the
migration round trip, the fixture ingests, the property tests, and the
golden suite all run there: the variable's URL is the owner that runs
the migrations, and the app and ingest roles' configured URLs are
retargeted at that database, so the role split is still exercised. A
live ingest in the main database survives `uv run poe check`. With the
variable unset the suite falls back to the configured database as
before and warns once (`ScratchDatabaseUnsetWarning`), and the round
trip then empties a local live ingest. CI points the variable at the
throwaway service database.

**Hypothesis.** `tests/property/` runs under the profile named by
`HYPOTHESIS_PROFILE`: `ci` (50 examples per test, no deadline; CI sets
it) or `dev` (the default: 20 examples, no deadline, because generating
a dataset takes longer than Hypothesis's 200 ms default). Strategies
draw seeds, orderings, and formatting variants only — never names — and
a failing example prints the seed and the scale. The example database
`.hypothesis/` is ignored by git.

## Compose services

`uv run poe up` starts PostgreSQL 17 (with `pg_trgm` and the roles
`judgemetrics_app`, `judgemetrics_ingest`, `judgemetrics_admin` created
from `infra/docker/postgres/`) and MinIO (bucket `judgemetrics-raw`
with versioning), waits for them to be healthy, and runs the one-shot
bucket-creation job. `uv run poe down` stops them; add `-v` by hand
(`docker compose down -v`) to discard the volumes. Ports are
overridable in `.env` (`POSTGRES_PORT`, `MINIO_API_PORT`,
`MINIO_CONSOLE_PORT`) for machines where 5432 or 9000 are taken.

## Conventions

- Every new source file starts with its repo-relative path as a comment
  on the first line (`# src/judgemetrics/x.py`, `// web/lib/x.ts`,
  `<!-- docs/x.md -->`, `-- infra/docker/x.sql`).
- Markdown prose wraps at 80 columns; Python line length is 100; line
  endings are LF everywhere.
- ruff (lint and format), mypy `--strict`, pytest. `uv sync` installs
  everything; never `pip install` into the environment by hand.
- Definition of done for any feature: implemented; typed; migration if
  required; unit tests; integration tests when relevant; documentation
  updated; lint, type check, and tests pass; frontend build passes when
  the frontend is affected; no credentials committed; data lineage
  preserved when data is affected.

## Repository settings

Applied once with `gh` (Phase 1 Step 1) and recorded here so they can
be re-applied or audited:

```sh
gh repo edit nathanramoscfa/judge-metrics \
  --enable-squash-merge \
  --enable-merge-commit=false \
  --enable-rebase-merge=false \
  --delete-branch-on-merge

gh api -X PUT repos/nathanramoscfa/judge-metrics/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["test", "phase-verify (01)"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON

gh api -X PATCH repos/nathanramoscfa/judge-metrics --input - <<'JSON'
{
  "security_and_analysis": {
    "secret_scanning": { "status": "enabled" },
    "secret_scanning_push_protection": { "status": "enabled" }
  }
}
JSON
```

`required_pull_request_reviews` is `null` because the project has a
single maintainer; the required status checks and `enforce_admins` are
what keep unreviewed or red changes off `main`. Two contexts are
required: `test`, the aggregate of `ci.yml`, and `phase-verify (01)`,
the Phase 1 entry of `.github/workflows/phase-verify.yml` (Phase 1
Step 6). Each later phase adds its matrix entry to the required
contexts with the same call, replacing the whole list:

```sh
gh api -X PATCH repos/nathanramoscfa/judge-metrics/branches/main/protection/required_status_checks   --input - <<'JSON'
{ "strict": true, "contexts": ["test", "phase-verify (01)"] }
JSON
```

Verify with:

```sh
gh api repos/nathanramoscfa/judge-metrics/branches/main/protection \
  --jq '{admins: .enforce_admins.enabled,
         linear: .required_linear_history.enabled,
         checks: .required_status_checks.contexts}'
gh repo view nathanramoscfa/judge-metrics --json \
  deleteBranchOnMerge,squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed
```
