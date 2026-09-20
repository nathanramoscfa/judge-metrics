<!-- docs/phase03-roadmap.md -->
# Phase 3 Roadmap — Metrics Engine and the Complete Local Demo (First Milestone)

## Overview

Phase 3 opens the gate to every published number: it turns the seeded
synthetic database of Phase 2 into reproducible descriptive and
longitudinal metrics computed from a versioned registry, traces every
observation back to raw artifacts, and ships every remaining public page
so the brief's seventeen-item first milestone passes end to end from one
documented command. A versioned YAML registry defines every metric
(numerator, denominator, eligibility, attribution inclusion rules,
suppression threshold, version) and generates the methodology page; an
analytic frame defines index events, observation windows, time at risk,
and right-censoring; a computation engine exports a hashed snapshot,
computes observations with Wilson intervals and small-cohort
suppression, and reproduces the golden `truth/metrics.json`
expectations exactly; `judgemetrics provenance trace` and
`GET /api/v1/metrics/{observation_id}/provenance` reconstruct the chain
from an observation to source records, raw artifacts, and parser
versions; the API gains the metrics, compare, coverage, and corrections
endpoints; the web app gains the judge metric panels, the compare page,
the registry-generated methodology page, the coverage page, the
corrections form, the court page's comparable-judge table, and a
jurisdiction page v0; and `uv run poe bootstrap` plus a Playwright
walkthrough prove the milestone. Phase 3 covers the brief's development
phase 5 (Metrics Engine) through suppression and methodology versioning,
phase 6 (Web Application), and the first milestone.

Phase 3 does NOT compute an expected-outcome model, an observed/expected
ratio, or any adjusted statistic (Phase 4); it does NOT ingest any real
case data (Phase 5); it does NOT ship administrative authentication,
correction handling, or suppression tooling beyond the intake form
(Phase 6); and it does NOT deploy anything beyond the maintainer's
machine and the repository's CI (Phase 8). Every rate it publishes is a
raw descriptive rate accompanied by the case-mix context and the
statistical warnings the brief requires.

The phase lands in 6 layers:

1. **Metric registry, analytic frame, and generated methodology** —
   `data/reference/metric_registry.yaml` (version, methodology version,
   every metric with slug, kind, subject types, numerator, denominator,
   eligibility, attribution inclusion rules, index event, outcome,
   windows, suppression threshold, version; the brief's eight
   statistical warnings verbatim as `known_limitations`), the
   `judgemetrics/metrics/` package (`registry.py` loader and
   `metric_definition` sync, `frame.py` typed Polars frames,
   `attribution.py` the inclusion gate, `index_events.py`, `windows.py`,
   `exposure.py` time at risk with incarceration deferral,
   `censoring.py` right-censoring, adequately-followed cohorts, and the
   Kaplan–Meier estimator, `intervals.py` Wilson and Greenwood), migration
   `0005_metric_registry_and_snapshots`, `judgemetrics methodology
   render`, the committed `docs/METHODOLOGY.md`, and Hypothesis property
   tests over the frame.
2. **Snapshot export, computation engine, `metrics compute|verify`, and
   the golden metric tests** — `snapshot.py` (PostgreSQL → Parquet under
   `JUDGEMETRICS_SNAPSHOT_DIR` with a content hash, DuckDB views over the
   files), `compute.py` (one function per metric kind over the frame),
   `suppression.py`, `publish.py` (observations plus their member rows),
   `verify.py` (byte-for-byte reproduction from a snapshot),
   `judgemetrics metrics compute|verify`, the `compute-metrics` target,
   pipeline step 13 (incremental recompute of impacted subjects),
   `truth/metrics.json` extended under `TRUTH_VERSION` `2` (disposition-
   and sentence-indexed windows, incarceration deferral, Kaplan–Meier
   estimates) with the golden fixture regenerated, and
   `tests/golden/test_golden_metrics.py` asserting every registry metric
   equals its truth expectation exactly.
3. **Provenance trace, metrics API, and corrections intake** —
   `judgemetrics provenance trace <observation_id>`, `GET
   /api/v1/metrics` (the registry), `/judges/{id}/metrics`,
   `/courts/{id}/metrics`, `/metrics/compare`,
   `/metrics/{observation_id}/provenance`, the extended `/coverage`,
   `POST /api/v1/corrections` with the Fernet-encrypted contact and
   migration `0007_corrections_intake` (INSERT-only grant to the app
   role), the snapshot block on `/api/v1/ready`, word similarity for
   surname-only search (Phase 2 carry-over item 1), regenerated
   `docs/openapi.json` and `web/lib/api/schema.d.ts`, and `docs/API.md`
   plus `docs/PROVENANCE.md`.
4. **Judge metric panels, compare page, methodology page, and coverage
   page** — the `MetricStat` presentation component (numerator,
   denominator, date range, coverage, sample size, interval, methodology
   link, suppression notice), the judge page's pretrial, disposition,
   sentencing, and subsequent-outcome panels with the association
   statement, the comparison-cohort selector, and case drill-down;
   `/compare` (one metric at a time, comparable filters, sortable table
   with sample size, interval, and coverage warnings); `/methodology`
   rendered from `GET /api/v1/metrics`; `/coverage` with date ranges,
   snapshot, and methodology version; a cached coverage read for the
   banner (carry-over item 7); Vitest presentation-rule tests.
5. **Corrections form, court and jurisdiction pages, `bootstrap`, and the
   first-milestone walkthrough** — `/corrections` and the per-page
   "Report a data error" action, the court page's comparable-judge
   metric table, `/jurisdictions/[jurisdictionId]` v0, the `bootstrap`
   poe task and `make bootstrap`, the README's one-command startup, the
   `e2e` CI job seeding the demo dataset and computing metrics, and
   `web/tests/e2e/first-milestone.spec.ts` automating items 8–16 of the
   brief's checklist.
6. **QA + `verify_phase03.py`** — verification script (`--fast`, `--py`,
   `--node`, `--e2e`, `--security`, `--all`, `--post`),
   `docs/phase03-qa-findings.md` rollup with the alarm exercise and the
   Phase 4 carry-over checklist, the `phase-verify.yml` matrix entry `03`
   with its required context, the status update in `docs/ROADMAP.md`,
   and the tag `v0.3.0-phase-3`.

The ship test for Phase 3 is straightforward: on a clean machine
`uv run poe bootstrap` alone brings up the services, migrates, ingests
the FJC judges, seeds the synthetic dataset, and computes metrics, after
which the seventeen-item walkthrough passes (search a synthetic judge,
open the profile, view case volume and objective outcome metrics, open
an underlying case, view its timeline and provenance, return, compare
the metric against the judge's comparison cohort, read exactly how it was
calculated on the methodology page, run the full test suite); every
registry metric on the golden fixture equals its `truth/metrics.json`
expectation exactly and `judgemetrics metrics verify` reproduces every
stored observation byte for byte from its snapshot; every metric on every
page and in every API response shows numerator, denominator, date range,
coverage, sample size, and a methodology link, and cohorts below the
documented threshold are suppressed in the API and the web; every
published observation has a complete provenance trace (test) and an
observation whose chain breaks is not published; a correction request
round-trips through the form, is stored with an encrypted contact, and
is unreadable by the public role; `uv run python
scripts/verify_phase03.py --fast` and `--security` exit 0 on Ubuntu CI
under the `phase-verify.yml` matrix entry `03`; and the security gate is
clean with no per-person row reachable from any metrics endpoint
(contract test) and the encryption key absent from every log line.

**Pre-requisite:** Phase 1 closed (tag `v0.1.0-phase-1`, 2026-09-16):
its canonical schema carries `metric_definition`, `metric_observation`,
and `correction_request`, its API conventions are what the metrics
routes extend, and its web foundation is what the panels and pages are
built on. Phase 2 closed (tag `v0.2.0-phase-2`, 2026-09-18): its seeded
database with resolved persons and `justice_event` rows is what index
events and outcome windows are computed over, its `truth/metrics.json`
is the expectation the registry must reproduce exactly, its case pages
are the drill-down target of every judge metric, and its golden fixture
and property suites are the regression harness every metric is tested
against.

