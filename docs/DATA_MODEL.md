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
  (`docs/METHODOLOGY.md`, `docs/ARCHITECTURE.md` "Metrics engine").

`uv run alembic check` must report no drift between the models and the
head. Every table has a UUID `id` (`gen_random_uuid()` server default)
and server-set `created_at` / `updated_at` (timezone-aware), except
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
| `case_party`                   | A party to a case, optionally resolved to a person; `source_row_id` (0003).         | `source_record_id`            |
| `judge_assignment`             | A judge's assignment to a case with an interval and confidence; `source_row_id`.    | `source_record_id`            |
| `charge`                       | One charge against one person: statute, category, severity, filing, disposition, `disposition_actor` (0003); `source_row_id`. | `source_record_id` |
| `court_event`                  | A dated event on a case with the acting `actor_type`; `source_row_id`.              | `source_record_id`            |
| `decision`                     | A decision on a case: type, time, value, `actor_type`, discretion classification; `source_row_id`. | `source_record_id`  |
| `pretrial_release`             | The release terms of a pretrial decision (one per decision).                         | via `decision`                |
| `sentence`                     | A sentence: incarceration, probation, fine, components; `source_row_id`.              | `source_record_id`            |
| `justice_event`                | A documented later justice-system event for a person (new case, reconviction, FTA, revocation, …), derived by the connector. | `source_record_id` |
| `source`                       | A data source from `docs/DATA_SOURCES.md`: owner, type, access method, terms; `coverage_start`, `coverage_end` (the window the metrics engine right-censors at) and `observable_outcomes` (the `justice_event_type` values the source can document; 0005). | — |
| `source_record`                | One retrieved artifact: immutable object path, sha256, retrieval and effective time, parser version, run, `metadata`. | `ingest_run_id` |
| `ingest_run`                   | One pipeline run: status, counts, `code_version`, `parser_version`, `checkpoint`, `failure_reason`. | —                  |
| `entity_resolution_candidate`  | One ordered pair per model version: features (booleans, counts, the stage trace), score, decision, `stage`, `decided_at`/`decided_by` (`system:<model version>` or a reviewer label), `reason`, `ingest_run_id` (0004). **Restricted.** | `ingest_run_id` |
| `metric_definition`            | A versioned metric with numerator, denominator, and eligibility definitions, and (0005) the registry columns `kind`, `subject_types`, `attribution`, `index_event`, `outcome`, `windows_days`, `dimension`, `suppression_threshold`, `unit`, `registry_version`, `methodology_version`, mirrored from `data/reference/metric_registry.yaml` by `sync_definitions`. | — |
| `metric_snapshot`              | One hashed export of the canonical tables that observations are computed from (0005): `content_hash` (unique), `label`, `exported_at`, `code_version`, `registry_version`, `methodology_version`, `row_counts`, `coverage` (per source id: `coverage_start`, `coverage_end`), `storage_uri`. | — |
| `metric_observation`           | A computed value for a subject and period with cohort size, counts, interval, suppression flag, methodology version, and (0005) `snapshot_id`, `source_id`, `window_days`, `dimension_value`, `eligible_count` (the cohort before the follow-up restriction), `value` (medians in days, survival estimates), `distribution`, `code_version`, `registry_version`, `superseded_at` (set when a recompute replaced it; the current rows are `IS NULL`). | via `metric_snapshot` and its members |
| `metric_observation_member`    | The canonical rows behind an observation (0005): `member_kind` (`decision`, `charge`, `court_case`, `sentence`, `court_event`, `justice_event`), `member_id`, `counted` (in the numerator), `followed` (in the denominator after censoring). Entity ids of public rows only — never a person id. | the member rows' own `source_record_id` |
| `data_quality_issue`           | A finding of a data-quality check: severity, code, description, status.             | `source_record_id`            |
| `correction_request`           | A public correction request with an encrypted requester contact. **Restricted.**     | —                             |
| `audit_log`                    | Append-only: `occurred_at`, `actor`, `action`, entity, JSON `payload`, `request_id`; a trigger rejects UPDATE and DELETE (0004). **Restricted.** | — |

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
| `pretrial_release` | `decision_id`                                                                                   | unique column                                |
| `justice_event`    | `(person_id, event_type, event_at, related_case_id)`, `NULLS NOT DISTINCT`                      | `uq_justice_event_natural`                   |
| `entity_resolution_candidate` | `(entity_type, left_record_id, right_record_id, model_version)`, with `left_record_id < right_record_id` | `uq_er_candidate_pair_version`, `ck_entity_resolution_candidate_ordered_pair` |
| `source`           | `name`                                                                                          | `uq_source_name`                             |
| `source_record`    | `(source_id, external_record_id, raw_sha256)`, `NULLS NOT DISTINCT`                             | `uq_source_record_source_external_sha256`    |
| `metric_definition`| `(slug, version)`                                                                               | `metric_definition_slug_version`             |
| `metric_snapshot`  | `content_hash`                                                                                  | `uq_metric_snapshot_content_hash`            |
| `metric_observation` | `(metric_definition_id, subject_type, subject_id, source_id, period_start, period_end, window_days, dimension_value, snapshot_id)`, `NULLS NOT DISTINCT` | `uq_metric_observation_key` |

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
`data/reference/case_vocabulary.yaml` (`version: 1`), loaded once by
`judgemetrics.normalization.vocabulary` (`yaml.safe_load`) and equal to
the constants of `judgemetrics.synthetic.vocabulary` (unit test). Every
connector maps its source values onto these kinds before a draft leaves
`normalize`; `require(kind, value)` rejects a row whose value is not
listed, so an unmapped source value never enters a canonical column.
Kinds: `case_type`, `case_status`, `party_type`, `assignment_type`,
`event_type`, `decision_type`, `judicial_discretion_classification`,
`release_type`, `charge_disposition`, `severity`, `offense_category`,
`justice_event_type`, `actor_type` (the brief's enum verbatim),
`position`, `sentence_component`, `release_condition`. `unknown` is a
listed value only where the brief allows an explicit unknown
(`actor_type`, `judicial_discretion_classification`); the
`unknown_category_measured` check counts it per field.

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

### Metric registry

`data/reference/metric_registry.yaml` (`version: 1`,
`methodology_version: "0.1"`) is the second versioned reference file:
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

## JSONB columns

| Column                     | Content                                                                                       |
|----------------------------|-----------------------------------------------------------------------------------------------|
| `judge.external_ids`       | `{"fjc_nid": "…", "fjc_jid": "…"}`; other sources add their keys (merged, never replaced).     |
| `judge.metadata`           | Public biographical facts: `birth_year`, `birth_year_approximate`.                            |
| `court.external_ids`       | `{"fjc_court_name": "…"}`.                                                                    |
| `judge_service.metadata`   | `fjc_sequence`, `start_date_basis` (`commission_date` / `recess_appointment_date`), `senior_status_date`, `termination`. |
| `source_record.metadata`   | `uri`, `export_page`, `final_url`, `etag`, `last_modified`, `content_type`, `content_length`. |
| `ingest_run.checkpoint`    | Incremental state of a checkpointing connector (none in Phase 1).                             |
| `entity_resolution_candidate.features` | `PairFeatures.as_dict()` (booleans, `filing_gap_days`, `age_consistent`) plus `stage_trace`; never a hash, name, date, or participant id. |
| `audit_log.payload`        | Ids, counts, decision, reason, model version of the recorded action; never a restricted value. |
| `decision.decision_value`  | `{"release_type": …, "detained": …}` for a pretrial decision; `{}` otherwise (the type and actor columns say the rest). |
| `pretrial_release.conditions` | `{"<release_condition>": true, …}` — one key per condition, containment-queryable.        |
| `sentence.sentence_components` | `{"<sentence_component>": true, …}`.                                                     |
| `source.terms_metadata`    | Terms and redistribution answers copied from the connector's `source_info`.                   |
| `source.observable_outcomes` | `["new_case", "failure_to_appear", …]`: the `justice_event_type` values the source can document (default `[]`). |
| `metric_definition.subject_types`, `.attribution`, `.windows_days` | `["judge", "court"]`; `{"decision_type": …, "actor_types": […], "discretion": […], "assignment_gate": …}`; `[30, 90, 180, 365, 730, 1095]` or null. |
| `metric_snapshot.row_counts`, `.coverage` | `{"<table>": <rows>}`; `{"<source id>": {"coverage_start": …, "coverage_end": …}}`. |
| `metric_observation.distribution` | `{"<dimension value>": <count>, …}` for a distribution observation; null otherwise. |

Restricted attributes never appear in any of these columns.

## Grants

| Role                  | `person_identifier`, `correction_request` | Every other table                       |
|-----------------------|--------------------------------------------|-----------------------------------------|
| `judgemetrics_app`    | none (revoked); likewise on `entity_resolution_candidate` and `audit_log` | `SELECT` (including `metric_snapshot` and `metric_observation_member`, granted by 0005: hashes, counts, and entity ids of public rows) |
| `judgemetrics_ingest` | `SELECT, INSERT, UPDATE, DELETE`; on `audit_log` only `SELECT, INSERT` | `SELECT, INSERT, UPDATE, DELETE` (0005 grants the two metrics tables explicitly; the metrics engine writes as this role) |
| `judgemetrics_admin`  | all (owner of migrations); the `audit_log` trigger still rejects its updates and deletes | all      |

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
which every connector must declare from Phase 5).
