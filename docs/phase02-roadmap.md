<!-- docs/phase02-roadmap.md -->
# Phase 2 Roadmap — Synthetic Justice Dataset, Entity Resolution, and Case Timelines

**Status:** Complete — 2026-09-19

## Overview

Phase 2 opens the gate to every analytic the platform will ever publish:
before a single real case record exists, it makes the whole pipeline
demonstrable and golden-testable on a deterministic synthetic justice
dataset with known truth. A seeded generator writes source-format files
plus a `truth/` directory the canonical database never sees; a
`synthetic` connector loads those files through the same fourteen-step
runner real data will use, extending the runner to every case-level
table of the canonical model; an entity-resolution framework resolves
persons in auditable stages with a manual-review queue and an
append-only audit log; the API and web app gain case detail, case
timelines, judge case lists, and a coverage page v0; and Hypothesis
property tests plus a committed golden fixture become the permanent
regression harness that Phase 3's metrics engine and Phase 7's
probabilistic linkage are tested against. Phase 2 covers the brief's
development phase 2 (Synthetic Justice Dataset), the case portions of
phases 4 (Core API) and 6 (Web Application), and the testing strategy's
property tests and golden dataset.

Phase 2 does NOT compute any metric, publish any rate, or build the
metric registry (Phase 3); it does NOT ingest any real case data
(Phase 5); it does NOT implement probabilistic record linkage beyond a
stubbed scoring interface (Phase 7); and it does NOT deploy anything
beyond the maintainer's machine and the repository's CI. The
expected-metric values the generator writes into `truth/` are
expectations for Phase 3 to meet, not numbers Phase 2 publishes.

The phase lands in 6 layers:

1. **Deterministic synthetic generator** — the `judgemetrics/synthetic/`
   package (`config.py` scale specs, `rng.py` seeded streams,
   `wordlists.py` names from word lists, `world.py`, `cases.py`,
   `edge_cases.py`, `truth.py`, `writer.py`, `generate.py`), the CLI
   `judgemetrics synthetic generate --seed <int> --scale golden|demo
   --out <dir>` and `synthetic verify <dir>`, source-format CSVs under
   `<out>/source/`, a `manifest.json` with the sha256 of every file, a
   `truth/` directory (true person identities, true subsequent events,
   entity-resolution expectations, expected metric values), the golden
   fixture committed under `tests/fixtures/golden/`, and
   `docs/SYNTHETIC_DATA.md`.
2. **Synthetic connector, case-level publishing, and `seed`** — the
   case-level drafts (`PersonDraft`, `CaseDraft`, `CasePartyDraft`,
   `JudgeAssignmentDraft`, `ChargeDraft`, `CourtEventDraft`,
   `DecisionDraft`, `SentenceDraft`, `JusticeEventDraft`) in
   `ingest/base.py`, their publishers in `ingest/runner.py`, migration
   `0003_case_level_natural_keys`, the `judgemetrics/ingest/synthetic/`
   connector with `source_type = synthetic`, hashed person identifiers
   under a peppered `person_identifier`, the production refusal proven
   with the real connector, `judgemetrics seed`, and the `seed` target.
3. **Entity-resolution framework v0, review queue, and audit log** —
   `judgemetrics/entity_resolution/` (features, deterministic stage,
   rule stage, `Scorer` protocol with the probabilistic stage stubbed,
   per-entity-type thresholds, the queue, the merge), migration
   `0004_entity_resolution_review` (candidate stage, decision
   timestamp, reviewer, reason; `person.merged_into_person_id`; the
   append-only `audit_log`), pipeline step 10 for persons,
   `judgemetrics er run|review list|review decide`, and
   `docs/ENTITY_RESOLUTION.md`.
4. **Case API, case pages, and coverage v0** — `GET /api/v1/cases/{id}`,
   `/cases/{id}/timeline`, `/judges/{id}/cases`, `/coverage`; case
   numbers in `/search`; `synthetic` flags on every summary, detail,
   and provenance block; judge detail case counts and coverage dates;
   the web `/cases/[caseId]` page, the judge page's cases panel and
   `/judges/[judgeId]/cases` list, `/coverage` v0, the site-wide
   synthetic-data banner and per-entity badge; regenerated
   `docs/openapi.json` and `web/lib/api/schema.d.ts`; Playwright
   coverage of the case flow.
5. **Property tests, golden regression suite, and the scratch test
   database** — `tests/property/` (Hypothesis: a subsequent event never
   precedes its index event; rerunning an ingestion produces no
   duplicates; identical deterministic identifiers resolve
   consistently), `tests/golden/` (entity-resolution expectations hold
   exactly; regenerating the golden seed is byte-identical to the
   committed fixture), and `JUDGEMETRICS_TEST_DATABASE_URL` so the
   migration round-trip and fixture-ingesting tests stop emptying a
   local live ingest.
6. **QA + `verify_phase02.py`** — verification script (`--fast`,
   `--py`, `--node`, `--e2e`, `--security`, `--all`, `--post`),
   `docs/phase02-qa-findings.md` rollup, the `phase-verify.yml` matrix
   entry `02` with its required context, and the status update in
   `docs/ROADMAP.md`.

The ship test for Phase 2 is straightforward: `uv run poe seed`
populates a database meeting the brief's minimums (at least 5 courts,
20 judges, 5,000 cases, 3,000 defendants) from a fixed seed, a rerun
creates zero new canonical rows, and two generator runs from the same
seed produce byte-identical source files; the golden entity-resolution
expectations hold exactly (planted duplicates merge, planted ambiguous
pairs land in the review queue, distinct persons never merge) and every
candidate row carries features, score, model version, and decision; a
synthetic case page is reachable from a synthetic judge page and renders
timeline, charges, attributed decisions with actor badges, disposition,
sentence, and source citations; every public surface labels synthetic
data and the ingest runner refuses a synthetic source in the production
environment (test); the Hypothesis property tests and `uv run python
scripts/verify_phase02.py --fast` are green on Ubuntu CI with the
`phase-verify.yml` matrix entry `02` green; and the security gate is
clean, synthetic names come from word lists only, and
`person_identifier` is unreachable through any public route (contract
test over the OpenAPI document and the database grants).

**Pre-requisite:** Phase 1 closed (tag `v0.1.0-phase-1`, 2026-09-16):
its canonical schema is what the case-level drafts publish into, its
connector protocol and runner are what the synthetic connector plugs
into, its API conventions (`schemas/` → `services/` → `repositories/`,
`StrictQuery`, `Page`, `Provenance`, the OpenAPI snapshot) are what the
case routes extend, and its web foundation (generated client,
`ApiResult`, `force-dynamic` pages, Vitest and Playwright) is what the
case pages are built on.

**Dependency:** Phase 3 (Metrics Engine and the Complete Local Demo)
does not start until Phase 2's V-checks are green; it inherits the
seeded database, the `truth/metrics.json` expectations its registry must
reproduce exactly, the resolved persons and `justice_event` rows its
index events and outcome windows are computed over, the case pages its
judge-page drill-down links to, and the golden fixture as its permanent
regression harness. Phase 7 inherits the `Scorer` protocol and the
review queue for probabilistic linkage.

