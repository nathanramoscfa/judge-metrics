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
  within its case (below, "The restricted schema");
- `0009_outcome_models` — the `outcome_model` catalogue of fitted
  expected-outcome models (`SELECT` for the app role, DML for the ingest
  role; "Outcome model specification" below);
- `0010_adjusted_observations` — `metric_observation.outcome_model_id`,
  `pooling_weight`, and `suppression_reason` with its two check
  constraints (the observed-to-expected ratios);
- `0011_cook_county_connector` — `uq_judge_external_ids_cook_sao_judge`
  (a partial unique expression index: one judge per Cook County judge
  key), `charge.judge_id` (nullable, indexed, `RESTRICT`: the judge who
  entered the charge's disposition, as the source records it), and
  `REVOKE ALL ON data_quality_issue FROM judgemetrics_app` (an issue
  describes source rows; no API route reads the table);
- `0012_real_data_semantics` — `source.capabilities` (JSONB, default
  `{}`: the judge gates the source records, its person-key scope, the
  revocation scopes it documents), the `coverage_statistic` table (the
  brief's six coverage statistics and the unknown-actor share per snapshot,
  source, and scope — `source`, `jurisdiction`, or `court` — with numerator,
  denominator, the share at six decimals, and the methodology version; unique
  per snapshot, source, scope, and statistic; checks on the scope, the
  statistic, and `0 <= numerator <= denominator`; `SELECT` for the app role,
  DML for the ingest role), `metric_observation.calendar_year` (smallint,
  null for the whole coverage window; checked to name the year's first and
  last days as the period) added to `uq_metric_observation_key`, and the
  `outcome_model` status `unavailable`. A downgrade deletes the
  calendar-year observations and the `unavailable` models (with the
  suppressed observations that cite one) before restoring the earlier key
  and check.

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
| `metric_observation`           | A computed value for a subject and period with cohort size, counts, interval, suppression flag, methodology version, and (0005) `snapshot_id`, `source_id`, `window_days`, `dimension_value`, `eligible_count` (the cohort before the follow-up restriction), `value` (medians, in days), `distribution`, `code_version`, `registry_version`, `superseded_at` (set when a recompute replaced it; the current rows are `IS NULL`). Per kind (Phase 3 Step 2): a count keeps `observed_count` (`cohort_size` and `eligible_count` are the population); a share and a fixed-window rate keep `observed_count` / `cohort_size` with `observed_rate` (six decimals) and the Wilson bounds, a rate's `eligible_count` being the whole cohort before censoring; a survival estimate keeps the events by the window in `observed_count`, the whole cohort in `cohort_size`, `1 - S(w)` in `observed_rate`, and the Greenwood interval in the bounds; a distribution keeps one row per dimension value with the whole map in `distribution`; a median keeps `n` in `cohort_size` and the median in `value`. An `observed_expected` observation (0010, Phase 4 Step 3) keeps O in `observed_count`, n (the members in the ratio: followed for the window and every excluded-on-missing model feature known) in `cohort_size`, the cohort before the follow-up restriction in `eligible_count`, O / n in `observed_rate`, the model-expected count E in `expected_count` (Numeric(14, 4)), E / n in `expected_rate`, the pooled ratio (α + O) / (α + E) in `standardized_ratio`, its bootstrap percentile interval in the bounds, E / (E + α) in `pooling_weight` (Numeric(9, 6)), and the fitted model it was computed with in `outcome_model_id` (→ `outcome_model`, RESTRICT; null for every other kind); without a fitted model the expected and pooled figures are null. Every suppressed row carries `suppression_reason` — `below_threshold` for the descriptive kinds (0010 backfilled the stored rows), `below_threshold`, `expected_below_minimum`, or `model_unavailable` for an adjusted one — and no other row does (two check constraints). `period_start`/`period_end` are the source's coverage window, or (0012, Phase 5 Step 5) one calendar year of it — `calendar_year` (smallint) names that year and is null for the whole window; it is part of the unique key, and a check ties it to the year's first and last days. | via `metric_snapshot` and its members (and, adjusted, the model's artifact) |
| `metric_observation_member`    | The canonical rows behind an observation (0005): `member_kind` (`decision`, `charge`, `court_case`, `sentence`, `court_event`, `justice_event`), `member_id`, `counted` (in the numerator), `followed` (in the denominator after censoring). Entity ids of public rows only — never a person id. | the member rows' own `source_record_id` |
| `outcome_model`                | One fitted expected-outcome model (0009, Phase 4 Step 2) per snapshot, source, specification version, target, window, and seed: `content_hash` (the sha256 of its canonical JSON artifact, unique), `snapshot_id` and `source_id` (RESTRICT), `spec_version`, `model_version`, `target`, `window_days` (null for the release target), `seed`, `status` (`fitted`, `insufficient_events`, `not_converged`; 0012 adds `unavailable`: a target the source cannot support, its reason in `diagnostics`, no fit), the temporal split's `n_train`/`events_train` (before the cutoff) and `n_test`/`events_test` (at or after it; the published fit is over both), `train_start`/`train_end` (the index-time range) and `split_cutoff`, `diagnostics` and `coefficients` (JSONB, so a model card needs no artifact), `storage_uri` (the artifact under the snapshot directory; never returned by a public surface), `code_version`, `fitted_at`. No person-level column. | via `metric_snapshot` and its artifact |
| `data_quality_issue`           | A finding of a data-quality check: severity, code, description, status.             | `source_record_id`            |
| `coverage_statistic`           | One coverage statistic (0012, Phase 5 Step 5) per snapshot, source, scope, and statistic: `snapshot_id` and `source_id` (RESTRICT), `scope_type` (`source`, `jurisdiction`, `court`), `scope_id` (the source, jurisdiction, or court it covers), `statistic` (the brief's six — `cases_with_identified_judge`, `cases_with_final_disposition`, `cases_with_person_resolution`, `cases_with_adequate_follow_up`, `cases_with_complete_charge_classification`, `records_with_provenance` — and `unknown_actor_share`; defined in docs/METHODOLOGY.md "Coverage statistics"), `numerator`, `denominator`, `share` (Numeric(9, 6), null without a denominator), `methodology_version`. Aggregates only: no person id, no case list. | via `metric_snapshot` |
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
| `judge`            | `external_ids->>'cook_sao_judge'` (partial: rows that carry the key; 0011)                      | `uq_judge_external_ids_cook_sao_judge`       |
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
`synthetic_judge_code` for the synthetic source, `cook_sao_judge` for
Cook County, whose key comes from the reviewed alias table); further
systems add their own partial unique index when their connector lands. Case numbers
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
`data/reference/case_vocabulary.yaml` (`version: 3`), loaded once by
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
`judicial_discretion_classification`), in `age_band`, where it names an
absent age (the synthetic source withholds the age with the date of
birth), and in `race` and `gender` (version 3), where it names a blank
source value or the source's own "Unknown"; the `unknown_category_measured`
check counts it per field. `normalization/age_bands.py` maps an age at
filing (a bounded integer, 0-130; anything else rejects the row) onto
`age_band`.

