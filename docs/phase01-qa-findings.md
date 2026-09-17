<!-- docs/phase01-qa-findings.md -->
# Phase 1 — QA findings

The rollup of every finding surfaced while executing Phase 1 (Steps 1
through 6 of [`phase01-roadmap.md`](phase01-roadmap.md)), classified
per `ROADMAP.md` §5 "Defect handling & triage", with the guard each one
left behind ("prevent the class, not the instance"). Findings that were
recorded elsewhere at the time (pull-request bodies, `docs/ROADMAP.md`
known issues, `AGENTS.md` decisions) are gathered here so the phase has
one QA record; the guard column names the test, hook, CI job, or
verify-script check that now catches a recurrence.

Verification lives in `scripts/verify_phase01.py` (43 static checks,
the tool suites, and the V1–V6 matrix; see "Step 6" below) and runs in
CI through `.github/workflows/phase-verify.yml`.

## Step 1 — Repository bootstrap, command interface, security gate, CI

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 1.1 | `pip-audit --strict` over the live environment fails because the editable `judgemetrics` project is not on PyPI, so the gate audited the wrong target. | Spec rot | `scripts/audit_deps.py` exports `uv.lock` with hashes and audits that (`pip-audit --strict --require-hashes`); it is the pre-push hook, the CI `security` job, and `verify_phase01.py --security`. Task block patched. |
| 1.2 | `docker compose up -d --wait` treats the cleanly exited one-shot `minio-init` job as a failure. | Spec rot | `up` is a sequence task (`up-services`, then `up-init`); static check 10 requires the task; `test_repo_hygiene.py` checks the Makefile mirror. |
| 1.3 | MinIO's Docker Hub repository is no longer served. | Upstream gap | Images pinned from `quay.io/minio` at a release tag; Dependabot `docker` covers `infra/docker`. |
| 1.4 | Planted-secret exercise: a scratch file with the AWS documentation example key pair was staged; the pre-commit hook rejected the commit (ruff S105, bandit B105, detect-secrets AWS key / high-entropy / keyword). | Security finding (exercise, expected) | The gate is fail-closed and observed to block; static check 39 is the in-tree backstop; `test_env_example_has_only_placeholders` and static check 9 keep `.env.example` placeholder-only and `.env` untracked. |
| 1.5 | Workflow files are a trust boundary: an unpinned action or a broad `permissions:` would let a compromised upstream act with the repository token. | Process improvement | Static checks 6, 7, and 43 require a 40-hex SHA on every `uses:` and a top-level `permissions:` in `ci.yml` and `phase-verify.yml`; `test_repo_hygiene.py` checks the same. |

## Step 2 — Application core, canonical schema, API image

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 2.1 | The API image's Debian packages and pip's vendored `msgpack`/`setuptools` tripped the Trivy HIGH/CRITICAL gate. | Security finding | The runtime stage applies security updates and removes pip; the CI `container` job scans both images on every PR (`ignore-unfixed`, exit code 1). V2.4 reads that job through `gh pr checks`. |
| 2.2 | A readiness probe against an unreachable host hung for minutes on Windows. | Implementation bug | `make_engine` sets a 5-second psycopg `connect_timeout`; `test_health.py` covers the 503 path. |
| 2.3 | Migrations that import the models drift silently from the schema. | Process improvement | Migrations are self-contained (explicit enums, `create_type=False`); `uv run alembic check` must report no drift; `test_migrations.py` round-trips the baseline. |
| 2.4 | `alembic.runtime.migration` logged at INFO on every readiness probe. | Implementation bug | Raised to WARNING in `configure_logging`; the access log carries the request id instead. |
| 2.5 | The migration round-trip test downgrades the configured database to base, so `uv run poe check` empties a local live ingest. | Process improvement | Documented in `docs/ROADMAP.md` known issues and `AGENTS.md`; a scratch database for that test is a Phase 2 follow-up (see "Pre-ship items"). |

## Step 3 — Ingest framework and the FJC connector

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 3.1 | The baseline schema had no provenance column on `jurisdiction`, `court`, `judge`, no natural-key unique indexes for upserts, no `court.state_code`, and no place for service metadata. | Upstream gap | Revision `0002_ingest_provenance`; `test_migrations.py` and `test_fjc_ingest.py` (idempotent second run creates zero rows; provenance hashes match stored bytes). |
| 3.2 | Compose `minio-init` created the bucket but not the S3 application user named by `JUDGEMETRICS_S3_ACCESS_KEY_ID`. | Upstream gap | `minio-init` provisions that user when it differs from the root user; `test_store_s3.py` runs the S3 contract against MinIO in CI. |
| 3.3 | `judges.csv` carries `Gender` and `Race or Ethnicity`; a connector that read the full header set would carry restricted attributes into a payload. | Data-semantics finding (restricted attributes) | The parser projects rows to the expected columns; the fixture drops both columns; `test_fjc_connector.py` asserts neither header reaches a payload; static check 27 requires the verified header set in `docs/DATA_SOURCES.md`. |
| 3.4 | `docs/ROADMAP.md` question 1 (exact FJC headers, conditional-request support) was open until the live check. | Data-access question | Resolved 2026-09-16 and recorded; the connector depends only on verified facts (`schema.py` drift → warning, missing expected header → the run fails naming it). |
| 3.5 | Live data-quality issues (18 `service_overlap`, 2 `missing_start_date`) are real source facts, not defects. | Data-semantics finding | `quality/checks.py` persists them as `data_quality_issue` rows tied to the run; the fixture plants two by row selection so `test_quality_checks.py` exercises the path with real records. |

