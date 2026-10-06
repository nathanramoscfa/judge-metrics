<!-- docs/florida/requests/broward-clerk.md -->
# Request 3 — Broward County Clerk of Courts

| Field | Value |
|-------|-------|
| Recipient | Broward County Clerk of Courts, Custodian of Public Records (17th Judicial Circuit) |
| Published contact | `PublicRecords@BrowardClerk.org` (custodian); API and bulk-data questions also to `PublicAccessHelpDesk@browardclerk.org` (`docs/florida-data-inventory.md` [B11], [B1]) |
| Legal basis | Fla. Const. art. I, §24; Fla. R. Gen. Prac. & Jud. Admin. 2.420(m) for court records; ch. 119, Fla. Stat., for the clerk's other records |
| Role in the plan | Fallback 1 (`docs/florida-data-inventory.md` "Selection") |
| Drafted | 2026-10-05 |
| Submission | Recorded in `docs/ROADMAP.md` "Florida acquisition requests" |

**Before sending (operator).** Replace every bracketed field with your own
details, send from your own address to the custodian with the help desk copied,
and keep the sent copy and every answer outside the repository (they carry your
contact details). Record the submission date in `docs/ROADMAP.md`. Do not
subscribe to the API or sign any agreement as part of this request.

---

**To:** PublicRecords@BrowardClerk.org
**Cc:** PublicAccessHelpDesk@browardclerk.org
**Subject:** Public records request — Commercial Data Access terms, criminal
case data in bulk, and its use terms

To the Custodian of Public Records:

Under Article I, section 24 of the Florida Constitution, Florida Rule of General
Practice and Judicial Administration 2.420(m), and, for any record that is not
a court record, chapter 119, Florida Statutes, I request the records below. I
make the request for JudgeMetrics, a public-interest project that publishes
reproducible statistics on criminal-court outcomes by court and by judge, with
its methodology and the source of every figure. The rule does not require a
reason; I give one because part 4 asks about use.

**1. Documentation.**

a. The Commercial Data Services registration agreement and the terms and
   conditions a subscriber to the Commercial Data Access (API) Service accepts.
b. The catalog of the Report Downloads service, with each report's layout,
   cadence, and price.
c. A record defining the Broward County Control Number (BCCN) and stating
   whether it identifies the same person across all of that person's cases.
d. A record stating from what filing year the API returns felony and
   misdemeanor case data.

**2. A bulk extract of criminal case data**, as an alternative to the API, if it
exists or can be produced: all felony and misdemeanor cases filed on or after
January 1, 2015, with, for each case:

a. case number, uniform case number, case type, filing date, case status, and
   closing date;
b. each judicial assignment: the division, the assigned judge, and the start
   and end dates;
c. for each charge: charge number, statute, degree, offense date, plea,
   disposition, disposition date, and the disposition judicial officer;
d. pretrial release: the first-appearance date; each release or detention
   determination with its date, type, monetary and nonmonetary conditions, and
   the judicial officer who made it; bond posting and revocation dates;
e. hearings with date, type, and judicial officer; each failure to appear and
   each warrant issued for one, with dates;
f. for each sentence: date, charge, type, length, and the sentencing judge;
   probation violations and their outcomes;
g. for each defendant: the BCCN, if it identifies the same person across cases;
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

**4. Use and redistribution.** The clerk's website disclaimer prohibits
"reproducing, publishing online, selling, reselling or otherwise disseminating
data or information accessed pursuant to this Disclaimer, except as permitted by
law." Please state in writing whether that disclaimer, the API terms, or any
other condition applies to the API data, the report downloads, or the extract,
and specifically whether I may:

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
