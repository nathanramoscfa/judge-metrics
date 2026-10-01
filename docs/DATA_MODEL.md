<!-- docs/DATA_MODEL.md -->
# Data model

The canonical schema is the brief's (`docs/brief/…`, `<canonical_data_model>`),
implemented as SQLAlchemy models under `src/judgemetrics/db/models/` and
created by the Alembic revisions under `alembic/versions/`:

- `0001_baseline` — the twenty-three tables, enums, indexes, and grants;
- `0002_ingest_provenance` — provenance references on the reference
  entities, natural keys for upserts, `court.state_code`, JSONB
  `metadata` on `judge_service` and `source_record`, and run bookkeeping;
- `0003_case_level_natural_keys` — `source_row_id` and the
  `(case_id, source_row_id)` natural key on every row that belongs to a
  case, the justice-event natural key, `person.source_record_id`, the
  identifier indexes of the restricted table,
  `court_case.related_case_number_normalized`, `charge.disposition_actor`,
  and the synthetic judge identity index;
- `0004_entity_resolution_review` — `stage`, `decided_at`, `decided_by`,
  `reason`, and `ingest_run_id` on `entity_resolution_candidate` with the
  pair-per-version unique index and the ordered-pair check,
  `person.merged_into_person_id`, and the append-only `audit_log` with
  its trigger (`docs/ENTITY_RESOLUTION.md`);
- `0005_metric_registry_and_snapshots` — the registry columns on
  `metric_definition`, the `metric_snapshot` table, the snapshot, source,
  window, dimension, eligible-count, value, distribution, version, and
  `superseded_at` columns on `metric_observation` with its unique key and
  the current-observation index, the `metric_observation_member` table,
  and `source.coverage_start`, `coverage_end`, `observable_outcomes`
  (`docs/METHODOLOGY.md`, `docs/ARCHITECTURE.md` "Metrics engine");
- `0006_ingest_run_metrics_snapshot` — `ingest_run.metrics_snapshot_id`,
  the snapshot pipeline step 13 published a run's impacted subjects from;
- `0007_corrections_intake` — `GRANT INSERT` on `correction_request` to
  `judgemetrics_app` (and nothing else), the one write the public API
  makes (`docs/API.md` "Corrections");
- `0008_restricted_schema` — the PostgreSQL schema `restricted` with
  `restricted.party_attribute` and grants that give the app role no
  `USAGE`, and `case_party.source_row_id` rewritten to the party's ordinal
  within its case (below, "The restricted schema").

`uv run alembic check` must report no drift between the models and the
head; `alembic/env.py` sets `include_schemas` (filtered to `public` and
`restricted`), so the check covers the restricted schema too. Every
table has a UUID `id` (`gen_random_uuid()` server default) and
server-set `created_at` / `updated_at` (timezone-aware), except
`metric_observation_member`, whose `id` is a bigint identity and which
carries no timestamps (a member row is immutable and lives with its
observation).

## Tables

