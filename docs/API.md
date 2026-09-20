<!-- docs/API.md -->
# JudgeMetrics API v1

The public API is versioned and paginated. It serves the canonical
tables the ingest pipeline publishes (`docs/ARCHITECTURE.md`) and the
metric observations the metrics engine computes, every entity carrying
the provenance of the raw source artifacts it was derived from; its one
write path, `POST /corrections`, accepts a data-correction request whose
contact is encrypted at rest. The generated OpenAPI document is committed at
[`openapi.json`](openapi.json) (`judgemetrics openapi export`) and is
served live at `/api/v1/openapi.json`, with Swagger UI at `/api/v1/docs`.

## Base URL and versioning

- Local development: `http://127.0.0.1:8000/api/v1` (`uv run poe dev-api`).
- Every path carries the major version. Within `v1`, changes are
  additive only: new endpoints, new optional query parameters, new
  response fields. Removing or renaming a field, changing a type,
  tightening validation, or changing the meaning of a value is a
  breaking change and ships under `/api/v2` with `v1` kept alive for a
  deprecation window announced in the changelog. A response never
  contains a field that the OpenAPI document does not declare.
- The OpenAPI document is the contract: the web client (Phase 1 Step 5)
  is generated from the committed `docs/openapi.json`, and a test fails
  the build when a route changes without the document being regenerated.

## Endpoints

| Method | Path                                   | Returns                                  |
|--------|----------------------------------------|------------------------------------------|
| GET    | `/health`                              | Liveness: version, git SHA, Alembic head |
| GET    | `/ready`                               | Readiness: database reachable and at head |
| GET    | `/judges`                              | `Page[JudgeSummary]`                     |
| GET    | `/judges/{judge_id}`                   | `JudgeDetail` (service records, provenance) |
| GET    | `/judges/{judge_id}/service`           | `list[ServiceRecord]`, oldest first      |
| GET    | `/judges/{judge_id}/cases`             | `Page[CaseSummary]`, newest filing first |
| GET    | `/courts`                              | `Page[CourtSummary]`                     |
| GET    | `/courts/{court_id}`                   | `CourtDetail` (provenance)               |
| GET    | `/jurisdictions`                       | `Page[JurisdictionSummary]`              |
| GET    | `/jurisdictions/{jurisdiction_id}`     | `JurisdictionDetail` (provenance)        |
| GET    | `/cases/{case_id}`                     | `CaseDetail` (parties, assignments, charges, decisions, sentences, provenance) |
| GET    | `/cases/{case_id}/timeline`            | `Timeline`: every dated fact of the case, chronological |
| GET    | `/search`                              | `SearchResponse`: judges and courts by name, cases by exact number (rate limited) |
| GET    | `/coverage`                            | `Coverage`: per-source counts, filing and coverage windows, observable outcomes, last run, latest snapshot, `synthetic_present`, registry and methodology versions |
| GET    | `/metrics`                             | `Registry`: every metric definition, the suppression rule, the known limitations, the versions |
| GET    | `/judges/{judge_id}/metrics`           | `SubjectMetrics`: every current observation of the judge, by metric slug |
| GET    | `/courts/{court_id}/metrics`           | `SubjectMetrics`: every current observation of the court, by metric slug |
| GET    | `/metrics/compare`                     | `ComparePage`: one metric and window for the judges of a court or jurisdiction, sorted and paginated |
| GET    | `/metrics/{observation_id}/provenance` | `ObservationProvenance`: the chain from the number to the raw artifacts (`docs/PROVENANCE.md`) |
| POST   | `/corrections`                         | `CorrectionAccepted` (202): a data-correction request, stored with an encrypted contact (rate limited) |

Identifiers are UUIDs. The API exposes public UUIDs, public judge data
(name, status, appointment facts, the FJC identifiers under
`external_ids`), case-level facts, and provenance metadata; it never
exposes internal storage keys, database identifiers of any other kind,
or restricted attributes. A person (defendant) appears only as the
pseudonymous `public_person_key` of the resolved `person` row — never a
name, date of birth, or source identifier (those exist only as peppered
hashes in the restricted `person_identifier` table, which the API role
cannot read and no route selects from) — and a person merged into
another by entity resolution is never returned (every person join
filters `merged_into_person_id IS NULL`). No metrics route returns a
person at all: observations carry subject ids and entity ids only
(`tests/golden/test_public_contract.py` walks every metrics route for a
person key, a `person_id`, or a hash other than the artifact and
snapshot digests). A unit test over the committed OpenAPI document
asserts that no schema property is named `value_hash`,
`encrypted_value`, `date_of_birth`, `full_name`, `person_identifier`,
`raw_object_path`, or `requester_contact`.

