<!-- docs/phase03-qa-findings.md -->
# Phase 3 — QA findings

The rollup of every finding surfaced while executing Phase 3 (Steps 1
through 6 of [`phase03-roadmap.md`](roadmap/phase03-roadmap.md)), classified
per `ROADMAP.md` §5 "Defect handling & triage", with the guard each one
left behind ("prevent the class, not the instance"). Findings recorded
elsewhere at the time (pull-request bodies #18–#23, `docs/ROADMAP.md`
known issues, `AGENTS.md` decisions) are gathered here so the phase has
one QA record; the guard column names the test, hook, CI job, or
verify-script check that now catches a recurrence, and every finding
has a destination: fixed, an issue, or a named phase that owns it.

Verification lives in `scripts/verify_phase03.py` (49 static checks,
the tool suites, the first-milestone items, the seed and compute
idempotency probes, `metrics verify`, the provenance trace probe, and
the V1–V6 matrix; see "Step 6" below) and runs in CI through
`.github/workflows/phase-verify.yml` as the required check
`phase-verify (03)`.

## Step 1 — Metric registry, analytic frame, generated methodology

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 1.1 | The eligibility metrics (`eligible_cases`, `eligible_defendants`) cannot be expressed with a time-gated assignment rule, and the compute functions need to know which rows a metric reads and which rows it counts. | Spec rot | A fifth gate `assigned_ever` and the registry fields `population`, `counted`, and `measure`, patched into the Step 1 task block; `test_metric_registry.py` validates every value; static check 1 requires every slug. |
| 1.2 | The task block's Step 6 V-check named `test_registry.py`, which is the connector registry's test. | Spec rot | The metric registry's test is `test_metric_registry.py`; V1.2 in the roadmap and in `verify_phase03.py` names it. |
| 1.3 | The synthetic connector derives `new_case` and `reconviction` per participant id before entity resolution merges the planted split persons, and never derives `new_charge`, so the golden fixture's two split persons lack two truth `new_case` events in `justice_event`. | Upstream gap | Patched into the Step 2 task block: the snapshot loader derives the other-case outcomes from the merged person's charges; `test_golden_metrics.py` asserts every golden observation equals the truth; recorded in `docs/ROADMAP.md` known issues. |
| 1.4 | Exposure after a disposition or a sentence is deferred by the index case's own incarceration term only; other terms the person serves are not modelled, so time at risk is overstated and windowed rates biased downward for such persons. | Data-semantics finding | Published in `docs/METHODOLOGY.md` "Exposure" and implemented identically by `TRUTH_VERSION` 2 (the property test compares engine and truth); pre-ship item below; revisited with Phase 4's methodology `1.0` (carry-over item 1). |
| 1.5 | A metric whose outcome the source cannot document must never be published as a zero. | Data-semantics finding | `NotObservable` yields no observation and is reported (`sources_skipped`, `not_observable`); `test_golden_metrics.py` asserts the not-observable metrics are absent; `truth/metrics.json` carries `not_observable` (static check 14). |
| 1.6 | The analytic frame must never carry restricted person material. | Security finding (design) | `persons.id` is the frame's only person column; no module under `metrics/` names `full_name`, `date_of_birth`, or `public_person_key`, and only `snapshot.py`'s own denylist names `person_identifier` (static check 9; `test_metrics_snapshot.py` greps the package too). |

## Step 2 — Snapshot, computation engine, golden metric tests

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 2.1 | The snapshot loader missed rows still pointing at a merged alias person. | Implementation bug (fixed in-step) | Reads cover the whole merge family; `test_metrics_snapshot.py` builds a snapshot by hand with a merged alias and derived outcomes. |
| 2.2 | The lead convicted charge breaks severity ties by charge id; with canonical UUIDs a re-ingest would choose differently (the demo world has 51 category-changing ties). | Data-semantics finding (clarification) | "Charge id" means the source's charge id: the frame's `charges` carries `source_row_id`; `test_metrics_compute.py` pins the tie-break; recorded in `docs/ARCHITECTURE.md` and `AGENTS.md` (no registry bump: the prose was unchanged). |
| 2.3 | An assignment change cannot move a court's numbers, so the step-13 test cannot expect the courts to be republished. | Judgement call | The test asserts the courts are recomputed and left in place (PR #19 body). |
| 2.4 | DuckDB returns timezone-aware timestamps to Python only through `pytz`. | Architectural question (resolved) | Timestamps are stored as naive UTC in the snapshot; `pytz` and `pyarrow` are not dependencies (`AGENTS.md`). |
| 2.5 | A snapshot hash becomes a path, and DuckDB can install and load extensions. | Security finding (design) | The hash is validated as 64 hex characters before it becomes a path; DuckDB runs in memory with no extension installed or loaded (`test_metrics_snapshot.py`; static check 11). |
| 2.6 | Member rows are written once per observation, so a windowed metric lists its cohort six times: the demo seed writes 822,777 members for 3,426 observations. | Architectural question (deferred) | Recorded in `docs/ROADMAP.md` known issues with the fix (one member row per metric with per-window flags); owned by Phase 5 if Cook County scale makes it a problem, else Phase 8's performance work (carry-over item 9). |
| 2.7 | The run's snapshot id could not live in `ingest_run.checkpoint`, which the runner hands back whole to a checkpointing connector. | Architectural question (resolved) | Migration `0006` adds `ingest_run.metrics_snapshot_id` as a column (`AGENTS.md`). |

