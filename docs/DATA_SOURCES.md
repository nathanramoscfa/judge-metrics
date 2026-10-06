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
| `fjc`         | Federal Judicial Center, Biographical Directory export   | Federal judge master data, court roster   | verified (2026-09-16)    | 1     | yes (US government work) |
| `synthetic`   | Deterministic synthetic justice dataset (in-repo generator) | MVP demo data, golden regression fixture | by construction         | 2     | n/a (never a product) |
| `cook_sao`    | Cook County State's Attorney case-level datasets         | First real state-court corpus             | verified (2026-10-05)    | 5     | unverified (question 2; aggregates yes) |
| `fl_jdms`     | Florida Courts Judicial Data Management Services / UCR   | Florida court-event structure; reference only | researched (2026-10-05); no non-agency access found | 5, 7 | unverified (question 8) |
| `fl_cjdt`     | FDLE Criminal Justice Data Transparency (statewide)      | Florida pilot companion: cross-case person key, pretrial, sentences | verified, partial (2026-10-05) | 5, 7 | unverified; requested (question 8) |
| `fl_clerks`   | Florida county clerks (pilot Hillsborough; fallback Broward, Miami-Dade) | Florida pilot criminal case data | verified, partial (2026-10-05) | 5, 7 | unverified; requested (question 8) |
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
- **Fetch (verified 2026-09-16):**
  `https://www.fjc.gov/sites/default/files/history/judges.csv`
  (5,452,935 bytes, 4,075 rows) and
  `https://www.fjc.gov/sites/default/files/history/federal-judicial-service.csv`
  (1,638,289 bytes, 4,775 rows), served as `application/octet-stream`
  with `ETag` and `Last-Modified` (`Wed, 16 Sep 2026 05:05:19 GMT` and
  `05:05:22 GMT`), so conditional requests (`If-None-Match`,
  `If-Modified-Since`) work and the connector sends both. UTF-8, LF
  line endings, no byte-order mark, every field quoted, dates
  `YYYY-MM-DD`. No redirects.
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
  judge service, education, career, nominations.
- **Headers (verified 2026-09-16; recorded in
  `src/judgemetrics/ingest/fjc/schema.py`):**
  - `federal-judicial-service.csv`, 30 columns, one row per
    appointment: `nid`, `Sequence`, `Judge Name`, `Court Type`,
    `Court Name`, `Appointment Title`, `Appointing President`,
    `Party of Appointing President`, `Reappointing President`,
    `Party of Reappointing President`, `ABA Rating`, `Seat ID`,
    `Statute Authorizing New Seat`, `Recess Appointment Date`,
    `Nomination Date`, `Committee Referral Date`, `Hearing Date`,
    `Judiciary Committee Action`, `Committee Action Date`,
    `Senate Vote Type`, `Ayes/Nays`, `Confirmation Date`,
    `Commission Date`, `Service as Chief Judge, Begin`,
    `Service as Chief Judge, End`, `2nd Service as Chief Judge, Begin`,
    `2nd Service as Chief Judge, End`, `Senior Status Date`,
    `Termination`, `Termination Date`.
  - `judges.csv`, 201 columns, one row per judge: `nid`, `jid`,
    `Last Name`, `First Name`, `Middle Name`, `Suffix`, `Birth Month`,
    `Birth Day`, `Birth Year`, `Birth City`, `Birth State`,
    `Death Month`, `Death Day`, `Death Year`, `Death City`,
    `Death State`, `Gender`, `Race or Ethnicity`; then the 27
    appointment columns above (`Court Type` … `Termination Date`) six
    times, suffixed ` (1)` … ` (6)`; `Other Federal Judicial Service
    (1)` … ` (4)`; `School`, `Degree`, `Degree Year` ` (1)` … ` (5)`;
    `Professional Career`; `Other Nominations/Recess Appointments`.
  - The connector reads, and requires, `nid`, `jid`, the four name
    parts, `Birth Year`, and per appointment `Court Type`,
    `Court Name`, `Appointment Title`, `Recess Appointment Date`,
    `Commission Date`, `Senior Status Date`, `Termination`, and
    `Termination Date`. A missing expected header fails the run
    naming the header; a header outside the verified set is logged as
    a warning (schema drift).
  - Vocabularies (every distinct value on 2026-09-16): `Court Type` ∈
    {`U.S. District Court`, `U.S. Court of Appeals`, `Supreme Court`,
    `Other`, `U.S. Circuit Court (1869-1911)`,
    `U.S. Circuit Court (1801-1802)`, `U.S. Circuit Court (other)`};
    `Appointment Title` ∈ {`Judge`, `Chief Judge`, `Associate Judge`,
    `Presiding Judge`, `Associate Justice`, `Chief Justice`};
    `Termination` ∈ {`Death`, `Retirement`, `Resignation`,
    `Appointment to Another Judicial Position`, `Reassignment`,
    `Abolition of Court`, `Recess Appointment-Not Confirmed`,
    `Impeachment & Conviction`} or blank. `Birth Year` is `YYYY` or
    `ca. YYYY`. 35 appointments have no commission date (33 of them
    have a recess appointment date, which the connector uses as the
    start); 2 have no start date at all.
