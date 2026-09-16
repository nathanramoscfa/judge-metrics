<!-- docs/DATA_SOURCES.md -->
# Data sources

The source register for JudgeMetrics. Every source goes through the
same due-diligence record before a production connector is written, per
the brief's source policy: owner, documentation, access method, terms,
update frequency, cost, rate limits, fields available, fields
prohibited, retention restrictions, and provenance requirements.

Entries marked **verified** were checked against the live source on the
date shown. Entries marked **unverified** are candidates; nothing in a
connector may depend on an unverified claim. Do not fabricate
capabilities: if a field or file is not listed here as verified, the
connector must confirm it at first fetch and fail loudly if it is
absent. Open questions about any source are tracked in
[`docs/ROADMAP.md`](ROADMAP.md) "Unresolved data-access questions".

Every entry carries a **Redistribution** field answering three
questions separately: may derived aggregates be republished, may
pseudonymous case-level views be republished, and may either be
redistributed commercially. Each answer is `yes`, `no`, or
`unverified`, with the terms that support it. The free public surface
depends only on the first two; the paid tiers of Phase 9 depend on the
third and exclude by configuration any source whose commercial answer
is not a verified `yes`. Record the answer when the source is verified,
not when a product needs it; for negotiated access (Florida), ask for
it as a term of the agreement (root roadmap §5.5).

## Register

| Id            | Source                                                   | Role in the roadmap                       | Status (date)            | Phase | Commercial redistribution |
|---------------|----------------------------------------------------------|-------------------------------------------|--------------------------|-------|---------------------------|
| `fjc`         | Federal Judicial Center, Biographical Directory export   | Federal judge master data, court roster   | verified (2026-09-15)    | 1     | yes (US government work) |
| `synthetic`   | Deterministic synthetic justice dataset (in-repo generator) | MVP demo data, golden regression fixture | by construction         | 2     | n/a (never a product) |
| `cook_sao`    | Cook County State's Attorney case-level datasets         | First real state-court corpus             | verified (2026-09-15)    | 5     | unverified (question 2) |
| `fl_jdms`     | Florida Courts Judicial Data Management Services / UCR   | Florida court-event structure; credentialed access | unverified; workstream | 5, 7 | unverified; negotiate (question 8) |
| `fl_clerks`   | Florida county clerks (candidates: Broward, Miami-Dade, others) | Florida pilot criminal case data     | unverified; workstream   | 5, 7  | unverified; negotiate (question 8) |
| `courtlistener` | CourtListener bulk data and REST API                   | Federal courts, dockets, judges; coverage | verified, partial (2026-09-15) | 7 | bulk yes (Public Domain Mark); API unverified (question 5) |
| `pacer`       | PACER (federal judiciary)                                | Federal case locator and dockets, metered | unverified; workstream   | 7     | unverified (question 6) |
| `ny_oca_pretrial` | New York State court system pretrial release data    | Pretrial decisions with judge attribution | unverified; candidate    | 7     | unverified (question 7) |
| `fbi_cde`     | FBI Crime Data Explorer                                  | Jurisdiction crime context only           | reference                | 7+    | n/a (context only) |
| `bjs`         | Bureau of Justice Statistics                             | Reference statistics and methodology      | reference                | 3+    | n/a (cited, not redistributed) |

---

## `fjc` — Federal Judicial Center Biographical Directory export

- **Owner:** Federal Judicial Center (United States federal government).
- **Documentation:** the export page
  `https://www.fjc.gov/history/judges/biographical-directory-article-iii-federal-judges-export`.
- **Access method:** HTTPS download of static files. No credentials.
- **Files (verified 2026-09-15):**
  - Format 1, organized by judge: `judges.csv` and `judges.xlsx`.
  - Format 2, organized by category: `categories.xlsx`,
    `demographics.csv`, `federal-judicial-service.csv`,
    `other-federal-judicial-service.csv`, `education.csv`,
    `professional-career.csv`, `other-nominations-recess.csv`.
