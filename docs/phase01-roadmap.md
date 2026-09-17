<!-- docs/phase01-roadmap.md -->
# Phase 1 Roadmap — Foundation, Canonical Schema, and the FJC Judge Slice

## Overview

Phase 1 opens the gate every later phase walks through: a repository
with a fail-closed security gate, CI that builds and scans containers,
branch protection, and the brief's command interface; an application
core with the complete canonical schema behind a reversible baseline
migration; an ingest framework whose first connector loads real public
data (the Federal Judicial Center's biographical directory) into an
immutable raw lake and canonical tables; a versioned public API with
rate-limited search; and a web app that renders a judge page from that
data. Phase 2 cannot load the synthetic justice dataset without every
canonical table, the connector protocol, and the runner, and Phase 3
cannot publish metrics without the API and web foundations, so all of
it lands here as one runnable vertical slice rather than as scattered
placeholders. Phase 1 covers the brief's development phases 0
(Repository Bootstrap), 1 (Database Foundation), 3 (First Real Data
Connector), and the judge portions of 4 (Core API) and 6 (Web
Application).

Phase 1 does NOT ingest any case, charge, disposition, or defendant
data, synthetic or real; it does NOT compute any metric; and it does
NOT deploy anything beyond the maintainer's machine and the GitHub
repository settings and workflows. Those are Phases 2, 3, and 8
respectively.

The phase lands in 6 layers:

1. **Repository bootstrap, command interface, security gate, and CI**
   — the GitHub remote with branch protection (`enforce_admins`,
   linear history, squash-only, delete-branch-on-merge); `LICENSE`,
   `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue and PR
   templates; the `pre-commit` gate (ruff, mypy, bandit,
   `detect-secrets`, `pip-audit`) mirrored in
   `.github/workflows/ci.yml` with SHA-pinned actions and an aggregate
   `test` status check; `dependabot.yml`; `docker-compose.yml`
   (PostgreSQL 17 with a `pg_trgm` init script, MinIO with a
   bucket-creation job); `.env.example`; and the `up` and `down`
   targets of the command interface.
2. **Application core and the canonical schema** —
   `src/judgemetrics/config.py`, `logging.py` (JSON logs with a
   scrubbing processor), `main.py` (`create_app()`), `/api/v1/health`
   and `/api/v1/ready`, SQLAlchemy 2 models for all twenty-three
   entities of the brief's canonical data model, the reversible Alembic
   baseline `0001_baseline` with the performance-strategy indexes, the
   Typer CLI with `db`, `ingest`, and `serve` groups, the API container
   image (`infra/docker/api.Dockerfile`), a compose `api` service, the
   CI `container` job that builds and vulnerability-scans the image, and
   the `migrate` and `dev-api` targets.
3. **Ingest framework and the FJC connector** — the `SourceConnector`
   protocol, `RawObjectStore` (filesystem and S3-compatible, never
   overwriting), the idempotent fourteen-step runner, and
   `judgemetrics/ingest/fjc/` loading `judges.csv` and
   `federal-judicial-service.csv` into judges, service records, and an
   Article III court roster with data-quality checks; the `ingest-fjc`
   target; `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`,
   `data/README.md`.
4. **Public API v1** — judges, courts, jurisdictions, and trigram
   search endpoints with pagination, strict maximum page sizes, strict
   filter validation, provenance metadata, an in-process rate limiter
   on search, an N+1 query guard, `docs/openapi.json` checked in, and
   `docs/API.md`.
5. **Web foundation** — the Next.js app in `web/` with a typed client
   generated from the OpenAPI document, home, search, judge, court, and
   methodology pages, light and dark mode, Vitest, a frontend type
   check, a Playwright smoke test, the web container image, and the
   `dev-web` target.
6. **QA + `verify_phase01.py`** — verification script (`--fast`,
   `--py`, `--node`, `--e2e`, `--security`, `--all`, `--post`),
   `docs/phase01-qa-findings.md` rollup, the `phase-verify.yml` matrix
   entry that binds the phase to CI, and the status update in
   `docs/ROADMAP.md`.

The ship test for Phase 1 is straightforward: `uv run poe up`,
`uv run poe migrate`, and `uv run poe ingest-fjc` complete on a clean
machine, the baseline creates every canonical table and downgrades
cleanly, and a second ingest run creates zero new canonical rows;
`GET /api/v1/judges/{id}` returns an FJC judge with service records and
provenance and `/search` returns 429 after the configured burst;
`/judges/[judgeId]` renders that judge from the local API and the
Playwright smoke test passes; `uv run poe check`, `pnpm typecheck`,
`pnpm test`, and `pnpm build` are green locally and in CI; the API and
web images build and pass the vulnerability scan in CI; a direct push
to `main` is rejected; and `uv run python scripts/verify_phase01.py
--fast` exits 0 on Ubuntu CI with the `phase-verify.yml` matrix entry
`01` green.

**Pre-requisite:** the repository scaffold is committed and pushed
(operator, once, before Step 1 — see "Operator pre-step" below). No
prior phase exists.

**Dependency:** Phase 2 (Synthetic Justice Dataset, Entity Resolution,
and Case Timelines) does not start until Phase 1's V-checks are green;
it inherits the complete canonical schema, the connector protocol and
runner, the API conventions, and the web foundation, and adds the
synthetic connector, the entity-resolution framework, and the case
pages on top of them.

**Design rationale (judges first, the whole schema first).** The FJC
export is the only Phase 1 candidate that is official, bulk, free,
nightly, and free of defendant data, so the pipeline's provenance,
idempotency, and API and web conventions are proven on the lowest-risk
data before any defendant-level record — synthetic or real — enters the
system. The baseline migration creates the whole canonical model rather
than the judge tables alone because the brief says to use migrations
from the beginning, Phase 2's synthetic dataset exercises every table,
and one reversible baseline is easier to reason about than a schema
that accretes across phases. Verification scripts are Python and the
command interface is poethepoet with a `Makefile` shim because the
maintainer develops on Windows without GNU make; one task runner works
identically on Windows and Ubuntu CI.

**Operator pre-step (once, before Step 1).** Commit the scaffold on
`main` as the initial commit and create the remote:

```sh
git add -A
git commit -m "chore: scaffold repository, planning kit, and roadmap"
gh repo create nathanramoscfa/judge-metrics --private --source=. \
  --remote=origin --push
```

Step 1 then configures branch protection, so this initial push is the
only direct push `main` ever receives.

**Branch strategy.** Every step in this phase lands on its own
short-lived feature branch (`feature/phase01-step{M}-<slug>`), opens a
pull request against `main`, waits for the project's CI workflow to go
green, and squash-merges with a Conventional Commits subject line.
Direct pushes to `main` are blocked by branch protection. See the
parent [`ROADMAP.md`](../ROADMAP.md) "Branch management strategy" for
the canonical naming convention, PR rules, and release tagging — this
paragraph confirms those rules apply unchanged within this phase.
Per-step branches are listed on each step header below as
`**Branch:**` so reviewers can map commits 1:1 to the step they
implement.

**Branch-first execution rule.** The very first action of every step
— before reading any files, before running any tool, before drafting
any change — is to check out the branch named in that step's
`**Branch:**` line:

```sh
git checkout -b feature/phase01-step{M}-<slug>
```

This is non-negotiable. `main` is protected with
`enforce_admins: true`, so a commit on `main` cannot be pushed and
must be rewound or rebased onto the feature branch before the PR can
open. If you discover mid-step that you started on `main`, recover by
running the same `git checkout -b` command immediately (uncommitted
changes carry over), then continue. AI coding agents executing a step
from this roadmap must treat the branch checkout as Step 0 of every
step.

**Worktree rule.** One working tree, one step in flight — the
lifecycle below assumes the primary checkout. A second working tree is
created only with `git worktree add`, and only for the three cases the
parent ROADMAP "Worktree strategy" sanctions: a `hotfix/` branch
interrupting this step (cut from `origin/main` in its own worktree so
this step's tree is untouched); steps the Execution Order below
explicitly draws in parallel (none in this phase); and
worktree-isolated subagents inside a step (throwaway trees that merge
back into the step branch locally and are removed before the PR
opens). In those cases Stage 1 becomes `git fetch origin && git
worktree add -b feature/phase01-step{M}-<slug> .worktrees/<slug>
origin/main`, the worktree is bootstrapped before any test or build
(`uv sync`, `pnpm install` in `web/`, `.env` copied — a worktree has
none of the primary tree's untracked state and must never borrow the
primary tree's environment), the Stage 4 merge runs from the primary
tree, and Stage 5 removes the worktree BEFORE pruning the branch.
Undeclared parallelism is a lifecycle violation, not a shortcut.
Worktree location for this project: git-ignored `.worktrees/<slug>/`.

**Security-first execution rule.** Security is not a phase — it is a
gate on every commit of every step. Before each `git commit`, the
step's work must pass the local, fail-closed security gate: secret/PII
scan clean (`detect-secrets`), SAST clean (`bandit`; and
`eslint-plugin-security` once `web/` exists), dependency audit clean
(`pip-audit`; `pnpm audit --audit-level=high` once `web/` exists), and
a diff review confirming no sensitive data and no new insecure
pattern. This gate is wired into the `pre-commit` hook (Step 1
installs it) and re-run in CI together with the container image scan
(Step 2 adds it), so a security issue introduced while implementing a
step is caught during development — before it reaches the branch, the
PR, or `main`. See the parent ROADMAP "Security & privacy strategy" →
"Per-step security gate" for the canonical checks; each step's XML
`<task>` carries a `<security>` block restating them, and each step's
Acceptance Criteria ends with a security check. Phase 1 handles no
defendant data, but it establishes the secrets handling (`.env`
untracked, `.env.example` placeholders only, database and S3
credentials read from the environment, database roles separated) that
every later phase relies on.

**Deploy-and-verify rule.** Merged is not deployed, and deployed is
not released. Every step header carries a `**Deploys:**` line naming
the surface and environment the step's merge reaches — or `nothing
beyond merge`. In Phase 1 the only surfaces a merge reaches are the
GitHub repository settings and workflow files (live on merge) and the
maintainer's local environment (`uv run poe up`, `uv run poe migrate`,
`uv run poe dev-api`); no step deploys to a shared environment. Where a
step's Deploys line names a surface, its acceptance criteria carry a
**Deployed & verified** bullet that must be green before the step is
declared complete. A step that introduces a required environment
variable verifies at kickoff that `.env.example` documents it and that
the local `.env` carries a value.

**Triage rule.** Findings surfaced while executing a step are
classified before they are acted on, per the parent ROADMAP "Defect
handling & triage": spec rot → edit this roadmap's affected `<task>`
block now; upstream gap → patch the earlier step's prompt and add it
to the carry-over checklist; implementation bug → fix in-step only if
it blocks this step's acceptance criteria, otherwise an issue and its
own branch in a fresh conversation; architectural question → an issue
for a future phase; process improvement → recorded where the next
conversation will read it (this roadmap or `AGENTS.md`); data-semantics
finding → edit the versioned rule or reference table and bump its
version; data-access question → recorded in `docs/ROADMAP.md`
"Unresolved data-access questions", never answered by guesswork;
security finding → jumps the queue by severity. A step's PR contains
the step plus blocking fixes only, and lists the issues it opened.
`docs/phase01-qa-findings.md` is the rollup: every finding, its class,
and the guard added so the class cannot recur.

**Step lifecycle.** Every step in this phase follows the exact same
six-stage lifecycle, in order, with no exceptions. Each stage is a
hard checkpoint — if a stage is skipped, branch protection or the next
step's Stage 1 will fail loudly, and that is the safety net. AI coding
agents MUST execute all six stages before declaring a step complete.

1. **Create the branch.** Before any Read / Edit / Bash, run
   `git checkout -b feature/phase01-step{M}-<slug>` from a clean,
   up-to-date `main`. The exact branch name comes from this step's
   `**Branch:**` line. When the Worktree rule applies, the equivalent
   is `git fetch origin && git worktree add -b <branch>
   .worktrees/<slug> origin/main`, followed by the worktree's
   bootstrap.

2. **Work on the branch, passing the security gate before every
   commit.** All commits land here. Never push to `main` directly —
   branch protection (`enforce_admins: true`) rejects it. Before each
   `git commit`, run the local security gate (secret/PII scan, SAST,
   dependency audit, sensitive-data diff review — see the step's
   `<security>` block). It is fail-closed: a finding blocks the
   commit.

3. **Open the PR.** `gh pr create --base main --head <branch>` with a
   Conventional Commits title and a body that references this roadmap
   step and its acceptance criteria. One PR per step; never bundle two
   steps into one PR.

4. **Wait for green checks, then squash-merge.** Every required status
   check (the aggregate `test` gate from `ci.yml`, and from Step 6 on
   the `phase-verify.yml` matrix entry for this phase) must report
   success. If the PR goes BEHIND main while waiting, refresh with
   `gh pr update-branch --rebase` — never merge `main` into the
   branch; `required_linear_history: true` enforces rebase. Once
   every check is green:

   ```sh
   gh pr merge <PR_NUMBER> --squash --delete-branch
   ```

   If this step's `**Deploys:**` line names a surface, the merge is not
   the finish line: run the Deployed & verified check from the
   acceptance criteria against the target environment now before
   declaring the step complete.

5. **Retire the branch (remote + local).** The `--delete-branch` flag
   plus the repo's `delete_branch_on_merge: true` setting retire the
   remote automatically. Sync local state and prune the merged branch
   plus any other `[gone]` labels left over from prior PRs:

   ```sh
   git switch main
   git pull --ff-only origin main
   git fetch --prune origin
   git branch -vv | grep ': gone]' | awk '{print $1}' \
     | xargs -r git branch -D
   ```

   If this step ran in its own worktree, remove it FIRST —
   `git worktree remove .worktrees/<slug>`, then `git worktree prune`
   — because `git branch -D` refuses a branch still checked out in a
   worktree. Confirm with `git branch -vv` that only `main` remains
   locally, and with `git worktree list` that only the primary tree
   remains.

6. **Declare completion, then new conversation.** Update
   `docs/ROADMAP.md` (completed items, any new unresolved data-access
   question). Once the PR is merged and every one of this step's
   acceptance criteria is affirmatively met, say so plainly. End your
   final response with an explicit, unhedged completion line —
   verbatim shape "Step {M} is complete. You can now move on to
   Step {M+1}." — so the operator has a clean stopping point at which
   to close this conversation. Do NOT bury that line under caveats,
   newly discovered issues, or suggested improvements: if you have
   any, report them in a short, clearly labelled "Follow-ups
   (non-blocking)" note placed AFTER the completion line, and never let
   them reopen the step. If any acceptance criterion is NOT met, state
   plainly that the step is NOT complete, name the failing criteria,
   and do not emit the completion line. Then the operator closes this
   Claude Code / Codex session and opens a fresh one before starting
   Step {M+1}; the new conversation begins again at Stage 1 with the
   next step's `**Branch:**` line driving the `git checkout -b`
   command. No work straddles two steps.

---

## Current State (as of the scaffold)

### Repository and tooling surface

- The repository is a fresh `git init` on branch `main` with no
  commits and no remote. `pyproject.toml` declares the `judgemetrics`
  package (src layout, `uv_build` backend, `requires-python >= 3.13`),
  a `dev` dependency group (ruff, mypy, pytest, pytest-cov,
  poethepoet) and a `planning` group (roadmodel), both synced by
  default, and `[tool.poe.tasks]` with `test`, `lint`, `fmt`,
  `fmt-check`, `typecheck`, `check`, and `kit`; a `Makefile` shim
  mirrors those targets. `uv run poe check` is green. `uv.lock` and
  `.python-version` (3.13) pin the environment; `.venv/` holds
  CPython 3.13.15.
- `.gitignore`, `.gitattributes` (LF everywhere), and `.editorconfig`
  exist. There is no `LICENSE`, no `CONTRIBUTING.md`, no
  `SECURITY.md`, no `.github/`, no `docker-compose.yml`, no
  `.env.example`, no `infra/`, and no `pre-commit` configuration. Step 1
  adds all of them except `infra/`, which Step 2 creates.
- `src/judgemetrics/__init__.py` exposes `__version__` and a
  placeholder `main()` wired to the `judgemetrics` console script;
  `tests/test_smoke.py` covers both. Step 2 replaces `main()` with the
  Typer CLI and moves tests into `tests/unit/` and
  `tests/integration/`.

### Application surface

- No application code exists: no FastAPI app, no settings, no logging,
  no database models, no migrations, no CLI beyond the placeholder.
  Step 2 creates `config.py`, `logging.py`, `main.py`, `cli.py`,
  `api/routes/health.py`, `db/base.py`, `db/session.py`, the
  `db/models/` package, and `alembic/`.
- No ingest code exists. Step 3 creates `ingest/base.py`,
  `ingest/store.py`, `ingest/registry.py`, `ingest/runner.py`,
  `ingest/fjc/`, `quality/checks.py`, and `normalization/names.py`.
- No API routes beyond health exist until Step 4; no `web/` exists
  until Step 5.

### Data and schema surface

- No database exists. Step 1 adds Docker Compose with PostgreSQL 17
  (with `pg_trgm` enabled by an init script) and MinIO; Step 2 adds
  the Alembic baseline creating all twenty-three entities of the
  brief's canonical data model
  (`docs/brief/judgemetrics-master-project-specification.xml`,
  `<canonical_data_model>`), with the `case` entity stored as table
  `court_case` because `case` is a reserved word. UUID primary keys,
  `external_ids` JSONB with GIN indexes, `normalized_name` columns with
  trigram indexes, and the brief's performance-strategy indexes on
  court, judge, person, normalized case number, event time, and source
  external ids.
- The only Phase 1 source is `fjc` (see `docs/DATA_SOURCES.md`,
  verified 2026-09-15): `judges.csv` and
  `federal-judicial-service.csv`, keyed by the FJC node id (`nid`),
  refreshed nightly, public federal-government data. Exact column
  headers are not yet recorded; Step 3 reads them at first fetch and
  records them in the source register.

### Security & sensitive-data surface

- Phase 1 handles no defendant data. The sensitive surface is
  configuration: the database URL, S3-compatible credentials for the
  raw lake, and any future source tokens. Today nothing enforces
  their handling. Step 1 installs the fail-closed gate
  (`detect-secrets`, `bandit`, `pip-audit`, ruff, mypy in
  `.pre-commit-config.yaml`; `gitleaks`, `bandit`, `pip-audit` as CI
  required checks), Step 2 adds the container image scan, and the
  pattern every later step mirrors is fixed: secrets come only from
  the environment, `.env` is untracked, `.env.example` carries
  placeholders, database roles are separated (`judgemetrics_app`
  read-only public role, `judgemetrics_ingest` writer, `judgemetrics_admin`),
  and CI pins every action to a commit SHA under least-privilege
  `permissions:`.
- Step 2's logging scrubber (drops keys such as `password`, `token`,
  `secret`, `authorization`, `person_id`, `case_participant_id`) is the
  pattern Phase 5 extends to real defendant identifiers.

### Operations & observability surface

- No runtime surface exists. Step 2 adds `/api/v1/health` (version,
  git SHA, Alembic head) and `/api/v1/ready` (database reachability);
  Step 1's CI aggregate `test` check and Step 6's `phase-verify.yml`
  are the alarms — a red check on `main` is the failure signal a solo
  maintainer sees. There is no deployed environment, no scheduled
  automation, and no metered dependency in Phase 1; PACER (metered)
  is a Phase 7 concern.

### Documentation surface

- `ROADMAP.md`, `docs/ROADMAP.md` (status and unresolved data-access
  questions), `AGENTS.md` (imported by `CLAUDE.md`), `README.md`,
  `docs/DATA_SOURCES.md`, `docs/brief/` (the verbatim brief), and this
  file exist. `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, and
  `data/README.md` are created in Step 3; `docs/openapi.json` and
  `docs/API.md` in Step 4; `docs/phase01-qa-findings.md` in Step 6.
  The brief's remaining documents (`METHODOLOGY.md`,
  `ENTITY_RESOLUTION.md`, `PRIVACY.md`, `SECURITY.md`,
  `DEPLOYMENT.md`) belong to later phases.

