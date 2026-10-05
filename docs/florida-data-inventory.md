<!-- docs/florida-data-inventory.md -->
# Florida data inventory and lawful acquisition plan

Researched on 2026-10-05 for Phase 5 Step 2 (project roadmap §5.5). This
document inventories Florida's statewide court-data sources, the law that
governs them, and nine county clerks; applies the brief's nine-step selection
process as a scored table; names the selected pilot jurisdiction and a ranked
fallback; and writes the lawful acquisition plan whose requests are drafted
under [`docs/florida/requests/`](florida/requests/) and logged in
[`docs/ROADMAP.md`](ROADMAP.md) "Florida acquisition requests".

Every fact cites a source id (`[H5]`, `[L14]`, …) listed in "Sources" at the
end with its URL and access date. A claim marked **unverified** was not
confirmed on an official page the research could read; each one says what
would confirm it. Nothing here is inferred from a neighbouring county or a news
report.

**Result.** The selected pilot is **Hillsborough County (13th Judicial
Circuit)**: its clerk publishes free, weekly, machine-readable criminal case
files back to 1988 whose published layouts carry the presiding judge, the
division, the charge statute, per-count dispositions, the date of birth, and a
person identifier. FDLE's statewide Criminal Justice Data Transparency (CJDT)
data, which by statute carries a random person identifier that is the same
across all of a person's court cases, is the pilot's companion source for
cross-case outcomes and pretrial release. The ranked fallback is **Broward
County** (a paid API that documents the judicial officer of every hearing,
disposition, and sentence), then **Miami-Dade County**. Four requests — the
Hillsborough clerk, FDLE, the Broward clerk, the Miami-Dade clerk — are drafted
for the operator to submit together.

## Purpose and criteria

The brief's Florida pilot ingests real criminal-court records from "one Florida
jurisdiction with the best lawful machine-readable data access", chosen by a
nine-step process and "with the strongest data rather than selecting solely by
population"; Broward and Miami-Dade "may be evaluated, but do not assume either
is the best pilot" (brief `<florida_pilot>`). Phase 7 §7.1 builds the connector
for the jurisdiction selected here, gated on the access this plan secures.

**How the research was done.** Only public pages were read. Each host's
`robots.txt` was read first and no disallowed path was fetched; no account was
created, no form or search submitted, no login or CAPTCHA passed, no message
sent, and no record of any person downloaded or quoted (a directory listing's
file names and sizes, and one headers-only request, were read; never a data
file's contents). These hosts could not be read by an automated client and
everything from them is **unverified**: `flcourts.gov` and its media and
Supreme Court hosts (`User-agent: *` / `Disallow: /`) [W2], the Department of
Corrections (`Disallow: /`) [W19], `flclerks.com` (a Cloudflare challenge),
the Palm Beach clerk's main site (HTTP 403) [P8], the Pinellas clerk's sites
(a Cloudflare challenge) [PI1], the current Attorney General's manual (HTTP
403; the 2014 edition was read [L19]), and Lee's bulk-data page (HTTP 403)
[X1]. A person reading those pages in a browser, or a written answer from the
office, would confirm them.

**Criteria.** Each of the brief's first eight steps is a scored criterion; the
ninth is the selection rule itself (the weighted sum decides, and population
enters nowhere). Redistribution is added as a ninth scored criterion because
the project roadmap §5.5 makes it a term of every agreement and Phase 9 §9.1
excludes any source whose answer is not verified for a tier. A lawful
cross-case person key and the redistribution rights carry the top weight,
beside access and judge attribution: Step 1 verified that Cook County has no
cross-case key, so no follow-up outcome can be measured there, and the brief's
preferred first real metric — new criminal cases after a qualifying pretrial
event — depends on one.

| Code | Brief's step | Criterion | Weight | 0 | 1 | 2 | 3 |
|------|--------------|-----------|--------|---|---|---|---|
| A | 1. Evaluate data accessibility | Lawful machine-readable route open to a non-agency requester | 3 | closed to non-agency requesters | only through a records request; no documented product | a documented product behind payment or a notarized agreement | a documented, open download or API |
| F | 2. Document fields and history | Published layout and history depth | 2 | nothing documented | product named, no layout | layout published but partial, ambiguous, or short history | published layout and ten or more years of history |
| J | 3. Confirm judge assignment | Judge attribution | 3 | no judge | undocumented | case-level judge or division (current assignment) | judicial officer per decision (hearing, disposition, sentence) |
| D | 4. Confirm charges and dispositions | Charges and dispositions | 2 | none | undocumented | dispositions documented | per-charge dispositions whose codes separate prosecutorial from judicial outcomes |
| K | 5. Confirm lawful defendant-matching fields | Cross-case person key | 3 | none | undocumented, or name only | a documented identifier whose cross-case stability is unverified, or name and full date of birth | an identifier documented as stable across a person's cases |
| R | 6. Confirm pretrial and release information | Pretrial and release decisions | 2 | none | undocumented | bond or release fields without the deciding judge | first-appearance decisions with the deciding judge |
| U | 7. Confirm follow-up event feasibility | Linking later events of the same person | 2 | none | within-case only, or short retention | later cases countywide over years, linkage unverified | linkage documented as stable statewide |
| C | 8. Estimate extraction and maintenance cost | Cost (higher is cheaper) | 1 | prohibitive or unbounded | unknown price or per-request programming | paid at a documented price | free |
| X | (project roadmap §5.5) | Redistribution rights on the face of the published terms | 3 | published terms restrict republication or commercial use | no published terms on use | a statute or published license permits use | a written grant of all three rights |
| — | 9. Select by data strength, not population | The weighted sum; population is not scored | — | | | | |

The weights sum to 21, so the maximum is 63. A score reflects what the cited
pages document today; an answer to a request changes it, and the plan re-scores
on every answer ("Acquisition plan").

## Statewide sources

### OSCA's JDMS and the Uniform Case Reporting specification

- **Basis (verified).** "The Supreme Court shall develop a uniform case
  reporting system" and a clerk who "willfully fails to report to the Supreme
  Court as directed by the court … shall be guilty of misfeasance in office"
  (§25.075) [L9]. Rule 2.245(a): "The clerk of the circuit court shall report
  the activity of all cases before all courts within the clerk's jurisdiction
  to the supreme court in the manner and on the forms established by the office
  of the state courts administrator" [L17].