- **Key:** the FJC "Node ID" (`nid`) identifies a judge across every
  file and links to the judge's biography page.
- **Update frequency:** the export is regenerated nightly; historical
  records are revised when errors are discovered.
- **Terms:** work of the United States federal government; cite the FJC
  as the source. Questions about discrepancies go to `history@fjc.gov`.
- **Redistribution:** aggregates `yes`; record-level `yes`;
  commercial `yes` — a work of the United States government is not
  subject to copyright (17 U.S.C. § 105); attribution to the FJC is
  kept as a courtesy and for provenance.
- **Cost / rate limits:** free; none stated. Fetch at most once per
  ingest run and honour conditional requests where the server supports
  them.
- **Fields available:** judge identity, service records per court with
  appointment, commission, senior-status, and termination dates, chief
  judge service, education, career, nominations. The exact column
  headers must be read from the file at first fetch; the connector
  maps by exact header name and fails if an expected header is absent.
- **Fields prohibited / sensitive:** none legally restricted; the
  directory covers public officials. Demographic fields exist in
  `demographics.csv` and are not needed for Phase 1; do not ingest them
  until a documented purpose exists.
- **Retention:** none.
- **Provenance requirements:** store each downloaded file immutably with
  sha256, retrieval timestamp, and the export page URL; record the
  parser version on every derived row.
- **Remaining to verify:** exact header names of `judges.csv` and
  `federal-judicial-service.csv`; whether the server sends `ETag` or
  `Last-Modified` headers.

---

## `synthetic` — deterministic synthetic justice dataset

- **Owner:** this repository (`judgemetrics synthetic generate`).
- **Role:** the brief's synthetic demo dataset and golden regression
  fixture. The complete website and analytics engine must be
  demonstrable before production jurisdiction data exists, and only
  synthetic data with known truth allows entity resolution and every
  metric to be tested against exact expectations.
- **Access method:** generated locally from a seed; source-format files
  under `data/synthetic/<seed>/` (untracked) and the golden fixture
  under `tests/fixtures/golden/` (tracked).
- **Content (Phase 2 requirements from the brief):** at least 5 courts,
  20 judges, 5,000 cases, and 3,000 defendants at demo scale; multiple
  judge assignments and offense categories; pretrial release and
  detention decisions with a deciding judge; dismissals attributed
  separately to judges and prosecutors; convictions; sentences;
  subsequent cases; failures to appear; revocations; intentional
  duplicate source records; intentional ambiguous person matches;
  missing-data examples. A `truth/` directory records true identities,
  true events, and expected metric values and never enters the
  canonical database.
- **Handling rules:** `source.source_type = synthetic`; labelled as
  synthetic on every public surface; refused by the ingest runner when
  `JUDGEMETRICS_ENV=production`; person names generated from word
  lists, never from lists of real people; two runs from the same seed
  are byte-identical.
- **Redistribution:** not applicable. Synthetic data is never part of
  any snapshot bundle or paid tier; it is refused in production.

---

## `cook_sao` — Cook County State's Attorney case-level datasets

- **Owner:** Cook County State's Attorney's Office (SAO), published on
  the Cook County open-data portal (`datacatalog.cookcountyil.gov`).
- **Documentation:** each dataset's portal page and the SAO data
  documentation. The datasets' descriptions state: "This dataset is no
  longer actively maintained as of 12/30/2024" and point to the SAO
  data dashboards for 2025 onward.
- **Access method:** Socrata export endpoints (bulk CSV) and the SODA
  API. An application token raises API rate limits; bulk export needs
  no credential.