### Verification surfaces

- No `scripts/verify_phaseNN.py` exists; Phase 1 creates the first
  one, `scripts/verify_phase01.py`, which becomes the structural
  template for every later phase (`--fast` / `--py` / `--node` /
  `--e2e` / `--security` / `--all` / `--post` mode contract, numbered
  static checks, V-check matrix, summary table, exit codes).
- `.github/workflows/phase-verify.yml` does not exist; Step 6 creates
  it with matrix entry `01`.

---

## Execution Order

```
Step 1  (bootstrap + interface + gate)   LICENSE, community files, pre-commit
                                          gate, ci.yml, dependabot, compose,
                                          .env.example, up/down targets,
                                          branch protection
                                          → implement
  ↓
Step 2  (core + canonical schema)        settings, JSON logging, create_app,
                                          /health /ready, 23 models, Alembic
                                          baseline, Typer CLI, API image +
                                          container scan, migrate/dev-api
                                          → implement
  ↓
Step 3  (ingest framework + FJC)         SourceConnector, RawObjectStore,
                                          runner, fjc connector, DQ checks,
                                          ingest-fjc target, ARCHITECTURE.md,
                                          DATA_MODEL.md, data/README.md
                                          → implement
  ↓
Step 4  (public API v1)                  judges/courts/jurisdictions/search
                                          routes, pagination, provenance,
                                          rate limiter, N+1 guard,
                                          docs/openapi.json, docs/API.md
                                          → implement
  ↓
Step 5  (web foundation)                 web/ Next.js app, typed client,
                                          home/search/judge/court/methodology
                                          pages, Vitest, typecheck, Playwright
                                          smoke, web image, dev-web target
                                          → implement
  ↓
Step 6  (QA + verify_phase01.py)         scripts/verify_phase01.py
                                          + docs/phase01-qa-findings.md
                                          + phase-verify.yml matrix entry
                                          + docs/ROADMAP.md status update
                                          → create

--- post-implementation ---

V1  Gate, CI, branch protection, compose, command interface, and
    community files exist and are enforced (planted secret blocked;
    direct push rejected).
V2  Baseline creates every canonical table and round-trips; /health
    and /ready report version, SHA, Alembic head, and database state;
    logs are scrubbed; the API image builds and scans clean.
V3  FJC ingest is idempotent, provenance-complete, and DQ-checked.
V4  API v1 endpoints paginate, validate, search under a rate limit,
    avoid N+1 queries, and carry provenance; docs/openapi.json matches
    the app.
V5  Web pages render from the local API; type check, unit tests, and
    Playwright smoke pass; the web image builds; no non-public env var
    reaches the client bundle.
V6  verify_phase01.py --fast and --security exit 0 on Ubuntu CI under
    the phase-verify.yml matrix entry 01.
```

Steps are sequential by dependency: Step 1's gate, CI, compose
services, and command interface must exist before Step 2 can run
integration tests against PostgreSQL under the same checks every later
commit faces; Step 2's models, migrations, image, and CLI are what Step
3's runner publishes into, what its `ingest` commands hang from, and
what the container job builds; Step 4's routes read the tables Step 3
fills and cannot be tested without ingested fixtures; Step 5's typed
client is generated from the `docs/openapi.json` Step 4 commits; Step 6
verifies every deliverable of Steps 1–5. This phase has no steps drawn
in parallel.

---

## Step 1 — Repository Bootstrap, Command Interface, Security Gate, and CI

> **Goal:** Turn the scaffold into a governed repository: land the
> `LICENSE` (Apache-2.0, operator confirms in the PR), `CONTRIBUTING.md`,
> `SECURITY.md`, `CODE_OF_CONDUCT.md`, `.github/ISSUE_TEMPLATE/`, and
> `.github/PULL_REQUEST_TEMPLATE.md`; wire the fail-closed local
> security gate in `.pre-commit-config.yaml` (ruff check and format,
> mypy, bandit, `detect-secrets` with a committed baseline, and
> `pip-audit` at the pre-push stage) with `pre-commit`, `bandit`,
> `pip-audit`, and `detect-secrets` added to the `dev` group; mirror
> the gate in `.github/workflows/ci.yml` (python, security, and an
> aggregate `test` job) with every action pinned to a commit SHA under
> least-privilege `permissions:`; add `.github/dependabot.yml`,
> `docker-compose.yml` (PostgreSQL 17 with a `pg_trgm` init script and
> the three database roles, MinIO with a bucket-creation job),
> `.env.example` with placeholders only, and the `up` and `down`
> targets in `[tool.poe.tasks]` and the `Makefile`; configure branch
> protection and repository merge settings through `gh`; and ship
> `tests/unit/test_repo_hygiene.py` covering all of it. This step lands
> the governance chassis; Steps 2–6 build on it.

**Branch:** `feature/phase01-step1-bootstrap`

**Deploys:** GitHub repository settings (branch protection, merge
policy) and the `ci.yml` and `dependabot.yml` workflows → live on
merge; local Docker Compose services → maintainer's machine. Nothing
else.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** This step is cross-cutting repository work —
many small files, `gh` API calls, CI YAML, and hook wiring that must be
correct on the first merge because every later commit depends on it —
so PRIMARY `coding` with SECONDARY `agentic` at High overall complexity
(cross-cutting scope), which requires an S-tier coder; Claude Opus 5
is rated S in both categories (Terminal-Bench 2.1 89.1) and supersedes
Opus 4.8 in the same series. The Platform is Claude Code, funded by
the flat claude.ai Max subscription, so the marginal cost is zero and
the flat-funding gate is open: Effort sits at `Max`, the top rung Opus
5 exposes, because holding effort down saves nothing here, and
Thinking is `On` because the branch-protection and CI configuration
reward deliberate reasoning over speed. Backup: GPT-5.3 Codex on Codex
(ChatGPT Plus; Intelligence High), the cost-efficient S-tier coding
and agentic pick from a different provider. Conversation is New per
phase-boundary hygiene.

```xml
<task>
  <lifecycle>
    This step MUST follow all six
    stages, in order. Stages 1, 3,
    4, 5, 6 are AS BINDING as any
    `<requirement>` below. Do not
    emit the Stage 6 completion
    line until the PR is merged and
    every acceptance criterion for
    this step is affirmatively met.

    1. CREATE THE BRANCH. Before
       any Read / Edit / Bash, run
       `git checkout -b
       feature/phase01-step1-bootstrap`
       from a clean, up-to-date
       `main`. If the Worktree rule
       applies, use `git fetch
       origin && git worktree add
       -b <branch> .worktrees/<slug>
       origin/main` instead, then
       bootstrap the worktree.

    2. WORK ON THE BRANCH. All
       commits land here. `main`
       is protected with
       `enforce_admins: true` —
       direct pushes will be
       rejected.

    3. OPEN THE PR. `gh pr create
       --base main --head <branch>`
       with a Conventional Commits
       title and a body that
       references this roadmap step
       and its acceptance criteria.
       One PR per step.

    4. WAIT FOR GREEN CHECKS, THEN
       SQUASH-MERGE. Every required
       check must pass. If the PR
       falls behind main, refresh
       with `gh pr update-branch
       --rebase` — never merge main
       into the branch
       (`required_linear_history:
       true`). Once green:
       `gh pr merge <PR> --squash
       --delete-branch`. This
       step's `**Deploys:**` line
       names surfaces: run the
       Deployed & verified check
       before declaring the step
       complete.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree,
       `git worktree remove <path>`
       FIRST.

    6. DECLARE COMPLETION, THEN
       NEW CONVERSATION. Update
       docs/ROADMAP.md. Once the
       PR is merged and every
       acceptance criterion for
       this step is affirmatively
       met, end your final response
       with the verbatim line
       "Step 1 is complete. You can
       now move on to Step 2." Put
       any caveats or ideas in a
       short "Follow-ups
       (non-blocking)" note AFTER
       that line. If any criterion
       is unmet, state plainly that
       the step is NOT complete,
       name what failed, and omit
       the completion line. The
       operator then closes this
       session and opens a fresh
       one for Step 2.
  </lifecycle>

  <security>
    Security is a gate on THIS
    step, not a later phase. It is
    AS BINDING as any
    `<requirement>` below. Before
    the Stage-2 commit, this
    step's work MUST pass the
    local, fail-closed security
    gate — the SAME gate this step
    wires into the pre-commit hook
    and CI:

    1. SECRET / PII SCAN. No
       credentials, API keys,
       tokens, or real person
       identifiers in the diff
       (`detect-secrets`). Secrets
       come from the environment;
       `.env` is untracked;
       `.env.example` carries
       placeholders only.

    2. SAST. No new injection,
       unsafe deserialization,
       weak crypto, path
       traversal, or unsafe-eval
       pattern (`bandit`).
       Suppress a finding ONLY
       with an inline
       justification comment.

    3. DEPENDENCY AUDIT. Every new
       or bumped dependency passes
       `pip-audit`; no
       known-vulnerable, yanked,
       or typo-squatted package.

    4. SENSITIVE-DATA REVIEW.
       Workflow files are a trust
       boundary: every action is
       pinned to a full commit
       SHA, every workflow
       declares minimum
       `permissions:`, and no
       secret is exposed to a
       workflow triggered by an
       untrusted pull request.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 1.
    Step 1: repository bootstrap,
    command interface, security
    gate, and CI.

    Current state (scaffold):

    - `pyproject.toml` (uv, src
      layout, `dev` and `planning`
      groups, `[tool.poe.tasks]`),
      `Makefile` shim, `uv.lock`,
      `.python-version` (3.13),
      `.gitignore`,
      `.gitattributes`,
      `.editorconfig`, `README.md`,
      `AGENTS.md`, `CLAUDE.md`,
      `ROADMAP.md`,
      `docs/ROADMAP.md`,
      `docs/DATA_SOURCES.md`,
      `docs/brief/`,
      `src/judgemetrics/__init__.py`,
      `tests/test_smoke.py`.
    - The operator has pushed the
      scaffold as the initial
      commit on `main` to
      `nathanramoscfa/judge-metrics`
      and `gh auth status` is
      logged in.
    - No `.github/`, no
      `pre-commit`, no compose, no
      LICENSE.

    Files to read (every file
    before drafting):
    - ROADMAP.md (§5 command
      interface, branch, security,
      release, and operations
      strategy — the rules this
      step enforces).
    - docs/brief/judgemetrics-
      master-project-specification.xml
      (`<security>`,
      `<ci_pipeline>`,
      `<local_development_commands>`).
    - AGENTS.md (conventions:
      filepath comment, 80-column
      prose, LF, definition of
      done).
    - pyproject.toml, Makefile
      (tasks and targets to
      extend).
    - .gitignore, .gitattributes,
      .editorconfig (already
      correct; do not weaken).
    - docs/phase01-roadmap.md
      (this file; Step 1 only).
  </context>

  <goal>
    Ship the governance chassis:
    LICENSE and community files;
    `.pre-commit-config.yaml` with
    the four-check gate; `ci.yml`
    with python, security, and an
    aggregate `test` job;
    `dependabot.yml`;
    `docker-compose.yml` with
    PostgreSQL 17 (pg_trgm, three
    roles) and MinIO;
    `.env.example`; `up` and
    `down` targets; branch
    protection and merge settings
    applied through `gh`; and
    `tests/unit/test_repo_hygiene.py`
    proving all of it. Move
    `tests/test_smoke.py` to
    `tests/unit/test_smoke.py`.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Add `LICENSE` (Apache
      License 2.0 text) and set
      `license = "Apache-2.0"` and
      `license-files = ["LICENSE"]`
      in `pyproject.toml`. State
      in the PR body that the
      operator confirms the license
      choice; do not add a NOTICE
      file (no third-party
      attributions yet).
    </requirement>

    <requirement>
      Add `CONTRIBUTING.md` (branch
      naming, the six-stage step
      lifecycle in brief, how to
      install and run the gate,
      the command interface, how
      to run tests and compose),
      `SECURITY.md` (private
      disclosure via GitHub
      security advisories; no
      public issues for
      vulnerabilities),
      `CODE_OF_CONDUCT.md`
      (Contributor Covenant 2.1),
      `.github/ISSUE_TEMPLATE/
      bug_report.md`,
      `feature_request.md`,
      `data_source_issue.md`
      (fields: source id, dataset,
      what is wrong, evidence URL),
      and
      `.github/PULL_REQUEST_TEMPLATE.md`
      with sections: Roadmap step,
      Summary, Test plan,
      Screenshots (UI), Breaking
      changes, Rollback plan,
      Security gate (checkbox per
      check), Definition of done
      (checkbox per item from
      AGENTS.md), Issues opened.
    </requirement>

    <requirement>
      `uv add --group dev
      pre-commit bandit pip-audit
      detect-secrets`. Add
      `.pre-commit-config.yaml`
      using LOCAL hooks that call
      `uv run <tool>` so the gate
      runs the locked versions:
      `ruff check`, `ruff format
      --check`, `mypy`
      (pass_filenames: false),
      `bandit -c pyproject.toml -r
      src`, `detect-secrets-hook
      --baseline .secrets.baseline`,
      and `pip-audit --strict` at
      `stages: [pre-push]` (run via
      `scripts/audit_deps.py`, which
      exports `uv.lock` with hashes
      and audits that — the editable
      project is not on PyPI, so a
      bare `pip-audit --strict` on
      the environment fails for the
      wrong reason). Include
      the upstream `pre-commit-hooks`
      repo pinned to a commit SHA
      for `trailing-whitespace`,
      `end-of-file-fixer`,
      `check-yaml`, `check-toml`,
      `check-added-large-files`.
      Generate `.secrets.baseline`
      with `detect-secrets scan`.
      Add `[tool.bandit]` to
      `pyproject.toml` (exclude
      tests). Document `uv run
      pre-commit install
      --hook-type pre-commit
      --hook-type pre-push` in
      CONTRIBUTING.md and run it.
      Add a `gate` poe task that
      runs `pre-commit run
      --all-files`.
    </requirement>

    <requirement>
      Add `.github/workflows/ci.yml`:
      triggers `push` (branches:
      main) and `pull_request`;
      top-level `permissions:
      contents: read`; concurrency
      group per ref with
      cancel-in-progress. Jobs on
      ubuntu-latest: `python`
      (checkout, astral-sh/setup-uv,
      `uv sync --frozen`, `uv run
      poe lint`, `uv run poe
      fmt-check`, `uv run poe
      typecheck`, `uv run pytest
      --cov`), with a `postgres:17`
      service container (health
      check; env from job-level
      placeholders; used from Step
      2 on) and `JUDGEMETRICS_*`
      env pointing at it;
      `security` (gitleaks action,
      `uv run bandit -c
      pyproject.toml -r src`, `uv
      run python
      scripts/audit_deps.py`); and
      `test` (`needs: [python,
      security]`, `if: always()`,
      fails when any needed job did
      not succeed) as the single
      required status check. Every
      third-party action is pinned
      to a full 40-character commit
      SHA with a `# vX.Y.Z` comment.
    </requirement>

    <requirement>
      Add `.github/dependabot.yml`
      for `uv` (weekly) and
      `github-actions` (weekly);
      `npm` for `/web` is added in
      Step 5 and `docker` for
      `/infra/docker` in Step 2.
    </requirement>

    <requirement>
      Add `docker-compose.yml`:
      service `postgres` (image
      `postgres:17`, env
      `POSTGRES_USER`,
      `POSTGRES_PASSWORD`,
      `POSTGRES_DB` from `.env`,
      port 5432, named volume,
      healthcheck `pg_isready`,
      and `./infra/docker/postgres/
      01-extensions.sql` plus
      `02-roles.sql` mounted into
      `/docker-entrypoint-initdb.d/`
      — the first runs `CREATE
      EXTENSION IF NOT EXISTS
      pg_trgm;`, the second creates
      the roles `judgemetrics_app`
      (read-only on public tables),
      `judgemetrics_ingest`
      (writer), and
      `judgemetrics_admin`, with
      passwords from `.env`);
      service `minio` (official
      image, ports 9000/9001, env
      `MINIO_ROOT_USER`,
      `MINIO_ROOT_PASSWORD`, named
      volume, healthcheck); service
      `minio-init` (runs once,
      creates bucket
      `judgemetrics-raw` with
      versioning enabled). Add
      `.env.example` with every
      variable the compose file and
      the Step 2 settings will read
      (`JUDGEMETRICS_ENV`,
      `JUDGEMETRICS_DATABASE_URL`,
      `JUDGEMETRICS_RAW_STORE_URL`,
      `JUDGEMETRICS_S3_ENDPOINT_URL`,
      `JUDGEMETRICS_S3_ACCESS_KEY_ID`,
      `JUDGEMETRICS_S3_SECRET_ACCESS_KEY`,
      `JUDGEMETRICS_LOG_FORMAT`,
      `POSTGRES_USER`,
      `POSTGRES_PASSWORD`,
      `POSTGRES_DB`,
      `JUDGEMETRICS_APP_DB_PASSWORD`,
      `JUDGEMETRICS_INGEST_DB_PASSWORD`,
      `JUDGEMETRICS_ADMIN_DB_PASSWORD`,
      `MINIO_ROOT_USER`,
      `MINIO_ROOT_PASSWORD`) using
      obvious placeholders such as
      `change-me`. Add poe tasks
      `up` (a sequence: `docker
      compose up -d --wait postgres
      minio`, then `docker compose
      run --rm minio-init` — `--wait`
      alone treats the cleanly exited
      one-shot job as a failure) and
      `down = "docker compose down"`
      and the matching Makefile
      targets.
      Verify `uv run poe up`
      reaches healthy, `SELECT
      extname FROM pg_extension`
      lists `pg_trgm`, and the
      three roles exist.
    </requirement>

    <requirement>
      Apply repository settings
      with `gh`: `gh repo edit
      --enable-squash-merge
      --enable-merge-commit=false
      --enable-rebase-merge=false
      --delete-branch-on-merge`;
      then `gh api -X PUT
      repos/{owner}/{repo}/branches/
      main/protection` with
      `required_status_checks:
      {strict: true, contexts:
      ["test"]}`, `enforce_admins:
      true`,
      `required_pull_request_reviews:
      null` (solo maintainer),
      `restrictions: null`,
      `required_linear_history:
      true`, `allow_force_pushes:
      false`, `allow_deletions:
      false`,
      `required_conversation_resolution:
      true`. Enable secret scanning
      and push protection on the
      repository. Record the exact
      commands in CONTRIBUTING.md
      under "Repository settings".
    </requirement>

    <requirement>
      Move `tests/test_smoke.py` to
      `tests/unit/test_smoke.py`
      and add
      `tests/unit/test_repo_hygiene.py`:
      - test_license_exists_and_is_apache.
      - test_community_files_exist.
      - test_env_example_has_only_placeholders
        (no value matches common
        secret shapes; every value
        is `change-me`, a URL with
        `change-me` credentials, or
        a non-secret constant).
      - test_precommit_config_lists_gate_checks
        (ruff, mypy, bandit,
        detect-secrets, pip-audit).
      - test_ci_actions_are_sha_pinned
        (every `uses:` matches
        `@[0-9a-f]{40}`).
      - test_ci_declares_least_privilege_permissions.
      - test_compose_defines_postgres_and_minio.
      - test_command_interface_targets_present
        (poe tasks and Makefile
        targets agree on up, down,
        check, test, lint,
        typecheck, gate).
      Update
      `[tool.pytest.ini_options]`
      `testpaths` and add markers
      `unit` and `integration`.
    </requirement>

    <requirement>
      Prove the gate: create a
      scratch file containing a
      synthetic secret (for
      example a fake AWS-style key
      that `detect-secrets`
      flags), attempt `git commit`,
      observe the hook reject it,
      delete the file. Describe the
      observation in the PR body;
      commit nothing from this
      exercise.
    </requirement>

    <requirement>
      Filepath comment: every new
      Python / YAML / Markdown /
      SQL file gets the
      repo-relative path as the
      first line where the file
      type accepts comments
      (Python: `# path`; YAML:
      `# path`; SQL: `-- path`;
      Markdown: `<!-- path -->`).
      `LICENSE` and JSON files are
      exempt.
    </requirement>
  </requirements>
