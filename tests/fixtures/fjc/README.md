<!-- tests/fixtures/fjc/README.md -->
# FJC fixture excerpt

A small real excerpt of the Federal Judicial Center's Biographical
Directory export (`docs/DATA_SOURCES.md`, entry `fjc`), used by the unit
tests and by `tests/integration/test_fjc_ingest.py`, which runs the
ingest pipeline over it twice to prove idempotency.

- **Export page:**
  `https://www.fjc.gov/history/judges/biographical-directory-article-iii-federal-judges-export`
- **Files:** `judges.csv` (25 rows) and `federal-judicial-service.csv`
  (42 rows, every appointment of those 25 judges; 28 distinct courts).
- **Retrieved:** 2026-09-16 from
  `https://www.fjc.gov/sites/default/files/history/judges.csv` and
  `https://www.fjc.gov/sites/default/files/history/federal-judicial-service.csv`
  (`Last-Modified: Wed, 16 Sep 2026 05:05:19 GMT` and `05:05:22 GMT`).
- **Terms:** a work of the United States federal government; cite the
  FJC as the source.

## How the excerpt was made

Rows were selected by FJC node id (`nid`) and written back with every
field quoted, as the FJC publishes them. No value was edited. Two
columns of `judges.csv` were dropped: `Gender` and `Race or Ethnicity`.
The connector never reads them (they are outside its expected header
set, and the parser projects each row to that set), and the repository
does not carry demographic attributes of named people. The remaining
199 columns of `judges.csv` and all 30 columns of
`federal-judicial-service.csv` are the verified headers recorded in
`src/judgemetrics/ingest/fjc/schema.py`.

## Why these judges

The selection covers every mapping the connector implements:

| Scenario                                              | Judge (nid)                                   |
|-------------------------------------------------------|-----------------------------------------------|
| Two or more courts                                    | Acheson (1376981), Alito (1377101), Sotomayor (1388091), Ginsburg (1381271), Kavanaugh (1392406), Henley (1382066), Groner (1381546), Lawrence (1383686), Archbald (1377251), George Adams (1377021) |
| Senior status, still serving (`senior`)               | Henry Lee Adams, Jr. (1377031), Aquilino (1392821) |
| Senior status then death (`deceased`)                 | Abruzzo (1376976), Henley (1382066)           |
| Retirement / resignation                              | Arlin Adams (1377011) / George Adams (1377021) |
| Impeachment and conviction (`removed`)                | Archbald (1377251)                            |
| Recess appointment only, never confirmed              | Andrews (1390306)                             |
| Approximate birth year (`ca. 1793`) / no birth year   | Lawrence (1383686) / Mascott (13762064)       |
| Diacritics, hyphens, apostrophes in names             | Alarcón (1377066), Antongiorgi-Jordán (12802356), D'Agostino (1393661) |
| District of Columbia / Puerto Rico state codes        | Ali (13761895) / Acosta (1377001), Antongiorgi-Jordán (12802356) |
| Court types `other` (Court of International Trade, historical circuit courts) | Aquilino (1392821), Acheson (1376981), McAllister (1384486) |
| Supreme Court (`supreme`), courts of appeals (`appeals`) | Alito, Sotomayor, Ginsburg, Kavanaugh      |

## Planted data-quality issues

Both issues are real rows chosen for the property they exhibit; nothing
was altered:

1. **`service_overlap` (warning):** Duncan Lawrence Groner (1381546)
   served on the U.S. Court of Appeals for the District of Columbia
   Circuit as Associate Justice from 1931-02-21 to 1938-01-15 and as
   Chief Justice from 1937-12-07, so the two intervals overlap.
2. **`missing_start_date` (info):** Matthew Richard Byrne (13762157)
   has a service row for the Southern District of Ohio with no
   commission date and no recess appointment date at retrieval time.

Jesse Smith Henley (1382066) is included as the counter-example: his
recess appointment to the Eastern District of Arkansas ends on the same
day his commissioned service begins, and touching intervals are not an
overlap.