- **Datasets (verified 2026-09-15; portal ids in parentheses):**
  - **Intake** (`3k7z-hchi`), 17 columns: `case_id`,
    `case_participant_id`, `received_date`, `offense_category`,
    `participant_status`, `age_at_incident`, `race`, `gender`,
    `incident_city`, `incident_begin_date`, `incident_end_date`,
    `law_enforcement_agency`, `unit`, `arrest_date`,
    `felony_review_date`, `felony_review_result`,
    `update_offense_category`. One row per potential defendant per case
    brought for felony review.
  - **Initiation** (`7mck-ehwz`), 38 columns, including `case_id`,
    `case_participant_id`, `received_date`, `offense_category`,
    `primary_charge`, `charge_id`, `charge_version_id`,
    `charge_offense_title`, `charge_count`, `chapter`, `act`,
    `section`, `class`, `aoic`, `event`, `event_date`,
    `finding_no_probable_cause`, `arraignment_date`,
    `bond_date_initial`, `bond_date_current`, `bond_type_initial`,
    `bond_type_current`, `bond_amount_initial`, `bond_amount_current`,
    `bond_electronic_monitor_flag_initial`,
    `bond_electroinic_monitor_flag_current` (sic, as published),
    `age_at_incident`, `race`, `gender`, `incident_city`,
    `incident_begin_date`, `incident_end_date`,
    `law_enforcement_agency`, `unit`, `arrest_date`,
    `felony_review_date`, `felony_review_result`,
    `updated_offense_category`. One row per charge at initiation.
    Bond fields describe the pretrial release decision; the deciding
    judicial officer is not in the data.
  - **Dispositions** (`apwk-dzx8`), 33 columns, including `case_id`,
    `case_participant_id`, `received_date`, `offense_category`,
    `primary_charge`, `charge_id`, `charge_version_id`,
    `disposition_charged_offense_title`, `charge_count`,
    `disposition_date`, `disposition_charged_chapter`,
    `disposition_charged_act`, `disposition_charged_section`,
    `disposition_charged_class`, `disposition_charged_aoic`,
    `charge_disposition`, `charge_disposition_reason`, `judge`,
    `court_name`, `court_facility`, `age_at_incident`, `race`,
    `gender`, `incident_city`, `incident_begin_date`,
    `incident_end_date`, `law_enforcement_agency`, `unit`,
    `arrest_date`, `felony_review_date`, `felony_review_result`,
    `arraignment_date`, `updated_offense_category`. One row per
    disposed charge. `judge` is the disposing judge as recorded by the
    SAO.
  - **Sentencing** (`tg8v-tm6u`), 41 columns: the Dispositions columns
    plus `sentence_judge`, `sentence_phase`, `sentence_date`,
    `sentence_type`, `current_sentence`, `commitment_type`,
    `commitment_term`, `commitment_unit`, `length_of_case_in_days`.
    One row per sentenced charge.
  - **Diversion** (`gpu3-5dfh`), 13 columns: `case_id`,
    `case_participant_id`, `received_date`, `offense_category`,
    `diversion_program`, `referral_date`, `diversion_count`,
    `primary_charge_offense_title`, `statute`, `race`, `gender`,
    `diversion_result`, `diversion_closed_date`.
  - Archived pre-2018-02-13 versions of Intake, Initiation,
    Dispositions, and Sentencing also exist on the portal; the
    connector records which version each raw file came from.
- **Person linkage:** `case_participant_id` is a pseudonymous
  participant identifier assigned by the source. It is the only lawful
  person key for this source; the canonical `person` row is created
  from it with resolution confidence 1.0 within the source, and it is
  never merged across sources by name.
- **Judge attribution:** present on dispositions (`judge`) and
  sentences (`sentence_judge`) as free-text names; resolved to judge
  entities in Phase 5 with a curated alias table and the review queue.
- **Actor attribution:** `charge_disposition` and
  `charge_disposition_reason` value sets drive the attribution rule
  table; the value sets must be read from the published documentation
  and the data itself in Phase 5 Step 1.
