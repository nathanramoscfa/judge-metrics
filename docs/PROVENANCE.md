<!-- docs/PROVENANCE.md -->
# Provenance: from a published number back to the raw artifacts

Every statistic JudgeMetrics publishes must be traceable to the
versioned source records and code it was computed from
(`ROADMAP.md` §5 "Provenance chain"; the brief's
`<provenance_requirement>`). This document describes the chain as it is
stored, the trace that reconstructs it (`judgemetrics provenance trace`
and `GET /api/v1/metrics/{observation_id}/provenance`), the completeness
rule, and an example over the golden fixture.

## The chain

The brief's chain, top-down, and where each link lives:

| Link                                        | Where it is stored                                                                                         |
|---------------------------------------------|------------------------------------------------------------------------------------------------------------|
| Published metric                            | A `metric_definition` row: slug, version, numerator, denominator, eligibility, attribution rule, threshold (`data/reference/metric_registry.yaml`, `docs/METHODOLOGY.md`). |
| `metric_observation`                        | The number: subject, source, period, window, dimension, `eligible_count`, `cohort_size`, `observed_count`, rate, bounds, value, distribution, `suppressed_flag`, the registry, methodology, and code versions, `computed_at`, `superseded_at`. |
| The snapshot                                | `metric_snapshot`: the content hash of the Parquet export the number was computed from, its label, export time, code version, row counts, and storage URI (`docs/ARCHITECTURE.md` "Metrics engine"). `metrics verify` recomputes the number from it. |
| Eligible canonical events                   | `metric_observation_member`: one row per canonical row behind the number — `member_kind` (`decision`, `charge`, `court_case`, `sentence`, `court_event`, `justice_event`), `member_id`, `counted` (in the numerator), `followed` (in the denominator after censoring). Entity ids only, never a person id. |
| Canonical cases, decisions, outcomes        | The member rows themselves, each with its `case_id` (a justice event's `related_case_id`) and its `source_record_id`. |
| `source_record`                             | One retrieved artifact: `external_record_id`, `raw_sha256`, `retrieved_at`, `parser_version`, `ingest_run_id`, the artifact URI in its `metadata`. |
| Raw source artifact                         | The immutable object in the raw lake under the record's sha256 (`docs/ARCHITECTURE.md` "The raw lake"); its storage key is internal and never returned. |
| Source system, retrieval time, checksum, parser version | The `source` row (key, owner, type, coverage window, observable outcomes) and the record's retrieval facts above. |

`publish.check_chain` enforces the chain *before* an observation is
written: every member id of every draft must be present in the
snapshot's own tables, otherwise `ProvenanceError` is raised, nothing is
written, and the caller rolls back. An observation whose chain cannot be
reconstructed is therefore never published.

## The trace

`judgemetrics.metrics.provenance.trace(session, observation_id)`
reconstructs the chain for one observation in three statements,
whatever the observation holds:

1. the observation joined to its definition, its snapshot, and its
   source;
2. its members, each outer-joined to the canonical row its kind names,
   yielding the row's case and `source_record_id` — a member whose row
   no longer exists yields neither and is counted as unresolved;
3. the distinct source records behind those rows joined to their
   sources, built over the member statement as a subquery rather than
   an `IN` list, so an observation with thousands of members never
   exceeds the bind-parameter limit.

The trace names no person, no hash of a person identifier, and never the
lake's storage key (`raw_object_path` is not selected). Members are
grouped by kind with counts (`members`, `counted`, `followed`,
`resolved`) and the distinct case ids they belong to, which are what a
reader can follow (`/cases/{id}`).

### The completeness rule

A trace is `complete` when:

- every member resolved to a canonical row (`unresolved_members == 0`);
- every row's source record was found (`unresolved_records == 0`);
- every source record carries a 64-hex sha256 digest of its stored
  artifact.

This is `check_chain`'s rule re-checked against the live tables after
publication. `tests/golden/test_golden_provenance.py` asserts that every
current observation of the golden fixture traces complete, that deleting
one member's canonical row inside a rolled-back session makes the trace
incomplete (the row is the member's link to its record; the record
itself is protected by the `RESTRICT` foreign keys of every row it
produced), and that `check_chain` refuses a draft naming a foreign id.

### The command

```sh
uv run judgemetrics provenance trace <observation id>          # the chain as text
uv run judgemetrics provenance trace <observation id> --json   # the same chain as JSON
```

Reads as the read-only role. Exit 0 when the chain is complete, 1 when
it is not (the last line reads `complete: no` and an `INCOMPLETE:` line
counts what is missing), 2 for a malformed or unknown id. The text form
prints the chain top-down in the brief's order: the published metric,
the observation, the snapshot, the eligible canonical events by kind,
the canonical cases, the source records with their raw artifacts, the
source systems, and the verdict. The JSON form is the same chain with
the same keys the endpoint serves, plus the operator-only fields below.
Superseded observations trace too (`superseded: <time>`), so history
can be audited.

### The endpoint

`GET /api/v1/metrics/{observation_id}/provenance` returns
`ObservationProvenance` (`docs/API.md` "Metrics"): the same chain for a
*current* observation — 404 for an unknown or superseded id — in at
most six statements (three today). Two fields of the CLI's output are
withheld on the public surface, the way `raw_object_path` is never
returned: the snapshot's `storage_uri` (a path on the operator's
machine) and any artifact URI that is not a public `http(s)` URL (a
fixture file or the synthetic dataset read from the operator's
filesystem; the FJC artifacts keep their URLs). The observation block is
the public `Observation` shape, so a suppressed observation's numbers
are null in the trace as everywhere else.