| Table                          | Purpose                                                                              | Source of provenance          |
|--------------------------------|--------------------------------------------------------------------------------------|-------------------------------|
| `jurisdiction`                 | Federal, state, county, city, district, or circuit jurisdiction; optional parent.     | `source_record_id` (0002)     |
| `court`                        | A court within a jurisdiction: `canonical_name`, `court_type`, `external_ids`, `state_code`, active range. | `source_record_id` (0002) |
| `judge`                        | A judicial officer: `canonical_name`, `normalized_name`, `external_ids`, `status`, `metadata`. | `source_record_id` (0002) |
| `judge_service`                | One appointment of a judge to a court: `position_type`, `start_date`, `end_date`, `metadata`. | `source_record_id`       |
| `person`                       | Internal resolved person: `public_person_key` (the only public handle, `secrets.token_urlsafe(12)` assigned once at insert), `resolution_status` (`deterministic`, `rule`, `probabilistic`, `review`, or `merged`), `resolution_confidence`, `merged_into_person_id` (0004: set on a merged person, whose row stays as history and which every public query filters out). No name, no date of birth — ever. | `source_record_id` (0003) |
| `person_identifier`            | Peppered sha256 hashes of a person's source identifiers by `identifier_type` (`source_participant_id`, `full_name`, `date_of_birth`, `name_dob`); `encrypted_value` NULL in Phase 2. **Restricted.** | `source_record_id`  |
| `court_case`                   | The brief's `case` (reserved word): court, case number (raw and normalized), type, dates, status, `related_case_number_normalized` (0003). | `source_record_id`   |
| `case_party`                   | A party to a case, optionally resolved to a person; `source_row_id` (0003) is `<party_type>:<ordinal>` from 0008 — never a participant id. | `source_record_id` |
| `judge_assignment`             | A judge's assignment to a case with an interval and confidence; `source_row_id`.    | `source_record_id`            |
| `charge`                       | One charge against one person: statute, category, severity, filing, disposition, `disposition_actor` (0003); `source_row_id`. | `source_record_id` |
| `court_event`                  | A dated event on a case with the acting `actor_type`; `source_row_id`.              | `source_record_id`            |
| `decision`                     | A decision on a case: type, time, value, `actor_type`, discretion classification; `source_row_id`. | `source_record_id`  |
| `pretrial_release`             | The release terms of a pretrial decision (one per decision).                         | via `decision`                |
| `sentence`                     | A sentence: incarceration, probation, fine, components; `source_row_id`.              | `source_record_id`            |
| `justice_event`                | A documented later justice-system event for a person (new case, reconviction, FTA, revocation, …), derived by the connector. | `source_record_id` |
| `source`                       | A data source from `docs/DATA_SOURCES.md`: owner, type, access method, terms; `coverage_start`, `coverage_end` (inclusive dates: the window the source's records cover, written by the runner from a `SupportsCoverage` connector — the synthetic connector reports its manifest's corpus — and the instant the metrics engine right-censors follow-up at is the day after `coverage_end` at 00:00 UTC; null for a source that declares none, for which no metric is computed) and `observable_outcomes` (the `justice_event_type` values the source can document, from `SourceInfo.observable_outcomes`; a metric whose outcome is not listed is *not observable* for the source: no observation is published, never a zero; 0005). | — |
| `source_record`                | One retrieved artifact: immutable object path, sha256, retrieval and effective time, parser version, run, `metadata`. | `ingest_run_id` |
| `ingest_run`                   | One pipeline run: status, counts, `code_version`, `parser_version`, `checkpoint`, `failure_reason`, `metrics_snapshot_id` (0006: the `metric_snapshot` step 13 published the impacted subjects from; null when the run touched no subject or the recompute setting was off). | —                  |
| `entity_resolution_candidate`  | One ordered pair per model version: features (booleans, counts, the stage trace), score, decision, `stage`, `decided_at`/`decided_by` (`system:<model version>` or a reviewer label), `reason`, `ingest_run_id` (0004). **Restricted.** | `ingest_run_id` |
| `metric_definition`            | A versioned metric with numerator, denominator, and eligibility definitions, and (0005) the registry columns `kind`, `subject_types`, `attribution`, `index_event`, `outcome`, `windows_days`, `dimension`, `suppression_threshold`, `unit`, `registry_version`, `methodology_version`, mirrored from `data/reference/metric_registry.yaml` by `sync_definitions`. | — |
| `metric_snapshot`              | One hashed export of the canonical tables that observations are computed from (0005): `content_hash` (unique), `label`, `exported_at`, `code_version`, `registry_version`, `methodology_version`, `row_counts`, `coverage` (per source id: `coverage_start`, `coverage_end`), `storage_uri`. | — |
| `metric_observation`           | A computed value for a subject and period with cohort size, counts, interval, suppression flag, methodology version, and (0005) `snapshot_id`, `source_id`, `window_days`, `dimension_value`, `eligible_count` (the cohort before the follow-up restriction), `value` (medians, in days), `distribution`, `code_version`, `registry_version`, `superseded_at` (set when a recompute replaced it; the current rows are `IS NULL`). Per kind (Phase 3 Step 2): a count keeps `observed_count` (`cohort_size` and `eligible_count` are the population); a share and a fixed-window rate keep `observed_count` / `cohort_size` with `observed_rate` (six decimals) and the Wilson bounds, a rate's `eligible_count` being the whole cohort before censoring; a survival estimate keeps the events by the window in `observed_count`, the whole cohort in `cohort_size`, `1 - S(w)` in `observed_rate`, and the Greenwood interval in the bounds; a distribution keeps one row per dimension value with the whole map in `distribution`; a median keeps `n` in `cohort_size` and the median in `value`. `period_start`/`period_end` are the source's coverage window. | via `metric_snapshot` and its members |
| `metric_observation_member`    | The canonical rows behind an observation (0005): `member_kind` (`decision`, `charge`, `court_case`, `sentence`, `court_event`, `justice_event`), `member_id`, `counted` (in the numerator), `followed` (in the denominator after censoring). Entity ids of public rows only — never a person id. | the member rows' own `source_record_id` |
| `outcome_model`                | One fitted expected-outcome model (0009, Phase 4 Step 2) per snapshot, source, specification version, target, window, and seed: `content_hash` (the sha256 of its canonical JSON artifact, unique), `snapshot_id` and `source_id` (RESTRICT), `spec_version`, `model_version`, `target`, `window_days` (null for the release target), `seed`, `status` (`fitted`, `insufficient_events`, `not_converged`), the temporal split's `n_train`/`events_train` (before the cutoff) and `n_test`/`events_test` (at or after it; the published fit is over both), `train_start`/`train_end` (the index-time range) and `split_cutoff`, `diagnostics` and `coefficients` (JSONB, so a model card needs no artifact), `storage_uri` (the artifact under the snapshot directory; never returned by a public surface), `code_version`, `fitted_at`. No person-level column. | via `metric_snapshot` and its artifact |
| `data_quality_issue`           | A finding of a data-quality check: severity, code, description, status.             | `source_record_id`            |
| `correction_request`           | A public correction request (`POST /api/v1/corrections`): `target_type` (`judge`, `court`, `case`, `metric_observation`), `target_id`, `requester_contact` (Fernet ciphertext under `JUDGEMETRICS_CORRECTION_CONTACT_KEY`, never plaintext), `reason`, `supporting_material_path` (an optional http(s) URL), `status` (`received` at intake), `resolved_at`. **Restricted**: the app role inserts and never reads. | — |
| `audit_log`                    | Append-only: `occurred_at`, `actor`, `action`, entity, JSON `payload`, `request_id`; a trigger rejects UPDATE and DELETE (0004). **Restricted.** | — |
| `restricted.party_attribute`   | A case party's restricted attribute (0008): `case_party_id` (→ `case_party`, `ON DELETE CASCADE`), `attribute` (a `restricted_attribute` value), `value` (a value of that kind). In the `restricted` schema, which the app role cannot use. | `source_record_id` |