## The `synthetic` flag

Every summary, detail, search result, provenance block, timeline, and
coverage entry carries `synthetic: bool`: true when the row's
`source_record` belongs to a source whose `source_type` is `synthetic`
(the in-repo generator, `docs/SYNTHETIC_DATA.md`). The flag is computed
in the same statement as the row (a join to `source_record` and
`source`), so a list page still costs one statement. The web tier shows
a "Synthetic" badge beside every flagged entity and a site-wide demo
banner whenever `/coverage` reports `synthetic_present`; the ingest
runner refuses synthetic sources in production, so a production
deployment never sets the flag.

## Pagination

Every list is a page:

```json
{
  "items": [...],
  "total": 4075,
  "limit": 25,
  "offset": 0,
  "next_offset": 25
}
```

- `limit` — page size, default `25`, minimum `1`, **maximum `100`**.
  A larger value is a `422`, never silently clamped.
- `offset` — rows skipped, default `0`, minimum `0`.
- `total` — rows matching the filters across all pages.
- `next_offset` — the `offset` of the following page, or `null` on the
  last page. Clients page by following `next_offset` until it is `null`.
- Ordering is deterministic (name, then id), and by similarity first
  when a `q` filter is given, so pages do not overlap or skip rows.

## Filters

Filters are validated strictly. A malformed value (a non-ISO date, a
non-UUID id, a status outside the vocabulary) is a `422`, and so is any
query parameter the endpoint does not declare — `?name=…` on `/judges`
is rejected rather than ignored, so a misspelt filter never returns an
unfiltered list.

`GET /judges`

| Parameter   | Type              | Meaning                                                                 |
|-------------|-------------------|-------------------------------------------------------------------------|
| `q`         | string, 1–200     | Trigram match on the normalized name (diacritics, case, and punctuation are folded exactly as for `normalized_name`): a single word by word similarity, several words by whole-name similarity (see `/search`); results ordered by similarity |
| `court_id`  | UUID              | Judges with a service record at this court                              |
| `active_on` | ISO date          | Judges with a service record whose interval covers the date: `start_date <= active_on` and (`end_date` is null or `end_date >= active_on`) |
| `status`    | enum              | `active`, `senior`, `deceased`, `retired`, `resigned`, `removed`, `inactive`, `unknown` |

`court_id` and `active_on` together apply to the *same* service record:
"sat at that court on that date". A data-semantics note: the FJC service
interval ends with the termination of the appointment (death,
resignation, retirement), not with senior status, so a judge on senior
status is still "active on" a date within the appointment; the
`senior_status_date` is in the service record's `metadata`.

`GET /courts`

| Parameter         | Type   | Meaning                                                   |
|-------------------|--------|-----------------------------------------------------------|
| `jurisdiction_id` | UUID   | Courts of this jurisdiction                               |
| `court_type`      | string | Exact type: `district`, `appeals`, `supreme`, `other` (federal vocabulary; state registries extend it in Phase 5) |

`GET /judges/{judge_id}/cases`

| Parameter    | Type     | Meaning                                                              |
|--------------|----------|----------------------------------------------------------------------|
| `filed_from` | ISO date | Only cases filed on or after this date                               |
| `filed_to`   | ISO date | Only cases filed on or before this date; earlier than `filed_from` is a `422` |
| `status`     | string   | Exact case status: `open` or `closed` (`data/reference/case_vocabulary.yaml`) |
| `case_type`  | string   | Exact case type: `felony` or `misdemeanor` (same vocabulary)          |

A case is the judge's when any `judge_assignment` names the judge. Rows
order newest filing first (undated last), then by normalized number. An
unknown judge is a `404`; a judge with no case on file (every FJC judge
today) is an empty page with `total: 0`. `status` and `case_type` are
validated by shape (`^[a-z][a-z0-9_]*$`) rather than by enumeration so
the vocabulary file can grow without an API change; a value outside it
simply matches nothing.

`GET /search`

