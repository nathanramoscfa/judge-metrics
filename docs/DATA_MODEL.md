<!-- docs/DATA_MODEL.md -->
# Data model

The canonical schema is the brief's (`docs/brief/…`, `<canonical_data_model>`),
implemented as SQLAlchemy models under `src/judgemetrics/db/models/` and
created by the Alembic revisions under `alembic/versions/`:

- `0001_baseline` — the twenty-three tables, enums, indexes, and grants;
- `0002_ingest_provenance` — provenance references on the reference
  entities, natural keys for upserts, `court.state_code`, JSONB
  `metadata` on `judge_service` and `source_record`, and run bookkeeping.

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
| `person`                       | Internal resolved person; public surfaces use `public_person_key` only.              | via `person_identifier`       |
| `person_identifier`            | Hashed (optionally encrypted) source identifiers of a person. **Restricted.**         | `source_record_id`            |
| `court_case`                   | The brief's `case` (reserved word): court, case number (raw and normalized), type, dates, status. | `source_record_id`   |
| `case_party`                   | A party to a case, optionally resolved to a person.                                  | `source_record_id`            |
| `judge_assignment`             | A judge's assignment to a case with an interval and confidence.                      | `source_record_id`            |
| `charge`                       | One charge against one person: statute, category, severity, filing and disposition. | `source_record_id`            |
| `court_event`                  | A dated event on a case with the acting `actor_type`.                                | `source_record_id`            |
| `decision`                     | A decision on a case: type, time, value, `actor_type`, discretion classification.    | `source_record_id`            |
| `pretrial_release`             | The release terms of a pretrial decision (one per decision).                         | via `decision`                |
| `sentence`                     | A sentence: incarceration, probation, fine, components.                               | `source_record_id`            |
| `justice_event`                | A documented later justice-system event for a person (new case, FTA, revocation, …). | `source_record_id`            |
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
| `person`           | `public_person_key`                                                                             | `uq_person_public_person_key`                |
| `court_case`       | `(court_id, case_number_normalized)`                                                            | `court_case_number`                          |
| `pretrial_release` | `decision_id`                                                                                   | unique column                                |
| `source`           | `name`                                                                                          | `uq_source_name`                             |
| `source_record`    | `(source_id, external_record_id, raw_sha256)`, `NULLS NOT DISTINCT`                             | `uq_source_record_source_external_sha256`    |
| `metric_definition`| `(slug, version)`                                                                               | `metric_definition_slug_version`             |

The ingest runner upserts on these keys (`INSERT … ON CONFLICT`) and
deduplicates drafts by the same keys within a run. Judge resolution in
Phase 1 is exact external-id matching on `fjc_nid`; further identifier
systems add their own partial unique index when their connector lands.
Persons are never merged on names (`entity_resolution_candidate` and the
review queue arrive in Phase 2).

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

## JSONB columns

| Column                     | Content                                                                                       |
|----------------------------|-----------------------------------------------------------------------------------------------|
| `judge.external_ids`       | `{"fjc_nid": "…", "fjc_jid": "…"}`; other sources add their keys (merged, never replaced).     |
| `judge.metadata`           | Public biographical facts: `birth_year`, `birth_year_approximate`.                            |
| `court.external_ids`       | `{"fjc_court_name": "…"}`.                                                                    |
| `judge_service.metadata`   | `fjc_sequence`, `start_date_basis` (`commission_date` / `recess_appointment_date`), `senior_status_date`, `termination`. |
| `source_record.metadata`   | `uri`, `export_page`, `final_url`, `etag`, `last_modified`, `content_type`, `content_length`. |
| `ingest_run.checkpoint`    | Incremental state of a checkpointing connector (none in Phase 1).                             |
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
`ingest_run.failure_reason`. No field of the brief was removed or
renamed (the `case` table is `court_case`, as the root roadmap records).
