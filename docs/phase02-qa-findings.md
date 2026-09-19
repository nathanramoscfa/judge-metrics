<!-- docs/phase02-qa-findings.md -->
# Phase 2 — QA findings

The rollup of every finding surfaced while executing Phase 2 (Steps 1
through 6 of [`phase02-roadmap.md`](phase02-roadmap.md)), classified
per `ROADMAP.md` §5 "Defect handling & triage", with the guard each one
left behind ("prevent the class, not the instance"). Findings recorded
elsewhere at the time (pull-request bodies #12–#17, `docs/ROADMAP.md`
known issues, `AGENTS.md` decisions) are gathered here so the phase has
one QA record; the guard column names the test, hook, CI job, or
verify-script check that now catches a recurrence.

Verification lives in `scripts/verify_phase02.py` (44 static checks,
the tool suites, the seed idempotency probe, and the V1–V6 matrix; see
"Step 6" below) and runs in CI through
`.github/workflows/phase-verify.yml` as the required check
`phase-verify (02)`.

## Step 1 — Deterministic synthetic generator

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 1.1 | gitleaks (the CI `security` job) flagged the `hashed_secret` sha1 fingerprints that `detect-secrets` writes into `.secrets.baseline` for every allowlisted false positive (rule `generic-api-key`), so the documented "add a false positive to the baseline" procedure could never pass CI once the baseline held an entry. | Security finding (scanner reconciliation) | `.gitleaks.toml` extends the default rules and allowlists `.secrets.baseline` only; gitleaks (CLI and action) auto-detects it at the repository root; verified over the same commit range (15 findings before, none after). Recorded in `AGENTS.md`. |
| 1.2 | `detect-secrets` flags the 64-character sha256 digests in `tests/fixtures/golden/manifest.json` as high-entropy strings, so every golden regeneration would trip the pre-commit gate. | Security finding (false positive) | The baseline is refreshed by scanning only the manifest (`docs/SYNTHETIC_DATA.md` "Regenerating the golden fixture"), with forward slashes in its `filename` entries so the same baseline matches on Windows and Ubuntu; static check 5 proves the tracked fixture files still match the manifest's digests. |
| 1.3 | `random.Random` is the one place the generator draws entropy from, and both scanners (ruff S311, bandit B311) flag it as a non-cryptographic generator. | Security finding (expected, simulation only) | Constructed once in `rng.py` with `# noqa: S311 # nosec B311` and a justification; static check 3 rejects any `datetime.now()`, `uuid4()`, `os.urandom()`, or module-level `random.*()` call anywhere in `synthetic/`. |
| 1.4 | `truth/metrics.json` computes the windowed outcome rates on the pretrial-release index only; disposition- and sentence-indexed rates and time-at-risk deferral after incarceration are not modelled; `age_at_filing` is filled even when a date of birth is missing; a revocation is recorded after its case closed. | Data-semantics finding | Recorded in `docs/ROADMAP.md` known issues; each arrives under a new `TRUTH_VERSION` when Phase 3's registry defines the metric (carry-over item 2 below); `test_golden_fixture.py` fails on a `TRUTH_VERSION` bump without regeneration. |
| 1.5 | Synthetic names could drift toward real people if a word list were ever seeded from a name corpus. | Security finding (design) | `wordlists.py` holds dictionary tokens only (reviewed against real names); `test_synthetic_generator.py` asserts every generated name is composed from those lists; the root roadmap's Phase 2 security criterion names the rule. |