| Parameter | Type          | Meaning                                                |
|-----------|---------------|--------------------------------------------------------|
| `q`       | string, 1–200 | Required. Normalized like a judge name, then matched by trigram similarity against judge normalized names and court names; normalized like a case number (`normalize_case_number`) and matched exactly against `case_number_normalized` |
| `limit`   | 1–100         | Results to return, default `25`                        |

Search returns judges, courts, and cases in one list ordered by `score`
(`0`–`1`). A query of several words (after normalization) matches by
whole-name similarity — `pg_trgm` `similarity()` with the `%` operator
at `JUDGEMETRICS_SEARCH_SIMILARITY_THRESHOLD` (default `0.3`) — so
"ruth ginsberg" finds Ruth Bader Ginsburg. A single word matches by
*word similarity* — `word_similarity()` with the `<%` operator at
`JUDGEMETRICS_SEARCH_WORD_SIMILARITY_THRESHOLD` (default `0.5`) — the
query against the best-matching extent of the name, so a misspelt
surname alone finds a long full name that whole-name similarity would
score below the threshold ("Ginsberg" scored 0.26 against
"ruth bader ginsburg" before; Phase 1 finding 4.1). Both operators use
the GIN trigram indexes; the threshold of the mode in use is set per
request with `set_config`, never interpolated into SQL, and `score` is
the matching function's value. The judges list's `q` filter takes the
same path. A case matches only when the whole query,
normalized (`syn 2020 000005` → `SYN-2020-000005`), equals its
normalized number: an exact match scores `1` and therefore outranks
every similar name, and a partial number matches nothing. A case
result's `name` is the number as the source filed it.

## Error envelope

Every non-2xx response is an `ErrorBody`:

```json
{
  "code": "not_found",
  "message": "judge 00000000-0000-0000-0000-000000000000 not found",
  "request_id": "6a4c587b-75d8-4cdf-a98b-de6816122265"
}
```

| Status | `code`                 | When                                                        |
|--------|------------------------|-------------------------------------------------------------|
| 404    | `not_found`            | No entity with that id (or an unknown path); a superseded observation on `/metrics/{id}/provenance`; an unknown court or jurisdiction on `/metrics/compare` |
| 422    | `validation_error`     | A parameter or body field failed validation, or a query parameter is not one the route declares; `message` names the parameter (`metric`, `window`, `court_id`, `target_id`, …) |
| 429    | `rate_limited`         | The `/search` or `/corrections` bucket is exhausted; `Retry-After` gives the wait in seconds |
| 503    | `database_unavailable` | The database did not answer                                 |
| 503    | `corrections_unavailable` | `POST /corrections` when the contact encryption key is not configured (a fixed message) |
| 500    | `internal_error`       | Anything else                                               |

`request_id` equals the `X-Request-ID` response header (a client may
send its own, up to 128 URL-safe characters). Error responses never
contain stack traces, SQL, or configuration values; the class of a
failure is logged with the request id and nothing more.

## Cases and the timeline