## Step 4 — Public API v1

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 4.1 | Whole-name trigram similarity at 0.3 finds "Sotomayer" but not a short misspelt surname against a long name ("Ginsberg" → "ruth bader ginsburg", 0.26). | Data-semantics finding | Documented in `docs/ROADMAP.md`; `test_api_search.py` pins the working case; word similarity (`<%`) is a Phase 2+ improvement. |
| 4.2 | `active_on` follows the FJC service interval, which ends at termination rather than senior status. | Data-semantics finding | Documented in `docs/ROADMAP.md` and `docs/API.md`; `senior_status_date` is kept in the service record's `metadata`; the court page says so beside its date form. |
| 4.3 | `raw_object_path` and the DSN must never leave the API. | Security finding (design) | Provenance selects only public columns; `SQLAlchemyError` → 503 without text; `test_api_*.py` assert no `raw_object_path` in any response and no SQL in error bodies. |
| 4.4 | A route could accept an undocumented query parameter silently. | Process improvement | `StrictQuery` allow-lists per route return 422; `test_openapi.py` checks each allow-list against the OpenAPI parameters and diffs `docs/openapi.json` against the generated document (V4.3). |
| 4.5 | An N+1 regression would pass every functional test. | Process improvement | `test_query_counts.py` bounds statements per endpoint (detail ≤ 3, lists and search ≤ 2). |
| 4.6 | The literal header and scheme names `X-API-Key` and `ApiKey` trip the secret scanner. | Security finding (false positive) | Allowlisted inline with `# pragma: allowlist secret`; the baseline stays empty of real findings. |

## Step 5 — Web foundation

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 5.1 | `NEXT_PUBLIC_API_BASE_URL` is inlined at build time, so the web image is built per API origin. | Architectural question | Documented in `docs/ROADMAP.md`; a runtime-configurable origin is a later-phase item; the Compose `web` service bakes `http://api:8000`. |
| 5.2 | `eslint-config-next` 16 depends on `eslint-plugin-react` 7, which does not load under ESLint 10. | Upstream gap | `web/` pins ESLint 9 (deprecated, not vulnerable; `pnpm audit` clean); Dependabot `npm` for `/web` will surface the fix. |
| 5.3 | The shadcn CLI resolved `cn` to a separate npm package and added the `shadcn` CLI as a runtime dependency. | Implementation bug | Replaced by `lib/utils.ts` and inlined CSS; recorded in `AGENTS.md` so a re-run gets the same cleanup. |
| 5.4 | `openapi-fetch` captures `globalThis.fetch` at import time and bypasses test stubs. | Implementation bug | The client resolves `fetch` per call; Vitest client tests stub it. |
| 5.5 | A server-only variable could reach the client bundle. | Security finding (design) | `bundle-secrets.test.ts` scans the production build for `JUDGEMETRICS_`; the CI `web` job builds before it tests so the scan has output; `verify_phase01.py --node` keeps that order. |
| 5.6 | The Supreme Court page lists retired justices as serving on a later date (consequence of 4.2). | Data-semantics finding | Explained beside the date form; no data change. |

## Step 6 — Verification script

