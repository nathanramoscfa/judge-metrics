<!-- docs/API.md -->
# JudgeMetrics API v1

The public API is read-only, versioned, and paginated. It serves the
canonical tables the ingest pipeline publishes (`docs/ARCHITECTURE.md`),
and every entity carries the provenance of the raw source artifacts it
was derived from. The generated OpenAPI document is committed at
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
| GET    | `/courts`                              | `Page[CourtSummary]`                     |
| GET    | `/courts/{court_id}`                   | `CourtDetail` (provenance)               |
| GET    | `/jurisdictions`                       | `Page[JurisdictionSummary]`              |
| GET    | `/jurisdictions/{jurisdiction_id}`     | `JurisdictionDetail` (provenance)        |
| GET    | `/search`                              | `SearchResponse`: judges and courts by name (rate limited) |

Identifiers are UUIDs. The API exposes public UUIDs, public judge data
(name, status, appointment facts, the FJC identifiers under
`external_ids`), and provenance metadata; it never exposes internal
storage keys, database identifiers of any other kind, or restricted
attributes. Persons (defendants) do not appear in `v1`.

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
| `q`         | string, 1–200     | Trigram match on the normalized name (diacritics, case, and punctuation are folded exactly as for `normalized_name`); results ordered by similarity |
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

`GET /search`

| Parameter | Type          | Meaning                                                |
|-----------|---------------|--------------------------------------------------------|
| `q`       | string, 1–200 | Required. Normalized like a judge name, then matched by trigram similarity against judge normalized names and court names |
| `limit`   | 1–100         | Results to return, default `25`                        |

Search returns judges and courts in one list ordered by `score`
(`pg_trgm` `similarity()`, `0`–`1`), using the `%` operator so the GIN
trigram indexes apply. Only names at or above the similarity threshold
(`JUDGEMETRICS_SEARCH_SIMILARITY_THRESHOLD`, default `0.3`) match; the
threshold is set per request with `set_config`, never interpolated into
SQL. Similarity is computed over the whole name, so a misspelt surname
finds a judge when the surname is a large share of the full name
("Sotomayer" → Sonia Sotomayor); a short token against a long name may
fall below the threshold.

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
| 404    | `not_found`            | No entity with that id (or an unknown path)                 |
| 422    | `validation_error`     | A parameter failed validation, or a query parameter is not one the route declares; `message` names the parameter |
| 429    | `rate_limited`         | `/search` burst exhausted; `Retry-After` gives the wait in seconds |
| 503    | `database_unavailable` | The database did not answer                                 |
| 500    | `internal_error`       | Anything else                                               |

`request_id` equals the `X-Request-ID` response header (a client may
send its own, up to 128 URL-safe characters). Error responses never
contain stack traces, SQL, or configuration values; the class of a
failure is logged with the request id and nothing more.

## Caching

List and detail responses (`/judges`, `/courts`, `/jurisdictions` and
their details) carry `Cache-Control: public, max-age=60`. Error
responses and `/search` are not cached.

## Rate limits

`/search` is rate limited in-process by an anonymous token bucket per
client address: `JUDGEMETRICS_SEARCH_RATE_LIMIT_BURST` tokens (default
`10`) refilled at `JUDGEMETRICS_SEARCH_RATE_LIMIT_PER_MINUTE` (default
`60`) a minute. When the bucket is empty the response is `429` with
`Retry-After` and the `rate_limited` error body. The client address is
the TCP peer, or the address a trusted reverse proxy appended to
`X-Forwarded-For` when `JUDGEMETRICS_TRUST_PROXY=true`; without that
setting the header is ignored because a client controls it. This
limiter is the local layer beneath the Phase 8 edge limits (the reverse
proxy or CDN): it protects one process from one client, is not shared
across workers, and forgets everything on restart. It is on in every
environment except `test`, where `JUDGEMETRICS_SEARCH_RATE_LIMIT_ENABLED=true`
switches it on explicitly.

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
  "ingest_run_id": "30e40b48-f9c7-40ca-8c0d-ace56a3e1ed3"
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
statements at the cursor: a judge detail costs at most three statements
(the judge, its service records with their courts, the provenance
rows), a list at most two (the page with its window count, plus the
similarity `set_config` when `q` is given), and a search at most two.

## Examples

```sh
curl -s 'http://127.0.0.1:8000/api/v1/judges?q=sotomayor&limit=5'
curl -s 'http://127.0.0.1:8000/api/v1/judges?court_id=<uuid>&active_on=2010-01-01'
curl -s 'http://127.0.0.1:8000/api/v1/judges/<uuid>'
curl -s 'http://127.0.0.1:8000/api/v1/courts?court_type=district&limit=100'
curl -s 'http://127.0.0.1:8000/api/v1/search?q=ninth%20circuit'
curl -si 'http://127.0.0.1:8000/api/v1/judges?limit=101'        # 422
```