</task>
```

### Step 1 acceptance criteria

- `LICENSE` (Apache-2.0), `CONTRIBUTING.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, the three issue templates, and the PR template
  exist; `pyproject.toml` declares the license.
- `uv run poe gate` passes on the merged tree, and the hook was
  observed to block a commit containing a planted synthetic secret
  (documented in the PR body).
- `ci.yml` runs `python`, `security`, and the aggregate `test` job on
  the PR; every action is SHA-pinned; `permissions: contents: read` is
  declared; the PR merged only after `test` was green.
- `uv run poe up` brings `postgres` and `minio` to healthy; `pg_trgm`
  is listed in `pg_extension`; the three database roles exist; the
  `judgemetrics-raw` bucket exists with versioning enabled;
  `uv run poe down` stops the services.
- `.env.example` documents every variable and contains placeholders
  only; no `.env` is tracked.
- `tests/unit/test_repo_hygiene.py` and `tests/unit/test_smoke.py`
  pass under `uv run poe test`.
- **Deployed & verified:** `gh api repos/{owner}/{repo}/branches/main/
  protection` reports `enforce_admins.enabled: true`,
  `required_linear_history.enabled: true`, and required context
  `test`; `gh repo view --json deleteBranchOnMerge,squashMergeAllowed,
  mergeCommitAllowed,rebaseMergeAllowed` reports `true, true, false,
  false`; a test push directly to `main` is rejected.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean,
  SAST clean, dependency audit clean — and the workflow files pin every
  action by SHA, declare least-privilege permissions, and expose no
  secret to pull-request triggers.

---

## Step 2 — Application Core, Canonical Schema, and the API Image

> **Goal:** Land the application chassis: `src/judgemetrics/config.py`
> (`pydantic-settings`, `JUDGEMETRICS_` prefix, `.env` loaded only when
> `JUDGEMETRICS_ENV=local`), `logging.py` (structlog JSON renderer, a
> request-id binder, and a scrubbing processor that drops or redacts
> sensitive keys), `main.py` with `create_app()` and request-id and
> access-log middleware, `api/routes/health.py` serving `/api/v1/health`
> (status, package version, git SHA, Alembic head) and `/api/v1/ready`
> (200 when the database answers at the expected head, 503 otherwise),
> `db/base.py` (declarative base with a naming convention, UUID
> primary-key and timestamp mixins), `db/session.py` (engine and session
> factory from settings, FastAPI dependency), the `db/models/` package
> with all twenty-three entities of the brief's canonical data model,
> `normalization/names.py`, the Alembic environment and reversible
> baseline migration `0001_baseline` (every table, enum, and index,
> `pg_trgm`, and a complete `downgrade()`), `cli.py` (Typer:
> `db upgrade|downgrade|current`, `serve`, `ingest list-sources`
> placeholder) replacing the placeholder `main()`,
> `infra/docker/api.Dockerfile` with a compose `api` service, the CI
> `container` job that builds and scans the image, and the `migrate`
> and `dev-api` targets; with unit tests for settings, name
> normalization, and scrubbing, and integration tests for the migration
> round-trip, model constraints, and both health endpoints. Steps 3–5
> layer the connector, routes, and web on this chassis.

**Branch:** `feature/phase01-step2-app-core`

**Deploys:** nothing beyond merge — the local database schema is
applied by the operator with `uv run poe migrate` against the Compose
PostgreSQL; the `container` CI job is live on merge.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** The step is correctness-sensitive, cross-file
implementation with a design component — twenty-three tables and their
constraints are the contract every later phase writes against, and the
baseline must downgrade cleanly — so PRIMARY `coding` with SECONDARY
`planning` at High overall complexity, requiring an S-tier coder;
Claude Opus 5 is rated S in coding and S in planning (Artificial
Analysis Intelligence Index 60.7 at max) and supersedes Opus 4.8. The
Platform is Claude Code on the flat claude.ai Max subscription; with
the flat-funding gate open, Effort is `Max` (the top rung Opus 5
supports) and Thinking is `On`, since schema and migration decisions
benefit from extended reasoning and nothing is saved by holding effort
down. Backup: GPT-5.6 Sol on Codex (ChatGPT Plus; Intelligence Extra
High), S-tier in coding and planning from a different provider.
Conversation is New per phase-boundary hygiene.