| # | Finding | Class | Guard added |
|---|---------|-------|-------------|
| 6.1 | The task block's `--security` mode names `detect-secrets scan --baseline .secrets.baseline`, which rewrites the baseline (adding whatever it finds) and exits 0 — verified with a planted AWS example key: `scan` exit 0 and the key written into the baseline copy; `detect-secrets-hook` exit 1. | Spec rot | `--security` runs `detect-secrets-hook --baseline .secrets.baseline` over every tracked file (the pre-commit hook's form, batched under the Windows argv limit); the Step 6 task block in `phase01-roadmap.md` is patched. |
| 6.2 | Check 39 (the security backstop) would match its own regex source in `test_repo_hygiene.py` and the roadmap's prose if it searched for the bare string `-----BEGIN`. | Implementation bug (caught while writing) | The backstop matches complete headers only (`-----BEGIN [A-Z ]*PRIVATE KEY-----`, `-----BEGIN [A-Z ]+-----`, `AKIA[0-9A-Z]{16}`) over `git ls-files` of the five trees, excluding the lockfile, so `node_modules` and build output never enter the scan. |
| 6.3 | `bandit -r src` in the task block is narrower than the gate (`src alembic`). | Spec rot | `--security` scans `src` and `alembic`, the same surface as the pre-commit hook and the CI `security` job. |
| 6.4 | The `pnpm test` bundle scan needs a production build, so the task block's suite order (lint, typecheck, test, build) would fail under `CI=true`. | Spec rot | `--node` and V5.2 run build before test, as `ci.yml` does. |
| 6.5 | A check-name mismatch between the workflow and branch protection would leave the new check unrequired without any error. | Process improvement | The job is named `phase-verify (${{ matrix.phase }})`; the required context `phase-verify (01)` is recorded in `CONTRIBUTING.md` "Repository settings" beside `test`; `--post` V6.1 reads that check by name. |
| 6.6 | Alarm exercise: a deliberately broken static check (check 5 pointed at a non-existent baseline path) was pushed to the pull request. `phase-verify (01)` failed on `[FAIL] 05` and the aggregate `test` check failed through `test_verify_script_fast_exits_zero`; both passed after the fix. See "Alarm exercise" below. | Process improvement (exercise, expected) | The phase's alarm is those two required checks; the unit test ties the `test` check to the verify script so a red `--fast` can never merge. |
| 6.7 | First CI run of `phase-verify (01)`: `pnpm --dir web audit` from the repository root failed with `ERR_PNPM_BAD_PM_VERSION` — corepack reads the `packageManager` pin from the package.json of the directory it is invoked in, found none at the root, downloaded pnpm 12.4.2, and that pnpm refused to run against `web/`'s pinned 10.14.0. `ci.yml` never hit this because its `web` job sets `working-directory: web`. | Implementation bug (caught by the new check on its own PR) | The script runs every pnpm script with `cwd=web/` (the `pnpm` helper); the `phase-verify` check runs `--security` on every PR, so a regression fails the required check. |

### Alarm exercise

Recorded per the Step 6 acceptance criterion ("both were seen to fail on
a deliberately broken check during this step and then pass after the
fix"):

| Event | Commit | `phase-verify (01)` | `test` |
|-------|--------|---------------------|--------|
| Deliberate break (check 5 → `.secrets.baseline.missing`) | see PR #10 timeline | fail | fail |
| Fix (check 5 restored) | see PR #10 timeline | pass | pass |

## Pre-ship items

Documented limitations at the Phase 1 exit (`v0.1.0-phase-1`); none
blocks the tag, each is on a later phase's plan:

- **No deployed environment.** The only runtime is the maintainer's
  machine and CI; "deployed" means the merged commit runs under
  `uv run poe up`, `migrate`, `dev-api`, and `dev-web`. Staging and
  production arrive in Phase 8 (`ROADMAP.md` "Release & deployment
  strategy").
- **FJC only.** The one ingested source is the Federal Judicial Center
  biographical directory: judges, service records, courts, one
  jurisdiction. No case, charge, disposition, or defendant data exists;
  Phase 2 adds the synthetic justice dataset and Phase 5 the first real
  state-court corpus.
- **Demographics not ingested.** `judges.csv` columns `Gender` and
  `Race or Ethnicity` are never parsed and `demographics.csv` is never
  fetched (Step 3 finding 3.3). Restricted attributes, when any are
  ever needed, enter only the restricted schema under Phase 4's rules.
- **In-process rate limiter only.** The `/search` token bucket is per
  process and per client address; a multi-worker deployment gets
  `workers × burst` until Phase 8 places edge limits in front of it.
- **Whole-name search similarity** (finding 4.1) and the **FJC service
  interval semantics** (findings 4.2, 5.6) are documented data
  semantics, not defects.
- **Build-time API origin** in the web image (finding 5.1).

Phase 2 follow-ups carried forward (each becomes an issue or a step
item, not silent work):

1. A scratch database for `test_migrations.py` so `uv run poe check`
   stops emptying a local live ingest (finding 2.5); the same applies to
   the API tests' module-scoped fixture ingest on a database that also
   holds the live export (`docs/ROADMAP.md` known issues).
2. Word similarity (`<%`) for surname-only search queries (finding 4.1).
3. A runtime-configurable API origin for the web image (finding 5.1).
4. Move `web/` to ESLint 10 when `eslint-plugin-react` supports it
   (finding 5.2).
5. `verify_phase02.py` follows this script's pattern (argparse modes,
   numbered static checks over `pathlib`/`re`/`json`/`git ls-files`,
   subprocess suites, `[PASS] NN` / `[FAIL] NN` lines, summary table,
   exit 0/1) and joins the `phase-verify.yml` matrix as `"02"`.
