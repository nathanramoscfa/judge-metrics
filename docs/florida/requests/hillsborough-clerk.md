<!-- docs/florida/requests/hillsborough-clerk.md -->
# Request 1 — Hillsborough County Clerk of the Circuit Court & Comptroller

| Field | Value |
|-------|-------|
| Recipient | Hillsborough County Clerk of the Circuit Court & Comptroller, custodian of the court records of the 13th Judicial Circuit |
| Published contact | `PublicRecords@hillsclerk.com`; 601 E. Kennedy Blvd., 13th floor, Tampa, FL 33602; an online request portal is also offered (`docs/florida-data-inventory.md` [H1]) |
| Legal basis | Fla. Const. art. I, §24; Fla. R. Gen. Prac. & Jud. Admin. 2.420(m) for court records; ch. 119, Fla. Stat., for the clerk's other records |
| Role in the plan | The selected pilot (`docs/florida-data-inventory.md` "Selection") |
| Drafted | 2026-10-05 |
| Submission | Recorded in `docs/ROADMAP.md` "Florida acquisition requests" |

**Before sending (operator).** Replace every bracketed field with your own
details, send from your own address to the published contact, and keep the sent
copy and every answer outside the repository (they carry your contact details).
Record the submission date in `docs/ROADMAP.md`. Add nothing that names a
defendant or a case.

---

**To:** PublicRecords@hillsclerk.com
**Subject:** Public records request — bulk criminal case data, its layouts, and
its use terms

To the Records Custodian:

Under Article I, section 24 of the Florida Constitution, Florida Rule of General
Practice and Judicial Administration 2.420(m), and, for any record that is not
a court record, chapter 119, Florida Statutes, I request the records below. I
make the request for JudgeMetrics, a public-interest project that publishes
reproducible statistics on criminal-court outcomes by court and by judge, with
its methodology and the source of every figure. The rule does not require a
reason; I give one because part 4 asks about use.

**1. Documentation of the public data files on publicrec.hillsclerk.com.**

a. The current record layout or data dictionary of the Circuit and County
   Criminal Name Index files (the pipe-delimited files and the fixed-width
   `FF1020CF.WP` and `FF1020CM.WP`), of the daily criminal filing files
   (`CriminalFiling_YYYYMMDD.csv`), and of the sentencing guideline archives
   (`YYYYMMDD_SentenceGuidelines.zip`).
b. The disposition code table in effect.
c. A record stating whether the party ID ("PID") identifies the same person
   across all of that person's cases or is assigned per case.
d. Any terms, license, or policy that governs the use of these files.

**2. A bulk extract of criminal case data.** If it exists or can be produced
from the clerk's case maintenance system: all circuit (felony) and county
(misdemeanor) criminal cases filed on or after January 1, 2015, with, for each
case:

a. uniform case number, court type, case type, filing date, case status, and
   closing date;
b. each judicial assignment: the division, the assigned judge, and the start
   and end dates of the assignment;
c. for each count: count number, statute, level and degree, offense date,
   disposition, disposition date, and the judicial officer who entered the
   disposition, where recorded;
d. pretrial release: the first-appearance date; each pretrial release or
   detention determination with its date, its type (for example release on
   recognizance, monetary bond, supervised release, or detention), its monetary
   and nonmonetary conditions, and the judicial officer who made it; bond
   posting and revocation dates;
e. court events: the date, type, and judicial officer of each hearing; each
   failure to appear and each warrant or capias issued for one, with dates;
f. for each sentence: date, count, type, length, and the sentencing judge;
   violations of probation or community control and their outcomes;
g. for each defendant: the party ID, if it identifies the same person across
   cases; only if no such identifier exists, the defendant's name and full date
   of birth, which will be used solely to link the same person's cases, stored
   only as one-way hashes, and never published.

Please omit street addresses, driver-licence numbers, telephone numbers, social
security numbers, and race and sex.

**3. Exclusions at the source.** Please exclude every record and field that is
confidential or exempt, including information the clerk must keep confidential
under rule 2.420(d)(1), records sealed or expunged under sections 943.059,
943.0585, or 943.0595, Florida Statutes, and juvenile records under section
985.04; please include no juvenile case. If you provide updates, please identify
the cases or counts removed since the previous delivery so that I can remove
them as well.

**4. Use and redistribution.** Please state in writing whether the clerk places
any condition on the use of the public data files or of the extract, and
specifically whether I may:

1. republish derived aggregates — counts, rates, and statistics by judge, court,
   and period that reproduce no individual record;
2. republish pseudonymous case-level views — a case's events, charges,
   dispositions, and sentences under a random key, without any defendant's
   name, date of birth, address, or identifier;
3. redistribute either of the above commercially, for example in a licensed
   research dataset or a paid data service.

**5. Format, cadence, and delivery.** Delimited text (CSV or pipe-delimited)
with a header row, or the machine-readable format the clerk already maintains,
with its layout; a monthly update keyed by a stable record identifier, if the
clerk can provide one; delivery by HTTPS download or on encrypted media.

**6. Cost.** If any part requires a special service charge under section
119.07(4)(d) or another fee, please send me a written estimate first. I do not
authorize any charge until I have approved an estimate in writing. If part 2
cannot be produced, please fulfil parts 1 and 4.

Please acknowledge receipt and send the records and any questions to:

[YOUR NAME]
[YOUR EMAIL ADDRESS]
[YOUR MAILING ADDRESS — optional]
[YOUR TELEPHONE — optional]

[DATE SENT]