```xml
<task>
  <lifecycle>
    This step MUST follow all six
    stages, in order. Stages 1, 3,
    4, 5, 6 are AS BINDING as any
    `<requirement>` below. Do not
    emit the Stage 6 completion
    line until the PR is merged and
    every acceptance criterion for
    this step is affirmatively met.

    1. CREATE THE BRANCH. Before
       any Read / Edit / Bash, run
       `git checkout -b
       feature/phase01-step2-app-core`
       from a clean, up-to-date
       `main`. If the Worktree rule
       applies, use `git fetch
       origin && git worktree add
       -b <branch> .worktrees/<slug>
       origin/main` instead, then
       bootstrap the worktree.

    2. WORK ON THE BRANCH. All
       commits land here. `main`
       is protected with
       `enforce_admins: true` —
       direct pushes will be
       rejected.

    3. OPEN THE PR. `gh pr create
       --base main --head <branch>`
       with a Conventional Commits
       title and a body that
       references this roadmap step
       and its acceptance criteria.
       One PR per step.

    4. WAIT FOR GREEN CHECKS, THEN
       SQUASH-MERGE. Every required
       check must pass. If the PR
       falls behind main, refresh
       with `gh pr update-branch
       --rebase` — never merge main
       into the branch
       (`required_linear_history:
       true`). Once green:
       `gh pr merge <PR> --squash
       --delete-branch`. This
       step's `**Deploys:**` line
       is "nothing beyond merge";
       apply the migration locally
       and confirm the acceptance
       criteria before Stage 6.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree,
       `git worktree remove <path>`
       FIRST.

    6. DECLARE COMPLETION, THEN
       NEW CONVERSATION. Update
       docs/ROADMAP.md. Once the
       PR is merged and every
       acceptance criterion for
       this step is affirmatively
       met, end your final response
       with the verbatim line
       "Step 2 is complete. You can
       now move on to Step 3." Put
       any caveats or ideas in a
       short "Follow-ups
       (non-blocking)" note AFTER
       that line. If any criterion
       is unmet, state plainly that
       the step is NOT complete,
       name what failed, and omit
       the completion line. The
       operator then closes this
       session and opens a fresh
       one for Step 3.
  </lifecycle>

  <security>
    Security is a gate on THIS
    step, not a later phase. It is
    AS BINDING as any
    `<requirement>` below. Before
    the Stage-2 commit, this
    step's work MUST pass the
    local, fail-closed security
    gate — the SAME gate wired
    into the pre-commit hook and
    re-run in CI:

    1. SECRET / PII SCAN. No
       credentials, API keys,
       tokens, or real person
       identifiers in the diff
       (`detect-secrets`). The
       database URL and S3
       credentials are read from
       the environment only; test
       fixtures use obvious
       placeholders.

    2. SAST. No new injection,
       unsafe deserialization,
       weak crypto, path
       traversal, or unsafe-eval
       pattern (`bandit`). SQL is
       issued only through
       SQLAlchemy constructs;
       `text()` with untrusted
       input is forbidden.

    3. DEPENDENCY AUDIT. Every new
       dependency (fastapi,
       uvicorn, sqlalchemy,
       alembic, psycopg, pydantic,
       pydantic-settings, typer,
       structlog, httpx) passes
       `pip-audit --strict`; the
       API image passes the CI
       vulnerability scan with no
       HIGH or CRITICAL findings.

    4. SENSITIVE-DATA REVIEW. The
       logging scrubber is tested;
       `/health` reveals version,
       git SHA, and migration head
       only — never configuration
       values, hostnames, or
       credentials; the image runs
       as a non-root user and
       contains no `.env`.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 1.
    Step 2: application core,
    canonical schema, and the API
    image.

    Current state (as of Step 1):

    - Governance chassis merged:
      pre-commit gate, `ci.yml`
      with a `postgres:17` service
      and the aggregate `test`
      check, `docker-compose.yml`
      with pg_trgm and the three
      database roles,
      `.env.example`, `up`/`down`
      targets, branch protection.
    - `src/judgemetrics/__init__.py`
      still holds the placeholder
      `main()`; the `judgemetrics`
      console script points at it.
    - No settings, logging, app,
      models, migrations, CLI,
      Dockerfile, or container job.

    Files to read (every file
    before drafting):
    - docs/brief/judgemetrics-
      master-project-specification.xml
      (`<canonical_data_model>` —
      every entity and field name
      is fixed; `<performance_
      strategy>` for indexes;
      `<security>`).
    - ROADMAP.md §3 and §4 Phase 1
      (architecture; 1.2 scope)
      and §5 "Security & privacy
      strategy" (data
      classification, logging
      rules, database roles).
    - AGENTS.md (conventions).
    - docs/DATA_SOURCES.md (`fjc`
      entry — the external ids the
      schema must index).
    - pyproject.toml, Makefile,
      .env.example,
      docker-compose.yml,
      infra/docker/postgres/*.sql,
      .github/workflows/ci.yml
      (environment variables, the
      CI database, the job to
      extend).
    - src/judgemetrics/__init__.py,
      tests/unit/test_smoke.py.
  </context>

  <goal>
    Ship settings, JSON logging
    with scrubbing, the FastAPI
    application factory with
    `/api/v1/health` and
    `/api/v1/ready`, SQLAlchemy 2
    models for all twenty-three
    canonical entities, the
    reversible Alembic baseline
    migration, the Typer CLI
    (`db`, `serve`, `ingest
    list-sources`), the API
    container image with its
    compose service and CI build
    and scan, and the `migrate`
    and `dev-api` targets, with
    unit and integration tests, so
    that `uv run poe migrate`
    creates the whole schema and
    `uv run poe dev-api` answers
    both health endpoints.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      `uv add fastapi
      "uvicorn[standard]"
      "sqlalchemy>=2"
      alembic "psycopg[binary]"
      pydantic pydantic-settings
      typer structlog` and `uv add
      --group dev httpx` (for the
      TestClient). Keep `uv.lock`
      committed.
    </requirement>

    <requirement>
      `src/judgemetrics/config.py`:
      `Settings(BaseSettings)` with
      `env_prefix="JUDGEMETRICS_"`,
      fields `env` (local | test |
      production, default local),
      `database_url`
      (`postgresql+psycopg://…`,
      the app role by default),
      `raw_store_url` (`file://…`
      or `s3://bucket`),
      `s3_endpoint_url`,
      `s3_access_key_id`,
      `s3_secret_access_key`
      (`SecretStr`), `log_format`
      (json | console), `git_sha`
      (optional; falls back to `git
      rev-parse HEAD` when
      available, else "unknown").
      `.env` is read only when
      `env == local`. A cached
      `get_settings()` accessor.
    </requirement>

    <requirement>
      `src/judgemetrics/logging.py`:
      `configure_logging(settings)`
      using structlog with ISO
      timestamps, level, logger,
      event, and bound context; a
      `scrub_sensitive` processor
      that replaces values for keys
      matching a documented
      denylist (`password`,
      `passwd`, `secret`, `token`,
      `authorization`, `api_key`,
      `access_key`, `cookie`,
      `person_id`,
      `case_participant_id`,
      `identifier_value`,
      `encrypted_value`,
      `requester_contact`) with
      `"[redacted]"`, recursively
      through dicts and lists; JSON
      renderer when `log_format ==
      json`, console renderer
      otherwise. Unit test the
      scrubber.
    </requirement>

    <requirement>
      `src/judgemetrics/main.py`:
      `create_app(settings=None)`
      returning a FastAPI app with
      title "JudgeMetrics API",
      `openapi_url=
      "/api/v1/openapi.json"`,
      request-id middleware (reads
      or generates `X-Request-ID`,
      binds it to the log context,
      echoes it on the response),
      an access-log middleware, and
      the health router mounted at
      `/api/v1`. Module-level `app
      = create_app()` for uvicorn.
    </requirement>

    <requirement>
      `src/judgemetrics/api/routes/
      health.py`: `GET /api/v1/
      health` → `{"status": "ok",
      "version": <package
      version>, "git_sha": <sha>,
      "alembic_head": <head
      revision from the migration
      scripts>}` without touching
      the database; `GET /api/v1/
      ready` → 200 `{"status":
      "ready", "database": "ok",
      "alembic_current": <applied
      revision>}` when `SELECT 1`
      succeeds and the applied
      revision equals the head,
      503 with a reason otherwise.
    </requirement>

    <requirement>
      `src/judgemetrics/db/base.py`:
      `Base(DeclarativeBase)` with
      the SQLAlchemy naming
      convention for constraints
      and indexes; `UUIDPrimaryKey`
      mixin (`id: uuid, default
      uuid4, server_default
      gen_random_uuid()`);
      `Timestamps` mixin
      (`created_at`, `updated_at`,
      timezone-aware, server
      defaults). `db/session.py`:
      engine from
      `settings.database_url`
      (pool_pre_ping), a
      `SessionLocal` factory, and a
      `get_session()` FastAPI
      dependency that closes the
      session.
    </requirement>

    <requirement>
      The `src/judgemetrics/db/
      models/` package implements
      every entity of the brief's
      `<canonical_data_model>`
      with the brief's field names,
      grouped as: `reference.py`
      (`Jurisdiction`, `Court`,
      `Judge`, `JudgeService`),
      `provenance.py` (`Source`,
      `SourceRecord`, `IngestRun`,
      `DataQualityIssue`),
      `persons.py` (`Person`,
      `PersonIdentifier`,
      `JusticeEvent`), `cases.py`
      (`Case` on table
      `court_case`, `CaseParty`,
      `JudgeAssignment`, `Charge`,
      `CourtEvent`, `Decision`,
      `PretrialRelease`,
      `Sentence`), `resolution.py`
      (`EntityResolutionCandidate`),
      `metrics.py`
      (`MetricDefinition`,
      `MetricObservation`), and
      `corrections.py`
      (`CorrectionRequest`).
      Enumerations as the brief
      lists them (jurisdiction
      type; actor types judge,
      prosecutor, defense, jury,
      clerk, law_enforcement,
      legislature_or_mandatory_rule,
      appellate_court, unknown;
      resolution decision matched,
      rejected, review; subject
      type judge, court,
      jurisdiction; run status;
      issue severity and status;
      correction status). Every
      `source_record_id` is a
      foreign key to
      `source_record`. `Person`
      carries `public_person_key`
      unique; `PersonIdentifier`
      carries `value_hash` and
      nullable `encrypted_value`;
      `CorrectionRequest.requester_contact`
      is stored encrypted (bytes)
      with a documented
      application-level key from
      settings. Add `__init__.py`
      exporting every model so
      Alembic autogenerate sees
      them.
    </requirement>

    <requirement>
      `src/judgemetrics/
      normalization/names.py`:
      `normalize_person_name(raw)
      -> str` (Unicode NFKD, strip
      diacritics, casefold, remove
      punctuation, collapse
      whitespace),
      `canonical_person_name(first,
      middle, last, suffix) ->
      str`, and
      `normalize_case_number(raw,
      court_type) -> str`
      (uppercase, strip whitespace
      and separators, keep the
      year and sequence). Unit
      tests with accented,
      hyphenated, and suffixed
      names and with several case
      number formats.
    </requirement>

    <requirement>
      `alembic.ini` at the repo
      root and `alembic/env.py`
      reading the URL from
      `get_settings()` (never from
      the ini) and using the admin
      role for migrations.
      `alembic/versions/
      0001_baseline.py`: `CREATE
      EXTENSION IF NOT EXISTS
      pg_trgm`, all twenty-three
      tables, the enums, indexes
      on every `court_id`,
      `judge_id`, `person_id`,
      `case_id`, `source_record_id`
      foreign key, on
      `court_case.case_number_normalized`
      (unique with `court_id`), on
      `court_event.event_at`,
      `decision.decision_at`,
      `justice_event.event_at`, on
      `metric_observation
      (metric_definition_id,
      subject_type, subject_id,
      period_start)`, GIN trigram
      indexes on
      `judge.normalized_name` and
      `court.canonical_name`
      (`gin_trgm_ops`), GIN indexes
      on `judge.external_ids` and
      `court.external_ids`, a
      unique expression index on
      `(judge.external_ids->>
      'fjc_nid')`, grants that give
      `judgemetrics_app` SELECT on
      every table except
      `person_identifier` and
      `correction_request`, and a
      complete `downgrade()`.
      Integration tests: upgrade →
      downgrade → upgrade leaves
      the schema identical
      (compare `inspect()` table,
      index, and enum names);
      inserting a `Decision`
      without a `source_record_id`
      fails; the app role cannot
      read `person_identifier`.
    </requirement>

    <requirement>
      `src/judgemetrics/cli.py`:
      Typer app `judgemetrics`
      with groups `db` (`upgrade
      [--revision head]`,
      `downgrade <revision>`,
      `current`), `serve`
      (`--host`, `--port`,
      `--reload`; runs uvicorn on
      `judgemetrics.main:app`), and
      `ingest` (`list-sources`
      printing the registered
      sources — empty until Step
      3). Point
      `[project.scripts]
      judgemetrics` at
      `judgemetrics.cli:main` and
      remove the placeholder from
      `__init__.py` (keep
      `__version__`). Add poe tasks
      `migrate = "judgemetrics db
      upgrade"` and `dev-api =
      "judgemetrics serve
      --reload"` and the matching
      Makefile targets. Update
      `tests/unit/test_smoke.py`
      to invoke the CLI with
      Typer's `CliRunner`
      (`--version` prints the
      package version).
    </requirement>

    <requirement>
      `infra/docker/api.Dockerfile`:
      multi-stage build on the
      official `python:3.13-slim`
      base with uv (`uv sync
      --frozen --no-dev --no-group
      planning`), a non-root user,
      no `.env` copied, `HEALTHCHECK`
      against `/api/v1/health`, and
      `CMD ["judgemetrics", "serve",
      "--host", "0.0.0.0"]`. Add a
      compose service `api` under
      profile `app` (build from the
      Dockerfile, env from `.env`,
      depends on `postgres`
      healthy, port 8000). Add a CI
      job `container` (checkout,
      `docker build -f
      infra/docker/api.Dockerfile
      -t judgemetrics-api:ci .`,
      then an image vulnerability
      scanner action pinned by SHA
      that fails on HIGH or
      CRITICAL findings) and add
      it to the `test` job's
      `needs`. Add `docker` for
      `/infra/docker` to
      `dependabot.yml`.
    </requirement>

    <requirement>
      Tests: `tests/unit/
      test_settings.py`
      (prefix, SecretStr, env
      gating of `.env`),
      `tests/unit/test_logging.py`
      (scrubber),
      `tests/unit/test_names.py`,
      `tests/integration/
      test_migrations.py`
      (round-trip, constraints,
      grants; marker
      `integration`; skipped with
      a clear reason when
      `JUDGEMETRICS_DATABASE_URL`
      is unset), `tests/integration/
      test_health.py` (TestClient:
      `/health` fields; `/ready`
      200 with the CI/Compose
      database and 503 with an
      unreachable URL).
      `tests/conftest.py` provides
      a `settings` fixture and a
      per-test transactional
      session. CI's `python` job
      exports
      `JUDGEMETRICS_DATABASE_URL`
      for the service container
      and creates the three roles.
    </requirement>

    <requirement>
      Update `.env.example` for any
      new variable; update
      `README.md` "Quick start"
      with `cp .env.example .env`,
      `uv run poe up`, `uv run poe
      migrate`, `uv run poe
      dev-api`; update
      `docs/ROADMAP.md` completed
      items.
    </requirement>

    <requirement>
      Filepath comment: every new
      file gets the repo-relative
      path as the first line
      (Dockerfile: `# path`).
    </requirement>
  </requirements>
