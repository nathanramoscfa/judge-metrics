<!-- docs/roadmap/phase05-roadmap.md -->
# Phase 5 Roadmap — First Real State-Court Pipeline and the Florida Acquisition Plan

**Status:** Not started

## Overview

Phase 5 opens the gate to real data: it brings the first real state
criminal-court corpus — the five Cook County, IL State's Attorney (SAO)
datasets — through the connector framework of Phase 1, the attribution and
entity-resolution machinery of Phase 2, and the metrics engine of Phases 3 and
4, so that every published number about a real judge or court is traceable to a
retrieved public artifact, attributed only to the actor who made the decision,
and shown with its coverage and the corpus end date. Beside it, the phase
completes the Florida source inventory and a lawful acquisition plan, and the
operator submits the requests, because the Florida pilot of Phase 7 waits on
answers with an unbounded lead time. Phase 6's methodological validation on
real data, its admin tools, and its legal review all need a real corpus to
audit; Phase 7 needs the acquisition plan. Phase 5 covers the brief's
development phases 8 and 9, with Cook County standing in for the first real
pipeline until Florida access is secured.

Phase 5 does NOT publish any cross-case outcome for Cook County: the planning
measurement below shows the source has no person key that spans cases, so new
case, new charge, and reconviction are not observable for it and are reported
as unavailable, never as zero. It does NOT publish an adjusted (observed to
expected) figure on real data — no expected-outcome target the specification
supports is attributable to a Cook County judge — and it does NOT run or
publish a fairness analysis over the real restricted attributes, which waits for
Phase 6 §6.1's methodological validation and §6.4's legal go/no-go. It does
NOT ship administrative authentication, the corrections reader, or rapid
suppression (Phase 6), and it deploys nothing beyond the maintainer's machine
and the repository's CI (Phase 8). Real case data never enters the repository
except as a small committed fixture of real rows whose restricted and
quasi-identifying columns are blanked.

The phase lands in 8 layers:

1. **Cook County source due diligence, the streamed fetch, and the value-set
   profile** — the completed `cook_sao` source-policy record in
   `docs/DATA_SOURCES.md` (portal terms and each dataset's license read,
   redistribution answered or left with the operator as question 2, the
   archived pre-2018 versions recorded); a registered `cook_sao` connector
   (`src/judgemetrics/ingest/cook_sao/`) whose fetch path streams the five
   bulk exports to disk under a source-specific size cap with chunked
   hashing and a file-based raw-store put (`RawObjectStore.put_file`), at
   parser version `0`, which parses nothing yet; `judgemetrics sources profile
   cook_sao`, which derives the versioned `data/reference/cook_sao/profile.yaml`
   from the stored artifacts (row counts, date ranges, null counts, every
   coded column's value set, the distinct judge strings, key stability across
   datasets, and the cross-case measurement); `judgemetrics sources excerpt
   cook_sao`, which writes the committed real-row fixture
   `tests/fixtures/cook_sao/` by a documented stratified rule; questions 2–4 of
   `docs/ROADMAP.md` resolved or assigned; and the project roadmap's Phase 5
   text corrected where it assumed a cross-case person key.
2. **Florida source research and the lawful acquisition plan** —
   `docs/florida-data-inventory.md` (OSCA's JDMS and the Uniform Case
   Reporting specification, the clerks' statewide systems, the public-records
   and court-records rules, and at least six county clerks including Broward
   and Miami-Dade), the brief's nine-step selection process scored, the
   selected pilot jurisdiction with a ranked fallback, the written acquisition
   plan, drafted requests under `docs/florida/requests/` that ask for
   redistribution rights explicitly, the `fl_jdms` and `fl_clerks` register
   entries, and the requests' submission dates in `docs/ROADMAP.md`. This
   step may run in parallel with Steps 3–7.