**Design rationale (truth outside the database, resolution as a
pipeline step).** The generator writes a `truth/` directory beside the
source files rather than embedding true identities in the source rows,
because the point of the exercise is that the canonical database sees
only what a real source would expose — participant ids, names, partial
dates of birth, case linkage — and the tests compare what the pipeline
derived against what the generator knows. Entity resolution runs inside
the runner as the brief's pipeline step 10 rather than as a separate
batch job, so provenance and idempotency are inherited rather than
re-implemented, and it is also re-runnable on demand (`judgemetrics er
run`) so Phase 7's probabilistic stage can be introduced without a
re-ingest. The audit log lands in Step 3 rather than Step 4 (where the
parent roadmap lists it) because the first writer of an administrative
decision is `er review decide`, and a log that no code writes to is not
a deliverable. The golden fixture is committed in Step 1 (it is the
generator's output at golden scale) so Steps 2 and 3 can test against it
immediately; Step 5 turns it into the permanent regression suite.

**Branch strategy.** Every step in this phase lands on its own
short-lived feature branch (`feature/phase02-step{M}-<slug>`), opens a
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
git checkout -b feature/phase02-step{M}-<slug>
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
worktree add -b feature/phase02-step{M}-<slug> .worktrees/<slug>
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
scan clean (`detect-secrets`), SAST clean (`bandit` over `src` and
`alembic`; `eslint-plugin-security` in `web/`), dependency audit clean
(`pip-audit --strict --require-hashes` over `uv.lock` via
`scripts/audit_deps.py`; `pnpm audit --audit-level=high`), and a diff
review confirming no sensitive data and no new insecure pattern. This
gate is wired into the `pre-commit` hook (installed in Phase 1) and
re-run in CI together with the container image scan, so a security
issue introduced while implementing a step is caught during development
— before it reaches the branch, the PR, or `main`. See the parent
ROADMAP "Security & privacy strategy" → "Per-step security gate" for
the canonical checks; each step's XML `<task>` carries a `<security>`
block restating them, and each step's Acceptance Criteria ends with a
security check. Phase 2 is the first phase that handles person-level
records — synthetic ones — and it fixes the pattern every later phase
relies on: person names and dates of birth exist in the canonical
database only as peppered hashes in the restricted `person_identifier`
table, the public surface carries only `public_person_key`, the pepper
is a `SecretStr` setting that never appears in a log line, and synthetic
names come from word lists, never from any list of real people.

**Deploy-and-verify rule.** Merged is not deployed, and deployed is
not released. Every step header carries a `**Deploys:**` line naming
the surface and environment the step's merge reaches — or `nothing
beyond merge`. In Phase 2 the only surfaces a merge reaches are the
repository's workflow files (live on merge) and the maintainer's local
environment (`uv run poe up`, `migrate`, `seed`, `dev-api`, `dev-web`);
no step deploys to a shared environment. Where a step's Deploys line
names a surface, its acceptance criteria carry a **Deployed &
verified** bullet that must be green before the step is declared
complete. A step that introduces a required environment variable
(`JUDGEMETRICS_IDENTIFIER_PEPPER` in Step 2,
`JUDGEMETRICS_TEST_DATABASE_URL` in Step 5) verifies at kickoff that
`.env.example` documents it, that the local `.env` carries a value, and
that `ci.yml` and `phase-verify.yml` set it where a job needs it.

**Triage rule.** Findings surfaced while executing a step are
classified before they are acted on, per the parent ROADMAP "Defect
handling & triage": spec rot → edit this roadmap's affected `<task>`
block now; upstream gap → patch the earlier step's prompt and add it
to the carry-over checklist; implementation bug → fix in-step only if
it blocks this step's acceptance criteria, otherwise an issue and its
own branch in a fresh conversation; architectural question → an issue
for a future phase; process improvement → recorded where the next
conversation will read it (this roadmap or `AGENTS.md`); data-semantics
finding → edit the versioned rule, threshold, or truth definition and
bump its version; data-access question → recorded in `docs/ROADMAP.md`
"Unresolved data-access questions", never answered by guesswork;
security finding → jumps the queue by severity. A step's PR contains
the step plus blocking fixes only, and lists the issues it opened.
`docs/phase02-qa-findings.md` is the rollup: every finding, its class,
and the guard added so the class cannot recur. Phase 1's carry-over
checklist (`docs/phase01-qa-findings.md` "Pre-ship items") is owned as
follows: the scratch test database → Step 5; word similarity for
surname-only search → not in this phase (issue); the runtime API origin
for the web image → Phase 8; ESLint 10 → Dependabot; `verify_phase02.py`
→ Step 6.

**Step lifecycle.** Every step in this phase follows the exact same
six-stage lifecycle, in order, with no exceptions. Each stage is a
hard checkpoint — if a stage is skipped, branch protection or the next
step's Stage 1 will fail loudly, and that is the safety net. AI coding
agents MUST execute all six stages before declaring a step complete.

1. **Create the branch.** Before any Read / Edit / Bash, run
   `git checkout -b feature/phase02-step{M}-<slug>` from a clean,
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
   commit. On the maintainer's machine, stop the local API before
   `uv run poe gate` or `git commit` (the editable reinstall cannot
   replace a running `judgemetrics.exe`).

3. **Open the PR.** `gh pr create --base main --head <branch>` with a
   Conventional Commits title and a body that references this roadmap
   step and its acceptance criteria. One PR per step; never bundle two
   steps into one PR.

4. **Wait for green checks, then squash-merge.** Every required status
   check (the aggregate `test` gate from `ci.yml`, `phase-verify (01)`,
   and from Step 6 on `phase-verify (02)`) must report success. If the
   PR goes BEHIND main while waiting, refresh with
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
   `docs/ROADMAP.md` (completed items, known issues, any new unresolved
   data-access question). Once the PR is merged and every one of this
   step's acceptance criteria is affirmatively met, say so plainly. End
   your final response with an explicit, unhedged completion line —
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

## Current State (as of Phase 1)

### Ingest and connector surface

- `src/judgemetrics/ingest/base.py` defines the brief's
  `SourceConnector` protocol (`source_id`, `parser_version`,
  `source_info`, `discover`, `fetch`, `validate_raw`, `parse`,
  `normalize`), the optional `SupportsCheckpoint` protocol, the frozen
  value types (`SourceArtifact`, `RawArtifact` with `from_bytes`,
  `from_path`, and `unchanged`, `ValidationResult`,
  `SourceRecordDraft` with `record_type`, `SourceInfo`), and exactly
  four canonical drafts — `JurisdictionDraft`, `CourtDraft`,
  `JudgeDraft` (keyed on `identity_key`), `JudgeServiceDraft` — each
  with a `natural_key`. `CanonicalRecord` is their union; the docstring
  says "case-level drafts arrive in Phase 2". Step 2 adds nine drafts.
- `src/judgemetrics/ingest/runner.py` implements the fourteen steps
  (`run_ingest(settings, source_id, *, force, from_fixture)`), with
  `_resolve` doing exact external-id matching for judges and exact
  `(canonical_name, court_type)` for courts, `_publish` dispatching to
  `_upsert_jurisdictions`, `_upsert_courts`, `_upsert_judges`,
  `_upsert_services` (`INSERT … ON CONFLICT DO UPDATE` writing only
  changed rows, JSONB merged with `||`), `PublishedIds` mapping natural
  keys to ids for issue linkage, `_refusal_reason` (a connector whose
  `source_info.source_type == "synthetic"` or any `--from-fixture`
  ingest is refused when `settings.env == "production"`, recorded as
  `refused`), and `recompute_metrics` as a no-op hook for Phase 3. The
  run row is committed first; the publish is one transaction.
  `--from-fixture DIR` reads each discovered artifact from
  `<DIR>/<external_id>` (plain file names only).
- `src/judgemetrics/ingest/registry.py` registers connectors by
  `source_id` through `@register`; `BUILTIN_CONNECTOR_MODULES` lists
  only `judgemetrics.ingest.fjc.connector`. `docs/DATA_SOURCES.md`
  already carries a `synthetic` register entry ("by construction",
  phase 2, redistribution n/a) describing the generator, the `truth/`
  directory, and the handling rules, so a synthetic connector may be
  registered without a new verification.
- `src/judgemetrics/ingest/fjc/` is the connector pattern to mirror:
  `schema.py` (verified header set → drift warning; expected set → the
  run fails naming the header), `parse.py` (Polars string-only parsing
  projected to expected columns), `normalize.py` (canonical-domain
  mapping only), `sources.py`, `connector.py`. `quality/checks.py`
  produces `IssueDraft(entity_type, entity_key, severity, issue_code,
  description, source_record_id)` rows the runner persists as
  `data_quality_issue`; today it checks service dates, overlaps,
  missing start dates, and provenance.
- `src/judgemetrics/cli.py` exposes `db upgrade|downgrade|current`,
  `serve`, `ingest list-sources|run|runs`, `openapi export`. There is
  no `synthetic`, `seed`, or `er` command group. `pyproject.toml`
  `[tool.poe.tasks]` has `up`, `down`, `migrate`, `dev-api`, `dev-web`,
  `ingest-fjc`, `gate`, `check`, `kit`; its comment reserves `seed`,
  `compute-metrics`, and `bootstrap` for later steps, and the
  `Makefile` mirrors every target.

### Data and schema surface

- Every case-level table exists from the baseline
  (`alembic/versions/0001_baseline.py`; models in
  `db/models/cases.py`, `persons.py`, `resolution.py`): `court_case`
  (unique `(court_id, case_number_normalized)`), `case_party`,
  `judge_assignment`, `charge` (`person_id` NOT NULL), `court_event`,
  `decision` (`person_id`, `actor_type`,
  `judicial_discretion_classification` NOT NULL; `decision_value`
  JSONB), `pretrial_release` (one per decision), `sentence`,
  `person` (`public_person_key` unique, `resolution_status`,
  `resolution_confidence`; no name column by design),
  `person_identifier` (restricted: `identifier_type`, `value_hash`,
  `encrypted_value`, `source_record_id`; `REVOKE ALL` from
  `judgemetrics_app`), `justice_event`, and
  `entity_resolution_candidate` (`entity_type`, `left_record_id`,
  `right_record_id`, `match_probability`, `decision` enum
  `matched|rejected|review`, `features` JSONB, `model_version`). None
  of them has rows. Revision `0002_ingest_provenance` added
  `source_record_id` and natural-key unique indexes (`NULLS NOT
  DISTINCT`) for the reference entities only; the case-level tables
  have no natural-key indexes and no column for a source row id, so
  Step 2's upserts need migration `0003`.
- The case-level vocabularies (`case_type`, `status`, `party_type`,
  `assignment_type`, `event_type`, `decision_type`,
  `judicial_discretion_classification`, `release_type`, charge
  `disposition`, `severity`, `offense_category`, `justice_event.
  event_type`) are free text until a versioned registry defines them
  (`docs/ROADMAP.md` known issues). Phase 2 fixes the first versioned
  vocabulary in `data/reference/case_vocabulary.yaml` (Step 2), which
  the synthetic connector emits and Phase 5's real connectors map onto.
- `docs/DATA_MODEL.md` documents the twenty-three tables, natural keys,
  indexes, and grants; `docs/ARCHITECTURE.md` documents the pipeline,
  the raw lake, idempotency, refusals, roles, the API, and the web
  tier. `.gitignore` already excludes `data/synthetic/`, and
  `data/README.md` already describes it and names
  `tests/fixtures/golden/` as the tracked golden fixture.
- `judgemetrics.security.crypto` provides Fernet encryption for
  `correction_request.requester_contact` under
  `JUDGEMETRICS_CORRECTION_CONTACT_KEY`; there is no identifier pepper
  setting yet. The `Settings` class (`config.py`, `JUDGEMETRICS_`
  prefix, `.env` loaded only when `env == local`, `SecretStr` for
  secrets) is where Step 2 adds `identifier_pepper` and
  `synthetic_dir`.

### API and web surface

- API v1 (`docs/API.md`, `docs/ARCHITECTURE.md` "Public API v1")
  serves `/judges`, `/judges/{id}`, `/judges/{id}/service`, `/courts`,
  `/courts/{id}`, `/jurisdictions`, `/jurisdictions/{id}`, `/search`
  through `api/routes/*.py` → `services/` → `repositories/` →
  `db/models`, with `schemas/common.py` (`Page[T]`, `Provenance`
  with `source`, `external_record_id`, `retrieved_at`, `raw_sha256`,
  `parser_version`, `ingest_run_id`; `ErrorBody`), `api/deps.py`
  (`get_session`, `PageParams`, `StrictQuery`), the `/search` token
  bucket, `count(*) OVER ()` pagination, the query-count guard
  (`tests/integration/test_query_counts.py`: detail ≤ 3 statements,
  lists and search ≤ 2), and the committed `docs/openapi.json` diffed
  by `tests/unit/test_openapi.py` (regenerate with `uv run
  judgemetrics openapi export`). There is no `/cases`, `/coverage`, or
  `/judges/{id}/cases` route, no `synthetic` flag on any response, and
  `/search` matches judges and courts only.
- `web/` (Next.js 16, App Router, TypeScript strict, Tailwind 4,
  shadcn/ui, pnpm 10 via corepack with `cwd=web/`) renders `/`,
  `/search`, `/judges/[judgeId]`, `/courts/[courtId]`, `/methodology`,
  `/coverage` (a Phase 2 stub), `/about`. `web/lib/api/client.ts`
  helpers return `ApiResult` and never throw; `web/lib/api/schema.d.ts`
  is generated from `docs/openapi.json` by `pnpm generate:api` and
  diffed by `schema-freshness.test.ts`; every data page is
  `force-dynamic`. Components: `provenance-panel.tsx`, `badges.tsx`,
  `service-table.tsx`, `search-form.tsx`, `states.tsx`
  (`ErrorState`/`EmptyState`), `site-header.tsx`, `site-footer.tsx`.
  The home page's coverage tile says "Case, charge, and disposition
  data arrive in Phase 2". Playwright `web/tests/e2e/smoke.spec.ts`
  runs six scenarios against the FJC fixture ingest the CI `e2e` job
  performs (`judgemetrics ingest run fjc --from-fixture
  tests/fixtures/fjc`); Step 4 adds the golden synthetic ingest to that
  job and a case scenario.

### Security & sensitive-data surface

- Phase 2 handles synthetic person-level records: names, partial dates
  of birth, source participant ids, charges, and outcomes for people
  who do not exist. The controls that must hold anyway, because Phase 5
  reuses them for real records: `person_identifier` is the only table
  that stores name, date-of-birth, and source-id material, as
  `sha256(pepper ‖ normalized value)` hashes (`value_hash`) with
  `encrypted_value` left NULL in Phase 2; the pepper is
  `JUDGEMETRICS_IDENTIFIER_PEPPER` (`SecretStr`, required, placeholder
  in `.env.example`, generated per environment, never logged — the
  scrubber's denylist in `logging.py` gains `pepper` and
  `identifier_pepper`); the app role keeps `REVOKE ALL` on
  `person_identifier` and gains nothing on `audit_log`; every public
  response carries only `public_person_key`; the OpenAPI document
  contains no schema field named `value_hash`, `encrypted_value`,
  `date_of_birth`, or `person_identifier` (contract test, Step 4).
- Synthetic names are composed from word lists in
  `synthetic/wordlists.py` (dictionary words: colours, trees, minerals,
  birds, weather, rivers) and a static check plus a unit test assert
  that every generated name token is in those lists; no list of real
  people is ever read. Synthetic courts and jurisdictions carry
  "Synthetic" in their canonical names, the source is
  `source_type = synthetic`, and the API exposes `synthetic: true` on
  every row derived from it.
- The gate is unchanged: `.pre-commit-config.yaml` (ruff, mypy, bandit,
  `detect-secrets` with `.secrets.baseline`, `pip-audit` at pre-push),
  `ci.yml` (`python`, `security`, `web`, `e2e`, `container`, aggregate
  `test`), `phase-verify.yml`. New dependencies in this phase:
  `hypothesis` (dev, Step 5) and `pyyaml` promoted from dev to runtime
  for the vocabulary and threshold files (Step 2) — each must pass
  `pip-audit --strict`.

### Operations & observability surface

- The runtime surface is still the local API (`/api/v1/health`,
  `/api/v1/ready`) and the CI checks; there is no deployed environment,
  scheduled job, or metered dependency. Phase 2 adds one operator
  command that must be observable: `uv run poe seed` logs generation
  and ingest counts and writes an `ingest_run` row whose status is the
  health signal; a failed seed leaves a `failed` run with a
  `failure_reason`. The phase's alarm remains the required checks
  (`test`, `phase-verify (01)`, and from Step 6 `phase-verify (02)`),
  which Step 6 exercises with a deliberately broken check.

### Documentation surface

- `ROADMAP.md` §4 Phase 2, `docs/ROADMAP.md` (status; Phase 2 "not
  started"), `AGENTS.md` (architectural decisions through Phase 1),
  `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `docs/API.md`,
  `docs/DATA_SOURCES.md` (`synthetic` entry), `data/README.md`,
  `docs/phase01-roadmap.md`, `docs/phase01-qa-findings.md`, and this
  file exist. `docs/SYNTHETIC_DATA.md` (Step 1) and
  `docs/ENTITY_RESOLUTION.md` (Step 3) are created in this phase; the
  brief's `METHODOLOGY.md`, `PRIVACY.md`, and `DEPLOYMENT.md` belong to
  later phases.

### Verification surfaces

- `scripts/verify_phase01.py` exists and is the structural template
  (standard-library only; mutually exclusive argparse modes `--fast`,
  `--py`, `--node`, `--e2e`, `--security`, `--all`, `--post`, default
  `--fast` plus `--py`; numbered `check_NN()` functions returning a
  failure reason or `None`; `[PASS] NN` / `[FAIL] NN — reason` lines;
  subprocess suites with argument lists over PATH-resolved `uv`,
  `pnpm` run with `cwd=web/`, and `gh`; the V-matrix read partly
  through `gh pr checks`; a summary table; exit 0/1). A unit test
  (`tests/unit/test_phase01_verification.py`) runs `--fast`, tying the
  aggregate `test` check to the script.
- `.github/workflows/phase-verify.yml` matrix includes `"01"`; its
  check `phase-verify (01)` is a required context on `main` beside
  `test` (the `gh api` command that patches the required contexts is
  recorded in `CONTRIBUTING.md` "Repository settings"). Phase 2 adds
  `"02"` and the context `phase-verify (02)`.

---

## Execution Order

```
Step 1  (synthetic generator)            judgemetrics/synthetic/ package,
                                          seeded streams, word-list names,
                                          source CSVs + manifest + truth/,
                                          `synthetic generate|verify`,
                                          tests/fixtures/golden/,
                                          docs/SYNTHETIC_DATA.md
                                          → implement
  ↓
Step 2  (synthetic connector + seed)     nine case-level drafts, runner
                                          publishers, migration 0003,
                                          case_vocabulary.yaml, hashed
                                          person identifiers + pepper,
                                          ingest/synthetic/ connector,
                                          `judgemetrics seed`, seed target
                                          → implement
  ↓
Step 3  (entity resolution v0)           entity_resolution/ package (stages,
                                          Scorer stub, thresholds, queue,
                                          merge), migration 0004 (candidate
                                          columns, merged_into, audit_log),
                                          pipeline step 10, `er run|review`,
                                          docs/ENTITY_RESOLUTION.md
                                          → implement
  ↓
Step 4  (case API + pages + coverage)    /cases/{id}, /cases/{id}/timeline,
                                          /judges/{id}/cases, /coverage,
                                          case numbers in /search, synthetic
                                          flags, case page, judge cases
                                          panel + list, coverage page v0,
                                          banner + badge, openapi + schema
                                          regenerated, Playwright case flow
                                          → implement
  ↓
Step 5  (property tests + golden)        hypothesis, tests/property/,
                                          tests/golden/, golden README,
                                          JUDGEMETRICS_TEST_DATABASE_URL and
                                          the scratch database
                                          → implement
  ↓
Step 6  (QA + verify_phase02.py)         scripts/verify_phase02.py
                                          + docs/phase02-qa-findings.md
                                          + phase-verify.yml matrix entry 02
                                          + required context + ROADMAP status
                                          → create

--- post-implementation ---

V1  Two generator runs from one seed are byte-identical; demo scale
    meets the brief's minimums; every planted edge case is present;
    names come from word lists; the golden fixture matches its
    manifest.
V2  `seed` populates the database through the runner with full
    provenance; a rerun creates zero canonical rows; the synthetic
    source is refused in production; person material exists only as
    peppered hashes in person_identifier.
V3  Planted duplicates merge, ambiguous pairs queue, distinct persons
    never merge; every candidate carries features, score, model
    version, decision; review decisions are audited append-only.
V4  Case, timeline, judge-cases, and coverage endpoints paginate,
    validate, carry provenance and synthetic flags; the case page is
    reachable from a judge page; person_identifier is unreachable
    through any public route; openapi.json and schema.d.ts match.
V5  Property tests and the golden regression suite are green in CI;
    the scratch database keeps a local live ingest intact.
V6  verify_phase02.py --fast and --security exit 0 on Ubuntu CI under
    the phase-verify.yml matrix entry 02.
```

Steps are sequential by dependency: Step 1's source files, manifest,
and golden fixture are what Step 2's connector parses and what its
integration tests ingest; Step 2's case-level drafts, publishers,
migration `0003`, and hashed person identifiers are what Step 3's
resolution stages read and what its merge rewrites; Step 3's resolved
persons and `public_person_key` values are what Step 4's case and
timeline responses expose, and Step 4's coverage endpoint is what the
synthetic banner reads; Step 5's property tests exercise the generator,
runner, and resolver of Steps 1–3 and its golden suite needs Step 4's
routes for the contract test over `person_identifier`; Step 6 verifies
every deliverable of Steps 1–5. This phase has no steps drawn in
parallel.

---

## Step 1 — Deterministic Synthetic Generator ✅

**Status:** Complete — PR #12 (2026-09-17)

> **Goal:** Land the generator with truth: `src/judgemetrics/synthetic/`
> (`config.py` with the `ScaleSpec` for `golden` and `demo`, `rng.py`
> with named seeded streams derived from one seed, `wordlists.py` with
> the dictionary-word lists every synthetic name is composed from,
> `world.py` building the synthetic jurisdiction, courts, judges, and
> persons, `cases.py` simulating each case's lifecycle — assignments,
> charges, events, pretrial decisions with a deciding judge, dismissals
> attributed to judges or prosecutors, convictions, sentences,
> subsequent cases, failures to appear, revocations — `edge_cases.py`
> planting duplicate source records, ambiguous person matches, and
> missing data, `truth.py` deriving true identities, true subsequent
> events, resolution expectations, and expected metric values,
> `writer.py` writing the source CSVs, `truth/`, and `manifest.json`
> with the sha256 of every file, and `generate.py` with
> `generate_dataset(seed, scale, out) -> Manifest`); the CLI
> `judgemetrics synthetic generate --seed <int> --scale golden|demo
> --out <dir>` and `judgemetrics synthetic verify <dir>`; the golden
> fixture committed under `tests/fixtures/golden/` (seed `7`, scale
> `golden`) with a README; `docs/SYNTHETIC_DATA.md` documenting the
> source format, the world model, the planted edge cases, the truth
> schema, and the determinism contract; with unit tests proving
> byte-identical regeneration, the brief's minimums at demo scale, the
> presence of every planted edge case, and word-list-only names. Steps
> 2 and 3 ingest and resolve what this step generates; Phase 3's
> registry must reproduce `truth/metrics.json`.

**Branch:** `feature/phase02-step1-synthetic-generator`

**Deploys:** nothing beyond merge — the operator runs
`uv run judgemetrics synthetic generate` locally; nothing enters the
database until Step 2.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Fable 5.1                      |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** This is one of the phase's two ceiling-class steps:
it designs a simulated justice world whose every downstream expectation
— resolution decisions, subsequent-event windows, the metric values
Phase 3 must reproduce exactly — is derived from the same seeded state,
while keeping the source files indistinguishable in shape from what a
real court export would carry — PRIMARY `coding`, SECONDARY `planning`,
High complexity with novel problem-solving and cross-file chain-of-thought
(the conditions that push the selector to its Extra High and Max rungs).
Fable 5.1 is rated S in coding and S in planning (HLE 59.1% and
Terminal-Bench 2.1 91.4, both at max) and supersedes Fable 5; under the
operator's balanced posture it is reserved for exactly this kind of
step, matching the parent roadmap's §8 assignment of Fable to the
generator-with-truth step, while Opus 5 (also S/S) takes the standard
implementation steps because Fable draws the Max budget down at about
twice Opus's rate. The Platform is Claude Code on the flat claude.ai Max
subscription, so the flat-funding gate is open: Effort `Max`, Thinking
`On`. Backup: GPT-5.6 Sol on Codex (ChatGPT Plus; Intelligence Extra
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
       feature/phase02-step1-synthetic-generator`
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
       rejected. Stop the local
       API before `uv run poe
       gate` or `git commit`.

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
       run the local generation and
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
       items, known issues). Once
       the PR is merged and every
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
    gate — the SAME gate wired
    into the pre-commit hook and
    re-run in CI:

    1. SECRET / PII SCAN. No
       credentials or tokens in
       the diff (`detect-secrets`).
       No real person's name, date
       of birth, or identifier
       anywhere in the generator,
       its word lists, or the
       golden fixture: names are
       composed from dictionary
       words only, and a unit test
       proves every name token is
       in `wordlists.py`.

    2. SAST. No new injection,
       unsafe deserialization,
       weak crypto, path
       traversal, or unsafe-eval
       pattern (`bandit`). The
       `--out` directory is
       resolved and created with
       `Path.mkdir(parents=True)`;
       the generator never deletes
       or overwrites a directory it
       did not create in this run
       (it refuses an existing
       `<out>/manifest.json` unless
       `--force`). `random.Random`
       is used for simulation, not
       for anything security-
       sensitive; annotate with
       `# nosec B311` and a
       justification.

    3. DEPENDENCY AUDIT. This step
       adds no runtime dependency
       (CSV via the standard
       library `csv` module; no
       Faker, no numpy). If one is
       added, it passes `pip-audit
       --strict`.

    4. SENSITIVE-DATA REVIEW.
       `truth/` is documentation
       of the simulation, not
       data about anyone; it still
       never enters the database
       (Step 2's connector
       discovers `source/` only).
       Logs carry counts and the
       seed, never rows.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 2.
    Step 1: deterministic
    synthetic generator.

    Current state (as of Phase 1):

    - The canonical schema, the
      connector protocol and
      runner, API v1, and the web
      foundation are merged; no
      case-level rows exist.
    - `docs/DATA_SOURCES.md` has a
      `synthetic` entry: generated
      locally from a seed, source
      files under
      `data/synthetic/<seed>/`
      (untracked), golden fixture
      under `tests/fixtures/golden/`
      (tracked), names from word
      lists, byte-identical runs.
    - `.gitignore` excludes
      `data/synthetic/`;
      `data/README.md` describes
      it.
    - `src/judgemetrics/cli.py` is
      a Typer app with `db`,
      `ingest`, and `openapi`
      groups; add a `synthetic`
      group.
    - `data/reference/us_states.csv`
      is the pattern for curated
      reference tables.

    Files to read (every file
    before drafting):
    - docs/brief/judgemetrics-
      master-project-specification.xml
      (`<synthetic_demo_dataset>`,
      `<canonical_data_model>`,
      `<event_attribution_model>`,
      `<entity_resolution>`,
      `<outcome_definitions>`,
      `<testing_strategy>`
      golden_dataset and
      property_tests,
      `<agent_working_rules>` on
      deterministic seeds).
    - ROADMAP.md §4 Phase 2 (2.1,
      2.5), Phase 3 (3.2, 3.3 —
      the metric set truth must
      carry expectations for), §5
      "Security & privacy
      strategy" data
      classification.
    - docs/DATA_SOURCES.md
      (`synthetic` entry).
    - docs/DATA_MODEL.md (the
      columns each source file
      must be able to fill).
    - src/judgemetrics/db/models/
      cases.py, persons.py,
      enums.py (ActorType values
      the source's decisions must
      express).
    - src/judgemetrics/ingest/
      base.py (what Step 2's
      connector will need from the
      files).
    - src/judgemetrics/cli.py,
      config.py, logging.py.
    - src/judgemetrics/
      normalization/names.py (the
      normalizer the connector
      will apply; generated names
      must round-trip through it).
    - tests/fixtures/fjc/README.md
      (fixture README pattern).
  </context>

  <goal>
    Ship a deterministic generator
    such that `uv run judgemetrics
    synthetic generate --seed 7
    --scale golden --out
    tests/fixtures/golden` and a
    second run into a temporary
    directory produce byte-
    identical files; `--scale demo`
    exceeds the brief's minimums
    and models every listed
    behaviour and edge case; and
    `truth/` records true
    identities, true subsequent
    events, resolution
    expectations, and expected
    metric values that Steps 3 and
    5 and Phase 3 test against.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      `src/judgemetrics/synthetic/
      config.py`: frozen dataclass
      `ScaleSpec(name, courts,
      judges, persons, cases,
      start_year, end_year,
      duplicate_source_records,
      ambiguous_person_pairs,
      split_person_pairs,
      missing_dob_share,
      missing_judge_share,
      missing_disposition_share)`
      and two constants: `GOLDEN`
      (3 courts, 6 judges, 40
      persons, 60 cases, years
      2019-2021, 3 duplicate
      records, 2 ambiguous pairs,
      2 split-person pairs, small
      missing shares — every
      planted case hand-checkable
      from `truth/README.md`) and
      `DEMO` (5 courts, 24 judges,
      3,200 persons, 5,200 cases,
      years 2016-2023, 40
      duplicates, 25 ambiguous
      pairs, 25 split pairs). Both
      exceed or meet the brief's
      minimums; a unit test
      asserts `DEMO` does. A
      `GENERATOR_VERSION = "1"`
      constant is written to the
      manifest and bumped whenever
      output for a fixed seed
      changes.
    </requirement>

    <requirement>
      `synthetic/rng.py`:
      `Streams(seed)` derives one
      `random.Random` per named
      stream (`world`, `persons`,
      `cases`, `events`,
      `edge_cases`) from
      `hashlib.sha256(f"{seed}:
      {name}")`, so adding a draw
      to one stream cannot change
      another; no call to
      `random` module-level
      functions, `datetime.now`,
      `uuid.uuid4`, `os.urandom`,
      or dict/set iteration order
      anywhere in the package
      (sorted iteration
      everywhere). Identifiers are
      formatted counters
      (`C-0001`, `J-0001`,
      `P-000001`, `SYN-2019-000123`
      as a case number, `CH-`,
      `EV-`, `DC-`, `SN-` for
      rows).
    </requirement>

    <requirement>
      `synthetic/wordlists.py`:
      `GIVEN_TOKENS` and
      `FAMILY_TOKENS` — dictionary
      words only (colours, trees,
      minerals, birds, weather,
      rivers; at least 150 each),
      no token that is a common
      real given name or surname
      by construction (the lists
      are reviewed in the PR), and
      `compose_name(rng) -> (given,
      family)`. Judge names and
      person names both come from
      these lists; judges get the
      prefix-free canonical name
      the FJC normalizer accepts
      (`normalize_person_name`
      round-trips). A unit test
      asserts every token of every
      generated name (golden and a
      demo sample) is in the
      lists.
    </requirement>

    <requirement>
      `synthetic/world.py`: one
      jurisdiction ("Synthetic
      State", type `state`,
      `state_code` `ZZ`), courts
      named "Synthetic County
      Circuit Court, Division N"
      (type `circuit`), judges with
      one or two service records
      (positions `circuit_judge`,
      `associate_judge`), start and
      end dates inside the scale's
      years, and persons with a
      true identity (`P-`), a
      composed name, a date of
      birth (missing for
      `missing_dob_share`), and an
      age band. Persons are the
      pool from which cases draw
      defendants; each demo person
      appears in 1-4 cases so
      subsequent cases exist.
    </requirement>

    <requirement>
      `synthetic/cases.py`: for
      each case, a court, a filed
      date, a case type
      (`felony`/`misdemeanor`), one
      to three charges from
      `data/reference/
      synthetic_offenses.csv`
      (offense category, severity,
      statute code `SYN-###`,
      description, violent flag —
      a curated table, not
      generated), one or more judge
      assignments (an initial
      assignment; a reassignment in
      a share of cases so multiple
      assignments per case exist),
      a pretrial decision by the
      assigned judge (release on
      recognizance, monetary bond
      with amount, or detention;
      `actor_type = judge`,
      discretion classification
      `discretionary`) or a
      statutory release
      (`actor_type =
      legislature_or_mandatory_rule`,
      classification `mandatory`)
      in a fixed share, court
      events (arraignment,
      hearings, a failure-to-
      appear event in a share of
      released cases, a bench
      warrant after it), a
      disposition per charge —
      dismissed by the prosecutor
      (`actor_type = prosecutor`),
      dismissed by the judge
      (`actor_type = judge`),
      acquitted (`jury`),
      convicted (plea or verdict)
      — a sentence for convictions
      (incarceration days,
      probation days, fine, or
      combinations; `sentence_at`
      after the disposition; the
      sentencing judge), and
      subsequent behaviour drawn
      from the person's latent
      propensity: a new case
      (another case row for the
      same person filed after the
      index decision), a failure
      to appear, a revocation
      event for a share of
      probation sentences. Every
      timestamp is derived from
      the filed date plus seeded
      offsets, strictly ordered
      (filed < assignment start <
      arraignment < pretrial
      decision < disposition <=
      closed; sentence after
      disposition; subsequent
      events after their index
      event) — the generator
      enforces the order and a
      unit test checks it.
      Timestamps are timezone-
      aware UTC ISO 8601 strings
      in the files.
    </requirement>

    <requirement>
      `synthetic/edge_cases.py`
      plants, after the clean
      world is built and with
      their own stream:
      (a) duplicate source
      records — a case (with its
      participants, charges,
      events, decisions) emitted
      twice, once verbatim and once
      with only formatting
      differences (case number
      with different spacing/
      case, name in different
      case, trailing whitespace)
      that the connector's
      normalization must collapse;
      (b) ambiguous person matches
      — two DISTINCT true persons
      sharing the same composed
      name and the same date of
      birth, in different courts,
      with no shared case; and two
      distinct persons sharing a
      name with one DOB missing;
      (c) split persons — one true
      person appearing under two
      different participant ids
      (a second id in a second
      court) with the same name,
      the same DOB, and a case
      linkage signal (the second
      case cites the first case
      number in a `related_case_
      number` column) — the rule
      stage must merge these;
      (d) missing data — the
      shares in `ScaleSpec`:
      missing DOB, a decision with
      no judge id (`actor_type =
      unknown`), a charge with no
      disposition, an event with
      no description. Each planted
      item is written to
      `truth/planted.csv`
      (kind, ids involved,
      expected pipeline
      behaviour).
    </requirement>

    <requirement>
      Source format (`<out>/
      source/`, CSV, UTF-8, `\n`
      newlines, header row, one
      file each, sorted by id):
      `courts.csv` (court_code,
      name, court_type,
      jurisdiction, state_code),
      `judges.csv` (judge_code,
      full_name, court_code,
      position, start_date,
      end_date), `cases.csv`
      (case_number, court_code,
      case_type, filed_date,
      closed_date, status,
      related_case_number),
      `participants.csv`
      (participant_id, case_number,
      court_code, party_type,
      full_name, date_of_birth,
      age_at_filing),
      `charges.csv` (charge_id,
      case_number, court_code,
      participant_id, statute_code,
      description, offense_
      category, severity,
      violent_flag, filed_at,
      disposed_at, disposition,
      disposition_actor),
      `assignments.csv`
      (assignment_id, case_number,
      court_code, judge_code,
      assignment_type, start_at,
      end_at), `events.csv`
      (event_id, case_number,
      court_code, participant_id,
      judge_code, event_type,
      event_at, actor, description),
      `decisions.csv` (decision_id,
      case_number, court_code,
      participant_id, judge_code,
      decision_type, decision_at,
      actor, discretion, release_
      type, bond_amount,
      detained, release_at,
      conditions), `sentences.csv`
      (sentence_id, case_number,
      court_code, participant_id,
      judge_code, sentence_at,
      incarceration_days,
      probation_days, fine_amount,
      components). Vocabularies are
      the ones Step 2 fixes in
      `data/reference/
      case_vocabulary.yaml`; write
      that file's values into a
      `synthetic/vocabulary.py`
      constant now so Step 2 lifts
      them verbatim. Empty string
      means missing.
    </requirement>

    <requirement>
      `synthetic/truth.py` writes
      `<out>/truth/`: `persons.csv`
      (true_person_id,
      participant_id, court_code —
      the true identity behind
      every participant),
      `subsequent_events.csv`
      (true_person_id, index_case_
      number, index_event_type,
      index_at, outcome_type ∈
      new_case|new_charge|
      reconviction|failure_to_
      appear|revocation, outcome_at,
      days_after), `resolution_
      expectations.csv` (left_
      participant_id, right_
      participant_id, expected_
      decision ∈ matched|rejected|
      review, reason), `planted.csv`
      (above), `metrics.json`
      (`truth_version`, and per
      judge_code and per court_code
      the ROADMAP §4 3.3 metric set
      computed from truth:
      eligible_cases, eligible_
      defendants, released_count,
      detained_count, release_
      share, fta_rate, new_case_
      rate and reconviction_rate
      per window 30/90/180/365/
      730/1095 with numerator,
      denominator, and the
      adequately-followed cohort
      given the corpus end date,
      judicial_dismissal_rate
      (judge-attributed
      dismissals over charges
      disposed while assigned),
      median_days_to_disposition,
      sentence distributions
      (median incarceration days
      by offense category) — each
      with its definition string),
      and `README.md` (how to read
      the files and, for the
      golden scale, the hand-
      checkable list of planted
      items). `truth/` is never
      read by any connector.
    </requirement>

    <requirement>
      `synthetic/writer.py` and
      `generate.py`:
      `generate_dataset(seed: int,
      scale: str, out: Path, *,
      force: bool = False) ->
      Manifest` writes `source/`,
      `truth/`, and `<out>/
      manifest.json` (`seed`,
      `scale`, `generator_version`,
      `truth_version`, `counts`
      per file, `files`: relative
      path → sha256 for every
      source and truth file,
      sorted). Refuse to write into
      a directory that already has
      a manifest unless `force`.
      `verify_dataset(out) ->
      list[str]` recomputes the
      hashes and returns
      mismatches. CLI: `judgemetrics
      synthetic generate --seed
      INT --scale golden|demo --out
      DIR [--force]` (default
      `--seed 20260916 --scale demo
      --out data/synthetic/<seed>`)
      printing the counts and the
      manifest path; `judgemetrics
      synthetic verify DIR` exiting
      1 on any mismatch. Log with
      `judgemetrics.logging`
      (seed, scale, counts —
      never rows).
    </requirement>

    <requirement>
      Golden fixture: run
      `judgemetrics synthetic
      generate --seed 7 --scale
      golden --out tests/fixtures/
      golden` and commit the
      result (`manifest.json`,
      `source/*.csv`, `truth/*`)
      plus `tests/fixtures/golden/
      README.md` (seed, scale,
      generator version, the
      regeneration command, and the
      rule that the fixture is
      regenerated — never hand-
      edited — when
      `GENERATOR_VERSION` bumps).
      The golden `truth/README.md`
      lists every planted item by
      id with its expected pipeline
      behaviour.
    </requirement>

    <requirement>
      Tests: `tests/unit/
      test_synthetic_generator.py`
      — golden regeneration into a
      temp directory is byte-
      identical to
      `tests/fixtures/golden/` (per
      file); `verify_dataset` on
      the fixture returns no
      mismatch; `DEMO` counts meet
      the brief's minimums (assert
      on `ScaleSpec` and on a demo
      generation run once per
      session into a temp dir,
      marked `slow` if it exceeds
      ten seconds — target under
      five); every name token is
      in the word lists; every
      planted kind appears in
      `planted.csv` in the
      configured quantity;
      temporal order holds for
      every case and every
      subsequent event; `truth/
      metrics.json` numerators
      never exceed denominators;
      two different seeds differ.
      `tests/unit/
      test_cli_synthetic.py` —
      generate refuses an existing
      manifest without `--force`;
      verify exits 1 after a byte
      is flipped in a copy.
    </requirement>

    <requirement>
      Docs: `docs/SYNTHETIC_DATA.md`
      (the world model, the source
      format with every column and
      vocabulary, the planted edge
      cases and what each must
      produce downstream, the
      `truth/` schema including
      the metric definitions and
      `truth_version`, the
      determinism contract and the
      `GENERATOR_VERSION` bump
      rule, the word-list rule);
      `data/README.md` (the
      `data/synthetic/<seed>/`
      layout and
      `data/reference/
      synthetic_offenses.csv`);
      `README.md` (the `synthetic
      generate` command); update
      the `synthetic` entry of
      `docs/DATA_SOURCES.md` with
      the file list; `AGENTS.md`
      (decisions: named streams,
      truth outside the database,
      manifest hashes, word lists);
      `docs/ROADMAP.md` (Step 1
      done; known issues).
    </requirement>

    <requirement>
      Filepath comment: every new
      Python, Markdown, CSV-adjacent
      README, and YAML file gets
      the repo-relative path as the
      first line where the file
      type accepts comments (CSV
      files carry none).
    </requirement>
  </requirements>
</task>
```

### Step 1 acceptance criteria

- `uv run judgemetrics synthetic generate --seed 7 --scale golden --out
  <tmp>` produces files byte-identical to `tests/fixtures/golden/`
  (unit test), and `judgemetrics synthetic verify tests/fixtures/golden`
  exits 0.
- `--scale demo` writes at least 5 courts, 20 judges, 5,000 cases, and
  3,000 defendants (persons) with multiple judge assignments, multiple
  offense categories, pretrial release and detention decisions with a
  deciding judge, dismissals attributed separately to judges and
  prosecutors, convictions, sentences, subsequent cases, failures to
  appear, and revocations (unit test over `ScaleSpec` and a demo run).
- `truth/planted.csv` lists every planted duplicate source record,
  ambiguous person pair, split person, and missing-data example in the
  configured quantities, and `truth/resolution_expectations.csv` names
  the expected decision for every planted pair.
- Every timestamp in every case is strictly ordered and every
  subsequent event in `truth/subsequent_events.csv` occurs after its
  index event (unit test); `truth/metrics.json` carries a
  `truth_version` and, for every judge and court, the Phase 3 metric
  set with numerator, denominator, and definition.
- Every generated name token is in `synthetic/wordlists.py` (unit
  test); no file under `src/judgemetrics/synthetic/` or
  `tests/fixtures/golden/` references a list of real people.
- `docs/SYNTHETIC_DATA.md`, `tests/fixtures/golden/README.md`, and the
  `data/README.md`, `README.md`, `docs/DATA_SOURCES.md`, `AGENTS.md`,
  and `docs/ROADMAP.md` updates exist; `uv run poe check` is green
  locally and in CI.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean
  (no real names, no credentials), SAST clean (`# nosec B311` justified
  on the simulation RNG only; no overwrite of a foreign directory),
  dependency audit clean — and `truth/` is documented as never entering
  the database.

---

## Step 2 — Synthetic Connector, Case-Level Publishing, and `seed` ✅

**Status:** Complete — PR #13 (2026-09-18)

> **Goal:** Load the generated dataset through the same path real data
> will use: extend `src/judgemetrics/ingest/base.py` with the nine
> case-level drafts (`PersonDraft`, `CaseDraft`, `CasePartyDraft`,
> `JudgeAssignmentDraft`, `ChargeDraft`, `CourtEventDraft`,
> `DecisionDraft` carrying an optional `PretrialReleaseDraft`,
> `SentenceDraft`, `JusticeEventDraft`), each with a `natural_key`;
> extend `ingest/runner.py` with their resolution (persons by exact
> source-identifier hash in this step; Step 3 adds the staged
> framework) and their publishers in dependency order; add migration
> `0003_case_level_natural_keys` (a `source_row_id` column and
> natural-key unique indexes on every case-level table, a partial
> unique index on `person_identifier` for stable source identifiers,
> `person.source_record_id`); fix the first versioned case vocabulary
> in `data/reference/case_vocabulary.yaml` loaded by
> `judgemetrics/normalization/vocabulary.py`; add
> `JUDGEMETRICS_IDENTIFIER_PEPPER` and `judgemetrics/security/
> identifiers.py` (`hash_identifier`) so names, dates of birth, and
> participant ids reach the database only as peppered hashes in
> `person_identifier`; land `ingest/synthetic/` (`schema.py`,
> `parse.py`, `normalize.py`, `connector.py` with `source_type =
> synthetic`) discovering `manifest.json` and the nine source files
> from `settings.synthetic_dir`; extend `quality/checks.py` with the
> brief's case-level checks; add `judgemetrics seed` and the `seed`
> target; prove the production refusal with the real connector; with
> unit tests per module and an integration test that ingests the golden
> fixture twice. Step 3 resolves what this step publishes; Step 4 reads
> it.

**Branch:** `feature/phase02-step2-synthetic-connector`

**Deploys:** nothing beyond merge — the operator runs `uv run poe
migrate` (revision `0003`) and `uv run poe seed` locally against the
Compose services.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** A large, correctness-sensitive, multi-file
implementation against fixed contracts — the Phase 1 connector and
runner patterns, the canonical schema, the generator's file format —
with a migration, a new settings surface, and integration tests
against PostgreSQL: PRIMARY `coding`, SECONDARY `agentic`, High
complexity by scope but a known pattern rather than novel design.
Claude Opus 5 is S-tier in coding and S-tier in agentic (Terminal-Bench
2.1 89.1) and supersedes Opus 4.8; under the operator's balanced posture
it is the funded frontier model for standard implementation steps,
while Fable 5.1 is held for the two design-heavy steps. The Platform is
Claude Code on the flat claude.ai Max subscription, so the flat-funding
gate is open: Effort `Max`, Thinking `On` — nothing is saved by running
lower, and the publishers' idempotency is what every later ingest
depends on. Backup: GPT-5.3 Codex on Codex (ChatGPT Plus; Intelligence
High), S-tier in coding from a different provider. Conversation is New
per phase-boundary hygiene.

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
       feature/phase02-step2-synthetic-connector`
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
       rejected. Stop the local
       API before `uv run poe
       gate` or `git commit`.

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
       run `uv run poe migrate` and
       `uv run poe seed` locally
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
       docs/ROADMAP.md (completed
       items, known issues). Once
       the PR is merged and every
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
       credentials or tokens in
       the diff (`detect-secrets`).
       `JUDGEMETRICS_IDENTIFIER_
       PEPPER` is a placeholder in
       `.env.example`
       (`# pragma: allowlist
       secret` if the scanner
       flags it), a real random
       value in the untracked
       `.env`, and a fixed test
       value only in `tests/
       conftest.py`.

    2. SAST. No new injection,
       unsafe deserialization,
       weak crypto, path
       traversal, or unsafe-eval
       pattern (`bandit`). Hashing
       is `hashlib.sha256` over
       `pepper + "\x00" +
       normalized value` (never
       md5, never unsalted);
       `yaml.safe_load` only;
       `settings.synthetic_dir` is
       resolved and every
       discovered file name is
       checked to be a plain file
       name inside it.

    3. DEPENDENCY AUDIT. `pyyaml`
       moves from the dev group to
       runtime dependencies; it
       and any other addition pass
       `pip-audit --strict`; the
       image scan stays clean.

    4. SENSITIVE-DATA REVIEW.
       `person` has no name or
       date-of-birth column and
       none is added; name, DOB,
       and participant-id material
       is written only to
       `person_identifier` as
       hashes, `encrypted_value`
       stays NULL in this phase;
       `charge`, `decision`,
       `sentence`, `court_event`,
       and `justice_event` carry
       `person_id` only; the app
       role's `REVOKE ALL` on
       `person_identifier` is re-
       asserted by the migration
       test; log lines carry counts
       and natural keys of cases
       and judges, never a
       participant name, DOB, hash,
       or the pepper (the scrubber
       denylist gains `pepper`,
       `identifier_pepper`,
       `value_hash`,
       `date_of_birth`,
       `full_name`).

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 2.
    Step 2: synthetic connector,
    case-level publishing, and
    `seed`.

    Current state (as of Phase 1,
    post-Phase-2 Step 1):

    - The generator writes
      `<out>/source/*.csv`,
      `<out>/truth/`, and
      `<out>/manifest.json`; the
      golden fixture is at
      `tests/fixtures/golden/`
      (seed 7); vocabularies are
      in `synthetic/vocabulary.py`.
    - `ingest/base.py` has four
      reference drafts;
      `ingest/runner.py` resolves
      and publishes only those;
      `_refusal_reason` already
      refuses `source_type ==
      "synthetic"` in production.
    - Case-level tables exist with
      no natural-key indexes and
      no source row id column.
    - `Settings` has no pepper and
      no synthetic directory.

    Files to read (every file
    before drafting):
    - docs/brief/judgemetrics-
      master-project-specification.xml
      (`<ingestion_framework>`,
      `<canonical_data_model>`,
      `<event_attribution_model>`,
      `<data_quality>` checks,
      `<privacy_and_legal_design>`).
    - ROADMAP.md §4 Phase 2 (2.2),
      §5 "Security & privacy
      strategy".
    - docs/SYNTHETIC_DATA.md
      (source format, vocabularies,
      planted edge cases).
    - docs/ARCHITECTURE.md (ingest
      pipeline, idempotency,
      refusals, roles).
    - docs/DATA_MODEL.md.
    - src/judgemetrics/ingest/
      base.py, runner.py,
      registry.py, store.py,
      fjc/connector.py,
      fjc/schema.py, fjc/parse.py,
      fjc/normalize.py.
    - src/judgemetrics/quality/
      checks.py.
    - src/judgemetrics/db/models/
      cases.py, persons.py,
      provenance.py, enums.py;
      alembic/versions/
      0002_ingest_provenance.py
      (migration pattern; grants).
    - src/judgemetrics/config.py,
      logging.py, cli.py,
      security/crypto.py,
      normalization/names.py.
    - src/judgemetrics/synthetic/
      vocabulary.py, generate.py.
    - tests/integration/
      test_fjc_ingest.py and
      conftest.py (the idempotency
      test pattern and
      `purge_run`).
    - tests/integration/
      test_migrations.py (round
      trip, grants).
  </context>

  <goal>
    Ship the case-level drafts and
    publishers, migration 0003, the
    versioned case vocabulary, the
    peppered identifier hashing,
    the synthetic connector, the
    case-level data-quality checks,
    and `judgemetrics seed` so that
    `uv run poe seed` populates a
    database exceeding the brief's
    minimums with full provenance
    and a rerun creates and updates
    zero canonical rows, while the
    same connector is refused when
    `JUDGEMETRICS_ENV=production`.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      `data/reference/
      case_vocabulary.yaml`
      (`version: 1`) fixing the
      values of `case_type`,
      `case_status`, `party_type`,
      `assignment_type`,
      `event_type` (arraignment,
      hearing, failure_to_appear,
      bench_warrant, trial,
      revocation, ...),
      `decision_type`
      (pretrial_release,
      dismissal, disposition,
      sentencing), `judicial_
      discretion_classification`
      (discretionary, mandatory,
      unknown), `release_type`
      (recognizance, monetary_bond,
      detained, statutory),
      `charge_disposition`
      (dismissed, acquitted,
      convicted_plea,
      convicted_verdict, pending),
      `severity`, `offense_
      category`, and `justice_
      event_type` (new_case,
      new_charge, reconviction,
      failure_to_appear,
      release_violation,
      revocation, rearrest). It
      must equal the constants in
      `synthetic/vocabulary.py`
      (unit test); `judgemetrics/
      normalization/vocabulary.py`
      loads it once
      (`yaml.safe_load`) and offers
      `require(kind, value)` raising
      `NormalizationError` for an
      unknown value and
      `UNKNOWN = "unknown"`
      handling where the brief
      allows it. Document in
      docs/DATA_MODEL.md that
      Phase 5 connectors map onto
      this vocabulary and bump
      `version` when it changes.
    </requirement>

    <requirement>
      `src/judgemetrics/security/
      identifiers.py`:
      `hash_identifier(pepper:
      SecretStr, kind: str, value:
      str) -> str` (sha256 hex of
      `pepper + "\x00" + kind +
      "\x00" + normalized value`,
      normalization per kind: names
      through `normalize_person_
      name`, dates as ISO, ids
      stripped and upper-cased).
      `Settings.identifier_pepper:
      SecretStr` (required; the
      test settings fixture sets a
      constant; `.env.example`
      placeholder; startup of the
      ingest CLI fails with a named
      error when unset).
    </requirement>

    <requirement>
      `ingest/base.py` drafts, all
      frozen with `natural_key`:
      `PersonDraft(identity:
      tuple[str, str] — (identifier
      kind, HASH); identifier_
      hashes: Mapping[str, str] —
      kind → hash for `source_
      participant_id`, `full_name`,
      `date_of_birth`, `name_dob`
      (present only when both
      exist); birth_year_known:
      bool)` — key ("person",
      kind, hash); `CaseDraft(
      court_key, case_number,
      case_number_normalized,
      case_type, filed_date,
      closed_date, status,
      source_row_id, related_case_
      number_normalized)` — key
      ("case", *court_key[1:],
      case_number_normalized);
      `CasePartyDraft(case_key,
      person_key, party_type,
      source_party_label,
      source_row_id)`;
      `JudgeAssignmentDraft(
      case_key, judge_key,
      assignment_type, start_at,
      end_at, source_row_id)`;
      `ChargeDraft(case_key,
      person_key, statute_code,
      description, offense_
      category, severity,
      violent_flag, filed_at,
      disposed_at, disposition,
      disposition_actor: ActorType
      | None, source_row_id)`;
      `CourtEventDraft(case_key,
      person_key | None, judge_key
      | None, event_type, event_at,
      description, actor_type,
      source_row_id)`;
      `PretrialReleaseDraft(
      release_type, bond_amount,
      conditions, release_at,
      detained_flag)`;
      `DecisionDraft(case_key,
      person_key, judge_key | None,
      decision_type, decision_at,
      decision_value, actor_type,
      judicial_discretion_
      classification, pretrial:
      PretrialReleaseDraft | None,
      source_row_id)`;
      `SentenceDraft(case_key,
      person_key, judge_key | None,
      sentence_at, incarceration_
      days, probation_days,
      fine_amount, components,
      source_row_id)`;
      `JusticeEventDraft(person_
      key, event_type, event_at,
      related_case_key | None,
      description, confidence)`.
      Natural keys for the case-
      level rows are ("<table>",
      *case_key[1:], source_row_id);
      justice events are keyed on
      (person hash, event_type,
      event_at, related case).
      Extend `CanonicalRecord`.
      Normalize case numbers with a
      new `normalization/
      case_numbers.py`
      (`normalize_case_number`:
      upper-case, strip whitespace
      and punctuation except `-`,
      collapse runs; unit-tested on
      the planted duplicate
      formats).
    </requirement>

    <requirement>
      Migration `alembic/versions/
      0003_case_level_natural_keys.py`
      (self-contained, reversible,
      `uv run alembic check`
      clean): `source_row_id` (Text
      NOT NULL, server default
      backfill not needed — tables
      are empty; keep NOT NULL) on
      `case_party`, `judge_
      assignment`, `charge`,
      `court_event`, `decision`,
      `sentence`; unique indexes
      `uq_<table>_case_source_row`
      on (`case_id`,
      `source_row_id`) for those
      six; `uq_justice_event_
      natural` on (`person_id`,
      `event_type`, `event_at`,
      `related_case_id`) `NULLS NOT
      DISTINCT`; `person.source_
      record_id` (nullable FK,
      last-substantive-writer like
      the reference entities);
      partial unique index
      `uq_person_identifier_stable`
      on (`identifier_type`,
      `value_hash`) `WHERE
      identifier_type IN
      ('source_participant_id')`
      (name and DOB hashes may
      legitimately repeat);
      `court_case.related_case_
      number_normalized` (Text,
      nullable, indexed). Re-assert
      grants for the app role
      (nothing new readable beyond
      the public tables) and the
      ingest role (DML on every
      case-level table).
      `test_migrations.py` gains
      the round trip through 0003
      and the grants assertion.
    </requirement>

    <requirement>
      `ingest/runner.py`:
      `_resolve` gains person
      resolution by exact
      `source_participant_id` hash
      (an existing
      `person_identifier` row of
      that type → that person;
      otherwise a new person with
      `public_person_key =
      secrets.token_urlsafe(12)`
      generated ONCE at insert and
      never rewritten by the
      upsert, `resolution_status =
      "deterministic"`) — a hook
      `resolve_persons(session,
      drafts, run)` that Step 3
      replaces with the staged
      pipeline; case-level drafts
      whose case, person, judge, or
      court cannot be resolved are
      rejected with a
      `data_quality_issue`
      (`unresolved_case`,
      `unresolved_person`,
      `unresolved_judge`) and
      counted, never silently
      dropped. `_publish` gains
      `_upsert_persons` (person +
      its identifier rows),
      `_upsert_cases`,
      `_upsert_parties`,
      `_upsert_assignments`,
      `_upsert_charges`,
      `_upsert_events`,
      `_upsert_decisions` (with the
      `pretrial_release` child),
      `_upsert_sentences`,
      `_upsert_justice_events`, in
      that order, each `INSERT …
      ON CONFLICT (natural index)
      DO UPDATE` writing only when
      substantive columns changed
      (the `IS DISTINCT FROM`
      pattern of Phase 1),
      `PublishedIds` extended for
      every entity type, counts per
      table in `RunCounts` and the
      run log. `SYNTHETIC_SOURCE_
      TYPE` refusal is unchanged;
      add a refusal test that uses
      the real synthetic connector
      under `env = "production"`.
    </requirement>

    <requirement>
      `ingest/synthetic/`:
      `schema.py` (the expected
      header set of each of the
      nine files, lifted from
      docs/SYNTHETIC_DATA.md;
      missing header → the run
      fails naming it; extra
      header → warning),
      `sources.py`
      (`SourceInfo(owner="this
      repository", source_type=
      "synthetic", access_method=
      "local_generator",
      terms_metadata={"redistri-
      bution": "not_applicable",
      "synthetic": True})`),
      `parse.py` (Polars string-
      only parsing projected to
      the expected columns; one
      `SourceRecordDraft` per row
      with `record_type` = file
      stem), `normalize.py`
      (source rows → drafts: court
      and judge rows become the
      reference drafts with
      `identity_key =
      ("synthetic_judge_code",
      code)` and `external_ids`;
      participant rows become
      `PersonDraft` (hashes via
      `hash_identifier`; the
      participant id is hashed as
      the source hands it out —
      the generator assigns one
      `PT-` id per person across
      courts, so a court-code
      prefix would split every
      multi-court person into
      pairs `truth/` does not
      list; spec-rot patch,
      2026-09-18) plus
      `CasePartyDraft`;
      charge/disposition rows
      become `ChargeDraft` and, for
      a disposition with an actor,
      a `DecisionDraft(decision_type
      ="dismissal"|"disposition")`;
      pretrial rows become
      `DecisionDraft` with
      `pretrial`; sentences,
      events, assignments map 1:1;
      `JusticeEventDraft`s are
      derived: a case filed after
      an earlier case of the same
      participant hash →
      `new_case`; a conviction
      after an earlier disposition
      → `reconviction`;
      `failure_to_appear` and
      `revocation` events map to
      justice events; `related_
      case_number` is normalized
      and kept on the case for
      Step 3's linkage feature),
      `connector.py`
      (`@register`, `source_id =
      "synthetic"`, `parser_version
      = "1"`; `discover` lists
      `manifest.json` first then
      the nine files as
      `source/<name>` from
      `settings.synthetic_dir`,
      the dataset root that holds
      `manifest.json` and
      `source/` — the manifest is
      not inside `source/`, so the
      root is what the connector
      and `--from-fixture` point
      at; spec-rot patch,
      2026-09-18; `fetch` reads
      bytes from disk with
      `RawArtifact.from_path`;
      `validate_raw` on the
      manifest checks
      `generator_version`, and
      `load_context` (the runner
      hands every artifact to a
      `SupportsContext` connector
      before parsing) fails the
      run when a file's sha256
      drifts from the manifest;
      `truth/` is never
      discovered). Add the module
      to `BUILTIN_CONNECTOR_
      MODULES`. `Settings.
      synthetic_dir: Path` default
      `data/synthetic/20260916`.
    </requirement>

    <requirement>
      `quality/checks.py` case-
      level checks (issue codes):
      `case_number_duplicate`
      (within a court after
      normalization — the planted
      duplicate collapses to one
      case, the second source
      record attributed; issue at
      `info`), `disposition_before_
      filing` (error), `event_
      order_impossible` (error),
      `subsequent_before_index`
      (error), `missing_judge_on_
      decision` (warning),
      `missing_disposition`
      (info), `unknown_category_
      measured` (info: counts of
      `unknown` values per
      vocabulary kind), `person_
      resolution_confidence_
      missing` (warning). The
      golden fixture's planted
      items produce exactly the
      issues `truth/planted.csv`
      predicts (integration
      assertion).
    </requirement>

    <requirement>
      CLI and targets:
      `judgemetrics seed [--seed
      20260916] [--scale demo]
      [--force]` = generate into
      `data/synthetic/<seed>` (skip
      when the manifest already
      matches the seed, scale, and
      generator version), point
      the connector at
      `<out>/source`, then
      `run_ingest("synthetic")`
      with the ingest role;
      refused in production like
      any synthetic ingest. Poe
      task `seed = "judgemetrics
      seed"` and the Makefile
      target. `judgemetrics ingest
      run synthetic --from-fixture
      tests/fixtures/golden` works
      through the runner's fixture
      path (which accepts contained
      relative ids such as
      `source/cases.csv`).
    </requirement>

    <requirement>
      Tests: `tests/unit/
      test_case_numbers.py`,
      `test_identifiers.py`
      (peppered hash differs per
      pepper and per kind; name
      normalization applied),
      `test_vocabulary.py`,
      `test_synthetic_connector.py`
      (schema, parse, normalize
      over the golden fixture:
      counts per draft type, the
      planted duplicate yields one
      case key, `truth/` never
      discovered, missing header
      fails naming it),
      `test_drafts.py` (natural
      keys); `tests/integration/
      test_synthetic_ingest.py`
      (golden fixture ingested
      twice: first run creates the
      expected counts per table
      matching `manifest.json`
      minus planted duplicates;
      second run creates and
      updates zero; every case-
      level row's `source_record_
      id` resolves to a record
      whose `raw_sha256` matches
      the fixture file; the
      `person` table has no name
      column and `person_
      identifier` holds only 64-hex
      hashes; `Decision` rows for
      prosecutor dismissals carry
      `actor_type = prosecutor`;
      the predicted data-quality
      issues exist; `seed` in
      `env = "production"` records
      `refused`), and the app-role
      grant assertion for every
      new column. The demo-scale
      end-to-end run is exercised
      locally (`uv run poe seed`)
      and its counts recorded in
      the PR body and docs/
      ROADMAP.md, not in CI.
    </requirement>

    <requirement>
      Docs: `docs/ARCHITECTURE.md`
      (case-level publish order,
      person resolution hook,
      hashing), `docs/DATA_MODEL.md`
      (0003 columns and indexes,
      the vocabulary file, the
      identifier kinds),
      `docs/DATA_SOURCES.md`
      (`synthetic` entry: files,
      parser version, settings),
      `README.md` and
      `CONTRIBUTING.md` (`seed`,
      the pepper variable),
      `.env.example`, `AGENTS.md`
      (decisions: `source_row_id`
      natural keys, person hashes,
      vocabulary versioning, seed
      skip rule), `docs/ROADMAP.md`
      (Step 2 done; live demo
      counts; known issues).
    </requirement>

    <requirement>
      Filepath comment: every new
      file gets the repo-relative
      path as the first line where
      the file type accepts
      comments.
    </requirement>
  </requirements>
</task>
```

### Step 2 acceptance criteria

- `uv run poe migrate` applies `0003` and `test_migrations.py`
  round-trips base → head → base; `uv run alembic check` reports no
  drift; the app role still has no privilege on `person_identifier`.
- `uv run poe seed` on a migrated database completes with status
  `succeeded`, logs per-table counts, and leaves at least 5 courts, 20
  judges, 5,000 `court_case` rows, and 3,000 `person` rows; a second
  `uv run poe seed` creates and updates zero canonical rows (counts
  recorded in `docs/ROADMAP.md`).
- The golden fixture ingested twice through
  `judgemetrics ingest run synthetic --from-fixture
  tests/fixtures/golden` creates the manifest's counts (minus
  planted duplicates) on the first run and zero rows on the second;
  every case-level row references a `source_record` whose `raw_sha256`
  equals the sha256 of the stored raw object (integration test).
- The `person` table carries no name or date-of-birth column; every
  `person_identifier.value_hash` is a 64-character hex digest; no log
  line emitted during the fixture ingest contains a participant name,
  date of birth, hash, or the pepper (log-capture assertion).
- With `JUDGEMETRICS_ENV=production` the synthetic connector's run is
  recorded as `refused` with the reason "synthetic sources are refused
  in production" (test using the real connector, not a stub).
- `data/reference/case_vocabulary.yaml` equals `synthetic/vocabulary.py`
  (test); the predicted data-quality issues for every planted item
  exist after the golden ingest.
- All unit and integration tests pass locally and in CI; `uv run poe
  check` is green.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean
  (pepper placeholder only), SAST clean (sha256 peppered hashing,
  `yaml.safe_load`, plain-file-name discovery), dependency audit clean
  (`pyyaml` at runtime passes `pip-audit --strict`), image scan clean —
  and the sensitive-data review confirms person material reaches the
  database only as hashes in the restricted table.

---

## Step 3 — Entity-Resolution Framework v0, Review Queue, and Audit Log ✅

**Status:** Complete — PR #14 (2026-09-18)

> **Goal:** Land the brief's staged resolution for persons as pipeline
> step 10: `src/judgemetrics/entity_resolution/` (`config.py` with
> per-entity-type thresholds and `MODEL_VERSION`, `features.py`
> computing the feature vector of a candidate pair from restricted
> hashes and case linkage, `deterministic.py` matching on stable
> source identifiers, `rules.py` matching on normalized name plus date
> of birth plus a linkage or context signal — never name alone —
> `scoring.py` with the `Scorer` protocol and a `StubScorer` that
> declines every pair (the probabilistic stage arrives in Phase 7),
> `candidates.py` writing `entity_resolution_candidate` rows with
> features, score, model version, stage, decision, timestamp, and
> reviewer, `queue.py` listing and deciding review items, `merge.py`
> re-pointing every person-bearing row and recording
> `person.merged_into_person_id`, and `pipeline.py` with
> `resolve_persons(session, drafts, run)` replacing Step 2's hook plus
> `rerun(session, *, source)`); migration `0004_entity_resolution_review`
> (candidate `stage`, `decided_at`, `decided_by`, `reason`,
> `ingest_run_id`, an ordered-pair unique index; `person.merged_into_
> person_id`; the append-only `audit_log` table with a trigger that
> rejects `UPDATE` and `DELETE`); `judgemetrics er run`, `er review
> list`, `er review decide`; `docs/ENTITY_RESOLUTION.md`; with unit
> tests per stage and an integration test proving the golden
> expectations (planted duplicates merge, ambiguous pairs queue,
> distinct persons never merge). Step 4 exposes the resolved persons;
> Step 5 makes the golden expectations a permanent regression test;
> Phase 7 fills the `Scorer`.

**Branch:** `feature/phase02-step3-entity-resolution`

**Deploys:** nothing beyond merge — the operator runs `uv run poe
migrate` (revision `0004`) and `uv run judgemetrics er run` locally;
a re-seed is not required.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Fable 5.1                      |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** The second ceiling-class step of the phase: it
designs the resolution framework every later source's person linkage
(Cook County in Phase 5, cross-source linkage in Phase 7) must fit,
including the feature contract over restricted hashes, thresholds whose
false-positive posture is a domain rule, a merge that rewrites rows
across seven tables without breaking provenance or idempotency, and an
audit log the brief's security requirements name — PRIMARY `coding`,
SECONDARY `planning`, High complexity with novel problem-solving and
cross-file chain-of-thought. Fable 5.1 is rated S in coding and S in
planning (HLE 59.1%, Terminal-Bench 2.1 91.4 at max) and supersedes
Fable 5; the parent roadmap's §8 reserves Fable for exactly the
resolution-framework step under the operator's balanced posture, with
Opus 5 taking the implementation steps around it. The Platform is
Claude Code on the flat claude.ai Max subscription; the flat-funding
gate is open, so Effort `Max`, Thinking `On`. Backup: GPT-5.6 Sol on
Codex (ChatGPT Plus; Intelligence Extra High), S-tier in coding and
planning from a different provider. Conversation is New per
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
       feature/phase02-step3-entity-resolution`
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
       rejected. Stop the local
       API before `uv run poe
       gate` or `git commit`.

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
       run `uv run poe migrate`,
       `uv run judgemetrics er run`,
       and `er review list` locally
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
       docs/ROADMAP.md (completed
       items, known issues). Once
       the PR is merged and every
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
       Reviewer identities in the
       audit log are operator-
       chosen labels passed on the
       command line, never
       e-mail addresses read from
       git config.

    2. SAST. No new injection,
       unsafe deserialization,
       weak crypto, path
       traversal, or unsafe-eval
       pattern (`bandit`). The
       merge is SQLAlchemy Core
       updates with bound
       parameters; the trigger
       function body is a fixed
       string in the migration
       with no interpolation; the
       `decide` command validates
       the candidate id as a UUID
       and the decision against
       the enum before touching the
       database.

    3. DEPENDENCY AUDIT. No new
       runtime dependency is
       expected; any addition
       passes `pip-audit
       --strict`.

    4. SENSITIVE-DATA REVIEW.
       Features stored in
       `entity_resolution_candidate.
       features` are booleans,
       counts, and similarity
       scores — never a name, a
       date of birth, a hash, or a
       participant id; the `er
       review list` output shows
       candidate ids, public
       person keys, stage, score,
       and feature booleans, never
       restricted values; the app
       role has no privilege on
       `audit_log` or
       `entity_resolution_
       candidate`; log lines carry
       counts and candidate ids
       only.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 2.
    Step 3: entity-resolution
    framework v0, review queue,
    and audit log.

    Current state (as of Phase 1,
    post-Phase-2 Step 2):

    - `uv run poe seed` loads the
      synthetic dataset; persons
      are created one per distinct
      `source_participant_id` hash
      by `resolve_persons` in
      `ingest/runner.py` (the hook
      this step replaces).
    - `person_identifier` holds
      hashes of kinds
      `source_participant_id`,
      `full_name`, `date_of_birth`,
      `name_dob`; `court_case.
      related_case_number_
      normalized` carries the
      linkage signal; `case_party`
      links persons to cases and
      courts.
    - `entity_resolution_candidate`
      has entity_type, left/right
      ids, match_probability,
      decision, features,
      model_version — no stage,
      timestamp, reviewer, or
      reason.
    - `truth/resolution_
      expectations.csv` in the
      golden fixture names the
      expected decision for every
      planted pair; the split
      persons must merge, the
      ambiguous pairs must queue,
      name-only pairs must be
      rejected.
    - There is no audit log table.

    Files to read (every file
    before drafting):
    - docs/brief/judgemetrics-
      master-project-specification.xml
      (`<entity_resolution>` in
      full, `<security>` "Log
      administrative changes",
      `<data_quality>` "Entity-
      resolution confidence
      available").
    - ROADMAP.md §4 Phase 2 (2.3,
      2.4 audit log), Phase 6
      (6.1-6.2, what the error-
      rate measurement and admin
      tools will need), Phase 7
      (7.3 probabilistic linkage),
      §5 "Risks & mitigations"
      (false-positive merges).
    - docs/SYNTHETIC_DATA.md
      (planted edge cases).
    - docs/ARCHITECTURE.md,
      docs/DATA_MODEL.md.
    - src/judgemetrics/ingest/
      runner.py (`resolve_persons`,
      `_upsert_persons`,
      `PublishedIds`),
      ingest/base.py.
    - src/judgemetrics/db/models/
      persons.py, resolution.py,
      cases.py, enums.py;
      alembic/versions/
      0003_case_level_natural_keys.py.
    - src/judgemetrics/security/
      identifiers.py, config.py,
      cli.py, logging.py.
    - tests/integration/
      test_synthetic_ingest.py,
      conftest.py.
    - tests/fixtures/golden/truth/
      resolution_expectations.csv,
      planted.csv, README.md.
  </context>

  <goal>
    Ship the staged person-
    resolution framework, the
    review queue, the merge, the
    audit log, and their CLI so
    that ingesting the golden
    fixture resolves every planted
    pair exactly as `truth/
    resolution_expectations.csv`
    predicts, every candidate row
    carries features, score, model
    version, stage, and decision,
    a reviewer's decision merges
    or rejects with an audit entry
    that cannot be altered, and
    rerunning resolution is
    idempotent.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      `entity_resolution/config.py`:
      `MODEL_VERSION =
      "person-rules-v0"`; frozen
      `Thresholds(auto_match: float
      = 0.95, auto_reject: float =
      0.20)` per entity type in a
      `THRESHOLDS` mapping (person
      now; judge, court, case
      entries present with the
      same defaults for Phase 7);
      the values are also written
      to `data/reference/
      entity_resolution_
      thresholds.yaml` (`version:
      1`) which the module loads
      and a test asserts equal —
      thresholds are versioned
      data, per the parent
      roadmap's triage rule for
      data-semantics findings.
    </requirement>

    <requirement>
      `entity_resolution/
      features.py`: `PairFeatures`
      (frozen; JSON-serializable
      via `as_dict`): `same_source_
      id: bool`, `same_name: bool`,
      `same_dob: bool`,
      `dob_missing_either: bool`,
      `same_name_dob: bool`,
      `shared_case: bool`,
      `related_case_link: bool`
      (one person's case cites the
      other's case number),
      `same_court: bool`,
      `filing_gap_days: int |
      None`, `age_consistent: bool
      | None`. Computed from
      `person_identifier` hashes
      (equality only — the feature
      never carries a hash) and
      from `case_party`,
      `court_case`, and `court`
      joins. Blocking: candidate
      pairs are generated only
      among persons sharing a
      `full_name` hash or a
      `source_participant_id`
      hash, so the pair space is
      bounded.
    </requirement>

    <requirement>
      Stages (`pipeline.py`
      applies them in order, each
      returning a decision, a
      score, and a stage label,
      stopping at the first
      decisive stage):
      1. `deterministic.py`:
         `same_source_id` within
         one source → `matched`,
         score 1.0, stage
         `deterministic`.
      2. `rules.py`: `same_name_
         dob` AND (`shared_case` OR
         `related_case_link`) →
         `matched`, score 0.98,
         stage `rule`; `same_name_
         dob` AND `same_court` AND
         `age_consistent` and no
         contradicting signal →
         `review`, score 0.70
         (deliberately below
         auto-match), stage
         `rule`; `same_name` with
         `dob_missing_either` →
         `rejected`, score 0.10,
         reason `name_only`, stage
         `rule` (never merge on a
         name alone); `same_name`
         with differing DOB →
         `rejected`, score 0.02.
      3. `scoring.py`: `class
         Scorer(Protocol): def
         score(self, features:
         PairFeatures) -> float |
         None` and `StubScorer`
         returning `None` (stage
         `probabilistic` is
         recorded as `skipped`
         in the candidate
         features). When a scorer
         returns a value, the
         thresholds decide:
         ≥ auto_match → matched,
         < auto_reject → rejected,
         otherwise review.
      Everything that is not
      decisively matched or
      rejected is `review`. A pair
      that produces no feature
      signal at all is not stored.
    </requirement>

    <requirement>
      `candidates.py` writes one
      `entity_resolution_candidate`
      per ordered pair (left id <
      right id) per model version:
      `features` (the
      `PairFeatures.as_dict()`
      plus `stage_trace`),
      `match_probability` (the
      score), `decision`, `stage`,
      `decided_at` (system
      decisions: the run time;
      review: NULL until decided),
      `decided_by` (`system:
      person-rules-v0` or the
      reviewer label), `reason`,
      `ingest_run_id`. Rerunning
      with the same model version
      upserts and leaves an
      existing human decision
      untouched (`decided_by` not
      starting with `system:` is
      never overwritten); a new
      model version writes new
      rows and leaves old ones as
      history.
    </requirement>

    <requirement>
      `merge.py`: `merge_persons(
      session, keep_id, drop_id,
      *, actor, reason)` moves
      `case_party`, `charge`,
      `court_event`, `decision`,
      `sentence`, `justice_event`,
      and `person_identifier` rows
      from `drop` to `keep`
      (respecting the natural-key
      unique indexes: a justice
      event that would collide is
      dropped as a duplicate and
      counted), sets
      `person.merged_into_person_
      id = keep` and
      `resolution_status =
      "merged"` on `drop`, sets
      `resolution_status` and
      `resolution_confidence` on
      `keep` to the deciding
      stage's values, and writes
      one `audit_log` row. A merged
      person is never returned by
      any public query (Step 4
      filters `merged_into_person_
      id IS NULL`; the repository
      helper lives here). Merges
      are applied only for
      `matched` decisions; a
      `rejected` decision writes
      the candidate and an audit
      row only.
    </requirement>

    <requirement>
      Migration `alembic/versions/
      0004_entity_resolution_review.py`
      (self-contained, reversible,
      `alembic check` clean):
      `entity_resolution_candidate`
      gains `stage` (String 32 NOT
      NULL), `decided_at`
      (timestamptz NULL),
      `decided_by` (String 128
      NULL), `reason` (Text NULL),
      `ingest_run_id` (FK NULL);
      unique index
      `uq_er_candidate_pair_version`
      on (`entity_type`,
      `left_record_id`,
      `right_record_id`,
      `model_version`); a CHECK
      that `left_record_id <
      right_record_id`.
      `person.merged_into_person_
      id` (self FK NULL, indexed).
      `audit_log` (`id` UUID PK,
      `occurred_at` timestamptz NOT
      NULL default now(), `actor`
      String 128 NOT NULL, `action`
      String 64 NOT NULL,
      `entity_type` String 32,
      `entity_id` UUID,
      `payload` JSONB NOT NULL
      default '{}', `request_id`
      String 64 NULL), index on
      (`entity_type`, `entity_id`)
      and `occurred_at`; a trigger
      function `audit_log_append_
      only()` raising an exception
      on UPDATE or DELETE, attached
      BEFORE UPDATE OR DELETE;
      grants: `judgemetrics_ingest`
      INSERT and SELECT,
      `judgemetrics_admin` SELECT
      and INSERT, `judgemetrics_
      app` nothing (also nothing
      on `entity_resolution_
      candidate` — re-assert).
      `test_migrations.py` proves
      the round trip, the grants,
      and that an UPDATE and a
      DELETE on `audit_log` raise
      even as the admin role.
    </requirement>

    <requirement>
      Runner integration:
      `ingest/runner.py` step 10
      calls `entity_resolution.
      pipeline.resolve_persons(
      session, person_drafts,
      run)`, which (a) creates or
      finds persons by stable
      source id exactly as Step 2
      did, (b) generates candidate
      pairs among the run's
      persons and existing
      persons by blocking, (c)
      applies the stages, (d)
      writes candidates and
      applies system merges, (e)
      returns the person id per
      draft key so publishing
      proceeds with merged ids. It
      is idempotent: a second
      ingest of the same fixture
      writes no new candidate rows
      and performs no merge.
      `rerun(session, *, source:
      str | None)` recomputes
      candidates for all persons
      (or one source's) under the
      current model version
      without re-ingesting and
      records an `ingest_run`-
      independent audit row per
      merge.
    </requirement>

    <requirement>
      CLI group `er`: `judgemetrics
      er run [--source synthetic]`
      (rerun; prints candidates
      created, matched, rejected,
      review, merges), `er review
      list [--entity-type person]
      [--limit 50] [--json]`
      (review items: candidate id,
      the two public person keys,
      stage, score, feature
      booleans, created time —
      never restricted values),
      `er review decide
      <candidate_id> --decision
      matched|rejected --reviewer
      <label> --reason <text>`
      (applies the merge or the
      rejection, sets decided_at/
      decided_by/reason, writes
      `audit_log` with action
      `er.decide`, refuses a
      candidate not in `review`,
      refuses in `env ==
      production` until Phase 6's
      admin authn exists — say so
      in the error). All three run
      as the ingest role.
    </requirement>

    <requirement>
      Tests: `tests/unit/
      test_er_features.py`,
      `test_er_rules.py` (each rule
      and each negative: name-only
      never matches; differing DOB
      rejects; the stub scorer is
      skipped and recorded),
      `test_er_thresholds.py`
      (yaml equals constants;
      decision boundaries),
      `test_er_candidates.py`
      (ordered pair, human
      decision preserved on
      rerun); `tests/integration/
      test_entity_resolution.py`
      (golden fixture ingested:
      every row of `truth/
      resolution_expectations.csv`
      matches the stored candidate
      decision exactly; split
      persons are merged and their
      cases sit under one
      `public_person_key`;
      ambiguous pairs are in
      review; distinct persons
      keep distinct ids; every
      candidate carries non-empty
      features, a score, the model
      version, a stage, and a
      decision; a second ingest
      writes zero candidates and
      performs zero merges; `er
      review decide … matched` on
      a planted ambiguous pair
      merges, writes an audit row,
      and an UPDATE on that audit
      row raises; `er review
      decide` on an already-
      decided candidate is
      refused). The runner's
      person-resolution log lines
      are captured and asserted
      free of names, DOBs, and
      hashes.
    </requirement>

    <requirement>
      Docs: `docs/ENTITY_RESOLUTION.md`
      (the objective, the signals
      used and the ones deferred,
      the blocking rule, each
      stage and rule with its
      score, the thresholds file
      and the version rule, the
      candidate row contract, the
      review workflow and CLI, the
      merge semantics and
      irreversibility note — Phase
      6 adds unmerge — the audit
      log, what Phase 6 measures
      and Phase 7 adds),
      `docs/ARCHITECTURE.md` (step
      10, audit log),
      `docs/DATA_MODEL.md` (0004),
      `README.md` (`er` commands),
      `AGENTS.md` (decisions:
      features never carry
      restricted values, human
      decisions survive reruns,
      audit trigger), `docs/
      ROADMAP.md` (Step 3 done;
      known issues: no unmerge
      until Phase 6; `decide`
      refused in production until
      admin authn).
    </requirement>

    <requirement>
      Filepath comment: every new
      file gets the repo-relative
      path as the first line where
      the file type accepts
      comments.
    </requirement>
  </requirements>
</task>
```

### Step 3 acceptance criteria

- `uv run poe migrate` applies `0004`; `test_migrations.py` round-trips
  through it, asserts the grants, and proves `UPDATE` and `DELETE` on
  `audit_log` raise for the admin role.
- After the golden fixture is ingested, every row of
  `truth/resolution_expectations.csv` matches the stored candidate's
  decision exactly: planted split persons are merged under one
  `public_person_key`, planted ambiguous pairs are in `review`, and
  distinct persons — including name-only and differing-DOB pairs —
  never merge (integration test).
- Every `entity_resolution_candidate` row carries non-empty `features`,
  a `match_probability`, `model_version = person-rules-v0`, a `stage`,
  and a `decision`; features contain no name, date of birth, hash, or
  participant id (test scans the JSON).
- A second ingest of the same fixture creates zero candidate rows and
  performs zero merges; `judgemetrics er run` on the seeded database is
  likewise idempotent (counts in the PR body).
- `judgemetrics er review list` shows only public keys, stages, scores,
  and feature booleans; `er review decide` merges or rejects, writes an
  `audit_log` row, and refuses an already-decided candidate and any
  invocation under `env == production`.
- `docs/ENTITY_RESOLUTION.md` exists and names every stage, rule,
  score, threshold, and the version rule; `uv run poe check` is green
  locally and in CI.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean,
  SAST clean (bound-parameter updates, fixed trigger body, validated
  CLI inputs), dependency audit clean — and the sensitive-data review
  confirms candidate features, review output, and log lines carry no
  restricted values and the app role has no privilege on `audit_log`
  or `entity_resolution_candidate`.

---

## Step 4 — Case API, Case Pages, and Coverage v0 ✅

**Status:** Complete — PR #15 (2026-09-18)

> **Goal:** Expose cases end to end: `api/routes/cases.py`
> (`GET /api/v1/cases/{case_id}` and `/cases/{case_id}/timeline`),
> `/judges/{judge_id}/cases` in `api/routes/judges.py` (paginated, with
> `filed_from`, `filed_to`, `status`, `case_type` filters),
> `api/routes/coverage.py` (`GET /api/v1/coverage` v0: per source the
> source type, synthetic flag, jurisdictions, courts, judges, cases,
> earliest and latest filed date, last successful ingest run; a global
> `synthetic_present`), exact normalized case-number matches in
> `/search`, a `synthetic: bool` on every summary, detail, and
> provenance block, `case_count` and `coverage` (earliest/latest filed
> date) on judge detail, with `schemas/cases.py`, `schemas/coverage.py`,
> `repositories/cases.py`, `repositories/coverage.py`, `services/
> cases.py`, `services/coverage.py`, `StrictQuery` allow-lists, the
> query-count guard extended, and `docs/openapi.json` regenerated; the
> web `/cases/[caseId]` page (timeline, charges, judge assignments,
> attributed decisions with actor badges, disposition, sentence, source
> citations), the judge page's cases panel and `/judges/[judgeId]/cases`
> list, `/coverage` v0, the site-wide `SyntheticBanner` and per-entity
> `SyntheticBadge`, case results on `/search`, `web/lib/api/schema.d.ts`
> regenerated, Vitest unit tests, and a Playwright case scenario against
> the golden fixture the CI `e2e` job now ingests; `docs/API.md`
> updated. Step 5's contract test and Step 6's checks read these routes.

**Branch:** `feature/phase02-step4-case-api-pages`

**Deploys:** nothing beyond merge — served locally by `uv run poe
dev-api` and `uv run poe dev-web` over the seeded database.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** Cross-cutting Python and TypeScript implementation
against fixed conventions (the Phase 1 route → service → repository
layering, `StrictQuery`, the OpenAPI snapshot, the generated client,
`force-dynamic` pages) with agentic test-and-run loops across the API,
Vitest, and Playwright — PRIMARY `coding`, SECONDARY `agentic`, High
complexity by scope, known patterns throughout. Claude Opus 5 is
S-tier in coding and S-tier in agentic (Terminal-Bench 2.1 89.1), A-tier
in multimodal for reviewing page screenshots, and supersedes Opus 4.8;
under the balanced posture it takes this implementation step while
Fable 5.1 is held for Steps 1 and 3. The Platform is Claude Code on the
flat claude.ai Max subscription; the flat-funding gate is open, so
Effort `Max`, Thinking `On`. Backup: GPT-5.3 Codex on Codex (ChatGPT
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
       feature/phase02-step4-case-api-pages`
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
       rejected. Stop the local
       API before `uv run poe
       gate` or `git commit`; run
       pnpm with `cwd=web/`.

    3. OPEN THE PR. `gh pr create
       --base main --head <branch>`
       with a Conventional Commits
       title and a body that
       references this roadmap step
       and its acceptance criteria,
       with screenshots of the case
       page, the judge cases panel,
       the coverage page, and the
       banner in light and dark
       mode. One PR per step.

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
       verify the pages against the
       seeded local database before
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
       docs/ROADMAP.md (completed
       items, known issues). Once
       the PR is merged and every
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
       the diff (`detect-secrets`);
       no server-only variable
       reaches the client bundle
       (`bundle-secrets.test.ts`
       stays green).

    2. SAST. No new injection,
       unsafe deserialization,
       weak crypto, path
       traversal, or unsafe-eval
       pattern (`bandit`; `eslint-
       plugin-security` at
       `--max-warnings 0`). Case
       numbers from the query
       string are normalized and
       bound as parameters; no
       `dangerouslySetInnerHTML`.

    3. DEPENDENCY AUDIT. Any new
       Python or npm dependency
       passes `pip-audit --strict`
       / `pnpm audit --audit-level
       =high`; both images scan
       clean.

    4. SENSITIVE-DATA REVIEW.
       Every response about a
       person carries only
       `public_person_key`; no
       route, schema, or repository
       selects from
       `person_identifier`,
       `entity_resolution_
       candidate`, or `audit_log`
       (the app role cannot, and a
       contract test over
       `docs/openapi.json` asserts
       no schema property named
       `value_hash`,
       `encrypted_value`,
       `date_of_birth`,
       `full_name`, or `person_
       identifier`); merged persons
       (`merged_into_person_id IS
       NOT NULL`) are never
       exposed; `raw_object_path`
       and the DSN stay out of
       every response; a case
       timeline never renders a
       participant name because
       none exists.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 2.
    Step 4: case API, case pages,
    and coverage v0.

    Current state (as of Phase 1,
    post-Phase-2 Step 3):

    - The seeded database holds
      synthetic courts, judges,
      persons (resolved; some
      merged), cases, parties,
      assignments, charges,
      events, decisions with
      pretrial releases,
      sentences, justice events,
      candidates, and audit rows,
      each case-level row with
      `source_record_id`.
    - API v1 serves judges,
      courts, jurisdictions, and
      search with `Page`,
      `Provenance`, `StrictQuery`,
      the query-count guard, and
      the committed OpenAPI
      snapshot.
    - The web app renders the
      Phase 1 pages; `/coverage`
      is a stub; the home coverage
      tile says case data arrives
      in Phase 2.
    - `merge.py` exposes the
      not-merged filter helper.

    Files to read (every file
    before drafting):
    - docs/brief/judgemetrics-
      master-project-specification.xml
      (`<api_design>` case,
      coverage, and judge cases
      endpoints and rules;
      `<application_pages>` case,
      judge, coverage, search;
      `<metric_presentation>`
      presentation_rules for the
      synthetic label and source
      citations;
      `<privacy_and_legal_design>`).
    - ROADMAP.md §4 Phase 2 (2.4),
      Phase 3 (3.5 — what the
      judge page will add so the
      cases panel leaves room).
    - docs/API.md,
      docs/ARCHITECTURE.md ("Public
      API v1", "Web tier").
    - src/judgemetrics/api/deps.py,
      routes/judges.py,
      routes/search.py,
      schemas/common.py,
      schemas/judges.py,
      repositories/judges.py,
      repositories/provenance.py,
      services/search.py,
      services/provenance.py,
      openapi.py.
    - src/judgemetrics/db/models/
      cases.py, persons.py,
      provenance.py.
    - src/judgemetrics/
      entity_resolution/merge.py.
    - tests/integration/
      test_api_judges.py,
      test_query_counts.py,
      conftest.py; tests/unit/
      test_openapi.py.
    - web/lib/api/client.ts,
      web/app/judges/[judgeId]/
      page.tsx, web/app/coverage/
      page.tsx, web/app/search/
      page.tsx, web/app/layout.tsx,
      web/components/
      provenance-panel.tsx,
      badges.tsx, states.tsx,
      web/tests/e2e/smoke.spec.ts,
      web/tests/unit/*.
    - .github/workflows/ci.yml
      (`e2e` job seeding).
  </context>

  <goal>
    Ship the case, timeline, judge-
    cases, and coverage endpoints
    with synthetic labelling on
    every response, and the web
    pages that make a synthetic
    case reachable from a synthetic
    judge page, rendering timeline,
    charges, attributed decisions
    with actor badges, disposition,
    sentence, and source citations,
    with the demo-data banner shown
    whenever a synthetic source is
    present.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Schemas (`schemas/cases.py`,
      `schemas/coverage.py`;
      extend `common.py` and
      `judges.py`): `Provenance`
      gains `synthetic: bool`;
      `JudgeSummary`, `JudgeDetail`,
      `CourtSummary`, `CourtDetail`,
      and `SearchResult` gain
      `synthetic: bool` (true when
      the row's `source_record`
      belongs to a source with
      `source_type == synthetic`);
      `JudgeDetail` gains
      `case_count: int` and
      `coverage: CoverageWindow |
      None` (`earliest_filed`,
      `latest_filed`, `case_count`,
      computed over the judge's
      assignments); `CaseSummary`
      (id, court ref, case_number,
      case_type, filed_date,
      closed_date, status,
      synthetic); `CaseDetail`
      (summary fields + `parties`
      [party_type,
      public_person_key],
      `assignments` [judge ref,
      assignment_type, start_at,
      end_at], `charges` [statute_
      code, description, offense_
      category, severity,
      violent_flag, filed_at,
      disposed_at, disposition],
      `decisions` [decision_type,
      decision_at, actor_type,
      judicial_discretion_
      classification, judge ref |
      null, public_person_key,
      decision_value, pretrial_
      release | null], `sentences`
      [sentence_at, judge ref |
      null, incarceration_days,
      probation_days, fine_amount,
      components], `provenance`:
      list of the distinct
      provenance blocks of every
      row in the case);
      `TimelineEntry` (at, kind ∈
      filed|assignment_start|
      assignment_end|event|
      decision|charge_filed|
      charge_disposed|sentence|
      closed, actor_type | null,
      judge ref | null, label,
      detail: dict, source:
      Provenance) and `Timeline`
      (case_id, entries sorted by
      `at` then a stable kind
      order); `CoverageSource`
      (source, source_type,
      synthetic, jurisdictions,
      courts, judges, cases,
      persons, earliest_filed,
      latest_filed, last_ingest:
      {run_id, completed_at,
      status}) and `Coverage`
      (sources, synthetic_present,
      generated_at). No schema
      names a restricted column.
    </requirement>

    <requirement>
      Repositories and services:
      `repositories/cases.py`
      (detail in a constant number
      of statements — one explicit
      statement per case-level
      table plus one for provenance,
      eight in all, never a
      cartesian eager load; the
      timeline assembled in the
      service from the same loaded
      rows — no second round of
      queries;
      judge cases with `count(*)
      OVER ()` and the four
      filters; every person join
      excludes merged persons),
      `repositories/coverage.py`
      (one aggregate statement per
      source plus one for runs),
      `repositories/judges.py`
      gains the case count and
      window (one statement),
      `repositories/search.py` /
      `services/search.py` gain an
      exact match on
      `case_number_normalized`
      (using `normalize_case_
      number` on `q`) unioned into
      the results with entity type
      `case`; `services/
      provenance.py` sets
      `synthetic` from the source
      row. Routes: `api/routes/
      cases.py` (`/cases/{case_id}`
      404 for unknown, `/cases/
      {case_id}/timeline`),
      `routes/judges.py`
      (`/judges/{judge_id}/cases`
      with `StrictQuery` allowing
      `limit`, `offset`,
      `filed_from`, `filed_to`,
      `status`, `case_type`; 422
      when `filed_to <
      filed_from`), `routes/
      coverage.py` (`/coverage`,
      `Cache-Control: public,
      max-age=60`). Register in
      `main.py`; `uv run
      judgemetrics openapi export`
      regenerates `docs/
      openapi.json` (paths:
      existing eight plus `/cases/
      {case_id}`, `/cases/{case_id}
      /timeline`, `/judges/
      {judge_id}/cases`,
      `/coverage`).
    </requirement>

    <requirement>
      Web: `web/lib/api/client.ts`
      helpers `getCase`,
      `getCaseTimeline`,
      `getJudgeCases`,
      `getCoverage`; `pnpm
      generate:api` regenerates
      `schema.d.ts`; `web/app/
      cases/[caseId]/page.tsx`
      (header: court link, case
      number, type, status, filed/
      closed, `SyntheticBadge`;
      timeline list with actor
      badges from `badges.tsx`
      extended for every
      `ActorType` and the
      discretion classification;
      charges table; judge
      assignments; decisions with
      pretrial detail; sentence;
      "Sources" panel listing every
      provenance block through
      `provenance-panel.tsx`;
      `ErrorState`/`EmptyState`;
      `force-dynamic`); `web/app/
      judges/[judgeId]/page.tsx`
      gains a "Cases" panel (count,
      coverage window, link to
      `/judges/[judgeId]/cases`)
      and the badge; `web/app/
      judges/[judgeId]/cases/
      page.tsx` (paginated table
      with the filters as form
      controls, rows linking to
      the case page); `web/app/
      coverage/page.tsx` v0 (table
      per source with the counts,
      window, and last run; the
      Phase 3 completeness
      estimates noted as coming);
      `web/components/synthetic-
      banner.tsx` rendered from
      `layout.tsx` as a server
      component that calls
      `getCoverage` and shows a
      persistent, non-dismissable
      banner "Demo data: this site
      currently includes a
      synthetic dataset; synthetic
      records are labelled" when
      `synthetic_present` (nothing
      when the call fails —
      `ApiResult` never throws);
      `SyntheticBadge` beside every
      entity whose `synthetic` is
      true (judge, court, case,
      search result); `/search`
      shows `case` results; the
      home coverage tile reads
      case counts from
      `/coverage`. Accessibility as
      in Phase 1 (landmarks, table
      semantics, focus rings;
      timeline as an ordered list
      with `<time>` elements).
    </requirement>

    <requirement>
      Tests: `tests/integration/
      test_api_cases.py` (detail,
      timeline ordering and kinds,
      404, no restricted field
      name in any response, no
      merged person key, actor
      types present for judge and
      prosecutor dismissals),
      `test_api_judges.py` (cases
      list pagination, filters,
      422s, `case_count`, and
      `coverage`), `test_api_
      coverage.py` (synthetic
      source reported,
      `synthetic_present` true
      with the golden fixture,
      false when only the FJC
      fixture is present — order
      the fixtures accordingly),
      `test_api_search.py` (exact
      case-number match; a partial
      number does not match),
      `test_query_counts.py`
      (case detail ≤ 8, timeline
      ≤ 8, judge cases ≤ 2,
      coverage ≤ 3, judge detail
      ≤ 4 with the case window),
      `tests/unit/
      test_openapi.py` (the
      snapshot, the allow-lists,
      and the contract assertion
      over restricted names);
      Vitest: client helpers,
      banner renders only on
      `synthetic_present`, badge,
      timeline entry rendering,
      schema freshness; Playwright
      `web/tests/e2e/smoke.spec.ts`
      gains: search a synthetic
      judge → judge page shows the
      banner, badge, and cases
      panel → cases list → case
      page renders timeline,
      charges, an actor badge for
      a prosecutor dismissal and
      one for a judge decision,
      the sentence, and the
      sources panel. `ci.yml`
      `e2e` job (and the docs'
      local recipe) ingests
      `tests/fixtures/golden` (the
      dataset root: manifest.json
      beside source/) after the FJC
      fixture and sets
      `JUDGEMETRICS_IDENTIFIER_
      PEPPER` for the job.
    </requirement>

    <requirement>
      Docs: `docs/API.md` (the four
      endpoints, filters, the
      `synthetic` flag, the
      timeline kinds, the query
      budget), `docs/ARCHITECTURE.md`
      (web tier: banner, badge,
      case pages), `README.md`
      (endpoint list, pages),
      `AGENTS.md` (decisions:
      synthetic flag derivation,
      merged persons filtered at
      the repository, timeline
      assembled from loaded rows,
      e2e golden ingest),
      `docs/ROADMAP.md` (Step 4
      done; the home tile and
      coverage stub retired; known
      issues).
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

- `GET /api/v1/cases/{id}` returns a synthetic case with parties (public
  keys only), assignments, charges, decisions carrying `actor_type` and
  `judicial_discretion_classification`, sentences, provenance blocks
  with `synthetic: true`, and 404 for an unknown id;
  `/cases/{id}/timeline` returns entries in chronological order with
  every kind the case contains (integration tests).
- `GET /api/v1/judges/{id}/cases` paginates with `limit` ≤ 100, applies
  `filed_from`, `filed_to`, `status`, `case_type`, rejects unknown
  parameters and inverted ranges with 422; judge detail carries
  `case_count` and `coverage`.
- `GET /api/v1/coverage` reports every ingested source with counts,
  window, last run, and `synthetic_present`; `/search` returns a `case`
  result for an exact normalized case number.
- `docs/openapi.json` equals the generated document and lists exactly
  the twelve v1 paths plus health and ready; no schema property is
  named `value_hash`, `encrypted_value`, `date_of_birth`, `full_name`,
  or `person_identifier` (contract test); the query-count guard holds
  for every new endpoint.
- `/judges/[judgeId]` for a synthetic judge shows the banner, the badge,
  and the cases panel; `/judges/[judgeId]/cases` links to
  `/cases/[caseId]`, which renders timeline, charges, judge assignments,
  attributed decisions with actor badges, disposition, sentence, and
  source citations; `/coverage` lists the synthetic source; the banner
  is absent when no synthetic source is ingested (Vitest); Playwright
  passes locally and in the `e2e` job over the FJC plus golden
  fixtures.
- `pnpm lint`, `pnpm typecheck`, `pnpm build`, `pnpm test`, and the
  schema-freshness test are green locally and in CI; both images scan
  clean.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean,
  SAST clean (Python and `eslint-plugin-security`), dependency audits
  clean, bundle scan clean — and the sensitive-data review confirms no
  route touches `person_identifier`, `entity_resolution_candidate`, or
  `audit_log`, merged persons are never exposed, and every person
  reference is a `public_person_key`.

---

## Step 5 — Property Tests, Golden Suite, and the Scratch Test Database ✅

**Status:** Complete — PR #16 (2026-09-18)

> **Goal:** Turn the phase's invariants into the permanent regression
> harness: add `hypothesis` to the dev group and `tests/property/`
> (`test_event_ordering.py` — for any seed and scale, no subsequent
> event precedes its index event and no disposition precedes filing,
> through the generator and through the normalized drafts;
> `test_ingest_idempotent.py` — for any small seed, ingesting a
> generated dataset twice creates zero rows the second time (integration,
> bounded examples); `test_resolution_consistency.py` — identical
> deterministic identifiers resolve to the same person across runs and
> across draft orderings; `test_case_numbers.py` — normalization is
> idempotent and format-insensitive); `tests/golden/`
> (`test_golden_fixture.py` — regenerating seed 7 is byte-identical to
> the committed fixture and the manifest verifies;
> `test_golden_resolution.py` — the Step 3 expectations as the permanent
> regression test, parametrized over `truth/resolution_expectations.csv`;
> `test_golden_counts.py` — canonical counts after the golden ingest
> equal the manifest counts minus planted duplicates, and the predicted
> data-quality issues exist; `test_public_contract.py` — the restricted
> tables are unreachable through the OpenAPI document and through the
> app role); `JUDGEMETRICS_TEST_DATABASE_URL` so the migration
> round-trip and every fixture-ingesting integration test run against a
> scratch database (Compose creates `judgemetrics_test` with the same
> roles; CI points it at the service database) and a local live ingest
> survives `uv run poe check`; `pytest` markers `property` and `golden`;
> and the `tests/fixtures/golden/README.md` regeneration rule. Step 6
> wires the suites into the verify script; Phase 3 adds golden metric
> tests beside these.

**Branch:** `feature/phase02-step5-property-golden`

**Deploys:** nothing beyond merge — the operator runs `uv run poe up`
once more (the Compose init script now creates the scratch database)
and sets `JUDGEMETRICS_TEST_DATABASE_URL` in the local `.env`.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** Test-engineering work with a small infrastructure
change: property-based tests need well-chosen strategies and bounded
example budgets so CI stays fast, the golden suite must parametrize
over fixture files without duplicating Step 3's assertions, and the
scratch database touches Compose, settings, CI, and every integration
fixture — PRIMARY `coding`, SECONDARY `agentic`, Medium-to-High
complexity with no novel design. Claude Opus 5 is S-tier in coding and
agentic (Terminal-Bench 2.1 89.1) and supersedes Opus 4.8; the selector
ranks by the highest PRIMARY tier first and the open flat-funding gate
suspends tier-down for routine work, so the funded frontier model takes
it at zero marginal cost. The Platform is Claude Code on the flat
claude.ai Max subscription: Effort `Max`, Thinking `On`. Backup:
GPT-5.3 Codex on Codex (ChatGPT Plus; Intelligence High). Conversation
is New per phase-boundary hygiene.

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
       feature/phase02-step5-property-golden`
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
       rejected. Stop the local
       API before `uv run poe
       gate` or `git commit`.

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
       confirm locally that `uv run
       poe check` leaves the seeded
       database intact before
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
       docs/ROADMAP.md (completed
       items; retire the "check
       empties the live ingest"
       known issue). Once the PR
       is merged and every
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
    re-run in CI:

    1. SECRET / PII SCAN. No
       credentials or tokens in
       the diff (`detect-secrets`).
       `JUDGEMETRICS_TEST_DATABASE_
       URL` in `.env.example` is a
       placeholder (`# pragma:
       allowlist secret` if
       flagged); the CI value uses
       the service container's
       throwaway password already
       in `ci.yml`.

    2. SAST. No new injection,
       unsafe deserialization,
       weak crypto, path
       traversal, or unsafe-eval
       pattern (`bandit`). The
       scratch-database init SQL is
       a fixed file under
       `infra/docker/`; tests never
       build SQL from strategies.

    3. DEPENDENCY AUDIT.
       `hypothesis` (dev group)
       passes `pip-audit --strict`.

    4. SENSITIVE-DATA REVIEW.
       Hypothesis strategies
       generate seeds and
       formatting variants, never
       names — every name still
       comes from the word lists;
       the public-contract test
       asserts the app role cannot
       read `person_identifier`,
       `entity_resolution_
       candidate`, or `audit_log`
       and that no OpenAPI schema
       names a restricted column;
       failing-example output from
       Hypothesis contains ids and
       seeds, not restricted
       values.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 2.
    Step 5: property tests, golden
    regression suite, and the
    scratch test database.

    Current state (as of Phase 1,
    post-Phase-2 Step 4):

    - The generator, connector,
      resolver, and case routes
      are merged; the golden
      fixture at
      `tests/fixtures/golden/`
      has `truth/` with
      expectations; Step 3's
      integration test already
      asserts the resolution
      expectations once.
    - `tests/integration/
      test_migrations.py`
      downgrades the configured
      database to base and back;
      the API tests ingest and
      purge fixtures per module.
      Both empty or disturb a
      local live ingest
      (`docs/ROADMAP.md` known
      issues; `docs/phase01-qa-
      findings.md` finding 2.5).
    - `tests/` is a package with
      `unit/` and `integration/`;
      pytest markers `unit` and
      `integration` exist in
      `pyproject.toml`.
    - CI `python` job runs pytest
      against a `postgres:17`
      service with the three roles
      created from the Compose
      init scripts.

    Files to read (every file
    before drafting):
    - docs/brief/judgemetrics-
      master-project-specification.xml
      (`<testing_strategy>`
      property_tests,
      golden_dataset,
      integration_tests).
    - ROADMAP.md §4 Phase 2 (2.5),
      §5 "Definition of done".
    - docs/phase01-qa-findings.md
      (finding 2.5 and pre-ship
      item 1).
    - docs/SYNTHETIC_DATA.md,
      docs/ENTITY_RESOLUTION.md.
    - src/judgemetrics/synthetic/
      generate.py, rng.py,
      cases.py, truth.py.
    - src/judgemetrics/ingest/
      synthetic/normalize.py,
      ingest/runner.py.
    - src/judgemetrics/
      entity_resolution/
      pipeline.py.
    - src/judgemetrics/config.py
      (database URLs), db/
      session.py, db/migrations.py.
    - tests/conftest.py,
      tests/integration/
      conftest.py,
      test_migrations.py,
      test_synthetic_ingest.py,
      test_entity_resolution.py,
      test_api_cases.py.
    - infra/docker/ (Postgres init
      scripts), docker-compose.yml,
      .env.example,
      .github/workflows/ci.yml,
      pyproject.toml (pytest
      config, markers).
  </context>

  <goal>
    Ship the Hypothesis property
    tests and the golden
    regression suite the brief
    requires, and the scratch
    test database so that `uv run
    poe check` is green in CI and
    locally without emptying a
    seeded database.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      `uv add --group dev
      hypothesis`; register a
      Hypothesis profile in
      `tests/conftest.py` (`ci`:
      `max_examples=50`,
      `deadline=None`; `dev`:
      `max_examples=20`; selected
      by `HYPOTHESIS_PROFILE`, CI
      sets `ci`) and pytest
      markers `property` and
      `golden` in `pyproject.toml`
      with descriptions.
    </requirement>

    <requirement>
      `tests/property/` (package):
      `test_event_ordering.py` —
      strategy `seeds =
      integers(0, 2**31 - 1)`;
      for `GOLDEN` scale (and a
      reduced `ScaleSpec` variant
      exported by `synthetic/
      config.py` as `TINY` for
      tests: 2 courts, 3 judges, 12
      persons, 16 cases) generate
      into a temp dir and assert:
      every `truth/subsequent_
      events.csv` row has
      `outcome_at > index_at` and
      `days_after >= 1`; every
      charge `disposed_at >=
      filed_at`; every sentence
      after its disposition; every
      decision inside its case's
      filed/closed window; then
      normalize through the
      synthetic connector and
      assert the same on the
      `JusticeEventDraft`,
      `ChargeDraft`, `DecisionDraft`,
      and `SentenceDraft` values.
      `test_case_numbers.py` —
      `text()` variants of a case
      number with inserted spaces,
      case changes, and
      punctuation normalize to
      the same value and
      normalization is idempotent.
      `test_resolution_
      consistency.py` — for random
      seeds at `TINY` scale,
      `resolve_persons` over the
      drafts in two different
      shuffles (a `permutations`
      strategy over the draft
      list) yields the same person
      per participant hash, and
      the deterministic stage maps
      equal `source_participant_
      id` hashes to equal persons
      (integration marker; uses
      the scratch database).
      `test_ingest_idempotent.py`
      — integration: for `TINY`
      datasets from 5 sampled
      seeds (`max_examples=5`,
      `derandomize=True` so CI is
      reproducible), ingest twice
      through `run_ingest(...,
      from_fixture=<tmp>/source)`
      and assert the second run
      creates and updates zero
      rows in every canonical
      table and writes zero
      candidates; purge the runs
      afterwards.
    </requirement>

    <requirement>
      `tests/golden/` (package,
      marker `golden`):
      `test_golden_fixture.py`
      (byte-identical
      regeneration; `verify_
      dataset` clean; `manifest.
      generator_version` equals
      `GENERATOR_VERSION` — a bump
      without regeneration fails
      here); `test_golden_
      resolution.py` (module-
      scoped golden ingest;
      parametrized over every row
      of `truth/resolution_
      expectations.csv` asserting
      the stored decision; the
      split persons share one
      public key; ambiguous pairs
      are in review); `test_
      golden_counts.py` (canonical
      counts per table equal the
      manifest counts minus
      planted duplicates; predicted
      data-quality issues exist;
      every case-level row's
      provenance hash matches the
      fixture file); `test_public_
      contract.py` (the OpenAPI
      document names no restricted
      property; as the app role,
      `SELECT` from `person_
      identifier`, `entity_
      resolution_candidate`, and
      `audit_log` raises
      `InsufficientPrivilege`;
      every `/cases/{id}` response
      for the golden cases carries
      only public keys). Step 3's
      integration test keeps its
      narrower assertions; the
      golden suite is the
      parametrized, permanent
      form.
    </requirement>

    <requirement>
      Scratch test database:
      `infra/docker/postgres-init/
      <NN>_test_database.sql` (or
      the existing init script
      pattern) creates
      `judgemetrics_test` owned by
      the Compose superuser with
      `pg_trgm` and the same
      default privileges for the
      three roles; `.env.example`
      documents `JUDGEMETRICS_
      TEST_DATABASE_URL`
      (placeholder); `Settings.
      test_database_url: str |
      None`; `tests/conftest.py`
      exposes a `test_settings`
      fixture whose database URLs
      (app, ingest, admin) point
      at `JUDGEMETRICS_TEST_
      DATABASE_URL` when set — the
      migration round-trip test,
      every fixture-ingesting
      integration test, the
      property tests, and the
      golden suite use it; when it
      is unset they fall back to
      the configured database with
      today's behaviour and emit
      one pytest warning naming
      the variable. The round-trip
      test upgrades the scratch
      database to head at session
      start so the other tests
      find the schema. CI sets the
      variable to the service
      database (one database is
      fine in CI). `docs/ROADMAP.md`
      retires the known issue and
      `CONTRIBUTING.md` explains
      the variable; the API tests'
      "fixture rows resolve to the
      live judges" caveat is
      retired with it.
    </requirement>

    <requirement>
      Verify locally: `uv run poe
      seed` on the main database,
      then `uv run poe check`, then
      `SELECT count(*) FROM
      court_case` unchanged, and
      `/api/v1/coverage` still
      reports the synthetic source
      — record the result in the
      PR body and docs/ROADMAP.md.
      CI runtime for the `python`
      job must stay under its
      current timeout; report the
      before/after duration.
    </requirement>

    <requirement>
      Docs: `tests/fixtures/golden/
      README.md` (the regeneration
      rule and the `GENERATOR_
      VERSION` guard),
      `docs/SYNTHETIC_DATA.md`
      (property invariants
      listed), `docs/ENTITY_
      RESOLUTION.md` (the golden
      suite as the regression
      gate), `CONTRIBUTING.md`
      (markers, Hypothesis profile,
      the test database),
      `AGENTS.md` (decisions:
      `TINY` scale for property
      tests, derandomized
      integration properties, the
      test database fallback
      rule), `docs/ROADMAP.md`.
    </requirement>

    <requirement>
      Filepath comment: every new
      file gets the repo-relative
      path as the first line.
    </requirement>
  </requirements>
</task>
```

### Step 5 acceptance criteria

- `uv run pytest -m property` and `uv run pytest -m golden` pass
  locally and in the CI `python` job; the four property tests cover the
  brief's three Phase 2 properties (subsequent event never precedes its
  index event; rerunning an ingestion produces no duplicates; identical
  deterministic identifiers resolve consistently) plus case-number
  normalization.
- `tests/golden/test_golden_resolution.py` is parametrized over every
  row of `truth/resolution_expectations.csv` and passes;
  `test_golden_fixture.py` fails when `GENERATOR_VERSION` is bumped
  without regenerating the fixture (demonstrated in the PR body by a
  temporary bump, then reverted).
- `test_public_contract.py` proves `person_identifier`,
  `entity_resolution_candidate`, and `audit_log` are unreadable by the
  app role and absent from the OpenAPI document.
- With `JUDGEMETRICS_TEST_DATABASE_URL` set locally, `uv run poe check`
  leaves the seeded database's row counts unchanged (recorded in
  `docs/ROADMAP.md`); with it unset, the suite still passes and warns
  once.
- The CI `python` job stays within its timeout with the new suites
  (duration recorded in the PR body).
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean
  (test URL placeholder only), SAST clean, dependency audit clean
  (`hypothesis` passes `pip-audit --strict`) — and the sensitive-data
  review confirms strategies never generate names and failing-example
  output carries no restricted value.

---

## Step 6 — QA & Verification Script ✅

**Status:** Complete — PR #17 (2026-09-19)

> **Goal:** Package the verification matrix into
> `scripts/verify_phase02.py` (with `--fast`, `--py`, `--node`, `--e2e`,
> `--security`, `--all`, and `--post` modes), produce
> `docs/phase02-qa-findings.md`, add `02` to the `phase-verify.yml`
> matrix and `phase-verify (02)` to the required contexts, and bring
> `docs/ROADMAP.md` up to date for the `v0.2.0-phase-2` tag. The script
> checks every Step 1 through Step 5 deliverable statically and runs the
> Python (including the `property` and `golden` markers), web,
> end-to-end, and security suites in the appropriate modes; the
> `--post` mode runs the full V1–V6 sweep, the seed idempotency check
> against the local database, and `gh pr checks` when the CLI is logged
> in. It mirrors `scripts/verify_phase01.py` so CI logs read
> continuously across phases.

**Branch:** `feature/phase02-step6-verify`

**Deploys:** nothing beyond merge — the `phase-verify.yml` matrix entry
and its required context are live on merge.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** A bounded, mostly mechanical translation of the
Steps 1–5 deliverables into numbered static checks, mode dispatch, a
CI matrix entry, and the findings rollup — PRIMARY `coding`, Medium
complexity, where an A-tier coder would suffice; the selector still
ranks by the highest PRIMARY tier first, and under the operator's flat
claude.ai Max subscription the flat-funding gate suspends tier-down on
cost grounds for routine work, so Claude Opus 5 (S in coding,
Terminal-Bench 2.1 89.1; supersedes Opus 4.8) on Claude Code remains the
pick at zero marginal cost. Effort is `Max` and Thinking `On` for the
same reason — no saving from running lower, and the script's
correctness gates every later phase's CI. Backup: GPT-5.3 Codex on
Codex (ChatGPT Plus; Intelligence High). Conversation is New per
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
       feature/phase02-step6-verify`
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
       rejected. Stop the local
       API before `uv run poe
       gate` or `git commit`.

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
       the new `phase-verify (02)`
       once it is added to the
       required contexts (the
       `gh api` command in
       CONTRIBUTING.md; `gh pr
       edit` is known to fail on
       this token — use `gh api`).
       If the PR falls behind main,
       refresh with `gh pr
       update-branch --rebase` —
       never merge main into the
       branch (`required_linear_
       history: true`). Once green:
       `gh pr merge <PR> --squash
       --delete-branch`. This
       step's `**Deploys:**` line
       is "nothing beyond merge";
       run `--post` locally
       against the Compose services
       before Stage 6.

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
       docs/ROADMAP.md (Phase 2
       complete; tag
       `v0.2.0-phase-2` on the
       squash-merged commit; next
       milestones). Once the PR is
       merged, the tag is pushed,
       and every acceptance
       criterion for this step is
       affirmatively met, end your
       final response with the
       verbatim line "Step 6 is
       complete. You can now move
       on to Phase 3." Phase 3
       begins in a fresh
       conversation after `uv run
       poe kit` and the Phase 3
       roadmap are done. Put any
       caveats or ideas in a short
       "Follow-ups (non-blocking)"
       note AFTER that line. If any
       criterion is unmet, state
       plainly that the step is
       NOT complete, name what
       failed, and omit the
       completion line.
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
    AUTHORS the `--security`
    verify mode, so its own diff
    must still pass the gate
    before commit:

    1. SECRET / PII SCAN. No
       credentials or tokens in
       the diff (`detect-secrets`).
       The script prints names and
       paths, never file contents,
       so a planted secret can
       never be echoed into a CI
       log.

    2. SAST. No new injection,
       unsafe deserialization,
       weak crypto, path
       traversal, or unsafe-eval
       pattern (`bandit`).
       Subprocesses take argument
       lists, never shell strings;
       executables are resolved
       with `shutil.which`.

    3. DEPENDENCY AUDIT. The
       script is standard-library
       only; no dependency is
       added.

    4. SENSITIVE-DATA REVIEW.
       `--security` runs the gate
       over the phase's surface;
       the security backstop check
       greps for secret patterns
       AND for restricted column
       names in `docs/openapi.json`
       and `web/lib/api/schema.d.ts`,
       and for any word-list
       violation marker; the
       `--post` seed check reads
       counts only.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 2.
    Step 6: QA + verification
    script.

    Steps 1 through 5 have been
    implemented. Now create the
    verification script, QA
    findings doc, and CI matrix
    update.

    Reference script (pattern
    template):
    - scripts/verify_phase01.py
      (structural precedent:
      argparse modes, `check_NN`
      functions, `_missing` /
      `_lacks` / `_git_ls_files` /
      `_poe_tasks` helpers, the
      `pnpm` helper with
      `cwd=web/`, `[PASS] NN` /
      `[FAIL] NN — reason`, the
      summary table, `--post`
      reading CI checks through
      `gh pr checks`).

    Phase 2 deliverables to verify
    (44 static checks across Steps
    1 through 5, the security
    backstop, and the Step 6
    self-checks):

    Step 1 (generator) — checks
    1-8:
    1.  src/judgemetrics/synthetic/
        {config,rng,wordlists,
        world,cases,edge_cases,
        truth,writer,generate}.py
        exist.
    2.  synthetic/config.py
        defines GOLDEN, DEMO, TINY,
        and GENERATOR_VERSION;
        DEMO's literal counts meet
        the brief's minimums (regex
        over the dataclass call).
    3.  synthetic/ never imports
        `datetime.now`,
        `uuid.uuid4`, `os.urandom`,
        or calls module-level
        `random.` functions (grep).
    4.  tests/fixtures/golden/
        manifest.json exists, and
        `source/` holds the nine
        CSVs, `truth/` the five
        truth files and README.
    5.  Every sha256 in the golden
        manifest matches the file
        on disk (hashlib over
        `git ls-files`).
    6.  data/reference/
        synthetic_offenses.csv
        exists with a header.
    7.  docs/SYNTHETIC_DATA.md
        exists and names
        `truth_version` and
        `GENERATOR_VERSION`.
    8.  cli.py registers the
        `synthetic` group with
        `generate` and `verify`.

    Step 2 (connector + seed) —
    checks 9-17:
    9.  ingest/base.py defines the
        nine case-level drafts.
    10. ingest/runner.py defines
        `_upsert_cases` through
        `_upsert_justice_events`.
    11. alembic/versions contains
        `0003_case_level_natural_
        keys.py` creating
        `uq_person_identifier_
        stable` and `source_row_id`.
    12. data/reference/
        case_vocabulary.yaml exists
        with `version:`;
        normalization/vocabulary.py
        exists.
    13. security/identifiers.py
        defines `hash_identifier`;
        config.py defines
        `identifier_pepper` as
        `SecretStr` and
        `synthetic_dir`.
    14. ingest/synthetic/
        {schema,parse,normalize,
        connector,sources}.py exist;
        registry lists the module;
        `source_type = "synthetic"`.
    15. .env.example documents
        JUDGEMETRICS_IDENTIFIER_
        PEPPER with a placeholder
        value.
    16. poe task `seed` exists;
        the Makefile mirrors it;
        cli.py registers `seed`.
    17. logging.py scrubber
        denylist contains
        `identifier_pepper`,
        `value_hash`,
        `date_of_birth`,
        `full_name`.

    Step 3 (entity resolution) —
    checks 18-25:
    18. entity_resolution/
        {config,features,
        deterministic,rules,
        scoring,candidates,queue,
        merge,pipeline}.py exist.
    19. scoring.py defines
        `class Scorer(Protocol)`
        and `StubScorer`.
    20. data/reference/
        entity_resolution_
        thresholds.yaml exists;
        config.py defines
        MODEL_VERSION.
    21. alembic/versions contains
        `0004_entity_resolution_
        review.py` creating
        `audit_log` and the
        `audit_log_append_only`
        trigger.
    22. rules.py contains no rule
        that matches on
        `same_name` without
        `same_dob`/`same_name_dob`
        (grep for the guard
        comment `never name alone`
        and the `name_only`
        rejection).
    23. cli.py registers `er run`,
        `er review list`, `er
        review decide`.
    24. docs/ENTITY_RESOLUTION.md
        exists and names every
        stage.
    25. tests/integration/
        test_entity_resolution.py
        exists.

    Step 4 (API + pages) — checks
    26-34:
    26. api/routes/cases.py and
        api/routes/coverage.py
        exist.
    27. docs/openapi.json lists
        exactly the twelve v1
        paths plus health and
        ready.
    28. docs/openapi.json contains
        no property named
        value_hash, encrypted_
        value, date_of_birth,
        full_name, or person_
        identifier.
    29. schemas/common.py
        `Provenance` has
        `synthetic`;
        schemas/cases.py and
        schemas/coverage.py exist.
    30. web/app/cases/[caseId]/
        page.tsx, web/app/judges/
        [judgeId]/cases/page.tsx,
        web/components/
        synthetic-banner.tsx exist.
    31. web/app/layout.tsx renders
        the banner component.
    32. web/tests/e2e/smoke.spec.ts
        contains a case-page
        scenario (`/cases/`).
    33. ci.yml `e2e` job ingests
        tests/fixtures/golden/
        source and sets
        JUDGEMETRICS_IDENTIFIER_
        PEPPER.
    34. docs/API.md documents
        `/cases/{case_id}`,
        `/cases/{case_id}/timeline`,
        `/judges/{judge_id}/cases`,
        `/coverage`.

    Step 5 (property + golden) —
    checks 35-39:
    35. pyproject.toml declares
        `hypothesis` in the dev
        group and markers
        `property` and `golden`.
    36. tests/property/
        {test_event_ordering,
        test_case_numbers,
        test_resolution_
        consistency,
        test_ingest_idempotent}.py
        exist.
    37. tests/golden/
        {test_golden_fixture,
        test_golden_resolution,
        test_golden_counts,
        test_public_contract}.py
        exist.
    38. .env.example documents
        JUDGEMETRICS_TEST_DATABASE_
        URL; config.py defines
        `test_database_url`; the
        Postgres init scripts
        create `judgemetrics_test`.
    39. tests/fixtures/golden/
        README.md names the
        regeneration command.

    Security backstop — check 40:
    40. No private-key header,
        `AKIA`-style key, or
        `-----BEGIN` block under
        src/, web/ (excluding
        node_modules), tests/,
        docs/, infra/, or data/;
        and no restricted column
        name in web/lib/api/
        schema.d.ts.

    Step 6 self-checks — checks
    41-44:
    41. scripts/verify_phase02.py
        exists.
    42. docs/phase02-qa-findings.md
        exists.
    43. docs/phase02-roadmap.md
        exists (this doc).
    44. .github/workflows/
        phase-verify.yml matrix
        includes "02".

    Files to read:
    - scripts/verify_phase01.py
      (primary structural
      template).
    - tests/unit/
      test_phase01_verification.py.
    - all Phase 2 implementation
      files from Steps 1 through 5
      (paths above).
    - .github/workflows/ci.yml,
      phase-verify.yml.
    - CONTRIBUTING.md "Repository
      settings".
    - docs/phase01-qa-findings.md
      (rollup format).
    - docs/ROADMAP.md (to update).
  </context>

  <goal>
    Create scripts/verify_phase02.py
    with 44 static deliverable
    checks (Steps 1 through 5, the
    security backstop, and the
    Step 6 self-checks) plus a
    post-implementation V1-V6
    matrix. Create
    docs/phase02-qa-findings.md.
    Add "02" to the
    phase-verify.yml matrix and
    `phase-verify (02)` to the
    required status checks.
    Update docs/ROADMAP.md and tag
    the phase.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Read scripts/verify_phase01.py
      end-to-end for structure,
      flag parsing, output format,
      helper conventions, and the
      final summary table. Mirror
      the format exactly so the
      Phase 2 script is visually
      continuous with the Phase 1
      script in CI logs. Do not
      import from verify_phase01
      (each script stands alone).
    </requirement>

    <requirement>
      scripts/verify_phase02.py
      modes (argparse, mutually
      exclusive, default = --fast
      plus --py):
      - --fast: static checks only,
        CI-safe on Ubuntu and
        Windows; only pathlib / re
        / json / hashlib /
        subprocess for `git
        ls-files`; MUST complete in
        under 30 seconds.
      - --py: static + `uv run poe
        lint`, `uv run poe
        fmt-check`, `uv run poe
        typecheck`, `uv run pytest
        -m "not integration"`, and
        the integration, property,
        and golden suites when a
        database URL is configured
        (`JUDGEMETRICS_TEST_
        DATABASE_URL` preferred,
        else the configured
        database with the Phase 1
        caveat printed).
      - --node: static + pnpm
        (cwd=web/) `lint`,
        `typecheck`, `build`,
        `test` (build before test).
      - --e2e: static + pnpm
        (cwd=web/) `e2e` (requires
        the API and web app
        running over a database
        holding the FJC and golden
        fixtures; prints a clear
        skip reason otherwise).
      - --security: the gate over
        the phase's surface — `uv
        run detect-secrets-hook
        --baseline .secrets.baseline
        <every tracked file>`
        (batched under the Windows
        argv limit), `uv run bandit
        -c pyproject.toml -r src
        alembic scripts`, `uv run
        python scripts/
        audit_deps.py`, pnpm
        (cwd=web/) `audit
        --audit-level=high`;
        CI-safe on Ubuntu; exits
        non-zero on any finding.
      - --all: static + py + node +
        e2e + security (web and e2e
        suites before the Python
        suites, as verify_phase01
        does, for the no-test-
        database fallback case).
      - --post: static + V1-V6 +
        the seed idempotency probe
        (when a database URL and
        the seeded dataset are
        present: read the canonical
        row counts, run
        `judgemetrics seed`, read
        them again, PASS when
        unchanged; SKIP with reason
        otherwise) + (when `gh` is
        logged in) `gh pr checks`
        against the current branch
        for V4.4 (`container`),
        V4.5 (`e2e`), and V6.1
        (`phase-verify (02)`).

      Static checks: the 44
      numbered checks above, each
      using pathlib / re / json /
      hashlib / `git ls-files`
      only, printing a clear PASS
      / FAIL line referencing the
      deliverable number,
      independent of the others.
      Check 40 is the security
      backstop (matches complete
      key headers only, as
      verify_phase01 check 39
      does, over `git ls-files` of
      the six trees excluding
      lockfiles, plus the
      restricted-name scan of
      schema.d.ts).
    </requirement>

    <requirement>
      Post-implementation V-checks
      section mirroring the Phase
      1 structure (V1-V6):

      V1 — Generator
      - V1.1 Static checks 1-8 all
        PASS.
      - V1.2 test_synthetic_
        generator.py and
        test_cli_synthetic.py pass
        (--py).
      - V1.3 `judgemetrics
        synthetic verify
        tests/fixtures/golden`
        exits 0 (--post).

      V2 — Connector + seed
      - V2.1 Static checks 9-17 all
        PASS.
      - V2.2 test_case_numbers.py,
        test_identifiers.py,
        test_vocabulary.py,
        test_synthetic_connector.py,
        test_drafts.py pass.
      - V2.3 test_synthetic_
        ingest.py and test_
        migrations.py pass against
        Postgres.
      - V2.4 Seed idempotency probe
        PASS (--post, local).

      V3 — Entity resolution
      - V3.1 Static checks 18-25
        all PASS.
      - V3.2 test_er_*.py unit
        tests pass.
      - V3.3 test_entity_
        resolution.py passes
        against Postgres.

      V4 — Case API + pages
      - V4.1 Static checks 26-34
        all PASS.
      - V4.2 test_api_cases.py,
        test_api_coverage.py,
        test_api_judges.py,
        test_api_search.py,
        test_query_counts.py,
        test_openapi.py pass.
      - V4.3 pnpm lint, typecheck,
        build, test pass; schema
        regeneration has no diff;
        bundle scan clean (--node).
      - V4.4 Both images build and
        scan clean (`container`
        via gh pr checks).
      - V4.5 Playwright case
        scenario passes (--e2e /
        `e2e` job).

      V5 — Property + golden
      - V5.1 Static checks 35-39
        all PASS.
      - V5.2 `pytest -m property`
        passes.
      - V5.3 `pytest -m golden`
        passes.

      V6 — CI integration +
      security
      - V6.1 verify_phase02.py
        --fast exits 0 on Ubuntu
        CI (`phase-verify (02)`).
      - V6.2 phase-verify.yml
        matrix includes "02".
      - V6.3 All 44 static checks
        pass.
      - V6.4 verify_phase02.py
        --security exits 0.
    </requirement>

    <requirement>
      Create tests/unit/
      test_phase02_verification.py
      with: test_roadmap_doc_
      exists, test_qa_findings_doc_
      exists, test_verify_script_
      fast_exits_zero (runs the
      script's --fast in a
      subprocess), test_phase_
      verify_matrix_includes_02.
      Keep test_phase01_
      verification.py unchanged.
    </requirement>

    <requirement>
      Update .github/workflows/
      phase-verify.yml to include
      "02" in the matrix — append
      to the existing
      `matrix.phase` list;
      preserve "01". Add the check
      `phase-verify (02)` to the
      required status contexts on
      `main` with the `gh api`
      command recorded in
      CONTRIBUTING.md "Repository
      settings" (record the new
      context there). The workflow
      must set JUDGEMETRICS_
      IDENTIFIER_PEPPER only if a
      mode it runs needs it
      (`--fast` and `--security`
      do not).
    </requirement>

    <requirement>
      Create docs/phase02-qa-
      findings.md with rollup
      sections for Steps 1 through
      5 (every finding, its class
      per the Triage rule, and the
      guard added), a Step 6
      verify-script rollup, an
      "Alarm exercise" section
      (break one static check on
      the PR, observe `phase-verify
      (02)` and `test` fail, fix,
      observe both pass; record
      commit SHAs and run ids), a
      "Pre-ship items" section
      (documented limitations at
      the Phase 2 exit), and the
      Phase 3 carry-over checklist
      (at minimum: word similarity
      for surname search; the
      metric expectations in
      truth/metrics.json to be
      reproduced; unmerge in
      Phase 6; probabilistic
      scorer in Phase 7; `er
      review decide` admin authn
      in Phase 6).
    </requirement>

    <requirement>
      Update docs/ROADMAP.md:
      - Verify the root ROADMAP.md
        Phase 2 "Acceptance
        criteria" section matches
        this roadmap's V1-V6 checks
        (consistency audit; patch
        the root roadmap's Phase 2
        acceptance bullets if they
        drifted, in this PR).
      - Current phase → Phase 3
        not started; Phase 2
        complete with the tag.
      - Next milestones updated.
      After the squash-merge, tag
      the merge commit
      `v0.2.0-phase-2` and push
      the tag.
    </requirement>

    <requirement>
      Script prints clear pass /
      fail per check, exits 0 on
      success, exits 1 on any
      failure; mirrors the exact
      output format, check-
      numbering convention, and
      summary table of
      verify_phase01.py. --fast
      must complete in under 30
      seconds on Ubuntu CI and on
      Windows.
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

- `scripts/verify_phase02.py` exists and passes on a clean tree
  post-implementation in every mode the environment supports.
- The script has 44 static checks plus the V1–V6 post-implementation
  matrix (66 reported items in `--post`).
- `--fast` runs in under 30 seconds on Ubuntu CI and on Windows.
- `--post` runs cleanly on the maintainer's machine with the local API,
  web app, and seeded database up, including the seed idempotency
  probe.
- `docs/phase02-qa-findings.md` is complete with every rollup section,
  the alarm exercise, pre-ship items, and the Phase 3 carry-over
  checklist.
- `.github/workflows/phase-verify.yml` matrix includes `02`; the check
  `phase-verify (02)` appears on every PR and is a required context on
  `main` beside `test` and `phase-verify (01)`.
- `--security` mode exists and exits 0 (secret/PII scan, SAST over
  `src`, `alembic`, and `scripts`, dependency audits clean); V6.4 is
  green.
- `docs/ROADMAP.md` records Phase 2 as complete with the tag
  `v0.2.0-phase-2`; the root `ROADMAP.md` Phase 2 acceptance criteria
  agree with V1–V6; branch protection still passes on the resulting PR.
- **Operations:** the Phase 2 runtime surface is the local API plus the
  `seed` command; its health signals (`/api/v1/health`, `/api/v1/ready`,
  the `ingest_run` status row `seed` writes) exist, and the phase's
  alarm — the required checks `test` and `phase-verify (02)` — was seen
  to fail on a deliberately broken static check during this step and
  then pass after the fix (recorded in the QA findings).
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff and the `security`,
  `container`, and both `phase-verify` workflows are green.

---

## Post-Implementation Verification

Every V1–V6 check below runs automatically in CI on every push and
pull request — no manual invocation required — except V1.3, V2.4, and
the `--post` sweep, which the operator runs locally against the Compose
services and the seeded database before tagging `v0.2.0-phase-2` (the
`e2e` CI job covers V4.5 on Ubuntu over the FJC and golden fixtures; the
demo-scale seed is a local, wall-clock check because CI holds only the
golden fixture).

| Mode         | Workflow                                     | Runner          | Coverage                                            |
| ------------ | -------------------------------------------- | --------------- | --------------------------------------------------- |
| `--fast`     | `phase-verify.yml` (matrix entry `02`)       | Ubuntu          | Static checks 1–44, V1.1, V2.1, V3.1, V4.1, V5.1, V6.1–V6.3 |
| `--py`       | `ci.yml` (`python` job, Postgres service)    | Ubuntu          | V1.2, V2.2, V2.3, V3.2, V3.3, V4.2, V5.2, V5.3      |
| `--node`     | `ci.yml` (`web` job)                         | Ubuntu          | V4.3                                                |
| `--e2e`      | `ci.yml` (`e2e` job)                         | Ubuntu          | V4.5                                                |
| `--security` | `ci.yml` (`security` and `container` jobs) + `phase-verify.yml` | Ubuntu | V4.4, V6.4                                |
| `--post`     | local (maintainer's machine)                 | Windows / Ubuntu | Full V1–V6 sweep + V1.3 + V2.4 + `gh pr checks`   |

Local invocations remain available for ad-hoc runs and pre-release
sweeps:

```bash
uv run python scripts/verify_phase02.py --post   # static + V1-V6 + seed probe + gh pr checks
```

`--post` is the canonical command to run before tagging the phase
release.

Other modes:

```bash
uv run python scripts/verify_phase02.py             # static + Python suites
uv run python scripts/verify_phase02.py --fast      # static only (CI)
uv run python scripts/verify_phase02.py --py        # static + ruff + mypy + pytest (unit, integration, property, golden)
uv run python scripts/verify_phase02.py --node      # static + web lint/typecheck/build/test
uv run python scripts/verify_phase02.py --e2e       # static + Playwright (FJC + golden fixtures)
uv run python scripts/verify_phase02.py --security  # secret scan + SAST + audits
uv run python scripts/verify_phase02.py --all       # everything
```

The script reports each V-check by id (V1.1, V2.1, …) so a failure in
any workflow above maps directly to the corresponding row below.

### V1 — Deterministic synthetic generator

> **Automated in CI.** `phase-verify.yml` → V1.1; `ci.yml` → V1.2;
> local `--post` → V1.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V1.1 | Static checks 1–8 all PASS (package modules, scale specs and minimums, no nondeterministic calls, golden fixture files and hashes, offenses table, docs, CLI group). | `phase-verify.yml` runs `verify_phase02.py --fast`. |
| V1.2 | `test_synthetic_generator.py` and `test_cli_synthetic.py` pass: byte-identical regeneration, minimums, planted items, ordering, word-list names. | `ci.yml` `python` job (`--py` locally).   |
| V1.3 | `judgemetrics synthetic verify tests/fixtures/golden` exits 0.              | `--post` locally.                                      |

### V2 — Synthetic connector, case-level publishing, seed

> **Automated in CI.** `phase-verify.yml` → V2.1; `ci.yml` → V2.2 and
> V2.3; local `--post` → V2.4.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V2.1 | Static checks 9–17 all PASS.                                                | `phase-verify.yml --fast`.                              |
| V2.2 | `test_case_numbers.py`, `test_identifiers.py`, `test_vocabulary.py`, `test_synthetic_connector.py`, `test_drafts.py` pass. | `ci.yml` `python` job.        |
| V2.3 | `test_synthetic_ingest.py` (golden fixture twice: expected counts, then zero; provenance hashes; hashes-only person material; production refusal) and `test_migrations.py` (through 0003 and 0004) pass against Postgres. | `ci.yml` `python` job with the `postgres:17` service. |
| V2.4 | Seed idempotency probe: canonical row counts unchanged after a second `judgemetrics seed`. | `--post` locally against the seeded database.  |

### V3 — Entity-resolution framework v0

> **Automated in CI.** `phase-verify.yml` → V3.1; `ci.yml` → V3.2
> and V3.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V3.1 | Static checks 18–25 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V3.2 | `test_er_features.py`, `test_er_rules.py`, `test_er_thresholds.py`, `test_er_candidates.py` pass. | `ci.yml` `python` job.                 |
| V3.3 | `test_entity_resolution.py` passes: golden expectations exact; candidates complete; idempotent rerun; audited, immutable decisions. | `ci.yml` `python` job. |

### V4 — Case API, case pages, coverage v0

> **Automated in CI.** `phase-verify.yml` → V4.1; `ci.yml` `python` →
> V4.2; `ci.yml` `web` → V4.3; `ci.yml` `container` → V4.4; `ci.yml`
> `e2e` → V4.5.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V4.1 | Static checks 26–34 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V4.2 | `test_api_cases.py`, `test_api_coverage.py`, `test_api_judges.py`, `test_api_search.py`, `test_query_counts.py`, `test_openapi.py` pass. | `ci.yml` `python` job. |
| V4.3 | `pnpm lint`, `pnpm typecheck`, `pnpm build`, `pnpm test` pass; schema regeneration has no diff; bundle contains no `JUDGEMETRICS_`. | `ci.yml` `web` job (`--node` locally). |
| V4.4 | Both images build and the vulnerability scans are clean.                    | `ci.yml` `container` job (`--post` reads it via `gh pr checks`). |
| V4.5 | Playwright case scenario passes over the FJC plus golden fixtures.          | `ci.yml` `e2e` job (`--e2e` locally).                   |

### V5 — Property tests and golden regression suite

> **Automated in CI.** `phase-verify.yml` → V5.1; `ci.yml` → V5.2
> and V5.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V5.1 | Static checks 35–39 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V5.2 | `pytest -m property` passes (event ordering, case numbers, resolution consistency, ingest idempotency). | `ci.yml` `python` job (`HYPOTHESIS_PROFILE=ci`). |
| V5.3 | `pytest -m golden` passes (fixture regeneration, resolution expectations, counts, public contract). | `ci.yml` `python` job.            |

### V6 — CI integration + security

> **Automated in CI.** `phase-verify.yml` → V6.1 through V6.4 on
> every push/PR.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V6.1 | `verify_phase02.py --fast` exits 0 on Ubuntu CI.                            | `phase-verify.yml` matrix entry `02`.                   |
| V6.2 | `phase-verify.yml` matrix includes `02`.                                    | `phase-verify.yml --fast` static check 44.              |
| V6.3 | All 44 static checks in `verify_phase02.py` pass.                           | `phase-verify.yml --fast` records pass only when zero static failures. |
| V6.4 | `verify_phase02.py --security` exits 0 (secret/PII scan + SAST + dependency audits clean). | `phase-verify.yml` runs `--security` on every push/PR. |

---

## Summary Table

| Step | Scope                                 | Model          | Platform     | Reasoning dial | Thinking | Conv | Status                  |
| ---- | ------------------------------------- | -------------- | ------------ | -------------- | -------- | ---- | ----------------------- |
| 1    | Deterministic synthetic generator     | Fable 5.1      | Claude Code  | Effort Max     | On       | New  | Complete — PR #12 |
| 2    | Synthetic connector, publishing, seed | Claude Opus 5  | Claude Code  | Effort Max     | On       | New  | Complete — PR #13 |
| 3    | Entity resolution v0, queue, audit    | Fable 5.1      | Claude Code  | Effort Max     | On       | New  | Complete — PR #14 |
| 4    | Case API, case pages, coverage v0     | Claude Opus 5  | Claude Code  | Effort Max     | On       | New  | Complete — PR #15 |
| 5    | Property tests, golden suite, test DB | Claude Opus 5  | Claude Code  | Effort Max     | On       | New  | Complete — PR #16 |
| 6    | QA + verify_phase02.py                | Claude Opus 5  | Claude Code  | Effort Max     | On       | New  | Complete — PR #17 |
| V1   | Generator scope                       | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   | -- |
| V2   | Connector and seed scope              | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   | -- |
| V3   | Entity-resolution scope               | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   | -- |
| V4   | API and pages scope                   | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   | -- |
| V5   | Property and golden scope             | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   | -- |
| V6   | CI integration                        | CI: phase-verify.yml | --   | --             | --       | --   | -- |

Backups (same platform rules, different provider): GPT-5.6 Sol on
Codex at Intelligence Extra High for Steps 1 and 3; GPT-5.3 Codex on
Codex at Intelligence High for Steps 2, 4, 5, and 6. Both are funded by
the ChatGPT Plus subscription, whose caps are modest, so they are
fallbacks for a Claude Code outage rather than parallel capacity.

---

## Model selection blocks

**Selection method.** Each block below was produced by running the
selector in `planning/model-selector.txt` (catalog exported by
roadmodel 0.2.33; re-exported with `uv run poe kit` on 2026-09-16 at
the start of this phase — no catalog change since the Phase 1 export)
against `planning/user-context.md`, in this order: Step 0a dropped no
models (the cold-start availability list is empty and no runtime
override was supplied); Step 0b dropped every `cn`-jurisdiction model
(Kimi, DeepSeek, GLM) under the allowed list `us, eu, uk, ca, au, jp,
kr`; Steps 1–4 classified each step and ranked survivors by PRIMARY
then SECONDARY tier; within the tied frontier set, a superseded model
yields to its successor in the same series (Opus 5 over Opus 4.8 and
4.7; Fable 5.1 over Fable 5) as the catalog's `best-for` rows direct;
between the tied Claude and GPT frontier models, the operator context
breaks the tie on subscription-utilization economics rather than list
price — Claude picks run at zero marginal cost on the 20x claude.ai
Max plan, while GPT picks would draw on ChatGPT Plus caps the operator
declares modest and reserves for fallback — so the GPT model becomes
the required cross-provider BACKUP (Step 7); under the operator's
`balanced` posture Fable 5.1 is reserved for the two ceiling-class
steps (Steps 1 and 3, matching the parent roadmap's §8 assignment) and
Opus 5 takes the rest, because Fable draws the Max budget down at
about twice Opus's rate for the same output. Access selection Step A00
excluded `cursor` and `xai-api` per the operator's list; Step C ranked
`claude-code` first as subscription-funded; Step E applied the
flat-funding gate (open for Claude on Claude Code), raising Effort to
`Max` with Thinking `On`; Step E2 emitted `ORCHESTRATION: None`
because no Phase 2 step warrants Ultracode under the balanced posture
(each is a single scoped deliverable, not a codebase-wide audit);
Step F emitted no MAX MODE line (Claude Code has no such dial).

```text
PROMPT: Step 1 — Deterministic Synthetic Generator
MODEL: Fable 5.1
BACKUP: GPT-5.6 Sol
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: coding with novel simulation design whose every downstream expectation derives from one seeded state, secondary planning. PICK: Fable 5.1 is S-tier in coding and S-tier in planning (HLE 59.1% and Terminal-Bench 2.1 91.4 at max) and supersedes Fable 5; reserved for this ceiling-class step under the balanced posture. EFFORT: Max effort with thinking on because the step meets the novel-problem-solving and cross-file chain-of-thought conditions and the flat-funding gate is open; orchestration None because one package and one fixture is a single scoped deliverable.

PROMPT: Step 2 — Synthetic Connector, Case-Level Publishing, and seed
MODEL: Claude Opus 5
BACKUP: GPT-5.3 Codex
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: correctness-sensitive multi-file coding against fixed contracts with a migration and Postgres integration loops, secondary agentic. PICK: Claude Opus 5 is S-tier in coding and S-tier in agentic (Terminal-Bench 2.1 89.1) and supersedes Opus 4.8. EFFORT: Max effort with thinking on because the publishers' idempotency and the hashed-identifier path are what every later ingest depends on and effort costs nothing under the open flat-funding gate; orchestration None.

PROMPT: Step 3 — Entity-Resolution Framework v0, Review Queue, and Audit Log
MODEL: Fable 5.1
BACKUP: GPT-5.6 Sol
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: coding with novel framework design — staged matching over restricted hashes, a cross-table merge, an append-only audit log — secondary planning. PICK: Fable 5.1 is S-tier in coding and S-tier in planning (HLE 59.1%, Terminal-Bench 2.1 91.4 at max) and supersedes Fable 5; the parent roadmap reserves Fable for this step. EFFORT: Max effort with thinking on because false-positive merges are a domain risk the design must resist and the flat-funding gate is open; orchestration None.

PROMPT: Step 4 — Case API, Case Pages, and Coverage v0
MODEL: Claude Opus 5
BACKUP: GPT-5.3 Codex
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: multi-file Python and TypeScript coding against fixed API and web conventions with agentic test-and-run loops. PICK: Claude Opus 5 is S-tier in coding and S-tier in agentic (Terminal-Bench 2.1 89.1), A-tier in multimodal for page screenshots, and supersedes Opus 4.8. EFFORT: Max effort with thinking on because the routes, snapshot, generated client, and pages are cross-cutting and effort is free under the open gate; orchestration None.

PROMPT: Step 5 — Property Tests, Golden Suite, and the Scratch Test Database
MODEL: Claude Opus 5
BACKUP: GPT-5.3 Codex
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: test-engineering coding with Hypothesis strategies and a small Compose, settings, and CI change. PICK: Claude Opus 5 is S-tier in coding (Terminal-Bench 2.1 89.1); the open flat-funding gate suspends tier-down for routine work, so the funded frontier model takes it at zero marginal cost. EFFORT: Max effort with thinking on because property strategies and bounded example budgets need judgment and effort is free here; orchestration None.

PROMPT: Step 6 — QA + verify_phase02.py
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

Per [`ROADMAP.md`](../ROADMAP.md) Phase 2, Phase 3, and §6 "Out of
Scope":

- Any metric, metric registry, methodology page content, provenance
  trace command, compare page, or published rate; the generator's
  `truth/metrics.json` is an expectation for Phase 3, and nothing in
  Phase 2 computes or displays a rate.
- Real case data of any kind; the first real state-court corpus (Cook
  County) is Phase 5, and its attribution rules map onto the
  vocabulary Phase 2 fixes.
- Probabilistic record linkage; Phase 2 ships the `Scorer` protocol
  and a stub, Phase 7 the model, and Phase 6 the measured error rates
  and the unmerge tool.
- Admin authentication and authorization; `er review decide` is a
  local operator command refused in production until Phase 6.
- The corrections workflow and form (Phase 3), suppression and
  takedown mechanics (Phase 6), and any deployment beyond the
  maintainer's machine (Phase 8).
- The person timeline page (`/subjects/[publicKey]`); it stays
  internal/admin-only per the brief and arrives with Phase 6's admin
  tools.

Additionally not in scope for this phase:

- Word similarity (`<%`) for surname-only search queries (Phase 1
  finding 4.1); tracked as an issue for a Phase 3 API step.
- A runtime-configurable API origin for the web image (Phase 1 finding
  5.1); Phase 8.
- Encrypting `person_identifier.encrypted_value`; Phase 2 stores hashes
  only, and the encrypted original is a Phase 5 decision tied to the
  first real source's lawful-basis review.
- Judge and court resolution across sources (synthetic judges never
  link to FJC judges by design); Phase 7's CourtListener linkage.
- Coverage completeness estimates and known-gap narratives; Phase 3's
  coverage page builds on the v0 counts.
- Generating synthetic data at any scale beyond `demo`, or a synthetic
  federal court; the synthetic world is one state-level jurisdiction.

---

_This roadmap is the execution plan for Phase 2. Update step status as
each is completed. After all steps and verification pass, Phase 2 is
complete and Phase 3 (Metrics Engine and the Complete Local Demo)
inherits the seeded synthetic database with resolved persons and
justice events, the `truth/metrics.json` expectations its registry must
reproduce exactly, the case pages its judge-page drill-down links to,
and the golden fixture and property suites as the regression harness
every metric is tested against._
