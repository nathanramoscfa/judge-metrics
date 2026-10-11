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
| The outcome model (adjusted observations)   | Phase 4 Step 3: an `observed_expected` observation's `outcome_model_id` → the `outcome_model` row (content hash, specification and model versions, target, window, seed, status) and its canonical JSON artifact under the snapshot directory — the coefficients and bootstrap replicates the expected count, the pooled ratio, and the interval were computed from (`docs/ARCHITECTURE.md` "Observed-to-expected ratios"). `metrics verify` recomputes the number from the snapshot and that artifact. |
| Eligible canonical events                   | The observation's **member family** (Phase 5 Step 6; `docs/DATA_MODEL.md` "Member families"): `metric_observation.member_family_id` → `metric_member_family` (`member_kind`: `decision`, `charge`, `court_case`, `sentence`, `court_event`, or `justice_event`; `members_hash`) and its `metric_member` rows — each canonical row once, with the calendar year, dimension value, and per-window `counted` and `followed` flags that cut it into the observations of every window and year. The observation's own members are a filter of the family (`MemberFamily.project`, in SQL `member_store.projection`). Entity ids only, never a person id. |
| Canonical cases, decisions, outcomes        | The member rows themselves, each with its `case_id` (a justice event's `related_case_id`) and its `source_record_id`, resolved from the canonical table the family's kind names. |
| `source_record`                             | One retrieved artifact: `external_record_id`, `raw_sha256`, `retrieved_at`, `parser_version`, `ingest_run_id`, the artifact URI in its `metadata`. |
| Raw source artifact                         | The immutable object in the raw lake under the record's sha256 (`docs/ARCHITECTURE.md` "The raw lake"); its storage key is internal and never returned. |
| Source system, retrieval time, checksum, parser version | The `source` row (key, owner, type, coverage window, observable outcomes) and the record's retrieval facts above. |

`publish.check_chain` enforces the chain *before* a subject's observations
are written: every member id of every draft's family must be present in the
snapshot's own tables (a binary search of the family's distinct ids in the
snapshot's sorted id column of the family's kind), otherwise `ProvenanceError`
is raised, nothing of that subject is written, and the caller rolls back. An
observation whose chain cannot be reconstructed is therefore never published.

## The trace

`judgemetrics.metrics.provenance.trace(session, observation_id, limit=100,
offset=0)` reconstructs the chain for one observation in three statements,
whatever the observation holds (a page of members past the end of a
non-empty set costs a fourth, for the totals):

1. the observation joined to its definition, its snapshot, its source, its
   member family, and — outer-joined, so the count stays three — the outcome
   model an adjusted observation cites;
2. its members: the observation's cut of the family (the family's rows for its
   calendar year, flag slot, and dimension value), each outer-joined to the
   canonical row the family's kind names, yielding the row's case and
   `source_record_id` — a member whose row no longer exists yields neither and
   is counted as unresolved. The statement returns the **totals over every
   member** (members, counted, followed, resolved, without a source record,
   distinct cases) as window aggregates computed in the database before the page
   is cut, and one **page** of members ordered by member id: `limit` (1 to
   1,000, default 100) from `offset`;
3. the distinct source records behind *all* the members (not only the page's)
   joined to their sources, built over the same common table expression rather
   than an `IN` list, so an observation with thousands of members never exceeds
   the bind-parameter limit.

The trace names no person, no hash of a person identifier, and never the
lake's storage key (`raw_object_path` is not selected). Members are
grouped by kind with counts (`members`, `counted`, `followed`,
`resolved`, and the distinct `cases`) and the page's `member_ids` and
`case_ids` — the cases a reader can follow (`/cases/{id}`). A response is
bounded by its page, so one request cannot pull a court's whole case list; the
completeness rule below is judged over every member, never the page.

### The completeness rule

A trace is `complete` when:

- every member resolved to a canonical row (`unresolved_members == 0`);
- every row's source record was found (`unresolved_records == 0`);
- every source record carries a 64-hex sha256 digest of its stored
  artifact;
- for an adjusted observation (Phase 4 Step 3), the cited model's artifact
  exists under the configured snapshot directory — the path rebuilt from
  the snapshot hash and the model's content hash, both validated, never
  from `storage_uri` — and hashes to the content hash. The trace needs the
  settings to look (`provenance trace` passes them); without them an
  adjusted chain is reported incomplete rather than assumed whole.

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
uv run judgemetrics provenance trace <observation id> --limit 20 --offset 40   # members 41-60
```

Reads as the read-only role. Exit 0 when the chain is complete, 1 when
it is not (the last line reads `complete: no` and an `INCOMPLETE:` line
counts what is missing), 2 for a malformed or unknown id. The text form
prints the chain top-down in the brief's order: the published metric,
the observation (with its suppression reason, and an adjusted
observation's expected count, expected rate, pooled ratio, and pooling
weight), the snapshot, the outcome model of an adjusted observation with
its artifact check (`artifact: ok`), the eligible canonical events by kind,
the canonical cases, the source records with their raw artifacts, the
source systems, and the verdict. The JSON form is the same chain with
the same keys the endpoint serves, plus the operator-only fields below.
Superseded observations trace too (`superseded: <time>`), so history
can be audited.

### The endpoint

`GET /api/v1/metrics/{observation_id}/provenance` returns
`ObservationProvenance` (`docs/API.md` "Metrics"): the same chain for a
*current* observation of a kind the API serves (every kind since Phase 4
Step 5) — 404 for an unknown or superseded id — in at most six statements
(three today). For an adjusted observation the body names the model
(`model`: id, content hash, model and specification versions, the card's
`url`, target, window, status, the training counts and range, and
`artifact_ok`); the API checks the artifact under its own
`JUDGEMETRICS_SNAPSHOT_DIR`, so `complete` holds only where the API can
read the snapshot directory the compute wrote (an API without it answers
`complete: false`, `artifact_ok: false`). The model itself is served by
`GET /api/v1/models/{id}` (`docs/API.md` "Models") without its
`storage_uri`. Two fields of the CLI's output are
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
  members 1-9 of 9 (--limit 100); their cases:
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
(without `storage_uri`), `members` (by kind, with the page's `member_ids` and
`case_ids`), the page's `limit` and `offset`, `source_records` (with
`artifact_uri: null` for the fixture file), `sources`, and `complete: true`.