## Step 2 — Synthetic connector, case-level publishing, `seed`

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 2.1 | The task block hashed the participant id as `<court_code>:<participant_id>`, but the generator assigns one `PT-` id per person across courts, so a court prefix would split every multi-court person into pairs `truth/` does not list. | Spec rot | Patched in the Step 2 task block: the id is hashed in the namespace the source assigns; `test_synthetic_ingest.py` and `test_golden_resolution.py` compare against `truth/persons.csv`, which would fail on any prefixing. Recorded in `AGENTS.md`. |
| 2.2 | The task block pointed `--from-fixture` at `tests/fixtures/golden/source`, but `manifest.json` sits beside `source/`, not inside it. | Spec rot | The connector reads the dataset root; the runner's fixture reader accepts contained relative ids; static check 33 requires the `e2e` job to ingest `tests/fixtures/golden`; the golden README was corrected in Step 5. |
| 2.3 | The brief's field list has no per-charge disposition actor, but the judicial-dismissal rule must be evaluated per charge (a prosecutor's dismissal beside a judge's disposition in one case). | Data-semantics finding | `charge.disposition_actor` (revision 0003) is a documented departure (`docs/DATA_MODEL.md`); `test_synthetic_ingest.py` asserts prosecutor dismissals keep `actor_type = prosecutor`. |
| 2.4 | Person identifiers (name, date of birth, participant id) must never reach the database or a log line in clear text. | Security finding (design) | `security/identifiers.py` writes peppered sha256 hashes only, to the restricted `person_identifier` table; `person` has no name or date column; the scrubber denylist covers `pepper`, `identifier_pepper`, `value_hash`, `date_of_birth`, `full_name` (static check 17); `describe_key` renders person-keyed drafts without the hash; `test_synthetic_ingest.py` scans every log line. |
| 2.5 | `JUDGEMETRICS_IDENTIFIER_PEPPER` is a deployment secret every hashing process needs; a missing pepper must fail the run rather than hash with an empty one. | Security finding (design) | `ingest run` and `seed` refuse to start without it (`IdentifierPepperMissingError`); `.env.example` documents a placeholder (static check 15); the tests set a fixed constant. |
| 2.6 | Case-level data-quality checks that need a parent case's filing date or status see only the cases drafted in the same run. | Implementation gap (deferred) | Recorded in `docs/ROADMAP.md` known issues; the step that first ships a child-only export reads the parent case from the database. |
| 2.7 | The log scrubber redacts any key containing `person_id`, which includes the table name `person_identifier`, so the run log's per-table counts would be redacted for that table. | Implementation bug (caught while writing) | The run log reports that table's counts under `identifier_hashes`; recorded in `docs/ROADMAP.md`. |
| 2.8 | Case numbers with different separators (`syn 2019 000013`, `SYN-2019-000013`) are the same case; the Phase 1 strip-everything rule made the key unreadable. | Data-semantics finding | `normalization/case_numbers.py` collapses every run of whitespace or punctuation to one `-`; `test_case_numbers.py` (unit and property) pins the invariant. |

## Step 3 — Entity-resolution framework v0, review queue, audit log

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 3.1 | The rule stage reads case linkage (`shared_case`, `related_case_link`, `same_court`) from published rows, so resolution cannot run entirely at the runner's step 10 as the task block assumed. | Architectural question (resolved) | The hook is split: identity at step 10 (`resolve_persons`), candidates and merges right after step 12 (`resolve_candidates`), both inside the run's single transaction; one feature code path for the hook and `er run`. Documented in `docs/ARCHITECTURE.md` and `docs/ENTITY_RESOLUTION.md`. |
| 3.2 | A rule that matched on a shared name alone would violate the brief's "never merge persons on name alone". | Security finding (design) | `rules.py` rejects name-only pairs (`name_only`, 0.10) and pairs with a differing date of birth (0.02); static check 22 requires the guard comment and the rejection; `test_er_rules.py` and `test_golden_resolution.py` assert the name-only golden pair is rejected. |
| 3.3 | Candidate features, review output, and audit payloads could leak a hash, name, date, or participant id. | Security finding (design) | Features are computed from hash equality and the published linkage and carry booleans and day counts only; `test_er_features.py` and `test_entity_resolution.py` scan the JSON and the `er review list` output. |
| 3.4 | A rerun (system decision) must never overwrite a human reviewer's decision, and an audit row must never be altered. | Process improvement | `candidates.py` keeps any `decided_by` not starting with `system:`; `audit_log` is append-only by trigger for every role (static check 21); `test_migrations.py` proves UPDATE and DELETE raise for the admin role. |
| 3.5 | There is no unmerge, and `er review decide` has no authenticated reviewer identity. | Architectural question (deferred) | `er review decide` is refused in production until Phase 6's admin authentication; the reviewer is a command-line label; recorded in `docs/ROADMAP.md` known issues and carry-over items 3 and 5 below. |
| 3.6 | Resolution scores are the rule set's ordinal labels, not calibrated probabilities. | Data-semantics finding | Documented in `docs/ENTITY_RESOLUTION.md`; `MODEL_VERSION` bumps whenever a rule, score, or threshold changes and old rows stay as history; the probabilistic scorer is Phase 7 (carry-over item 4). |
| 3.7 | Integration tests that purge synthetic persons hit the self-referential `merged_into_person_id` foreign key (RESTRICT) and the append-only audit log. | Implementation bug (test hygiene) | Purges null `merged_into_person_id` and delete candidates first; audit rows are written only inside rolled-back sessions; the shared `purge_source` helper in `tests/integration/conftest.py`. |

