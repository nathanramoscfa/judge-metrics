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

**Phase 1 — Foundation, Canonical Schema, and the FJC Judge Slice.**
Not started. The operator pre-step in
[`docs/phase01-roadmap.md`](phase01-roadmap.md) (initial commit and
GitHub remote) is pending; Step 1 begins on branch
`feature/phase01-step1-bootstrap` in a fresh session.

## Completed

| Date       | Item                                                                                              |
|------------|---------------------------------------------------------------------------------------------------|
| 2026-09-15 | Repository scaffolded: uv project on Python 3.13, ruff, mypy (strict), pytest, pytest-cov, poethepoet task interface with a `Makefile` shim; `uv run poe check` green. |
| 2026-09-15 | roadmodel 0.2.33 installed in the `planning` group; planning kit exported to `planning/`.         |
| 2026-09-15 | Brief archived verbatim under `docs/brief/`.                                                      |
| 2026-09-15 | Project roadmap (`ROADMAP.md`, v2) and Phase 1 execution roadmap authored with per-step model selections. |
| 2026-09-15 | Data-source register (`docs/DATA_SOURCES.md`) with live verification of FJC, Cook County, and CourtListener. |
| 2026-09-16 | Root roadmap v2.1: post-launch Phase 9 (sustainability and data products) added; §1.4 request-identity hook, §5.5 redistribution rights, and §6.4 commercial-licensing scope pulled forward; **Redistribution** field added to every source-register entry. |

## Unresolved data-access questions

| # | Question                                                                                     | Source            | Blocks                    | Owner    | Status |
|---|----------------------------------------------------------------------------------------------|-------------------|---------------------------|----------|--------|
| 1 | Exact column headers of `judges.csv` and `federal-judicial-service.csv`; conditional-request support | `fjc`         | Phase 1 Step 3            | agent    | open — read at first fetch |
| 2 | Cook County open-data portal terms: republication of derived aggregates and pseudonymous case views, and commercial redistribution (Phase 9 snapshot tier) | `cook_sao`   | Phase 5 Step 1; Phase 9 §9.2 | operator | open   |
| 3 | Documented value sets for `charge_disposition`, `charge_disposition_reason`, bond types, sentence fields | `cook_sao` | Phase 5 attribution rules | agent    | open   |
| 4 | Stability of `case_participant_id` across the five Cook County datasets                       | `cook_sao`        | Phase 5 person resolution | agent    | open   |
| 5 | CourtListener API rate limits and terms including redistribution of API responses; whether docket entries and parties are bulk or API-only; RECAP coverage of federal criminal dockets | `courtlistener` | Phase 7; Phase 9 §9.2 | agent | open |
| 6 | PACER account, Case Locator API terms including redistribution, fee schedule, waiver threshold | `pacer`           | Phase 7 (feature-flagged); Phase 9 §9.2 | operator | open   |
| 7 | New York pretrial release data: files, cadence, data dictionary, presence of judge names, terms including redistribution (page returned HTTP 403 to automated fetch) | `ny_oca_pretrial` | Phase 7 candidate; Phase 9 §9.2 | operator | open — verify manually |
| 8 | Florida target jurisdiction: JDMS/UCR credentials, county clerk bulk or API offering, public-records process, cost, terms, fields; redistribution rights (aggregates, pseudonymous case-level, commercial) requested as a term of every agreement | `fl_jdms`, `fl_clerks` | Phase 5 §5.5, Phase 7; Phase 9 §9.2 | operator | open — research in Phase 5 |

## Known issues and limitations

- No application code, database, or ingested data exists yet.
- The first real state-court corpus (Cook County) is frozen at
  2024-12-30, lacks judge attribution on pretrial decisions, and has no
  failure-to-appear, rearrest, or release-violation events.
- GNU make is not installed on the maintainer's machine; the `Makefile`
  is a shim and `uv run poe <task>` is the primary interface.

## Next milestones

1. **Phase 1 exit (`v0.1.0-phase-1`).** Canonical schema behind
   reversible migrations; FJC judges ingested idempotently with
   provenance; API v1 and the web judge page running locally; CI with
   the security gate and container scan; branch protection live.
2. **First milestone (`v0.3.0-phase-3`).** The brief's seventeen-item
   checklist passes end to end on synthetic data plus FJC judges from
   `uv run poe bootstrap` alone.
3. **First real metrics (`v0.5.0-phase-5`).** Cook County ingested with
   attribution and coverage; the first real metric published with a
   complete provenance trace; the Florida acquisition plan written.
