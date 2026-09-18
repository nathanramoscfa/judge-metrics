<!-- docs/ROADMAP.md -->
# JudgeMetrics — status, open questions, and next milestones

This is the living status document the brief asks for: the current
phase, completed items, unresolved issues (above all, unresolved
data-access questions, which are recorded here rather than answered by
guesswork), and the next milestones. The plan itself is the root
[`ROADMAP.md`](../ROADMAP.md); the per-phase execution plans are
`docs/phaseNN-roadmap.md`. Update this file at the end of every step
(Stage 6 of the step lifecycle).

## Current phase

**Phase 2 — Synthetic Justice Dataset, Entity Resolution, and Case
Timelines.** In progress. Phase 1 (Foundation, Canonical Schema, and
the FJC Judge Slice) completed on 2026-09-16 with Step 6 (QA and
`scripts/verify_phase01.py`) and is tagged `v0.1.0-phase-1` on the
squash-merged commit. The planning kit was re-exported (`uv run poe
kit`, no catalog change) and the execution plan
[`docs/phase02-roadmap.md`](phase02-roadmap.md) was authored from
[`ROADMAP.md`](../ROADMAP.md) §4 Phase 2 on 2026-09-16. Step 1 (the
deterministic synthetic generator) completed on 2026-09-17, Step 2
(the synthetic connector, case-level publishing, and `seed`) and Step 3
(the entity-resolution framework v0, review queue, and audit log) on
2026-09-18, Step 4 (the case API, case pages, and coverage v0) later
the same day, and Step 5 (property tests, the golden suite, and the
scratch test database) the same evening; Step 6 (QA and
`scripts/verify_phase02.py`, branch `feature/phase02-step6-verify`)
begins in a fresh conversation.

## Completed