- **First real metric:** the brief prefers a metric based on new
  criminal court cases after a clearly identified qualifying pretrial
  event; this source supports it at the court level (bond type at
  initiation plus participant-id linkage to later cases) without
  judge attribution of the pretrial decision.
- **Update frequency:** frozen; the SAO stopped maintaining the
  datasets on 2024-12-30. Rows were last updated on the portal on
  2026-04-02. Treat the corpus as a fixed historical snapshot and
  record the coverage end date on every coverage surface.
- **Terms:** the Cook County open-data portal terms of use. Confirm in
  Phase 5 Step 1 that republication of derived aggregates and
  pseudonymous case-level views is permitted, and record the required
  citation.
- **Redistribution:** aggregates `unverified`; case-level
  `unverified`; commercial `unverified` — all three resolve with
  question 2 in `docs/ROADMAP.md` when the portal terms are read in
  Phase 5 Step 1. Until then the corpus enters no snapshot bundle.
- **Cost / rate limits:** free. SODA API limits apply without an app
  token; bulk export is the preferred path.
- **Fields prohibited / sensitive:** `race`, `gender`, and
  `age_at_incident` are ingested only into the restricted schema, are
  never exposed at the person level, are never model features by
  default, and are used only for aggregate fairness analysis pending
  the Phase 6 legal review. Names of defendants are not in these
  datasets.
- **Retention:** none stated.
- **Provenance requirements:** immutable raw CSV per dataset per fetch
  with sha256, portal id, rows-updated timestamp from the portal
  metadata, and retrieval time; parser version on every derived row.
- **Known limitations:** felony cases only; pretrial release decisions
  lack judge attribution; no failure-to-appear, rearrest, or
  release-violation events; judge names are free text; the corpus ends
  on 2024-12-30, so outcome windows are right-censored there.
- **Remaining to verify:** portal terms of use; the documented value
  sets for dispositions, reasons, bond types, and sentence fields;
  stability of `case_participant_id` across the five datasets.

---

## `fl_jdms` and `fl_clerks` — Florida sources

- **Owner:** Florida Office of the State Courts Administrator (OSCA),
  whose Judicial Data Management Services (JDMS) program owns the
  Uniform Case Reporting (UCR) specification; individual county clerks
  of court for case data.
- **Role:** the brief's pilot jurisdiction and its "State" scaling
  stage. The UCR specification documents Florida's canonical
  court-event fields, including judicial officers and case events.
  Direct web-service access requires coordinated credentials; it is not
  anonymously readable.
- **Candidates:** Broward County and Miami-Dade County may be
  evaluated, but neither is assumed to be the best pilot until current
  source access is verified; other counties and circuits are in scope.
- **Selection process (Phase 5 §5.5, from the brief):** evaluate
  jurisdictions for data accessibility; document available fields and
  history; confirm judge assignment information; confirm charges and
  dispositions; confirm defendant matching fields that may lawfully be
  processed; confirm pretrial and release information; confirm
  follow-up event feasibility; estimate extraction and maintenance
  cost; select the jurisdiction with the strongest data rather than by
  population. Prefer bulk exports, APIs, machine-readable downloads, or
  public-records requests before any scraping, and never scrape
  against a site's terms.
- **Status:** unverified; a Phase 5 research workstream producing
  `docs/florida-data-inventory.md` and a lawful acquisition plan, with
  the connector landing in Phase 7 once access is secured.
- **Redistribution:** aggregates `unverified`; case-level
  `unverified`; commercial `unverified`. Access is negotiated, so each
  request and agreement asks for all three explicitly (root roadmap
  §5.5); the answer is a term of the agreement and is recorded here
  when it is signed.
- **Remaining to verify:** JDMS/UCR credential process; each
  candidate clerk's bulk or API offering; public-records request
  process and turnaround; cost; terms; fields; history depth;
  redistribution rights.

---

## `courtlistener` — CourtListener bulk data and REST API