The `Source of provenance` column shows how every fact row traces to raw
bytes: `source_record` → `ingest_run` → the immutable object in the raw
lake (`raw_object_path`, `raw_sha256`). A metric observation traces
through its member rows — the decisions, charges, cases, sentences, court
events, and justice events that formed its denominator and numerator —
to their source records, and through its snapshot to the exact bytes it
was computed from (Phase 3 Step 2 writes both; Step 3's
`judgemetrics provenance trace` walks the chain).

## Natural keys and unique constraints

| Table              | Natural key / unique constraint                                                                 | Index or constraint name                     |
|--------------------|-------------------------------------------------------------------------------------------------|----------------------------------------------|
| `jurisdiction`     | `(name, type)`                                                                                  | `uq_jurisdiction_name_type`                  |
| `court`            | `(canonical_name, court_type)`                                                                  | `uq_court_canonical_name_court_type`         |
| `judge`            | `external_ids->>'fjc_nid'` (partial: rows that carry the key)                                   | `uq_judge_external_ids_fjc_nid`              |
| `judge_service`    | `(judge_id, court_id, position_type, start_date)`, `NULLS NOT DISTINCT`                         | `uq_judge_service_natural_key`               |
| `judge`            | `external_ids->>'synthetic_judge_code'` (partial: rows that carry the key)                      | `uq_judge_external_ids_synthetic_judge_code` |
| `person`           | `public_person_key`                                                                             | `uq_person_public_person_key`                |
| `person_identifier`| `(identifier_type, value_hash)` for the stable kinds (`source_participant_id`): one person per source identifier | `uq_person_identifier_stable` (partial) |
| `person_identifier`| `(person_id, identifier_type, value_hash)`: one row per hash per person                         | `uq_person_identifier_person_type_hash`      |
| `court_case`       | `(court_id, case_number_normalized)`                                                            | `court_case_number`                          |
| `case_party`, `judge_assignment`, `charge`, `court_event`, `decision`, `sentence` | `(case_id, source_row_id)` — the source's own row id within the case | `uq_<table>_case_source_row` |
| `restricted.party_attribute` | `(case_party_id, attribute)`                                                          | `uq_party_attribute_case_party_attribute`    |
| `pretrial_release` | `decision_id`                                                                                   | unique column                                |
| `justice_event`    | `(person_id, event_type, event_at, related_case_id)`, `NULLS NOT DISTINCT`                      | `uq_justice_event_natural`                   |
| `entity_resolution_candidate` | `(entity_type, left_record_id, right_record_id, model_version)`, with `left_record_id < right_record_id` | `uq_er_candidate_pair_version`, `ck_entity_resolution_candidate_ordered_pair` |
| `source`           | `name`                                                                                          | `uq_source_name`                             |
| `source_record`    | `(source_id, external_record_id, raw_sha256)`, `NULLS NOT DISTINCT`                             | `uq_source_record_source_external_sha256`    |
| `metric_definition`| `(slug, version)`                                                                               | `metric_definition_slug_version`             |
| `metric_snapshot`  | `content_hash`                                                                                  | `uq_metric_snapshot_content_hash`            |
| `metric_observation` | `(metric_definition_id, subject_type, subject_id, source_id, period_start, period_end, window_days, dimension_value, snapshot_id)`, `NULLS NOT DISTINCT` | `uq_metric_observation_key` |
| `outcome_model`    | `(snapshot_id, source_id, spec_version, target, window_days, seed)`, `NULLS NOT DISTINCT`; `content_hash` | `uq_outcome_model_key`, `uq_outcome_model_content_hash` |