- **Fields prohibited / sensitive:** none legally restricted; the
  directory covers public officials. Demographic fields exist in
  `demographics.csv` (never fetched) and as the `Gender` and
  `Race or Ethnicity` columns of `judges.csv`; the parser projects
  every row to the expected columns, so they never reach a payload, a
  canonical row, or a log. Do not ingest them until a documented
  purpose exists.
- **Retention:** none.
- **Provenance requirements:** store each downloaded file immutably with
  sha256, retrieval timestamp, and the export page URL; record the
  parser version on every derived row.
- **Ingested by:** `judgemetrics ingest run fjc` (`uv run poe
  ingest-fjc`), connector `FjcConnector`, parser version `2026.09.1`,
  into `jurisdiction`, `court`, `judge`, and `judge_service`; the
  fixture excerpt is `tests/fixtures/fjc/`.
- **Remaining to verify:** nothing for Phase 1 (headers and conditional
  requests verified 2026-09-16; `docs/ROADMAP.md` question 1 resolved).

---

## `synthetic` — deterministic synthetic justice dataset

- **Owner:** this repository (`judgemetrics synthetic generate`).
- **Role:** the brief's synthetic demo dataset and golden regression
  fixture. The complete website and analytics engine must be
  demonstrable before production jurisdiction data exists, and only
  synthetic data with known truth allows entity resolution and every
  metric to be tested against exact expectations.
- **Access method:** generated locally from a seed by
  `judgemetrics synthetic generate --seed <int> --scale golden|demo|tiny
  --out <dir>` (default `data/synthetic/<seed>`, untracked); the golden
  fixture (seed 7) is tracked under `tests/fixtures/golden/`;
  `judgemetrics synthetic verify <dir>` recomputes every file hash
  against the manifest. Format and world model: `docs/SYNTHETIC_DATA.md`.