- **Owner:** Free Law Project (non-governmental, non-profit).
- **Documentation:** bulk data help page (redirects to the Free Law
  wiki) and the REST API documentation.
- **Access method (verified 2026-09-15):** bulk CSV files generated
  from the PostgreSQL tables (UTF-8, header row), downloaded from an S3
  bucket through a browsable interface or the AWS CLI; the REST API
  with an API token for incremental and detail data.
- **Bulk files:** courts, dockets, opinion clusters, opinions,
  citations map, parentheticals, the integrated FJC database, judges
  ("people"), financial disclosures, oral arguments, and embeddings.
- **Update frequency:** bulk files are regenerated quarterly on the
  last day of March, June, September, and December; each run is a full
  snapshot, not a delta.
- **Terms:** bulk data files are released under the Public Domain
  Mark; API terms and rate limits apply to the REST API and must be
  recorded before the connector goes live.
- **Redistribution:** bulk files — aggregates `yes`; record-level
  `yes`; commercial `yes` (Public Domain Mark, verified 2026-09-15).
  REST API responses — all three `unverified` until the API terms are
  recorded (question 5); keep bulk-derived and API-derived rows
  distinguishable by `source_record` so a snapshot bundle can exclude
  the latter.
- **Cost:** free for bulk; the API has rate limits per token.
- **Fields available:** court metadata, docket metadata including
  assigned judges, judge biographies linked to FJC identifiers.
- **Known limitations:** the bulk page does not describe RECAP coverage
  of federal criminal dockets; coverage is partial and must be measured
  before any metric depends on it. Docket entries and parties may be
  API-only; confirm.
- **Remaining to verify:** API rate limits and terms; whether docket
  entries and parties are in bulk or API-only; the FJC linkage field on
  judges.

---

## `pacer` — PACER

- **Owner:** Administrative Office of the United States Courts.
- **Role:** official federal case locator and dockets. Fees apply per
  page with a quarterly waiver threshold; an account is required.
- **Status:** unverified; a Phase 7 workstream. The connector interface
  ships behind a feature flag with a dry-run mode, a per-run and monthly
  spend ledger, and a hard cap; no uncontrolled paid requests are
  possible by construction.
- **Redistribution:** aggregates `unverified`; record-level
  `unverified`; commercial `unverified`. Court records obtained from
  PACER are public records, but the Case Locator API terms may
  restrict redistribution and must be read first (question 6).
- **Remaining to verify:** account type and credentials, the
  Authentication API and Case Locator API terms, current fee schedule,
  the waiver threshold, and redistribution rights.

---

## `ny_oca_pretrial` — New York State court system pretrial release data

- **Owner:** New York State Unified Court System, Office of Court
  Administration.
- **Role:** a candidate pretrial-decision source with judge
  attribution, published under state law after the 2019 bail reforms.
- **Status:** unverified. The public page returned HTTP 403 to an
  automated fetch on 2026-09-15; verify manually in a browser.
- **Believed to contain (must be verified before use):** case-level
  arraignment records by county with the top charge, release decision,
  bail amounts, and subsequent re-arrest and failure-to-appear
  indicators; the arraignment judge's name is reported in public
  analyses of this data and must be confirmed against the data
  dictionary.
- **Redistribution:** aggregates `unverified`; case-level
  `unverified`; commercial `unverified` (question 7).
- **Remaining to verify:** files and cadence, the data dictionary,
  whether judge names are present, terms of use, and any republication
  restrictions including commercial redistribution.

---

## `fbi_cde` and `bjs` — reference sources

- FBI Crime Data Explorer provides jurisdiction- and agency-level crime
  context. It is not a person-level criminal-history source and is
  never used for person linkage.
- Bureau of Justice Statistics publications provide reference
  statistics, recidivism definitions, and methodology that the
  methodology page cites.
- **Redistribution:** not applicable; both are cited, never
  redistributed, and enter no snapshot bundle.