The ingest runner upserts on these keys (`INSERT … ON CONFLICT`) and
deduplicates drafts by the same keys within a run. Judge resolution is
exact external-id matching per identity system (`fjc_nid` for the FJC,
`synthetic_judge_code` for the synthetic source); further systems add
their own partial unique index when their connector lands. Case numbers
are normalized by `normalization/case_numbers.py` (upper-case, every run
of whitespace or punctuation becomes one `-`, ends trimmed), so
`syn 2019 000013` and `SYN-2019-000013` are one case. Persons resolve
deterministically on the `source_participant_id` hash in Phase 2 Step 2;
they are never merged on names (`entity_resolution_candidate` and the
review queue arrive in Step 3).

## Identifier kinds (`person_identifier.identifier_type`)

| Kind                    | Value hashed (after normalization)                                | Stable? |
|-------------------------|-------------------------------------------------------------------|---------|
| `source_participant_id` | The source's participant id, stripped and upper-cased             | yes — the deterministic resolution key (`uq_person_identifier_stable`) |
| `full_name`             | `normalize_person_name(name)`                                     | no — may repeat across persons |
| `date_of_birth`         | ISO `YYYY-MM-DD`                                                  | no |
| `name_dob`              | `<normalized name>\|<iso date>`, only when both exist             | no — a rule-stage signal, never name alone |

Every `value_hash` is `sha256(pepper || "\x00" || kind || "\x00" || value)`
in hex under `JUDGEMETRICS_IDENTIFIER_PEPPER`
(`judgemetrics.security.identifiers`). The pepper is a per-deployment
secret that never enters the database or the logs; changing it orphans
every hash.

## Indexes

- Every foreign key (`court_id`, `judge_id`, `person_id`, `case_id`,
  `source_record_id`, `ingest_run_id`, `jurisdiction_id`, …) has a
  btree index named `ix_<table>_<column>`.
- Event times: `court_event.event_at`, `decision.decision_at`,
  `justice_event.event_at`.
- Search: trigram (`pg_trgm`, GIN) on `judge.normalized_name`
  (`ix_judge_normalized_name_trgm`) and `court.canonical_name`
  (`ix_court_canonical_name_trgm`); GIN on `judge.external_ids` and
  `court.external_ids` for JSONB containment.
- `court.state_code` (`ix_court_state_code`),
  `court_case.related_case_number_normalized`,
  `source_record.raw_sha256`, `source_record.external_record_id`,
  `data_quality_issue.issue_code`.
- `metric_observation (metric_definition_id, subject_type, subject_id,
  period_start)` and `entity_resolution_candidate (entity_type,
  left_record_id, right_record_id)`.