`GET /cases/{case_id}` returns the `CaseDetail`: the summary fields
(court reference, number, type, status, filed and closed dates,
`synthetic`), `parties` (`party_type`, `public_person_key`),
`assignments` (judge reference, type, interval, oldest first), `charges`
(statute, description, category, severity, violent flag, filing and
disposition times, `disposition`, and `disposition_actor` — who disposed
of the charge, so a prosecutor's dismissal is never a judicial one),
`decisions` (type, time, `actor_type`,
`judicial_discretion_classification`, the deciding judge when the
decision was judicial, the subject's public key, `decision_value`, and
the `pretrial_release` detail when the decision is one), `sentences`
(time, judge, incarceration and probation days, fine, components), and
`provenance`: one block per distinct raw artifact behind the case and
every row it contains (the synthetic dataset yields seven: one per
source file).

`GET /cases/{case_id}/timeline` returns the same facts as one
chronological list. Each `TimelineEntry` has `at`, a `kind`, the
`actor_type` when the source records who acted, the judge when one is
named, a short `label`, a `detail` dictionary of the row's public
columns, and `source`, the provenance block of that row. The kinds:

| Kind               | Row                   | `at`                        | `actor_type`            |
|--------------------|-----------------------|-----------------------------|-------------------------|
| `filed`            | the case              | `filed_date` at 00:00 UTC   | —                       |
| `assignment_start` | judge assignment      | `start_at`                  | —                       |
| `assignment_end`   | judge assignment      | `end_at` (when set)         | —                       |
| `event`            | court event           | `event_at`                  | the event's actor       |
| `decision`         | decision              | `decision_at`               | the decision's actor    |
| `charge_filed`     | charge                | `filed_at`                  | —                       |
| `charge_disposed`  | charge                | `disposed_at` (when disposed) | `disposition_actor`   |
| `sentence`         | sentence              | `sentence_at`               | —                       |
| `closed`           | the case              | `closed_date` at 23:59:59.999999 UTC | —              |

Entries sort by `at`, then by the kind order of the table (so a
disposition decision precedes the charge dispositions of the same
instant), then by row id. Date-only facts are placed at the start
(`filed`) and the end (`closed`) of their day so a day's timestamped
events fall between them; `detail.date` carries the plain date. An event
recorded after the closing date (a revocation) follows the `closed`
entry, which is the record, not an error.

## Coverage

`GET /coverage` reports every registered source: `source`,
`source_type`, `synthetic`, the number of jurisdictions, courts,
judges, cases, and resolved persons (merged rows excluded) whose rows
derive from its artifacts, the earliest and latest `filed_date` of its
cases, `last_ingest` (the most recent completed run: id, completion
time, status, which may be `failed`), and — coverage v1, Phase 3 — the
window the connector declares its records cover (`coverage_start`,
`coverage_end`; follow-up is censored the day after `coverage_end`, and
a source without a window has no metric), `observable_outcomes` (the
`justice_event_type` values the source can document; a metric whose
outcome is not listed is never published for it), `latest_snapshot`
(the newest hashed export behind the source's current observations:
`content_hash`, `exported_at`; null before the first compute) and that
snapshot's `methodology_version`. The top level carries the
`registry_version` and `methodology_version` the API serves from the
registry file. `synthetic_present` is true when any synthetic source has
at least one row in those tables — a source registered by a refused run
raises no banner. `generated_at` is the server time of the response.

## Metrics

Every published number leaves the API through one shape, `Observation`,
which carries the brief's presentation rules (`<metric_presentation>`)
as fields, so no client can show a number without its context:

| Field                                   | Meaning                                                                                                   |
|-----------------------------------------|-----------------------------------------------------------------------------------------------------------|
| `id`, `slug`, `name`, `kind`, `unit`, `version` | The observation and its definition (`GET /metrics`); `kind` is `count`, `share`, `windowed_rate`, `survival`, `distribution`, or `median` |
| `subject_type`, `subject_id`, `source`, `synthetic` | Whose number, from which source register key; `synthetic` when the source is the in-repo generator |
| `numerator`                             | `observed_count`: the rows or members meeting the condition                                              |
| `denominator`                           | `cohort_size`: what the numerator is divided by (the followed members of a fixed-window rate, the whole cohort of a survival estimate, the attributed rows of a share, the values of a median, the population of a count) |
| `eligible_count`                        | Sample size: the whole cohort before any follow-up restriction                                           |
| `period_start`, `period_end`            | Date range: the source's coverage window the number is computed over                                     |
| `window_days`, `dimension_value`        | The follow-up window of a windowed metric; the group of a dimensioned one                                |
| `rate`, `value`, `distribution`         | The figure: `numerator / denominator` or `1 - S(w)` (six decimals); a median in days; a distribution's whole map |
| `lower`, `upper`, `interval_method`     | The 95% interval and how it was computed: `wilson` for shares and fixed-window rates, `greenwood` for Kaplan-Meier estimates, null otherwise |
| `suppressed`, `suppression_threshold`   | Whether the denominator fell below the metric's threshold, and the threshold                             |
| `coverage`                              | `coverage_start`, `coverage_end`, and `observable` (whether the source documents the metric's outcome)   |
| `methodology_version`, `methodology_url` | The methodology the number follows and the page anchored at the metric (`<JUDGEMETRICS_METHODOLOGY_URL>#<slug>`, default `/methodology#<slug>`) |
| `snapshot_hash`, `computed_at`          | The hashed export the number was computed from (`judgemetrics metrics verify` reproduces it) and when   |

**Suppression.** When `suppressed` is true the API withholds the number:
`numerator`, `denominator`, `rate`, `value`, `distribution`, `lower`,
and `upper` are null, whatever the stored row holds, and only
`eligible_count` and `suppression_threshold` say why. The stripping is
done by the response schema itself (`schemas/metrics.py`), so no route
can leak a withheld figure; the `methodology` page states the rule and
the rationale (`GET /metrics` → `suppression`).

`GET /metrics` is the registry: `registry_version`,
`methodology_version`, `methodology_url`, `windows_days` (the follow-up
windows every windowed metric is computed over), the eight
`known_limitations` verbatim, the `suppression` rule and rationale, the
methodology prose the web page renders — `how_to_read` and `semantics`
(lists of `{term, text}`), `attribution_notes`, `gate_descriptions`
(each `assignment_gate` in words), and the `changelog` (`{version,
text}`, oldest first) — which are the same constants
`docs/METHODOLOGY.md` is rendered from (`metrics/methodology.py`), and
one `MetricDefinitionOut` per metric in registry order (slug, name,
kind, subject types, description, numerator, denominator, eligibility,
the structured attribution rule, index event, outcome, windows,
dimension, threshold, unit, version, `methodology_url`). It needs no
database and is cacheable.

`GET /judges/{judge_id}/metrics` and `GET /courts/{court_id}/metrics`
return `SubjectMetrics`: the subject summary, the versions, `total`, and
`observations` — every *current* observation of the subject across its
sources, keyed by metric slug, each list ordered by window, dimension
value, and source. A metric the source cannot observe has no entry
(never a zero); a court-only metric never appears for a judge; an
unknown subject is a 404; a subject with no observation (every FJC
judge today) is `total: 0` with an empty map.

`GET /metrics/compare` answers one metric for one cohort:

| Parameter         | Type              | Meaning                                                                               |
|-------------------|-------------------|---------------------------------------------------------------------------------------|
| `metric`          | slug, required    | A registry metric with judge-level observations; anything else is a 422              |
| `window`          | days              | Required for, and one of, a windowed metric's windows; forbidden otherwise (422)     |
| `court_id` / `jurisdiction_id` | UUID | Exactly one: the judges with a service record at the court, or at a court of the jurisdiction (the linkage `/judges?court_id=` uses); unknown is a 404 |
| `period_start`, `period_end` | ISO dates | Only observations of exactly that source period; `period_end` earlier than `period_start` is a 422 |
| `sort`            | `rate` (default), `numerator`, `denominator`, `value`, `name` | The figure to order by; a suppressed row sorts as if its figure were null, so the order never reveals a withheld number; nulls last |
| `order`           | `desc` (default), `asc` | Direction; ties break by name and id                                             |
| `limit`, `offset` | as every list     |                                                                                       |

The response is a page of `CompareRow`s (`subject_id`, `name`, the
judge's `court` within the cohort, `synthetic`, `observation_id`,
`source`, the period, window, and dimension, the figures and interval
under the same suppression rule, `eligible_count`, and
`coverage_warning`) plus `cohort` (the metric and version compared, the
cohort's court or jurisdiction and name, the reference period, the sort)
and the methodology version and link. The reference period is the
requested one when given, otherwise the period most rows of the *whole*
cohort share; a row whose period differs carries a `coverage_warning`,
as does a row whose source cannot document the metric's outcome. The
comparison is the current definition version of the metric; a judge's
observation under an older, not yet recomputed version is not compared.
One page is one statement (`count(*) OVER ()`); an empty page costs one
more that also settles whether the cohort exists.

`GET /metrics/{observation_id}/provenance` is the chain
(`docs/PROVENANCE.md`): the observation (the public shape above plus
its registry and code versions), the snapshot (hash, label, export time,
versions, row counts — never its storage path), the members grouped by
kind with counts and the cases they belong to, the distinct source
records with their sha256 digests, retrieval times, parser versions,
runs, and public artifact URLs (an artifact read from the operator's
filesystem shows `artifact_uri: null`), the source systems, and
`complete`. A superseded or unknown observation is a 404.

## Corrections

`POST /corrections` is the API's one write path (the brief's correction
process, `ROADMAP.md` §5 "Security & privacy strategy"). The body is a
`CorrectionIn`:

| Field                 | Constraint                                                     |
|-----------------------|----------------------------------------------------------------|
| `target_type`         | `judge`, `court`, `case`, or `metric_observation`              |
| `target_id`           | The UUID of an existing row of that kind (otherwise a 422 naming `target_id`) |
| `reason`              | 20–4000 characters, no control characters                      |
| `contact`             | 3–320 characters: how to reach the requester; **encrypted before it is stored** |
| `supporting_material` | Optional `http(s)` URL, at most 2000 characters                |

Unknown body fields and any query parameter are 422. The contact is
encrypted with Fernet under `JUDGEMETRICS_CORRECTION_CONTACT_KEY`
(`security/crypto.py`) and nothing else; the row is inserted with a
client-generated id and `status = received` by a role that holds
`INSERT` on `correction_request` and nothing else (revision 0007) — no
`SELECT`, so the API can never read a contact back, and no `RETURNING`.
The response is `202 {id, status, received_at}` with
`Cache-Control: no-store`; it never echoes a submitted field, and
neither does any log line (the scrubber redacts `reason`, `contact`,
`supporting_material`, and the key). Without a usable key the route
answers 503 `corrections_unavailable` with a fixed message — and the
API refuses to start without one outside the test environment.
Requests are rate limited per client (below).

The web app's `/corrections` form never calls this route from the
browser: it posts JSON to the web server's own route handler
(`web/app/api/corrections/route.ts`, `POST /api/corrections`), which
validates the same limits, forwards exactly the five fields above (an
allow-list, never a spread of the caller's body) to `POST
/api/v1/corrections` with the caller's `X-Forwarded-For` chain when the
request carried one, and answers with `{id, status}` under the API's
`202`, or the API's error body under its status — `422`, `429` with
`Retry-After`, `503` (also for an unreachable API). The handler logs
nothing; the received page shows the request id and never the contact.
Because the API's TCP peer is then the web server, the corrections
limiter keys on the forwarded chain only under
`JUDGEMETRICS_TRUST_PROXY=true`; otherwise every browser behind one web
server shares one bucket (`docker-compose.yml`, the `web` service).

## Caching

List and detail responses (`/judges`, `/courts`, `/jurisdictions`,
`/cases` and their details, `/judges/{id}/cases`, `/coverage`, and the
metrics reads: `/metrics`, `/judges/{id}/metrics`,
`/courts/{id}/metrics`, `/metrics/compare`,
`/metrics/{id}/provenance`) carry `Cache-Control: public, max-age=60`.
Error responses, `/search`, and `POST /corrections` (`no-store`) are
not cached.

## Rate limits

`/search` is rate limited in-process by an anonymous token bucket per
client address: `JUDGEMETRICS_SEARCH_RATE_LIMIT_BURST` tokens (default
`10`) refilled at `JUDGEMETRICS_SEARCH_RATE_LIMIT_PER_MINUTE` (default
`60`) a minute. `POST /corrections` has its own bucket per client:
`JUDGEMETRICS_CORRECTIONS_RATE_LIMIT_BURST` tokens (default `5`)
refilled at `JUDGEMETRICS_CORRECTIONS_RATE_LIMIT_PER_HOUR` (default `5`)
an hour, checked before the body is parsed so an over-limit client never
reaches validation or the database. When a bucket is empty the response
is `429` with `Retry-After` and the `rate_limited` error body. The
client address is the TCP peer, or the address a trusted reverse proxy
appended to `X-Forwarded-For` when `JUDGEMETRICS_TRUST_PROXY=true`;
without that setting the header is ignored because a client controls
it. These limiters are the local layer beneath the Phase 8 edge limits
(the reverse proxy or CDN): they protect one process from one client,
are not shared across workers, and forget everything on restart. Each is
on in every environment except `test`, where
`JUDGEMETRICS_SEARCH_RATE_LIMIT_ENABLED=true` or
`JUDGEMETRICS_CORRECTIONS_RATE_LIMIT_ENABLED=true` switches it on
explicitly.

The OpenAPI document declares an optional `X-API-Key` scheme
(`ApiKey`). No keys are issued in Phase 1; every request is served as
the anonymous tier. Keyed tiers (Phase 9) will add a lookup behind the
same header without changing the routes.

## Provenance block

Detail responses carry `provenance`: one entry per distinct raw
artifact behind the entity (for a judge: the judge row and each of its
service records).

```json
{
  "source": "fjc",
  "external_record_id": "judges.csv",
  "retrieved_at": "2026-09-16T19:08:18.323504Z",
  "raw_sha256": "b6a69ef2…870b475",
  "parser_version": "2026.09.1",
  "ingest_run_id": "30e40b48-f9c7-40ca-8c0d-ace56a3e1ed3",
  "synthetic": false
}
```

`source` is the register key in `docs/DATA_SOURCES.md`; `raw_sha256`
identifies the immutable bytes in the raw lake; `parser_version` is the
connector version that derived the row; `ingest_run_id` is the run that
retrieved the artifact (`judgemetrics ingest runs`). The lake's storage
key is internal and is never returned (the provenance query does not
even select it).

## Query budget

The API is guarded against N+1 access patterns by a test that counts
statements at the cursor (`tests/integration/test_query_counts.py`):

| Request                        | Statements | What they are                                                       |
|--------------------------------|------------|---------------------------------------------------------------------|
| judge detail                   | ≤ 4        | the judge with its synthetic flag, its service records with their courts, the case window (count, earliest, latest filed), the provenance rows |
| any list                       | ≤ 2        | the page with its window count, plus the similarity `set_config` when `q` is given |
| search                         | ≤ 2        | `set_config` and the union                                          |
| a judge's cases                | ≤ 2        | the page with its window count; an empty page costs one more that also settles whether the judge exists |
| case detail, case timeline     | ≤ 8        | one statement per case-level table — the case with its court and flag, parties with persons, assignments with judges, charges, events with judges, decisions with pretrial releases, judges, and persons, sentences with judges — plus the provenance rows: a constant, whatever the case holds; the timeline is assembled from the same load |
| coverage                       | ≤ 3        | one statement over `source` with correlated counts, one for the latest runs, one for the latest snapshots |
| registry                       | 0          | `GET /metrics` reads the registry file only                          |
| subject metrics                | ≤ 2        | the subject with its synthetic flag, then its current observations joined to their definition, source, and snapshot |
| compare                        | ≤ 2        | the page with its window count, the cohort's reference period, and the sort columns; an empty page costs one more that also settles whether the cohort exists |
| observation provenance         | ≤ 6        | three today: the observation with its definition, snapshot, and source; the members resolved to their rows; the distinct source records with their sources |
| correction                     | ≤ 2        | the target lookup and the `INSERT` — with no `RETURNING`             |

The person joins select only `public_person_key`; no statement of any
route touches `person_identifier`, `entity_resolution_candidate`, or
`audit_log`, and the provenance query never selects `raw_object_path`.

## Examples

```sh
curl -s 'http://127.0.0.1:8000/api/v1/judges?q=sotomayor&limit=5'
curl -s 'http://127.0.0.1:8000/api/v1/judges?court_id=<uuid>&active_on=2010-01-01'
curl -s 'http://127.0.0.1:8000/api/v1/judges/<uuid>'
curl -s 'http://127.0.0.1:8000/api/v1/courts?court_type=district&limit=100'
curl -s 'http://127.0.0.1:8000/api/v1/search?q=ninth%20circuit'
curl -si 'http://127.0.0.1:8000/api/v1/judges?limit=101'        # 422
curl -s 'http://127.0.0.1:8000/api/v1/judges/<uuid>/cases?status=closed&filed_from=2020-01-01'
curl -s 'http://127.0.0.1:8000/api/v1/cases/<uuid>'
curl -s 'http://127.0.0.1:8000/api/v1/cases/<uuid>/timeline'
curl -s 'http://127.0.0.1:8000/api/v1/search?q=SYN-2020-000005'  # an exact case number
curl -s 'http://127.0.0.1:8000/api/v1/search?q=Ginsberg'         # a surname alone: word similarity
curl -s 'http://127.0.0.1:8000/api/v1/coverage'
curl -s 'http://127.0.0.1:8000/api/v1/metrics'
curl -s 'http://127.0.0.1:8000/api/v1/judges/<uuid>/metrics'
curl -s 'http://127.0.0.1:8000/api/v1/metrics/compare?metric=new_case_rate&window=365&court_id=<uuid>&sort=rate&order=desc'
curl -s 'http://127.0.0.1:8000/api/v1/metrics/<observation uuid>/provenance'
curl -si -X POST 'http://127.0.0.1:8000/api/v1/corrections' -H 'Content-Type: application/json' \
  -d '{"target_type":"judge","target_id":"<uuid>","reason":"The commission date is a year off.","contact":"requester@example.invalid"}'   # 202
```
