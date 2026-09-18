<!-- docs/ENTITY_RESOLUTION.md -->
# Entity resolution

How JudgeMetrics decides that two records belong to the same person,
while aggressively limiting false-positive merges (the brief's
`<entity_resolution>`; ROADMAP.md §4 Phase 2.3 and §5 "Risks &
mitigations"). The package is `src/judgemetrics/entity_resolution/`;
this version resolves persons only. Judges resolve on exact external
identifiers (Phase 1, `docs/DATA_MODEL.md`), cases on
`(court, case_number_normalized)`; probabilistic linkage of judges and
courts across sources arrives in Phase 7.

## Objective and posture

Two rows that are the same real person must end up under one
`public_person_key`; two rows that are different people must never be
merged. Between the two lies a manual-review queue. The posture is
asymmetric on purpose: a missed merge costs a longitudinal metric one
observation; a wrong merge attributes one person's outcomes to another
and is only reversible by hand (Phase 6 adds unmerge). Hence the rules:

- **Never on a name alone.** A shared name with a missing or differing
  date of birth is rejected, however many cases coincide.
- **Deliberately high auto-match, deliberately low auto-reject.** The
  probabilistic stage merges only at or above `auto_match = 0.95` and
  rejects only below `auto_reject = 0.20`; everything between is
  reviewed.
- **Everything is auditable.** Every candidate pair stores its feature
  vector, score, model version, stage, decision, timestamp, and actor;
  every merge and every reviewer decision writes an append-only audit
  row.

## Signals

Used in this version (`features.py`), all computed by *equality of
hashes* or from the case linkage the ingest published, so a feature is
a boolean, a count, or null — never a name, a date of birth, a hash, or
a participant id:

| Feature              | Meaning                                                                    |
|----------------------|----------------------------------------------------------------------------|
| `same_source_id`     | Both carry the same `source_participant_id` hash (a stable identifier).    |
| `same_name`          | The same `full_name` hash (normalized name).                               |
| `same_dob`           | Both carry a `date_of_birth` hash and they are equal.                      |
| `dob_missing_either` | Either side has no date of birth.                                          |
| `same_name_dob`      | The same `name_dob` hash (normalized name and date of birth together).     |
| `shared_case`        | Both are parties to one case.                                              |
| `related_case_link`  | A case of one cites the other's case number (`related_case_number_normalized`). |
| `same_court`         | They have cases in a common court.                                         |
| `filing_gap_days`    | The smallest gap in days between their filings (null without dated cases). |
| `age_consistent`     | `same_dob` when both dates of birth are known; null otherwise.             |

Deferred (the brief lists them; no source carries them yet): attorney
relationships, geographic consistency beyond the court, and age
consistency when a date of birth is missing — the synthetic source's
`age_at_filing` is not ingested, so `age_consistent` is null in exactly
the cases where it would help. They join the vector, under a new model
version, when a source provides them lawfully.

## Blocking

Candidate pairs are generated only among persons that share a
`full_name` hash or a `source_participant_id` hash (`features.blocks_for`),
so the pair space is bounded by the number of shared names rather than
the square of the person count, and the hash is used as a grouping key
only — it never enters a feature or a row. Merged persons
(`merged_into_person_id` set) are excluded from blocking; their
identifier rows moved to the survivor when they merged.

## Stages

`pipeline.evaluate` applies the stages in order and stops at the first
decisive (matched or rejected) result; a review result waits for a
later stage to be decisive, and if none is, it stands.

### 1. Deterministic (`deterministic.py`)

| Condition                     | Decision | Score | Reason           |
|-------------------------------|----------|-------|------------------|
| `same_source_id`              | matched  | 1.00  | `same_source_id` |

The same rule finds a person for an incoming source row: the partial
unique index `uq_person_identifier_stable` guarantees one person per
stable identifier, so a draft finds exactly that person or is new. Two
stored persons therefore never share a stable identifier and this stage
fires on drafts, not on stored pairs; cross-source identifiers (Phase 7)
will need a source qualifier before it may fire across sources.

### 2. Rules (`rules.py`)

| Condition                                                              | Decision | Score | Reason                |
|------------------------------------------------------------------------|----------|-------|-----------------------|
| `same_name_dob` and (`shared_case` or `related_case_link`)             | matched  | 0.98  | `name_dob_case_link`  |
| `same_name_dob` and `same_court` and `age_consistent`, no contradiction | review  | 0.70  | `name_dob_same_court` |
| `same_name` and `dob_missing_either`                                   | rejected | 0.10  | `name_only`           |
| `same_name` and both dates of birth known and different                | rejected | 0.02  | `dob_differs`         |

The review score sits below `auto_match` deliberately: a same-court
coincidence of name and date of birth is queued, never merged by a
rule. The two rejections are what "never merge people on name alone"
means in code. Anything else (for example the same name and date of
birth in different courts with no linkage — the planted ambiguous pair)
yields no rule decision.

### 3. Probabilistic (`scoring.py`)

`Scorer` is a protocol: `score(features) -> float | None`. `StubScorer`
declines every pair, and the candidate's `stage_trace` records the stage
as `skipped`. When a scorer answers, the thresholds decide: `>=
auto_match` matched, `< auto_reject` rejected, otherwise review, stage
`probabilistic`. Phase 7 supplies the first model.

### 4. Review (the queue)

A pair no stage decided is stored as `review` with stage `review`,
score 0.50, reason `no_decisive_stage`; a rule- or scorer-review keeps
its own stage and score. Review items wait for a person.

Scores are the rule set's ordinal labels, not calibrated probabilities;
Phase 6 measures the false-positive and false-negative rates on real
data and Phase 7's model produces the first calibrated scores.

## Thresholds and versions

`data/reference/entity_resolution_thresholds.yaml` (`version: 1`) holds
`auto_match` and `auto_reject` per entity type (`person`, and `judge`,
`court`, `case` with the same defaults for Phase 7); `config.py` loads it
with `yaml.safe_load` and a unit test asserts it equals `THRESHOLDS`.
Thresholds are versioned data under the root roadmap's triage rule for
data-semantics findings: a change bumps `version`, updates the
constants, and is recorded here.

`MODEL_VERSION = "person-rules-v0"` names the rule set above. Any change
to a rule, a score, a feature, or a threshold that alters a decision
bumps it. Candidates are stored per model version: a new version writes
new rows and leaves the old ones as history, so every past decision can
be explained by the rules in force when it was made.

## The candidate row

`entity_resolution_candidate` (revision 0004; `candidates.py`), one row
per ordered pair (`left_record_id < right_record_id`, a check
constraint) per `model_version` (`uq_er_candidate_pair_version`):

| Column               | Content                                                                   |
|----------------------|---------------------------------------------------------------------------|
| `features`           | `PairFeatures.as_dict()` plus `stage_trace` (`{"deterministic": "no_signal", "rule": "matched:name_dob_case_link"}` — what each stage that ran said). |
| `match_probability`  | The score.                                                                |
| `decision`           | `matched`, `rejected`, or `review`.                                       |
| `stage`              | `deterministic`, `rule`, `probabilistic`, or `review`.                    |
| `decided_at`, `decided_by` | The run time and `system:person-rules-v0` for a system decision; NULL while a review item waits; the reviewer's label and the decision time afterwards. |
| `reason`             | The rule's reason, or the reviewer's text.                                |
| `ingest_run_id`      | The run that produced the candidate; NULL for `er run`.                   |

Reruns upsert: a system decision is rewritten when it changed; a human
decision (`decided_by` not starting with `system:`) is never overwritten,
and its pair is never re-merged or re-rejected by the system.

## Where it runs

The ingest runner (`docs/ARCHITECTURE.md`, step 10) calls
`pipeline.resolve_persons` to find or create each draft's person by its
stable identifier, and — right after step 12 has published the run's
cases and parties, because case linkage is a rule-stage feature —
`pipeline.resolve_candidates`, which blocks the run's persons against
every person they share a name or identifier hash with, evaluates the
pairs, stores the candidates, and applies the system merges; the run's
published person ids follow the merges. `pipeline.rerun` (`er run`)
recomputes candidates for every person, or one source's, without
re-ingesting, through the same feature code. Both are idempotent: a
second ingest of unchanged files parses nothing; a forced re-parse and
a rerun block the same pairs and upsert identical rows.

## Merges (`merge.py`)

`merge_persons(session, keep, drop, actor=…, reason=…)` moves
`case_party`, `charge`, `court_event`, `decision`, `sentence`,
`justice_event`, and `person_identifier` rows from `drop` to `keep` with
bound-parameter updates, respecting the natural-key unique indexes — a
justice event or identifier row `keep` already holds is deleted as a
duplicate and counted — then sets `drop.merged_into_person_id = keep`
and `drop.resolution_status = merged`, sets `keep.resolution_status`
and `resolution_confidence` to the deciding stage's values, and writes
one audit row. The earlier-created person survives. A merged person is
never returned by a public query (`merge.unmerged()` is the predicate
Step 4's repositories apply); its public key stops resolving. Merges
are applied for `matched` decisions only; a `rejected` decision writes
the candidate and an audit row.

**Irreversibility.** There is no unmerge in this phase. The audit row
carries what an unmerge needs (which person, which rows moved, which
duplicates were dropped) and Phase 6 ships the operation behind
administrative authentication.

## The review workflow

```sh
uv run judgemetrics er run [--source synthetic]          # recompute candidates; prints counts
uv run judgemetrics er review list [--entity-type person] [--limit 50] [--json]
uv run judgemetrics er review decide <candidate_id> --decision matched|rejected \
    --reviewer <label> --reason "<why>"
```

All three run as the ingest role. `list` shows candidate ids, the two
public person keys, stage, score, the feature booleans, and the created
time — never a restricted value. `decide` validates the id as a UUID and
the decision against the enum before touching the database, refuses a
candidate that is not in review or is already decided or whose persons
were merged elsewhere, applies the merge or records the rejection, sets
`decided_at`/`decided_by`/`reason`, writes an `er.decide` audit row, and
is refused in the production environment until Phase 6 ships
administrative authentication. The reviewer is an operator-chosen label
passed on the command line, never an e-mail address read from git.

## The audit log

`audit_log` (revision 0004): `occurred_at`, `actor`, `action`
(`er.merge` for system merges, `er.decide` for reviewer decisions),
`entity_type`, `entity_id`, `payload` (ids, counts, decision, reason,
model version — never a restricted value), `request_id`. The trigger
`audit_log_append_only()` raises on `UPDATE` and `DELETE` for every
role, including the migration owner; the ingest role may insert and
read; the public API role has no privilege on it, nor on
`entity_resolution_candidate`.

## What later phases add

- **Phase 4** reads resolved persons for cohorts; a merged person's
  outcomes count once.
- **Phase 6** measures linkage false-positive and false-negative rates
  on real data by manual audit, revises thresholds under a new version
  where warranted, ships the authenticated review UI, and adds unmerge.
- **Phase 7** fills the `Scorer` with a trained model (`splink`-based
  linkage for judges and courts across sources; persons stay
  within-source unless lawful stable identifiers exist) and adds the
  cross-source identifier qualifier the deterministic stage needs.