## Step 3 — Provenance trace, metrics API, corrections intake

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 3.1 | A route that forgot to blank a suppressed figure would leak it. | Security finding (design) | `SuppressibleFigures` nulls every figure of a suppressed row in a schema validator, so no route can leak one; `test_schemas_metrics.py` and `test_public_contract.py` assert it; the compare sort columns are null for suppressed rows so the order never leaks a withheld number. |
| 3.2 | PostgreSQL requires `SELECT` on every returned column, so an insert with `RETURNING` would force a read grant on `correction_request`. | Security finding (design) | The insert has no `RETURNING` (client `uuid4()`); migration `0007` grants `INSERT` only (static check 22); `test_api_corrections.py` proves the app role cannot `SELECT`, `UPDATE`, `DELETE`, or `RETURNING`; `test_query_counts.py` asserts no `RETURNING`. |
| 3.3 | Adding `reason` to the log scrubber's denylist redacted the operational lines that used a `reason` key. | Implementation bug (caught while writing) | Operational lines name their cause `failure`, `refusal`, or `because`; `test_logging.py`; static check 24 requires the denylist entries. |
| 3.4 | Phase 2 carry-over item 1: whole-name similarity misses a surname-only query against a long name. | Carry-over (closed) | Word similarity (`<%`) for one-token queries; `test_api_search.py` ("Ginsberg" finds Ruth Bader Ginsburg); static check 28. |
| 3.5 | A suppressed share's `eligible_count` equals its withheld denominator, so the published sample size reveals it. | Data-semantics finding | Suppression's rationale is estimate stability, not cohort-size secrecy; the methodology names which counts are published; recorded in `docs/ROADMAP.md`; revisited with real data in Phase 5 (carry-over item 4). |
| 3.6 | The snapshot's storage URI and local artifact paths are operator detail, not public provenance. | Security finding (design) | The provenance endpoint withholds `storage_uri` and any non-`http(s)` artifact URI (`test_api_metrics.py`); the CLI, run by the operator, prints them. |
| 3.7 | An API started without the correction contact key would accept requests it cannot encrypt. | Security finding (design) | `create_app` requires a usable Fernet key outside `env == test` and `judgemetrics.main.app` is built lazily (`test_app_startup.py`). |

## Step 4 — Judge metric panels, compare, methodology, coverage

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 4.1 | The cases route has no pretrial, disposition, or sentence filter, so "View eligible cases" cannot narrow to a metric's cohort. | Upstream gap (deferred) | Disposition and Sentencing link with `status=closed`, the others unfiltered; listed under the phase roadmap's "Not in scope" for the case-filter work that follows real data (Phase 5). |
| 4.2 | Phase 2 carry-over item 7: the banner read `/coverage` on every request. | Carry-over (closed) | `lib/coverage-cache.ts`, sixty-second in-process TTL, failures never cached (`coverage-cache.test.ts`; static check 35). |
| 4.3 | A web methodology page written separately from `docs/METHODOLOGY.md` would drift. | Architectural question (resolved) | `GET /metrics` serves the renderer's own constants, so both surfaces come from one source (`methodology-page.test.tsx`; `methodology render --check`; static check 31). |
| 4.4 | The compare page's court chooser reads two `/courts` pages; a larger registry needs search. | Upstream gap (deferred) | Listed under the phase roadmap's "Not in scope"; arrives with the larger registry of Phase 5. |
| 4.5 | The web hygiene test rejected `process.env.NODE_ENV`, which the coverage cache needs to bypass itself under test. | Process improvement | `NODE_ENV` joined the allowed reads as Node's own flag, not a setting (`AGENTS.md`). |

