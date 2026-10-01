<!-- docs/roadmap/phase04-roadmap.md -->
# Phase 4 Roadmap — Risk Adjustment and Statistical Validation

**Status:** In progress

## Overview

Phase 4 opens the gate to adjusted comparison: it turns the descriptive registry
of Phase 3 into observed-versus-expected measures for comparable cohorts, proves
on synthetic data with a known answer that the adjustment recovers what was
planted, and publishes the validation before any adjusted number reaches a judge
page. The synthetic generator gains planted case-mix confounding and known
per-judge effects, recorded in a new truth file with the oracle expected counts
per judge, target, and window; a versioned expected-outcome specification and an
interpretable regularized logistic model turn the analytic frame into expected
probabilities; expected counts, observed/expected ratios, hierarchical partial
pooling, and bootstrap intervals become a new kind of metric observation,
reproducible from a named snapshot and a pinned seed; `docs/VALIDATION.md`
reports calibration, Brier score, ROC AUC, feature stability, missing-data
sensitivity, bootstrap stability, recovery of the planted effects, and subgroup
calibration over synthetic restricted attributes in aggregate only; methodology
version `1.0` is published with its changelog; and the judge and compare pages
gain risk-adjusted panels that always show the interval, the cohort definition,
the model, and the methodology version. Phase 4 covers the expected-outcome
model, O/E, and uncertainty portion of the brief's development phase 5 and the
calibration portion of phase 10.

Phase 4 does NOT ingest any real case data or choose thresholds against real
cohorts (Phase 5); it does NOT use a restricted attribute — the age band
included — as a model feature, publish any restricted attribute outside the
aggregate validation tables, or build a composite, ideological, partisan, or
"best/worst judge" score; it does NOT ship administrative authentication or the
validation of the model on real data (Phase 6); and it does NOT deploy anything
beyond the maintainer's machine and the repository's CI (Phase 8). Every
adjusted figure it publishes is labelled synthetic, framed as a comparison with
a model's expectation rather than a causal effect, and accompanied by the raw
descriptive rate it adjusts.

The phase lands in 6 layers:

1. **Planted effects, synthetic restricted attributes, and the restricted
   schema** — `GENERATOR_VERSION` `3`: risk-dependent judge assignment on
   observable case features (planted case-mix confounding), per-judge
   release-leniency, new-case, and failure-to-appear effects on the generator's
   own probability scale, an age effect that the model is forbidden to use (the
   positive control for subgroup calibration), an abstract `synthetic_group`
   attribute independent of every draw (the negative control), and the age at
   filing withheld when the date of birth is unknown; `TRUTH_VERSION` `3` with
   `truth/effects.json` (the planted parameters and, per judge, target, and
   window, the cohort, the observed count, and the oracle expected counts with
   and without the judge's effect); exposure deferred by every incarceration
   term of the person (Phase 3 finding 1.4, carry-over item 1) in
   `metrics/exposure.py` and `synthetic/truth.py` identically, methodology
   `0.2`; migration `0008_restricted_schema` (the PostgreSQL schema
   `restricted`, `restricted.party_attribute`, grants that give the app role no
   `USAGE`, Alembic `include_schemas`, and `case_party.source_row_id` rewritten
   to a within-case ordinal so no plaintext participant id sits in a canonical
   column); the connector publishing `age_band` and `synthetic_group` into the
   restricted schema; the golden fixture regenerated; and `verify_phase03.py`
   check 14 comparing the manifest with the source constants instead of the
   literal `"2"`.
2. **Feature specification, leakage review, and the baseline model** —
   `data/reference/outcome_model.yaml` (version `1`: the targets, every feature
   with its known-at rule and its leakage justification, the explicit
   exclusions, the missing-data rule, the L2 penalty, the temporal split, the
   seed, the bootstrap size, the pooling bounds, the thresholds, and the
   recovery tolerance); the `judgemetrics.metrics.adjustment` package
   (`spec.py`, `features.py` over the frame, every history feature evaluated
   strictly before the index case's filing and every order taken from
   source-assigned keys, `logistic.py` penalized iteratively reweighted least
   squares in NumPy, `diagnostics.py` temporal-split calibration, Brier score,
   ROC AUC, and feature stability, `resample.py` person-cluster bootstrap
   replicates from seeded streams, `fit.py` the published, temporal-split, and
   replicate fits over an in-memory frame or a snapshot, `artifacts.py`
   canonical JSON artifacts written once under the snapshot directory);
   migration `0009_outcome_models` (`outcome_model`); `judgemetrics models
   fit|list|show|verify`; `numpy` as the one new runtime dependency; leakage and
   order-invariance property tests; and the artifact inspection test (no
   person-level row in any artifact).
3. **Expected counts, observed/expected ratios, partial pooling, bootstrap
   intervals, and the recovery test** — registry version `2` with three
   `observed_expected` metrics (`pretrial_release_observed_expected`,
   `new_case_observed_expected`, `failure_to_appear_observed_expected`),
   methodology `0.3`; `expected.py` (expected count as the sum of predicted
   probabilities), `pooling.py` (gamma–Poisson empirical-Bayes partial pooling
   with the between-judge shape fitted by maximum marginal likelihood),
   `bootstrap.py` (each person-cluster replicate's observed and expected counts
   under the replicate model Step 2 refitted, its re-estimated pooling shape,
   and its pooled ratio, giving the percentile interval); migration
   `0010_adjusted_observations` (`outcome_model_id`, `pooling_weight`,
   `suppression_reason` on `metric_observation`); compute, publish, verify, and
   provenance for the new kind; pipeline step 13 leaving adjusted observations
   to the full `metrics compute`, with publishing scoped to the kinds a run
   computes; the adjusted kind held out of every public metrics response until
   Step 5; the models on `/api/v1/ready`; and
   `tests/golden/test_golden_adjusted.py` plus
   `tests/golden/test_golden_recovery.py`, the permanent proof that the planted
   judge ranking is recovered within the documented tolerance.
4. **Validation report and methodology `1.0`** — the `judgemetrics.validation`
   package (the report, the fairness analysis — the only reader of the
   restricted schema, as the ingest role, aggregate cells only with small-cell
   suppression — the missing-data sensitivity, the bootstrap stability summary,
   and the recovery section against `truth/effects.json`), `judgemetrics
   validation report [--out] [--check]` and `validation recovery`, the committed
   and generated `docs/VALIDATION.md` for the demo seed (checked in the `e2e` CI
   job), methodology `1.0` with its changelog, the "Adjusted statistics" section
   of `docs/METHODOLOGY.md` rendered from the registry and the specification,
   and the same prose served by `GET /api/v1/metrics`.
5. **Risk-adjusted panels, the adjusted compare, and the model card** — the
   adjusted kind served: `Observation` gains the expected count and rate, the
   pooled ratio with its interval, the pooling weight, the model, and the
   suppression reason (`interval_method` `bootstrap`), `SuppressibleFigures`
   withholds them all, `GET /api/v1/models/{model_id}` returns the model card,
   the provenance endpoint names the model, and `/metrics/compare` sorts by
   `ratio`; the web `AdjustedStat` component, the judge page's "Risk-adjusted
   comparison" panel with the comparison-cohort selector and the cohort
   definition, adjusted measures on `/compare`, `/models/[modelId]`, and the
   methodology page's adjustment section; Vitest presentation-rule tests and
   `web/tests/e2e/adjusted.spec.ts`.
6. **QA + `verify_phase04.py`** — verification script (`--fast`, `--py`,
   `--node`, `--e2e`, `--security`, `--all`, `--post`),
   `docs/phase04-qa-findings.md` rollup with the alarm exercise and the Phase 5
   carry-over checklist, the `phase-verify.yml` matrix entry `04` with its
   required context, the status update in `docs/ROADMAP.md`, and the tag
   `v0.4.0-phase-4`.

The ship test for Phase 4 is straightforward: `metrics compute` on the demo seed
fits every expected-outcome model from the snapshot it exports and a pinned
seed, and a second run on the same snapshot fits, computes, and publishes
nothing; `models verify --refit` reproduces every model artifact byte for byte
and `metrics verify` reproduces every descriptive and adjusted observation; the
planted judge ranking is recovered within the tolerance
`data/reference/outcome_model.yaml` documents, while the raw rates rank the same
judges measurably worse; `docs/VALIDATION.md` equals its render from the demo
seed and reports calibration, Brier score, ROC AUC, feature stability,
missing-data sensitivity, bootstrap stability, recovery, and subgroup
calibration over the synthetic restricted attributes in aggregate only;
methodology `1.0` is published with its changelog and the brief's eight warnings
unchanged; every adjusted statistic on the web shows observed, expected, the
ratio, its interval, the cohort definition, the model, and the methodology
version, and a suppressed subject shows the reason; no model artifact, API
response, log line, or page carries a person-level row or a restricted
attribute; `uv run python scripts/verify_phase04.py --fast` and `--security`
exit 0 on Ubuntu CI under the `phase-verify.yml` matrix entry `04`; and the
security gate is clean.

**Pre-requisite:** Phase 3 closed (tag `v0.3.0-phase-3`, 2026-09-29): its
registry and methodology changelog are what the adjusted metrics join, its
analytic frame (index events, exposure, censoring, followed cohorts) is what the
expected-outcome model is fitted over, its hashed snapshots are what model
artifacts are pinned to, its `metric_observation` columns `expected_count`,
`expected_rate`, and `standardized_ratio` are the reserved homes of the adjusted
figures, its `metrics verify` and provenance trace are what adjusted
observations must pass, and its judge, compare, and methodology pages are what
the adjusted panels extend. Phases 1 and 2 closed earlier (the canonical schema,
the role split, the synthetic generator with truth, and entity resolution the
person-level features are counted over).

**Dependency:** Phase 5 (First Real State-Court Pipeline and the Florida
Acquisition Plan) does not start until Phase 4's V-checks are green; it inherits
the `restricted` schema and `restricted.party_attribute` (Cook County's race,
gender, and age land there, §5.2), the expected-outcome specification and its
versioning (refitted on real data under a specification bump), the
order-invariant feature builder, the validation report generator it re-runs on
real data (and Phase 6 §6.1 audits), and the adjusted panels its real metrics
appear in.

**Design rationale (two-stage adjustment with partial pooling).** The brief asks
for an interpretable regularized or hierarchical logistic model before anything
more complex, for expected counts as the sum of predicted probabilities, and for
partial pooling because small judges otherwise produce unstable extremes. Phase
4 takes the two-stage form used for provider profiling: one expected-outcome
model per target and window, fitted over every eligible index event of the
source with no judge term (so a judge's expected count is what the model expects
for that judge's docket), then gamma–Poisson empirical-Bayes pooling of each
judge's observed count against the expected count, which shrinks a judge's ratio
toward 1 by the weight `E / (E + α)` and handles a judge with no events without
a continuity correction. The published interval is a person-cluster bootstrap
that refits the model and re-estimates the pooling shape on every replicate, so
it carries model, pooling, and sampling uncertainty together, and the same
replicates feed the validation report's stability section. NumPy is the only
numeric dependency: a penalized Newton solver is thirty readable lines, is
checked against its own optimality conditions, and keeps every step inspectable,
where scikit-learn or statsmodels would add a large audit surface for one
estimator.

**Design rationale (adjusted observations are their own kind, computed whole,
served last).** An adjusted figure depends on a model and a pooling shape fitted
over every subject, so it cannot be recomputed for the few subjects an ingest
touched without mixing models on one compare page. Adjusted figures therefore
live in their own observations of kind `observed_expected`, computed only by the
full `metrics compute` (pipeline step 13 leaves them alone and they keep citing
the snapshot and model they came from), with the brief's formula mapped onto the
reserved columns. The web places any registry metric by its `index_event`, and
the API's kind literal does not know the new kind, so Step 3 holds the kind out
of every public metrics response and Step 5 serves it with its presentation;
that ordering is also what makes the parent roadmap's rule — validation
documented before any adjusted statistic appears on a judge page — mechanical
rather than a promise.

**Design rationale (restricted attributes are controls, never features).** The
brief lists the age band as a candidate feature "when lawfully and reliably
available", but the root roadmap classifies it as a restricted demographic
attribute (§5.2), and restricted attributes are never model features by default
(AGENTS.md; the brief's sensitive-variable rule demands a documented purpose,
legal review, fairness analysis, and publication rationale first). Phase 4 keeps
it out of the model and uses it for what the restricted schema is for: the
synthetic world plants an age effect on later outcomes, so the subgroup
calibration by age band has a known direction of miscalibration to detect, while
`synthetic_group` is independent of every draw and must come back calibrated.
Neither attribute feeds judge assignment, so both leave the judge comparison
unbiased on synthetic data; the report states that real data guarantees neither,
which is why the analysis is repeated on real data in Phase 6.

**Design rationale (order invariance).** Canonical ids are database-generated
UUIDs, so any computation that iterates in id order gives different
floating-point sums and different bootstrap draws in two databases holding the
same source. Every order-dependent step in Phase 4 sorts by source-assigned keys
instead (a person by the earliest `source_row_id` among the person's charges, an
index event by its time and its case's earliest charge `source_row_id`), and a
property test relabels every UUID and requires identical artifacts and figures.
The same dataset therefore yields the same models, the same adjusted figures,
and the same `docs/VALIDATION.md` on the maintainer's machine and in CI, which
is what lets CI check the committed report.

**Branch strategy.** Every step in this phase lands on its own short-lived
feature branch (`feature/phase04-stepM-<slug>`), opens a pull request against
`main`, waits for the project's CI workflow to go green, and squash-merges with
a Conventional Commits subject line. Direct pushes to `main` are blocked by
branch protection. See the parent project's ROADMAP "Branch management strategy"
section for the canonical naming convention, PR rules, and release tagging —
this paragraph confirms those rules apply unchanged within this phase. Per-step
branches are listed on each step header below as `**Branch:**` so reviewers can
map commits 1:1 to the step they implement.

**Branch-first execution rule.** The very first action of every step — before
reading any files, before running any tool, before drafting any change — is to
check out the branch named in that step's `**Branch:**` line:

```sh
git checkout -b feature/phase04-stepM-<slug>
```

This is non-negotiable. `main` is protected with `enforce_admins: true`, so a
commit on `main` cannot be pushed and must be rewound or rebased onto the
feature branch before the PR can open — an avoidable round-trip. If you discover
mid-step that you started on `main`, recover by running the same `git checkout
-b` command immediately (uncommitted changes carry over to the new branch), then
continue. AI coding agents executing a step from this roadmap must treat the
branch checkout as Step 0 of every step.

**Worktree rule.** One working tree, one step in flight — the lifecycle below
assumes the primary checkout. A second working tree is created only with `git
worktree add`, and only for the three cases the parent ROADMAP "Worktree
strategy" sanctions: a `hotfix/` branch interrupting this step (cut from
`origin/main` in its own worktree so this step's tree is untouched); steps the
Execution Order below explicitly draws in parallel (each in its own worktree AND
its own conversation); and worktree-isolated subagents inside a step (throwaway
trees that merge back into the step branch locally and are removed before the PR
opens). In those cases Stage 1 becomes `git fetch origin && git worktree add -b
feature/phase04-stepM-<slug> .worktrees/<slug> origin/main`, the worktree is
bootstrapped before any test or build (`uv sync`, `pnpm install` in `web/`,
`.env` copied — a worktree has none of the primary tree's untracked state, and
it must never borrow the primary tree's editable install), the Stage 4 merge
runs from the primary tree, and Stage 5 removes the worktree BEFORE pruning the
branch. Undeclared parallelism is a lifecycle violation, not a shortcut.
Worktree location for this project: git-ignored `.worktrees/<slug>/` inside the
repository, matching the parent ROADMAP.

**Security-first execution rule.** Security is not a phase — it is a gate on
every commit of every step. Before each `git commit`, the step's work must pass
the local, fail-closed security gate: secret/PII scan clean, SAST clean,
dependency audit clean, and a diff review confirming no sensitive data (PII,
credentials, tokens) and no new insecure pattern (injection, weak crypto,
over-broad scope, secret in a client bundle or log line). This gate is wired
into the pre-commit hook and re-run in CI, so a security issue introduced while
implementing a step is caught during development — before it reaches the branch,
the PR, or `main`. See the parent project's ROADMAP "Security & privacy
strategy" → "Per-step security gate" for the canonical checks and tooling; each
step's XML `<task>` carries a `<security>` block restating them for the agent,
and each step's Acceptance Criteria ends with a security check. AI coding agents
executing a step MUST treat the security gate as part of the step's definition
of done, exactly like its tests. This matters most in this phase because Step 1
creates the first PostgreSQL schema whose whole purpose is to hold sensitive
attributes, Step 2 adds the first numeric dependency and the first artifacts
written beside the snapshots, and Step 4 adds the first code path that reads
restricted attributes: the operator running a step's prompt must not be able to
introduce a data-exposure risk that only surfaces after merge.

**Deploy-and-verify rule.** Merged is not deployed, and deployed is not
released. Every step header carries a `**Deploys:**` line naming the surface and
environment the step's merge reaches — or `nothing beyond merge` — and when
going live needs a release, a version-floor bump, a migration, or a redeploy,
the line says so and this step (or a named follow-on step) owns that event.
Through Phase 7 the only environment is the maintainer's machine, so in this
phase "deployed" means the merged commit runs under `uv run poe up` with
migrations applied; a step whose Deploys line names that surface carries a
**Deployed & verified** bullet (the local `/api/v1/ready` reports the migration
head the step introduced, and the changed behaviour is exercised locally via the
hands-off recipe the step names), and that bullet must be green before the step
is declared complete. No step in this phase introduces a required environment
variable; Step 2 introduces a required runtime dependency (`numpy`), which is
proven by `uv sync` and an import in the container smoke test, never by listing
packages. See the parent ROADMAP "Release & deployment strategy" for the
surfaces table, promotion path, staged-rollout rule, migrations, and rollback.

**Triage rule.** Findings surfaced while executing a step are classified before
they are acted on, per the parent ROADMAP "Defect handling & triage": spec rot →
edit this roadmap's affected `<task>` block now; upstream gap → patch the
earlier step's prompt and add it to the carry-over checklist; implementation bug
→ fix in-step only if it blocks this step's acceptance criteria, otherwise an
issue and its own branch in a fresh conversation; architectural question → an
issue for a future phase; process improvement → recorded where the next
conversation will read it; security finding → jumps the queue by severity;
data-semantics finding (a metric definition, a feature, an attribution rule, or
a source value was misread) → edit the versioned registry or specification
entry, bump its version, and re-run `metrics verify`; data-access question →
`docs/ROADMAP.md` "Unresolved data-access questions", never an invented answer.
A step's PR contains the step plus blocking fixes only, and lists the issues it
opened. When a merged PR auto-closes an issue, the environment check is what
earns the close — reopen or follow up if a gap remains.
`docs/phase04-qa-findings.md` is the rollup: every finding, its class, and the
guard added so the class cannot recur. Phase 3's carry-over checklist
(`docs/phase03-qa-findings.md`, last section) is folded into this roadmap as
follows: item 1 (methodology `1.0` with the exposure limitation revisited) →
Steps 1 and 4; item 2 (fill the expected count, expected rate, ratio, and
adjusted interval) → Step 3; item 3 (planted judge effects under a new
`TRUTH_VERSION`) → Step 1; item 10 (`verify_phase04.py`, subset assertions) →
Step 6; items 4, 7, and 9 → Phase 5, items 5 and 8 → Phases 6 and 7, items 6 and
11 → Phase 8, all listed under Not in scope. Phase 3's Not-in-scope items owned
by this phase land here too: the exposure limitation → Step 1; the calendar
period as a model feature → Step 2 (the compare page's calendar-period filter
moves to Phase 5, see Not in scope). One finding was made while surveying the
code for this roadmap and is owned by Step 1: the synthetic connector stores the
normalized participant id in `case_party.source_row_id`, a canonical column the
app role can read, contradicting `docs/ARCHITECTURE.md` "Person hashing and
resolution" (no route serves it; latent until a real source's identifiers arrive
in Phase 5).

**Status rule.** Every step carries a `**Status:**` line directly under its `##
Step N — …` heading, before the Goal, and this file on `main` is the ledger of
what is done — never a chat transcript, never a later conversation
reconstructing history from `git log`. The line reads `Not started` when this
roadmap is written and is flipped by the step's OWN pull request: at Stage 3,
right after `gh pr create` returns the PR number, the agent sets it to `Complete
— PR #<n> (<YYYY-MM-DD>)`, appends ` ✅` to the step's heading (`## Step 3 —
Expected Counts, Ratios, Partial Pooling, and the Recovery Test ✅`) so the
completion shows in the rendered preview, the outline, and the table of
contents, sets the step's Summary Table Status cell to `Complete — PR #<n>`,
commits that edit on the step branch, and pushes. The PR therefore carries its
own completion mark, and the roadmap on `main` says a step is complete exactly
when that step's PR merges — never before. This file's phase-level `**Status:**`
line (under the title) and the parent project roadmap are marked the same way,
in the same commit: Step 1's PR flips both from `Not started` to `In progress`
(the parent's `### Phase 4` line reads `In progress — phase04-roadmap.md`), and
the final step's PR flips both to `Complete — …` (the parent's with its row in
the "Phase Complexity Summary" table and the header `> **Status:**` line) and
appends ` ✅` to this file's `# ` title and to the parent's `### Phase 4`
heading, so the project roadmap shows a finished phase the way this file shows a
finished step. There is no separate "update the roadmaps" chore: a step whose PR
merged without its Status line is a lifecycle violation, and the next step's
Stage 1 (and `/roadmap-step`) refuses to start until the previous step reads
`Complete`. If a post-merge check fails — a Deployed & verified bullet, an alarm
that never fired — the step is NOT complete despite the merged line; say so, and
the `hotfix/` PR that completes it appends its own number to the line. `grep -n
'^\*\*Status:\*\*'` on this file is the phase's progress report, and the ✅
headings are the same report at a glance.

**Step lifecycle.** Every step in this phase follows the exact same six-stage
lifecycle, in order, with no exceptions. Each stage is a hard checkpoint — if a
stage is skipped, branch protection or the next step's Stage 1 will fail loudly,
and that is the safety net. AI coding agents MUST execute all six stages before
declaring a step complete.

1. **Create the branch.** Before any Read / Edit / Bash, run `git checkout -b
   feature/phase04-stepM-<slug>` from a clean, up-to-date `main`. The exact
   branch name comes from this step's `**Branch:**` line. When the Worktree rule
   applies, the equivalent is `git fetch origin && git worktree add -b <branch>
   .worktrees/<slug> origin/main`, followed by the worktree's bootstrap.

2. **Work on the branch, passing the security gate before every commit.** All
   commits land here. Never push to `main` directly — branch protection
   (`enforce_admins: true`) rejects it. Before each `git commit`, run the local
   security gate (secret/PII scan, SAST, dependency audit, sensitive-data diff
   review — see the step's `<security>` block and the parent ROADMAP "Per-step
   security gate"). It is fail-closed: a finding blocks the commit, so a
   security issue in this step's work is caught here, before the PR and before
   `main`. Stop the local API before `uv run poe gate` or `git commit` (a
   running uvicorn child holds the editable install open on Windows).

3. **Open the PR, then mark the step.** `gh pr create --base main --head
   <branch>` with a Conventional Commits title and a body that references this
   roadmap step and its acceptance criteria. One PR per step; never bundle two
   steps into one PR. Then, with the PR number in hand, set this step's
   `**Status:**` line (directly under its heading) to `Complete — PR #<n>
   (<YYYY-MM-DD>)`, append ` ✅` to the step's `## Step` heading, set its Summary
   Table Status cell to `Complete — PR #<n>`, commit that edit on the step
   branch (`docs: mark Phase 4 Step M complete`), and push — the PR now carries
   its own completion mark, so the roadmap on `main` will say the step is
   complete exactly when the PR merges (Status rule). On the phase's first step,
   the same commit sets this roadmap's phase-level `**Status:**` (under its
   title) and the parent project roadmap's Phase 4 `**Status:**` to `In
   progress`; on the final step, both to `Complete`, with ` ✅` appended to this
   roadmap's `# ` title and to the parent's `### Phase 4` heading.

4. **Wait for green checks, then squash-merge.** Every required status check
   (`test`, the aggregate of `python`, `security`, `container`, `web`, and
   `e2e`; `phase-verify (01)`; `phase-verify (02)`; `phase-verify (03)`; and,
   from Step 6, `phase-verify (04)`) must report success. If the PR goes BEHIND
   main while waiting, refresh with `gh pr update-branch --rebase` — never merge
   `main` into the branch; `required_linear_history: true` enforces rebase. Once
   every check is green:

   ```sh
   gh pr merge <PR_NUMBER> --squash --delete-branch
   ```

   If this step's `**Deploys:**` line names a surface, the merge is not the
   finish line: run the Deployed & verified check from the acceptance criteria
   against the local environment now (see the Deploy-and-verify rule) before
   declaring the step complete.

5. **Retire the branch (remote + local).** The `--delete-branch` flag plus the
   repo's `delete_branch_on_merge: true` setting retire the remote
   automatically. Sync local state and prune the merged branch plus any other
   `[gone]` labels left over from prior PRs:

   ```sh
   git switch main
   git pull --ff-only origin main
   git fetch --prune origin
   git branch -vv | grep ': gone]' | awk '{print $1}' \
     | xargs -r git branch -D
   ```

   If this step ran in its own worktree, remove it FIRST — `git worktree remove
   <worktree-path>`, then `git worktree prune` — because `git branch -D` refuses
   a branch still checked out in a worktree. Confirm with `git branch -vv` that
   only `main` and any intentional long-lived branches remain locally, and with
   `git worktree list` that only the primary tree remains.

6. **Dispose of every finding, declare completion, then new conversation.**
   Before you declare anything, walk the findings this step surfaced and send
   each to its destination per the Triage rule above — a note that a later step
   needs is edited into that step's `<task>` block now; a wrong claim in this
   step's spec is fixed in this roadmap now; an implementation bug is fixed
   in-step or exists as an issue with a number; a judgement call you made in the
   diff is explained in the PR body; a process lesson is written where the next
   conversation reads it (`AGENTS.md` or this roadmap); a data-access question
   is a row in `docs/ROADMAP.md`. Update `docs/ROADMAP.md` (completed items,
   known issues, next milestones). A finding you can only *describe* has not
   been disposed of, and an undisposed finding is an unmet acceptance criterion.
   Only once the PR is merged — and `main` therefore carries this step's
   `Complete` Status line — every acceptance criterion is affirmatively met, and
   every finding has a destination, say so plainly: end your final response with
   an explicit, unhedged completion line — verbatim shape "Step M is complete.
   You can now move on to Step M+1." — so the operator has a clean stopping
   point at which to close this conversation. That line is the LAST line of the
   response. Nothing follows it: no "Follow-ups (non-blocking)", no "Notes", no
   "Next", no "worth a glance", no suggested improvements. If you want to show
   your work, a short ledger may PRECEDE the line, one entry per finding naming
   its destination (an issue number, a file you edited, the PR body) — never an
   open item. If any acceptance criterion is NOT met, or any finding has no
   destination yet, do the opposite — state plainly that the step is NOT
   complete, name what is outstanding, and do not emit the completion line.
   "Done" means done, not "done, but here is what you still have to do". Then,
   for phase-boundary hygiene, the operator closes this Claude Code session and
   opens a fresh one before starting Step M+1; the new conversation begins again
   at Stage 1 of this lifecycle, with the next step's `**Branch:**` line driving
   the `git checkout -b` command. No work straddles two steps.

---

## Current State (as of Phase 3)

### Synthetic generator and truth surface

- `judgemetrics.synthetic` is at `GENERATOR_VERSION` `2` (`synthetic/config.py`)
  and `TRUTH_VERSION` `2` (`synthetic/truth.py`). `build_dataset` runs
  `build_world` (courts, then `build_judges` on the `world` stream, then
  `build_persons` on the `persons` stream), `build_cases`
  (`allocate_case_counts`, then `generate_case` per person and ordinal on the
  `cases` and `events` streams), `assign_identifiers`, `plant_edge_cases` (the
  `edge_cases` stream), and the writers (nine `source/` CSVs, six `truth/`
  files, `manifest.json`). The streams are `STREAM_NAMES = ("world", "persons",
  "cases", "events", "edge_cases")`, each
  `random.Random(sha256(f"{seed}:{name}"))`, drawn only through the
  `random()`-based helpers in `rng.py` (`uniform`, `randint`, `chance`,
  `choice`, `weighted_choice`, `shuffled`, `sample`, `skewed_fraction(rng, k) =
  random() ** k`); `verify_phase02.py` check 3 forbids `datetime.now(`,
  `uuid4(`, `urandom(`, and module-level `random.*(` under `synthetic/`. Scales:
  `GOLDEN` 3 courts, 6 judges, 40 persons, 60 cases (2019–2021, seed 7); `DEMO`
  5 courts, 24 judges, 3,200 persons, 5,200 cases (2016–2023, seed `20260916`);
  `TINY` 2 courts, 3 judges, 12 persons, 16 cases (2020–2021).
- Judges already carry three latent tendencies drawn on the `world` stream —
  `release_bias` U(−0.15, 0.15), `dismissal_bias` U(−0.04, 0.06),
  `severity_bias` U(0.7, 1.3) — commented "Phase 4's planted effects" in
  `synthetic/model.py` and written to no truth file. Assignment is uniform among
  the judges serving the court on the day (`choice(rng,
  world.judges_serving(...))` in `cases.generate_case`), with a planned
  reassignment in 20% of cases, so there is no case-mix confounding today. The
  pretrial decision is statutory in 10% of cases
  (`legislature_or_mandatory_rule`, `mandatory`); otherwise recognizance is
  `clamp(BASE_RECOGNIZANCE[type] + release_bias)`, detention
  `clamp(BASE_DETENTION[type] − release_bias / 2)`, and a bond is posted with
  probability 0.75 — the only inputs are the case type and the judge. Failure to
  appear is `chance(0.05 + 0.12 · propensity)` on the first hearing at least 13
  days before the disposition; a later case is filed at least 14 days after the
  previous pretrial decision, at `skewed_fraction(1 + 2 · propensity)` of the
  remaining span; case counts are allocated by `0.2 + propensity` (at most four
  per person); revocation is `chance(0.06 + 0.20 · propensity)`. The latent
  `propensity = random() ** 2` is the only driver of later outcomes, and a
  person's prior case count is its observable proxy; no outcome depends on a
  judge.
- `Person` carries `date_of_birth`, `age_band` (drawn at the corpus start:
  `18-24`, `25-34`, `35-44`, `45-54`, `55+`), `propensity`, `home_court`, and
  `dob_known`. `source/participants.csv` carries the name, the date of birth
  (blank when `dob_known` is false), and `age_at_filing` (always filled today);
  the connector hashes the name and the date of birth and drops `age_at_filing`.
  No sex, race, ethnicity, or other demographic attribute is generated. Every
  person's first case has no prior history: the corpus has no pre-corpus
  records.
- `truth/` holds `persons.csv`, `subsequent_events.csv`,
  `resolution_expectations.csv`, `planted.csv`, `metrics.json` (per judge and
  court: eligible counts, the pretrial block, `index_events.<kind>.windows.<w>`
  with every rate and survival estimate, the dismissal rate, the disposition
  distribution, the medians; plus `corpus`, `windows_days`, `index_kinds`,
  `observable_outcomes`, `not_observable`, `definitions`), and `README.md`.
  Nothing in `truth/` states an expected outcome, a judge tendency, or a
  propensity. The golden manifest lists 15 files, and `.secrets.baseline` holds
  one detect-secrets entry per manifest digest;
  `tests/golden/test_golden_fixture.py` regenerates the fixture byte for byte
  and fails on a version bump without regeneration. A generator change that
  alters a decision shifts every later draw in its stream (draw counts depend on
  outcomes), so a Phase 4 generator change regenerates the whole fixture; the
  procedure is `docs/SYNTHETIC_DATA.md` "Regenerating the golden fixture" plus
  the scoped baseline refresh in `AGENTS.md`.
- `scripts/verify_phase03.py` check 14 requires `str(manifest.get(key)) == "2"`
  for `generator_version` and `truth_version`; because `phase-verify (03)` is a
  required context and `tests/unit/test_phase03_verification.py` counts 49
  passes, the first version bump fails two required checks unless the same PR
  relaxes the check (Phase 3 finding 6.1's subset pattern, one level down).
  `verify_phase02.py` checks only that the version names exist.

### Metrics engine and schema surface

- `judgemetrics.metrics` chains `registry` → `frame` → `attribution` →
  `index_events` → `exposure` → `windows` → `censoring` → `intervals` →
  `compute` (with `suppression`) → `publish` → `verify` → `provenance`, with
  `snapshot` building the frame, `methodology` rendering `docs/METHODOLOGY.md`,
  and `engine.compute_and_publish(session, settings, *, subjects=None,
  label=None, registry=None)` chaining them (the caller commits). There is no
  random draw anywhere under `metrics/`, and no module names `numpy`: the engine
  is Polars, DuckDB (the read-only SQL layer over the snapshot), and the
  standard library, and `uv.lock` holds no numpy, scipy, scikit-learn,
  statsmodels, pandas, or pyarrow.
- The registry (`data/reference/metric_registry.yaml`, `version` 1,
  `methodology_version` `"0.1"`, the brief's eight warnings as
  `known_limitations`, `suppression.default_threshold` 10) holds 33 metrics: 8
  `count`, 2 `share`, 15 `windowed_rate`, 3 `survival`, 1 `distribution`, 4
  `median`. `parse_metric` rejects an unknown field; the kinds, gates,
  populations, index events, dimensions, units, and measures are fixed
  enumerations in `registry.py`, and `windows_days` must equal `[30, 90, 180,
  365, 730, 1095]`. The header comment reads "0.1 is the first registry; 1.0 is
  Phase 4's". `tests/unit/test_metric_registry.py` pins version 1, `"0.1"`,
  every threshold, every entry version `"1"`, and that the kinds in use equal
  `KINDS`; `tests/unit/test_methodology_render.py` pins "methodology version
  0.1" and the `0.1` changelog line; `tests/integration/test_api_metrics.py`
  line 113 asserts `changelog[0].version == methodology_version` (oldest first),
  and `tests/integration/test_api_coverage.py` pins `"0.1"`.
- The frame (`frame.SCHEMAS`, ids as text, timestamps UTC) holds `cases` (id,
  court_id, filed_at, closed_at, status, case_type), `assignments`, `charges`
  (with `offense_category`, `severity`, `disposition`, `disposition_actor`,
  `source_row_id`), `decisions` (with `judge_id`, `actor_type`, `discretion`,
  `release_at`, `detained_flag`, `release_type`), `sentences`, `events`,
  `justice_events` (stored any-case rows plus `new_case`, `new_charge`, and
  `reconviction` derived from the merged person's charges), and `persons` (id
  only). It has no jurisdiction (the snapshot's `courts` table has
  `jurisdiction_id`), no age, and no case party. The brief's candidate features
  map onto it as: offense category and severity, charge count, court — present;
  prior cases, prior convictions, prior failures to appear, the pending-case
  indicator, and the calendar period — derivable; the age band — absent (and
  restricted, below).
- `exposure.with_exposure` defers exposure after a disposition or a sentence by
  the index case's own incarceration term only and never defers a pretrial
  release; `docs/METHODOLOGY.md` "Exposure" publishes the limitation (Phase 3
  finding 1.4), and the frame property test
  (`tests/property/test_frame_invariants.py`) compares the engine with
  `synthetic/truth.py` on the same world.
- `metric_observation` (from `0001`, keyed and versioned by `0005`) already has
  `expected_count` Numeric(14,4), `expected_rate` Numeric(9,6), and
  `standardized_ratio` Numeric(9,6), always written as null by
  `publish._observation_row` and absent from `ObservationDraft`,
  `VERIFIED_COLUMNS`, the provenance trace, and every API schema. The bounds
  `lower_confidence_bound` and `upper_confidence_bound` hold the Wilson or
  Greenwood interval; there is no pooling weight, no model link, and no
  suppression reason (the row keeps `suppressed_flag` only). Observations are
  unique per `(definition, subject, source, period, window, dimension,
  snapshot)` with `superseded_at` history; members (`metric_observation_member`)
  are entity ids of public rows.
- The snapshot (`snapshot.py`) exports eleven tables to
  `<snapshot_dir>/<content_hash>/<table>.parquet` with `manifest.json`
  (`MANIFEST_VERSION` 1), reuses an existing hash and never overwrites
  (`mkdir(exist_ok=False)`), and opens only a manifest whose table set equals
  `SNAPSHOT_TABLES`; its own `RESTRICTED_TABLES` denylist keeps restricted
  tables out. `publish.py` refuses a missing member before any write
  (`ProvenanceError`), supersedes instead of deleting, skips a subject whose
  drafts equal its current rows over `VERIFIED_COLUMNS` and members, and stamps
  `code_version` `<package version>+<sha7>`; `verify.py` recomputes every
  observation from its snapshot. Pipeline step 13
  (`ingest/runner.recompute_metrics`) recomputes the impacted subjects inside
  the ingest transaction. Alembic's head is revision `0007`
  (`alembic/versions/0007_corrections_intake.py`; `/api/v1/ready` reports it as
  `alembic_current`), pinned by `tests/integration/test_health.py` and
  `tests/integration/test_migrations.py`; `test_migrations.py` also asserts 26
  `CANONICAL_TABLES`, and `alembic/env.py` sets no `include_schemas`, so a table
  outside `public` is invisible to `uv run alembic check` today.
- The CLI (`src/judgemetrics/cli.py`) carries `methodology render [--out]
  [--check]`, `metrics compute [--label] [--subject] [--json]` (ingest role),
  `metrics verify [--snapshot] [--json]`, and `provenance trace <id> [--json]`
  (app role). The demo `compute-metrics` takes about 2.5 minutes the first time
  and 25 seconds on a rerun; `bootstrap` takes about four minutes (`seed` 206
  s); CI's `e2e` job seeds in 120 s and computes in 20 s.

### Security & sensitive-data surface

- Sensitive data this phase handles: synthetic restricted attributes (the age
  band at filing and an abstract `synthetic_group`), which exist nowhere in the
  database today; the expected-outcome model artifacts, which must hold
  coefficients, counts, and diagnostics only (the parent roadmap's acceptance
  criterion: "model artifacts contain no person-level rows"); and per-person
  feature rows, which exist only in memory inside `metrics compute`. The
  `synthetic` label and the pseudonymity rules of every earlier phase still
  apply to every new surface.
- There is no PostgreSQL `restricted` schema. The restricted tables are four
  `public` tables with revoked app-role grants — `RESTRICTED_TABLES =
  {"person_identifier", "correction_request", "entity_resolution_candidate",
  "audit_log"}` in `db/models/__init__.py` — enforced by
  `test_migrations.py::test_app_role_cannot_read_restricted_tables` and
  `tests/golden/test_public_contract.py::test_the_app_role_cannot_select_from_a_restricted_table`.
  `infra/docker/postgres/02-roles.sql` grants the app role `SELECT` on every new
  `public` table by default privilege and says "the `restricted` schema … is
  granted separately when it is created; judgemetrics_app never receives access
  to it"; `infra/docker/postgres/03-test-database.sql` re-runs a blanket `GRANT
  SELECT ON ALL TABLES` on every `uv run poe up` and then re-revokes a
  hard-coded list (Phase 3 finding 5.1), so every new restricted object must be
  added there.
- The root roadmap places the age band, race, and gender "into a `restricted`
  schema granted only to the ingest and admin roles" (§5.2) and the
  data-classification table says restricted demographics are "never a model
  feature by default"; the brief's `excluded_or_sensitive_features` requires a
  documented methodological purpose, legal review, fairness analysis, and
  publication rationale for any sensitive variable. `docs/DATA_SOURCES.md`
  records that Cook County's race, gender, and age go to the restricted schema
  and are used only for aggregate fairness analysis.
- Security finding (latent, owned by Step 1): the synthetic connector writes
  `case_party.source_row_id = normalize_identifier(KIND_SOURCE_PARTICIPANT_ID,
  participant_id)` (`ingest/synthetic/normalize.py`), the plaintext participant
  id (for example `PT-000017`), into a canonical column the app role can
  `SELECT`; `docs/ARCHITECTURE.md` "Person hashing and resolution" says a
  participant's source identifier never reaches a canonical column. No API
  schema serves it (`CasePartyOut` carries `party_type` and `public_person_key`,
  not `source_row_id`), and the synthetic ids are synthetic, but the first real
  source (Phase 5) would expose real participant identifiers to the public role.
- Controls to mirror: `security/identifiers.py` for anything keyed on a person
  (peppered sha256); the log scrubber's `SENSITIVE_KEYS` in `logging.py` (a
  substring match on the normalized key: a bare `age` entry would redact
  `stage=` and `message=`;
  `tests/unit/test_logging.py::test_documented_denylist_is_complete` pins the
  exact list);
  `tests/unit/test_openapi.py::test_no_schema_property_carries_a_restricted_name`
  (`RESTRICTED_PROPERTY_NAMES`), `tests/golden/test_public_contract.py`
  (`RESTRICTED_NAMES` in `tests/golden/conftest.py`; no 64-hex string other than
  the snapshot and artifact hashes),
  `tests/unit/test_metrics_snapshot.py::test_no_module_under_metrics_names_a_restricted_attribute`
  and `verify_phase03.py` check 9 — both of which glob only the top level of
  `metrics/`, so a new subpackage is unguarded until the globs recurse. The gate
  is `detect-secrets` against `.secrets.baseline`, `bandit -r src alembic
  scripts`, `pip-audit --strict --require-hashes` over the `uv.lock` export
  (`scripts/audit_deps.py`), `pnpm audit --audit-level=high`,
  `eslint-plugin-security` with `--max-warnings 0`, and `check-added-large-files
  --maxkb=1024`; a bandit suppression sits after the ruff one with the
  justification between them.

### API and web surface

- The metrics routes live in `api/routes/metrics.py` (`GET /api/v1/metrics`,
  `/metrics/compare`, `/metrics/{observation_id}/provenance`, behind
  `cache_public`) plus `GET /judges/{id}/metrics` and `/courts/{id}/metrics`
  through `routes.metrics.subject_metrics_route`; the layers are
  `schemas/metrics.py`, `services/metrics.py`, and `repositories/metrics.py`
  (not under `api/`). `MetricKind` is the literal
  `count|share|windowed_rate|survival|distribution|median`; `IntervalMethod` is
  `wilson|greenwood` from `INTERVAL_METHOD_BY_KIND`; `SuppressibleFigures` nulls
  `numerator`, `denominator`, `rate`, `value`, `distribution`, `lower`, and
  `upper` when `suppressed` is true, and declares `lower`/`upper` in `[0, 1]`,
  so a ratio's interval cannot use them. An observation whose kind the literal
  does not list would fail validation inside `observation_from_row` and turn the
  subject route into a 500. `Observation` has 30 required fields
  (`methodology_version` included); `tests/integration/test_api_metrics.py`
  asserts the top-level key sets of `Registry`, `SubjectMetrics`, `ComparePage`,
  and the provenance body exactly and the observation fields as a superset;
  `tests/unit/test_openapi.py` pins exactly 20 paths and 18 StrictQuery routes;
  `docs/openapi.json` and `web/lib/api/schema.d.ts` are committed snapshots
  regenerated by `uv run judgemetrics openapi export` and `pnpm generate:api`
  and drift-tested on both sides.
- `/metrics/compare` validates the metric, window, and cohort against the
  registry before any query (`validate_compare_metric`, 422 `validation_error`),
  restricts to the current registry version, sorts on
  `rate|numerator|denominator|value|name` with the sort columns null for a
  suppressed row, and picks the cohort's reference period from window functions;
  the statement budget is one statement for a non-empty page.
- The web judge page (`web/app/judges/[judgeId]/page.tsx`) groups observations
  with `lib/metrics.ts` (`groupObservations`, `JUDGE_PANELS`,
  `panelDefinitions`): named slugs per panel, windowed metrics placed by the
  registry's `index_event`, and any unwindowed judge metric no panel names
  listed under "Other metrics" — so a new registry metric appears on the page as
  soon as its entry lands, rendered by `MetricStat`'s default branch as a plain
  rate. `components/metric-stat.tsx` is the only number renderer (label,
  synthetic badge, figure, fraction, eligible count, interval with its method,
  sample size, period, coverage, methodology link; a suppressed row renders the
  threshold notice and no figure) and shows `methodology_version` only in the
  link's `title`, never as text. `KIND_NOUN` (the component), `KIND_TEXT` (the
  methodology page and `metrics/methodology.py`), `COMPARED_KINDS`,
  `defaultSort`, `primaryFigure`, and `CompareTable`'s figure logic each
  enumerate the kinds; `web/tests/unit/metrics.test.ts` asserts `COURT_PANELS`
  ids equal `JUDGE_PANELS` ids; `web/tests/unit/fixtures/observations.ts` is
  type-checked. The association statement lives in `lib/metrics.ts`
  (`ASSOCIATION_STATEMENT`) and renders once per page
  (`data-testid="association-statement"`, strict Playwright locators). The
  Playwright suites are `smoke.spec.ts` (8 tests), `metrics.spec.ts` (3), and
  `first-milestone.spec.ts` (10); the web has 12 Vitest files.
- `/api/v1/ready` reports the Alembic head and `metrics: {snapshot_hash,
  exported_at, methodology_version}` from the latest snapshot; it knows nothing
  about models.

### Operations & observability surface

- Runtime surfaces before this phase: the API (`/api/v1/health`, `/api/v1/ready`
  with the migration head and the latest snapshot), the ingest runner
  (`ingest_run` rows with status and failure reason), and the analytics snapshot
  (health signal: `metrics verify` green on the latest snapshot; alarm: `metrics
  verify` non-zero on a tampered observation, exercised in Phase 3 Step 6). This
  phase changes the analytics snapshot surface: a snapshot now carries its
  fitted expected-outcome models (artifacts under
  `<snapshot_dir>/<hash>/models/`, rows in `outcome_model`), and adjusted
  observations cite a model. Step 3 adds the models to `/api/v1/ready`
  (`metrics.models`: the count fitted for the latest snapshot and the
  specification version), Step 2's `models verify --refit` is the model's alarm
  (non-zero on a tampered or irreproducible artifact), `metrics verify` extends
  to adjusted observations, and Step 4's `validation report --check` in the
  `e2e` job fails on any drift between the committed `docs/VALIDATION.md` and a
  fresh render. Step 6's alarm exercise tampers one adjusted observation and one
  model artifact in the scratch database and records each alarm failing and then
  passing. Snapshots and model artifacts stay under `JUDGEMETRICS_SNAPSHOT_DIR`
  (default `data/snapshots/`, git-ignored); the object-store variant is Phase 8.

### Documentation surface

- `docs/ARCHITECTURE.md` (ingest, roles, "Public API v1", "Web tier", "Metrics
  engine"), `docs/API.md` (endpoints, "Metrics", "Corrections", the query
  budget), `docs/DATA_MODEL.md` (tables, natural keys, vocabularies, "Metric
  registry", grants, departures), `docs/METHODOLOGY.md` (generated),
  `docs/PROVENANCE.md`, `docs/SYNTHETIC_DATA.md`, `docs/ENTITY_RESOLUTION.md`,
  `docs/DATA_SOURCES.md`, `docs/ROADMAP.md`, `README.md`, and `AGENTS.md` exist.
  Missing: `docs/VALIDATION.md` (Step 4), a "Risk adjustment" section in
  `docs/ARCHITECTURE.md` (Steps 2–3), the restricted schema, `outcome_model`,
  and the new observation columns in `docs/DATA_MODEL.md` (Steps 1–3), the
  planted effects and the controls in `docs/SYNTHETIC_DATA.md` (Step 1), the
  adjusted fields and the model card in `docs/API.md` (Step 5), the model link
  in `docs/PROVENANCE.md` (Steps 3 and 5), and the Phase 4 decisions in
  `AGENTS.md` (every step).

### Verification surfaces

- `scripts/verify_phase01.py`, `verify_phase02.py`, and `verify_phase03.py`
  exist; `verify_phase03.py` (2,099 lines, 49 static checks) is the most recent
  template: standard library only (a line reader for the registry's folded
  `known_limitations` and a regular expression over the brief's one
  `<important_statistical_warnings>` element, because an XML parser is
  SAST-flagged); mutually exclusive `--fast`, `--py`, `--node`, `--e2e`,
  `--security`, `--all`, `--post` with the default `--fast` plus `--py`; `[PASS]
  NN` / `[FAIL] NN — reason` / `[SKIP] id — reason`; subprocess suites over
  PATH-resolved `uv`, `pnpm`, `gh`, and `docker`; `probe_environment()` pointing
  the three role URLs at `JUDGEMETRICS_TEST_DATABASE_URL` and the snapshot
  directory at `data/snapshots/scratch-test-db`; the seed, compute, verify, and
  trace probes; the milestone items; `gh pr checks`; the V-matrix; a summary
  table; `PYTHONIOENCODING=utf-8` for captured children.
  `tests/unit/test_phase03_verification.py` runs `--fast` (49 passes), asserts
  `{"01", "02", "03"}` as a subset of the matrix, and pins the standard-library
  readers against `yaml.safe_load`.
- `.github/workflows/phase-verify.yml` matrix is `phase: ["01", "02", "03"]`
  (each entry runs `--fast`, then `--security`); Phase 4 adds `"04"`, and
  `phase-verify (04)` becomes a required context on `main` beside `test`,
  `phase-verify (01)`, `(02)`, and `(03)` through `gh api -X PATCH
  repos/nathanramoscfa/judge-metrics/branches/main/protection/required_status_checks`
  (`CONTRIBUTING.md` "Repository settings"; its "Four contexts are required"
  prose becomes five). Earlier phases' pins that a Phase 4 edit can trip:
  `verify_phase03.py` checks 1, 4, and 5 (exactly eight limitations under `##
  Known limitations`), 9 (restricted names under `metrics/*.py`), 11 (`duckdb`
  present, no extension), 14 (the versions), 23 (no person field in
  `schemas/metrics.py`), 31 (the exact `getRegistry()` body), 40 (the exact
  `bootstrap` sequence), 41 (exactly 17 README milestone items), 42 (the `e2e`
  job's seed and compute lines), and 43 (at least nine first-milestone tests);
  `tests/unit/test_repo_hygiene.py` pins `jobs.test.needs` exactly and the order
  of the `e2e` commands.

---

## Execution Order

```
Step 1  (planted effects + restricted     GENERATOR_VERSION 3 (confounded
         schema)                          assignment, judge effects, age and
                                          group controls), TRUTH_VERSION 3 +
                                          truth/effects.json, any-term exposure
                                          deferral (methodology 0.2), migration
                                          0008 (restricted schema,
                                          party_attribute, case_party key fix),
                                          connector, golden regen, check 14
                                          → implement
  ↓
Step 2  (feature spec + baseline model)  data/reference/outcome_model.yaml,
                                          metrics/adjustment/ (spec, features,
                                          logistic, resample, diagnostics,
                                          artifacts, fit),
                                          migration 0009 (outcome_model),
                                          `models fit|list|show|verify`, numpy,
                                          leakage + order-invariance properties,
                                          artifact inspection test
                                          → implement
  ↓
Step 3  (expected, O/E, pooling,         registry v2 (three observed_expected
         recovery)                        metrics, methodology 0.3), expected,
                                          pooling, bootstrap, migration 0010,
                                          compute/publish/verify/provenance,
                                          step 13 skip, API hold-out, /ready
                                          models, golden adjusted + recovery
                                          tests
                                          → implement
  ↓
Step 4  (validation + methodology 1.0)   judgemetrics.validation (report,
                                          fairness over the restricted schema,
                                          sensitivity, stability, recovery),
                                          `validation report|recovery`,
                                          docs/VALIDATION.md (+ e2e --check),
                                          methodology 1.0, adjustment prose in
                                          METHODOLOGY.md and GET /metrics
                                          → implement
  ↓
Step 5  (adjusted panels + compare +     adjusted fields served, model card
         model card)                      route, provenance model block,
                                          compare sort=ratio, AdjustedStat,
                                          judge risk-adjusted panel, /compare
                                          adjusted, /models/[modelId],
                                          methodology section, Vitest,
                                          adjusted.spec.ts, screenshots
                                          → implement
  ↓
Step 6  (QA + verify_phase04.py)         scripts/verify_phase04.py
                                          + docs/phase04-qa-findings.md
                                          + phase-verify.yml matrix entry 04
                                          + required context + ROADMAP status
                                          + tag v0.4.0-phase-4
                                          → create

--- post-implementation ---

V1  The generator plants confounded assignment, judge effects, and the
    age and group controls under GENERATOR_VERSION 3; truth/effects.json
    records every planted parameter and oracle expected count; exposure is
    deferred by every term identically in engine and truth; the
    restricted schema is unreachable by the app role and no canonical
    column holds a participant id.
V2  The specification loads and rejects any restricted or post-index
    feature; features never read a row at or after their case's filing and
    are invariant to UUID relabelling; the penalized solver meets its
    optimality conditions; models fit from a snapshot and a seed
    reproduce byte for byte; no artifact holds a person-level row.
V3  Adjusted observations publish expected count, pooled ratio, pooling
    weight, and bootstrap interval with their model; metrics verify
    reproduces them; step 13 leaves them alone; no public response
    serves them yet; the planted ranking is recovered within tolerance
    and better than by raw rates.
V4  docs/VALIDATION.md equals its render from the demo seed and reports
    every diagnostic, subgroup calibration in aggregate only, and
    recovery; methodology 1.0 is published with its changelog and the
    eight warnings unchanged.
V5  Every adjusted statistic on the judge, compare, and model pages shows
    observed, expected, ratio, interval, cohort definition, model, and
    methodology version; suppressed subjects show the reason; the
    Playwright adjusted flow passes.
V6  verify_phase04.py --fast and --security exit 0 on Ubuntu CI under the
    phase-verify.yml matrix entry 04; the tag v0.4.0-phase-4 marks the
    merge.
```

Steps are sequential by dependency: Step 1's planted world and
`truth/effects.json` are the known answer every later step is tested against,
its restricted schema is what Step 4's fairness analysis reads, and its exposure
change must land with the `TRUTH_VERSION` bump that encodes it; Step 2's
specification, feature builder, solver, and `outcome_model` table are what Step
3's expected counts, pooling, and bootstrap refit; Step 3's adjusted
observations, stored models, and bootstrap replicates are what Step 4's report
summarizes, and Step 4's validation must be published before Step 5 serves any
adjusted number (the parent roadmap's rule); Step 5's routes and pages are what
Step 6's static checks, Playwright suite, and `--post` probes exercise. This
phase has no steps drawn in parallel.

---

## Step 1 — Planted Effects, Synthetic Restricted Attributes, and the Restricted Schema ✅

**Status:** Complete — PR #37 (2026-09-30)

> **Goal:** Give the synthetic world a known answer and give restricted
> attributes a home. The generator (`GENERATOR_VERSION` `3`, new named streams
> `effects` and `attributes`) assigns judges by an observable risk index so
> dockets differ in case mix (planted confounding), draws each judge's release
> leniency, new-case effect, failure-to-appear effect, and docket tilt, makes
> the release decision and both later outcomes depend on observable case
> features plus the deciding judge's effect, adds an age effect on the later
> outcomes (the restricted positive control the model will not see) and an
> abstract `synthetic_group` independent of every draw (the negative control),
> and leaves `age_at_filing` blank when the date of birth is unknown;
> `synthetic/truth.py` (`TRUTH_VERSION` `3`) writes `truth/effects.json` with
> every planted parameter and, per judge, target, and window, the cohort, the
> observed count, and the oracle expected count under the generator's own
> probabilities; `metrics/exposure.py` and the truth defer exposure by every
> incarceration term of the person (Phase 3 finding 1.4), under methodology
> `0.2`; migration `0008_restricted_schema` creates the PostgreSQL schema
> `restricted` and `restricted.party_attribute` with grants that give the app
> role no `USAGE`, turns on Alembic's `include_schemas`, and rewrites
> `case_party.source_row_id` to a within-case ordinal so no plaintext
> participant id sits in a canonical column; the synthetic connector publishes
> `age_band` and `synthetic_group` into the restricted schema; the golden
> fixture is regenerated; and `scripts/verify_phase03.py` check 14 compares the
> manifest with the source constants. This step lands the known answer; Step 2
> fits a model to it, Step 3 measures how well the model recovers it, and Step 4
> reads the restricted controls.

**Branch:** `feature/phase04-step1-planted-effects-restricted-schema`

**Deploys:** local database (`uv run poe up` + `uv run poe migrate`) and the
local demo dataset — the merge carries migration `0008_restricted_schema`, which
the operator applies; `uv run poe seed` then regenerates
`data/synthetic/20260916` (its manifest records generator version `2`) and
ingests it, and `uv run poe compute-metrics` republishes every observation under
methodology `0.2`. `/api/v1/ready` reports the new head.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                                  |
| ------------ | ------------------------------------------------------ |
| Model        | Opus 5.5                                               |
| Backup       | GPT-5.6 Sol — Codex · Intelligence Extra High          |
| Platform     | Claude Code                                            |
| Effort       | Extra High (raised from Claude Code's default Medium)  |
| Thinking     | On                                                     |
| Conversation | **New**                                                |

**Model rationale:** This step designs a causal generative process whose oracle
probabilities the truth must compute exactly under the generator's own draw
rules, then carries one semantic change (any-term exposure deferral) through the
engine, the truth, and the methodology identically, and adds a new database
schema with a least-privilege boundary — PRIMARY `coding`, SECONDARY `planning`,
High complexity with novel problem-solving and chain-of-thought across the
generator, the truth, the engine, the connector, the migration, and the golden
fixture. Opus 5.5 is S-tier in coding and S-tier in planning (AA Intelligence
Index 57.6 and HLE 61.4% at max); Fable 5.1 and GPT-5.6 Sol tie it on both rows
and on coverage, the output-price tie-breaker drops Fable 5.1 ($50 against $20),
and the operator's platform order puts Claude Code ahead of Codex for the
remaining tie. The Platform is Claude Code on the $200 claude.ai Max
subscription (weekly pool at `headroom`); the operator's `capped` consumption
posture closes the flat-funding gate, so effort follows the complexity ladder:
Claude Code opens Opus 5.5 at Effort `Medium`, and this step raises it to `Extra
High` because it meets the novel-problem and cross-file conditions — not `Max`,
since reasoning depth is not the demonstrated bottleneck and the
oracle-consistency and property tests catch a wrong formula. Thinking `On` (the
operator never disables it). Backup: GPT-5.6 Sol on Codex (the $100 ChatGPT Pro
5x pool, the operator's first backup provider), S-tier in coding and planning
from OpenAI, at Intelligence `Extra High` for the same conditions; no `*-codex`
variant, which the operator's ChatGPT-account sign-in cannot run. Conversation
is New per phase-boundary hygiene.

```xml
<task>
  <lifecycle>
    This step MUST follow all six
    stages, in order. Stages 1, 3,
    4, 5, 6 are AS BINDING as any
    `<requirement>` below. Do not
    emit the Stage 6 completion line
    until the PR is merged and every
    acceptance criterion for this
    step is affirmatively met.

    1. CREATE THE BRANCH. Before any
       Read / Edit / Bash, run `git
       checkout -b
       feature/phase04-step1-planted-effects-restricted-schema`
       from a clean, up-to-date
       `main`. The exact branch name
       is in this step's
       `**Branch:**` line above. If
       the Worktree rule applies,
       use `git fetch origin && git
       worktree add -b <branch>
       .worktrees/<slug>
       origin/main` instead, then
       bootstrap the worktree.

    2. WORK ON THE BRANCH. All
       commits land here. `main` is
       protected with
       `enforce_admins: true` —
       direct pushes will be
       rejected. Pass the security
       gate before every commit.
       Stop the local API before `uv
       run poe gate` or `git
       commit`.

    3. OPEN THE PR, THEN MARK THE
       STEP. `gh pr create --base
       main --head <branch>` with a
       Conventional Commits title
       and a body that references
       this roadmap step and its
       acceptance criteria. One PR
       per step. Then, in this
       roadmap file: set this step's
       `**Status:**` line (directly
       under its heading) to
       `Complete — PR #<n>
       (<YYYY-MM-DD>)`, append ` ✅`
       to the step's `## Step`
       heading, and set its Summary
       Table Status cell to
       `Complete — PR #<n>`. Commit
       that edit on the step branch
       and push — the PR carries its
       own completion mark, so the
       roadmap on `main` marks this
       step complete exactly when
       the PR merges (Status rule).
       Same commit: on the phase's
       first step, set this
       roadmap's phase-level
       `**Status:**` (under its
       title) and the parent project
       roadmap's Phase 4
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 4` heading.

    4. WAIT FOR GREEN CHECKS, THEN
       SQUASH-MERGE. Every required
       check must pass. If the PR
       falls behind main, refresh
       with `gh pr update-branch
       --rebase` — never merge main
       into the branch
       (`required_linear_history:
       true`). Once green: `gh pr
       merge <PR> --squash
       --delete-branch`. If this
       step's `**Deploys:**` line
       names a surface, the merge is
       not the finish line: run the
       Deployed & verified check
       against the local environment
       before declaring the step
       complete.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree, `git
       worktree remove <path>` FIRST
       — the branch prune fails
       while the branch is checked
       out there.

    6. DISPOSE OF EVERY FINDING,
       DECLARE COMPLETION, THEN NEW
       CONVERSATION. First send
       every finding this step
       surfaced to its destination
       (Triage rule): a note for a
       later step → edit that step's
       <task> block now; spec rot →
       edit this roadmap now; a bug
       → fixed in-step or an issue
       number; a judgement call in
       the diff → the PR body; a
       process lesson → written
       where the next conversation
       reads it (AGENTS.md or this
       roadmap); a data-semantics
       finding → the registry or
       model-specification entry,
       version bumped; a data-access
       question → a row in
       docs/ROADMAP.md. Update
       docs/ROADMAP.md (completed
       items, known issues, next
       milestones). A finding you
       can only describe is NOT
       disposed of, and counts as an
       unmet criterion. Only once
       the PR is merged — and `main`
       therefore carries this step's
       `Complete` Status line —
       every acceptance criterion is
       affirmatively met, and every
       finding has a destination,
       say so plainly: end your
       final response with an
       explicit, unhedged completion
       line — verbatim shape "Step 1
       is complete. You can now move
       on to Step 2." That line is
       the LAST line of the
       response. NOTHING follows it
       — no "Follow-ups
       (non-blocking)", "Notes",
       "Next", "worth a glance", or
       suggested improvements. A
       short ledger may PRECEDE it,
       one entry per finding naming
       its destination (issue #,
       file edited, PR body) — never
       an open item. If any
       criterion is unmet or any
       finding has no destination,
       state plainly that the step
       is NOT complete, name what is
       outstanding, and omit the
       completion line. "Done" means
       done. Then, for
       phase-boundary hygiene, the
       operator closes this session
       and opens a fresh one before
       Step 2.
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
       credentials, API keys,
       tokens, or real PII in the
       diff (gitleaks /
       detect-secrets or the
       project's equivalent).
       Secrets go in the secrets
       manager, never in source or
       committed env files. In this
       step: the regenerated golden
       fixture's names, dates of
       birth, and participant ids
       stay word-list and counter
       values, never real people;
       `.secrets.baseline` is
       refreshed by scanning
       `tests/fixtures/golden/manifest.json`
       alone (`uv run detect-secrets
       scan --baseline
       .secrets.baseline
       tests/fixtures/golden/manifest.json`,
       then forward slashes in its
       `filename` entries); no
       pepper, key, or connection
       string appears in any test,
       fixture, or document.

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. In
       this step: migration `0008`
       builds every `CREATE SCHEMA`,
       `GRANT`, `REVOKE`, and `ALTER
       DEFAULT PRIVILEGES` from
       module constants, never from
       input, as `0001` through
       `0007` do; the connector
       parses `age_at_filing` as a
       bounded integer and
       `synthetic_group` against the
       vocabulary; the generator
       adds no `datetime.now(`,
       `uuid4(`, `urandom(`, or
       module-level `random` call
       (`verify_phase02.py` check
       3).

    3. DEPENDENCY AUDIT. Any new or
       bumped dependency passes the
       audit (pip-audit / npm audit
       / osv-scanner); no
       known-vulnerable, yanked, or
       typo-squatted package. This
       step adds no dependency. If
       one is added, it passes
       `pip-audit --strict
       --require-hashes` over the
       `uv.lock` export
       (`scripts/audit_deps.py`).

    4. SENSITIVE-DATA REVIEW.
       Whatever this step touches
       stays least-privilege,
       encrypted in transit + at
       rest, and out of logs and
       client bundles. If the step
       adds a data path, name how
       PII/secrets are protected. In
       this step:
       `restricted.party_attribute`
       is reachable by the ingest
       and admin roles only — the
       app role receives no `USAGE`
       on the schema in the
       migration, in
       `infra/docker/postgres/02-roles.sql`,
       or in the scratch database
       after `03-test-database.sql`
       reruns; after the rewrite no
       canonical column holds a
       plaintext participant id; the
       snapshot never exports a
       `restricted` table;
       `age_band`,
       `synthetic_group`, and
       `attribute_value` join the
       log scrubber's denylist
       (never a bare `age`, which
       would redact `stage=` and
       `message=`); the planted
       parameters and the oracle
       probabilities live in
       `truth/` only, which no
       connector reads and nothing
       loads into the database.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean. This is the safety net
    that stops a security issue from
    reaching the branch, the PR, or
    `main`.
  </security>

  <context>
    JudgeMetrics. Phase 4. Step 1:
    planted effects, synthetic
    restricted attributes, and the
    restricted schema.

    Current state (as of Phase 3):

    - The generator is at
      `GENERATOR_VERSION` `2` and
      `TRUTH_VERSION` `2`. Streams
      are `STREAM_NAMES = ("world",
      "persons", "cases", "events",
      "edge_cases")` in
      `synthetic/rng.py`;
      `build_dataset`
      (`synthetic/generate.py`) runs
      `build_world`, `build_cases`,
      `assign_identifiers`,
      `plant_edge_cases`, and the
      writers. Scales in
      `synthetic/config.py`:
      `GOLDEN` (3 courts, 6 judges,
      40 persons, 60 cases,
      2019–2021, seed 7), `DEMO` (5,
      24, 3,200, 5,200, 2016–2023,
      seed `20260916`), `TINY` (2,
      3, 12, 16, 2020–2021).
    - Judges draw `release_bias`,
      `dismissal_bias`, and
      `severity_bias` on the `world`
      stream (`world.build_judges`);
      only `release_bias` touches
      the pretrial decision
      (`cases._pretrial_decision`:
      recognizance
      `BASE_RECOGNIZANCE[type] +
      release_bias`, detention
      `BASE_DETENTION[type] −
      release_bias / 2`, a bond
      posted with probability 0.75,
      10% statutory releases).
      Assignment is `choice` among
      the judges serving the court
      that day. Failure to appear
      (`_plant_failure_to_appear`)
      and the next filing
      (`_filed_date`,
      `skewed_fraction(1 + 2 ·
      propensity)` over the
      remaining span after the
      previous pretrial decision
      plus 14 days) depend on the
      latent propensity only; case
      counts are allocated by `0.2 +
      propensity`. No truth file
      records a judge tendency or a
      propensity.
    - `Person` has `date_of_birth`,
      `age_band` (drawn at the
      corpus start), `propensity`,
      `home_court`, `dob_known`;
      `participants.csv` carries
      `age_at_filing` always filled,
      which the connector drops. No
      other demographic exists.
    - `metrics/exposure.with_exposure`
      defers exposure by the index
      case's own incarceration term
      only (never for a pretrial
      release), and
      `synthetic/truth.py` does the
      same;
      `tests/property/test_frame_invariants.py`
      compares the two on in-memory
      `TINY` worlds built by
      `tests/property/support.frame_from_world`.
    - No PostgreSQL schema other
      than `public` exists;
      restricted tables are `public`
      tables with revoked app grants
      (`RESTRICTED_TABLES` in
      `db/models/__init__.py`);
      `02-roles.sql` grants the app
      role `SELECT` on every new
      `public` table by default
      privilege;
      `03-test-database.sql`
      re-grants `SELECT ON ALL
      TABLES` on every `uv run poe
      up` and re-revokes a
      hard-coded list;
      `alembic/env.py` sets no
      `include_schemas`. The head is
      revision `0007`
      (`alembic/versions/0007_corrections_intake.py`).
    - The synthetic connector writes
      `case_party.source_row_id =
      normalize_identifier(KIND_SOURCE_PARTICIPANT_ID,
      participant_id)`
      (`ingest/synthetic/normalize.py`):
      the plaintext participant id
      in an app-readable canonical
      column (the security finding
      this step owns).
    - `scripts/verify_phase03.py`
      check 14 requires the golden
      manifest's `generator_version`
      and `truth_version` to equal
      the literal `"2"`;
      `phase-verify (03)` is a
      required context and
      `tests/unit/test_phase03_verification.py`
      counts 49 passes.
    - The registry is `version` 1,
      `methodology_version` `"0.1"`;
      `metrics/methodology.py` holds
      `SEMANTICS` (the exposure
      prose) and `CHANGELOG`; tests
      pin `"0.1"` in
      `test_metric_registry.py`,
      `test_methodology_render.py`,
      `test_api_coverage.py`, and
      `test_api_metrics.py` line 113
      (`changelog[0]`).

    Files to read (every file before
    drafting):
    - src/judgemetrics/synthetic/config.py,
      model.py, rng.py, world.py,
      cases.py, edge_cases.py,
      truth.py, writer.py,
      generate.py, vocabulary.py
      (the whole generator).
    - docs/SYNTHETIC_DATA.md (the
      metric set, the plants,
      "Regenerating the golden
      fixture").
    - src/judgemetrics/ingest/synthetic/connector.py,
      parse.py, normalize.py,
      schema.py, sources.py (the
      participant path and the
      headers).
    - src/judgemetrics/ingest/runner.py
      and ingest/publish.py (draft
      publishing order, the upsert
      guards).
    - src/judgemetrics/metrics/exposure.py,
      frame.py, snapshot.py (the
      deferral rule, the frame, the
      snapshot's
      `RESTRICTED_TABLES`).
    - src/judgemetrics/metrics/methodology.py
      and
      data/reference/metric_registry.yaml
      (the exposure prose, the
      changelog, the version rule).
    - src/judgemetrics/db/models/__init__.py
      and
      src/judgemetrics/db/models/cases.py
      (the restricted sets,
      `CaseParty`).
    - alembic/env.py,
      alembic/versions/0004_entity_resolution_review.py
      and 0007_corrections_intake.py
      (the grant patterns).
    - infra/docker/postgres/02-roles.sql
      and 03-test-database.sql
      (default privileges, the
      re-revoke block).
    - src/judgemetrics/logging.py
      and tests/unit/test_logging.py
      (the denylist and its pin).
    - data/reference/case_vocabulary.yaml,
      src/judgemetrics/normalization/vocabulary.py
      (the vocabulary and its
      equality with the
      generator's).
    - tests/golden/ (every file),
      tests/property/support.py,
      tests/property/test_frame_invariants.py,
      tests/unit/test_metrics_snapshot.py,
      tests/integration/test_migrations.py,
      tests/integration/test_synthetic_ingest.py.
    - scripts/verify_phase03.py
      (check 9 and check 14) and
      tests/unit/test_phase03_verification.py.
    - docs/DATA_MODEL.md,
      docs/ARCHITECTURE.md ("Person
      hashing and resolution",
      "Metrics engine"),
      docs/roadmap/ROADMAP.md §5.2
      and "Security & privacy
      strategy" → "Data
      classification".
  </context>

  <goal>
    Ship `GENERATOR_VERSION` `3` and
    `TRUTH_VERSION` `3` with the
    planted confounding, the judge
    effects, the two restricted
    controls, and
    `truth/effects.json`; the
    any-term exposure deferral in
    the engine and the truth under
    methodology `0.2`; migration
    `0008_restricted_schema` with
    `restricted.party_attribute`,
    the grants, `include_schemas`,
    and the
    `case_party.source_row_id`
    rewrite; the connector
    publishing the two restricted
    attributes; the regenerated
    golden fixture; the recursive
    restricted-name guards; and
    `verify_phase03.py` check 14
    comparing against the source
    constants — with the tests that
    prove the planted structure is
    recoverable in principle.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      The planted world
      (`GENERATOR_VERSION` `"3"`).
      Add the named streams
      `effects` and `attributes` to
      `STREAM_NAMES` and `Streams`
      (the stream-independence test
      iterates `STREAM_NAMES`). On
      the `effects` stream draw, per
      judge, `leniency` (a shift of
      the release decision on the
      log-odds scale; it replaces
      `release_bias`),
      `new_case_effect` and
      `fta_effect` (shifts of the
      two later outcomes on the
      generator's own probability
      scales), and `docket_tilt`
      (the judge's preference for
      high-risk cases); keep
      `dismissal_bias` and
      `severity_bias` as they are.
      Plant the confounding
      deliberately rather than leave
      it to chance: within each
      court, order the docket tilts
      inversely to the judges'
      new-case effects, so the judge
      whose later cases are least
      likely draws the riskiest
      docket and raw rates mislead.
      Record every draw for the
      truth.
    </requirement>

    <requirement>
      The observable risk index and
      the assignment. Define one
      risk index per case at filing
      from observable features only
      — the lead charge's severity
      rank, the charge count, and
      the person's prior cases,
      prior convictions, prior
      failures to appear, and
      pending cases counted over
      corpus records strictly before
      the filing (the corpus has no
      earlier history, so a first
      case has none), at the
      resolution Step 2's
      specification adopts (charge
      count 1, 2, 3+; prior cases 0,
      1, 2, 3+; prior convictions 0,
      1, 2+; prior failures to
      appear 0, 1+; pending or not)
      and at the instant its history
      features are evaluated (the
      index case's filing), so that
      conditioning on the model's
      features removes the planted
      confounding — never from the
      propensity, the age band, or
      the group. Choose the initial
      judge by `weighted_choice`
      among the judges serving the
      court that day with weight
      `exp(docket_tilt ·
      risk_index)`; the planned and
      forced reassignments stay as
      they are. Assignment then
      depends on observables only,
      which is what makes the judge
      comparison recoverable after
      adjustment on those
      observables.
    </requirement>

    <requirement>
      The decisions and outcomes.
      For a judge-attributed
      discretionary pretrial
      decision, release with
      probability
      `logistic(r0[case_type] + r ·
      x + leniency)` where `x` are
      the same banded observable
      features, then split a release
      into recognizance or a posted
      bond with a subsequent draw;
      statutory releases keep their
      10% share and stay
      non-judicial. For a release,
      failure to appear with
      probability `logistic(f0 + f ·
      x + g · propensity +
      a[age_band] + fta_effect)` of
      the releasing judge, on the
      hearing the current rule
      picks. For a release, file the
      person's next case (when the
      allocation gives one) with the
      skew exponent `k0 + 2 ·
      propensity + b[age_band] +
      new_case_effect` of the
      releasing judge, bounded below
      so it stays positive, so a
      positive effect files sooner.
      `a` and `b` are the planted
      age effects by the band of the
      age at the index case's filing
      — the band the connector
      publishes, not
      `Person.age_band`, which is
      drawn at the corpus start —
      younger bands higher;
      `synthetic_group` (`group_a`,
      `group_b`, `group_c`) is drawn
      per person on the `attributes`
      stream after `build_persons`
      and feeds no draw.
      `age_at_filing` is blank in
      `participants.csv` when
      `dob_known` is false.
      Calibrate the magnitudes so
      the demo world meets the
      recoverability criteria below,
      keep `DEMO` above the brief's
      minimums, keep every plant in
      `synthetic/edge_cases.py`
      working (the fallbacks
      included), and document the
      functional forms and the
      constants in
      `docs/SYNTHETIC_DATA.md`
      "Planted effects".
    </requirement>

    <requirement>
      The oracle truth
      (`TRUTH_VERSION` `"3"`). Where
      each draw happens, compute its
      exact probability under the
      generator's own rules (the
      release probability; the
      failure-to-appear probability
      times the chance its date
      falls within each window; the
      chance the next filing falls
      within each window given the
      allocation, the span, and the
      exponent), both with the
      judge's effect and with the
      effect replaced by the
      case-weighted mean effect of
      the judges of the case's court
      (`p0`, the centered oracle).
      Write `truth/effects.json`
      with `truth_version`,
      `generator_version`, `seed`,
      `scale`, `definitions` (the
      prose semantics of every
      field), `parameters` (the
      functional forms' constants
      and the age effects),
      `judges.<J-code>` (court
      codes, `leniency`,
      `new_case_effect`,
      `fta_effect`, `docket_tilt`,
      each effect also centered on
      its court),
      `targets.pretrial_release.judges.<J-code>`
      (attributed discretionary
      decisions, releases, oracle
      expected releases `sum(p0)`,
      and the oracle ratio),
      `targets.new_case` and
      `targets.failure_to_appear`
      per window of the six (per
      judge: the followed
      pretrial-release cohort under
      the Phase 3 cohort and
      follow-up rules, the observed
      count, `sum(p0)`, `sum(p)`,
      and the oracle ratio), and
      `controls` (the planted age
      effects per filing-age band;
      `synthetic_group` independent
      by construction). Only
      per-judge and per-band
      aggregates are written — no
      per-person row. Add
      `effects.json` to
      `TRUTH_FILES`, regenerate
      `truth/README.md`, and keep
      `metrics.json`'s structure.
    </requirement>

    <requirement>
      Any-term exposure deferral
      (Phase 3 finding 1.4,
      carry-over item 1). In
      `metrics/exposure.py` and in
      `synthetic/truth.py`,
      identically: for every index
      kind, pretrial release
      included, the exposure start
      is the index time moved to the
      end of any incarceration term
      of the same person (any case,
      the merged person's in the
      engine) that contains it,
      repeated until no term
      contains it; a term is
      `[sentence_at, sentence_at +
      incarceration_days)`;
      `deferral_days` is the total.
      Update the "Exposure" text in
      `metrics/methodology.py`
      `SEMANTICS`, set the
      registry's
      `methodology_version` to
      `"0.2"`, append `("0.2",
      "Exposure is deferred by every
      incarceration term of the
      person, not the index case's
      alone (Phase 3 finding
      1.4).")` to `CHANGELOG`,
      re-render
      `docs/METHODOLOGY.md`, and
      update the version pins
      (`test_metric_registry.py`,
      `test_methodology_render.py`,
      `test_api_coverage.py`, and
      `test_api_metrics.py` line
      113, changed from
      `changelog[0]` to
      `changelog[-1]` so it asserts
      the newest entry). The
      registry `version` stays 1: no
      entry changes. Add
      tests/unit/test_exposure_deferral.py
      over hand-built frames with
      overlapping terms (a chain of
      two terms; a pretrial release
      inside another case's term)
      and keep the frame property
      test's engine-equals-truth
      assertion.
    </requirement>

    <requirement>
      Migration
      `alembic/versions/0008_restricted_schema.py`:
      `CREATE SCHEMA restricted`;
      `REVOKE ALL ON SCHEMA
      restricted FROM PUBLIC`;
      `GRANT USAGE ON SCHEMA
      restricted TO
      judgemetrics_ingest,
      judgemetrics_admin`; table
      grants and `ALTER DEFAULT
      PRIVILEGES IN SCHEMA
      restricted` giving the ingest
      role DML and the admin role
      every privilege (the root
      roadmap's "ingest and admin
      roles only"); no grant of any
      kind to `judgemetrics_app`;
      skip role statements for a
      role that does not exist, as
      the earlier revisions do.
      Create
      `restricted.party_attribute`
      (`id` UUID with
      `gen_random_uuid()`,
      `case_party_id` FK to
      `public.case_party` `ON DELETE
      CASCADE`, `attribute` text,
      `value` text,
      `source_record_id` FK to
      `source_record`, `created_at`,
      `updated_at`; unique
      `(case_party_id, attribute)`
      as
      `uq_party_attribute_case_party_attribute`).
      Rewrite
      `case_party.source_row_id` to
      `<party_type>:<ordinal>`, the
      ordinal being the party's
      position within its case and
      party type in the order of the
      old key, and document that a
      downgrade keeps the ordinal
      keys (a re-ingest restores
      nothing else). Add the ORM
      model with
      `schema="restricted"`, a
      `RESTRICTED_SCHEMA_TABLES` set
      beside `RESTRICTED_TABLES`
      (the 26 `CANONICAL_TABLES`
      stay 26),
      `include_schemas=True` in
      `alembic/env.py` with a filter
      to `public` and `restricted`
      so `uv run alembic check`
      covers the new table, the
      comment in `02-roles.sql`, and
      a `03-test-database.sql` step
      that revokes the app role's
      schema usage whenever the
      schema exists. Update the head
      pins to `0008`.
    </requirement>

    <requirement>
      Vocabulary version 2
      (`data/reference/case_vocabulary.yaml`
      and `synthetic/vocabulary.py`,
      equal by test):
      `restricted_attribute`
      (`age_band`,
      `synthetic_group`), `age_band`
      (`18-24`, `25-34`, `35-44`,
      `45-54`, `55+`, `unknown`),
      `synthetic_group` (`group_a`,
      `group_b`, `group_c`). Record
      the kinds in
      `docs/DATA_MODEL.md`
      "Vocabularies" as restricted
      vocabularies.
    </requirement>

    <requirement>
      The connector.
      `participants.csv` gains
      `synthetic_group`
      (`schema.EXPECTED_HEADERS`
      equals
      `writer.SOURCE_HEADERS`); the
      connector maps `age_at_filing`
      to an `age_band` (blank →
      `unknown`) and publishes one
      `PartyAttributeDraft` per
      attribute per case party into
      `restricted.party_attribute`
      after the case parties, with
      the natural-key upsert and `IS
      DISTINCT FROM` guards the
      other case-level tables use,
      inside the same transaction;
      the raw age and the group
      never reach a `PersonDraft` or
      `CasePartyDraft` field
      (`tests/unit/test_synthetic_connector.py::test_person_attribute_columns_never_reach_a_draft_field`
      extended to them);
      `case_party.source_row_id` is
      `<party_type>:<ordinal>` in
      normalized participant-id
      order, the same keys the
      migration writes; bump
      `SyntheticConnector.parser_version`
      to `"2"` so recorded artifacts
      re-parse.
    </requirement>

    <requirement>
      Guards. The snapshot refuses
      any table of the `restricted`
      schema by its schema, through
      a constant imported from
      `db/models` rather than a
      table name (a new test in
      `tests/unit/test_metrics_snapshot.py`);
      `tests/integration/test_synthetic_ingest.py`
      asserts one `age_band` and one
      `synthetic_group` row per case
      party and the
      `<party_type>:<ordinal>` keys;
      `tests/unit/test_metrics_snapshot.py::test_no_module_under_metrics_names_a_restricted_attribute`
      and `verify_phase03.py` check
      9 glob `metrics/**/*.py`
      recursively and add
      `age_band`, `synthetic_group`,
      and `party_attribute` to the
      forbidden names (check 9 keeps
      its number and still passes);
      `RESTRICTED_NAMES`
      (`tests/golden/conftest.py`)
      and
      `RESTRICTED_PROPERTY_NAMES`
      (`tests/unit/test_openapi.py`)
      gain the same names;
      `SENSITIVE_KEYS` gains
      `age_band`, `synthetic_group`,
      and `attribute_value` with
      `test_logging.py`'s pin
      updated; a golden contract
      test scans every app-readable
      text column of the golden
      database for the
      participant-id pattern
      `PT-\d{6}` and finds none;
      `tests/integration/test_restricted_schema.py`
      proves the app role cannot use
      the schema or select the table
      (`InsufficientPrivilege`) in
      the configured and the scratch
      database, and the ingest role
      can read and write it.
    </requirement>

    <requirement>
      `scripts/verify_phase03.py`
      check 14: read
      `GENERATOR_VERSION` from
      `src/judgemetrics/synthetic/config.py`
      and `TRUTH_VERSION` from
      `src/judgemetrics/synthetic/truth.py`
      with a regular expression,
      require the golden manifest's
      versions to equal them and
      both to be integers of at
      least 2, and keep every other
      assertion. `verify_phase03.py
      --fast` still reports 49
      passes and
      `tests/unit/test_phase03_verification.py`
      stays unchanged. Record the
      change as Phase 4 Step 1's
      first finding (a later phase's
      bump must never fail an
      earlier phase's required
      check).
    </requirement>

    <requirement>
      Regenerate the golden fixture:
      `uv run judgemetrics synthetic
      generate --seed 7 --scale
      golden --out
      tests/fixtures/golden
      --force`, `uv run judgemetrics
      synthetic verify
      tests/fixtures/golden`, the
      counts in
      `tests/fixtures/golden/README.md`,
      the scoped `.secrets.baseline`
      refresh, and
      `tests/golden/truth_map.py`
      for any new truth path.
      `tests/golden/test_golden_metrics.py`
      still proves every registry
      metric equals
      `truth/metrics.json` exactly,
      now under the any-term
      deferral.
    </requirement>

    <requirement>
      Add
      tests/unit/test_synthetic_effects.py
      (over the demo world generated
      in memory once per module,
      seed `20260916`, and the
      golden world):
      - test_assignment_weights_read_observable_features_only
        (a stub case that differs
        only in propensity, age
        band, or group gets
        identical weights).
      - test_docket_tilt_confounds_raw_rates
        (within at least one court,
        a judge pair's raw 365-day
        new-case rates rank opposite
        to their planted new-case
        effects).
      - test_oracle_ratios_rank_the_centered_effects
        (Spearman at least 0.9 for
        the release target and at
        least 0.8 for the 365-day
        new-case and
        failure-to-appear targets,
        over judges with at least 30
        followed members).
      - test_oracle_totals_match_the_draws
        (for every target at 365
        days, the summed observed
        and summed oracle expected
        counts agree within 10%).
      - test_effects_json_cohorts_equal_metrics_json
        (the cohorts and observed
        counts of `effects.json`
        equal `metrics.json`'s for
        the same judge and window).
      - test_group_stream_is_independent
        (regenerating with the
        `attributes` stream
        re-seeded changes only
        `synthetic_group` values).
    </requirement>

    <requirement>
      Add
      tests/property/test_effects_invariants.py
      (Hypothesis over `TINY`
      worlds, `ci` and `dev`
      profiles): every oracle
      probability lies strictly
      inside (0, 1); zeroing every
      judge effect makes `p` equal
      `p0`; the risk index of a case
      never changes when a later
      case, event, or sentence of
      the person changes.
    </requirement>

    <requirement>
      Documentation:
      `docs/SYNTHETIC_DATA.md`
      ("Planted effects",
      "Restricted controls",
      `truth/effects.json`),
      `docs/DATA_MODEL.md` (the
      `restricted` schema,
      `party_attribute`, vocabulary
      2, the grants table, and the
      `case_party.source_row_id`
      departure),
      `docs/ARCHITECTURE.md`
      ("Person hashing and
      resolution" corrected to the
      ordinal key; a "Restricted
      schema" subsection),
      `docs/METHODOLOGY.md`
      (re-rendered), `AGENTS.md`
      (the decisions this step
      makes), and `docs/ROADMAP.md`
      (status, the bump, the
      finding). In the Stage-3
      commit, beside the status
      lines, set the parent
      roadmap's §8 "Phase Complexity
      Summary" row for Phase 4 to
      `In progress` and its model
      cell to the models this
      roadmap assigns ("Claude Opus
      5.5 (Claude Code): Extra High
      for Steps 1–3, High for Steps
      4–5, Medium for QA"), because
      the operator's context of
      2026-09-22 superseded the
      Fable 5.1 assignment written
      there.
    </requirement>

    <requirement>
      Filepath comment: every new
      Python, SQL, YAML, and
      Markdown file gets the
      repo-relative path as the
      first line (`#
      src/judgemetrics/…`, `--
      infra/docker/…`, `<!-- docs/…
      -->`).
    </requirement>
  </requirements>
</task>
```

### Step 1 acceptance criteria

- `GENERATOR_VERSION` and `TRUTH_VERSION` are `"3"`; the golden fixture is
  regenerated (manifest versions 3, `effects.json` listed), `uv run judgemetrics
  synthetic verify tests/fixtures/golden` exits 0, and
  `tests/golden/test_golden_fixture.py` regenerates it byte for byte.
- `truth/effects.json` records every judge's leniency, new-case effect,
  failure-to-appear effect, docket tilt, and court-centered effects, and per
  target and window the cohort, the observed count, and the oracle expected
  counts, with no per-person row; its cohorts and observed counts equal
  `truth/metrics.json`'s (test).
- On the demo world, raw 365-day new-case rates rank at least one same-court
  judge pair opposite to their planted effects, the oracle ratios rank the
  centered effects with Spearman at least 0.9 (release) and 0.8 (365-day new
  case and failure to appear), and the oracle totals match the draws within 10%
  (`test_synthetic_effects.py`).
- Assignment reads observable features only and `synthetic_group` feeds no draw
  (tests); `test_effects_invariants.py` passes under the `ci` profile.
- Exposure is deferred by every incarceration term of the person in the engine
  and the truth identically (the frame property test and
  `test_exposure_deferral.py`); methodology `0.2` carries its changelog entry;
  `docs/METHODOLOGY.md` equals the render; `tests/golden/test_golden_metrics.py`
  passes.
- Migration `0008_restricted_schema` round-trips; `uv run alembic check` reports
  no drift with `include_schemas`; the app role has no `USAGE` on `restricted`
  and `InsufficientPrivilege` on `restricted.party_attribute` in the configured
  and the scratch database (`test_restricted_schema.py`); the head pins read
  `0008`.
- The golden ingest writes one `age_band` and one `synthetic_group` row per case
  party and `case_party.source_row_id` is `<party_type>:<ordinal>`
  (`test_synthetic_ingest.py`); no app-readable text column of the golden
  database matches `PT-\d{6}` (contract test).
- The restricted-name guards recurse under `metrics/` and name the new
  attributes; the scrubber denylist carries `age_band`, `synthetic_group`, and
  `attribute_value`; `verify_phase03.py --fast` reports 49 passes with check 14
  comparing against the source constants.
- `uv run poe check` passes and every required CI check is green.
- **Deployed & verified**: after `uv run poe up && uv run poe migrate`, `GET
  http://localhost:8000/api/v1/ready` reports `alembic_current` `0008`; `uv run
  poe seed` regenerates `data/synthetic/20260916` at generator version 3 and
  ingests it; `uv run poe compute-metrics` publishes under methodology `0.2`;
  and `SELECT 1 FROM restricted.party_attribute` as `judgemetrics_app` fails
  with a permission error while the same query as `judgemetrics_ingest`
  succeeds.
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff — secret scan clean against the refreshed
  baseline, `bandit` clean over `src alembic scripts`, dependency audit clean —
  and the restricted-schema surface handles sensitive data per the project
  ROADMAP "Security & privacy strategy": the app role cannot reach `restricted`,
  no canonical column holds a participant id, no restricted attribute reaches a
  log line or the snapshot, and the migration's grants come from constants.

---

## Step 2 — Feature Specification, Leakage Review, and the Baseline Model

**Status:** Not started

> **Goal:** Land the expected-outcome model as a versioned, inspectable contract
> and a deterministic fit. `data/reference/outcome_model.yaml` (specification
> `version` 1, `model_version` `expected-logit-v1`) names the three targets and
> their populations, every feature with its source, levels, reference, known-at
> rule, missing-data rule, and leakage justification, the explicit exclusions
> with their reasons, the L2 penalty, the solver limits, the temporal split, the
> seed, the bootstrap size, the pooling bounds, the thresholds, and the recovery
> tolerance; `judgemetrics.metrics.adjustment` loads and validates it
> (`spec.py`), builds one design row per eligible index event from the frame
> using, for every history feature, only rows strictly before the index case's
> filing and sorting by source-assigned keys (`features.py`), fits an
> L2-penalized logistic regression by iteratively reweighted least squares in
> NumPy (`logistic.py`), draws person-cluster bootstrap replicates from seeded
> streams (`resample.py`), computes the temporal-split calibration, Brier score,
> ROC AUC, calibration slope, and feature stability (`diagnostics.py`), and
> writes each fitted model as a canonical JSON artifact, content-addressed and
> written once under the snapshot directory (`artifacts.py`, `fit.py`);
> migration `0009_outcome_models` records every model in `outcome_model`;
> `judgemetrics models fit|list|show|verify` operates them; `numpy` becomes the
> one new runtime dependency; and property tests prove the features never read
> the future and are invariant to UUID relabelling, while the artifact
> inspection test proves no artifact holds a person-level row. This step lands
> the model; Step 3 turns its predictions into expected counts, ratios, pooled
> estimates, and intervals.

**Branch:** `feature/phase04-step2-outcome-model`

**Deploys:** local database (`uv run poe migrate`) and the local snapshot
directory — the merge carries migration `0009_outcome_models`; the operator
applies it and runs `uv run judgemetrics models fit`, which fits every model for
the latest demo snapshot and writes the artifacts under
`data/snapshots/<hash>/models/`. `/api/v1/ready` reports the new head.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                                  |
| ------------ | ------------------------------------------------------ |
| Model        | Opus 5.5                                               |
| Backup       | GPT-5.6 Terra — Codex · Intelligence Extra High        |
| Platform     | Claude Code                                            |
| Effort       | Extra High (raised from Claude Code's default Medium)  |
| Thinking     | On                                                     |
| Conversation | **New**                                                |

**Model rationale:** This step writes a penalized maximum-likelihood solver, a
leakage-safe feature builder, and a deterministic artifact format whose
correctness every adjusted figure depends on, and it must reason about
statistical methodology (calibration, temporal validation, the leakage review)
as much as about code — PRIMARY `coding`, SECONDARY `knowledge`, High complexity
with novel problem-solving and multi-step verification (optimality conditions,
order invariance, the strictly-before rule). Opus 5.5 is S-tier in coding and
S-tier in knowledge (HLE 61.4% and SciCode 66.9 at max); Fable 5.1 ties it on
both rows and on coverage, and the output-price tie-breaker selects Opus 5.5
($20 against $50). The Platform is Claude Code on the $200 claude.ai Max
subscription (weekly pool at `headroom`); under the operator's `capped` posture
the flat-funding gate is closed and effort follows the ladder, so this step
raises Claude Code's default `Medium` to `Extra High` for the novel-problem and
multi-step-proof conditions, and stops short of `Max` because the solver's own
optimality check and the property tests, not reasoning depth, are what catch an
error. Thinking `On`. Backup: GPT-5.6 Terra on Codex (the $100 ChatGPT Pro 5x
pool), S-tier in coding and A-tier in knowledge from OpenAI, where the coverage
tie-break (seven S or A ratings against GPT-5.6 Sol's six) selects it among the
OpenAI models, at Intelligence `Extra High` for the same conditions.
Conversation is New per phase-boundary hygiene.

```xml
<task>
  <lifecycle>
    This step MUST follow all six
    stages, in order. Stages 1, 3,
    4, 5, 6 are AS BINDING as any
    `<requirement>` below. Do not
    emit the Stage 6 completion line
    until the PR is merged and every
    acceptance criterion for this
    step is affirmatively met.

    1. CREATE THE BRANCH. Before any
       Read / Edit / Bash, run `git
       checkout -b
       feature/phase04-step2-outcome-model`
       from a clean, up-to-date
       `main`. The exact branch name
       is in this step's
       `**Branch:**` line above. If
       the Worktree rule applies,
       use `git fetch origin && git
       worktree add -b <branch>
       .worktrees/<slug>
       origin/main` instead, then
       bootstrap the worktree.

    2. WORK ON THE BRANCH. All
       commits land here. `main` is
       protected with
       `enforce_admins: true` —
       direct pushes will be
       rejected. Pass the security
       gate before every commit.
       Stop the local API before `uv
       run poe gate` or `git
       commit`.

    3. OPEN THE PR, THEN MARK THE
       STEP. `gh pr create --base
       main --head <branch>` with a
       Conventional Commits title
       and a body that references
       this roadmap step and its
       acceptance criteria. One PR
       per step. Then, in this
       roadmap file: set this step's
       `**Status:**` line (directly
       under its heading) to
       `Complete — PR #<n>
       (<YYYY-MM-DD>)`, append ` ✅`
       to the step's `## Step`
       heading, and set its Summary
       Table Status cell to
       `Complete — PR #<n>`. Commit
       that edit on the step branch
       and push — the PR carries its
       own completion mark, so the
       roadmap on `main` marks this
       step complete exactly when
       the PR merges (Status rule).
       Same commit: on the phase's
       first step, set this
       roadmap's phase-level
       `**Status:**` (under its
       title) and the parent project
       roadmap's Phase 4
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 4` heading.

    4. WAIT FOR GREEN CHECKS, THEN
       SQUASH-MERGE. Every required
       check must pass. If the PR
       falls behind main, refresh
       with `gh pr update-branch
       --rebase` — never merge main
       into the branch
       (`required_linear_history:
       true`). Once green: `gh pr
       merge <PR> --squash
       --delete-branch`. If this
       step's `**Deploys:**` line
       names a surface, the merge is
       not the finish line: run the
       Deployed & verified check
       against the local environment
       before declaring the step
       complete.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree, `git
       worktree remove <path>` FIRST
       — the branch prune fails
       while the branch is checked
       out there.

    6. DISPOSE OF EVERY FINDING,
       DECLARE COMPLETION, THEN NEW
       CONVERSATION. First send
       every finding this step
       surfaced to its destination
       (Triage rule): a note for a
       later step → edit that step's
       <task> block now; spec rot →
       edit this roadmap now; a bug
       → fixed in-step or an issue
       number; a judgement call in
       the diff → the PR body; a
       process lesson → written
       where the next conversation
       reads it (AGENTS.md or this
       roadmap); a data-semantics
       finding → the registry or
       model-specification entry,
       version bumped; a data-access
       question → a row in
       docs/ROADMAP.md. Update
       docs/ROADMAP.md (completed
       items, known issues, next
       milestones). A finding you
       can only describe is NOT
       disposed of, and counts as an
       unmet criterion. Only once
       the PR is merged — and `main`
       therefore carries this step's
       `Complete` Status line —
       every acceptance criterion is
       affirmatively met, and every
       finding has a destination,
       say so plainly: end your
       final response with an
       explicit, unhedged completion
       line — verbatim shape "Step 2
       is complete. You can now move
       on to Step 3." That line is
       the LAST line of the
       response. NOTHING follows it
       — no "Follow-ups
       (non-blocking)", "Notes",
       "Next", "worth a glance", or
       suggested improvements. A
       short ledger may PRECEDE it,
       one entry per finding naming
       its destination (issue #,
       file edited, PR body) — never
       an open item. If any
       criterion is unmet or any
       finding has no destination,
       state plainly that the step
       is NOT complete, name what is
       outstanding, and omit the
       completion line. "Done" means
       done. Then, for
       phase-boundary hygiene, the
       operator closes this session
       and opens a fresh one before
       Step 3.
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
       credentials, API keys,
       tokens, or real PII in the
       diff (gitleaks /
       detect-secrets or the
       project's equivalent).
       Secrets go in the secrets
       manager, never in source or
       committed env files. In this
       step: the specification, the
       artifacts, and the tests
       carry no person material;
       artifacts are written under
       the git-ignored snapshot
       directory and never
       committed; no model file
       enters `tests/fixtures/`.

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. In
       this step: the specification
       is loaded with
       `yaml.safe_load` only;
       artifacts are written and
       read as JSON only (never
       `pickle`, `numpy.load`, or
       `eval`); an artifact path is
       built from a snapshot hash
       and a content hash each
       validated as 64 hexadecimal
       characters before it becomes
       a path, and is resolved under
       `JUDGEMETRICS_SNAPSHOT_DIR`;
       files are created exclusively
       (`open(path, "xb")`) and
       never overwritten; migration
       `0009` builds its grants from
       module constants.

    3. DEPENDENCY AUDIT. Any new or
       bumped dependency passes the
       audit (pip-audit / npm audit
       / osv-scanner); no
       known-vulnerable, yanked, or
       typo-squatted package. In
       this step: `numpy` is added
       to `[project].dependencies`
       with `uv add`, locked with
       hashes in `uv.lock`, and
       passes `pip-audit --strict
       --require-hashes`
       (`scripts/audit_deps.py`); no
       other package is added (no
       scipy, scikit-learn,
       statsmodels, or pandas); the
       API image still passes the
       Trivy HIGH/CRITICAL scan with
       the new wheel.

    4. SENSITIVE-DATA REVIEW.
       Whatever this step touches
       stays least-privilege,
       encrypted in transit + at
       rest, and out of logs and
       client bundles. If the step
       adds a data path, name how
       PII/secrets are protected. In
       this step: a feature row
       exists only in memory inside
       a fit and is never written,
       logged, or returned; an
       artifact holds coefficients,
       counts, bins, and replicate
       summaries only — no array
       whose length is the number of
       index events or persons, no
       UUID-shaped string, and no
       64-hex string other than the
       snapshot hash (the artifact
       inspection test);
       `outcome_model` holds no
       person-level column, and the
       app role receives `SELECT` on
       it and nothing on any
       restricted table; no module
       under `metrics/` reads the
       `restricted` schema or names
       a restricted attribute (the
       recursive guard); log lines
       name the target, window,
       status, and counts only.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean. This is the safety net
    that stops a security issue from
    reaching the branch, the PR, or
    `main`.
  </security>

  <context>
    JudgeMetrics. Phase 4. Step 2:
    feature specification, leakage
    review, and the baseline model.

    Current state (as of Phase 4
    Step 1):

    - The synthetic world is at
      `GENERATOR_VERSION` `3` with
      planted, observable-only
      confounding in judge
      assignment, per-judge release,
      new-case, and
      failure-to-appear effects, and
      the age-band and
      `synthetic_group` controls;
      `truth/effects.json` records
      every planted parameter and
      the oracle expected counts per
      judge, target, and window. The
      demo dataset
      (`data/synthetic/20260916`) is
      regenerated at version 3.
    - Note from Step 1 (the history
      instant): the generator's risk
      features read the person's rows
      strictly before 00:00 UTC of
      the index case's filing date —
      the instant the frame's
      `cases.filed_at` carries — not
      the charge's business-hour
      `filed_at`; `prior_cases`
      counts other cases filed on an
      earlier date, `pending_case`
      one whose case disposition (the
      latest `disposed_at` of its
      disposed charges) is null or at
      or after that instant, and
      `lead_severity` breaks no tie
      the generator reads (it takes
      the most severe level). Evaluate
      every history feature at that
      same instant so the model's
      features are exactly what
      assignment read
      (`synthetic/effects.py`
      `risk_features`;
      `test_synthetic_effects.py`
      recomputes them on the final
      world). The next filing's
      exponent also carries `3.0 · R`
      (R the index case's risk index;
      docs/SYNTHETIC_DATA.md "Planted
      effects").
    - The analytic frame
      (`metrics/frame.py`) holds
      `cases`, `assignments`,
      `charges` (with `severity`,
      `offense_category`,
      `disposition`,
      `disposition_actor`,
      `source_row_id`), `decisions`,
      `sentences`, `events`,
      `justice_events` (stored
      failures to appear and
      revocations plus `new_case`,
      `new_charge`, and
      `reconviction` derived from
      the merged person's charges),
      and `persons` (id only). The
      snapshot
      (`metrics/snapshot.py`)
      already exports `courts(id,
      jurisdiction_id)`, which the
      frame does not carry. Exposure
      is deferred by every
      incarceration term of the
      person (methodology `0.2`).
    - The pretrial-release cohort,
      its followed members per
      window, and the attribution
      gate for pretrial decisions
      are computed by
      `metrics/index_events.py`,
      `metrics/exposure.py`,
      `metrics/windows.py`,
      `metrics/censoring.py`, and
      `metrics/attribution.py`; Step
      2 reuses them rather than
      re-deriving a cohort.
    - The restricted attributes live
      in
      `restricted.party_attribute`
      (migration `0008`); the
      recursive guard forbids any
      module under `metrics/` to
      read the `restricted` schema
      or name a restricted
      attribute.
    - `uv.lock` holds no numeric
      library; the engine is Polars,
      DuckDB, and the standard
      library. The head is revision
      `0008`.

    Files to read (every file before
    drafting):
    - src/judgemetrics/metrics/frame.py,
      snapshot.py, attribution.py,
      index_events.py, exposure.py,
      windows.py, censoring.py,
      compute.py, publish.py,
      engine.py (the frame, the
      cohorts, the conventions).
    - src/judgemetrics/metrics/registry.py
      and
      data/reference/metric_registry.yaml
      (the loader and validation
      pattern the specification
      mirrors).
    - data/reference/case_vocabulary.yaml
      and
      src/judgemetrics/normalization/vocabulary.py
      (severities, categories,
      dispositions, the restricted
      kinds).
    - src/judgemetrics/synthetic/truth.py
      and docs/SYNTHETIC_DATA.md
      "Planted effects" (the
      generator's functional forms
      the specification's features
      mirror).
    - src/judgemetrics/cli.py (the
      `metrics` group, role
      selection, exit codes).
    - src/judgemetrics/db/models/metrics.py
      and
      alembic/versions/0005_metric_registry_and_snapshots.py
      (the snapshot row and the
      grant pattern).
    - src/judgemetrics/config.py
      (`snapshot_dir`, role URLs).
    - tests/property/support.py,
      tests/property/test_frame_invariants.py,
      tests/unit/test_metrics_snapshot.py
      (in-memory frames, the
      property profiles, the
      restricted-name guard).
    - infra/docker/api.Dockerfile
      and the `container` job in
      .github/workflows/ci.yml (the
      image and the smoke test the
      new dependency must pass).
    - The brief's
      `<risk_adjustment>` element
      (docs/brief/judgemetrics-master-project-specification.xml:
      the candidate features,
      `excluded_or_sensitive_features`,
      `model_validation`).
  </context>

  <goal>
    Ship
    `data/reference/outcome_model.yaml`,
    the
    `judgemetrics.metrics.adjustment`
    package (`spec`, `features`,
    `logistic`, `resample`,
    `diagnostics`, `artifacts`,
    `fit`), the frame's `courts`
    table, migration
    `0009_outcome_models`,
    `judgemetrics models
    fit|list|show|verify`, and the
    `numpy` dependency, with the
    tests that prove the solver
    optimal, the features
    leakage-free and
    order-invariant, the fit
    reproducible from a snapshot and
    a seed, and the artifacts free
    of person-level rows.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      The specification
      `data/reference/outcome_model.yaml`
      (`version: 1`, `model_version:
      expected-logit-v1`), loaded
      once by
      `metrics/adjustment/spec.py`
      with `yaml.safe_load` and
      validated like the registry
      (every field required or
      optional by name; an unknown
      field rejected; every level
      checked against the
      vocabulary). Blocks:
      - `targets`:
        `pretrial_release`
        (population:
        judge-attributed
        discretionary pretrial
        decisions under the
        `pretrial_decisions` gate;
        outcome: released),
        `new_case` and
        `failure_to_appear`
        (population: the
        pretrial-release cohort;
        outcome: the event within
        each of the six windows,
        fitted over the members
        followed for that window;
        one model per window).
      - `features`: each with
        `name`, `source` (the frame
        columns it reads), `kind`
        (`categorical`, `binary`,
        `banded_count`), `levels` or
        `bands`, `reference`,
        `known_at` (the instant it
        is evaluated at), `missing`
        (`level` or `exclude`), and
        `leakage` (one sentence on
        why it is known before the
        decision). Every history
        feature is evaluated at the
        index case's filing
        (`known_at: filed_at`),
        which precedes every index
        event of the case and is the
        instant the generator's risk
        index reads (Step 1). The v1
        set: `lead_severity` (the
        most severe charge of the
        index case against the
        person, severity ties broken
        by the source's charge id),
        `lead_category`,
        `charge_count` (1, 2, 3+),
        `prior_cases` (0, 1, 2, 3+;
        the person's other cases
        filed strictly before the
        index case's filing),
        `prior_convictions` (0, 1,
        2+; other cases with a
        conviction disposed strictly
        before that filing),
        `prior_failures_to_appear`
        (0, 1+; strictly before that
        filing; dropped for a source
        that cannot observe the
        outcome), `pending_case`
        (another case of the person
        filed before that filing and
        not disposed by it),
        `history_truncated` (the
        filing falls within 1,095
        days of the coverage start,
        so priors are undercounted),
        `court`, `jurisdiction`
        (dropped when the source has
        one), and `calendar_year`
        (the index event's year).
      - `excluded`: every restricted
        attribute (read from the
        vocabulary's
        `restricted_attribute`
        kinds, so no module under
        `metrics/` names one), the
        judge (the subject of
        comparison), the release
        type, conditions, and bond
        (the judge's own decision,
        so a mediator of any later
        outcome), anything at or
        after the index time
        (dispositions, sentences,
        later events), and the
        latent propensity
        (unobservable by
        construction) — each with
        its reason, rendered by
        Step 4.
      - `model` (`penalty: l2`,
        `lambda`, the intercept
        unpenalized,
        `max_iterations`,
        `tolerance`),
        `temporal_split` (the test
        set is each target's index
        events at or after the 75th
        percentile of index time; a
        calendar year unseen in
        training is scored at the
        last training year's level),
        `seed`, `bootstrap`
        (`replicates: 500`, person
        clusters, percentile
        interval at 95%), `pooling`
        (`family: gamma_poisson`,
        the shape's search bounds
        and grid), `thresholds`
        (`minimum_events_per_column:
        5`, `minimum_cohort: 30`,
        `minimum_expected: 5`), and
        `recovery` (every tolerance
        Steps 3 and 4 assert: the
        targets and windows the
        recovery test fits, the
        minimum followed cohort a
        judge needs to enter it, the
        Spearman minimum per target,
        the effect magnitude above
        which the sign must agree,
        the minimum correlation of
        expected counts with the
        oracle's, the minimum share
        of intervals covering the
        true ratio, and the negative
        control's band around 1 —
        initial values here, which
        Step 3 sets from its run). A
        change to any value that
        alters a fitted model or a
        published figure bumps
        `version`; a `recovery`
        tolerance alters neither and
        does not; the rule is
        written in the file's
        header, as the registry's
        is.
    </requirement>

    <requirement>
      `metrics/adjustment/features.py`:
      `design_rows(frame, spec,
      target, window) ->
      DesignFrame` — one row per
      eligible index event (reusing
      `index_events`,
      `with_exposure`, and the
      follow-up rule for windowed
      targets), the outcome, and the
      feature levels computed from
      rows strictly before each
      feature's known-at instant
      (the index case's filing for
      every history feature), then
      the one-hot design matrix with
      the reference levels dropped,
      as a `numpy.ndarray` in
      float64. Rows sort by
      `(index_at, the index case's
      earliest charge
      source_row_id)`; each person's
      cluster key is the earliest
      `source_row_id` among the
      merged person's charges; level
      order is fixed by the
      specification, and
      data-dependent orders (courts,
      years) sort by count and then
      by source-assigned keys, never
      by UUID. Add `courts(id,
      jurisdiction_id)` to the frame
      (`frame.SCHEMAS`, the snapshot
      loader, `Frame.empty`, and
      `tests/property/support.frame_from_world`,
      which Step 3's recovery test
      builds its frame with), which
      the snapshot already exports.
      Every group-by sorts
      explicitly afterwards (Polars
      does not keep group order by
      default). No function reads a
      restricted table.
    </requirement>

    <requirement>
      `metrics/adjustment/logistic.py`:
      `fit_logistic(design, outcome,
      *, lam, max_iterations,
      tolerance) -> LogisticFit` —
      Newton-Raphson on the
      L2-penalized log-likelihood
      with the intercept
      unpenalized, a fixed iteration
      order, a step-halving line
      search, and a stop when the
      gradient's infinity norm falls
      below the tolerance; the
      result carries the
      coefficients, the iterations,
      the final gradient norm, and
      `converged`; `predict(fit,
      design) -> ndarray`. No global
      state, no randomness, no
      thread-dependent reduction the
      tests can observe;
      coefficients are rounded to 12
      significant digits when
      serialized.
    </requirement>

    <requirement>
      `metrics/adjustment/resample.py`:
      `replicates(clusters, *, seed,
      stream, count) ->
      Iterator[ndarray]` —
      person-cluster bootstrap
      weights (cluster keys sorted,
      one `random.Random` per stream
      derived as `synthetic/rng.py`
      derives its streams, from
      `sha256(f"{seed}:{stream}")`,
      drawn only through
      `random()`-based helpers), so
      the replicates depend on the
      seed and the source-assigned
      keys alone.
    </requirement>

    <requirement>
      `metrics/adjustment/diagnostics.py`:
      for the temporal split's test
      set — the Brier score and its
      skill against the training
      base rate, ROC AUC by the
      Mann–Whitney statistic with
      ties averaged (a secondary
      diagnostic), ten calibration
      bins at the
      predicted-probability deciles
      (mean predicted and observed
      rate per bin), calibration in
      the large (observed over
      expected), and the calibration
      slope (a one-feature logistic
      fit of the outcome on the
      logit of the prediction); and,
      over the bootstrap replicates,
      feature stability (each
      coefficient's mean, standard
      deviation, and share of
      replicates agreeing in sign).
      Missing-data sensitivity is
      Step 4's; this module exposes
      the complete-case refit it
      needs
      (`refit_complete_cases`).
    </requirement>

    <requirement>
      `metrics/adjustment/fit.py`
      and `artifacts.py`:
      `fit_frame(frame, spec, *,
      seed, source) ->
      list[FittedModel]` over one
      source's frame, in memory
      (Step 3's recovery test and
      Step 4's control test call it
      on `frame_from_world` frames),
      and `fit_models(snapshot,
      spec, *, seed) ->
      list[FittedModel]`, which
      builds each source's frame
      from the snapshot, calls
      `fit_frame`, and writes the
      artifacts — per source,
      target, and window: the
      published fit over every
      eligible event, the
      temporal-split fit and its
      diagnostics, and one refit per
      bootstrap replicate (a
      `FittedModel` carries the
      replicate coefficients, which
      Step 3's interval reads from
      it or from the artifact); a
      target with fewer events than
      `minimum_events_per_column`
      times the design width, or a
      solver that does not converge,
      is recorded with status
      `insufficient_events` or
      `not_converged` and no
      coefficients. Each fitted
      model becomes a canonical JSON
      artifact (sorted keys, fixed
      float formatting,
      `artifact_version` 1; the
      specification and model
      versions, the code version,
      the snapshot hash, the
      source's register name — not
      its UUID — the target, the
      window, the seed, the design
      columns and coefficients, the
      training counts and time
      range, the split cutoff, the
      diagnostics, the stability
      summary, the replicate
      coefficients, and the solver
      trace) whose sha256 is its id,
      written once to
      `<snapshot_dir>/<snapshot
      hash>/models/<content
      hash>.json`.
    </requirement>

    <requirement>
      Migration
      `alembic/versions/0009_outcome_models.py`:
      `outcome_model` (`id` UUID;
      `content_hash` CHAR(64)
      unique; `snapshot_id` FK to
      `metric_snapshot`; `source_id`
      FK to `source`;
      `spec_version`,
      `model_version`, `target`,
      `window_days` (null for the
      release target), `seed`,
      `status`; `n_train`,
      `events_train`, `n_test`,
      `events_test`; `train_start`,
      `train_end`, and
      `split_cutoff` (timestamptz,
      the training range and the
      temporal cutoff);
      `diagnostics` JSONB (the
      summary — Brier, skill, AUC,
      calibration in the large,
      slope — and the ten
      calibration bins);
      `coefficients` JSONB (per
      design column: the level, the
      estimate, the bootstrap
      standard deviation, and the
      sign agreement), so a model
      card is served from the
      database without reading an
      artifact from disk;
      `storage_uri`; `code_version`;
      `fitted_at`; unique
      `(snapshot_id, source_id,
      spec_version, target,
      window_days, seed)` `NULLS NOT
      DISTINCT`), `SELECT` to the
      app role and DML to the ingest
      role from constants, the ORM
      model, `uv run alembic check`
      clean, and the head pins at
      `0009`.
    </requirement>

    <requirement>
      CLI group `judgemetrics
      models` (ingest role for
      writes, app role for reads,
      exit codes as `metrics`): `fit
      [--snapshot HASH] [--json]`
      (fits every missing model of
      the latest or the named
      snapshot; idempotent — a
      second run fits nothing),
      `list [--snapshot HASH]
      [--json]`, `show <id or
      content hash> [--json]` (the
      model card: design columns and
      coefficients, counts,
      diagnostics; never
      `storage_uri`), and `verify
      [--snapshot HASH] [--refit]
      [--json]` (every artifact
      exists and hashes to its row's
      `content_hash`; with
      `--refit`, a fresh fit
      reproduces every artifact byte
      for byte; exit 1 on any
      mismatch, naming the model and
      the field).
    </requirement>

    <requirement>
      The dependency: `uv add
      numpy`; the lock refreshed
      with hashes; the container
      smoke in
      `.github/workflows/ci.yml`
      imports
      `judgemetrics.metrics.adjustment.logistic`
      inside the API image; mypy
      strict passes with NumPy's own
      annotations.
    </requirement>

    <requirement>
      Add
      tests/unit/test_outcome_model_spec.py:
      - test_the_specification_loads_and_validates.
      - test_a_restricted_attribute_is_rejected_as_a_feature
        (every
        `restricted_attribute` kind
        from the vocabulary).
      - test_an_excluded_or_unknown_field_is_rejected.
      - test_every_feature_states_known_at_and_leakage.
    </requirement>

    <requirement>
      Add
      tests/unit/test_logistic.py:
      - test_the_penalized_gradient_vanishes_at_the_solution.
      - test_an_unpenalized_saturated_fit_equals_the_group_means.
      - test_a_larger_penalty_shrinks_every_coefficient.
      - test_complete_separation_stays_finite_under_the_penalty.
      - test_two_fits_are_byte_identical.
      - test_non_convergence_is_reported.
    </requirement>

    <requirement>
      Add
      tests/unit/test_adjustment_features.py
      (hand-built frames): prior
      cases, prior convictions,
      prior failures to appear, and
      the pending-case indicator at
      the boundaries (an event
      exactly at the filing instant
      is excluded); the
      lead-severity tie-break by
      charge id;
      `history_truncated`; the
      missing-level rule; the
      reference levels dropped.
    </requirement>

    <requirement>
      Add
      tests/property/test_feature_leakage.py
      (Hypothesis over `TINY`
      worlds): removing every row at
      or after an index event's
      known-at instant (its case's
      filing) never changes that
      event's feature row;
      relabelling every UUID in the
      frame leaves the design
      matrix, the fitted
      coefficients, and the
      replicate draws identical.
    </requirement>

    <requirement>
      Add
      tests/unit/test_model_diagnostics.py
      and
      tests/unit/test_model_artifacts.py:
      AUC against brute-force pair
      counting with ties; the Brier
      score; the decile bins; the
      calibration slope near 1 on
      data drawn from the fitted
      model; the temporal cutoff;
      canonical serialization, the
      content hash, write-once (an
      equal artifact is a no-op, a
      different one at an existing
      path raises); and the artifact
      inspection test over every
      artifact a fit writes (no
      array as long as the event or
      person count, no UUID-shaped
      string, no 64-hex string other
      than the snapshot hash, no key
      naming a person, case,
      decision, or participant).
    </requirement>

    <requirement>
      Add
      tests/integration/test_outcome_models.py
      (the golden snapshot through
      the existing `golden_metrics`
      fixture): `models fit` writes
      one `outcome_model` row per
      source, target, and window
      with the status the golden
      cohorts allow; a second `fit`
      writes nothing; `models verify
      --refit` exits 0 and exits 1
      after an artifact byte is
      changed; the app role can
      `SELECT` `outcome_model` and
      cannot write it. Extend
      `purge_source` in
      `tests/integration/conftest.py`
      to delete a source's
      `outcome_model` rows after its
      observations and before its
      snapshots (the new foreign
      keys). Add `uv run
      judgemetrics models fit` and
      then `uv run judgemetrics
      models verify` after `metrics
      compute` in the `e2e` CI job —
      in this step `metrics compute`
      does not fit, so these lines
      are the demo seed's fitted
      path; from Step 3 the compute
      fits first and `models fit`
      finds nothing to do — and
      update
      `tests/unit/test_repo_hygiene.py`'s
      command-order pin.
    </requirement>

    <requirement>
      Documentation:
      `docs/ARCHITECTURE.md` "Risk
      adjustment" (the
      specification, the feature
      builder, the solver, the
      artifacts, order invariance),
      `docs/DATA_MODEL.md`
      (`outcome_model`, the frame's
      `courts`, the specification as
      the third versioned reference
      file), `README.md` (the
      `models` commands),
      `AGENTS.md`, and
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

### Step 2 acceptance criteria

- `data/reference/outcome_model.yaml` loads and validates; a restricted
  attribute, an excluded variable, or an unknown field is rejected; every
  feature states its known-at rule and leakage justification
  (`test_outcome_model_spec.py`).
- The penalized solver meets its optimality conditions, reproduces closed-form
  cases, shrinks under a larger penalty, stays finite under separation, reports
  non-convergence, and is byte-for-byte deterministic (`test_logistic.py`).
- No history feature reads a row at or after its index case's filing, and UUID
  relabelling leaves the design, the coefficients, and the replicates identical
  (`test_feature_leakage.py` under the `ci` profile;
  `test_adjustment_features.py`).
- The diagnostics match their references (`test_model_diagnostics.py`); every
  artifact passes the inspection test and is written once
  (`test_model_artifacts.py`).
- Migration `0009_outcome_models` round-trips; `uv run alembic check` is clean;
  `models fit` is idempotent and `models verify --refit` reproduces every
  artifact and fails on a changed byte (`test_outcome_models.py`); the `e2e` job
  runs `models fit` and `models verify` after `metrics compute` on the demo
  seed.
- `numpy` is the only new dependency, locked with hashes, audited clean, and
  imported by the container smoke test; `uv run poe check` passes and every
  required CI check is green.
- **Deployed & verified**: after `uv run poe migrate`, `GET
  http://localhost:8000/api/v1/ready` reports `alembic_current` `0009`; `uv run
  judgemetrics models fit` on the demo database writes thirteen `outcome_model`
  rows for the latest snapshot, `uv run judgemetrics models list` shows them
  with their status, and `uv run judgemetrics models verify --refit` exits 0.
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff — secret scan clean, `bandit` clean, and
  `pip-audit` clean with `numpy` added — and the model surface handles sensitive
  data per the project ROADMAP "Security & privacy strategy": artifacts are JSON
  under the snapshot directory with validated paths, hold no person-level row,
  and no module under `metrics/` touches the restricted schema.

---

## Step 3 — Expected Counts, Ratios, Partial Pooling, and the Recovery Test

**Status:** Not started

> **Goal:** Turn the fitted models into published, reproducible adjusted
> observations and prove they recover the planted answer. Registry version 2
> adds the kind `observed_expected` and three judge metrics —
> `pretrial_release_observed_expected` (releases among attributed discretionary
> decisions), `new_case_observed_expected` and
> `failure_to_appear_observed_expected` (outcomes among followed
> pretrial-release members, per window) — under methodology `0.3`;
> `metrics/adjustment/expected.py` sums each judge's predicted probabilities
> into the expected count, `pooling.py` fits the gamma–Poisson shape by maximum
> marginal likelihood over the judges and publishes the pooled ratio `(α + O) /
> (α + E)` with its pooling weight `E / (E + α)`, and `bootstrap.py` recomputes
> observed, expected, the shape, and the pooled ratio on every person-cluster
> replicate from the replicate coefficients Step 2 stored, giving the 95%
> percentile interval; migration `0010_adjusted_observations` adds
> `outcome_model_id`, `pooling_weight`, and `suppression_reason` to
> `metric_observation`; `compute.py`, `publish.py`, `verify.py`, and
> `provenance.py` handle the new kind (members are the cohort's decisions; the
> trace names the model and checks its artifact); `metrics compute` fits the
> snapshot's missing models first; pipeline step 13 leaves adjusted observations
> to the full compute; every public metrics response holds the kind out until
> Step 5; `/api/v1/ready` reports the latest snapshot's models; and
> `tests/golden/test_golden_adjusted.py` and
> `tests/golden/test_golden_recovery.py` prove the golden observations exact and
> reproducible and the planted judge ranking recovered within the
> specification's tolerance. This step publishes the estimator; Step 4 documents
> its validation before Step 5 shows it.

**Branch:** `feature/phase04-step3-observed-expected`

**Deploys:** local database (`uv run poe migrate`) and the local analytics
snapshot — the merge carries migration `0010_adjusted_observations`; the
operator applies it and runs `uv run poe compute-metrics`, which fits any
missing model and publishes the adjusted observations for the demo seed under
methodology `0.3`. `/api/v1/ready` reports the new head and the models; no
public metrics response serves an adjusted observation yet.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                                  |
| ------------ | ------------------------------------------------------ |
| Model        | Opus 5.5                                               |
| Backup       | GPT-5.6 Terra — Codex · Intelligence Extra High        |
| Platform     | Claude Code                                            |
| Effort       | Extra High (raised from Claude Code's default Medium)  |
| Thinking     | On                                                     |
| Conversation | **New**                                                |

**Model rationale:** This step implements an empirical-Bayes estimator and a
refitting bootstrap whose every digit must reproduce from a snapshot and a seed,
wires a new observation kind through compute, publish, verify, provenance, and
the ingest pipeline without breaking Phase 3's byte-for-byte guarantees, and
proves recovery of a planted answer — PRIMARY `coding`, SECONDARY `knowledge`,
High complexity with novel problem-solving and multi-step verification across
the engine, the migration, the API hold-out, and the golden suite. Opus 5.5 is
S-tier in coding and S-tier in knowledge (AA Intelligence Index 57.6 and HLE
61.4% at max); Fable 5.1 ties it on both rows and on coverage, and the
output-price tie-breaker selects Opus 5.5 ($20 against $50). The Platform is
Claude Code on the $200 claude.ai Max subscription (weekly pool at `headroom`);
with the flat-funding gate closed under the `capped` posture, effort follows the
ladder, and this step raises Claude Code's default `Medium` to `Extra High` for
the novel estimator and the cross-file proof obligations, not to `Max`, because
the recovery test and `metrics verify` are what catch an estimator error.
Thinking `On`. Backup: GPT-5.6 Terra on Codex (the $100 ChatGPT Pro 5x pool),
S-tier in coding and A-tier in knowledge from OpenAI, chosen over GPT-5.6 Sol by
the coverage tie-break, at Intelligence `Extra High`. Conversation is New per
phase-boundary hygiene.

```xml
<task>
  <lifecycle>
    This step MUST follow all six
    stages, in order. Stages 1, 3,
    4, 5, 6 are AS BINDING as any
    `<requirement>` below. Do not
    emit the Stage 6 completion line
    until the PR is merged and every
    acceptance criterion for this
    step is affirmatively met.

    1. CREATE THE BRANCH. Before any
       Read / Edit / Bash, run `git
       checkout -b
       feature/phase04-step3-observed-expected`
       from a clean, up-to-date
       `main`. The exact branch name
       is in this step's
       `**Branch:**` line above. If
       the Worktree rule applies,
       use `git fetch origin && git
       worktree add -b <branch>
       .worktrees/<slug>
       origin/main` instead, then
       bootstrap the worktree.

    2. WORK ON THE BRANCH. All
       commits land here. `main` is
       protected with
       `enforce_admins: true` —
       direct pushes will be
       rejected. Pass the security
       gate before every commit.
       Stop the local API before `uv
       run poe gate` or `git
       commit`.

    3. OPEN THE PR, THEN MARK THE
       STEP. `gh pr create --base
       main --head <branch>` with a
       Conventional Commits title
       and a body that references
       this roadmap step and its
       acceptance criteria. One PR
       per step. Then, in this
       roadmap file: set this step's
       `**Status:**` line (directly
       under its heading) to
       `Complete — PR #<n>
       (<YYYY-MM-DD>)`, append ` ✅`
       to the step's `## Step`
       heading, and set its Summary
       Table Status cell to
       `Complete — PR #<n>`. Commit
       that edit on the step branch
       and push — the PR carries its
       own completion mark, so the
       roadmap on `main` marks this
       step complete exactly when
       the PR merges (Status rule).
       Same commit: on the phase's
       first step, set this
       roadmap's phase-level
       `**Status:**` (under its
       title) and the parent project
       roadmap's Phase 4
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 4` heading.

    4. WAIT FOR GREEN CHECKS, THEN
       SQUASH-MERGE. Every required
       check must pass. If the PR
       falls behind main, refresh
       with `gh pr update-branch
       --rebase` — never merge main
       into the branch
       (`required_linear_history:
       true`). Once green: `gh pr
       merge <PR> --squash
       --delete-branch`. If this
       step's `**Deploys:**` line
       names a surface, the merge is
       not the finish line: run the
       Deployed & verified check
       against the local environment
       before declaring the step
       complete.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree, `git
       worktree remove <path>` FIRST
       — the branch prune fails
       while the branch is checked
       out there.

    6. DISPOSE OF EVERY FINDING,
       DECLARE COMPLETION, THEN NEW
       CONVERSATION. First send
       every finding this step
       surfaced to its destination
       (Triage rule): a note for a
       later step → edit that step's
       <task> block now; spec rot →
       edit this roadmap now; a bug
       → fixed in-step or an issue
       number; a judgement call in
       the diff → the PR body; a
       process lesson → written
       where the next conversation
       reads it (AGENTS.md or this
       roadmap); a data-semantics
       finding → the registry or
       model-specification entry,
       version bumped; a data-access
       question → a row in
       docs/ROADMAP.md. Update
       docs/ROADMAP.md (completed
       items, known issues, next
       milestones). A finding you
       can only describe is NOT
       disposed of, and counts as an
       unmet criterion. Only once
       the PR is merged — and `main`
       therefore carries this step's
       `Complete` Status line —
       every acceptance criterion is
       affirmatively met, and every
       finding has a destination,
       say so plainly: end your
       final response with an
       explicit, unhedged completion
       line — verbatim shape "Step 3
       is complete. You can now move
       on to Step 4." That line is
       the LAST line of the
       response. NOTHING follows it
       — no "Follow-ups
       (non-blocking)", "Notes",
       "Next", "worth a glance", or
       suggested improvements. A
       short ledger may PRECEDE it,
       one entry per finding naming
       its destination (issue #,
       file edited, PR body) — never
       an open item. If any
       criterion is unmet or any
       finding has no destination,
       state plainly that the step
       is NOT complete, name what is
       outstanding, and omit the
       completion line. "Done" means
       done. Then, for
       phase-boundary hygiene, the
       operator closes this session
       and opens a fresh one before
       Step 4.
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
       credentials, API keys,
       tokens, or real PII in the
       diff (gitleaks /
       detect-secrets or the
       project's equivalent).
       Secrets go in the secrets
       manager, never in source or
       committed env files. In this
       step: no fixture, test, or
       document gains person
       material; the recovery test
       builds its world in memory
       from the fixed demo seed and
       writes nothing.

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. In
       this step: artifacts are read
       as JSON through Step 2's
       validated paths only;
       migration `0010` adds its
       columns and check constraint
       from constants; the hold-out
       filters by kind in the SQL
       statement with bound
       parameters, never by string
       concatenation.

    3. DEPENDENCY AUDIT. Any new or
       bumped dependency passes the
       audit (pip-audit / npm audit
       / osv-scanner); no
       known-vulnerable, yanked, or
       typo-squatted package. This
       step adds no dependency. If
       one is added, it passes
       `pip-audit --strict
       --require-hashes`.

    4. SENSITIVE-DATA REVIEW.
       Whatever this step touches
       stays least-privilege,
       encrypted in transit + at
       rest, and out of logs and
       client bundles. If the step
       adds a data path, name how
       PII/secrets are protected. In
       this step: an adjusted
       observation's members are
       decisions — entity ids of
       public rows, never a person
       id; the per-person predicted
       probabilities and replicate
       weights exist only in memory;
       no public metrics response,
       provenance body, or compare
       page serves an
       `observed_expected` row until
       Step 5 (tests);
       `/api/v1/ready` reports
       counts and versions, never an
       artifact path or a model
       hash.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean. This is the safety net
    that stops a security issue from
    reaching the branch, the PR, or
    `main`.
  </security>

  <context>
    JudgeMetrics. Phase 4. Step 3:
    expected counts, ratios, partial
    pooling, and the recovery test.

    Current state (as of Phase 4
    Step 2):

    - Note from Step 1 (the planted
      answer's strength on the demo
      world, seed `20260916`): the
      oracle ratios (observed / the
      court-centered oracle
      `sum(p0)`) rank the centered
      effects with Spearman 0.944
      (release), 0.846 (365-day new
      case), and 0.933 (365-day
      failure to appear) over the
      judges with at least 30
      members; the raw 365-day
      new-case rates rank them at
      0.716. The adjusted ratios can
      only approach the oracle's, so
      set the `recovery` tolerances
      below those values, and expect
      the raw-versus-adjusted margin
      on the new-case target to be
      about 0.1 at best.
    - Note from Step 2 (the model
      as landed): `design_rows(frame,
      spec, spec.target(name),
      window)` takes the
      `TargetSpec`; `fit_frame(frame,
      spec, *, seed, source,
      only=None)` returns
      `FittedModel`s whose `design`
      holds, in memory only, per row
      `member_ids` (the decision
      ids), `judge_ids` (the judge
      the published gate attributed
      the row to), `clusters`, and
      `index_at` (UTC microseconds);
      `model.predict()` is p_i for
      those rows, and
      `replicate_coefficients` has
      one entry per replicate
      (`None` where a refit did not
      converge). The stream name is
      `resample.replicate_stream(target,
      window)`. `fit_models(snapshot,
      spec, *, seed, code_version,
      write, only)` renders and
      writes; `catalog.fit_snapshot`
      fits only the models a
      snapshot lacks and records
      them, so the compute's fitting
      should go through it rather
      than refit. The
      events-per-column gate counts
      the limiting class (the fewer
      of outcomes and non-outcomes)
      against every column, the
      intercept included: every
      golden model is
      `insufficient_events` (the
      release design has 19 limiting
      events against 115 needed) and
      every demo model is `fitted`
      (thirteen, about 30 s with 500
      replicates), so golden
      adjusted observations can only
      carry the
      `insufficient_events`
      suppression reason and the
      recovery test needs the demo
      world. Out of time the demo
      release model is calibrated
      (AUC 0.81, observed over
      expected 1.005, slope 1.19)
      but the new-case models are
      weak (AUC 0.49-0.55, slope
      0.1-0.6; in-sample AUC
      0.61-0.64); the recovery test
      compares in-sample expected
      counts, so expect its new-case
      margin to stay modest.
    - `data/reference/outcome_model.yaml`
      (version 1,
      `expected-logit-v1`) defines
      the three targets, the
      features, the exclusions, the
      penalty, the temporal split,
      the seed,
      `bootstrap.replicates` 500,
      the `pooling` bounds, the
      `thresholds`
      (`minimum_events_per_column`
      5, `minimum_cohort` 30,
      `minimum_expected` 5), and the
      `recovery` tolerances.
    - `judgemetrics.metrics.adjustment`
      fits one model per source,
      target, and window for a
      snapshot (`fit.fit_models`),
      each a canonical JSON artifact
      under
      `<snapshot_dir>/<hash>/models/`
      holding the published
      coefficients, the
      temporal-split diagnostics,
      the stability summary, and the
      coefficients of every
      bootstrap replicate;
      `outcome_model` rows record
      them (migration `0009`);
      `judgemetrics models
      fit|list|show|verify` operate
      them; the `e2e` job runs
      `models verify` on the demo
      seed.
    - `metric_observation` has the
      reserved `expected_count`
      Numeric(14,4), `expected_rate`
      Numeric(9,6), and
      `standardized_ratio`
      Numeric(9,6), always null;
      `publish.VERIFIED_COLUMNS`
      omits them; `ObservationDraft`
      has no field for them. The
      bounds are Numeric(9,6).
    - The registry is `version` 1,
      methodology `0.2`, with the
      kinds `count`, `share`,
      `windowed_rate`, `survival`,
      `distribution`, `median` in
      `registry.KINDS`; the API's
      `MetricKind` literal lists the
      same six, and an observation
      of another kind reaching
      `services.metrics.observation_from_row`
      fails validation (a 500 on the
      subject route).
    - The web places every registry
      metric on the judge page by
      its `index_event` or under
      "Other metrics"
      (`web/lib/metrics.ts`), so a
      new definition served by `GET
      /api/v1/metrics` would render
      at once through `MetricStat`'s
      default branch as a plain
      rate.
    - Pipeline step 13
      (`ingest/runner.recompute_metrics`)
      recomputes the impacted
      subjects inside the ingest
      transaction through
      `engine.compute_and_publish`.
    - The head is revision `0009`.

    Files to read (every file before
    drafting):
    - data/reference/outcome_model.yaml
      and
      src/judgemetrics/metrics/adjustment/
      (every module).
    - src/judgemetrics/metrics/registry.py,
      compute.py, suppression.py,
      publish.py, verify.py,
      provenance.py, engine.py,
      methodology.py (the dispatch,
      the draft, the verified
      columns, the trace, the
      renderer).
    - data/reference/metric_registry.yaml
      (the entry format; the
      header's version rule).
    - src/judgemetrics/ingest/runner.py
      (`recompute_metrics`,
      `impacted_subjects`).
    - src/judgemetrics/schemas/metrics.py,
      services/metrics.py,
      repositories/metrics.py,
      api/routes/metrics.py,
      api/routes/health.py (the
      kinds, the registry response,
      the subject and compare
      queries, the provenance route,
      `/ready`).
    - src/judgemetrics/cli.py
      (`metrics compute|verify`,
      `provenance trace`).
    - src/judgemetrics/db/models/metrics.py
      and
      alembic/versions/0005_metric_registry_and_snapshots.py.
    - tests/golden/test_golden_metrics.py,
      tests/golden/truth_map.py,
      tests/golden/test_public_contract.py,
      tests/integration/test_api_metrics.py,
      tests/integration/test_query_counts.py,
      tests/integration/test_synthetic_ingest.py,
      tests/unit/test_metric_registry.py,
      tests/unit/test_methodology_render.py,
      tests/property/support.py.
    - tests/fixtures/golden/truth/effects.json
      and docs/SYNTHETIC_DATA.md
      "Planted effects" (the known
      answer).
    - docs/ARCHITECTURE.md "Metrics
      engine" and "Risk adjustment",
      docs/DATA_MODEL.md "Metric
      registry", docs/PROVENANCE.md.
  </context>

  <goal>
    Ship registry version 2 with the
    kind `observed_expected` and its
    three metrics under methodology
    `0.3`, `expected.py`,
    `pooling.py`, `bootstrap.py`,
    migration
    `0010_adjusted_observations`,
    the new kind through compute,
    publish, verify, and the
    provenance trace, step 13's
    exemption, the public hold-out,
    the models on `/api/v1/ready`,
    and the golden adjusted and
    recovery tests.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Registry version 2
      (`data/reference/metric_registry.yaml`,
      `methodology_version: "0.3"`):
      the kind `observed_expected`
      in `registry.KINDS`, the unit
      `ratio`, and the field
      `adjustment` (`target`, the
      specification target the
      metric reads, and
      `minimum_expected`), required
      for the new kind and rejected
      for every other. Three
      entries, `subject_types:
      [judge]`,
      `suppression_threshold: 30`,
      `version: "1"`, each with
      prose `description`,
      `numerator` (the observed
      count), `denominator` (the
      model-expected count),
      `eligibility`, and
      `attribution` exactly as the
      descriptive metric they
      adjust:
      `pretrial_release_observed_expected`
      (population
      `pretrial_decisions`, the
      `pretrial_decisions` gate;
      outcome released; no window),
      `new_case_observed_expected`
      and
      `failure_to_appear_observed_expected`
      (population `index_events`,
      index event
      `pretrial_release`, outcome
      `new_case` or
      `failure_to_appear`, the six
      windows, followed members
      only). Append `("0.3",
      "Observed-to-expected ratios
      with partial pooling and
      bootstrap intervals are
      defined and computed for three
      judge metrics; they are not
      served until the validation
      that methodology 1.0
      publishes.")` to `CHANGELOG`;
      `KIND_TEXT` gains the kind;
      the file header's suppression
      rationale gains the new kind's
      threshold and minimum expected
      count with their reasons (a
      ratio of two small counts is
      unstable well above the ten
      members a share needs, and an
      expected count below five
      makes the ratio a function of
      a handful of predicted
      events); re-render
      `docs/METHODOLOGY.md`; update
      the registry and methodology
      pins.
    </requirement>

    <requirement>
      `metrics/adjustment/expected.py`:
      for a metric, a snapshot's
      source, and a judge subject,
      the members (the judge's
      attributed decisions, or the
      judge's pretrial-release
      cohort followed for the
      window), `O` (their outcomes),
      `E` (the sum of the model's
      predicted probabilities over
      the same members, from the
      published coefficients), and
      `n`. The predictions come from
      one design built over every
      eligible event of the source,
      so every judge is scored by
      the same model.
    </requirement>

    <requirement>
      `metrics/adjustment/pooling.py`:
      `fit_shape(observed, expected,
      *, bounds, grid) -> ShapeFit`
      — the gamma–Poisson
      (negative-binomial) marginal
      log-likelihood over the judges
      with `E > 0`, evaluated with
      `log Γ(α + O) − log Γ(α) =
      Σ_{k<O} log(α + k)` (exact for
      integer counts, no scipy),
      maximized on the log-spaced
      grid and refined by
      golden-section search within
      the bounds; a maximum at the
      upper bound is reported as
      `pooled_fully` (no
      between-judge variation
      detectable). `pooled_ratio(O,
      E, α) = (α + O) / (α + E)` and
      `pooling_weight(E, α) = E /
      (E + α)`. Every judge with
      `E > 0` informs the shape,
      suppressed or not; a
      suppressed judge's row is
      stored with its figures and
      its reason, and every public
      surface withholds the figures
      (Phase 3's suppression rule).
    </requirement>

    <requirement>
      `metrics/adjustment/bootstrap.py`:
      `interval(...)` takes the
      replicate coefficients as an
      argument — from a
      `FittedModel` in memory or
      from the stored artifact — and
      for each of the
      specification's replicates
      computes the person-cluster
      weights from
      `resample.replicates` (Step 2,
      the same streams the fit
      used), the replicate's
      predicted probabilities from
      its coefficients, and per
      judge the weighted `O` and
      `E`, the re-fitted shape, and
      the pooled ratio; the
      published interval is the 2.5%
      and 97.5% percentiles over the
      replicates. The model is not
      refitted here — Step 2's fit
      refitted it per replicate — so
      `metrics verify`, reading the
      artifact, reproduces the
      interval exactly.
    </requirement>

    <requirement>
      Migration
      `alembic/versions/0010_adjusted_observations.py`:
      `metric_observation.outcome_model_id`
      (FK to `outcome_model`,
      RESTRICT, nullable),
      `pooling_weight` Numeric(9,6),
      and `suppression_reason` text
      with a check constraint over
      `below_threshold`,
      `expected_below_minimum`, and
      `model_unavailable`; the app
      role keeps `SELECT`; the ORM
      model; `uv run alembic check`
      clean; the head pins at
      `0010`. The
      `observed_expected` layout
      (recorded in
      `docs/DATA_MODEL.md` beside
      Phase 3's per-kind layout):
      `observed_count` = O,
      `cohort_size` = n,
      `eligible_count` = the cohort
      before the follow-up
      restriction, `observed_rate` =
      O / n, `expected_count` = E,
      `expected_rate` = E / n,
      `standardized_ratio` = the
      pooled ratio, the bounds = its
      bootstrap interval,
      `pooling_weight`,
      `outcome_model_id`, and
      `suppression_reason`. Every
      suppressed row of every kind
      now carries its reason
      (`below_threshold` for the
      descriptive kinds).
    </requirement>

    <requirement>
      Compute and publish.
      `compute.py` dispatches
      `observed_expected` to the
      adjustment package;
      suppression is `n <
      suppression_threshold` →
      `below_threshold`, else `E <
      minimum_expected` →
      `expected_below_minimum`, else
      a model whose status is not
      `fitted` → `model_unavailable`
      (the observed figures are
      still computed and stored, as
      Phase 3 stores a suppressed
      row's numbers); a court
      subject has no adjusted
      observation.
      `ObservationDraft` gains the
      new fields;
      `publish.VERIFIED_COLUMNS`
      gains `expected_count`,
      `expected_rate`,
      `standardized_ratio`,
      `pooling_weight`,
      `suppression_reason`, and the
      model's content hash;
      quantization follows the
      column scales.
      `engine.compute_and_publish`
      fits the snapshot's missing
      models (Step 2's `fit_models`)
      before computing, so `metrics
      compute` is still one command
      and a second run on the same
      snapshot fits, computes, and
      publishes nothing.
    </requirement>

    <requirement>
      Step 13 and verify.
      `recompute_metrics` computes
      the descriptive kinds only: an
      adjusted figure depends on a
      model and a shape fitted over
      every judge, so it is
      recomputed by the full
      `metrics compute`, and the
      adjusted observations keep
      citing the snapshot and model
      they came from.
      `publish.publish` loads,
      compares, and supersedes only
      the kinds a run computes (a
      `kinds` argument; step 13
      passes the descriptive kinds)
      — today it compares a
      subject's whole current set
      and would supersede the
      adjusted rows of every judge a
      step-13 run touches;
      `docs/ARCHITECTURE.md` records
      the exception to ROADMAP §5
      "Performance rules".
      `verify.py` recomputes
      adjusted observations from
      their snapshot and their
      model's stored artifact and
      compares every verified
      column; an observation whose
      model artifact is missing or
      altered is reported by id and
      field. The provenance trace
      (`metrics/provenance.py`,
      `provenance trace`) adds the
      model (content hash,
      specification and model
      versions, target, window,
      seed) and `check_chain`
      requires its artifact to exist
      and hash to its content hash.
    </requirement>

    <requirement>
      The public hold-out. In
      `services/metrics.py`, a
      `SERVED_KINDS` set (the six
      Phase 3 kinds) filters `GET
      /api/v1/metrics` definitions,
      the subject routes'
      observations (in the
      repository statement, by kind,
      so the statement count is
      unchanged), `/metrics/compare`
      (an `observed_expected` slug
      answers the unknown-metric
      422), and the provenance route
      (an adjusted observation id
      answers 404).
      `tests/integration/test_api_adjusted.py`
      asserts each against the
      golden compute (Step 5 turns
      it into the serving tests).
      Step 5 adds the kind to
      `SERVED_KINDS` with its
      schema; `docs/API.md` states
      the hold-out and its reason.
    </requirement>

    <requirement>
      `/api/v1/ready`:
      `metrics.models` for the
      latest snapshot — `fitted`
      (the count with status
      `fitted`), `unavailable` (the
      others), `spec_version`, and
      `model_version` — from one
      additional statement at most;
      no hash or path. Regenerate
      `docs/openapi.json` and
      `web/lib/api/schema.d.ts`.
    </requirement>

    <requirement>
      Add tests/unit/test_pooling.py
      and
      tests/unit/test_bootstrap.py:
      - the marginal likelihood
        equals a direct evaluation
        with `math.lgamma`; the
        shape recovered on data
        simulated from a known shape
        within tolerance;
        `pooled_fully` at the bound;
        a judge with `O = 0` gets a
        finite ratio below 1; the
        pooled ratio and the weight
        at the formula.
      - replicates are identical
        across two runs and after
        UUID relabelling; the
        interval contains the pooled
        estimate for a
        well-populated judge; a
        replicate set read from the
        artifact reproduces the
        stored interval exactly.
    </requirement>

    <requirement>
      Add
      tests/golden/test_golden_adjusted.py
      (the shared `golden_metrics`
      fixture): every judge,
      adjusted metric, and window
      has one observation; its
      observed count equals the
      descriptive metric's numerator
      for the same judge and window
      and `truth/effects.json`'s
      observed count; every
      suppression reason is the one
      the golden cohorts and models
      imply; `metrics verify`
      reports no mismatch; a
      tampered `standardized_ratio`
      is reported by id and column;
      a second compute publishes
      nothing; every member exists;
      no court subject has an
      adjusted observation; step 13
      publishes none and supersedes
      none, even for a judge the run
      touches
      (`test_synthetic_ingest.py`).
    </requirement>

    <requirement>
      Add
      tests/golden/test_golden_recovery.py
      (the demo world built in
      memory from seed `20260916`
      with
      `tests/property/support.frame_from_world`,
      fitted with Step 2's
      `fit_frame` and the
      specification, for the targets
      and windows the `recovery`
      block names): over the judges
      with at least the block's
      minimum followed cohort, the
      Spearman correlation between
      the log pooled ratio and the
      court-centered planted effect
      meets the block's tolerance;
      the sign agrees for every
      judge whose centered effect
      exceeds the block's magnitude;
      the raw rates' Spearman
      correlation with the same
      effects is lower than the
      adjusted one; the model's
      expected counts correlate with
      the oracle's `sum(p0)` across
      judges at the block's minimum;
      and at least the block's share
      of the published intervals
      cover each judge's true ratio
      `sum(p) / sum(p0)`. Set the
      tolerances by running the test
      once, record them in the
      specification's `recovery`
      block (a tolerance alters no
      model or figure, so `version`
      stays), and state them in
      `docs/SYNTHETIC_DATA.md`. The
      test runs in the default
      suite; if it exceeds about a
      minute, fit only the recovery
      targets.
    </requirement>

    <requirement>
      Update
      tests/integration/test_outcome_models.py
      for the fitting compute: the
      `golden_metrics` compute now
      fits the models, so the test
      asserts the rows exist and
      that `models fit` then writes
      nothing; `purge_source`
      deletes a source's
      observations before its
      `outcome_model` rows (the new
      foreign key).
    </requirement>

    <requirement>
      Documentation:
      `docs/ARCHITECTURE.md` "Risk
      adjustment" (expected counts,
      pooling, the bootstrap, the
      step-13 exception, the
      hold-out),
      `docs/DATA_MODEL.md` (the new
      columns, the
      `observed_expected` layout,
      registry version 2),
      `docs/PROVENANCE.md` (the
      model in the chain),
      `docs/API.md` (`/ready`
      models, the hold-out),
      `docs/METHODOLOGY.md`
      (re-rendered), `AGENTS.md`,
      and `docs/ROADMAP.md`.
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

- Registry version 2 loads with the kind `observed_expected` and its three
  metrics, methodology `0.3` carries its changelog entry, and
  `docs/METHODOLOGY.md` equals the render (`test_metric_registry.py`,
  `test_methodology_render.py`).
- The pooling and bootstrap functions meet their references and are
  deterministic under UUID relabelling (`test_pooling.py`, `test_bootstrap.py`).
- Migration `0010_adjusted_observations` round-trips and `uv run alembic check`
  is clean; every suppressed row carries a reason.
- On the golden fixture, every adjusted observation's observed count equals its
  descriptive numerator and the truth's, every suppression reason is the
  expected one, `metrics verify` reproduces every observation and reports a
  tampered ratio, a second compute publishes nothing, and step 13 neither
  publishes nor supersedes an adjusted observation (`test_golden_adjusted.py`,
  `test_synthetic_ingest.py`).
- On the demo world, the planted judge ranking is recovered within the
  specification's tolerance, better than by raw rates, with expected counts
  tracking the oracle and the intervals covering the true ratios at the
  specified share (`test_golden_recovery.py`).
- No `GET /api/v1/metrics`, subject-metrics, compare, or provenance response
  serves an `observed_expected` definition or observation
  (`test_api_adjusted.py`); `/api/v1/ready` reports the models;
  `docs/openapi.json` and `web/lib/api/schema.d.ts` are regenerated; the
  provenance trace of an adjusted observation names its model and reports
  `complete`.
- `uv run poe check` passes and every required CI check is green.
- **Deployed & verified**: after `uv run poe migrate` and `uv run poe
  compute-metrics` on the demo database, `GET
  http://localhost:8000/api/v1/ready` reports `alembic_current` `0010` and
  `metrics.models.fitted` above zero; `uv run judgemetrics metrics verify` exits
  0 with the adjusted observations counted; `uv run judgemetrics provenance
  trace <an adjusted observation id>` prints `complete: yes`; and `GET
  /api/v1/judges/<a demo judge id>/metrics` lists no adjusted slug.
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff — secret scan, `bandit`, and dependency audit
  clean — and the analytics surface handles sensitive data per the project
  ROADMAP "Security & privacy strategy": adjusted members are decision ids,
  per-person predictions never leave memory, and nothing adjusted reaches a
  public response before Step 5.

---

## Step 4 — Validation Report and Methodology 1.0

**Status:** Not started

> **Goal:** Publish the validation before any adjusted number is shown. The
> `judgemetrics.validation` package assembles, from the current snapshot's
> models and adjusted observations, a report of every diagnostic the brief's
> `model_validation` lists: the temporal-split calibration bins, calibration in
> the large and the calibration slope, the Brier score and its skill, ROC AUC as
> a secondary diagnostic, feature stability over the bootstrap replicates,
> missing-data sensitivity (a complete-case refit compared with the published
> fit), bootstrap stability of the judge-level estimates (interval widths, the
> share excluding 1, rank-interval widths, as distributions, never per judge),
> recovery of the planted effects against `truth/effects.json` for a synthetic
> source, and subgroup calibration over the synthetic restricted attributes in
> aggregate only (`validation/fairness.py`, the only code that reads the
> `restricted` schema, as the ingest role, withholding every cell below the
> thresholds); `judgemetrics validation report [--out docs/VALIDATION.md]
> [--check] [--truth DIR]` renders it deterministically and `judgemetrics
> validation recovery --truth DIR [--json]` prints the database-path recovery;
> the committed `docs/VALIDATION.md` is the demo seed's report and the `e2e` CI
> job checks it; the registry moves to methodology `1.0` with its changelog
> entry; `metrics/methodology.py` renders an "Adjusted statistics" section into
> `docs/METHODOLOGY.md` from the registry and the specification (the model,
> every feature with its known-at rule and leakage justification, the exclusions
> and their reasons, the brief's O/E interpretation verbatim, the pooling, the
> interval, the thresholds, and the limitations of adjustment), and `GET
> /api/v1/metrics` serves the same prose. The brief's eight known limitations
> stay exactly as they are. This step documents the validation; Step 5 shows the
> adjusted statistics it validates.

**Branch:** `feature/phase04-step4-validation-methodology`

**Deploys:** local analytics surface — nothing is migrated; after the merge the
operator runs `uv run poe compute-metrics` (the registry's methodology version
changes, so every observation is republished under `1.0`) and `uv run
judgemetrics validation report --check`, which must exit 0 against the demo
database; `GET /api/v1/metrics` then serves methodology `1.0` and the adjustment
prose.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                            |
| ------------ | ------------------------------------------------ |
| Model        | Opus 5.5                                         |
| Backup       | GPT-5.6 Terra — Codex · Intelligence High        |
| Platform     | Claude Code                                      |
| Effort       | High (raised from Claude Code's default Medium)  |
| Thinking     | On                                               |
| Conversation | **New**                                          |

**Model rationale:** This step turns the stored diagnostics into an honest,
reproducible validation document, adds the one code path allowed to read
restricted attributes, and writes the methodology prose readers will rely on to
interpret every adjusted number — PRIMARY `coding`, SECONDARY `knowledge`, High
complexity (a least-privilege data path, small-cell suppression, cross-database
determinism, a generated document checked in CI, and a methodology version) but
not novel problem-solving: the estimators exist and this step reports on them.
Opus 5.5 is S-tier in coding and S-tier in knowledge (HLE 61.4% at max); Fable
5.1 ties it and the output-price tie-breaker selects Opus 5.5 ($20 against $50).
The Platform is Claude Code on the $200 claude.ai Max subscription (weekly pool
at `headroom`); with the flat-funding gate closed under the `capped` posture,
effort follows the ladder, and this step raises Claude Code's default `Medium`
to `High` for the High-complexity rung without the novel-problem conditions that
would earn `Extra High`. Thinking `On`. Backup: GPT-5.6 Terra on Codex (the $100
ChatGPT Pro 5x pool), S-tier in coding and A-tier in knowledge from OpenAI,
chosen over GPT-5.6 Sol by the coverage tie-break, at Intelligence `High`.
Conversation is New per phase-boundary hygiene.

```xml
<task>
  <lifecycle>
    This step MUST follow all six
    stages, in order. Stages 1, 3,
    4, 5, 6 are AS BINDING as any
    `<requirement>` below. Do not
    emit the Stage 6 completion line
    until the PR is merged and every
    acceptance criterion for this
    step is affirmatively met.

    1. CREATE THE BRANCH. Before any
       Read / Edit / Bash, run `git
       checkout -b
       feature/phase04-step4-validation-methodology`
       from a clean, up-to-date
       `main`. The exact branch name
       is in this step's
       `**Branch:**` line above. If
       the Worktree rule applies,
       use `git fetch origin && git
       worktree add -b <branch>
       .worktrees/<slug>
       origin/main` instead, then
       bootstrap the worktree.

    2. WORK ON THE BRANCH. All
       commits land here. `main` is
       protected with
       `enforce_admins: true` —
       direct pushes will be
       rejected. Pass the security
       gate before every commit.
       Stop the local API before `uv
       run poe gate` or `git
       commit`.

    3. OPEN THE PR, THEN MARK THE
       STEP. `gh pr create --base
       main --head <branch>` with a
       Conventional Commits title
       and a body that references
       this roadmap step and its
       acceptance criteria. One PR
       per step. Then, in this
       roadmap file: set this step's
       `**Status:**` line (directly
       under its heading) to
       `Complete — PR #<n>
       (<YYYY-MM-DD>)`, append ` ✅`
       to the step's `## Step`
       heading, and set its Summary
       Table Status cell to
       `Complete — PR #<n>`. Commit
       that edit on the step branch
       and push — the PR carries its
       own completion mark, so the
       roadmap on `main` marks this
       step complete exactly when
       the PR merges (Status rule).
       Same commit: on the phase's
       first step, set this
       roadmap's phase-level
       `**Status:**` (under its
       title) and the parent project
       roadmap's Phase 4
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 4` heading.

    4. WAIT FOR GREEN CHECKS, THEN
       SQUASH-MERGE. Every required
       check must pass. If the PR
       falls behind main, refresh
       with `gh pr update-branch
       --rebase` — never merge main
       into the branch
       (`required_linear_history:
       true`). Once green: `gh pr
       merge <PR> --squash
       --delete-branch`. If this
       step's `**Deploys:**` line
       names a surface, the merge is
       not the finish line: run the
       Deployed & verified check
       against the local environment
       before declaring the step
       complete.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree, `git
       worktree remove <path>` FIRST
       — the branch prune fails
       while the branch is checked
       out there.

    6. DISPOSE OF EVERY FINDING,
       DECLARE COMPLETION, THEN NEW
       CONVERSATION. First send
       every finding this step
       surfaced to its destination
       (Triage rule): a note for a
       later step → edit that step's
       <task> block now; spec rot →
       edit this roadmap now; a bug
       → fixed in-step or an issue
       number; a judgement call in
       the diff → the PR body; a
       process lesson → written
       where the next conversation
       reads it (AGENTS.md or this
       roadmap); a data-semantics
       finding → the registry or
       model-specification entry,
       version bumped; a data-access
       question → a row in
       docs/ROADMAP.md. Update
       docs/ROADMAP.md (completed
       items, known issues, next
       milestones). A finding you
       can only describe is NOT
       disposed of, and counts as an
       unmet criterion. Only once
       the PR is merged — and `main`
       therefore carries this step's
       `Complete` Status line —
       every acceptance criterion is
       affirmatively met, and every
       finding has a destination,
       say so plainly: end your
       final response with an
       explicit, unhedged completion
       line — verbatim shape "Step 4
       is complete. You can now move
       on to Step 5." That line is
       the LAST line of the
       response. NOTHING follows it
       — no "Follow-ups
       (non-blocking)", "Notes",
       "Next", "worth a glance", or
       suggested improvements. A
       short ledger may PRECEDE it,
       one entry per finding naming
       its destination (issue #,
       file edited, PR body) — never
       an open item. If any
       criterion is unmet or any
       finding has no destination,
       state plainly that the step
       is NOT complete, name what is
       outstanding, and omit the
       completion line. "Done" means
       done. Then, for
       phase-boundary hygiene, the
       operator closes this session
       and opens a fresh one before
       Step 5.
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
       credentials, API keys,
       tokens, or real PII in the
       diff (gitleaks /
       detect-secrets or the
       project's equivalent).
       Secrets go in the secrets
       manager, never in source or
       committed env files. In this
       step: `docs/VALIDATION.md`
       carries aggregates of
       labelled synthetic data only
       — no judge-level table, no
       UUID, no hash, no restricted
       value below the cell
       thresholds; the dataset it
       describes is named by its
       manifest (seed, scale,
       versions), never by a path on
       the maintainer's machine.

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. In
       this step: the restricted
       read is one parameterized
       SQLAlchemy statement in
       `validation/fairness.py`; the
       report writes only to the
       path it is given, resolved
       under the repository root as
       `methodology render` does;
       `--truth DIR` reads
       `truth/effects.json` with
       `json.loads` and a path
       contained in the directory
       given.

    3. DEPENDENCY AUDIT. Any new or
       bumped dependency passes the
       audit (pip-audit / npm audit
       / osv-scanner); no
       known-vulnerable, yanked, or
       typo-squatted package. This
       step adds no dependency. If
       one is added, it passes
       `pip-audit --strict
       --require-hashes`.

    4. SENSITIVE-DATA REVIEW.
       Whatever this step touches
       stays least-privilege,
       encrypted in transit + at
       rest, and out of logs and
       client bundles. If the step
       adds a data path, name how
       PII/secrets are protected. In
       this step:
       `validation/fairness.py` is
       the only module that reads
       the `restricted` schema (a
       static check,
       `tests/unit/test_restricted_readers.py`:
       under `src/judgemetrics/`,
       the pattern
       `party_attribute`, a
       schema-qualified
       `restricted.<name>`, or
       `schema="restricted"` appears
       only in
       `validation/fairness.py`, the
       ORM model and
       `db/models/__init__.py`, and
       Step 1's write path —
       `ingest/base.py`,
       `ingest/publish.py`,
       `ingest/runner.py`, and
       `ingest/synthetic/`); it runs
       on an ingest-role session and
       refuses any other (the app
       role gets
       `InsufficientPrivilege`
       anyway); the attribute of an
       individual index event exists
       only inside one function's
       memory, is never logged,
       written, cached, or returned;
       every published cell has at
       least `minimum_cohort` index
       events and `minimum_expected`
       expected events, and a
       smaller cell is withheld with
       its reason; the prose `GET
       /api/v1/metrics` serves names
       no restricted value.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean. This is the safety net
    that stops a security issue from
    reaching the branch, the PR, or
    `main`.
  </security>

  <context>
    JudgeMetrics. Phase 4. Step 4:
    validation report and
    methodology 1.0.

    Current state (as of Phase 4
    Step 3):

    - Note from Step 2 (the
      temporal-split diagnostics as
      first fitted on the demo seed):
      the release model transports
      (test AUC 0.81, observed over
      expected 1.005, slope 1.19),
      the failure-to-appear models
      moderately (AUC 0.54-0.68),
      and the new-case models do not
      (AUC 0.49-0.55, slopes 0.1-0.6,
      observed over expected up to
      1.7 at 180 days, against an
      in-sample AUC of 0.61-0.64).
      Report them as found and never
      tune the specification to
      improve them (any change bumps
      its `version`). Examine and
      state the cause; a hypothesis
      to test, not a finding: the
      generator allocates each
      person's case count (one to
      four) up front, so late index
      events have fewer later cases
      left whatever their features,
      and an unseen calendar year is
      scored at the last training
      year's level.

    - `metrics compute` fits one
      expected-outcome model per
      source, target, and window
      (thirteen for the synthetic
      source) and publishes
      `observed_expected`
      observations with the pooled
      ratio, its bootstrap interval,
      the pooling weight, the model,
      and the suppression reason
      (registry version 2,
      methodology `0.3`). Each
      model's artifact holds the
      published coefficients, the
      temporal-split diagnostics
      (bins, calibration in the
      large, slope, Brier score and
      skill, AUC), the stability
      summary, and the replicate
      coefficients;
      `outcome_model.diagnostics`
      holds the summary.
    - `tests/golden/test_golden_recovery.py`
      proves recovery on the
      in-memory demo world; nothing
      yet reports recovery on the
      database path, where entity
      resolution decides the
      persons.
    - `restricted.party_attribute`
      holds `age_band` and
      `synthetic_group` per case
      party (migration `0008`);
      nothing reads it yet.
      `truth/effects.json` records
      the planted age effects (the
      positive control) and the
      group's independence (the
      negative control).
    - Every public metrics response
      holds the `observed_expected`
      kind out
      (`services/metrics.SERVED_KINDS`);
      `GET /api/v1/metrics` serves
      the methodology prose from
      `metrics/methodology.py`
      (`HOW_TO_READ`, `SEMANTICS`,
      `ATTRIBUTION_TEXT`,
      `GATE_TEXT`, `CHANGELOG`). Its
      "Interval" term still says
      adjusted statistics carry
      their own intervals and "none
      is published under this
      version".
    - The `e2e` CI job seeds
      `data/synthetic/ci` (the same
      manifest as the demo seed),
      runs `metrics compute` and
      `models verify`, then starts
      the API and the web app.

    Files to read (every file before
    drafting):
    - src/judgemetrics/metrics/adjustment/
      (every module) and
      data/reference/outcome_model.yaml.
    - src/judgemetrics/metrics/methodology.py,
      registry.py, and
      data/reference/metric_registry.yaml
      (the renderer, the changelog,
      the version rule).
    - src/judgemetrics/services/metrics.py
      and schemas/metrics.py
      (`registry_response`, the
      `Registry` schema).
    - src/judgemetrics/db/models/
      (the `PartyAttribute` model,
      `CaseParty`) and
      src/judgemetrics/config.py
      (the ingest role URL,
      `synthetic_dir`).
    - src/judgemetrics/cli.py (the
      `methodology render --check`
      pattern, role selection).
    - tests/fixtures/golden/truth/effects.json
      and docs/SYNTHETIC_DATA.md
      ("Planted effects",
      "Restricted controls").
    - docs/METHODOLOGY.md,
      tests/unit/test_methodology_render.py,
      tests/integration/test_api_metrics.py,
      tests/unit/test_repo_hygiene.py,
      and the `e2e` job in
      .github/workflows/ci.yml.
    - The brief's
      `<risk_adjustment>` element
      (`interpretation`,
      `uncertainty`,
      `minimum_sample_size`,
      `temporal_controls`,
      `jurisdiction_controls`,
      `model_validation`) and
      `<important_statistical_warnings>`.
  </context>

  <goal>
    Ship the
    `judgemetrics.validation`
    package (`report`, `fairness`,
    `sensitivity`, `stability`,
    `recovery`), `judgemetrics
    validation report|recovery`, the
    committed `docs/VALIDATION.md`
    for the demo seed with its `e2e`
    check, methodology `1.0` with
    the "Adjusted statistics"
    section in
    `docs/METHODOLOGY.md`, and the
    same prose on `GET
    /api/v1/metrics`.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      `src/judgemetrics/validation/fairness.py`:
      `subgroup_calibration(session,
      snapshot, models, *, spec) ->
      list[SubgroupCell]` — refuses
      a session that is not the
      ingest role's; reads, in one
      statement, the `age_band` and
      `synthetic_group` of the
      defendant case party of every
      index event the models score
      (decision → case and person →
      `case_party` →
      `restricted.party_attribute`);
      for each model and attribute
      value aggregates the index
      events, the observed outcomes,
      the expected count from the
      published coefficients, the
      ratio, and its 95% interval
      over the stored bootstrap
      replicates; withholds a cell
      below `minimum_cohort` index
      events or `minimum_expected`
      expected events with its
      reason; returns cells only. A
      pure function
      `calibration_cells(predictions,
      outcomes, groups, replicates)`
      does the arithmetic so it can
      be tested in memory.
    </requirement>

    <requirement>
      `validation/sensitivity.py`
      (missing-data sensitivity: the
      complete-case refit of each
      model — Step 2's
      `refit_complete_cases`,
      excluding every index event
      with a feature at its
      `missing` level — against the
      published fit: events dropped,
      and across judges the Spearman
      correlation and the largest
      absolute change of the pooled
      ratio);
      `validation/stability.py`
      (from the replicates: per
      model the coefficients' sign
      agreement and spread, and
      across judges the median
      interval width, the share of
      intervals excluding 1, and the
      median width of each judge's
      95% rank interval —
      distributions, no judge
      named);
      `validation/recovery.py` (for
      a source with
      `truth/effects.json`: the
      Spearman correlation of the
      published pooled ratios with
      the centered planted effects,
      the sign agreement, the raw
      rates' correlation for
      contrast, the expected counts
      against the oracle, and the
      interval coverage of the true
      ratios, against the
      specification's `recovery`
      tolerances).
    </requirement>

    <requirement>
      `validation/report.py` and the
      CLI. `judgemetrics validation
      report [--out
      docs/VALIDATION.md] [--check]
      [--truth DIR]` (ingest role;
      `--truth` defaults to
      `Settings.synthetic_dir`; exit
      1 with a unified diff on
      drift, 2 on a missing snapshot
      or model) renders, wrapped at
      80 columns: the generated
      notice and the synthetic
      label; the dataset (source
      register name, manifest seed,
      scale, generator and truth
      versions, coverage window, row
      counts), the specification,
      model, registry, and
      methodology versions; the
      association statement; a
      summary table per target and
      window (training and test
      events, Brier score and skill,
      AUC, calibration in the large,
      slope, status); the
      calibration bins; feature
      stability; missing-data
      sensitivity; bootstrap
      stability; subgroup
      calibration with the controls
      explained (the model omits the
      age band by policy, so its
      cells show the planted
      direction; `synthetic_group`
      is independent by construction
      and must be calibrated);
      recovery; and a pointer to the
      limitations in
      `docs/METHODOLOGY.md`. No
      UUID, hash, judge name, or
      local path appears, and every
      order is fixed, so the same
      dataset renders the same
      document in any database (Step
      2's order invariance).
      `judgemetrics validation
      recovery --truth DIR [--json]`
      prints the recovery section's
      figures and exits 1 below a
      tolerance.
    </requirement>

    <requirement>
      Commit `docs/VALIDATION.md`
      rendered from the demo seed
      (`uv run poe bootstrap`, then
      `uv run judgemetrics
      validation report`). Add `uv
      run judgemetrics validation
      report --check --truth
      data/synthetic/ci` to the
      `e2e` CI job after `models
      verify` and update
      `tests/unit/test_repo_hygiene.py`'s
      command-order pin. If the CI
      render differs from the local
      one, the difference is an
      order-invariance bug to fix,
      never a reason to drop the
      check.
    </requirement>

    <requirement>
      Methodology `1.0`. The
      registry's
      `methodology_version` is
      `"1.0"` (its `version` stays
      2: no entry changes); append
      `("1.0", "The expected-outcome
      model, observed-to-expected
      ratios with partial pooling
      and bootstrap intervals, and
      their validation
      (docs/VALIDATION.md) are
      published; the known
      limitations are unchanged.")`
      to `CHANGELOG`; update the
      "Interval" term of
      `HOW_TO_READ` (bootstrap
      intervals for adjusted
      statistics). Render an
      "Adjusted statistics" section
      into `docs/METHODOLOGY.md`
      from the registry and
      `data/reference/outcome_model.yaml`:
      the model (regularized
      logistic, the penalty, one
      model per target and window
      over every eligible event of
      the source, no judge term);
      the targets; every feature
      with its levels, known-at
      rule, and leakage
      justification; every exclusion
      with its reason; expected
      count as the sum of predicted
      probabilities; the brief's
      interpretation verbatim ("An
      O/E ratio above 1 means
      observed outcomes exceeded the
      model's expected count for the
      defined cohort. A ratio below
      1 means observed outcomes were
      below the model's expected
      count. It must not be
      described as proof that the
      judge caused the
      difference."); the pooling
      (the formula and the weight);
      the interval (the
      person-cluster bootstrap with
      the model refitted, its size,
      the percentiles); the
      thresholds and their reasons;
      the temporal and jurisdiction
      controls (the calendar-year
      and court features; judges
      compared within their source's
      model); and the limitations of
      adjustment (unobserved
      confounding and selection on
      unobservables, model
      misspecification, restricted
      attributes excluded by policy
      and what the subgroup
      calibration shows about that
      choice, intervals conditional
      on the specification). The `##
      Known limitations` section and
      the registry's eight warnings
      are unchanged.
    </requirement>

    <requirement>
      `GET /api/v1/metrics` serves
      the adjustment prose from the
      same constants as a new
      `adjustment` block on
      `Registry` (the model
      description, the features with
      known-at and leakage text, the
      exclusions with reasons, the
      interpretation, the pooling,
      the interval, the thresholds,
      the limitations of
      adjustment); update the exact
      key-set assertion in
      `tests/integration/test_api_metrics.py`;
      regenerate `docs/openapi.json`
      and `web/lib/api/schema.d.ts`;
      `tests/golden/test_public_contract.py`
      still passes (no person key,
      no restricted value, no
      unknown hash in the prose).
    </requirement>

    <requirement>
      Add
      tests/unit/test_validation_report.py:
      - test_the_report_renders_every_section_from_fixture_diagnostics.
      - test_the_report_names_no_uuid_hash_judge_or_path.
      - test_a_small_subgroup_cell_is_withheld_with_its_reason.
      - test_check_reports_a_diff_and_exits_one.
    </requirement>

    <requirement>
      Add
      tests/unit/test_subgroup_calibration.py
      (the demo world in memory,
      seed `20260916`, fitted with
      Step 2's `fit_frame`, grouped
      by the filing-age band and
      `synthetic_group` exactly as
      the connector publishes them):
      `calibration_cells` orders the
      age-band ratios like the
      planted age effects and keeps
      every `synthetic_group` ratio
      within the tolerance the
      specification's `recovery`
      block names for the negative
      control. Add
      tests/integration/test_fairness_analysis.py
      (the golden database): the
      ingest role runs the analysis
      and the app role cannot; every
      golden cell is withheld (the
      golden cohorts are below the
      thresholds) with its reason;
      the function returns cells
      only.
    </requirement>

    <requirement>
      Extend
      tests/unit/test_methodology_render.py:
      methodology `1.0`; the
      changelog in order `0.1`,
      `0.2`, `0.3`, `1.0`; the
      adjustment section present
      with the brief's
      interpretation verbatim; the
      eight known limitations
      unchanged;
      `docs/METHODOLOGY.md` equals
      the render. Add
      tests/unit/test_restricted_readers.py:
      under `src/judgemetrics/`,
      `party_attribute`, a
      schema-qualified
      `restricted.<name>`, or
      `schema="restricted"` appears
      only in
      `validation/fairness.py` (the
      one reader), the ORM model and
      `db/models/__init__.py`, and
      Step 1's write path
      (`ingest/base.py`,
      `ingest/publish.py`,
      `ingest/runner.py`,
      `ingest/synthetic/`); the bare
      word "restricted" is not the
      pattern (a dozen modules use
      it in prose).
    </requirement>

    <requirement>
      Documentation:
      `docs/VALIDATION.md`
      (generated),
      `docs/METHODOLOGY.md`
      (re-rendered),
      `docs/ARCHITECTURE.md` ("Risk
      adjustment": the validation
      package and the restricted
      read), `docs/API.md` (the
      `adjustment` block),
      `docs/SYNTHETIC_DATA.md` (how
      the controls read in the
      report), `README.md` (the
      validation command),
      `AGENTS.md`, and
      `docs/ROADMAP.md` (known
      issue: the validation is
      synthetic; real-data
      validation is Phase 6 §6.1).
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

- `docs/VALIDATION.md` equals its render from the demo seed (`validation report
  --check` exits 0 locally and in the `e2e` CI job; `test_validation_report.py`)
  and reports, per target and window, the calibration bins, calibration in the
  large and slope, the Brier score and skill, AUC, feature stability,
  missing-data sensitivity, bootstrap stability, recovery, and subgroup
  calibration, with no UUID, hash, judge name, or local path.
- The subgroup calibration reads the `restricted` schema only through
  `validation/fairness.py` as the ingest role (no other reader exists),
  publishes aggregate cells only, withholds every cell below the thresholds with
  its reason, shows the age-band positive control in the planted direction and
  the `synthetic_group` negative control within tolerance
  (`test_subgroup_calibration.py`, `test_fairness_analysis.py`,
  `test_restricted_readers.py`).
- `validation recovery --truth data/synthetic/20260916` meets the
  specification's tolerances on the database path.
- Methodology `1.0` is published with the changelog `0.1`, `0.2`, `0.3`, `1.0`;
  `docs/METHODOLOGY.md` carries the "Adjusted statistics" section with the
  brief's interpretation verbatim and equals the render; the eight known
  limitations are unchanged (`test_methodology_render.py`; `verify_phase03.py`
  checks 1, 4, and 5 still pass).
- `GET /api/v1/metrics` serves the `adjustment` block; `docs/openapi.json` and
  `web/lib/api/schema.d.ts` are regenerated; the public contract test passes.
- `uv run poe check` passes and every required CI check is green.
- **Deployed & verified**: after `uv run poe compute-metrics` on the demo
  database, `uv run judgemetrics validation report --check` exits 0, `GET
  http://localhost:8000/api/v1/metrics` reports `methodology_version` `1.0` with
  the `adjustment` block, and every current observation cites methodology `1.0`
  (`uv run judgemetrics metrics verify` exits 0).
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff — secret scan, `bandit`, and dependency audit
  clean — and the validation surface handles sensitive data per the project
  ROADMAP "Security & privacy strategy": one module, on the ingest role, reads
  the restricted schema; no individual attribute leaves its memory; every
  published cell meets the thresholds.

---

## Step 5 — Risk-Adjusted Panels, Adjusted Compare, and the Model Card

**Status:** Not started

> **Goal:** Show the validated adjusted statistics the way the brief's
> presentation rules require. The API serves the `observed_expected` kind
> (`services/metrics.SERVED_KINDS` gains it): `MetricKind`, the `ratio` unit,
> and the `bootstrap` interval method join the schema; `Observation` and
> `CompareRow` gain `expected`, `expected_rate`, `ratio` (the pooled ratio),
> `ratio_lower` and `ratio_upper` (its interval, unbounded above, where
> `lower`/`upper` stay in `[0, 1]` and null for this kind), `pooling_weight`,
> `model` (id, content hash, model and specification versions, link), and
> `suppression_reason`, every figure withheld by `SuppressibleFigures` when the
> row is suppressed; `GET /api/v1/models/{model_id}` returns the model card from
> `outcome_model` (coefficients, counts, validation summary, calibration bins,
> versions); the provenance body names the model; `/metrics/compare` sorts by
> `ratio`. The web gains `components/adjusted-stat.tsx` — the only renderer of
> an adjusted figure: observed and expected events, the pooled ratio with its
> 95% bootstrap interval, the pooling weight in words, the cohort size and
> eligible count, period and coverage, the model link, the methodology version
> as visible text, the brief's O/E interpretation, and the suppression reason —
> the judge page's "Risk-adjusted comparison" panel with the window and
> comparison-cohort selectors, the cohort definition, the judge's position among
> cohort peers, and the raw rate it adjusts beside it; adjusted measures on
> `/compare`; `/models/[modelId]`; the methodology page's adjustment section;
> Vitest presentation-rule tests, `web/tests/e2e/adjusted.spec.ts`, and
> screenshots. This step is the phase's public surface; Step 6 verifies it.

**Branch:** `feature/phase04-step5-adjusted-panels`

**Deploys:** local API and web app (`uv run poe dev-api`, `uv run poe dev-web`)
— no migration; after the merge a demo judge's page shows the risk-adjusted
panel, `/compare` sorts an adjusted metric by its ratio, and `/models/<id>`
shows the model card.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                            |
| ------------ | ------------------------------------------------ |
| Model        | Opus 5.5                                         |
| Backup       | GPT-5.6 Sol — Codex · Intelligence High          |
| Platform     | Claude Code                                      |
| Effort       | High (raised from Claude Code's default Medium)  |
| Thinking     | On                                               |
| Conversation | **New**                                          |

**Model rationale:** This step changes the API contract and the web surfaces
together — schemas, a route, the provenance body, the compare sort, a component,
a panel, two pages, the generated client, typed fixtures, a Playwright flow, and
screenshots — under a presentation contract that is mechanically enforced, with
long build, test, and browser loops: PRIMARY `coding`, SECONDARY `agentic`, High
complexity through its cross-cutting scope but no novel problem-solving (the
patterns are Phase 3's). Opus 5.5 is S-tier in coding and S-tier in agentic (AA
Intelligence Index 57.6 at max) and A-tier in multimodal for reading its own
screenshots; Fable 5.1 and GPT-5.6 Sol tie it on both rows and on coverage, the
output-price tie-breaker drops Fable 5.1 ($50 against $20), and the operator's
platform order puts Claude Code ahead of Codex for the remaining tie. The
Platform is Claude Code on the $200 claude.ai Max subscription (weekly pool at
`headroom`); with the flat-funding gate closed under the `capped` posture,
effort follows the ladder, and this step raises Claude Code's default `Medium`
to `High` for the High-complexity rung without the novel-problem conditions of
`Extra High`. Thinking `On`. Backup: GPT-5.6 Sol on Codex (the $100 ChatGPT Pro
5x pool), S-tier in coding and agentic from OpenAI, chosen over GPT-6 Astra by
the coverage tie-break, at Intelligence `High`. Conversation is New per
phase-boundary hygiene.

```xml
<task>
  <lifecycle>
    This step MUST follow all six
    stages, in order. Stages 1, 3,
    4, 5, 6 are AS BINDING as any
    `<requirement>` below. Do not
    emit the Stage 6 completion line
    until the PR is merged and every
    acceptance criterion for this
    step is affirmatively met.

    1. CREATE THE BRANCH. Before any
       Read / Edit / Bash, run `git
       checkout -b
       feature/phase04-step5-adjusted-panels`
       from a clean, up-to-date
       `main`. The exact branch name
       is in this step's
       `**Branch:**` line above. If
       the Worktree rule applies,
       use `git fetch origin && git
       worktree add -b <branch>
       .worktrees/<slug>
       origin/main` instead, then
       bootstrap the worktree.

    2. WORK ON THE BRANCH. All
       commits land here. `main` is
       protected with
       `enforce_admins: true` —
       direct pushes will be
       rejected. Pass the security
       gate before every commit.
       Stop the local API before `uv
       run poe gate` or `git
       commit`.

    3. OPEN THE PR, THEN MARK THE
       STEP. `gh pr create --base
       main --head <branch>` with a
       Conventional Commits title
       and a body that references
       this roadmap step and its
       acceptance criteria. One PR
       per step. Then, in this
       roadmap file: set this step's
       `**Status:**` line (directly
       under its heading) to
       `Complete — PR #<n>
       (<YYYY-MM-DD>)`, append ` ✅`
       to the step's `## Step`
       heading, and set its Summary
       Table Status cell to
       `Complete — PR #<n>`. Commit
       that edit on the step branch
       and push — the PR carries its
       own completion mark, so the
       roadmap on `main` marks this
       step complete exactly when
       the PR merges (Status rule).
       Same commit: on the phase's
       first step, set this
       roadmap's phase-level
       `**Status:**` (under its
       title) and the parent project
       roadmap's Phase 4
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 4` heading.

    4. WAIT FOR GREEN CHECKS, THEN
       SQUASH-MERGE. Every required
       check must pass. If the PR
       falls behind main, refresh
       with `gh pr update-branch
       --rebase` — never merge main
       into the branch
       (`required_linear_history:
       true`). Once green: `gh pr
       merge <PR> --squash
       --delete-branch`. If this
       step's `**Deploys:**` line
       names a surface, the merge is
       not the finish line: run the
       Deployed & verified check
       against the local environment
       before declaring the step
       complete.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree, `git
       worktree remove <path>` FIRST
       — the branch prune fails
       while the branch is checked
       out there.

    6. DISPOSE OF EVERY FINDING,
       DECLARE COMPLETION, THEN NEW
       CONVERSATION. First send
       every finding this step
       surfaced to its destination
       (Triage rule): a note for a
       later step → edit that step's
       <task> block now; spec rot →
       edit this roadmap now; a bug
       → fixed in-step or an issue
       number; a judgement call in
       the diff → the PR body; a
       process lesson → written
       where the next conversation
       reads it (AGENTS.md or this
       roadmap); a data-semantics
       finding → the registry or
       model-specification entry,
       version bumped; a data-access
       question → a row in
       docs/ROADMAP.md. Update
       docs/ROADMAP.md (completed
       items, known issues, next
       milestones). A finding you
       can only describe is NOT
       disposed of, and counts as an
       unmet criterion. Only once
       the PR is merged — and `main`
       therefore carries this step's
       `Complete` Status line —
       every acceptance criterion is
       affirmatively met, and every
       finding has a destination,
       say so plainly: end your
       final response with an
       explicit, unhedged completion
       line — verbatim shape "Step 5
       is complete. You can now move
       on to Step 6." That line is
       the LAST line of the
       response. NOTHING follows it
       — no "Follow-ups
       (non-blocking)", "Notes",
       "Next", "worth a glance", or
       suggested improvements. A
       short ledger may PRECEDE it,
       one entry per finding naming
       its destination (issue #,
       file edited, PR body) — never
       an open item. If any
       criterion is unmet or any
       finding has no destination,
       state plainly that the step
       is NOT complete, name what is
       outstanding, and omit the
       completion line. "Done" means
       done. Then, for
       phase-boundary hygiene, the
       operator closes this session
       and opens a fresh one before
       Step 6.
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
       credentials, API keys,
       tokens, or real PII in the
       diff (gitleaks /
       detect-secrets or the
       project's equivalent).
       Secrets go in the secrets
       manager, never in source or
       committed env files. In this
       step: screenshots show
       labelled synthetic data only;
       no key, pepper, or connection
       string enters a fixture, a
       test, the bundle, or a
       screenshot (the web bundle
       scan stays green).

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. In
       this step: the model card
       route validates `model_id` as
       a UUID and answers 404 for an
       unknown or superseded
       snapshot's model; every query
       is a SQLAlchemy construct
       with bound parameters; the
       pages render API text as text
       nodes (no
       `dangerouslySetInnerHTML`,
       `verify_phase03.py` check
       37); `eslint-plugin-security`
       passes with `--max-warnings
       0`.

    3. DEPENDENCY AUDIT. Any new or
       bumped dependency passes the
       audit (pip-audit / npm audit
       / osv-scanner); no
       known-vulnerable, yanked, or
       typo-squatted package. This
       step adds no dependency. If
       one is added, it passes
       `pip-audit --strict
       --require-hashes` or `pnpm
       audit --audit-level=high`.

    4. SENSITIVE-DATA REVIEW.
       Whatever this step touches
       stays least-privilege,
       encrypted in transit + at
       rest, and out of logs and
       client bundles. If the step
       adds a data path, name how
       PII/secrets are protected. In
       this step: no response, page,
       or screenshot carries a
       person key, a person-level
       row, or a restricted
       attribute
       (`tests/golden/test_public_contract.py`
       over every metrics route and
       the model card, with the
       model content hashes added to
       its allowed hashes); the
       model card never returns
       `storage_uri`; a suppressed
       adjusted row returns no
       figure — expected, ratio,
       interval, or weight — in the
       API or on a page; the
       adjusted panel carries the
       association statement's page
       once and the brief's
       interpretation beside the
       figures, never causal
       language.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean. This is the safety net
    that stops a security issue from
    reaching the branch, the PR, or
    `main`.
  </security>

  <context>
    JudgeMetrics. Phase 4. Step 5:
    risk-adjusted panels, adjusted
    compare, and the model card.

    Current state (as of Phase 4
    Step 4):

    - `metric_observation` rows of
      kind `observed_expected` exist
      for every judge, adjusted
      metric
      (`pretrial_release_observed_expected`,
      `new_case_observed_expected`,
      `failure_to_appear_observed_expected`),
      and window, with the layout
      `docs/DATA_MODEL.md` records
      (observed and cohort counts,
      `expected_count`,
      `expected_rate`,
      `standardized_ratio` = the
      pooled ratio, the bounds = its
      bootstrap interval,
      `pooling_weight`,
      `outcome_model_id`,
      `suppression_reason`);
      `services/metrics.SERVED_KINDS`
      holds them out of every public
      response.
    - `outcome_model` rows carry the
      summary diagnostics, the
      calibration bins, and the
      coefficient table, so a model
      card needs no artifact read.
    - Methodology `1.0` is
      published; `GET
      /api/v1/metrics` serves the
      `adjustment` prose block;
      `docs/VALIDATION.md` is
      committed and checked in the
      `e2e` job.
    - The API conventions: routes →
      services → repositories →
      schemas; `StrictQuery` per
      route; `ErrorBody` on every
      non-2xx; `cache_public` on the
      metrics router; statement
      budgets in
      `tests/integration/test_query_counts.py`;
      `tests/unit/test_openapi.py`
      pins 20 paths and 18
      StrictQuery routes;
      `docs/openapi.json` and
      `web/lib/api/schema.d.ts`
      regenerate on any change.
    - The web: `MetricStat` renders
      every descriptive figure and
      shows the methodology version
      only in a link title;
      `lib/metrics.ts` places panels
      (`JUDGE_PANELS`,
      `panelDefinitions`, "Other
      metrics"), enumerates kinds
      (`COMPARED_KINDS`,
      `defaultSort`,
      `primaryFigure`), and holds
      `ASSOCIATION_STATEMENT`, while
      `KIND_NOUN` is private to
      `components/metric-stat.tsx`;
      `web/tests/unit/metrics.test.ts`
      asserts `COURT_PANELS` ids
      equal `JUDGE_PANELS` ids;
      `CompareTable` renders the
      compare rows; the methodology
      page renders `GET
      /api/v1/metrics`; the
      Playwright suites discover
      synthetic judges through the
      API.

    Files to read (every file before
    drafting):
    - src/judgemetrics/schemas/metrics.py,
      services/metrics.py,
      repositories/metrics.py,
      api/routes/metrics.py,
      api/routes/judges.py,
      api/routes/courts.py,
      src/judgemetrics/main.py (the
      kinds, the hold-out, the
      queries, the routers).
    - src/judgemetrics/metrics/provenance.py
      and the provenance schema (the
      model block).
    - src/judgemetrics/db/models/
      (`OutcomeModel`) and the
      `outcome_model` columns.
    - tests/integration/test_api_metrics.py,
      tests/integration/test_query_counts.py,
      tests/unit/test_openapi.py,
      tests/unit/test_schemas_metrics.py,
      tests/golden/test_public_contract.py.
    - web/lib/metrics.ts,
      web/lib/api/client.ts,
      web/components/metric-stat.tsx,
      web/components/metric-panel.tsx,
      web/components/cohort-selector.tsx,
      web/components/compare-table.tsx,
      web/app/judges/[judgeId]/page.tsx,
      web/app/compare/page.tsx,
      web/app/methodology/page.tsx.
    - web/tests/unit/metric-stat.test.tsx,
      web/tests/unit/metrics.test.ts,
      web/tests/unit/fixtures/observations.ts,
      web/tests/e2e/metrics.spec.ts,
      web/AGENTS.md.
    - docs/API.md,
      docs/ARCHITECTURE.md ("Public
      API v1", "Web tier"),
      docs/PROVENANCE.md,
      docs/METHODOLOGY.md "Adjusted
      statistics".
    - The brief's
      `<presentation_rules>`,
      `<judge_profile_example>`, and
      `<judge_profile_schematic>`
      (the adjusted block and
      "Risk-adjusted O/E 1.10
      [0.99 - 1.21]").
  </context>

  <goal>
    Serve the adjusted kind with its
    schema fields, the model card
    route, the provenance model
    block, and the compare `ratio`
    sort; render it through
    `AdjustedStat` in the judge
    page's risk-adjusted panel, on
    `/compare`, on
    `/models/[modelId]`, and in the
    methodology page's adjustment
    section; and prove every
    presentation rule with Vitest,
    Playwright, the public contract
    test, and screenshots.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Schemas
      (`schemas/metrics.py`):
      `MetricKind` gains
      `observed_expected`, the
      `unit` literal gains `ratio`,
      `IntervalMethod` gains
      `bootstrap`
      (`INTERVAL_METHOD_BY_KIND[observed_expected]`);
      `Observation` and `CompareRow`
      gain the required, nullable
      fields `expected` (≥ 0),
      `expected_rate` (0–1), `ratio`
      (≥ 0), `ratio_lower` and
      `ratio_upper` (≥ 0),
      `pooling_weight` (0–1),
      `model` (`ModelRef`: `id`,
      `content_hash`,
      `model_version`,
      `spec_version`, `url`), and
      `suppression_reason`
      (`below_threshold`,
      `expected_below_minimum`,
      `model_unavailable`, or null);
      `SUPPRESSED_FIELDS` gains
      every new figure (the reason
      and the model survive
      suppression); for the adjusted
      kind `numerator` is the
      observed count, `denominator`
      the cohort size, `rate` the
      observed rate, and
      `lower`/`upper` null.
      `services.metrics.observation_from_row`
      maps the stored columns. The
      new fields are null for every
      descriptive kind.
    </requirement>

    <requirement>
      Serve the kind: `SERVED_KINDS`
      gains `observed_expected`; the
      subject routes, the registry
      response, the compare route,
      and the provenance route serve
      it (the hold-out's tests
      become serving tests).
      `/metrics/compare` accepts
      `sort=ratio` (the pooled
      ratio; null for a suppressed
      row so the order never leaks a
      withheld figure) and defaults
      to it for the kind; the budget
      stays one statement for a
      non-empty page. The provenance
      body (`ObservationProvenance`)
      gains `model` (the `ModelRef`
      plus the training window and
      counts; null for a descriptive
      observation); update its exact
      key-set assertion.
    </requirement>

    <requirement>
      `GET
      /api/v1/models/{model_id}`
      (new router
      `api/routes/models.py`,
      `StrictQuery` with no
      parameters, `cache_public`,
      `error_responses(404, 422)`)
      returns `ModelCard`: `id`,
      `content_hash`,
      `snapshot_hash`, `source`,
      `synthetic`, `target`,
      `window_days`, `spec_version`,
      `model_version`, `seed`,
      `status`, `fitted_at`,
      `code_version`, `training`
      (events, index events, time
      range), `validation` (Brier
      score and skill, AUC,
      calibration in the large,
      slope, the calibration bins),
      `coefficients` (per design
      column: feature, level,
      estimate, bootstrap standard
      deviation, sign agreement),
      `methodology_url`
      (`#adjusted-statistics`);
      never `storage_uri`. One
      statement (a join to the
      snapshot and source); a budget
      test. Update
      `tests/unit/test_openapi.py`
      (21 paths, 19 StrictQuery
      routes),
      `tests/golden/test_public_contract.py`
      (the model card route; the
      model content hashes allowed),
      regenerate `docs/openapi.json`
      and `web/lib/api/schema.d.ts`,
      and add `getModel(id)` to
      `web/lib/api/client.ts`.
    </requirement>

    <requirement>
      `web/components/adjusted-stat.tsx`
      (`AdjustedStat`,
      `data-testid="adjusted-stat"`,
      `data-slug`, `data-window`,
      `data-suppressed`,
      `data-reason`): the label and
      the synthetic badge; when
      suppressed, the reason in
      words (fewer than the
      threshold's followed members;
      fewer than five expected
      events; the model could not be
      fitted for this window) and no
      figure region; otherwise
      observed events, expected
      events, the pooled ratio with
      "95% bootstrap interval" and
      its bounds, the pooling weight
      as a sentence ("estimate
      pooled toward 1.0; this
      judge's own data carries
      weight 0.62"), the cohort size
      and the eligible count, the
      period, the coverage, a link
      to `/models/<id>`, the
      methodology version as visible
      text linking to
      `/methodology#<slug>`, and the
      brief's interpretation ("An
      O/E ratio above 1 means
      observed outcomes exceeded the
      model's expected count for the
      defined cohort. …"). Every
      formatter is null-safe.
      `KIND_NOUN`, `KIND_TEXT`,
      `primaryFigure` (the ratio),
      `defaultSort`, and
      `COMPARED_KINDS` gain the
      kind.
    </requirement>

    <requirement>
      The judge page. `JUDGE_PANELS`
      gains `{ id: "adjusted",
      title: "Risk-adjusted
      comparison" }` selected by
      kind, after the outcomes
      panel; `panelDefinitions` and
      the "Other metrics" list
      exclude the adjusted kind; the
      panel reuses the page's
      `?window=` and `?cohort=`
      selectors, shows for each
      adjusted metric the
      `AdjustedStat`, the raw
      descriptive rate it adjusts
      (the matching `MetricStat` in
      its compact variant), the
      judge's position among the
      cohort's published pooled
      ratios (the existing
      `CohortPositionLine` over a
      `/metrics/compare` call sorted
      by `ratio`), and the cohort
      definition ("Expected counts
      from model expected-logit-v1,
      specification 1, fitted on N
      events of <source> (<coverage
      window>), adjusting for
      <features>; compared within
      <cohort label>"); "Report a
      data error" targets the
      panel's first adjusted
      observation. The association
      statement still renders once
      per page. `COURT_PANELS` is
      unchanged (adjusted metrics
      are judge-only), and the
      panel-id test becomes "court
      panel ids are a subset of
      judge panel ids".
    </requirement>

    <requirement>
      The compare page and the model
      page. `/compare` lists the
      adjusted metrics in its metric
      control; for the kind,
      `CompareTable` shows Judge,
      Court, Observed / Expected,
      O/E (pooled) with its
      interval, Pooling weight,
      Sample size, and Coverage,
      sorts by `ratio` by default,
      and the comparison notes state
      the formula `(α + O) / (α +
      E)` and link the methodology
      and the model.
      `web/app/models/[modelId]/page.tsx`
      (`force-dynamic`) renders the
      model card: target, window,
      status, the synthetic badge,
      the training window and
      counts, the validation summary
      with the calibration bins as a
      table, the coefficient table,
      the versions, and links to
      `/methodology#adjusted-statistics`
      and the validation report's
      section on
      `docs/VALIDATION.md`;
      `ErrorState` on failure, a 404
      page for an unknown id. The
      methodology page renders the
      `adjustment` block with an
      `id="adjusted-statistics"`
      section and the adjusted
      definitions through
      `KIND_TEXT`.
    </requirement>

    <requirement>
      Add web tests:
      - web/tests/unit/adjusted-stat.test.tsx:
        "renders every presentation
        field for a published ratio"
        (observed, expected, ratio,
        interval and its method,
        cohort size, eligible count,
        period, coverage, the model
        link, the visible
        methodology version, the
        interpretation); "renders
        the reason and no digit in
        the figure region for each
        suppression reason".
      - web/tests/unit/metrics.test.ts:
        the adjusted panel collects
        exactly the adjusted
        definitions; no other panel
        or the "Other metrics" list
        contains one; court panel
        ids are a subset of judge
        panel ids.
      - web/tests/unit/compare-table.test.tsx
        (or the existing file): the
        adjusted columns and the
        `ratio` sort; a suppressed
        adjusted row spans the
        figure columns.
      - web/tests/unit/model-page.test.tsx
        and the methodology page
        test: the card's tables; the
        adjustment section with its
        anchor.
      - web/tests/unit/fixtures/observations.ts:
        typed adjusted fixtures
        (published and each
        suppression reason).
      - web/tests/e2e/adjusted.spec.ts
        (the demo seed; discovers a
        judge with a published
        adjusted observation through
        the API): the judge page's
        adjusted panel shows a
        ratio, an interval, the
        methodology version, and a
        model link; switching
        `?window=` changes the
        panel's windows; the model
        link opens the card;
        `/compare` for
        `new_case_observed_expected`
        sorts by ratio; the
        methodology anchor
        `#adjusted-statistics`
        resolves; a judge whose
        adjusted row is suppressed
        shows the reason.
    </requirement>

    <requirement>
      Add API tests:
      tests/integration/test_api_adjusted.py
      (the golden compute: adjusted
      observations served with every
      new field; a suppressed one
      withholds every figure and
      keeps its reason; the model
      card's fields, no
      `storage_uri`, 404 for an
      unknown id, 422 for a
      malformed one; the provenance
      model block; `sort=ratio`
      ordering with suppressed rows
      last),
      `tests/unit/test_schemas_metrics.py`
      (suppression of the new
      fields; the interval method),
      and the budgets in
      `tests/integration/test_query_counts.py`.
    </requirement>

    <requirement>
      Capture screenshots of the
      judge page's adjusted panel,
      the adjusted compare table,
      and the model card, light and
      dark, into
      `docs/screenshots/phase04-step5/`
      with a `README.md`, as
      `docs/screenshots/phase03-step4/`
      does.
    </requirement>

    <requirement>
      Documentation: `docs/API.md`
      (the adjusted fields, the
      model card, `sort=ratio`, the
      provenance model block; the
      hold-out note removed),
      `docs/ARCHITECTURE.md` ("Web
      tier": `AdjustedStat` is the
      only renderer of an adjusted
      figure; "Public API v1": the
      model card),
      `docs/PROVENANCE.md`,
      `web/AGENTS.md`, `README.md`
      (the risk-adjusted panel; the
      seventeen first-milestone
      items unchanged), `AGENTS.md`,
      and `docs/ROADMAP.md`.
    </requirement>

    <requirement>
      Filepath comment: every new
      file gets the repo-relative
      path as the first line (`//
      web/…` for TypeScript).
    </requirement>
  </requirements>
</task>
```

### Step 5 acceptance criteria

- The API serves `observed_expected` observations with `expected`,
  `expected_rate`, `ratio`, `ratio_lower`, `ratio_upper`, `pooling_weight`,
  `model`, and `suppression_reason`, and a suppressed one withholds every figure
  while keeping its reason (`test_api_adjusted.py`, `test_schemas_metrics.py`).
- `GET /api/v1/models/{model_id}` returns the model card without `storage_uri`
  in one statement; the provenance body names the model; `/metrics/compare`
  sorts by `ratio` with suppressed rows last; `docs/openapi.json`,
  `web/lib/api/schema.d.ts`, `test_openapi.py` (21 paths), and the budgets are
  updated.
- Every adjusted statistic on the judge page, the compare page, and the model
  page shows observed, expected, the ratio, its interval and method, the cohort
  definition, the model, and the methodology version as visible text; a
  suppressed subject shows the reason and no figure (`adjusted-stat.test.tsx`,
  `metrics.test.ts`, `model-page.test.tsx`, the compare and methodology page
  tests).
- `web/tests/e2e/adjusted.spec.ts` passes over the demo seed locally and in the
  `e2e` CI job, beside the unchanged smoke, metrics, and first-milestone suites.
- `pnpm lint`, `pnpm typecheck`, `pnpm build`, and `pnpm test` pass; `uv run poe
  check` passes; every required CI check is green; the screenshots are
  committed.
- **Deployed & verified**: with `uv run poe dev-api` and `uv run poe dev-web`
  over the bootstrapped demo database, `GET
  http://localhost:8000/api/v1/judges/<a demo judge id>/metrics` lists the
  adjusted slugs, `http://localhost:3000/judges/<that id>` shows the
  "Risk-adjusted comparison" panel with a ratio, an interval, and "Methodology
  1.0", its model link opens `/models/<id>` with the coefficient table, and
  `/compare?metric=new_case_observed_expected&window=365&court_id=<court>` lists
  judges sorted by ratio.
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff — secret scan, `bandit`,
  `eslint-plugin-security`, `pip-audit`, and `pnpm audit` clean — and the public
  surface handles sensitive data per the project ROADMAP "Security & privacy
  strategy": no route or page returns a person key, a person-level row, a
  restricted attribute, or `storage_uri` (the public contract test), and a
  suppressed figure never leaves the API.

---

## Step 6 — QA & Verification Script

**Status:** Not started

> **Goal:** Package the verification matrix into `scripts/verify_phase04.py`
> (with `--fast`, `--py`, `--node`, `--e2e`, `--security`, `--all`, and `--post`
> modes, mirroring `verify_phase03.py`), produce `docs/phase04-qa-findings.md`,
> add `"04"` to the `phase-verify.yml` matrix and make `phase-verify (04)` a
> required context, update `docs/ROADMAP.md`, and tag `v0.4.0-phase-4`. The
> script checks every Step 1 through Step 5 deliverable statically and runs the
> Phase 4 pytest, Vitest, and Playwright suites in the appropriate modes; the
> `--post` mode runs the V1–V6 matrix, the seed and compute idempotency probes
> (a second compute fits no model and publishes nothing), `metrics verify`,
> `models verify --refit`, `validation report --check`, `validation recovery`, a
> `provenance trace` of a random current adjusted observation, the milestone
> items, and `gh pr checks`.

**Branch:** `feature/phase04-step6-verify`

**Deploys:** nothing beyond merge — the CI matrix entry is live on merge; the
tag is pushed after the merge.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                                      |
| ------------ | ---------------------------------------------------------- |
| Model        | Opus 5.5                                                   |
| Backup       | GPT-5.6 Terra — Codex · Intelligence Medium                |
| Platform     | Claude Code                                                |
| Effort       | Medium (Claude Code's default — no change, run as opened)  |
| Thinking     | On                                                         |
| Conversation | **New**                                                    |

**Model rationale:** This is the mechanical translation of `verify_phase03.py`
into Phase 4's deliverables — numbered static checks, mode dispatch, subprocess
suites, probes, the V-matrix, the findings rollup, a one-line matrix edit, the
required-context call, and the tag: PRIMARY `coding`, Medium complexity (a
bounded, well-specified, multi-file task following a known pattern with no novel
reasoning). Opus 5.5 is S-tier in coding (AA Intelligence Index 57.6 at max) and
the operator's `balanced` anchor for Medium work under the `capped` posture. The
Platform is Claude Code on the $200 claude.ai Max subscription (weekly pool at
`headroom`): Effort `Medium`, which is Claude Code's default for Opus 5.5, so
the session runs as opened; Thinking `On`. Nothing in the step earns a raise —
the pattern is fixed by `verify_phase03.py`, and the CI matrix, the unit test,
and the `--post` probes catch any slip. Backup: GPT-5.6 Terra on Codex (the $100
ChatGPT Pro 5x pool), S-tier in coding from OpenAI and the cheaper of the S-tier
GPT models the coverage tie-break already favours, at Intelligence `Medium`.
Conversation is New per phase-boundary hygiene.

```xml
<task>
  <lifecycle>
    This step MUST follow all six
    stages, in order. Stages 1, 3,
    4, 5, 6 are AS BINDING as any
    `<requirement>` below. Do not
    emit the Stage 6 completion line
    until the PR is merged and every
    acceptance criterion for this
    step is affirmatively met.

    1. CREATE THE BRANCH. Before any
       Read / Edit / Bash, run `git
       checkout -b
       feature/phase04-step6-verify`
       from a clean, up-to-date
       `main`. The exact branch name
       is in this step's
       `**Branch:**` line above. If
       the Worktree rule applies,
       use `git fetch origin && git
       worktree add -b <branch>
       .worktrees/<slug>
       origin/main` instead, then
       bootstrap the worktree.

    2. WORK ON THE BRANCH. All
       commits land here. `main` is
       protected with
       `enforce_admins: true` —
       direct pushes will be
       rejected. Pass the security
       gate before every commit.
       Stop the local API before `uv
       run poe gate` or `git
       commit`.

    3. OPEN THE PR, THEN MARK THE
       STEP. `gh pr create --base
       main --head <branch>` with a
       Conventional Commits title
       and a body that references
       this roadmap step and its
       acceptance criteria. One PR
       per step. Then, in this
       roadmap file: set this step's
       `**Status:**` line (directly
       under its heading) to
       `Complete — PR #<n>
       (<YYYY-MM-DD>)`, append ` ✅`
       to the step's `## Step`
       heading, and set its Summary
       Table Status cell to
       `Complete — PR #<n>`. Commit
       that edit on the step branch
       and push — the PR carries its
       own completion mark, so the
       roadmap on `main` marks this
       step complete exactly when
       the PR merges (Status rule).
       Same commit: on the phase's
       first step, set this
       roadmap's phase-level
       `**Status:**` (under its
       title) and the parent project
       roadmap's Phase 4
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 4` heading.

    4. WAIT FOR GREEN CHECKS, THEN
       SQUASH-MERGE. Every required
       check must pass. If the PR
       falls behind main, refresh
       with `gh pr update-branch
       --rebase` — never merge main
       into the branch
       (`required_linear_history:
       true`). Once green: `gh pr
       merge <PR> --squash
       --delete-branch`. If this
       step's `**Deploys:**` line
       names a surface, the merge is
       not the finish line: run the
       Deployed & verified check
       against the local environment
       before declaring the step
       complete.

    5. RETIRE THE BRANCH. Sync
       local: `git switch main &&
       git pull --ff-only origin
       main && git fetch --prune
       origin`. Prune any local
       `[gone]` branches. If the
       step ran in a worktree, `git
       worktree remove <path>` FIRST
       — the branch prune fails
       while the branch is checked
       out there.

    6. DISPOSE OF EVERY FINDING,
       DECLARE COMPLETION, THEN NEW
       CONVERSATION. First send
       every finding this step
       surfaced to its destination
       (Triage rule): a note for a
       later step → edit that step's
       <task> block now; spec rot →
       edit this roadmap now; a bug
       → fixed in-step or an issue
       number; a judgement call in
       the diff → the PR body; a
       process lesson → written
       where the next conversation
       reads it (AGENTS.md or this
       roadmap); a data-semantics
       finding → the registry or
       model-specification entry,
       version bumped; a data-access
       question → a row in
       docs/ROADMAP.md. Update
       docs/ROADMAP.md (completed
       items, known issues, next
       milestones). A finding you
       can only describe is NOT
       disposed of, and counts as an
       unmet criterion. Only once
       the PR is merged — and `main`
       therefore carries this step's
       `Complete` Status line —
       every acceptance criterion is
       affirmatively met, and every
       finding has a destination,
       say so plainly: end your
       final response with an
       explicit, unhedged completion
       line — verbatim shape "Step 6
       is complete. Phase 4 is
       complete. You can now move on
       to Phase 5." That line is the
       LAST line of the response.
       NOTHING follows it — no
       "Follow-ups (non-blocking)",
       "Notes", "Next", "worth a
       glance", or suggested
       improvements. A short ledger
       may PRECEDE it, one entry per
       finding naming its
       destination (issue #, file
       edited, PR body) — never an
       open item. If any criterion
       is unmet or any finding has
       no destination, state plainly
       that the step is NOT
       complete, name what is
       outstanding, and omit the
       completion line. "Done" means
       done. Then, for
       phase-boundary hygiene, the
       operator closes this session
       and opens a fresh one before
       Phase 5.
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
       credentials, API keys,
       tokens, or real PII in the
       diff (gitleaks /
       detect-secrets or the
       project's equivalent).
       Secrets go in the secrets
       manager, never in source or
       committed env files. In this
       step: the script prints check
       names, ids, paths, counts,
       and exit codes — never a
       file's contents, an
       environment value, a pepper,
       a key, or a connection
       string; the findings document
       names synthetic ids only.

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. In
       this step: every subprocess
       runs from an argument list
       over a PATH-resolved
       executable with no shell (`#
       noqa: S603 - fixed argv, no
       shell # nosec B603`, the
       justification between the
       markers); static checks use
       `pathlib`, `re`, `json`,
       `hashlib`, and `git ls-files`
       only (no XML or YAML parser;
       the registry and the
       specification are read with
       line readers, pinned against
       `yaml.safe_load` by the unit
       test).

    3. DEPENDENCY AUDIT. Any new or
       bumped dependency passes the
       audit (pip-audit / npm audit
       / osv-scanner); no
       known-vulnerable, yanked, or
       typo-squatted package. This
       step adds no dependency. If
       one is added, it passes
       `pip-audit --strict
       --require-hashes`.

    4. SENSITIVE-DATA REVIEW.
       Whatever this step touches
       stays least-privilege,
       encrypted in transit + at
       rest, and out of logs and
       client bundles. If the step
       adds a data path, name how
       PII/secrets are protected. In
       this step: every writing
       probe runs inside
       `probe_environment()` against
       `JUDGEMETRICS_TEST_DATABASE_URL`
       and
       `data/snapshots/scratch-test-db`,
       never the live database; the
       alarm exercise tampers the
       scratch database and the
       scratch snapshot directory
       only and restores both.

    This step also AUTHORS the
    `--security` verify mode, so its
    own diff must still pass the
    gate before commit.

    A finding blocks the commit —
    fix it in this step, do not
    defer. Do not declare the step
    complete until the gate is
    clean. This is the safety net
    that stops a security issue from
    reaching the branch, the PR, or
    `main`.
  </security>

  <context>
    JudgeMetrics. Phase 4. Step 6:
    QA + verification script.

    Steps 1 through 5 have been
    implemented. Now create the
    verification script, the QA
    findings document, the CI matrix
    update, and the tag.

    Reference scripts (pattern
    templates):
    - scripts/verify_phase03.py
      (closest structural precedent:
      49 static checks,
      `probe_environment()`, the
      compute, verify, and trace
      probes, the milestone items,
      the V-matrix).
    - scripts/verify_phase02.py
      (secondary pattern reference).

    Phase 4 deliverables to verify
    (45 static checks across Steps 1
    through 5 plus 5 Step 6
    self-checks, 50 in all):

    Step 1 (planted effects and the
    restricted schema) — checks
    1–11:
    1. `synthetic/config.py` sets
       `GENERATOR_VERSION = "3"` and
       `synthetic/rng.py`
       `STREAM_NAMES` includes
       `effects` and `attributes`.
    2. `synthetic/truth.py` sets
       `TRUTH_VERSION = "3"` and
       `TRUTH_FILES` includes
       `effects.json`.
    3. The golden manifest's
       versions equal the source
       constants and are at least 3;
       `truth/effects.json` is
       tracked, listed,
       sha256-matched, and carries
       `judges`, `targets`
       (`pretrial_release`,
       `new_case`,
       `failure_to_appear`),
       `controls`, and
       `definitions`.
    4. `alembic/versions/0008_restricted_schema.py`
       creates the `restricted`
       schema and `party_attribute`,
       and never grants anything on
       them to the app role.
    5. `alembic/env.py` sets
       `include_schemas`.
    6. `infra/docker/postgres/03-test-database.sql`
       revokes the app role's usage
       on the `restricted` schema.
    7. `data/reference/case_vocabulary.yaml`
       is version 2 with
       `restricted_attribute`,
       `age_band`, and
       `synthetic_group`.
    8. `ingest/synthetic/normalize.py`
       no longer writes the
       normalized participant id
       into `source_row_id`, and the
       synthetic connector's
       `parser_version` is `"2"`.
    9. The log scrubber's
       `SENSITIVE_KEYS` includes
       `age_band`,
       `synthetic_group`, and
       `attribute_value`.
    10. `metrics/methodology.py`
        `CHANGELOG` carries `0.2`;
        `tests/unit/test_synthetic_effects.py`,
        `tests/property/test_effects_invariants.py`,
        `tests/integration/test_restricted_schema.py`,
        and
        `tests/unit/test_exposure_deferral.py`
        are tracked.
    11. `scripts/verify_phase03.py`
        check 14 reads the source
        constants (no literal `"2"`
        comparison remains).

    Step 2 (the specification and
    the baseline model) — checks
    12–20:
    12. `data/reference/outcome_model.yaml`
        is tracked, starts with its
        path comment, and has
        `version:`, `model_version:
        expected-logit-v1`, and the
        blocks `targets`,
        `features`, `excluded`,
        `model`, `temporal_split`,
        `seed`, `bootstrap`,
        `pooling`, `thresholds`,
        `recovery`.
    13. Every feature in the
        specification has `known_at`
        and `leakage` (line reader).
    14. `metrics/adjustment/` has
        `__init__`, `spec`,
        `features`, `logistic`,
        `resample`, `diagnostics`,
        `artifacts`, `fit`.
    15. No module under `metrics/`
        names `pickle`,
        `numpy.load`, `np.load`, or
        `eval(`, and `artifacts.py`
        creates files with `"xb"`.
    16. `numpy` is in
        `[project].dependencies` and
        `uv.lock`; `uv.lock` holds
        no scipy, scikit-learn,
        statsmodels, or pandas.
    17. `alembic/versions/0009_outcome_models.py`
        creates `outcome_model` with
        `content_hash` and
        `coefficients` and grants
        the app role `SELECT` from a
        constant.
    18. `cli.py` registers the
        `models` group with `fit`,
        `list`, `show`, `verify`,
        and `--refit`.
    19. The Step 2 test files
        (`test_outcome_model_spec.py`,
        `test_logistic.py`,
        `test_adjustment_features.py`,
        `test_feature_leakage.py`,
        `test_model_diagnostics.py`,
        `test_model_artifacts.py`,
        `test_outcome_models.py`)
        are tracked.
    20. The `e2e` job runs
        `judgemetrics models fit`
        and `models verify` after
        `metrics compute`, and the
        `container` job imports
        `judgemetrics.metrics.adjustment.logistic`
        in the API image.

    Step 3 (expected counts, ratios,
    pooling, recovery) — checks
    21–29:
    21. The registry is `version: 2`
        with the kind
        `observed_expected`, the
        three slugs, an `adjustment`
        block on each, and threshold
        30 on each.
    22. `metrics/adjustment/` has
        `expected`, `pooling`,
        `bootstrap`.
    23. `alembic/versions/0010_adjusted_observations.py`
        adds `outcome_model_id`,
        `pooling_weight`, and
        `suppression_reason` with
        its three values.
    24. `publish.VERIFIED_COLUMNS`
        includes `expected_count`,
        `expected_rate`,
        `standardized_ratio`,
        `pooling_weight`, and
        `suppression_reason`.
    25. `ingest/runner.recompute_metrics`
        restricts step 13 to the
        descriptive kinds.
    26. `tests/unit/test_pooling.py`,
        `tests/unit/test_bootstrap.py`,
        `tests/golden/test_golden_adjusted.py`,
        `tests/golden/test_golden_recovery.py`,
        and
        `tests/integration/test_api_adjusted.py`
        are tracked, and the
        specification's `recovery`
        block holds numbers.
    27. `api/routes/health.py`
        reports `models` under
        `metrics`.
    28. `metrics/provenance.py`
        names the model (its content
        hash) in the trace.
    29. `docs/DATA_MODEL.md` names
        `observed_expected`,
        `outcome_model`, and
        `party_attribute`;
        `docs/ARCHITECTURE.md` has a
        "Risk adjustment" heading.

    Step 4 (validation and
    methodology 1.0) — checks 30–37:
    30. `src/judgemetrics/validation/`
        has `__init__`, `report`,
        `fairness`, `sensitivity`,
        `stability`, `recovery`.
    31. Under `src/judgemetrics/`,
        `party_attribute`, a
        schema-qualified
        `restricted.<name>`, or
        `schema="restricted"`
        appears only in the modules
        `tests/unit/test_restricted_readers.py`
        allows
        (`validation/fairness.py`,
        the ORM model and
        `db/models/__init__.py`,
        `ingest/base.py`,
        `ingest/publish.py`,
        `ingest/runner.py`,
        `ingest/synthetic/`).
    32. `docs/VALIDATION.md` is
        tracked, starts with its
        path comment and the
        generated notice, carries
        the sections (summary,
        calibration, feature
        stability, missing-data
        sensitivity, bootstrap
        stability, subgroup
        calibration, recovery), and
        contains no UUID-shaped and
        no 64-hex string.
    33. The registry's
        `methodology_version` is
        `"1.0"`;
        `docs/METHODOLOGY.md` states
        methodology version 1.0, has
        `## Adjusted statistics`
        with the brief's
        `<interpretation>` text
        verbatim (regular expression
        over the brief, whitespace
        normalized), and keeps `##
        Known limitations` with the
        eight warnings.
    34. `metrics/methodology.py`
        `CHANGELOG` lists `0.1`,
        `0.2`, `0.3`, `1.0` in
        order.
    35. `cli.py` registers
        `validation report` (with
        `--check` and `--truth`) and
        `validation recovery`.
    36. The `e2e` job runs
        `judgemetrics validation
        report --check`.
    37. `test_validation_report.py`,
        `test_subgroup_calibration.py`,
        `test_fairness_analysis.py`,
        and
        `test_restricted_readers.py`
        are tracked.

    Step 5 (adjusted panels and the
    model card) — checks 38–45:
    38. `schemas/metrics.py` lists
        `observed_expected` in
        `MetricKind` and `bootstrap`
        in `IntervalMethod`,
        declares `ratio_lower`,
        `ratio_upper`,
        `pooling_weight`, and
        `suppression_reason`, and
        still names no person field.
    39. `api/routes/models.py`
        exists; `docs/openapi.json`
        includes
        `/api/v1/models/{model_id}`
        and every Phase 3 path (a
        subset check).
    40. `web/lib/api/schema.d.ts`
        names
        `/api/v1/models/{model_id}`
        and `observed_expected`.
    41. `web/components/adjusted-stat.tsx`
        has
        `data-testid="adjusted-stat"`,
        `data-reason`, the bootstrap
        interval text, and
        `methodologyHref`.
    42. `web/app/models/[modelId]/page.tsx`
        exists; `JUDGE_PANELS` has
        the `adjusted` panel; the
        judge page still renders one
        `association-statement`.
    43. `web/app/methodology/page.tsx`
        has the
        `adjusted-statistics`
        section.
    44. `web/tests/unit/adjusted-stat.test.tsx`,
        `web/tests/unit/model-page.test.tsx`,
        and
        `web/tests/e2e/adjusted.spec.ts`
        (at least five tests) are
        tracked.
    45. `docs/screenshots/phase04-step5/README.md`
        exists beside non-empty
        `*-light.png` and
        `*-dark.png`.

    Step 6 self-checks — checks
    46–50:
    46. scripts/verify_phase04.py is
        tracked, starts with `#
        scripts/verify_phase04.py`,
        and has an `add_argument`
        for each of the seven modes.
    47. docs/phase04-qa-findings.md
        carries `## Step 1` … `##
        Step 6`, `### Alarm
        exercise`, `## Pre-ship
        items`, and `## Phase 5
        carry-over checklist`.
    48. docs/roadmap/phase04-roadmap.md
        exists (this doc).
    49. .github/workflows/phase-verify.yml's
        matrix includes `"01"`,
        `"02"`, `"03"`, and `"04"`
        (a subset check) and every
        `uses:` is SHA-pinned.
    50. Security wiring: the
        pre-commit hooks run
        detect-secrets, bandit, and
        pip-audit through
        `scripts/audit_deps.py`;
        `ci.yml` and
        `phase-verify.yml` declare
        top-level `permissions:`; no
        PEM private-key header,
        `AKIA` key prefix, or
        five-dash `BEGIN` line in
        tracked files under `src`,
        `alembic`, `scripts`,
        `web/app`, `web/components`,
        `web/lib`, `data/reference`,
        or `docs` (the brief
        excepted).

    Files to read:
    - scripts/verify_phase03.py
      (primary structural template)
      and
      tests/unit/test_phase03_verification.py.
    - All Phase 4 implementation
      files from Steps 1 through 5,
      the Phase 4 PR bodies, and
      `docs/ROADMAP.md` known issues
      (the findings to roll up).
    - .github/workflows/phase-verify.yml,
      .github/workflows/ci.yml, and
      CONTRIBUTING.md "Repository
      settings".
    - docs/phase03-qa-findings.md
      (the rollup structure, the
      alarm exercise, the carry-over
      checklist).
  </context>

  <goal>
    Create scripts/verify_phase04.py
    with the 50 static checks above
    plus a post-implementation V1–V6
    matrix and the `--post` probes;
    create
    docs/phase04-qa-findings.md; add
    `"04"` to the phase-verify.yml
    matrix and make `phase-verify
    (04)` a required context; update
    docs/ROADMAP.md; tag
    `v0.4.0-phase-4`.
  </goal>

  <requirements>
    <requirement>
      Read scripts/verify_phase03.py
      end-to-end for structure, flag
      parsing, output format, the
      `report` and `Outcome`
      conventions,
      `probe_environment()`, and the
      final summary table. Mirror
      the format exactly so the
      Phase 4 script is visually
      continuous with the Phase 3
      script in CI logs.
    </requirement>

    <requirement>
      scripts/verify_phase04.py
      modes:
      - default (no flag): `--fast`
        plus `--py`.
      - --fast: the 50 static checks
        only, CI-safe on Ubuntu,
        standard library only; under
        30 seconds.
      - --py: static + `uv run poe
        lint`, `fmt-check`,
        `typecheck`, and pytest
        unit, integration, property,
        and golden (SKIP without a
        configured database, as
        Phase 3 does).
      - --node: static + `pnpm
        lint`, `typecheck`, `build`,
        `test` with cwd `web/`.
      - --e2e: static + `pnpm e2e`
        (smoke, metrics, first
        milestone, adjusted), SKIP
        when the API or the web app
        does not answer.
      - --security: the gate over
        the tracked files —
        `detect-secrets-hook
        --baseline` in argv-bounded
        batches, `bandit -c
        pyproject.toml -r src
        alembic scripts`,
        `scripts/audit_deps.py`,
        `pnpm audit
        --audit-level=high`; exits
        non-zero on any finding.
      - --all: static + e2e + node +
        py + security (e2e before
        py, as Phase 3 orders them).
      - --post: static + the V1–V6
        matrix + the probes, in
        Phase 3's order: `gh pr
        checks`;
        `probe_environment()`; the
        milestone setup (`uv sync`,
        `poe up`, `poe migrate`,
        `poe seed`, the `bootstrap`
        rerun, all on the scratch
        database); the seed probe
        (row counts of Phase 3's
        fifteen tables plus
        `outcome_model` unchanged
        across a second
        `judgemetrics seed`); the
        compute probe (a second
        `metrics compute --json`
        fits no model and publishes
        nothing); `metrics verify`;
        `models verify --refit`;
        `validation report --check
        --truth <the probe's
        dataset>`; `validation
        recovery --truth <the same>
        --json` within tolerance; a
        `provenance trace` of a
        random current
        `observed_expected`
        observation reporting
        `complete: yes`; the
        reachability items; the e2e,
        node, and security suites;
        the V-suites; `uv run poe
        check`; the V rows. Every
        check prints `[PASS] NN`,
        `[FAIL] NN — reason`, or
        `[SKIP] id — reason`;
        captured children get
        `PYTHONIOENCODING=utf-8`;
        the script exits 0 on
        success and 1 on any
        failure.
    </requirement>

    <requirement>
      Post-implementation V-checks
      (V1–V6):
      - V1: V1.1 statics 1–11; V1.2
        `test_synthetic_effects.py`,
        `test_effects_invariants.py`
        (`HYPOTHESIS_PROFILE=ci`),
        `test_frame_invariants.py`,
        `test_exposure_deferral.py`;
        V1.3
        `test_restricted_schema.py`,
        `test_migrations.py`,
        `test_synthetic_ingest.py`;
        V1.4
        `test_golden_fixture.py`,
        `test_golden_metrics.py`,
        `test_public_contract.py`.
      - V2: V2.1 statics 12–20; V2.2
        the Step 2 unit tests; V2.3
        `test_feature_leakage.py`;
        V2.4
        `test_outcome_models.py`;
        V2.5 the `models verify
        --refit` probe.
      - V3: V3.1 statics 21–29; V3.2
        `test_pooling.py`,
        `test_bootstrap.py`,
        `test_api_adjusted.py` (the
        hold-out); V3.3
        `test_golden_adjusted.py`,
        `test_golden_recovery.py`;
        V3.4 the compute and verify
        probes; V3.5 the adjusted
        provenance trace probe.
      - V4: V4.1 statics 30–37; V4.2
        `test_validation_report.py`,
        `test_subgroup_calibration.py`,
        `test_fairness_analysis.py`,
        `test_restricted_readers.py`,
        `test_methodology_render.py`;
        V4.3 the `validation report
        --check` and `validation
        recovery` probes (the `e2e`
        CI job runs the check too).
      - V5: V5.1 statics 38–45; V5.2
        `test_api_adjusted.py`,
        `test_schemas_metrics.py`,
        `test_query_counts.py`,
        `test_openapi.py`,
        `test_public_contract.py`;
        V5.3 the node suites; V5.4
        the Playwright suites with
        `adjusted.spec.ts` (the
        `e2e` CI job when `--e2e` is
        SKIP).
      - V6: V6.1 `verify_phase04.py
        --fast` exits 0 on Ubuntu CI
        (`phase-verify (04)`); V6.2
        static 49; V6.3 all 50
        statics; V6.4 the security
        suites.
    </requirement>

    <requirement>
      Add
      tests/unit/test_phase04_verification.py:
      the roadmap and the QA
      document start with their path
      comments; the QA document
      carries every section;
      `--fast` exits 0 with exactly
      50 passes; the matrix contains
      `{"01", "02", "03", "04"}` as
      a subset (never the exact list
      — Phase 3 finding 6.1),
      `permissions` is `{"contents":
      "read"}`, and no
      `JUDGEMETRICS_` variable
      appears in the workflow; the
      standard-library readers of
      the registry's limitations,
      the specification's features,
      and the brief's warnings and
      interpretation equal their
      `yaml.safe_load` and
      regular-expression references.
    </requirement>

    <requirement>
      Update
      .github/workflows/phase-verify.yml
      to include `"04"` in the
      matrix — append it to the
      existing `matrix.phase` list,
      preserving every prior entry.
      After the PR's `phase-verify
      (04)` check has run once, add
      it to the required contexts
      with `gh api -X PATCH
      repos/nathanramoscfa/judge-metrics/branches/main/protection/required_status_checks
      --input -` (the body
      `{"strict": true, "contexts":
      ["test", "phase-verify (01)",
      "phase-verify (02)",
      "phase-verify (03)",
      "phase-verify (04)"]}`), and
      update `CONTRIBUTING.md`
      "Repository settings" (five
      contexts).
    </requirement>

    <requirement>
      Create
      docs/phase04-qa-findings.md
      with a rollup section per step
      (every finding, its class, and
      the guard added), the Step 6
      verify-script rollup, an
      "Alarm exercise" section
      recording (a) a deliberately
      broken static check on the PR
      failing `phase-verify (04)`
      and `test`, then both passing
      after the fix, (b) one current
      adjusted observation's
      `standardized_ratio` tampered
      in the scratch database and
      `metrics verify` exiting 1
      naming the observation, the
      slug, the subject, the window,
      and the column, then 0 after
      the restore, and (c) one byte
      of one model artifact under
      `data/snapshots/scratch-test-db`
      changed and `models verify`
      exiting 1 naming the model,
      then 0 after the restore; a
      "Pre-ship items" section (the
      documented limitations at the
      tag: synthetic-only
      validation, the age band
      excluded by policy, intervals
      conditional on the
      specification, the step-13
      exception, thresholds chosen
      before real data); and a
      "Phase 5 carry-over checklist"
      (Phase 3's items 4, 7, and 9;
      the refit of the model on real
      data under a specification
      bump and per-metric
      thresholds; Cook County's
      restricted attributes into
      `restricted.party_attribute`
      and the fairness analysis on
      real data, with Phase 6 §6.1;
      the calendar-period cohorts
      and the compare page's period
      filter; a real connector's
      `case_party.source_row_id`
      never holding a source
      identifier;
      `verify_phase05.py` following
      this pattern with subset
      assertions; items owned by
      Phases 6–8 named with their
      phase).
    </requirement>

    <requirement>
      Mark the phase complete in the
      parent project roadmap
      (docs/roadmap/ROADMAP.md,
      beside this file) in the SAME
      Stage-3 commit that marks this
      step (Status rule):
      - `### Phase 4` gets
        `**Status:** Complete —
        <YYYY-MM-DD>; PR #<n>;
        v0.4.0-phase-4;
        phase04-roadmap.md` directly
        under its heading, and the
        heading ends in ✅.
      - Its row in the "Phase
        Complexity Summary" table
        reads `Complete` (Step 1's
        PR set it to `In progress`).
      - The header `> **Status:**`
        line names Phase 4 as
        shipped and Phase 5 as next.
      - Consistency audit: the Phase
        4 "Acceptance criteria"
        there match this roadmap's
        V1–V6 checks. And in THIS
        roadmap, same commit: its
        phase-level `**Status:**`
        line (under the title) reads
        `Complete — <YYYY-MM-DD>`,
        the title and every step
        heading end in ✅, and every
        step's Summary Table Status
        cell reads `Complete —
        PR #<n>`.
    </requirement>

    <requirement>
      Update docs/ROADMAP.md
      (current phase → Phase 5 not
      started; completed items;
      known issues; the pre-ship
      items; next milestones: the
      Phase 5 roadmap from a
      re-exported kit). After the
      squash-merge, tag the merge
      commit `v0.4.0-phase-4` and
      push the tag.
    </requirement>

    <requirement>
      Script must print clear pass /
      fail per check, exit 0 on
      success, exit 1 on any
      failure, and mirror the exact
      output format, check-numbering
      convention, and summary table
      from verify_phase03.py so CI
      log diffing across phases is
      frictionless. `--fast` must
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

- `scripts/verify_phase04.py` exists, is tracked, and passes on a clean tree
  post-implementation; `tests/unit/test_phase04_verification.py` passes.
- The script has 50 deliverable checks plus the V1–V6 post-implementation checks
  and the `--post` probes.
- `--fast` runs in under 30 seconds on Ubuntu CI.
- `--post` runs cleanly on the maintainer's machine (Docker Desktop, `dev-api`,
  and `dev-web` running) with every probe green: the seed and compute
  idempotency probes, `metrics verify`, `models verify --refit`, `validation
  report --check`, `validation recovery`, and a complete adjusted provenance
  trace.
- `docs/phase04-qa-findings.md` is complete with every rollup section, the alarm
  exercise, the pre-ship items, and the Phase 5 carry-over checklist.
- `.github/workflows/phase-verify.yml` matrix includes `"04"`; `phase-verify
  (04)` appears on every PR and is a required context on `main` beside `test`,
  `(01)`, `(02)`, and `(03)`.
- `--security` mode exists and exits 0 (secret/PII scan, SAST, and dependency
  audit clean over the phase's surface); V6.4 is green.
- Branch protection still passes on the resulting PR; the tag `v0.4.0-phase-4`
  marks the merge commit.
- **Operations**: the analytics surface's health signals (`/api/v1/ready`
  `metrics.models`; `metrics verify` and `models verify --refit` green) and
  alarms (`metrics verify` non-zero on a tampered adjusted observation, `models
  verify` non-zero on a tampered artifact, `validation report --check` non-zero
  on drift) exist, and the first two were seen to fire once in the alarm
  exercise, recorded with their output in `docs/phase04-qa-findings.md`.
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff and the security workflow is green.
- **Phase closed, nothing carried.** Every finding recorded in
  `docs/phase04-qa-findings.md` has a destination (fixed, an issue number, or a
  named phase that owns it), the "Not in scope" section below is current, and no
  un-tracked item remains. Every step of this roadmap, this one included, reads
  `**Status:** Complete — PR #…` on `main` under a ✅ heading, the Summary
  Table's Status column and this roadmap's phase-level Status line say
  `Complete` under a ✅ title, and the parent project roadmap's Phase 4 entry
  (under a ✅ heading), its summary-table row, and its header status line say
  `Complete` — all landed in this step's PR. This step's final response ends
  with two lines and nothing after them: "Step 6 is complete. You can now move
  on to Step 7." is replaced by "Step 6 is complete. Phase 4 is complete. You
  can now move on to Phase 5." — same Stage 6 rule: no "Follow-ups", no trailer.

---

## Post-Implementation Verification

Every V1–V6 check below runs automatically in CI on every push and pull request
— no manual invocation required — except V2.5, V3.4, V3.5, the local half of
V4.3, and the `--post` sweep, which the operator runs on the maintainer's
machine against the Compose services and the scratch database before tagging
`v0.4.0-phase-4` (the `e2e` CI job covers V4.3's `validation report --check` and
V5.4 on Ubuntu over the FJC fixture plus the demo seed; the refit, idempotency,
recovery, and trace probes write, so they run only inside
`probe_environment()`).

| Mode         | Workflow                                     | Runner           | Coverage                                                            |
| ------------ | -------------------------------------------- | ---------------- | ------------------------------------------------------------------- |
| `--fast`     | `phase-verify.yml` (matrix entry `04`)       | Ubuntu           | Static checks 1–50, V1.1, V2.1, V3.1, V4.1, V5.1, V6.1–V6.3          |
| `--py`       | `ci.yml` (`python` job, Postgres service)    | Ubuntu           | V1.2–V1.4, V2.2–V2.4, V3.2, V3.3, V4.2, V5.2                         |
| `--node`     | `ci.yml` (`web` job)                         | Ubuntu           | V5.3                                                                |
| `--e2e`      | `ci.yml` (`e2e` job, demo seed)              | Ubuntu           | V4.3 (`validation report --check`), V5.4                            |
| `--security` | `ci.yml` (`security` and `container` jobs) + `phase-verify.yml` | Ubuntu | V6.4                                                        |
| `--post`     | local (maintainer's machine)                 | Windows / Ubuntu | Full V1–V6 sweep + V2.5 + V3.4 + V3.5 + V4.3 + `gh pr checks`        |

Local invocations remain available for ad-hoc runs and pre-release sweeps:

```bash
uv run python scripts/verify_phase04.py --post   # static + V1-V6 + probes + milestone items + gh pr checks
```

`--post` is the canonical command to run before tagging the phase release.

Other modes:

```bash
uv run python scripts/verify_phase04.py             # static + Python suites
uv run python scripts/verify_phase04.py --fast      # static only (CI)
uv run python scripts/verify_phase04.py --py        # static + ruff + mypy + pytest (unit, integration, property, golden)
uv run python scripts/verify_phase04.py --node      # static + web lint/typecheck/build/test
uv run python scripts/verify_phase04.py --e2e       # static + Playwright (smoke, metrics, first milestone, adjusted)
uv run python scripts/verify_phase04.py --security  # secret scan + SAST + audits
uv run python scripts/verify_phase04.py --all       # everything
```

The script reports each V-check by id (V1.1, V2.1, …) so a failure in any
workflow above maps directly to the corresponding row below.

### V1 — Planted effects, synthetic restricted attributes, restricted schema

> **Automated in CI.** `phase-verify.yml` → V1.1; `ci.yml` → V1.2 through V1.4.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V1.1 | Static checks 1–11 all PASS (versions 3, the new streams, `effects.json` in the manifest, migration 0008 with no app grant, `include_schemas`, the scratch re-revoke, vocabulary 2, the participant-id key gone, the scrubber, the 0.2 changelog, Phase 3 check 14 reading the constants). | `phase-verify.yml` runs `verify_phase04.py --fast`. |
| V1.2 | `test_synthetic_effects.py` (observable-only assignment, confounding, oracle ranking and totals, cohort equality, group independence), `test_effects_invariants.py` under the `ci` profile, `test_frame_invariants.py`, and `test_exposure_deferral.py` (any-term deferral, engine equals truth) pass. | `ci.yml` `python` job (`HYPOTHESIS_PROFILE=ci`). |
| V1.3 | `test_restricted_schema.py` (no app-role usage or select; ingest reads and writes), `test_migrations.py` through 0008, and `test_synthetic_ingest.py` (party attributes, ordinal keys) pass. | `ci.yml` `python` job with the `postgres:17` service. |
| V1.4 | `test_golden_fixture.py` at versions 3/3, `test_golden_metrics.py` under methodology 0.2 and later, and `test_public_contract.py` (no participant id in any app-readable column; no restricted name in any response) pass. | `ci.yml` `python` job. |

### V2 — Feature specification, leakage review, baseline model

> **Automated in CI.** `phase-verify.yml` → V2.1; `ci.yml` → V2.2 through V2.4;
> local `--post` → V2.5.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V2.1 | Static checks 12–20 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V2.2 | `test_outcome_model_spec.py`, `test_logistic.py`, `test_adjustment_features.py`, `test_model_diagnostics.py`, and `test_model_artifacts.py` (the inspection test included) pass. | `ci.yml` `python` job. |
| V2.3 | `test_feature_leakage.py` passes under the `ci` profile: no feature reads its future; UUID relabelling changes nothing. | `ci.yml` `python` job. |
| V2.4 | `test_outcome_models.py` passes: idempotent fit, `models verify --refit` reproduces and catches a changed byte, the app role reads and cannot write. | `ci.yml` `python` job; the `e2e` job runs `models fit` and `models verify` on the demo seed. |
| V2.5 | `models verify --refit` exits 0 against the scratch database's latest snapshot. | `--post` locally. |

### V3 — Expected counts, ratios, partial pooling, recovery

> **Automated in CI.** `phase-verify.yml` → V3.1; `ci.yml` → V3.2 and V3.3;
> local `--post` → V3.4 and V3.5.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V3.1 | Static checks 21–29 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V3.2 | `test_pooling.py`, `test_bootstrap.py`, and `test_api_adjusted.py` (the adjusted kind held out of every public response) pass. | `ci.yml` `python` job.                                  |
| V3.3 | `test_golden_adjusted.py` (exact observed counts, suppression reasons, verify, tamper detection, no court subject, no step-13 publication or supersession) and `test_golden_recovery.py` (the planted ranking recovered within the specification's tolerance, better than raw rates) pass. | `ci.yml` `python` job. |
| V3.4 | A second `metrics compute` fits no model and publishes nothing; `metrics verify` exits 0 with the adjusted observations counted. | `--post` locally. |
| V3.5 | `provenance trace` of a random current adjusted observation names its model and prints `complete: yes`. | `--post` locally. |

### V4 — Validation report and methodology 1.0

> **Automated in CI.** `phase-verify.yml` → V4.1; `ci.yml` `python` → V4.2;
> `ci.yml` `e2e` and local `--post` → V4.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V4.1 | Static checks 30–37 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V4.2 | `test_validation_report.py`, `test_subgroup_calibration.py` (positive and negative controls), `test_fairness_analysis.py` (ingest role only, aggregate cells, small cells withheld), `test_restricted_readers.py` (the one reader), and `test_methodology_render.py` (1.0, the changelog, the interpretation verbatim, the limitations unchanged) pass. | `ci.yml` `python` job. |
| V4.3 | `validation report --check` exits 0 on the demo seed and `validation recovery` meets the tolerances on the database path. | `ci.yml` `e2e` job (`--check`); `--post` locally (both). |

### V5 — Risk-adjusted panels, adjusted compare, model card

> **Automated in CI.** `phase-verify.yml` → V5.1; `ci.yml` `python` → V5.2;
> `ci.yml` `web` → V5.3; `ci.yml` `e2e` → V5.4.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V5.1 | Static checks 38–45 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V5.2 | `test_api_adjusted.py` (every adjusted field, suppression withholds every figure, the model card, the provenance model block, `sort=ratio`), `test_schemas_metrics.py`, `test_query_counts.py`, `test_openapi.py` (21 paths), and `test_public_contract.py` pass. | `ci.yml` `python` job. |
| V5.3 | `pnpm lint`, `pnpm typecheck`, `pnpm build`, and `pnpm test` pass (`adjusted-stat.test.tsx`, the panel placement, the compare table, the model and methodology pages, schema freshness, the bundle scan). | `ci.yml` `web` job (`--node` locally). |
| V5.4 | `adjusted.spec.ts` passes over the demo seed beside the smoke, metrics, and first-milestone suites. | `ci.yml` `e2e` job (`--e2e` locally). |

### V6 — CI integration + security

> **Automated in CI.** `phase-verify.yml` → V6.1 through V6.4 on every push/PR.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V6.1 | `verify_phase04.py --fast` exits 0 on Ubuntu CI.                            | `phase-verify.yml` matrix entry `04`.                   |
| V6.2 | `phase-verify.yml` matrix includes `04`.                                    | `phase-verify.yml --fast` static check 49.              |
| V6.3 | All 50 static checks in `verify_phase04.py` pass.                           | `phase-verify.yml --fast` records pass only when zero static failures. |
| V6.4 | `verify_phase04.py --security` exits 0 (secret/PII scan + SAST + dependency audits clean). | `phase-verify.yml` runs `--security` on every push/PR. |

---

## Summary Table

| Step | Scope                                          | Model    | Platform    | Reasoning dial | Thinking | Conv | Status      |
| ---- | ---------------------------------------------- | -------- | ----------- | -------------- | -------- | ---- | ----------- |
| 1    | Planted effects, restricted schema             | Opus 5.5 | Claude Code | Effort XHigh   | On       | New  | Complete — PR #37 |
| 2    | Feature specification, baseline model          | Opus 5.5 | Claude Code | Effort XHigh   | On       | New  | Not started |
| 3    | Expected counts, ratios, pooling, recovery     | Opus 5.5 | Claude Code | Effort XHigh   | On       | New  | Not started |
| 4    | Validation report, methodology 1.0             | Opus 5.5 | Claude Code | Effort High    | On       | New  | Not started |
| 5    | Adjusted panels, compare, model card           | Opus 5.5 | Claude Code | Effort High    | On       | New  | Not started |
| 6    | QA + verify_phase04.py                         | Opus 5.5 | Claude Code | Effort Medium  | On       | New  | Not started |
| V1   | Planted effects and restricted schema scope    | CI: phase-verify.yml, ci.yml | -- | --     | --       | --   | --          |
| V2   | Specification and model scope                  | CI: phase-verify.yml, ci.yml | -- | --     | --       | --   | --          |
| V3   | Estimator and recovery scope                   | CI: phase-verify.yml, ci.yml | -- | --     | --       | --   | --          |
| V4   | Validation and methodology scope               | CI: phase-verify.yml, ci.yml | -- | --     | --       | --   | --          |
| V5   | Panels, compare, and model card scope          | CI: phase-verify.yml, ci.yml | -- | --     | --       | --   | --          |
| V6   | CI integration                                 | CI: phase-verify.yml | --  | --             | --       | --   | --          |

Backups (same platform rules, different provider): GPT-5.6 Sol on Codex at
Intelligence Extra High for Step 1 and at Intelligence High for Step 5; GPT-5.6
Terra on Codex at Intelligence Extra High for Steps 2 and 3, High for Step 4,
and Medium for Step 6. Both run on the $100 ChatGPT Pro 5x pool, the operator's
deliberate second funded pool for a Claude outage or a `tight` or `exhausted`
Claude weekly pool; neither is a `*-codex` variant, which the operator's
ChatGPT-account Codex sign-in cannot run.

---

## Model selection blocks

**Selection method.** Each block below was produced by running the selector in
`planning/model-selector.txt` against `planning/user-context.md` and the prices
in `planning/model-tier-cost-scale.md`, with the kit exported by roadmodel
0.2.51 (re-exported with `uv run poe kit` at the start of this phase; since the
Phase 3 export the catalog adds Claude Sonnet 5.5, marks Claude Opus 5
superseded by Opus 5.5 and Fable 5 by Fable 5.1, and adds the GLM 5.3 models),
in the selector's own step order: its Step 0a dropped no model (the cold-start
availability list is empty and no runtime override was supplied); Step 0b
dropped every `cn`-jurisdiction model (Kimi, DeepSeek, GLM) under the default
allowed list `us, eu, uk, ca, au, jp, kr`; Grok and Composer stay unreachable
(no xAI key, no Cursor subscription); its Steps 1–3 rated this roadmap's Steps 1
through 5 High complexity, which requires S in the PRIMARY category, and this
roadmap's Step 6 Medium; its Step 4 ranked the S-tier coders (Opus 5.5, Fable
5.1, GPT-5.6 Sol, GPT-5.6 Terra, GPT-6 Astra) by the SECONDARY rating and then
by coverage, and a superseded model yields to its successor as the catalog's
rows direct; its Step 5 output-price tie-breaker removed Fable 5.1 ($50 against
$20) from every tie with Opus 5.5, and the tie between Opus 5.5 and GPT-5.6 Sol
at $20 went to the operator's platform order, which puts Claude Code (claude.ai
Max) ahead of Codex (ChatGPT Pro 5x), so the GPT model became the required
cross-provider BACKUP (its Step 7): GPT-5.6 Sol where the SECONDARY is
`planning` or `agentic` (S-tier; ahead of GPT-6 Astra on coverage), GPT-5.6
Terra where it is `knowledge` (A-tier like Sol, with seven S or A ratings
against Sol's six); for this roadmap's Medium QA step the operator's `balanced`
posture names Opus 5.5 at Claude Code's default Medium as its anchor, and the
backup follows the posture's close-quality rule to the cheaper S-tier GPT model,
GPT-5.6 Terra. The parent roadmap's §8 row assigned Fable 5.1 to Phase 4's
methodology and validation; the operator's context of 2026-09-22 supersedes it
(Opus 5.5 outscores Fable 5.1 on reasoning at 40% of the price, and Fable draws
the weekly pool fastest under a 50% sub-cap), and the algorithm's cost
tie-breaker agrees. Access selection Step C ranked `claude-code` first as
subscription-funded (weekly pool at `headroom`); Step E applied the `capped`
consumption posture, which closes the flat-funding gate, so the complexity
ladder is the final effort: Extra High for the three steps with novel
problem-solving and multi-step proof, High for the two High-complexity steps
without them, and Medium — Claude Code's default for Opus 5.5 — for the QA step;
`Max` is reserved for demonstrated reasoning-depth bottlenecks and none is
claimed; Step E2 emitted `ORCHESTRATION: None` because no step is an exhaustive
audit, review, or research sweep; Step F emitted no MAX MODE line (Claude Code
has no such dial).

```text
PROMPT: Step 1 — Planted Effects, Synthetic Restricted Attributes, and the Restricted Schema
MODEL: Opus 5.5
BACKUP: GPT-5.6 Sol
PLATFORM: Claude Code
EFFORT: XHigh
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: coding with a novel causal-generator design whose oracle probabilities the truth must compute exactly, plus a least-privilege schema and an engine semantics change, secondary planning. PICK: Opus 5.5 is S-tier in coding and S-tier in planning (AA Intelligence Index 57.6 at max) and wins the $20 tie with GPT-5.6 Sol on the operator's platform order. EFFORT: Extra High with thinking on because the step meets the novel-problem and cross-file conditions under the capped posture's final ladder; orchestration None for one scoped deliverable.

PROMPT: Step 2 — Feature Specification, Leakage Review, and the Baseline Model
MODEL: Opus 5.5
BACKUP: GPT-5.6 Terra
PLATFORM: Claude Code
EFFORT: XHigh
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: coding of a penalized solver, a leakage-safe feature builder, and deterministic artifacts against a statistical contract, secondary knowledge. PICK: Opus 5.5 is S-tier in coding and S-tier in knowledge (HLE 61.4% at max) and beats the tied Fable 5.1 on output price. EFFORT: Extra High with thinking on for the novel-problem and multi-step-proof conditions (optimality, order invariance, the strictly-before rule); orchestration None.

PROMPT: Step 3 — Expected Counts, Ratios, Partial Pooling, and the Recovery Test
MODEL: Opus 5.5
BACKUP: GPT-5.6 Terra
PLATFORM: Claude Code
EFFORT: XHigh
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: coding of an empirical-Bayes estimator and a refitting bootstrap wired through compute, publish, verify, and provenance with a recovery proof, secondary knowledge. PICK: Opus 5.5 is S-tier in coding and S-tier in knowledge (AA Intelligence Index 57.6 at max) and beats the tied Fable 5.1 on output price. EFFORT: Extra High with thinking on because byte-for-byte reproducibility and the recovery tolerance are multi-step proofs across files; orchestration None.

PROMPT: Step 4 — Validation Report and Methodology 1.0
MODEL: Opus 5.5
BACKUP: GPT-5.6 Terra
PLATFORM: Claude Code
EFFORT: High
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: coding of a generated validation report, the one restricted-schema reader, and methodology prose over existing estimators, secondary knowledge. PICK: Opus 5.5 is S-tier in coding and S-tier in knowledge (HLE 61.4% at max) and beats the tied Fable 5.1 on output price. EFFORT: High with thinking on for the High-complexity rung without novel problem-solving, a raise from Claude Code's default Medium; orchestration None.

PROMPT: Step 5 — Risk-Adjusted Panels, Adjusted Compare, and the Model Card
MODEL: Opus 5.5
BACKUP: GPT-5.6 Sol
PLATFORM: Claude Code
EFFORT: High
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: multi-surface coding across schemas, a route, components, pages, the generated client, and Playwright under a mechanically enforced presentation contract, secondary agentic. PICK: Opus 5.5 is S-tier in coding and S-tier in agentic (AA Intelligence Index 57.6 at max), beats the tied Fable 5.1 on output price, and wins the $20 tie with GPT-5.6 Sol on the operator's platform order. EFFORT: High with thinking on because the scope is cross-cutting but the patterns are Phase 3's; orchestration None.

PROMPT: Step 6 — QA + verify_phase04.py
MODEL: Opus 5.5
BACKUP: GPT-5.6 Terra
PLATFORM: Claude Code
EFFORT: Medium
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: Medium-complexity mechanical translation of the Steps 1–5 deliverables into numbered static checks, mode dispatch, probes, and a CI matrix entry, following verify_phase03.py. PICK: Opus 5.5 is S-tier in coding (AA Intelligence Index 57.6 at max) and the operator's balanced anchor for Medium work under the capped posture. EFFORT: Medium (Claude Code's default, run as opened) with thinking on because the pattern is fixed and CI catches slips; orchestration None.
```

---

## Not in scope (from product roadmap)

Per [`ROADMAP.md`](ROADMAP.md) Phase 4, Phases 5–8, §6 "Out of Scope", and the
Phase 3 carry-over checklist:

- Real case data of any kind, the refit of the expected-outcome model on real
  data, per-metric thresholds chosen against real cohorts, and the cohort-size
  question of Phase 3 finding 3.5 (carry-over item 4); Phase 5 (Cook County)
  refits under a specification bump and revisits the registry's thresholds.
- The validation of the model, the linkage, and the attribution on real data —
  the remainder of the brief's development phase 10; Phase 6 §6.1 repeats this
  phase's report, subgroup calibration included, on the real restricted
  attributes.
- Opaque machine-learning models for expected outcomes; excluded at v1 by §6 —
  the regularized logistic model is the published estimator.
- Any composite, ideological, partisan, or "best/worst judge" score; excluded
  permanently — the compare page ranks one objective metric at a time with its
  interval and sample size, adjusted or not.
- The use of any restricted attribute (the age band, race, gender) as a model
  feature; the brief requires a documented methodological purpose, legal review
  (Phase 6 §6.4), fairness analysis, and publication rationale first, and v1
  records the choice and its measured consequence instead.
- Administrative authentication, the corrections reader, envelope or asymmetric
  encryption for correction contacts (carry-over item 5), unmerge and `er review
  decide` behind admin authentication, and the probabilistic scorer (carry-over
  item 8); Phases 6 and 7.
- The object-store variant of snapshots and model artifacts (carry-over item 6),
  edge rate limits and `JUDGEMETRICS_TRUST_PROXY` behind the production proxy
  (carry-over item 11), and a scheduled `metrics verify` and `models verify`
  run; Phase 8.
- Parent-case data-quality checks across runs (carry-over item 7) and member
  rows once per metric with per-window flags (carry-over item 9); Phase 5, or
  Phase 8's performance work for the latter.

Additionally not in scope for this phase:

- Calendar-period cohorts and the compare page's calendar-period filter, which
  Phase 3's roadmap expected here: the model carries the calendar year as a
  feature (the temporal control), but per-period adjusted observations would
  fall below the adjusted threshold of 30 at demo scale (24 judges over eight
  years); Phase 5, where Cook County's volume supports contemporaneous cohorts.
- Adjusted measures after a disposition or a sentence, and the reconviction and
  revocation targets; the v1 specification adjusts the pretrial release decision
  and the two pretrial-release outcomes of the brief's example panel, and later
  targets join under a specification bump with the first real source that
  supports them (Phase 5 or later).
- Court- and jurisdiction-level adjusted measures: under a model with a court
  feature a court's expected count is its observed count by construction; courts
  keep their descriptive rates and pooled values.
- Incremental recompute of adjusted observations in pipeline step 13; the
  documented exception stands until Phase 8 schedules the full compute after
  every ingest.
- A restricted snapshot freezing the attributes the fairness analysis reads
  (they are read live, never frozen with the public snapshot); Phase 6, with the
  admin surface and the real attributes.
- Sensitivity of the adjusted figures to the penalty and to alternative model
  families; the validation reports the specified model only, and Phase 6's
  methodological validation revisits both.
- Moving `person_identifier`, `correction_request`,
  `entity_resolution_candidate`, and `audit_log` into the `restricted` schema;
  their grants already exclude the app role, and the move is an architectural
  question for Phase 6's admin surface.
- Bumping `[project].version` (still `0.1.0` beside the `v0.3.0-phase-3` tag) so
  `code_version` and `/api/v1/health` report the release; Phase 8's release
  pipeline (§8.4).

---

_This roadmap is the execution plan for Phase 4. Each step's `**Status:**` line
is flipped by that step's own PR (Status rule), so this file on `main` is the
phase's ledger — `grep -n '^\*\*Status:\*\*'` reports progress. After all steps
and verification pass, and every finding has a destination, Phase 4 is complete
— declared with the line "Phase 4 is complete. You can now move on to Phase 5."
and nothing after it — and Phase 5 (First Real State-Court Pipeline and the
Florida Acquisition Plan) inherits the restricted schema its Cook County race,
gender, and age attributes land in, the versioned expected-outcome specification
it refits on real data, the order-invariant feature builder and
content-addressed model artifacts, the validation report it re-runs on real
cohorts, and the risk-adjusted panels its first real adjusted comparisons appear
in._