## Example: a golden-fixture observation

The golden fixture (`tests/fixtures/golden`, seed 7) ingested into an
empty database and computed with `metrics compute`, then
`judgemetrics provenance trace 98793363-c99c-4bef-a700-31a1995dded6`
(the judge `J-0003`'s 365-day new-case rate after pretrial release).
Ids and times are those of that run; the artifact digests are the
fixture's and are stable across runs.

```text
published metric: new_case_rate (version 1) — New-case rate after pretrial release
observation 98793363-c99c-4bef-a700-31a1995dded6
  subject: judge 34861e1a-0d2d-4afc-9734-6eff261e8730
  source: synthetic (synthetic)
  period: 2019-01-01 to 2021-12-31; window: 365 days; dimension: —
  numerator / denominator: 1 / 4; eligible: 9; rate: 0.25; interval: [0.045587, 0.699358]; value: —
  suppressed: yes (threshold 10)
  versions: methodology 0.1; registry 1; code 0.1.0+722f083
  computed: 2026-09-19T19:47:03.808517+00:00; superseded: no
snapshot 2e0cfd16915a192975d4b3ae695da80e765bdef8fec4c74934901f7d4a0c7edf
  label: docs example; exported: 2026-09-19T19:47:01.713344+00:00; code 0.1.0+722f083; registry 1; methodology 0.1
  storage: file:///…/snapshots/2e0cfd16915a192975d4b3ae695da80e765bdef8fec4c74934901f7d4a0c7edf
  rows: assignments=78, cases=60, charges=99, courts=3, decisions=128, events=213, judges=6, justice_events=30, persons=42, sentences=20, sources=2
eligible canonical events: 9 member(s)
  decision: 9 (counted 1, followed 4); resolved 9; cases 9
canonical cases: 9
  1b4ec1d4-80d8-4582-989c-ead4fee7142a
  1d9d4368-02b9-4d5f-a7c4-6a314c1b07a2
  36d3b147-fc05-43ce-a710-a36069207ac6
  3961580b-b808-4d58-b26c-f0ed78e3b810
  3c67c347-e100-4337-ac20-c4c2bd59bfb6
  490b57c2-2960-4ef1-bb88-bc1b606c31c4
  8dbc5888-abdd-4774-bcfe-9ff1dcb0c4be
  9f8c75ab-9706-4d4e-9d2a-fb7e62d4ca96
  fb67dedb-1817-467e-85b1-558d0bee0c1b
source records: 1
  9aa63193-790b-458a-ab54-7a02f56856ed synthetic source/decisions.csv sha256=a3cc2d14aea0d92839b899d773c10a69cca5d99286460cdb0afdd6c8ba951949 retrieved=2026-09-19T19:47:00.935412+00:00 parser=1 run=13914f17-3138-4be8-8bf2-0a2ad03f3304
    raw artifact: file:///…/tests/fixtures/golden/source/decisions.csv
source systems: 1
  synthetic: this repository; type synthetic; synthetic yes; coverage 2019-01-01 to 2021-12-31; observable outcomes failure_to_appear, new_case, new_charge, reconviction, revocation
complete: yes
```

Reading it: the number is 1 new case among the 4 cohort members
followed for 365 days, out of 9 eligible pretrial releases — suppressed,
because the denominator is below the threshold of 10, so the API
withholds `1 / 4` and `0.25` and serves the eligible count and the
threshold instead. The 9 members are decisions, one per case; all 9
came from `source/decisions.csv`, whose sha256 identifies the exact
bytes in the raw lake; the snapshot hash identifies the exact export the
number was computed from, which `judgemetrics metrics verify`
reproduces. The same chain through the endpoint:

```sh
curl -s 'http://127.0.0.1:8000/api/v1/metrics/98793363-c99c-4bef-a700-31a1995dded6/provenance'
```

returns `observation` (the public shape: `numerator`, `denominator`,
`rate`, `lower`, `upper` null because it is suppressed), `snapshot`
(without `storage_uri`), `members`, `source_records` (with
`artifact_uri: null` for the fixture file), `sources`, and
`complete: true`.