| Date       | Item                                                                                              |
|------------|---------------------------------------------------------------------------------------------------|
| 2026-09-15 | Repository scaffolded: uv project on Python 3.13, ruff, mypy (strict), pytest, pytest-cov, poethepoet task interface with a `Makefile` shim; `uv run poe check` green. |
| 2026-09-15 | roadmodel 0.2.33 installed in the `planning` group; planning kit exported to `planning/`.         |
| 2026-09-15 | Brief archived verbatim under `docs/brief/`.                                                      |
| 2026-09-15 | Project roadmap (`ROADMAP.md`, v2) and Phase 1 execution roadmap authored with per-step model selections. |
| 2026-09-15 | Data-source register (`docs/DATA_SOURCES.md`) with live verification of FJC, Cook County, and CourtListener. |
| 2026-09-16 | Root roadmap v2.1: post-launch Phase 9 (sustainability and data products) added; §1.4 request-identity hook, §5.5 redistribution rights, and §6.4 commercial-licensing scope pulled forward; **Redistribution** field added to every source-register entry. |
| 2026-09-16 | Phase 2 execution roadmap (`docs/phase02-roadmap.md`) authored from the re-exported planning kit: six steps (generator, connector and `seed`, entity resolution v0 with audit log, case API and pages, property tests and golden suite, QA), per-step model selections (Fable 5.1 for Steps 1 and 3, Opus 5 elsewhere; GPT backups on Codex), the V1–V6 matrix, and the 44-check `verify_phase02.py` specification. |
| 2026-09-16 | Scaffold pushed as the initial commit; public repository `nathanramoscfa/judge-metrics` created. |
| 2026-09-18 | **Phase 2 Step 5.** Property tests, the golden regression suite, and the scratch test database. `hypothesis` in the dev group with profiles `ci` (50 examples, no deadline; CI sets `HYPOTHESIS_PROFILE=ci`) and `dev` (20) registered in `tests/conftest.py`; markers `property` and `golden`; `tests/property/` (`test_event_ordering.py` — for random seeds at `tiny` and `golden` every truth subsequent event follows its index event with `days_after >= 1`, charges dispose after filing, sentences follow dispositions, decisions sit in their case window, and the same holds on the drafts the synthetic connector produces; `test_case_numbers.py` — formatting variants normalize to one key, idempotently; `test_resolution_consistency.py` — `resolve_persons` in two Hypothesis-drawn draft orders yields the same person per participant hash and equal stable hashes are exactly the pairs that share a person; `test_ingest_idempotent.py` — five derandomized `tiny` seeds ingested twice: the truth expectations hold after the first run and the second creates, updates, and resolves nothing); `tests/golden/` (`test_golden_fixture.py` byte-identical regeneration, `verify_dataset`, the `GENERATOR_VERSION`/`TRUTH_VERSION` guard — a bump without regeneration fails four tests; `test_golden_resolution.py` parametrized over every `resolution_expectations.csv` row, split persons under one public key, ambiguous pairs in review; `test_golden_counts.py` manifest counts minus planted duplicates, the predicted data-quality issues, provenance hashes equal to the fixture files; `test_public_contract.py` no restricted name in the OpenAPI document, `InsufficientPrivilege` for the app role on the restricted tables, public keys only in every golden `/cases/{id}`); the scratch database `judgemetrics_test` (`infra/docker/postgres/03-test-database.sql`, idempotent, from initdb and the one-shot `postgres-test-init` job in `uv run poe up`; `Settings.test_database_url`; `JUDGEMETRICS_TEST_DATABASE_URL` in `.env.example`; the `test_settings` fixture retargets the app and ingest role URLs at it and warns once when it is unset); every database test rerouted through it; CI runs the init script and points the variable at the service database. The property tests found `tiny` seeds (5 of 3,000) whose world had no two unused persons in disjoint courts: the same-date-of-birth ambiguous plant now falls back to a same-court pair (still `review`, its own `expected_behaviour` text), every seed generates, and no previously generated dataset changed (no version bump; the golden byte comparison proves it). Verified locally: `uv run poe seed` and `uv run poe ingest-fjc` on the main database, then `uv run poe check` (831 passed in 1m54s, no warnings) left every live row count unchanged (`court_case` 5,200, `person` 3,225, `judge` 4,100, `audit_log` 27) and `/api/v1/coverage` still reports the synthetic source with 5,200 cases; the whole property and golden set runs in about 40 s at the `ci` profile. |
| 2026-09-18 | **Phase 2 Step 4.** The case API, case pages, and coverage v0. `schemas/cases.py` (`CaseSummary`, `CaseDetail` with parties as public keys, assignments, charges with `disposition_actor`, decisions with `actor_type` and `judicial_discretion_classification` and the pretrial detail, sentences, provenance; `TimelineEntry`/`Timeline` with the nine kinds and `TIMELINE_KIND_ORDER`), `schemas/coverage.py`, `synthetic: bool` on `Provenance`, `JudgeSummary`, `CourtSummary`, `SearchResult` (entity type `case` added), `case_count` and `coverage` (`CoverageWindow`) on `JudgeDetail`; `repositories/provenance.py` (`with_source` + `synthetic_flag()` joined into every list and detail statement, `source_records_by_id`), `repositories/common.py` (`paginate_rows`), `repositories/cases.py` (`load_case`: one explicit statement per case-level table plus provenance, every person join under `unmerged()` selecting `public_person_key` only; `list_judge_cases` with the four filters and the empty-page existence statement), `repositories/coverage.py` (one correlated-count statement plus one `DISTINCT ON` for the latest runs), `repositories/search.py` (the union with the exact `case_number_normalized` arm scored 1), `repositories/judges.py` (`case_window`); `services/cases.py` (detail, `build_timeline` from the same load — `filed` at the start and `closed` at the end of their day, then kind rank, then row id — labels per kind), `services/coverage.py` (`synthetic_present` from rows), `services/search.py` (name and case-number normalization); routes `GET /cases/{id}`, `/cases/{id}/timeline`, `/judges/{id}/cases` (`StrictQuery` of `limit`, `offset`, `filed_from`, `filed_to`, `status`, `case_type`; 422 on an inverted range), `/coverage` (cached); `docs/openapi.json` regenerated (the twelve v1 paths plus health and ready); `SYNTHETIC_SOURCE_TYPE` moved to `db/models/provenance.py`. Web: `client.ts` (`getCase`, `getCaseTimeline`, `getJudgeCases`, `getCoverage`; `schema.d.ts` regenerated), `components/synthetic-banner.tsx` (async server component in the `force-dynamic` root layout; absent when the call fails), `badges.tsx` (`SyntheticBadge`, `ActorBadge` for every `ActorType`, `DiscretionBadge`, `case` entity type), `case-timeline.tsx` (ordered list, `<time>` per entry, actor and discretion badges, source per line), `cases-panel.tsx`, pages `/cases/[caseId]` (header, timeline, charges with the disposing actor, assignments, disposition, attributed decisions with pretrial detail, sentence, "Sources" panel), `/judges/[judgeId]` (badge, cases panel), `/judges/[judgeId]/cases` (GET-form filters, paginated table), `/coverage` v0 (one card per source: counts table, filing window, last run; Phase 3 note), `/search` (case results, badges), the home cases tile from `/coverage`, badges on the court page and the provenance panel (`title`/`description` props); `links.ts` `synthetic` entry. Tests: `test_api_cases.py` (7), `test_api_coverage.py` (3, FJC-only false then golden true), `test_api_judges.py` (+15: cases list pagination, filters, ten 422 cases, 404 vs empty page, `case_count`/`coverage`), `test_api_search.py` (+2: exact and partial numbers, flags), `test_query_counts.py` (+3: case detail and timeline ≤ 8 on the busiest case, judge cases ≤ 2, coverage ≤ 3, judge detail ≤ 4), `test_openapi.py` (twelve paths, twelve allow-lists, the restricted-name contract, filters and kinds), the module-scoped `golden_fixture` and shared `purge_source` in `tests/integration/conftest.py`; Vitest (+11: helpers, banner only on `synthetic_present` and never on failure, badges for every actor, timeline rendering, panel label; 28 total); Playwright (+2: the case flow and the coverage page; 8 total, green locally over the demo seed); the `e2e` CI job ingests `tests/fixtures/golden` after the FJC fixture. Docs: `API.md` (endpoints, filters, the flag, the timeline kinds, the query budget table), `ARCHITECTURE.md` (repositories, services, web tier), `README.md`, `AGENTS.md`. Findings: spec rot ×3 patched in the Step 4 task block (a case detail cannot load six collections in four statements without a cartesian product or a JSON aggregate, so the budget is one statement per table, eight; the golden ingest path is the dataset root, not `source/`; judge detail is four with the case window); process finding — `verify_phase01.py` check 29 asserted the exact Phase 1 path set and would have failed the required `phase-verify (01)` check on any later phase's route, so it now asserts a subset; implementation bug (blocking) — `test_entity_resolution.py` counted every `er.merge` audit row in the database, which the committed golden ingests of the API tests (and the demo seed) break, so it now scopes the count to the persons this ingest kept. Verified locally: every endpoint against the demo seed (a judge with 697 cases, a case with a prosecutor dismissal beside a judicial disposition, exact case-number search, coverage with 5,200 synthetic cases and 3,200 unmerged persons), the pages in light and dark mode, `pnpm lint|typecheck|build|test|e2e` green. |
| 2026-09-18 | **Phase 2 Step 3.** Staged person resolution (`docs/ENTITY_RESOLUTION.md`): `entity_resolution/config.py` (`MODEL_VERSION = person-rules-v0`, `Thresholds(0.95, 0.20)` per entity type, loaded from the versioned `data/reference/entity_resolution_thresholds.yaml`), `features.py` (`PairFeatures` from hash equality and case linkage — never a restricted value; blocking on shared name or participant-id hashes), `deterministic.py`, `rules.py` (name+DOB with a shared case or related-case link → matched 0.98; same court → review 0.70; name-only → rejected 0.10; differing DOB → rejected 0.02), `scoring.py` (`Scorer` protocol, `StubScorer`, recorded `skipped`), `candidates.py` (one row per ordered pair per model version; human decisions never overwritten), `merge.py` (Core updates across seven tables, duplicate justice-event and identifier rows dropped and counted, `merged_into_person_id`, `unmerged()` for public queries), `audit.py`, `queue.py` (`list_review`, `decide` with validation and the production refusal), `pipeline.py` (`evaluate`, `resolve_persons` at step 10, `resolve_candidates` after step 12, `rerun`); migration `0004_entity_resolution_review` (`stage`, `decided_at`, `decided_by`, `reason`, `ingest_run_id`, `uq_er_candidate_pair_version`, the ordered-pair check, `person.merged_into_person_id`, `audit_log` with the `audit_log_append_only()` trigger, grants: app role nothing on candidates or the audit log, ingest role append-only); CLI `er run`, `er review list [--json]`, `er review decide`; 30 unit tests and 9 integration tests (every `truth/resolution_expectations.csv` row matches; split persons merged under one public key; ambiguous pairs in review; name-only pairs rejected; features free of restricted values; second and forced ingests and `rerun` write no candidate and merge nothing; a reviewer's `matched` merges with an `er.decide` audit row on which UPDATE and DELETE raise; already-decided candidates refused; production refused; log lines free of names, DOBs, hashes; migration round trip through 0004 with the trigger proven for the admin role). Live on the demo seed (2026-09-18): the ingest resolved 50 pairs — 25 matched and merged (the 25 planted split persons), 13 review, 12 rejected (name-only) — and `judgemetrics er run` twice afterwards reported pairs=25, candidates_created=0, candidates_updated=0, merges=0; `er review decide … rejected` on one queued pair wrote audit row `91f60635…`, a second decision on it was refused, and the same command under `JUDGEMETRICS_ENV=production` was refused. |
| 2026-09-18 | **Phase 2 Step 2.** The synthetic dataset through the standard runner with full provenance, and case-level publishing for every later source. `data/reference/case_vocabulary.yaml` (`version: 1`, equal to `synthetic/vocabulary.py` by test) loaded once by `normalization/vocabulary.py` (`require`, `require_or_unknown`, `UNKNOWN`); `normalization/case_numbers.py` (separators → one `-`; `syn 2019 000013` and `SYN-2019-000013` collapse); `security/identifiers.py` (`hash_identifier`: `sha256(pepper‖kind‖normalized value)` for `source_participant_id`, `full_name`, `date_of_birth`, `name_dob`; `JUDGEMETRICS_IDENTIFIER_PEPPER` required by `ingest run` and `seed`); the nine case-level drafts in `ingest/base.py` with natural keys on `(case, source_row_id)` and `describe_key` (no hash in descriptions), the `SupportsContext` hook; migration `0003_case_level_natural_keys` (`source_row_id` + `uq_<table>_case_source_row` on six tables, `uq_justice_event_natural`, `person.source_record_id`, `uq_person_identifier_stable` partial + `uq_person_identifier_person_type_hash`, `court_case.related_case_number_normalized`, `charge.disposition_actor`, `uq_judge_external_ids_synthetic_judge_code`, grants re-asserted; reversible, `alembic check` clean); `ingest/runner.py` resolution of cases and persons (`resolve_persons` hook; `unresolved_case`/`unresolved_person`/`unresolved_judge` rejections counted), judge upserts per identity system, `run_ingest(connector=)`, fixture ids as contained relative paths, per-table counts in the run log; `ingest/publish.py` (batched upserts for persons + identifier rows, cases, parties, assignments, charges, events, decisions + pretrial release, sentences, justice events; `public_person_key` generated once); `quality/checks.py` case-level checks (`case_number_duplicate` before dedup, `disposition_before_filing`, `event_order_impossible`, `subsequent_before_index`, `missing_judge_on_decision`, `missing_disposition`, `unknown_category_measured`, `person_resolution_confidence_missing`); `ingest/synthetic/` (`schema`, `sources`, `parse`, `normalize` with derived `new_case`/`reconviction`/FTA/revocation justice events, `connector` with manifest-drift failure; `source_type = synthetic`, parser `1`); CLI `judgemetrics seed [--seed] [--scale] [--force]`, poe/Make `seed`; `.env.example` pepper and dataset dir, scrubber denylist extended; 78 new unit tests (case numbers, identifiers, vocabulary, drafts, connector over the golden fixture, the case-level checks) and 12 integration tests (golden fixture ingested twice: 969 rows then 0/0; provenance to the fixture bytes; hashes only; prosecutor dismissals keep `actor_type = prosecutor`; the planted issues exactly — 3 `case_number_duplicate`, 3 `missing_judge_on_decision`, 2 `missing_disposition`, no errors; no participant attribute or hash in any log line; the real connector and `seed` refused in production; app-role grants on every new column). Live `uv run poe seed` (demo, MinIO lake, ingest role, 32 s): 1 jurisdiction, 5 courts, 24 judges, 32 service records, 3,225 persons, 5,200 cases, 5,200 parties, 6,306 assignments, 8,328 charges, 21,346 court events, 13,940 decisions, 5,189 pretrial releases, 3,145 sentences, 3,716 justice events (88,277 rows created, 0 rejected; issues 40 duplicates, 94 missing judge, 73 missing disposition, 2 unknown-category counts); the second `seed` skipped generation and created and updated 0 rows in 3 s. Two spec-rot patches to the Step 2 task block: the participant id is hashed in the source's namespace (a court-code prefix would split every multi-court person into pairs `truth/` does not list), and the connector reads the dataset root because `manifest.json` sits beside `source/`, not inside it. |
| 2026-09-17 | **Phase 2 Step 1.** Deterministic synthetic generator `src/judgemetrics/synthetic/` (`docs/SYNTHETIC_DATA.md`): `config.py` (`ScaleSpec` with self-validation, `GOLDEN` 3/6/40/60 over 2019–2021, `DEMO` 5/24/3,200/5,200 over 2016–2023, `TINY` for property tests, `GENERATOR_VERSION`); `rng.py` (one `random.Random` per named stream from `sha256(seed:name)`, `random()`-only helpers); `wordlists.py` (222 given and 339 family dictionary tokens, reviewed against real names); `world.py` (Synthetic State `ZZ`, circuit courts, anchor judges plus judges with one or two service records and latent release, dismissal, and severity biases; persons with unique names, dates of birth by age band, propensities, home courts); `cases.py` (charges from the curated `data/reference/synthetic_offenses.csv`, business-hour timelines, statutory and judicial pretrial decisions with bond amounts and conditions, reassignments including forced ones at service ends, four disposition tracks with judge, prosecutor, and jury actors, sentences by severity, hearings, failures to appear with bench warrants, revocations, corpus-end truncation to open cases and pending charges); `edge_cases.py` (split persons with `related_case_number`, ambiguous same-DOB and missing-DOB pairs, duplicate source records as formatting variants, missing DOB, judge, disposition, and description); `truth.py` (`persons.csv`, `subsequent_events.csv` with a ceiling `days_after`, `resolution_expectations.csv`, `planted.csv`, `metrics.json` per judge and court with a definition per metric, generated `README.md`); `writer.py` and `generate.py` (`generate_dataset`, `verify_dataset`, manifest with sha256 per file, refusal of an existing dataset without `--force`); CLI `synthetic generate|verify`; the golden fixture under `tests/fixtures/golden/` (seed 7: 60 cases plus 3 duplicates, 40 persons, 18 planted items, 4 resolution expectations) with README; `synthetic/vocabulary.py` fixing the case vocabulary Step 2 lifts; 53 unit test cases (byte-identical regeneration, hash verification, the brief's minimums on the spec and a demo run, every listed behaviour, planted quantities recomputed from the files, temporal order, subsequent events after their index, numerators bounded by denominators, an independent recount of the simplest metrics, word-list names, CLI refusal and exit codes). Demo scale generates in about 2 s (5,200 cases, 3,200 persons, 811 planted items); a 300-seed sweep at tiny scale and 100 seeds at golden scale produced no failure. Security finding fixed on the way: gitleaks flagged the `hashed_secret` fingerprints in `.secrets.baseline`, so `.gitleaks.toml` now extends the default rules and allowlists the baseline file. |
| 2026-09-16 | **Phase 1 Step 6 — Phase 1 complete.** `scripts/verify_phase01.py` (modes `--fast`, `--py`, `--node`, `--e2e`, `--security`, `--all`, `--post`; 43 static checks over Steps 1–5, the security backstop, and the Step 6 self-checks using only `pathlib`, `re`, `json`, and `git ls-files`; subprocess suites over `uv run`, `pnpm`, and `gh`; the V1–V6 matrix with `gh pr checks` in `--post`; `[PASS] NN` / `[FAIL] NN — reason` lines, a summary table, exit 0/1; `--fast` in 0.1 s); `tests/unit/test_phase01_verification.py`; `.github/workflows/phase-verify.yml` (matrix `["01"]`, SHA-pinned, `contents: read`, `--fast` then `--security` with pnpm for the audit) and its check `phase-verify (01)` added to the required contexts beside `test` (command recorded in `CONTRIBUTING.md`); `docs/phase01-qa-findings.md` (Steps 1–6 rollups with class and guard, the alarm exercise, pre-ship items); three spec-rot patches to the Step 6 task block (`detect-secrets scan --baseline` rewrites the baseline and exits 0, so the hook form is used; bandit over `src alembic`; web build before test); the root roadmap's Phase 1 acceptance criteria aligned with V1–V6. Verified: `--fast` 43/43 and `--security` 4/4 locally and in CI; a planted AWS example key fails check 39 and the secret scan; `--post` green on the maintainer's machine against the Compose services (see the QA findings). |
| 2026-09-16 | **Phase 1 Step 5.** Web foundation in `web/`: Next.js 16 (App Router, TypeScript strict, Tailwind CSS 4, ESLint 9 with `eslint-plugin-security` at `--max-warnings 0`), pnpm 10 via corepack, `.node-version` 22; shadcn/ui button, input, table, card, badge, tooltip (with the `cn` and `shadcn` runtime packages the CLI adds replaced by a local helper and inlined CSS); `next-themes` on `data-theme` with a toggle; `openapi-typescript` → committed `web/lib/api/schema.d.ts` (`pnpm generate:api`) and an `openapi-fetch` client (`web/lib/api/client.ts`) whose helpers return `ApiResult` (API error envelope, `Retry-After`, status 0 on transport failure) and resolve `fetch` per call; pages `/` (headline, global search with the `/` shortcut, coverage tiles from `/jurisdictions` and the judge and court totals, methodology link), `/search` (entity-type badges, 429 wait time), `/judges/[judgeId]` (identity, status badge, FJC biography link, sortable TanStack service table with `aria-sort`, "Source coverage" panel with source name, retrieved-at, truncated sha256 with copy-to-clipboard, parser version, ingest run, source export link, "Report a data issue" to the data-source issue template), `/courts/[courtId]` (court, type, jurisdiction, date form driving `/judges?court_id=&active_on=` with pagination), `/methodology` (ten principles, the association-is-not-causation statement, Phase 3 note), `/coverage` (Phase 2 note), `/about`, not-found and error boundaries; empty and error states on every fetch; skip link, landmarks, `scope="col"`, visible focus rings; security headers, no cookies, no third-party scripts, no fonts fetched; Vitest (client helpers with stubbed fetch, provenance panel truncation and copy, schema freshness, production-bundle scan for `JUDGEMETRICS_`) and Playwright `tests/e2e/smoke.spec.ts` (six scenarios); `infra/docker/web.Dockerfile` (node:22-alpine, corepack pnpm, standalone output, uid 10001, npm removed from the runtime, Trivy clean) with the Compose `web` service (profile `app`, port 3000); CI `web` (lint, typecheck, build, test, audit), `e2e` (Postgres with the three roles, migrate, FJC fixture ingest, API and web in the background, Chromium), and `container` extended to both images, all required by `test`; Dependabot `npm` for `/web`; `dev-web` task and Makefile target; hygiene tests for the web chassis; README, ARCHITECTURE "Web tier", AGENTS decisions. Verified locally against the live ingest: all pages in light and dark mode, `pnpm lint|typecheck|test|build|e2e` green, `pnpm audit` clean, the image serving `/methodology` as uid 10001. |
| 2026-09-16 | **Phase 1 Step 4.** Public API v1 (`docs/API.md`): `schemas/` (`Page[T]` with `items`/`total`/`limit`/`offset`/`next_offset`, `Provenance`, `ErrorBody`, judge/court/jurisdiction summaries and details, `SearchResult`; Pydantic v2 `from_attributes`); `repositories/` (typed queries returning rows plus totals; `count(*) OVER ()` pagination so a list is one statement; `selectinload` + chained `joinedload` so a judge detail is three; trigram `%` matches on `normalized_name`; `active_on`/`court_id`/`status` and `jurisdiction_id`/`court_type` filters; provenance selects only public columns, never `raw_object_path`); `services/` (search normalizing `q` with `normalize_person_name`, `pg_trgm.similarity_threshold` set per request with a bound `set_config`, judge and court matches unioned and ordered by `similarity()`; provenance blocks); `api/deps.py` (app-bound session per request, `PageParams` with `limit` default 25 / max 100 and `offset` ≥ 0, `StrictQuery` allow-lists rejecting unknown parameters with 422, `Cache-Control: public, max-age=60` on lists and details); `api/errors.py` (every non-2xx response an `ErrorBody`; validation errors name the parameter; database errors 503 without SQL; unhandled errors 500 without a trace); `api/identity.py` (ROADMAP §1.4 request identity: anonymous bucket keyed by client address, `X-Forwarded-For` honoured only with `trust_proxy`; optional `X-API-Key` scheme declared in OpenAPI); `api/ratelimit.py` (in-process token bucket on `/search`, burst 10 / 60 per minute by default, 429 with `Retry-After`, off under `env == test` unless enabled); routes `GET /judges`, `/judges/{id}`, `/judges/{id}/service`, `/courts`, `/courts/{id}`, `/jurisdictions`, `/jurisdictions/{id}`, `/search`; settings `trust_proxy`, `search_rate_limit_per_minute`, `search_rate_limit_burst`, `search_rate_limit_enabled`, `search_similarity_threshold`; CLI `judgemetrics openapi export [--out docs/openapi.json]` and the committed `docs/openapi.json` (exactly the health probes and the eight v1 paths) guarded by a unit test; `tests/` made a package with a module-scoped committed fixture ingest for the API tests (pagination bounds, unknown parameters, filters, 404/422/429/500/503 envelopes, provenance with 64-character sha256, no `raw_object_path` in any response) and the cursor-level query-count guard (judge detail ≤ 3, lists ≤ 2, search ≤ 2); `docs/API.md`, `docs/ARCHITECTURE.md` API layering and limiter, README endpoint list. Verified against the live local ingest (4,075 judges): all eight endpoints, `Sotomayer` → Sonia Sotomayor first, 429 after the burst. |
| 2026-09-16 | **Phase 1 Step 3.** `ingest/base.py` (the brief's connector protocol plus `source_id`, `parser_version`, `source_info`, and an optional checkpoint protocol; frozen drafts with natural keys); `ingest/store.py` (content-addressed immutable raw lake, `<source>/<yyyy>/<mm>/<sha256>.csv`, filesystem and S3/MinIO backends that refuse to overwrite); `ingest/http.py` (HTTPS-only downloads: 30 s timeout, 3 retries with backoff, 200 MB cap, `If-None-Match`/`If-Modified-Since`); `ingest/runner.py` (the fourteen steps; one publish transaction; `INSERT … ON CONFLICT` upserts that write only changed rows and merge JSONB identifiers; last-substantive-writer provenance on jurisdiction, court, judge; unchanged hashes short-circuit; new parser versions re-derive; refusals of synthetic sources and fixture ingests in production); `ingest/fjc/` (verified headers and vocabularies in `schema.py`, Polars string-only parsing projected to expected columns, normalization of names, status, court types, and state codes from `data/reference/us_states.csv`); `quality/checks.py` (service dates, overlaps, missing start dates, provenance); migration `0002_ingest_provenance` (`source_record_id` on the reference entities, natural-key unique indexes with `NULLS NOT DISTINCT`, `court.state_code`, JSONB `metadata` on `judge_service` and `source_record`, `ingest_run.parser_version`/`checkpoint`/`failure_reason`); CLI `ingest list-sources`, `ingest run <source> [--from-fixture DIR] [--force]`, `ingest runs`; the `ingest-fjc` target; Compose `minio-init` provisions the S3 application user; CI starts MinIO for the S3 contract test; fixture excerpt (25 judges, 42 service rows, 28 courts) with two data-quality issues chosen by row selection; unit tests (store, connector, normalizer, checks, registry) and integration tests (first run, idempotent second and forced runs, changed artifact, provenance to stored bytes, issues, validation failure, refusals, CLI); `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `data/README.md`; `docs/DATA_SOURCES.md` `fjc` entry with the verified headers. Live ingest verified 2026-09-16 against the Compose services (MinIO lake, ingest role): 4,075 judges, 4,775 service records, 159 courts, 1 jurisdiction (9,010 rows created), 20 data-quality issues (18 `service_overlap` warnings, 2 `missing_start_date`); the second live run received `304 Not Modified` for both files and created and updated nothing; a forced run re-parsed 8,850 rows and changed nothing. |
| 2026-09-16 | **Phase 1 Step 2.** `config.py` (pydantic-settings, `JUDGEMETRICS_` prefix, `.env` only when local, one URL per database role, `SecretStr` secrets); `logging.py` (structlog, ISO timestamps, JSON or console renderer, stdlib loggers routed through the same chain, `scrub_sensitive` processor with a documented denylist tested recursively); `main.py` `create_app()` with request-id and access-log middleware; `GET /api/v1/health` (version, git SHA, Alembic head, nothing else) and `GET /api/v1/ready` (200 at head, 503 with a reason, DSN never echoed); SQLAlchemy 2 models for all twenty-three canonical entities with the brief's field names and enums; reversible Alembic baseline `0001` (`pg_trgm`, enums, foreign-key and event-time indexes, trigram and JSONB GIN indexes, unique FJC `nid` expression index, grants that deny `judgemetrics_app` on `person_identifier` and `correction_request`); `normalization/names.py`; Typer CLI `judgemetrics` (`db upgrade|downgrade|current`, `serve`, `ingest list-sources`); `infra/docker/api.Dockerfile` (multi-stage, locked runtime deps, non-root, no `.env`, HEALTHCHECK) with the compose `api` service (profile `app`) and the CI `container` job (build, smoke, Trivy HIGH/CRITICAL gate) required by `test`; `migrate` and `dev-api` targets; unit tests (settings, scrubber, names, CLI) and integration tests (migration round trip, `Decision` requires `source_record_id`, app-role grants, both health probes) against the CI `postgres:17` service with the three roles created from the Compose init scripts. |
| 2026-09-16 | **Phase 1 Step 1.** Apache-2.0 `LICENSE`; `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue and PR templates; fail-closed `pre-commit` gate (ruff, mypy, bandit, detect-secrets with baseline, pip-audit over `uv.lock` at pre-push) observed to block a planted synthetic credential; `ci.yml` (`python`, `security`, aggregate `test`) with SHA-pinned actions and read-only `contents` permissions; `dependabot.yml` (uv, github-actions); `docker-compose.yml` with PostgreSQL 17 (`pg_trgm`, roles `judgemetrics_app`/`_ingest`/`_admin`) and MinIO (`judgemetrics-raw`, versioning on); `.env.example`; `up`/`down`/`gate` tasks; branch protection (`enforce_admins`, linear history, required `test`), squash-only merges, secret scanning and push protection; `tests/unit/test_repo_hygiene.py`. |

## Unresolved data-access questions

| # | Question                                                                                     | Source            | Blocks                    | Owner    | Status |
|---|----------------------------------------------------------------------------------------------|-------------------|---------------------------|----------|--------|
| 1 | Exact column headers of `judges.csv` and `federal-judicial-service.csv`; conditional-request support | `fjc`         | Phase 1 Step 3            | agent    | **resolved 2026-09-16** — 201 and 30 headers recorded in `docs/DATA_SOURCES.md` and `src/judgemetrics/ingest/fjc/schema.py`; the server sends `ETag` and `Last-Modified` and the connector uses both |
| 2 | Cook County open-data portal terms: republication of derived aggregates and pseudonymous case views, and commercial redistribution (Phase 9 snapshot tier) | `cook_sao`   | Phase 5 Step 1; Phase 9 §9.2 | operator | open   |
| 3 | Documented value sets for `charge_disposition`, `charge_disposition_reason`, bond types, sentence fields | `cook_sao` | Phase 5 attribution rules | agent    | open   |
| 4 | Stability of `case_participant_id` across the five Cook County datasets                       | `cook_sao`        | Phase 5 person resolution | agent    | open   |
| 5 | CourtListener API rate limits and terms including redistribution of API responses; whether docket entries and parties are bulk or API-only; RECAP coverage of federal criminal dockets | `courtlistener` | Phase 7; Phase 9 §9.2 | agent | open |
| 6 | PACER account, Case Locator API terms including redistribution, fee schedule, waiver threshold | `pacer`           | Phase 7 (feature-flagged); Phase 9 §9.2 | operator | open   |
| 7 | New York pretrial release data: files, cadence, data dictionary, presence of judge names, terms including redistribution (page returned HTTP 403 to automated fetch) | `ny_oca_pretrial` | Phase 7 candidate; Phase 9 §9.2 | operator | open — verify manually |
| 8 | Florida target jurisdiction: JDMS/UCR credentials, county clerk bulk or API offering, public-records process, cost, terms, fields; redistribution rights (aggregates, pseudonymous case-level, commercial) requested as a term of every agreement | `fl_jdms`, `fl_clerks` | Phase 5 §5.5, Phase 7; Phase 9 §9.2 | operator | open — research in Phase 5 |

## Known issues and limitations

- Case-level data-quality checks that need a case's filing date or
  status (`disposition_before_filing`, `event_order_impossible`,
  `subsequent_before_index`, `missing_disposition`) see only the cases
  drafted in the same run; a child row of a case that already exists in
  the database (a later export that ships only `charges.csv`) is not
  checked against it. Reading the parent case from the database is a
  small extension for the step that first needs it.
- There is no unmerge: a merge (system or reviewer) is reversed only by
  hand until Phase 6 ships the operation behind administrative
  authentication; the audit row carries what it needs. `er review
  decide` is refused in the production environment until then.
- Resolution scores are the rule set's ordinal labels, not calibrated
  probabilities (`docs/ENTITY_RESOLUTION.md`); Phase 6 measures the
  linkage error rates on real data and Phase 7 supplies the first scorer.
  `age_consistent` is null whenever a date of birth is missing because
  the synthetic source's `age_at_filing` is not ingested; attorney and
  geographic signals are deferred.
- `case_party.person_id` is never null for the synthetic source, so
  `person_resolution_confidence_missing` has no live instance yet.
- `unknown_category_measured` issues are run-level (no source record or
  entity); they are deduplicated by code and description, so a rerun
  with the same counts adds nothing and a changed count adds a new
  issue beside the old one rather than updating it.
- The log scrubber redacts any key containing `person_id`, which
  includes the table name `person_identifier`; the run log therefore
  reports that table's counts under `identifier_hashes`.
- `judgemetrics seed` refuses to regenerate into a directory whose
  manifest records a different scale or generator version unless
  `--force` is given (it never deletes anything); `--force` also
  re-parses unchanged artifacts, which changes nothing.
- The synthetic generator's `truth/metrics.json` computes the windowed
  outcome rates on the pretrial-release index only; disposition- and
  sentence-indexed rates and time-at-risk deferral after incarceration
  arrive under a new `TRUTH_VERSION` when Phase 3's registry defines
  them. `age_at_filing` is filled even when a date of birth is missing;
  a revocation is recorded after its case closed; the
  `missing_description` share is a package constant.
- `.secrets.baseline` allowlists the sha256 digests in
  `tests/fixtures/golden/manifest.json` (`detect-secrets` flags
  64-character hex strings), so regenerating the golden fixture ends
  with a baseline refresh scoped to the manifest
  (`docs/SYNTHETIC_DATA.md`, "Regenerating the golden fixture").
- Real case, charge, disposition, and defendant data begin in Phase 5;
  until then the only case-level source is the synthetic dataset,
  labelled as such on every surface (the `synthetic` flag, the badge,
  the banner) and refused in production. The FJC export is regenerated
  nightly, so a later live run records new source records for the
  changed files and updates only the rows whose values changed.
- The API integration modules that need case data commit a golden
  ingest per module through the `golden_fixture` fixture, which purges
  the whole `synthetic` source before and after because the golden and
  demo datasets share natural keys. With `JUDGEMETRICS_TEST_DATABASE_URL`
  set (Step 5) that happens in the scratch database and the demo seed
  is untouched; on the fallback database (the variable unset, one
  warning) the purge still removes the demo seed and each golden
  ingest's merges leave append-only `audit_log` rows (ids and counts
  only), so run `uv run poe seed` afterwards there.
- The demo-data banner reads `/coverage` on every request from the root
  layout, so every page is server-rendered on demand (no page is
  prerendered) and each page view costs one extra API call; a cached
  read (Next's `"use cache"` or an in-process TTL) is a later
  improvement.
- A case timeline places date-only facts at the start (`filed`) or end
  (`closed`) of their day; an event recorded after the closing date (a
  synthetic revocation) follows the `closed` entry, which is the record.
  Sentence entries carry no `actor_type` because the `sentence` table
  has none; the `sentencing` decision beside it does.
- `/judges/{id}/cases` validates `status` and `case_type` by shape, not
  against the vocabulary file, so a value outside it matches nothing
  rather than answering 422; the web form offers only the vocabulary.
- The e2e case flow discovers its synthetic judge and case through the
  API (a synthetic circuit court, then a closed case with a prosecutor
  dismissal, a judicial decision, and a sentence) rather than naming
  one, because the golden fixture (CI) and the demo seed (a developer's
  machine) name different judges.
- `judge.status` is derived from the latest appointment's termination
  and senior-status fields with a fixed mapping
  (`src/judgemetrics/ingest/fjc/schema.py`); an unmapped termination
  value yields `unknown` rather than a guess, and `court_type` values
  outside the verified vocabulary map to `other`.
- The unique indexes of revision 0002 use `NULLS NOT DISTINCT`, which
  needs PostgreSQL 15 or newer (Compose and CI run 17).
- Retired (Step 5): `uv run poe check` no longer empties a local live
  ingest. The migration round-trip test and every fixture ingest run
  against the scratch database `judgemetrics_test`
  (`JUDGEMETRICS_TEST_DATABASE_URL`, created by `uv run poe up`); a
  machine whose `.env` predates Step 5 must set the variable (the suite
  warns once and falls back to the old behaviour until it does).
- A `.env` written before Step 3 may name an S3 application user that
  MinIO does not know; `uv run poe up` (its `minio-init` job) now
  creates that user, so run it once more on such machines.
- Search similarity is computed over the whole normalized name with
  the `%` operator at threshold 0.3, so a misspelt surname finds a
  judge when the surname is a large share of the full name
  ("Sotomayer" → Sonia Sotomayor) but a short token against a long
  name ("Ginsberg" → "ruth bader ginsburg", 0.26) does not. Word
  similarity (`<%`, also GIN-indexable) would fit surname-only queries
  better; the search page (Step 5) uses the API as it is, so this
  remains an API-side improvement for a later step.
- The web tier inlines `NEXT_PUBLIC_API_BASE_URL` at build time, so the
  image is built per API origin (the Compose service bakes
  `http://api:8000`); a runtime-configurable origin needs a server-side
  variable and a rebuild-free path in a later phase. The web `e2e` CI
  job runs Chromium against a production build and adds roughly ten
  minutes to a pull request.
- `eslint-config-next` 16 depends on `eslint-plugin-react` 7, which
  fails to load under ESLint 10, so `web/` pins ESLint 9 (npm marks it
  deprecated, not vulnerable; `pnpm audit` is clean).
- The Supreme Court page lists retired justices as serving on a date
  after their retirement because the FJC interval ends only at
  termination (`active_on`, above); the court page says so beside the
  date form.
- `active_on` follows the FJC service interval, which ends with the
  appointment's termination (death, resignation, retirement), not with
  senior status; a judge on senior status is "active on" a date within
  the appointment, and `senior_status_date` is in the service record's
  `metadata`.
- The `/search` limiter is per process and per client address; a
  multi-worker deployment gets `workers × burst` until the Phase 8
  edge limits sit in front of it.
- API integration tests commit a fixture ingest per module and purge
  exactly that run afterwards. Retired with Step 5's scratch database:
  the FJC fixture no longer shares a database with the live ingest, so
  its rows never resolve to the live judges; the caveat still applies
  on the fallback database only (`JUDGEMETRICS_TEST_DATABASE_URL`
  unset), where `uv run poe ingest-fjc` restores a moved judge.
- `judicial_discretion_classification`, case status, charge disposition,
  release type, position type, and event type are free-text columns
  constrained by the versioned vocabulary file
  (`data/reference/case_vocabulary.yaml`) at ingest time, not by a
  database enum; the brief fixes only the enums the baseline creates.
  The versioned attribution rules of Phase 5 map real sources onto it.
- `correction_request.requester_contact` is Fernet-encrypted under
  `JUDGEMETRICS_CORRECTION_CONTACT_KEY` (`judgemetrics.security.crypto`);
  the corrections workflow that writes it arrives in Phase 3.
- The API image reports `git_sha: unknown` unless built with
  `--build-arg GIT_SHA=…` (CI passes `GITHUB_SHA`; Compose reads
  `GIT_SHA` from the environment).
- On the maintainer's machine native PostgreSQL instances hold ports
  5432 and 5433 and Windows reserves 9000, so the local `.env` overrides
  `POSTGRES_PORT` (5440) and `MINIO_API_PORT`; CI and fresh machines use
  the defaults.
- MinIO's community images are pulled from `quay.io/minio` (Docker Hub
  no longer serves them) and MinIO has announced maintenance mode for
  the community edition; the raw store is S3-compatible, so swapping
  the local object store later is a Compose change only.
- The first real state-court corpus (Cook County) is frozen at
  2024-12-30, lacks judge attribution on pretrial decisions, and has no
  failure-to-appear, rearrest, or release-violation events.
- GNU make is not installed on the maintainer's machine; the `Makefile`
  is a shim and `uv run poe <task>` is the primary interface.
- `scripts/verify_phase01.py --post` reads V2.4 (the `container` job)
  and V6.1 (`phase-verify (01)`) from `gh pr checks`, so those two rows
  are `SKIP` on a branch with no open pull request and `PASS` only once
  the PR's checks are green; V2.3, V3.3, and V4.2 need a configured
  database (`.env` or `JUDGEMETRICS_DATABASE_URL`) and V5.3 needs the
  API and web app running, each reported as `SKIP` with the reason
  otherwise. `--post` and `--all` run the Playwright smoke before the
  Python suites, an ordering chosen when the migration round-trip test
  still emptied the configured database; with the scratch test
  database (Step 5) the order no longer matters.

## Next milestones

1. **Phase 2 exit (`v0.2.0-phase-2`).** Deterministic synthetic justice
   dataset with known truth loaded through the connector path, entity
   resolution with a review queue, case timelines, property tests and
   the golden dataset; `verify_phase02.py` in the `phase-verify`
   matrix. (Phase 1 exit `v0.1.0-phase-1` reached 2026-09-16.)
2. **First milestone (`v0.3.0-phase-3`).** The brief's seventeen-item
   checklist passes end to end on synthetic data plus FJC judges from
   `uv run poe bootstrap` alone.
3. **First real metrics (`v0.5.0-phase-5`).** Cook County ingested with
   attribution and coverage; the first real metric published with a
   complete provenance trace; the Florida acquisition plan written.
