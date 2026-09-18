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
  and the synthetic judge identity index.

`uv run alembic check` must report no drift between the models and the
head. Every table has a UUID `id` (`gen_random_uuid()` server default)
and server-set `created_at` / `updated_at` (timezone-aware).

## Tables

| Table                          | Purpose                                                                              | Source of provenance          |
|--------------------------------|--------------------------------------------------------------------------------------|-------------------------------|
| `jurisdiction`                 | Federal, state, county, city, district, or circuit jurisdiction; optional parent.     | `source_record_id` (0002)     |
| `court`                        | A court within a jurisdiction: `canonical_name`, `court_type`, `external_ids`, `state_code`, active range. | `source_record_id` (0002) |
| `judge`                        | A judicial officer: `canonical_name`, `normalized_name`, `external_ids`, `status`, `metadata`. | `source_record_id` (0002) |
| `judge_service`                | One appointment of a judge to a court: `position_type`, `start_date`, `end_date`, `metadata`. | `source_record_id`       |
| `person`                       | Internal resolved person: `public_person_key` (the only public handle, `secrets.token_urlsafe(12)` assigned once at insert), `resolution_status`, `resolution_confidence`. No name, no date of birth — ever. | `source_record_id` (0003) |
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
| `source`                       | A data source from `docs/DATA_SOURCES.md`: owner, type, access method, terms.        | —                             |
| `source_record`                | One retrieved artifact: immutable object path, sha256, retrieval and effective time, parser version, run, `metadata`. | `ingest_run_id` |
| `ingest_run`                   | One pipeline run: status, counts, `code_version`, `parser_version`, `checkpoint`, `failure_reason`. | —                  |
| `entity_resolution_candidate`  | A candidate pair with probability, features, model version, and decision.            | —                             |
| `metric_definition`            | A versioned metric with numerator, denominator, and eligibility definitions.         | —                             |
| `metric_observation`           | A computed value for a subject and period with cohort size, counts, interval, suppression flag, methodology version. | — |
| `data_quality_issue`           | A finding of a data-quality check: severity, code, description, status.             | `source_record_id`            |
| `correction_request`           | A public correction request with an encrypted requester contact. **Restricted.**     | —                             |

The `Source of provenance` column shows how every fact row traces to raw
bytes: `source_record` → `ingest_run` → the immutable object in the raw
lake (`raw_object_path`, `raw_sha256`). Metric tables trace through the
events they count (Phase 3).

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
| `source`           | `name`                                                                                          | `uq_source_name`                             |
| `source_record`    | `(source_id, external_record_id, raw_sha256)`, `NULLS NOT DISTINCT`                             | `uq_source_record_source_external_sha256`    |
| `metric_definition`| `(slug, version)`                                                                               | `metric_definition_slug_version`             |

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

## JSONB columns

| Column                     | Content                                                                                       |
|----------------------------|-----------------------------------------------------------------------------------------------|
| `judge.external_ids`       | `{"fjc_nid": "…", "fjc_jid": "…"}`; other sources add their keys (merged, never replaced).     |
| `judge.metadata`           | Public biographical facts: `birth_year`, `birth_year_approximate`.                            |
| `court.external_ids`       | `{"fjc_court_name": "…"}`.                                                                    |
| `judge_service.metadata`   | `fjc_sequence`, `start_date_basis` (`commission_date` / `recess_appointment_date`), `senior_status_date`, `termination`. |
| `source_record.metadata`   | `uri`, `export_page`, `final_url`, `etag`, `last_modified`, `content_type`, `content_length`. |
| `ingest_run.checkpoint`    | Incremental state of a checkpointing connector (none in Phase 1).                             |
| `decision.decision_value`  | `{"release_type": …, "detained": …}` for a pretrial decision; `{}` otherwise (the type and actor columns say the rest). |
| `pretrial_release.conditions` | `{"<release_condition>": true, …}` — one key per condition, containment-queryable.        |
| `sentence.sentence_components` | `{"<sentence_component>": true, …}`.                                                     |
| `source.terms_metadata`    | Terms and redistribution answers copied from the connector's `source_info`.                   |

Restricted attributes never appear in any of these columns.

## Grants

| Role                  | `person_identifier`, `correction_request` | Every other table                       |
|-----------------------|--------------------------------------------|-----------------------------------------|
| `judgemetrics_app`    | none (revoked)                             | `SELECT`                                |
| `judgemetrics_ingest` | `SELECT, INSERT, UPDATE, DELETE`           | `SELECT, INSERT, UPDATE, DELETE`        |
| `judgemetrics_admin`  | all (owner of migrations)                  | all                                     |

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