**Dependency:** Phase 4 (Risk Adjustment and Statistical Validation)
does not start until Phase 3's V-checks are green; it inherits the
registry and its versioning (methodology version `1.0` is Phase 4's), the
analytic frame (index events, exposure, censoring) its expected-outcome
model is fitted over, the snapshot mechanism its model artifacts are
pinned to, the `metric_observation` columns reserved for expected
counts, ratios, and intervals, and the judge and compare pages its
adjusted panels extend. Phase 5 inherits `source.coverage_start`,
`coverage_end`, and `observable_outcomes` as the fields every real
connector must declare. Phase 6 inherits the corrections intake and its
restricted table.

**Design rationale (snapshots as the unit of reproducibility, members
as the unit of provenance).** Observations are never computed from the
live database: `metrics compute` first exports the canonical tables to
Parquet files whose content hash is the snapshot id, and every
observation records the snapshot, the code version, the registry version,
and the methodology version it was computed under, so `metrics verify`
can reproduce it later from the same bytes even after further ingests.
Every observation also records its members — the decisions, charges,
cases, sentences, and justice events that formed its denominator and
numerator — because the brief's provenance chain runs from a published
number through eligible events to source records and raw artifacts, and a
chain that has to be re-derived is not a chain. Member rows carry entity
ids, never person keys; the public provenance endpoint exposes cases,
source records, and artifacts in the shape the case page already does.
Polars does the arithmetic; DuckDB is the read-only SQL layer over the
snapshot's Parquet files that `verify` and `provenance trace` query.
Incremental recompute after ingest (pipeline step 13) recomputes only the
subjects an ingest run touched, superseding their previous observations
rather than deleting them, so history is kept and nothing is computed in
a web request.

**Branch strategy.** Every step in this phase lands on its own
short-lived feature branch (`feature/phase03-stepM-<slug>`), opens a
pull request against `main`, waits for the project's CI workflow to go
green, and squash-merges with a Conventional Commits subject line. Direct
pushes to `main` are blocked by branch protection. See the parent
project's ROADMAP "Branch management strategy" section for the canonical
naming convention, PR rules, and release tagging — this paragraph
confirms those rules apply unchanged within this phase. Per-step
branches are listed on each step header below as `**Branch:**` so
reviewers can map commits 1:1 to the step they implement.

**Branch-first execution rule.** The very first action of every step —
before reading any files, before running any tool, before drafting any
change — is to check out the branch named in that step's `**Branch:**`
line:

```sh
git checkout -b feature/phase03-stepM-<slug>
```

This is non-negotiable. `main` is protected with `enforce_admins: true`,
so a commit on `main` cannot be pushed and must be rewound or rebased
onto the feature branch before the PR can open — an avoidable
round-trip. If you discover mid-step that you started on `main`, recover
by running the same `git checkout -b` command immediately (uncommitted
changes carry over to the new branch), then continue. AI coding agents
executing a step from this roadmap must treat the branch checkout as
Step 0 of every step.

**Worktree rule.** One working tree, one step in flight — the lifecycle
below assumes the primary checkout. A second working tree is created
only with `git worktree add`, and only for the three cases the parent
ROADMAP "Worktree strategy" sanctions: a `hotfix/` branch interrupting
this step (cut from `origin/main` in its own worktree so this step's
tree is untouched); steps the Execution Order below explicitly draws in
parallel (each in its own worktree AND its own conversation); and
worktree-isolated subagents inside a step (throwaway trees that merge
back into the step branch locally and are removed before the PR opens).
In those cases Stage 1 becomes `git fetch origin && git worktree add -b
feature/phase03-stepM-<slug> .worktrees/<slug> origin/main`, the
worktree is bootstrapped before any test or build (`uv sync`, `pnpm
install` in `web/`, `.env` copied — a worktree has none of the primary
tree's untracked state, and it must never borrow the primary tree's
editable install), the Stage 4 merge runs from the primary tree, and
Stage 5 removes the worktree BEFORE pruning the branch. Undeclared
parallelism is a lifecycle violation, not a shortcut. Worktree location
for this project: git-ignored `.worktrees/<slug>/` inside the
repository, matching the parent ROADMAP.

**Security-first execution rule.** Security is not a phase — it is a
gate on every commit of every step. Before each `git commit`, the step's
work must pass the local, fail-closed security gate: secret/PII scan
clean, SAST clean, dependency audit clean, and a diff review confirming
no sensitive data (PII, credentials, tokens) and no new insecure pattern
(injection, weak crypto, over-broad scope, secret in a client bundle or
log line). This gate is wired into the pre-commit hook and re-run in CI,
so a security issue introduced while implementing a step is caught
during development — before it reaches the branch, the PR, or `main`.
See the parent project's ROADMAP "Security & privacy strategy" → "Per-
step security gate" for the canonical checks and tooling; each step's
XML `<task>` carries a `<security>` block restating them for the agent,
and each step's Acceptance Criteria ends with a security check. AI
coding agents executing a step MUST treat the security gate as part of
the step's definition of done, exactly like its tests. This matters most
in this phase because Step 3 introduces the first public write path
(`POST /api/v1/corrections`) and the first encryption key the API
process holds: the operator running a step's prompt must not be able to
introduce a data-exposure risk that only surfaces after merge.

**Deploy-and-verify rule.** Merged is not deployed, and deployed is not
released. Every step header carries a `**Deploys:**` line naming the
surface and environment the step's merge reaches — or `nothing beyond
merge` — and when going live needs a release, a version-floor bump, a
migration, or a redeploy, the line says so and this step (or a named
follow-on step) owns that event. Through Phase 7 the only environment is
the maintainer's machine, so in this phase "deployed" means the merged
commit runs under `uv run poe up` with migrations applied; a step whose
Deploys line names that surface carries a **Deployed & verified** bullet
(the local `/api/v1/ready` reports the migration head and snapshot the
step introduced, and the changed behaviour is exercised locally via the
hands-off recipe the step names), and that bullet must be green before
the step is declared complete. A step that introduces a required
environment variable (Step 3's `JUDGEMETRICS_CORRECTION_CONTACT_KEY`
becomes required for the API) verifies at kickoff that it exists in
`.env.example` as a placeholder and in the operator's untracked `.env`
as a real value, proven by an authenticated round-trip (a correction
request accepted), never by listing env names. See the parent ROADMAP
"Release & deployment strategy" for the surfaces table, promotion path,
staged-rollout rule, migrations, and rollback.

**Triage rule.** Findings surfaced while executing a step are classified
before they are acted on, per the parent ROADMAP "Defect handling &
triage": spec rot → edit this roadmap's affected `<task>` block now;
upstream gap → patch the earlier step's prompt and add it to the
carry-over checklist; implementation bug → fix in-step only if it blocks
this step's acceptance criteria, otherwise an issue and its own branch in
a fresh conversation; architectural question → an issue for a future
phase; process improvement → recorded where the next conversation will
read it; security finding → jumps the queue by severity; data-semantics
finding (a metric definition, attribution rule, or source value was
misread) → edit the versioned registry entry, bump its version, and
re-run `metrics verify`; data-access question → `docs/ROADMAP.md`
"Unresolved data-access questions", never an invented answer. A step's
PR contains the step plus blocking fixes only, and lists the issues it
opened. When a merged PR auto-closes an issue, the environment check is
what earns the close — reopen or follow up if a gap remains.
`docs/phase03-qa-findings.md` is the rollup: every finding, its class,
and the guard added so the class cannot recur. Phase 2's carry-over
checklist (`docs/phase02-qa-findings.md`, last section) is folded into
this roadmap as follows: item 1 (word similarity for surname search) →
Step 3; item 2 (reproduce `truth/metrics.json`, extend the truth under a
new `TRUTH_VERSION`) → Step 2; items 3, 4, and 5 → Phases 6 and 7, listed
under Not in scope; item 6 (parent-case checks across runs) → the first
step that ships a child-only export, which is Phase 5's Cook County
connector, listed under Not in scope; item 7 (a cached `/coverage` read)
→ Step 4; item 8 (`verify_phase03.py` conventions) → Step 6.

**Step lifecycle.** Every step in this phase follows the exact same
six-stage lifecycle, in order, with no exceptions. Each stage is a hard
checkpoint — if a stage is skipped, branch protection or the next step's
Stage 1 will fail loudly, and that is the safety net. AI coding agents
MUST execute all six stages before declaring a step complete.

1. **Create the branch.** Before any Read / Edit / Bash, run
   `git checkout -b feature/phase03-stepM-<slug>` from a clean,
   up-to-date `main`. The exact branch name comes from this step's
   `**Branch:**` line. When the Worktree rule applies, the equivalent is
   `git fetch origin && git worktree add -b <branch> .worktrees/<slug>
   origin/main`, followed by the worktree's bootstrap.

2. **Work on the branch, passing the security gate before every
   commit.** All commits land here. Never push to `main` directly —
   branch protection (`enforce_admins: true`) rejects it. Before each
   `git commit`, run the local security gate (secret/PII scan, SAST,
   dependency audit, sensitive-data diff review — see the step's
   `<security>` block and the parent ROADMAP "Per-step security gate").
   It is fail-closed: a finding blocks the commit, so a security issue in
   this step's work is caught here, before the PR and before `main`.
   Stop the local API before `uv run poe gate` or `git commit` (a
   running uvicorn child holds the editable install open on Windows).

3. **Open the PR.** `gh pr create --base main --head <branch>` with a
   Conventional Commits title and a body that references this roadmap
   step and its acceptance criteria. One PR per step; never bundle two
   steps into one PR.

4. **Wait for green checks, then squash-merge.** Every required status
   check (`test`, the aggregate of `python`, `security`, `container`,
   `web`, and `e2e`; `phase-verify (01)`; `phase-verify (02)`; and, from
   Step 6, `phase-verify (03)`) must report success. If the PR goes
   BEHIND main while waiting, refresh with `gh pr update-branch
   --rebase` — never merge `main` into the branch;
   `required_linear_history: true` enforces rebase. Once every check is
   green:

   ```sh
   gh pr merge <PR_NUMBER> --squash --delete-branch
   ```

   If this step's `**Deploys:**` line names a surface, the merge is not
   the finish line: run the Deployed & verified check from the
   acceptance criteria against the local environment now (see the
   Deploy-and-verify rule) before declaring the step complete.

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
   `git worktree remove <worktree-path>`, then `git worktree prune` —
   because `git branch -D` refuses a branch still checked out in a
   worktree. Confirm with `git branch -vv` that only `main` and any
   intentional long-lived branches remain locally, and with
   `git worktree list` that only the primary tree remains.

6. **Dispose of every finding, declare completion, then new
   conversation.** Before you declare anything, walk the findings this
   step surfaced and send each to its destination per the Triage rule
   above — a note that a later step needs is edited into that step's
   `<task>` block now; a wrong claim in this step's spec is fixed in this
   roadmap now; an implementation bug is fixed in-step or exists as an
   issue with a number; a judgement call you made in the diff is
   explained in the PR body; a process lesson is written where the next
   conversation reads it (`AGENTS.md` or this roadmap); a data-access
   question is a row in `docs/ROADMAP.md`. Update `docs/ROADMAP.md`
   (completed items, known issues, next milestones). A finding you can
   only *describe* has not been disposed of, and an undisposed finding is
   an unmet acceptance criterion. Only once the PR is merged, every
   acceptance criterion is affirmatively met, and every finding has a
   destination, say so plainly: end your final response with an
   explicit, unhedged completion line — verbatim shape "Step M is
   complete. You can now move on to Step M+1." — so the operator has a
   clean stopping point at which to close this conversation. That line
   is the LAST line of the response. Nothing follows it: no "Follow-ups
   (non-blocking)", no "Notes", no "Next", no "worth a glance", no
   suggested improvements. If you want to show your work, a short ledger
   may PRECEDE the line, one entry per finding naming its destination (an
   issue number, a file you edited, the PR body) — never an open item. If
   any acceptance criterion is NOT met, or any finding has no destination
   yet, do the opposite — state plainly that the step is NOT complete,
   name what is outstanding, and do not emit the completion line. "Done"
   means done, not "done, but here is what you still have to do". Then,
   for phase-boundary hygiene, the operator closes this Claude Code
   session and opens a fresh one before starting Step M+1; the new
   conversation begins again at Stage 1 of this lifecycle, with the next
   step's `**Branch:**` line driving the `git checkout -b` command. No
   work straddles two steps.

---

## Current State (as of Phase 2)

### Metrics and schema surface

- `metric_definition` and `metric_observation` exist from revision
  `0001_baseline` (`src/judgemetrics/db/models/metrics.py`) and have
  never held a row. `metric_definition` carries `slug`, `name`,
  `description`, `numerator_definition`, `denominator_definition`,
  `eligibility_definition`, `version`, unique on `(slug, version)`.
  `metric_observation` carries `subject_type` (`SubjectType`: `judge`,
  `court`, `jurisdiction`), `subject_id`, `period_start`, `period_end`,
  `cohort_size`, `observed_count`, `expected_count`, `observed_rate`,
  `expected_rate`, `standardized_ratio`, `lower_confidence_bound`,
  `upper_confidence_bound`, `suppressed_flag`, `methodology_version`,
  `computed_at`, indexed on `(metric_definition_id, subject_type,
  subject_id, period_start)`. Missing: the registry columns (kind,
  subject types, attribution rules, index event, outcome, windows,
  suppression threshold), the snapshot linkage, the window and dimension
  keys, a source link, the member rows, and a unique key. The app role
  has `SELECT` on both tables and the ingest role has DML (baseline
  grants); new tables need explicit grants in their migration.
- The case-level tables the frame reads are `court_case`, `case_party`,
  `judge_assignment` (`start_at`, `end_at`, `assignment_type`), `charge`
  (`disposed_at`, `disposition`, `disposition_actor`,
  `offense_category`, `severity`), `court_event` (`event_type` includes
  `failure_to_appear` and `revocation`), `decision` (`decision_type`,
  `actor_type`, `judicial_discretion_classification`, `decision_value`,
  `judge_id`) with `pretrial_release` (`release_at`, `detained_flag`,
  `release_type`), `sentence` (`sentence_at`, `incarceration_days`,
  `probation_days`), and `justice_event` (`person_id`, `event_type` from
  the `justice_event_type` vocabulary, `event_at`, `related_case_id`).
  Persons are read through `entity_resolution.merge.unmerged()` and
  `public_person_key` only. The vocabulary
  (`data/reference/case_vocabulary.yaml`, version 1) fixes every value
  the registry's rules name.
- `source` has no coverage window and no statement of which outcomes it
  can document; the synthetic corpus dates live only in
  `judgemetrics.synthetic.config.ScaleSpec` (`corpus_start`,
  `corpus_end`, `corpus_end_at`) and in `truth/metrics.json`
  (`corpus.end_exclusive_at`). Right-censoring needs the corpus end in
  the database, per source; Step 1 adds `source.coverage_start`,
  `coverage_end`, and `observable_outcomes`, Step 2 fills them from the
  manifest and the connector.
- `correction_request` exists from `0001` (`target_type`, `target_id`,
  `requester_contact` as `LargeBinary`, `reason`,
  `supporting_material_path`, `status` from `CorrectionStatus`,
  `resolved_at`) and is a restricted table: `REVOKE ALL ... FROM
  judgemetrics_app`. `security/crypto.py` already implements
  `encrypt_contact` / `decrypt_contact` (Fernet under
  `Settings.correction_contact_key`, `JUDGEMETRICS_CORRECTION_CONTACT_KEY`,
  placeholder in `.env.example`) and `ContactKeyMissingError`; nothing
  calls it yet. The app role therefore cannot insert a correction: Step 3
  grants `INSERT` only, and the insert never uses `RETURNING`.
- Migrations are self-contained (never import the models), create and
  drop enums explicitly, and `uv run alembic check` must report no drift;
  the head is `0004_entity_resolution_review`. Phase 3 adds `0005` (Step
  1), `0006` (Step 2: `ingest_run.metrics_snapshot_id`), and `0007`
  (Step 3).

### Truth and golden-fixture surface

- `tests/fixtures/golden/` is seed `7`, scale `golden`, `GENERATOR_VERSION`
  `1`, `TRUTH_VERSION` `1`: 3 courts, 7 judges, 63 cases, 45 true persons,
  135 decisions, 224 events, 105 charges, 21 sentences, 99 true subsequent
  events. `truth/metrics.json` carries, per judge (`J-0001` …) and per
  court (`C-0001` …), `eligible_cases`, `eligible_defendants`,
  `pretrial` (`decisions`, `released_count`, `detained_count`,
  `release_share`, court-only `statutory_release_count` and
  `unknown_actor_count`, and `windows.<30|90|180|365|730|1095>` with
  `cohort`, `followed`, `failure_to_appear_rate`, `new_case_rate`,
  `reconviction_rate`), `judicial_dismissal_rate`,
  `disposition_distribution`, `median_days_to_disposition` (`n`,
  `value`), and `sentences` (`count`, `incarceration_days_median`,
  `probation_days_median`, `incarceration_days_median_by_offense_category`)
  — every rate as `numerator`, `denominator`, `value` (`null` when the
  denominator is zero) — plus `corpus` (`start`, `end`,
  `end_exclusive_at`), `windows_days`, and a `definitions` block whose
  text is the contract (`docs/SYNTHETIC_DATA.md` "The metric set").
  Windowed rates are pretrial-release-indexed only; `truth.py` already
  models `disposition` and `sentence` index events (`index_events()`)
  and `new_charge` and `revocation` outcomes (`outcomes_of()`) in
  `subsequent_events.csv` but does not window them (Phase 2 finding 1.4;
  carry-over item 2).
- The generator draws only through named `random.Random` streams
  (`rng.py`), so extending `truth.py` changes no source file; a
  `TRUTH_VERSION` bump alone leaves `source/` byte-identical and changes
  `truth/metrics.json`, `truth/README.md`, and `manifest.json`. Adding
  the corpus dates to the manifest is a `GENERATOR_VERSION` bump. After
  regeneration `.secrets.baseline` is refreshed by scanning only the
  manifest (`docs/SYNTHETIC_DATA.md` "Regenerating the golden fixture").
  `tests/golden/test_golden_fixture.py` fails on a version bump without
  regeneration; `test_golden_counts.py` recounts the simplest truth
  metrics from the source files and is the closest precedent for the
  golden metrics test.
- `tests/property/` runs the `TINY` scale (2 courts, 3 judges, 12
  persons, 16 cases) under the `ci` and `dev` Hypothesis profiles;
  `tests/property/support.py` builds worlds in memory without a
  database. The frame's property tests (Step 1) build Polars frames from
  the same in-memory world.

### Ingest and pipeline surface

- The runner's step 13 is `recompute_metrics(session, run)` in
  `src/judgemetrics/ingest/runner.py`, a documented no-op hook called
  inside the publish transaction after step 12 and the rule stages of
  entity resolution; the run's `counts` and the published rows'
  `case_id`s are in scope when it is called. The ingest role runs it, so
  it may write metric tables once they are granted.
- `SourceInfo` (`ingest/base.py`) is the static description a connector
  gives its `source` row (`owner`, `source_type`, `access_method`,
  `terms_metadata`); `SupportsContext.load_context(artifacts)` is where
  the synthetic connector reads `manifest.json`. A coverage window is
  dataset-specific, so Step 2 adds an optional `SupportsCoverage`
  protocol (`coverage_window() -> tuple[date, date] | None`, read after
  `load_context`) and the runner writes it to `source`;
  `observable_outcomes` is static and joins `SourceInfo`.
- `judgemetrics seed` generates `data/synthetic/20260916` (demo scale)
  when the manifest is stale and ingests it; it is refused in production.
  The `e2e` CI job ingests the FJC fixture and then the golden fixture;
  the golden judges' cohorts are small (`J-0001`: 7 pretrial decisions,
  6 disposed charges), so a walkthrough over the golden fixture would
  meet suppression on most rates — Step 5 switches the `e2e` job to the
  demo seed.

### API and web surface

- API v1 paths: `/health`, `/ready`, `/judges`, `/judges/{id}`,
  `/judges/{id}/service`, `/judges/{id}/cases`, `/courts`,
  `/courts/{id}`, `/jurisdictions`, `/jurisdictions/{id}`, `/cases/{id}`,
  `/cases/{id}/timeline`, `/search`, `/coverage`. Conventions
  (`docs/ARCHITECTURE.md` "Public API v1"): routes → services →
  repositories → models with `schemas/` the only shapes that leave;
  `StrictQuery` allow-lists checked against the OpenAPI document by
  `tests/unit/test_openapi.py`, which pins the exact path set;
  `paginate` / `paginate_rows` with `count(*) OVER ()`; `ErrorBody` on
  every non-2xx; `SQLAlchemyError` → 503; the `synthetic` flag derived
  per row through `repositories.provenance.with_source` +
  `synthetic_flag()`, never from a column; statement budgets in
  `tests/integration/test_query_counts.py` (judge detail 4, lists 2,
  case detail and timeline 8, coverage 3). `/search` has the token-bucket
  limiter in `app.state.search_limiter` (`api/ratelimit.py`), `None`
  under `env == test` unless enabled. `docs/openapi.json` is regenerated
  with `uv run judgemetrics openapi export`; `web/lib/api/schema.d.ts`
  with `pnpm generate:api`; both are drift-tested.
- Search and the judges `q` filter set `pg_trgm.similarity_threshold`
  per request and match with `%` over the whole normalized name, so a
  short misspelt surname against a long name does not match ("Ginsberg"
  → "ruth bader ginsburg", 0.26). Word similarity (`<%`,
  `pg_trgm.word_similarity_threshold`, GIN-indexable) is the recorded
  improvement (Phase 1 finding 4.1; carry-over item 1).
- Web pages: `/`, `/search`, `/judges/[judgeId]`,
  `/judges/[judgeId]/cases`, `/courts/[courtId]`, `/cases/[caseId]`,
  `/coverage`, `/methodology`, `/about`. The methodology page is static
  prose whose "Status" section says the definitions arrive in Phase 3
  (`data-testid="metrics-note"`); its association statement
  (`data-testid="association-statement"`) is asserted by
  `web/tests/e2e/smoke.spec.ts`. The judge page has the service table,
  the cases panel, and the provenance panel; there is no metric
  component, no `/compare`, no `/corrections`, no
  `/jurisdictions/[jurisdictionId]`. The root layout is `force-dynamic`
  because `components/synthetic-banner.tsx` reads `/coverage` per
  request (carry-over item 7). `lib/api/client.ts` never throws
  (`ApiResult`); pages render `ErrorState` / `EmptyState`; `lib/format.ts`
  and `lib/links.ts` hold formatting and route helpers. Playwright
  (`web/tests/e2e/smoke.spec.ts`) discovers a synthetic judge and case
  through the API; the config starts no server.
- `/api/v1/ready` reports the Alembic head; `/api/v1/health` reports the
  version. Neither knows about snapshots.

### Security & sensitive-data surface

- Sensitive data this phase handles: correction requester contacts
  (encrypted at rest under `JUDGEMETRICS_CORRECTION_CONTACT_KEY`; the
  API process holds the key to encrypt and never decrypts; the app role
  has no `SELECT` on `correction_request`; the key and the contact are
  denylisted in the log scrubber), pseudonymous person linkage inside the
  frame (windows are computed per resolved person, but no observation,
  member row, trace, or API response carries a person id or public key —
  the contract test over the OpenAPI document and the database grants is
  extended to the metrics endpoints), and the synthetic label (every
  observation's `synthetic` flag derives from its source through the
  same join as every other row). The restricted `person_identifier` and
  `audit_log` tables stay unreachable through every new route.
- Controls to mirror: `security/identifiers.py` and `security/crypto.py`
  for anything cryptographic (no hand-rolled primitives); `logging.py`'s
  scrubber denylist (`pepper`, `value_hash`, `date_of_birth`,
  `full_name`, `person_id`); the pre-commit gate (`detect-secrets`
  against `.secrets.baseline`, `bandit` over `src alembic scripts`,
  `pip-audit --strict --require-hashes` over the `uv.lock` export,
  `pnpm audit --audit-level=high`, `eslint-plugin-security` with
  `--max-warnings 0`); a bandit suppression sits after the ruff one with
  the justification between them. New dependencies this phase: `duckdb`
  (Step 2) — it must pass the audit and needs no network at import or
  query time (no extension downloads).
- The public write path (`POST /api/v1/corrections`) is the first: it
  validates every field with Pydantic (bounded lengths, an allow-listed
  `target_type`, a UUID `target_id` that must exist), rate-limits per
  client with the existing token bucket, inserts with a client-generated
  UUID and no `RETURNING` (the app role has no `SELECT`), stores nothing
  the caller typed in a log line, and answers `202` with the id only.

### Operations & observability surface

- Runtime surfaces before this phase: the API (`/api/v1/health`,
  `/api/v1/ready` with the migration head) and the ingest runner
  (`ingest_run` rows with status and failure reason). This phase adds
  the analytics snapshot: `compute-metrics` is a job whose health signal
  is `metrics verify` green on the latest snapshot (ROADMAP "Operations
  & observability strategy", "Analytics snapshot" row) and whose alarm
  is a non-zero exit from `metrics verify`. Step 2 makes `verify` exit 1
  on any mismatch, Step 3 adds the latest snapshot (id, `computed_at`,
  methodology version) to `/api/v1/ready`, and Step 6's alarm exercise
  tampers one observation in the scratch database and records `verify`
  failing and then passing. Snapshots live under
  `JUDGEMETRICS_SNAPSHOT_DIR` (default `data/snapshots/`, git-ignored);
  the object-store variant is Phase 8.

### Documentation surface

- `docs/ARCHITECTURE.md` (ingest pipeline, roles, API v1, web tier),
  `docs/API.md` (endpoints, pagination, filters, errors, provenance
  block, query budget), `docs/DATA_MODEL.md` (tables, natural keys,
  identifier kinds, vocabularies, grants, departures from the brief),
  `docs/SYNTHETIC_DATA.md` (the metric set), `docs/ENTITY_RESOLUTION.md`,
  `docs/DATA_SOURCES.md`, `README.md` (quick start), and `AGENTS.md`
  (architectural decisions) exist. Missing: `docs/METHODOLOGY.md`
  (generated, Step 1), `docs/PROVENANCE.md` (Step 3), a "Metrics engine"
  section in `docs/ARCHITECTURE.md` (Steps 1–2), the metrics endpoints in
  `docs/API.md` (Step 3), the `bootstrap` quick start in `README.md`
  (Step 5), and the Phase 3 decisions in `AGENTS.md` (every step).

### Verification surfaces

- `scripts/verify_phase01.py` and `scripts/verify_phase02.py` exist;
  `verify_phase02.py` is the most recent template (Python, standard
  library only; mutually exclusive `--fast`, `--py`, `--node`, `--e2e`,
  `--security`, `--all`, `--post`; default `--fast` plus `--py`; 44
  numbered static checks over `pathlib`, `re`, `json`, `hashlib`, and
  `git ls-files`; `[PASS] NN` / `[FAIL] NN — reason`; subprocess suites
  with argument lists over PATH-resolved `uv`, `pnpm`, `gh`; the V-matrix
  in `--post` read through `gh pr checks` where a check is a CI job; the
  seed idempotency probe; a summary table; names and paths only, never
  file contents). `tests/unit/test_phase02_verification.py` runs `--fast`
  so the aggregate `test` check fails with the phase check.
- `.github/workflows/phase-verify.yml` matrix includes `"01"` and `"02"`;
  Phase 3 adds `"03"`, and `phase-verify (03)` becomes a required context
  on `main` (`CONTRIBUTING.md` "Repository settings"; `gh pr edit` is
  unreliable on this machine, so the branch-protection edit is done with
  `gh api`). Earlier phases' OpenAPI checks assert their paths as a
  subset, so Phase 3's new routes never fail a required check;
  `tests/unit/test_openapi.py` pins the exact set and is updated in Step
  3.

---

## Execution Order

```
Step 1  (registry + analytic frame)      data/reference/metric_registry.yaml,
                                          judgemetrics/metrics/ (registry,
                                          frame, attribution, index_events,
                                          windows, exposure, censoring,
                                          intervals), migration 0005,
                                          `methodology render`,
                                          docs/METHODOLOGY.md, property tests
                                          → implement
  ↓
Step 2  (snapshot + compute + golden)    snapshot.py (Parquet + DuckDB views),
                                          compute.py, suppression.py,
                                          publish.py (observations + members),
                                          verify.py, `metrics compute|verify`,
                                          compute-metrics target, step 13,
                                          TRUTH_VERSION 2 + golden regen,
                                          tests/golden/test_golden_metrics.py
                                          → implement
  ↓
Step 3  (provenance + metrics API)       `provenance trace`, /metrics,
                                          /judges/{id}/metrics,
                                          /courts/{id}/metrics,
                                          /metrics/compare,
                                          /metrics/{id}/provenance,
                                          /coverage v1, POST /corrections,
                                          migration 0007, /ready snapshot,
                                          word similarity, openapi + schema
                                          → implement
  ↓
Step 4  (judge panels + compare +        MetricStat, judge page panels +
         methodology + coverage)          cohort selector + drill-down,
                                          /compare, /methodology from the
                                          registry, /coverage v1, cached
                                          banner read, Vitest presentation
                                          tests, Playwright metric flow
                                          → implement
  ↓
Step 5  (corrections + court/            /corrections + report action,
         jurisdiction pages + bootstrap)  court comparable-judge table,
                                          /jurisdictions/[id] v0, bootstrap
                                          target + README, e2e job on the
                                          demo seed, first-milestone.spec.ts
                                          → implement
  ↓
Step 6  (QA + verify_phase03.py)         scripts/verify_phase03.py
                                          + docs/phase03-qa-findings.md
                                          + phase-verify.yml matrix entry 03
                                          + required context + ROADMAP status
                                          + tag v0.3.0-phase-3
                                          → create

--- post-implementation ---

V1  The registry loads, validates against the vocabulary, and syncs
    metric_definition; index events, windows, exposure, censoring, and
    Kaplan–Meier hold their property invariants; docs/METHODOLOGY.md
    equals the render and carries the brief's warnings verbatim.
V2  `metrics compute` exports a hashed snapshot and publishes
    observations with members; every registry metric equals its
    truth expectation exactly on the golden fixture; `metrics verify`
    reproduces every observation byte for byte and exits 1 on a
    tampered row; step 13 recomputes only impacted subjects.
V3  Every observation trace is complete (test) and an incomplete chain
    is not published; the metrics, compare, coverage, and provenance
    endpoints paginate, validate, carry the presentation fields, and
    suppress; a correction round-trips encrypted and is unreadable by
    the app role; no metrics response carries a person key.
V4  Every metric on the judge, compare, methodology, and coverage pages
    shows numerator, denominator, date range, coverage, sample size,
    and a methodology link; suppressed cohorts show the notice; the
    Playwright metric flow passes.
V5  A correction submits through the form; the court and jurisdiction
    pages render their tables; `uv run poe bootstrap` alone brings a
    clean machine to the walkthrough; first-milestone.spec.ts passes
    over the demo seed in CI.
V6  verify_phase03.py --fast and --security exit 0 on Ubuntu CI under
    the phase-verify.yml matrix entry 03; the tag v0.3.0-phase-3 marks
    the merge.
```

Steps are sequential by dependency: Step 1's registry schema, frame
types, and migration `0005` are what Step 2's snapshot export, compute
functions, and observation publisher consume, and Step 1's exposure and
censoring rules are what Step 2's `TRUTH_VERSION` `2` must implement
identically in the generator; Step 2's observations, members, and
snapshots are what Step 3's trace, metrics endpoints, and `/ready` block
read; Step 3's endpoints, regenerated OpenAPI snapshot, and generated
client are what Step 4's components and pages call; Step 4's `MetricStat`
and compare table are reused by Step 5's court and jurisdiction pages,
and Step 5's walkthrough exercises every page Steps 3–5 shipped; Step 6
verifies every deliverable of Steps 1–5. This phase has no steps drawn in
parallel.

---

## Step 1 — Metric Registry, Analytic Frame, and Generated Methodology

> **Goal:** Land the contract every published number is computed
> against: `data/reference/metric_registry.yaml` (registry `version`,
> `methodology_version` `0.1`, the brief's eight statistical warnings
> verbatim as `known_limitations`, and one entry per metric with `slug`,
> `name`, `kind`, `subject_types`, `description`, `numerator`,
> `denominator`, `eligibility`, `attribution` inclusion rules,
> `index_event`, `outcome`, `windows_days`, `suppression_threshold`,
> `unit`, `version`) loaded by `src/judgemetrics/metrics/registry.py`
> and synced into `metric_definition` by `sync_definitions(session)`;
> the analytic frame in `src/judgemetrics/metrics/` — `frame.py` (the
> typed Polars frames the engine reads: cases, assignments, charges,
> decisions with releases, sentences, events, justice events, persons),
> `attribution.py` (the inclusion gate per registry rule), `index_events.py`
> (pretrial release, disposition, sentence), `exposure.py` (time at risk
> from the index time, deferred by incarceration), `windows.py` (the
> six windows, outcomes in `(start, start + w]`, other-case outcomes),
> `censoring.py` (right-censoring at the source's coverage end,
> adequately followed cohorts, the Kaplan–Meier estimator), and
> `intervals.py` (Wilson score and Greenwood intervals); migration
> `0005_metric_registry_and_snapshots` (the registry columns on
> `metric_definition`, the `metric_snapshot` table, the snapshot, source,
> window, dimension, eligible-count, value, distribution, code-version,
> registry-version, and `superseded_at` columns and the unique index on
> `metric_observation`, the `metric_observation_member` table,
> `source.coverage_start`, `coverage_end`, and `observable_outcomes`,
> and the grants); `judgemetrics methodology render [--check]` writing
> the committed `docs/METHODOLOGY.md` from the registry; `docs/ARCHITECTURE.md`
> "Metrics engine" (the frame and the semantics); and Hypothesis
> property tests over in-memory `TINY` worlds proving the frame's
> invariants. This step lands the semantics; Step 2 exports the
> snapshot, computes, publishes, and proves the golden expectations.

**Branch:** `feature/phase03-step1-metric-registry-frame`

**Deploys:** local database (`uv run poe up` + `uv run poe migrate`) —
the merge carries migration `0005`; the operator applies it locally and
`/api/v1/ready` reports the new head. Nothing else changes at runtime
until Step 2 computes.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Fable 5.1                      |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** This is the phase's ceiling-class step: it fixes
the semantics of index events, time at risk, incarceration deferral,
right-censoring, adequately-followed cohorts, and the product-limit
estimator in a form that the computation engine (Step 2), the truth
generator (`TRUTH_VERSION` `2`), the golden test, and the methodology
page must all agree on exactly — PRIMARY `coding`, SECONDARY `planning`,
High complexity with novel problem-solving and cross-file
chain-of-thought (the conditions that push the selector to its Extra
High and Max rungs). Fable 5.1 is rated S in coding and S in planning
(HLE 59.1% and Terminal-Bench 2.1 91.4, both at max) and supersedes
Fable 5; under the operator's balanced posture it is reserved for
exactly this kind of step, matching the parent roadmap's §8 assignment
of Fable to "index events, exposure, and censoring design", while Opus 5
(also S/S) takes the implementation steps because Fable draws the Max
budget down at about twice Opus's rate. The Platform is Claude Code on
the flat claude.ai Max subscription, so the flat-funding gate is open:
Effort `Max`, Thinking `On`. Backup: GPT-5.6 Sol on Codex (ChatGPT Plus;
Intelligence Extra High), S-tier in coding and planning from a different
provider. Conversation is New per phase-boundary hygiene.

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
       feature/phase03-step1-metric-registry-frame`
       from a clean, up-to-date
       `main`. The exact branch
       name is in this step's
       `**Branch:**` line above.
       If the Worktree rule
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
       rejected. Pass the security
       gate before every commit.
       Stop the local API before
       `uv run poe gate` or
       `git commit`.

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
       --delete-branch`. If this
       step's `**Deploys:**` line
       names a surface, the merge
       is not the finish line: run
       the Deployed & verified
       check against the local
       environment before
       declaring the step complete.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree,
       `git worktree remove <path>`
       FIRST — the branch prune
       fails while the branch is
       checked out there.

    6. DISPOSE OF EVERY FINDING,
       DECLARE COMPLETION, THEN
       NEW CONVERSATION. First
       send every finding this
       step surfaced to its
       destination (Triage rule):
       a note for a later step →
       edit that step's <task>
       block now; spec rot → edit
       this roadmap now; a bug →
       fixed in-step or an issue
       number; a judgement call in
       the diff → the PR body; a
       process lesson → written
       where the next conversation
       reads it (AGENTS.md or this
       roadmap); a data-semantics
       finding → the registry
       entry, version bumped; a
       data-access question → a
       row in docs/ROADMAP.md.
       Update docs/ROADMAP.md
       (completed items, known
       issues, next milestones). A
       finding you can only
       describe is NOT disposed
       of, and counts as an unmet
       criterion. Only once the PR
       is merged, every acceptance
       criterion is affirmatively
       met, and every finding has
       a destination, say so
       plainly: end your final
       response with an explicit,
       unhedged completion line —
       verbatim shape "Step 1 is
       complete. You can now move on
       to Step 2."
       That line is the LAST line
       of the response. NOTHING
       follows it — no "Follow-ups
       (non-blocking)", "Notes",
       "Next", "worth a glance",
       or suggested improvements.
       A short ledger may PRECEDE
       it, one entry per finding
       naming its destination
       (issue #, file edited, PR
       body) — never an open item.
       If any criterion is unmet
       or any finding has no
       destination, state plainly
       that the step is NOT
       complete, name what is
       outstanding, and omit the
       completion line. "Done"
       means done. Then, for
       phase-boundary hygiene, the
       operator closes this
       session and opens a fresh
       one before Step 2.
  </lifecycle>

  <security>
    Security is a gate on THIS step,
    not a later phase. It is AS
    BINDING as any `<requirement>`
    below. Before the Stage-2
    commit, this step's work MUST
    pass the local, fail-closed
    security gate — the SAME gate
    wired into the pre-commit hook
    and re-run in CI:

    1. SECRET / PII SCAN. No
       credentials or tokens in the
       diff (`detect-secrets`
       against `.secrets.baseline`).
       The registry file, the
       methodology document, and the
       property tests carry no
       person material of any kind;
       the frame's person column is
       the resolved `person_id`
       UUID, never a name, date of
       birth, hash, or public key.

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern
       (`bandit`). The registry is
       loaded with `yaml.safe_load`
       only; `methodology render`
       writes only to the repository
       path it is given, resolved
       under the repository root;
       migration `0005` builds every
       `GRANT` from module constants
       (never user input), as `0001`
       and `0004` do.

    3. DEPENDENCY AUDIT. This step
       adds no runtime dependency
       (Polars, pyyaml, and
       Hypothesis are already
       present). If one is added, it
       passes `pip-audit --strict`.

    4. SENSITIVE-DATA REVIEW.
       `metric_observation_member`
       stores entity ids of public
       case-level rows (decision,
       charge, case, sentence,
       court_event) and, for justice
       events, the
       `justice_event.id` — never a
       `person_id` column; the app
       role gets `SELECT` on
       `metric_snapshot`,
       `metric_observation_member`,
       and the new
       `metric_observation` columns,
       nothing on any restricted
       table;
       `source.observable_outcomes`
       and the coverage window are
       public facts. Log lines from
       the loader carry the registry
       version and metric slugs
       only.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 3. Step 1:
    metric registry, analytic frame,
    and generated methodology.

    Current state (as of Phase 2):

    - `metric_definition` and
      `metric_observation` exist
      from `0001_baseline`
      (`src/judgemetrics/db/models/metrics.py`)
      and have never held a row; the
      head is
      `0004_entity_resolution_review`.
      The app role has SELECT on
      both, the ingest role DML.
    - The case-level tables and the
      `justice_event` table are
      populated by the synthetic
      connector; persons are read
      through
      `entity_resolution.merge.unmerged()`.
      The vocabulary is
      `data/reference/case_vocabulary.yaml`
      (version 1), loaded by
      `normalization/vocabulary.py`.
    - `truth/metrics.json` in
      `tests/fixtures/golden/truth/`
      states the expected value of
      every Phase 3 metric per judge
      and court with a `definitions`
      block; its windowed rates are
      pretrial-release-indexed only,
      and `truth.py` already models
      `disposition` and `sentence`
      index events and `new_charge`
      and `revocation` outcomes in
      `subsequent_events.csv`.
    - `source` has no coverage
      window; the synthetic corpus
      dates live in
      `synthetic/config.py`
      (`ScaleSpec.corpus_start`,
      `corpus_end`,
      `corpus_end_at`).
    - `tests/property/support.py`
      builds `TINY` worlds in
      memory;
      `tests/property/test_event_ordering.py`
      is the closest precedent for a
      frame invariant.
    - `docs/openapi.json` is
      regenerated by `judgemetrics
      openapi export` and
      drift-tested;
      `docs/METHODOLOGY.md` follows
      the same committed-snapshot
      pattern.
    - `web/app/methodology/page.tsx`
      is static prose; Step 4
      replaces it with a render of
      the registry through the API.
      This step ships the Markdown
      render only.

    Files to read (every file before
    drafting):
    - docs/brief/judgemetrics-master-project-specification.xml
      (`<outcome_definitions>`,
      `<analytics_methodology>`
      descriptive metrics and
      minimum sample size,
      `<metric_presentation>`,
      `<important_statistical_warnings>`
      — the eight warnings copied
      verbatim,
      `<event_attribution_model>`).
    - ROADMAP.md §4 Phase 3 (3.1,
      3.2, 3.3 metric set), Phase 4
      (what the registry must leave
      room for), §5 "Provenance
      chain", "Performance rules",
      "Defect handling & triage"
      (data-semantics finding).
    - docs/SYNTHETIC_DATA.md "The
      metric set (`metrics.json`)"
      and "`truth/`" (the
      definitions the registry must
      match on the golden fixture).
    - src/judgemetrics/synthetic/truth.py
      (`index_events`,
      `outcomes_of`,
      `PersonTimeline.has_outcome`,
      `_subject_metrics`,
      `WINDOWS_DAYS`,
      `OTHER_CASE_OUTCOMES` — the
      semantics Step 2's
      `TRUTH_VERSION` 2 extends and
      this frame must implement
      identically).
    - src/judgemetrics/synthetic/config.py
      (corpus dates), model.py (the
      in-memory world the property
      tests build frames from).
    - src/judgemetrics/db/models/metrics.py,
      cases.py, persons.py,
      provenance.py, enums.py,
      _types.py, base.py.
    - alembic/versions/0004_entity_resolution_review.py
      (migration conventions:
      explicit enums, grants from
      constants, self-contained).
    - src/judgemetrics/normalization/vocabulary.py
      (`require(kind, value)` —
      registry rules are validated
      against it).
    - src/judgemetrics/entity_resolution/merge.py
      (`unmerged()`).
    - src/judgemetrics/cli.py,
      config.py, logging.py,
      openapi.py (the `openapi
      export` pattern for
      `methodology render`).
    - tests/property/support.py,
      tests/property/test_event_ordering.py,
      tests/unit/test_vocabulary.py,
      tests/unit/test_openapi.py
      (the snapshot drift test
      pattern).
    - docs/ARCHITECTURE.md,
      docs/DATA_MODEL.md, AGENTS.md.
  </context>

  <goal>
    Ship the versioned registry and
    the analytic frame such that `uv
    run judgemetrics methodology
    render --check` exits 0 against
    the committed
    `docs/METHODOLOGY.md`,
    `sync_definitions(session)`
    inserts one `metric_definition`
    row per registry metric and
    version and is idempotent,
    migration `0005` upgrades and
    downgrades cleanly with `uv run
    alembic check` reporting no
    drift, and the frame's pure
    functions reproduce, from an
    in-memory `TINY` world, the
    pretrial-release cohorts,
    followed counts, and windowed
    numerators that
    `synthetic/truth.py` computes
    for the same world — with
    property tests proving the
    invariants Step 2 and Phase 4
    rely on.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Create
      `data/reference/metric_registry.yaml`
      with a first-line path
      comment, `version: 1`,
      `methodology_version: "0.1"`,
      `known_limitations:` (the
      eight
      `<important_statistical_warnings>`
      of the brief, each verbatim,
      in the brief's order),
      `suppression:` (the default
      threshold and the rule text),
      and `metrics:`. Each metric
      entry carries: `slug`
      (snake_case, unique), `name`,
      `kind` (one of `count`,
      `share`, `windowed_rate`,
      `survival`, `distribution`,
      `median`), `subject_types`
      (subset of `judge`, `court`),
      `description`, `numerator`,
      `denominator`, `eligibility`
      (prose, the text
      `docs/METHODOLOGY.md`
      publishes), `attribution`
      (structured: `decision_type`,
      `actor_types`, `discretion`,
      `assignment_gate` — one of
      `deciding_judge`,
      `assigned_at_time`,
      `assigned_ever` (cases with
      at least one assignment of
      the judge: the eligibility
      gate, which no time-gated
      rule can express),
      `sentencing_judge`,
      `court_of_case`), `population`
      (which rows the metric reads:
      `cases`, `defendants`,
      `pretrial_decisions`,
      `disposed_charges`,
      `disposed_cases`, `sentences`,
      `index_events`), optional
      `counted` (column conditions
      a row must meet to enter the
      numerator or the count, e.g.
      `detained_flag: false`,
      `disposition: dismissed`,
      `disposition_actor: judge`)
      and, for medians, `measure`
      (`days_to_disposition`,
      `incarceration_days`,
      `probation_days`),
      `index_event`
      (`pretrial_release`,
      `disposition`, `sentence`, or
      null), `outcome` (a
      `justice_event_type` value or
      null), `windows_days` (list or
      null), `dimension`
      (`disposition`,
      `offense_category`, or null),
      `suppression_threshold`
      (integer; the minimum
      denominator below which the
      observation is suppressed; `0`
      for counts), `unit` (`count`,
      `share`, `days`), and
      `version` (`"1"`). Define at
      least: `eligible_cases`,
      `eligible_defendants`,
      `pretrial_decisions`,
      `pretrial_released` (count),
      `pretrial_detained` (count),
      `pretrial_release_share`,
      `statutory_release_count`
      (court only),
      `unknown_actor_pretrial_count`
      (court only),
      `failure_to_appear_rate`,
      `new_case_rate`,
      `new_charge_rate`,
      `reconviction_rate`,
      `release_violation_rate`,
      `revocation_rate`,
      `rearrest_rate` (each
      `windowed_rate` over
      `index_event:
      pretrial_release` with the six
      windows),
      `failure_to_appear_survival`,
      `new_case_survival`,
      `reconviction_survival`
      (`survival`, Kaplan–Meier
      cumulative incidence at each
      window), the same windowed
      rates over `index_event:
      disposition` and `index_event:
      sentence` as separate slugs
      (suffix `_after_disposition`,
      `_after_sentence`) for
      `new_case`, `new_charge`,
      `reconviction`, and
      `revocation`,
      `disposition_distribution`
      (`distribution` by
      `disposition`),
      `judicial_dismissal_rate`,
      `median_days_to_disposition`,
      `sentence_count`,
      `incarceration_days_median`,
      `probation_days_median`, and
      `incarceration_days_median_by_offense_category`
      (`median` with `dimension:
      offense_category`). The
      default
      `suppression_threshold` is 10
      for every `share`,
      `windowed_rate`, `survival`,
      and `median`, and 0 for
      `count` and `distribution`;
      record the rationale in the
      file and in
      `docs/METHODOLOGY.md`.
    </requirement>

    <requirement>
      Create
      `src/judgemetrics/metrics/__init__.py`
      and `registry.py`: frozen
      dataclasses
      `MetricDefinitionSpec` and
      `Registry` (`version`,
      `methodology_version`,
      `known_limitations`,
      `suppression`, `metrics` keyed
      by slug),
      `load_registry(path=DEFAULT_PATH)
      -> Registry` (cached,
      `yaml.safe_load`), validation
      on load that every
      `attribution` value,
      `outcome`, `dimension`, and
      `index_event` is in the
      vocabulary or the fixed
      enumerations, that slugs are
      unique, that `subject_types`
      is non-empty, and that every
      `windowed_rate` and `survival`
      has both `index_event` and
      `outcome` and windows equal to
      the brief's six;
      `RegistryError` on any
      violation.
      `sync_definitions(session) ->
      SyncResult` upserts
      `metric_definition` on `(slug,
      version)`: inserts new
      versions, updates only rows
      whose substantive columns
      changed, never deletes, and
      returns counts. Unit tests:
      the committed file loads; a
      tampered copy with an unlisted
      actor fails naming the slug
      and field; `known_limitations`
      equals the brief's
      `<important_statistical_warnings>`
      text parsed from the XML with
      whitespace normalized (the
      test reads
      `docs/brief/judgemetrics-master-project-specification.xml`);
      the pretrial and dismissal
      entries' prose equals the
      corresponding `definitions`
      text in
      `tests/fixtures/golden/truth/metrics.json`
      after whitespace
      normalization, or the registry
      states the difference in a
      `truth_note` field the test
      checks for.
    </requirement>

    <requirement>
      Create migration
      `alembic/versions/0005_metric_registry_and_snapshots.py`
      (self-contained; never imports
      the models).
      `metric_definition` gains
      `kind` (text, not null),
      `subject_types` (JSONB array),
      `attribution` (JSONB),
      `index_event` (text,
      nullable), `outcome` (text,
      nullable), `windows_days`
      (JSONB, nullable), `dimension`
      (text, nullable),
      `suppression_threshold`
      (integer, not null), `unit`
      (text, not null),
      `registry_version` (integer,
      not null),
      `methodology_version` (text,
      not null). New table
      `metric_snapshot`: `id` UUID
      pk, `content_hash` (char 64,
      unique), `label` (text),
      `exported_at` (timestamptz),
      `code_version` (text),
      `registry_version` (integer),
      `methodology_version` (text),
      `row_counts` (JSONB),
      `coverage` (JSONB: per source
      id, `coverage_start`,
      `coverage_end`), `storage_uri`
      (text),
      `created_at`/`updated_at`.
      `metric_observation` gains
      `snapshot_id` (FK
      `metric_snapshot.id`,
      RESTRICT, not null),
      `source_id` (FK `source.id`,
      RESTRICT, not null),
      `window_days` (integer,
      nullable), `dimension_value`
      (text, nullable),
      `eligible_count` (integer, not
      null — the cohort before the
      follow-up restriction; equals
      `cohort_size` for non-windowed
      metrics), `value` (numeric(14,
      4), nullable — medians in
      days), `distribution` (JSONB,
      nullable), `code_version`
      (text, not null),
      `registry_version` (integer,
      not null), `superseded_at`
      (timestamptz, nullable), and a
      unique index
      `uq_metric_observation_key` on
      `(metric_definition_id,
      subject_type, subject_id,
      source_id, period_start,
      period_end, window_days,
      dimension_value, snapshot_id)`
      `NULLS NOT DISTINCT`, plus a
      partial index on
      `superseded_at IS NULL` over
      `(subject_type, subject_id)`.
      New table
      `metric_observation_member`:
      `id` bigint identity pk,
      `observation_id` (FK
      `metric_observation.id`,
      CASCADE), `member_kind` (text:
      `decision`, `charge`,
      `court_case`, `sentence`,
      `court_event`,
      `justice_event`), `member_id`
      (UUID), `counted` (boolean —
      in the numerator), `followed`
      (boolean — in the denominator
      after censoring), index on
      `(observation_id)` and on
      `(member_kind, member_id)`.
      `source` gains
      `coverage_start` (date,
      nullable), `coverage_end`
      (date, nullable),
      `observable_outcomes` (JSONB
      array, not null, default
      `[]`). Grants from constants:
      app role SELECT on
      `metric_snapshot` and
      `metric_observation_member`;
      ingest role SELECT, INSERT,
      UPDATE, DELETE on both.
      Downgrade removes everything
      it created. Update the models
      to match; `uv run alembic
      check` reports no drift;
      `tests/integration/test_migrations.py`
      round-trips through `0005`.
    </requirement>

    <requirement>
      Create
      `src/judgemetrics/metrics/frame.py`:
      a frozen `Frame` dataclass of
      Polars DataFrames with
      documented schemas — `cases`
      (id, court_id, filed_at,
      closed_at, status, case_type),
      `assignments` (case_id,
      judge_id, start_at, end_at),
      `charges` (id, case_id,
      person_id, filed_at,
      disposed_at, disposition,
      disposition_actor,
      offense_category, severity),
      `decisions` (id, case_id,
      person_id, judge_id,
      decision_type, decision_at,
      actor_type, discretion,
      release_at, detained_flag,
      release_type), `sentences`
      (id, case_id, person_id,
      judge_id, sentence_at,
      incarceration_days,
      probation_days), `events` (id,
      case_id, person_id, judge_id,
      event_type, event_at),
      `justice_events` (id,
      person_id, event_type,
      event_at, related_case_id),
      `persons` (id) — plus
      `coverage_start`,
      `coverage_end` (the source's
      window;
      `coverage_end_exclusive_at` is
      the day after `coverage_end`
      at 00:00 UTC), and
      `observable_outcomes`. Provide
      `frame_from_world(world, spec)
      -> Frame` in
      `tests/property/support.py`
      (test-only) building the frame
      from an in-memory synthetic
      world with the true person ids
      as `persons.id`, and leave the
      database loader to Step 2's
      `snapshot.py`. Every timestamp
      column is timezone-aware UTC;
      every id is a UUID or the
      world's string id (the frame
      is generic over the id dtype —
      document that).
    </requirement>

    <requirement>
      Create `attribution.py`:
      `attributed_decisions(frame,
      rule) -> DataFrame` applying a
      registry `attribution` block
      (decision type, actor types,
      discretion, and the assignment
      gate: `deciding_judge` keeps
      decisions whose `judge_id` is
      the subject;
      `assigned_at_time` keeps rows
      whose event time falls in one
      of the subject's assignment
      intervals on that case,
      `start_at <= t < end_at` with
      a null `end_at` open;
      `assigned_ever` keeps rows of
      cases with at least one
      assignment of the subject;
      `sentencing_judge` keeps
      sentences whose `judge_id` is
      the subject; `court_of_case`
      keeps rows of the court's
      cases, and is what a court
      subject always gets whatever
      gate the rule names) and
      `attributed_charges(frame,
      rule)`;
      `pretrial_decisions_for(frame,
      subject_type, subject_id,
      rule)`. A statutory release
      (`actor_type =
      legislature_or_mandatory_rule`,
      `discretion = mandatory`) and
      an `unknown` actor are never
      attributed to a judge; the
      court-level
      `statutory_release_count` and
      `unknown_actor_pretrial_count`
      count them explicitly. Unit
      tests over hand-built frames
      for each gate.
    </requirement>

    <requirement>
      Create `index_events.py`,
      `exposure.py`, `windows.py`,
      `censoring.py`,
      `intervals.py`. Semantics
      (write them in each module
      docstring and in
      `docs/METHODOLOGY.md`, because
      Step 2's `TRUTH_VERSION` 2
      implements the same rules in
      `synthetic/truth.py`): an
      index event is (person, case,
      kind, index_at) —
      `pretrial_release`: attributed
      pretrial decisions with
      `detained_flag = false` and a
      non-null `release_at`,
      `index_at = release_at`;
      `disposition`: the case's
      disposition time (the latest
      `disposed_at` among its
      disposed charges); `sentence`:
      `sentence_at`. Exposure starts
      at `index_at`; for the
      `disposition` and `sentence`
      kinds, when the case's
      sentence carries a positive
      `incarceration_days`, exposure
      starts at `sentence_at +
      incarceration_days` (time at
      risk is deferred by
      incarceration; other terms of
      the same person are not
      modelled — a documented
      limitation). An outcome counts
      for a window `w` when an event
      of the outcome type occurs in
      `(exposure_start,
      exposure_start + w days]`;
      `new_case`, `new_charge`, and
      `reconviction` count only in
      another case of the same
      person; `failure_to_appear`,
      `release_violation`,
      `revocation`, and `rearrest`
      count in any case. Outcomes
      are read from `justice_events`
      (which the ingest pipeline
      derives per person) with
      `related_case_id` deciding
      "another case".
      Right-censoring: a cohort
      member is *followed* for
      window `w` when
      `exposure_start + w days <
      coverage_end_exclusive_at`;
      the fixed-window rate's
      denominator is the followed
      members and its numerator the
      followed members with an
      outcome; `eligible_count` is
      the whole cohort.
      Kaplan–Meier: over the whole
      cohort, with time to first
      outcome and censoring at
      `coverage_end_exclusive_at -
      exposure_start`, the
      product-limit survival `S(t)`
      evaluated at `t = w` days and
      published as cumulative
      incidence `1 - S(w)` with the
      Greenwood standard error and a
      symmetric 95% interval clipped
      to `[0, 1]`; ties are handled
      by counting events before
      censorings at the same time.
      `intervals.wilson(numerator,
      denominator, z=1.959964) ->
      (lower, upper)`; a zero
      denominator yields nulls.
      Everything is a pure function
      over `Frame` plus registry
      values, decimal-safe via
      `round(x, 6)` at the boundary
      only. A metric whose `outcome`
      is not in
      `frame.observable_outcomes` is
      *not observable* for that
      source and yields no rows (a
      `NotObservable` marker the
      engine records), never a zero.
    </requirement>

    <requirement>
      Add
      `tests/property/test_frame_invariants.py`
      (Hypothesis, `TINY` scale, the
      existing profiles, no
      database): no outcome is
      counted before its exposure
      start; a followed member is a
      cohort member and `numerator
      <= followed <= eligible`; the
      fixed-window numerator is
      monotone non-decreasing in `w`
      for a fixed cohort; `1 - S(w)`
      is in `[0, 1]`, monotone
      non-decreasing in `w`, and
      equals the fixed-window rate
      when no member is censored
      before `w`; exposure start is
      never before `index_at` and
      equals `sentence_at +
      incarceration_days` when a
      sentence incarcerates; a
      statutory release never
      appears in a judge's
      attributed decisions; and,
      against `synthetic/truth.py`
      on the same in-memory world,
      the pretrial-release `cohort`,
      `followed`, and
      `failure_to_appear` /
      `new_case` / `reconviction`
      numerators per judge and
      window are equal (the truth is
      the oracle). Keep each example
      under one second; derandomize
      with fixed seeds where the
      world build dominates.
    </requirement>

    <requirement>
      Add `judgemetrics methodology
      render [--out
      docs/METHODOLOGY.md]
      [--check]` in `cli.py` (a
      `methodology` group) backed by
      `metrics/methodology.py`:
      renders Markdown from the
      registry — a header with the
      registry and methodology
      versions, "How to read a
      number" (numerator,
      denominator, date range,
      coverage, sample size,
      interval, suppression), "Index
      events, exposure, and
      censoring" (the semantics
      above), "Metrics" (one section
      per metric: name, slug,
      version, subject types,
      formula as numerator over
      denominator, eligibility,
      attribution rules, windows,
      threshold, unit),
      "Suppression", "Known
      limitations" (the eight
      warnings verbatim, unsoftened,
      as a list), and "Methodology
      changelog" (`0.1` — first
      registry). `--check` exits 1
      with a diff summary when the
      file differs. Commit the
      rendered `docs/METHODOLOGY.md`
      (80-column prose). Unit test:
      the committed file equals the
      render (the
      `docs/openapi.json` pattern);
      the "Known limitations"
      section contains each warning
      verbatim.
    </requirement>

    <requirement>
      Documentation:
      `docs/ARCHITECTURE.md` gains
      "Metrics engine" (the registry
      as the contract, the frame,
      attribution gates, index
      events, exposure, censoring,
      Kaplan–Meier, intervals; what
      Step 2 adds);
      `docs/DATA_MODEL.md` gains the
      `0005` columns and tables, the
      observation unique key, and
      the member table under
      "Tables", "Natural keys and
      unique constraints", "Grants",
      and a "Metric registry"
      subsection under
      "Vocabularies";
      `docs/SYNTHETIC_DATA.md` "The
      metric set" notes which
      registry slug each truth entry
      maps to; `AGENTS.md` records
      the decisions (registry
      versioning, `NotObservable`,
      the member table,
      snapshot-keyed observations,
      the incarceration-deferral
      rule and its limitation).
      Update the `Commands` list in
      `AGENTS.md` and `README.md`
      with `methodology render`.
    </requirement>

    <requirement>
      Filepath comment: every new
      Python, YAML, Markdown, and
      test file gets the
      repo-relative path as its
      first line (`#
      src/judgemetrics/metrics/registry.py`,
      `#
      data/reference/metric_registry.yaml`,
      `<!-- docs/METHODOLOGY.md
      -->`).
    </requirement>
  </requirements>
</task>
```

### Step 1 acceptance criteria

- `data/reference/metric_registry.yaml` loads through `load_registry()`;
  a tampered copy with an unlisted actor, outcome, or window fails with
  `RegistryError` naming the slug and field (unit test).
- `known_limitations` equals the brief's eight
  `<important_statistical_warnings>` verbatim (unit test parses the
  XML).
- `sync_definitions(session)` inserts one `metric_definition` row per
  registry metric and is idempotent on rerun (integration test: second
  run inserts and updates zero rows).
- Migration `0005` upgrades and downgrades cleanly;
  `tests/integration/test_migrations.py` round-trips through it; `uv run
  alembic check` reports no drift; the app role has `SELECT` on
  `metric_snapshot` and `metric_observation_member` and nothing on any
  restricted table (grant test).
- `tests/property/test_frame_invariants.py` passes under the `ci`
  profile, including equality with `synthetic/truth.py` for the
  pretrial-release cohorts, followed counts, and windowed numerators on
  the same in-memory world.
- `tests/unit/test_attribution.py` covers each assignment gate, the
  statutory-release exclusion, and the unknown-actor exclusion.
- `uv run judgemetrics methodology render --check` exits 0 against the
  committed `docs/METHODOLOGY.md`; the unit test asserts equality and the
  verbatim warnings; the document wraps at 80 columns.
- `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `docs/SYNTHETIC_DATA.md`,
  `AGENTS.md`, and `README.md` updated as specified.
- `uv run poe check` passes (ruff, format, mypy `--strict`, pytest
  including the property suite).
- **Deployed & verified:** after the squash-merge, `uv run poe migrate`
  applies `0005` locally and `GET /api/v1/ready` reports the head
  `0005_metric_registry_and_snapshots`; `uv run judgemetrics methodology
  render --check` exits 0 in the merged tree.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean, SAST
  clean, dependency audit clean — and the metrics schema handles
  sensitive data per the project ROADMAP "Security & privacy strategy"
  (no `person_id` column on `metric_observation_member`; the app role
  has no privilege on `person_identifier`, `audit_log`,
  `entity_resolution_candidate`, or `correction_request` after `0005`
  — grant test).

---

## Step 2 — Snapshot, Computation Engine, and Golden Metric Tests

> **Goal:** Make the registry compute and prove it:
> `src/judgemetrics/metrics/snapshot.py` exports the canonical tables a
> metric reads to Parquet files under `JUDGEMETRICS_SNAPSHOT_DIR/<hash>/`
> with a manifest whose sha256 over every file is the snapshot's
> `content_hash`, opens them as DuckDB
> views, and loads the `Frame`; `compute.py` runs every registry metric
> for every subject and source (`count`, `share`, `windowed_rate`,
> `survival`, `distribution`, `median`) and returns observations with
> their members; `suppression.py` applies each metric's threshold;
> `publish.py` writes `metric_snapshot`, `metric_observation`, and
> `metric_observation_member` rows in one transaction, superseding the
> subjects' previous current observations; `verify.py` recomputes every
> current observation from its own snapshot and compares every stored
> column exactly; `judgemetrics metrics compute [--subjects …] [--label …]`
> and `metrics verify [--snapshot …]`; the `compute-metrics` poe task and
> Makefile target; pipeline step 13 (`recompute_metrics`) recomputing the
> subjects an ingest run touched; `SupportsCoverage` and the manifest's
> corpus dates filling `source.coverage_start`/`coverage_end`, and
> `SourceInfo.observable_outcomes` filling `source.observable_outcomes`;
> `synthetic/truth.py` extended under `TRUTH_VERSION` `2` (disposition-
> and sentence-indexed windows with incarceration deferral, `new_charge`
> and `revocation` outcomes, Kaplan–Meier estimates, `release_violation`
> and `rearrest` marked not observable) with `GENERATOR_VERSION` `2`
> (corpus dates in the manifest) and the golden fixture regenerated; and
> `tests/golden/test_golden_metrics.py` asserting that every registry
> metric equals its truth expectation exactly for every judge and court
> of the golden fixture, that `verify` reproduces every observation, and
> that a tampered observation fails verification. Step 3 exposes what
> this step stores.

**Branch:** `feature/phase03-step2-metrics-engine`

**Deploys:** local database — after the merge the operator runs
`uv run poe compute-metrics` against the seeded database and `uv run
judgemetrics metrics verify` exits 0; nothing is served until Step 3.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** This step is correctness-sensitive multi-file
implementation against a fixed contract — Step 1's registry and frame
semantics, the truth generator's expectations, and an exact byte-for-byte
reproduction requirement — with a Parquet export, a new dependency, a
transaction-bound publisher, a pipeline hook, and a golden fixture
regeneration: PRIMARY `coding`, SECONDARY `agentic` (long compute-test
loops against Postgres), High complexity from scope rather than novelty.
Claude Opus 5 is rated S in coding and S in agentic (Terminal-Bench 2.1
89.1 at max) and supersedes Opus 4.8; the design was fixed by Step 1, so
the balanced posture keeps Fable for the ceiling-class step and gives
this one to Opus at half the Max-budget draw. The Platform is Claude Code
on the flat claude.ai Max subscription, so the flat-funding gate is open:
Effort `Max`, Thinking `On`. Backup: GPT-5.3 Codex on Codex (ChatGPT
Plus; Intelligence High), S-tier in coding from a different provider.
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
       feature/phase03-step2-metrics-engine`
       from a clean, up-to-date
       `main`. The exact branch
       name is in this step's
       `**Branch:**` line above.
       If the Worktree rule
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
       rejected. Pass the security
       gate before every commit.
       Stop the local API before
       `uv run poe gate` or
       `git commit`.

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
       --delete-branch`. If this
       step's `**Deploys:**` line
       names a surface, the merge
       is not the finish line: run
       the Deployed & verified
       check against the local
       environment before
       declaring the step complete.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree,
       `git worktree remove <path>`
       FIRST — the branch prune
       fails while the branch is
       checked out there.

    6. DISPOSE OF EVERY FINDING,
       DECLARE COMPLETION, THEN
       NEW CONVERSATION. First
       send every finding this
       step surfaced to its
       destination (Triage rule):
       a note for a later step →
       edit that step's <task>
       block now; spec rot → edit
       this roadmap now; a bug →
       fixed in-step or an issue
       number; a judgement call in
       the diff → the PR body; a
       process lesson → written
       where the next conversation
       reads it (AGENTS.md or this
       roadmap); a data-semantics
       finding → the registry
       entry, version bumped; a
       data-access question → a
       row in docs/ROADMAP.md.
       Update docs/ROADMAP.md
       (completed items, known
       issues, next milestones). A
       finding you can only
       describe is NOT disposed
       of, and counts as an unmet
       criterion. Only once the PR
       is merged, every acceptance
       criterion is affirmatively
       met, and every finding has
       a destination, say so
       plainly: end your final
       response with an explicit,
       unhedged completion line —
       verbatim shape "Step 2 is
       complete. You can now move on
       to Step 3."
       That line is the LAST line
       of the response. NOTHING
       follows it — no "Follow-ups
       (non-blocking)", "Notes",
       "Next", "worth a glance",
       or suggested improvements.
       A short ledger may PRECEDE
       it, one entry per finding
       naming its destination
       (issue #, file edited, PR
       body) — never an open item.
       If any criterion is unmet
       or any finding has no
       destination, state plainly
       that the step is NOT
       complete, name what is
       outstanding, and omit the
       completion line. "Done"
       means done. Then, for
       phase-boundary hygiene, the
       operator closes this
       session and opens a fresh
       one before Step 3.
  </lifecycle>

  <security>
    Security is a gate on THIS step,
    not a later phase. It is AS
    BINDING as any `<requirement>`
    below. Before the Stage-2
    commit, this step's work MUST
    pass the local, fail-closed
    security gate — the SAME gate
    wired into the pre-commit hook
    and re-run in CI:

    1. SECRET / PII SCAN. No
       credentials or tokens in the
       diff (`detect-secrets`).
       Regenerating the golden
       fixture changes
       `tests/fixtures/golden/manifest.json`;
       refresh `.secrets.baseline`
       by scanning only the manifest
       and normalize its `filename`
       entries to forward slashes
       (`docs/SYNTHETIC_DATA.md`
       "Regenerating the golden
       fixture"). No real person's
       name, date of birth, or
       identifier anywhere in the
       truth extension.

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern
       (`bandit`). DuckDB is queried
       with parameterized statements
       and `read_parquet` over paths
       the snapshot module built
       itself under
       `JUDGEMETRICS_SNAPSHOT_DIR`
       (resolved; a snapshot id is
       validated as a 64-character
       hex string before it becomes
       a path); no DuckDB extension
       is installed or loaded; the
       snapshot directory is created
       with `mkdir(parents=True,
       exist_ok=False)` and never
       overwritten (a snapshot whose
       hash already exists is
       reused, not rewritten).
       `hashlib.sha256` for the
       content hash.

    3. DEPENDENCY AUDIT. This step
       adds `duckdb` as a runtime
       dependency; it passes
       `pip-audit --strict
       --require-hashes` over the
       `uv.lock` export and needs no
       network at import or query
       time. Polars writes Parquet
       natively (no pyarrow).

    4. SENSITIVE-DATA REVIEW. The
       snapshot exports no
       restricted table
       (`person_identifier`,
       `audit_log`,
       `entity_resolution_candidate`,
       `correction_request` are
       never read) and the `persons`
       frame is the id column only;
       Parquet files live under a
       git-ignored directory.
       Observation and member rows
       carry no person id; log lines
       carry the snapshot id,
       counts, and slugs only. The
       `compute` and `verify`
       commands run as the ingest
       role
       (`JUDGEMETRICS_INGEST_DATABASE_URL`),
       never the admin role.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 3. Step 2:
    snapshot export, computation
    engine, `metrics
    compute|verify`, and the golden
    metric tests.

    Current state (as of Phase 2,
    post-Phase-3 Step 1):

    - `data/reference/metric_registry.yaml`,
      `metrics/registry.py`
      (`load_registry`,
      `sync_definitions`), the
      `Frame` and the pure functions
      in `attribution.py`,
      `index_events.py`,
      `exposure.py`, `windows.py`,
      `censoring.py`,
      `intervals.py`, and migration
      `0005` (registry columns,
      `metric_snapshot`, the
      observation key and columns,
      `metric_observation_member`,
      `source.coverage_start`/`coverage_end`/`observable_outcomes`)
      are merged;
      `docs/METHODOLOGY.md` states
      the semantics. No observation
      exists; `source.coverage_*`
      and `observable_outcomes` are
      null and `[]`.
    - The runner's step 13
      `recompute_metrics(session,
      run)` is a no-op called inside
      the publish transaction after
      step 12 and the resolution
      rule stages; the run's
      published case ids are
      available from the publish
      result.
    - `synthetic/truth.py`
      (`TRUTH_VERSION` `1`) windows
      pretrial-release index events
      only for `failure_to_appear`,
      `new_case`, `reconviction`;
      `index_events()` already
      yields `disposition` and
      `sentence`, and
      `outcomes_of()` already yields
      `new_charge` and `revocation`.
      `synthetic/config.py`
      `GENERATOR_VERSION` `1`; the
      manifest carries seed, scale,
      versions, counts, files.
    - `tests/golden/` holds
      `test_golden_fixture.py`
      (regeneration byte-identical;
      fails on a version bump
      without regeneration),
      `test_golden_counts.py`,
      `test_golden_resolution.py`,
      `test_public_contract.py`; its
      conftest re-exports
      `golden_fixture`
      (module-scoped, purges the
      `synthetic` source before and
      after, uses the scratch
      database).
    - `tests/integration/test_synthetic_ingest.py`
      ingests the golden fixture
      twice and asserts counts; it
      is where the step-13 test
      belongs.
    - `pyproject.toml`
      `[tool.poe.tasks]` and the
      `Makefile` mirror each other;
      `seed = "judgemetrics seed"`
      is the pattern for
      `compute-metrics`.
    - `config.py` `Settings` carries
      per-role URLs and
      `synthetic_dir`; add
      `snapshot_dir` and
      `metrics_recompute_on_ingest`.

    Files to read (every file before
    drafting):
    - docs/METHODOLOGY.md and
      data/reference/metric_registry.yaml
      (the contract).
    - src/judgemetrics/metrics/*.py
      (Step 1).
    - src/judgemetrics/synthetic/truth.py,
      config.py, generate.py,
      writer.py (the truth extension
      and the manifest).
    - src/judgemetrics/ingest/runner.py
      (`recompute_metrics`, the
      publish result, the
      transaction boundary), base.py
      (`SourceInfo`,
      `SupportsContext`),
      synthetic/connector.py
      (`load_context` reads the
      manifest),
      synthetic/sources.py,
      fjc/sources.py, publish.py
      (batched upserts with `IS
      DISTINCT FROM` guards — the
      pattern for `publish.py`).
    - src/judgemetrics/db/models/metrics.py,
      provenance.py, session.py,
      config.py, cli.py, logging.py.
    - tests/golden/conftest.py,
      test_golden_fixture.py,
      test_golden_counts.py;
      tests/integration/conftest.py,
      test_synthetic_ingest.py;
      tests/property/support.py.
    - docs/SYNTHETIC_DATA.md
      ("Regenerating the golden
      fixture", "The metric set"),
      docs/ARCHITECTURE.md ("Metrics
      engine"), docs/DATA_MODEL.md,
      AGENTS.md, ROADMAP.md §4 3.3
      and 3.6, §5 "Performance
      rules".
  </context>

  <goal>
    Ship the engine such that `uv
    run judgemetrics metrics
    compute` against a seeded
    database exports one snapshot,
    publishes every registry metric
    for every judge and court of
    every source with case data, and
    records the members behind each
    observation; `uv run
    judgemetrics metrics verify`
    recomputes every current
    observation from its snapshot
    and exits 0 only when every
    stored column matches; on the
    regenerated golden fixture every
    observation equals its
    `truth/metrics.json` expectation
    exactly (numerator, denominator,
    value at six decimals, medians,
    distributions, Kaplan–Meier
    estimates); and an ingest run
    recomputes only the subjects it
    touched.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Extend `synthetic/truth.py`
      under `TRUTH_VERSION = "2"`:
      windows for every index kind
      (`pretrial_release`,
      `disposition`, `sentence`)
      with exposure deferred by the
      case's `incarceration_days`
      for the `disposition` and
      `sentence` kinds exactly as
      `docs/METHODOLOGY.md` states;
      outcomes `failure_to_appear`,
      `new_case`, `new_charge`,
      `reconviction`, `revocation`
      (`release_violation` and
      `rearrest` are listed under
      `not_observable` with the
      reason "the synthetic source
      records no such event"); per
      window `cohort`, `followed`,
      each fixed-window rate as
      `numerator`/`denominator`/`value`,
      and each `*_survival` as
      `value` (`1 - S(w)`, six
      decimals) with `events` and
      `at_risk` counts;
      `metrics.json` gains
      `index_events:
      {pretrial_release: {...},
      disposition: {...}, sentence:
      {...}}` per subject while the
      existing `pretrial.windows`
      block is kept for continuity
      and equals
      `index_events.pretrial_release.windows`.
      Add the corpus dates to
      `manifest.json` (`corpus:
      {start, end}`) and bump
      `GENERATOR_VERSION = "2"` (a
      manifest schema change).
      Regenerate
      `tests/fixtures/golden/` with
      `uv run judgemetrics synthetic
      generate --seed 7 --scale
      golden --out
      tests/fixtures/golden
      --force`, confirm `source/` is
      byte-identical to before (the
      truth extension draws
      nothing), refresh
      `.secrets.baseline` over the
      manifest, and update the
      golden README,
      `docs/SYNTHETIC_DATA.md` ("The
      metric set", "`truth/`", known
      limitations), and
      `tests/unit/test_synthetic_generator.py`.
    </requirement>

    <requirement>
      Coverage and observability in
      `source`: add
      `observable_outcomes:
      tuple[str, ...]` to
      `SourceInfo` (synthetic:
      `new_case`, `new_charge`,
      `reconviction`,
      `failure_to_appear`,
      `revocation`; FJC: empty) and
      an optional `SupportsCoverage`
      protocol in `ingest/base.py`
      (`coverage_window(self) ->
      tuple[date, date] | None`,
      read by the runner after
      `load_context`); the synthetic
      connector implements it from
      the manifest's `corpus`; the
      runner writes
      `source.coverage_start`,
      `coverage_end`, and
      `observable_outcomes` when
      they differ (the `IS DISTINCT
      FROM` pattern). Unit tests
      over the connector; the ingest
      integration test asserts the
      golden source's window is
      2019-01-01 to 2021-12-31.
    </requirement>

    <requirement>
      Add `duckdb` to
      `[project.dependencies]` (`uv
      add duckdb`, lock updated) and
      create `metrics/snapshot.py`:
      `export_snapshot(session,
      settings, label=None) ->
      SnapshotRef` reads
      `court_case`,
      `judge_assignment`, `charge`,
      `decision` joined to
      `pretrial_release`,
      `sentence`, `court_event`,
      `justice_event`, `person` (id
      and `merged_into_person_id`
      only, unmerged), `judge` (id,
      court linkage through
      assignments), `court` (id,
      jurisdiction_id), and `source`
      (id, source_type, coverage,
      observable_outcomes) through
      SQLAlchemy into Polars and
      writes one Parquet file per
      table plus `manifest.json`
      (table → sha256, row count)
      under
      `<snapshot_dir>/<content_hash>/`,
      where `content_hash` is the
      sha256 over the sorted
      `table:sha256` lines; an
      existing directory with the
      same hash is reused.
      `open_snapshot(settings,
      content_hash) -> Snapshot`
      registers each Parquet file as
      a DuckDB view (`read_parquet`,
      read-only, in-memory database)
      and `Snapshot.frame(source_id)
      -> Frame` builds the Step 1
      `Frame` for one source's rows
      (cases of the source's
      records, and every justice
      event of the persons in those
      cases). The frame's
      `justice_events` must carry
      the other-case outcomes of the
      *merged* person: the synthetic
      connector derives `new_case`
      and `reconviction` per
      participant id at
      normalization time, before the
      rule stage merges the planted
      split persons, and derives no
      `new_charge` event at all, so
      on the golden fixture two
      truth `new_case` outcomes
      (`P-000029`'s
      `SYN-2020-000013`, `P-000004`'s
      `SYN-2021-000021`) have no
      `justice_event` row (Step 1
      finding). Derive `new_case`,
      `new_charge`, and
      `reconviction` for the frame
      from the merged person's cases
      and charges at snapshot time
      (the truth's `outcomes_of`
      semantics: every case's
      filing, every charge's filing,
      every convicted charge's
      disposition, each keyed by its
      own case), keeping the stored
      `justice_event` rows for
      `failure_to_appear` and
      `revocation`; the property
      test's `frame_from_world`
      builds the same set from the
      world. `code_version` is the
      package version plus the short
      git SHA when available (as
      `ingest_run.code_version`
      does).
    </requirement>

    <requirement>
      Create `metrics/compute.py`:
      `compute_all(snapshot,
      registry, subjects=None) ->
      ComputeResult` (`drafts`,
      `not_observable`,
      `sources_skipped`, `subjects`;
      shipped so that the
      not-observable records and the
      sources without a coverage
      window are counted rather than
      lost — spec rot fixed in-step)
      iterating sources with case
      data, subjects (every judge
      with an attributed row in the
      source; every court with
      cases), and registry metrics
      whose `subject_types` include
      the subject type, dispatching
      on `kind` to `compute_count`,
      `compute_share`,
      `compute_windowed_rate`,
      `compute_survival`,
      `compute_distribution`,
      `compute_median`, each a pure
      function over the `Frame` and
      the Step 1 helpers returning
      an `ObservationDraft`
      (definition slug and version,
      subject, source,
      `period_start`/`period_end` =
      the source's coverage window,
      `window_days`,
      `dimension_value`,
      `eligible_count`,
      `cohort_size`,
      `observed_count`,
      `observed_rate`, `value`,
      `distribution`,
      `lower`/`upper` bounds,
      members as `(kind, id,
      counted, followed)`) or
      `NotObservable`.
      `eligible_cases` counts
      distinct cases (duplicate
      source records are already one
      row); `eligible_defendants`
      counts distinct resolved
      persons among them; medians
      are over non-null values with
      `n` in `cohort_size`;
      `disposition_distribution`
      yields one observation per
      disposition value with
      `dimension_value`;
      `incarceration_days_median_by_offense_category`
      groups by the offense category
      of the case's lead convicted
      charge (most severe by
      severity rank, ties by charge
      id) exactly as the truth does.
      Every rate is rounded to six
      decimals at the boundary;
      every count is an integer.
      `suppression.py`:
      `apply(draft, definition) ->
      draft` sets `suppressed_flag`
      when the denominator
      (`cohort_size`) is below
      `suppression_threshold`; the
      stored row keeps its numbers
      (the API strips them in Step
      3), and the flag is what every
      public surface honours.
    </requirement>

    <requirement>
      Create `metrics/publish.py`:
      `publish(session,
      snapshot_ref, drafts,
      registry, settings) ->
      PublishResult` in one
      transaction: upsert
      `metric_snapshot` on
      `content_hash`;
      `sync_definitions`; for every
      subject in `drafts` set
      `superseded_at = now()` on its
      current observations of the
      same source (rows with
      `superseded_at IS NULL`),
      insert the new observations
      (batched, 500 per statement)
      and their members (batched),
      and refuse to publish —
      raising `ProvenanceError` and
      rolling back — any observation
      whose member ids are not all
      present in the snapshot's
      tables (the chain-completeness
      rule; Step 3's trace test
      relies on it). Return counts
      (observations published,
      suppressed, not observable,
      superseded, members written).
      A subject whose drafts are
      unchanged from its current
      observations (every stored
      column equal) is left in place
      — no supersede, no insert — so
      a recompute without data
      changes writes nothing.
    </requirement>

    <requirement>
      Create `metrics/verify.py`:
      `verify(session, settings,
      snapshot=None) ->
      VerifyResult` loads every
      current observation (or those
      of one snapshot), opens each
      observation's snapshot,
      recomputes with the same
      registry version the
      observation records (the
      current registry file must
      carry that version; otherwise
      the observation is reported
      `unverifiable`), and compares
      every stored column and the
      member set exactly; returns
      per-observation mismatches
      naming the column, stored and
      recomputed values. Exit 1 on
      any mismatch or unverifiable
      observation; log the snapshot
      id and counts only.
    </requirement>

    <requirement>
      CLI and tasks: `judgemetrics
      metrics compute [--label TEXT]
      [--subject judge:<uuid> ...]
      [--json]` (export a snapshot,
      compute, publish; prints the
      snapshot hash and counts) and
      `judgemetrics metrics verify
      [--snapshot HASH] [--json]`;
      `compute-metrics =
      "judgemetrics metrics
      compute"` in `pyproject.toml`
      and the `Makefile`;
      `Settings.snapshot_dir`
      (`JUDGEMETRICS_SNAPSHOT_DIR`,
      default `data/snapshots`,
      git-ignored — add to
      `.gitignore` and
      `data/README.md`) and
      `Settings.metrics_recompute_on_ingest`
      (default `True`; the root
      conftest sets it `False` for
      the suite and the step-13 test
      enables it). Both commands use
      the ingest role URL.
      `.env.example` documents
      `JUDGEMETRICS_SNAPSHOT_DIR`.
    </requirement>

    <requirement>
      Pipeline step 13:
      `recompute_metrics(session,
      run, published)` computes the
      impacted subjects — judges of
      the run's published
      `judge_assignment`,
      `decision`, and `sentence`
      rows and courts of its
      published `court_case` rows —
      and, when the setting is on
      and the set is non-empty,
      exports a snapshot inside the
      same session and publishes
      observations for those
      subjects only (the previous
      current observations of those
      subjects are superseded; every
      other subject's observations
      are untouched). An FJC run
      touches no case rows and
      computes nothing. Record the
      snapshot hash in
      `ingest_run.checkpoint` under
      `metrics_snapshot` or a new
      `ingest_run.metrics_snapshot_id`
      column — choose the column,
      add it in a small migration
      only if `checkpoint` cannot
      carry it without conflicting
      with the connector's
      checkpoint, and record the
      choice in `AGENTS.md`.
      Integration test in
      `test_synthetic_ingest.py`:
      with the setting on, the
      golden ingest publishes
      observations for every golden
      judge and court; a second
      identical ingest supersedes
      nothing and writes no
      observation; a run that moves
      one assignment from one judge
      to another supersedes exactly
      those two judges' observations
      (spec rot fixed in-step: a
      court's metrics take the
      court's cases whatever the
      gate, so an assignment change
      cannot move a court's numbers;
      the court is in the impacted
      set and recomputed, and the
      unchanged rule leaves its rows
      in place, which the test
      asserts).
    </requirement>

    <requirement>
      Add
      `tests/golden/test_golden_metrics.py`
      (module-scoped
      `golden_fixture`, then
      `metrics compute` through the
      Python API): for every judge
      and court in
      `truth/metrics.json` and every
      registry metric, the current
      observation's
      `observed_count`,
      `cohort_size`,
      `eligible_count`,
      `observed_rate` (six
      decimals), `value`,
      `distribution`, and survival
      value equal the truth entry —
      a table in the test maps each
      truth path to its registry
      slug, index event, window, and
      dimension; every metric listed
      under the truth's
      `not_observable` has no
      observation and is reported
      not observable; `verify()`
      returns zero mismatches;
      tampering one observation's
      `observed_count` in the
      session makes `verify()`
      report exactly that
      observation and column; and
      every observation's member ids
      exist in the canonical tables.
      Extend `test_golden_counts.py`
      for the new truth blocks.
      Parametrize so a failure names
      the subject, slug, window, and
      column.
    </requirement>

    <requirement>
      Documentation:
      `docs/ARCHITECTURE.md`
      "Metrics engine" gains the
      snapshot layout, the compute
      dispatch, the publish
      transaction and supersession,
      verification, and step 13;
      `docs/SYNTHETIC_DATA.md`
      records `TRUTH_VERSION` 2 and
      `GENERATOR_VERSION` 2;
      `docs/DATA_MODEL.md` records
      `source.coverage_*` semantics
      and `not observable`;
      `AGENTS.md` records the
      decisions (DuckDB read-only
      over Parquet, Polars for
      arithmetic, snapshot reuse by
      hash, supersession instead of
      deletion, the recompute
      setting, the
      chain-completeness refusal);
      `README.md` and the
      `AGENTS.md` command list gain
      `compute-metrics` and `metrics
      compute|verify`.
    </requirement>

    <requirement>
      Filepath comment: every new
      file gets the repo-relative
      path as the first line.
    </requirement>
  </requirements>
</task>
```

### Step 2 acceptance criteria

- `tests/fixtures/golden/` regenerated at `GENERATOR_VERSION` `2` and
  `TRUTH_VERSION` `2`: `source/*.csv` byte-identical to the Phase 2
  fixture (asserted in the PR body with the file hashes), `manifest.json`
  carries `corpus`, `truth/metrics.json` carries `index_events` for the
  three index kinds and the `not_observable` list;
  `test_golden_fixture.py` passes.
- `uv run judgemetrics metrics compute` against the seeded demo database
  exports one snapshot under `data/snapshots/<hash>/`, publishes
  observations for every synthetic judge and court, and prints the hash
  and counts; a second run publishes nothing (idempotency).
- `tests/golden/test_golden_metrics.py` passes: every registry metric
  equals its truth expectation exactly for every golden judge and court,
  not-observable metrics have no observation, `verify()` reports zero
  mismatches, a tampered observation is reported by id and column, and
  every member id exists.
- `uv run judgemetrics metrics verify` exits 0 on the seeded database
  and exits 1 after `UPDATE metric_observation SET observed_count =
  observed_count + 1 WHERE id = <any>` (recorded in the PR body and
  reverted).
- Step 13 integration tests pass: impacted subjects only; an FJC run
  computes nothing; an unchanged rerun supersedes nothing.
- `source.coverage_start`/`coverage_end`/`observable_outcomes` are
  written for the synthetic source (integration test) and stay null /
  `[]` for FJC.
- `duckdb` is locked and passes the dependency audit; no extension is
  loaded (grep test over `metrics/snapshot.py` for `INSTALL` / `LOAD`).
- `docs/ARCHITECTURE.md`, `docs/SYNTHETIC_DATA.md`, `docs/DATA_MODEL.md`,
  `AGENTS.md`, `README.md`, `.env.example`, `.gitignore`, and
  `data/README.md` updated as specified.
- `uv run poe check` passes.
- **Deployed & verified:** after the squash-merge, `uv run poe seed`
  (restores the demo dataset if a test run purged it), `uv run poe
  compute-metrics`, and `uv run judgemetrics metrics verify` exit 0
  locally; `SELECT count(*) FROM metric_observation WHERE superseded_at
  IS NULL` is greater than zero.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean after
  the scoped baseline refresh, SAST clean, dependency audit clean with
  `duckdb` — and the snapshot handles sensitive data per the project
  ROADMAP "Security & privacy strategy" (no restricted table is
  exported — test that the snapshot manifest lists no `person_identifier`,
  `audit_log`, `entity_resolution_candidate`, or `correction_request`
  file; no person key or hash in any observation, member, or log line).

---

## Step 3 — Provenance Trace, Metrics API, and Corrections Intake

> **Goal:** Expose what Step 2 stores and prove the chain: `judgemetrics
> provenance trace <observation_id> [--json]` and `GET
> /api/v1/metrics/{observation_id}/provenance` reconstruct observation →
> definition and versions → snapshot (hash, code version) → members by
> kind → cases → source records (external id, sha256, retrieved at,
> parser version) → raw artifacts (uri) → source system, with a golden
> test asserting every published observation traces completely; `GET
> /api/v1/metrics` (the registry: definitions, versions, thresholds,
> known limitations, methodology version), `GET /api/v1/judges/{id}/metrics`
> and `/courts/{id}/metrics` (every current observation of the subject
> with the presentation fields, suppressed rows stripped of their
> numbers), `GET /api/v1/metrics/compare` (one metric, one window, one
> court or jurisdiction, sortable, paginated, with sample size, interval,
> and coverage warnings), `/coverage` v1 (per-source date ranges,
> observable outcomes, snapshot hash and time, methodology version),
> `POST /api/v1/corrections` (validated, rate-limited, contact encrypted
> with `security/crypto.py`, INSERT-only grant to the app role via
> migration `0007_corrections_intake`, `202` with the id), the latest
> snapshot on `/api/v1/ready`, word similarity (`<%`) for surname-only
> search (carry-over item 1), the regenerated `docs/openapi.json` and
> `web/lib/api/schema.d.ts`, `tests/unit/test_openapi.py` pinned to the
> new path set, statement budgets for every new route, the extended
> public-contract test (no person key or hash from any metrics route),
> `docs/API.md`, and `docs/PROVENANCE.md`. Steps 4 and 5 render these
> responses.

**Branch:** `feature/phase03-step3-provenance-metrics-api`

**Deploys:** local API (`uv run poe dev-api`) — the merge carries
migration `0007`; the operator applies it locally, restarts the API, and
`/api/v1/ready` reports the head `0007_corrections_intake` and the
latest snapshot. `JUDGEMETRICS_CORRECTION_CONTACT_KEY` becomes a required
setting for the API process (verified at kickoff: placeholder in
`.env.example`, a real Fernet key in the operator's `.env`, proven by an
accepted correction request in the Deployed & verified check).

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** This step is multi-file API implementation against
fixed conventions (routes → services → repositories, `StrictQuery`,
`paginate_rows`, the OpenAPI snapshot, statement budgets) plus a
security-sensitive write path and a migration: PRIMARY `coding`,
SECONDARY `agentic`, High complexity from cross-cutting scope with no
novel design (the trace's shape is the brief's chain and the corrections
path is specified column by column). Claude Opus 5 is rated S in coding
and S in agentic (Terminal-Bench 2.1 89.1) and supersedes Opus 4.8; under
the balanced posture the funded frontier model takes it at zero marginal
cost. The Platform is Claude Code on the flat claude.ai Max
subscription, so the flat-funding gate is open: Effort `Max`, Thinking
`On`. Backup: GPT-5.3 Codex on Codex (ChatGPT Plus; Intelligence High),
S-tier in coding from a different provider. Conversation is New per
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
       feature/phase03-step3-provenance-metrics-api`
       from a clean, up-to-date
       `main`. The exact branch
       name is in this step's
       `**Branch:**` line above.
       If the Worktree rule
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
       rejected. Pass the security
       gate before every commit.
       Stop the local API before
       `uv run poe gate` or
       `git commit`.

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
       --delete-branch`. If this
       step's `**Deploys:**` line
       names a surface, the merge
       is not the finish line: run
       the Deployed & verified
       check against the local
       environment before
       declaring the step complete.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree,
       `git worktree remove <path>`
       FIRST — the branch prune
       fails while the branch is
       checked out there.

    6. DISPOSE OF EVERY FINDING,
       DECLARE COMPLETION, THEN
       NEW CONVERSATION. First
       send every finding this
       step surfaced to its
       destination (Triage rule):
       a note for a later step →
       edit that step's <task>
       block now; spec rot → edit
       this roadmap now; a bug →
       fixed in-step or an issue
       number; a judgement call in
       the diff → the PR body; a
       process lesson → written
       where the next conversation
       reads it (AGENTS.md or this
       roadmap); a data-semantics
       finding → the registry
       entry, version bumped; a
       data-access question → a
       row in docs/ROADMAP.md.
       Update docs/ROADMAP.md
       (completed items, known
       issues, next milestones). A
       finding you can only
       describe is NOT disposed
       of, and counts as an unmet
       criterion. Only once the PR
       is merged, every acceptance
       criterion is affirmatively
       met, and every finding has
       a destination, say so
       plainly: end your final
       response with an explicit,
       unhedged completion line —
       verbatim shape "Step 3 is
       complete. You can now move on
       to Step 4."
       That line is the LAST line
       of the response. NOTHING
       follows it — no "Follow-ups
       (non-blocking)", "Notes",
       "Next", "worth a glance",
       or suggested improvements.
       A short ledger may PRECEDE
       it, one entry per finding
       naming its destination
       (issue #, file edited, PR
       body) — never an open item.
       If any criterion is unmet
       or any finding has no
       destination, state plainly
       that the step is NOT
       complete, name what is
       outstanding, and omit the
       completion line. "Done"
       means done. Then, for
       phase-boundary hygiene, the
       operator closes this
       session and opens a fresh
       one before Step 4.
  </lifecycle>

  <security>
    Security is a gate on THIS step,
    not a later phase. It is AS
    BINDING as any `<requirement>`
    below. Before the Stage-2
    commit, this step's work MUST
    pass the local, fail-closed
    security gate — the SAME gate
    wired into the pre-commit hook
    and re-run in CI:

    1. SECRET / PII SCAN. No
       credentials or tokens in the
       diff (`detect-secrets`). The
       Fernet key used by tests is
       generated in the test
       process, never committed;
       `.env.example` keeps
       `change-me`. No real contact
       detail in any fixture or test
       string (use
       `requester@example.invalid`).

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern
       (`bandit`). Every query is a
       SQLAlchemy construct; the
       compare route's `sort` is an
       allow-listed enum mapped to
       column expressions, never
       interpolated;
       `similarity_threshold` and
       `word_similarity_threshold`
       are set with `set_config(...,
       true)` and bound parameters;
       the corrections insert uses
       the ORM with a
       client-generated `uuid4()` id
       and no `RETURNING`; the
       contact is encrypted with
       `security/crypto.encrypt_contact`
       (Fernet) and nothing else.

    3. DEPENDENCY AUDIT. This step
       adds no runtime dependency;
       `cryptography` is already
       present and audited.

    4. SENSITIVE-DATA REVIEW. The
       app role gets `INSERT` on
       `correction_request` and
       nothing else on it (migration
       `0007`; test that `SELECT` as
       the app role raises
       insufficient privilege); the
       API never reads the table;
       the response carries the id
       and status only; `reason`,
       `requester_contact`,
       `supporting_material`, and
       the key are added to the log
       scrubber denylist
       (`correction_contact_key`,
       `requester_contact`,
       `contact`, `reason`) and a
       unit test proves a bound log
       line redacts them; every
       metrics response is built
       from `schemas/metrics.py`
       shapes that have no person
       field, and
       `tests/golden/test_public_contract.py`
       is extended to assert that no
       path under `/api/v1/metrics`,
       `/judges/{id}/metrics`,
       `/courts/{id}/metrics`, or
       `/metrics/{id}/provenance`
       returns a
       `public_person_key`,
       `person_id`, or 64-character
       hex string other than
       artifact and snapshot hashes;
       suppressed observations leave
       the API with
       `observed_count`,
       `observed_rate`, `value`,
       `distribution`, and bounds
       null.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 3. Step 3:
    provenance trace, metrics API,
    and corrections intake.

    Current state (as of Phase 2,
    post-Phase-3 Step 2):

    - `metric_snapshot`,
      `metric_observation` (with the
      snapshot, source, window,
      dimension, eligible-count,
      value, distribution, and
      `superseded_at` columns), and
      `metric_observation_member`
      hold rows after `metrics
      compute`;
      `source.coverage_start`/`coverage_end`/`observable_outcomes`
      are filled for the synthetic
      source; `verify` proves
      reproduction; `publish`
      refuses an incomplete chain.
      Column layout per kind (Step 2,
      `docs/DATA_MODEL.md`): a count
      keeps `observed_count`
      (`cohort_size` and
      `eligible_count` are the
      population); a share and a
      fixed-window rate keep
      `observed_count`/`cohort_size`,
      `observed_rate` (six decimals),
      and the Wilson bounds, the
      rate's `eligible_count` being
      the whole cohort; a survival
      estimate keeps the events by the
      window in `observed_count`, the
      whole cohort in `cohort_size`,
      `1 - S(w)` in `observed_rate`,
      and the Greenwood bounds
      (`value` is null); a
      distribution has one row per
      vocabulary value (zero counts
      included) with the whole map in
      `distribution`; a median keeps
      `n` in `cohort_size` and the
      median in `value`. The
      `interval_method` is therefore
      `wilson` for shares and rates,
      `greenwood` for survival, none
      otherwise. Members: a
      `court_case` id may repeat
      inside one observation (one
      cohort member per defendant of
      a disposition-indexed case);
      `eligible_defendants`'s members
      are its cases. Helpers to reuse:
      `metrics.publish.load_observations`
      (current rows with normalized
      columns and members),
      `publish.VERIFIED_COLUMNS`,
      `metrics.engine.compute_and_publish`,
      `metrics.snapshot.open_snapshot`
      (`Snapshot.member_ids(kind)`);
      `ingest_run.metrics_snapshot_id`
      (0006) names the snapshot a run's
      step 13 published from;
      `metric_snapshot.coverage` is
      `{source id: {name,
      coverage_start, coverage_end}}`.
      The test suite runs with
      `JUDGEMETRICS_METRICS_RECOMPUTE_ON_INGEST=false`
      (root conftest); the golden
      metrics suite computes through
      `compute_and_publish` as the
      ingest role with a temporary
      `snapshot_dir`, and
      `purge_source` deletes a
      source's observations before the
      source row.
    - API v1 conventions:
      `api/routes/*.py` with
      `StrictQuery` allow-lists,
      `services/*.py`,
      `repositories/*.py`
      (`paginate`, `paginate_rows`,
      `with_source`,
      `synthetic_flag()`),
      `schemas/*.py`,
      `api/errors.py` (`ApiError`,
      `ErrorBody`),
      `api/ratelimit.py` (token
      bucket keyed by client,
      `app.state.search_limiter`),
      `api/identity.py` (client key
      from the rightmost
      `X-Forwarded-For` when
      `trust_proxy`).
      `tests/unit/test_openapi.py`
      pins the exact path set and
      checks every `StrictQuery`
      against the document;
      `tests/integration/test_query_counts.py`
      holds the statement budgets;
      `tests/golden/test_public_contract.py`
      walks the OpenAPI document and
      the grants.
    - `/coverage`
      (`repositories/coverage.py`,
      `schemas/coverage.py`) is one
      correlated-count statement
      over `source` plus one
      `DISTINCT ON` for the latest
      runs; `synthetic_present`
      means rows exist.
    - `/search` and the judges `q`
      filter use `%` with
      `pg_trgm.similarity_threshold`
      0.3 over the whole normalized
      name
      (`repositories/search.py`,
      `repositories/judges.py`); the
      GIN trigram indexes exist from
      `0001`.
    - `correction_request` is
      restricted (no app-role
      privilege);
      `security/crypto.py`
      implements `encrypt_contact`;
      `Settings.correction_contact_key`
      is optional today.
    - `/api/v1/ready`
      (`api/routes/health.py`) asks
      Alembic for the current
      revision on every probe.
    - `logging.py` scrubs keys by
      denylist;
      `tests/unit/test_logging.py`
      is the pattern.
    - `web/lib/api/schema.d.ts` is
      generated by `pnpm
      generate:api` from
      `docs/openapi.json` and
      drift-tested by Vitest.

    Files to read (every file before
    drafting):
    - docs/brief/judgemetrics-master-project-specification.xml
      (`<api_design>` rules —
      methodology metadata, sample
      size and coverage with every
      metric, no private
      identifiers;
      `<data_provenance>` or the
      provenance chain text;
      `<metric_presentation>` rules;
      the correction process under
      trust and safety).
    - ROADMAP.md §4 Phase 3 (3.4,
      3.5), §5 "Provenance chain",
      "Performance rules"
      (query-count guard, strict
      page sizes, cached stable
      responses), "Security &
      privacy strategy" (correction
      requester contacts, rate
      limits on search, compare,
      corrections).
    - docs/API.md,
      docs/ARCHITECTURE.md ("Public
      API v1", "Metrics engine"),
      docs/METHODOLOGY.md,
      docs/DATA_MODEL.md.
    - src/judgemetrics/api/routes/cases.py,
      judges.py, coverage.py,
      search.py, health.py;
      api/deps.py, errors.py,
      ratelimit.py, identity.py;
      services/cases.py,
      coverage.py, provenance.py,
      search.py;
      repositories/cases.py,
      coverage.py, provenance.py,
      search.py, judges.py,
      common.py; schemas/cases.py,
      common.py, coverage.py,
      judges.py.
    - src/judgemetrics/metrics/*.py
      (Step 1 and 2),
      db/models/metrics.py,
      corrections.py, provenance.py,
      enums.py; security/crypto.py;
      config.py; logging.py; cli.py;
      openapi.py.
    - alembic/versions/0005_metric_registry_and_snapshots.py
      (grant constants),
      0001_baseline.py
      (`RESTRICTED_TABLES`).
    - tests/unit/test_openapi.py,
      test_logging.py,
      test_ratelimit.py;
      tests/integration/test_api_cases.py,
      test_api_coverage.py,
      test_api_search.py,
      test_query_counts.py,
      conftest.py;
      tests/golden/test_public_contract.py,
      test_golden_metrics.py.
    - web/lib/api/client.ts,
      web/tests/unit/schema-freshness.test.ts
      (what regeneration must
      satisfy).
    - AGENTS.md (API decisions to
      extend).
  </context>

  <goal>
    Ship the trace, the metrics
    endpoints, the compare endpoint,
    coverage v1, and the corrections
    intake such that every current
    observation of the golden
    fixture traces from its id to
    raw artifacts through the CLI
    and the endpoint (test), every
    metrics response carries
    numerator, denominator, date
    range, coverage, sample size,
    interval where defined,
    suppression, methodology
    version, and a methodology link,
    suppressed rows carry no
    numbers, the compare endpoint
    answers one metric for one
    cohort in two statements, a
    correction request is accepted,
    stored encrypted, and unreadable
    by the app role, and
    `docs/openapi.json` plus
    `web/lib/api/schema.d.ts` are
    regenerated with the exact path
    set pinned.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Create
      `metrics/provenance.py`:
      `trace(session,
      observation_id) ->
      ObservationTrace` — the
      observation (id, slug,
      version, subject type and id,
      source key, period, window,
      dimension, counts, rate,
      value, suppression,
      methodology version, registry
      version, code version,
      `computed_at`,
      `superseded_at`), its snapshot
      (hash, label, exported at,
      code version, storage uri, row
      counts), its members grouped
      by kind with counts
      (`counted`, `followed`) and
      the case ids they belong to,
      the distinct source records
      behind those members (id,
      external id, sha256, retrieved
      at, parser version, artifact
      uri) and their source (key,
      name, source type, synthetic
      flag), and `complete: bool`
      (every member resolved to a
      row and every row to a source
      record and artifact). The CLI
      `judgemetrics provenance trace
      <id> [--json]` prints the
      chain top-down in the brief's
      order and exits 1 when
      `complete` is false. Golden
      test: every current
      observation of the golden
      fixture traces `complete`;
      deleting one member's source
      record in the session makes
      the trace incomplete and
      `publish` would have refused
      it (assert `ProvenanceError`
      on a draft with a foreign id).
    </requirement>

    <requirement>
      Schemas in
      `schemas/metrics.py`:
      `MetricDefinitionOut` (slug,
      name, kind, subject types,
      description, numerator,
      denominator, eligibility,
      attribution, index event,
      outcome, windows, dimension,
      suppression threshold, unit,
      version, `methodology_url`),
      `Registry` (registry version,
      methodology version, known
      limitations, suppression rule,
      definitions), `Observation`
      (id, slug, version, subject
      type, subject id, `source`,
      `synthetic`, `period_start`,
      `period_end`, `window_days`,
      `dimension_value`,
      `eligible_count`,
      `denominator` (=
      `cohort_size`), `numerator` (=
      `observed_count`), `rate`,
      `value`, `distribution`,
      `lower`, `upper`,
      `interval_method`,
      `suppressed`,
      `suppression_threshold`,
      `coverage` (source coverage
      window and `observable`),
      `methodology_version`,
      `methodology_url`,
      `snapshot_hash`,
      `computed_at`),
      `SubjectMetrics` (subject
      summary plus observations
      grouped by metric slug),
      `CompareRow` (subject id,
      name, court, `numerator`,
      `denominator`,
      `eligible_count`, `rate`,
      `lower`, `upper`,
      `suppressed`,
      `coverage_warning`),
      `ObservationProvenance`,
      `CorrectionIn` (`target_type`
      in `judge`, `court`, `case`,
      `metric_observation`;
      `target_id` UUID; `reason`
      20–4000 chars; `contact` 3–320
      chars; `supporting_material`
      optional URL ≤ 2000 chars),
      `CorrectionAccepted` (id,
      status, received at). When
      `suppressed` is true the
      serializer nulls `numerator`,
      `rate`, `value`,
      `distribution`, `lower`,
      `upper` and keeps
      `denominator` only if it is at
      or above the threshold (it
      never is; keep the field null
      and `suppression_threshold`
      filled) — a unit test over the
      serializer.
    </requirement>

    <requirement>
      Routes, services,
      repositories: `GET
      /api/v1/metrics` (the registry
      from `load_registry()`, no
      database; cacheable); `GET
      /api/v1/judges/{judge_id}/metrics`
      and `GET
      /api/v1/courts/{court_id}/metrics`
      (current observations of the
      subject across its sources;
      404 from the subject lookup;
      two statements: the subject
      and the observations joined to
      definition, source, and
      `with_source` for the
      synthetic flag); `GET
      /api/v1/metrics/compare?metric=<slug>&window=<days>&court_id=<uuid>|jurisdiction_id=<uuid>&period_start=&period_end=&sort=rate|denominator|name&order=asc|desc&limit=&offset=`
      (judges of the court or
      jurisdiction with a current
      observation of that metric and
      window over the same source
      period; one page statement
      with `count(*) OVER ()`;
      `metric` validated against the
      registry, `window` against the
      metric's windows, unknown
      parameters rejected by
      `StrictQuery`; rows carry
      `coverage_warning` when the
      judge's coverage window
      differs from the cohort's or
      the metric is not observable
      for the source); `GET
      /api/v1/metrics/{observation_id}/provenance`
      (the trace; 404 for an unknown
      or superseded id; at most six
      statements); `/coverage` v1
      adds per source
      `coverage_start`,
      `coverage_end`,
      `observable_outcomes`,
      `latest_snapshot` (hash,
      `exported_at`),
      `methodology_version`, and
      top-level `registry_version`
      (one extra statement at most).
      `POST /api/v1/corrections`:
      `CorrectionIn` validated; the
      target must exist (one
      statement against the named
      table); the client key from
      `api/identity.py` is
      rate-limited by a second token
      bucket
      `app.state.corrections_limiter`
      (configurable, default 5 per
      hour per client, `None` under
      `env == test` unless enabled)
      answering 429 with
      `Retry-After`;
      `ContactKeyMissingError`
      answers 503 with a fixed
      message; the row is inserted
      with a client-generated id,
      `status = received`, no
      `RETURNING`; the response is
      `202 {id, status,
      received_at}`. Budgets in
      `test_query_counts.py`:
      subject metrics 2, compare 2,
      provenance 6, corrections 2.
    </requirement>

    <requirement>
      Migration
      `alembic/versions/0007_corrections_intake.py`
      (spec rot: `0006` was taken by
      Step 2's
      `ingest_run.metrics_snapshot_id`):
      `GRANT INSERT ON TABLE
      correction_request TO
      judgemetrics_app` (no SELECT,
      UPDATE, DELETE); downgrade
      revokes it. Integration test:
      as the app role, an INSERT
      succeeds and a SELECT raises
      `InsufficientPrivilege`; as
      the admin role the stored
      `requester_contact` decrypts
      to the submitted contact with
      `decrypt_contact` and is not
      the plaintext bytes. Make
      `Settings.correction_contact_key`
      required when `env != test` at
      API startup (`create_app`
      fails fast with a message
      naming the variable), and keep
      `.env.example` and `README.md`
      current. Update
      `docs/DATA_MODEL.md` "Grants".
    </requirement>

    <requirement>
      `/api/v1/ready` gains
      `metrics: {snapshot_hash,
      exported_at,
      methodology_version} | null`
      from one statement over
      `metric_snapshot` (latest
      `exported_at`);
      `/api/v1/health` is unchanged
      (no database).
    </requirement>

    <requirement>
      Word similarity (carry-over
      item 1): `/search` and the
      judges `q` filter match a
      single-token query with
      `word_similarity` (`<%`) under
      `pg_trgm.word_similarity_threshold`
      set per request with
      `set_config(..., true)`, and
      keep whole-name `%` similarity
      for multi-token queries; the
      GIN trigram indexes support
      both operators. Integration
      test over the FJC fixture: a
      misspelt surname alone finds
      the judge (the Phase 1 finding
      4.1 example, or a fixture
      judge with a long full name);
      the existing whole-name tests
      still pass. Document in
      `docs/API.md` "Filters".
    </requirement>

    <requirement>
      Regenerate `docs/openapi.json`
      (`uv run judgemetrics openapi
      export`) and
      `web/lib/api/schema.d.ts`
      (`pnpm generate:api` in
      `web/`); update
      `tests/unit/test_openapi.py`
      to the exact new path set and
      the new `StrictQuery`
      allow-lists; `pnpm test` in
      `web/` passes the
      schema-freshness test.
    </requirement>

    <requirement>
      Documentation: `docs/API.md`
      gains "Metrics" (the
      presentation fields on every
      observation, suppression, the
      compare parameters, coverage
      v1, the corrections intake and
      its limits),
      `docs/PROVENANCE.md` (the
      chain, the CLI, the endpoint,
      the completeness rule, an
      example trace over the golden
      fixture with hashes),
      `docs/ARCHITECTURE.md` "Public
      API v1" (the new routes and
      budgets; the INSERT-only write
      path), `AGENTS.md` (decisions:
      suppressed numbers stripped at
      the schema layer, the
      corrections grant and
      no-`RETURNING` insert, the
      second limiter, the required
      key, word similarity for
      single tokens), `README.md`
      command list (`provenance
      trace`).
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

- `uv run judgemetrics provenance trace <id>` prints the full chain for
  any current observation of the seeded database and exits 0; the golden
  test asserts every current observation traces `complete` and that an
  incomplete chain is refused at publish.
- `GET /api/v1/metrics` returns the registry with the eight known
  limitations verbatim and a `methodology_url` per definition.
- `GET /api/v1/judges/{id}/metrics` and `/courts/{id}/metrics` return
  every current observation with `numerator`, `denominator`,
  `eligible_count`, `period_start`, `period_end`, `coverage`, `rate`,
  `lower`, `upper`, `suppressed`, `suppression_threshold`,
  `methodology_version`, `methodology_url`, `snapshot_hash`, and
  `synthetic`; suppressed rows carry null numbers (contract test over the
  golden fixture, where small cohorts exist).
- `GET /api/v1/metrics/compare` answers one metric and window for one
  court or jurisdiction, sorted and paginated, in two statements; unknown
  parameters, an unknown metric, and a window the metric lacks answer
  422 with an `ErrorBody`.
- `GET /api/v1/metrics/{id}/provenance` matches the CLI trace and answers
  404 for unknown and superseded ids.
- `/coverage` carries per-source coverage windows, observable outcomes,
  the latest snapshot, and the methodology version; `/api/v1/ready`
  carries the latest snapshot block.
- `POST /api/v1/corrections` round-trips: 202 with an id; the row's
  contact decrypts under the admin role and is unreadable by the app role
  (integration tests); 422 on every invalid field; 429 when the bucket is
  exhausted (test with the limiter enabled); 503 without a key.
- A misspelt surname alone finds a fixture judge through `/search` and
  `/judges?q=` (integration test); existing search tests pass.
- `docs/openapi.json` and `web/lib/api/schema.d.ts` regenerated;
  `tests/unit/test_openapi.py` pins the new path set; `pnpm test` passes
  the freshness test; `tests/integration/test_query_counts.py` covers
  every new route within its budget.
- `docs/API.md`, `docs/PROVENANCE.md`, `docs/ARCHITECTURE.md`,
  `docs/DATA_MODEL.md`, `AGENTS.md`, `README.md`, `.env.example` updated
  as specified.
- `uv run poe check` passes; `pnpm lint`, `pnpm typecheck`, `pnpm test`
  pass in `web/`.
- **Deployed & verified:** after the squash-merge, `uv run poe migrate`
  applies `0007`, the restarted local API's `/api/v1/ready` reports the
  head `0007_corrections_intake` and a `metrics.snapshot_hash`, and a
  `curl -X POST /api/v1/corrections` with a valid body answers 202
  (proving the configured key), after which `SELECT status FROM
  correction_request WHERE id = <id>` as the admin role returns
  `received`.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean, SAST
  clean, dependency audit clean — and the new endpoints handle sensitive
  data per the project ROADMAP "Security & privacy strategy": no
  per-person row or key from any metrics endpoint (the extended
  public-contract test), the contact key and the submitted fields
  redacted in every log line (scrubber test), the app role holds
  `INSERT` only on `correction_request` (grant test), and the
  corrections route is rate-limited.

---

## Step 4 — Judge Metric Panels, Compare, Methodology, and Coverage

> **Goal:** Put the numbers on the pages under the brief's presentation
> rules: `web/components/metric-stat.tsx` (a `MetricStat` that always
> renders the numerator, denominator, date range, coverage, sample size,
> the interval when defined, the methodology link anchored at the
> metric's slug, the synthetic badge, and — when suppressed — the notice
> with the threshold instead of a number), `web/lib/metrics.ts`
> (grouping, window selection, formatting, cohort helpers); the judge
> page's four panels — Pretrial (decisions, released, detained, release
> share), Outcomes after qualifying release (the windowed rates and
> Kaplan–Meier estimates with a window selector defaulting to 365 days,
> `not observable` rows named), Disposition (distribution, judicial
> dismissal rate, median days to disposition), Sentencing (count and the
> medians by offense category) — with the association statement above
> them, a comparison-cohort selector (same court over the same period,
> the judge's value beside the court's pooled value and the court's
> judge distribution from `/metrics/compare`), and case drill-down
> (each panel links to `/judges/[judgeId]/cases` filtered to the
> panel's cohort); `/compare` (metric and window selectors, court or
> jurisdiction filter, a sortable table with sample size, interval, and
> coverage warnings, suppressed rows shown as suppressed, query
> parameters as the page state); `/methodology` rendered from
> `GET /api/v1/metrics` (definitions with formulas, attribution rules,
> windows, thresholds, versions, the known limitations verbatim, the
> changelog) replacing the static page; `/coverage` v1 (date ranges,
> observable outcomes, latest snapshot, methodology version, per-source
> completeness notes); the banner's coverage read cached in-process
> for sixty seconds (carry-over item 7); Vitest presentation-rule tests
> over `MetricStat` and the panels; and a Playwright metric flow
> (judge → panel → compare → methodology anchor). Step 5 reuses
> `MetricStat` and the compare table on the court and jurisdiction pages.

**Branch:** `feature/phase03-step4-metric-pages`

**Deploys:** local web app (`uv run poe dev-web` against the local API)
— nothing beyond merge; the operator runs the pages locally.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** This step is multi-file TypeScript and React
implementation against fixed conventions (the generated client,
`ApiResult`, `force-dynamic` pages, `ErrorState`/`EmptyState`, Vitest,
Playwright) with a presentation contract to enforce mechanically:
PRIMARY `coding`, SECONDARY `agentic` (build-and-run loops), with A-tier
multimodal useful for reviewing page screenshots; High complexity from
scope. Claude Opus 5 is rated S in coding, S in agentic (Terminal-Bench
2.1 89.1), and A in multimodal, and supersedes Opus 4.8; under the
balanced posture the funded frontier model takes it at zero marginal
cost. The Platform is Claude Code on the flat claude.ai Max
subscription, so the flat-funding gate is open: Effort `Max`, Thinking
`On`. Backup: GPT-5.3 Codex on Codex (ChatGPT Plus; Intelligence High),
S-tier in coding from a different provider. Conversation is New per
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
       feature/phase03-step4-metric-pages`
       from a clean, up-to-date
       `main`. The exact branch
       name is in this step's
       `**Branch:**` line above.
       If the Worktree rule
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
       rejected. Pass the security
       gate before every commit.
       Stop the local API before
       `uv run poe gate` or
       `git commit`.

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
       --delete-branch`. If this
       step's `**Deploys:**` line
       names a surface, the merge
       is not the finish line: run
       the Deployed & verified
       check against the local
       environment before
       declaring the step complete.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree,
       `git worktree remove <path>`
       FIRST — the branch prune
       fails while the branch is
       checked out there.

    6. DISPOSE OF EVERY FINDING,
       DECLARE COMPLETION, THEN
       NEW CONVERSATION. First
       send every finding this
       step surfaced to its
       destination (Triage rule):
       a note for a later step →
       edit that step's <task>
       block now; spec rot → edit
       this roadmap now; a bug →
       fixed in-step or an issue
       number; a judgement call in
       the diff → the PR body; a
       process lesson → written
       where the next conversation
       reads it (AGENTS.md or this
       roadmap); a data-semantics
       finding → the registry
       entry, version bumped; a
       data-access question → a
       row in docs/ROADMAP.md.
       Update docs/ROADMAP.md
       (completed items, known
       issues, next milestones). A
       finding you can only
       describe is NOT disposed
       of, and counts as an unmet
       criterion. Only once the PR
       is merged, every acceptance
       criterion is affirmatively
       met, and every finding has
       a destination, say so
       plainly: end your final
       response with an explicit,
       unhedged completion line —
       verbatim shape "Step 4 is
       complete. You can now move on
       to Step 5."
       That line is the LAST line
       of the response. NOTHING
       follows it — no "Follow-ups
       (non-blocking)", "Notes",
       "Next", "worth a glance",
       or suggested improvements.
       A short ledger may PRECEDE
       it, one entry per finding
       naming its destination
       (issue #, file edited, PR
       body) — never an open item.
       If any criterion is unmet
       or any finding has no
       destination, state plainly
       that the step is NOT
       complete, name what is
       outstanding, and omit the
       completion line. "Done"
       means done. Then, for
       phase-boundary hygiene, the
       operator closes this
       session and opens a fresh
       one before Step 5.
  </lifecycle>

  <security>
    Security is a gate on THIS step,
    not a later phase. It is AS
    BINDING as any `<requirement>`
    below. Before the Stage-2
    commit, this step's work MUST
    pass the local, fail-closed
    security gate — the SAME gate
    wired into the pre-commit hook
    and re-run in CI:

    1. SECRET / PII SCAN. No
       credentials or tokens in the
       diff (`detect-secrets`);
       `web/tests/unit/bundle-secrets.test.ts`
       still finds no
       `JUDGEMETRICS_` string in the
       production bundle.

    2. SAST.
       `eslint-plugin-security` with
       `--max-warnings 0`; no
       `dangerouslySetInnerHTML`
       (the methodology text is
       rendered as React text nodes,
       never HTML); query parameters
       read on `/compare` are
       validated against the
       registry's slugs and windows
       before they reach a fetch; no
       `eval`, no dynamic `require`.

    3. DEPENDENCY AUDIT. Any added
       package passes `pnpm audit
       --audit-level=high`; prefer
       no new dependency (the table,
       selectors, and formatting
       build on the existing shadcn
       primitives and
       `lib/format.ts`).

    4. SENSITIVE-DATA REVIEW. Pages
       render only fields the API
       schemas define; no page
       fetches a person route; the
       synthetic badge renders
       whenever `synthetic` is true;
       a suppressed observation
       renders the notice and never
       a number (a Vitest test
       asserts the DOM contains no
       digit inside a suppressed
       `MetricStat`); the cached
       coverage read is in-process
       and unkeyed (no per-client
       state).

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 3. Step 4:
    judge metric panels, compare
    page, methodology page, and
    coverage page.

    Current state (as of Phase 2,
    post-Phase-3 Step 3):

    - The API serves `GET
      /api/v1/metrics`,
      `/judges/{id}/metrics`,
      `/courts/{id}/metrics`,
      `/metrics/compare`,
      `/metrics/{id}/provenance`,
      `/coverage` v1;
      `web/lib/api/schema.d.ts` is
      regenerated and typed for
      them; `web/lib/api/client.ts`
      wraps every call in
      `ApiResult` (Step 3 added
      `getRegistry`,
      `getJudgeMetrics`,
      `getCourtMetrics`,
      `compareMetrics`,
      `getObservationProvenance`,
      `submitCorrection`).
      Shapes as shipped by Step 3
      (docs/API.md "Metrics"):
      `SubjectMetrics.observations`
      is a dict keyed by slug, each
      list ordered by window,
      dimension value, and source —
      `groupObservations` takes that
      map and groups each list by
      window → dimension;
      `Observation` carries `kind`,
      `unit`, `name`, and
      `interval_method` beside the
      presentation fields;
      `methodology_url` is already
      `/methodology#<slug>`
      (`JUDGEMETRICS_METHODOLOGY_URL`
      + `#<slug>`), so
      `methodologyHref` can pass it
      through; `/metrics/compare`
      takes `sort=rate|numerator|
      denominator|value|name`,
      answers `ComparePage` (a page
      plus `cohort` with the
      reference period, name, and
      ids) and 422 for a windowed
      metric without `window`;
      `/coverage` carries
      `registry_version` and
      `methodology_version` at the
      top level and `latest_snapshot`
      per source.
    - Web conventions
      (`docs/ARCHITECTURE.md` "Web
      tier", `web/AGENTS.md`): App
      Router, `force-dynamic` data
      pages,
      `ErrorState`/`EmptyState` for
      every fetch, `next-themes` on
      `data-theme`, shadcn
      primitives under
      `components/ui/`,
      `lib/format.ts`,
      `lib/links.ts`, Vitest with
      `tests/setup.ts`, Playwright
      in `tests/e2e/smoke.spec.ts`
      that discovers a synthetic
      judge and case through the
      API.
    - `app/judges/[judgeId]/page.tsx`
      renders the header, the
      service table, the cases
      panel, and the provenance
      panel;
      `app/methodology/page.tsx` is
      static prose with
      `data-testid="association-statement"`
      and
      `data-testid="metrics-note"`;
      `app/coverage/page.tsx`
      renders the v0 counts;
      `components/synthetic-banner.tsx`
      reads `/coverage` per request
      from the root layout.
    - `docs/METHODOLOGY.md` is the
      Markdown render of the
      registry; the page must show
      the same definitions from the
      API, not a second copy.

    Files to read (every file before
    drafting):
    - docs/brief/judgemetrics-master-project-specification.xml
      (`<metric_presentation>`
      example and rules,
      `<frontend_design>` judge,
      compare, methodology, and
      coverage pages,
      `<important_statistical_warnings>`).
    - ROADMAP.md §4 Phase 3 (3.5,
      3.6), §5 "Performance rules"
      (cached stable responses).
    - docs/API.md ("Metrics"),
      docs/METHODOLOGY.md,
      docs/ARCHITECTURE.md ("Web
      tier"), web/AGENTS.md.
    - web/app/judges/[judgeId]/page.tsx,
      judges/[judgeId]/cases/page.tsx,
      courts/[courtId]/page.tsx,
      coverage/page.tsx,
      methodology/page.tsx,
      layout.tsx, search/page.tsx.
    - web/components/cases-panel.tsx,
      provenance-panel.tsx,
      badges.tsx, states.tsx,
      synthetic-banner.tsx,
      site-header.tsx, ui/*.tsx.
    - web/lib/api/client.ts,
      schema.d.ts (the metrics
      types), format.ts, links.ts.
    - web/tests/unit/provenance-panel.test.tsx,
      synthetic.test.tsx,
      client.test.ts;
      web/tests/e2e/smoke.spec.ts;
      web/playwright.config.ts;
      web/vitest.config.ts.
    - src/judgemetrics/schemas/metrics.py
      (the shapes; every field the
      panels render).
  </context>

  <goal>
    Ship the pages such that a
    synthetic judge's page shows
    case volume and every objective
    outcome metric under the
    presentation rules with the
    association statement, a cohort
    selector that compares the judge
    against the same court over the
    same period, and drill-down to
    the underlying cases; `/compare`
    answers one metric at a time for
    a comparable cohort with sample
    sizes, intervals, and coverage
    warnings; `/methodology` shows
    exactly how each metric is
    calculated from the registry the
    API serves with the known
    limitations verbatim;
    `/coverage` states what each
    source covers and observes; and
    Vitest proves the presentation
    rules while Playwright walks
    judge → panel → compare →
    methodology.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Create `web/lib/metrics.ts`:
      `groupObservations(observations)`
      by slug → window → dimension;
      `pickWindow(group, days)`;
      `formatRate`,
      `formatInterval`,
      `formatDays`, `formatCount`,
      `formatPeriod` (date range),
      `formatCoverage`;
      `isSuppressed`;
      `cohortLabel(observation)`
      ("Same court, same period");
      `methodologyHref(slug,
      version)`
      (`/methodology#<slug>`); and
      the `WINDOWS` constant read
      from the registry response,
      never hard-coded. Unit tests
      over every helper, including
      null-safe formatting for
      not-observable and suppressed
      rows.
    </requirement>

    <requirement>
      Create
      `web/components/metric-stat.tsx`:
      props are one `Observation`
      (from `schema.d.ts`) plus
      `label`; renders the label,
      the primary figure (rate as a
      percentage, median as days,
      count as an integer),
      `numerator / denominator` and
      `eligible` when it differs,
      the interval with its method,
      the period, the coverage
      (source key, coverage window,
      observable), the sample-size
      line, the methodology link,
      the synthetic badge when
      `synthetic`, and — when
      `suppressed` — the text
      "Suppressed: fewer than N
      eligible …" with the threshold
      in place of every figure;
      `data-testid="metric-stat"`
      with `data-slug`,
      `data-window`, and
      `data-suppressed`. Create
      `components/metric-panel.tsx`
      (a titled card of
      `MetricStat`s with an optional
      window selector and a "View
      eligible cases" link) and
      `components/cohort-selector.tsx`
      (a client component: cohort
      options "Same court, same
      period" — the default — and
      "Jurisdiction, same period";
      selection is a query parameter
      `cohort=court|jurisdiction`,
      read by the server page).
      Vitest: `metric-stat.test.tsx`
      asserts every presentation
      field is present for a rate, a
      median, a count, and a
      distribution; a suppressed
      observation renders the notice
      and no digit; a not-observable
      metric renders "Not observable
      in this source"; the
      methodology link anchors at
      the slug.
    </requirement>

    <requirement>
      Judge page: fetch
      `/judges/{id}`,
      `/judges/{id}/metrics`, and,
      for the selected cohort,
      `/metrics/compare` for each
      displayed metric's slug and
      window (batched by
      `Promise.all`; on any failure
      the panel renders `ErrorState`
      and the rest of the page
      renders) and
      `/courts/{id}/metrics` for the
      pooled court value. Render, in
      order: the association
      statement (the exact text of
      the methodology page's
      statement,
      `data-testid="association-statement"`),
      Cases (eligible cases,
      eligible defendants),
      Pretrial, Outcomes after
      qualifying release (window
      selector `?window=` defaulting
      to 365; both the fixed-window
      rate and the Kaplan–Meier
      estimate per outcome; each row
      shows the judge's value, the
      court's pooled value, and
      where the judge falls in the
      court's distribution — count
      of judges, the cohort's median
      rate — from the compare rows),
      Disposition, Sentencing, then
      the existing cases panel,
      service table, and provenance
      panel. Every panel carries a
      "View eligible cases" link to
      `/judges/[judgeId]/cases` with
      the panel's filter (status or
      case type where the cases
      route supports it; otherwise
      unfiltered — record the gap in
      the PR body and Not in scope).
      Section anchors `#pretrial`,
      `#outcomes`, `#disposition`,
      `#sentencing`.
    </requirement>

    <requirement>
      `/compare` page
      (`app/compare/page.tsx`,
      `force-dynamic`): controls for
      metric (from the registry, one
      at a time), window (the
      metric's windows), cohort
      (court or jurisdiction, chosen
      by search from `/courts` and
      `/jurisdictions` lists or by
      id in the query), sort, and
      order, all held in query
      parameters (`metric`,
      `window`, `court_id`,
      `jurisdiction_id`, `sort`,
      `order`, `offset`); validated
      client-side against the
      registry and server-side by
      the API; a sortable table
      (judge, court, numerator /
      denominator, rate, interval,
      sample size, coverage warning,
      suppressed) with pagination
      and a "Comparison notes" block
      (the cohort definition, the
      period, the methodology link,
      the warning that rates are
      associations and depend on
      case mix). Add `/compare` to
      the site header.
    </requirement>

    <requirement>
      `/methodology`
      (`force-dynamic`, from `GET
      /api/v1/metrics`): the
      statement section (unchanged
      text and test ids), "How to
      read a number", "Index events,
      exposure, and censoring" (the
      API's registry text), one
      `<section id="<slug>">` per
      definition (name, version,
      subject types, formula,
      eligibility, attribution,
      windows, threshold, unit),
      "Suppression", "Known
      limitations" (the eight
      warnings verbatim as a list,
      `data-testid="known-limitations"`),
      "Changelog", and the existing
      links; remove the Phase 3
      "Status" note. A Vitest test
      renders the page with a
      stubbed registry and asserts
      every definition has an anchor
      and every limitation is
      present verbatim. Keep
      `ErrorState` when the registry
      fetch fails.
    </requirement>

    <requirement>
      `/coverage` v1: per source,
      add the coverage window, the
      observable outcomes (and the
      not-observable ones named),
      the latest snapshot hash and
      time, and the methodology
      version; a top-level
      "Snapshot" card; keep the
      synthetic labelling. Cache the
      banner's coverage read:
      `components/synthetic-banner.tsx`
      reads through a module-level
      in-process cache with a
      sixty-second TTL
      (`lib/coverage-cache.ts`; the
      cache is bypassed under
      `NODE_ENV=test`), so a page
      view no longer costs a
      `/coverage` call every time;
      unit test the TTL with fake
      timers.
    </requirement>

    <requirement>
      Playwright
      `tests/e2e/metrics.spec.ts`:
      discover a synthetic judge
      through the API whose
      `/judges/{id}/metrics` has an
      unsuppressed
      `pretrial_release_share`
      (query `/metrics/compare`
      sorted by denominator), open
      the judge page, assert the
      association statement precedes
      the panels, assert a
      `metric-stat` for
      `pretrial_release_share` shows
      numerator, denominator,
      period, coverage, and the
      methodology link, switch the
      window selector to 90 days and
      assert the outcomes panel
      updates, open the compare link
      and assert the judge's row is
      in the table with a
      sample-size cell, follow the
      methodology link and assert
      the anchor's section is
      visible with the formula. The
      suite passes over the demo
      seed (Step 5 switches CI's
      `e2e` job); until then, run it
      locally.
    </requirement>

    <requirement>
      Documentation:
      `docs/ARCHITECTURE.md` "Web
      tier" (the metric components,
      the cohort selector as a query
      parameter, the compare page
      state, the coverage cache),
      `web/AGENTS.md` (the
      presentation-rule component is
      the only way a number is
      rendered), `AGENTS.md`,
      `README.md` "Web" (the new
      pages). Update
      `docs/screenshots/phase03-step4/`
      with light and dark captures
      of the judge panels, compare,
      methodology, and coverage
      pages and a README, as Phase 1
      Step 5 did.
    </requirement>

    <requirement>
      Filepath comment: every new
      TypeScript and Markdown file
      gets the repo-relative path as
      the first line (`//
      web/lib/metrics.ts`).
    </requirement>
  </requirements>
</task>
```

### Step 4 acceptance criteria

- `MetricStat` renders numerator, denominator, date range, coverage,
  sample size, interval (when defined), methodology link, and the
  synthetic badge for rate, median, count, and distribution
  observations; a suppressed observation renders the notice and no digit;
  a not-observable metric renders its notice (Vitest).
- The judge page shows the association statement above the Cases,
  Pretrial, Outcomes, Disposition, and Sentencing panels, a window
  selector, the cohort selector with the court's pooled value and
  distribution, and "View eligible cases" links; the existing service,
  cases, and provenance panels remain.
- `/compare` renders one metric for one court or jurisdiction with
  sortable columns, sample size, interval, coverage warnings, and
  suppressed rows marked; its state lives in query parameters; invalid
  parameters render `ErrorState`, never a crash.
- `/methodology` is rendered from `GET /api/v1/metrics` with one anchored
  section per definition and the eight known limitations verbatim
  (Vitest); the association statement and its test id are unchanged.
- `/coverage` shows coverage windows, observable outcomes, the latest
  snapshot, and the methodology version.
- The banner's coverage read is cached in-process for sixty seconds
  (unit test with fake timers); the root layout stays `force-dynamic`.
- `web/tests/e2e/metrics.spec.ts` passes locally against the demo seed
  (recorded in the PR body with the run output).
- `pnpm lint`, `pnpm typecheck`, `pnpm build`, `pnpm test` pass in
  `web/`; `uv run poe check` passes.
- `docs/screenshots/phase03-step4/` holds the light and dark captures
  with a README; `docs/ARCHITECTURE.md`, `web/AGENTS.md`, `AGENTS.md`,
  `README.md` updated.
- **Deployed & verified:** after the squash-merge, `uv run poe dev-web`
  against the local API renders a synthetic judge's panels, `/compare`,
  `/methodology`, and `/coverage` without an `ErrorState`, and
  `pnpm e2e --grep metrics` passes locally.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean,
  `eslint-plugin-security` clean with zero warnings, `pnpm audit` clean —
  and the pages handle sensitive data per the project ROADMAP "Security
  & privacy strategy" (no person route fetched, no HTML injection of
  methodology text, suppressed cohorts never rendered as numbers, no
  `JUDGEMETRICS_` string in the bundle).

---

## Step 5 — Corrections Form, Remaining Pages, `bootstrap`, and Walkthrough

> **Goal:** Close the brief's page list and prove the milestone from one
> command: `/corrections` (`app/corrections/page.tsx` with a client form
> posting to `POST /api/v1/corrections` through a Next route handler
> `app/api/corrections/route.ts` that forwards the client key, validates,
> and never logs the body; prefilled from `?target_type=&target_id=`) and
> a "Report a data error" action on the judge, court, case, and metric
> surfaces; the court page's comparable-judge metric table (the compare
> table for the court, default metric and window, linking to `/compare`)
> plus the court's own `MetricStat` panels from `/courts/{id}/metrics`;
> `/jurisdictions/[jurisdictionId]` v0 (name, courts, available years
> from the coverage window, data completeness from `/coverage`, and the
> jurisdiction-level compare table); the `bootstrap` poe task (`up`,
> `migrate`, `ingest-fjc`, `seed`, `compute-metrics`) and `make
> bootstrap` (`install` first), the README "Quick start" rewritten around
> it with the seventeen-item walkthrough as a numbered list mapping each
> item to a command or page; the `e2e` CI job switched from the golden
> fixture to `judgemetrics seed` (demo scale, fixed seed) followed by
> `metrics compute`; and `web/tests/e2e/first-milestone.spec.ts`
> automating items 8–16 (open the site, search a synthetic judge, open
> the profile, view case volume and objective outcome metrics, open an
> underlying case, view its timeline and provenance, return, compare the
> metric against the comparison cohort, read the methodology section)
> while `scripts/verify_phase03.py --post` (Step 6) covers items 1–7 and
> 17. Step 6 verifies everything.

**Branch:** `feature/phase03-step5-corrections-bootstrap-walkthrough`

**Deploys:** local web app and CI — nothing beyond merge; the `e2e` job
definition changes on merge, and the operator runs `uv run poe
bootstrap` locally.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** This step is multi-file TypeScript and CI
implementation reusing Step 4's components, plus a task-runner change and
a documentation rewrite: PRIMARY `coding`, SECONDARY `agentic` (long
end-to-end loops over a seeded database and a Playwright run), Medium
novelty with High scope. Claude Opus 5 is rated S in coding and S in
agentic (Terminal-Bench 2.1 89.1) and supersedes Opus 4.8; under the
balanced posture the funded frontier model takes it at zero marginal
cost. The Platform is Claude Code on the flat claude.ai Max
subscription, so the flat-funding gate is open: Effort `Max`, Thinking
`On`. Backup: GPT-5.3 Codex on Codex (ChatGPT Plus; Intelligence High),
S-tier in coding from a different provider. Conversation is New per
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
       feature/phase03-step5-corrections-bootstrap-walkthrough`
       from a clean, up-to-date
       `main`. The exact branch
       name is in this step's
       `**Branch:**` line above.
       If the Worktree rule
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
       rejected. Pass the security
       gate before every commit.
       Stop the local API before
       `uv run poe gate` or
       `git commit`.

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
       --delete-branch`. If this
       step's `**Deploys:**` line
       names a surface, the merge
       is not the finish line: run
       the Deployed & verified
       check against the local
       environment before
       declaring the step complete.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree,
       `git worktree remove <path>`
       FIRST — the branch prune
       fails while the branch is
       checked out there.

    6. DISPOSE OF EVERY FINDING,
       DECLARE COMPLETION, THEN
       NEW CONVERSATION. First
       send every finding this
       step surfaced to its
       destination (Triage rule):
       a note for a later step →
       edit that step's <task>
       block now; spec rot → edit
       this roadmap now; a bug →
       fixed in-step or an issue
       number; a judgement call in
       the diff → the PR body; a
       process lesson → written
       where the next conversation
       reads it (AGENTS.md or this
       roadmap); a data-semantics
       finding → the registry
       entry, version bumped; a
       data-access question → a
       row in docs/ROADMAP.md.
       Update docs/ROADMAP.md
       (completed items, known
       issues, next milestones). A
       finding you can only
       describe is NOT disposed
       of, and counts as an unmet
       criterion. Only once the PR
       is merged, every acceptance
       criterion is affirmatively
       met, and every finding has
       a destination, say so
       plainly: end your final
       response with an explicit,
       unhedged completion line —
       verbatim shape "Step 5 is
       complete. You can now move on
       to Step 6."
       That line is the LAST line
       of the response. NOTHING
       follows it — no "Follow-ups
       (non-blocking)", "Notes",
       "Next", "worth a glance",
       or suggested improvements.
       A short ledger may PRECEDE
       it, one entry per finding
       naming its destination
       (issue #, file edited, PR
       body) — never an open item.
       If any criterion is unmet
       or any finding has no
       destination, state plainly
       that the step is NOT
       complete, name what is
       outstanding, and omit the
       completion line. "Done"
       means done. Then, for
       phase-boundary hygiene, the
       operator closes this
       session and opens a fresh
       one before Step 6.
  </lifecycle>

  <security>
    Security is a gate on THIS step,
    not a later phase. It is AS
    BINDING as any `<requirement>`
    below. Before the Stage-2
    commit, this step's work MUST
    pass the local, fail-closed
    security gate — the SAME gate
    wired into the pre-commit hook
    and re-run in CI:

    1. SECRET / PII SCAN. No
       credentials or tokens in the
       diff (`detect-secrets`). The
       `e2e` job's pepper and
       contact key are generated in
       the job (`openssl rand` / a
       Python one-liner into
       `$GITHUB_ENV`), never stored
       in the workflow; the
       Playwright test submits
       `requester@example.invalid`.

    2. SAST.
       `eslint-plugin-security`
       clean; the route handler
       forwards only the validated
       fields to the API (an
       allow-list, not a spread),
       sets no cookie, and returns
       the API's status and the id
       only; the form has no file
       upload (supporting material
       is a URL field); `bandit`
       clean over any Python
       touched.

    3. DEPENDENCY AUDIT. No new
       package; `pnpm audit
       --audit-level=high` and
       `pip-audit` clean.

    4. SENSITIVE-DATA REVIEW. The
       route handler and the page
       never log the body; the
       reason and contact appear in
       no server log line (assert
       with a Vitest test over the
       handler using a spied
       logger); the client key
       reaches the API through
       `X-Forwarded-For` only when
       the API's `trust_proxy` is
       set, which the Compose `web`
       service documents; the
       workflow declares
       `permissions: contents: read`
       and pins every action by SHA
       (unchanged); the confirmation
       page shows the request id and
       never echoes the contact.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 3. Step 5:
    corrections form, court and
    jurisdiction pages, `bootstrap`,
    and the first-milestone
    walkthrough.

    Current state (as of Phase 2,
    post-Phase-3 Step 4):

    - `POST /api/v1/corrections`
      accepts a validated request,
      rate-limited per client,
      contact encrypted, 202 with an
      id; the app role cannot read
      the table.
    - `MetricStat`, `MetricPanel`,
      `CohortSelector`,
      `lib/metrics.ts`, `/compare`,
      the registry-driven
      `/methodology`, and
      `/coverage` v1 are merged;
      `web/tests/e2e/metrics.spec.ts`
      passes locally over the demo
      seed.
    - `app/courts/[courtId]/page.tsx`
      renders the court header and
      the judges-serving-on-a-date
      table; there is no
      jurisdiction page;
      `/jurisdictions` and
      `/jurisdictions/{id}` exist in
      the API.
    - `pyproject.toml`
      `[tool.poe.tasks]`: `up`
      (sequence), `migrate`,
      `ingest-fjc`, `seed`,
      `compute-metrics`, `dev-api`,
      `dev-web`; the `Makefile`
      mirrors every target and has
      `install`.
    - `.github/workflows/ci.yml`
      `e2e` job: creates roles,
      migrates, ingests the FJC
      fixture, ingests the golden
      fixture, starts the API and
      the web app, installs
      Chromium, runs `pnpm e2e`; the
      golden judges' cohorts are
      below the suppression
      threshold on most rates, so
      the walkthrough needs the demo
      seed.
    - `README.md` "Quick start"
      lists the commands one by one;
      the brief's first milestone is
      the seventeen-item checklist.
    - `web/tests/e2e/smoke.spec.ts`
      discovers a synthetic judge
      and case through the API (the
      pattern for the walkthrough's
      discovery).

    Files to read (every file before
    drafting):
    - docs/brief/judgemetrics-master-project-specification.xml
      (`<first_milestone_expected_result>`,
      `<frontend_design>` court,
      jurisdiction, and correction
      pages, the correction process
      under trust and safety).
    - ROADMAP.md §4 Phase 3 (3.5,
      3.6, acceptance criteria), §5
      "Command interface"
      (`bootstrap`), "Release &
      deployment strategy".
    - README.md, pyproject.toml,
      Makefile, docker-compose.yml,
      .github/workflows/ci.yml,
      .env.example,
      web/.env.example.
    - web/app/courts/[courtId]/page.tsx,
      judges/[judgeId]/page.tsx,
      cases/[caseId]/page.tsx,
      compare/page.tsx,
      coverage/page.tsx, layout.tsx;
      web/components/metric-stat.tsx,
      metric-panel.tsx,
      cohort-selector.tsx,
      site-header.tsx, states.tsx;
      web/lib/api/client.ts,
      metrics.ts, links.ts.
    - web/tests/e2e/smoke.spec.ts,
      metrics.spec.ts;
      web/playwright.config.ts.
    - src/judgemetrics/api/routes/jurisdictions.py,
      schemas/jurisdictions.py,
      coverage.py;
      src/judgemetrics/cli.py
      (`seed` options).
    - docs/ARCHITECTURE.md ("Web
      tier"), docs/API.md,
      web/AGENTS.md, AGENTS.md.
  </context>

  <goal>
    Ship the remaining pages and the
    one-command startup such that a
    correction submitted through
    `/corrections` is accepted and
    stored encrypted, the court page
    shows its metrics and a
    comparable-judge table, a
    jurisdiction page renders, `uv
    run poe bootstrap` (or `make
    bootstrap`) alone brings a clean
    machine from a fresh clone with
    Docker to a database with FJC
    judges, the demo dataset, and
    computed metrics, and
    `first-milestone.spec.ts` walks
    items 8–16 of the brief's
    checklist over that data in CI.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      `/corrections`:
      `app/corrections/page.tsx`
      (server page reading
      `target_type`, `target_id`,
      and `label` from the query;
      renders the target summary
      when the API knows it) hosting
      `components/correction-form.tsx`
      (client component: target type
      and id as read-only fields
      when prefilled, `reason`
      textarea with the API's length
      limits, `contact` input,
      optional `supporting_material`
      URL, a consent line stating
      that the contact is stored
      encrypted and used only to
      answer the request, submit
      with pending and error
      states). The form posts to
      `app/api/corrections/route.ts`,
      a route handler that validates
      the same limits, forwards an
      allow-listed body to `POST
      /api/v1/corrections` with the
      caller's `X-Forwarded-For`
      when present, and returns
      `{id, status}` or the API's
      `ErrorBody` and status (422,
      429 with `Retry-After`, 503).
      On success render
      `/corrections/received?id=`
      with the id and what happens
      next. Add a "Report a data
      error" link to the judge page
      header, the court page header,
      the case page header, and each
      `MetricPanel` (target
      `metric_observation` with the
      first observation's id).
      Vitest: the form disables
      submit until valid, shows the
      API's field errors, and the
      handler forwards only the
      allow-listed fields and logs
      nothing of the body.
    </requirement>

    <requirement>
      Court page: fetch
      `/courts/{id}/metrics` and
      `/metrics/compare?court_id=…`
      for the default metric
      (`pretrial_release_share`) and
      window; render the court's
      Pretrial, Outcomes,
      Disposition, and Sentencing
      panels with `MetricStat`
      (court-level rows include
      `statutory_release_count` and
      `unknown_actor_pretrial_count`),
      then "Comparable judges" — the
      compare table (judge,
      numerator / denominator, rate,
      interval, sample size,
      suppressed) with a metric
      selector and a link to
      `/compare?court_id=…` — above
      the existing judges-serving
      table. Jurisdiction page
      `app/jurisdictions/[jurisdictionId]/page.tsx`
      v0: name and type, the courts
      list (linked), available years
      (from the coverage windows of
      the sources in `/coverage`
      whose jurisdiction matches, or
      "no case data" for FJC-only
      jurisdictions), data
      completeness (the `/coverage`
      source rows for the
      jurisdiction), and the
      jurisdiction-level compare
      table for the default metric.
      Add jurisdiction links from
      the court page and the
      coverage page.
    </requirement>

    <requirement>
      `bootstrap`: `pyproject.toml`
      `bootstrap = ["up", "migrate",
      "ingest-fjc", "seed",
      "compute-metrics"]` (a
      sequence task; `uv sync` is
      the documented prerequisite
      because poe runs inside the
      environment) and `Makefile`
      `bootstrap: install` followed
      by `uv run poe bootstrap`; the
      task must be idempotent (a
      second run re-ingests nothing,
      re-seeds nothing, publishes
      nothing) and must fail loudly
      when `.env` lacks
      `JUDGEMETRICS_IDENTIFIER_PEPPER`
      or
      `JUDGEMETRICS_CORRECTION_CONTACT_KEY`
      (`judgemetrics seed` already
      refuses without the pepper;
      add the key check to `metrics
      compute`'s startup only if the
      API needs it there — otherwise
      document that the key is
      checked when the API starts).
      Rewrite `README.md` "Quick
      start" around `bootstrap`,
      then `dev-api` and `dev-web`,
      and add "The first milestone"
      — the seventeen items as a
      numbered list, each mapped to
      the command, page, or test
      that satisfies it (`uv run poe
      check` for item 17). Keep the
      individual commands documented
      below it.
    </requirement>

    <requirement>
      CI `e2e` job: replace "Ingest
      the golden synthetic fixture"
      with `uv run judgemetrics seed
      --out data/synthetic/ci` (demo
      scale, the default seed;
      generate the pepper and the
      contact key into `$GITHUB_ENV`
      in an earlier step) followed
      by `uv run judgemetrics
      metrics compute`; keep the FJC
      fixture ingest; start the API
      with
      `JUDGEMETRICS_CORRECTION_CONTACT_KEY`
      set; keep the timeouts
      realistic (measure the seed
      and compute durations in the
      PR body). Update
      `web/tests/e2e/smoke.spec.ts`
      if its discovery assumptions
      depended on the golden fixture
      (it discovers through the API,
      so it should not). Note from
      Step 4: the golden ingest
      already computes metrics at
      pipeline step 13 (the job does
      not disable
      `JUDGEMETRICS_METRICS_RECOMPUTE_ON_INGEST`),
      so `metrics.spec.ts` passed in
      CI on PR #21 over the golden
      fixture (J-0002 has 17
      pretrial decisions); the
      switch to the seed is for the
      walkthrough's scale, not for
      the metrics flow. Step 4's
      `metric-stat`, `metric-panel`,
      `compare-table`, and
      `lib/metrics.ts` are the
      components to reuse on the
      court and jurisdiction pages;
      `/compare` accepts `judge=` to
      highlight a row and its court
      chooser is two `/courts`
      pages.
    </requirement>

    <requirement>
      `web/tests/e2e/first-milestone.spec.ts`:
      one test per checklist item
      8–16, in order, sharing a
      discovered judge (a synthetic
      circuit judge with an
      unsuppressed
      `pretrial_release_share` and
      at least one closed case,
      found through
      `/metrics/compare` and
      `/judges/{id}/cases`): 8 open
      `/` and assert the banner and
      search; 9 search the judge's
      surname and assert the result;
      10 open the profile and assert
      the header and synthetic
      badge; 11 assert the Cases
      panel's eligible-cases figure
      and an unsuppressed outcome
      `metric-stat`; 12 open a case
      from the cases panel; 13
      assert the timeline and the
      provenance panel with a
      sha256; 14 navigate back and
      assert the judge header; 15
      use the cohort selector,
      assert the court's pooled
      value beside the judge's,
      follow the compare link, and
      assert the judge's row and its
      sample-size cell; 16 follow
      the metric's methodology link
      and assert the anchored
      section shows the formula and
      the known limitations list is
      present; plus one test that
      submits the corrections form
      for the judge and asserts the
      received page shows an id. The
      suite runs in CI over the demo
      seed and locally after
      `bootstrap`.
    </requirement>

    <requirement>
      Documentation:
      `docs/ARCHITECTURE.md` "Web
      tier" (the corrections route
      handler and why the page never
      calls the API from the browser
      directly, the court and
      jurisdiction pages),
      `docs/API.md` (the intake from
      the web), `web/AGENTS.md`,
      `AGENTS.md` (decisions:
      `bootstrap` sequence and
      idempotency, the `e2e` job on
      the demo seed, the corrections
      handler allow-list),
      `README.md` as above,
      `CONTRIBUTING.md` if the e2e
      instructions live there,
      `docs/screenshots/phase03-step5/`
      (court, jurisdiction,
      corrections; light and dark;
      README).
    </requirement>

    <requirement>
      Filepath comment: every new
      TypeScript, YAML, and Markdown
      file gets the repo-relative
      path as the first line.
    </requirement>
  </requirements>
</task>
```

### Step 5 acceptance criteria

- `/corrections` submits through the route handler and renders the
  received page with an id; the row exists with an encrypted contact
  (checked as the admin role in the Deployed & verified recipe); invalid
  input shows field errors; the handler logs nothing of the body
  (Vitest).
- "Report a data error" links exist on the judge, court, case, and
  metric-panel surfaces and prefill the target.
- The court page renders its metric panels and the comparable-judge
  table; the jurisdiction page renders courts, available years,
  completeness, and the compare table; both handle an empty cohort with
  `EmptyState`.
- `uv run poe bootstrap` on a clean clone with Docker and `.env`
  configured completes with FJC judges, the demo dataset, and computed
  metrics; a second run changes nothing (recorded in the PR body with
  the console output).
- The `e2e` CI job seeds the demo dataset, computes metrics, and runs
  the smoke, metrics, and first-milestone suites green.
- `web/tests/e2e/first-milestone.spec.ts` passes in CI and locally after
  `bootstrap`, one test per checklist item 8–16 plus the corrections
  submission.
- `README.md` "Quick start" is `bootstrap`-first and "The first
  milestone" maps every checklist item to its command, page, or test.
- `pnpm lint`, `pnpm typecheck`, `pnpm build`, `pnpm test` pass;
  `uv run poe check` passes; `docs/screenshots/phase03-step5/` present.
- **Deployed & verified:** after the squash-merge, `uv run poe
  bootstrap`, `uv run poe dev-api`, and `uv run poe dev-web` on the
  maintainer's machine, then `pnpm e2e` passes every suite locally, and a
  correction submitted through the form is present with `status =
  received` when read as the admin role.
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff — secret/PII scan clean, SAST
  clean, dependency audits clean — and the corrections path handles
  sensitive data per the project ROADMAP "Security & privacy strategy"
  (the handler forwards an allow-list and logs nothing of the body; the
  CI job generates its pepper and key at run time; the workflow keeps
  least-privilege permissions and SHA-pinned actions).

---

## Step 6 — QA & Verification Script

> **Goal:** Package the verification matrix into
> `scripts/verify_phase03.py` (with `--fast`, `--py`, `--node`, `--e2e`,
> `--security`, `--all`, and `--post` modes, mirroring
> `verify_phase02.py`), produce `docs/phase03-qa-findings.md`, add `"03"`
> to the `phase-verify.yml` matrix and make `phase-verify (03)` a
> required context, update `docs/ROADMAP.md`, and tag `v0.3.0-phase-3`.
> The script checks every Step 1 through Step 5 deliverable statically
> and runs the Phase 3 pytest, Vitest, and Playwright suites in the
> appropriate modes; the `--post` mode runs the V1–V6 matrix, the seed
> and compute idempotency probes, `metrics verify`, a `provenance trace`
> of a random current observation, the first-milestone items 1–7 and 17
> as subprocess steps (`bootstrap` on the configured database, `uv run
> poe check`), and `gh pr checks`.

**Branch:** `feature/phase03-step6-verify`

**Deploys:** nothing beyond merge — the CI matrix entry is live on
merge; the tag is pushed after the merge.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                          |
| ------------ | ------------------------------ |
| Model        | Claude Opus 5                  |
| Platform     | Claude Code                    |
| Effort       | Max                            |
| Thinking     | On                             |
| Conversation | **New**                        |

**Model rationale:** This is the mechanical translation of
`verify_phase02.py` into Phase 3's deliverables — numbered static checks,
mode dispatch, subprocess suites, the V-matrix, the findings rollup, a
one-line matrix edit, and the tag: PRIMARY `coding`, a known pattern with
no novel reasoning (roadmodel's "standard implementation, multi-file
changes, and roadmap execution" default). Claude Opus 5 is rated S in
coding (Terminal-Bench 2.1 89.1); the open flat-funding gate suspends
tier-down for routine work, so the funded frontier model takes it at
zero marginal cost. The Platform is Claude Code on the flat claude.ai Max
subscription: Effort `Max` (this script gates every later phase's CI and
its `--post` mode drives the milestone probe), Thinking `On`. Backup:
GPT-5.3 Codex on Codex (ChatGPT Plus; Intelligence High), S-tier in
coding from a different provider. Conversation is New per phase-boundary
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
       feature/phase03-step6-verify`
       from a clean, up-to-date
       `main`. The exact branch
       name is in this step's
       `**Branch:**` line above.
       If the Worktree rule
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
       rejected. Pass the security
       gate before every commit.
       Stop the local API before
       `uv run poe gate` or
       `git commit`.

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
       --delete-branch`. If this
       step's `**Deploys:**` line
       names a surface, the merge
       is not the finish line: run
       the Deployed & verified
       check against the local
       environment before
       declaring the step complete.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree,
       `git worktree remove <path>`
       FIRST — the branch prune
       fails while the branch is
       checked out there.

    6. DISPOSE OF EVERY FINDING,
       DECLARE COMPLETION, THEN
       NEW CONVERSATION. First
       send every finding this
       step surfaced to its
       destination (Triage rule):
       a note for a later step →
       edit that step's <task>
       block now; spec rot → edit
       this roadmap now; a bug →
       fixed in-step or an issue
       number; a judgement call in
       the diff → the PR body; a
       process lesson → written
       where the next conversation
       reads it (AGENTS.md or this
       roadmap); a data-semantics
       finding → the registry
       entry, version bumped; a
       data-access question → a
       row in docs/ROADMAP.md.
       Update docs/ROADMAP.md
       (completed items, known
       issues, next milestones). A
       finding you can only
       describe is NOT disposed
       of, and counts as an unmet
       criterion. Only once the PR
       is merged, every acceptance
       criterion is affirmatively
       met, and every finding has
       a destination, say so
       plainly: end your final
       response with an explicit,
       unhedged completion line —
       verbatim shape "Step 6 is
       complete. Phase 3 is
       complete. You can now move on
       to Phase 4."
       That line is the LAST line
       of the response. NOTHING
       follows it — no "Follow-ups
       (non-blocking)", "Notes",
       "Next", "worth a glance",
       or suggested improvements.
       A short ledger may PRECEDE
       it, one entry per finding
       naming its destination
       (issue #, file edited, PR
       body) — never an open item.
       If any criterion is unmet
       or any finding has no
       destination, state plainly
       that the step is NOT
       complete, name what is
       outstanding, and omit the
       completion line. "Done"
       means done. Then, for
       phase-boundary hygiene, the
       operator closes this
       session and opens a fresh
       one before Phase 4.
  </lifecycle>

  <security>
    Security is a gate on THIS step,
    not a later phase. It is AS
    BINDING as any `<requirement>`
    below. Before the Stage-2
    commit, this step's work MUST
    pass the local, fail-closed
    security gate — the SAME gate
    wired into the pre-commit hook
    and re-run in CI. This step also
    AUTHORS the `--security` verify
    mode, so its own diff must still
    pass the gate before commit:

    1. SECRET / PII SCAN. No
       credentials or tokens in the
       diff (`detect-secrets`); the
       findings document quotes
       issue numbers, file paths,
       and commit SHAs, never file
       contents or environment
       values.

    2. SAST. `bandit` clean over
       `scripts/`; every subprocess
       is an argument list over a
       PATH-resolved tool
       (`shutil.which`), never a
       shell; the `--security`
       mode's detect-secrets
       invocation batches file
       arguments under the Windows
       argv limit; suppressions sit
       after the ruff one with the
       justification between them.

    3. DEPENDENCY AUDIT. Standard
       library only; `pip-audit` and
       `pnpm audit` clean.

    4. SENSITIVE-DATA REVIEW. The
       script prints check names,
       paths, counts, and tool
       output — never repository
       file contents, never a
       database row; the `--post`
       probes read counts and hashes
       only; the `provenance trace`
       probe prints the CLI's
       output, which carries no
       person material by Step 3's
       contract. At least one static
       check is security-oriented:
       the pre-commit config still
       wires detect-secrets, bandit,
       and the dependency audit;
       `phase-verify.yml` and
       `ci.yml` still run them with
       least-privilege permissions
       and SHA-pinned actions; the
       metrics schemas carry no
       person field; the corrections
       grant is INSERT-only in
       `0007`; and no private-key
       header, `AKIA`, or
       `-----BEGIN` string exists
       under the phase's paths.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean.
  </security>

  <context>
    JudgeMetrics. Phase 3. Step 6:
    QA + verification script.

    Steps 1 through 5 have been
    implemented. Now create the
    verification script, the QA
    findings document, the CI matrix
    update, the required context,
    the status update, and the tag.

    Reference scripts (pattern
    templates):
    - scripts/verify_phase02.py
      (closest structural precedent:
      modes, numbered checks,
      `[PASS] NN` / `[FAIL] NN —
      reason`, subprocess suites,
      the V-matrix via `gh pr
      checks`, the seed idempotency
      probe, the summary table,
      Windows and Ubuntu parity).
    - scripts/verify_phase01.py
      (secondary pattern reference;
      its OpenAPI subset check 29).
    - tests/unit/test_phase02_verification.py
      (runs `--fast` under pytest).

    Phase 3 deliverables to verify
    (44 static checks across Steps 1
    through 5 plus 5 Step 6
    self-checks):

    Step 1 (registry + frame) —
    checks 1–9:
    1. `data/reference/metric_registry.yaml`
       exists, is tracked, parses,
       carries `version`,
       `methodology_version`,
       exactly eight
       `known_limitations`, and the
       required slugs (the list in
       Step 1's requirement).
    2. `src/judgemetrics/metrics/`
       contains `__init__.py`,
       `registry.py`, `frame.py`,
       `attribution.py`,
       `index_events.py`,
       `exposure.py`, `windows.py`,
       `censoring.py`,
       `intervals.py`,
       `methodology.py`.
    3. `alembic/versions/0005_metric_registry_and_snapshots.py`
       exists, creates
       `metric_snapshot` and
       `metric_observation_member`,
       adds `source.coverage_start`,
       `coverage_end`,
       `observable_outcomes`, and
       grants from constants.
    4. `docs/METHODOLOGY.md` exists
       with the "Known limitations"
       section containing each of
       the brief's eight warnings
       verbatim (parse the XML).
    5. The registry's
       `known_limitations` equal the
       brief's warnings verbatim.
    6. `tests/property/test_frame_invariants.py`
       and
       `tests/unit/test_attribution.py`
       exist and are tracked.
    7. `cli.py` defines the
       `methodology` group with
       `render` and `--check`.
    8. `docs/ARCHITECTURE.md` has a
       "Metrics engine" section;
       `docs/DATA_MODEL.md` names
       `metric_snapshot` and
       `metric_observation_member`.
    9. No module under
       `src/judgemetrics/metrics/`
       reads `person_identifier`,
       `full_name`, `date_of_birth`,
       or `public_person_key`
       (grep).

    Step 2 (engine) — checks 10–18:
    10. `src/judgemetrics/metrics/snapshot.py`,
        `compute.py`,
        `suppression.py`,
        `publish.py`, `verify.py`
        exist.
    11. `pyproject.toml` lists
        `duckdb` in
        `[project.dependencies]` and
        `uv.lock` pins it;
        `snapshot.py` contains no
        `INSTALL` or `LOAD`
        statement.
    12. `pyproject.toml` defines
        `compute-metrics`; the
        `Makefile` mirrors it.
    13. `cli.py` defines `metrics
        compute` and `metrics
        verify`.
    14. `tests/fixtures/golden/manifest.json`
        records `generator_version`
        `2`, `truth_version` `2`,
        and `corpus`;
        `truth/metrics.json` carries
        `index_events` and
        `not_observable`; every file
        hash matches (recompute).
    15. `tests/golden/test_golden_metrics.py`
        exists and is tracked.
    16. `ingest/runner.py`'s
        `recompute_metrics` is no
        longer a no-op (it imports
        from
        `judgemetrics.metrics`).
    17. `ingest/base.py` defines
        `SupportsCoverage` and
        `SourceInfo.observable_outcomes`.
    18. `.gitignore` excludes
        `data/snapshots/`;
        `.env.example` documents
        `JUDGEMETRICS_SNAPSHOT_DIR`.

    Step 3 (API) — checks 19–29:
    19. `src/judgemetrics/metrics/provenance.py`
        exists; `cli.py` defines
        `provenance trace`.
    20. `api/routes/metrics.py` and
        `corrections.py`,
        `schemas/metrics.py`,
        `services/metrics.py`,
        `repositories/metrics.py`
        exist.
    21. `docs/openapi.json` contains
        `/api/v1/metrics`,
        `/api/v1/judges/{judge_id}/metrics`,
        `/api/v1/courts/{court_id}/metrics`,
        `/api/v1/metrics/compare`,
        `/api/v1/metrics/{observation_id}/provenance`,
        and `POST
        /api/v1/corrections` (a
        subset check;
        `test_openapi.py` pins the
        exact set).
    22. `alembic/versions/0007_corrections_intake.py`
        exists and grants `INSERT`
        only (no `SELECT`, `UPDATE`,
        `DELETE` for the app role on
        `correction_request`).
    23. `schemas/metrics.py` defines
        no field named `person_id`,
        `public_person_key`,
        `full_name`, or
        `date_of_birth` (grep).
    24. `logging.py`'s denylist
        includes
        `correction_contact_key`,
        `requester_contact`,
        `contact`, `reason`.
    25. `web/lib/api/schema.d.ts`
        mentions
        `/api/v1/metrics/compare`
        and `/api/v1/corrections`.
    26. `docs/API.md` has a
        "Metrics" section;
        `docs/PROVENANCE.md` exists.
    27. `tests/golden/test_public_contract.py`
        names the metrics routes;
        `tests/integration/test_query_counts.py`
        names compare, subject
        metrics, provenance, and
        corrections budgets.
    28. `repositories/search.py`
        uses `word_similarity` or
        `<%`.
    29. `api/routes/health.py`
        reports `metrics` on
        `/ready` (grep for
        `snapshot_hash`).

    Step 4 (pages) — checks 30–37:
    30. `web/components/metric-stat.tsx`,
        `metric-panel.tsx`,
        `cohort-selector.tsx`,
        `web/lib/metrics.ts`,
        `web/lib/coverage-cache.ts`
        exist.
    31. `web/app/compare/page.tsx`
        exists;
        `web/app/methodology/page.tsx`
        no longer contains
        `metrics-note` and fetches
        `/api/v1/metrics`.
    32. `web/app/judges/[judgeId]/page.tsx`
        renders `MetricPanel` and
        the association statement
        test id.
    33. `web/tests/unit/metric-stat.test.tsx`
        and
        `web/tests/e2e/metrics.spec.ts`
        exist.
    34. `metric-stat.tsx` renders
        `methodologyHref` and a
        suppressed notice (grep for
        `data-suppressed`).
    35. `web/components/synthetic-banner.tsx`
        imports the coverage cache.
    36. `docs/screenshots/phase03-step4/README.md`
        exists with light and dark
        captures.
    37. No `dangerouslySetInnerHTML`
        under `web/app` or
        `web/components` (grep).

    Step 5 (corrections, pages,
    bootstrap, walkthrough) — checks
    38–44:
    38. `web/app/corrections/page.tsx`,
        `web/app/corrections/received/page.tsx`,
        `web/app/api/corrections/route.ts`,
        `web/components/correction-form.tsx`
        exist.
    39. `web/app/jurisdictions/[jurisdictionId]/page.tsx`
        exists;
        `web/app/courts/[courtId]/page.tsx`
        renders `MetricPanel`.
    40. `pyproject.toml` defines
        `bootstrap` as the sequence
        `up`, `migrate`,
        `ingest-fjc`, `seed`,
        `compute-metrics`; the
        `Makefile` has `bootstrap`.
    41. `README.md` has "The first
        milestone" with seventeen
        numbered items.
    42. `.github/workflows/ci.yml`
        `e2e` job runs `judgemetrics
        seed` and `metrics compute`
        and no longer ingests
        `tests/fixtures/golden`.
    43. `web/tests/e2e/first-milestone.spec.ts`
        exists with at least nine
        tests.
    44. `docs/screenshots/phase03-step5/README.md`
        exists.

    Step 6 self-checks — checks
    45–49:
    45. `scripts/verify_phase03.py`
        exists, is tracked, has the
        path comment and the
        argparse modes.
    46. `docs/phase03-qa-findings.md`
        exists with every rollup
        section.
    47. `docs/phase03-roadmap.md`
        exists (this doc).
    48. `.github/workflows/phase-verify.yml`
        matrix includes `"03"`.
    49. Security wiring:
        `.pre-commit-config.yaml`
        runs detect-secrets, bandit,
        and the dependency audit;
        `ci.yml` and
        `phase-verify.yml` declare
        `permissions:` and pin every
        `uses:` to a 40-character
        SHA; no `-----BEGIN`,
        `AKIA`, or private-key
        header under `src`,
        `alembic`, `scripts`,
        `web/app`, `web/components`,
        `web/lib`, `data/reference`,
        `docs` (excluding the
        brief).

    Files to read:
    - scripts/verify_phase02.py
      (primary structural template).
    - all Phase 3 implementation
      files from Steps 1 through 5
      (the paths above).
    - docs/phase02-qa-findings.md
      (rollup structure, the alarm
      exercise, pre-ship items, the
      carry-over checklist).
    - docs/ROADMAP.md, ROADMAP.md §4
      Phase 3 acceptance criteria
      and Phase 4, CONTRIBUTING.md
      "Repository settings".
    - .github/workflows/phase-verify.yml,
      ci.yml.
  </context>

  <goal>
    Create scripts/verify_phase03.py
    with the 44 static deliverable
    checks (Steps 1 through 5) plus
    the 5 Step 6 self-checks plus
    the post-implementation V1–V6
    matrix. Create
    docs/phase03-qa-findings.md. Add
    `"03"` to the phase-verify.yml
    matrix and make `phase-verify
    (03)` a required context. Update
    docs/ROADMAP.md and the root
    ROADMAP.md if its Phase 3
    acceptance bullets drifted. Tag
    `v0.3.0-phase-3`.
  </goal>

  <requirements>
    <requirement>
      Read scripts/verify_phase02.py
      end-to-end for structure, flag
      parsing, output format,
      `record` conventions, the
      suite runners, the `--post`
      probes, and the final summary
      table. Mirror the format
      exactly so the Phase 3 script
      is visually continuous with
      the Phase 2 script in CI logs.
    </requirement>

    <requirement>
      scripts/verify_phase03.py
      modes (mutually exclusive;
      default `--fast` plus `--py`):
      `--fast` static checks only,
      CI-safe on Ubuntu and Windows,
      under 30 seconds, `pathlib`,
      `re`, `json`, `hashlib`,
      `yaml`-free (parse the
      registry's required keys with
      a minimal reader or `json`
      after a `uv run python -c`
      dump — choose the approach
      that keeps the script
      standard-library only, as
      Phase 2 did for the manifest),
      and `git ls-files`; `--py`
      static + ruff, ruff format
      --check, mypy, the unit suite,
      and the integration, property,
      and golden suites when a
      database is configured
      (`JUDGEMETRICS_TEST_DATABASE_URL`
      preferred); `--node` static +
      `pnpm lint`, `typecheck`,
      `build`, `test` in `web/`;
      `--e2e` static + `pnpm e2e`
      (skips with a reason when the
      API or web app is not
      reachable); `--security`
      detect-secrets against the
      baseline over tracked files
      batched under the Windows argv
      limit, bandit over `src
      alembic scripts`, `pip-audit`
      over `uv.lock` through
      `scripts/audit_deps.py`, `pnpm
      audit`; `--all` everything;
      `--post` static + the V1–V6
      matrix (reading `gh pr checks`
      where a check is a CI job) +
      the seed idempotency probe +
      the compute idempotency probe
      (`metrics compute` twice; the
      second publishes zero) +
      `metrics verify` + `provenance
      trace` of one current
      observation (exit 0 and
      `complete`) + the milestone
      items 1–7 and 17 as labelled
      subprocess steps (`uv sync`,
      `poe up`, `poe migrate`, `poe
      seed`, API `/ready` and web
      `/` reachable, `poe check`)
      that run against the
      configured environment and
      skip with a reason when Docker
      is absent + `gh pr checks` for
      the current branch when `gh`
      is signed in. Each static
      check is independent, prints
      `[PASS] NN description` or
      `[FAIL] NN description —
      reason`, and never prints file
      contents.
    </requirement>

    <requirement>
      Post-implementation V-checks
      mirroring Phase 2 (V1–V6): V1
      registry and frame (V1.1
      static 1–9; V1.2
      `test_metric_registry.py`
      (`test_registry.py` is the
      connector registry's test),
      `test_attribution.py`,
      `test_methodology_render.py`;
      V1.3
      `test_frame_invariants.py`
      under the `ci` profile; V1.4
      `test_migrations.py` through
      0005); V2 engine (V2.1 static
      10–18; V2.2
      `test_golden_metrics.py` and
      the extended
      `test_golden_counts.py`; V2.3
      `test_synthetic_ingest.py`
      step-13 tests; V2.4 compute
      idempotency and `metrics
      verify` probes in `--post`);
      V3 API (V3.1 static 19–29;
      V3.2 `test_api_metrics.py`,
      `test_api_corrections.py`,
      `test_api_search.py`,
      `test_query_counts.py`,
      `test_openapi.py`,
      `test_public_contract.py`;
      V3.3 the provenance trace
      probe in `--post`; V3.4 the
      container job green); V4 pages
      (V4.1 static 30–37; V4.2
      `pnpm` lint, typecheck, build,
      test; V4.3 `metrics.spec.ts`
      in the `e2e` job); V5
      corrections, pages, bootstrap,
      walkthrough (V5.1 static
      38–44; V5.2
      `first-milestone.spec.ts` in
      the `e2e` job; V5.3 the
      bootstrap and milestone probe
      in `--post`); V6 CI
      integration + security (V6.1
      `--fast` exits 0 on Ubuntu;
      V6.2 the matrix includes `03`;
      V6.3 all 49 static checks
      pass; V6.4 `--security` exits
      0).
    </requirement>

    <requirement>
      Add
      `tests/unit/test_phase03_verification.py`
      running
      `scripts/verify_phase03.py
      --fast` as a subprocess and
      asserting exit 0 and no
      `[FAIL]` line, so the
      aggregate `test` check and
      `phase-verify (03)` fail
      together on a broken
      deliverable.
    </requirement>

    <requirement>
      Update
      `.github/workflows/phase-verify.yml`
      to include `"03"` in
      `matrix.phase` (additive;
      preserve `"01"` and `"02"`).
      After the PR's first green
      run, add `phase-verify (03)`
      to the required status checks
      on `main` with `gh api -X PUT
      repos/{owner}/{repo}/branches/main/protection/required_status_checks`
      (read the current contexts
      first and re-submit them plus
      the new one; `gh pr edit` is
      unreliable on this machine and
      is not the tool for this), and
      record the command in
      `CONTRIBUTING.md` "Repository
      settings".
    </requirement>

    <requirement>
      Create
      docs/phase03-qa-findings.md
      with rollup sections for Steps
      1 through 5 (every finding,
      its class per the Triage rule,
      and the guard added), a Step 6
      verify-script rollup, an
      "Alarm exercise" section
      (break one static check on the
      PR, observe `phase-verify
      (03)` and `test` fail, fix,
      observe both pass; record
      commit SHAs and run ids; and
      the analytics-snapshot alarm:
      tamper one observation in the
      scratch database, observe
      `metrics verify` exit 1 naming
      it, restore, observe exit 0 —
      record the commands and output
      lines), a "Pre-ship items"
      section (documented
      limitations at the Phase 3
      exit: methodology `0.1` with
      no adjusted statistics, the
      incarceration-deferral
      limitation, thresholds fixed
      at 10 pending real data,
      `release_violation` and
      `rearrest` not observable in
      the synthetic source,
      snapshots on the local
      filesystem, the corrections
      key held by the API process,
      no admin reader for
      corrections), and the Phase 4
      carry-over checklist (at
      minimum: methodology `1.0`
      with the changelog; the
      expected-count, expected-rate,
      ratio, and interval columns to
      fill; planted judge effects in
      the generator under a new
      `TRUTH_VERSION`; per-metric
      thresholds revisited with real
      data in Phase 5; envelope or
      asymmetric encryption for
      correction contacts when Phase
      6's admin reader arrives; the
      object-store snapshot variant
      in Phase 8; parent-case checks
      across runs from Phase 2
      carry-over item 6; unmerge,
      admin authentication, and the
      probabilistic scorer from
      Phase 2 items 3–5).
    </requirement>

    <requirement>
      Update docs/ROADMAP.md: verify
      the root ROADMAP.md Phase 3
      "Acceptance criteria" section
      matches this roadmap's V1–V6
      checks (consistency audit;
      patch the root roadmap's Phase
      3 acceptance bullets in this
      PR if they drifted); Current
      phase → Phase 4 not started,
      Phase 3 complete with the tag;
      Completed table rows for Steps
      1–6; Known issues from the
      pre-ship items; Next
      milestones updated. After the
      squash-merge, tag the merge
      commit `v0.3.0-phase-3` and
      push the tag.
    </requirement>

    <requirement>
      The script prints clear pass /
      fail per check, exits 0 on
      success, exits 1 on any
      failure; mirrors the exact
      output format, check-numbering
      convention, and summary table
      of verify_phase02.py so CI log
      diffing across phases is
      frictionless. `--fast` must
      complete in under 30 seconds
      on Ubuntu CI and on Windows.
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

- `scripts/verify_phase03.py` exists, is tracked, and passes on a clean
  tree post-implementation.
- The script has 44 deliverable checks plus 5 self-checks plus the
  V1–V6 post-implementation matrix (49 static checks total).
- `--fast` runs in under 30 seconds on Ubuntu CI and on Windows.
- `--post` runs cleanly on the maintainer's machine with the seed and
  compute idempotency probes, `metrics verify`, the provenance trace
  probe, and the milestone items 1–7 and 17 green.
- `docs/phase03-qa-findings.md` complete with every rollup section, the
  two alarm exercises, pre-ship items, and the Phase 4 carry-over
  checklist.
- `.github/workflows/phase-verify.yml` matrix includes `"03"`; the check
  appears on the PR; `phase-verify (03)` is a required context on
  `main` (recorded in `CONTRIBUTING.md`).
- `--security` mode exists and exits 0 (secret/PII scan, SAST, and
  dependency audits clean over the phase's surface); V6.4 is green.
- `tests/unit/test_phase03_verification.py` passes; branch protection
  still passes on the resulting PR.
- `docs/ROADMAP.md` updated; the root `ROADMAP.md` Phase 3 acceptance
  bullets match V1–V6; the tag `v0.3.0-phase-3` is on the squash-merged
  commit and pushed.
- **Operations:** the analytics snapshot has a health signal
  (`/api/v1/ready` `metrics.snapshot_hash`; `metrics verify` green) and
  an alarm (`metrics verify` non-zero) that was seen to fire once in the
  alarm exercise (a tampered observation in the scratch database,
  reported by id and column, then restored) — per the parent ROADMAP
  "Operations & observability strategy".
- **Security gate clean** (always the final criterion): the pre-commit
  security gate passed on this step's diff and the security workflow is
  green.
- **Phase closed, nothing carried.** Every finding recorded in
  `docs/phase03-qa-findings.md` has a destination (fixed, an issue
  number, or a named phase that owns it), the "Not in scope" section
  below is current, and no un-tracked item remains. This step's final
  response ends with two lines and nothing after them: "Step 6 is
  complete. You can now move on to Step 7." is replaced by "Step 6 is
  complete. Phase 3 is complete. You can now move on to Phase 4." — same
  Stage 6 rule: no "Follow-ups", no trailer.

---

## Post-Implementation Verification

Every V1–V6 check below runs automatically in CI on every push and
pull request — no manual invocation required — except V2.4, V3.3, V5.3,
and the `--post` sweep, which the operator runs locally against the
Compose services and the bootstrapped database before tagging
`v0.3.0-phase-3` (the `e2e` CI job covers V4.3 and V5.2 on Ubuntu over
the FJC fixture plus the demo seed; the milestone's items 1–7 on a clean
machine are a local, wall-clock check because CI's runner is not a clean
developer machine).

| Mode         | Workflow                                     | Runner           | Coverage                                                            |
| ------------ | -------------------------------------------- | ---------------- | ------------------------------------------------------------------- |
| `--fast`     | `phase-verify.yml` (matrix entry `03`)       | Ubuntu           | Static checks 1–49, V1.1, V2.1, V3.1, V4.1, V5.1, V6.1–V6.3          |
| `--py`       | `ci.yml` (`python` job, Postgres service)    | Ubuntu           | V1.2, V1.3, V1.4, V2.2, V2.3, V3.2                                   |
| `--node`     | `ci.yml` (`web` job)                         | Ubuntu           | V4.2                                                                |
| `--e2e`      | `ci.yml` (`e2e` job, demo seed)              | Ubuntu           | V4.3, V5.2                                                          |
| `--security` | `ci.yml` (`security` and `container` jobs) + `phase-verify.yml` | Ubuntu | V3.4, V6.4                                            |
| `--post`     | local (maintainer's machine)                 | Windows / Ubuntu | Full V1–V6 sweep + V2.4 + V3.3 + V5.3 + `gh pr checks`              |

Local invocations remain available for ad-hoc runs and pre-release
sweeps:

```bash
uv run python scripts/verify_phase03.py --post   # static + V1-V6 + probes + milestone items + gh pr checks
```

`--post` is the canonical command to run before tagging the phase
release.

Other modes:

```bash
uv run python scripts/verify_phase03.py             # static + Python suites
uv run python scripts/verify_phase03.py --fast      # static only (CI)
uv run python scripts/verify_phase03.py --py        # static + ruff + mypy + pytest (unit, integration, property, golden)
uv run python scripts/verify_phase03.py --node      # static + web lint/typecheck/build/test
uv run python scripts/verify_phase03.py --e2e       # static + Playwright (smoke, metrics, first milestone)
uv run python scripts/verify_phase03.py --security  # secret scan + SAST + audits
uv run python scripts/verify_phase03.py --all       # everything
```

The script reports each V-check by id (V1.1, V2.1, …) so a failure in
any workflow above maps directly to the corresponding row below.

### V1 — Metric registry, analytic frame, generated methodology

> **Automated in CI.** `phase-verify.yml` → V1.1; `ci.yml` → V1.2
> through V1.4.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V1.1 | Static checks 1–9 all PASS (registry file and slugs, package modules, migration 0005, METHODOLOGY.md with verbatim warnings, tests present, CLI group, docs, no person material in the package). | `phase-verify.yml` runs `verify_phase03.py --fast`. |
| V1.2 | `test_metric_registry.py` (load, validation, verbatim warnings, truth-definition equality), `test_attribution.py`, `test_methodology_render.py` pass. | `ci.yml` `python` job (`--py` locally). |
| V1.3 | `test_frame_invariants.py` passes under the `ci` profile, including equality with `synthetic/truth.py` on the same world. | `ci.yml` `python` job (`HYPOTHESIS_PROFILE=ci`). |
| V1.4 | `test_migrations.py` round-trips through 0005; `sync_definitions` is idempotent; grant tests pass. | `ci.yml` `python` job with the `postgres:17` service. |

### V2 — Snapshot, computation engine, golden metric tests

> **Automated in CI.** `phase-verify.yml` → V2.1; `ci.yml` → V2.2 and
> V2.3; local `--post` → V2.4.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V2.1 | Static checks 10–18 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V2.2 | `test_golden_metrics.py` passes: every registry metric equals its truth expectation exactly, not-observable metrics absent, `verify()` zero mismatches, a tampered observation reported, every member id exists; `test_golden_counts.py` extended; `test_golden_fixture.py` at versions 2/2. | `ci.yml` `python` job. |
| V2.3 | `test_synthetic_ingest.py` step-13 tests pass (impacted subjects only; FJC computes nothing; unchanged rerun supersedes nothing); coverage window and observable outcomes written. | `ci.yml` `python` job. |
| V2.4 | Compute idempotency probe (second `metrics compute` publishes zero) and `metrics verify` exit 0 against the seeded database. | `--post` locally. |

### V3 — Provenance trace, metrics API, corrections intake

> **Automated in CI.** `phase-verify.yml` → V3.1; `ci.yml` `python` →
> V3.2; local `--post` → V3.3; `ci.yml` `container` → V3.4.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V3.1 | Static checks 19–29 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V3.2 | `test_api_metrics.py` (registry, subject metrics, compare, provenance, coverage v1, ready block, suppression stripping), `test_api_corrections.py` (202, 422, 429, 503, encrypted and unreadable by the app role), `test_api_search.py` (word similarity), `test_query_counts.py`, `test_openapi.py`, `test_public_contract.py` (no person key from any metrics route) pass. | `ci.yml` `python` job. |
| V3.3 | `judgemetrics provenance trace <id>` of one current observation exits 0 and reports `complete`. | `--post` locally. |
| V3.4 | Both images build and the vulnerability scans are clean.                    | `ci.yml` `container` job (`--post` reads it via `gh pr checks`). |

### V4 — Judge metric panels, compare, methodology, coverage pages

> **Automated in CI.** `phase-verify.yml` → V4.1; `ci.yml` `web` →
> V4.2; `ci.yml` `e2e` → V4.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V4.1 | Static checks 30–37 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V4.2 | `pnpm lint`, `pnpm typecheck`, `pnpm build`, `pnpm test` pass (`metric-stat.test.tsx` presentation rules, methodology render, coverage cache TTL, schema freshness, bundle scan). | `ci.yml` `web` job (`--node` locally). |
| V4.3 | `metrics.spec.ts` passes over the demo seed (judge → panel → window → compare → methodology anchor). | `ci.yml` `e2e` job (`--e2e` locally). |

### V5 — Corrections form, court and jurisdiction pages, bootstrap, walkthrough

> **Automated in CI.** `phase-verify.yml` → V5.1; `ci.yml` `e2e` →
> V5.2; local `--post` → V5.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V5.1 | Static checks 38–44 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V5.2 | `first-milestone.spec.ts` passes over the demo seed: items 8–16 plus the corrections submission. | `ci.yml` `e2e` job (`--e2e` locally). |
| V5.3 | `uv run poe bootstrap` is idempotent and the milestone items 1–7 and 17 pass as subprocess steps on the maintainer's machine. | `--post` locally. |

### V6 — CI integration + security

> **Automated in CI.** `phase-verify.yml` → V6.1 through V6.4 on
> every push/PR.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V6.1 | `verify_phase03.py --fast` exits 0 on Ubuntu CI.                            | `phase-verify.yml` matrix entry `03`.                   |
| V6.2 | `phase-verify.yml` matrix includes `03`.                                    | `phase-verify.yml --fast` static check 48.              |
| V6.3 | All 49 static checks in `verify_phase03.py` pass.                           | `phase-verify.yml --fast` records pass only when zero static failures. |
| V6.4 | `verify_phase03.py --security` exits 0 (secret/PII scan + SAST + dependency audits clean). | `phase-verify.yml` runs `--security` on every push/PR. |

---

## Summary Table

| Step | Scope                                     | Model          | Platform     | Reasoning dial | Thinking | Conv |
| ---- | ----------------------------------------- | -------------- | ------------ | -------------- | -------- | ---- |
| 1    | Registry, analytic frame, methodology     | Fable 5.1      | Claude Code  | Effort Max     | On       | New  |
| 2    | Snapshot, engine, compute/verify, golden  | Claude Opus 5  | Claude Code  | Effort Max     | On       | New  |
| 3    | Provenance trace, metrics API, corrections | Claude Opus 5 | Claude Code  | Effort Max     | On       | New  |
| 4    | Judge panels, compare, methodology, coverage | Claude Opus 5 | Claude Code | Effort Max     | On       | New  |
| 5    | Corrections form, pages, bootstrap, walkthrough | Claude Opus 5 | Claude Code | Effort Max  | On       | New  |
| 6    | QA + verify_phase03.py                    | Claude Opus 5  | Claude Code  | Effort Max     | On       | New  |
| V1   | Registry and frame scope                  | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   |
| V2   | Engine scope                              | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   |
| V3   | API scope                                 | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   |
| V4   | Pages scope                               | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   |
| V5   | Corrections, bootstrap, walkthrough scope | CI: phase-verify.yml, ci.yml | -- | --          | --       | --   |
| V6   | CI integration                            | CI: phase-verify.yml | --   | --             | --       | --   |

Backups (same platform rules, different provider): GPT-5.6 Sol on
Codex at Intelligence Extra High for Step 1; GPT-5.3 Codex on Codex at
Intelligence High for Steps 2 through 6. Both are funded by the ChatGPT
Plus subscription, whose caps are modest, so they are fallbacks for a
Claude Code outage rather than parallel capacity.

---

## Model selection blocks

**Selection method.** Each block below was produced by running the
selector in `planning/model-selector.txt` (catalog exported by roadmodel
0.2.35; re-exported with `uv run poe kit` on 2026-09-18 at the start of
this phase — the export changed only the Claude Code changelog notes on
the `claude-code` access method; no model entry, tier, price, or
availability changed since the Phase 2 export) against
`planning/user-context.md`, in this order: Step 0a dropped no models
(the cold-start availability list is empty and no runtime override was
supplied); Step 0b dropped every `cn`-jurisdiction model (Kimi,
DeepSeek, GLM) under the allowed list `us, eu, uk, ca, au, jp, kr`;
Steps 1–4 classified each step and ranked survivors by PRIMARY then
SECONDARY tier; within the tied frontier set, a superseded model yields
to its successor in the same series (Opus 5 over Opus 4.8 and 4.7;
Fable 5.1 over Fable 5) as the catalog's `best-for` rows direct; between
the tied Claude and GPT frontier models, the operator context breaks the
tie on subscription-utilization economics rather than list price —
Claude picks run at zero marginal cost on the 20x claude.ai Max plan,
while GPT picks would draw on ChatGPT Plus caps the operator declares
modest and reserves for fallback — so the GPT model becomes the required
cross-provider BACKUP (Step 7); under the operator's `balanced` posture
Fable 5.1 is reserved for the one ceiling-class step (Step 1, matching
the parent roadmap's §8 assignment of Fable to "index events, exposure,
and censoring design") and Opus 5 takes the rest, because Fable draws
the Max budget down at about twice Opus's rate for the same output.
Access selection Step A00 excluded `cursor` and `xai-api` per the
operator's list; Step C ranked `claude-code` first as
subscription-funded; Step E applied the flat-funding gate (open for
Claude on Claude Code), raising Effort to `Max` with Thinking `On`; Step
E2 emitted `ORCHESTRATION: None` because no Phase 3 step warrants
Ultracode under the balanced posture (each is a single scoped
deliverable, not a codebase-wide audit); Step F emitted no MAX MODE line
(Claude Code has no such dial).

```text
PROMPT: Step 1 — Metric Registry, Analytic Frame, and Generated Methodology
MODEL: Fable 5.1
BACKUP: GPT-5.6 Sol
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: coding with novel statistical-frame design — index events, exposure deferral, right-censoring, and a product-limit estimator that the engine, the truth generator, and the methodology page must implement identically — secondary planning. PICK: Fable 5.1 is S-tier in coding and S-tier in planning (HLE 59.1% and Terminal-Bench 2.1 91.4 at max) and supersedes Fable 5; reserved for this ceiling-class step under the balanced posture. EFFORT: Max effort with thinking on because the step meets the novel-problem-solving and cross-file chain-of-thought conditions and the flat-funding gate is open; orchestration None because one package, one migration, and one document is a single scoped deliverable.

PROMPT: Step 2 — Snapshot, Computation Engine, and Golden Metric Tests
MODEL: Claude Opus 5
BACKUP: GPT-5.3 Codex
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: correctness-sensitive multi-file coding against a fixed contract with a Parquet export, a transaction-bound publisher, a pipeline hook, and an exact golden reproduction, secondary agentic. PICK: Claude Opus 5 is S-tier in coding and S-tier in agentic (Terminal-Bench 2.1 89.1) and supersedes Opus 4.8. EFFORT: Max effort with thinking on because byte-for-byte reproducibility and the chain-completeness refusal are what every published number depends on and effort costs nothing under the open flat-funding gate; orchestration None.

PROMPT: Step 3 — Provenance Trace, Metrics API, and Corrections Intake
MODEL: Claude Opus 5
BACKUP: GPT-5.3 Codex
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: multi-file API coding against fixed conventions with a security-sensitive write path, a migration, and contract tests, secondary agentic. PICK: Claude Opus 5 is S-tier in coding and S-tier in agentic (Terminal-Bench 2.1 89.1) and supersedes Opus 4.8. EFFORT: Max effort with thinking on because the routes, budgets, the INSERT-only grant, and the public contract are cross-cutting and effort is free under the open gate; orchestration None.

PROMPT: Step 4 — Judge Metric Panels, Compare, Methodology, and Coverage
MODEL: Claude Opus 5
BACKUP: GPT-5.3 Codex
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: multi-file TypeScript and React coding against fixed web conventions with a mechanically enforced presentation contract, secondary agentic. PICK: Claude Opus 5 is S-tier in coding and S-tier in agentic (Terminal-Bench 2.1 89.1), A-tier in multimodal for page screenshots, and supersedes Opus 4.8. EFFORT: Max effort with thinking on because the components, pages, cache, and Playwright flow are cross-cutting and effort is free under the open gate; orchestration None.

PROMPT: Step 5 — Corrections Form, Remaining Pages, bootstrap, and Walkthrough
MODEL: Claude Opus 5
BACKUP: GPT-5.3 Codex
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: multi-file TypeScript, CI, and task-runner coding reusing fixed components with long end-to-end loops, secondary agentic. PICK: Claude Opus 5 is S-tier in coding and S-tier in agentic (Terminal-Bench 2.1 89.1) and supersedes Opus 4.8. EFFORT: Max effort with thinking on because the walkthrough is the phase's exit test and effort is free under the open gate; orchestration None.

PROMPT: Step 6 — QA + verify_phase03.py
MODEL: Claude Opus 5
BACKUP: GPT-5.3 Codex
PLATFORM: Claude Code
EFFORT: Max
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: mechanical translation of the Steps 1–5 deliverables into numbered static checks, mode dispatch, probes, and a CI matrix entry. PICK: Claude Opus 5 is S-tier in coding (Terminal-Bench 2.1 89.1); the open flat-funding gate suspends tier-down for routine work, so the funded frontier model takes it at zero marginal cost. EFFORT: Max effort with thinking on because effort is free here and this script gates every later phase's CI and drives the milestone probe; orchestration None.
```

---

## Not in scope (from product roadmap)

Per [`ROADMAP.md`](../ROADMAP.md) Phase 3, Phase 4, and §6 "Out of
Scope":

- The expected-outcome model, expected counts, observed/expected ratios,
  bootstrap intervals, partial pooling, and every adjusted statistic;
  Phase 4 fills the `expected_count`, `expected_rate`,
  `standardized_ratio`, and interval columns this phase leaves null and
  publishes methodology version `1.0`.
- Planted case-mix confounding and per-judge effects in the generator;
  Phase 4 adds them under a new `TRUTH_VERSION`.
- Real case data of any kind and per-source suppression thresholds
  chosen against real cohorts; Phase 5 (Cook County) revisits the
  registry's thresholds with a version bump.
- Administrative authentication, a corrections reader, correction
  handling and status changes, and the suppression and takedown
  mechanics; Phase 6. The intake stores an encrypted contact that
  nothing in Phase 3 decrypts.
- Any composite, ideological, partisan, or "best/worst judge" score; the
  compare page ranks by one objective metric with its sample size and
  interval and never aggregates across metrics.
- The person timeline page (`/subjects/[publicKey]`); internal/admin-only
  per the brief, Phase 6.
- Deployment beyond the maintainer's machine, bucket-versioned or
  object-store snapshots, a scheduled `metrics verify` run, and edge rate
  limits; Phase 8.

Additionally not in scope for this phase:

- Modelling a person's incarceration terms from other cases when
  deferring time at risk; Phase 3 defers by the index case's own
  sentence only, states the limitation in `docs/METHODOLOGY.md`, and
  Phase 4's feature specification revisits it.
- `release_violation` and `rearrest` observations for the synthetic
  source; the generator records no such events, the registry marks them
  not observable per source, and a real source that documents them
  (Phase 5 or 7) is the first to publish them.
- Calendar-period cohorts (temporal controls beyond "same source
  coverage window"); Phase 4's model carries the calendar period as a
  feature and the compare page gains a period filter then.
- Envelope or asymmetric encryption of correction contacts so the API
  process holds no decrypting key; an architectural question for Phase
  6, when the admin reader that needs the private key arrives.
- Reading the parent case from the database for the case-level
  data-quality checks (Phase 2 carry-over item 6); the first step that
  ships a child-only export is Phase 5's Cook County connector.
- Unmerge behind administrative authentication, `er review decide`
  authentication, and the probabilistic scorer (Phase 2 carry-over items
  3–5); Phases 6 and 7.
- A runtime-configurable API origin for the web image (Phase 1 finding
  5.1) and ESLint 10 in `web/` (Phase 1 finding 5.2); Phase 8 and the
  `eslint-plugin-react` release respectively.
- Server-side rendering caches for stable metric responses beyond the
  banner's coverage read; ROADMAP §5 "Performance rules" reserves them
  for measured expensive queries, none of which exist at demo scale.
- A cohort filter on `/judges/{id}/cases` for the metric panels' case
  drill-down (pretrial decision, disposition, sentence): the route
  filters on filing dates, `status`, and `case_type` only, so Step 4's
  "View eligible cases" links carry `status=closed` on the Disposition
  and Sentencing panels and are unfiltered elsewhere; a per-cohort
  filter needs a cases-route parameter and lands with the first real
  case-level source (Phase 5), when the eligible cohort is worth
  inspecting at scale.
- A court search on `/compare`: the chooser lists two `/courts` pages
  (164 courts today); a `q` filter on `/courts` arrives with the Phase 5
  registries.

---

_This roadmap is the execution plan for Phase 3. Update step status as
each is completed. After all steps and verification pass, and every
finding has a destination, Phase 3 is complete — declared with the line
"Phase 3 is complete. You can now move on to Phase 4." and nothing after
it — and Phase 4 (Risk Adjustment and Statistical Validation) inherits
the versioned registry and its methodology changelog, the analytic frame
its expected-outcome model is fitted over, the hashed snapshots its model
artifacts are pinned to, the observation columns reserved for expected
counts, ratios, and intervals, the golden metric suite as the regression
harness every adjusted statistic is tested beside, and the judge and
compare pages its risk-adjusted panels extend._