- Metrics (0005): `metric_observation (subject_type, subject_id)` where
  `superseded_at IS NULL` (`ix_metric_observation_current`, the rows the
  API serves), `metric_observation.snapshot_id`, `.source_id`;
  `metric_observation_member (observation_id)` and
  `(member_kind, member_id)` (an entity's observations, for the trace).

## Enumerations

PostgreSQL `ENUM` types, values verbatim from the brief
(`src/judgemetrics/db/models/enums.py`): `jurisdiction_type`,
`actor_type`, `resolution_decision`, `subject_type`, `ingest_run_status`
(`running`, `succeeded`, `failed`, `refused`), `issue_severity`,
`issue_status`, `correction_status`. Vocabularies the brief leaves open
stay free text until their registries exist; the FJC connector uses:

| Column               | Values (Phase 1)                                                                   |
|----------------------|------------------------------------------------------------------------------------|
| `court.court_type`   | `district`, `appeals`, `supreme`, `other`                                          |
| `judge.status`       | `active`, `senior`, `deceased`, `retired`, `resigned`, `removed`, `inactive`, `unknown` — from the latest appointment's termination or senior-status fields |
| `judge_service.position_type` | The source's appointment title verbatim (`Judge`, `Chief Judge`, `Associate Justice`, …) |

## Vocabularies

The case-level vocabulary is versioned in
`data/reference/case_vocabulary.yaml` (`version: 2`), loaded once by
`judgemetrics.normalization.vocabulary` (`yaml.safe_load`) and equal to
the constants of `judgemetrics.synthetic.vocabulary` (unit test). Every
connector maps its source values onto these kinds before a draft leaves
`normalize`; `require(kind, value)` rejects a row whose value is not
listed, so an unmapped source value never enters a canonical column.
Kinds: `case_type`, `case_status`, `party_type`, `assignment_type`,
`event_type`, `decision_type`, `judicial_discretion_classification`,
`release_type`, `charge_disposition`, `severity`, `offense_category`,
`justice_event_type`, `actor_type` (the brief's enum verbatim),
`position`, `sentence_component`, `release_condition`, and (version 2,
Phase 4 Step 1) the **restricted vocabularies** `restricted_attribute`
(`age_band`, `synthetic_group`: the attributes `restricted.party_attribute`
may hold), `age_band` (`18-24`, `25-34`, `35-44`, `45-54`, `55+`,
`unknown`), and `synthetic_group` (`group_a`, `group_b`, `group_c`, the
synthetic source's abstract negative control). A restricted vocabulary's
values appear only in the `restricted` schema, are never a model feature
(Step 2's specification reads the attribute names from
`restricted_attribute`, so no module under `metrics/` names one), and are
read only by the aggregate fairness analysis. `unknown` is a listed value
only where the brief allows an explicit unknown (`actor_type`,
`judicial_discretion_classification`) and in `age_band`, where it names an
absent age (the synthetic source withholds the age with the date of
birth); the `unknown_category_measured` check counts it per field.
`normalization/age_bands.py` maps an age at filing (a bounded integer,
0-130; anything else rejects the row) onto `age_band`.

Phase 5's real-source connectors map onto this vocabulary and never
extend it silently: adding, renaming, or removing a value bumps
`version`, updates the generator's constants, and is recorded here.

| Column                                  | Vocabulary kind                       |
|-----------------------------------------|---------------------------------------|
| `court_case.case_type`, `.status`       | `case_type`, `case_status`            |
| `case_party.party_type`                 | `party_type`                          |
| `judge_assignment.assignment_type`      | `assignment_type`                     |
| `charge.offense_category`, `.severity`, `.disposition` | `offense_category`, `severity`, `charge_disposition` |
| `court_event.event_type`                | `event_type`                          |
| `decision.decision_type`, `.judicial_discretion_classification` | `decision_type`, `judicial_discretion_classification` |
| `pretrial_release.release_type`, `.conditions` keys | `release_type`, `release_condition` |
| `sentence.sentence_components` keys     | `sentence_component`                  |
| `justice_event.event_type`              | `justice_event_type`                  |
| `judge_service.position_type` (synthetic) | `position`                          |
| `source.observable_outcomes` entries    | `justice_event_type`                  |
| `restricted.party_attribute.attribute`  | `restricted_attribute`                |
| `restricted.party_attribute.value`      | the kind the attribute names (`age_band`, `synthetic_group`) |

### Metric registry

`data/reference/metric_registry.yaml` (`version: 1`,
`methodology_version: "0.2"` since Phase 4 Step 1 deferred exposure by
every incarceration term of the person) is the second versioned
reference file:
the contract every published number is computed against
(`docs/METHODOLOGY.md` is rendered from it; `docs/ARCHITECTURE.md`
"Metrics engine"). `judgemetrics.metrics.registry.load_registry` loads it
once with `yaml.safe_load` and validates every entry against the case
vocabulary (`attribution.decision_type` → `decision_type`,
`attribution.actor_types` → `actor_type`, `attribution.discretion` →
`judicial_discretion_classification`, `outcome` → `justice_event_type`,
`counted.disposition` → `charge_disposition`, `counted.disposition_actor`
→ `actor_type`) and the fixed enumerations (`kind`: `count`, `share`,
`windowed_rate`, `survival`, `distribution`, `median`; `subject_types`:
`judge`, `court`; `assignment_gate`: `deciding_judge`, `assigned_at_time`,
`assigned_ever`, `sentencing_judge`, `court_of_case`; `index_event`:
`pretrial_release`, `disposition`, `sentence`; `dimension`:
`disposition`, `offense_category`; `unit`: `count`, `share`, `days`;
`windows_days`: the brief's 30, 90, 180, 365, 730, 1095). `sync_definitions`
mirrors every entry into `metric_definition` on `(slug, version)`; the
row carries the published fields, while `population`, `counted`, and
`measure` steer the compute functions and live in the file only. Adding
or changing a metric bumps the entry's `version` and the registry
`version` (old rows stay as the history of the observations that cite
them); a change of semantics bumps `methodology_version` and adds a
changelog entry.

### Outcome model specification

`data/reference/outcome_model.yaml` (`version: 1`, `model_version:
expected-logit-v1`, Phase 4 Step 2) is the third versioned reference file:
the contract every risk-adjusted figure is computed against
(`docs/ARCHITECTURE.md` "Risk adjustment"). `metrics.adjustment.spec.load_spec`
loads it once with `yaml.safe_load` and validates it: the targets
(`pretrial_release` over the `pretrial_decisions` gate; `new_case` and
`failure_to_appear` over the pretrial-release cohort of the registry's
windowed rates, one model per window), the eleven features (each with its
frame columns, kind, levels or bands, reference, known-at instant, missing
rule, and leakage statement, checked against the builder the code
implements and, for fixed levels, against the case vocabulary: every
`severity` and `offense_category` value listed once), the exclusions (every
`restricted_attribute` value through the vocabulary, the judge, the release
terms, anything at or after the index, the latent propensity — each with
its reason), the L2 penalty and solver limits, the temporal split, the
seed, the bootstrap, the pooling bounds, the thresholds, and the recovery
tolerances. A change that alters a fitted model or a published figure
bumps `version` (the old `outcome_model` rows keep theirs as history); a
`recovery` tolerance alters neither and does not.

The analytic frame (`metrics/frame.py`) gained `courts` (id,
jurisdiction) in the same step: the courts of the frame's cases, which the
snapshot already exported, for the model's court and jurisdiction
features.

## JSONB columns

| Column                     | Content                                                                                       |
|----------------------------|-----------------------------------------------------------------------------------------------|
| `judge.external_ids`       | `{"fjc_nid": "…", "fjc_jid": "…"}`; other sources add their keys (merged, never replaced).     |
| `judge.metadata`           | Public biographical facts: `birth_year`, `birth_year_approximate`.                            |
| `court.external_ids`       | `{"fjc_court_name": "…"}`.                                                                    |
| `judge_service.metadata`   | `fjc_sequence`, `start_date_basis` (`commission_date` / `recess_appointment_date`), `senior_status_date`, `termination`. |
| `source_record.metadata`   | `uri`, `export_page`, `final_url`, `etag`, `last_modified`, `content_type`, `content_length`. |
| `ingest_run.checkpoint`    | Incremental state of a checkpointing connector (none yet); the metrics snapshot is the `metrics_snapshot_id` column, never a key here. |
| `entity_resolution_candidate.features` | `PairFeatures.as_dict()` (booleans, `filing_gap_days`, `age_consistent`) plus `stage_trace`; never a hash, name, date, or participant id. |
| `audit_log.payload`        | Ids, counts, decision, reason, model version of the recorded action; never a restricted value. |
| `decision.decision_value`  | `{"release_type": …, "detained": …}` for a pretrial decision; `{}` otherwise (the type and actor columns say the rest). |
| `pretrial_release.conditions` | `{"<release_condition>": true, …}` — one key per condition, containment-queryable.        |
| `sentence.sentence_components` | `{"<sentence_component>": true, …}`.                                                     |
| `source.terms_metadata`    | Terms and redistribution answers copied from the connector's `source_info`.                   |
| `source.observable_outcomes` | `["new_case", "failure_to_appear", …]`: the `justice_event_type` values the source can document (default `[]`). |
| `metric_definition.subject_types`, `.attribution`, `.windows_days` | `["judge", "court"]`; `{"decision_type": …, "actor_types": […], "discretion": […], "assignment_gate": …}`; `[30, 90, 180, 365, 730, 1095]` or null. |
| `metric_snapshot.row_counts`, `.coverage` | `{"<table>": <rows>}` over the eleven exported tables; `{"<source id>": {"name": …, "coverage_start": …, "coverage_end": …}}`. |
| `metric_observation.distribution` | `{"<dimension value>": <count>, …}` for a distribution observation; null otherwise. |
| `outcome_model.diagnostics` | `{"status": …, "base_rate_train", "brier", "brier_skill", "auc", "calibration_in_the_large", "calibration_slope", "bins": [{"bin", "count", "mean_predicted", "observed_rate"} × 10]}` — the temporal-split test set's diagnostics; `status` alone when the split could not be fitted. |
| `outcome_model.coefficients` | `[{"column", "feature", "level", "reference", "estimate", "sd", "sign_agreement"}, …]` per design column of a fitted model (the bootstrap standard deviation and sign agreement); a court's `level` and `reference` are its id, the artifact keeps the rank label (`column`); null unless `fitted`. |

Restricted attributes never appear in any of these columns.

## Grants

| Role                  | `person_identifier` | `correction_request`                          | The `restricted` schema (0008)          | Every other table                       |
|-----------------------|---------------------|-----------------------------------------------|-----------------------------------------|-----------------------------------------|
| `judgemetrics_app`    | none (revoked); likewise on `entity_resolution_candidate` and `audit_log` | `INSERT` only (0007): the corrections intake writes a row it can never read back; no `SELECT` means no `RETURNING` either, so the API's insert has none | nothing: no `USAGE` on the schema, so it cannot even name `restricted.party_attribute` (`InsufficientPrivilege`) | `SELECT` (including `metric_snapshot` and `metric_observation_member`, granted by 0005: hashes, counts, and entity ids of public rows; and `outcome_model`, granted by 0009: coefficients, counts, and bins, never a person-level value) |
| `judgemetrics_ingest` | `SELECT, INSERT, UPDATE, DELETE`; on `audit_log` only `SELECT, INSERT` | `SELECT, INSERT, UPDATE, DELETE` | `USAGE`; `SELECT, INSERT, UPDATE, DELETE` on its tables, and by default privilege on later ones | `SELECT, INSERT, UPDATE, DELETE` (0005 grants the two metrics tables and 0009 `outcome_model` explicitly; the metrics engine and `models fit` write as this role) |
| `judgemetrics_admin`  | all (owner of migrations); the `audit_log` trigger still rejects its updates and deletes | all (the admin tooling that answers corrections holds the key and decrypts) | all, and by default privilege on later tables | all |

`PUBLIC` holds nothing on `restricted` (revoked by 0008).
`tests/integration/test_restricted_schema.py` proves the split in the
scratch database and in the configured one: as the app role naming the
table raises `InsufficientPrivilege` and `has_schema_privilege` answers
false; the ingest role reads and writes it. `03-test-database.sql`, which
reruns on every `uv run poe up`, revokes the app role's schema usage again
whenever the schema exists. Creating the schema needs `CREATE` on the
database, which the Compose init scripts grant the admin role.

`tests/integration/test_api_corrections.py` proves the split: as the app
role an `INSERT` succeeds and a `SELECT`, `UPDATE`, `DELETE`, or
`INSERT … RETURNING` raises `InsufficientPrivilege`;
`tests/integration/test_migrations.py` reads the catalog and finds
exactly `{INSERT}`.

`ALTER DEFAULT PRIVILEGES` in `infra/docker/postgres/02-roles.sql`
extends the split to objects created by later migrations, whether they
run as the admin role or as the Compose superuser.

## Departures from the brief's field lists

Revision 0002 adds columns the brief's entity lists do not name, each
required by Phase 1 Step 3 and recorded here so the departure is
explicit: `source_record_id` on `jurisdiction`, `court`, and `judge`
(every published row must reference a source record with a hash);
`court.state_code`; `judge_service.metadata`; `source_record.metadata`;
`ingest_run.parser_version`, `ingest_run.checkpoint`,
`ingest_run.failure_reason`. Revision 0003 adds, for Phase 2 Step 2:
`source_row_id` on the six tables whose rows belong to a case (the
natural key of an upsert); `person.source_record_id`;
`court_case.related_case_number_normalized` (the source's link to a
related case, the linkage signal of the resolution rule stage); and
`charge.disposition_actor` — the brief keeps the actor on `decision`,
but the judicial-dismissal rule ("a prosecutor's dismissal is not a
judicial dismissal") is evaluated per charge, so the charge carries the
actor who disposed of it as well. No field of the brief was removed or
renamed (the `case` table is `court_case`, as the root roadmap records).
Revision 0004 adds `entity_resolution_candidate.stage`, `.decided_at`,
`.decided_by`, `.reason`, `.ingest_run_id` (the brief's auditability
clause asks for the stage, timestamp, and reviewer),
`person.merged_into_person_id`, and the `audit_log` table the brief's
security requirement "log administrative changes" needs. Revision 0005
adds, for Phase 3 Step 1, the registry columns on `metric_definition`
(the brief names numerator, denominator, eligibility, and version; the
attribution rule, kind, subject types, index event, outcome, windows,
dimension, threshold, and unit make the definition computable and
publishable), the `metric_snapshot` table (reproducibility: every
observation names the exact bytes it was computed from), the
`metric_observation` columns that key an observation by snapshot,
source, window, and dimension and keep superseded rows as history, the
`metric_observation_member` table (the brief's provenance chain from a
published number to eligible events, as rows), and
`source.coverage_start`, `coverage_end`, `observable_outcomes` (the
window follow-up is censored at and the outcomes a source can document,
which every connector must declare from Phase 5). Revision 0008 creates
the `restricted` schema the root roadmap's data classification names for
restricted attributes, with `restricted.party_attribute` (the brief lists
no field for them: they are kept out of every public table by design),
and changes the meaning of `case_party.source_row_id`: it was the
source's participant id — a plaintext identifier in an app-readable
column, the security finding Phase 4 Step 1 owns — and is now
`<party_type>:<ordinal>`, the party's 1-based position within its case and
party type in code-point order of the normalized participant ids (the
order the migration ranked the old keys in, `COLLATE "C"`). The
participant id reaches the database only as its peppered hash in
`person_identifier`; a downgrade keeps the ordinal keys.

## The restricted schema

`restricted` is the PostgreSQL schema for the attributes the root
roadmap classifies as restricted (ROADMAP.md "Data classification"):
reachable by the ingest and admin roles only, never by the public API's
role, never in a snapshot (the snapshot refuses every table of the schema
by its schema, `metrics/snapshot.py` `refuse_restricted`), never in a log
line (`age_band`, `synthetic_group`, and `attribute_value` are on the
scrubber's denylist), and never a model feature. Its one table:

| Column             | Type          | Notes |
|--------------------|---------------|-------|
| `id`               | UUID          | `gen_random_uuid()` |
| `case_party_id`    | UUID          | → `public.case_party.id`, `ON DELETE CASCADE` |
| `attribute`        | text          | a `restricted_attribute` value (`age_band`, `synthetic_group`) |
| `value`            | text          | a value of the attribute's kind; the source's raw value (an age, a birth date) never reaches it |
| `source_record_id` | UUID          | → `source_record.id`; indexed (`ix_party_attribute_source_record_id`) |
| `created_at`, `updated_at` | timestamptz | server-set |

The ingest runner writes one row per case party per attribute after the
parties, upserting on `(case_party_id, attribute)` with the `IS DISTINCT
FROM` guard, inside the ingest transaction. The synthetic connector
publishes `age_band` (from `participants.csv`'s `age_at_filing`, blank →
`unknown`) and `synthetic_group`. `RESTRICTED_SCHEMA_TABLES`
(`db/models/__init__.py`) lists the schema's tables beside
`RESTRICTED_TABLES`; the twenty-seven `CANONICAL_TABLES` stay public.