</task>
```

### Step 2 acceptance criteria

- `uv run poe migrate` against the Compose database creates all
  twenty-three tables, the enums, the indexes, and the grants;
  `uv run judgemetrics db current` prints the baseline revision; the
  migration round-trip integration test passes in CI against the
  `postgres:17` service.
- `GET /api/v1/health` returns the package version, a 40-character git
  SHA (or `unknown` outside a checkout), and the Alembic head;
  `GET /api/v1/ready` returns 200 with the database up and 503 with it
  unreachable (both tested).
- The logging scrubber redacts every denylisted key recursively (unit
  test) and `JUDGEMETRICS_LOG_FORMAT=json` produces one JSON object per
  line with `request_id` bound on request logs.
- The app role cannot read `person_identifier` or
  `correction_request` (integration test).
- `uv run judgemetrics --version` prints the package version;
  `judgemetrics ingest list-sources` prints an empty registry.
- The `container` CI job builds the API image and the scan reports no
  HIGH or CRITICAL findings; `docker compose --profile app up` serves
  `/api/v1/health` from the container.
- `uv run poe check` and CI are green.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean,
  SAST clean, dependency audit clean for every added package, image
  scan clean — and `/api/v1/health` exposes no configuration value,
  hostname, or credential (asserted in `test_health.py`).

---

## Step 3 — Ingest Framework and the FJC Connector

> **Goal:** Land the ingest chassis and its first real connector:
> `src/judgemetrics/ingest/base.py` (`SourceArtifact`, `RawArtifact`,
> `ValidationResult`, `SourceRecordDraft`, the `CanonicalRecord` union,
> and the `SourceConnector` protocol exactly as the brief specifies),
> `ingest/store.py` (`RawObjectStore` protocol with content-addressed,
> immutable `FilesystemRawObjectStore` and `S3RawObjectStore` backends),
> `ingest/registry.py`, `ingest/runner.py` (the fourteen-step pipeline:
> discover, retrieve, hash, store immutably, create `source_record`,
> parse, schema-validate, normalize, deduplicate, resolve, run
> data-quality checks, publish canonical rows, recompute affected
> metrics — a no-op hook until Phase 3 — and record lineage and run
> statistics, idempotent on rerun), `ingest/fjc/` (`connector.py`,
> `parse.py`, `normalize.py`, `sources.py`, `schema.py`) loading
> `judges.csv` and `federal-judicial-service.csv` into `Judge`,
> `JudgeService`, `Court`, and `Jurisdiction` rows keyed on the FJC node
> id, `quality/checks.py` for service-date validity and overlap
> detection, the `judgemetrics ingest run <source>` and `ingest runs`
> commands with the `ingest-fjc` target, `docs/ARCHITECTURE.md`,
> `docs/DATA_MODEL.md`, `data/README.md`, and an updated `fjc` entry in
> `docs/DATA_SOURCES.md` recording the verified headers; with
> fixture-driven unit tests and an end-to-end integration test proving
> idempotency. Steps 4 and 5 read what this step publishes; Phase 2's
> synthetic connector reuses everything here.

**Branch:** `feature/phase01-step3-fjc-ingest`

**Deploys:** nothing beyond merge — the operator runs
`uv run poe ingest-fjc` locally against the Compose services.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Fable 5.1                      |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** This is the phase's ceiling-class step: it
designs the connector protocol, the immutable store, and the idempotent
runner that every later source (the synthetic generator, Cook County,
Florida, CourtListener, PACER) must fit, while simultaneously mapping a
live external dataset whose headers are read at fetch time — PRIMARY
`coding`, SECONDARY `planning`, High complexity with novel
problem-solving and cross-file chain-of-thought (the conditions that
push the selector to its Extra High and Max rungs). Fable 5.1 is rated
S in coding and S in planning (HLE 59.1% and Terminal-Bench 2.1 91.4,
both at max) and supersedes Fable 5; under the operator's balanced
posture it is reserved for exactly this kind of step, while Opus 5
(also S/S) takes the standard implementation steps because Fable draws
the Max budget down at about twice Opus's rate. The Platform is Claude
Code on the flat claude.ai Max subscription, so the flat-funding gate is
open: Effort `Max`, Thinking `On`. Backup: GPT-5.6 Sol on Codex
(ChatGPT Plus; Intelligence Extra High), S-tier in coding and planning
from a different provider. Conversation is New per phase-boundary
hygiene.

```xml
<task>
  <lifecycle>
    This step MUST follow all six
    stages, in order. Stages 1, 3,
    4, 5, 6 are AS BINDING as any
    `<requirement>` below. Do not
    emit the Stage 6 completion
    line until the PR is merged and
    every acceptance criterion for
    this step is affirmatively met.

    1. CREATE THE BRANCH. Before
       any Read / Edit / Bash, run
       `git checkout -b
       feature/phase01-step3-fjc-ingest`
       from a clean, up-to-date
       `main`. If the Worktree rule
       applies, use `git fetch
       origin && git worktree add
       -b <branch> .worktrees/<slug>
       origin/main` instead, then
       bootstrap the worktree.

    2. WORK ON THE BRANCH. All
       commits land here. `main`
       is protected with
       `enforce_admins: true` —
       direct pushes will be
       rejected.

    3. OPEN THE PR. `gh pr create
       --base main --head <branch>`
       with a Conventional Commits
       title and a body that
       references this roadmap step
       and its acceptance criteria.
       One PR per step.

    4. WAIT FOR GREEN CHECKS, THEN
       SQUASH-MERGE. Every required
       check must pass. If the PR
       falls behind main, refresh
       with `gh pr update-branch
       --rebase` — never merge main
       into the branch
       (`required_linear_history:
       true`). Once green:
       `gh pr merge <PR> --squash
       --delete-branch`. This
       step's `**Deploys:**` line
       is "nothing beyond merge";
       run the local ingest and
       confirm the acceptance
       criteria before Stage 6.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree,
       `git worktree remove <path>`
       FIRST.

    6. DECLARE COMPLETION, THEN
       NEW CONVERSATION. Update
       docs/ROADMAP.md (completed
       items; resolve open
       question 1 with the
       verified headers). Once the
       PR is merged and every
       acceptance criterion for
       this step is affirmatively
       met, end your final response
       with the verbatim line
       "Step 3 is complete. You can
       now move on to Step 4." Put
       any caveats or ideas in a
       short "Follow-ups
       (non-blocking)" note AFTER
       that line. If any criterion
       is unmet, state plainly that
       the step is NOT complete,
       name what failed, and omit
       the completion line. The
       operator then closes this
       session and opens a fresh
       one for Step 4.
  </lifecycle>

  <security>
    Security is a gate on THIS
    step, not a later phase. It is
    AS BINDING as any
    `<requirement>` below. Before
    the Stage-2 commit, this
    step's work MUST pass the
    local, fail-closed security
    gate — the SAME gate wired
    into the pre-commit hook and
    re-run in CI:

    1. SECRET / PII SCAN. No
       credentials or tokens in
       the diff (`detect-secrets`).
       S3 credentials come only
       from settings; fixture CSVs
       contain public FJC rows and
       nothing else.

    2. SAST. No new injection,
       unsafe deserialization,
       weak crypto, path
       traversal, or unsafe-eval
       pattern (`bandit`). Raw
       object keys are derived from
       the sha256, never from
       source-supplied file names;
       downloads enforce timeouts,
       size caps, and HTTPS.

    3. DEPENDENCY AUDIT. Every new
       dependency (httpx, polars,
       boto3 or the chosen S3
       client) passes `pip-audit
       --strict`; the image scan
       stays clean.

    4. SENSITIVE-DATA REVIEW. The
       FJC `demographics.csv` is
       NOT fetched; only judge
       identity and service files
       are ingested. Logs carry
       counts and ids, never raw
       rows. The runner writes with
       the ingest role, never the
       app role.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 1.
    Step 3: ingest framework and
    the FJC connector.

    Current state (as of Step 2):

    - Settings, JSON logging with
      scrubbing, `create_app()`,
      health endpoints, all
      twenty-three canonical
      models, the Alembic baseline,
      the Typer CLI (`db`, `serve`,
      `ingest list-sources`), the
      API image, and the `migrate`
      and `dev-api` targets are
      merged.
    - No connector, store, or
      runner exists; the `ingest`
      registry is empty.
    - `docs/DATA_SOURCES.md` `fjc`
      entry lists the export files
      and the `nid` key; exact
      headers are unrecorded
      (docs/ROADMAP.md open
      question 1).

    Files to read (every file
    before drafting):
    - docs/brief/judgemetrics-
      master-project-specification.xml
      (`<ingestion_framework>`:
      connector interface, the
      fourteen pipeline steps,
      idempotency, incremental
      updates; `<data_quality>`;
      `<agent_working_rules>` on
      never overwriting raw
      artifacts).
    - ROADMAP.md §3, §4 Phase 1.3.
    - docs/DATA_SOURCES.md (`fjc`
      entry).
    - src/judgemetrics/config.py,
      db/models/reference.py,
      db/models/provenance.py,
      db/session.py, cli.py,
      normalization/names.py.
    - alembic/versions/
      0001_baseline.py (constraints
      the publish step must
      respect).
    - tests/conftest.py.
  </context>

  <goal>
    Ship the connector protocol,
    the immutable raw object store
    with filesystem and S3
    backends, the idempotent
    pipeline runner, and the FJC
    connector so that `uv run poe
    ingest-fjc` populates judges,
    service records, courts, and
    the federal jurisdiction with
    full provenance and
    data-quality issues, and a
    second run creates zero new
    canonical rows.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      `uv add httpx polars boto3`
      (or `obstore` if preferred;
      justify in the PR). Keep
      `uv.lock` committed.
    </requirement>

    <requirement>
      `src/judgemetrics/ingest/
      base.py`: frozen dataclasses
      `SourceArtifact` (source_id,
      external_id, uri,
      content_type, metadata),
      `RawArtifact` (artifact,
      path_or_bytes, sha256,
      retrieved_at, size_bytes,
      response_headers subset),
      `ValidationResult` (ok,
      errors: list[str], warnings),
      `SourceRecordDraft`
      (external_record_id,
      effective_at, payload dict),
      and a `CanonicalRecord`
      union of small typed drafts
      (`JurisdictionDraft`,
      `CourtDraft`, `JudgeDraft`,
      `JudgeServiceDraft`, with the
      case-level drafts added in
      Phase 2) each carrying a
      `natural_key` property;
      `SourceConnector` Protocol
      with `source_id`,
      `parser_version`, `async
      discover()`, `async
      fetch(artifact)`,
      `validate_raw(raw)`,
      `parse(raw)`, and
      `normalize(record)` exactly
      as the brief's interface,
      plus an optional
      `checkpoint()` hook for
      incremental sources.
    </requirement>

    <requirement>
      `src/judgemetrics/ingest/
      store.py`: `RawObjectStore`
      Protocol (`put(data, key) ->
      ObjectRef`, `get(key) ->
      bytes`, `exists(key)`); keys
      are `<source_id>/<yyyy>/<mm>/
      <sha256><ext>`; `put` is
      immutable — writing a
      different payload to an
      existing key raises
      `ImmutableObjectError`, and
      writing the same payload is a
      no-op returning the existing
      ref. `FilesystemRawObjectStore`
      rooted at `raw_store_url`
      (`file://`), atomic
      write-then-rename;
      `S3RawObjectStore` for
      `s3://bucket` using the
      configured endpoint and keys
      (MinIO locally). Factory
      `open_raw_store(settings)`.
    </requirement>

    <requirement>
      `src/judgemetrics/ingest/
      registry.py`: `register(
      connector_cls)` decorator and
      `get_connector(source_id)`;
      `ingest list-sources` prints
      registered ids with parser
      versions.
      `src/judgemetrics/ingest/
      runner.py`: `run_ingest(
      source_id, *, session,
      store, settings,
      from_fixture=None,
      force=False) -> IngestRun`
      implementing the fourteen
      steps: discover; fetch (or
      read fixture files); sha256;
      store immutably; upsert
      `Source` by name; create
      `SourceRecord` per artifact
      unique on (source_id,
      external_record_id,
      raw_sha256) — an existing
      record short-circuits
      re-parsing unless `force`;
      parse; validate (errors abort
      the run with status failed);
      normalize into drafts;
      deduplicate drafts by
      natural_key within the run;
      resolve (Phase 1: exact
      external-id match for judges
      via `external_ids->>'fjc_nid'`,
      exact (canonical_name,
      court_type) for courts);
      run data-quality checks;
      publish with INSERT … ON
      CONFLICT upserts that update
      only changed columns and
      count created vs updated;
      call a `recompute_metrics`
      hook (no-op); write
      `IngestRun` counts,
      `code_version` (git SHA),
      `parser_version`, status.
      The whole publish is one
      transaction per run, using
      the ingest role.
    </requirement>

    <requirement>
      `src/judgemetrics/ingest/
      fjc/sources.py`: the export
      page URL and the two file
      URLs as constants with a
      comment citing
      docs/DATA_SOURCES.md.
      `fjc/connector.py`:
      `FjcConnector` (source_id
      "fjc", parser_version
      "2026.09.1"): `discover()`
      yields the two artifacts;
      `fetch()` downloads over
      HTTPS with httpx (30 s
      timeout, 3 retries with
      backoff, 200 MB size cap,
      `If-None-Match` /
      `If-Modified-Since` when the
      server supports them);
      `validate_raw()` checks
      non-empty CSV, header row
      present, and that every
      EXPECTED header exists —
      read the real headers on
      first fetch, record them in
      `fjc/schema.py` as the
      expected set, and fail
      loudly on any missing
      header; `parse()` uses
      Polars with all columns as
      strings; `normalize()` maps
      `judges.csv` rows to
      `JudgeDraft` (canonical name
      via `canonical_person_name`,
      normalized_name, external_ids
      {"fjc_nid", "fjc_jid"},
      status derived from the
      latest service termination
      or senior-status fields,
      metadata with birth year if
      present but NOT the
      demographics file) and
      `federal-judicial-service.csv`
      rows to `JudgeServiceDraft`
      (court resolved or created
      from the court-name and
      court-type columns;
      position_type from the
      appointment-title column;
      start_date = commission date,
      falling back to the recess
      appointment date; end_date =
      termination date; senior
      status date and termination
      reason in metadata) plus
      `CourtDraft` (court_type
      normalized to district |
      appeals | supreme | other;
      external_ids
      {"fjc_court_name"}) and a
      single `JurisdictionDraft`
      ("United States federal
      courts", type federal), with
      per-court `state_code` parsed
      from district-court names via
      `data/reference/us_states.csv`
      (null when unparseable).
    </requirement>

    <requirement>
      `src/judgemetrics/quality/
      checks.py`: check functions
      returning `DataQualityIssue`
      drafts: `service_dates_valid`
      (start ≤ end; error),
      `service_overlap` (same
      judge, same court,
      overlapping intervals;
      warning), `missing_start_date`
      (info), and
      `provenance_complete` (every
      published row references a
      source record with a hash;
      error). The runner persists
      issues with the run's
      source records.
    </requirement>

    <requirement>
      CLI: `judgemetrics ingest run
      <source_id> [--from-fixture
      DIR] [--force]` and
      `judgemetrics ingest runs
      [--source ID] [--limit N]`
      printing a table of runs
      with counts and status. Add
      the poe task `ingest-fjc =
      "judgemetrics ingest run
      fjc"` and the Makefile
      target.
    </requirement>

    <requirement>
      Fixtures: `tests/fixtures/
      fjc/judges.csv` and
      `federal-judicial-service.csv`
      as a small real excerpt (about
      25 judges and their service
      rows, including one judge
      with two courts and one with
      senior status), with
      `tests/fixtures/fjc/README.md`
      recording the retrieval date
      and the export page URL.
      Tests: `tests/unit/
      test_store.py` (immutability,
      same-payload no-op, key
      shape), `tests/unit/
      test_fjc_normalize.py`
      (name canonicalization,
      status derivation, court
      type mapping, state parsing),
      `tests/unit/
      test_quality_checks.py`,
      `tests/integration/
      test_fjc_ingest.py` (run from
      fixtures twice: first run
      creates N judges, M service
      rows, K courts; second run
      creates 0 and updates 0;
      every canonical row's
      `source_record_id` resolves
      to a record whose
      `raw_sha256` matches the
      fixture file; the two DQ
      issues planted in the fixture
      are persisted).
    </requirement>

    <requirement>
      Docs: `docs/ARCHITECTURE.md`
      (ingest pipeline diagram and
      the fourteen steps mapped to
      runner functions; raw-lake
      key scheme; idempotency
      rules; database roles),
      `docs/DATA_MODEL.md` (the
      twenty-three tables, natural
      keys, indexes, grants),
      `data/README.md` (what lives
      under `data/reference/`,
      `data/fixtures/`, and the
      untracked `data/lake/` and
      `data/synthetic/`), update
      the `fjc` entry in
      `docs/DATA_SOURCES.md` with
      the verified header names and
      the fetch date, and resolve
      open question 1 in
      `docs/ROADMAP.md`.
    </requirement>

    <requirement>
      Filepath comment: every new
      file gets the repo-relative
      path as the first line.
    </requirement>
  </requirements>
</task>
```

### Step 3 acceptance criteria

- `uv run poe ingest-fjc` against the live export completes with
  status `succeeded` and logs counts of judges, service rows, courts,
  and one jurisdiction; `judgemetrics ingest runs --source fjc` shows
  the run.
- A second live run records `records_created = 0` for canonical rows
  and reuses the existing `source_record` rows when file hashes are
  unchanged.
- Every `judge`, `judge_service`, and `court` row references a
  `source_record` whose `raw_sha256` equals the sha256 of the stored
  raw object (integration assertion over the fixture run).
- `FilesystemRawObjectStore.put` refuses to overwrite a key with
  different content and the S3 backend passes the same contract test
  against MinIO.
- `docs/DATA_SOURCES.md` records the verified FJC headers; the
  connector fails with a named-header error when a header is missing
  (unit test); `docs/ROADMAP.md` open question 1 is resolved.
- All unit and integration tests pass locally and in CI.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean,
  SAST clean (download timeouts, size cap, HTTPS-only, hash-derived
  keys), dependency audit clean, image scan clean — and the
  demographics file is not fetched or stored.

---

## Step 4 — Public API v1

> **Goal:** Expose the ingested data through the versioned read-only
> API: `api/routes/judges.py` (`GET /api/v1/judges` with `q`,
> `court_id`, `active_on`, `status`, `limit`, `offset`;
> `/judges/{judge_id}`; `/judges/{judge_id}/service`),
> `api/routes/courts.py` (`/courts` with `jurisdiction_id`,
> `court_type`; `/courts/{court_id}`), `api/routes/jurisdictions.py`
> (`/jurisdictions`, `/jurisdictions/{jurisdiction_id}`),
> `api/routes/search.py` (`/search?q=` trigram search over judges and
> courts), `api/ratelimit.py` (an in-process limiter applied to
> `/search`), `schemas/` (Pydantic response models including a generic
> `Page[T]` envelope and a `Provenance` block), `repositories/` (query
> modules), `services/search.py` (`pg_trgm` similarity with a
> configurable threshold), a `judgemetrics openapi export` command that
> writes `docs/openapi.json`, `docs/API.md`, and integration tests over
> the FJC fixture ingest for pagination bounds, filter validation,
> search tolerance, rate limiting, provenance presence, query counts,
> and the OpenAPI snapshot. Step 5 generates its client from the
> document this step commits.

**Branch:** `feature/phase01-step4-api-v1`

**Deploys:** nothing beyond merge — served locally by
`uv run poe dev-api`.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** A well-specified, multi-file implementation with
correctness demands (pagination contracts, strict validation, rate
limiting, no internal identifiers leaked, an OpenAPI snapshot that Step
5 depends on) — PRIMARY `coding`, SECONDARY `agentic` (running the API
and database while iterating), High complexity from the cross-cutting
scope, so an S-tier coder is required; Claude Opus 5 is S in coding and
S in agentic (Terminal-Bench 2.1 89.1) and supersedes Opus 4.8.
Platform is Claude Code on the flat claude.ai Max subscription; the
flat-funding gate is open, so Effort is `Max` and Thinking `On` —
nothing is saved by running lower. Backup: GPT-5.3 Codex on Codex
(ChatGPT Plus; Intelligence High), the cost-efficient S-tier coding
and agentic model from a different provider. Conversation is New per
phase-boundary hygiene.

```xml
<task>
  <lifecycle>
    This step MUST follow all six
    stages, in order. Stages 1, 3,
    4, 5, 6 are AS BINDING as any
    `<requirement>` below. Do not
    emit the Stage 6 completion
    line until the PR is merged and
    every acceptance criterion for
    this step is affirmatively met.

    1. CREATE THE BRANCH. Before
       any Read / Edit / Bash, run
       `git checkout -b
       feature/phase01-step4-api-v1`
       from a clean, up-to-date
       `main`. If the Worktree rule
       applies, use `git fetch
       origin && git worktree add
       -b <branch> .worktrees/<slug>
       origin/main` instead, then
       bootstrap the worktree.

    2. WORK ON THE BRANCH. All
       commits land here. `main`
       is protected with
       `enforce_admins: true` —
       direct pushes will be
       rejected.

    3. OPEN THE PR. `gh pr create
       --base main --head <branch>`
       with a Conventional Commits
       title and a body that
       references this roadmap step
       and its acceptance criteria.
       One PR per step.

    4. WAIT FOR GREEN CHECKS, THEN
       SQUASH-MERGE. Every required
       check must pass. If the PR
       falls behind main, refresh
       with `gh pr update-branch
       --rebase` — never merge main
       into the branch
       (`required_linear_history:
       true`). Once green:
       `gh pr merge <PR> --squash
       --delete-branch`. This
       step's `**Deploys:**` line
       is "nothing beyond merge";
       exercise the local API and
       confirm the acceptance
       criteria before Stage 6.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree,
       `git worktree remove <path>`
       FIRST.

    6. DECLARE COMPLETION, THEN
       NEW CONVERSATION. Update
       docs/ROADMAP.md. Once the
       PR is merged and every
       acceptance criterion for
       this step is affirmatively
       met, end your final response
       with the verbatim line
       "Step 4 is complete. You can
       now move on to Step 5." Put
       any caveats or ideas in a
       short "Follow-ups
       (non-blocking)" note AFTER
       that line. If any criterion
       is unmet, state plainly that
       the step is NOT complete,
       name what failed, and omit
       the completion line. The
       operator then closes this
       session and opens a fresh
       one for Step 5.
  </lifecycle>

  <security>
    Security is a gate on THIS
    step, not a later phase. It is
    AS BINDING as any
    `<requirement>` below. Before
    the Stage-2 commit, this
    step's work MUST pass the
    local, fail-closed security
    gate — the SAME gate wired
    into the pre-commit hook and
    re-run in CI:

    1. SECRET / PII SCAN. No
       credentials or tokens in
       the diff (`detect-secrets`).

    2. SAST. No new injection
       pattern (`bandit`): search
       uses bound parameters
       through SQLAlchemy; no
       string-built SQL; `limit`
       is capped server-side; the
       search endpoint is rate
       limited.

    3. DEPENDENCY AUDIT. Any new
       dependency passes
       `pip-audit --strict`; the
       image scan stays clean.

    4. SENSITIVE-DATA REVIEW. The
       API is read-only, connects
       with the app role, and
       exposes only public UUIDs,
       public judge data, and
       provenance metadata; no
       `source_record.raw_object_path`
       (an internal storage key)
       leaves the API; error
       responses never include
       stack traces or SQL.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 1.
    Step 4: public API v1.

    Current state (as of Step 3):

    - The FJC connector populates
      `jurisdiction`, `court`,
      `judge`, and `judge_service`
      with provenance; fixtures
      under `tests/fixtures/fjc/`
      drive integration tests via
      `run_ingest(..., from_fixture)`.
    - Only the health router is
      mounted at `/api/v1`.
    - `create_app()` sets
      `openapi_url=
      "/api/v1/openapi.json"`.

    Files to read (every file
    before drafting):
    - docs/brief/judgemetrics-
      master-project-specification.xml
      (`<api_design>` endpoints
      and rules; `<performance_
      strategy>` API rules;
      `<security>` rate limiting
      and input validation).
    - ROADMAP.md §4 Phase 1.4 and
      §5 "Performance rules".
    - src/judgemetrics/main.py,
      api/routes/health.py,
      db/models/reference.py,
      db/models/provenance.py,
      db/session.py, cli.py,
      config.py.
    - alembic/versions/
      0001_baseline.py (trigram
      indexes the search must
      use).
    - tests/conftest.py,
      tests/integration/
      test_fjc_ingest.py (reuse
      the fixture-ingest pattern).
  </context>

  <goal>
    Ship the judges, courts,
    jurisdictions, and search
    endpoints with a uniform page
    envelope, strict filter
    validation, a rate limiter on
    search, provenance blocks, an
    N+1 guard, and a committed
    OpenAPI document, tested end
    to end over the FJC fixture
    data.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      `src/judgemetrics/schemas/`:
      `common.py` (`Page[T]` with
      `items`, `total`, `limit`,
      `offset`, `next_offset`;
      `Provenance` with `source`,
      `external_record_id`,
      `retrieved_at`, `raw_sha256`,
      `parser_version`,
      `ingest_run_id`; `ErrorBody`
      with `code`, `message`,
      `request_id`), `judges.py`
      (`JudgeSummary`,
      `JudgeDetail` with
      `service: list[ServiceRecord]`
      and `provenance:
      list[Provenance]`),
      `courts.py`,
      `jurisdictions.py`,
      `search.py` (`SearchResult`
      with `entity_type`, `id`,
      `name`, `score`). Pydantic v2
      with `from_attributes=True`.
    </requirement>

    <requirement>
      `src/judgemetrics/
      repositories/`: `judges.py`,
      `courts.py`,
      `jurisdictions.py` with typed
      query functions taking a
      `Session` and returning ORM
      rows plus totals, using
      `selectinload` for service
      records so a detail response
      needs at most three
      statements; filters: judges
      `q` (trigram on
      `normalized_name`),
      `court_id`, `active_on`
      (date within a service
      interval), `status`; courts
      `jurisdiction_id`,
      `court_type`. `limit`
      default 25, maximum 100;
      `offset` ≥ 0; unknown query
      parameters rejected with
      422 via a strict dependency.
    </requirement>

    <requirement>
      `src/judgemetrics/services/
      search.py`: `search(session,
      q, limit)` unioning judge and
      court matches using
      `similarity()` and the `%`
      operator with the threshold
      set per session from
      settings (default 0.3),
      ordered by score; normalize
      `q` with
      `normalize_person_name`.
      `src/judgemetrics/api/
      ratelimit.py`: an in-process
      token-bucket limiter keyed by
      client IP (honouring
      `X-Forwarded-For` only when
      `settings.trust_proxy` is
      true), configured by
      `settings.search_rate_limit_per_minute`
      (default 60) and
      `search_rate_limit_burst`
      (default 10), returning 429
      with `Retry-After` and an
      `ErrorBody`; documented as
      the local layer beneath the
      Phase 8 edge limits.
    </requirement>

    <requirement>
      Routes under
      `src/judgemetrics/api/routes/`
      mounted at `/api/v1`:
      `GET /judges`,
      `GET /judges/{judge_id}`
      (404 with `ErrorBody` when
      missing), `GET /judges/
      {judge_id}/service`,
      `GET /courts`, `GET /courts/
      {court_id}`, `GET /
      jurisdictions`,
      `GET /jurisdictions/
      {jurisdiction_id}`,
      `GET /search` (rate
      limited). Detail responses
      include `provenance`.
      Register a global exception
      handler that returns
      `ErrorBody` and never a stack
      trace. Add `Cache-Control:
      public, max-age=60` on list
      and detail routes.
    </requirement>

    <requirement>
      CLI `judgemetrics openapi
      export [--out
      docs/openapi.json]` writing
      the app's OpenAPI document
      with sorted keys and a
      trailing newline; commit
      `docs/openapi.json`; a unit
      test asserts the committed
      file equals the generated
      document (so a route change
      without a regenerated
      document fails CI). Write
      `docs/API.md` (base URL,
      pagination, filters, error
      envelope, rate limits,
      provenance block, versioning
      policy).
    </requirement>

    <requirement>
      Tests: `tests/integration/
      test_api_judges.py`,
      `test_api_courts.py`,
      `test_api_jurisdictions.py`,
      `test_api_search.py` over a
      module-scoped fixture ingest:
      pagination (`total`,
      `next_offset`, `limit=100`
      accepted, `limit=101`
      rejected, `offset=-1`
      rejected), unknown parameter
      rejected, `active_on`
      filter, 404 shape, search
      returns the fixture judge for
      a misspelled surname, the
      limiter returns 429 with
      `Retry-After` after the burst
      (limiter enabled explicitly
      in that test and disabled by
      default under `env == test`),
      detail responses carry
      provenance with a
      64-character sha256, and no
      response body contains
      `raw_object_path`.
      `tests/integration/
      test_query_counts.py` counts
      statements with a
      `before_cursor_execute`
      listener: judge detail ≤ 3,
      judges list ≤ 2, search ≤ 2.
    </requirement>

    <requirement>
      Update `docs/ARCHITECTURE.md`
      with the API layering
      (routes → services →
      repositories → models) and
      the rate limiter;
      `README.md` with the endpoint
      list; `docs/ROADMAP.md`
      completed items.
    </requirement>

    <requirement>
      Filepath comment: every new
      file gets the repo-relative
      path as the first line.
    </requirement>
  </requirements>
</task>
```

### Step 4 acceptance criteria

- All eight endpoints respond with the documented schemas against the
  locally ingested FJC data; `GET /api/v1/judges/{id}` for an FJC
  judge returns service records and provenance.
- Pagination bounds and unknown-parameter rejection are tested;
  `limit` above 100 and negative `offset` return 422 with `ErrorBody`.
- `GET /api/v1/search?q=<misspelled surname>` returns the intended
  judge within the top results, and the limiter returns 429 with
  `Retry-After` after the configured burst (tests).
- The query-count guard passes: judge detail in at most three
  statements, list and search in at most two.
- `docs/openapi.json` is committed and equals the generated document
  (test); the document lists exactly the health and the eight new
  paths; `docs/API.md` exists.
- No response contains `raw_object_path` or any non-UUID internal
  identifier (test).
- All tests green locally and in CI.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean,
  SAST clean (parameterized queries only; server-side limit cap; rate
  limiter), dependency audit clean — and error responses never include
  stack traces or SQL (test).

---

## Step 5 — Web Foundation

> **Goal:** Stand up the web application in `web/`: a Next.js
> (current stable, App Router) TypeScript project with Tailwind CSS,
> shadcn/ui, TanStack Table, `next-themes` for light and dark mode, a
> typed API client (`openapi-typescript` types generated from
> `docs/openapi.json` and an `openapi-fetch` client reading
> `NEXT_PUBLIC_API_BASE_URL`), pages for `/` (global search, coverage
> summary, methodology link), `/search`, `/judges/[judgeId]` (identity,
> service timeline, source panel), `/courts/[courtId]` (court and the
> judges serving on a selected date), and `/methodology` (principles and
> the association-is-not-causation statement), keyboard-accessible
> navigation with a skip link, `eslint-plugin-security`, a `typecheck`
> script, Vitest unit tests, a Playwright smoke test against the local
> API, `infra/docker/web.Dockerfile` built and scanned by the CI
> `container` job, the `web` and `e2e` CI jobs, a Dependabot `npm`
> entry, and the `dev-web` target. Step 6 verifies all of it.

**Branch:** `feature/phase01-step5-web`

**Deploys:** nothing beyond merge — served locally with
`uv run poe dev-web` against `uv run poe dev-api`; the `web`, `e2e`,
and extended `container` CI jobs are live on merge.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** A multi-file TypeScript implementation driven
from a committed API contract, with tooling setup, tests, a container
image, and CI wiring — PRIMARY `coding`, SECONDARY `agentic`
(installing, running the dev server and Playwright, iterating on
screenshots), High complexity from the cross-cutting scope; Claude Opus
5 is S in coding and S in agentic (Terminal-Bench 2.1 89.1), A in
multimodal for the occasional screenshot review, and supersedes Opus
4.8. Platform is Claude Code on the flat claude.ai Max subscription;
the flat-funding gate is open, so Effort is `Max` and Thinking `On`.
Backup: GPT-5.3 Codex on Codex (ChatGPT Plus; Intelligence High),
S-tier coding and agentic from a different provider. Conversation is
New per phase-boundary hygiene.

```xml
<task>
  <lifecycle>
    This step MUST follow all six
    stages, in order. Stages 1, 3,
    4, 5, 6 are AS BINDING as any
    `<requirement>` below. Do not
    emit the Stage 6 completion
    line until the PR is merged and
    every acceptance criterion for
    this step is affirmatively met.

    1. CREATE THE BRANCH. Before
       any Read / Edit / Bash, run
       `git checkout -b
       feature/phase01-step5-web`
       from a clean, up-to-date
       `main`. If the Worktree rule
       applies, use `git fetch
       origin && git worktree add
       -b <branch> .worktrees/<slug>
       origin/main` instead, then
       bootstrap the worktree.

    2. WORK ON THE BRANCH. All
       commits land here. `main`
       is protected with
       `enforce_admins: true` —
       direct pushes will be
       rejected.

    3. OPEN THE PR. `gh pr create
       --base main --head <branch>`
       with a Conventional Commits
       title and a body that
       references this roadmap step
       and its acceptance criteria,
       with screenshots of every
       page in light and dark mode.
       One PR per step.

    4. WAIT FOR GREEN CHECKS, THEN
       SQUASH-MERGE. Every required
       check must pass. If the PR
       falls behind main, refresh
       with `gh pr update-branch
       --rebase` — never merge main
       into the branch
       (`required_linear_history:
       true`). Once green:
       `gh pr merge <PR> --squash
       --delete-branch`. This
       step's `**Deploys:**` line
       is "nothing beyond merge";
       run the pages against the
       local API and confirm the
       acceptance criteria before
       Stage 6.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree,
       `git worktree remove <path>`
       FIRST.

    6. DECLARE COMPLETION, THEN
       NEW CONVERSATION. Update
       docs/ROADMAP.md. Once the
       PR is merged and every
       acceptance criterion for
       this step is affirmatively
       met, end your final response
       with the verbatim line
       "Step 5 is complete. You can
       now move on to Step 6." Put
       any caveats or ideas in a
       short "Follow-ups
       (non-blocking)" note AFTER
       that line. If any criterion
       is unmet, state plainly that
       the step is NOT complete,
       name what failed, and omit
       the completion line. The
       operator then closes this
       session and opens a fresh
       one for Step 6.
  </lifecycle>

  <security>
    Security is a gate on THIS
    step, not a later phase. It is
    AS BINDING as any
    `<requirement>` below. Before
    the Stage-2 commit, this
    step's work MUST pass the
    local, fail-closed security
    gate — the SAME gate wired
    into the pre-commit hook and
    re-run in CI, extended here to
    the web stack:

    1. SECRET / PII SCAN. No
       credentials or tokens in
       the diff (`detect-secrets`).
       Only `NEXT_PUBLIC_*`
       variables reach the client
       bundle; add a unit test that
       greps the production build
       output for `JUDGEMETRICS_`
       and fails on any hit.

    2. SAST.
       `eslint-plugin-security` is
       enabled in `web/` and clean;
       no `dangerouslySetInnerHTML`
       with API data; no `eval`.

    3. DEPENDENCY AUDIT. `pnpm
       audit --audit-level=high` is
       clean; `pnpm-lock.yaml` is
       committed; the `web` CI job
       runs the audit; the web
       image passes the CI scan.

    4. SENSITIVE-DATA REVIEW. The
       web tier is read-only and
       renders public judge data
       and provenance; no cookies,
       no analytics, no third-party
       scripts in Phase 1; the
       image runs as a non-root
       user.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 1.
    Step 5: web foundation.

    Current state (as of Step 4):

    - The API serves health,
      judges, courts,
      jurisdictions, and
      rate-limited search at
      `/api/v1`; `docs/openapi.json`
      is committed and tested
      against the app.
    - No `web/` directory, no Node
      tooling, no `web` CI job; the
      `container` job builds only
      the API image.
    - `ci.yml` has `python`,
      `security`, `container`, and
      the aggregate `test` job;
      `dependabot.yml` covers `uv`,
      `github-actions`, and
      `docker`.

    Files to read (every file
    before drafting):
    - docs/brief/judgemetrics-
      master-project-specification.xml
      (`<frontend_design>`,
      `<application_pages>` for
      home, search, judge, court,
      methodology; `<ci_pipeline>`
      frontend steps).
    - ROADMAP.md §4 Phase 1.5.
    - docs/openapi.json (the
      contract the client is
      generated from).
    - .github/workflows/ci.yml,
      .github/dependabot.yml,
      infra/docker/api.Dockerfile,
      docker-compose.yml,
      .gitignore, .editorconfig,
      .pre-commit-config.yaml,
      pyproject.toml (poe tasks),
      Makefile.
    - README.md.
  </context>

  <goal>
    Ship `web/` with a typed client
    generated from the committed
    OpenAPI document and the home,
    search, judge, court, and
    methodology pages rendering
    real local data, with a type
    check, Vitest unit tests, a
    Playwright smoke test, a web
    container image, and `web`,
    `e2e`, and `container` CI jobs
    folded into the aggregate
    `test` check.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Scaffold `web/` with the
      current stable Next.js
      (App Router, TypeScript
      strict, Tailwind CSS,
      ESLint), pnpm, and a
      `.node-version` of 22 at the
      repo root; add shadcn/ui
      (button, input, table, card,
      badge, tooltip), TanStack
      Table, `next-themes`,
      `openapi-typescript`,
      `openapi-fetch`, Vitest with
      Testing Library, Playwright,
      and `eslint-plugin-security`.
      Scripts: `dev`, `build`,
      `start`, `lint`, `typecheck`
      (`tsc --noEmit`), `test`,
      `e2e`, `generate:api`
      (writes `web/lib/api/
      schema.d.ts` from
      `../docs/openapi.json`);
      commit the generated file and
      add a test that regeneration
      produces no diff. Enable
      `output: "standalone"` for
      the container image.
    </requirement>

    <requirement>
      `web/lib/api/client.ts`:
      `openapi-fetch` client using
      `NEXT_PUBLIC_API_BASE_URL`
      (default
      `http://localhost:8000`);
      server components fetch on
      the server; typed helpers
      `getJudge(id)`,
      `listJudges(params)`,
      `getCourt(id)`,
      `listJurisdictions()`,
      `search(q)`.
    </requirement>

    <requirement>
      Pages (App Router):
      `app/layout.tsx` (header nav:
      Search, Coverage (link to
      `/coverage` rendering a
      "coming in Phase 2" note),
      Methodology, About; theme
      toggle; skip link; footer
      with "Data sources" and
      "Methodology" links),
      `app/page.tsx` (headline
      "Judicial outcomes, measured
      from data", global search
      box, coverage summary tiles
      from `/jurisdictions` and
      list totals, prominent
      methodology link),
      `app/search/page.tsx` (query
      → `/search`; results table
      with entity type badge),
      `app/judges/[judgeId]/
      page.tsx` (name, status,
      current and historical
      service as a sortable
      TanStack table, a "Source
      coverage" panel listing each
      provenance entry with source
      name, retrieved-at,
      truncated sha256 with a
      copy-to-clipboard full hash,
      and a link to the FJC export
      page; a "Report a data
      issue" link to the GitHub
      data-source issue template),
      `app/courts/[courtId]/
      page.tsx` (court name, type,
      jurisdiction, and a date
      picker driving
      `/judges?court_id=&active_on=`),
      `app/methodology/page.tsx`
      (the ten principles; the
      statement "These statistics
      describe associations in
      available records. They do
      not prove that a judicial
      decision caused a later
      event."; a note that metrics
      arrive in Phase 3). Empty and
      error states for every
      fetch. Semantic landmarks,
      visible focus rings, table
      headers with scope.
    </requirement>

    <requirement>
      Tests: Vitest for the client
      helpers (mocked fetch) and
      one component (the provenance
      panel truncation and copy);
      Playwright `web/tests/e2e/
      smoke.spec.ts`: home renders
      and search box focuses on
      `/`; searching a fixture
      judge's surname lists the
      judge; the judge page shows
      at least one service row and
      the source panel; theme
      toggle switches
      `data-theme`; the court page
      lists judges for a date.
      Playwright config starts
      nothing itself — CI and the
      operator provide the API.
    </requirement>

    <requirement>
      `infra/docker/web.Dockerfile`:
      multi-stage build on the
      official `node:22-alpine`
      base with pnpm via corepack,
      the standalone output, a
      non-root user, and
      `NEXT_PUBLIC_API_BASE_URL` as
      a build argument; a compose
      service `web` under profile
      `app` (port 3000, depends on
      `api`). Extend the CI
      `container` job to build and
      scan both images.
    </requirement>

    <requirement>
      CI: add the `web` job
      (setup-node pinned by SHA,
      pnpm via corepack, `pnpm
      install --frozen-lockfile`,
      `pnpm lint`, `pnpm
      typecheck`, `pnpm test`,
      `pnpm build`, `pnpm audit
      --audit-level=high`) and the
      `e2e` job (Postgres service
      with the three roles; `uv
      sync --frozen`; `uv run poe
      migrate`; `uv run judgemetrics
      ingest run fjc --from-fixture
      tests/fixtures/fjc`; start
      `uv run judgemetrics serve`
      in the background; `pnpm exec
      playwright install
      --with-deps chromium`; `pnpm
      e2e`); add both to the
      aggregate `test` job's
      `needs`. Add `npm` for `/web`
      to `dependabot.yml`. Add the
      poe task `dev-web = "pnpm
      --dir web dev"` and the
      Makefile target.
    </requirement>

    <requirement>
      Add `web/.env.example`
      (`NEXT_PUBLIC_API_BASE_URL`)
      and extend `.gitignore` if
      the scaffold needs entries
      not already present. Update
      `README.md` (web quick
      start), `docs/ARCHITECTURE.md`
      (web tier, the generated
      client, the web image), and
      `docs/ROADMAP.md`.
    </requirement>

    <requirement>
      Filepath comment: every new
      TS / TSX / CSS / YAML /
      Markdown / Dockerfile file
      gets the repo-relative path
      as the first line (`// web/
      ...`; `/* web/app/globals.css
      */`; `# infra/docker/
      web.Dockerfile`). Generated
      files and JSON are exempt.
    </requirement>
  </requirements>
</task>
```

### Step 5 acceptance criteria

- `pnpm install --frozen-lockfile`, `pnpm lint`, `pnpm typecheck`,
  `pnpm test`, and `pnpm build` succeed locally and in the `web` CI
  job.
- With the API running on the ingested FJC data, `/`, `/search`,
  `/judges/[judgeId]`, `/courts/[courtId]`, and `/methodology` render
  real data; light and dark modes both render (screenshots in the PR).
- The Playwright smoke test passes locally and in the `e2e` CI job,
  which ingests the FJC fixture, starts the API, and runs the browser.
- `web/lib/api/schema.d.ts` regenerates from `docs/openapi.json` with
  no diff (test).
- The production bundle contains no `JUDGEMETRICS_` variable (test);
  `pnpm audit --audit-level=high` is clean; the web image builds and
  scans clean in the `container` job and `docker compose --profile
  app up` serves the home page from the container.
- The aggregate `test` check now requires `python`, `security`,
  `container`, `web`, and `e2e`.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean,
  `eslint-plugin-security` clean, `pnpm audit` clean, image scan clean
  — and the web tier sets no cookies and loads no third-party script.

---

## Step 6 — QA & Verification Script

> **Goal:** Package the verification matrix into
> `scripts/verify_phase01.py` (with `--fast`, `--py`, `--node`, `--e2e`,
> `--security`, `--all`, and `--post` modes), produce
> `docs/phase01-qa-findings.md`, add `01` to the `phase-verify.yml`
> matrix, and bring `docs/ROADMAP.md` up to date. The script checks
> every Step 1 through Step 5 deliverable statically and runs the
> Python, web, end-to-end, and security suites in the appropriate
> modes; the `--post` mode runs the full V1–V6 sweep plus
> `gh pr checks` when the CLI is logged in. This script is the
> structural template every later phase copies.

**Branch:** `feature/phase01-step6-verify`

**Deploys:** nothing beyond merge — the `phase-verify.yml` matrix
entry is live on merge.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** A bounded, mostly mechanical translation of the
Steps 1–5 deliverables into numbered static checks, mode dispatch, and
a CI matrix entry — PRIMARY `coding`, Medium complexity, where an
A-tier coder would suffice; the selector still ranks by the highest
PRIMARY tier first, and under the operator's flat claude.ai Max
subscription the flat-funding gate suspends tier-down on cost grounds
for trivial work, so Claude Opus 5 (S in coding, Terminal-Bench 2.1
89.1; supersedes Opus 4.8) on Claude Code remains the pick at zero
marginal cost. Effort is `Max` and Thinking `On` for the same reason —
no saving from running lower, and the script's correctness is what
gates every later phase's CI. Backup: GPT-5.3 Codex on Codex (ChatGPT
Plus; Intelligence High). Conversation is New per phase-boundary
hygiene.

```xml
<task>
  <lifecycle>
    This step MUST follow all six
    stages, in order. Stages 1, 3,
    4, 5, 6 are AS BINDING as any
    `<requirement>` below. Do not
    emit the Stage 6 completion
    line until the PR is merged and
    every acceptance criterion for
    this step is affirmatively met.

    1. CREATE THE BRANCH. Before
       any Read / Edit / Bash, run
       `git checkout -b
       feature/phase01-step6-verify`
       from a clean, up-to-date
       `main`. If the Worktree rule
       applies, use `git fetch
       origin && git worktree add
       -b <branch> .worktrees/<slug>
       origin/main` instead, then
       bootstrap the worktree.

    2. WORK ON THE BRANCH. All
       commits land here. `main`
       is protected with
       `enforce_admins: true` —
       direct pushes will be
       rejected.

    3. OPEN THE PR. `gh pr create
       --base main --head <branch>`
       with a Conventional Commits
       title and a body that
       references this roadmap step
       and its acceptance criteria.
       One PR per step.

    4. WAIT FOR GREEN CHECKS, THEN
       SQUASH-MERGE. Every required
       check must pass, including
       the new `phase-verify.yml`
       matrix entry once it is
       added to the required
       contexts. If the PR falls
       behind main, refresh with
       `gh pr update-branch
       --rebase` — never merge main
       into the branch
       (`required_linear_history:
       true`). Once green:
       `gh pr merge <PR> --squash
       --delete-branch`.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree,
       `git worktree remove <path>`
       FIRST.

    6. DECLARE COMPLETION, THEN
       NEW CONVERSATION. Update
       docs/ROADMAP.md (Phase 1
       complete; current phase
       becomes Phase 2). Once the
       PR is merged and every
       acceptance criterion for
       this step is affirmatively
       met, end your final response
       with the verbatim line
       "Step 6 is complete. You can
       now move on to Phase 2." Put
       any caveats or ideas in a
       short "Follow-ups
       (non-blocking)" note AFTER
       that line. If any criterion
       is unmet, state plainly that
       the step is NOT complete,
       name what failed, and omit
       the completion line. The
       operator then closes this
       session; Phase 2 begins in a
       fresh conversation after
       re-exporting the planning
       kit (`uv run poe kit`).
  </lifecycle>

  <security>
    Security is a gate on THIS
    step, not a later phase. It is
    AS BINDING as any
    `<requirement>` below. Before
    the Stage-2 commit, this
    step's work MUST pass the
    local, fail-closed security
    gate — the SAME gate wired
    into the pre-commit hook and
    re-run in CI. This step also
    AUTHORS the `--security` verify
    mode, so its own diff must
    still pass the gate before
    commit:

    1. SECRET / PII SCAN clean
       (`detect-secrets`).
    2. SAST clean (`bandit`); the
       verify script runs
       subprocesses with argument
       lists only, never
       `shell=True`, and only
       against repository-local
       tools resolved through
       `uv run` / `pnpm`.
    3. DEPENDENCY AUDIT clean; the
       script adds no dependency
       (standard library only).
    4. SENSITIVE-DATA REVIEW: the
       script prints check names
       and paths, never file
       contents that could contain
       a secret.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 1.
    Step 6: QA + verification
    script.

    Steps 1 through 5 have been
    implemented. Now create the
    verification script, QA
    findings doc, CI matrix
    workflow, and the status
    update.

    There is no prior
    `verify_phaseNN.py` to copy;
    this script defines the
    pattern: argparse modes,
    numbered static checks using
    only `pathlib`, `re`, and
    `json`, subprocess-driven
    suites, `[PASS] NN` /
    `[FAIL] NN` lines, a summary
    table, exit 0 on success and 1
    on any failure.

    Phase 1 deliverables to verify
    (43 static checks across Steps
    1 through 5, the security
    backstop, and the Step 6
    self-checks):

    Step 1 (bootstrap) — checks
    1-11:
    1.  LICENSE exists and contains
        "Apache License".
    2.  CONTRIBUTING.md, SECURITY.md,
        CODE_OF_CONDUCT.md exist.
    3.  .github/PULL_REQUEST_TEMPLATE.md
        and the three issue
        templates exist.
    4.  .pre-commit-config.yaml
        names ruff, mypy, bandit,
        detect-secrets, pip-audit.
    5.  .secrets.baseline exists.
    6.  ci.yml: every `uses:` is
        pinned to a 40-hex SHA.
    7.  ci.yml declares top-level
        `permissions:` and a `test`
        job with `if: always()`.
    8.  docker-compose.yml defines
        `postgres` and `minio`; the
        pg_trgm and roles init
        scripts exist.
    9.  .env.example exists, no
        value matches a secret
        shape, and `.env` is not
        tracked (`git ls-files`).
    10. pyproject `[tool.poe.tasks]`
        defines up, down, check,
        gate; the Makefile mirrors
        them.
    11. .github/dependabot.yml
        covers uv and
        github-actions.

    Step 2 (core + schema) —
    checks 12-20:
    12. src/judgemetrics/config.py
        defines `Settings` with
        env prefix `JUDGEMETRICS_`.
    13. src/judgemetrics/logging.py
        defines `scrub_sensitive`.
    14. src/judgemetrics/main.py
        defines `create_app`.
    15. api/routes/health.py
        declares `/health` and
        `/ready`.
    16. alembic/versions contains a
        baseline creating
        `pg_trgm` and every
        canonical table name.
    17. db/models/ modules define
        all twenty-three entities.
    18. infra/docker/api.Dockerfile
        exists and compose defines
        `api`.
    19. ci.yml has a `container`
        job that builds and scans
        images.
    20. poe tasks migrate and
        dev-api exist.

    Step 3 (ingest + FJC) — checks
    21-27:
    21. ingest/base.py defines
        `SourceConnector`.
    22. ingest/store.py defines
        `FilesystemRawObjectStore`
        and `S3RawObjectStore`.
    23. ingest/runner.py defines
        `run_ingest`.
    24. ingest/fjc/connector.py
        registers source id "fjc";
        poe task ingest-fjc exists.
    25. tests/fixtures/fjc/ holds
        both CSVs and a README with
        a retrieval date.
    26. docs/ARCHITECTURE.md,
        docs/DATA_MODEL.md, and
        data/README.md exist.
    27. docs/DATA_SOURCES.md `fjc`
        entry lists verified
        headers.

    Step 4 (API v1) — checks
    28-32:
    28. api/routes/{judges,courts,
        jurisdictions,search}.py
        exist.
    29. docs/openapi.json lists the
        eight v1 paths plus health
        and ready.
    30. schemas/common.py defines
        `Page` and `Provenance`.
    31. api/ratelimit.py exists and
        config.py defines the
        search rate-limit settings.
    32. docs/API.md,
        tests/integration/
        test_api_*.py, and
        test_query_counts.py exist.

    Step 5 (web) — checks 33-38:
    33. web/package.json declares
        lint, typecheck, test,
        build, e2e, generate:api
        scripts.
    34. web/lib/api/schema.d.ts and
        client.ts exist.
    35. web/app/judges/[judgeId]/
        page.tsx and
        web/app/methodology/page.tsx
        exist.
    36. web/tests/e2e/smoke.spec.ts
        exists.
    37. ci.yml has `web` and `e2e`
        jobs in the `test` job's
        `needs`, and the
        `container` job builds the
        web image.
    38. infra/docker/web.Dockerfile
        exists; poe task dev-web
        exists.

    Security backstop — check 39:
    39. No private-key header,
        `AKIA`-style key, or
        `-----BEGIN` block under
        src/, web/ (excluding
        node_modules), tests/,
        docs/, or infra/.

    Step 6 self-checks — checks
    40-43:
    40. scripts/verify_phase01.py
        exists.
    41. docs/phase01-qa-findings.md
        exists.
    42. docs/phase01-roadmap.md
        exists (this doc).
    43. .github/workflows/
        phase-verify.yml matrix
        includes "01".

    Files to read:
    - all Phase 1 implementation
      files from Steps 1 through 5
      (paths above).
    - .github/workflows/ci.yml
      (job names the `--post`
      mode reports).
    - docs/ROADMAP.md (to update).
  </context>

  <goal>
    Create scripts/verify_phase01.py
    with 43 static deliverable
    checks (Steps 1 through 5, the
    security backstop, and the
    Step 6 self-checks) plus a
    post-implementation V1-V6
    matrix. Create
    docs/phase01-qa-findings.md.
    Create .github/workflows/
    phase-verify.yml with matrix
    entry "01" and add it to the
    required status checks. Update
    docs/ROADMAP.md.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      scripts/verify_phase01.py
      modes (argparse, mutually
      exclusive, default = --fast
      plus --py):
      - --fast: static checks only,
        CI-safe on Ubuntu and
        Windows; uses only pathlib
        / re / json / subprocess
        for `git ls-files`; MUST
        complete in under 30
        seconds.
      - --py: static + `uv run poe
        lint`, `uv run poe
        fmt-check`, `uv run poe
        typecheck`, `uv run pytest
        -m "not integration"`, and
        the integration suite when
        `JUDGEMETRICS_DATABASE_URL`
        is set.
      - --node: static + `pnpm
        --dir web lint`, `pnpm
        --dir web typecheck`, `pnpm
        --dir web build`, `pnpm
        --dir web test` (build
        before test, as in ci.yml:
        the Vitest bundle scan
        needs a production build).
      - --e2e: static + `pnpm --dir
        web e2e` (requires the API
        running; prints a clear
        skip reason otherwise).
      - --security: the gate over
        the phase's surface — `uv
        run detect-secrets-hook
        --baseline .secrets.baseline
        <every tracked file>` (the
        pre-commit hook's form;
        `detect-secrets scan
        --baseline` rewrites the
        baseline and exits 0, so it
        cannot fail closed), `uv run
        bandit -c pyproject.toml -r
        src alembic` (the gate's
        surface), `uv run python
        scripts/audit_deps.py`
        (pip-audit --strict over
        uv.lock), and `pnpm --dir
        web audit
        --audit-level=high`;
        CI-safe on Ubuntu; exits
        non-zero on any finding.
      - --all: static + py + node +
        e2e + security.
      - --post: static + V1-V6
        matrix + (when `gh auth
        status` succeeds) `gh pr
        checks` against the current
        branch.

      Static checks: 43 numbered
      checks as listed in context.
      Each check uses file
      existence, regex over file
      contents, or `git ls-files`
      only; prints `[PASS] NN
      description` or `[FAIL] NN
      description — reason`; is
      independent of the others.
      Check 39 is the security
      backstop and must exist.
    </requirement>

    <requirement>
      Post-implementation V-checks
      section (V1-V6) printed by
      `--post` and mirrored in this
      roadmap's "Post-Implementation
      Verification":

      V1 — Step 1 scope
      - V1.1 Static checks 1-11 all
        PASS.
      - V1.2 tests/unit/
        test_repo_hygiene.py passes
        (--py).
      - V1.3 `--security` exits 0.

      V2 — Step 2 scope
      - V2.1 Static checks 12-20
        all PASS.
      - V2.2 tests/unit/
        test_settings.py,
        test_logging.py,
        test_names.py pass (--py).
      - V2.3 tests/integration/
        test_migrations.py and
        test_health.py pass (--py
        with a database).
      - V2.4 the `container` CI job
        is green on the current
        branch (--post via `gh pr
        checks`).

      V3 — Step 3 scope
      - V3.1 Static checks 21-27
        all PASS.
      - V3.2 tests/unit/
        test_store.py,
        test_fjc_normalize.py,
        test_quality_checks.py pass.
      - V3.3 tests/integration/
        test_fjc_ingest.py passes
        (idempotency).

      V4 — Step 4 scope
      - V4.1 Static checks 28-32
        all PASS.
      - V4.2 tests/integration/
        test_api_*.py and
        test_query_counts.py pass.
      - V4.3 OpenAPI snapshot test
        passes.

      V5 — Step 5 scope
      - V5.1 Static checks 33-38
        all PASS.
      - V5.2 `pnpm lint`, `pnpm
        typecheck`, `pnpm test`,
        `pnpm build` pass (--node).
      - V5.3 `pnpm e2e` passes
        (--e2e).

      V6 — CI integration +
      security
      - V6.1 verify_phase01.py
        --fast exits 0 on Ubuntu
        CI.
      - V6.2 phase-verify.yml
        matrix includes "01".
      - V6.3 All 43 static checks
        pass.
      - V6.4 verify_phase01.py
        --security exits 0.
    </requirement>

    <requirement>
      Create tests/unit/
      test_phase01_verification.py
      with:
      - test_roadmap_doc_exists.
      - test_qa_findings_doc_exists.
      - test_verify_script_fast_exits_zero
        (subprocess, cwd = repo
        root, timeout 60 s).
      - test_phase_verify_matrix_includes_01.
    </requirement>

    <requirement>
      Create .github/workflows/
      phase-verify.yml: triggers
      push (main) and pull_request;
      `permissions: contents:
      read`; matrix `phase:
      ["01"]`; steps: checkout
      (SHA-pinned), setup-uv
      (SHA-pinned), `uv sync
      --frozen`, `uv run python
      scripts/verify_phase${{
      matrix.phase }}.py --fast`,
      then `--security` (with
      setup-node for the pnpm
      audit). Add the resulting
      check name to the branch
      protection required contexts
      with `gh api` and record the
      command in CONTRIBUTING.md.
    </requirement>

    <requirement>
      Create docs/phase01-qa-
      findings.md with rollup
      sections for Steps 1 through
      5 (finding, class per the
      triage rule, guard added), a
      Step 6 verify-script rollup,
      and a "Pre-ship items"
      section noting documented
      limitations (no deployed
      environment; FJC only;
      demographics not ingested;
      in-process rate limiter only)
      and Phase 2 follow-ups.
    </requirement>

    <requirement>
      Update ROADMAP.md and
      docs/ROADMAP.md:
      - Verify the Phase 1 entry's
        "Acceptance criteria"
        section in ROADMAP.md
        matches this roadmap's
        V1-V6 checks (consistency
        audit; edit whichever is
        wrong).
      - In docs/ROADMAP.md, move
        Phase 1 to Completed with
        the date, set the current
        phase to Phase 2, and carry
        forward any open questions.
      - Tag `v0.1.0-phase-1` on the
        merged commit and record
        it.
    </requirement>

    <requirement>
      Script must print clear pass
      / fail per check, a summary
      table (passed, failed, total,
      mode, elapsed), exit 0 on
      success, exit 1 on any
      failure, and run under both
      Windows and Ubuntu without
      modification. `--fast` must
      complete in under 30 seconds
      on Ubuntu CI.
    </requirement>

    <requirement>
      Filepath comment: every new
      file gets the repo-relative
      path as the first line.
    </requirement>
  </requirements>
</task>
```

### Step 6 acceptance criteria

- `scripts/verify_phase01.py` exists and passes on a clean tree
  post-implementation in every mode the environment supports.
- The script has 43 static checks plus the V1–V6 post-implementation
  matrix (63 reported items in `--post`).
- `--fast` runs in under 30 seconds on Ubuntu CI and on Windows.
- `--post` runs cleanly on the maintainer's machine with the local API
  and database up, all phase-specific suites green.
- `docs/phase01-qa-findings.md` is complete with every rollup section.
- `.github/workflows/phase-verify.yml` matrix includes `01`; the check
  appears on every PR and is a required context on `main`.
- `--security` mode exists and exits 0 (secret/PII scan, SAST, and
  dependency audits clean over the phase's surface); V6.4 is green.
- `docs/ROADMAP.md` records Phase 1 as complete with the tag
  `v0.1.0-phase-1`; branch protection still passes on the resulting
  PR.
- **Operations:** the Phase 1 runtime surface is the local API; its
  health signal (`/api/v1/health`, `/api/v1/ready`) exists and the
  phase's alarm is the CI aggregate `test` check plus the
  `phase-verify` check — both were seen to fail on a deliberately
  broken check during this step and then pass after the fix (recorded
  in the QA findings).
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff and the `security`,
  `container`, and `phase-verify` workflows are green.

---

## Post-Implementation Verification

Every V1–V6 check below runs automatically in CI on every push and
pull request — no manual invocation required — except V5.3 and the
`--post` sweep, which the operator runs locally against the Compose
services before tagging `v0.1.0-phase-1` (the `e2e` CI job covers the
same Playwright suite on Ubuntu).

| Mode         | Workflow                                     | Runner          | Coverage                                            |
| ------------ | -------------------------------------------- | --------------- | --------------------------------------------------- |
| `--fast`     | `phase-verify.yml` (matrix entry `01`)       | Ubuntu          | Static checks 1–43, V1.1, V2.1, V3.1, V4.1, V5.1, V6.1–V6.3 |
| `--py`       | `ci.yml` (`python` job, Postgres service)    | Ubuntu          | V1.2, V2.2, V2.3, V3.2, V3.3, V4.2, V4.3            |
| `--node`     | `ci.yml` (`web` job)                         | Ubuntu          | V5.2                                                |
| `--e2e`      | `ci.yml` (`e2e` job)                         | Ubuntu          | V5.3                                                |
| `--security` | `ci.yml` (`security` and `container` jobs) + `phase-verify.yml` | Ubuntu | V1.3, V2.4, V6.4                          |
| `--post`     | local (maintainer's machine)                 | Windows / Ubuntu | Full V1–V6 sweep + `gh pr checks`                  |

Local invocations remain available for ad-hoc runs and pre-release
sweeps:

```bash
uv run python scripts/verify_phase01.py --post   # static + V1-V6 + gh pr checks
```

`--post` is the canonical command to run before tagging the phase
release.

Other modes:

```bash
uv run python scripts/verify_phase01.py             # static + Python suites
uv run python scripts/verify_phase01.py --fast      # static only (CI)
uv run python scripts/verify_phase01.py --py        # static + ruff + mypy + pytest
uv run python scripts/verify_phase01.py --node      # static + web lint/typecheck/test/build
uv run python scripts/verify_phase01.py --e2e       # static + Playwright smoke
uv run python scripts/verify_phase01.py --security  # secret scan + SAST + audits
uv run python scripts/verify_phase01.py --all       # everything
```

The script reports each V-check by id (V1.1, V2.1, …) so a failure in
any workflow above maps directly to the corresponding row below.

### V1 — Repository bootstrap, command interface, security gate, CI

> **Automated in CI.** `phase-verify.yml` → V1.1; `ci.yml` → V1.2
> and V1.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V1.1 | Static checks 1–11 all PASS (license, community files, gate config, SHA-pinned CI, compose, env example, command interface, dependabot). | `phase-verify.yml` runs `verify_phase01.py --fast`. |
| V1.2 | `tests/unit/test_repo_hygiene.py` passes.                                   | `ci.yml` `python` job (`--py` locally).                 |
| V1.3 | `verify_phase01.py --security` exits 0.                                     | `ci.yml` `security` job and `phase-verify.yml`.         |

### V2 — Application core, canonical schema, API image

> **Automated in CI.** `phase-verify.yml` → V2.1; `ci.yml` → V2.2,
> V2.3, and V2.4.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V2.1 | Static checks 12–20 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V2.2 | `test_settings.py`, `test_logging.py`, `test_names.py` pass.                | `ci.yml` `python` job.                                  |
| V2.3 | `test_migrations.py` (round-trip, constraints, grants) and `test_health.py` pass against Postgres. | `ci.yml` `python` job with the `postgres:17` service. |
| V2.4 | The API image builds and the vulnerability scan is clean.                   | `ci.yml` `container` job (`--post` reads it via `gh pr checks`). |

### V3 — Ingest framework and FJC connector

> **Automated in CI.** `phase-verify.yml` → V3.1; `ci.yml` → V3.2
> and V3.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V3.1 | Static checks 21–27 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V3.2 | `test_store.py`, `test_fjc_normalize.py`, `test_quality_checks.py` pass.    | `ci.yml` `python` job.                                  |
| V3.3 | `test_fjc_ingest.py` passes: second fixture run creates zero rows; provenance hashes match. | `ci.yml` `python` job.                     |

### V4 — Public API v1

> **Automated in CI.** `phase-verify.yml` → V4.1; `ci.yml` → V4.2
> and V4.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V4.1 | Static checks 28–32 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V4.2 | `test_api_judges.py`, `test_api_courts.py`, `test_api_jurisdictions.py`, `test_api_search.py`, `test_query_counts.py` pass. | `ci.yml` `python` job. |
| V4.3 | The committed `docs/openapi.json` equals the generated document.            | `ci.yml` `python` job.                                  |

### V5 — Web foundation

> **Automated in CI.** `phase-verify.yml` → V5.1; `ci.yml` `web` →
> V5.2; `ci.yml` `e2e` → V5.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V5.1 | Static checks 33–38 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V5.2 | `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build` pass; schema regeneration has no diff; bundle contains no `JUDGEMETRICS_`; web image scans clean. | `ci.yml` `web` and `container` jobs. |
| V5.3 | Playwright smoke passes against the fixture-ingested API.                   | `ci.yml` `e2e` job (`--e2e` locally).                   |

### V6 — CI integration + security

> **Automated in CI.** `phase-verify.yml` → V6.1 through V6.4 on
> every push/PR.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V6.1 | `verify_phase01.py --fast` exits 0 on Ubuntu CI.                            | `phase-verify.yml` matrix entry `01`.                   |
| V6.2 | `phase-verify.yml` matrix includes `01`.                                    | `phase-verify.yml --fast` static check 43.              |
| V6.3 | All 43 static checks in `verify_phase01.py` pass.                           | `phase-verify.yml --fast` records pass only when zero static failures. |
| V6.4 | `verify_phase01.py --security` exits 0 (secret/PII scan + SAST + dependency audits clean). | `phase-verify.yml` runs `--security` on every push/PR. |

---

## Summary Table

| Step | Scope                                 | Model          | Platform     | Reasoning dial | Thinking | Conv |
| ---- | ------------------------------------- | -------------- | ------------ | -------------- | -------- | ---- |
| 1    | Bootstrap, interface, gate, CI        | Claude Opus 5  | Claude Code  | Effort Max     | On       | New  |
| 2    | Core, canonical schema, API image     | Claude Opus 5  | Claude Code  | Effort Max     | On       | New  |
| 3    | Ingest framework + FJC connector      | Fable 5.1      | Claude Code  | Effort Max     | On       | New  |
| 4    | Public API v1                         | Claude Opus 5  | Claude Code  | Effort Max     | On       | New  |
| 5    | Web foundation                        | Claude Opus 5  | Claude Code  | Effort Max     | On       | New  |
| 6    | QA + verify_phase01.py                | Claude Opus 5  | Claude Code  | Effort Max     | On       | New  |
| V1   | Bootstrap scope                       | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   |
| V2   | Core and schema scope                 | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   |
| V3   | Ingest scope                          | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   |
| V4   | API scope                             | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   |
| V5   | Web scope                             | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   |
| V6   | CI integration                        | CI: phase-verify.yml | --   | --             | --       | --   |

Backups (same platform rules, different provider): GPT-5.6 Sol on
Codex at Intelligence Extra High for Steps 2 and 3; GPT-5.3 Codex on
Codex at Intelligence High for Steps 1, 4, 5, and 6. Both are funded
by the ChatGPT Plus subscription, whose caps are modest, so they are
fallbacks for a Claude Code outage rather than parallel capacity.

---

## Model selection blocks

**Selection method.** Each block below was produced by running the
selector in `planning/model-selector.txt` (catalog dated with roadmodel
0.2.33, exported 2026-09-15) against `planning/user-context.md`, in
this order: Step 0a dropped no models (no availability restriction is
in force); Step 0b dropped every `cn`-jurisdiction model (Kimi,
DeepSeek, GLM) under the allowed list `us, eu, uk, ca, au, jp, kr`;
Steps 1–4 classified each step and ranked survivors by PRIMARY then
SECONDARY tier; within the tied frontier set, a superseded model
yields to its successor in the same series (Opus 5 over Opus 4.8 and
4.7; Fable 5.1 over Fable 5) as the catalog's `best-for` rows direct;
between the tied Claude and GPT frontier models, the operator context
breaks the tie on subscription-utilization economics rather than list
price — Claude picks run at zero marginal cost on the 20x claude.ai
Max plan, while GPT picks would draw on ChatGPT Plus caps the operator
declares modest and reserves for fallback — so the GPT model becomes
the required cross-provider BACKUP (Step 7); under the operator's
`balanced` posture Fable 5.1 is reserved for the ceiling-class step
(Step 3) and Opus 5 takes the rest, because Fable draws the Max budget
down at about twice Opus's rate for the same output. Access selection
Step A00 excluded `cursor` and `xai-api` per the operator's list; Step
C ranked `claude-code` first as subscription-funded; Step E applied
the flat-funding gate (open for Claude on Claude Code), raising Effort
to `Max` with Thinking `On`; Step E2 emitted `ORCHESTRATION: None`
because no Phase 1 step warrants Ultracode under the balanced posture;
Step F emitted no MAX MODE line (Claude Code has no such dial).

```text
PROMPT: Step 1 — Repository Bootstrap, Command Interface, Security Gate, and CI
MODEL: Claude Opus 5
BACKUP: GPT-5.3 Codex
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: cross-cutting repository coding with agentic gh, CI, and hook wiring. PICK: Claude Opus 5 is S-tier in coding and S-tier in agentic (Terminal-Bench 2.1 89.1) and supersedes Opus 4.8 in the same series. EFFORT: Max effort with thinking on because the flat-funding gate is open and the governance configuration rewards deliberate reasoning; orchestration is None for a single well-scoped deliverable.

PROMPT: Step 2 — Application Core, Canonical Schema, and the API Image
MODEL: Claude Opus 5
BACKUP: GPT-5.6 Sol
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: correctness-sensitive multi-file coding with schema-design planning across twenty-three tables. PICK: Claude Opus 5 is S-tier in coding and S-tier in planning (Artificial Analysis Intelligence Index 60.7 at max) and supersedes Opus 4.8. EFFORT: Max effort with thinking on because the canonical schema is the contract every later phase writes against and effort costs nothing under the open flat-funding gate; orchestration None.

PROMPT: Step 3 — Ingest Framework and the FJC Connector
MODEL: Fable 5.1
BACKUP: GPT-5.6 Sol
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: coding with novel cross-file protocol design and live-schema mapping, secondary planning. PICK: Fable 5.1 is S-tier in coding and S-tier in planning (HLE 59.1% and Terminal-Bench 2.1 91.4 at max) and supersedes Fable 5; reserved for this ceiling-class step under the balanced posture. EFFORT: Max effort with thinking on because the step meets the novel-problem-solving and cross-file chain-of-thought conditions and the flat-funding gate is open; orchestration None because one connector and runner is a single scoped deliverable.

PROMPT: Step 4 — Public API v1
MODEL: Claude Opus 5
BACKUP: GPT-5.3 Codex
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: multi-file API coding against a fixed contract with agentic test-and-run loops. PICK: Claude Opus 5 is S-tier in coding and S-tier in agentic (Terminal-Bench 2.1 89.1) and supersedes Opus 4.8. EFFORT: Max effort with thinking on because pagination, validation, rate limiting, and the OpenAPI snapshot gate the web client and effort is free under the open gate; orchestration None.

PROMPT: Step 5 — Web Foundation
MODEL: Claude Opus 5
BACKUP: GPT-5.3 Codex
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: multi-file TypeScript coding with agentic tooling setup, container build, and browser test runs. PICK: Claude Opus 5 is S-tier in coding and S-tier in agentic (Terminal-Bench 2.1 89.1), A-tier in multimodal for screenshot review, and supersedes Opus 4.8. EFFORT: Max effort with thinking on because the typed client, pages, image, and CI jobs are cross-cutting and the flat-funding gate makes lower effort a pure quality loss; orchestration None.

PROMPT: Step 6 — QA + verify_phase01.py
MODEL: Claude Opus 5
BACKUP: GPT-5.3 Codex
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: mechanical translation of the Steps 1–5 deliverables into numbered static checks, mode dispatch, and a CI matrix entry. PICK: Claude Opus 5 is S-tier in coding (Terminal-Bench 2.1 89.1); the open flat-funding gate suspends tier-down for routine work, so the funded frontier model takes it at zero marginal cost. EFFORT: Max effort with thinking on because effort is free here and this script gates every later phase's CI; orchestration None.
```

---

## Not in scope (from product roadmap)

Per [`ROADMAP.md`](../ROADMAP.md) Phase 1 and §6 "Out of Scope":

- Case, charge, disposition, sentence, or defendant data of any kind,
  synthetic or real; the synthetic generator and connector are
  Phase 2, and the first real case corpus is Phase 5.
- Any metric, metric registry, provenance trace, compare page, or
  coverage page beyond the Phase 2 placeholder note; metrics and the
  first milestone are Phase 3.
- Entity resolution beyond exact FJC identifier matching; the
  framework and review queue are Phase 2, probabilistic linkage is
  Phase 7.
- Deployment to any shared or public environment; production is
  Phase 8.
- The corrections workflow, admin tools, and suppression mechanism;
  Phases 3 and 6.

Additionally not in scope for this phase:

- Ingesting the FJC `demographics.csv`, `education.csv`,
  `professional-career.csv`, or nominations files; only identity and
  service files are needed for the judge page, and demographic fields
  have no documented purpose yet.
- CourtListener linkage for federal judges and courts; Phase 7.
- Edge rate limiting and response caching beyond the in-process
  limiter and `Cache-Control` headers; the API is local-only until
  Phase 8.
- Accessibility audit against WCAG 2.1 AA; Phase 1 applies the
  basics (landmarks, focus, table semantics) and Phase 8 audits.
- A coverage map; Phase 7 adds it with the second real jurisdiction.

---

_This roadmap is the execution plan for Phase 1. Update step status as
each is completed. After all steps and verification pass, Phase 1 is
complete and Phase 2 (Synthetic Justice Dataset, Entity Resolution, and
Case Timelines) inherits the complete canonical schema, the connector
protocol and runner, the API conventions, and the web foundation on
which the synthetic connector, the entity-resolution framework, and the
case pages are built._
