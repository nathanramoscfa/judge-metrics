<!-- docs/florida/requests/miami-dade-clerk.md -->
# Request 4 — Miami-Dade County Clerk of the Court and Comptroller

| Field | Value |
|-------|-------|
| Recipient | Miami-Dade County Clerk of the Court and Comptroller, Records Management (11th Judicial Circuit) |
| Published contact | `cocpubreq@miamidadeclerk.gov`; Records Management, P.O. Box 14695, Miami, FL 33101; the blank request form names `COCPUBREQ@miamidade.gov` instead (`docs/florida-data-inventory.md` [M7], [M8]); commercial data files are run by Technical Services, `clerksoffice@miamidade.gov` [M1] |
| Legal basis | Fla. Const. art. I, §24; Fla. R. Gen. Prac. & Jud. Admin. 2.420(m) for court records; ch. 119, Fla. Stat., for the clerk's other records |
| Role in the plan | Fallback 2 (`docs/florida-data-inventory.md` "Selection") |
| Drafted | 2026-10-05 |
| Submission | Recorded in `docs/ROADMAP.md` "Florida acquisition requests" |

**Before sending (operator).** Replace every bracketed field with your own
details, send from your own address to `cocpubreq@miamidadeclerk.gov` with
Technical Services copied (if it bounces, use the form's address), and keep the
sent copy and every answer outside the repository (they carry your contact
details). Record the submission date in `docs/ROADMAP.md`. Do not register for
the commercial data service or sign any form as part of this request. Requests
are closed after sixty days without a response from the requester, so answer an
estimate within that window.

---

**To:** cocpubreq@miamidadeclerk.gov
**Cc:** clerksoffice@miamidade.gov
**Subject:** Public records request — historical criminal case data, field
definitions, and use terms

To Records Management:

Under Article I, section 24 of the Florida Constitution, Florida Rule of General
Practice and Judicial Administration 2.420(m), and, for any record that is not
a court record, chapter 119, Florida Statutes, I request the records below. I
make the request for JudgeMetrics, a public-interest project that publishes
reproducible statistics on criminal-court outcomes by court and by judge, with
its methodology and the source of every figure. The rule does not require a
reason; I give one because part 4 asks about use.

**1. Documentation.**

a. Records defining the criminal file fields `CIN`, `IDS`, `Section`
   (`BFILE Sect`), `PROS Action`, `COURT Action`, and the `BIWEEKLYPTD` file's
   "PTD", and the criminal API fields `NextCase` and `PreviousCase`.
b. A record stating whether `CIN` or `IDS` identifies the same person across all
   of that person's cases.
c. The terms of the notarized "Data Download or Custom Public Access Request"
   form and of any license that governs the commercial data folders, and the
   list of criminal folders with their prices.

**2. A historical extract of criminal case data**, if it exists or can be
produced: all felony and misdemeanor cases filed on or after January 1, 2015,
with, for each case:

a. case number, state case number, case type, filing date, case status, and
   closing date;
b. each judicial assignment: the section, the assigned judge, and the start and
   end dates;
c. for each charge: statute, degree, offense date, disposition, disposition
   date, and the judicial officer who entered the disposition, where recorded;
d. pretrial release: the first-appearance date; each release or detention
   determination with its date, type, monetary and nonmonetary conditions, and
   the judicial officer who made it; bond posting and revocation dates;
e. hearings with date, type, and judicial officer; each failure to appear and
   each warrant or capias issued for one, with dates;
f. for each sentence: date, charge, type, length, and the sentencing judge;
   probation violations and their outcomes;
g. for each defendant: the `CIN`, if it identifies the same person across cases;
   only if no such identifier exists, the defendant's name and full date of
   birth, which will be used solely to link the same person's cases, stored only
   as one-way hashes, and never published.

Please omit street addresses, driver-licence numbers, telephone numbers, social
security numbers, and race and sex.

**3. Exclusions at the source.** Please exclude every record and field that is
confidential or exempt, including information the clerk must keep confidential
under rule 2.420(d)(1), records sealed or expunged under sections 943.059,
943.0585, or 943.0595, Florida Statutes, and juvenile records under section
985.04; please include no juvenile case. If you provide updates, please identify
the cases or charges removed since the previous delivery so that I can remove
them as well.

**4. Use and redistribution.** The clerk's case-search notice says its content
may not be reproduced or redistributed "without prior written permission from
the Clerk and Comptroller's Office." Please state in writing whether that
notice, the commercial data terms, or any other condition applies to the
commercial data files or to the extract, and specifically whether I may:

1. republish derived aggregates — counts, rates, and statistics by judge, court,
   and period that reproduce no individual record;
2. republish pseudonymous case-level views — a case's events, charges,
   dispositions, and sentences under a random key, without any defendant's
   name, date of birth, address, or identifier;
3. redistribute either of the above commercially, for example in a licensed
   research dataset or a paid data service.

If permission is required, please treat this letter as the request for it.

**5. Format, cadence, and delivery.** Delimited text (CSV or pipe-delimited)
with a header row, or the machine-readable format the clerk already maintains,
with its layout; a monthly update keyed by a stable record identifier, if the
clerk can provide one; delivery by HTTPS download or on encrypted media.

**6. Cost.** If any part requires a special service charge under section
119.07(4)(d) or another fee, please send me a written estimate first, with its
clerk and information-technology components. I do not authorize any charge
until I have approved an estimate in writing. If part 2 cannot be produced,
please fulfil parts 1 and 4.

Please acknowledge receipt and send the records and any questions to:

[YOUR NAME]
[YOUR EMAIL ADDRESS]
[YOUR MAILING ADDRESS — optional]
[YOUR TELEPHONE — optional]

[DATE SENT]