- **Everything else is unverified** because every `flcourts.gov` host disallows
  generic crawlers [W2]; the following come from search-engine listings of the
  official URLs, not from text read: the JDMS page [W1]; Administrative Order
  AOSC16-15 (April 2016), directing clerks to "electronically transmit data to
  the Office of the State Courts Administrator directly through an approved
  interface" [W6]; the UCR Data Collection Specification, latest version found
  1.4.2 (November 2020) [W3], which reportedly tracks "case initiation,
  closure, and post-judgment activity" and "case assignment events, including
  the primary and supporting judicial officers", reporting the primary judicial
  officer by name (element `evtPrimOfc`), not by a numeric judge id; and the UCR
  web-service specification and FAQ, which reportedly require a user name,
  password, and a firewall-registered IP address issued per county ("you will
  need to request your county's user credentials from OSCA") [W4, W5].
- **Access for a non-agency requester: none found.** UCR is a submission
  channel from clerks to OSCA; no OSCA page, form, or policy for an outside
  researcher's case-level request was found. The general route is a written
  request under rule 2.420(m) [L17]. Because the assignment events UCR reports
  originate in each clerk's case maintenance system, this plan asks the pilot's
  clerk for them directly rather than OSCA ("Open questions" 1).
- **Published OSCA data (verified).** The Trial Court Statistics search
  [W8] states "Statistics available for January 1986 through June 2025" and
  offers a statistic, a jurisdiction, and a month range — no judge and no case
  selector; it is aggregate by design (its output was not requested).
  Aggregate only, so it is reference material, not a pilot source.

### The clerks' statewide system (CCIS)

- **Statute (verified).** "All clerks of the circuit court shall participate in
  the Comprehensive Case Information System of the Florida Association of Court
  Clerks and Comptrollers, Inc., and shall submit electronic case data to the
  system" (§28.2405) [L8]; CCIS records are "the property of the State of
  Florida" with the clerk as custodian (§28.24(13)(e)1.) [L7].
- **Closed to non-government users (verified).** The CCIS login page reads
  "FOR OFFICIAL USE ONLY" and "By logging in, you are affirming that you have an
  official need to review the court case data within" [W9]. The FCCC's CCIS
  Court Records Access Policy (amended through 2021-06-25) says "CCIS has been
  closed to non-government users such as attorneys, the media, and the public"
  and lists "Commercial Purchasers of Bulk Records (Role 11)" among the "User
  Roles that will NOT be implemented" [W10]; a 2018 House staff analysis says
  "CCIS is not publicly available" [W11]. Whether the 2021 policy is still in
  force is **unverified** (`flclerks.com` could not be read). Excluded.

### FDLE Criminal Justice Data Transparency (CJDT)

- **What the clerks report (verified).** Section 900.05(3) requires each clerk
  to report to FDLE "on a monthly basis", "for each criminal case", among
  others: "1. Case number"; "10. Charge disposition"; "11. Disposition date and
  disposition type"; "12. … Identifying information, including name, known
  aliases, date of birth, race, ethnicity, and gender"; "14. Information related
  to bail or bond and pretrial release determinations, including the dates of
  any such determinations: a. Pretrial release determination made at a first
  appearance hearing that occurs within 24 hours of arrest, including any
  monetary and nonmonetary conditions of release"; "15. … b. Date of any failure
  to appear in court"; "17. Information related to sentencing"; and "18. The
  sentencing judge or magistrate, or their equivalent" [L14]. "Charge
  disposition" is defined to include "dismissal by state attorney, dismissal by
  judge" (§900.05(2)(j)) [L14]. No clerk item names the judge of a pretrial
  release determination or of a disposition.
- **A lawful cross-case person key (verified, by statute).** "The department
  shall create a unique identifier for each criminal case received from the
  clerks of court which identifies the person who is the subject of the
  criminal case. The unique identifier must be the same for that person in any
  court case and used across local and state entities for all information
  related to that person at any time. The unique identifier shall be randomly
  created and may not include any portion of the person's social security
  number or date of birth" (§943.6871(1)) [L15].
- **Publication (verified).** FDLE "shall publish datasets in its possession in
  a modern, open, electronic format that is machine-readable" and "searchable,
  at a minimum, by data elements, county, circuit, and unique identifier"
  (§900.05(4)) [L14]; the database is "readily accessible through an
  application program interface" and "The department may not require a license
  or charge a fee to access or receive information from the database"
  (§943.6871(3)) [L15]. Information confidential when collected "remains
  confidential and exempt when reported" (§900.05(6)) [L14].
- **What FDLE publishes (verified).** "The person-based CJDT data includes only
  adult and treat-as-adult records, and contains no personal identifying
  information. The records are linked by a unique identifier created for each
  criminal case to ensure every subject of the case is the same for all
  information related to that person at any time"; the data "is also available
  for download as a filtered dataset directly from the dashboard or in full from
  a Full Data Download link"; "Contributing agencies submit data to FDLE on a
  monthly basis, and FDLE makes monthly updates to the CJDT dashboards"; "FDLE
  does not warrant that the records provided here are comprehensive or
  complete" [W13]. "CJDT records go only as far back as the inception of the
  initiative in 2018" and the contributors are the clerks, county detention
  facilities, the Department of Corrections, the Justice Administrative
  Commission, public defenders, regional conflict counsel, and state attorneys
  [W12]. The clerk page offers full unfiltered CSV reports "separated into
  multiple files not to exceed 1M rows" [W14]; a headers-only request for the
  clerk-case archive returned 394,175,576 bytes, last modified 2026-10-05 [W15].
  The December 2025 CJJIS Council minutes record that "all contributors are
  fully onboarded, with the exception of some of the county detention
  facilities" [W16].
- **Unverified.** Whether the public clerk-case download carries the unique
  identifier, the sentencing judge, and the first-appearance determination as
  columns: the data catalog the rule names sits on CJNet
  (`flcjn.net`, not publicly resolvable) [L20], and no data file was opened.
  Per-county completeness of clerk reporting, and the cadence ("updated once
  daily" on the program page [W12] against "monthly" on the about page [W13]).
  Request 2 asks for all of it.
- **Role in the plan.** CJDT is not a jurisdiction but it covers every county:
  it is the pilot's companion source for the cross-case key, the
  first-appearance release determination, failures to appear, and later cases
  anywhere in Florida.

### Other state sources considered

- **FDLE criminal history (CCH)** — per-name searches at "$24.00" [W17],
  fingerprint-based, and it "does not include records involving a notice to
  appear, direct file, or sworn complaint where no jail booking has taken
  place" [W18]; "Criminal justice information provided by the Department of Law
  Enforcement shall be used only for the purpose stated in the request"
  (§943.053(4)) [L16]. No bulk channel for non-criminal-justice requesters was
  found (**unverified**). Not a pilot source.
- **Department of Corrections offender database (OBIS)** — a public-records
  page for a downloadable database is listed in search results but the host
  disallows crawlers [W19]; its fields, cadence, and terms are **unverified**.
  FDLE's CJDT already republishes the Department's contributions [W12]. A
  candidate for incarceration events in Phase 7 if CJDT's are insufficient.

### Statewide scores

| Source | A | F | J | D | K | R | U | C | X | Weighted (of 63) | Evidence |
|--------|---|---|---|---|---|---|---|---|---|------------------|----------|
| FDLE CJDT | 3 | 2 | 1 | 2 | 3 | 2 | 3 | 3 | 2 | 48 | https://www.fdle.state.fl.us/cjab/cjdt/about-cjdt-data ; https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0900-0999/0943/Sections/0943.6871.html ; https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0900-0999/0900/Sections/0900.05.html |
| OSCA UCR | 0 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 18 | https://www.flcourts.gov/Services/court-services/judicial-data-management-services-jdms (unread; robots) ; https://trialstats.flcourts.org/ |
| FCCC CCIS | 0 | — | — | — | — | — | — | — | — | excluded | https://www.flccis.com/ccis/ ; https://cdn.ymaws.com/www.flclerks.com/resource/resmgr/technologysubcommittee/ccis/asm_v9/ccis_court_records_access_po.pdf |

CJDT's judge score is 1 because the statute requires only the sentencing judge
and its presence in the public data is unverified; its K is 3 because the
statute documents stability across cases, and request 2 verifies the column.

## Legal framework

- **The constitutional right (verified).** "Every person has the right to
  inspect or copy any public record made or received in connection with the
  official business of any public body … This section specifically includes the
  legislative, executive, and judicial branches of government" (art. I, §24(a));
  exemptions only "by general law passed by a two-thirds vote of each house"
  that states "with specificity the public necessity" (§24(c)) [L1].
- **Chapter 119 governs agencies; rule 2.420 governs court records.** "It is
  the policy of this state that all state, county, and municipal records are
  open for personal inspection and copying by any person" (§119.01(1)) [L2]; a
  custodian "must acknowledge requests to inspect or copy records promptly and
  respond to such requests in good faith" (§119.07(1)(c)) [L4]; public records
  include "data processing software, or other material, regardless of the
  physical form" (§119.011(12)) [L3]. Chapter 119 does not require a written
  request ("Public records requests do not have to be made in writing unless
  specifically required by statute", FDLE [W20]), and the Attorney General's
  manual
  (2014 edition; the current edition could not be read) says "The requestor is
  not required to explain the purpose or reason for a public records request"
  [L19]. The same manual: "the courts have consistently held that the judiciary
  is not an 'agency' for purposes of Ch. 119" and, when the clerk acts as part
  of the judicial branch, "access to the judicial records under the clerk's
  control is governed exclusively by Fla. R. Jud. Admin. 2.420" [L19]. Rule
  2.420(b)(2) includes "the clerk of court when acting as an arm of the court"
  in the judicial branch, and rule 2.420(m)(1) says "Requests for access to
  judicial branch records must be in writing and must be directed to the
  custodian. … The reason for the request is not required to be disclosed";
  under (m)(2) "The custodian must determine the form in which the record is
  provided. If the request is denied, the custodian must state in writing the
  basis for the denial" [L17]. The rule sets no deadline. FDLE is an executive
  agency, so Chapter 119 applies to request 2; the three clerk requests cite
  both rule 2.420(m) and Chapter 119 (for the clerks' non-court records).
- **Rule 2.420's confidential categories (verified) [L17].** Subdivision (c)
  lists ten classes of confidential judicial-branch records, including "(7) All
  records made confidential under the Florida and United States Constitutions
  and Florida and federal law" and "(8) All records presently deemed to be
  confidential by court rule … by Florida Statutes". Under (d)(1)(B) the clerk
  "must maintain as confidential" information made confidential by twenty-five
  listed statutes, among them "(iii) Social Security, bank account, charge,
  debit, and credit card numbers", "(xvi) Grand jury records", "(xviii) Juvenile
  delinquency records. §§ 985.04(1), 985.045(2)", "(xx) Complete presentence
  investigation reports", and "(xxiv) a court record in the case giving rise to
  the Department of Law Enforcement's sealing of a criminal history record.
  § 943.0595". Court-ordered sealing and expunction (§§943.059, 943.0585) are
  not on the list; rule 3.692 governs those court records (below).
- **Rule 2.425 (verified) [L17].** Filers limit designated sensitive
  information to "(1) the initials of a person known to be a minor; (2) the year
  of birth of a person's birth date", but criminal proceedings except, among
  others, "(D) a charging document and an affidavit or other documents filed in
  support of any charging document" and "(I) information needed to complete a
  sentencing scoresheet", and the rule excepts "(9) information used by the
  clerk for case maintenance purposes". So a full date of birth in a clerk's
  criminal case data is not barred by rule 2.425, and no listed statute makes
  it confidential; it is a lawfully obtainable matching field. The project
  hashes it with the pepper on ingest and never publishes it
  (`docs/ENTITY_RESOLUTION.md`).
- **Sealing and expunction (verified).** A sealed criminal history record "is
  confidential and exempt" and available only to the listed persons
  (§943.059(6)(a)) [L11]; an expunged one "must be physically destroyed or
  obliterated by any criminal justice agency having custody of such record"
  (§943.0585(6)(a)) [L10]. A criminal history record is a "nonjudicial record"
  (§943.045(6)) [L21]; for court records, "The courts of this state have
  jurisdiction over their own procedures, including the maintenance,
  expunction, and correction of judicial records" (§943.0585(4)(a)) [L10]. On
  automatic sealing
  "the clerk of the court must automatically keep the related court record …
  confidential and exempt" (§943.0595(3)(b)) [L12]. Rule 3.692(d)(2) has the
  clerk "remove from the official records of the court, excepting the court
  file, all entries and records subject to the order" and "seal the entries and
  records … in a nonpublic index" [L18]. Whether a private holder of a record
  later sealed or expunged must remove it is not addressed in the text read
  (**unverified**; counsel, Phase 6 §6.4); the plan removes such records anyway
  (below).
- **Juvenile records (verified).** Information obtained under chapter 985
  "is confidential and exempt from s. 119.07(1)" except, among others, the name
  and crime of a child charged with or found to have committed a felony
  (§985.04(1)(a), (2)(a)) [L13]. The requests ask for juvenile records to be
  excluded entirely; CJDT publishes "only adult and treat-as-adult records"
  [W13].
- **Court-file exemptions (verified).** Social security, bank account, and card
  numbers are kept confidential "without any person having to request
  redaction" (§119.0714(2)(e)1.) [L5].
- **Fees (verified).** Absent a fee set by law, "Up to 15 cents per one-sided
  copy"; for "extensive use of information technology resources or extensive
  clerical or supervisory assistance", "a special service charge, which shall be
  reasonable and shall be based on the cost incurred" (§119.07(4)(a), (d)) [L4].
  Clerks charge "1.00" per page for copies of court records, "2.00" per year
  searched, and, "For furnishing an electronic copy of information contained in
  a computer database: a fee as provided for in chapter 119" (§28.24(6)(a),
  (21)(a), (29)) [L7]; rule 2.420(m)(3) carves copies of court records out of
  §119.07's fees [L17]. A bulk extract is therefore priced as a special service
  charge; every request asks for an estimate first and authorizes no charge.
- **Bulk electronic court records.** Rule 2.420(a) puts "Access to all
  electronic and other court records" under the Supreme Court's "Standards for
  Access to Electronic Court Records and Access Security Matrix" [L17]; the
  rule itself has no bulk provision. The Standards' role for "Commercial
  Purchasers of Bulk Records" (role 11), access "by written notarized
  agreement", is **unverified** statewide (the current order, AOSC24-32 of June
  2024, could not be read [W7]) and verified as Broward's practice:
  "Commercial Purchasers of Bulk Records may gain secure access through username
  and password by written notarized agreement" [W22]. Section 28.2221 covers
  official records and has no bulk provision for court records [L6].
- **Transparency data (verified).** Sections 900.05 and 943.6871 (above) make
  CJDT a statutory open dataset that FDLE may not license or charge for [L14,
  L15].

## County candidates

Nine county clerks were researched; six others were looked at briefly (end of
this section). Every county clerk is the custodian of its county's and
circuit's criminal court records.

### Hillsborough County (13th Circuit, Tampa)

- **Access (verified).** The clerk's "Public Data Files" page links an open
  HTTPS directory, `publicrec.hillsclerk.com`, with no login [H3]. "Criminal
  Name Index … These files are refreshed weekly and include all Circuit and
  County Criminal cases filed after January 1988 or that have had any court
  action since 1988 to the present date. The files provide an index of
  defendant names for all Circuit and County Criminal cases, both active and
  disposed" [H3]. On 2026-10-05 the directory listed the pipe-delimited files
  (one per initial letter of the surname and one non-alphabetic: 27 county
  files, and 26 circuit files because no circuit `T` file was present) and two
  fixed-width files of 1,140,106,041 and 682,593,970 bytes, all dated
  2026-09-29 [H4]. Also published: daily criminal filings
  (`CriminalFiling_YYYYMMDD.csv`, a rolling two weeks, no layout) [H7], daily
  "SentenceGuidelines" archives (no layout) [H8], court calendars by division
  and hearing type (PDF) [H9], and a yearly criminal traffic index from 2003
  [H3].
- **Fields (verified, two layouts).** The fixed-width readme (updated
  2015-07-27): "Each data record contains the following items: defendant
  name/alias, party ID, party code, defendant case number, division, sex, race,
  date of birth, date of filing, number of count, level of count, charge
  description, disposition code if available, and disposition date if
  available"; "PID — This field defines the identification number used to
  access person on-line"; "Each Judge is assigned to preside over a specific
  letter division"; "Data purged from the database is also purged from the
  Circuit/County Criminal Name Index files"; "This record layout is subject to
  change without notification" [H5]. The pipe-delimited README (updated
  2019-06-17): "Files are in pipe delimited format and contain column headings.
  No value will be displayed between the respective pipe fields for
  confidential or null values"; columns include `Uniform Case Number`,
  `Division`, `Judge Name` ("Last Name, First Name of Presiding Court Officer"),
  `Date Filed`, `Current Status`, `Date of Birth`, `Count Number`,
  `Count Level and Degree`, `Statute Violation`, `Charge Description`,
  `Offense Date`, `Disposition Code`, `Disposition Date`, and also `Race`,
  `Sex/Gender`, a party address, and driver-licence fields — but no party id
  [H6]. The fixed-width readme's disposition codes separate prosecutorial from
  judicial outcomes, for example "NT - NOLLE PROSSED FOR PURPOSE OF PRE TRIAL
  DIVERSION" and "DISMISSED SPEEDY TRIAL" [H5]. Which layout the current files
  follow is **unverified**.
- **Not documented:** sentences, bond, first appearance, pretrial release, the
  judge of each decision, and assignment history. The judge field names the
  case's "Presiding Court Officer" [H6]; the criminal traffic index defines the
  same column as the officer "currently assigned" [H10], so for a reassigned
  case it need not be the judge who decided.
- **History and cadence (verified).** 1988 to date, refreshed weekly [H3].
- **Limits.** Purged data leaves the files [H5]; confidential values are blank
  [H6]; the layout may change without notice [H5].
- **Terms.** The data page states no license or use terms [H3]; the site
  disclaimer says only "Unauthorized attempts to upload information or change
  information on this website is prohibited" [H13]. **Unverified:** any use or
  redistribution terms.
- **Cost (verified).** Free (an open directory); copies otherwise "$1.00" per
  page [H2].
- **Effort.** Low to fetch (about 3.1 GB per weekly refresh across the four
  file sets [H4]); moderate to parse (two layouts, fixed width); the
  sensitive columns are dropped at parse (address, driver licence) or written
  only to the restricted schema (race, sex).
- **Public-records route (verified).** "Requests for court records should be
  emailed directly to PublicRecords@hillsclerk.com"; mail to the clerk at "601
  E. Kennedy Blvd. 13th floor Tampa, FL 33602"; an online portal is also offered
  [H1].
- **Case search (verified).** HOVER: "An anonymous user may view
  non-confidential/sealed name indexes, progress dockets and redacted images for
  cases except Family Law, Probate and Juvenile cases" [H12]; "HOVER is
  available to the attorneys of record and self-represented litigants (Pro Se)
  on a case, registered users and anonymous users" [H11]. Not used: the files
  above make a case search unnecessary.
- **Lawful matching.** The `PID` is documented, but whether it is the same for
  one person across cases is **unverified**; the date of birth and name are in
  the data and lawfully obtainable (Legal framework). Countywide linkage over
  thirty-eight years is feasible on either; CJDT's statutory identifier adds
  statewide linkage. Request 1 asks whether the PID is stable.

### Broward County (17th Circuit, Fort Lauderdale)

- **Access (verified).** "Is bulk court data available through this website?
  A. Yes, all Commercial Purchasers of Bulk Records can obtain access to all
  non-confidential records for a cost after subscribing to the Commercial Data
  Access (API) Service and submitting the required notarized registration
  agreement form" [B9]. The API "is for high volume customers who want to
  automate their access to court records filed in the 17th Judicial Circuit",
  covers felony and traffic-and-misdemeanor cases, and offers methods for "Case
  Summary / Party information / Case Events / Hearings / Related Cases / Arrests
  / Charges / Warrants / Bonds / Criminal Pleas, Dispositions and Sentencing /
  Judgments" [B1]; "The API is a REST style interface. Response content can be
  XML or JSON" over HTTPS with an API key [B4]. Search by filing date is limited
  to ranges that "cannot exceed 31 days" and pages of 200 [B5, B4].
- **Fields (verified as documented names) [B5].** `Judge_Name`,
  `Magistrate_Name`, hearing `Judicial_Officer`, `Disposition_Judicial_Officer`,
  a sentence `Judge`, `PleaList`, `DispositionList`, `SentenceList`, bonds
  (`Posted_Date`, `Bond_Type`, `Bond_Amount`, `BondStatusList`), warrants with
  `Hold_WithOut_Bail_Bond`, arrests with `OBTS_Number`, party `Birth_Date`,
  `Race`, `Gender`, and `BCCN` ("BCCN - Broward County Control Number"), which
  is searchable as a "Party ID" [B6]. Whether each is populated for criminal
  cases is **unverified**.
- **History and cadence.** Real time ("frequently being updated throughout the
  day") [B4]; e-filing mandatory since 2014-01-06 and "All court records filed
  since this date are available in electronic format" [B11]; how many years the
  API returns is **unverified**. Prepared daily, weekly, and monthly reports
  also exist [B9]; their catalog sits on a robots-disallowed path
  (**unverified**).
- **Terms (verified).** "The User is expressly prohibited from reproducing,
  publishing online, selling, reselling or otherwise disseminating data or
  information accessed pursuant to this Disclaimer, except as permitted by law.
  The information accessed is not intended or permitted to be used for
  commercial resale, except as permitted by law" [B11]. The API terms and the
  notarized agreement sit behind a login (**unverified**).
- **Cost (verified).** Units at "$0.10" falling to "$0.01" by volume tier,
  non-refundable, expiring after 18 months [B2]; a search costs 2 units and a
  case-detail method 1 [B3]; code lists are "free of charge" [B5].
- **Effort.** Moderate: about eight detail calls per case, a backfill by
  31-day filing windows, a notarized agreement.
- **Public-records route (verified).** "Custodian of Public Records … General
  Counsel PublicRecords@BrowardClerk.org" [B11]; court-record copies through the
  Archives division, "up to 2 weeks" [B10]; API questions to
  `PublicAccessHelpDesk@browardclerk.org` [B1].
- **Case search (verified).** Anonymous, behind a Cloudflare Turnstile widget,
  "limited to the first 200 results" [B12]; not used.
- **Lawful matching.** `BCCN` is documented as a control number and a party
  search key, but whether it identifies one person across cases is
  **unverified**; the date of birth is a documented field. Request 3 asks.

### Miami-Dade County (11th Circuit, Miami)

- **Access (verified).** "The available data files are updated on daily,
  weekly, and monthly bases (files are available for 30 days). There are fees
  associated with accessing each of the folders" [M1]; registration requires
  "a notarized form confirming identity" and a notarized "Data Download or
  Custom Public Access Request form" [M1]. A per-case criminal API takes only a
  case number [M5].
- **Fields (verified) [M2, M5].** The criminal layout (revised 2026-03-23)
  documents a daily file of filed and closed cases with `CIN`, `IDS`, names,
  `DOB`, `Race`, `Sex`, address, case numbers, a four-character `Section`,
  arrest, filing, and close dates, offense, disposition code and date, and
  sentence type and duration; a daily nolle prosequi file; and weekly code
  tables whose disposition table carries `PROS Action` and `COURT Action` flags
  [M2]. No bulk file has a judge, bond, or first-appearance field [M2]. The
  per-case API returns `FiledJudge`, `AltJudge`, bond and release fields, and
  charges with dispositions and sentences [M5]. The meanings of `CIN`, `IDS`,
  `Section`, and the action flags are **unverified**.
- **History and cadence (verified).** Daily, weekly, and monthly files kept 30
  days ("Files are automatically removed from the folder after 30 days") [M3];
  back data only by a public-records request [M1].
- **Terms (verified).** The case-search notice: "you may not reproduce,
  retransmit, redistribute, upload or post any part of this website … without
  prior written permission from the Clerk and Comptroller's Office" [M11]; the
  registration agreement as displayed has no redistribution clause [M6]; the
  notarized form's terms are **unverified**.
- **Cost (verified).** "$110.00 per month" per folder and "$0.20 per unit, one
  unit per request" for the API [M1].
- **Effort.** Moderate to high: a daily pull before the 30-day expiry, a
  per-case API call for the judge, a separate historical extract.
- **Public-records route (verified).** "Records Management, Miami-Dade County
  Clerk of Courts, P.O. Box 14695, Miami, Fl. 33101 Email:
  cocpubreq@miamidadeclerk.gov" [M7] (the blank form names
  `COCPUBREQ@miamidade.gov` [M8]); "All requests will be Administratively Closed
  after sixty (60) days for nonpayment or nonresponse" [M8].
- **Lawful matching.** `CIN` and `IDS` exist but are undefined; a county IT
  document expands "Criminal Identification Number (CIN)" for the arrest-form
  system [M13], not proven to be the clerk's field. The date of birth is in the
  daily file. Request 4 asks.

### Palm Beach County (15th Circuit, West Palm Beach)

- **Access (verified on the application host).** ClerkCart sells "Daily,
  weekly and monthly data from the Clerk of the Circuit Court & Comptroller's
  court computer system" [P1] in "Microsoft Excel or PDF format" [P4], including
  daily criminal cases, daily criminal dispositions, weekly disposed and
  dismissed charges, and monthly felony and misdemeanor reports [P3]; "the
  development of new specialized reports in Clerk Cart has been suspended" [P4].
  Product layouts and prices sit behind form postbacks (**unverified**).
- **Fields.** Not documented for the products. The free eCaseView search shows
  "Charges / Sentences", "Court Events", and "Arrests / Bonds" tabs [P6] but
  uses Google reCAPTCHA and says "Do not use third‑party interface programs to
  access eCaseView" [P7].
- **Terms (verified).** "you may not reproduce, retransmit, redistribute, upload
  or post any part of this website … without prior written permission from the
  Clerk" [P5].
- **Cost (verified).** "Costs vary by product"; custom programming "a minimum
  charge of $60 per hour" with an estimate first [P4].
- **Public-records route.** The clerk's main site returned HTTP 403 to every
  automated request [P8]; its contacts are **unverified**.
- **Lawful matching.** No identifier documented; date of birth is a
  registered-user search field only [P6].

### Alachua County (8th Circuit, Gainesville)

- **Access (verified).** A "Bulletin Board Service (BBS)" delivers "database
  extracts" of "Civil, Criminal and Civil Traffic Cases" and "Alachua County
  Jail Booking Logs and Arrest Report", "daily, weekly or monthly", at "$30 per
  month" [A2]. It is served over plain HTTP only (port 443 refused), which the
  project's HTTPS-only client rejects; its library requires sign-in.
- **Fields.** No layout published (**unverified**).
- **Terms (verified).** The BBS terms page reads "Coming soon." [A3].
- **History (verified).** "Criminal: December 2005" for online documents; "You
  will not be able to do online research for many closed criminal records prior
  to 1990" [A4].
- **Public-records route (verified).** "osr@alachuaclerk.org" or the Public
  Records Custodian, 201 E University Ave, Gainesville [A1].
- **Lawful matching.** Undocumented.

### Duval County (4th Circuit, Jacksonville)

- **Access (verified).** The complex-request policy covers "requests for
  records that contain complex or historical information or those that call for
  bulk data reports or recurring data subscriptions"; "Email submissions are
  preferred and can be sent to Public.Info@duvalclerk.com" [D2]. No product,
  format, or layout is published (**unverified**).
- **Cost (verified).** "A special service charge will be warranted if the
  nature or volume of the public records requested … requires more than 30
  minutes"; "For estimates exceeding $50, an advance deposit of 50 percent";
  "Programmer Time: $35.00 per hour" [D3].
- **Pretrial (verified existence).** The Pretrial Release Register required by
  §907.043 is prepared by the Sheriff's Office and published by the clerk [D7];
  its format is **unverified** (it lists defendants and was not opened).
- **Case search (verified).** CORE presents a reCAPTCHA challenge "pursuant to
  a directive issued by the Florida Court Technology Commission" [D9].
- **Terms.** "Copyright in the Material on this Web Site is owned by the Duval
  County Clerk of Court" [D10]; data terms **unverified**.
- **Lawful matching.** A "Jail offender number" is named in the felony FAQ
  [D6] but not as a data field (**unverified**); the registration agreement's
  "Party ID number" is a login credential, not a person key [D5].

### Leon County (2nd Circuit, Tallahassee)

- **Access (verified).** A reports subscription at "a monthly rate of $25 or
  $50", "an additional $200 per year" for historical data, programming "$75 per
  hour" [LE4]; which reports exist and whether criminal reports are among them
  is **unverified** (the reports host returned 403).
- **Terms (verified).** "To not use or permit others to use the information
  obtained from this site for commercial or resale purposes" [LE4]; the site
  says information may be copied "provided that it is used solely for personal
  information" [LE6].
- **Public-records route (verified).** Written requests to the custodian at 301
  South Monroe Street [LE2]; fees and deposits [LE1, LE3].
- **Lawful matching.** Undocumented.

### Orange County (9th Circuit, Orlando)

- **Access (verified).** "The my eClerk system is intended for accessing
  documents and information on individual cases, not bulk data" [O3]; anonymous
  searches require a CAPTCHA "before each search request" [O4]. Whether a bulk
  extract is available by request is **unverified**.
- **Terms (verified).** The registered-user agreement: "To not use or permit
  others to use the information obtained from this site for commercial or
  resale purposes" [O5].
- **History (verified).** "Online docket information is available for most
  cases filed from approximately 1990 to present" [O4].
- **Public-records route (verified).** An online form, or mail to 425 N. Orange
  Ave., "up to 10 business days"; copies "$1.00" per page [O1, O2].
- **Lawful matching.** Undocumented.

### Pinellas County (6th Circuit, Clearwater)

- Both clerk hosts answered with a Cloudflare challenge, and the readable
  `robots.txt` of the `.org` domain disallows `/Portals/` (where its fee
  schedule sits) and blocks AI crawlers by name [PI1, PI2]. Nothing was read;
  every criterion is **unverified**. A person reading the clerk's pages in a
  browser, or a written request, would confirm whether a criminal bulk product
  exists.

### Looked at briefly

Lee (a bulk-data page answered HTTP 403 [X1]); Manatee (a daily "New Cases
Filed Today" list, no bulk criminal product documented [X2]); Seminole (online
search and a Pretrial Release Register link, no bulk product in its sitemap
[X3]); Sarasota (its `robots.txt` disallows the court-records paths; none read
[X4]); Polk (its `robots.txt` timed out; not researched). None is scored.

## Selection

Scores follow the criteria table in "Purpose and criteria"; the weighted sum is
`3A + 2F + 3J + 2D + 3K + 2R + 2U + C + 3X` (maximum 63).

| Rank | County | A | F | J | D | K | R | U | C | X | Weighted | Evidence |
|------|--------|---|---|---|---|---|---|---|---|---|----------|----------|
| 1 | Hillsborough | 3 | 2 | 2 | 3 | 2 | 1 | 2 | 3 | 1 | 43 | https://www.hillsclerk.com/records-and-reports/public-data-files ; https://publicrec.hillsclerk.com/Criminal/name_index/hccc1020/readme.txt ; https://publicrec.hillsclerk.com/Criminal/name_index/Circuit/README.pdf |
| 2 | Broward | 2 | 2 | 3 | 2 | 2 | 2 | 2 | 2 | 0 | 39 | https://www.browardclerk.org/Web2/Services/AboutAPI ; https://www.browardclerk.org/Web2/Broward%20Clerk%20Web%20API%20Service%20Technical%20Documentation%20-%20Request%20Parameters.pdf ; https://www.browardclerk.org/GeneralInformation/Miscellaneous |
| 3 | Miami-Dade | 2 | 2 | 2 | 3 | 2 | 2 | 1 | 2 | 0 | 36 | https://www.miamidadeclerk.gov/clerk/commercial-data-services.page ; https://www.miamidadeclerk.gov/resources-clerk/library/FTP_File_Layouts/FTP_Layout_Criminal.pdf ; https://www2.miamidadeclerk.gov/Developers/Help/Api/GET-api-Criminal_CaseNumber_AuthKey |
| 4 | Alachua | 2 | 1 | 1 | 1 | 1 | 1 | 1 | 2 | 1 | 25 | https://alachuacounty.us/Depts/Clerk/PublicRecords/pages/courtrecords.aspx ; http://clerk-bbs.alachuaclerk.org/ (HTTP only) |
| 5 | Palm Beach | 2 | 1 | 1 | 2 | 1 | 1 | 1 | 1 | 0 | 23 | https://appsgp.mypalmbeachclerk.com/clerkcart/ProductList.aspx ; https://appsgp.mypalmbeachclerk.com/eCaseView/ |
| 6 | Duval | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 2 | 1 | 22 | https://www.duvalclerk.com/getmedia/92cdf29c-19ad-4fab-9bf2-fcfc009c2a09/Cost_Recovery_Policy2_ADA_Compliant.pdf ; https://www.duvalclerk.com/services/public-information |
| 7 | Pinellas | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 21 | https://www.mypinellasclerk.org/robots.txt (site unread: challenge) |
| 8 | Leon | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 2 | 0 | 19 | https://leonclerk.com/uploads/2026/03/reports_subscription.pdf ; https://leonclerk.com/privacy-policy/ |
| 9 | Orange | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 18 | https://myeclerk.myorangeclerk.com/Home/FAQ ; https://myeclerk.myorangeclerk.com/PublicDocuments/Access%20Agreement.pdf |

**Selected pilot: Hillsborough County, with FDLE CJDT as its companion
source.** Hillsborough is the only candidate whose criminal case data is
published openly, free, and machine-readably, with documented layouts that
carry the presiding judge and division, statute-level charges, per-count
dispositions that separate nolle prosequi from judicial dismissal, a person
identifier, and the date of birth, over thirty-eight years refreshed weekly. Its
gaps — no sentences, no pretrial decisions, the judge of the division rather
than the judge of each decision, and no published use terms — are what request
1 asks the clerk to fill, and CJDT (scored 48 on its own) covers the cross-case
key, the first-appearance release determination, failures to appear, sentences
with the sentencing judge, and later cases anywhere in the state. Together they
make the brief's preferred first real metric measurable at the court level from
the first ingest; its judge-level form needs request 1's first-appearance
judicial officer, without which the pretrial family is not attributable to a
judge (Phase 5 Step 5's `NotAttributable` rule, written for Cook County's bond
decisions).

**Ranked fallback.** (1) **Broward** — the richest judge attribution of any
candidate (a judicial officer on every hearing, disposition, and sentence) and
bond and arrest detail, held back by a notarized paid agreement and published
terms that prohibit republication "except as permitted by law"; a written grant
of the three rights would raise it to 48, above Hillsborough. (2)
**Miami-Dade** — documented layouts and dispositions with prosecutorial and
court action flags, but no judge in any bulk file, a 30-day retention, and
restrictive site terms. Population plays no part in either ranking.

**What would change the ranking.** A written answer moves a score and the table
is re-scored the day it arrives: Hillsborough rises to 46 if it can supply the
judge of each decision, and stays first if its PID is not cross-case (the date
of birth and CJDT keep K at 2); Broward overtakes Hillsborough if it grants the
three rights while Hillsborough's terms stay unknown; any clerk's restrictive
answer on derived aggregates removes it from the pilot ("Acquisition plan").

## Acquisition plan

**Requests (all drafted 2026-10-05, sent together by the operator).**

| # | Request file | Recipient | Published contact | Legal basis | Purpose in the plan |
|---|--------------|-----------|-------------------|-------------|---------------------|
| 1 | [`hillsborough-clerk.md`](florida/requests/hillsborough-clerk.md) | Hillsborough County Clerk of the Circuit Court & Comptroller, records custodian | PublicRecords@hillsclerk.com [H1] | rule 2.420(m); ch. 119 | The pilot: current layouts, PID stability, an extract with assignment history, decision-level judges, sentences, and pretrial decisions; use terms |
| 2 | [`florida-fdle.md`](florida/requests/florida-fdle.md) | Florida Department of Law Enforcement, Office of Open Government | publicrecords@fdle.state.fl.us [W20]; an online portal is also offered [W21] | ch. 119 | The companion: the CJDT public data catalog, the identifier and judge columns, per-county completeness, the API, removals |
| 3 | [`broward-clerk.md`](florida/requests/broward-clerk.md) | Broward County Clerk of Courts, Custodian of Public Records | PublicRecords@BrowardClerk.org [B11] | rule 2.420(m); ch. 119 | Fallback 1: the API terms and agreement, BCCN, history depth, a historical extract |
| 4 | [`miami-dade-clerk.md`](florida/requests/miami-dade-clerk.md) | Miami-Dade County Clerk of the Court and Comptroller, Records Management | cocpubreq@miamidadeclerk.gov [M7] | rule 2.420(m); ch. 119 | Fallback 2: a historical extract with judge and section, the field meanings, the agreement terms |

**Every request** names the fields, the years (cases filed from 2015-01-01:
about ten years, three times the registry's longest outcome window of 1,095
days, and three years of prior history before CJDT's 2018 start), a
machine-readable bulk format (delimited text with a header row
and a layout), the update cadence (monthly increments keyed by a stable record
id), the three redistribution rights explicitly, the exclusion of confidential,
sealed, expunged, and juvenile records at the source, the minimum fields the
metrics need (no address, driver licence, telephone, social security number, or
race and sex; name and full date of birth only where no stable person
identifier exists), a cost estimate before any work that would be charged, the
delivery method (an HTTPS download or encrypted media), and a bracketed field
for the operator's contact details that is filled when sending and never
committed.

**Sequencing.** All four in one sitting. The lead time is Florida's, not the
project's: each request asks for an estimate and authorizes no charge, so
sending a fallback request commits nothing, while waiting on the pilot's answer
before asking the fallbacks would add months. Request 2 is independent of the
county chosen.

**Cost ceiling: TBD — operator decision.** No request authorizes a charge; an
estimate is approved or declined by the operator against the ceiling, and the
answer is recorded in the requests table. FDLE warns that labor "may be incurred
prior to the issuance of a good-faith invoice" beyond the first 30 minutes it
waives [W20]; request 2 therefore withholds authorization for any work beyond
those 30 minutes.

**Follow-up cadence.** Chapter 119 requires a prompt acknowledgement [L4] and
rule 2.420(m) a "reasonable manner" [L17], with no fixed deadline. If a request
is not acknowledged within ten business days, the operator sends one follow-up
quoting the original date; afterwards, a follow-up every thirty days until an
answer, a denial in writing, or closure. Each date goes into the requests
table's "Next follow-up" column; Miami-Dade closes a request after sixty days
of non-response or non-payment on the requester's side [M8], so its estimates
are answered within that window.

**When an answer arrives.** The agent records it the same day: the source's
**Redistribution** field and status in `docs/DATA_SOURCES.md`, question 8 and
the requests table in `docs/ROADMAP.md`, and the re-scored row here. Any data
delivered before Phase 7 stays outside the repository and the raw lake until
Phase 7 §7.1's due-diligence gate admits the source; no agent opens it earlier.
The correspondence (it carries the operator's contact details) is kept by the
operator outside the repository.

**The Phase 7 trigger.** Florida enters Phase 7 §7.1 only through a candidate
— Hillsborough, then Broward, then Miami-Dade — that is verified on all three
of: (1) a lawful machine-readable route with a current layout; (2) the judge of
at least one decision family (disposition, sentence, or pretrial release); (3)
Redistribution aggregates `yes`, from the custodian's written answer or an
agreement, or from counsel's Phase 6 §6.4 opinion that derived aggregates of
openly published files may be published. **§7.1's fallback to the next-best
verified state source fires when, at the start of Phase 7, no candidate meets
(1)–(3)** — whether because all three county requests were denied in writing,
answered only with estimates above the operator's ceiling, answered with terms
that forbid derived aggregates, or are still unanswered after the follow-up
cadence. Florida then lands when an answer completes (1)–(3). CJDT alone does
not open the pilot (its judge column is unverified); it joins whichever county
enters.

**Handling on arrival.** The pilot's connector follows the Cook County pattern:
the raw files are stored immutably with their digests; the parser projects rows
to the expected columns so the address and driver-licence fields never reach a
payload; race and sex, when present, go only to `restricted.party_attribute`;
the person identifier and any name and date of birth reach the database only as
peppered hashes; every refresh re-applies removals — a case or count absent from
a later full file, or flagged by FDLE as removed, is retired, because sealed and
expunged records leave the source ("Data purged from the database is also purged
from the … files" [H5]); the committed fixture blanks the restricted and
quasi-identifying columns.

## Redistribution

Every request asks for three rights explicitly, each answered `yes`, `no`, or
with conditions: (1) **republishing derived aggregates** — counts, rates, and
statistics by judge, court, and period that reproduce no record; (2)
**republishing pseudonymous case-level views** — a case's events, charges,
dispositions, and sentences under a random public key, without any name, date
of birth, address, or identifier of the defendant; (3) **commercial
redistribution** — either of the first two in a licensed research dataset or a
paid API, under the project's planned sustainability tier (project roadmap
Phase 9).

Current state, as published (every answer stays `unverified` until a written
answer or agreement says otherwise):

| Source | Aggregates | Case-level | Commercial | On the face of the published terms |
|--------|------------|------------|------------|------------------------------------|
| FDLE CJDT | unverified | unverified | unverified | "The department may not require a license or charge a fee to access or receive information from the database" [L15] |
| Hillsborough clerk files | unverified | unverified | unverified | No use terms published [H3, H13] |
| Broward clerk API | unverified | unverified | unverified | "expressly prohibited from reproducing, publishing online, selling, reselling … except as permitted by law" [B11] |
| Miami-Dade clerk files | unverified | unverified | unverified | "you may not reproduce, retransmit, redistribute … without prior written permission" (case search) [M11] |
| OSCA UCR | unverified | unverified | unverified | Not openly accessible; no terms read [W2] |

**How an answer is recorded.** The register's **Redistribution** field for the
source (`docs/DATA_SOURCES.md` `fl_cjdt` or `fl_clerks`) records each right
separately as `yes`, `no`, or `unverified`, with the date, the document (for
example "email from the clerk's records office, YYYY-MM-DD" or "data agreement
signed YYYY-MM-DD"), and the quoted clause that supports it; a conditional
answer is quoted with its condition and recorded `no` for any use outside it.
The register table's "Commercial redistribution" column, question 8, and the
requests table are updated in the same commit. A signed agreement or letter is
kept by the operator outside the repository. No source enters a snapshot bundle
or a paid tier until its field is a verified `yes` for that tier (Phase 9
§9.1).

## Open questions

1. **OSCA's UCR specification and process.** The JDMS page, the UCR
   specification (current version, judicial-officer elements, any person
   identifier), and whether OSCA releases case-level UCR data to a non-agency
   requester are unverified because `flcourts.gov` disallows crawlers. A person
   reading the pages in a browser, or a rule 2.420(m) request to OSCA, would
   confirm. Not requested now: the clerk holds the same assignment events
   (request 1); reopen if the clerk cannot supply them.
2. **The current Standards for Access and Access Security Matrix** (AOSC24-32 or
   later), including the bulk-purchaser role and its anti-automation clauses —
   a person reading the order on `flcourts.gov` would confirm.
3. **Hillsborough:** which layout the current files carry; whether the PID is
   stable across a person's cases; the columns of the daily filings and the
   sentencing guideline archives; the use terms of the public data files —
   request 1.
4. **CJDT:** the public data catalog (on CJNet [L20]); whether the clerk-case
   download carries the unique identifier, the sentencing judge, and the
   first-appearance determination; per-county completeness; daily or monthly
   cadence; how sealed and expunged records leave the published data — request
   2.
5. **Broward:** the API terms and the notarized agreement; the meaning of BCCN;
   the API's history depth; the report catalog — request 3.
6. **Miami-Dade:** the meanings of `CIN`, `IDS`, `Section`, `PROS Action`, and
   `COURT Action`; a historical extract with the judge; the notarized form's
   terms; which records-request address is current — request 4.
7. **Palm Beach and Pinellas** could not be read by an automated client; a
   person reading their clerks' pages in a browser would confirm whether either
   publishes a criminal bulk product, and would re-score them.
8. **Duty after sealing or expunction.** Whether a private holder of a record
   later sealed or expunged must remove it — counsel (Phase 6 §6.4). The plan
   retires such records on every refresh regardless.
9. **Commercial use of Florida court data.** Whether Florida law permits a
   custodian to restrict the use of court records it releases, and so whether
   Broward's and Miami-Dade's site terms bind a bulk purchaser — counsel (Phase
   6 §6.4).
10. **Restricted attributes.** The requests do not ask for race or sex (the
    minimum-fields rule); Hillsborough's open files carry them. Whether any
    Florida fairness analysis uses them is Phase 6 §6.4's go/no-go.
11. **Department of Corrections data.** The OBIS public database's fields,
    cadence, and terms (robots-excluded [W19]) — a person reading the page, or a
    records request in Phase 7 if CJDT's incarceration data proves insufficient.

## Sources

All accessed 2026-10-05. "Unread" marks a URL known only from a search listing
because the host's `robots.txt` or an access control stopped the research.

| Id | Source | URL |
|----|--------|-----|
| L1 | Fla. Const. art. I, §24 | https://www.leg.state.fl.us/statutes/index.cfm?submenu=3#A1S24 |
| L2 | §119.01, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0100-0199/0119/Sections/0119.01.html |
| L3 | §119.011, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0100-0199/0119/Sections/0119.011.html |
| L4 | §119.07, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0100-0199/0119/Sections/0119.07.html |
| L5 | §119.0714, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0100-0199/0119/Sections/0119.0714.html |
| L6 | §28.2221, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0000-0099/0028/Sections/0028.2221.html |
| L7 | §28.24, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0000-0099/0028/Sections/0028.24.html |
| L8 | §28.2405, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0000-0099/0028/Sections/0028.2405.html |
| L9 | §25.075, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0000-0099/0025/Sections/0025.075.html |
| L10 | §943.0585, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0900-0999/0943/Sections/0943.0585.html |
| L11 | §943.059, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0900-0999/0943/Sections/0943.059.html |
| L12 | §943.0595, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0900-0999/0943/Sections/0943.0595.html |
| L13 | §985.04, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0900-0999/0985/Sections/0985.04.html |
| L14 | §900.05, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0900-0999/0900/Sections/0900.05.html |
| L15 | §943.6871, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0900-0999/0943/Sections/0943.6871.html |
| L16 | §943.053, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0900-0999/0943/Sections/0943.053.html |
| L17 | Fla. R. Gen. Prac. & Jud. Admin. 2.245, 2.420, 2.425 (The Florida Bar's compilation of July 1, 2026) | https://www-media.floridabar.org/uploads/2026/08/2027_01-JULY-Florida-Rules-of-General-Practice-and-Judicial-Administration-7-1-2026.pdf |
| L18 | Fla. R. Crim. P. 3.692 (compilation of October 1, 2026) | https://www-media.floridabar.org/uploads/2026/10/2027_04-Oct-Criminal-Procedure-Rules-10-1-2026.pdf |
| L19 | Attorney General, Government-in-the-Sunshine Manual (2014 edition) | https://legacy.myfloridalegal.com/webfiles.nsf/WF/RMAS-9GNQTW/$file/2014SunshineLawManual.pdf |
| L20 | Fla. Admin. Code R. 11C-11.001 (CJDT data catalog) | https://www.flrules.org/gateway/ruleNo.asp?id=11C-11.001 |
| L21 | §943.045, Fla. Stat. (2026) | https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0900-0999/0943/Sections/0943.045.html |
| W1 | OSCA, Judicial Data Management Services (unread) | https://www.flcourts.gov/Services/court-services/judicial-data-management-services-jdms |
| W2 | `flcourts.gov` robots.txt (`Disallow: /`) | https://www.flcourts.gov/robots.txt |
| W3 | UCR Data Collection Specification 1.4.2 (unread) | https://flcourts-media.flcourts.gov/content/download/793907/file/UCR_Data_Collection_Spec_1-4-2-20_FINAL_508.pdf |
| W4 | UCR Web Service Technical Specification 1.0.2 (unread) | https://flcourts-media.flcourts.gov/content/download/218975/file/OSCA-UCR-Web-Service-Tech-Specs-2017_v1_0_2.pdf |
| W5 | UCR FAQ (unread) | https://flcourts-media.flcourts.gov/content/download/534770/file/ucr-faq.pdf |
| W6 | AOSC16-15, In re: Uniform Case Reporting Requirements (unread) | https://supremecourt.flcourts.gov/content/download/241168/file/AOSC16-15.pdf |
| W7 | AOSC24-32 and the Standards for Access to Electronic Court Records, June 2024 (unread) | https://flcourts-media.flcourts.gov/content/download/2436393/file/AOSC24-32.pdf |
| W8 | OSCA Trial Court Statistics search | https://trialstats.flcourts.org/ |
| W9 | FCCC, Comprehensive Case Information System login page | https://www.flccis.com/ccis/ |
| W10 | FCCC, CCIS Court Records Access Policy (amended through 2021-06-25) | https://cdn.ymaws.com/www.flclerks.com/resource/resmgr/technologysubcommittee/ccis/asm_v9/ccis_court_records_access_po.pdf |
| W11 | Florida House staff analysis, CS/HB 7071 (2018-02-14) | https://www.flsenate.gov/Session/Bill/2018/7071/Analyses/h7071a.JUA.PDF |
| W12 | FDLE, Criminal Justice Data Transparency | https://www.fdle.state.fl.us/CJAB/CJDT |
| W13 | FDLE, About CJDT data | https://www.fdle.state.fl.us/cjab/cjdt/about-cjdt-data |
| W14 | FDLE, CJDT Clerk of Court case reports | https://www.fdle.state.fl.us/CJAB/CJDT/COC-Case-Reports |
| W15 | CJDT clerk-case full download (headers only) | https://cjdtpublicstorageprod.blob.core.usgovcloudapi.net/cjdtpubliccontainer/CjdtClerkCase/CjdtClerkCase.zip |
| W16 | CJJIS Council minutes, 2025-12-03 | https://www.fdle.state.fl.us/getContentAsset/cc04fc3a-9466-45a9-b0f2-50e92879839c/73aabf56-e6e5-4330-95a3-5f2a270a1d2b/December-3-2025-CJJIS-Council-Minutes-Final.pdf |
| W17 | FDLE, Florida criminal history checks | https://www.fdle.state.fl.us/criminal-history-records/florida-checks |
| W18 | FDLE, Computerized Criminal History | https://www.fdle.state.fl.us/CJAB/FSAC/CCH |
| W19 | Department of Corrections, OBIS public-records page (unread; `Disallow: /`) | https://pubapps.fdc.myflorida.com/pub/obis_request.html |
| W20 | FDLE's Guide to Public Records Requests (2025) | https://www.fdle.state.fl.us/getContentAsset/9128d66f-6931-40ba-96a0-f8a6691f7c9f/73aabf56-e6e5-4330-95a3-5f2a270a1d2b/2025-FDLE-s-Guide-to-Public-Records-Requests.pdf?language=en |
| W21 | FDLE, Public Records | https://www.fdle.state.fl.us/ogc/public-records |
| W22 | Broward Clerk, Standards for Electronic Court Access | https://www.browardclerk.org/Web2/Services/StandardsForECA |
| H1 | Hillsborough Clerk, Public Records Request | https://www.hillsclerk.com/Records-and-Reports/Public-Records-Request |
| H2 | Hillsborough Clerk, Fees and Fines | https://www.hillsclerk.com/About-Us/Fees-and-Fines |
| H3 | Hillsborough Clerk, Public Data Files | https://www.hillsclerk.com/records-and-reports/public-data-files |
| H4 | Criminal Name Index directory (listing only) | https://publicrec.hillsclerk.com/Criminal/name_index/ |
| H5 | Criminal Name Index readme, fixed width (updated 2015-07-27) | https://publicrec.hillsclerk.com/Criminal/name_index/hccc1020/readme.txt |
| H6 | Circuit Criminal Name Index README, pipe-delimited (updated 2019-06-17) | https://publicrec.hillsclerk.com/Criminal/name_index/Circuit/README.pdf |
| H7 | Daily criminal filings (listing only) | https://publicrec.hillsclerk.com/Criminal/dailyfilings/ |
| H8 | Sentencing guidelines (listing only) | https://publicrec.hillsclerk.com/Criminal/sentencing_guidelines/ |
| H9 | Court calendars (listing only) | https://publicrec.hillsclerk.com/Criminal/court_calendars/ |
| H10 | Criminal Traffic Name Index README (updated 2022-05-11) | https://publicrec.hillsclerk.com/Traffic/Criminal_Traffic_Name_Index_files/README_Criminal_Traffic_Name_Index.pdf |
| H11 | HOVER FAQ | https://hover.hillsclerk.com/html/faq.html |
| H12 | HOVER user roles | https://hover.hillsclerk.com/html/userRoleSummary.html |
| H13 | Hillsborough Clerk, Legal Info and Disclaimer | https://www.hillsclerk.com/Legal-Info-and-Disclaimer |
| B1 | Broward Clerk, About the API | https://www.browardclerk.org/Web2/Services/AboutAPI |
| B2 | Broward Clerk, Commercial Data Access units pricing tiers | https://www.browardclerk.org/Web2/Broward%20County%20Clerk%20of%20Courts%20-%20Commercial%20Data%20Access%20Units%20-%20Pricing%20Tiers.pdf |
| B3 | Broward Clerk, API service method cost | https://www.browardclerk.org/Web2/Broward%20County%20Clerk%20of%20Courts%20-%20Commercial%20Data%20Access%20(API)%20Service%20Method%20Cost.pdf |
| B4 | Broward Clerk, Web API technical documentation (2017-12-19) | https://www.browardclerk.org/Web2/Broward%20Clerk%20Web%20API%20Service%20Technical%20Documentation.pdf |
| B5 | Broward Clerk, Web API request parameters (2021-05-14) | https://www.browardclerk.org/Web2/Broward%20Clerk%20Web%20API%20Service%20Technical%20Documentation%20-%20Request%20Parameters.pdf |
| B6 | Broward Clerk, API change log (2019-03-05) | https://www.browardclerk.org/Web2/Broward%20County%20Clerk%20of%20Courts%20-%20Commercial%20Data%20Access%20(API)%20-%20Change%20Log.pdf |
| B9 | Broward Clerk, case search FAQ | https://www.browardclerk.org/Web2/CaseSearchECA/FrequentQuestions/ |
| B10 | Broward Clerk, Records Request | https://www.browardclerk.org/GeneralInformation/RecordsRequest |
| B11 | Broward Clerk, Miscellaneous (disclaimer; custodian) | https://www.browardclerk.org/GeneralInformation/Miscellaneous |
| B12 | Broward Clerk, case search (landing page) | https://www.browardclerk.org/Web2/CaseSearchECA/Index/?AccessLevel=ANONYMOUS |
| M1 | Miami-Dade Clerk, Commercial Data Services | https://www.miamidadeclerk.gov/clerk/commercial-data-services.page |
| M2 | Miami-Dade Clerk, criminal FTP file layout (revised 2026-03-23) | https://www.miamidadeclerk.gov/resources-clerk/library/FTP_File_Layouts/FTP_Layout_Criminal.pdf |
| M3 | Miami-Dade Clerk, Commercial Data Services user guide (2025-09-22) | https://www.miamidadeclerk.gov/resources-clerk/library/commercial_data_services_user_guide.pdf |
| M5 | Miami-Dade Clerk, criminal API help | https://www2.miamidadeclerk.gov/Developers/Help/Api/GET-api-Criminal_CaseNumber_AuthKey |
| M6 | Miami-Dade Clerk, developer registration agreement (displayed) | https://www2.miamidadeclerk.gov/Developers/Account/Register |
| M7 | Miami-Dade Clerk, Public Records Requests | https://www.miamidadeclerk.gov/clerk/public-records-requests.page |
| M8 | Miami-Dade Clerk, public records request form 466 (Rev. 02/25) | https://www.miamidadeclerk.gov/resources-clerk/library/466-Web.pdf |
| M11 | Miami-Dade Clerk, CJIS case search (notice in the published script) | https://www2.miamidadeclerk.gov/cjis/ |
| M13 | Miami-Dade County, Electronic Arrest Form scope of services | https://www.miamidade.gov/Apps/ISD/StratProc/ProcurementNAS/pdf_Files/WaiveCompetitions/Scope_of_Services_-_Electronic_Arrest_Form.pdf |
| P1 | Palm Beach Clerk, ClerkCart | https://appsgp.mypalmbeachclerk.com/clerkcart/ |
| P3 | Palm Beach Clerk, ClerkCart product list | https://appsgp.mypalmbeachclerk.com/clerkcart/ProductList.aspx |
| P4 | Palm Beach Clerk, ClerkCart FAQ | https://appsgp.mypalmbeachclerk.com/clerkcart/FAQ.aspx |
| P5 | Palm Beach Clerk, eCaseView (landing page) | https://appsgp.mypalmbeachclerk.com/eCaseView/ |
| P6 | Palm Beach Clerk, eCaseView user guide | https://appsgp.mypalmbeachclerk.com/eCaseView/External/eCaseViewUserGuide |
| P7 | Palm Beach Clerk, eCaseView MFA and reCAPTCHA | https://appsgp.mypalmbeachclerk.com/eCaseView/External/MfaRecaptcha |
| P8 | Palm Beach Clerk, public records requests (unread; HTTP 403) | https://www.mypalmbeachclerk.com/records/public-records-requests |
| A1 | Alachua Clerk, Public Records Requests | https://alachuacounty.us/Depts/Clerk/PublicRecords/Pages/Public-Records-Requests.aspx |
| A2 | Alachua Clerk, BBS reports and database subscription (HTTP only) | http://clerk-bbs.alachuaclerk.org/ |
| A3 | Alachua Clerk, BBS terms | http://clerk-bbs.alachuaclerk.org/Home/About/Terms.wgs |
| A4 | Alachua Clerk, court records | https://alachuacounty.us/Depts/Clerk/PublicRecords/pages/courtrecords.aspx |
| D2 | Duval Clerk, complex public and court records request | https://www.duvalclerk.com/getmedia/26edc9ad-7ac5-4ea3-8142-45459141246f/RequesttoObtainComplexPublicAndCourtRecords_ADA_Compliant2.pdf |
| D3 | Duval Clerk, special service, cost recovery and compliance policy | https://www.duvalclerk.com/getmedia/92cdf29c-19ad-4fab-9bf2-fcfc009c2a09/Cost_Recovery_Policy2_ADA_Compliant.pdf |
| D5 | Duval Clerk, registration agreement for electronic court records | https://www.duvalclerk.com/getmedia/ed5412ad-b36e-4ce6-acda-4ddc149d201a/registration_agreement_for_viewing_electronic_court_records_ADA_Compliant.pdf |
| D6 | Duval Clerk, felony | https://www.duvalclerk.com/departments/criminal-court-services/felony |
| D7 | Duval Clerk, Pre-Trial Release Register | https://www.duvalclerk.com/services/pre-trial-release-register |
| D9 | Duval Clerk, CORE (landing page) | https://core.duvalclerk.com/ |
| D10 | Duval Clerk, site policies | https://www.duvalclerk.com/site-policies |
| LE1 | Leon Clerk, records request | https://leonclerk.com/helpful-resources/records/records-request/ |
| LE2 | Leon Clerk, request for court records form | https://leonclerk.com/uploads/2026/03/request_records.pdf |
| LE3 | Leon Clerk, fees | https://leonclerk.com/helpful-resources/fees/ |
| LE4 | Leon Clerk, registration agreement for court records and reports online | https://leonclerk.com/uploads/2026/03/reports_subscription.pdf |
| LE6 | Leon Clerk, privacy policy | https://leonclerk.com/privacy-policy/ |
| O1 | Orange Clerk, request court records | https://www.myorangeclerk.com/Divisions/Records/Request-Court-Records |
| O2 | Orange Clerk, court records | https://www.myorangeclerk.com/Divisions/Records/Court-Records |
| O3 | Orange Clerk, my eClerk FAQ | https://myeclerk.myorangeclerk.com/Home/FAQ |
| O4 | Orange Clerk, my eClerk search (landing page) | https://myeclerk.myorangeclerk.com/Cases/Search |
| O5 | Orange Clerk, online viewing agreement | https://myeclerk.myorangeclerk.com/PublicDocuments/Access%20Agreement.pdf |
| PI1 | Pinellas Clerk (unread; Cloudflare challenge) | https://www.mypinellasclerk.gov/ |
| PI2 | Pinellas Clerk, `.org` robots.txt | https://www.mypinellasclerk.org/robots.txt |
| X1 | Lee Clerk, bulk data services (unread; HTTP 403) | https://www.leeclerk.org/services/bulk-data-services |
| X2 | Manatee Clerk, public access | https://www.manateeclerk.com/departments/public-access/ |
| X3 | Seminole Clerk, search for a court case | https://www.seminoleclerk.org/search-for-a-court-case/ |
| X4 | Sarasota Clerk (robots-disallowed court-records paths; unread) | https://www.sarasotaclerk.com/robots.txt |