## Step 4 — Case API, case pages, coverage v0

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 4.1 | The task block budgeted a case detail at four statements, but six collections cannot load in four without a cartesian product or a JSON aggregate. | Spec rot | Patched: one explicit statement per case-level table plus provenance (eight, a constant); `test_query_counts.py` bounds detail and timeline at 8 on the busiest golden case, judge cases at 2, coverage at 3, judge detail at 4. |
| 4.2 | `verify_phase01.py` check 29 asserted the exact Phase 1 OpenAPI path set, so the required `phase-verify (01)` check would have failed on any later phase's route. | Process improvement | Check 29 asserts the Phase 1 paths are a subset; `verify_phase02.py` check 27 asserts the Phase 2 paths are a subset for the same reason (the task block said "exactly"; the exact current set is `test_openapi.py`'s job, updated with each route), so no later phase edits an earlier phase's required check. |
| 4.3 | `test_entity_resolution.py` counted every `er.merge` audit row in the database, which the committed golden ingests of the API tests (and the demo seed) break. | Implementation bug (blocking) | The count is scoped to the persons this ingest kept; the module-scoped `golden_fixture` purges the `synthetic` source before and after. |
| 4.4 | The `synthetic` flag could be derived from a column of the row and drift from the source's type. | Security finding (design, labelling) | Derived per row from `source.source_type == SYNTHETIC_SOURCE_TYPE` through a join in the same statement; static check 29 requires `Provenance.synthetic`; static check 31 the banner in the root layout; Vitest asserts the banner only on `synthetic_present` and never on a failed fetch. |
| 4.5 | The golden fixture (CI) and the demo seed (a developer's machine) name different judges, so a Playwright scenario naming one would pass in one environment and fail in the other. | Process improvement | The case flow discovers a synthetic judge and case through the API; static check 32 requires the `/cases/` scenario; the `e2e` job ingests the golden fixture after the FJC fixture (static check 33). |
| 4.6 | The demo-data banner reads `/coverage` on every request from the root layout, so no page is prerendered and each view costs one extra API call. | Architectural question (deferred) | Recorded in `docs/ROADMAP.md` known issues; a cached read is a later improvement. |
| 4.7 | `/judges/{id}/cases` validates `status` and `case_type` by shape, not against the vocabulary file. | Data-semantics finding | Documented; a value outside the vocabulary matches nothing rather than answering 422; the web form offers only the vocabulary. |

## Step 5 — Property tests, golden suite, scratch test database

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 5.1 | The property tests found `tiny`-scale seeds (5 of 3,000) whose world holds no two unused persons in disjoint courts, so the same-date-of-birth ambiguous plant raised `GenerationError`. | Implementation bug (found by property testing) | `edge_cases.py` falls back to a same-court pair (still `review`) with its own `expected_behaviour` text; extra draws happen only on the fallback path, so no previously generated dataset changed (no `GENERATOR_VERSION` bump; the golden byte comparison proves it); a unit test pins seed 511. |
| 5.2 | Phase 1 finding 2.5 carried forward: the migration round trip and every fixture ingest ran on the configured database, so `uv run poe check` emptied a local live ingest and the demo seed. | Process improvement (Phase 1 carry-over closed) | The scratch database `judgemetrics_test` (`03-test-database.sql`, created by `uv run poe up`; `JUDGEMETRICS_TEST_DATABASE_URL`; static check 38); the root conftest retargets every database test at it and warns once when unset; CI points it at the service database. Verified: `uv run poe check` left every live row count unchanged. |
| 5.3 | A `GENERATOR_VERSION` or `TRUTH_VERSION` bump without regenerating the golden fixture would silently pass. | Process improvement | `test_golden_fixture.py` compares a fresh generation byte for byte and asserts the manifest's versions equal the constants; static check 5 recomputes every digest. |
| 5.4 | A Hypothesis run with a random seed could make CI non-reproducible on the ingest-idempotency property. | Process improvement | Derandomized (five fixed `tiny` seeds); profiles `ci`/`dev` from `HYPOTHESIS_PROFILE`; strategies never generate names. |
| 5.5 | The golden README still named the Step 2 task block's stale `--from-fixture …/source` path (finding 2.2 reaching the docs). | Implementation bug (docs) | Corrected; static check 39 requires the regeneration command in the README. |

## Step 6 — Verification script

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 6.1 | The task block names `_upsert_cases` through `_upsert_justice_events` in `ingest/runner.py`, but Step 2 placed the case-level upserts in `ingest/publish.py` as public `upsert_*` functions the runner imports (`AGENTS.md`). | Spec rot | Static check 10 requires the eight `upsert_*` functions in `publish.py` and the runner's import of that module. |
| 6.2 | The task block's `--security` mode adds `scripts` to the bandit surface, but the Phase 1 scripts carried ruff `# noqa: S603` markers only, so `bandit -r scripts` reported nine LOW and one MEDIUM finding (B404, B603, B310) and the new mode failed on its own PR. | Spec rot (gate surface) / process improvement | `# nosec` markers with a justification beside each `noqa` in `scripts/audit_deps.py`, `verify_phase01.py`, and `verify_phase02.py`; the pre-commit hook, the CI `security` job, `CONTRIBUTING.md`, and `--security` all scan `src alembic scripts`, so the gate and the script agree again. |
| 6.3 | A `# nosec B603 - <justification>` comment makes bandit warn "Test in comment: … is not a test name" for every word of the justification, which would have filled the CI log. | Implementation bug (caught while writing) | The justification sits between the `noqa` and the `nosec` (`# noqa: S603 - fixed argv, no shell  # nosec B603`), so bandit reads the test id alone. |
| 6.4 | `rng.py`'s docstring names `datetime.now`, `uuid.uuid4`, and `os.urandom` as the calls the generator must avoid, so a bare-string grep for check 3 would fail on the guard's own documentation (the Phase 1 check 39 lesson again). | Implementation bug (caught while writing) | Check 3 requires the call parenthesis (`datetime.now(`, `uuid4(`, `urandom(`, `random.<fn>(`) and excludes `random.Random(`. |
| 6.5 | The task block's V4.2 lists `test_openapi.py` (a unit test) beside five integration modules, and `-m "not integration"` in `--py` also covers the DB-free property and golden tests. | Spec rot (bookkeeping) | V4.2 runs the six modules in one database-gated invocation; `--py` runs `-m "not integration"`, `-m integration`, `-m property`, and `-m golden` (the last three when a database is configured), so every marker is exercised once. |
| 6.6 | The seed idempotency probe (V2.4) needs row counts, but the script is standard-library only. | Architectural question (resolved) | The probe runs a fixed snippet through `uv run python -c … <tables>` (argument list, the table names as `argv`, `sa.table(name)` with no SQL string) and compares the JSON before and after `judgemetrics seed`; it skips with a reason when the dataset, the pepper, a database URL, or seeded rows are absent. |
| 6.7 | Alarm exercise: a deliberately broken static check pushed to the pull request must fail both `phase-verify (02)` and the aggregate `test` check, then pass after the fix. | Process improvement (exercise, expected) | See "Alarm exercise" below; `test_phase02_verification.py` ties the `test` check to `--fast` so a red static check can never merge. |

### Alarm exercise

Recorded per the Step 6 acceptance criterion ("the phase's alarm — the
required checks `test` and `phase-verify (02)` — was seen to fail on a
deliberately broken static check during this step and then pass after
the fix"):

| Event | Commit (PR #17) | `phase-verify (02)` | `test` |
|-------|-----------------|---------------------|--------|
| Deliberate break (check 39 → `tests/fixtures/golden/README.missing`) | _(recorded on the PR)_ | fail — `[FAIL] 39 … missing tests/fixtures/golden/README.missing` | fail — `python` job: `test_verify_script_fast_exits_zero` |
| Fix (check 39 restored) | _(recorded on the PR)_ | pass | pass |

## Pre-ship items

Documented limitations at the Phase 2 exit (`v0.2.0-phase-2`); none
blocks the tag, each is on a later phase's plan:

- **Synthetic data only.** The one case-level source is the in-repo
  generator; it is labelled synthetic on every surface (the flag, the
  badge, the banner) and refused by the ingest runner in production.
  Real case, charge, disposition, and defendant data begin in Phase 5.
- **No metrics yet.** `truth/metrics.json` states the expected value of
  every metric the registry will define; nothing computes or publishes
  them until Phase 3 (carry-over item 2). The windowed rates it holds
  are pretrial-indexed only (finding 1.4).
- **Rule-based resolution, no unmerge, no authenticated reviewer.**
  Scores are ordinal labels (finding 3.6); a merge is reversed only by
  hand until Phase 6; `er review decide` is refused in production until
  Phase 6's admin authentication (finding 3.5).
- **Whole-name search similarity** (Phase 1 finding 4.1) is unchanged;
  word similarity for surname-only queries is carry-over item 1.
- **Per-request coverage read** in the root layout (finding 4.6).
- **Parent-case checks across runs** (finding 2.6).
- **Build-time API origin** in the web image and **ESLint 9** in `web/`
  (Phase 1 findings 5.1 and 5.2) remain as recorded there.

## Phase 3 carry-over checklist

Each item becomes an issue or a step item in the Phase 3 roadmap, never
silent work:

1. Word similarity (`<%`) for surname-only search queries (Phase 1
   finding 4.1; unchanged in Phase 2).
2. Reproduce the metric expectations in `truth/metrics.json` from the
   Phase 3 registry (`test_golden_counts.py` and a new golden metrics
   test), and extend the truth under a new `TRUTH_VERSION` with the
   disposition- and sentence-indexed rates and time-at-risk deferral
   (finding 1.4).
3. Unmerge behind administrative authentication — Phase 6 (finding 3.5).
4. The probabilistic scorer behind the `Scorer` protocol — Phase 7
   (finding 3.6); Phase 6 measures linkage error rates on real data
   first.
5. `er review decide` admin authentication — Phase 6 (finding 3.5); the
   production refusal stays until then.
6. Read the parent case from the database for the case-level
   data-quality checks (finding 2.6) in the first step that ships a
   child-only export.
7. A cached `/coverage` read for the demo-data banner (finding 4.6).
8. `verify_phase03.py` follows this script's pattern and joins the
   `phase-verify.yml` matrix as `"03"`; its OpenAPI check asserts the
   Phase 3 paths as a subset, like checks 29 and 27 before it (finding
   4.2 applied forward), leaving the exact set to `test_openapi.py`.