3. **Mapping and attribution rules, the judge and court tables, and
   vocabulary 3** — versioned reference data under `data/reference/cook_sao/`
   (`attribution_rules.yaml` for every observed disposition and reason pair,
   felony-review result, and diversion outcome; `pretrial_rules.yaml` for bond
   types and the Pretrial Fairness Act regime; `sentence_rules.yaml`;
   `offense_map.csv`; `courts.yaml`; `judge_aliases.csv` and `judges.csv`;
   `tables.yaml`, pinning each table's version and digest), their loaders and
   validators in `src/judgemetrics/ingest/cook_sao/rules.py`, case vocabulary
   version `3` with exactly the canonical values they need (the restricted
   kinds `race` and `gender` included), outcome-model specification version
   `2` listing every new severity and offense level, and the tests proving
   every value in the profile maps to a rule or to `unknown`, with the unknown
   share computed.
4. **The Cook County connector at corpus scale** — the connector's parse and
   normalize over the five datasets applying Step 3's tables (jurisdiction,
   the six district courts, judges by alias and their derived service
   records, cases once each, per-case persons, parties, restricted attributes,
   charges with the disposing judge, events, bond and prosecutor decisions,
   sentences, within-case revocation events); migration
   `0011_cook_county_connector` (the `cook_sao_judge` identity index,
   `charge.judge_id`, the app role's access to `data_quality_issue` revoked);
   the runner, publisher, and entity resolution made safe past PostgreSQL's
   65,535-parameter ceiling and bounded in memory; parent-case data-quality
   checks across runs; `judgemetrics ingest retire` (issue #36); and the full
   corpus ingested on the maintainer's machine with a rerun that creates
   nothing.
5. **Real-data metric semantics, calendar periods, and coverage statistics**
   — registry version `3` and methodology `1.1`: the `disposing_judge` gate
   for the disposition family, `NotAttributable` for a judge metric whose
   attribution the source does not record (Cook County's pretrial decisions),
   calendar-year cohorts beside the whole coverage window, per-metric
   suppression thresholds revisited against real cohorts, and a "Source
   limitations" section; migration `0012_real_data_semantics`
   (`source.capabilities`, the `coverage_statistic` table); the brief's
   six coverage statistics and the unknown-actor share computed per snapshot,
   source, jurisdiction, and court and checked by `metrics verify`;
   specification version `3` with per-source target availability, so Cook
   County fits no model and the report says why; `metrics compute --source`;
   and issues #40 and #42.
6. **The metrics engine at corpus scale** — migration `0013_member_storage`
   (one member row per member and observation family with window and period
   flags, written by `COPY`), a vectorized Kaplan-Meier estimator, a streamed
   snapshot export, a streaming `metrics verify`, a set-based and paged
   provenance trace, and a bounded step 13 — with every demo and golden
   observation and provenance chain unchanged and the full Cook County
   compute, rerun, and verify measured against recorded budgets.
7. **Public surfaces for the first real source** — `/api/v1/coverage` v2
   (coverage statistics, the unknown-actor share, not-observable and
   not-attributable lists, and a per-jurisdiction breakdown), the corpus end
   date on every response that cites a source, `/courts?q=`, a cohort filter
   on `/judges/{id}/cases`, calendar periods on `/metrics/compare`, and paged
   provenance members; the coverage, jurisdiction, compare, judge, and case
   pages for real data; and `web/tests/e2e/real-data.spec.ts` over the
   committed fixture, which CI's `e2e` job now ingests.
8. **QA + `verify_phase05.py`** — verification script (`--fast`, `--py`,
   `--node`, `--e2e`, `--security`, `--all`, `--post`),
   `docs/phase05-qa-findings.md` with the alarm exercises and the Phase 6
   carry-over checklist, the `phase-verify.yml` matrix entry `05` with its
   required context, the status update in `docs/ROADMAP.md`, and the tag
   `v0.5.0-phase-5`.

The ship test for Phase 5 is straightforward: the five Cook County exports sit
in the raw lake with their digests, and `data/reference/cook_sao/profile.yaml`
regenerates from them byte for byte; every disposition and reason pair, bond
type, sentence value, offense, court, and judge string in the profile maps to a
versioned rule or to an explicit `unknown`, whose share is published; the full
corpus ingests through those tables and a rerun creates zero new canonical
rows; race, gender, and the age band reach only `restricted.party_attribute`
through the ingest role, and no participant identifier or restricted value
appears in any app-readable column, data-quality issue, log line, or committed
file; `metrics compute` publishes the first real metrics — the sentencing and
disposition families by the judge the source records, the court-level bond
decisions, and within-case revocation after a sentence, per calendar year and
over the coverage window — publishes no observation for an outcome or an
attribution the source does not record, and `metrics verify` reproduces every
observation on the full corpus within the recorded budget; the brief's coverage
statistics and the unknown-actor share are published per source, jurisdiction,
and court; every real surface shows the corpus end date;
`docs/florida-data-inventory.md` names the selected pilot and its lawful
acquisition plan and the requests are logged in `docs/ROADMAP.md` with dates;
`uv run python scripts/verify_phase05.py --fast` and `--security` exit 0 on
Ubuntu CI under the `phase-verify.yml` matrix entry `05`; and the security gate
is clean.

**Pre-requisite:** Phase 4 closed (tag `v0.4.0-phase-4`, 2026-10-02): its
`restricted` schema and `restricted.party_attribute` are where Cook County's
race, gender, and age band land, its versioned expected-outcome specification
is what this phase bumps twice, its order-invariant feature builder and
validation report are what decide that no Cook County target is fitted, and its
adjusted panels must keep working beside real data. Phase 3 closed earlier (the
registry, the snapshot engine, `metrics verify`, the provenance trace, and
coverage v1 that the real metrics and coverage statistics extend), and Phases 1
and 2 before it (the connector framework, the immutable raw lake, the
vocabulary, entity resolution, and the role split the real ingest runs on).

**Dependency:** Phase 6 (Methodological Validation, Admin Tools, and Trust) does
not start until Phase 5's V-checks are green; it inherits the real Cook County
corpus its audit samples, the attribution tables it validates against source
documents (§6.1), the coverage statistics and unknown-actor share it audits, the
real restricted attributes its legal review (§6.4) must clear before any
fairness analysis is published, the judge review candidates its admin queue
decides, and the Florida requests whose answers Phase 7's pilot connector needs.

**Design rationale (no cross-case person key — measured before this plan was
written).** The project roadmap planned Phase 5 around "a pseudonymous
participant id linking a person across cases" and made the brief's preferred
first real metric — a new criminal case after a qualifying pretrial release —
the target. While surveying the source for this roadmap (2026-10-04, read-only
aggregate queries against the portal's public API), every one of the five
datasets showed the opposite: Intake has 528,111 rows, 528,111 distinct
`case_participant_id` values, and 479,260 cases; Initiation 450,133 participant
ids over 417,905 cases; Dispositions 379,670 over 355,113; Sentencing 264,518
over 247,649; Diversion 27,695 over 26,561 — and in none of them does a
participant id appear under more than one `case_id`. The identifier names a
participant within one case, the datasets carry no name or date of birth, and
linking on demographics would use restricted attributes and is forbidden. Cook
County therefore supports within-case analytics only: judge-attributed
dispositions and sentences, court-level bond decisions, timelines, and the one
within-case subsequent event the data records — a probation-violation
resentencing (7,492 rows of `sentence_phase` "Probation Violation
Sentencing"). The phase keeps its exits, changes its first real metrics to the
sentencing and disposition families the source does attribute, declares the
cross-case outcomes not observable, states in the methodology that a "person"
of this source is a case participation, and makes a lawful cross-case person
key a weighted criterion of the Florida selection. Step 1 re-measures the
finding from the stored artifacts and corrects the project roadmap, the source
register, and `docs/ROADMAP.md`.

**Design rationale (attribution is versioned data, applied on the first
ingest).** Misattributing a prosecutor's or a statute's outcome to a judge is
the first risk in the project roadmap, and Cook County's coding makes it
concrete: of 1,080,014 disposition rows, 714,681 are "Nolle Prosecution"
(prosecutorial), often with a reason such as "PG to Other Count/s" (161,048
rows); 5,696 carry the reason "Motion to Quash Arrest & Suppress
Evidence/Sustained", a judicial ruling that precedes a prosecutor's dismissal;
and the 36 disposition values include procedural non-finals ("Superseded by
Indictment", "BFW", "Mistrial Declared") that must never count as dispositions.
Step 3 therefore writes every mapping as reviewed, versioned reference data
before any connector code reads the source — each rule with its actor, its
judicial-discretion classification, its finality, and a rationale — and Step 4
applies it on the very first ingest, with the connector's parser version
embedding every table's version so a rule change re-derives every row. Whatever
the documentation does not settle maps to `unknown`, and the unknown share is a
published coverage statistic rather than a hidden residue; Phase 6 §6.1
validates the rules against source documents.

**Design rationale (real data at a hundred times the demo, on one machine).**
The corpus holds 3,171,690 rows (planning-time counts) against the demo seed's
5,200 cases, and the code was built and tuned at demo scale: downloads buffer in
memory under a 200 MiB cap, a run holds every draft in memory, several lookups
expand one bind parameter per id and fail past 65,535 ids, a windowed metric
writes its whole cohort once per window as member rows inserted 500 at a time,
Kaplan-Meier is a pure-Python loop, the snapshot export goes through Python
tuples, and `metrics verify` loads every member. Phase 5 fixes each of these in
the step that first needs it — the fetch in Step 1, the ingest in Step 4, the
engine in Step 6 — with budgets measured on the full corpus on the maintainer's
machine and recorded beside the code, while CI exercises every path on the
committed fixture. No published figure may change because of a performance
change: the golden suite, the demo's observations, and their provenance chains
are the regression oracle for Steps 4 and 6.

**Design rationale (no real person-level data leaves its boundary).** Real
defendant-level records arrive on the maintainer's machine for the first time.
The raw lake and the canonical database stay local; the committed fixture keeps
real rows (the brief's rule against fake integrations) but blanks `race`,
`gender`, `age_at_incident`, and the quasi-identifying columns the canonical
model never reads; the committed profile lists the restricted columns' values
without counts; participant identifiers reach the database only as peppered
hashes in the source's own namespace; race, gender, and the age band are written
only to `restricted.party_attribute` by the ingest role; data-quality issue
text, which the app role can read today, carries no identifier and loses that
grant; and no real source enters any snapshot bundle until the operator settles
its redistribution terms (question 2).

**Branch strategy.** Every step in this phase lands on its own short-lived
feature branch (`feature/phase05-stepM-<slug>`), opens a pull request against
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
git checkout -b feature/phase05-stepM-<slug>
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
its own conversation) — in this phase only Step 2, the Florida research, beside
Steps 3–7; and worktree-isolated subagents inside a step (throwaway trees that
merge back into the step branch locally and are removed before the PR opens). In
those cases Stage 1 becomes `git fetch origin && git worktree add -b
feature/phase05-stepM-<slug> .worktrees/<slug> origin/main`, the worktree is
bootstrapped before any test or build (`uv sync`, `pnpm install` in `web/`,
`.env` copied — a worktree has none of the primary tree's untracked state, and
it must never borrow the primary tree's editable install, raw lake, or
snapshots), the Stage 4 merge runs from the primary tree, and Stage 5 removes
the worktree BEFORE pruning the branch. Undeclared parallelism is a lifecycle
violation, not a shortcut. Worktree location for this project: git-ignored
`.worktrees/<slug>/` inside the repository, matching the parent ROADMAP.

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
brings real defendant-level records onto the maintainer's machine for the first
time, Step 4 writes real participant identifiers (as hashes) and real
restricted attributes, and Step 7 serves real data on every public surface:
the operator running a step's prompt must not be able to introduce a
data-exposure risk that only surfaces after merge, and a real record committed
by mistake is a disclosure that no revert undoes.

**Deploy-and-verify rule.** Merged is not deployed, and deployed is not
released. Every step header carries a `**Deploys:**` line naming the surface and
environment the step's merge reaches — or `nothing beyond merge` — and when
going live needs a release, a version-floor bump, a migration, or a redeploy,
the line says so and this step (or a named follow-on step) owns that event.
Through Phase 7 the only environment is the maintainer's machine, so in this
phase "deployed" means the merged commit runs under `uv run poe up` with
migrations applied and the step's data operation (a fetch, an ingest, a
compute) completed against the local services; a step whose Deploys line names
that surface carries a **Deployed & verified** bullet (the local
`/api/v1/ready` reports the migration head the step introduced, and the changed
behaviour is exercised locally via the hands-off recipe the step names, with
its wall time and counts recorded), and that bullet must be green before the
step is declared complete. No step in this phase introduces a required
environment variable or credential: the Cook County exports are anonymous HTTPS
downloads, and the identifier pepper and the correction-contact key already
exist. The full-corpus operations (Steps 1, 4, and 6) run on the maintainer's
machine only; CI runs every code path on the committed fixture. See the parent
ROADMAP "Release & deployment strategy" for the surfaces table, promotion path,
staged-rollout rule, migrations, and rollback.

**Triage rule.** Findings surfaced while executing a step are classified before
they are acted on, per the parent ROADMAP "Defect handling & triage": spec rot →
edit this roadmap's affected `<task>` block now; upstream gap → patch the
earlier step's prompt and add it to the carry-over checklist; implementation bug
→ fix in-step only if it blocks this step's acceptance criteria, otherwise an
issue and its own branch in a fresh conversation; architectural question → an
issue for a future phase; process improvement → recorded where the next
conversation will read it; security finding → jumps the queue by severity;
data-semantics finding (a source value, an attribution rule, or a metric
definition was misread) → edit the versioned rule, vocabulary, registry, or
specification entry, bump its version, and re-run `metrics verify`; data-access
question → `docs/ROADMAP.md` "Unresolved data-access questions", never an
invented answer. A step's PR contains the step plus blocking fixes only, and
lists the issues it opened. When a merged PR auto-closes an issue, the
environment check is what earns the close — reopen or follow up if a gap
remains. `docs/phase05-qa-findings.md` is the rollup: every finding, its class,
and the guard added so the class cannot recur. Phase 4's carry-over checklist
(`docs/phase04-qa-findings.md`, last section) is folded into this roadmap as
follows: item 1 (per-metric thresholds and the cohort-size question) → Step 5;
item 2 (parent-case data-quality checks across runs) → Step 4; item 3 (member
rows once per metric with per-window flags) → Step 6; item 4 (the refit on real
data under a specification bump, the events-per-column gate revisited) → Steps
3 and 5, where the specification records that no Cook County target is
supportable and why; item 5 (Cook County's restricted attributes through the
ingest role only) → Step 4, the fairness analysis on real data → Phase 6; item
6 (calendar-period cohorts and the compare filter) → Steps 5 and 7; item 7 (no
source identifier in `case_party.source_row_id`; the bootstrap cluster key) →
Step 4, with the key measured in Step 1; item 8 (`verify_phase05.py`) → Step 8;
item 9 (issues #36, #40, #42) → Steps 4, 5, and 5; item 10 → the phases it
names, listed under Not in scope. Phase 3's Not-in-scope items owned by this
phase land here too: the cases-route cohort filter and the court search on
`/compare` → Step 7; a per-jurisdiction coverage breakdown → Steps 5 and 7.
Four findings were made while surveying for this roadmap and are owned as
follows: the missing cross-case person key (design rationale above) → Step 1
verifies and records it, Steps 3–7 build on it; the disposition family's
attribution through assignment intervals, which a source that records the
disposing judge but no assignments cannot feed → Steps 4 and 5; the
`data_quality_issue` table, readable by the app role, whose
`normalize_failed` text can carry a source identifier (security finding,
latent until real data) → Step 4; and the bind-parameter ceiling that fails any
run past 65,535 cases or persons → Step 4.

**Status rule.** Every step carries a `**Status:**` line directly under its `##
Step N — …` heading, before the Goal, and this file on `main` is the ledger of
what is done — never a chat transcript, never a later conversation
reconstructing history from `git log`. The line reads `Not started` when this
roadmap is written and is flipped by the step's OWN pull request: at Stage 3,
right after `gh pr create` returns the PR number, the agent sets it to `Complete
— PR #<n> (<YYYY-MM-DD>)`, appends ` ✅` to the step's heading (`## Step 4 — The
Cook County Connector at Corpus Scale ✅`) so the completion shows in the
rendered preview, the outline, and the table of contents, sets the step's
Summary Table Status cell to `Complete — PR #<n>`, commits that edit on the step
branch, and pushes. The PR therefore carries its own completion mark, and the
roadmap on `main` says a step is complete exactly when that step's PR merges —
never before. This file's phase-level `**Status:**` line (under the title) and
the parent project roadmap are marked the same way, in the same commit: Step 1's
PR flips both from `Not started` to `In progress` (the parent's `### Phase 5`
line reads `In progress — phase05-roadmap.md`), and the final step's PR flips
both to `Complete — …` (the parent's with its row in the "Phase Complexity
Summary" table and the header `> **Status:**` line) and appends ` ✅` to this
file's `# ` title and to the parent's `### Phase 5` heading, so the project
roadmap shows a finished phase the way this file shows a finished step. There is
no separate "update the roadmaps" chore: a step whose PR merged without its
Status line is a lifecycle violation, and the next step's Stage 1 (and
`/roadmap-step`) refuses to start until the previous step reads `Complete` —
except across the parallel branch the Execution Order draws, where Step 3 may
start while Step 2 is in flight, and Step 8 does not start until Step 2 reads
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
   feature/phase05-stepM-<slug>` from a clean, up-to-date `main`. The exact
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
   branch (`docs: mark Phase 5 Step M complete`), and push — the PR now carries
   its own completion mark, so the roadmap on `main` will say the step is
   complete exactly when the PR merges (Status rule). On the phase's first step,
   the same commit sets this roadmap's phase-level `**Status:**` (under its
   title) and the parent project roadmap's Phase 5 `**Status:**` to `In
   progress`; on the final step, both to `Complete`, with ` ✅` appended to this
   roadmap's `# ` title and to the parent's `### Phase 5` heading.

4. **Wait for green checks, then squash-merge.** Every required status check
   (`test`, the aggregate of `python`, `security`, `container`, `web`, and
   `e2e`; `phase-verify (01)` through `phase-verify (04)`; and, from Step 8,
   `phase-verify (05)`) must report success. If the PR goes BEHIND main while
   waiting, refresh with `gh pr update-branch --rebase` — never merge `main`
   into the branch; `required_linear_history: true` enforces rebase. Once every
   check is green:

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

## Current State (as of Phase 4)

### Cook County source surface (planning-time measurements)

- `docs/DATA_SOURCES.md` `cook_sao` (verified 2026-09-15) lists the five
  current datasets and their columns — Intake (`3k7z-hchi`, 17 columns),
  Initiation (`7mck-ehwz`, 38), Dispositions (`apwk-dzx8`, 33), Sentencing
  (`tg8v-tm6u`, 41), Diversion (`gpu3-5dfh`, 13) — on the Socrata portal
  `datacatalog.cookcountyil.gov`, bulk CSV exports with no credential, the
  archived pre-2018-02-13 versions, judge names as free text on dispositions
  (`judge`) and sentences (`sentence_judge`), bond fields without a deciding
  judicial officer, and race, gender, and `age_at_incident` destined for the
  restricted schema. Its "Remaining to verify" are the portal terms, the value
  sets, and the stability of `case_participant_id` — `docs/ROADMAP.md`
  questions 2 (operator), 3, and 4 (agent), all open. Its "Person linkage" and
  "First real metric" bullets assume a cross-case person key the data does not
  have (below).
- Measured while writing this roadmap (2026-10-04, read-only aggregate SODA
  queries; Step 1 re-measures every figure from the stored artifacts and is
  authoritative):

  | Dataset | Rows | `received_date` range | Participant ids | Cases |
  |---|---|---|---|---|
  | Intake | 528,111 | 2011-01-01 – 2024-11-30 | 528,111 | 479,260 |
  | Initiation | 1,228,260 | 2011-01-01 – 2024-11-30 | 450,133 | 417,905 |
  | Dispositions | 1,080,014 | 1901-07-24 – 2024-11-29 | 379,670 | 355,113 |
  | Sentencing | 305,884 | 1901-07-24 – 2024-10-31 | 264,518 | 247,649 |
  | Diversion | 29,421 | 2011-01-01 – 2024-11-12 | 27,695 | 26,561 |

  Every dataset's portal metadata reports rows updated 2026-04-02, the license
  "Public Domain", and the attribution "Cook County State's Attorney's Office".
  No `case_participant_id` appears under more than one `case_id` in any
  dataset: the identifier is per case, and the corpus has no cross-case person
  key. `charge_id` has 1,171,412 distinct values over 1,171,413 charge
  versions in Initiation, and a few charge ids appear in two cases.
- Value sets seen at planning time: `charge_disposition` has 36 values
  ("Nolle Prosecution" 714,681; "Plea Of Guilty" 268,753; "FNG" 42,695;
  "Finding Guilty" 25,041; "Death Suggested-Cause Abated" 6,904; "Verdict
  Guilty" 5,569; "Verdict-Not Guilty" 4,614; "Finding Not Not Guilty" 2,437;
  "Superseded by Indictment" 1,894; "BFW" 1,710; "Case Dismissed" 1,692; then
  25 rarer values down to "TRAN-FAI" with one row); `charge_disposition_reason`
  has 31 values plus null (791,562 null; "PG to Other Count/s" 161,048;
  "Proceeding on Other Count/s" 48,781; "Nolle - AONIC" 19,866; "Motion to
  Quash Arrest & Suppress Evidence/Sustained" 5,696; several specialty-court
  graduations); `sentence_phase` has six ("Original Sentencing" 293,489,
  "Probation Violation Sentencing" 7,492, "Amended/Corrected Sentencing",
  "Resentenced", "Remanded Sentencing", "Summary Charge Info");
  `sentence_type` 15 ("Prison" 159,122, "Probation" 116,834, "Jail" 13,415,
  …, "Death" 73); `commitment_type` 30; `bond_type_initial` four plus null
  ("D Bond" 543,247, null 419,212, "I Bond" 196,468, "No Bond" 63,712, "C
  Bond" 5,621) — a bond type records the decision, not whether the person was
  released, and Illinois ended cash bail on 2023-09-18 (the Pretrial Fairness
  Act); `court_name` six districts ("District 1 - Chicago" 634,058 rows, then
  Bridgeview, Markham, Skokie, Maywood, Rolling Meadows) plus "PROMIS",
  "Traffic", and null; `court_facility` 17 values; `judge` 469 distinct
  strings with 76,613 null rows; `sentence_judge` 402 distinct strings with 742
  null rows, some with doubled spaces ("Stanley  Sacks").

### Ingest surface

- `src/judgemetrics/ingest/base.py` defines the `SourceConnector` protocol
  (async `discover` and `fetch`; `validate_raw`, `parse`, `normalize`), the
  optional `SupportsCheckpoint`, `SupportsCoverage` (`coverage_window()`), and
  `SupportsContext` (`load_context(artifacts)`, every artifact of the run,
  changed or not), `SourceInfo(owner, source_type, access_method,
  terms_metadata, observable_outcomes)`, and frozen drafts keyed by
  `natural_key`: `JurisdictionDraft`, `CourtDraft`, `JudgeDraft` (identity
  `(system, value)`, also present in `external_ids`), `JudgeServiceDraft`,
  `PersonDraft`, `CaseDraft`, `CasePartyDraft`, `PartyAttributeDraft`
  (`repr=False`), `JudgeAssignmentDraft` (judge required), `ChargeDraft`,
  `CourtEventDraft`, `DecisionDraft` (actor required), `PretrialReleaseDraft`,
  `SentenceDraft`, `JusticeEventDraft`. `describe_key` renders a person key
  without its hash but prints every other key part, a case number or
  `source_row_id` included, into issue descriptions.
- `src/judgemetrics/ingest/runner.py` runs the fourteen steps in
  `_execute`: artifacts fetched sequentially, hashed with
  `sha256_hex(raw.read_bytes())`, stored with `store.put(bytes, key)`; every
  draft of every re-parsed artifact held in one in-memory list, deduplicated
  first-wins on `natural_key` (later conflicting drafts only counted), resolved,
  checked, and published in one transaction, then step 13 inside the same
  transaction. `JUDGE_IDENTITY_SYSTEMS = {"fjc_nid", "synthetic_judge_code"}`
  (line 166): any other system fails the run, and a case-level draft whose
  judge key does not resolve is REJECTED (`unresolved_judge`), never published
  with a null judge. A `PartyAttributeDraft` needs its party drafted in the
  same run. `publish.lookup_cases` reads every case of the involved courts
  into Python, twice per run. `impacted_subjects` and several lookups in
  `publish.py` (`_source_row_ids`, person ids) and in `entity_resolution/`
  (`deterministic.py`, `features.py`, `candidates.py`) pass run-sized id lists
  to `in_()`, which psycopg renders as one bind parameter per id: a run past
  65,535 distinct cases or persons fails, and no test covers it.
  `merge.canonical_person_id` issues one `SELECT` per person.
- `src/judgemetrics/ingest/http.py` enforces HTTPS, retries
  (`408, 425, 429, 5xx`, backoff 0.5/1/2 s), 30-second phase timeouts,
  conditional requests, and `DEFAULT_MAX_BYTES = 200 * 1024 * 1024`, and
  streams the body into an in-memory `bytearray`; `RawArtifact.from_bytes`,
  `store.put`, and `read_bytes()` then each hold a full copy. The raw lake
  (`ingest/store.py`) keys objects `<source_id>/<yyyy>/<mm>/<sha256><ext>`,
  where the extension comes from the external id and allows at most three
  suffixes of at most 16 characters, refuses to overwrite, and takes bytes
  only (`S3RawObjectStore` issues a single `put_object`).
- Connectors: `BUILTIN_CONNECTOR_MODULES` in `ingest/registry.py` lists the FJC
  and synthetic connectors, instantiated with no arguments. The FJC connector
  (`ingest/fjc/`, parser `2026.09.1`) is the pattern for an HTTPS source:
  verified and expected header sets in `schema.py` (missing expected header →
  error, unverified extra → warning), ETag and Last-Modified validators,
  Polars reading strings only and projecting to the expected columns. The
  synthetic connector (`ingest/synthetic/`, parser `2`) is the pattern for a
  case-level source: `load_context` builds indexes from every artifact, parties
  are keyed `<party_type>:<ordinal>` (revision `0008`), participant ids are
  hashed with the pepper (`security/identifiers.py`, kind
  `source_participant_id`, normalized `strip().upper()`, not qualified by
  source), restricted attributes are drafted as `PartyAttributeDraft`, and
  `new_case` and `reconviction` justice events are derived per participant id.
- `src/judgemetrics/quality/checks.py`: twelve checks; the case-level ones
  (`disposition_before_filing`, `event_order_impossible`,
  `subsequent_before_index`, `missing_disposition`) see only the cases drafted
  in the same run (Phase 2 carry-over item 6, Phase 4 carry-over item 2);
  `missing_judge_on_decision` writes one warning per judge-less decision;
  `case_number_duplicate` flags any natural key drafted twice;
  `unknown_category_measured` is run-level. `normalize_failed` issues store
  the `NormalizationError` text, which for the synthetic connector includes the
  participant id.
- No command retires or purges a source's rows (issue #36: `seed` over an
  older generator version leaves stale rows). The test helper
  `tests/integration/conftest.py::purge_source` deletes a source's rows in a
  documented dependency order (observations, models, unreferenced snapshots,
  case-level rows, persons, judges, courts, jurisdictions, records, runs,
  source). The CLI's `ingest run` requires the identifier pepper for every
  source; `seed` regenerates a stale dataset and re-ingests it by natural key.

### Data model, vocabulary, and entity-resolution surface

- Alembic's head is revision `0010` (`0010_adjusted_observations.py`;
  `/api/v1/ready` reports `alembic_current` `0010`), pinned by
  `tests/integration/test_health.py` and `test_migrations.py`;
  `CANONICAL_TABLES` has 27 entries. Revisions build every grant from module
  constants behind a `_role_exists()` guard and name constraints through
  `op.f()` (Phase 4 finding 3.3). `alembic/env.py` includes the `public` and
  `restricted` schemas.
- `data/reference/case_vocabulary.yaml` is `version: 2` and equal to
  `src/judgemetrics/synthetic/vocabulary.py` by test
  (`tests/unit/test_vocabulary.py`, which also pins the kinds allowing
  `unknown` — exactly `judicial_discretion_classification`, `actor_type`, and
  `age_band` — and `restricted_attribute = (age_band, synthetic_group)`). It is
  synthetic-shaped: `severity` has five ordered values (`felony_1` …
  `misdemeanor_b`, index 0 the most severe, read by `metrics/compute.py` and
  `metrics/adjustment/features.py`), `offense_category` seven,
  `charge_disposition` five (`dismissed`, `acquitted`, `convicted_plea`,
  `convicted_verdict`, `pending`), `position` two (`circuit_judge`,
  `associate_judge`), and there is no kind for a disposition reason, a bond
  type, a sentence type, race, gender, or a court facility. `actor_type` is
  also a PostgreSQL enum holding the brief's nine actors.
- Tables the connector writes: `court_case` (`court_id` and `case_number`
  required, unique per court on the normalized number), `case_party`,
  `judge_assignment` (`judge_id` required), `charge` (`person_id`,
  `offense_category`, `severity` required; `disposition`, `disposition_actor`;
  no judge and no reason column), `court_event`, `decision` (`actor_type` and
  `judicial_discretion_classification` required; `judge_id` nullable),
  `pretrial_release` (`detained_flag` required), `sentence` (`judge_id`
  nullable; no type column), `justice_event`, `person` (no name or date column),
  `person_identifier` (stable index on `(identifier_type, value_hash)` for
  `source_participant_id`, not qualified by source), and
  `restricted.party_attribute` (`case_party_id`, `attribute`, `value`; no
  check constraint). `judge` identifies a judge only through a partial unique
  index per identity system (`uq_judge_external_ids_fjc_nid`,
  `uq_judge_external_ids_synthetic_judge_code`); there is no alias table.
  `jurisdiction.type` allows `county`; `court.court_type` is free text;
  `source.jurisdiction_id` is never set.
- `src/judgemetrics/entity_resolution/` resolves persons only
  (`MODEL_VERSION` `person-rules-v0`; deterministic on the stable identifier,
  rules that never merge on a name alone, a stub scorer, a review queue).
  `entity_resolution_candidate.entity_type` is free text and could hold judge
  pairs, but `er review list --entity-type` raises for anything but `person`
  and `er review decide` handles person pairs only. With Cook County's per-case
  identifier and no name or date of birth, only the deterministic stage can
  fire, and it can link nothing across cases.

### Metrics engine and registry surface

- `data/reference/metric_registry.yaml` is `version` 2, `methodology_version`
  `1.0`, the brief's eight warnings as `known_limitations` (pinned to exactly
  eight by `scripts/verify_phase03.py`, a required check), suppression 10 for
  shares, rates, survival estimates, and medians, 0 for counts and
  distributions, 30 with a minimum expected count of 5 for the three
  `observed_expected` metrics (pinned to exactly 30 by `verify_phase04.py`
  check 21, also required). It holds 36 metrics over five gates
  (`deciding_judge`, `sentencing_judge`, `assigned_at_time`, `assigned_ever`,
  `court_of_case`).
- Attribution as it bears on Cook County (`metrics/attribution.py`): the
  pretrial metrics filter `actor [judge]`, `discretion [discretionary]`, and
  the `deciding_judge` gate — for court subjects too — so a bond decision
  recorded with actor `unknown` reaches only the court-only
  `unknown_actor_pretrial_count`; a pretrial-release index event needs a
  non-null `release_at` and `detained_flag` false. The whole disposition
  family (`disposition_distribution`, `judicial_dismissal_rate`,
  `median_days_to_disposition`, the four rates after disposition) attributes
  through `assigned_at_time` over `judge_assignment`; neither `charge` nor the
  frame's `charges` carries a judge, so a source that records the disposing
  judge but no assignment intervals feeds none of it. The sentencing family
  (`sentence_count`, the three incarceration and probation medians, the four
  rates after a sentence) attributes through `sentence.judge_id` and works as
  is. The synthetic generator chooses the disposing judge as the judge
  assigned at the disposition time (`synthetic/cases.py` `_judge_at`).
- Outcomes and observability: `metrics/windows.py` counts `new_case`,
  `new_charge`, and `reconviction` only in another case and `revocation`,
  `failure_to_appear`, `release_violation`, and `rearrest` in any case; an
  outcome missing from `source.observable_outcomes` yields `NotObservable` —
  no observation, never a zero. Nothing equivalent exists for an attribution
  a source does not record: a judge with no attributed population gets
  observations with a zero cohort (published zero counts, suppressed shares).
  Every observation's period is the source's whole coverage window
  (`compute.py`), although `uq_metric_observation_key` and
  `/metrics/compare`'s `period_start`/`period_end` already admit others.
- Scale: the snapshot export reads the whole database, every source, through
  `session.execute(...).all()` tuples; `_derived_outcomes` and `_family` loop
  over every person in Python; `censoring.product_limit` is pure Python,
  O(event times × members) per window and subject; `publish.py` writes one
  `metric_observation_member` row per member per observation (a windowed
  metric lists its cohort six times) in statements of 500, and `_revive`
  deletes a revived row's members despite its docstring; `verify.py` loads
  every member; `provenance.render` and the API return every case id of a
  member group. The demo seed's first compute wrote 3,426 observations and
  822,777 members in 2 m 27 s; `metrics verify` takes about 28 s
  (`docs/ROADMAP.md`).
- Step 13 (`ingest/runner.recompute_metrics`) computes the descriptive kinds
  for the impacted subjects inside the ingest transaction
  (`Settings.metrics_recompute_on_ingest`, default true; off in the test
  suite). `metric_snapshot` keeps the registry and methodology versions of the
  first compute that recorded it (issue #42); `models fit` prints `fitted`
  twice (issue #40).

### Adjustment and validation surface

- `data/reference/outcome_model.yaml` is `version` 1 (`expected-logit-v1`):
  three targets that must name judge-gated registry populations
  (`pretrial_release`, `new_case`, `failure_to_appear`), eleven features whose
  `lead_severity` and `lead_category` levels must list every vocabulary value
  (`metrics/adjustment/spec.py`), prior-history features that need a
  cross-case person key, and a 500-replicate person-cluster bootstrap keyed by
  the person's earliest `<filed_at>|<source_row_id>`. Designs are built judge
  by judge, so a Cook County design is empty and every target would be
  recorded `insufficient_events` — by accident rather than by declaration.
- `src/judgemetrics/validation/` renders `docs/VALIDATION.md` from every
  source of the latest snapshot; the committed document is the demo seed's and
  CI's `e2e` job checks it with `validation report --check --truth
  data/synthetic/ci`, so a database that also holds a real source changes the
  render. `validation/fairness.py` is the only reader of the restricted schema
  and knows `age_band` and `synthetic_group` only.

### Security & sensitive-data surface

- Sensitive data this phase handles for the first time: real defendant-level
  case records (pseudonymous participant identifiers, charges, dispositions,
  sentences) and real restricted attributes (race, gender, and the age band
  derived from `age_at_incident`), plus quasi-identifiers the canonical model
  has no field for (`incident_city`, incident dates, the arresting agency and
  unit). Judges are public officials; their names are not restricted.
- Controls to mirror: participant identifiers only as peppered sha256 hashes in
  `person_identifier` (`security/identifiers.py`); the `restricted` schema with
  no app-role `USAGE` (revision `0008`, `03-test-database.sql`'s re-revoke
  block); the snapshot's `refuse_restricted`; the log scrubber's
  `SENSITIVE_KEYS` in `logging.py` (a substring match on the key: a bare
  `race` would redact `trace`; `tests/unit/test_logging.py` pins the exact
  25-key list); `tests/unit/test_restricted_readers.py`, which allows the
  restricted table to be named only in `validation/fairness.py`, the two model
  modules, `ingest/base.py`, the runner, the publisher, and the directory
  `ingest/synthetic/` — mirrored by `verify_phase04.py` check 31, a required
  check;
  `tests/golden/test_public_contract.py`, which scans app-readable text
  columns for the synthetic `PT-\d{6}` identifiers and the API for restricted
  names. The gate is `detect-secrets` against `.secrets.baseline`, `bandit -r
  src alembic scripts`, `pip-audit --strict --require-hashes` over the
  `uv.lock` export, `pnpm audit --audit-level=high` (one documented exception,
  #47), `eslint-plugin-security`, and `check-added-large-files --maxkb=1024`.
- Security findings this roadmap assigns (latent until real data arrives):
  `data_quality_issue` is readable by the app role, and its
  `normalize_failed` text and `describe_key` output can carry a source
  identifier (Step 4); the stable participant hash is not qualified by source,
  so two sources that reuse an identifier value would resolve to one person
  (Step 4).

### API and web surface

- 21 OpenAPI paths and 19 `StrictQuery` routes, pinned exactly by
  `tests/unit/test_openapi.py`; `docs/openapi.json` and
  `web/lib/api/schema.d.ts` are committed snapshots, drift-tested on both
  sides. `/coverage` takes no parameters (pinned) and returns per source the
  counts, filing range, coverage window, observable outcomes, last ingest,
  latest snapshot, and the snapshot's methodology version — 16 keys pinned by
  `test_api_coverage.py` — with no coverage statistic, no unknown-actor share,
  and no per-jurisdiction breakdown. No route reads `data_quality_issue`.
  Entity responses carry provenance blocks but not the source's coverage end
  (the corpus end date appears only in `/coverage`, `Observation.coverage`, and
  the trace's `SourceOut`).
- `/metrics/compare` accepts `period_start`/`period_end` and matches them
  exactly; the web compare page never sends them, lists courts from two pages
  of 100 (a comment there asks for a court search in Phase 5), and offers no
  period control. A judge with service at several courts shows identical
  whole-source figures under each court, unflagged. `/judges/{id}/cases`
  filters by filing dates, `status`, and `case_type` only, so the metric
  panels' "View eligible cases" links cannot select a cohort.
- The web tier names `fjc` and `synthetic` only in `web/lib/links.ts`
  `SOURCES`; FJC-only wording sits on the judge, court, and jurisdiction pages;
  the coverage page's note promises real data "in Phase 5" (asserted by
  `web/tests/e2e/smoke.spec.ts`), and the jurisdiction page carries a "Trends …
  Phase 5" placeholder. `components/metric-stat.tsx` and
  `components/adjusted-stat.tsx` are the only number renderers; the judge page
  renders exactly one association statement (`verify_phase04.py` check 42). The
  Playwright suites are `smoke` (8), `metrics` (3), `first-milestone` (10), and
  `adjusted` (6), all over the FJC fixture and the demo seed.

### Operations & observability surface

- Runtime surfaces before this phase: the API (`/api/v1/health`,
  `/api/v1/ready` with the migration head, the latest snapshot, and the
  models), the ingest runner (`ingest_run` status and failure reason), and the
  analytics snapshot (health: `metrics verify` and `models verify --refit`
  green; alarms: both non-zero on a tampered observation or artifact, exercised
  in Phase 4 Step 6). This phase adds a real source to the ingest surface — a
  frozen corpus fetched once and re-checked by conditional requests or hash
  comparison — and makes the analytics surface carry it: Step 5 adds the
  coverage statistics to the snapshot and to `metrics verify` (the same alarm
  now fires on a tampered statistic), Step 6 makes `metrics verify` and the
  trace feasible on the full corpus within recorded budgets, and Step 8's alarm
  exercise tampers a real observation and a coverage statistic in the scratch
  database and records each alarm failing and then passing. The raw lake (about
  1.5 GB for the five exports, TBD exactly until Step 1 measures), the canonical
  database, and the snapshots stay on the maintainer's machine; the object-store
  variant and scheduled verification are Phase 8.

### Documentation surface

- `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/DATA_MODEL.md` (its methodology
  version still reads `0.3` and its revision list stops at `0008`),
  `docs/METHODOLOGY.md` (generated; its "Observable outcomes" prose names the
  synthetic source), `docs/PROVENANCE.md`, `docs/VALIDATION.md` (generated, the
  demo seed's), `docs/ENTITY_RESOLUTION.md` (persons only),
  `docs/SYNTHETIC_DATA.md`, `docs/DATA_SOURCES.md`, `docs/ROADMAP.md`,
  `README.md`, `AGENTS.md`, and the project roadmap exist. Missing: the
  `cook_sao` connector, profile, fixture, and rule tables in `ARCHITECTURE.md`,
  `DATA_MODEL.md`, and `DATA_SOURCES.md` (Steps 1, 3, 4); judge resolution by
  alias in `ENTITY_RESOLUTION.md` (Steps 3–4); the real-data semantics, the
  source limitations, the coverage statistics, and the calendar periods in
  `METHODOLOGY.md` and `API.md` (Steps 5 and 7); the scale budgets in
  `ARCHITECTURE.md` (Steps 4 and 6); `docs/florida-data-inventory.md` (Step 2);
  and the Phase 5 decisions in `AGENTS.md` (every step).

### Verification surfaces

- `scripts/verify_phase01.py` through `verify_phase04.py` exist;
  `verify_phase04.py` (2,502 lines, 50 static checks) is the most recent
  template: standard library only, mutually exclusive `--fast`, `--py`,
  `--node`, `--e2e`, `--security`, `--all`, `--post` (default `--fast` plus
  `--py`), `[PASS] NN` / `[FAIL] NN — reason` / `[SKIP] id — reason`, line
  readers instead of a YAML or XML parser, every version check a `>=`
  comparison with the source constant, `probe_environment()` pointing the role
  URLs at `JUDGEMETRICS_TEST_DATABASE_URL` and the snapshots at
  `data/snapshots/scratch-test-db`, the seed and compute idempotency probes,
  the trace probe, an `M` row folding the first-milestone items, `gh pr
  checks`, the V-matrix, and a summary.
  `tests/unit/test_phase04_verification.py` runs `--fast` (50 passes) and
  asserts the matrix as a subset.
- `.github/workflows/phase-verify.yml`'s matrix is `phase: ["01", "02", "03",
  "04"]` (each entry runs `--fast`, then `--security`); Phase 5 adds `"05"`, and
  `phase-verify (05)` becomes a required context on `main` beside `test` and
  `(01)`–`(04)` through the `gh api -X PATCH` call on
  `…/branches/main/protection/required_status_checks` that `CONTRIBUTING.md`
  "Repository settings" records (its five contexts become six). Earlier
  phases' required checks that a Phase 5 edit can trip: `verify_phase03.py`
  checks 1, 4, and 5 (exactly eight limitations), 40 (the exact `bootstrap`
  sequence, also pinned by `tests/unit/test_repo_hygiene.py`), 41 (exactly
  seventeen "The first milestone" items in `README.md`, which Steps 1 and 7
  edit), and 42 (the `e2e` job seeds `data/synthetic/ci` and never uses the
  golden fixture); `verify_phase04.py` checks 8 (the synthetic connector's
  parser version is numeric; Step 5 bumps it), 9 (the `SENSITIVE_KEYS` tuple;
  Step 4), 12 (the specification; Steps 3 and 5), 20 and 36 (the `e2e` order;
  Step 7), 21 (adjusted thresholds exactly 30; Step 5), 24 (the
  `VERIFIED_COLUMNS` literal; Step 6), 25 (`kinds=DESCRIPTIVE_KINDS` in
  `recompute_metrics`; Step 6), 28 (the trace's `outcome model` line; Step 6),
  31 (the restricted-reader allow-list; Step 4), 34 (the `CHANGELOG` prefix:
  Step 5 appends, never prepends), and 42 (one association statement; Step
  7). Each must be relaxed to the subset or `>=` pattern in the same PR that
  changes what it pins, as Phase 4 Step 1 did for Phase 3's check 14.

---

## Execution Order

```
Step 1  (Cook County due diligence,      cook_sao fetch path: streamed
         fetch, profile, fixture)        download to disk, put_file, chunked
                                         hash; profile.yaml from the stored
                                         artifacts; the real-row fixture;
                                         register, questions 2-4, project-
                                         roadmap corrections
                                         → implement
  ↓
  ├──▶ Step 2  (Florida research +       docs/florida-data-inventory.md,
  │            acquisition plan)         pilot + fallback, acquisition plan,
  │            ║ parallel with Steps     requests drafted, submitted by the
  │            ║ 3-7: own worktree,      operator, dates in docs/ROADMAP.md
  │            ║ own conversation        → implement + operate
  ↓            ║
Step 3  (rules, tables, vocabulary 3)    attribution, pretrial, sentence,
               ║                         offense, court, judge-alias tables;
               ║                         rules.py; vocabulary 3; spec 2;
               ║                         demo refit + VALIDATION.md
               ║                         → implement
  ↓            ║
Step 4  (connector at corpus scale)      five datasets parsed and normalized;
               ║                         migration 0011; runner, publish, ER
               ║                         past the parameter ceiling;
               ║                         restricted attributes; parent-case
               ║                         checks; ingest retire (#36); full
               ║                         live ingest
               ║                         → implement
  ↓            ║
Step 5  (real-data semantics +           registry 3, methodology 1.1:
         coverage statistics)            disposing_judge, NotAttributable,
               ║                         calendar years, thresholds;
               ║                         migration 0012; coverage_statistic;
               ║                         spec 3; metrics compute --source;
               ║                         #40, #42
               ║                         → implement
  ↓            ║
Step 6  (engine at corpus scale)         migration 0013 member storage +
               ║                         COPY; vectorized Kaplan-Meier;
               ║                         streamed export and verify; paged
               ║                         trace; bounded step 13; full live
               ║                         compute
               ║                         → implement
  ↓            ║
Step 7  (public surfaces)                coverage v2, corpus end date,
               ║                         /courts?q=, cases cohort filter,
               ║                         compare periods, paged provenance;
               ║                         pages; real-data.spec.ts; CI e2e
               ║                         ingests the fixture
               ║                         → implement
  ↓  ◀═════════╝  (Step 2 must read Complete)
Step 8  (QA + verify_phase05.py)         scripts/verify_phase05.py
                                         + docs/phase05-qa-findings.md
                                         + phase-verify.yml matrix entry 05
                                         + required context + ROADMAP status
                                         + tag v0.5.0-phase-5
                                         → create

--- post-implementation ---

V1  The five exports are in the raw lake through the streamed fetch with
    their digests; profile.yaml regenerates byte for byte and records no
    participant id under more than one case; the fixture's restricted and
    quasi-identifying columns are blank; the register, questions 2-4, and
    the project roadmap are corrected.
V2  docs/florida-data-inventory.md applies the nine-step selection to the
    state systems and at least six counties with every fact cited, names
    the pilot and a fallback, and plans a lawful acquisition; the drafted
    requests ask for all three redistribution rights; submission dates are
    logged.
V3  Every value of the profile maps to a versioned rule or to unknown, with
    the unknown share computed; every judge string appears exactly once in
    the alias table; vocabulary 3 equals the generator's constants;
    specification 2 lists every level; the demo's VALIDATION.md is current.
V4  The fixture ingests twice with zero new rows; lookups past 65,535 ids
    succeed; restricted attributes reach only restricted.party_attribute;
    no participant id or restricted value sits in an app-readable column,
    an issue, or a log line; retire then re-ingest equals a fresh ingest;
    the full corpus ingests within the recorded budget.
V5  disposing_judge leaves every golden number unchanged; NotAttributable
    publishes nothing for an attribution the source does not record;
    calendar-year observations agree with the whole-window ones; coverage
    statistics and the unknown-actor share are verified; Cook County fits
    no model and the specification says why.
V6  Every demo and golden observation and provenance chain is unchanged
    under the new member storage; the full Cook County compute, its rerun,
    metrics verify, and a random trace complete within recorded budgets.
V7  Coverage v2 and the corpus end date are served and rendered on every
    real surface; the period filter, court search, and cases cohort filter
    work; real-data.spec.ts passes over the fixture in CI.
V8  verify_phase05.py --fast and --security exit 0 on Ubuntu CI under the
    phase-verify.yml matrix entry 05; the tag v0.5.0-phase-5 marks the
    merge.
```

Steps are sequential by dependency except for one declared branch. Step 1's
profile is the evidence every mapping of Step 3 is tested against, and its
fixture is the input of every connector, engine, and surface test after it; Step
3's tables must exist before Step 4's connector reads the source, so the first
real ingest is attributed, resolved, and mapped from its first row; Step 4's
canonical rows — `charge.judge_id` above all — are what Step 5's
`disposing_judge` gate, `NotAttributable` rule, calendar periods, and coverage
statistics read; Step 5 fixes the semantic shape (periods and gates included)
that Step 6's member storage and bulk paths are designed for, and Step 6's full
compute is the first run of the final semantics on the whole corpus; Step 7
serves Step 5's statistics and Step 6's paged trace; Step 8 verifies all of it.
Step 2 is the only step drawn in parallel: it changes no application code (its
one code edit adds the inventory to the hygiene test's path-comment list),
starts once Step 1 has merged (its selection criteria cite Step 1's verified
cross-case finding), may run in its own worktree and conversation beside any of
Steps 3–7 (Worktree rule), and must read `Complete` before Step 8 starts. Its PR
and the others all edit `docs/ROADMAP.md`, `docs/DATA_SOURCES.md`, this
roadmap's status lines and Summary Table, and `tests/unit/test_repo_hygiene.py`;
whichever merges second rebases (`gh pr update-branch --rebase`) and resolves
those documents by hand, never by merging `main` into the branch. Running Step 2
immediately after Step 1 is recommended, because the Florida requests' lead time
is the longest in the project. Its completion line keeps the verbatim shape
("Step 2 is complete. You can now move on to Step 3."); when Step 2 finishes
after later steps, the operator resumes at the first step whose Status is not
`Complete`.

---

## Step 1 — Cook County Source Due Diligence, the Streamed Fetch, and the Value-Set Profile

**Status:** Not started

> **Goal:** Complete the source-policy record for `cook_sao` and build the path
> every later step reads the source through. The fetch path is rebuilt for
> gigabyte exports — `ingest/http.py` streams a body to a temporary file under
> a size cap the connector chooses, the runner hashes path-backed artifacts in
> chunks, and the raw lake gains `RawObjectStore.put_file` (a streamed copy on
> the filesystem backend, a managed multipart upload on S3) — and a registered
> `cook_sao` connector (`src/judgemetrics/ingest/cook_sao/`: `sources.py`,
> `schema.py`, `connector.py`) discovers the five current Socrata bulk exports,
> records each dataset's portal metadata (rows-updated time, license, column
> list), skips the download when the rows-updated time is unchanged, and stores
> the five artifacts at parser version `0`, which parses nothing yet;
> `judgemetrics sources profile cook_sao` derives the versioned
> `data/reference/cook_sao/profile.yaml` from the stored artifacts — row and
> null counts, date ranges, every coded column's value set with counts (the
> restricted columns' values only), the disposition and reason pairs, the
> distinct judge strings, key stability across datasets, the cross-case
> measurement, and the anomalies — and `--check` fails on drift;
> `judgemetrics sources excerpt cook_sao` writes the committed real-row fixture
> `tests/fixtures/cook_sao/` by a documented stratified rule with the
> restricted and quasi-identifying columns blanked; the `cook_sao` entry of
> `docs/DATA_SOURCES.md` is completed from the portal's terms, each dataset's
> license, and the profile; `docs/ROADMAP.md` questions 3 and 4 are resolved
> and question 2 carries what the terms say; and the project roadmap's Phase 5
> text is corrected where it assumed a cross-case person key. This step lands
> the evidence; Step 3 maps it, Step 4 parses it, and every later test runs on
> its fixture.

**Branch:** `feature/phase05-step1-cook-county-due-diligence`

**Deploys:** local raw lake and database rows — after the merge the operator
runs `uv run poe ingest-cook` once (the five exports, about 1.5 GB in total,
TBD exactly, stream into the raw lake with five `source_record` rows and an
`ingest_run` that publishes no canonical row) and a second time (no download:
the rows-updated times are unchanged). No migration; `/api/v1/coverage` lists
`cook_sao` with zero rows and no coverage window until Step 4.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                                  |
| ------------ | ------------------------------------------------------ |
| Model        | Opus 5.5                                               |
| Backup       | GPT-6 Sol — Codex · Intelligence Extra High            |
| Platform     | Claude Code                                            |
| Effort       | Extra High (raised from Claude Code's default Medium)  |
| Thinking     | On                                                     |
| Conversation | **New**                                                |

**Model rationale:** This step produces the evidence every later step stands
on: a due-diligence record that must not overstate a source's terms or fields,
a profile that settles two open data-access questions and a planning-time
finding from the stored artifacts, and a fetch path rebuilt to stream exports
of hundreds of megabytes — PRIMARY `knowledge` (grounded, low-hallucination
source research and documentation), SECONDARY `coding`, High complexity with
cross-cutting scope (the HTTP client, the raw store, the runner's hashing, a new
connector, two commands, the register, and the project roadmap). Opus 5.5 is
S-tier in knowledge and S-tier in coding (HLE 61.4% at max); Fable 5.1 ties it
on both rows and on coverage and the output-price tie-breaker removes it ($50
against $20), and Sonnet 5.5, A-tier in knowledge, drops at the PRIMARY
rating. The Platform is Claude Code on the $200 claude.ai Max subscription
(weekly pool at `headroom`); the operator's `capped` posture makes the
complexity ladder the final effort: Claude Code opens Opus 5.5 at Effort
`Medium`, and this step raises it to `Extra High` — `High` for the complexity,
one rung more for a knowledge task of cross-cutting scope — not `Max`, since no
reasoning-depth bottleneck is claimed and the profile's `--check` and the tests
pin every fact the step records. Thinking `On` (the operator never disables
it). Backup: GPT-6 Sol on Codex (the $100 ChatGPT Pro 5x pool, the operator's
first backup provider); no other provider is S-tier in knowledge, so the
selector drops the floor to the strongest A-tier knowledge model, and GPT-6 Sol
leads the S-tier coders there on coverage, at Intelligence `Extra High` for the
same reasons; it is not a `*-codex` variant, which the operator's
ChatGPT-account sign-in cannot run. Conversation is New per phase-boundary
hygiene.

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
       feature/phase05-step1-cook-county-due-diligence`
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
       roadmap's Phase 5
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 5` heading.

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
       finding → the versioned rule,
       vocabulary, registry, or
       specification entry, version
       bumped; a data-access
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
       step: the committed fixture
       is real public-domain rows,
       so every value of `race`,
       `gender`, `age_at_incident`,
       `incident_city`,
       `incident_begin_date`,
       `incident_end_date`,
       `law_enforcement_agency`, and
       `unit` is blank in every
       fixture row (a unit test
       reads each file and asserts
       it); the committed profile
       lists the restricted columns'
       distinct values without a
       count, a cross-tabulation, or
       a per-row value; no raw
       export, no lake object, and
       no local profile output with
       counts is ever staged
       (`data/lake/` and any scratch
       directory stay git-ignored);
       the Socrata exports need no
       token and none is added;
       `profile.yaml`'s 64-hex
       digests are allowlisted by
       the scoped
       `.secrets.baseline` refresh
       `AGENTS.md` describes (that
       file alone, forward-slash
       `filename` entries).

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. In
       this step: the temporary
       download file is created with
       `tempfile` under a directory
       the run owns, never under the
       repository, and is removed on
       success, on a cap overrun,
       and on any exception; the
       export and metadata URLs are
       module constants over HTTPS
       (the client refuses any other
       scheme, redirects included);
       CSV parsing reads strings
       only (`infer_schema=False`);
       the profile's YAML is written
       with `yaml.safe_dump` and the
       excerpt's paths are built
       from constants, never from a
       value in the data.

    3. DEPENDENCY AUDIT. Any new or
       bumped dependency passes the
       audit (pip-audit / npm audit
       / osv-scanner); no
       known-vulnerable, yanked, or
       typo-squatted package. This
       step adds no dependency
       (boto3's managed transfer and
       Polars' lazy CSV scan are
       already locked). If one is
       added, it passes `pip-audit
       --strict --require-hashes`
       over the `uv.lock` export
       (`scripts/audit_deps.py`).

    4. SENSITIVE-DATA REVIEW.
       Whatever this step touches
       stays least-privilege,
       encrypted in transit + at
       rest, and out of logs and
       client bundles. If the step
       adds a data path, name how
       PII/secrets are protected. In
       this step: real
       defendant-level records reach
       the maintainer's machine for
       the first time and stay
       there — in the raw lake and
       in temporary files the run
       deletes; no log line names a
       participant id, a case id, or
       a restricted value (the fetch
       logs dataset names, sizes,
       and digests only); the
       profile command runs as the
       ingest role and reads the
       lake, never the canonical
       tables of another source.
       The excerpt keeps real
       `case_id` and
       `case_participant_id` values
       (public, pseudonymous, and
       needed to join the datasets);
       the case id becomes the
       public SAO case number in
       Step 4, and Step 4's
       `test_cook_sao_ingest.py`
       and Step 7's public-contract
       extension prove no
       participant id reaches an
       app-readable column.

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
    JudgeMetrics. Phase 5. Step 1:
    Cook County source due
    diligence, the streamed fetch,
    and the value-set profile.

    Current state (as of Phase 4,
    tag `v0.4.0-phase-4`):

    - `docs/DATA_SOURCES.md`
      `cook_sao` (verified
      2026-09-15) lists the five
      current datasets and their
      columns — Intake `3k7z-hchi`
      (17), Initiation `7mck-ehwz`
      (38), Dispositions
      `apwk-dzx8` (33), Sentencing
      `tg8v-tm6u` (41), Diversion
      `gpu3-5dfh` (13) — on
      `datacatalog.cookcountyil.gov`,
      the archived pre-2018-02-13
      versions, and "Remaining to
      verify": the portal terms,
      the value sets, the stability
      of `case_participant_id`
      (`docs/ROADMAP.md` questions
      2, 3, 4; question 2 is the
      operator's).
    - Planning-time measurements
      (2026-10-04, read-only SODA
      aggregate queries, recorded
      in this roadmap's Current
      State): 528,111 / 1,228,260 /
      1,080,014 / 305,884 / 29,421
      rows; every dataset's
      metadata says rows updated
      2026-04-02 and license
      "Public Domain"; NO
      `case_participant_id` appears
      under more than one `case_id`
      in any dataset (the id is per
      case; the corpus has no
      cross-case person key);
      `received_date` reaches back
      to 1901-07-24 in Dispositions
      and Sentencing; 469 distinct
      `judge` strings (76,613 null
      rows) and 402 `sentence_judge`
      strings; a few `charge_id`
      values span two cases. Your
      measurements from the stored
      artifacts are authoritative;
      record any difference.
    - `src/judgemetrics/ingest/http.py`
      buffers a body in a
      `bytearray` under
      `DEFAULT_MAX_BYTES = 200 MiB`;
      `RawArtifact.from_path`
      already hashes a file in 1
      MiB chunks, but the runner
      re-hashes with
      `sha256_hex(raw.read_bytes())`
      and stores with
      `store.put(bytes, key)`;
      `S3RawObjectStore.put` is one
      `put_object`; a store key's
      extension comes from the
      external id (at most three
      suffixes of at most 16
      characters), so the external
      ids must be names like
      `intake.csv`.
    - Connector patterns:
      `ingest/fjc/` (an HTTPS
      source with verified and
      expected header sets,
      validators, a no-argument
      constructor for
      `ingest/registry.py`) and
      `ingest/synthetic/` (a
      multi-file source with
      `load_context`). The registry
      lists only those two in
      `BUILTIN_CONNECTOR_MODULES`.
      `judgemetrics ingest run`
      requires the identifier
      pepper for every source.
    - The FJC fixture
      (`tests/fixtures/fjc/`) is
      real rows with two
      demographic columns dropped
      and its data-quality issues
      planted by row selection,
      never by editing a record
      (AGENTS.md). There is no
      `judgemetrics sources` command
      group.
    - The project roadmap's Phase 5
      text, its "Changes from the
      original brief" row for Cook
      County ("person-linkable
      now"), and its risks table
      assume the cross-case key.

    Files to read (every file before
    drafting):
    - docs/DATA_SOURCES.md (the
      register's rules and the
      `cook_sao` and `fjc`
      entries).
    - docs/ROADMAP.md
      ("Unresolved data-access
      questions", "Known issues").
    - docs/roadmap/ROADMAP.md
      (§2 "Changes from the
      original brief", Phase 5,
      §5 "Risks & mitigations",
      "Data classification").
    - This roadmap's Overview and
      Current State.
    - src/judgemetrics/ingest/base.py,
      runner.py (`_retrieve`,
      `_with_validators`,
      `_read_fixture`, the 304
      path), http.py, store.py,
      registry.py.
    - src/judgemetrics/ingest/fjc/
      (every file).
    - src/judgemetrics/cli.py (the
      `ingest` group, option and
      exit-code conventions).
    - tests/fixtures/fjc/README.md,
      tests/integration/test_fjc_ingest.py,
      the raw-store and HTTP unit
      tests under tests/unit/.
    - pyproject.toml (poe tasks),
      Makefile,
      tests/unit/test_repo_hygiene.py
      (`SHARED_TARGETS` and the
      first-line path comments),
      .pre-commit-config.yaml,
      .gitignore.
    - AGENTS.md ("Architectural
      decisions").
  </context>

  <goal>
    Ship the streamed fetch path
    (temporary-file downloads under
    a connector-chosen cap, chunked
    hashing, `put_file` on both
    store backends); the `cook_sao`
    connector at parser version `0`
    with portal metadata and a
    rows-updated short-circuit;
    `judgemetrics sources profile
    cook_sao [--out] [--check]
    [--from-fixture]` and the
    committed
    `data/reference/cook_sao/profile.yaml`;
    `judgemetrics sources excerpt
    cook_sao --out DIR
    [--from-fixture]` and the
    committed
    `tests/fixtures/cook_sao/`; the
    completed register entry, the
    resolved questions, the
    corrected project roadmap; the
    `ingest-cook` task — with the
    tests that prove the fetch is
    bounded, the profile and the
    excerpt are deterministic, and
    no restricted value is
    committed.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Streamed downloads. In
      `ingest/http.py` add a
      download that streams the
      response body to a temporary
      file (`tempfile`, under a
      directory the run owns),
      hashing while it writes and
      enforcing the caller's
      `max_bytes` both against
      `Content-Length` and while
      reading, so an over-cap body
      aborts, deletes the file, and
      raises `FetchError` naming
      the cap; HTTPS on the request
      and the final URL, retries,
      backoff, timeouts, and the
      conditional-request headers
      behave as today. It returns
      `RawArtifact.from_path` with
      the digest it computed. The
      in-memory path stays for
      callers that want it; the FJC
      connector's stored records
      are unchanged (its fixture
      tests and digests prove it).
    </requirement>

    <requirement>
      Hash and store files without
      loading them. The runner
      takes the digest of a
      path-backed artifact from a
      chunked read, never from
      `read_bytes()`, and stores it
      through a new
      `RawObjectStore.put_file(path,
      key)`: the filesystem backend
      copies in chunks to a
      temporary file beside the
      target, fsyncs, and
      `os.replace`s; the S3 backend
      uses boto3's managed
      multipart transfer with the
      sha256 in the object
      metadata. Immutability holds:
      a key that exists with a
      different digest raises
      `ImmutableObjectError`, the
      same digest is a no-op —
      compared by the stored
      digest, not by reading the
      whole object. Add the
      reverse, `get_file(key,
      dest)`, which streams a stored
      object to a temporary file and
      verifies its digest, and use
      it wherever the runner reads an
      artifact back from the lake
      (`_retrieve` and
      `_materialized` call
      `store.get()` for whole bytes
      today), so re-deriving the
      corpus under a new parser
      version never holds an export
      in memory. Every temporary
      file is removed on success and
      on failure.
    </requirement>

    <requirement>
      The connector at parser
      version `0`. Create
      `src/judgemetrics/ingest/cook_sao/`
      with `sources.py`
      (`SOURCE_ID = "cook_sao"`;
      the five current datasets in
      dependency order — Intake,
      Initiation, Dispositions,
      Sentencing, Diversion — with
      their portal ids, external
      ids `intake.csv`,
      `initiation.csv`,
      `dispositions.csv`,
      `sentencing.csv`,
      `diversion.csv`, the export
      URL
      `https://datacatalog.cookcountyil.gov/api/views/<id>/rows.csv?accessType=DOWNLOAD`,
      and the metadata URL
      `https://datacatalog.cookcountyil.gov/api/views/<id>.json`),
      `schema.py` (the verified
      header set of each dataset,
      re-checked against the
      metadata's column list and
      the first fetched header,
      with `HEADERS_VERIFIED_ON`;
      `CODED_COLUMNS`,
      `RESTRICTED_COLUMNS` = `race`,
      `gender`, `age_at_incident`,
      and `BLANKED_COLUMNS` for the
      excerpt), and `connector.py`
      (`parser_version = "0"`;
      `SourceInfo(owner="Cook County
      State's Attorney's Office",
      source_type="government_open_data",
      access_method="socrata_bulk_export",
      terms_metadata` with the
      license, the attribution, and
      the terms URL,
      `observable_outcomes=()`);
      `discover` returns the five
      artifacts from constants and
      makes no network call (the
      runner calls it in fixture
      mode too); `fetch` first reads
      the dataset's metadata (rows
      updated, license, columns)
      into the artifact's response
      metadata, returns
      `RawArtifact.unchanged` with
      the previous digest when the
      rows-updated time equals the
      previous record's — the
      runner's `_with_validators`
      forwards the previous
      record's rows-updated time
      beside its digest and
      validators — and otherwise
      streams the export under a
      cap of at least twice the
      largest export you measure;
      `validate_raw` fails on a
      missing verified header and
      warns on an extra one; `parse`
      yields nothing, with a
      docstring saying Step 4 bumps
      the version). Register the
      module in
      `BUILTIN_CONNECTOR_MODULES`.
      Do not fetch the archived
      pre-2018 versions; record
      their portal ids and what
      they hold in the register.
    </requirement>

    <requirement>
      The profile. Add a
      `judgemetrics sources` group
      with `profile cook_sao [--out
      PATH] [--check]
      [--from-fixture DIR]` (ingest
      role; default `--out
      data/reference/cook_sao/profile.yaml`).
      It reads the five artifacts of
      the latest succeeded run from
      the raw lake (S3 objects are
      streamed to a temporary file
      first and verified against
      their digest), scans each
      lazily with Polars as
      strings, and writes, with
      `yaml.safe_dump`, sorted keys,
      and no wall-clock time:
      `version: 1`; the artifacts
      (external id, sha256, bytes,
      rows updated, retrieved at);
      per dataset the row count,
      each column's null count,
      each date column's range (the
      export's date format verified
      and stated), and for each
      `CODED_COLUMNS` entry the
      distinct values with counts
      ordered by count then value;
      the (`charge_disposition`,
      `charge_disposition_reason`)
      pairs with counts; the
      distinct `judge` and
      `sentence_judge` strings with
      counts; for `race` and
      `gender` the distinct values
      only and for
      `age_at_incident` its range
      and nulls only; for every
      other column the distinct
      count only; `keys` — per
      dataset distinct cases and
      participants, participants
      under more than one case
      (the cross-case measurement),
      the share of each dataset's
      (case, participant) keys
      found in Intake, charge ids
      under more than one case,
      versions per charge, rows and
      participants per charge
      version in Initiation (does a
      version ever span
      participants?), and
      disposition and sentence rows
      per charge version and per
      participant; and
      `anomalies` — rows received
      before 2011-01-01 per dataset
      with the earliest dates,
      dates after 2024-12-30,
      unparseable values. The same
      artifacts always render the
      same bytes; `--check` exits 1
      with a diff when the
      committed file differs;
      `--from-fixture` profiles a
      directory of the five CSVs.
    </requirement>

    <requirement>
      The excerpt and the fixture.
      Add `judgemetrics sources
      excerpt cook_sao --out DIR
      [--from-fixture DIR]`. It
      chooses cases stratum by
      stratum, each time the
      smallest `case_id` (string
      order) not chosen yet that
      satisfies the stratum: every
      `charge_disposition` with at
      least 100 rows; the five
      commonest reasons and the
      suppression-motion reason;
      each bond type and a null
      bond; each `sentence_phase`
      but "Summary Charge Info";
      each `sentence_type` with at
      least 1,000 rows; a
      diversion; an open case (no
      disposition); a case with two
      participants; a disposition
      without a judge; a case
      received before 2011; a case
      received on or after
      2023-09-18; a charge with two
      versions; then twelve
      sentenced cases and twelve
      disposed cases of the judge
      with the most sentences, so
      Step 7's e2e flow meets an
      unsuppressed observation
      (threshold 10). It writes, for
      every chosen case, all its
      rows of all five datasets in
      artifact order with the
      `BLANKED_COLUMNS` values
      emptied (headers verbatim),
      plus `README.md` (the rule,
      the strata each case
      satisfies, the blanked
      columns, the source digests,
      the counts). Rerunning over
      the same artifacts, or over
      the fixture itself, writes
      identical bytes. Commit the
      result as
      `tests/fixtures/cook_sao/`
      (under the 1,024 KB large-file
      hook); a stratum the data
      cannot satisfy is reported,
      not faked.
    </requirement>

    <requirement>
      The register, the questions,
      and the project roadmap. Read
      the portal's terms of use and
      each dataset's license and
      attribution metadata (URLs and
      dates recorded) and complete
      `docs/DATA_SOURCES.md`
      `cook_sao`: documentation read,
      access method and sizes,
      headers re-verified, terms,
      the required citation,
      Redistribution — each of the
      three answers `yes` only
      where the documents say so,
      quoted; anything they leave
      open stays `unverified` and
      question 2 stays open for the
      operator with what the
      documents say — the person
      linkage (a per-case
      participant id; no cross-case
      key; the profile's numbers),
      the judge and actor
      attribution, the first real
      metrics (the judge-attributed
      sentencing and disposition
      families and court-level bond
      decisions; no cross-case
      outcome), the update
      frequency and the coverage
      evidence (each dataset's last
      dates), and the known
      limitations (no cross-case
      key; a bond type is a
      decision, not a release; the
      Pretrial Fairness Act regime
      from 2023-09-18; pre-2011 and
      1901 receipt dates). In
      `docs/ROADMAP.md` resolve
      questions 3 (the value sets
      are `profile.yaml`; their
      mapping is Step 3's) and 4
      (stability and the cross-case
      measurement) and add the
      missing cross-case key to
      "Known issues". Correct the
      project roadmap
      (`docs/roadmap/ROADMAP.md`):
      the Phase 5 introduction's
      source facts, §5.2's persons
      (case participations), §5.4's
      linkage and first real metric,
      the Phase 5 acceptance
      criterion that names it, the
      Cook County row of "Changes
      from the original brief", and
      a new row in "Risks &
      mitigations" (the first real
      corpus has no cross-case
      person key → within-case
      metrics only, cross-case
      outcomes not observable, the
      Florida selection weights a
      lawful cross-case key). In the
      same Stage-3 commit that sets
      Phase 5 `In progress`, set the
      Phase 5 row of §8 "Phase
      Complexity Summary" to this
      roadmap's picks (Opus 5.5 for
      Steps 1, 2, 3, 5, and 8;
      Sonnet 5.5 for Steps 4, 6,
      and 7).
    </requirement>

    <requirement>
      Commands and documentation.
      Add the poe task `ingest-cook`
      (`judgemetrics ingest run
      cook_sao`) and the matching
      Makefile target, keeping
      `bootstrap` unchanged (its
      sequence is pinned by
      `verify_phase03.py` check 40
      and the hygiene test; a
      gigabyte download does not
      belong in the one-command
      demo). Document the fetch, the
      profile, and the excerpt in
      `docs/ARCHITECTURE.md`
      ("Cook County source"),
      `tests/fixtures/cook_sao/README.md`,
      `README.md` (how to fetch the
      real corpus), and `AGENTS.md`
      (the streamed fetch, the
      rows-updated short-circuit,
      the blanking rule, and that
      the profile is regenerated,
      never hand-edited).
    </requirement>

    <requirement>
      Add tests:
      - `tests/unit/test_streaming_download.py`
        (a mocked client: a body
        over the cap fails mid-
        stream and leaves no file;
        the digest equals the
        bytes'; validators are sent;
        a non-HTTPS redirect is
        refused).
      - `tests/unit/test_raw_store_files.py`
        (`put_file` on the
        filesystem backend: copy,
        no-op on the same digest,
        `ImmutableObjectError` on a
        different one, temporary
        files removed; the S3
        backend in the MinIO
        contract test CI already
        runs).
      - `tests/unit/test_cook_sao_connector.py`
        (discovery from mocked
        metadata; the rows-updated
        short-circuit; header drift
        error and warning; parse
        yields nothing; the registry
        lists the connector).
      - `tests/unit/test_cook_sao_profile.py`
        (the fixture's profile is
        deterministic, lists
        restricted values without
        counts, and reports zero
        participants under more than
        one case; the committed
        `profile.yaml` parses, names
        five digests, and lists the
        restricted columns without
        counts — CI has no lake, so
        `--check` over the stored
        artifacts is V1.3).
      - `tests/unit/test_cook_sao_fixture.py`
        (every `BLANKED_COLUMNS`
        value is empty in every row;
        headers equal the verified
        sets; excerpting the fixture
        reproduces it byte for byte;
        the README names every
        case's strata).
      - `tests/integration/test_cook_sao_fetch.py`
        (`ingest run cook_sao
        --from-fixture
        tests/fixtures/cook_sao`:
        five `source_record` rows,
        no canonical row, a rerun
        records nothing new).
    </requirement>

    <requirement>
      Filepath comment: every new
      file gets the repo-relative
      path as the first line
      (`# path` in Python and YAML,
      `<!-- path -->` in Markdown;
      the fixture's CSVs, whose
      first line is the source's
      header, carry none, as the
      FJC fixture's do). Add the
      fixture README to the hygiene
      test's path-comment list.
    </requirement>
  </requirements>
</task>
```

### Step 1 acceptance criteria

- `uv run judgemetrics ingest run cook_sao` stored the five current exports in
  the raw lake through the streamed path (peak memory independent of the
  export size), with their sizes and digests recorded in the PR body and in
  `docs/DATA_SOURCES.md`; a second run downloaded nothing and recorded no new
  `source_record`.
- `data/reference/cook_sao/profile.yaml` is generated from those artifacts and
  `judgemetrics sources profile cook_sao --check` exits 0; it reports zero
  participant ids under more than one case for every dataset (or the measured
  count, recorded as a finding if it is not zero), the key-overlap shares, and
  the anomalies.
- `tests/fixtures/cook_sao/` holds the five excerpted CSVs and a README naming
  the rule; every blanked column is empty in every row; excerpting the fixture
  reproduces it byte for byte.
- `docs/DATA_SOURCES.md` `cook_sao` has no "Remaining to verify" item except
  those question 2 leaves to the operator; questions 3 and 4 read resolved in
  `docs/ROADMAP.md`; the project roadmap no longer claims a cross-case person
  key and carries the new risk row.
- The new unit and integration tests pass; `uv run poe check` is green locally;
  CI is green.
- **Deployed & verified:** after the merge, `uv run poe ingest-cook` on the
  maintainer's machine completed twice (`judgemetrics ingest runs --source
  cook_sao` shows both succeeded; the second fetched no body), the five objects
  are in the lake under `cook_sao/`, and `GET /api/v1/coverage` lists
  `cook_sao` with zero rows and no coverage window.
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff — secret/PII scan clean, SAST clean,
  dependency audit clean, and the source surface handles sensitive data per the
  project ROADMAP "Security & privacy strategy": no restricted value, count, or
  quasi-identifier is committed (fixture test), the downloads stream to a
  temporary directory outside the repository that every exit path removes, and
  no log line of the fetch, the profile, or the excerpt names a participant id,
  a case id, or a restricted value.

---

## Step 2 — Florida Source Research and the Lawful Acquisition Plan

**Status:** Not started

> **Goal:** Produce the evidence and the plan the Florida pilot of Phase 7 waits
> on, and put the requests in the mail. `docs/florida-data-inventory.md`
> inventories the statewide sources (OSCA's Judicial Data Management Services
> and the Uniform Case Reporting specification, the clerks' statewide systems),
> the legal framework (Chapter 119, Florida Statutes; Article I, §24 of the
> Florida Constitution; Florida Rules of General Practice and Judicial
> Administration 2.420 and 2.425; sealing, expunction, and juvenile
> exclusions; the cost rules), and at least six county clerks — Broward and
> Miami-Dade among them, neither assumed best — each with its access method,
> fields (judge assignment, charges, dispositions, sentences, first-appearance
> and release decisions, lawfully processable defendant-matching fields, and
> whether a cross-case person key exists), history, limits, terms, cost, and
> effort; it applies the brief's nine-step selection process as a scored table
> in which a lawful cross-case person key carries weight (Step 1 verified that
> Cook County lacks one), names the selected pilot and a ranked fallback, and
> writes the lawful acquisition plan with the trigger for Phase 7 §7.1's
> fallback. Drafted requests under `docs/florida/requests/` ask explicitly for
> the three redistribution rights; the `fl_jdms` and `fl_clerks` register
> entries and question 8 are rewritten from verified facts; and the operator —
> the only party who may send them — submits the requests, whose dates this
> step's PR records in `docs/ROADMAP.md`. This step changes no application code
> (one line joins the hygiene test's path-comment list) and runs in parallel
> with Steps 3–7 when the operator chooses.

**Branch:** `feature/phase05-step2-florida-acquisition-plan`

**Deploys:** nothing beyond merge — operator wall-clock: before the merge the
operator submits each drafted request (an outward-facing act only the operator
may perform, with the operator's own contact details) and the PR records the
submission dates; the answers arrive on Florida's timeline, overlapping Phases 6
and 7.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                                  |
| ------------ | ------------------------------------------------------ |
| Model        | Opus 5.5                                               |
| Backup       | GPT-6 Astra — Codex · Intelligence Extra High          |
| Platform     | Claude Code                                            |
| Effort       | Extra High (raised from Claude Code's default Medium)  |
| Thinking     | On                                                     |
| Conversation | **New**                                                |

**Model rationale:** This is grounded research across many official sources —
statutes, court rules, a state program, and a dozen county clerks' pages —
where an overstated capability becomes a wasted request or an unlawful plan,
followed by a weighted selection and a written plan: PRIMARY `knowledge`
(low-hallucination, cited research), SECONDARY `planning`, High complexity
(high ambiguity, many interacting criteria) with knowledge-category
cross-cutting scope. Opus 5.5 is S-tier in knowledge and S-tier in planning
(HLE 61.4% at max); Fable 5.1 ties it on both rows and on coverage and loses
the output-price tie-breaker ($50 against $20), and Sonnet 5.5 is A-tier in
knowledge. The Platform is Claude Code on the $200 claude.ai Max subscription
(weekly pool at `headroom`), whose web search and fetch tools the research
needs; under the `capped` posture the ladder is final: Claude Code opens Opus
5.5 at Effort `Medium`, and this step raises it to `Extra High` — `High` for
the complexity, one rung more for a knowledge task of cross-cutting scope —
not `Max`, since the citation rule and the operator's review of the requests
catch an unsupported claim. Thinking `On`. Backup: GPT-6 Astra on Codex (the
$100 ChatGPT Pro 5x pool); no other provider is S-tier in knowledge, so the
selector drops the floor and GPT-6 Astra is the one A-tier knowledge model that
is S-tier in planning, at Intelligence `Extra High`; not a `*-codex` variant.
Conversation is New per phase-boundary hygiene (and, when it overlaps Steps
3–7, its own worktree per the Worktree rule).

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
       feature/phase05-step2-florida-acquisition-plan`
       from a clean, up-to-date
       `main`. The exact branch name
       is in this step's
       `**Branch:**` line above. If
       the Worktree rule applies —
       this step is drawn in
       parallel with Steps 3–7 — use
       `git fetch origin && git
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
       roadmap's Phase 5
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 5` heading.

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
       finding → the versioned rule,
       vocabulary, registry, or
       specification entry, version
       bumped; a data-access
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
       on to Step 3." (this step
       runs in parallel: the
       operator then resumes at the
       first step whose Status is
       not `Complete`). That line is
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
       step: the documents name
       offices, published
       public-records contacts, and
       public officials in their
       official role only — never a
       private individual, a
       defendant, a case, or any
       record content; the drafted
       requests carry the
       operator's contact details
       as a bracketed field the
       operator fills when
       submitting, never committed;
       no account, password, or
       portal credential is
       created, used, or recorded.

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. This
       step adds no code; the hooks
       still run over the diff.

    3. DEPENDENCY AUDIT. Any new or
       bumped dependency passes the
       audit (pip-audit / npm audit
       / osv-scanner); no
       known-vulnerable, yanked, or
       typo-squatted package. This
       step adds no dependency.

    4. SENSITIVE-DATA REVIEW.
       Whatever this step touches
       stays least-privilege,
       encrypted in transit + at
       rest, and out of logs and
       client bundles. If the step
       adds a data path, name how
       PII/secrets are protected. In
       this step: research reads
       public pages only, never
       behind a login, a CAPTCHA, or
       a robots exclusion, and never
       against a site's terms; no
       record of any person is
       downloaded, sampled, or
       pasted, even where a clerk
       publishes case search; the
       requests ask for confidential
       and sealed records to be
       excluded at the source (rule
       2.420, the expunction and
       juvenile statutes) and for
       the minimum fields the
       brief's metrics need.

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
    JudgeMetrics. Phase 5. Step 2:
    Florida source research and the
    lawful acquisition plan.

    Current state (as of Phase 4,
    post-Phase-5 Step 1):

    - The brief's `<florida_pilot>`:
      after the architecture works
      on synthetic data, ingest
      real state criminal-court
      records from one Florida
      jurisdiction with the best
      lawful machine-readable
      access; the nine-step
      selection process (evaluate
      access; document fields and
      history; confirm judge
      assignment; confirm charges
      and dispositions; confirm
      lawfully processable
      defendant-matching fields;
      confirm pretrial and release
      information; confirm
      follow-up event feasibility;
      estimate extraction and
      maintenance cost; select by
      data strength, not by
      population); Broward and
      Miami-Dade may be evaluated,
      neither assumed best; the
      preferred first real metric
      is new criminal court cases
      after a clearly identified
      qualifying pretrial event.
      Its `FL_UCR` source warns
      that OSCA's web services need
      coordinated credentials and
      are not anonymously readable;
      `COUNTY_CLERKS` prefers bulk
      exports, APIs,
      machine-readable downloads,
      or public-records requests
      before any scraping.
    - `docs/DATA_SOURCES.md`
      `fl_jdms` and `fl_clerks`:
      unverified workstreams; every
      request and agreement asks
      for redistribution rights
      (aggregates, pseudonymous
      case-level views, commercial
      redistribution) recorded in
      the **Redistribution** field;
      question 8 in
      `docs/ROADMAP.md` (operator).
    - Project roadmap: §5.5 (this
      step), §7.1 (the Florida
      connector, gated on access,
      with the next-best verified
      state source as the
      fallback), §9.1–9.2 (a source
      not verified for a tier is
      excluded from it).
    - Step 1 verified that Cook
      County's participant id is
      per case: without a lawful
      cross-case person key (or
      lawfully processable name
      and date of birth), no
      follow-up outcome can be
      measured, so the brief's
      preferred first real metric
      depends on it.

    Files to read (every file before
    drafting):
    - docs/brief/judgemetrics-master-project-specification.xml
      (`<florida_pilot>`,
      `<data_source_strategy>`
      incl. `<source_policy>`,
      `<privacy_and_legal_design>`,
      `<entity_resolution>`
      person signals).
    - docs/DATA_SOURCES.md (the
      register's rules, the
      `fl_jdms`, `fl_clerks`, and
      `cook_sao` entries).
    - docs/ROADMAP.md (question 8,
      the Cook County findings).
    - docs/roadmap/ROADMAP.md
      (§5.5, §7.1, §9.1–9.2, "Data
      classification").
    - This roadmap's Overview
      (the cross-case design
      rationale).
  </context>

  <goal>
    Ship `docs/florida-data-inventory.md`
    (statewide sources, legal
    framework, at least six county
    candidates, a scored selection
    table, the selected pilot and a
    ranked fallback, the acquisition
    plan with the Phase 7 fallback
    trigger, the redistribution
    asks, open questions), the
    drafted requests under
    `docs/florida/requests/`, the
    rewritten `fl_jdms` and
    `fl_clerks` register entries,
    question 8 and a "Florida
    acquisition requests" table in
    `docs/ROADMAP.md` — with every
    request submitted by the
    operator and dated before the
    merge.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Research rules. Official
      sources first: the Florida
      courts' pages for JDMS and the
      UCR specification, the
      statewide clerks'
      association's case-information
      offerings, the Florida
      Statutes and the court rules,
      each candidate clerk's own
      public-records, bulk-data, and
      case-search pages. Cite every
      fact with its URL and access
      date; mark anything you could
      not confirm `unverified` and
      say what would confirm it.
      Never create an account,
      submit a form, send a
      message, or bypass a login,
      CAPTCHA, robots rule, or
      terms of use; never download
      or quote a record of any
      person. A capability is never
      inferred from a neighbouring
      county or from a news report.
    </requirement>

    <requirement>
      The inventory
      (`docs/florida-data-inventory.md`,
      80-column prose), with these
      sections: "Purpose and
      criteria" (the brief's nine
      steps as scored criteria with
      weights, the cross-case
      person key and the
      redistribution rights
      weighted, data strength over
      population); "Statewide
      sources" (JDMS and UCR — what
      the specification documents,
      the credential process, the
      judicial-officer fields;
      statewide clerk systems;
      whether any is open to a
      non-agency requester);
      "Legal framework" (Chapter
      119 and Article I §24, rule
      2.420's confidential
      categories, rule 2.425,
      sealing, expunction, and
      juvenile exclusions, the
      duplication-fee and
      special-service-charge rules
      of §119.07(4), and any
      court-records bulk policy);
      "County candidates" (at least
      six, Broward and Miami-Dade
      included, each with access
      methods, fields, history,
      cadence, limits, terms, cost,
      effort, and the
      lawful-matching assessment);
      "Selection" (the scored table
      with evidence links, the
      selected pilot, a ranked
      fallback, and why);
      "Acquisition plan" (requests,
      recipients, sequencing, cost
      ceiling as an operator
      decision marked TBD,
      follow-up cadence, what
      response triggers Phase 7
      §7.1's fallback to the
      next-best verified state
      source); "Redistribution"
      (the three rights requested,
      and how an answer is
      recorded); "Open questions".
    </requirement>

    <requirement>
      The requests. For every
      request the plan calls for,
      write
      `docs/florida/requests/<jurisdiction>-<recipient>.md`:
      the recipient office and its
      published public-records
      contact, the legal basis, the
      records requested (fields
      named, years, a
      machine-readable bulk format,
      update cadence), the three
      redistribution rights asked
      for explicitly (republishing
      derived aggregates,
      republishing pseudonymous
      case-level views, commercial
      redistribution), the
      exclusion of confidential,
      sealed, expunged, and juvenile
      records at the source, a
      request for a cost estimate
      before fulfilment, the
      delivery method, and a
      bracketed field for the
      operator's contact details.
    </requirement>

    <requirement>
      The register and the status
      document. Rewrite
      `docs/DATA_SOURCES.md`
      `fl_jdms` and `fl_clerks` from
      what you verified (dated),
      with a candidate table and
      every Redistribution answer
      `unverified` until an
      agreement says otherwise.
      Update question 8 in
      `docs/ROADMAP.md` (what is
      verified, what the requests
      ask, the owner) and add a
      "Florida acquisition requests"
      table (request file,
      recipient, drafted, submitted,
      status, next follow-up). If
      the selection contradicts the
      project roadmap's §5.5 or
      §7.1, record it as a finding
      and correct the text.
    </requirement>

    <requirement>
      Operator submission (Stage 4
      waits on it). When the PR is
      green, ask the operator to
      submit each drafted request
      with the operator's own
      contact details — an
      outward-facing act only the
      operator may perform; never
      send, email, or file anything
      yourself — and record each
      submission date, or the
      operator's reason for not
      sending it with the plan's
      fallback named, in the
      requests table on this branch
      before the merge.
    </requirement>

    <requirement>
      Filepath comment: every new
      Markdown file starts with
      `<!-- path -->`; add
      `docs/florida-data-inventory.md`
      to the hygiene test's
      path-comment list.
    </requirement>
  </requirements>
</task>
```

### Step 2 acceptance criteria

- `docs/florida-data-inventory.md` exists with the eight sections, evaluates the
  statewide sources and at least six county clerks (Broward and Miami-Dade
  among them), cites every fact with its URL and access date, and marks every
  unconfirmed claim `unverified`.
- The scored selection table names the selected pilot and a ranked fallback,
  weighs a lawful cross-case person key and the redistribution rights, and the
  acquisition plan names the response that triggers Phase 7 §7.1's fallback.
- Every request the plan calls for is drafted under `docs/florida/requests/`,
  asks for the three redistribution rights explicitly, and asks for
  confidential, sealed, expunged, and juvenile records to be excluded at the
  source.
- `docs/DATA_SOURCES.md` `fl_jdms` and `fl_clerks`, question 8, and the
  "Florida acquisition requests" table are current; every request carries a
  submission date or the operator's recorded reason.
- The hygiene test passes with the new path comments; CI is green.
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff — secret/PII scan clean, SAST clean,
  dependency audit clean, and the research surface handles sensitive data per
  the project ROADMAP "Security & privacy strategy": no private individual's
  details, no record content, and no credential appear in any committed file,
  and no page was read behind a login, a CAPTCHA, or a terms restriction.

---

## Step 3 — Mapping and Attribution Rules, the Judge and Court Tables, and Vocabulary 3

**Status:** Not started

> **Goal:** Turn the Step 1 profile into reviewed, versioned reference data that
> the connector applies on its very first ingest, so no real row is ever
> published with a guessed actor, a silently dropped value, or a judge merged on
> a hunch. Under `data/reference/cook_sao/`: `attribution_rules.yaml` maps
> every observed (`charge_disposition`, `charge_disposition_reason`) pair, every
> felony-review result, and every diversion outcome to a canonical disposition,
> its finality, an actor type, a judicial-discretion classification, an
> optional judicial ruling the reason records, and a written rationale, with
> `unknown` as the explicit fallback and the unknown share computed;
> `pretrial_rules.yaml` maps bond types under each legal regime (before and
> from 2023-09-18) to release semantics that never claim an unobserved
> release; `sentence_rules.yaml` maps sentence phases, types, commitment types,
> and units to components, terms in days, superseding sentences, and the
> within-case revocation event; `offense_map.csv` maps offense categories and
> classes to canonical categories and severities; `courts.yaml` defines the
> jurisdiction, the six district courts and a parent court, and maps every court
> name and facility; `judge_aliases.csv` and `judges.csv` resolve every distinct
> judge string to a canonical judge or mark it `ambiguous` or `unresolved` with
> a reason. `src/judgemetrics/ingest/cook_sao/rules.py` loads and validates them
> against case vocabulary version `3` — which adds exactly the canonical values
> they need, the restricted kinds `race` and `gender` included, and stays equal
> to the generator's constants — and outcome-model specification version `2`
> lists every new severity and offense level, with the demo's models refit and
> `docs/VALIDATION.md` re-rendered. This step lands the semantics; Step 4
> applies them, Step 5 publishes the unknown share, and Phase 6 §6.1 validates
> the rules against source documents.

**Branch:** `feature/phase05-step3-attribution-rules`

**Deploys:** local analytics surface — no migration; after the merge `uv run
poe compute-metrics` refits the demo seed's expected-outcome models under
specification version `2` (new levels with no rows leave every figure
unchanged; the refit proves it or the PR records the change) and
`/api/v1/ready` reports `spec_version` 2.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                                  |
| ------------ | ------------------------------------------------------ |
| Model        | Opus 5.5                                               |
| Backup       | GPT-6 Sol — Codex · Intelligence Extra High            |
| Platform     | Claude Code                                            |
| Effort       | Extra High (raised from Claude Code's default Medium)  |
| Thinking     | On                                                     |
| Conversation | **New**                                                |

**Model rationale:** This step decides, value by value, who made each decision
in a real court's coding — the judgment the project roadmap names as its first
risk — and encodes it as data, vocabulary, and validators: PRIMARY `knowledge`
(the legal meaning of Illinois dispositions, reasons, bond types, and sentence
codes against the brief's attribution model; low-hallucination), SECONDARY
`coding`, High complexity with novel problem-solving (no mapping exists to
follow; each rule is a precedent Phase 6 audits) and cross-file verification
(profile, vocabulary, generator constants, specification, tests). Opus 5.5 is
S-tier in knowledge and S-tier in coding (HLE 61.4% at max); Fable 5.1 ties on
both rows and coverage and loses the output-price tie-breaker ($50 against
$20); Sonnet 5.5, A-tier in knowledge, drops at the PRIMARY rating. The Platform
is Claude Code on the $200 claude.ai Max subscription (weekly pool at
`headroom`); under the `capped` posture the ladder is final: Claude Code opens
Opus 5.5 at Effort `Medium`, and this step raises it to `Extra High` for the
novel-problem and multi-step-verification conditions — not `Max`, because every
rule is reviewable data with an `unknown` fallback, the totality tests catch an
unmapped value, and the rules stay open to Phase 6's validation. Thinking `On`.
Backup: GPT-6 Sol on Codex (the $100 ChatGPT Pro 5x pool); no other provider is
S-tier in knowledge, so the selector drops the floor and GPT-6 Sol leads the
S-tier coders on coverage, at Intelligence `Extra High`; not a `*-codex`
variant. Conversation is New per phase-boundary hygiene.

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
       feature/phase05-step3-attribution-rules`
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
       roadmap's Phase 5
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 5` heading.

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
       finding → the versioned rule,
       vocabulary, registry, or
       specification entry, version
       bumped; a data-access
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
       step: the tables hold source
       codes, category labels,
       court and facility names, and
       judges' names as the source
       records them — public
       officials in their official
       role — and nothing about any
       defendant: no case id, no
       participant id, no record,
       and no count of a restricted
       value (the restricted
       vocabulary lists category
       labels only); `tables.yaml`'s
       64-hex digests are
       allowlisted by the scoped
       `.secrets.baseline` refresh
       `AGENTS.md` describes (that
       file alone, forward-slash
       `filename` entries).

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. In
       this step: every table loads
       with `yaml.safe_load` or the
       standard `csv` module from a
       path built from a module
       constant; a value is never
       evaluated, formatted into
       SQL, or used as a path; a
       malformed table raises
       `RuleError` naming the file,
       key, and field.

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
       this step: the restricted
       kinds `race` and `gender`
       join the vocabulary as the
       source's categories,
       normalized but not recoded
       (a recoding is a
       methodological choice Phase
       6's legal review owns); they
       join `restricted_attribute`,
       so the snapshot's
       `refuse_restricted` and the
       specification's exclusion of
       every restricted attribute as
       a feature cover them at once
       (Step 4 adds them to the
       public contract's and the
       OpenAPI test's restricted
       names as whole words); no
       module under `metrics/` names
       them (the static guard globs
       `metrics/**/*.py`).

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
    JudgeMetrics. Phase 5. Step 3:
    mapping and attribution rules,
    the judge and court tables, and
    vocabulary 3.

    Current state (as of Phase 4,
    post-Phase-5 Step 1):

    - `data/reference/cook_sao/profile.yaml`
      (Step 1) holds every coded
      column's value set with
      counts, the disposition and
      reason pairs, the distinct
      `judge` and `sentence_judge`
      strings, the court names and
      facilities, bond types,
      sentence phases, types, and
      commitment fields, the
      offense categories and
      classes, and the restricted
      columns' values. At planning
      time: 36 dispositions ("Nolle
      Prosecution" 714,681 of
      1,080,014 rows; "Plea Of
      Guilty"; "FNG"; "Finding
      Guilty"; "Death Suggested-
      Cause Abated"; jury verdicts;
      "Superseded by Indictment";
      "BFW"; "Case Dismissed";
      "SOL"; "FNPC"; "Charge
      Vacated"; "Charge Reversed";
      …), 31 reasons plus null
      ("PG to Other Count/s";
      "Motion to Quash Arrest &
      Suppress Evidence/Sustained";
      specialty-court graduations;
      …), bond types D, I, C, No
      Bond, and null, six sentence
      phases (7,492 "Probation
      Violation Sentencing"), 15
      sentence types, 30 commitment
      types, six districts, 17
      facilities, 469 and 402 judge
      strings. The profile is
      authoritative.
    - `data/reference/case_vocabulary.yaml`
      is `version: 2`, equal to
      `synthetic/vocabulary.py` by
      `tests/unit/test_vocabulary.py`
      (which also pins the kinds
      allowing `unknown` and
      `restricted_attribute =
      (age_band, synthetic_group)`).
      `severity` has five values,
      index 0 the most severe (read
      by `metrics/compute.py` and
      `metrics/adjustment/features.py`);
      `charge_disposition` five
      (`dismissed`, `acquitted`,
      `convicted_plea`,
      `convicted_verdict`,
      `pending`); `position` two;
      no kind exists for a reason,
      a bond type, a sentence type,
      race, gender, or a facility.
      `actor_type` is a PostgreSQL
      enum with the brief's nine
      actors; it needs no new value.
    - `data/reference/outcome_model.yaml`
      `version: 1`: `lead_severity`
      and `lead_category` must list
      every vocabulary value
      exactly once
      (`metrics/adjustment/spec.py`),
      so any severity or category
      added here bumps the
      specification. The committed
      `docs/VALIDATION.md` is the
      demo seed's render and CI's
      `e2e` job checks it.
    - Attribution today is carried
      verbatim from the synthetic
      source's rows
      (`ingest/synthetic/normalize.py`);
      no rule table exists. Judges
      resolve only by exact
      external identifiers; no alias
      table exists; entity
      resolution is person-only.
    - Required checks that pin what
      this step changes:
      `verify_phase04.py` check 7
      (the vocabulary and its
      restricted kinds) and check 12
      (the specification); relax a
      literal to the `>=` or subset
      pattern in this PR if it
      trips.

    Files to read (every file before
    drafting):
    - data/reference/cook_sao/profile.yaml
      and tests/fixtures/cook_sao/README.md.
    - docs/DATA_SOURCES.md
      (`cook_sao`, the SAO
      documentation links Step 1
      recorded — read them).
    - docs/brief/judgemetrics-master-project-specification.xml
      (`<event_attribution_model>`,
      `<entity_resolution>` judge
      signals, `<outcome_definitions>`,
      `<important_statistical_warnings>`).
    - data/reference/case_vocabulary.yaml,
      src/judgemetrics/normalization/vocabulary.py,
      src/judgemetrics/synthetic/vocabulary.py,
      tests/unit/test_vocabulary.py.
    - data/reference/outcome_model.yaml,
      src/judgemetrics/metrics/adjustment/spec.py,
      tests/unit/test_outcome_model_spec.py.
    - src/judgemetrics/metrics/compute.py
      and attribution.py (how
      severity, disposition, and
      actor are read).
    - src/judgemetrics/ingest/synthetic/normalize.py
      (the actor and discretion
      pattern a rule replaces).
    - src/judgemetrics/normalization/names.py
      (`normalize_person_name`).
    - docs/DATA_MODEL.md
      ("Vocabularies"),
      docs/ENTITY_RESOLUTION.md,
      docs/SYNTHETIC_DATA.md
      ("Regenerating the golden
      fixture"), AGENTS.md.
  </context>

  <goal>
    Ship case vocabulary `3`;
    outcome-model specification `2`;
    the seven tables under
    `data/reference/cook_sao/`
    (`attribution_rules.yaml`,
    `pretrial_rules.yaml`,
    `sentence_rules.yaml`,
    `offense_map.csv`,
    `courts.yaml`,
    `judge_aliases.csv`,
    `judges.csv`) and `tables.yaml`,
    which pins each table's version
    and sha256; their loader and
    validators in
    `src/judgemetrics/ingest/cook_sao/rules.py`
    with `RULE_VERSIONS`; the demo
    refit and the re-rendered
    `docs/VALIDATION.md` — with the
    tests that prove every value of
    the profile maps to a rule or to
    an explicit `unknown`, and that
    every judge string is resolved,
    held as ambiguous, or left
    unresolved for a stated reason.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Attribution principles, stated
      verbatim in the header of
      `attribution_rules.yaml` and
      followed by every rule:
      attribute a decision to the
      actor who legally made it
      under Illinois procedure and
      the SAO's documentation, never
      to whoever presided over the
      case; a prosecutor's nolle
      prosequi or SOL is
      `prosecutor` and
      `non_judicial`, and a reason
      that records a judicial ruling
      before it (a sustained motion
      to quash and suppress; no
      probable cause) is kept as a
      `judicial_ruling` flag beside
      the rule, never counted as a
      judicial dismissal; a bench
      finding or a dismissal by the
      court is `judge`; a verdict is
      `jury`; the conviction a
      guilty plea produces gets the
      actor and classification you
      decide and justify; a value
      that ends no case on the
      merits ("Superseded by
      Indictment", "Transferred -
      Misd Crt", "Mistrial
      Declared", "BFW", "Hold
      Pending Interlocutory") is
      `final: false` and never
      counts as a disposition; a
      post-judgment value is
      attributed to the court that
      entered it; whatever the
      documentation does not settle
      is `unknown` with the reason
      "not settled by the source's
      documentation". A rule never
      guesses to avoid `unknown`.
    </requirement>

    <requirement>
      `attribution_rules.yaml`
      (`version: 1`): one rule per
      (`charge_disposition`,
      `charge_disposition_reason`)
      pair in the profile, or a
      disposition with reason `*`
      where every reason shares the
      outcome — each with
      `disposition` (canonical),
      `final`, `actor_type`,
      `judicial_discretion_classification`,
      an optional `judicial_ruling`,
      and a `rationale` of one or
      two sentences citing the SAO
      documentation's URL or the
      value's plain legal meaning;
      rules for Intake's
      `felony_review_result` (the
      prosecutor's charging
      decision) and Diversion's
      `diversion_program` and
      `diversion_result`; the
      explicit fallback; and a
      `summary` recomputed by the
      tests from the profile's
      counts — rows and pairs whose
      actor is `unknown`, the share
      of disposition rows that are
      final, and the share
      attributed to each actor.
    </requirement>

    <requirement>
      `pretrial_rules.yaml`
      (`version: 1`): every bond
      type of the profile, initial
      and current, under each regime
      (before 2023-09-18; from
      2023-09-18, when the Pretrial
      Fairness Act ended cash bail),
      mapped to a `release_type`,
      `detained_flag`, whether the
      decision itself releases the
      person (only then is
      `release_at` set — never for a
      deposit or cash bond whose
      posting the source does not
      record), the
      electronic-monitoring
      condition, the actor (the
      bond-court judicial officer
      the source does not identify:
      `judge`, judge unknown) and
      its classification; a null
      bond drafts no decision and is
      counted, never imputed. State
      in the file what "released"
      means for this source.
    </requirement>

    <requirement>
      `sentence_rules.yaml`
      (`version: 1`): the canonical
      grain of a sentence (one per
      Sentencing row, or one per
      participant, date, and phase
      — decided from the profile's
      rows per charge version and
      participant and stated in the
      file), which sentences are
      current (a later phase
      supersedes an earlier one),
      and each `sentence_phase`
      (original;
      probation violation — a
      superseding sentence and a
      within-case `revocation`
      justice event at its date;
      amended or corrected,
      resentenced, remanded —
      superseding sentences;
      "Summary Charge Info" —
      ignored, with the reason);
      each `sentence_type` and
      `commitment_type` to sentence
      components; the exact
      conversion of
      `commitment_term` and
      `commitment_unit` to days
      (state each unit's day count);
      life, natural life, and death
      as terms without a finite day
      count, flagged; what
      `current_sentence` means.
    </requirement>

    <requirement>
      `offense_map.csv`: every
      `offense_category` and
      updated category in the
      profile → a canonical
      `offense_category`, and every
      class (Initiation `class`,
      Dispositions
      `disposition_charged_class`) →
      a canonical `severity`; an
      unmapped value is an error,
      never a catch-all.
      `courts.yaml` (`version: 1`):
      the jurisdiction (Cook County,
      Illinois; type `county`; state
      `IL`; FIPS `17031`), the
      Circuit Court of Cook County's
      six municipal districts as
      courts and one parent court
      for a case with no district,
      and every `court_name` and
      `court_facility` value mapped
      (PROMIS, Traffic, and null to
      the parent court, with the
      reason), the facility kept as
      an attribute.
    </requirement>

    <requirement>
      Judges. `judge_aliases.csv`:
      one row per distinct `judge`
      and `sentence_judge` string of
      the profile — the source
      string, its
      `normalize_person_name` form,
      the canonical judge key (a
      stable slug) or `ambiguous` or
      `unresolved`, the rule that
      resolved it (an exact
      normalized match; a spacing or
      case variant; a middle initial
      present or absent where no
      other judge shares the given
      and family names), and a
      reason for every non-exact
      row; an `ambiguous` row names
      its candidate keys; two
      strings whose given names
      conflict are never merged.
      `judges.csv`: one row per
      canonical key with the display
      name and the position as the
      source states it (vocabulary
      3's value for an unstated
      rank, never a guessed one).
    </requirement>

    <requirement>
      Vocabulary 3. Add to
      `case_vocabulary.yaml`
      exactly the canonical values
      the tables use — severities
      ordered most severe first with
      the synthetic values keeping
      their relative order,
      dispositions with their
      finality recorded where the
      engine can read it (Step 5
      wires the engine), event and
      decision types the timelines
      need, the position for an
      unstated rank, and the
      restricted kinds `race` and
      `gender` with the source's
      categories normalized, each
      also listing `unknown` for a
      blank source value (both join
      the pinned list of kinds that
      allow `unknown` in
      `tests/unit/test_vocabulary.py`)
      — and bump
      `version` to 3; update
      `synthetic/vocabulary.py` so
      the two stay equal without
      changing a single draw (the
      golden fixture stays byte
      for byte; if it does not,
      regenerate it by the
      documented procedure and say
      why). Record every change in
      `docs/DATA_MODEL.md`
      "Vocabularies" and fix that
      file's stale methodology
      version and revision list.
    </requirement>

    <requirement>
      Specification 2. If vocabulary
      3 adds a severity or an
      offense category, list it in
      `outcome_model.yaml`'s
      `lead_severity` and
      `lead_category` levels and set
      `version: 2` (`model_version`
      stays `expected-logit-v1`);
      refit the demo with `uv run
      poe compute-metrics`, run
      `models verify --refit` and
      `metrics verify`, re-render
      `docs/VALIDATION.md` with
      `uv run judgemetrics
      validation report`, and commit
      it with the change. A level
      with no rows must leave every
      published figure unchanged;
      if one moves, it is a
      data-semantics finding
      recorded in the PR body.
    </requirement>

    <requirement>
      The loader:
      `src/judgemetrics/ingest/cook_sao/rules.py`
      loads every table listed in
      `tables.yaml` (each entry a
      file, its `version`, and its
      sha256; a file whose digest
      differs is refused, so an
      edit must touch the version
      beside the digest), validates
      every value against vocabulary
      3 and every rule's fields at
      load (`RuleError` naming the
      file, key, and field), and
      exposes total, deterministic
      matchers (a disposition pair →
      its rule by the precedence
      exact pair, then the
      disposition with `*`, then the
      fallback; a bond type and
      date → its pretrial rule; a
      sentence row → its
      components; a category or
      class → its canonical values;
      a court name or facility → its
      court; a judge string → its
      key or status) and
      `RULE_VERSIONS`, the version of
      every table, which Step 4's
      `parser_version` embeds.
    </requirement>

    <requirement>
      Add tests:
      - `tests/unit/test_cook_sao_rules.py`
        (every pair, felony-review
        result, and diversion value
        in the profile matches a
        rule; the fallback is
        reachable only for a value
        the documentation leaves
        open; no rule maps a
        prosecutor disposition to
        `judge`; every non-final
        value is `final: false`; the
        `summary` equals its
        recomputation; a tampered
        table raises `RuleError`
        naming the field).
      - `tests/unit/test_cook_sao_tables.py`
        (every bond type, sentence
        phase, type, commitment
        type, unit, offense
        category, class, court name,
        and facility in the profile
        maps; the term conversion;
        no release is claimed for a
        deposit or cash bond).
      - `tests/unit/test_judge_aliases.py`
        (every judge string appears
        once; keys are unique;
        conflicting given names are
        never merged; every
        `ambiguous` row names its
        candidates; every key has a
        `judges.csv` row).
      - `tests/property/test_cook_sao_matchers.py`
        (Hypothesis over arbitrary
        strings: every matcher is
        total and deterministic and
        returns a vocabulary value).
      - The existing
        `test_vocabulary.py`,
        `test_outcome_model_spec.py`,
        `test_golden_fixture.py`, and
        the validation-report tests,
        updated for versions 3 and 2.
    </requirement>

    <requirement>
      Documentation and pins: the
      `cook_sao` register entry's
      "Actor attribution" and "Judge
      attribution" point to the
      tables and state the unknown
      share; `docs/ENTITY_RESOLUTION.md`
      gains "Judges by alias (Cook
      County)"; `docs/ARCHITECTURE.md`
      describes the tables and the
      loader; `AGENTS.md` records
      that a table change bumps its
      version and re-derives every
      row through the parser
      version. Every new Python and
      YAML file starts with its
      repo-relative path (`#`), and
      Markdown with `<!-- -->`; the
      CSV tables carry no comment
      line, like `us_states.csv`,
      since `tables.yaml` names and
      versions them.
    </requirement>
  </requirements>
</task>
```

### Step 3 acceptance criteria

- Every disposition and reason pair, felony-review result, diversion value, bond
  type, sentence value, offense category, class, court name, and facility in
  `data/reference/cook_sao/profile.yaml` maps to a versioned rule; the actors
  left `unknown` are exactly those the documentation does not settle, and the
  unknown share is recorded in `attribution_rules.yaml`'s summary, the PR body,
  and `docs/ROADMAP.md`.
- No rule attributes a prosecutor's or a jury's outcome to a judge; every
  procedural non-final is `final: false`; no deposit or cash bond claims a
  release (tests).
- Every judge string appears exactly once in `judge_aliases.csv`; every
  `ambiguous` and `unresolved` row carries its reason and candidates.
- Case vocabulary is version 3 and equals the generator's constants; the golden
  fixture is unchanged; specification version 2 lists every severity and
  offense level.
- `uv run judgemetrics validation report --check` passes against the committed
  `docs/VALIDATION.md`; the unit, property, and golden suites pass; CI is green.
- **Deployed & verified:** after the merge, `uv run poe compute-metrics` refit
  the demo models under specification version 2, `uv run judgemetrics models
  verify --refit` and `uv run judgemetrics metrics verify` exited 0, and
  `GET /api/v1/ready` reports `spec_version` 2.
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff — secret/PII scan clean, SAST clean,
  dependency audit clean, and the reference-data surface handles sensitive data
  per the project ROADMAP "Security & privacy strategy": the tables hold no case
  id, participant id, record, or restricted count, every table loads through a
  safe loader, and the new restricted kinds are covered by the snapshot refusal,
  the specification's exclusions, and the public contract's name scan.

---

## Step 4 — The Cook County Connector at Corpus Scale

**Status:** Not started

> **Goal:** Ingest the real corpus. The `cook_sao` connector moves to parser
> version `1+<RULE_VERSIONS>` and parses and normalizes the five datasets
> through Step 3's tables: `load_context` builds compact case indexes from every
> artifact (district, filing date, participants, charge versions, status), the
> connector implements `SupportsCoverage`, declares `revocation` its one
> observable outcome, and drafts each natural key exactly once — the
> jurisdiction, the six district courts and the parent court, judges by alias
> under the new identity system `cook_sao_judge` with service records derived
> from their attributed rows, cases numbered by the SAO case id, one person per
> case participant hashed in the source's own namespace, `defendant:<ordinal>`
> parties, race, gender, and the age band as restricted party attributes,
> charges with the disposing judge, events, the prosecutor's charging and
> diversion decisions, the bond decision under the regime's rule, sentences with
> terms in days, and the within-case revocation events. Migration
> `0011_cook_county_connector` adds the `cook_sao_judge` identity index and
> `charge.judge_id` and revokes the app role's read of `data_quality_issue`. The
> runner, the publisher, and entity resolution stop expanding one bind parameter
> per id and stop reading every case of a court, so a run of nearly 480,000
> cases fits the parameter ceiling and a measured memory budget; a judge string
> the alias table holds as ambiguous publishes its rows with no judge and one
> issue instead of rejecting them; the case-level checks read a parent case from
> the database; `judgemetrics ingest retire` removes a source's rows for a clean
> re-ingest and `seed` uses it (issue #36). The full corpus is ingested on the
> maintainer's machine, and a rerun creates nothing. This step lands the real
> rows; Step 5 gives them metric semantics and Step 6 computes them at scale.

**Branch:** `feature/phase05-step4-cook-county-connector`

**Deploys:** local database and the real corpus — the merge carries migration
`0011_cook_county_connector`, which the operator applies (`uv run poe migrate`);
then `uv run poe ingest-cook` re-derives the stored artifacts under the new
parser version (no download), and a second run creates and updates nothing.
Pipeline step 13 stays off for this source's full runs until Step 6 makes the
compute feasible: the `ingest-cook` task sets
`JUDGEMETRICS_METRICS_RECOMPUTE_ON_INGEST` to `false` in its poe `env` table, so
the command is the same on Windows and Ubuntu. The demo seed and the FJC data
are untouched. `/api/v1/ready` reports `0011`.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                                  |
| ------------ | ------------------------------------------------------ |
| Model        | Sonnet 5.5                                             |
| Backup       | GPT-6 Sol — Codex · Intelligence Extra High            |
| Platform     | Claude Code                                            |
| Effort       | Extra High (raised from Claude Code's default Medium)  |
| Thinking     | On                                                     |
| Conversation | **New**                                                |

**Model rationale:** This step implements a five-dataset real connector and
re-engineers the runner, the publisher, and entity resolution for a corpus a
hundred times the demo while holding every synthetic and FJC result byte for
byte, then runs, measures, and iterates on multi-hour ingests: PRIMARY
`coding`, SECONDARY `agentic` (long-running terminal execution and
measurement), High complexity with novel problem-solving and chain-of-thought
across many files (connector, runner, publisher, resolution, quality checks, a
migration, the CLI, the scrubber). The S-tier coders that are also S-tier in
agentic work are Sonnet 5.5, Opus 5.5, Fable 5.1, GPT-6 Sol, and GPT-6 Astra;
the coverage tie-break selects Sonnet 5.5 (S or A in all seven categories), and
the operator's `balanced` posture agrees — the cheaper of two close models
($10 against $20 output; AA Intelligence Index 56.0 against Opus 5.5's 57.6;
the deterministic scoring core, `roadmodel score --category coding --complexity
high --novel`, puts them 0.5 points apart). The Platform is Claude Code on the
$200 claude.ai Max subscription (weekly pool at `headroom`; Sonnet draws it
more slowly than Opus, which the `capped` posture values); switch the session
with `/model sonnet`. Claude Code opens Sonnet 5.5 at Effort `Medium`, and this
step raises it to `Extra High` for the novel-problem and cross-file conditions
— not `Max`: the golden, FJC, property, and parameter-ceiling tests catch a
wrong change. Thinking `On`. Backup: GPT-6 Sol on Codex (the $100 ChatGPT Pro
5x pool), S-tier in coding and agentic work and the widest-coverage S-tier
coder outside Anthropic, at Intelligence `Extra High`; not a `*-codex`
variant. Conversation is New per phase-boundary hygiene.

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
       feature/phase05-step4-cook-county-connector`
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
       roadmap's Phase 5
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 5` heading.

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
       finding → the versioned rule,
       vocabulary, registry, or
       specification entry, version
       bumped; a data-access
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
       step: tests that exercise the
       restricted path build their
       input in a temporary
       directory from the committed
       fixture with vocabulary
       values written into the
       restricted columns, and
       commit nothing of it; no
       pepper, hash, participant
       id, or restricted value
       appears in a test assertion
       message, a fixture, or a
       document; the full-ingest
       measurements in the PR body
       are counts and timings only.

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. In
       this step: every new lookup
       binds its ids as one typed
       array parameter or in bounded
       batches, never by string
       formatting; migration `0011`
       builds every statement from
       module constants behind
       `_role_exists()` and names
       every constraint through
       `op.f()`; the identity-system
       allow-list stays the only
       source of the expression
       index's key; `ingest retire`
       takes a source id the
       registry knows, refuses in
       production, and deletes by
       bound parameters.

    3. DEPENDENCY AUDIT. Any new or
       bumped dependency passes the
       audit (pip-audit / npm audit
       / osv-scanner); no
       known-vulnerable, yanked, or
       typo-squatted package. This
       step adds no dependency
       (peak memory is measured
       outside the process — the
       operating system's monitor on
       Windows, `/usr/bin/time -v`
       on Linux). If
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
       this step: a participant id
       reaches the database only as
       a peppered hash in the
       source's own namespace and
       never in a canonical column,
       an issue, a log line, or a
       `case_party.source_row_id`;
       race, gender, and the age
       band reach only
       `restricted.party_attribute`,
       written by the ingest role;
       the app role loses `SELECT`
       on `data_quality_issue`
       (migration and the scratch
       database's re-revoke block),
       and issue text names a
       dataset and a row ordinal,
       never a participant id or a
       restricted value; the log
       scrubber gains `race`,
       `gender`, and
       `age_at_incident` as whole
       key tokens (so `trace`
       survives); `ingest retire`
       writes an audit row.

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
    JudgeMetrics. Phase 5. Step 4:
    the Cook County connector at
    corpus scale.

    Current state (as of Phase 4,
    post-Phase-5 Step 3):

    - Step 1 shipped
      `src/judgemetrics/ingest/cook_sao/`
      at parser version `0` (fetch,
      metadata, headers; parse yields
      nothing), the streamed fetch
      and `put_file`,
      `data/reference/cook_sao/profile.yaml`,
      and the fixture
      `tests/fixtures/cook_sao/`
      (real rows; restricted and
      quasi-identifying columns
      blank; one judge with twelve
      sentenced and twelve disposed
      cases). The local raw lake
      holds the five full exports.
    - Step 3 shipped the tables
      under `data/reference/cook_sao/`
      with `tables.yaml`, their
      loader `ingest/cook_sao/rules.py`
      (`RULE_VERSIONS`, total
      matchers), case vocabulary 3
      (the restricted kinds `race`
      and `gender` included), and
      specification 2.
    - The runner's limits (this
      roadmap's Current State,
      "Ingest surface"): run-sized
      `in_()` lists in
      `runner.impacted_subjects`,
      `publish._source_row_ids` and
      the person lookups, and
      `entity_resolution/`
      (`deterministic.py`,
      `features.py`, `candidates.py`)
      fail past 65,535 ids;
      `lookup_cases` reads every
      case of the involved courts,
      twice; `merge.canonical_person_id`
      selects once per person; every
      draft is held in one list;
      dedup is first-wins; an
      unresolved judge key rejects
      the row; `missing_judge_on_decision`
      warns per decision;
      `case_number_duplicate` flags
      any key drafted twice; the
      case-level checks see only the
      run's cases; a
      `PartyAttributeDraft` needs
      its party in the run;
      `JUDGE_IDENTITY_SYSTEMS` is
      `{"fjc_nid",
      "synthetic_judge_code"}`.
    - Attribution: the disposition
      family of the registry
      attributes through
      `assigned_at_time` over
      `judge_assignment`, and
      `charge` carries no judge;
      Step 5 adds a
      `disposing_judge` gate that
      reads the `charge.judge_id`
      this step adds. The synthetic
      generator's disposing judge
      is the judge assigned at the
      disposition time
      (`synthetic/cases.py`
      `_judge_at`).
    - Security today:
      `data_quality_issue` is
      app-readable,
      `normalize_failed` stores
      exception text, and
      `describe_key` prints key
      parts; the stable participant
      hash is unqualified by source;
      `SENSITIVE_KEYS` (25 keys,
      pinned exactly by
      `tests/unit/test_logging.py`)
      matches substrings, so a bare
      `race` would redact `trace`;
      `tests/unit/test_restricted_readers.py`
      and `verify_phase04.py` check
      31 allow only
      `ingest/synthetic/` among
      connector directories;
      `verify_phase04.py` check 9
      reads the `SENSITIVE_KEYS`
      tuple for a subset of its
      names, so the new whole-token
      constant sits beside it and
      the tuple stays a column-0
      literal.
    - Head `0010`; `test_health.py`
      and `test_migrations.py` pin
      it. No retire command exists
      (issue #36);
      `tests/integration/conftest.py::purge_source`
      has the deletion order.

    Files to read (every file before
    drafting):
    - src/judgemetrics/ingest/cook_sao/
      (every file),
      data/reference/cook_sao/
      (every file),
      tests/fixtures/cook_sao/README.md.
    - src/judgemetrics/ingest/base.py,
      runner.py, publish.py,
      registry.py,
      src/judgemetrics/ingest/synthetic/
      (every file — the multi-file
      pattern).
    - src/judgemetrics/entity_resolution/
      (deterministic.py,
      features.py, candidates.py,
      merge.py, pipeline.py).
    - src/judgemetrics/quality/checks.py,
      src/judgemetrics/security/identifiers.py,
      src/judgemetrics/logging.py,
      src/judgemetrics/normalization/age_bands.py.
    - src/judgemetrics/db/models/
      (reference.py, cases.py,
      persons.py, restricted.py,
      __init__.py),
      alembic/versions/0008_restricted_schema.py
      and 0010_adjusted_observations.py,
      infra/docker/postgres/03-test-database.sql.
    - src/judgemetrics/cli.py
      (`ingest`, `seed`).
    - tests/integration/conftest.py,
      tests/integration/test_synthetic_ingest.py,
      test_migrations.py,
      test_health.py,
      tests/golden/test_public_contract.py,
      tests/golden/conftest.py,
      tests/unit/test_openapi.py
      (`RESTRICTED_PROPERTY_NAMES`),
      tests/unit/test_logging.py,
      tests/unit/test_restricted_readers.py,
      scripts/verify_phase04.py
      (checks 9 and 31).
    - docs/ARCHITECTURE.md
      ("Ingest", "Person hashing and
      resolution", "Restricted
      schema"), docs/DATA_MODEL.md,
      docs/ENTITY_RESOLUTION.md,
      AGENTS.md.
  </context>

  <goal>
    Ship migration `0011`; the
    connector at parser version
    `1+<RULE_VERSIONS>` with
    `load_context`,
    `SupportsCoverage`, and every
    draft kind; the bounded lookups
    and the measured memory budget;
    judge-less publication with one
    issue per string; parent-case
    checks across runs; the
    source-qualified participant
    hash; the scrubber's restricted
    tokens; `judgemetrics ingest
    retire` and `seed` using it; the
    full live ingest — with the
    tests that prove the fixture
    ingests idempotently, no
    restricted value or participant
    id escapes its boundary, and
    every synthetic and FJC result
    is unchanged.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Migration
      `0011_cook_county_connector`
      (reversible; `uv run alembic
      check` clean): the partial
      unique expression index
      `uq_judge_external_ids_cook_sao_judge`
      (with the model's constraint
      and a `JUDGE_IDENTITY_SYSTEMS`
      entry); `charge.judge_id`, a
      nullable, indexed foreign key
      to `judge` with `RESTRICT` —
      the judge who entered the
      charge's disposition, as the
      source records it, else null;
      `REVOKE SELECT ON
      data_quality_issue FROM
      judgemetrics_app` (restored on
      downgrade), with the same
      revoke added to
      `03-test-database.sql`'s
      re-revoke block and the grants
      test. Move the head pins to
      `0011`.
    </requirement>

    <requirement>
      Bounded lookups (all sources).
      Replace every run-sized
      `in_()` in the runner, the
      publisher, and entity
      resolution with one typed
      array parameter (`= ANY(...)`)
      or batches below the ceiling,
      through one shared helper;
      make `lookup_cases` read only
      the run's case keys; batch
      `canonical_person_id`. Hold
      every synthetic and FJC result
      byte for byte (the golden
      suite and the FJC fixture
      tests are the oracle).
    </requirement>

    <requirement>
      Memory and the one
      transaction. Keep the single
      publish transaction. Parse
      artifact by artifact into
      compact drafts, build
      `load_context`'s indexes in
      Polars, and release what the
      publish no longer needs; then
      measure the full corpus's wall
      time and peak resident memory
      for a fresh run, a rerun, and
      a `--force` rerun (peak memory
      read from the operating
      system's process monitor) and
      record them with a margin as
      the ingest budget in
      `docs/ARCHITECTURE.md` "Scale
      budgets" (Step 6 adds the
      engine's). If the machine
      cannot hold a run, fix the
      design (for example publishing
      dataset by dataset inside the
      transaction), never split the
      source into partial runs that
      publish half a case. Until
      Step 6 bounds pipeline step
      13, the `ingest-cook` poe task
      turns it off through its `env`
      table
      (`JUDGEMETRICS_METRICS_RECOMPUTE_ON_INGEST
      = "false"`), which poe applies
      on every platform; `README.md`
      says so.
    </requirement>

    <requirement>
      The connector (parser version
      `1+<RULE_VERSIONS>`; a unit
      test binds the two). Each
      natural key is drafted exactly
      once per run:
      - `load_context` (all five
        artifacts, changed or not):
        per case its district
        (`courts.yaml` over the
        disposition and sentencing
        court names, the rule for
        several stated, else the
        parent court), its filing
        date (the earliest
        `received_date`; one before
        the coverage start is kept
        and raises an anomaly
        issue), its participants and
        their ordinals, its charges
        and versions, and its status
        (closed when every charge
        has a final disposition).
      - `coverage_window()`:
        2011-01-01 to the end date
        Step 1 recorded;
        `observable_outcomes =
        ("revocation",)`.
      - Reference drafts: the
        jurisdiction and courts of
        `courts.yaml`; a
        `JudgeDraft` per canonical
        key the run references
        (identity `("cook_sao_judge",
        key)`, display name from
        `judges.csv`); one derived
        `JudgeServiceDraft` per judge
        and court, from the first to
        the last attributed
        disposition or sentence date,
        marked `derived` in its
        metadata.
      - Case drafts: `case_number` =
        the SAO case id, `case_type`
        `felony`; one `PersonDraft`
        per participant, its stable
        identity the hash of the
        source-qualified participant
        id (`security/identifiers.py`
        gains that form; the
        synthetic connector keeps its
        unqualified hashes, so no
        existing hash moves); a
        `defendant:<ordinal>` party;
        `PartyAttributeDraft`s for
        `race`, `gender` (vocabulary
        3 values; blank → `unknown`
        as the vocabulary allows) and
        `age_band` (from
        `age_at_incident`;
        `parse_age`'s message names
        no column); charges keyed
        `<charge_id>:<charge_version_id>`,
        prefixed with the party's
        ordinal if Step 1's profile
        shows a version spanning
        participants, with category
        and severity
        from `offense_map.csv` and
        the disposition, finality,
        actor, and `judge_key` (the
        disposing judge by alias)
        from the matching
        Dispositions row and
        `attribution_rules.yaml`;
        court events the tables
        define; the charging and
        diversion decisions
        (`prosecutor`); one bond
        decision per participant at
        initiation by
        `pretrial_rules.yaml`, never
        one per charge row; sentences
        at the grain
        `sentence_rules.yaml` states,
        their phase and currency in
        `sentence_components`; a
        `revocation` justice event at
        each probation-violation
        sentencing, related to its
        own case.
      - A judge string the alias
        table holds `ambiguous` or
        `unresolved` publishes its
        row with no judge and one
        `judge_unresolved` issue per
        string per run (with its row
        count); the alias table is
        this phase's judge review
        queue, and deciding a string
        is a table edit and a version
        bump.
    </requirement>

    <requirement>
      Quality checks. The case-level
      checks read a parent case that
      is not in the run from the
      database (bounded), so a run
      that re-parses only the
      Dispositions artifact is
      checked against its cases
      (Phase 4 carry-over item 2);
      `missing_judge_on_decision`
      skips a decision whose rule
      says the source never names
      its judicial officer (the bond
      decisions) and records one
      run-level count instead;
      `case_number_duplicate` fires
      only for true duplicates.
    </requirement>

    <requirement>
      Restricted data and logs. Add
      `ingest/cook_sao/` to the
      allowed directories of
      `tests/unit/test_restricted_readers.py`
      and relax `verify_phase04.py`
      check 31 in this PR to read
      that list (a line reader), so
      a registered connector
      directory never fails an
      earlier phase's required
      check. Add `race`, `gender`,
      and `age_at_incident` to the
      scrubber as a separate
      whole-token constant beside
      `SENSITIVE_KEYS` (a substring
      `race` would redact `trace`),
      pinned by `test_logging.py`
      like the other list;
      add `race` and `gender` as
      whole words to the restricted
      names of
      `tests/golden/conftest.py` and
      `tests/unit/test_openapi.py`.
      Every `NormalizationError` and
      issue description the
      connector raises names the
      dataset and the row's
      ordinal, never a participant
      id, a restricted value, or a
      raw row.
    </requirement>

    <requirement>
      Retirement (issue #36). Add
      `judgemetrics ingest retire
      SOURCE_ID [--yes]` (ingest
      role; refused in production;
      a registered source only): it
      deletes, in the dependency
      order `purge_source` uses, the
      source's observations, models,
      unreferenced snapshots,
      case-level rows, the persons it
      created, its source records,
      and the reference rows no other
      source's rows reference,
      keeping the `source` row, the
      run history, the raw lake, and
      the audit log; it writes one
      `ingest.retire` audit row with
      the counts and prints them.
      `purge_source` calls it, and
      `seed` retires the synthetic
      source before ingesting a
      regenerated dataset whose
      manifest recorded an older
      generator version. The PR
      closes issue #36.
    </requirement>

    <requirement>
      Add tests:
      - `tests/unit/test_cook_sao_normalize.py`
        (each dataset's fixture rows
        → the expected drafts; the
        rules applied; one draft per
        natural key; party keys;
        restricted drafts only as
        `PartyAttributeDraft`; the
        parser version embeds
        `RULE_VERSIONS`).
      - `tests/unit/test_identifiers.py`
        (the qualified form; the
        synthetic hashes unchanged)
        and `test_logging.py` (the
        tokens; `trace` survives).
      - `tests/integration/test_cook_sao_ingest.py`
        (the fixture twice: counts,
        then nothing created or
        updated; `--force` changes
        nothing; provenance to the
        fixture's bytes; the expected
        issue codes and counts; no
        fixture participant id in any
        app-readable text or JSONB
        column; the app role denied
        on `data_quality_issue` and
        the restricted schema).
      - `tests/integration/test_cook_sao_restricted.py`
        (a temporary copy of the
        fixture with vocabulary
        values in the restricted
        columns: the values land in
        `restricted.party_attribute`
        only; no log line, issue, or
        app-readable column carries
        one).
      - `tests/integration/test_bind_parameter_ceiling.py`
        (70,000-id lookups through
        the helper on the scratch
        database).
      - `tests/integration/test_parent_case_checks.py`
        and
        `tests/integration/test_ingest_retire.py`
        (retire then re-ingest equals
        a fresh ingest; other sources
        untouched; the production
        refusal; the audit row).
      - `tests/property/test_cook_sao_order.py`
        (permuting the rows of each
        artifact yields the same
        canonical rows).
      - The migration round trip
        through `0011`; the golden,
        FJC, and synthetic suites
        unchanged.
    </requirement>

    <requirement>
      Documentation:
      `docs/ARCHITECTURE.md` "Cook
      County connector" (the dataset
      → table map, the indexes) and
      "Scale budgets" (the ingest
      figures); `docs/DATA_MODEL.md`
      (`0011`, `charge.judge_id`,
      the identity system, the
      departures);
      `docs/DATA_SOURCES.md`
      "Ingested by";
      `docs/ENTITY_RESOLUTION.md`
      (judges by alias; the alias
      table as the review queue;
      persons as case
      participations); `README.md`
      (`ingest-cook`, whose task
      turns step 13 off until Step
      6); `AGENTS.md`. Filepath
      comment: every new file gets
      the repo-relative path as the
      first line.
    </requirement>
  </requirements>
</task>
```

### Step 4 acceptance criteria

- Migration `0011_cook_county_connector` upgrades and downgrades cleanly and
  `uv run alembic check` reports no drift; the app role cannot select from
  `data_quality_issue` or the restricted schema (tests).
- The fixture ingests with the expected counts and issues, a second run creates
  and updates nothing, and a `--force` run changes nothing; every case, person,
  party, and charge is drafted once; no fixture participant id appears in any
  app-readable column, issue, or log line; race, gender, and the age band appear
  only in `restricted.party_attribute`.
- Lookups of 70,000 ids succeed through the shared helper; the parent-case
  checks read the database; `ingest retire` followed by a re-ingest equals a
  fresh ingest and leaves other sources untouched; `seed` uses it and issue
  #36 is closed by the PR.
- The golden, FJC, synthetic, property, and unit suites pass unchanged;
  `verify_phase04.py --fast` passes with check 31 reading the shared allow-list;
  CI is green.
- **Deployed & verified:** after the merge and `uv run poe migrate`, `GET
  /api/v1/ready` reports `0011`; `uv run poe ingest-cook` (step 13 off through
  the task's `env` table) ingested the full corpus (rows per table, issues by
  code, wall time, and peak memory recorded in the PR body and
  `docs/ARCHITECTURE.md`); a second run created and updated nothing within the
  recorded rerun budget; `GET /api/v1/coverage` lists `cook_sao` with its cases,
  courts, judges, and coverage window.
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff — secret/PII scan clean, SAST clean,
  dependency audit clean, and the ingest surface handles sensitive data per the
  project ROADMAP "Security & privacy strategy": participant identifiers exist
  only as source-qualified peppered hashes, restricted attributes only in the
  restricted schema through the ingest role, issue text and logs carry neither,
  and the app role's read of `data_quality_issue` is revoked.

---

## Step 5 — Real-Data Metric Semantics, Calendar Periods, and Coverage Statistics

**Status:** Not started

> **Goal:** Give the real rows honest metric semantics. Registry version `3` and
> methodology `1.1` add the `disposing_judge` gate — the judge on
> `charge.judge_id` — to the disposition family (the synthetic connector fills
> it with the judge assigned at the disposition time, its generator's own rule,
> so every golden number stands); `NotAttributable`, under which a judge metric
> whose gate the source does not record (Cook County names no judge on a bond
> decision) publishes nothing for that source, never a zero; the vocabulary's
> finality, so a non-final disposition is never counted as disposed;
> calendar-year cohorts beside the whole coverage window for every descriptive
> judge and court metric; per-metric suppression thresholds decided against
> Cook County's measured cohorts with a written rationale; and a generated
> "Source limitations" section stating what each source can and cannot show (a
> Cook County "person" is a case participation; cross-case outcomes are not
> observable; a bond type is a decision, not a release). Migration
> `0012_real_data_semantics` adds `source.capabilities` (the attributed gates
> and the person-key scope each connector declares) and the
> `coverage_statistic` table, which every compute fills — the brief's six
> coverage statistics and the unknown-actor share per source, jurisdiction,
> and court — and `metrics verify` checks. Outcome-model specification version
> `3` declares per-source target availability, so Cook County fits no model and
> the report says why; `metrics compute --source` scopes publishing; issues #40
> and #42 are fixed. This step fixes the semantic shape; Step 6 computes it on
> the full corpus and Step 7 serves it.

**Branch:** `feature/phase05-step5-real-data-semantics`

**Deploys:** local database and analytics surface — the merge carries migration
`0012_real_data_semantics` (`uv run poe migrate`); `uv run poe seed`, with
pipeline step 13 off for that run (its snapshot would export the full Cook
County corpus inside the ingest transaction, and the compute below does the
work: `JUDGEMETRICS_METRICS_RECOMPUTE_ON_INGEST=false` in `.env`, removed
afterwards), re-derives the demo under the synthetic connector's new parser
version (it now fills `charge.judge_id`); `uv run judgemetrics metrics compute
--source synthetic` republishes the demo under registry 3 and methodology 1.1
with its calendar years and records every source's coverage statistics, Cook
County's from the full corpus. The full Cook County observations are Step 6's.
`/api/v1/ready` reports `0012` and methodology `1.1`.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                                  |
| ------------ | ------------------------------------------------------ |
| Model        | Opus 5.5                                               |
| Backup       | GPT-6 Sol — Codex · Intelligence Extra High            |
| Platform     | Claude Code                                            |
| Effort       | Extra High (raised from Claude Code's default Medium)  |
| Thinking     | On                                                     |
| Conversation | **New**                                                |

**Model rationale:** This step changes what the published numbers mean — a new
attribution gate that must leave every golden number unchanged, a rule that
turns an unrecorded attribution into no figure rather than a zero, per-year
cohorts that must agree with the whole window, thresholds chosen against real
cohorts, verified coverage statistics, and a specification that declares what a
source can support — across the registry, the frame, the engine, a migration,
the renderer, and the validation report: PRIMARY `coding`, SECONDARY
`knowledge` (statistical and attribution semantics), High complexity with
novel problem-solving and multi-step proof. Opus 5.5 is S-tier in coding and
S-tier in knowledge (AA Intelligence Index 57.6 at max); Fable 5.1 ties on both
rows and coverage and loses the output-price tie-breaker ($50 against $20);
Sonnet 5.5, A-tier in knowledge, drops at the SECONDARY rating. The Platform is
Claude Code on the $200 claude.ai Max subscription (weekly pool at
`headroom`); under the `capped` posture the ladder is final: Claude Code opens
Opus 5.5 at Effort `Medium`, and this step raises it to `Extra High` for the
novel-problem and multi-step-proof conditions — not `Max`, since the golden
suite, the period-consistency property, and `metrics verify` check every claim.
Thinking `On`. Backup: GPT-6 Sol on Codex (the $100 ChatGPT Pro 5x pool); no
other provider's S-tier coder is S-tier in knowledge, and GPT-6 Sol leads them
on coverage, at Intelligence `Extra High`; not a `*-codex` variant. Conversation
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
       feature/phase05-step5-real-data-semantics`
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
       roadmap's Phase 5
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 5` heading.

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
       finding → the versioned rule,
       vocabulary, registry, or
       specification entry, version
       bumped; a data-access
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
       step: the cohort-size
       measurements behind the
       thresholds are recorded as
       distributions (quantiles per
       metric, subject type, and
       period), never as a list of
       judges with counts; no real
       figure is committed except in
       those summaries.

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. In
       this step: migration `0012`
       builds its grants from module
       constants and names every
       constraint through `op.f()`;
       the new CLI options validate
       a source id against the
       registry before any query;
       the registry's new fields are
       enumerations checked at load.

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
       this step: `coverage_statistic`
       holds aggregates per source,
       jurisdiction, and court
       (numerator, denominator,
       share) — never a person id or
       a case list — and the app
       role may read it; no
       statistic is computed over a
       restricted attribute; the
       per-year cohorts keep the
       suppression rule, so a small
       year withholds its figures
       like any small cohort;
       `NotAttributable` and
       `NotObservable` publish
       nothing rather than a value a
       reader could take for a fact.

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
    JudgeMetrics. Phase 5. Step 5:
    real-data metric semantics,
    calendar periods, and coverage
    statistics.

    Current state (as of Phase 4,
    post-Phase-5 Step 4):

    - The local database holds the
      full Cook County corpus (Step
      4; no observation yet), the
      demo seed, and the FJC data.
      `charge.judge_id` (revision
      `0011`) is filled by the Cook
      County connector from the
      disposing judge and is null
      for every synthetic charge.
    - Registry version 2,
      methodology `1.0`, 36 metrics
      (this roadmap's Current State,
      "Metrics engine and registry
      surface"): the pretrial family
      gates on `deciding_judge` with
      actor and discretion filters
      that also apply to courts; the
      disposition family on
      `assigned_at_time`; the
      sentencing family on
      `sentencing_judge`;
      `eligible_cases` and
      `eligible_defendants` on
      `assigned_ever`. Every
      observation's period is the
      whole coverage window.
      `NotObservable` exists for
      outcomes; nothing exists for
      an attribution a source does
      not record, so a Cook County
      judge would get zero counts
      and suppressed shares for
      every pretrial metric. The
      engine's disposed-charge
      population is "disposition not
      null and not pending".
    - Vocabulary 3 (Step 3) records
      each disposition's finality;
      the Cook County bond decisions
      carry actor `judge` with no
      judge, per
      `pretrial_rules.yaml`.
    - Required checks that pin what
      this step touches:
      `verify_phase03.py` (the 33
      Phase 3 slugs present; exactly
      eight `known_limitations` —
      keep the brief's eight
      verbatim and put source
      limitations elsewhere) and
      `verify_phase04.py` checks 8
      (the synthetic connector's
      `parser_version` stays a
      quoted integer, at least 2),
      21 (adjusted thresholds
      exactly 30 — relax to a `>=`
      reading of the registry in
      this PR if you change it), and
      34 (`CHANGELOG` starts with
      Phase 4's entries: append
      `1.1`, never prepend).
    - `metrics verify` reports an
      observation `unverifiable`
      when the registry no longer
      carries its version, so a
      registry bump needs a full
      recompute of the sources it
      covers; a methodology bump
      republishes every observation
      (the demo took about three
      minutes at 1.0).
    - The validation report renders
      every source of the latest
      snapshot; CI checks the demo's
      committed render.
    - Issues #40 (`models fit`
      prints `fitted` twice:
      `cli.py` and
      `catalog.FitSummary`) and #42
      (a reused `metric_snapshot`
      keeps its first versions:
      `publish.upsert_snapshot`).

    Files to read (every file before
    drafting):
    - data/reference/metric_registry.yaml,
      src/judgemetrics/metrics/
      (registry.py, frame.py,
      snapshot.py, attribution.py,
      index_events.py, windows.py,
      censoring.py, compute.py,
      suppression.py, publish.py,
      verify.py, engine.py,
      methodology.py,
      provenance.py).
    - data/reference/outcome_model.yaml,
      src/judgemetrics/metrics/adjustment/
      (spec.py, catalog.py, fit.py,
      features.py),
      src/judgemetrics/validation/
      (inputs.py, report.py).
    - src/judgemetrics/ingest/base.py
      (`SourceInfo`),
      ingest/runner.py
      (`_upsert_source`),
      ingest/synthetic/normalize.py,
      ingest/cook_sao/connector.py,
      data/reference/cook_sao/
      (the pretrial and attribution
      rules).
    - src/judgemetrics/db/models/
      (metrics.py, provenance.py,
      outcome_models.py),
      alembic/versions/0010_adjusted_observations.py,
      0011_cook_county_connector.py.
    - src/judgemetrics/cli.py
      (`metrics`, `models`,
      `validation`).
    - tests/golden/ (every file),
      tests/property/test_frame_invariants.py,
      tests/unit/test_metric_registry.py,
      test_methodology_render.py,
      test_outcome_model_spec.py,
      scripts/verify_phase03.py and
      verify_phase04.py (the checks
      named above).
    - docs/METHODOLOGY.md,
      docs/ARCHITECTURE.md
      ("Metrics engine"),
      docs/DATA_MODEL.md, AGENTS.md.
  </context>

  <goal>
    Ship registry `3` and methodology
    `1.1` (the `disposing_judge`
    gate, `NotAttributable`,
    finality, calendar years,
    per-metric thresholds with their
    rationale, the "Source
    limitations" section); migration
    `0012` (`source.capabilities`,
    `coverage_statistic`); the
    coverage statistics computed on
    every compute and checked by
    `metrics verify`; specification
    `3` with per-source availability
    and `validation report
    --source`; `metrics compute
    --source` and `metrics
    coverage`; the fixes for #40 and
    #42 — with the tests that prove
    every golden number is
    unchanged, every year agrees
    with the whole window, and Cook
    County publishes nothing it
    cannot attribute or observe.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      The `disposing_judge` gate.
      Add it to the registry's gates
      and to
      `attribution.gate_rows`: a
      judge subject takes the
      charges whose `judge_id` is
      the subject; a court subject
      keeps `court_of_case`. The
      frame's `charges` gains
      `judge_id` (exported by the
      snapshot). A disposition index
      event of a (case, person) is
      attributed to the judge on the
      charge whose disposal sets the
      event's time (ties by the
      source's charge id).
      `compute.subjects_of` adds the
      judges on `charges.judge_id`,
      so a judge with dispositions
      and no sentence is a subject.
      Move the disposition family —
      the distribution, the judicial
      dismissal rate, the median
      days to disposition, and the
      four rates after a disposition
      — to the gate, bump each
      entry's `version`, and rewrite
      their eligibility prose. The
      synthetic connector fills
      `charge.judge_id` with the
      judge assigned at the charge's
      disposition time (the
      generator's own choice) under
      a new parser version, so every
      golden observation keeps its
      value (the golden suite is the
      proof; a moved number is a
      data-semantics finding).
    </requirement>

    <requirement>
      `NotAttributable`. Add
      `SourceInfo.capabilities` (the
      judge gates the source records
      and its person-key scope,
      `cross_case` or `case`), stored
      in `source.capabilities`
      (JSONB, written by the runner
      when it differs) and carried by
      the frame. The synthetic and
      FJC connectors declare theirs;
      the Cook County connector
      declares `disposing_judge` and
      `sentencing_judge` and the
      scope `case`. For a judge
      subject, a metric whose gate
      the source does not record
      yields `NotAttributable` — no
      observation, never a zero —
      reported beside
      `NotObservable` in the compute
      result and in `metrics compute
      --json`; court subjects are
      unaffected.
    </requirement>

    <requirement>
      Finality and populations. The
      engine's disposed-charge and
      disposed-case populations and
      the distribution's dimension
      read the vocabulary's
      finality: a non-final
      disposition is never disposed,
      and the distribution lists
      final values only. State in
      the methodology what the Cook
      County bond decisions mean for
      the pretrial counts and shares
      (a decision that permits
      release, not a release, per
      `pretrial_rules.yaml`), and
      that the court-level pretrial
      metrics count them while no
      judge does. State which
      sentences enter the sentencing
      family: each sentencing
      decision once, attributed to
      its own judge (an original
      sentence and a
      probation-violation
      resentencing are two
      decisions; an amended or
      corrected sentence replaces
      the one it corrects, which is
      then not counted). Declare
      which revocation metrics a
      Cook County
      probation-violation
      resentencing (Step 4's
      within-case `revocation`
      event) feeds: it revokes the
      probation the case's sentence
      imposed, so it counts toward
      the revocation rates after a
      sentence and after a
      disposition and never toward
      the rate after a pretrial
      release, whose outcome (a
      revoked release) the source
      does not record and which is
      `NotObservable` for it; record
      the mechanism (a revocation
      kind on the event or a
      per-index-kind declaration) in
      the registry and the
      methodology.
    </requirement>

    <requirement>
      Calendar periods. Every
      descriptive judge and court
      metric publishes, beside its
      whole-window observation, one
      observation per calendar year
      (UTC) of the population's
      anchor — the index time for
      the windowed kinds, the
      decision, disposition, or
      sentence time otherwise, the
      filing for the case counts —
      with `period_start` and
      `period_end` the year's first
      and last days; follow-up is
      still censored at the coverage
      end, and suppression applies
      per year. The adjusted kind
      stays whole-window (its
      cohorts are too small per
      year). Declare the periods in
      the registry, render them in
      the methodology, and keep the
      compare query's exact period
      match working for a year.
    </requirement>

    <requirement>
      Thresholds (Phase 4 carry-over
      item 1). Measure the cohort
      sizes per metric, subject type,
      and period on the full Cook
      County corpus and the demo
      (counts from the canonical
      tables; no member rows
      needed), choose each metric's
      threshold, and record the
      measured quantiles and the
      reason in the registry's
      suppression block; answer
      Phase 3 finding 3.5 (whether a
      suppressed share's eligible
      count may stay published) in
      the same place. Keep the
      brief's eight
      `known_limitations` verbatim
      and exactly eight.
    </requirement>

    <requirement>
      Coverage statistics. Migration
      `0012_real_data_semantics`
      (reversible, `op.f()` names,
      grants from constants: the app
      role `SELECT`, the ingest role
      DML) adds `source.capabilities`
      and `coverage_statistic`
      (snapshot, source, scope type
      `source`, `jurisdiction`, or
      `court`, scope id, statistic,
      numerator, denominator, share
      to six decimals, methodology
      version; unique per snapshot,
      source, scope, and statistic).
      `src/judgemetrics/metrics/coverage.py`
      computes, from the snapshot's
      frames on every compute and for
      every source the snapshot holds
      (whatever `--source` scopes),
      the brief's six statistics —
      cases with an identified judge,
      with a final disposition, with
      usable person resolution (and
      its scope), with adequate
      follow-up, with complete charge
      classification, and records
      with provenance — and the
      unknown-actor share of the
      decisions and final
      dispositions, each defined
      exactly in a new methodology
      section "Coverage statistics".
      `metrics verify` recomputes
      them and reports a tampered
      statistic by scope and name
      (exit 1). Add `judgemetrics
      metrics coverage [--source]
      [--json]` (app role) to print
      the latest.
    </requirement>

    <requirement>
      Specification 3. A target is
      fitted for a source only when
      the source records the
      target's population gate,
      observes its outcome, and —
      for the history features — has
      a `cross_case` person key;
      otherwise the catalogue
      records it unavailable with
      the reason (a new
      `outcome_model` status in
      `0012`). Set `version: 3`;
      revisit the events-per-column
      gate against the demo and
      record the decision; refit the
      demo (figures must not move).
      `validation report` gains
      `--source` (default: every
      source with a fitted model),
      so the committed demo document
      does not change when a real
      source sits in the same
      database; re-render it if the
      specification's text changes
      it. Open an issue for the
      architectural question this
      leaves: a judge-attributed
      sentencing or disposition
      target that Cook County could
      support, which needs planted
      effects and recovery first.
      Record in `docs/ROADMAP.md`
      that Phase 4 finding 2.6 (the
      bootstrap cluster key, which a
      source whose charge ids
      restart per case would collide
      on) does not arise for Cook
      County, which fits no model,
      and carry it to the first real
      source that does.
    </requirement>

    <requirement>
      Methodology `1.1`. In
      `metrics/methodology.py`
      generalize the "Observable
      outcomes" prose (it names the
      synthetic source today), add
      "Source limitations" rendered
      from each source's
      capabilities, observable
      outcomes, and declared notes,
      add "Coverage statistics" and
      the calendar periods, and
      append the `1.1` changelog
      entry; set the registry's
      `methodology_version` to `1.1`
      and `version` to 3; re-render
      `docs/METHODOLOGY.md` (`--check`
      passes). `GET /api/v1/metrics`
      keeps serving the same
      constants; the new sections
      reach the API and the web in
      Step 7.
    </requirement>

    <requirement>
      Commands and issues. `metrics
      compute --source SOURCE_ID`
      (repeatable, validated against
      the registered sources)
      computes and publishes
      observations over those
      sources' frames only; the
      coverage statistics are still
      computed for every source the
      snapshot holds. The snapshot
      still exports every source, as
      provenance requires: record
      that export's wall time and
      peak memory with the full
      corpus present, and if it
      cannot complete on the
      maintainer's machine, bring
      Step 6's streamed export
      forward into this step rather
      than scoping the snapshot. Fix
      #40 (one `fitted` line) and
      #42 (a compute that reuses a
      snapshot records the registry
      and methodology versions it
      publishes under, so `/ready`
      and `/coverage` report the
      current ones); the PR closes
      both.
    </requirement>

    <requirement>
      Add tests:
      - `tests/unit/test_metric_registry.py`
        (version 3; the gate; the
        periods; every threshold with
        a rationale; eight
        limitations verbatim; the 33
        Phase 3 slugs present).
      - `tests/unit/test_attribution.py`
        (`disposing_judge` over a
        hand-built frame;
        `NotAttributable` for a
        judge and not for a court; a
        judge with dispositions and
        no sentence is a subject).
      - `tests/unit/test_coverage_statistics.py`
        (each definition over a
        hand-built frame, the unknown
        share, the scopes).
      - `tests/property/test_period_consistency.py`
        (per-year counts, share
        numerators and denominators,
        and fixed-window followed and
        counted members sum to the
        whole window's; Kaplan-Meier
        and medians excluded).
      - `tests/golden/test_golden_metrics.py`
        unchanged in value, with the
        gate switched.
      - `tests/integration/test_cook_sao_metrics.py`
        (the fixture: the sentencing
        and disposition families for
        its judge, one observation
        unsuppressed; the court bond
        counts; `NotObservable` for
        the cross-case outcomes;
        `NotAttributable` for the
        judge pretrial metrics;
        revocation after a sentence;
        the coverage statistics;
        `metrics verify` exit 0, then
        1 after a tampered statistic).
      - The migration round trip
        through `0012`; the
        methodology render; the spec
        and validation tests for
        version 3 and `--source`.
    </requirement>

    <requirement>
      Documentation:
      `docs/ARCHITECTURE.md`
      ("Metrics engine": the gate,
      `NotAttributable`, finality,
      periods, coverage statistics,
      `--source`),
      `docs/DATA_MODEL.md` (`0012`,
      registry 3, `coverage_statistic`,
      `source.capabilities`),
      `docs/VALIDATION.md` and
      `docs/METHODOLOGY.md`
      re-rendered, `AGENTS.md`.
      Filepath comment: every new
      file gets the repo-relative
      path as the first line.
    </requirement>
  </requirements>
</task>
```

### Step 5 acceptance criteria

- Registry version 3 and methodology `1.1` are published; the disposition
  family uses `disposing_judge`; every golden observation keeps its value; the
  brief's eight limitations are unchanged and the 33 Phase 3 slugs remain.
- A Cook County judge receives no observation for a metric whose gate the
  source does not record, and no source receives one for an outcome it does
  not observe; no non-final disposition is counted as disposed (tests).
- Calendar-year observations exist for every descriptive judge and court metric
  and agree with the whole window (property test); each metric's threshold
  carries its measured cohort quantiles and rationale.
- `coverage_statistic` holds the six statistics and the unknown-actor share per
  source, jurisdiction, and court; `metrics verify` checks them and fails on a
  tampered one (test); `judgemetrics metrics coverage` prints them.
- Specification version 3 records Cook County's targets as unavailable with
  their reasons, the demo's figures are unchanged, `validation report --check`
  passes, and the follow-up issue for a real-data target is open.
- Issues #40 and #42 are closed by the PR; the unit, property, golden, and
  integration suites pass; CI is green.
- **Deployed & verified:** after the merge, `uv run poe migrate`
  (`/api/v1/ready` reports `0012` and methodology `1.1`), `uv run poe seed`
  (step 13 off), and `uv run judgemetrics metrics compute --source synthetic`
  completed (wall time and peak memory recorded, the snapshot's export of every
  source included); `uv run judgemetrics metrics verify` exits 0; `uv run
  judgemetrics metrics coverage --source cook_sao` prints the full corpus's
  statistics and unknown-actor share, recorded in the PR body and
  `docs/ROADMAP.md`.
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff — secret/PII scan clean, SAST clean,
  dependency audit clean, and the analytics surface handles sensitive data per
  the project ROADMAP "Security & privacy strategy": coverage statistics are
  aggregates with no person or case list, none is computed over a restricted
  attribute, and the per-year cohorts keep the suppression rule.

---

## Step 6 — The Metrics Engine at Corpus Scale

**Status:** Not started

> **Goal:** Make the full Cook County compute, its rerun, `metrics verify`, the
> provenance trace, and pipeline step 13 run on the maintainer's machine within
> recorded budgets, without moving a single published figure. Migration
> `0013_member_storage` stores each provenance member once per observation
> family — one row per member of a (definition, subject, source, snapshot)
> family, carrying the windows in which it is counted and followed and the
> calendar year it falls in — instead of once per window and period, written
> with PostgreSQL `COPY`, with the existing rows converted in both directions;
> `censoring.product_limit` becomes a vectorized estimator equal to the
> reference implementation to six decimals; the snapshot export streams each
> table to Parquet in bounded batches with the same content hash;
> `_derived_outcomes` and `_family` become joins; `metrics verify` streams
> family by family; the trace checks completeness in SQL and pages member ids
> (CLI `--limit`, API `limit` and `offset`); step 13's recompute is bounded or,
> beyond a declared size, deferred to the full compute with the reason recorded.
> The golden and demo observations, their member multisets, and their
> provenance chains are the oracle, and the full corpus is computed, rerun,
> verified, and traced. This step makes Step 5's semantics feasible at real
> scale; Step 7 serves them.

**Branch:** `feature/phase05-step6-engine-scale`

**Deploys:** local database and the full analytics surface — the merge carries
migration `0013_member_storage` (`uv run poe migrate` converts the existing
member rows); then `uv run poe compute-metrics` computes every source,
Cook County's full corpus included, a second run publishes nothing, `uv run
judgemetrics metrics verify` passes, and a random Cook County observation
traces complete. `/api/v1/ready` reports `0013` and the new snapshot.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                                  |
| ------------ | ------------------------------------------------------ |
| Model        | Sonnet 5.5                                             |
| Backup       | GPT-6 Sol — Codex · Intelligence Extra High            |
| Platform     | Claude Code                                            |
| Effort       | Extra High (raised from Claude Code's default Medium)  |
| Thinking     | On                                                     |
| Conversation | **New**                                                |

**Model rationale:** This is performance engineering under an equivalence
proof — a storage redesign that must reproduce every observation's member
multiset, a vectorized estimator that must equal the reference to six
decimals, a streamed export with an unchanged content hash, a set-based trace —
followed by multi-hour full-corpus runs measured and iterated on: PRIMARY
`coding`, SECONDARY `agentic`, High complexity with novel problem-solving and
chain-of-thought across the snapshot, compute, publish, verify, provenance, the
API route, a migration, and the runner. As in Step 4, the S-tier coders that are
S-tier in agentic work are Sonnet 5.5, Opus 5.5, Fable 5.1, GPT-6 Sol, and GPT-6
Astra; the coverage tie-break selects Sonnet 5.5 and the `balanced` posture
agrees (half Opus 5.5's output price; 0.5 points behind it on `roadmodel score
--category coding --complexity high --novel`). The Platform is Claude Code on
the $200 claude.ai Max subscription (weekly pool at `headroom`); switch with
`/model sonnet`. Claude Code opens Sonnet 5.5 at Effort `Medium`, and this step
raises it to `Extra High` for the novel-problem and cross-file conditions — not
`Max`: the golden suite, the equivalence properties, and `metrics verify` catch
a wrong change. Thinking `On`. Backup: GPT-6 Sol on Codex (the $100 ChatGPT Pro
5x pool), S-tier in coding and agentic work, at Intelligence `Extra High`; not a
`*-codex` variant. Conversation is New per phase-boundary hygiene.

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
       feature/phase05-step6-engine-scale`
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
       roadmap's Phase 5
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 5` heading.

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
       finding → the versioned rule,
       vocabulary, registry, or
       specification entry, version
       bumped; a data-access
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
       is complete. You can now move
       on to Step 7." That line is
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
       Step 7.
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
       step: the budgets and
       measurements committed to
       `docs/ARCHITECTURE.md` and
       the PR body are timings,
       sizes, and counts only; no
       snapshot, Parquet file, or
       member dump is staged
       (`data/snapshots/` stays
       git-ignored).

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. In
       this step: `COPY` streams
       rows through psycopg's copy
       API with typed columns, never
       a statement built from data;
       the streamed export keeps the
       snapshot hash validation and
       the never-overwrite rule;
       DuckDB stays read-only with
       no extension; the trace's
       paging parameters are bounded
       integers validated by the
       route's `StrictQuery`.

    3. DEPENDENCY AUDIT. Any new or
       bumped dependency passes the
       audit (pip-audit / npm audit
       / osv-scanner); no
       known-vulnerable, yanked, or
       typo-squatted package. This
       step adds no dependency
       (psycopg's `COPY`, Polars,
       and NumPy are locked). If one
       is added, it passes `pip-audit
       --strict --require-hashes`
       over the `uv.lock` export
       (`scripts/audit_deps.py`).

    4. SENSITIVE-DATA REVIEW.
       Whatever this step touches
       stays least-privilege,
       encrypted in transit + at
       rest, and out of logs and
       client bundles. If the step
       adds a data path, name how
       PII/secrets are protected. In
       this step: member rows still
       hold entity ids of public
       rows only (decisions,
       charges, cases, sentences,
       events) and never a person id;
       the app role's effective
       access to the member storage
       is what it was; the snapshot
       still refuses the restricted
       schema by schema; a paged
       trace never returns more than
       the requested page, so one
       request cannot pull a whole
       court's case list.

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
    JudgeMetrics. Phase 5. Step 6:
    the metrics engine at corpus
    scale.

    Current state (as of Phase 4,
    post-Phase-5 Step 5):

    - The local database holds the
      full Cook County corpus with
      no observation, the demo seed
      under registry 3 and
      methodology 1.1 with calendar
      years, and every source's
      coverage statistics (Step 5).
    - Scale limits (this roadmap's
      Current State): the snapshot
      exports the whole database
      through `session.execute(...).all()`
      tuples; `_derived_outcomes`
      and `_family` loop over
      persons in Python;
      `censoring.product_limit` is
      O(event times × members) per
      window and subject;
      `publish.py` writes one member
      row per member per observation
      (now per window AND per
      calendar year) in statements
      of 500, and `_revive` deletes
      a revived row's members
      against its docstring;
      `verify.py` loads every
      member; `provenance.render`
      and the provenance route
      return every case id of a
      member group. The demo's
      first compute wrote 822,777
      members for 3,426
      observations before Step 5's
      calendar years.
    - Step 13 computes the
      descriptive kinds of the
      impacted subjects inside the
      ingest transaction; Step 4's
      `ingest-cook` task turns it
      off (its poe `env` table) for
      Cook County's full runs.
    - Revision head `0012`;
      `metric_observation_member`
      (revision `0005`) has a bigint
      id, `member_kind` (decision,
      charge, court_case, sentence,
      court_event, justice_event),
      `member_id`, `counted`,
      `followed`.
    - Query budgets
      (`tests/integration/test_query_counts.py`):
      provenance three statements in
      practice (six allowed), subject
      metrics two, compare one.
    - Required checks that pin what
      this step touches:
      `verify_phase04.py` checks 24
      (`publish.VERIFIED_COLUMNS`
      stays a column-0 tuple literal
      holding the adjusted columns),
      25 (`runner.recompute_metrics`
      keeps
      `kinds=DESCRIPTIVE_KINDS`), and
      28 (`provenance.py` keeps the
      `outcome model
      {model.content_hash}` line);
      relax a check to the subset
      pattern in this PR if a change
      must move what it pins.

    Files to read (every file before
    drafting):
    - src/judgemetrics/metrics/
      (snapshot.py, frame.py,
      compute.py, censoring.py,
      publish.py, verify.py,
      engine.py, provenance.py,
      coverage.py).
    - src/judgemetrics/ingest/runner.py
      (`impacted_subjects`,
      `recompute_metrics`).
    - src/judgemetrics/db/models/metrics.py,
      alembic/versions/0005_metric_registry_and_snapshots.py,
      0012_real_data_semantics.py.
    - src/judgemetrics/api/routes/metrics.py,
      services/metrics.py,
      repositories/metrics.py,
      schemas/metrics.py
      (the provenance route).
    - tests/golden/ (every file),
      tests/integration/test_query_counts.py,
      tests/property/test_frame_invariants.py,
      tests/unit/test_openapi.py.
    - docs/ARCHITECTURE.md
      ("Metrics engine", "The
      step-13 exception"),
      docs/PROVENANCE.md, AGENTS.md.
  </context>

  <goal>
    Ship migration `0013` and the
    member families with window and
    period flags written by `COPY`;
    the vectorized Kaplan-Meier; the
    streamed export; the vectorized
    derived outcomes and families;
    the streaming verify; the
    set-based, paged trace and its
    route parameters; the bounded or
    declared step 13; the budgets in
    `docs/ARCHITECTURE.md`; the full
    Cook County compute — with the
    tests that prove every
    observation, member multiset,
    snapshot hash, and provenance
    chain of the golden and demo
    computes is unchanged.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Member storage. Migration
      `0013_member_storage`
      (reversible, `op.f()` names,
      grants that keep the app and
      ingest roles' effective
      access) replaces
      per-observation member rows
      with one row per member of an
      observation family — the
      observations of one
      definition, subject, source,
      and snapshot across its
      windows, dimensions, and
      periods — carrying the windows
      in which the member is counted
      and followed, the dimension
      value it belongs to or is
      counted in (a distribution's
      members), its period anchor,
      and a multiplicity (an
      observation's member multiset
      can hold a member more than
      once — `eligible_defendants`
      lists a case once per
      defendant — and the family
      keeps that count without a
      person id), so every
      observation's member multiset
      is a filter of its family. It
      converts the existing rows
      both ways. `publish.py` writes
      members with `COPY`, keeps
      supersession and revival exact
      (a revived observation keeps
      its members — fix `_revive`),
      and never deletes history; the
      provenance chain rule (every
      member id in the snapshot's
      tables) is checked in SQL
      before any write. Choose the
      exact layout and record it in
      `docs/DATA_MODEL.md`.
    </requirement>

    <requirement>
      Compute. Replace
      `censoring.product_limit` with
      a vectorized estimator (events
      before censorings at ties; `se
      = 0` when every member at risk
      fails; Greenwood intervals
      rounded to six decimals at the
      boundary) and keep the old one
      in the tests as the oracle;
      turn `snapshot._derived_outcomes`
      and `_family` into joins; stop
      refiltering the whole frame per
      subject and definition where a
      group-by does the same work.
      Every golden and demo figure is
      unchanged.
    </requirement>

    <requirement>
      Export, verify, and trace. The
      snapshot export streams each
      table from PostgreSQL (a
      server-side cursor or `COPY
      TO`) into Parquet in bounded
      batches; the content hash, the
      row order, and the bytes for
      the same data are unchanged
      (the golden snapshot hash is
      the proof). `metrics verify`
      recomputes and compares family
      by family with bounded memory
      and reports exactly what it
      reported before. The trace
      checks completeness with set
      operations in SQL, never a
      Python loop over members,
      returns member counts per group
      with one page of ids, and takes
      `limit` (default 100, at most
      1,000) and `offset`; the CLI
      gains `--limit`; the provenance
      route gains the two parameters
      in its `StrictQuery` (update
      `docs/openapi.json`,
      `web/lib/api/schema.d.ts`, and
      the pinned allow-lists); its
      statement budget stays three.
    </requirement>

    <requirement>
      Step 13. Measure a
      fixture-sized change to the
      full corpus (one re-parsed
      artifact of the fixture's
      cases) with recompute on: if
      it fits the budget, keep it;
      beyond a declared size of the
      impacted set, defer the
      recompute to the next full
      `metrics compute`, record the
      deferral and its reason in the
      run, and document it beside
      the existing step-13 exception
      for the adjusted kind (ROADMAP
      §5 "Performance rules").
      Remove the `env` entry Step 4
      gave the `ingest-cook` task
      once the declared rule covers
      a full Cook County run, and
      say so in `README.md`.
    </requirement>

    <requirement>
      Budgets and the full run. On
      the maintainer's machine, run
      `uv run poe compute-metrics`
      over every source: record wall
      time, peak resident memory,
      observations, member rows, and
      the database's growth for the
      first run, the rerun (which
      publishes nothing), `metrics
      verify`, and a trace of a
      random Cook County observation;
      write them with a margin as the
      budgets in
      `docs/ARCHITECTURE.md` ("Scale
      budgets"), beside Step 4's.
    </requirement>

    <requirement>
      Add tests:
      - `tests/unit/test_censoring_vectorized.py`
        and
        `tests/property/test_km_equivalence.py`
        (the vectorized estimator
        equals the reference on
        Hypothesis-drawn cohorts with
        ties, all-censored, and
        all-failing cases).
      - `tests/integration/test_member_storage.py`
        (each golden observation's
        member multiset equals the
        pre-migration one; the
        migration converts both ways;
        a revived observation keeps
        its members).
      - `tests/unit/test_snapshot_export.py`
        (the streamed export's hash
        and bytes equal the reference
        on the golden data).
      - `tests/golden/test_golden_provenance.py`
        extended (paged traces; the
        counts; completeness unchanged;
        CLI and endpoint agree).
      - `tests/integration/test_query_counts.py`
        (provenance still three).
      - The golden, property, and
        Cook County fixture suites
        unchanged in value.
    </requirement>

    <requirement>
      Documentation:
      `docs/ARCHITECTURE.md`
      ("Metrics engine", "Scale
      budgets", the step-13 rule),
      `docs/DATA_MODEL.md` (`0013`,
      the member layout),
      `docs/PROVENANCE.md` (paged
      members), `docs/API.md` (the
      provenance parameters),
      `AGENTS.md`. Filepath comment:
      every new file gets the
      repo-relative path as the first
      line.
    </requirement>
  </requirements>
</task>
```

### Step 6 acceptance criteria

- Migration `0013_member_storage` converts the member rows both ways and `uv run
  alembic check` reports no drift; every golden and demo observation, member
  multiset, snapshot hash, and provenance chain is unchanged (tests).
- The vectorized Kaplan-Meier equals the reference to six decimals (property
  test); `metrics verify` and the trace run with bounded memory; the trace pages
  member ids and stays at three statements.
- Step 13 either fits the budget for a fixture-sized change to the full corpus
  or defers beyond the declared size with the reason recorded and documented.
- The unit, property, golden, and integration suites pass; `docs/openapi.json`
  and `web/lib/api/schema.d.ts` are regenerated; CI is green.
- **Deployed & verified:** after the merge and `uv run poe migrate`
  (`GET /api/v1/ready` reports `0013`), `uv run poe compute-metrics` computed
  the full corpus with Cook County observations published, a second run
  published nothing, `uv run judgemetrics metrics verify` exited 0, and `uv run
  judgemetrics provenance trace <a random Cook County observation> --limit 20`
  printed `complete: yes` — each with its wall time and peak memory recorded in
  `docs/ARCHITECTURE.md`.
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff — secret/PII scan clean, SAST clean,
  dependency audit clean, and the analytics surface handles sensitive data per
  the project ROADMAP "Security & privacy strategy": member rows hold no person
  id, the app role's access is unchanged in effect, `COPY` and the export bind
  no data into SQL, and a trace response is bounded by its page.

---

## Step 7 — Public Surfaces for the First Real Source

**Status:** Not started

> **Goal:** Put the real corpus on every public surface with its coverage, its
> limits, and its end date. The API serves `/api/v1/coverage` v2 — per source
> the coverage statistics and the unknown-actor share of the latest snapshot,
> the declared capabilities, the observable and not-observable outcomes, the
> gates the source does not attribute, and the coverage window, plus a
> per-jurisdiction breakdown — and `/jurisdictions/{id}` gains its coverage
> block; every `Provenance` block carries its source's coverage window, so the
> corpus end date reaches every response that cites a source; `/courts` gains
> `q`; `/judges/{id}/cases` gains a `cohort` filter (pretrial decision,
> disposition, sentence, assignment) that also lists a judge's cases where the
> source records no assignment; `/metrics/compare` exposes the cohort's periods
> and flags a judge whose service spans several courts; `GET /api/v1/metrics`
> serves Step 5's new methodology sections. The web renders all of it — the
> coverage page's statistics and limitations, the jurisdiction page's
> breakdown, the compare page's year selector and court search, real judges'
> pages (a "not recorded by this source" state for an unattributable metric,
> the corpus end date, cohort links), real cases' pages (a bond set by a
> judicial officer the source does not name, a prosecutor's dismissal, a
> probation-violation resentencing), paged provenance, and a `cook_sao` source
> link — with `web/tests/e2e/real-data.spec.ts` over the committed fixture,
> which CI's `e2e` job now ingests. This step lands the public face; Step 8
> verifies the phase.

**Branch:** `feature/phase05-step7-real-data-surfaces`

**Deploys:** local API and web app (`uv run poe dev-api`, and `pnpm dev` in
`web/` on Windows) serving the full Cook County corpus beside the demo — no
migration; `docs/openapi.json` and `web/lib/api/schema.d.ts` regenerated in the
PR; CI's `e2e` job ingests `tests/fixtures/cook_sao` from the merge on.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                                  |
| ------------ | ------------------------------------------------------ |
| Model        | Sonnet 5.5                                             |
| Backup       | GPT-6 Sol — Codex · Intelligence High                  |
| Platform     | Claude Code                                            |
| Effort       | High (raised from Claude Code's default Medium)        |
| Thinking     | On                                                     |
| Conversation | **New**                                                |

**Model rationale:** This is multi-surface coding across schemas, services,
repositories, routes, the OpenAPI snapshot, the generated client, components,
pages, Vitest, Playwright, and the CI job, under the presentation rules every
earlier phase enforces mechanically: PRIMARY `coding`, SECONDARY `agentic`
(driving the browser suites and the e2e job), High complexity without novel
problem-solving — the patterns are Phase 3's and Phase 4's. The S-tier coders
that are S-tier in agentic work are Sonnet 5.5, Opus 5.5, Fable 5.1, GPT-6 Sol,
and GPT-6 Astra; the coverage tie-break selects Sonnet 5.5, and the `balanced`
posture and the deterministic scoring core (`roadmodel score --category coding
--complexity high`: Sonnet 5.5 80.4, Opus 5.5 79.6) agree. The Platform is
Claude Code on the $200 claude.ai Max subscription (weekly pool at
`headroom`); switch with `/model sonnet`. Claude Code opens Sonnet 5.5 at
Effort `Medium`, and this step raises it to `High` for the High-complexity
rung; not `Extra High`, since no novel problem or multi-step proof is involved
and the contract, query-count, and browser tests catch a slip. Thinking `On`.
Backup: GPT-6 Sol on Codex (the $100 ChatGPT Pro 5x pool), S-tier in coding and
agentic work, at Intelligence `High`; not a `*-codex` variant. Conversation is
New per phase-boundary hygiene.

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
       feature/phase05-step7-real-data-surfaces`
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
       roadmap's Phase 5
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 5` heading.

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
       finding → the versioned rule,
       vocabulary, registry, or
       specification entry, version
       bumped; a data-access
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
       line — verbatim shape "Step 7
       is complete. You can now move
       on to Step 8." That line is
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
       Step 8.
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
       step: the screenshots under
       `docs/screenshots/phase05-step7/`
       show judges (public
       officials), courts, aggregate
       figures, and case pages that
       carry public keys only —
       never a participant id or a
       restricted value — and every
       screenshot is reviewed before
       it is committed; the CI
       ingest of the fixture keeps
       the masked throwaway pepper
       of the `e2e` job.

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. In
       this step: `q`, `cohort`, and
       the period parameters are
       validated by `StrictQuery`
       and bound, never formatted
       into SQL (the courts search
       uses the trigram pattern of
       `/search`); every page
       validates its query string
       before any fetch;
       `eslint-plugin-security` runs
       with `--max-warnings 0`.

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
       this step: every new field is
       an aggregate, a source
       declaration, or a date; the
       public contract runs over the
       Cook County fixture and
       finds no participant id, no
       restricted name (`race`,
       `gender`, `age_band` as whole
       words), and no restricted
       value in any response; the
       cases cohort filter lists
       public case summaries only;
       the production bundle scan
       finds no `JUDGEMETRICS_`
       value.

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
    JudgeMetrics. Phase 5. Step 7:
    public surfaces for the first
    real source.

    Current state (as of Phase 4,
    post-Phase-5 Step 6):

    - The local database holds the
      full Cook County corpus with
      its observations (registry 3,
      methodology 1.1, calendar
      years, `NotAttributable` and
      `NotObservable` records), its
      coverage statistics, and paged
      provenance (Step 6), beside
      the demo seed and the FJC
      data.
    - API (this roadmap's Current
      State, "API and web surface"):
      21 paths and 19 `StrictQuery`
      routes pinned exactly by
      `tests/unit/test_openapi.py`;
      `/coverage` takes no parameter
      and its 16 source keys and 5
      top-level keys are pinned by
      `test_api_coverage.py`; the
      coverage query is three
      statements; no response
      carries the corpus end date
      except `/coverage`,
      `Observation.coverage`, and
      the trace's source; `/courts`
      has no `q`; `/judges/{id}/cases`
      filters by filing dates,
      status, and case type only and
      finds cases through
      assignments; `/metrics/compare`
      already matches
      `period_start`/`period_end`
      exactly.
    - Web: `web/lib/links.ts`
      `SOURCES` knows `fjc` and
      `synthetic`; FJC-only wording
      on the judge, court, and
      jurisdiction pages; six "Phase
      5" promises remain under
      `web/app/` (the home page's
      case tile, the court page, the
      coverage page's note —
      asserted by
      `web/tests/e2e/smoke.spec.ts`
      — two on the jurisdiction
      page, and a comment on the
      compare page); the
      jurisdiction page infers its
      sources
      (`web/lib/jurisdictions.ts`)
      and carries a "Trends … Phase
      5" placeholder (trends belong
      to Phase 7 §7.4); the compare
      page lists two pages of courts
      and has no period control;
      `MetricStat` and
      `AdjustedStat` are the only
      number renderers; the judge
      page renders exactly one
      association statement
      (`verify_phase04.py` check
      42).
    - CI `e2e` (`.github/workflows/ci.yml`):
      the FJC fixture, `seed --out
      data/synthetic/ci`, `metrics
      compute`, `models fit`,
      `models verify`, `validation
      report --check --truth
      data/synthetic/ci`, then the
      API, the production web
      build, and Playwright; the
      hygiene test pins the command
      list and order, and
      `verify_phase03.py` check 42
      and `verify_phase04.py` checks
      20 and 36 pin parts of it.
      Step 5's `validation report
      --source` default keeps the
      committed demo render valid
      with a real source present.
    - `README.md`'s "The first
      milestone" lists exactly
      seventeen numbered items
      (`verify_phase03.py` check
      41): the real-data walkthrough
      goes under its own heading
      after that section, never into
      its list.

    Files to read (every file before
    drafting):
    - src/judgemetrics/schemas/
      (coverage.py, common.py,
      metrics.py, cases.py,
      courts.py, jurisdictions.py),
      services/ and repositories/
      (coverage, metrics, cases,
      courts, jurisdictions,
      provenance, judges),
      api/routes/ (coverage,
      courts, judges,
      jurisdictions, metrics),
      api/deps.py.
    - docs/API.md, docs/openapi.json,
      tests/unit/test_openapi.py,
      tests/integration/test_api_coverage.py,
      test_api_metrics.py,
      test_query_counts.py,
      tests/golden/test_public_contract.py.
    - web/app/ (coverage,
      jurisdictions, compare,
      judges, cases, methodology),
      web/components/ (metric-stat,
      metric-panel, compare-table,
      provenance-panel, badges,
      case-timeline, cases-panel,
      synthetic-banner),
      web/lib/ (metrics.ts,
      links.ts, jurisdictions.ts,
      api/client.ts),
      web/tests/ (unit and e2e),
      web/AGENTS.md.
    - .github/workflows/ci.yml,
      tests/unit/test_repo_hygiene.py,
      scripts/verify_phase03.py
      (checks 41 and 42) and
      verify_phase04.py (checks 20,
      36, 42).
    - docs/ARCHITECTURE.md
      ("Public API v1", "Web tier"),
      README.md.
  </context>

  <goal>
    Ship coverage v2 and the
    jurisdiction coverage block; the
    coverage window on every
    `Provenance`; `/courts?q=`; the
    cases `cohort` filter; compare
    periods and the multi-court
    flag; the new methodology
    sections on `GET /metrics`; the
    regenerated OpenAPI and client;
    the coverage, jurisdiction,
    compare, judge, case, and
    methodology pages for real data;
    `real-data.spec.ts`; the `e2e`
    job ingesting the fixture; the
    screenshots — with the tests
    that prove every real surface
    shows coverage, limits, and the
    corpus end date and leaks no
    identifier or restricted value.
  </goal>

  <requirements>
    <requirement>
      Read all files listed in
      context before making any
      changes.
    </requirement>

    <requirement>
      Coverage v2. `CoverageSource`
      gains the latest snapshot's
      coverage statistics (each with
      numerator, denominator, share,
      and a methodology anchor), the
      unknown-actor share, the
      capabilities (attributed gates
      and person-key scope), and the
      not-attributable judge gates
      beside the observable and
      not-observable outcomes;
      `Coverage` gains
      `jurisdictions` (per
      jurisdiction, per source, its
      statistics); `JurisdictionDetail`
      gains the same block. Keep
      `/coverage` free of parameters
      and within its statement
      budget (raise it only with a
      documented reason in
      `test_query_counts.py`); update
      the pinned key sets.
    </requirement>

    <requirement>
      The corpus end date and the
      routes. `Provenance` gains its
      source's `coverage_start` and
      `coverage_end`
      (`source_records_by_id` selects
      them in the same statement), so
      every response that cites a
      source carries the corpus
      window. `/courts` gains `q`
      (word and whole-name trigram
      similarity, as `/search`).
      `/judges/{id}/cases` gains
      `cohort` =
      `assignment|pretrial_decision|disposition|sentence`
      (the cases reached through that
      gate; with no `cohort`, a case
      reached through any gate the
      source records), so a Cook
      County judge's cases list and
      the panels' "View eligible
      cases" links select their
      cohort. `/metrics/compare`
      lists the cohort's available
      periods and sets
      `coverage_warning` for a judge
      whose service spans more than
      the cohort's court. `GET
      /api/v1/metrics` serves Step
      5's "Source limitations",
      "Coverage statistics", and
      periods prose from the same
      constants as the methodology
      render. Regenerate
      `docs/openapi.json` and
      `web/lib/api/schema.d.ts`;
      update the pinned path,
      parameter, and allow-list sets.
    </requirement>

    <requirement>
      Web. The coverage page renders
      each source's statistics table
      (definitions linked to the
      methodology), the
      unknown-actor share, the
      corpus window ("Corpus ends
      …"), the observable,
      not-observable, and
      not-attributable lists in
      plain words, and the
      person-key note, and every
      "Phase 5" promise under
      `web/app/` (the home, court,
      coverage, jurisdiction, and
      compare pages) is replaced
      with what this phase delivered
      (real case data, the coverage
      statistics, the court search)
      or the phase that owns the
      rest (trends, per-jurisdiction
      completeness, and the coverage
      map: Phase 7 §7.4), with
      `smoke.spec.ts` updated; the
      jurisdiction page uses the
      API's coverage block instead
      of inferring sources, and its
      trends placeholder names Phase
      7 §7.4; the compare page gains
      a period selector (whole
      window by default, then each
      year) and a court search on
      `/courts?q=`, and shows the
      multi-court flag; a real
      judge's page shows "Not
      recorded by this source" (no
      figure) for a not-attributable
      metric, the corpus end date,
      no synthetic badge, and cohort
      links; a real case's page
      shows a bond set by a judicial
      officer the source does not
      name, a prosecutor's dismissal
      with its actor badge,
      sentences with their terms,
      and the probation-violation
      resentencing; provenance
      panels page their members;
      `web/lib/links.ts` gains
      `cook_sao`; FJC-only wording
      is fixed where it is wrong.
      `MetricStat` shows a year
      period when the observation is
      not whole-window; the judge
      page still renders exactly one
      association statement.
    </requirement>

    <requirement>
      CI. The `e2e` job ingests
      `tests/fixtures/cook_sao` with
      `--from-fixture` after the FJC
      fixture and before the seed;
      `metrics compute` covers it;
      `validation report --check`
      still passes; Playwright runs
      `real-data.spec.ts` with the
      other suites. Update the
      hygiene test's command list and
      relax `verify_phase03.py` check
      42 or `verify_phase04.py`
      checks 20 and 36 to an
      order-preserving subset if they
      trip, in this PR.
    </requirement>

    <requirement>
      Add tests:
      - `tests/integration/test_api_coverage.py`
        (v2 keys; the fixture's
        statistics; the jurisdiction
        block), `test_api_cases.py`
        (the cohort filter, Cook
        County cases listed through
        dispositions and sentences),
        `test_api_courts.py` (`q`),
        `test_api_metrics.py`
        (periods; the multi-court
        flag; the new prose),
        `test_query_counts.py`.
      - `tests/golden/test_public_contract.py`
        extended to the Cook County
        fixture (no participant id,
        no restricted name or value
        in any response; the coverage
        window on every provenance
        block).
      - Vitest: the coverage page,
        the compare period selector
        and court search, the
        not-recorded state, the case
        page's actor badges, the
        links, schema freshness.
      - `web/tests/e2e/real-data.spec.ts`
        (at least six tests over the
        fixture: the coverage page's
        statistics and corpus end
        date; a Cook County judge's
        page with an unsuppressed
        sentencing figure, the
        not-recorded pretrial state,
        and no synthetic badge; a case
        page with a prosecutor's
        dismissal and a sentence; the
        compare page by year and by
        court search; paged
        provenance).
    </requirement>

    <requirement>
      Screenshots and documentation:
      `docs/screenshots/phase05-step7/`
      (the coverage, judge, case, and
      compare pages, light and dark,
      from the full corpus);
      `docs/API.md`,
      `docs/ARCHITECTURE.md` ("Public
      API v1", "Web tier"),
      `web/AGENTS.md`, `README.md`
      (the real-data walkthrough),
      `AGENTS.md`. Filepath comment:
      every new file gets the
      repo-relative path as the first
      line.
    </requirement>
  </requirements>
</task>
```

### Step 7 acceptance criteria

- `/api/v1/coverage` v2, the jurisdiction coverage block, the coverage window
  on every provenance block, `/courts?q=`, the cases `cohort` filter, compare
  periods with the multi-court flag, and the new methodology prose are served;
  `docs/openapi.json` and `web/lib/api/schema.d.ts` are regenerated and every
  pin is updated; the query budgets hold or carry a documented change.
- The coverage, jurisdiction, compare, judge, case, and methodology pages render
  the real corpus with its statistics, limitations, and corpus end date; an
  unattributable metric shows "Not recorded by this source" and no figure; the
  judge page keeps exactly one association statement.
- `real-data.spec.ts` passes over the fixture locally and in CI's `e2e` job
  beside the smoke, metrics, first-milestone, and adjusted suites; `pnpm lint`,
  `typecheck`, `build`, and `test` pass; the Python suites pass; CI is green.
- **Deployed & verified:** after the merge, `uv run poe dev-api` and `pnpm dev`
  (in `web/`) over the local database with the full corpus render the coverage
  page with Cook County's statistics, unknown-actor share, and corpus end date,
  a real judge's page with published figures and the not-recorded state, a real
  case's timeline, and the compare page by year; the screenshots are committed.
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff — secret/PII scan clean, SAST clean,
  dependency audit clean, and the public surface handles sensitive data per the
  project ROADMAP "Security & privacy strategy": the public contract over the
  Cook County fixture finds no participant id, restricted name, or restricted
  value in any response, every new parameter is validated and bound, and the
  screenshots show no defendant identifier.

---

## Step 8 — QA & Verification Script

**Status:** Not started

> **Goal:** Package the verification matrix into `scripts/verify_phase05.py`
> (with `--fast`, `--py`, `--node`, `--e2e`, `--security`, `--all`, and `--post`
> modes), produce `docs/phase05-qa-findings.md`, and add `05` to the
> `phase-verify.yml` matrix with `phase-verify (05)` as a required context on
> `main`. The script checks every Step 1 through Step 7 deliverable with sixty
> standard-library static checks and runs the Phase 5 Python, web, and
> Playwright suites in the appropriate modes; `--post` adds the scratch-database
> probes over the Cook County fixture (ingest idempotency, compute idempotency,
> `metrics verify` with the coverage statistics, `models verify --refit`, the
> validation report, a paged real-data trace) and the read-only full-corpus
> probes against the configured database, then the V1–V8 matrix. The findings
> rollup records the alarm exercises, the pre-ship items, and the Phase 6
> carry-over checklist; the parent roadmap's Phase 5 entry is marked complete
> and audited against the V-checks; and the merge is tagged `v0.5.0-phase-5`.

**Branch:** `feature/phase05-step8-verify`

**Deploys:** nothing beyond merge — the CI matrix entry is live on merge; the
operator adds the required context with the documented `gh api` call in this
step, and the tag `v0.5.0-phase-5` marks the squash-merged commit.

Settings table — Effort + Thinking variant (Claude Code):

| Setting      | Value                                                      |
| ------------ | ---------------------------------------------------------- |
| Model        | Opus 5.5                                                   |
| Backup       | GPT-6 Sol — Codex · Intelligence Medium                    |
| Platform     | Claude Code                                                |
| Effort       | Medium (Claude Code's default — no change, run as opened)  |
| Thinking     | On                                                         |
| Conversation | **New**                                                    |

**Model rationale:** This is the mechanical translation of `verify_phase04.py`
into Phase 5's deliverables — numbered static checks, mode dispatch, subprocess
suites, scratch-database and read-only probes, the V-matrix, the findings
rollup, a one-line matrix edit, the required-context call, and the tag: PRIMARY
`coding`, Medium complexity (bounded, well specified, a known pattern, no novel
reasoning). The operator's `balanced` posture names the surface's default model
at its default effort as the anchor for Medium work, so the step runs as Claude
Code opens: Opus 5.5 (S-tier in coding, AA Intelligence Index 57.6 at max) at
Effort `Medium` on the $200 claude.ai Max subscription (weekly pool at
`headroom`), Thinking `On`. Nothing earns a raise — the pattern is fixed by
`verify_phase04.py`, and the CI matrix, the unit test, and the `--post` probes
catch any slip. Backup: GPT-6 Sol on Codex (the $100 ChatGPT Pro 5x pool),
S-tier in coding and the widest-coverage S-tier coder outside Anthropic, at
Intelligence `Medium`; not a `*-codex` variant. Conversation is New per
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
       feature/phase05-step8-verify`
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
       roadmap's Phase 5
       `**Status:**` to `In
       progress`; on the final step,
       both to `Complete`, with ` ✅`
       appended to this roadmap's `#
       ` title and to the parent's
       `### Phase 5` heading.

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
       finding → the versioned rule,
       vocabulary, registry, or
       specification entry, version
       bumped; a data-access
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
       line — verbatim shape "Step 8
       is complete. Phase 5 is
       complete. You can now move on
       to Phase 6." That line is the
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
       Phase 6.
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
    and re-run in CI. This step
    also AUTHORS the `--security`
    verify mode, so its own diff
    must still pass the gate before
    commit:

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
       numbers, names, paths, and
       counts — never a file's
       contents, a participant id, a
       restricted value, or a
       credential; the alarm
       exercises tamper and restore
       rows in the scratch database
       only and record ids and
       column names, never values of
       a person; the findings
       document carries no real
       record.

    2. SAST. No new injection,
       unsafe deserialization, weak
       crypto, path traversal, or
       unsafe-eval pattern (bandit /
       semgrep /
       eslint-plugin-security per
       the stack). Suppress a
       finding ONLY with an inline
       justification comment. In
       this step: the script stays
       standard-library only (line
       readers, `csv`, `hashlib`,
       `json`, `re`; no YAML or XML
       parser), runs subprocesses
       with argument lists over
       PATH-resolved tools and no
       shell, and carries each
       bandit suppression after the
       ruff one with its
       justification between them.

    3. DEPENDENCY AUDIT. Any new or
       bumped dependency passes the
       audit (pip-audit / npm audit
       / osv-scanner); no
       known-vulnerable, yanked, or
       typo-squatted package. This
       step adds no dependency.

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
       the scratch database and its
       own snapshot directory; the
       full-corpus probes are
       read-only (`metrics verify`,
       `metrics coverage`, `ingest
       runs`) against the configured
       database; the workflow keeps
       `contents: read`, SHA-pinned
       actions, and no
       `JUDGEMETRICS_*` value.

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
    JudgeMetrics. Phase 5. Step 8:
    QA + verification script.

    Steps 1 through 7 have been
    implemented (Step 2 included,
    whichever order it ran in). Now
    create the verification script,
    the QA findings document, and
    the CI matrix update.

    Reference scripts (pattern
    templates):
    - scripts/verify_phase04.py
      (closest structural precedent:
      50 static checks, the seven
      modes, `probe_environment()`,
      the line readers, the `M` row,
      the V-matrix, the summary).
    - scripts/verify_phase03.py
      (secondary pattern reference).

    Phase 5 deliverables to verify
    (54 static checks across Steps 1
    through 7 plus 6 Step 8
    self-checks, 60 in all; every
    version check a `>=` against the
    source constant, every earlier
    phase's path or matrix entry a
    subset):

    Step 1 (due diligence, fetch,
    profile, fixture) — checks 1-8:
    1.  `src/judgemetrics/ingest/cook_sao/`
        tracked with `sources.py`
        (the five portal ids and
        external ids), `schema.py`
        (`HEADERS_VERIFIED_ON`,
        `RESTRICTED_COLUMNS`,
        `BLANKED_COLUMNS`), and
        `connector.py`; the module in
        `BUILTIN_CONNECTOR_MODULES`.
    2.  `ingest/http.py` streams to
        a temporary file and checks
        the cap while reading; the
        connector passes its own cap.
    3.  `put_file` and `get_file` on
        both store backends; the
        runner's hash path reads
        path artifacts in chunks (no
        `read_bytes()` in that
        function's body), and
        `_retrieve` and
        `_materialized` call
        `get_file`, never
        `store.get()`.
    4.  `data/reference/cook_sao/profile.yaml`
        tracked: `version` >= 1, five
        64-hex digests, `race` and
        `gender` listed without
        counts.
    5.  `tests/fixtures/cook_sao/`
        tracked with five CSVs and a
        README; every
        `BLANKED_COLUMNS` value empty
        in every row (`csv` module).
    6.  `docs/DATA_SOURCES.md`'s
        `cook_sao` entry states that
        the participant id is per
        case and names question 2 as
        its only open item;
        `docs/ROADMAP.md` marks
        questions 3 and 4 resolved
        (positive assertions over
        whitespace-normalized text).
    7.  The project roadmap's Phase
        5 entry states the per-case
        person key and its risks
        table has a row naming the
        missing cross-case key
        (positive assertions over
        whitespace-normalized text).
    8.  poe `ingest-cook` and its
        Makefile target; `sources
        profile` and `sources
        excerpt` in `cli.py`; the
        Step 1 tests tracked.

    Step 2 (Florida) — checks 9-12:
    9.  `docs/florida-data-inventory.md`
        tracked with its path comment
        and the eight section
        headings.
    10. At least six county
        candidates, Broward and
        Miami-Dade among them; the
        selection table's rows cite
        `https://` sources.
    11. `docs/florida/requests/`
        holds at least one request,
        each naming the three
        redistribution rights.
    12. The "Florida acquisition
        requests" table in
        `docs/ROADMAP.md` has at
        least one row with a
        submission date, and every
        row has a date or a recorded
        reason.

    Step 3 (rules, tables,
    vocabulary 3) — checks 13-20:
    13. `case_vocabulary.yaml`
        `version` >= 3 with `race`
        and `gender` under
        `restricted_attribute`, each
        listing `unknown`; the
        generator's constant equal.
    14. The seven tables and
        `tables.yaml` tracked under
        `data/reference/cook_sao/`;
        every digest in `tables.yaml`
        matches its file.
    15. `attribution_rules.yaml`:
        `version` >= 1, the
        principles header, every rule
        with `disposition`, `final`,
        `actor_type`,
        `judicial_discretion_classification`,
        and `rationale`; a `summary`
        with the unknown share.
    16. `pretrial_rules.yaml` names
        both regimes (2023-09-18);
        no deposit or cash rule sets
        a release.
    17. `judge_aliases.csv` has one
        row per distinct judge string
        of the profile; every
        `ambiguous` row names
        candidates.
    18. `outcome_model.yaml`
        `version` >= 2 and its
        severity and category levels
        cover the vocabulary's.
    19. `rules.py` defines
        `RULE_VERSIONS`, one version
        per table of `tables.yaml`.
    20. The Step 3 tests tracked.

    Step 4 (connector at scale) —
    checks 21-30:
    21. Migration
        `0011_cook_county_connector`:
        the `cook_sao_judge` index,
        `charge.judge_id`, the revoke
        on `data_quality_issue`, and
        `03-test-database.sql`
        revoking it too.
    22. `JUDGE_IDENTITY_SYSTEMS`
        includes `cook_sao_judge`.
    23. The bounded-lookup helper
        exists and the runner,
        publisher, and resolution
        functions named in Step 4
        call it (function bodies).
    24. The connector's parser
        version is `1+` followed by
        `RULE_VERSIONS` (built from
        the constant, leading number
        >= 1); it defines
        `load_context` and
        `coverage_window` and
        declares `revocation`.
    25. `PartyAttributeDraft` used in
        `ingest/cook_sao/`;
        `test_restricted_readers.py`
        allows the directory;
        `verify_phase04.py` check 31
        reads that list.
    26. The scrubber's whole-token
        constant beside
        `SENSITIVE_KEYS` holds
        `race`, `gender`, and
        `age_at_incident`.
    27. `identifiers.py` offers the
        source-qualified form and the
        synthetic connector does not
        use it.
    28. The case-level checks read
        parent cases from the
        database.
    29. `ingest retire` exists,
        refuses production, writes
        `ingest.retire`; `seed` calls
        it.
    30. The Step 4 tests tracked.

    Step 5 (semantics, periods,
    coverage statistics) — checks
    31-40:
    31. Registry `version` >= 3,
        `methodology_version` >= 1.1,
        `CHANGELOG` with 1.1, and the
        brief's eight limitations
        exactly.
    32. `disposing_judge` is a gate
        and every disposition-family
        entry uses it.
    33. `NotAttributable` in
        `metrics/` and
        `SourceInfo.capabilities` in
        `ingest/base.py`.
    34. The registry declares the
        calendar periods; the compute
        emits them.
    35. Migration
        `0012_real_data_semantics`:
        `source.capabilities` and
        `coverage_statistic` with the
        app role's `SELECT`.
    36. `metrics/coverage.py` names
        the six statistics and the
        unknown-actor share;
        `verify.py` checks them.
    37. `outcome_model.yaml`
        `version` >= 3 with
        per-source availability;
        `validation report --source`.
    38. `docs/METHODOLOGY.md` has
        "Source limitations" and
        "Coverage statistics".
    39. `metrics compute --source`
        and `metrics coverage` in
        `cli.py`.
    40. The Step 5 tests tracked.

    Step 6 (engine at scale) —
    checks 41-46:
    41. Migration
        `0013_member_storage` with
        the family layout.
    42. `publish.py` writes members
        with `COPY`.
    43. The vectorized estimator in
        `censoring.py`; the reference
        implementation only in tests.
    44. The provenance route's
        allow-list has `limit` and
        `offset`; the CLI `--limit`.
    45. `docs/ARCHITECTURE.md` "Scale
        budgets" with the Step 4 and
        Step 6 figures.
    46. The Step 6 tests tracked.

    Step 7 (public surfaces) —
    checks 47-54:
    47. `docs/openapi.json` holds
        the Phase 1-4 paths (a
        subset); `/courts` has `q`;
        `/judges/{judge_id}/cases`
        has `cohort`.
    48. The `Provenance` schema has
        `coverage_end`; the coverage
        schema has the statistics.
    49. `web/lib/links.ts` names
        `cook_sao`; no file under
        `web/app/` (the pages exist)
        contains "Phase 5"; the
        jurisdiction page names
        Phase 7 for trends.
    50. The compare page has the
        period selector and the court
        search.
    51. `web/tests/e2e/real-data.spec.ts`
        with at least six tests; the
        `e2e` job ingests
        `tests/fixtures/cook_sao`.
    52. Exactly one
        `data-testid="association-statement"`
        on the judge page.
    53. `docs/screenshots/phase05-step7/`
        in light and dark.
    54. The Step 7 tests tracked.

    Step 8 self-checks — checks
    55-60:
    55. `scripts/verify_phase05.py`
        tracked, its path comment,
        the seven modes.
    56. `docs/phase05-qa-findings.md`
        with every rollup section,
        the alarm exercise, the
        pre-ship items, and "## Phase
        6 carry-over checklist".
    57. `docs/roadmap/phase05-roadmap.md`
        exists (this doc).
    58. `.github/workflows/phase-verify.yml`
        matrix includes `05` (and
        01-04), SHA-pinned.
    59. Security wiring: the hooks
        (secret scan, bandit,
        pip-audit), least-privilege
        workflows, no PEM header or
        `AKIA` key in tracked files.
    60. No tracked file outside
        `tests/fixtures/cook_sao/`
        contains one of the
        fixture's participant ids.

    Files to read:
    - scripts/verify_phase04.py
      (primary structural
      template) and
      tests/unit/test_phase04_verification.py.
    - all Phase 5 implementation
      files from Steps 1 through 7.
    - .github/workflows/phase-verify.yml,
      ci.yml, CONTRIBUTING.md
      ("Repository settings").
    - docs/phase04-qa-findings.md
      (the rollup format).
  </context>

  <goal>
    Create scripts/verify_phase05.py
    with the 60 static checks above,
    the suites per mode, the
    scratch-database and read-only
    probes, and the V1-V8 matrix;
    tests/unit/test_phase05_verification.py;
    docs/phase05-qa-findings.md; the
    matrix entry `05` and its
    required context; the parent
    roadmap's Phase 5 completion;
    the tag `v0.5.0-phase-5`.
  </goal>

  <requirements>
    <requirement>
      Read scripts/verify_phase04.py
      end-to-end for structure, flag
      parsing, output format,
      `report` / `summary`
      conventions, and the final
      summary table. Mirror the
      format exactly so the Phase 5
      script is visually continuous
      with the Phase 4 script in CI
      logs.
    </requirement>

    <requirement>
      scripts/verify_phase05.py
      modes (mutually exclusive;
      default `--fast` plus `--py`):
      - `--fast`: static checks
        only, CI-safe on Ubuntu,
        standard library only.
      - `--py`: static + `uv run
        poe lint`, `typecheck`, and
        pytest over the unit,
        integration, property, and
        golden suites (scratch
        database preferred).
      - `--node`: static + `pnpm
        lint`, `typecheck`, `build`,
        `test` in `web/`.
      - `--e2e`: static + the
        Playwright suites (smoke,
        metrics, first milestone,
        adjusted, real-data) against
        a running API and web app;
        `SKIP` without them.
      - `--security`: the secret
        scan (`detect-secrets-hook
        --baseline` over tracked
        files, batched), bandit over
        `src alembic scripts`, the
        `uv.lock` audit, `pnpm audit
        --audit-level=high`; exits
        non-zero on any finding.
      - `--all`: static + e2e + node
        + py + security.
      - `--post`: static + the
        milestone setup (M rows) +
        the scratch-database probes
        inside `probe_environment()`
        — the Cook County fixture
        ingested twice (the second
        creates and updates nothing),
        the seed and compute
        idempotency probes, `metrics
        verify` (observations and
        coverage statistics), `models
        verify --refit`, `validation
        report --check`, `validation
        recovery`, a paged `provenance
        trace` of a random Cook County
        fixture observation (`complete:
        yes`), `metrics coverage
        --source cook_sao --json` with
        all seven statistics — then
        the read-only full-corpus
        probes against the configured
        database (`ingest runs
        --source cook_sao` latest
        succeeded, `sources profile
        cook_sao --check` over the
        lake, `metrics verify`,
        `metrics coverage`; `SKIP`
        when the corpus is absent),
        the suites, `gh pr checks`,
        and the V1-V8 matrix.
      Static checks print `[PASS]
      NN` / `[FAIL] NN — reason`;
      probes and suites `[PASS]`,
      `[FAIL]`, or `[SKIP] id —
      reason`. At least one static
      check (59) confirms the gate is
      wired, and check 60 is the
      backstop against a real
      identifier committed outside
      the fixture.
    </requirement>

    <requirement>
      Post-implementation V-checks
      section mirroring Phase 4
      (V1-V8, with an `M` row that
      folds the milestone items into
      the summary): V1.1 statics 1-8,
      V1.2 the Step 1 tests, V1.3
      `sources profile --check`
      against the lake; V2.1
      statics 9-12; V3.1 statics
      13-20, V3.2 the rule, table,
      alias, and vocabulary tests;
      V4.1 statics 21-30, V4.2 the
      ingest, restricted, ceiling,
      parent-case, retire, and order
      tests, V4.3 the fixture ingest
      probe; V5.1 statics 31-40,
      V5.2 the registry, attribution,
      coverage, period, golden, and
      Cook County metric tests, V5.3
      the verify and coverage probes;
      V6.1 statics 41-46, V6.2 the
      equivalence and member-storage
      tests, V6.3 the paged trace
      probe and the full-corpus
      probes; V7.1 statics 47-54,
      V7.2 the API and contract
      tests, V7.3 the web suites,
      V7.4 `real-data.spec.ts`; V8.1
      `--fast` on Ubuntu CI (the
      PR's `phase-verify (05)`),
      V8.2 the matrix (check 58),
      V8.3 all 60 statics, V8.4
      `--security`.
    </requirement>

    <requirement>
      Create
      tests/unit/test_phase05_verification.py:
      the roadmap and the findings
      document exist with their
      sections; `--fast` exits 0 with
      60 passes; the matrix includes
      `{"01", "02", "03", "04",
      "05"}` as a subset; the
      workflow sets no
      `JUDGEMETRICS_*` value; the
      script's line readers agree
      with `yaml.safe_load` on the
      registry, the vocabulary, the
      specification, and
      `tables.yaml`.
    </requirement>

    <requirement>
      Update
      .github/workflows/phase-verify.yml
      to include `"05"` in
      `matrix.phase` — an additive
      change preserving every prior
      entry — and, once the PR's
      `phase-verify (05)` run is
      green, make it a required
      context: `gh api -X PATCH
      repos/nathanramoscfa/judge-metrics/branches/main/protection/required_status_checks`
      with `test` and `phase-verify
      (01)` through `(05)`; record
      the six contexts in
      `CONTRIBUTING.md`.
    </requirement>

    <requirement>
      Create docs/phase05-qa-findings.md
      with rollup sections for Steps 1
      through 7 (each finding, its
      class, its guard), a Step 8
      verify-script rollup, the alarm
      exercise — (a) a deliberately
      broken static check failing
      `phase-verify (05)` and `test`,
      then passing; (b) a tampered
      Cook County fixture
      observation failing `metrics
      verify` in the scratch
      database, then passing; (c) a
      tampered coverage statistic
      failing it, then passing; (d) a
      changed byte of `profile.yaml`
      failing `sources profile
      --check`, then passing — the
      "Pre-ship items" (documented
      limitations: no cross-case key,
      no real adjusted figure, the
      fairness analysis withheld, the
      step-13 rule, the bond-type
      semantics, the unknown share),
      and "## Phase 6 carry-over
      checklist" (at least: the
      attribution validation against
      source documents and the real
      calibration of §6.1; the
      fairness analysis over the real
      restricted attributes after
      §6.4's go/no-go; the judge
      review queue and source
      retirement in the admin
      surface; the issue for a
      judge-attributed real-data
      target; the Florida requests'
      follow-ups; the person-linkage
      error estimates, which have
      nothing to estimate for a
      per-case key; the corrections
      reader and suppression over
      real data).
    </requirement>

    <requirement>
      Mark the phase complete in the
      parent project roadmap
      (docs/roadmap/ROADMAP.md,
      beside this file) in the SAME
      Stage-3 commit that marks this
      step (Status rule):
      - `### Phase 5` gets
        `**Status:** Complete —
        <YYYY-MM-DD>; PR #<n>;
        v0.5.0-phase-5;
        phase05-roadmap.md` directly
        under its heading, and the
        heading ends in ✅.
      - Its row in the "Phase
        Complexity Summary" table
        reads `Complete` (Step 1's PR
        set it to `In progress`).
      - The header `> **Status:**`
        line names Phase 5 as shipped
        and Phase 6 as next.
      - Consistency audit: the Phase
        5 "Acceptance criteria" there
        match this roadmap's V1-V8
        checks (Step 1 already
        corrected the cross-case
        claims; align the rest).
      And in THIS roadmap, same
      commit: its phase-level
      `**Status:**` line (under the
      title) reads `Complete —
      <YYYY-MM-DD>`, the title and
      every step heading end in ✅,
      and every step's Summary Table
      Status cell reads `Complete —
      PR #<n>`. Update
      `docs/ROADMAP.md` (current
      phase → Phase 6 not started;
      the completed row; next
      milestones), then tag the
      squash-merged commit
      `v0.5.0-phase-5` and push the
      tag.
    </requirement>

    <requirement>
      The script exits 0 on success
      and 1 on any failure; mirror the
      output format, the
      check-numbering convention, and
      the summary table of
      verify_phase04.py so CI log
      diffing across phases is
      frictionless; `--fast` completes
      in under 30 seconds on Ubuntu
      CI.
    </requirement>

    <requirement>
      Filepath comment: every new file
      gets the repo-relative path as
      the first line.
    </requirement>
  </requirements>
</task>
```

### Step 8 acceptance criteria

- `scripts/verify_phase05.py` exists, is tracked, and passes on a clean tree
  post-implementation; `tests/unit/test_phase05_verification.py` passes.
- The script has 60 deliverable checks plus the V1–V8 post-implementation
  checks, the `M` row, and the `--post` probes.
- `--fast` runs in under 30 seconds on Ubuntu CI.
- `--post` runs cleanly on the maintainer's machine (Docker Desktop, `dev-api`,
  and `pnpm dev` running, the full corpus in the configured database) with
  every probe green: the Cook County fixture ingest probe, the seed and compute
  idempotency probes, `metrics verify` with the coverage statistics, `models
  verify --refit`, `validation report --check`, `validation recovery`, the paged
  real-data trace, and the read-only full-corpus probes.
- `docs/phase05-qa-findings.md` is complete with every rollup section, the four
  alarm exercises, the pre-ship items, and the Phase 6 carry-over checklist.
- `.github/workflows/phase-verify.yml` matrix includes `"05"`; `phase-verify
  (05)` appears on every PR and is a required context on `main` beside `test`
  and `(01)`–`(04)`.
- `--security` mode exists and exits 0 (secret/PII scan, SAST, and dependency
  audit clean over the phase's surface); V8.4 is green.
- Branch protection still passes on the resulting PR; the tag `v0.5.0-phase-5`
  marks the merge commit.
- **Operations**: the real source's health signals (the latest `ingest runs
  --source cook_sao` succeeded; `/api/v1/coverage` carries its statistics;
  `metrics verify` and `sources profile --check` green) and alarms (`metrics
  verify` non-zero on a tampered real observation and on a tampered coverage
  statistic; `sources profile --check` non-zero on a changed profile) exist,
  and each alarm was seen to fire once in the alarm exercise, recorded with its
  output in `docs/phase05-qa-findings.md`.
- **Security gate clean** (always the final criterion): the pre-commit security
  gate passed on this step's diff and the security workflow is green.
- **Phase closed, nothing carried.** Every finding recorded in
  `docs/phase05-qa-findings.md` has a destination (fixed, an issue number, or a
  named phase that owns it), the "Not in scope" section below is current, and no
  un-tracked item remains. Every step of this roadmap, this one included, reads
  `**Status:** Complete — PR #…` on `main` under a ✅ heading, the Summary
  Table's Status column and this roadmap's phase-level Status line say
  `Complete` under a ✅ title, and the parent project roadmap's Phase 5 entry
  (under a ✅ heading), its summary-table row, and its header status line say
  `Complete` — all landed in this step's PR. This step's final response ends
  with two lines and nothing after them: "Step 8 is complete. You can now move
  on to Step 9." is replaced by "Step 8 is complete. Phase 5 is complete. You
  can now move on to Phase 6." — same Stage 6 rule: no "Follow-ups", no trailer.

---

## Post-Implementation Verification

Every V1–V8 check below runs automatically in CI on every push and pull request
— no manual invocation required — except V1.3, V4.3, V5.3, V6.3, and the
`--post` sweep, which the operator runs on the maintainer's machine against the
Compose services, the scratch database, and the configured database that holds
the full Cook County corpus before tagging `v0.5.0-phase-5`. Three things in
this phase are operator wall-clock work by design: submitting the Florida
requests (Step 2, recorded with dates), the full-corpus fetch, ingest, and
compute (the Deployed & verified bullets of Steps 1, 4, and 6, each with its
recorded budget), and the `--post` sweep. CI never downloads the corpus: every
code path runs there on the committed fixture, and the `e2e` job ingests it
beside the FJC fixture and the demo seed.

| Mode         | Workflow                                     | Runner           | Coverage                                                            |
| ------------ | -------------------------------------------- | ---------------- | ------------------------------------------------------------------- |
| `--fast`     | `phase-verify.yml` (matrix entry `05`)       | Ubuntu           | Static checks 1–60, V1.1, V2.1, V3.1, V4.1, V5.1, V6.1, V7.1, V8.1–V8.3 |
| `--py`       | `ci.yml` (`python` job, Postgres service)    | Ubuntu           | V1.2, V3.2, V4.2, V5.2, V6.2, V7.2                                   |
| `--node`     | `ci.yml` (`web` job)                         | Ubuntu           | V7.3                                                                |
| `--e2e`      | `ci.yml` (`e2e` job: FJC and Cook County fixtures, demo seed) | Ubuntu | V7.4                                                  |
| `--security` | `ci.yml` (`security` and `container` jobs) + `phase-verify.yml` | Ubuntu | V8.4                                                        |
| `--post`     | local (maintainer's machine)                 | Windows / Ubuntu | Full V1–V8 sweep + V1.3 + V4.3 + V5.3 + V6.3 + `gh pr checks`        |

Local invocations remain available for ad-hoc runs and pre-release sweeps:

```bash
uv run python scripts/verify_phase05.py --post   # static + probes + full-corpus probes + V1-V8 + gh pr checks
```

`--post` is the canonical command to run before tagging the phase release.

Other modes:

```bash
uv run python scripts/verify_phase05.py             # static + Python suites
uv run python scripts/verify_phase05.py --fast      # static only (CI)
uv run python scripts/verify_phase05.py --py        # static + ruff + mypy + pytest (unit, integration, property, golden)
uv run python scripts/verify_phase05.py --node      # static + web lint/typecheck/build/test
uv run python scripts/verify_phase05.py --e2e       # static + Playwright (smoke, metrics, first milestone, adjusted, real data)
uv run python scripts/verify_phase05.py --security  # secret scan + SAST + audits
uv run python scripts/verify_phase05.py --all       # everything
```

The script reports each V-check by id (V1.1, V2.1, …) so a failure in any
workflow above maps directly to the corresponding row below.

### V1 — Cook County due diligence, streamed fetch, profile, fixture

> **Automated in CI.** `phase-verify.yml` → V1.1; `ci.yml` → V1.2; local
> `--post` → V1.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V1.1 | Static checks 1–8 all PASS (the connector's files and registration, the streamed download and `put_file`, the profile's digests and uncounted restricted values, the blanked fixture, the corrected register, questions, and project roadmap, the commands). | `phase-verify.yml` runs `verify_phase05.py --fast`. |
| V1.2 | `test_streaming_download.py`, `test_raw_store_files.py`, `test_cook_sao_connector.py`, `test_cook_sao_profile.py`, `test_cook_sao_fixture.py`, and `test_cook_sao_fetch.py` pass. | `ci.yml` `python` job (MinIO for the S3 path). |
| V1.3 | `judgemetrics sources profile cook_sao --check` exits 0 over the five artifacts in the lake. | `--post` locally (read-only). |

### V2 — Florida source research and the acquisition plan

> **Automated in CI.** `phase-verify.yml` → V2.1.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V2.1 | Static checks 9–12 all PASS (the inventory's sections and candidates, cited sources, the requests' redistribution asks, every request dated or explained). | `phase-verify.yml --fast`. |

### V3 — Mapping and attribution rules, judge and court tables, vocabulary 3

> **Automated in CI.** `phase-verify.yml` → V3.1; `ci.yml` → V3.2.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V3.1 | Static checks 13–20 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V3.2 | `test_cook_sao_rules.py` (every pair maps; no prosecutor or jury outcome to a judge; the summary), `test_cook_sao_tables.py`, `test_judge_aliases.py`, `test_cook_sao_matchers.py` (`ci` profile), `test_vocabulary.py` (version 3, equal to the generator), `test_outcome_model_spec.py` (version 2), and `test_golden_fixture.py` (unchanged) pass. | `ci.yml` `python` job. |

### V4 — The Cook County connector at corpus scale

> **Automated in CI.** `phase-verify.yml` → V4.1; `ci.yml` → V4.2; local
> `--post` → V4.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V4.1 | Static checks 21–30 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V4.2 | `test_cook_sao_normalize.py`, `test_identifiers.py`, `test_logging.py`, `test_cook_sao_ingest.py`, `test_cook_sao_restricted.py`, `test_bind_parameter_ceiling.py`, `test_parent_case_checks.py`, `test_ingest_retire.py`, `test_cook_sao_order.py`, and `test_migrations.py` through `0011` pass; the golden, FJC, and synthetic suites are unchanged. | `ci.yml` `python` job. |
| V4.3 | The Cook County fixture ingested twice into the scratch database: the second run creates and updates nothing. | `--post` locally (`probe_environment()`). |

### V5 — Real-data semantics, calendar periods, coverage statistics

> **Automated in CI.** `phase-verify.yml` → V5.1; `ci.yml` → V5.2; local
> `--post` → V5.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V5.1 | Static checks 31–40 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V5.2 | `test_metric_registry.py`, `test_attribution.py` (`disposing_judge`, `NotAttributable`), `test_coverage_statistics.py`, `test_period_consistency.py` (`ci` profile), `test_golden_metrics.py` (unchanged values), `test_cook_sao_metrics.py`, `test_methodology_render.py` (1.1), and `test_migrations.py` through `0012` pass. | `ci.yml` `python` job. |
| V5.3 | `metrics verify` (observations and coverage statistics) and `metrics coverage --source cook_sao --json` (all seven statistics) pass on the scratch database. | `--post` locally. |

### V6 — The metrics engine at corpus scale

> **Automated in CI.** `phase-verify.yml` → V6.1; `ci.yml` → V6.2; local
> `--post` → V6.3.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V6.1 | Static checks 41–46 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V6.2 | `test_censoring_vectorized.py`, `test_km_equivalence.py`, `test_member_storage.py`, `test_snapshot_export.py`, `test_golden_provenance.py` (paged), and `test_query_counts.py` pass; every golden observation and member multiset is unchanged. | `ci.yml` `python` job. |
| V6.3 | A paged trace of a random Cook County fixture observation prints `complete: yes`; the read-only full-corpus probes (`ingest runs`, `metrics verify`, `metrics coverage`) pass against the configured database. | `--post` locally. |

### V7 — Public surfaces for the first real source

> **Automated in CI.** `phase-verify.yml` → V7.1; `ci.yml` `python` → V7.2;
> `ci.yml` `web` → V7.3; `ci.yml` `e2e` → V7.4.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V7.1 | Static checks 47–54 all PASS.                                               | `phase-verify.yml --fast`.                              |
| V7.2 | `test_api_coverage.py` (v2), `test_api_cases.py` (cohort), `test_api_courts.py` (`q`), `test_api_metrics.py` (periods, the multi-court flag), `test_query_counts.py`, `test_openapi.py`, and `test_public_contract.py` (the Cook County fixture: no identifier, restricted name, or value) pass. | `ci.yml` `python` job. |
| V7.3 | `pnpm lint`, `pnpm typecheck`, `pnpm build`, and `pnpm test` pass (the coverage page, the period selector and court search, the not-recorded state, the links, schema freshness, the bundle scan). | `ci.yml` `web` job (`--node` locally). |
| V7.4 | `real-data.spec.ts` passes over the Cook County fixture beside the smoke, metrics, first-milestone, and adjusted suites. | `ci.yml` `e2e` job (`--e2e` locally). |

### V8 — CI integration + security

> **Automated in CI.** `phase-verify.yml` → V8.1 through V8.4 on every push/PR.

| ID   | Check                                                                       | Automation                                             |
| ---- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| V8.1 | `verify_phase05.py --fast` exits 0 on Ubuntu CI.                            | `phase-verify.yml` matrix entry `05`.                   |
| V8.2 | `phase-verify.yml` matrix includes `05`.                                    | `phase-verify.yml --fast` static check 58.              |
| V8.3 | All 60 static checks in `verify_phase05.py` pass.                           | `phase-verify.yml --fast` records pass only when zero static failures. |
| V8.4 | `verify_phase05.py --security` exits 0 (secret/PII scan + SAST + dependency audits clean). | `phase-verify.yml` runs `--security` on every push/PR. |

---

## Summary Table

| Step | Scope                                          | Model      | Platform    | Reasoning dial | Thinking | Conv | Status      |
| ---- | ---------------------------------------------- | ---------- | ----------- | -------------- | -------- | ---- | ----------- |
| 1    | Cook County due diligence, fetch, profile      | Opus 5.5   | Claude Code | Effort XHigh   | On       | New  | Not started |
| 2    | Florida research and acquisition plan          | Opus 5.5   | Claude Code | Effort XHigh   | On       | New  | Not started |
| 3    | Attribution rules, tables, vocabulary 3        | Opus 5.5   | Claude Code | Effort XHigh   | On       | New  | Not started |
| 4    | Cook County connector at corpus scale          | Sonnet 5.5 | Claude Code | Effort XHigh   | On       | New  | Not started |
| 5    | Real-data semantics, coverage statistics       | Opus 5.5   | Claude Code | Effort XHigh   | On       | New  | Not started |
| 6    | Metrics engine at corpus scale                 | Sonnet 5.5 | Claude Code | Effort XHigh   | On       | New  | Not started |
| 7    | Public surfaces for the first real source      | Sonnet 5.5 | Claude Code | Effort High    | On       | New  | Not started |
| 8    | QA + verify_phase05.py                         | Opus 5.5   | Claude Code | Effort Medium  | On       | New  | Not started |
| V1   | Due diligence, fetch, profile scope            | CI: phase-verify.yml, ci.yml | -- | --     | --       | --   | --          |
| V2   | Florida plan scope                             | CI: phase-verify.yml | --  | --             | --       | --   | --          |
| V3   | Rules, tables, vocabulary scope                | CI: phase-verify.yml, ci.yml | -- | --     | --       | --   | --          |
| V4   | Connector at scale scope                       | CI: phase-verify.yml, ci.yml | -- | --     | --       | --   | --          |
| V5   | Semantics and coverage statistics scope        | CI: phase-verify.yml, ci.yml | -- | --     | --       | --   | --          |
| V6   | Engine at scale scope                          | CI: phase-verify.yml, ci.yml | -- | --     | --       | --   | --          |
| V7   | Public surfaces scope                          | CI: phase-verify.yml, ci.yml | -- | --     | --       | --   | --          |
| V8   | CI integration                                 | CI: phase-verify.yml | --  | --             | --       | --   | --          |

Backups (same platform rules, different provider): GPT-6 Sol on Codex at
Intelligence Extra High for Steps 1, 3, 4, 5, and 6, at Intelligence High for
Step 7, and at Intelligence Medium for Step 8; GPT-6 Astra on Codex at
Intelligence Extra High for Step 2. Both run on the $100 ChatGPT Pro 5x pool,
the operator's deliberate second funded pool for a Claude outage or a `tight`
or `exhausted` Claude weekly pool; neither is a `*-codex` variant, which the
operator's ChatGPT-account Codex sign-in cannot run.

---

## Model selection blocks

**Selection method.** Each block below was produced by running the selector in
`planning/model-selector.txt` against `planning/user-context.md` and the prices
in `planning/model-tier-cost-scale.md`, with the kit exported by roadmodel
0.2.65 — the release on PyPI, in `uv.lock`, in `.venv`, and in the committed
`planning/` on 2026-10-04 (`uv run poe kit` changed nothing) — in the
selector's own step order. Its Step 0a dropped no model (the cold-start
availability list is empty and no runtime override was supplied); Step 0b
dropped every `cn`-jurisdiction model (Kimi, DeepSeek, GLM) under the default
allowed list `us, eu, uk, ca, au, jp, kr`; Grok stays unreachable (no xAI key)
and the Cursor-only models unfunded (no Cursor subscription, no OpenRouter
key), and Muse Spark 1.3 — S-tier in coding at $4.25 — is A-tier in knowledge,
planning, and agentic work, so it fails a knowledge PRIMARY and never survives
a coding step's SECONDARY ranking. Steps 1–3 of the selector rated this
roadmap's Steps 1–7 High complexity (S required in the PRIMARY category) and
Step 8 Medium. For the
knowledge-PRIMARY Steps 1–3, only Opus 5.5 and Fable 5.1 are S-tier in
knowledge; they tie on the SECONDARY rating and on coverage, and the Step 5
output-price tie-breaker keeps Opus 5.5 ($20 against $50). For the
coding-PRIMARY steps, the S-tier coders are Opus 5.5, Sonnet 5.5, Fable 5.1,
GPT-6 Sol, GPT-6 Astra, and Muse Spark 1.3: with a `knowledge` SECONDARY (Step
5) only Opus 5.5 and Fable 5.1 are S-tier there and price keeps Opus 5.5; with
an `agentic` SECONDARY (Steps 4, 6, 7) Sonnet 5.5, Opus 5.5, Fable 5.1, GPT-6
Sol, and GPT-6 Astra are S-tier, and the coverage tie-break selects Sonnet 5.5
(S or A in all seven categories against six for Opus 5.5, Fable 5.1, and GPT-6
Sol), which the `balanced` posture's close-quality rule confirms ($10 against
$20 output, AA Intelligence Index 56.0 against 57.6). The picks were
cross-checked against `roadmodel score` — the deterministic scoring core shipped
with the same release, run locally with no engine or network call: it ranks
Opus 5.5 first for `knowledge` at High (with or without novelty) and for
`planning` at High with novelty, Sonnet 5.5 first for `coding` at High (80.4
against 79.6), and Opus 5.5 0.5 points ahead of Sonnet 5.5 for `coding` at High
with novelty — a gap inside the close-quality band, where the selector's
coverage rule decides for Sonnet 5.5 (Steps 4 and 6). The operator's `balanced`
posture names Claude Code's default model at its default effort as the anchor
for Medium work, so Step 8 runs Opus 5.5 at `Medium` as opened. Access
selection Step C ranked `claude-code` first as subscription-funded (weekly pool
at `headroom`; the dated `Resets` cells of `planning/user-context.md` have
passed, so every row reads `headroom`); Step D's platform order kept Claude
Code ahead of Codex; Step E applied the `capped` consumption posture, which
closes the flat-funding gate and makes the complexity ladder the final effort:
`Extra High` for the four steps with novel problem-solving or multi-step proof
(Steps 3–6) and for the two knowledge steps of cross-cutting scope (Steps 1 and
2, one rung above `High`), `High` for Step 7, and `Medium` — Claude Code's
default for Opus 5.5 and Sonnet 5.5 — for Step 8. `Max` is claimed for no step:
none names reasoning depth as its demonstrated bottleneck, and `/roadmap-step`
would lower a top rung under the `capped` posture anyway. Step E2 emitted
`ORCHESTRATION: None` (no step is an exhaustive audit, review, or research
sweep; Step 2's research is bounded by the brief's candidates); Step F emitted
no MAX MODE line (Claude Code has no such dial). Step 7 of the selector named
each BACKUP from OpenAI, the operator's first backup provider: no other
provider is S-tier in knowledge, so the floor drops for Steps 1–3 and GPT-6 Sol
(S-tier in coding and agentic work, the widest coverage among the S-tier GPT
coders) backs every step whose SECONDARY is `coding`, `agentic`, or
`knowledge`, while GPT-6 Astra — the one A-tier knowledge GPT model that is
S-tier in planning — backs Step 2. The parent roadmap's §8 row assigned Opus 5
with Fable 5.1 for the attribution rules; the catalog has since superseded Opus
5 by Opus 5.5, and the selector's price tie-breaker removes Fable 5.1 wherever
it ties Opus 5.5, so Step 1's status commit rewrites that row.

```text
PROMPT: Step 1 — Cook County Source Due Diligence, the Streamed Fetch, and the Value-Set Profile
MODEL: Opus 5.5
BACKUP: GPT-6 Sol
PLATFORM: Claude Code
EFFORT: XHigh
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: knowledge — grounded due diligence of a real source's terms, fields, and keys, with a rebuilt streaming fetch path as the coding secondary. PICK: Opus 5.5 is S-tier in knowledge (HLE 61.4% at max) and S-tier in coding, and beats the tied Fable 5.1 on output price. EFFORT: Extra High with thinking on — High complexity plus one rung for a knowledge task of cross-cutting scope; orchestration None for one scoped deliverable.

PROMPT: Step 2 — Florida Source Research and the Lawful Acquisition Plan
MODEL: Opus 5.5
BACKUP: GPT-6 Astra
PLATFORM: Claude Code
EFFORT: XHigh
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: knowledge — cited research of Florida's statewide and county court-data access, legal framework, and costs, with a scored selection and plan as the planning secondary. PICK: Opus 5.5 is S-tier in knowledge (HLE 61.4% at max) and S-tier in planning, and beats the tied Fable 5.1 on output price. EFFORT: Extra High with thinking on — High complexity plus one rung for a knowledge task of cross-cutting scope; orchestration None, since the research is bounded.

PROMPT: Step 3 — Mapping and Attribution Rules, the Judge and Court Tables, and Vocabulary 3
MODEL: Opus 5.5
BACKUP: GPT-6 Sol
PLATFORM: Claude Code
EFFORT: XHigh
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: knowledge — attributing every real disposition, reason, bond, and sentence code to the actor who made it, with versioned tables and validators as the coding secondary. PICK: Opus 5.5 is S-tier in knowledge (HLE 61.4% at max) and S-tier in coding, and beats the tied Fable 5.1 on output price. EFFORT: Extra High with thinking on for novel problem-solving and multi-step verification against the profile, vocabulary, and specification; orchestration None.

PROMPT: Step 4 — The Cook County Connector at Corpus Scale
MODEL: Sonnet 5.5
BACKUP: GPT-6 Sol
PLATFORM: Claude Code
EFFORT: XHigh
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: coding — a five-dataset real connector and a runner, publisher, and resolution rework for a hundredfold corpus, with long-running ingests as the agentic secondary. PICK: Sonnet 5.5 is S-tier in coding (AA Intelligence Index 56.0 at max) and wins the S-tier field on coverage, confirmed by the balanced close-quality rule against Opus 5.5. EFFORT: Extra High with thinking on for novel problem-solving and chain-of-thought across many files; orchestration None.

PROMPT: Step 5 — Real-Data Metric Semantics, Calendar Periods, and Coverage Statistics
MODEL: Opus 5.5
BACKUP: GPT-6 Sol
PLATFORM: Claude Code
EFFORT: XHigh
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: coding — a new gate, no-figure semantics, calendar cohorts, verified coverage statistics, and a per-source specification, with statistical semantics as the knowledge secondary. PICK: Opus 5.5 is S-tier in coding and S-tier in knowledge (AA Intelligence Index 57.6 at max), and beats the tied Fable 5.1 on output price. EFFORT: Extra High with thinking on for multi-step proof (golden equality, period consistency, verification); orchestration None.

PROMPT: Step 6 — The Metrics Engine at Corpus Scale
MODEL: Sonnet 5.5
BACKUP: GPT-6 Sol
PLATFORM: Claude Code
EFFORT: XHigh
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: coding — member storage, a vectorized estimator, a streamed export, and a paged trace under an equivalence proof, with full-corpus runs as the agentic secondary. PICK: Sonnet 5.5 is S-tier in coding (AA Intelligence Index 56.0 at max) and wins the S-tier field on coverage, confirmed by the balanced close-quality rule. EFFORT: Extra High with thinking on for novel problem-solving and cross-file proof that no figure moves; orchestration None.

PROMPT: Step 7 — Public Surfaces for the First Real Source
MODEL: Sonnet 5.5
BACKUP: GPT-6 Sol
PLATFORM: Claude Code
EFFORT: High
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: coding — schemas, routes, the generated client, pages, and browser suites for real data under the presentation rules, with the e2e job as the agentic secondary. PICK: Sonnet 5.5 is S-tier in coding (AA Intelligence Index 56.0 at max) and leads the deterministic scoring core for High coding (80.4 against Opus 5.5's 79.6). EFFORT: High with thinking on for the High-complexity rung without novel problem-solving; orchestration None.

PROMPT: Step 8 — QA + verify_phase05.py
MODEL: Opus 5.5
BACKUP: GPT-6 Sol
PLATFORM: Claude Code
EFFORT: Medium
THINKING: On
ORCHESTRATION: None
CONVERSATION: New
RATIONALE: TASK: Medium-complexity mechanical translation of the Steps 1–7 deliverables into numbered static checks, modes, probes, and a CI matrix entry, following verify_phase04.py. PICK: Opus 5.5 is S-tier in coding (AA Intelligence Index 57.6 at max) and Claude Code's default, the balanced anchor for Medium work under the capped posture. EFFORT: Medium (the default, run as opened) with thinking on because the pattern is fixed and CI catches slips; orchestration None.
```

---

## Not in scope (from product roadmap)

Per [`ROADMAP.md`](ROADMAP.md) Phase 5, Phases 6–9, §6 "Out of Scope", and the
Phase 4 carry-over checklist:

- Cross-case outcomes for Cook County — new case, new charge, reconviction —
  and the brief's preferred first real metric built on them: the source has no
  cross-case person key (measured while planning; verified in Step 1), so they
  are published as not observable; the Florida pilot (Phase 7 §7.1), selected
  with a lawful cross-case key weighted, is the first candidate to carry them.
- Adjusted (observed to expected) figures on real data: no target the
  specification supports is attributable to a Cook County judge; Step 5 opens
  the issue for a judge-attributed sentencing or disposition target, which
  needs planted effects and a recovery test first (Phase 6 or 7).
- The fairness analysis over the real restricted attributes, and any
  publication of it: Phase 6 §6.4's written go/no-go first, then §6.1.
- The validation of the model, the attribution rules, and the coverage on real
  data — the audit samples, the attribution check against source documents, the
  missingness and calibration analyses — Phase 6 §6.1.
- Administrative authentication, the in-database judge review queue and its
  decisions, unmerge and `er review decide` behind that authentication, source
  retirement in production, the corrections reader, envelope or asymmetric
  encryption for correction contacts, rapid suppression, moving the other
  restricted tables into the `restricted` schema, a restricted snapshot freezing
  the attributes the fairness analysis reads, and the adjusted-interval choice
  of Phase 4 finding 3.1; Phase 6.
- Person-linkage false-positive and false-negative estimates for Cook County:
  with a per-case key there is no cross-case linkage to estimate; Phase 6
  records that and estimates linkage for the first source that links.
- The Florida connector (Phase 7 §7.1) and the follow-ups of the requests
  submitted in Step 2 (operator wall-clock work overlapping Phases 6 and 7);
  probabilistic entity resolution (Phase 7 §7.3); jurisdiction trends and the
  coverage map (Phase 7 §7.4).
- The object-store variant of snapshots and artifacts, a scheduled `metrics
  verify` and `models verify`, the full compute after every ingest, edge rate
  limits and `JUDGEMETRICS_TRUST_PROXY` behind the production proxy, and the
  `[project].version` bump; Phase 8.
- Any snapshot bundle or paid tier that includes Cook County data; Phase 9, and
  only once the operator has settled question 2 and the source's
  **Redistribution** answers permit the tier.
- Any composite, ideological, partisan, or "best/worst judge" score; excluded
  permanently.

Additionally not in scope for this phase:

- The archived pre-2018-02-13 Cook County datasets: recorded in the register,
  not fetched; if Step 1 finds records in them that the current datasets lack,
  that is a data-access question in `docs/ROADMAP.md`.
- The SAO's dashboards for 2025 onward: no bulk export, so not a source.
- Linking Cook County participants across cases by any other signal: the
  datasets carry no name or date of birth, and a demographic attribute is never
  a linkage key.
- A judge-by-court subject that computes a judge's figures over one court's
  cases only: compare flags a judge who sat in several courts instead; a
  per-court observation is a registry change for a later phase if wanted.
- Court- and jurisdiction-level adjusted measures (excluded by design in Phase
  4) and a period for the Pretrial Fairness Act regime finer than calendar
  years (the methodology states the regime change within 2023).
- Re-hashing the synthetic source's participant identifiers into the
  source-qualified form: it needs the raw values re-read and moves every
  synthetic person; an architectural question for Phase 7's cross-source
  resolution.

---

_This roadmap is the execution plan for Phase 5. Each step's `**Status:**` line
is flipped by that step's own PR (Status rule), so this file on `main` is the
phase's ledger — `grep -n '^\*\*Status:\*\*'` reports progress. After all steps
and verification pass, and every finding has a destination, Phase 5 is complete
— declared with the line "Phase 5 is complete. You can now move on to Phase 6."
and nothing after it — and Phase 6 (Methodological Validation, Admin Tools, and
Trust) inherits the real Cook County corpus with its versioned attribution,
pretrial, sentence, offense, court, and judge tables to validate against source
documents, the coverage statistics and unknown-actor share it audits, the real
restricted attributes its legal review must clear before any fairness analysis
is published, the judge review rows its admin queue takes over, the scale
budgets it measures against, and the Florida requests whose answers Phase 7's
pilot connector needs._