- **Files:** `<dir>/manifest.json` (seed, scale, `generator_version`,
  `truth_version`, row counts, sha256 per file); `<dir>/source/`
  (`courts.csv`, `judges.csv`, `cases.csv`, `participants.csv`,
  `charges.csv`, `assignments.csv`, `events.csv`, `decisions.csv`,
  `sentences.csv` — UTF-8, LF, header row, sorted by id, empty means
  missing, UTC ISO 8601 timestamps; the only files the connector
  discovers); `<dir>/truth/` (`persons.csv`, `subsequent_events.csv`,
  `resolution_expectations.csv`, `planted.csv`, `metrics.json`,
  `README.md` — the simulation's truth, never ingested). Vocabularies:
  `judgemetrics.synthetic.vocabulary` (version 1), written to
  `data/reference/case_vocabulary.yaml` and loaded by
  `judgemetrics.normalization.vocabulary` (equal by unit test).
- **Connector (Phase 2 Step 2):** `judgemetrics.ingest.synthetic`,
  source id `synthetic`, parser version `1`. `discover` lists
  `manifest.json` and then `source/<file>` for the nine files under
  `JUDGEMETRICS_SYNTHETIC_DIR` (default `data/synthetic/20260916`, the
  dataset root); `truth/` is never discovered. `load_context` fails the
  run when a file's sha256 no longer matches the manifest;
  `validate_raw` checks the manifest's `generator_version` against the
  installed generator and each file's header set (missing → error naming
  the header, extra → warning). Person attributes (`full_name`,
  `date_of_birth`, `participant_id`) are hashed with
  `JUDGEMETRICS_IDENTIFIER_PEPPER` and reach the database only as
  `person_identifier` rows. Run it with `uv run poe seed` (generate and
  ingest the demo scale) or `judgemetrics ingest run synthetic
  --from-fixture tests/fixtures/golden` (the golden fixture).
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
  the Cook County open-data portal (`datacatalog.cookcountyil.gov`, owner
  "Cook County Open Data"; every dataset's metadata says `provenance:
  official`, category "Legal & Judicial").
- **Documentation read (2026-10-05):**
  - Each dataset's portal page and metadata document
    (`https://datacatalog.cookcountyil.gov/api/views/<id>.json`). Every
    description opens: "This dataset is no longer actively maintained as
    of 12/30/2024. Please visit the site below to explore data dashboards
    published by the State's Attorney's Office beginning 2025."
    Initiation's adds: "This data includes felony cases handled by the
    Criminal, Narcotics, and Special Prosecution Bureaus. It does not
    include information about cases processed through the Juvenile Justice
    and Civil Actions Bureaus."
  - The SAO's two attachments, identical on every dataset: the *CCSAO
    Data Glossary* (19 pages, authored 2020-07-01; definitions and
    "most common values" of every column),
    `https://datacatalog.cookcountyil.gov/api/views/apwk-dzx8/files/4d3f91ea-857d-4f04-994f-918980b0b319?download=true&filename=CCSAO%20Data%20Glossary.pdf`,
    and the *CCSAO Felony Cases Flowchart* (one page: intake, felony
    review, bond hearing, preliminary hearing or grand jury, arraignment,
    plea, bench or jury trial, sentencing, diversion),
    `https://datacatalog.cookcountyil.gov/api/views/apwk-dzx8/files/ebb427cf-8198-4b8d-bb7a-fd6906076eee?download=true&filename=CCSAO%20Felony%20Cases%20Flowchart.pdf`.
  - The portal's terms of use: its footer links
    `https://www.cookcountyil.gov/terms-use` (the County's site terms,
    sections 1–10).
- **Access method (verified 2026-10-05):** the Socrata bulk CSV export
  `https://datacatalog.cookcountyil.gov/api/views/<id>/rows.csv?accessType=DOWNLOAD`,
  anonymous HTTPS, no token, served chunked (no `Content-Length`; range
  requests are ignored), with `Last-Modified` and an `ETag`. UTF-8, LF
  line endings, no byte-order mark, a header row of the portal's column
  *display names*. The connector reads each dataset's metadata first and
  downloads nothing when its `rowsUpdatedAt` equals the one recorded with
  the previous retrieval; the SODA API is not used.
- **Datasets (stored 2026-10-05 by `judgemetrics ingest run cook_sao`,
  parser version `0`; rows updated on the portal on 2026-04-02 for all
  five):**

  | Dataset | Portal id | Columns | Rows | Bytes | sha256 |
  |---|---|---|---|---|---|
  | Intake | `3k7z-hchi` | 17 | 528,111 | 92,556,995 | `b43e8983b505d0be486a095660e38dd8f1ca96c4578e6510f77858b4d7d47b0f` |
  | Initiation | `7mck-ehwz` | 38 | 1,228,260 | 512,058,076 | `a333e72a0b928c30681914b93a07b316b0e5a354bc4de68aab396b0ba92f1457` |
  | Dispositions | `apwk-dzx8` | 33 | 1,080,014 | 453,255,374 | `38e516e38f6f373d083441efd03737ff5045d657c83749e4358978b72bd5c526` |
  | Sentencing | `tg8v-tm6u` | 41 | 305,884 | 158,370,275 | `3322a3c3d1c7e64458968e26b64826adf9f040c43000b910faa7be7144b3f1b3` |
  | Diversion | `gpu3-5dfh` | 13 | 29,421 | 5,407,571 | `69e843df6bc50e77a8f6656bf8daa83ea320b3d74aa853124191ef146103fd12` |

  1,221,648,291 bytes in total; a second download on the same day
  produced the same digests. The streamed fetch peaked at a 130 MiB
  working set (92 MiB of it the CLI itself), independent of the export
  size. Intake is one row per potential defendant
  per case brought for felony review; Initiation one row per charge per
  participant at initiation; Dispositions one row per disposed charge;
  Sentencing one row per sentenced charge; Diversion one row per
  referral to a program.
- **Headers (re-verified 2026-10-05 against each export's first line and
  each metadata column list; recorded in
  `src/judgemetrics/ingest/cook_sao/schema.py`):** the export's header row
  carries the display names, upper-case, which differ from the API field
  names above where noted: Intake `CASE_ID`, `CASE_PARTICIPANT_ID`,
  `RECEIVED_DATE`, `OFFENSE_CATEGORY`, `PARTICIPANT_STATUS`,
  `AGE_AT_INCIDENT`, `RACE`, `GENDER`, `INCIDENT_CITY`,
  `INCIDENT_BEGIN_DATE`, `INCIDENT_END_DATE`, `LAW_ENFORCEMENT_AGENCY`,
  `LAW_ENFORCEMENT_UNIT` (field `unit`), `ARREST_DATE`,
  `FELONY_REVIEW_DATE`, `FELONY_REVIEW_RESULT`, `UPDATE_OFFENSE_CATEGORY`
  (sic; the other datasets say `UPDATED_…`); Initiation and the two
  disposition datasets say `PRIMARY_CHARGE_FLAG` (field `primary_charge`);
  Dispositions `DISPOSITION_COURT_NAME` and `DISPOSITION_COURT_FACILITY`
  (fields `court_name`, `court_facility`); Sentencing
  `SENTENCE_COURT_NAME`, `SENTENCE_COURT_FACILITY`,
  `CURRENT_SENTENCE_FLAG` (field `current_sentence`), and
  `LENGTH_OF_CASE_in_Days`; Initiation keeps the published misspelling
  `BOND_ELECTROINIC_MONITOR_FLAG_CURRENT`. A verified header missing from
  an export or from the metadata fails the run naming it; an extra one is
  a warning.
- **Formats:** every date is month first, in one of two formats:
  `MM/DD/YYYY hh:mm:ss AM` (a real time on the arrest dates and on some
  bond and event dates) or `MM/DD/YYYY` (Intake's received, felony-review,
  and incident dates, and Dispositions' `INCIDENT_BEGIN_DATE`); every
  value parses under one of them. The checkbox columns
  (`PRIMARY_CHARGE_FLAG`, `CURRENT_SENTENCE_FLAG`, the electronic-monitor
  flags) export `true`/`false` where the glossary documents `1`/`0`.
- **Value sets:** every coded column's distinct values with counts, the
  (`CHARGE_DISPOSITION`, `CHARGE_DISPOSITION_REASON`) pairs, and the
  judge strings are in `data/reference/cook_sao/profile.yaml`, generated
  from the stored exports by `judgemetrics sources profile cook_sao`
  (`--check` fails on drift). The glossary documents "most common values"
  only for dispositions, reasons, commitment types, and felony-review
  results, and complete sets for bond types (I, D, C, No Bond, null —
  spelled `I-Bond` there and `I Bond` in the data), diversion programs and
  results, and sentence phases. Highlights: 36 dispositions in
  Dispositions (28 in Sentencing); 31 reasons plus 791,562 null; four
  bond types plus 419,212 null (initial and current alike); six sentence
  phases (7,492 "Probation Violation Sentencing"); 15 sentence types; 29
  commitment types and 12 commitment units ("Natural Life", "Term",
  "Dollars" among them) plus null; 13 classes; six districts plus
  "PROMIS" and "Traffic" in Dispositions; 16 facilities plus null.
- **Person linkage (measured 2026-10-05 from the stored exports):**
  `CASE_PARTICIPANT_ID` is the SAO's pseudonymous identifier of *one
  defendant in one case*: in every dataset no participant id appears
  under more than one `CASE_ID` (Intake 528,111 ids over 479,260 cases;
  Initiation 450,133 over 417,905; Dispositions 379,670 over 355,113;
  Sentencing 264,518 over 247,649; Diversion 27,695 over 26,561). The
  corpus therefore has **no cross-case person key**; the exports carry no
  name or date of birth, and linking on demographics would use the
  restricted attributes and is forbidden. Within the release the keys are
  stable across datasets: no participant id appears in Intake under
  another case, every Initiation and Diversion (case, participant) key is
  in Intake, and the Dispositions and Sentencing keys not in Intake
  (23,759 and 18,158) are exactly those received before 2011, which
  Intake does not cover. The glossary adds that both ids are "Hashed
  independently for every version released. Therefore, it is impossible
  to link two datasets released at different times." A canonical person
  of this source is a case participation (`person` from the participant
  id, confidence 1.0 within the source, never merged across sources or by
  name).
- **Charges:** `CHARGE_ID` and `CHARGE_VERSION_ID` are shared by
  co-defendants — 43,477 Initiation charge versions span more than one
  participant — so a charge row is keyed by (charge version, participant).
  Initiation has 1,171,412 charge ids over 1,171,413 versions; amended
  charges appear in the disposition datasets (3,930 Dispositions charges
  have two versions). Eight Initiation and two Dispositions charge ids
  appear under two cases.
- **Judge attribution:** free-text names on Dispositions (`JUDGE`, 469
  distinct strings, 76,613 rows without one) and Sentencing
  (`SENTENCE_JUDGE`, 402 strings, 742 rows without one), with spacing
  variants ("Stanley  Sacks"). The glossary defines `JUDGE` as "Judge who
  oversaw the case" and `SENTENCE_JUDGE` as "Judge who oversaw the
  sentencing" — it does not call `JUDGE` the judge who entered the
  disposition. The bond fields name no judicial officer. Resolution to
  judge entities by a curated alias table is Phase 5 Step 3.
- **Actor attribution:** the glossary attributes "Nolle Prosecution" to
  the prosecutor ("The prosecutor has decided not to pursue this
  charge"), "Finding Guilty" and "FNG" to "a judge in a bench trial", the
  verdicts to "jurors in a jury trial", and describes "SOL" as "Illinois
  judges remove cases from the court's active list … without the State
  forfeiting the right to reinstate". The rule table that maps every
  (disposition, reason) pair of the profile to an actor and a
  judicial-discretion classification, with `unknown` as the explicit
  fallback, is Phase 5 Step 3.
- **First real metrics:** the judge-attributed sentencing family
  (`SENTENCE_JUDGE`), the disposition family where Step 3's rules and
  Step 5's gate attribute it, and court-level bond decisions; the one
  within-case subsequent event the data records is a probation-violation
  resentencing. No cross-case outcome (new case, new charge,
  reconviction) is observable, and none is published for this source,
  never as a zero.
- **Update frequency and coverage evidence:** frozen. The SAO stopped
  maintaining the datasets on 2024-12-30, and the portal re-published
  all five on 2026-04-02 (the metadata's "Update Frequency: As Needed" and
  "Publishing frequency: Quarterly" are stale). The last receipt dates
  are 2024-11-30 (Intake, Initiation), 2024-11-29 (Dispositions),
  2024-10-31 (Sentencing), and 2024-11-12 (Diversion); Intake and
  Initiation begin on 2011-01-01. Record the coverage end on every
  coverage surface.
- **Archived versions (recorded, never fetched):** the releases of
  2018-02-13, archived on 2018-10-03 with no license recorded — Intake
  `a2mv-5et6` (298,919 rows, 16 columns), Initiation `qr2q-atnt`
  (732,589, 24), Dispositions `75tm-jf99` (654,580, 29), Sentencing
  `qhfs-h477` (189,288, 36); there is no Diversion archive. Their ids
  were hashed for that release and cannot be joined to the current one.
  The portal also holds 2017 aggregate reports of the SAO (counts by
  offense type, race, gender, age, location), not case-level data.
- **Terms (read 2026-10-05):** the County's terms disclaim liability and
  warranty ("NO WARRANTY, EXPRESSED OR IMPLIED, IS MADE REGARDING
  ACCURACY, ADEQUACY, COMPLETENESS, LEGALITY, RELIABILITY OR USEFULNESS
  OF ANY INFORMATION POSTED ON THE COUNTY WEBSITES", §2), bind the user to
  lawful use ("By use of this system and any data contained therein, you
  agree that your use shall conform to all applicable laws and
  regulations and you shall not violate the rights of any third
  parties", §7), and state that "The content of County websites is
  copyrighted … one should presume the need to obtain permission from the
  copyright holder before reproducing or otherwise using images/graphics
  from this website" (§10). Each dataset's metadata carries `"license":
  {"name": "Public Domain"}` (`licenseId` `PUBLIC_DOMAIN`), `"attribution":
  "Cook County State's Attorney's Office"` (Dispositions and Sentencing
  spell it "Cook County State's Attorney Office"), and the attribution
  link `https://www.cookcountystatesattorney.org/`.
- **Citation:** no document prescribes one. The project cites "Cook
  County State's Attorney's Office, <dataset> (Cook County Open Data,
  datacatalog.cookcountyil.gov, dataset <portal id>), rows updated
  2026-04-02, retrieved <date>", the attribution the metadata names.
- **Redistribution:** aggregates `yes` — all five datasets are licensed
  "Public Domain", and a derived aggregate reproduces none of the
  County's content, so §10 does not reach it; case-level `unverified` — a
  pseudonymous case-level view republishes the dataset's records, for
  which the dataset's "Public Domain" designation and the site terms'
  "content of County websites is copyrighted" (§10) conflict on their
  face, and §7 forbids violating "the rights of any third parties"
  without saying whether a pseudonymous view of a defendant's record does;
  commercial `unverified` — no document mentions commercial use, and the
  one-word designation carries no deed or license text defining its scope.
  Both open answers are question 2's (operator) in `docs/ROADMAP.md`;
  until they settle, the corpus enters no snapshot bundle and no paid
  tier.
- **Cost / rate limits:** free; the bulk export needs no token and none
  is used. Downloads ran at 0.25–4 MB/s on 2026-10-05 (a full fetch took
  12 minutes once and longer when the portal throttled).
- **Fields prohibited / sensitive:** `RACE`, `GENDER`, and
  `AGE_AT_INCIDENT` are ingested only into the restricted schema (the age
  as a band), are never exposed at the person level, are never model
  features by default, and are used only for aggregate fairness analysis
  pending the Phase 6 legal review; `profile.yaml` lists race and gender
  as values only and the age as a range, never with a count. The
  incident's city and dates and the arresting agency and unit are
  quasi-identifiers the canonical model never reads; with the restricted
  columns they are blanked in every row of the committed fixture
  (`tests/fixtures/cook_sao/`). The exports carry no defendant name.
- **Retention:** none stated.
- **Provenance requirements:** one immutable raw CSV per dataset per
  changed export in the raw lake with its sha256; the `source_record`
  carries the portal id, the rows-updated time, the license, the
  attribution, the column list, the metadata URL, the retrieval time, the
  `ETag`, and `Last-Modified`; the parser version on every derived row.
- **Ingested by:** `judgemetrics ingest run cook_sao` (`uv run poe
  ingest-cook`), connector `CookSaoConnector`, parser version `0` (fetch
  and store only; Phase 5 Step 4 parses); the fixture is
  `tests/fixtures/cook_sao/` (73 real cases chosen by
  `judgemetrics sources excerpt cook_sao`, restricted and
  quasi-identifying columns blanked).
- **Known limitations:** felony cases of three SAO bureaus only; no
  cross-case person key, so no cross-case outcome; the ids are re-hashed
  for every release, so a re-publication would re-key every case and
  participant and the 2018 archives cannot be joined; a bond type records
  the bond court's decision, not whether the person was released (posting
  is not recorded), and the bond fields name no judicial officer;
  Illinois ended cash bail on 2023-09-18 (the Pretrial Fairness Act), so
  bond types mean different things before and after; `JUDGE` is "Judge
  who oversaw the case", and 76,613 disposition rows have none; judge
  names are free text; 97,464 Dispositions and 25,013 Sentencing rows were
  received before 2011 (Intake and Initiation start on 2011-01-01), four
  Dispositions rows on 1901-07-24; typo dates run to the year 2924
  (`anomalies` in the profile); no failure-to-appear, rearrest, or
  release-violation events; the corpus ends on 2024-12-30, so outcome
  windows are right-censored there.
- **Remaining to verify:** question 2 only — whether pseudonymous
  case-level views may be republished and whether either view may be
  redistributed commercially, given the license and terms quoted above
  (for example, written confirmation from the SAO or the County's
  open-data team).

---

## Florida sources — `fl_jdms`, `fl_cjdt`, `fl_clerks`

Researched on 2026-10-05 (Phase 5 Step 2). The evidence, with every URL, the
law that governs these records, the scored selection, and the acquisition plan
are in [`docs/florida-data-inventory.md`](florida-data-inventory.md); the
bracketed ids below are its source ids. The selected pilot is Hillsborough
County, with `fl_cjdt` as its companion; the requests are logged in
[`docs/ROADMAP.md`](ROADMAP.md) "Florida acquisition requests" (question 8).
Nothing in a connector may depend on a claim below that is not marked
verified.

### `fl_jdms` — OSCA's JDMS and the UCR specification

- **Owner:** Florida Office of the State Courts Administrator (OSCA). Clerks
  must report "the activity of all cases before all courts within the clerk's
  jurisdiction to the supreme court" (rule 2.245(a)), and a uniform case
  reporting system is statutory (§25.075) — verified [L17, L9].
- **Documentation:** unread. Every `flcourts.gov` host serves `User-agent: *` /
  `Disallow: /` [W2], so the JDMS page, the UCR Data Collection Specification
  (latest found 1.4.2, November 2020), the UCR web-service specification and
  FAQ, and AOSC16-15 are known only from search listings [W1, W3–W6].
- **Access method:** none found for a non-agency requester. UCR is the clerks'
  submission channel to OSCA, with county credentials issued by OSCA
  (unverified [W4, W5]); OSCA publishes aggregates only (Trial Court
  Statistics, January 1986 through June 2025, verified [W8]).
- **Fields:** reportedly case events and the primary and supporting judicial
  officers by name, with no numeric judge id (unverified [W3]).
- **Terms, cost, rate limits, retention:** unverified.
- **Redistribution:** aggregates `unverified`; case-level `unverified`;
  commercial `unverified`. No request is planned: the same assignment events
  originate in the clerk's case system and are requested from the pilot's
  clerk.
- **Remaining to verify:** a person reading the specification and any OSCA
  data-request process in a browser, or a rule 2.420(m) request to OSCA
  (inventory "Open questions" 1–2).

### `fl_cjdt` — FDLE Criminal Justice Data Transparency

- **Owner:** Florida Department of Law Enforcement (FDLE), from data the
  clerks, state attorneys, public defenders, regional conflict counsel, the
  Justice Administrative Commission, county detention facilities, and the
  Department of Corrections report under §900.05 — verified [W12, L14].
- **Documentation (verified 2026-10-05):** §900.05 and §943.6871, Fla. Stat.
  (2026) [L14, L15]; the program and about pages [W12, W13]; the clerk-case
  report page [W14]; rule 11C-11.001 (the data catalog, published only on
  CJNet) [L20].
- **Access method (verified):** dashboards with filtered CSV downloads of up to
  300,000 rows and "Full Data Download" archives split into files of at most 1M
  rows, anonymous HTTPS [W14]; the clerk-case archive answered a headers-only
  request with 394,175,576 bytes, last modified 2026-10-05 [W15]; an API is
  required by §943.6871(3) [L15] (its documentation is unverified).
- **Person key (verified, by statute):** FDLE "shall create a unique identifier
  for each criminal case received from the clerks of court which identifies the
  person"; it "must be the same for that person in any court case" and is
  "randomly created and may not include any portion of the person's social
  security number or date of birth" (§943.6871(1)) [L15]; "The records are
  linked by a unique identifier" [W13].
- **Fields (by statute, verified; in the public download, unverified):** case
  number; charge disposition (including "dismissal by state attorney, dismissal
  by judge"); disposition date and type; the first-appearance pretrial release
  determination with its conditions; dates of failures to appear; sentencing;
  "The sentencing judge or magistrate, or their equivalent" (§900.05(2)(j),
  (3)(a)) [L14]. No clerk item names the judge of a pretrial release or a
  disposition.
- **Update frequency:** monthly reporting and monthly dashboard updates [W13]
  (the program page says "updated once daily" [W12]; which holds is
  unverified).
- **Coverage:** adult and treat-as-adult records only, with "no personal
  identifying information" [W13]; from 2018 [W12]; every contributor onboarded
  except some county detention facilities (December 2025) [W16]; per-county
  completeness unverified.
- **Terms:** "The department may not require a license or charge a fee to
  access or receive information from the database" (§943.6871(3)) [L15]; "FDLE
  does not warrant that the records provided here are comprehensive or
  complete" [W13].
- **Cost / rate limits:** free; none stated.
- **Fields prohibited / sensitive:** the published data carries no personal
  identifying information [W13]; the identifier is hashed with the pepper like
  every source identifier; race and ethnicity, if published, go only to the
  restricted schema.
- **Retention:** none stated.
- **Provenance requirements:** each archive stored immutably with its sha256,
  the page URL, `Last-Modified`, and the retrieval time; the parser version on
  every derived row.
- **Redistribution:** aggregates `unverified`; case-level `unverified`;
  commercial `unverified` — the statute bars a license or a fee for access,
  which supports all three on its face, and request 2 asks FDLE to confirm each
  in writing (`docs/florida/requests/florida-fdle.md`).
- **Remaining to verify:** the public field list (the identifier, the
  sentencing judge, the first-appearance determination); per-county
  completeness; the cadence; the API; how sealed and expunged records leave the
  published data — request 2.

### `fl_clerks` — Florida county clerks of court

- **Owner:** each county's clerk of the circuit court, custodian of the
  county's and circuit's court records. Court records are governed by rule
  2.420 (a request "must be in writing", no reason is required, and the
  custodian decides the form) and the clerks' other records by chapter 119
  [L17, L19].
- **Candidates (2026-10-05; weighted scores out of 63 from the inventory's
  "Selection"):**

  | County (circuit) | Machine-readable route | Judge | Cross-case key | Published use terms | Cost | Score | Role |
  |---|---|---|---|---|---|---|---|
  | Hillsborough (13th) | Open weekly criminal name index files since 1988, free, no login (verified [H3, H4]) | "Presiding Court Officer" and division (verified [H6]) | `PID`, stability unverified; date of birth (verified [H5, H6]) | none published [H3] | free | 43 | **pilot** (request 1) |
  | Broward (17th) | Paid REST API under a notarized agreement (verified [B1, B9]) | judicial officer per hearing, disposition, and sentence (verified names [B5]) | `BCCN`, stability unverified; date of birth [B5] | site disclaimer prohibits republication "except as permitted by law" [B11] | $0.01–$0.10 a unit [B2] | 39 | fallback 1 (request 3) |
  | Miami-Dade (11th) | Paid daily, weekly, and monthly files kept 30 days; per-case API (verified [M1, M3, M5]) | none in the bulk files; `FiledJudge` in the per-case API [M2, M5] | `CIN` and `IDS` undefined; date of birth [M2] | case search forbids redistribution without written permission [M11] | $110 a folder a month [M1] | 36 | fallback 2 (request 4) |
  | Alachua (8th) | $30-a-month extract service over plain HTTP; no layout [A2] | undocumented | undocumented | terms "Coming soon." [A3] | $30 a month | 25 | — |
  | Palm Beach (15th) | Paid Excel and PDF reports; main site unreadable (HTTP 403) [P3, P8] | undocumented | undocumented | no redistribution without permission [P5] | per product | 23 | — |
  | Duval (4th) | "bulk data reports or recurring data subscriptions" by complex request; no layout [D2] | undocumented | undocumented | site copyright notice [D10] | $35 an hour of programming [D3] | 22 | — |
  | Pinellas (6th) | unread (Cloudflare challenge) [PI1] | unverified | unverified | unverified | unverified | 21 | — |
  | Leon (2nd) | $25–$50 monthly reports subscription; contents unverified [LE4] | undocumented | undocumented | not "for commercial or resale purposes" [LE4] | $25–$50 a month | 19 | — |
  | Orange (9th) | none ("not bulk data") [O3] | undocumented | undocumented | registered users: no commercial or resale use [O5] | per request | 18 | — |

- **Pilot fields (Hillsborough, verified as published layouts [H5, H6]):** the
  fixed-width readme lists "defendant name/alias, party ID, party code,
  defendant case number, division, sex, race, date of birth, date of filing,
  number of count, level of count, charge description, disposition code if
  available, and disposition date if available"; the pipe-delimited README adds
  `Uniform Case Number`, `Judge Name`, `Statute Violation`, `Offense Date`, and
  address and driver-licence fields, and has no party id. Which layout the
  current files carry is unverified. Sentences, bond, first appearance,
  pretrial release, and assignment history are in neither layout.
- **Update frequency (pilot):** weekly ("These files are refreshed weekly")
  [H3].
- **Fields prohibited / sensitive (pilot):** the street address and driver
  licence are never read (the parser projects them away); race and sex go only
  to the restricted schema; the name, the date of birth, and the `PID` reach the
  database only as peppered hashes. Confidential values are blank in the files
  [H6], and "Data purged from the database is also purged from the
  Circuit/County Criminal Name Index files" [H5], so every refresh retires what
  a later file no longer carries.
- **Retention:** none stated.
- **Provenance requirements:** each weekly file stored immutably with its
  sha256, the directory URL, the file's listed date, and the retrieval time;
  the parser version on every derived row.
- **Redistribution:** aggregates `unverified`; case-level `unverified`;
  commercial `unverified` for every county. Requests 1, 3, and 4 ask each clerk
  for the three rights in writing; Hillsborough publishes no use terms, and
  Broward's, Miami-Dade's, Palm Beach's, Leon's, and Orange's published terms
  restrict republication or commercial use on their face (inventory
  "Redistribution").
- **Remaining to verify:** Hillsborough's current layout, the `PID`'s
  stability, the layouts of the daily filings and sentencing archives, and the
  use terms (request 1); Broward's API terms, `BCCN`, and history depth
  (request 3); Miami-Dade's field definitions, a historical extract, and its
  terms (request 4); Palm Beach and Pinellas by a person reading their pages.

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