Version 3 (Phase 5 Step 3) adds exactly the canonical values the Cook
County rule tables (`data/reference/cook_sao/`, docs/ARCHITECTURE.md "Cook
County source") use, and changes no existing value or order:

- `severity`: the Illinois classes `felony_m` (first-degree murder, the
  glossary's Class M), `felony_x`, `felony_4`, `misdemeanor_c`,
  `petty_offense`, and `unclassified` (a class the source does not state or
  documents nowhere), placed most severe first around the synthetic five,
  which keep their relative order (`felony_1` is Illinois Class 1);
- `offense_category`: `other` (the source's own catch-all) and
  `unclassified` (a case the source never categorized);
- `charge_disposition`: `superseded` and `transferred`, the two non-final
  states of a charge that left the case without an outcome on its merits
  (a charge still open in the case is `pending`); and the new kind
  `final_charge_disposition` (`dismissed`, `acquitted`, `convicted_plea`,
  `convicted_verdict`), the dispositions that end a charge on its merits:
  the disposition distribution lists these alone since this version, and
  Phase 5 Step 5 makes the disposed-charge and disposed-case populations
  read them;
- `event_type`: `preliminary_hearing`, `indictment`, `mistrial`,
  `transfer`, `appeal`, `diversion_completed`, `diversion_failed`;
  `decision_type`: `charging` (the State's felony review) and `diversion`;
- `position`: `unstated`, a judge whose source states no rank;
- `sentence_component`: `conditional_discharge`, `supervision`, `death`,
  `treatment`, `program`, `home_detention`; and the new kinds
  `sentence_phase` (`original`, `probation_violation`, `amended`,
  `resentenced`, `remanded`) and `sentence_term_flag` (`life`, `death`,
  `term_unstated`, `unit_not_a_term`, `unparseable_term`, `missing_term`,
  `implausible_term`), which `sentence_components` carries;
- the new kinds `charging_outcome` (`approved`, `rejected`, `continued`),
  `diversion_stage` (`pre_plea`, `post_plea`), and `judicial_ruling`
  (`suppression_granted`, `no_probable_cause`, `conviction_vacated`,
  `warrant_quashed`: a court's ruling recorded beside a prosecutor's
  dismissal, never counted as a judicial dismissal);
- the restricted kinds `race` and `gender`, joined to
  `restricted_attribute`: the Cook County source's own labels, letter case
  and punctuation normalized but not recoded (`ASIAN` and `Asian` are
  `asian`; `CAUCASIAN` and `White`, `HISPANIC` and `Latinx`, `Unknown
  Gender` and `Unknown` stay distinct), `unknown` for a blank. A recoding
  is a methodological choice the Phase 6 legal review owns.

The generator draws, ranks, and codes only the synthetic values
(`synthetic.vocabulary.SYNTHETIC_SEVERITIES` and the synthetic offense
table), and the truth's disposition distribution iterates
`FINAL_CHARGE_DISPOSITIONS`, so the golden fixture and the demo seed are
byte-identical under versions 2 and 3.

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
| `judge_service.position_type` (synthetic; Cook County `unstated`) | `position` |
| `source.observable_outcomes` entries    | `justice_event_type`                  |
| `restricted.party_attribute.attribute`  | `restricted_attribute`                |
| `restricted.party_attribute.value`      | the kind the attribute names (`age_band`, `synthetic_group`, `race`, `gender`) |

### Metric registry

`data/reference/metric_registry.yaml` (`version: 3`,
`methodology_version: "1.1"` since Phase 5 Step 5 gave the first real source
its semantics; `1.0` published the adjusted statistics' methodology, `0.3`
added the observed-to-expected ratios, `0.2` deferred exposure by every
incarceration term of the person) is the second versioned reference file:
the contract every published number is computed against
(`docs/METHODOLOGY.md` is rendered from it; `docs/ARCHITECTURE.md`
"Metrics engine"). `judgemetrics.metrics.registry.load_registry` loads it
once with `yaml.safe_load` and validates every entry against the case
vocabulary (`attribution.decision_type` → `decision_type`,
`attribution.actor_types` → `actor_type`, `attribution.discretion` →
`judicial_discretion_classification`, `outcome` → `justice_event_type`,
`counted.disposition` → `charge_disposition`, `counted.disposition_actor`
→ `actor_type`) and the fixed enumerations (`kind`: `count`, `share`,
`windowed_rate`, `survival`, `distribution`, `median`,
`observed_expected`; `subject_types`: `judge`, `court`; `assignment_gate`:
`deciding_judge`, `assigned_at_time`, `assigned_ever`, `sentencing_judge`,
`disposing_judge`, `court_of_case`; `index_event`: `pretrial_release`, `disposition`,
`sentence`; `dimension`: `disposition`, `offense_category`; `unit`:
`count`, `share`, `days`, `ratio`; `windows_days`: the brief's 30, 90, 180,
365, 730, 1095). `sync_definitions` mirrors every entry into
`metric_definition` on `(slug, version)`; the row carries the published
fields, while `population`, `counted`, `measure`, and `adjustment` steer
the compute functions and live in the file only. Adding or changing a
metric bumps the entry's `version` and the registry `version` (old rows
stay as the history of the observations that cite them); a change of
semantics bumps `methodology_version` and adds a changelog entry.

Registry version 2 (Phase 4 Step 3) adds the kind `observed_expected`
(unit `ratio`) with three judge metrics —
`pretrial_release_observed_expected` (population `pretrial_decisions`, no
window), `new_case_observed_expected` and
`failure_to_appear_observed_expected` (population `index_events`, index
event `pretrial_release`, the six windows) — each with the eligibility and
attribution of the descriptive metric it adjusts (`pretrial_release_share`,
`new_case_rate`, `failure_to_appear_rate`), `suppression_threshold: 30`,
and the field `adjustment` (`target`: the outcome model specification's
target it reads; `minimum_expected: 5`), which the loader requires for the
kind and rejects on every other. An adjusted entry is judge-only and has
no dimension and no `counted` conditions. The API serves the three since
Phase 4 Step 5, with their `adjustment` on the definition (docs/API.md
"Metrics").

Registry version 3 (Phase 5 Step 5, methodology `1.1`) adds the gate
`disposing_judge` (the judge the source records on a charge's disposition,
`charge.judge_id`; for a case, the judge on the charge whose disposal sets the
case disposition time) and moves the disposition family to it; counts each
sentencing decision once (the sentencing family's prose); reads the
vocabulary's finality in every disposed population; and adds three blocks the
loader validates: `periods` (the whole window, and the calendar years of the
descriptive kinds with each population's anchor, which must equal
`registry.POPULATION_ANCHORS`), `revocation_scopes` (`release` after a pretrial
release, `supervision` after a disposition or a sentence; every revocation
metric carries its scope as `revocation_scope`), and in `suppression` the
`thresholds` (every metric exactly once, at the threshold its entry carries,
with the reason), the `measurements` (the cohort sizes measured on the Cook
County corpus and the demo, as nearest-rank quantiles per cohort, source,
subject type, period, and window — never a subject — which every suppressed
metric's threshold must carry), and `eligible_count` (Phase 3 finding 3.5: a
suppressed observation keeps its eligible count). Sixteen entries changed
(`version: "2"`): the seven of the disposition family, the eight of the
sentencing family, and `revocation_rate`.

### Outcome model specification

`data/reference/outcome_model.yaml` (`version: 3`, `model_version:
expected-logit-v1`, Phase 4 Step 2; version 2, Phase 5 Step 3, lists case
vocabulary 3's new severities and offense categories as levels of
`lead_severity` and `lead_category`, each reference and every earlier
level's order unchanged, so a source without them encodes as before;
version 3, Phase 5 Step 5, adds `availability` — the three conditions a
source must meet for a target to be fitted, each with the reason the
catalogue records when it fails — and marks the four person-history
features `person_history: true`) is the third versioned reference file:
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
`recovery` tolerance alters neither and does not (Phase 4 Step 3 set the
tolerances from one run of the recovery test and recorded the measured
values beside them).

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
| `sentence.sentence_components` | `{"<sentence_component>": true, …}`; a Cook County sentence also carries `phase`, `current`, `superseded`, `components`, `terms`, and (Phase 5 Step 5) `replaced` — true when a later amended or corrected sentencing replaced it, which the metrics engine leaves out of the frame. |
| `source.terms_metadata`    | Terms and redistribution answers copied from the connector's `source_info`.                   |
| `source.observable_outcomes` | `["new_case", "failure_to_appear", …]`: the `justice_event_type` values the source can document (default `[]`). |
| `source.capabilities`      | `{"judge_gates": [...], "person_key_scope": "cross_case" \| "case" \| null, "revocation_scopes": [...]}` (0012): what the source records about judges and persons (`judgemetrics.capabilities`); `{}` records nothing. |
| `metric_definition.subject_types`, `.attribution`, `.windows_days` | `["judge", "court"]`; `{"decision_type": …, "actor_types": […], "discretion": […], "assignment_gate": …}`; `[30, 90, 180, 365, 730, 1095]` or null. |
| `metric_snapshot.row_counts`, `.coverage` | `{"<table>": <rows>}` over the eleven exported tables; `{"<source id>": {"name": …, "coverage_start": …, "coverage_end": …}}`. |
| `metric_observation.distribution` | `{"<dimension value>": <count>, …}` for a distribution observation; null otherwise. |
| `outcome_model.diagnostics` | `{"status": …, "base_rate_train", "brier", "brier_skill", "auc", "calibration_in_the_large", "calibration_slope", "bins": [{"bin", "count", "mean_predicted", "observed_rate"} × 10]}` — the temporal-split test set's diagnostics; `status` alone when the split could not be fitted; `{"status": "unavailable", "reason": …}` for a target the source cannot support (0012). |
| `outcome_model.coefficients` | `[{"column", "feature", "level", "reference", "estimate", "sd", "sign_agreement"}, …]` per design column of a fitted model (the bootstrap standard deviation and sign agreement); a court's `level` and `reference` are its id, the artifact keeps the rank label (`column`); null unless `fitted`. |

Restricted attributes never appear in any of these columns.

## Grants

| Role                  | `person_identifier` | `correction_request`                          | The `restricted` schema (0008)          | Every other table                       |
|-----------------------|---------------------|-----------------------------------------------|-----------------------------------------|-----------------------------------------|
| `judgemetrics_app`    | none (revoked); likewise on `entity_resolution_candidate`, `audit_log`, and (0011) `data_quality_issue` | `INSERT` only (0007): the corrections intake writes a row it can never read back; no `SELECT` means no `RETURNING` either, so the API's insert has none | nothing: no `USAGE` on the schema, so it cannot even name `restricted.party_attribute` (`InsufficientPrivilege`) | `SELECT` (including `metric_snapshot` and `metric_observation_member`, granted by 0005: hashes, counts, and entity ids of public rows; `outcome_model`, granted by 0009: coefficients, counts, and bins, never a person-level value; and `coverage_statistic`, granted by 0012: aggregates per source, jurisdiction, and court) |
| `judgemetrics_ingest` | `SELECT, INSERT, UPDATE, DELETE`; on `audit_log` only `SELECT, INSERT` | `SELECT, INSERT, UPDATE, DELETE` | `USAGE`; `SELECT, INSERT, UPDATE, DELETE` on its tables, and by default privilege on later ones | `SELECT, INSERT, UPDATE, DELETE` (0005 grants the two metrics tables, 0009 `outcome_model`, and 0012 `coverage_statistic` explicitly; the metrics engine and `models fit` write as this role) |
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

Revision 0011 (Phase 5 Step 4) adds `charge.judge_id` — a departure from
the brief's field list, whose charge carries no judge: the Cook County
exports record the judge of a disposition ("Judge who oversaw the case")
and no assignment intervals, so the disposition family cannot attribute
through `judge_assignment` (a synthetic charge leaves it null; Step 5's
`disposing_judge` gate reads it) — and the judge identity index for the
`cook_sao_judge` system. It also revokes the app role's read of
`data_quality_issue`: an issue's description names a dataset, a column,
and counts (and, for a judge string the alias table holds, the string),
which a real corpus makes sensitive in aggregate, and nothing in the API
reads the table.

The Cook County connector's use of the existing tables: one `jurisdiction`
(Cook County, Illinois, FIPS 17031), seven `court`s (the circuit court and
its six municipal districts), judges keyed `cook_sao_judge` with derived
`judge_service` rows, a `court_case` per SAO case (the case number is the
SAO `CASE_ID`; the status is closed when every charge has ended; the
filing date is the earliest received date), a `person` per case
participant (a case participation, not a person across cases — see
`docs/ENTITY_RESOLUTION.md`), a `case_party` keyed `defendant:<ordinal>`,
race, gender, and the age band in `restricted.party_attribute`, a `charge`
per charge version keyed `<ordinal>:<charge id>:<version id>`, `court_event`s
(`indictment`, `preliminary_hearing`, a disposition's own event, a
diversion's close), `decision`s (`charging`, `diversion`, and one
`pretrial_release` per participant from the initial bond, with its
`pretrial_release` row and no judge), a `sentence` per participant, date, and
phase (the longest finite incarceration and probation term in days;
`sentence_components` holds the phase, whether it is current, whether a later
sentence supersedes it, and every row's component, days, flags, sentence and
commitment type, and charge), and a `revocation` `justice_event` at each
probation-violation sentencing. The mapping is in `docs/ARCHITECTURE.md`
"Cook County connector".

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
| `attribute`        | text          | a `restricted_attribute` value (`age_band`, `synthetic_group`; from vocabulary 3 `race`, `gender`) |
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