## Step 5 — Corrections form, pages, `bootstrap`, walkthrough

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 5.1 | `infra/docker/postgres/03-test-database.sql` reruns on every `uv run poe up` and its blanket `GRANT SELECT ON ALL TABLES` re-opened the restricted tables to the app role in the scratch database after the migrations had revoked them. | Security finding (fixed in-step) | The script re-applies the migrations' revokes for every restricted table that exists; the hygiene test asserts it; `AGENTS.md` records the rule for any script that grants on `ALL TABLES`. |
| 5.2 | The corrections form posts through the web server, so without `JUDGEMETRICS_TRUST_PROXY` every browser behind one web server shares one bucket of five an hour. | Security finding (operational) | Documented on the Compose `web` service and in `docs/ROADMAP.md`; the production reverse proxy sets the flag and the edge limits arrive in Phase 8 (carry-over item 11). |
| 5.3 | `CourtSummary` carries no provenance and `/coverage` reports sources, not jurisdictions. | Upstream gap (deferred) | The jurisdiction page infers its sources (`lib/jurisdictions.ts`, `jurisdictions.test.ts`); a per-jurisdiction coverage breakdown arrives with Phase 5's first real state-court pipeline. |
| 5.4 | The `bootstrap` probe leaves the live FJC ingest in the scratch database, where a search test fails while a live "Douglas Howard Ginsburg" outranks the fixture's Ruth Bader Ginsburg. | Process improvement | The probe is followed by the suite, never interleaved with it: `verify_phase03.py --post` runs every writing probe before the Python suites and item 17. |
| 5.5 | `metrics compute` never needs the correction contact key, so `bootstrap` cannot check it. | Architectural question (resolved) | `dev-api` (`create_app`) checks it; `seed` fails loudly without the pepper. |
| 5.6 | `eslint-plugin-security` flags a `new RegExp` over an id discovered at run time. | Process improvement | The walkthrough's `toHaveURL` takes a predicate (`AGENTS.md`). |

