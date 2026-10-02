<!-- docs/phase04-qa-findings.md -->
# Phase 4 — QA findings

The rollup of every finding surfaced while executing Phase 4 (Steps 1
through 6 of [`phase04-roadmap.md`](roadmap/phase04-roadmap.md)), classified
per `ROADMAP.md` §5 "Defect handling & triage", with the guard each one
left behind ("prevent the class, not the instance"). Findings recorded
elsewhere at the time (pull-request bodies #37, #39, #41, #43, #44,
`docs/ROADMAP.md` known issues, `AGENTS.md` decisions) are gathered here so
the phase has one QA record; the guard column names the test, hook, CI
job, or verify-script check that now catches a recurrence, and every
finding has a destination: fixed, an issue, or a named phase that owns it.

Verification lives in `scripts/verify_phase04.py` (50 static checks, the
tool suites, the first-milestone setup, the seed and compute idempotency
probes, `metrics verify`, `models verify --refit`, `validation report
--check`, `validation recovery`, the adjusted provenance trace probe, and
the V1–V6 matrix; see "Step 6" below) and runs in CI through
`.github/workflows/phase-verify.yml` as the required check
`phase-verify (04)`.

## Step 1 — Planted effects, restricted attributes, the restricted schema

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 1.1 | `verify_phase03.py` check 14 compared the golden manifest with a literal `"2"`, so this phase's version bump failed an earlier phase's required check. | Process improvement (fixed in-step) | Check 14 reads `GENERATOR_VERSION`/`TRUTH_VERSION` from the source; `verify_phase04.py` check 11 keeps it so, and every Phase 4 version check is a `>=` against the source constant (Step 6 finding 6.3). |
| 1.2 | The step's literal deferral rule ("move the start to the end of any term that contains it") would have dropped the disposition kind's own-term deferral, because a sentence always follows its disposition. | Data-semantics finding | Methodology `0.2` "Exposure": the disposition kind first moves to its own term's end, then every kind applies the containment chain; engine and truth implement it independently (`test_exposure_deferral.py`, `test_frame_invariants.py`); static check 10. |
| 1.3 | Eighteen registry eligibility sentences restated the old exposure rule. | Data-semantics finding | Corrected in place without an entry or registry bump (`sync_definitions` updates rows in place); methodology `0.2` records the semantic change (`AGENTS.md`). |
| 1.4 | Without an observable term in the next filing's exponent the docket tilt had nothing to select on and raw new-case rates ranked the planted effects as well as any adjustment could. | Judgement call | `3.0·R` joins the exponent (documented departure, `docs/SYNTHETIC_DATA.md` "Planted effects"); `test_synthetic_effects.py` asserts confounding (24 inverted same-court pairs on the demo world). |
| 1.5 | The oracle's semantics: exact for the draws a judge's effect enters, other cases' outcomes as realized. | Judgement call | `truth/effects.json` `definitions`; totals within 1.6% on the demo world (`test_synthetic_effects.py`); static check 3. |
| 1.6 | `CREATE SCHEMA` needs `CREATE` on the database, which the admin role lacked. | Architectural question (resolved) | `02-roles.sql` (fresh volume) and the rerunning `03-test-database.sql` (existing volume) grant it; `uv run poe up` precedes the first `poe migrate` (`AGENTS.md`). |
| 1.7 | Run-level data-quality issues (`source_record_id` NULL) were never purged by the test fixtures and leaked into later modules' issue counts. | Implementation bug (test infrastructure, fixed in-step) | `purge_source` removes them; the underlying gap (a run-level issue has no run link) is a `docs/ROADMAP.md` known issue owned by Phase 6's data-quality triage. |
| 1.8 | `test_every_name_token_is_listed` used a string prefix that the listed word "Honeydew" tripped. | Implementation bug (fixed in-step) | The test checks the first token. |
| 1.9 | The ambiguous-pair plant scanned every case per person (9 of 10 s of a demo build). | Implementation bug (performance, fixed in-step) | Indexed in one pass with identical output (golden byte identity). |
| 1.10 | `seed` over a database holding an older generator version's dataset leaves stale rows and re-keyed ids. | Data-integrity finding | Issue [#36](https://github.com/nathanramoscfa/judge-metrics/issues/36); `docs/ROADMAP.md` known issues; owned by Phase 5 (the first real connector's re-ingest semantics). |
| 1.11 | The ambiguous same-date-of-birth plant rewrites a date of birth after the draws, so that person's published age band can differ from its draws' band. | Known limitation | `docs/SYNTHETIC_DATA.md`, `docs/ROADMAP.md`. |
| 1.12 | The first CI run failed the gate on advisories published after `main` was last green: `virtualenv` (PYSEC-2026-4011..4014) and a critical Next.js RCE (GHSA-vcvr-r3jv-pc5j). | Security finding (fixed in-step) | `virtualenv` 21.14.1, `next` and `eslint-config-next` 16.3.8; `pip-audit --strict` and `pnpm audit --audit-level=high` in the gate, CI, and `--security`. |
| 1.13 | A local pre-push `pip-audit` failed on a truncated download replayed from the pip HTTP cache. | Process improvement (environmental) | Purge the cache (recorded in the maintainer's notes); no repository change. |
| 1.14 | Notes for Steps 2 and 3: history features at 00:00 UTC of the filing date; the calibration numbers bound the `recovery` tolerances. | Process improvement | Written into the Step 2 and Step 3 task blocks before they ran. |

## Step 2 — Feature specification, leakage review, baseline model

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 2.1 | The "latest disposed charge" rule for a pending prior case reads whether a later charge was disposed — leakage. | Data-semantics finding | A prior case is pending when a charge filed before the filing was pending then or none was disposed before it (`outcome_model.yaml` `pending_case`); `test_feature_leakage.py` (a deliberately leaky feature fails 40 of 40 seeds); the demo world matches the generator on all 4,534 decisions (`test_adjustment_features.py`). |
| 2.2 | The index case's own charges are filed later on the filing day, so a "before the filing" rule would read none of them. | Data-semantics finding (clarification) | The case's own features are known at the pretrial decision, history at the filing (`known_at` per feature; static check 13). |
| 2.3 | The events-per-column gate is ambiguous about "events" and the design width. | Judgement call | The limiting class against every column including the intercept; every golden model `insufficient_events`, every demo model `fitted` (`test_outcome_models.py`). |
| 2.4 | An unpenalized fit of separated data reports convergence at a runaway coefficient (the gradient vanishes). | Process improvement | Only the calibration slope is unpenalized (`AGENTS.md`); `test_logistic.py` covers separation. |
| 2.5 | The new-case models transport poorly out of time (test AUC 0.49–0.55) while the release model transports well (AUC 0.81). | Diagnostic finding | Carried to Step 4, which traced it to a generator artifact (finding 4.4). |
| 2.6 | The bootstrap cluster key is the person's earliest `<filed_at>|<source_row_id>`, which a source whose charge ids restart per case would collide on. | Known limitation | `docs/ROADMAP.md`; revisited with the first real connector in Phase 5 (carry-over item 8). |
| 2.7 | CLI tests from a module-scoped fixture saw a stale `get_settings` cache and parsed log lines mixed into `result.output`. | Process improvement | Clear `get_settings` first and parse `result.stdout` (`AGENTS.md`). |
| 2.8 | The README still described Phase 3 as in progress; `test_health.py` pinned the head at `0008`. | Implementation bug (fixed in-step) | Corrected; `test_health.py` pins the current head. |

## Step 3 — Expected counts, ratios, partial pooling, recovery

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 3.1 | The 95% bootstrap intervals cover the planted true ratio for only 60–68% of judges: the interval describes the pooled estimate, which is shrunk toward 1. | Data-semantics finding | The `recovery` tolerance `interval_coverage_minimum: 0.55`; methodology `1.0` describes the interval as one for the pooled estimate; `docs/VALIDATION.md` reports it; the choice of a different interval is an operator decision recorded in `docs/ROADMAP.md` and revisited by Phase 6's methodological validation. |
| 3.2 | The new-case adjustment beats the raw rates by only 0.003 in Spearman (the outcome is driven by latent propensity). | Expected limitation | `docs/SYNTHETIC_DATA.md` "Recovery", the specification's `recovery` comment; `test_golden_recovery.py` holds the margin. |
| 3.3 | Migration 0010 named its check constraints without `op.f()`, so the naming convention applied twice; `alembic check` does not compare check constraints. | Implementation bug (fixed in-step) | `op.f()` on every constraint name (`AGENTS.md`); static check 23. |
| 3.4 | The Step 4 context quoted a superseded "Interval" text, and the `e2e` job now fits during `metrics compute`. | Spec rot | The roadmap's Step 4 and Step 5 task blocks corrected before they ran. |
| 3.5 | Pipeline step 13 computes the descriptive kinds only, so a judge an ingest touches keeps its adjusted rows on the older snapshot until the next full compute. | Architectural question (resolved) | The documented exception to ROADMAP §5 "Performance rules" (static check 25; `test_golden_adjusted.py` asserts no step-13 publication); Phase 8 schedules the full compute after every ingest. |

## Step 4 — Validation report and methodology 1.0

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 4.1 | The age-band ratios rank the planted effects with Spearman 0.9 but 45–54 sits above 35–44 by chance. | Judgement call | The positive control asserts the extremes' direction and a Spearman of at least 0.8 (`test_subgroup_calibration.py`). |
| 4.2 | The step's restricted-reader patterns would miss a second reader that imports the ORM class `PartyAttribute`. | Security finding (design) | `test_restricted_readers.py` matches the class too; static check 31 mirrors it. |
| 4.3 | Missing-data sensitivity is exact on the synthetic source because no index event has a feature at a missing level. | Known limitation | Reported as found in `docs/VALIDATION.md`; Phase 6 §6.1 repeats the report on real data. |
| 4.4 | The new-case models' poor temporal transport is a generator artifact (next filing within the remaining corpus span). | Diagnostic finding | `docs/SYNTHETIC_DATA.md` "Temporal transport"; the report's per-year table; the specification is not tuned. |
| 4.5 | A reused snapshot row keeps the registry and methodology versions of its first compute after a bump. | Implementation bug (minor) | Issue [#42](https://github.com/nathanramoscfa/judge-metrics/issues/42); owned by Phase 5 (the next registry bump). |
| 4.6 | `models fit`'s text summary prints `fitted` twice (run count and status count). | Implementation bug (cosmetic) | Issue [#40](https://github.com/nathanramoscfa/judge-metrics/issues/40); owned by Phase 5. |
| 4.7 | A truth directory must never be compared with another dataset. | Security finding (design) | `--truth` is matched to its source by the manifest's sha256 among the retrieved artifacts; `validation recovery` exits 2 otherwise. |

## Step 5 — Risk-adjusted panels, adjusted compare, model card

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 5.1 | A containerized API could not read the compute's snapshot directory, so every adjusted provenance chain answered `complete: false`. | Implementation bug (fixed in-step) | The Compose `api` service mounts `./data/snapshots` read-only (hygiene test). |
| 5.2 | The seven-column adjusted compare table overflowed the page. | Implementation bug (fixed in-step) | Court and suppressed cells wrap; the method is stated once in the header (`compare-table` Vitest suite; screenshots). |
| 5.3 | A model card must disappear once no current observation cites its snapshot, but survive an ingest that moves only the descriptive kinds. | Judgement call | `GET /models/{id}` is a 404 only when no current observation cites the model's snapshot (`test_api_adjusted.py`). |
| 5.4 | `/metrics/compare`'s default sort must follow the kind. | Judgement call | `sort` defaults to `None` and resolves per kind (an OpenAPI `anyOf`; `test_openapi.py`). |
| 5.5 | The literal "95% bootstrap interval" lives in `lib/metrics.ts`, and `KIND_TEXT` moved out of the methodology page (a page module may export only Next's conventions). | Spec rot (for Step 6) | Written into the Step 6 context; checks 41 and 43 read the label from `lib/metrics.ts` and the section from the page. |

## Step 6 — Verification script

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 6.1 | The task's check 15 forbids naming `pickle`, `numpy.load`, or `eval(` under `metrics/`, but `artifacts.py`'s docstring names all three as what it never does (the Phase 3 finding 6.4 lesson: a guard must not trip on its own documentation). | Spec rot | Check 15 matches uses — an `import pickle`, a `pickle.<name>(` call, `np.load(`/`numpy.load(`, and a bare `eval(` — not mentions. |
| 6.2 | The helper that extracts one function's body stopped at a multi-line signature's closing `) -> None:` at column 0, so check 25 first failed on correct code. | Implementation bug (caught while writing) | The body runs to the next top-level `def`, `class`, decorator, comment, or name, never a bracket. |
| 6.3 | The task names exact versions in checks 1, 2, 3, 7, 8, 21, and 33 (`"3"`, version 2, `"1.0"`); a literal is what made Phase 3 check 14 fail in Step 1 (finding 1.1). | Process improvement | Every version check compares the source constant with a `>=` minimum, so a Phase 5 bump never fails `phase-verify (04)`. |
| 6.4 | The task lists `test_feature_leakage.py` among the Step 2 files without its directory; it is a property test (`tests/property/`). | Spec rot | Check 19 and V2.3 name `tests/property/test_feature_leakage.py`. |
| 6.5 | Phase 4's V-matrix has no row for the first-milestone items, so a failed `poe up` or `poe check` in `--post` would print `[FAIL]` and still exit 0. | Implementation bug (caught while writing) | An `M` row aggregates items 1–7, 17, the `bootstrap` rerun, and the seed probe into the summary, as Phase 3's V5.3 did. |
| 6.6 | Issues #36, #40, and #42 are open at the phase exit. | Process improvement | Each is owned by Phase 5 (carry-over item 9). |
| 6.7 | Alarm exercises: a deliberately broken static check pushed to the pull request must fail `phase-verify (04)` and `test`; a tampered adjusted observation must fail `metrics verify`; a changed model-artifact byte must fail `models verify`. | Process improvement (exercise, expected) | See "Alarm exercise" below. |

### Alarm exercise

**(a) The phase's required checks.** Recorded per the Step 6 plan
("break one static check on the PR, observe `phase-verify (04)` and
`test` fail, fix, observe both pass"):

| Event | Commit (PR #45) | `phase-verify (04)` | `test` |
|-------|-----------------|---------------------|--------|
| Deliberate break (check 45 → `docs/screenshots/phase04-step5-alarm-exercise/README.md`) | `91f1d81` | fail — `[FAIL] 45 … missing docs/screenshots/phase04-step5-alarm-exercise/README.md`, `FAILED: 45` (run 37017815741) | fail — `python` job: `test_verify_script_fast_exits_zero` (`passed 49 failed 1 … FAILED: 45`; 1 failed, 1,615 passed; run 37017815579); every other job green, `phase-verify (01)`–`(03)` included |
| Fix (check 45 restored) | `f108090` | pass (run 37019595323) | pass (run 37019595596) |

`phase-verify (04)` became a required context on `main` after that run
(`gh api -X PATCH …/protection/required_status_checks`, five contexts;
`CONTRIBUTING.md` "Repository settings").

**(b) The adjusted-observation alarm** (the Operations criterion's
health signal: `/api/v1/ready` `metrics.models` with `metrics verify`
green; its alarm: `metrics verify` non-zero). Run on 2026-10-02 against
the scratch database after `uv run poe bootstrap` there (role URLs
pointed at `JUDGEMETRICS_TEST_DATABASE_URL`, snapshots under
`data/snapshots/scratch-test-db`); one current, unsuppressed adjusted
observation had its `standardized_ratio` raised by 0.1 and then
restored:

```text
observation=015871a9-53d5-4dd0-9036-4574deddfb93 slug=failure_to_appear_observed_expected standardized_ratio=0.903772
tamper: observation=015871a9-53d5-4dd0-9036-4574deddfb93 standardized_ratio=1.003772
$ uv run judgemetrics metrics verify
snapshots=1 observations=3730 verified=3729 mismatches=1 unverifiable=0
mismatch: failure_to_appear_observed_expected judge:0e0679ca-51d3-4ae9-8729-39dad4f82175@730 column=standardized_ratio stored=1.003772 recomputed=0.903772 observation=015871a9-53d5-4dd0-9036-4574deddfb93
exit 1
restore: observation=015871a9-53d5-4dd0-9036-4574deddfb93 standardized_ratio=0.903772
$ uv run judgemetrics metrics verify
snapshots=1 observations=3730 verified=3730 mismatches=0 unverifiable=0
exit 0
```

The alarm names the observation by id, slug, subject, window, and
column. `test_golden_adjusted.py` keeps the tamper assertion in CI.

**(c) The model-artifact alarm.** Same environment; one byte of one
fitted model's artifact under `data/snapshots/scratch-test-db` was
changed and then restored:

```text
model=91115941-610c-4459-9cf9-69caab5ad525 artifact=<scratch>/a1703c955643…/models/02ac7c83e2eb….json bytes=254402
tamper: byte 250452 changed
$ uv run judgemetrics models verify
models=13 verified=12 refitted=0 problems=1
mismatch: model 91115941-610c-4459-9cf9-69caab5ad525 failure_to_appear@365 field=content_hash: the artifact does not hash to the row's content_hash
exit 1
restore: artifact bytes restored
$ uv run judgemetrics models verify
models=13 verified=13 refitted=0 problems=0
exit 0
```

`test_outcome_models.py` keeps the changed-byte assertion in CI. The
third alarm, `validation report --check` non-zero on drift, is
exercised by `test_validation_report.py` and runs in the `e2e` job.

**`--post` on the maintainer's machine** (2026-10-02, Windows, the
Compose services, `dev-api` and `pnpm dev` running, on PR #45 at
`f108090`; 1,054 s): **76 passed, 0 failed, 0 skipped.** 50/50 static
checks; items 1–5 (`uv sync`, `poe up`, `poe migrate`, `poe seed` on the
scratch database) and the `bootstrap` rerun; the seed probe (sixteen
tables' row counts unchanged, `metric_observation` 3,730, `outcome_model`
13); the compute probe (`models_fitted=0 models_read=13 observations=0
superseded=0 subjects_published=0 subjects_unchanged=29` on both runs);
`metrics verify`; `models verify --refit` (`models=13 verified=13
refitted=13 problems=0`); `validation report --check --truth
data/synthetic/20260916`; `validation recovery` (Spearman 0.934 release,
0.719 365-day new case, 0.963 365-day failure to appear; interval
coverage 0.60, 0.63, 0.68 — every tolerance met); the adjusted
provenance trace (`outcome model 6544e266…`, `complete: yes`); items 6–7;
Playwright (27 tests, `adjusted.spec.ts` included); the web suites (121
Vitest tests); the security gate; every V-check suite; item 17 (`poe
check`); and V1.1–V6.4 with V6.1 read from the PR's green `phase-verify
(04)`.

## Pre-ship items

Documented limitations at the Phase 4 exit (`v0.4.0-phase-4`); none
blocks the tag, each is on a later phase's plan:

- **Synthetic-only validation.** `docs/VALIDATION.md`, the recovery test,
  and the subgroup calibration validate the expected-outcome models on
  the labelled synthetic world, whose planted effects are the answer key;
  no figure is validated on real cohorts until Phase 6 §6.1 repeats the
  report on real data.
- **The age band is excluded by policy.** No restricted attribute is a
  model feature (the brief requires a documented methodological purpose,
  legal review, fairness analysis, and publication rationale first); the
  subgroup calibration measures the consequence in aggregate. Phase 6
  §6.4's legal review owns any change.
- **Intervals are conditional on the specification.** The 95% bootstrap
  interval describes the pooled estimate under `expected-logit-v1` and
  its feature set; it carries neither model-specification uncertainty
  nor the shrinkage bias of finding 3.1 (coverage of the true ratio
  60–68% on the demo world).
- **The step-13 exception.** An ingest recomputes the descriptive kinds
  only; a touched judge's adjusted observations stay on the older
  snapshot until the next full `metrics compute` (finding 3.5), until
  Phase 8 schedules one after every ingest.
- **Thresholds chosen before real data.** The adjusted suppression
  threshold (30), the minimum expected count (5), the events-per-column
  gate (5), and the descriptive thresholds (10) were fixed on synthetic
  data; Phase 5 revisits them per metric against real cohorts.
- **Synthetic case data only.** Every case-level number, adjusted or
  not, is computed over the labelled synthetic dataset; real data begins
  in Phase 5.

## Phase 5 carry-over checklist

Each item becomes an issue or a step item in the Phase 5 (or the named
later) roadmap, never silent work:

1. Per-metric suppression thresholds and the cohort-size question of
   Phase 3 finding 3.5, revisited with Cook County's cohorts (Phase 3
   carry-over item 4).
2. Parent-case data-quality checks across runs (Phase 3 carry-over item
   7) — the first step that ships a child-only export.
3. Member rows once per metric with per-window flags if Cook County
   scale needs it (Phase 3 carry-over item 9) — Phase 5 or Phase 8.
4. The refit of the expected-outcome model on real data under a
   specification `version` bump, with per-metric thresholds and the
   events-per-column gate revisited.
5. Cook County's restricted attributes (race, gender, age) into
   `restricted.party_attribute` through the ingest role only, and the
   fairness analysis on real data — with Phase 6 §6.1's methodological
   validation and §6.4's legal review.
6. Calendar-period cohorts and the compare page's calendar-period filter
   (deferred from Phase 4: per-period adjusted cohorts fall below 30 at
   demo scale).
7. A real connector's `case_party.source_row_id` must never hold a
   source identifier (the synthetic connector keys parties
   `<party_type>:<ordinal>` since Step 1); the bootstrap cluster key of
   finding 2.6 revisited for a source whose charge ids restart per case.
8. `verify_phase05.py` follows this script's pattern, joins the
   `phase-verify.yml` matrix as `"05"`, compares versions as `>=`
   minimums, and asserts earlier phases' OpenAPI paths and matrix entries
   as subsets.
9. Open issues #36 (seed over an older generator version), #40 (`models
   fit` summary), and #42 (a reused snapshot's versions).
10. Owned by later phases, named here so none is silent: Phase 6 — the
    real-data validation (§6.1), the legal review of restricted
    attributes (§6.4), the adjusted-interval choice of finding 3.1,
    administrative authentication, the corrections reader, envelope or
    asymmetric encryption for correction contacts, unmerge, a restricted
    snapshot for the fairness analysis, and moving the other restricted
    tables into the `restricted` schema; Phase 7 — the probabilistic
    entity-resolution scorer; Phase 8 — the object-store snapshot and
    artifact variant, a scheduled `metrics verify` and `models verify`,
    the full compute after every ingest, edge rate limits and
    `JUDGEMETRICS_TRUST_PROXY`, and the `[project].version` bump.