## Step 6 — Verification script

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 6.1 | `tests/unit/test_phase02_verification.py` pinned the phase-verify matrix to exactly `["01", "02"]`, so adding `"03"` would have failed the aggregate `test` check (Phase 2 finding 4.2 again, one level down). | Process improvement | The Phase 2 and Phase 3 tests assert their entries as a subset, like the Phase 1 test; static check 48 does the same. |
| 6.2 | The task block's check 14 says `truth/metrics.json` carries `index_events`; the file carries `index_events` per subject and the index kinds as `index_kinds` at the top. | Spec rot | Check 14 requires `not_observable` at the top and `index_events` anywhere in the document. |
| 6.3 | The task block's check 31 greps the methodology page for `/api/v1/metrics`; the page reads the registry through the typed client (`getRegistry()`). | Spec rot | Check 31 requires the `getRegistry()` call and that the client's `getRegistry` is `GET /api/v1/metrics`. |
| 6.4 | `snapshot.py` names `person_identifier` in its own `RESTRICTED_TABLES` denylist and docstring, so a bare grep for check 9 would fail on the guard itself (the Phase 1 check 39 and Phase 2 finding 6.4 lesson). | Implementation bug (caught while writing) | Check 9 rejects any read of `person_identifier` (a table lookup, `sa.table`, the model class, a `FROM`) everywhere and the bare name outside `snapshot.py`, and the three person columns everywhere. |
| 6.5 | Check 37 read `web/app/favicon.ico` as UTF-8 and crashed. | Implementation bug (caught while writing) | The check scans bytes. |
| 6.6 | The task block asks the static mode to stay standard-library only and to "parse the XML" of the brief; an XML parser is flagged by SAST on principle (B314/B405) and the registry needs a YAML reader. | Architectural question (resolved) | A minimal line reader for the registry's folded `known_limitations` and a regular expression over the brief's one `<important_statistical_warnings>` element; `test_phase03_verification.py` asserts both equal `yaml.safe_load` and each other. |
| 6.7 | PR #28 moved MinIO to Chainguard's image, which runs as uid 65532; a volume created by the earlier root-running image is owned by root, so on every existing developer machine MinIO exited with "Unable to write to the backend" and `uv run poe up` (so `bootstrap`, so first-milestone item 3) failed. CI never saw it: its volumes are fresh. | Implementation bug (fixed in-step) | A one-shot `minio-volume-init` Compose service (profile `init`, root for the `chown` only; MinIO itself still runs as `nonroot`) runs first in `up`; `test_repo_hygiene.py` pins the sequence and asserts MinIO has no `user` override; `docs/ROADMAP.md` and `AGENTS.md` updated. |
| 6.8 | `docs/ROADMAP.md` still listed as open issues that Phase 3 closed: "the metrics engine computes nothing yet", whole-name search similarity, the per-request banner read, "the corrections workflow arrives in Phase 3", and MinIO from `quay.io`. | Spec rot (status document) | Removed or rewritten in this step's status update. |
| 6.9 | The `--post` probes that write (migrate, seed, bootstrap, compute) would otherwise run against the live database. | Process improvement | They run in `probe_environment()`: the three role URLs pointed at `JUDGEMETRICS_TEST_DATABASE_URL` and the snapshot directory at `data/snapshots/scratch-test-db` (Step 5's safe shape); without the variable the script names the configured database it uses. |
| 6.10 | Step 5's probe pointed `JUDGEMETRICS_SNAPSHOT_DIR` at a temporary directory, but the scratch database's observations keep citing their snapshots after it is deleted, so any later `metrics verify` there (the next `--post`, or one after an interrupted run, as happened here) cannot open them. | Implementation bug (found by running `--post`) | The probes use the persistent, git-ignored `data/snapshots/scratch-test-db` (snapshots are content-addressed and never overwritten, so reuse is safe); the scratch database's metric rows left by the interrupted run were cleared once. |
| 6.11 | The first `--post` run crashed in the provenance trace probe: a captured child writes its stdout in the locale encoding (cp1252 on Windows), and the CLI's em dash did not decode as UTF-8. | Implementation bug (found by running `--post`) | Captured probe subprocesses get `PYTHONIOENCODING=utf-8` and decode with `errors="replace"`. |
| 6.12 | The task block says to add the required context with `gh api -X PUT …/protection/required_status_checks`; GitHub defines that endpoint as `PATCH` (`PUT` exists only on `…/protection`, where it replaces every setting). | Spec rot | The `PATCH` call `CONTRIBUTING.md` "Repository settings" already records was used and its context list updated. |
| 6.13 | Alarm exercises: a deliberately broken static check pushed to the pull request must fail `phase-verify (03)` and `test`, and a tampered observation must fail `metrics verify`. | Process improvement (exercise, expected) | See "Alarm exercise" below. |

### Alarm exercise

RESULTS-PENDING

## Pre-ship items

Documented limitations at the Phase 3 exit (`v0.3.0-phase-3`); none
blocks the tag, each is on a later phase's plan:

- **Methodology `0.1`, descriptive only.** Every published number is an
  observed count, share, fixed-window rate, Kaplan–Meier estimate, or
  median; no expected count, expected rate, observed-to-expected ratio,
  or adjusted interval exists yet, and the methodology page says so.
  Adjusted statistics are Phase 4 (carry-over items 1–2).
- **Incarceration deferral** covers the index case's own term only
  (finding 1.4).
- **Suppression thresholds fixed at 10** for every share, rate, survival
  estimate, and median (0 for counts and distributions), chosen before
  any real data; revisited per metric in Phase 5 (carry-over item 4).
- **`release_violation` and `rearrest` are not observable** in the
  synthetic source, so their four metrics publish nothing; the first
  source that documents them (a separate arrest source) enables them.
- **Snapshots on the local filesystem** (`JUDGEMETRICS_SNAPSHOT_DIR`,
  git-ignored, never overwritten); the object-store variant is Phase 8
  (carry-over item 6).
- **The corrections key is held by the API process.** Contacts are
  Fernet-encrypted with a symmetric key the public API holds; envelope
  or asymmetric encryption arrives with Phase 6's admin reader
  (carry-over item 5).
- **No admin reader for corrections.** Requests are stored `received`;
  only the admin role can read the table, by hand, until Phase 6.
- **Per-process rate limits** on `/search` and `/corrections`, and the
  proxy caveat of finding 5.2, until Phase 8's edge limits.
- **Synthetic case data only.** Every case-level number is computed
  over the labelled synthetic dataset; real data begins in Phase 5.

## Phase 4 carry-over checklist

Each item becomes an issue or a step item in the Phase 4 (or the named
later) roadmap, never silent work:

1. Methodology `1.0` with its changelog entry: the brief's
   expected-outcome model, the exposure limitation of finding 1.4
   revisited, and the "Known limitations" unchanged.
2. Fill the observation columns Phase 3 left empty: expected count,
   expected rate, observed-to-expected ratio, and the adjusted interval.
3. Planted judge effects in the synthetic generator under a new
   `TRUTH_VERSION`, so the adjusted statistics have a known answer on
   the golden fixture.
4. Per-metric suppression thresholds and the cohort-size question of
   finding 3.5, revisited with real data — Phase 5.
5. Envelope or asymmetric encryption for correction contacts when Phase
   6's admin reader arrives.
6. The object-store snapshot variant — Phase 8.
7. Parent-case data-quality checks across runs (Phase 2 carry-over item
   6) — the first step that ships a child-only export (Phase 5).
8. Unmerge behind administrative authentication, `er review decide`
   admin authentication, and the probabilistic scorer (Phase 2
   carry-over items 3–5) — Phases 6 and 7.
9. Member rows once per metric with per-window flags if Cook County
   scale needs it (finding 2.6) — Phase 5 or Phase 8.
10. `verify_phase04.py` follows this script's pattern and joins the
    `phase-verify.yml` matrix as `"04"`; its checks and its unit test
    assert earlier phases' OpenAPI paths and matrix entries as subsets
    (finding 6.1).
11. Edge rate limits and `JUDGEMETRICS_TRUST_PROXY` behind the
    production reverse proxy (finding 5.2) — Phase 8.
