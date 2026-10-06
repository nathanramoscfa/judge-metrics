<!-- docs/SYNTHETIC_DATA.md -->
# The synthetic justice dataset

`judgemetrics synthetic generate` writes a deterministic synthetic
justice dataset: nine source-format CSV files a connector can ingest, a
`truth/` directory the canonical database never sees, and a manifest
with the sha256 of every file. It exists so the complete pipeline —
ingest, entity resolution, case timelines, and every metric — can be
demonstrated and tested against exact expectations before any real
case data is available (`docs/DATA_SOURCES.md`, entry `synthetic`; the
brief's `<synthetic_demo_dataset>` and `<testing_strategy>`). The
package is `src/judgemetrics/synthetic/`.

Every person, judge, court, and case in it is invented. Names are
composed from dictionary words (colours, minerals, weather; trees,
birds, rivers), never taken from a list of real people; the
jurisdiction is "Synthetic State" (`ZZ`); the courts carry "Synthetic"
in their names; the source is `source_type = synthetic`, labelled as
such on every public surface and refused by the ingest runner in
production.

## Commands

```sh
uv run judgemetrics synthetic generate --seed 7 --scale golden --out tests/fixtures/golden
uv run judgemetrics synthetic generate                 # --seed 20260916 --scale demo --out data/synthetic/20260916
uv run judgemetrics synthetic generate --scale tiny --out /tmp/tiny --force
uv run judgemetrics synthetic verify tests/fixtures/golden   # exit 1 on any hash mismatch
```

`generate` prints the row count of every CSV and the manifest path, and
logs the seed, scale, and counts through `judgemetrics.logging` (never a
row). It refuses to write into a directory that already holds a
`manifest.json` or generated files under `source/` or `truth/` unless
`--force` is given; it creates the output directory with
`Path.mkdir(parents=True)` and never deletes anything. `verify`
recomputes every sha256 in the manifest and reports each mismatch,
missing file, and unlisted file under `source/` or `truth/`.

In code: `generate_dataset(seed, scale, out, *, force=False) ->
Manifest` and `verify_dataset(out) -> list[str]`
(`judgemetrics.synthetic.generate`). `data/synthetic/` is untracked;
the golden fixture under `tests/fixtures/golden/` is tracked.

## The determinism contract

- One seed determines every byte. Two runs of the same seed and scale
  produce identical files on every supported interpreter; the unit test
  regenerates the golden fixture into a temporary directory and compares
  each file byte for byte.
- `Streams(seed)` (`rng.py`) derives one `random.Random` per named
  stream — `world`, `persons`, `cases`, `events`, `edge_cases`, and
  (`GENERATOR_VERSION` 3) `effects` and `attributes` — from
  `sha256(f"{seed}:{name}")`, so adding a draw to one stage cannot move
  another stage's output; a unit test re-seeds the `attributes` stream
  alone and finds only `synthetic_group` changed. The helpers in
  `rng.py` (`randint`, `choice`, `weighted_choice`, `shuffled`,
  `sample`, `skewed_fraction`) call only `Random.random()`, the one
  method whose sequence Python guarantees stable across versions for a
  given seed.
- Nothing in the package calls module-level `random` functions,
  `datetime.now`, `uuid.uuid4`, or `os.urandom`; every iteration over a
  mapping or set is sorted; identifiers are formatted counters assigned
  in one fixed pass (`model.assign_identifiers`): cases are numbered
  `SYN-<year>-<seq>` in filed order with the sequence restarting each
  year, rows `AS-`, `CH-`, `EV-`, `DC-`, `SN-` follow the same order,
  and participant ids `PT-` are assigned on a person's first appearance.
  Courts are `C-0001`.., judges `J-0001`.., and true persons `P-000001`..
  (the latter only in `truth/`).
- `GENERATOR_VERSION` (`config.py`) is written to the manifest and is
  bumped whenever the output for a fixed seed changes for any reason: a
  new draw, a changed constant, a new column, a changed word list. The
  golden fixture is then regenerated, never hand-edited (see
  "Regenerating the golden fixture"). `TRUTH_VERSION` (`truth.py`) is
  bumped whenever a truth file's schema or a metric definition changes.

## Scales

| Scale    | Courts | Judges | Persons | Cases | Years     | Duplicate records | Ambiguous pairs | Split pairs | Missing DOB / judge / disposition shares |
|----------|--------|--------|---------|-------|-----------|-------------------|-----------------|-------------|------------------------------------------|
| `golden` | 3      | 6      | 40      | 60    | 2019–2021 | 3                 | 2               | 2           | 0.05 / 0.05 / 0.03                       |
| `demo`   | 5      | 24     | 3,200   | 5,200 | 2016–2023 | 40                | 25              | 25          | 0.04 / 0.02 / 0.01                       |
| `tiny`   | 2      | 3      | 12      | 16    | 2020–2021 | 1                 | 1               | 1           | 0.1 / 0.1 / 0.1                          |

`demo` exceeds the brief's minimums (5 courts, 20 judges, 5,000 cases,
3,000 defendants) and a unit test asserts it, on the `ScaleSpec` and on
a generated run. `golden` is small enough that every planted item is
hand-checkable from `truth/README.md`; it is the permanent regression
fixture. `tiny` exists for the property tests (`tests/property/`, Phase
2 Step 5: a dataset generates and normalizes in well under a second, so
Hypothesis can draw dozens of seeds per test) and for smoke runs. A
`ScaleSpec` validates itself: at least one judge per court, at least as
many cases as persons, at most four cases per person, room for every
plant. What a spec cannot validate is the random draw: a two-court
`tiny` world occasionally holds no two unused persons in disjoint
courts, and the same-date-of-birth ambiguous plant then falls back to a
same-court pair (below) rather than failing the generation, so every
seed generates at every scale (3,000 consecutive seeds checked at
`tiny` and `golden`, again at `GENERATOR_VERSION` 3; seed 117 is the
`tiny` seed the unit test pins for the fallback). `DEMO` keeps its size
at version 3: the planted effects were calibrated to it ("Planted
effects").

## The world model

**Jurisdiction and courts.** One jurisdiction, "Synthetic State" (type
`state`, `state_code` `ZZ`), with courts named "Synthetic County
Circuit Court, Division N" (type `circuit`).

**Judges.** Each judge has one or two service records inside the
corpus years (positions `circuit_judge`, `associate_judge`). The first
judge of each court is an anchor serving the whole span, so every court
always has a sitting judge; other judges start at the corpus start or
later, some end inside the corpus, some transfer to another court or
are promoted in place (the first non-anchor judge always has two
records). Each judge carries two latent tendencies from the `world`
stream — a dismissal bias added to the judicial-dismissal share and a
severity multiplier on incarceration lengths — and, from the `effects`
stream, the four planted effects of "Planted effects" below: a
release leniency, a new-case effect, a failure-to-appear effect, and a
docket tilt.

**Persons.** Each person has a true identity (`P-`), a unique composed
name, a date of birth drawn inside an age band (18–24, 25–34, 35–44,
45–54, 55+ at the corpus start), a latent propensity (`random() ** 2`,
mean one third) that drives subsequent behaviour, a home court, and
(`GENERATOR_VERSION` 3, the `attributes` stream) a `synthetic_group` that
no draw reads ("Restricted controls"). Names are unique across judges
and persons; only the edge-case planter creates a collision, and it
records it. Every person appears in one to
four cases: one each, then the extra cases distributed by propensity,
so subsequent cases exist and the demo's 3,200 persons carry 5,200
cases.

**Cases.** A person's cases are chronological: the first is filed on a
random day of the corpus (leaving room for later ones), each later one
at least fourteen days after the previous case's pretrial decision,
sooner for a higher propensity, a riskier previous case, a younger
filing age, and a releasing judge with a larger new-case effect ("Planted
effects"). The first case sits in the home court;
later cases stay there 65% of the time (the persons the split-person
plant will use always get a second court for their second case). Then,
in a fixed draw order per case:

1. **Type and charges.** `felony` (45%) or `misdemeanor`; one (55%),
   two (30%), or three charges from the curated
   `data/reference/synthetic_offenses.csv` — the lead charge from the
   case type's severity class, add-ons from any class for felonies. All
   charges are filed with the case.
2. **Assignment.** An initial assignment to a judge serving at the
   court, within two days of filing, drawn by the case's observable risk
   index and the serving judges' docket tilts ("Planted effects"); an
   arraignment one to five days later; a pretrial decision within three
   days of that (business hours throughout).
3. **Pretrial decision.** A statutory release in 10% of cases
   (`actor = legislature_or_mandatory_rule`, `discretion = mandatory`,
   `release_type = statutory`, no judge); otherwise the assigned judge
   decides (`actor = judge`, `discretion = discretionary`): a release
   with the logistic probability of "Planted effects" (the case's
   observable features plus the judge's leniency), split into a
   `recognizance` or a posted `monetary_bond`, or a refusal, split into an
   unposted `monetary_bond` (the defendant stays `detained`) or a
   `detained`. A bond's amount comes from the schedule by the lead
   charge's severity. Released defendants get zero to two conditions.
4. **Disposition.** Sixty to 540 days after the decision for felonies,
   twenty to 240 for misdemeanors, along one of four tracks: a plea
   (55%: the lead charge `convicted_plea`, other charges dismissed by
   the prosecutor or pleaded), a prosecutor's dismissal of every charge
   (18%), a judge's dismissal of every charge (7% plus the judge's
   dismissal bias), or a trial (12%: each charge `convicted_verdict` or
   `acquitted` by the jury). Every charge records its `disposition` and
   `disposition_actor` (`judge` for pleas and judicial dismissals,
   `prosecutor`, `jury`).
5. **Reassignment.** In 20% of cases a second judge takes the case on a
   day between the pretrial decision and the disposition; a case is also
   reassigned whenever its judge's service at the court ends. Every
   event, decision, and sentence carries the judge assigned at that
   instant; assignment intervals are half-open (`start_at <= t <
   end_at`) and hand off at one instant.
6. **Sentence.** When any charge is convicted, a sentence zero to sixty
   days after the disposition (strictly after it) by the judge assigned
   then: incarceration days, probation days, a fine, or combinations
   drawn by the lead convicted charge's severity and scaled by the
   judge's severity multiplier.
7. **Events** (the `events` stream): the arraignment; zero to three
   hearings at least seven days after the pretrial decision; in a
   released case, with the logistic probability of "Planted effects"
   (observable features, propensity, filing-age band, and the releasing
   judge's failure-to-appear effect), the first hearing thirteen days or
   more before the disposition (or a random day in that range when there
   is none) becomes a `failure_to_appear` (`actor = defense`, the
   defendant) followed by a `bench_warrant` one to ten days later; a
   `trial` for the trial track; a `plea_hearing` or dismissal `hearing`
   at the disposition; a `sentencing_hearing`; and, for a share of
   probation sentences growing with propensity, a `revocation` thirty
   days or more after sentencing (after the case closed).
8. **Closing and the corpus end.** A case closes at its sentence or, if
   none, its disposition. Everything at or after the corpus end
   (`ScaleSpec.corpus_end_at`, midnight after 31 December of the last
   year) is removed the way an export taken on that date would show it:
   the case is `open` with no `closed_date`, its charges `pending`, its
   last assignment open-ended, later events absent, a release not yet
   posted shown as `detained`.

## Planted effects

`GENERATOR_VERSION` 3 (Phase 4 Step 1) gives the world a known answer:
per-judge effects on the release decision and on two later outcomes,
and case-mix confounding that makes raw rates mislead, planted so that
adjusting for observable case features recovers the effects
(`src/judgemetrics/synthetic/effects.py`; every constant below is
recorded in `truth/effects.json` under `parameters`).

**Risk features and the risk index.** At a case's filing the generator
reads, from the person's corpus records strictly before the start of the
filing day (00:00 UTC — the instant the analytic frame's `cases.filed_at`
carries; the corpus holds no earlier history, so a first case has none):
the lead charge's severity (code 4 for `felony_1` down to 0 for
`misdemeanor_b`), the charge count (1, 2, 3+ → 0, 1, 2), prior cases (0,
1, 2, 3+), prior convictions (other cases with a conviction disposed
before the filing: 0, 1, 2+), prior failures to appear (0, 1+), and a
pending case (another case filed earlier and not disposed by the filing:
0, 1) — the resolution Phase 4 Step 2's feature specification adopts.
The risk index is `R = 0.25·severity + 0.20·charges + 0.35·prior cases +
0.30·prior convictions + 0.50·prior FTA + 0.40·pending`. Nothing else
enters it: never the propensity, the age, or the group, and never a row
at or after the filing (a property test rewrites a person's later cases,
events, and sentences and finds every earlier index unchanged).

**Judge effects** (the `effects` stream, judges in code order): `leniency`
uniform on (−1.8, 1.8) in release log-odds, `new_case_effect` on (−3.0,
3.0) in the next filing's skew exponent, `fta_effect` on (−1.2, 1.2) in
failure-to-appear log-odds, and a raw docket tilt on (−2.5, 2.5).
Within each court (a judge's first service record) the raw tilts are
reassigned in descending order to the judges in ascending order of
`new_case_effect`, so the judge whose released defendants are least
likely to file again draws the riskiest docket: **planted confounding**.

**Assignment.** The initial judge is a weighted choice among the judges
serving the court that day with weight `exp(docket_tilt · R)`; planned
and forced reassignments are unchanged. Assignment reads observable
features only, which is what makes the judges comparable after
adjusting on them.

**Release** (a judge's discretionary decision):
`logistic(r0[case type] + r·x + leniency)` with `r0` = 1.6 (felony), 2.4
(misdemeanor) and `r` = −0.30 per severity code, −0.20 per extra charge,
−0.25 per prior case, −0.30 per prior conviction, −0.80 for a prior
failure to appear, −0.50 for a pending case. A release is a recognizance
(45% of felony and 70% of misdemeanor releases) or a posted bond; a
refusal is an unposted bond (45% / 55%) or a detention.

**Failure to appear** (a released case):
`logistic(−2.0 + f·x + 1.5·propensity + a[band] + fta_effect)` with `f`
= −0.05 per severity code, 0.10 per extra charge, 0.15 per prior case,
0.10 per prior conviction, 0.80 for a prior failure to appear, 0.30 for
a pending case; `fta_effect` is the releasing judge's (none for a
statutory release).

**Next filing.** When the allocation gives the person another case, it
is filed `int(U^k · (span + 1))` days into its span (`U` uniform on
[0, 1), the span from fourteen days after the previous case's pretrial
decision to the latest day that leaves room for the person's later
cases) with `k = max(0.25, 0.6 + 3.0·R + 2·propensity + b[band] +
new_case_effect)`, `R` being the previous case's risk index and the
effect its releasing judge's (none unless a judge released the person):
a larger `k` files sooner. The risk term is a judgement call beyond the
step's literal formula (`k0 + 2·propensity + b[band] + effect`): without
an observable term the filing time reads nothing the docket tilt
selects on, and the raw new-case rates ranked the planted effects as
well as any adjustment could (Spearman 0.83-0.94 across seeds), leaving
nothing for Step 3's adjustment to correct.

**The age effects** (`a` on the failure-to-appear log-odds, `b` on the
exponent) are by the band of the age at the index case's filing — the
band the connector publishes, not the band drawn at the corpus start:
18-24 +0.60 / +0.60, 25-34 +0.30 / +0.30, 35-44 0 / 0, 45-54 −0.30 /
−0.20, 55+ −0.60 / −0.40. The generator always knows the true age, so
the band of a person whose date of birth the source withholds is still
drawn from the true age (the connector publishes `unknown` for it); the
ambiguous same-date-of-birth plant rewrites a date of birth after the
simulation, so its second person's published band can differ from the
band its draws used.

**Calibration.** The magnitudes were set by sweeping the demo world
(seed `20260916`) and five to seven other seeds so that the oracle
ratios rank the court-centered effects with Spearman at least 0.9 for
the release target and 0.8 for the 365-day new-case and
failure-to-appear targets, the oracle's expected totals match the draws
within 10%, at least one same-court judge pair's raw 365-day new-case
rates rank opposite to their effects, and the raw new-case rates rank
the effects clearly worse than the oracle does (demo seed: release
0.944, new case 0.846, failure to appear 0.933; totals within 1.6%; raw
new-case ranking 0.716). `tests/unit/test_synthetic_effects.py` asserts
the first four on the demo world.

### Recovery

`tests/golden/test_golden_recovery.py` (Phase 4 Step 3) checks that the
published estimator — the outcome model, the pooled observed-to-expected
ratio, and its bootstrap interval, computed by the very function
`metrics compute` publishes from — recovers the planted answer. It builds
the demo world in memory (seed `20260916`), fits the three targets the
specification's `recovery` block names (release; 365-day new case;
365-day failure to appear) with `fit_frame`, and compares, over the judges
with at least 30 members in the ratio (20, 19, and 19 of the 24 judges),
against `compute_effects` on the same world. The tolerances were set by
running the test once, below the values measured, and are recorded in
`data/reference/outcome_model.yaml` (`recovery`; a tolerance alters no
model or figure, so the specification's `version` stays 1):

| Check (tolerance)                                                 | Release | New case 365 | Failure to appear 365 |
|-------------------------------------------------------------------|---------|--------------|-----------------------|
| Spearman, log pooled ratio vs centered effect (0.9 / 0.7 / 0.9)   | 0.934   | 0.719        | 0.963                 |
| Spearman, raw rate O / n vs centered effect (must be lower)       | 0.689   | 0.716        | 0.871                 |
| Spearman, the oracle ratio (the ceiling; Step 1)                   | 0.944   | 0.846        | 0.933                 |
| Pearson, expected counts vs the oracle's `sum(p0)` (0.95)          | 0.999   | 0.995        | 0.986                 |
| Sign agreement for \|centered effect\| > 0.85 (every judge)        | 5 of 5  | 13 of 13     | 5 of 5                |
| Intervals covering the true ratio `sum(p) / sum(p0)` (0.55)       | 0.60    | 0.63         | 0.68                  |
| Gamma shape α (pooling weight of a judge with E = α)              | 44.9    | 23.0         | 14.4                  |

Three findings, recorded where they act:

- **The new-case adjustment barely beats the raw rates** (0.719 against
  0.716). The planted docket tilt confounds the raw new-case rates only
  mildly, and the next filing depends mostly on the latent propensity no
  record carries, so the model's expected counts — calibrated on the
  observable features — cannot sharpen the ranking much (the oracle, which
  sees the propensity, reaches 0.846). The test asserts the strict
  inequality the step requires; Step 4's validation report states the
  margin.
- **The sign threshold is 0.85, not 0.5.** At 0.5 one 365-day new-case judge
  with a centered effect of 0.81 disagrees in sign — 9 observed against
  11.6 expected — which is sampling noise in a cohort of 54, not a fault
  of the estimator.
- **The intervals under-cover the true ratio** (60–68%, not 95%). The
  interval is the bootstrap distribution of the *pooled* estimate, which
  is shrunk toward 1, so for a judge whose true ratio lies far from 1 the
  interval is centered between the truth and 1 and often misses the truth
  (most misses are judges with strong negative effects, just below the
  lower bound); and a judge alone in a court (J-0001) has an expected count
  that the court feature fits to its observed count in every replicate, so
  its interval is a fraction of a percent wide around a ratio the penalty
  leaves at 0.997 against a true 1.000. The interval quantifies the pooled
  estimate's sampling variability, not a confidence interval for the
  judge's true ratio; Step 4's validation report and methodology 1.0 must
  say so.

**On the database path** (Phase 4 Step 4). `judgemetrics validation
recovery --truth data/synthetic/20260916` reads the figures `metrics
compute` published for the seeded demo database — after ingest, entity
resolution, and the snapshot — and finds exactly the in-memory values of
the table above (Spearman 0.934 / 0.719 / 0.963, expected-count Pearson
0.999 / 0.995 / 0.986, coverage 0.60 / 0.63 / 0.68, every sign agreeing):
entity resolution merges the split persons, so the persons the database
models are the world's. `docs/VALIDATION.md` "Recovery of the planted
effects" prints them beside the tolerances.

### Temporal transport

The temporal split (`docs/VALIDATION.md` "Summary") scores the last quarter
of the index events with a model fitted on the first three quarters. The
release model transports (test AUC 0.81, observed over expected 1.005,
slope 1.19); the failure-to-appear models moderately (AUC 0.54-0.68); the
new-case models do not (AUC 0.49-0.55, observed over expected up to 1.69 at
180 days, slopes from -0.04 to 0.60). Phase 4 Step 2 recorded a hypothesis
to test: the generator allocates each person's case count up front, so late
index events have fewer later cases left. Step 4 tested it on the demo
world's 365-day new-case design (per calendar year of the release):

| Year | Index events | With a later case | Median days to it | Within 365 days, of those | Observed rate |
|------|--------------|-------------------|-------------------|---------------------------|---------------|
| 2016 | 279          | 0.416             | 688               | 0.422                     | 0.179         |
| 2018 | 347          | 0.447             | 336               | 0.516                     | 0.233         |
| 2020 | 363          | 0.441             | 254               | 0.581                     | 0.256         |
| 2022 | 437          | 0.368             | 107               | 0.832                     | 0.307         |

The hypothesis holds only weakly and in the other direction from the one
that matters: the share of index events with any later case falls a little
(0.44 to 0.37), but the gap to that case shrinks from 688 to 107 days,
because the next filing is placed within the person's remaining corpus span
(`earliest day + int(U ** k × (span + 1))`), so late in the corpus it lands
soon. The 365-day new-case rate therefore rises with calendar time (0.18 to
0.31). The published fit carries the calendar year and absorbs the trend
(its mean prediction matches the observed rate within every year, the
report's "Temporal transport" tables); the temporal split cannot, because a
test year unseen in training is scored at the last training year's level,
which lies below the trend — hence observed over expected above 1 and a low
slope. The up-front allocation shows instead in the coefficients: a person
with three prior cases (the most a person can have before a fourth) has
`prior_cases=3+` at -1.56 in the 365-day new-case model, every replicate
agreeing in sign. Both are properties of the generator, not of the
estimator; the specification is not tuned to them (any change would bump
its `version`), and a real source's trend is what Phase 6's real-data
validation measures.

The failure-to-appear rates show no such trend (0.29-0.35 a year), which is
why those models transport better.

## Restricted controls

- **`age_band`** — the positive control. The age at filing moves both
  later outcomes (above), and no model feature carries it (the Phase 4
  specification excludes every restricted attribute), so subgroup
  calibration by age band must show the model's residual (Phase 4 Step 4).
- **`synthetic_group`** (`group_a`, `group_b`, `group_c`, equally likely)
  — the negative control, an abstract attribute drawn per person on the
  `attributes` stream after the persons and read by no draw, so its
  subgroup calibration must show nothing.

**How they read in the report** (`docs/VALIDATION.md` "Subgroup
calibration", the demo seed; `tests/unit/test_subgroup_calibration.py`
asserts the same on the world built in memory, where the figures are
identical). Every cell has at least 30 index events and 5 expected events,
so none is withheld on the demo seed (on the golden fixture every cell is).

- The positive control shows the planted direction for both outcomes: at 365
  days the failure-to-appear O/E runs from 1.29 (18-24, interval
  1.10-1.45) to 0.74 (55+, 0.59-0.89), the new-case O/E from 1.17 to 0.84,
  and the ratios over the five known bands rank like the planted effects
  with Spearman 0.9 for both. The order is not strict: 45-54 sits slightly
  above 35-44 in both outcomes (0.98 against 0.95, and 1.01 against 0.94),
  within each other's intervals. Propensity is drawn independently of age,
  so this is sampling noise, and it repeats across the two outcomes and the
  nested windows because they share their persons. The test therefore
  asserts the direction at the extremes and a rank correlation of at least
  0.8, not a strict order. The `unknown` band (a withheld date of birth)
  has no planted level of its own; its new-case ratios sit near 0.75 with
  intervals that reach 1.
- The negative control is calibrated: every `synthetic_group` cell of every
  model lies in the specification's `negative_control_band` [0.8, 1.25] —
  0.88 (`group_c`, 30-day new case, interval 0.74-1.04) is the farthest
  from 1 — and so does every age cell of the release model, which no age
  effect enters.

Both are restricted: the connector publishes them only into
`restricted.party_attribute` (`docs/DATA_MODEL.md` "The restricted
schema"), as `age_band` (from `age_at_filing`, blank → `unknown`) and
`synthetic_group`; neither ever reaches a public table, a snapshot, a log
line, or a model feature.

Timestamps are timezone-aware UTC ISO 8601 (`2019-03-04T14:30:00+00:00`)
at minute resolution; dates are `YYYY-MM-DD`. The order is enforced by
construction and checked by the unit tests: filed < assignment start <
arraignment < pretrial decision < disposition ≤ closed; sentence after
disposition; bench warrant after failure to appear; revocation after
sentence; every subsequent event strictly after its index event.

## Source format

`<out>/source/`: UTF-8, `\n` newlines, a header row, one file each,
sorted by id; an empty string means missing; booleans are `true` /
`false`; lists are `;`-separated. Every column is filled from the
canonical model's point of view (`docs/DATA_MODEL.md`); Step 2's
connector maps these files onto the case-level drafts.

| File                | Columns |
|---------------------|---------|
| `courts.csv`        | `court_code`, `name`, `court_type` (`circuit`), `jurisdiction` (`Synthetic State`), `state_code` (`ZZ`) |
| `judges.csv`        | `judge_code`, `full_name`, `court_code`, `position`, `start_date`, `end_date` — one row per service record, so a judge with two records has two rows |
| `cases.csv`         | `case_number`, `court_code`, `case_type`, `filed_date`, `closed_date`, `status` (`open` / `closed`), `related_case_number` (the split-person link) |
| `participants.csv`  | `participant_id`, `case_number`, `court_code`, `party_type` (`defendant`), `full_name`, `date_of_birth`, `age_at_filing` (whole years; blank when the date of birth is withheld, `GENERATOR_VERSION` 3), `synthetic_group` (`GENERATOR_VERSION` 3; the restricted negative control) |
| `charges.csv`       | `charge_id`, `case_number`, `court_code`, `participant_id`, `statute_code` (`SYN-###`), `description`, `offense_category`, `severity`, `violent_flag`, `filed_at`, `disposed_at`, `disposition`, `disposition_actor` |
| `assignments.csv`   | `assignment_id`, `case_number`, `court_code`, `judge_code`, `assignment_type` (`initial` / `reassignment`), `start_at`, `end_at` (empty while open) |
| `events.csv`        | `event_id`, `case_number`, `court_code`, `participant_id`, `judge_code` (the judge presiding), `event_type`, `event_at`, `actor`, `description` |
| `decisions.csv`     | `decision_id`, `case_number`, `court_code`, `participant_id`, `judge_code`, `decision_type`, `decision_at`, `actor`, `discretion`, `release_type`, `bond_amount`, `detained`, `release_at`, `conditions` — the release columns are filled for `pretrial_release` decisions only |
| `sentences.csv`     | `sentence_id`, `case_number`, `court_code`, `participant_id`, `judge_code`, `sentence_at`, `incarceration_days`, `probation_days`, `fine_amount`, `components` |

Decisions are per case: one `pretrial_release`; a `dismissal` per
dismissing actor (`prosecutor` with `discretion = non_judicial`, or
`judge` with `discretionary`); a `disposition` when any charge was
convicted or acquitted (`judge` accepting a plea, or `jury` for a
verdict); a `sentencing` by the sentencing judge. Charge-level
dispositions and their actors are in `charges.csv`. A judge's
`judge_code` is present only on decisions the judge made: a statutory
release, a prosecutor's dismissal, and a jury verdict carry none.

The `duplicate_source_record` plant emits a case twice: the copy
follows the original in every file with the same ids, the case number
in lower case with spaces for dashes (`syn 2019 000013`), and the
participant's name in upper case with trailing whitespace — differences
the connector's normalization (`normalize_case_number`,
`normalize_person_name`, stripped ids) must collapse. No value ever ends
a line with whitespace, so the repository's whitespace hooks leave the
fixture untouched.

## Vocabulary

`synthetic/vocabulary.py` fixes the values (`CASE_VOCABULARY_VERSION =
3` since Phase 5 Step 3 added the Cook County values; 2 since Phase 4
Step 1 added the restricted vocabularies); Phase 2 Step 2 writes the
same values to `data/reference/case_vocabulary.yaml`, which must equal
these constants, and Phase 5's real connectors map onto them. The table
lists the values the synthetic world uses; version 3's additions (the
Illinois classes, `other` and `unclassified` categories, the non-final
`superseded` and `transferred`, and the Cook County events, decisions,
sentence values, `unstated` position, and the restricted `race` and
`gender`) are in docs/DATA_MODEL.md "Vocabularies". The generator draws,
ranks, and codes only `SYNTHETIC_SEVERITIES` (the five below) and the
offense table's categories, and the truth's disposition distribution
iterates `FINAL_CHARGE_DISPOSITIONS`, so a value added for a real source
moves no draw and leaves the golden fixture byte for byte.

| Kind                                 | Values |
|--------------------------------------|--------|
| `case_type`                          | `felony`, `misdemeanor` |
| `case_status`                        | `open`, `closed` |
| `party_type`                         | `defendant` |
| `assignment_type`                    | `initial`, `reassignment` |
| `event_type`                         | `arraignment`, `hearing`, `failure_to_appear`, `bench_warrant`, `trial`, `plea_hearing`, `sentencing_hearing`, `revocation` |
| `decision_type`                      | `pretrial_release`, `dismissal`, `disposition`, `sentencing` |
| `judicial_discretion_classification` | `discretionary`, `mandatory`, `non_judicial`, `unknown` |
| `release_type`                       | `recognizance`, `monetary_bond`, `detained`, `statutory` |
| `charge_disposition`                 | `dismissed`, `acquitted`, `convicted_plea`, `convicted_verdict`, `pending` |
| `severity`                           | `felony_1`, `felony_2`, `felony_3`, `misdemeanor_a`, `misdemeanor_b` |
| `offense_category`                   | `drug`, `property`, `person`, `weapon`, `public_order`, `traffic`, `financial` |
| `justice_event_type`                 | `new_case`, `new_charge`, `reconviction`, `failure_to_appear`, `release_violation`, `revocation`, `rearrest` |
| `actor_type`                         | the brief's `ActorType` values verbatim (`judge`, `prosecutor`, `defense`, `jury`, `clerk`, `law_enforcement`, `legislature_or_mandatory_rule`, `appellate_court`, `unknown`); a unit test asserts they equal the enum |
| `position`                           | `circuit_judge`, `associate_judge` |
| `sentence_component`                 | `incarceration`, `probation`, `fine` |
| `release_condition`                  | `check_in`, `no_contact`, `travel_restriction`, `drug_testing`, `electronic_monitoring` |
| `restricted_attribute` (restricted)  | `age_band`, `synthetic_group` |
| `age_band` (restricted)              | `18-24`, `25-34`, `35-44`, `45-54`, `55+`, `unknown` |
| `synthetic_group` (restricted)       | `group_a`, `group_b`, `group_c` |

`non_judicial` marks a decision taken by a non-judicial actor (a
prosecutor's dismissal, a jury's verdict), for which a judicial
discretion classification does not apply; `unknown` marks a decision
whose actor the source does not name.

## Planted edge cases

After the clean world is built and identified, `edge_cases.py` plants
the following from the `edge_cases` stream, in this order, and records
each in `truth/planted.csv` (`kind`, `ids` as `key=value` pairs, and the
expected pipeline behaviour) and, for person pairs, in
`truth/resolution_expectations.csv`.

| Kind                           | Construction | What the pipeline must do |
|--------------------------------|--------------|---------------------------|
| `split_person`                 | One true person whose cases sit in two courts appears under a second participant id for the cases of the second court, with the same name and date of birth; the earliest case there cites the person's first case in `related_case_number`. | Step 3's rule stage decides `matched` (same name and date of birth plus a case link) and merges the two persons under one `public_person_key`. |
| `ambiguous_person_same_dob`    | Two distinct persons given the same name and date of birth, with cases in disjoint courts and no shared case. When the world holds no two unused persons in disjoint courts (possible at `tiny` scale only; never in the golden fixture), a same-court pair is planted instead and `planted.csv` says so in its `expected_behaviour`. | Two `person` rows; the candidate pair is decided `review`, never merged automatically (the same-court fallback is queued by the rule stage's `name_dob_same_court`). |
| `ambiguous_person_missing_dob` | Two distinct persons given the same name, one with its date of birth blanked. | Two `person` rows; the candidate pair is decided `rejected` (reason `name_only`) — never merge on a name alone. |
| `duplicate_source_record`      | A case emitted twice, the copy with formatting differences only (see above). | The copy collapses onto the same `court_case` and child rows; the second source row is attributed; `data_quality_issue` `case_number_duplicate` (info). |
| `missing_dob`                  | A person whose every participant row has an empty `date_of_birth`. | The person resolves by participant id; no candidate is matched on the name alone. |
| `missing_judge`                | A pretrial decision with no `judge_code`, `actor = unknown`, `discretion = unknown` (the release columns stay). | Published with `actor_type = unknown`; excluded from every judge-attributed metric; `data_quality_issue` `missing_judge_on_decision` (warning). |
| `missing_disposition`          | A charge of a closed case with empty `disposition`, `disposed_at`, and `disposition_actor` (never the only conviction behind a sentence). | Published with a null disposition; excluded from disposition metrics; `data_quality_issue` `missing_disposition` (info). |
| `missing_description`          | A court event with an empty `description`. | Published with a null description; no issue. |

Quantities: `duplicate_source_records`, `split_person_pairs`, and
`ambiguous_person_pairs` (alternating between the two ambiguous kinds,
the same-date-of-birth kind first) from the `ScaleSpec`;
`round(missing_dob_share × persons)`, `round(missing_judge_share ×
judicial pretrial decisions)`, `round(missing_disposition_share ×
charges of closed cases)`, and `round(0.02 × court events)`
(`MISSING_DESCRIPTION_SHARE`, the same at every scale), each at least
one when the share is positive. Plants never overlap: a person or case
used by one plant is not used by another, and the missing-data plants
skip duplicated cases so the copy stays a faithful copy. The unit test
recomputes every quantity from the source files and compares it with
`planted.csv`.

Names are unique across the world except for these planted collisions,
so the candidate pairs Step 3 generates (blocking on a shared name or
participant id) are exactly the pairs `resolution_expectations.csv`
lists.

## `truth/`

`truth/` documents the simulation. It is written beside `source/`, it is
never read by any connector (Step 2 discovers `source/` only), and it
never enters the database. `TRUTH_VERSION` is `3` (Phase 4 Step 1:
exposure deferred by every incarceration term of the person, and
`effects.json`; version `2`, Phase 3 Step 2, added the windowed cohorts
of every index kind, below); `GENERATOR_VERSION` is `3` (the planted
effects and the restricted controls; version `2` added `corpus.start`
and `corpus.end` to the manifest, the first and last day a case can be
filed, which the synthetic connector reports as the source's coverage
window).

| File                          | Columns / contents |
|-------------------------------|--------------------|
| `persons.csv`                 | `true_person_id`, `participant_id`, `court_code` — the true identity behind every participant id in every court (a split person has two rows with different participant ids). |
| `subsequent_events.csv`       | `true_person_id`, `index_case_number`, `index_event_type` (`pretrial_release` with `index_at` = the release time of a released pretrial decision, `disposition`, `sentence`), `index_at`, `outcome_type` (`new_case`, `new_charge`, `reconviction` — in another case of the person; `failure_to_appear`, `revocation` — any case), `outcome_at`, `days_after`. One row per distinct (index event, outcome type, outcome time), strictly after the index; `days_after` is the smallest whole number of days *d* with `outcome_at <= index_at + d days`, so an outcome is inside window *w* exactly when `days_after <= w`, and it is always at least 1. |
| `resolution_expectations.csv` | `left_participant_id`, `right_participant_id` (ordered), `expected_decision` (`matched` / `rejected` / `review`), `reason`. |
| `planted.csv`                 | `kind`, `ids`, `expected_behaviour` (above). |
| `metrics.json`                | `truth_version`, `generator_version`, `seed`, `scale`, `corpus` (`start`, `end`, `end_exclusive_at`), `windows_days`, `index_kinds`, `observable_outcomes`, `not_observable` (`outcome`, `reason`), `definitions` (every metric's definition string), and the metric set under `judges.<judge_code>` and `courts.<court_code>`. |
| `effects.json`                | The planted effects and the oracle (`TRUTH_VERSION` 3, below). Aggregates per judge, court, and band only — never a per-person row. |
| `README.md`                   | How to read the files; the count of planted items per kind; for scales with at most 100 planted items (golden, tiny) the full hand-checkable list; the metric definitions. |

### The planted effects and the oracle (`effects.json`)

`truth_version`, `generator_version`, `seed`, `scale`, `windows_days`,
`definitions` (the prose of every block), and:

- `parameters` — every constant of "Planted effects": the effect ranges,
  the features and their codes, the risk weights, the release,
  failure-to-appear, and next-filing forms, and the age effects.
- `judges.<J-code>` — `courts`, `leniency`, `new_case_effect`,
  `fta_effect`, `docket_tilt`, `centered` (each effect minus the
  decision-weighted mean of its courts' means: the effect the ratios
  rank), and `decisions_by_court` (the judicial discretionary release
  decisions the generator drew for the judge per court, the weights).
- `courts.<C-code>` — `mean` (the case-weighted mean of each effect over
  the judges who drew the court's judicial release decisions) and
  `decisions_by_judge`.
- `targets.pretrial_release.judges.<J-code>` — over the judge's
  attributed discretionary decisions: `decisions`, `released`,
  `expected` (the sum of `p = logistic(base + leniency)` times the chance
  the release takes effect before the corpus end), `expected_centered`
  (the same with the court's mean leniency: `sum(p0)`, the centered
  oracle), `oracle_ratio` (`released / expected_centered`), and
  `true_ratio` (`expected / expected_centered`).
- `targets.new_case` and `targets.failure_to_appear` — per window of the
  six and judge, over `metrics.json`'s pretrial-release cohort under the
  Phase 3 cohort and follow-up rules: `cohort`, `followed`, `observed`
  (the fixed-window numerator), `expected` and `expected_centered` summed
  over the followed members, `oracle_ratio`, and `true_ratio`. A member's
  `p` is the probability of its outcome in `(exposure_start,
  exposure_start + w]` under the generator's draws, given the realized
  exposure start: for `new_case`, 0 without a next case, else the exact
  chance the next filing (its day from the skewed draw, then a business
  minute) falls in the window, plus the chance it falls before the
  exposure start times whether a later case was filed in the window; for
  `failure_to_appear`, `1 - (1 - q)(1 - o)` with `q` the own draw's
  probability times the chance its date falls in the window and `o` = 1
  when another case of the person records a failure to appear there.
  Other cases' outcomes enter as realized, so the oracle is exact for the
  draws the judge's effect enters and unbiased in total (the unit test's
  10% tolerance).
- `controls` — the age effects by filing-age band (the positive
  control) and the `synthetic_group` values with `feeds_no_draw` (the
  negative control).

A unit test holds every cohort and observed count equal to
`metrics.json`'s for the same judge and window, on the demo, golden, and
committed golden worlds; a property test proves the draw probabilities
lie strictly inside (0, 1) and that zeroing every judge effect makes `p`
equal `p0`.

### The metric set (`metrics.json`)

Per subject (each judge, each court), computed from the planted world
with duplicate copies counted once and the attribution gate applied
exactly as the metric definitions state (the `definitions` block
carries the same text):

- `eligible_cases` — judge: cases with at least one assignment of the
  judge; court: cases filed in the court. `eligible_defendants` —
  distinct true persons among them.
- `pretrial` — `decisions` (pretrial decisions with `actor = judge`,
  `discretion = discretionary`, attributed to the judge who decided or
  to the court decided in; statutory releases and unknown-actor
  decisions are excluded), `released_count` (`detained = false`),
  `detained_count`, `release_share` (numerator, denominator, value), and
  for courts `statutory_release_count` and `unknown_actor_count`.
  `windows` is the same object as `index_events.pretrial_release.windows`
  below, kept for continuity with `TRUTH_VERSION` `1`.
- `index_events.<pretrial_release|disposition|sentence>.windows.<30|90|180|365|730|1095>`
  (`TRUTH_VERSION` `2`) — the windowed cohort of each index kind exactly
  as `docs/METHODOLOGY.md` states: `pretrial_release` members are the
  attributed released decisions (`index_at = release_at`);
  `disposition` members are the disposed cases at the case disposition
  time, attributed to the judge assigned at that time (court: the
  court's disposed cases), one per defendant; `sentence` members are the
  attributed sentences at `sentence_at`. Exposure (`TRUTH_VERSION` 3,
  methodology 0.2) starts at the index time — for the `disposition` kind
  at the end of the index case's own incarceration term when it has one
  — and then moves past every incarceration term `[sentence_at,
  sentence_at + incarceration_days)` of the person, in any case, that
  contains it (`truth.deferred_start`, written independently of the
  engine's `metrics/exposure.py`). Per window `w`:
  `cohort`, `followed` (`exposure_start + w days` strictly before
  `corpus.end_exclusive_at`), `<outcome>_rate` (`numerator`,
  `denominator` = followed, `value`) and `<outcome>_survival` (`value` =
  `1 - S(w)` at six decimals from the Kaplan–Meier product-limit survival
  over the whole cohort, events counted before censorings at a tie,
  `S = 0` once every member at risk fails; `events` at or before `w`,
  `censored` strictly before `w`, `at_risk` the rest,
  `standard_error` (Greenwood), `lower`, `upper` (symmetric 95%,
  clipped)) for every outcome in `observable_outcomes`:
  `failure_to_appear`, `new_case`, `new_charge`, `reconviction`,
  `revocation`. `new_case`, `new_charge`, and `reconviction` count only
  in another case of the person; the other two in any case.
  `release_violation` and `rearrest` are listed under `not_observable`
  ("the synthetic source records no such event") and no rate is
  computed for them.
- `judicial_dismissal_rate` — charges dismissed with
  `disposition_actor = judge` over charges with a disposition other
  than `pending` or missing; judge: charges whose `disposed_at` falls in
  one of the judge's assignment intervals; court: the court's charges.
  `disposition_distribution` counts the denominator by disposition.
- `median_days_to_disposition` — `n` and the median of (case
  disposition date − `filed_date`) in whole days over disposed cases,
  the case disposition being the latest `disposed_at` of its disposed
  charges; judge: cases where the judge was assigned at that time.
- `sentences` — `count`, `incarceration_days_median`,
  `probation_days_median` (`n`, `value`, over non-empty values), and
  `incarceration_days_median_by_offense_category`, grouped by the
  offense category of the case's lead convicted charge (most severe by
  severity rank, ties by `charge_id`).

Every rate carries `numerator`, `denominator`, and `value` (`null` when
the denominator is zero); a unit test asserts no numerator exceeds its
denominator, that every survival estimate is bounded and nested across
windows and equals the fixed-window rate when every member is followed,
and recounts the simplest metrics from the source files. The metrics
engine reproduces every value exactly: `tests/unit/test_metrics_compute.py`
over the in-memory golden world and `tests/golden/test_golden_metrics.py`
over the golden fixture in the database, both through the truth-path
table in `tests/golden/truth_map.py`. The truth arithmetic imports
nothing from `judgemetrics.metrics`: it is the independent oracle.

Each truth entry maps to a registry slug
(`data/reference/metric_registry.yaml`, Phase 3 Step 1;
`docs/METHODOLOGY.md`), and a unit test holds the prose of the pretrial
and dismissal entries equal to the truth's `definitions` text unless the
entry states the difference in a `truth_note`:

| Truth entry                                   | Registry slug                                                          |
|-----------------------------------------------|------------------------------------------------------------------------|
| `eligible_cases`, `eligible_defendants`       | `eligible_cases`, `eligible_defendants`                                |
| `pretrial.decisions`                          | `pretrial_decisions`                                                   |
| `pretrial.released_count`, `.detained_count`  | `pretrial_released`, `pretrial_detained`                               |
| `pretrial.release_share`                      | `pretrial_release_share`                                               |
| `pretrial.statutory_release_count`            | `statutory_release_count` (court only)                                 |
| `pretrial.unknown_actor_count`                | `unknown_actor_pretrial_count` (court only)                            |
| `index_events.pretrial_release.windows.<w>.<outcome>_rate` (= `pretrial.windows`) | `failure_to_appear_rate`, `new_case_rate`, `new_charge_rate`, `reconviction_rate`, `revocation_rate` (`window_days` = `w`; `cohort` is the observation's `eligible_count`, `followed` its `cohort_size`, `numerator` its `observed_count`, `value` its `observed_rate`) |
| `index_events.pretrial_release.windows.<w>.<outcome>_survival` | `failure_to_appear_survival`, `new_case_survival`, `reconviction_survival` (`value` is `observed_rate`, `events` is `observed_count`, `cohort` is both `cohort_size` and `eligible_count`, `lower`/`upper` the bounds) |
| `index_events.disposition.windows.<w>.<outcome>_rate` | `new_case_rate_after_disposition`, `new_charge_rate_after_disposition`, `reconviction_rate_after_disposition`, `revocation_rate_after_disposition` |
| `index_events.sentence.windows.<w>.<outcome>_rate` | `new_case_rate_after_sentence`, `new_charge_rate_after_sentence`, `reconviction_rate_after_sentence`, `revocation_rate_after_sentence` |
| `judicial_dismissal_rate`                     | `judicial_dismissal_rate`                                              |
| `disposition_distribution`                    | `disposition_distribution` (one observation per `disposition` value)   |
| `median_days_to_disposition`                  | `median_days_to_disposition` (`n` is the `cohort_size`)                |
| `sentences.count`                             | `sentence_count`                                                       |
| `sentences.incarceration_days_median`, `.probation_days_median` | `incarceration_days_median`, `probation_days_median` |
| `sentences.incarceration_days_median_by_offense_category` | `incarceration_days_median_by_offense_category` (one observation per `offense_category`) |

The registry's `release_violation_rate` and `rearrest_rate` have no
truth entry: their outcomes are under `not_observable`, the engine
publishes no observation for them on the synthetic source, and the
golden suite asserts exactly that. The frame's property tests
(`tests/property/test_frame_invariants.py`) prove the pretrial-release
cohorts, followed counts, and numerators equal `truth.py` on every
in-memory `TINY` world the profile draws.

## Property invariants (`tests/property/`)

The brief's property tests (`<testing_strategy>`) run with Hypothesis
over generated datasets (Phase 2 Step 5; `HYPOTHESIS_PROFILE=ci` draws
50 examples per test, the local `dev` profile 20). Strategies draw
seeds, draft orderings, and case-number formatting variants only; every
name still comes from the word lists, and a failing example prints the
seed and the scale, never a restricted value. The invariants, each
checked on the generated files and again on the drafts the synthetic
connector produces from them:

- **A subsequent event never precedes its index event**
  (`test_event_ordering.py`, `tiny` and `golden`): every
  `truth/subsequent_events.csv` row has `outcome_at > index_at` and
  `days_after >= 1`, with `days_after` the smallest whole number of days
  covering the gap; every charge is disposed on or after its filing;
  every sentence follows its case's disposition; every decision lies
  inside its case's filed/closed window; every derived `new_case` or
  `reconviction` justice event has an earlier filing or disposition in
  another case of the same person.
- **Case-number normalization is format-insensitive and idempotent**
  (`test_case_numbers.py`): inserted separators at segment boundaries,
  case changes, and leading or trailing separators normalize to the
  same key; a key normalizes to itself; a key holds only upper-case
  alphanumerics and single hyphens.
- **Identical deterministic identifiers resolve consistently**
  (`test_resolution_consistency.py`, integration): `resolve_persons`
  over the participant drafts in two Hypothesis-drawn orders — the
  second including the planted duplicate row — yields the same person
  per participant hash and creates nothing the second time; equal
  `source_participant_id` hashes are exactly the pairs that share a
  person, and `lookup_by_identity` returns the same map.
- **The planted effects' oracle is well formed**
  (`test_effects_invariants.py`, `tiny`): every draw probability lies
  strictly inside (0, 1) and every window probability inside [0, 1];
  zeroing every judge effect makes `p` equal `p0` for every target,
  judge, and window; and a case's risk index never changes when a later
  case, event, or sentence of the person changes.
- **Rerunning an ingestion produces no duplicates**
  (`test_ingest_idempotent.py`, integration, five derandomized seeds):
  after the first ingest every row of the dataset's own
  `truth/resolution_expectations.csv` holds; the second ingest of the
  same dataset parses nothing, creates and updates zero rows in every
  canonical table (row counts and the latest `updated_at` per table
  unchanged), and writes zero candidates and zero source records.

The integration properties run inside one rolled-back transaction per
example on the scratch test database (`CONTRIBUTING.md`, "Tests").

## The word-list rule

`synthetic/wordlists.py` holds `GIVEN_TOKENS` (colours, minerals,
weather) and `FAMILY_TOKENS` (trees, birds, rivers), at least 150 each,
dictionary words only, plain ASCII letters, capitalised. Words that
double as common real given names or surnames (Amber, Hazel, Ruby,
Rose, Robin, Martin, Hudson, Jordan, Willow, Rowan, Jasper, Flint, …)
were left out when the lists were written, and the lists are reviewed
in any pull request that changes them. Judges and persons draw from the
same lists; a name round-trips through `normalize_person_name`
unchanged apart from case, so judge names need no prefix stripping. A
unit test asserts that every name token in the golden fixture and in a
demo run is in the lists and that names are unique except for the
planted collisions.

## Regenerating the golden fixture

The fixture (`tests/fixtures/golden/`, seed 7, scale `golden`) is
regenerated, never hand-edited, whenever `GENERATOR_VERSION` or
`TRUTH_VERSION` changes:

```sh
uv run judgemetrics synthetic generate --seed 7 --scale golden --out tests/fixtures/golden --force
uv run judgemetrics synthetic verify tests/fixtures/golden
uv run detect-secrets scan --baseline .secrets.baseline tests/fixtures/golden/manifest.json
uv run pytest tests/unit/test_synthetic_generator.py tests/unit/test_cli_synthetic.py
```

`detect-secrets` flags the manifest's 64-character hashes as
high-entropy strings; they are file digests, not credentials, and the
baseline records them the way the repository's lockfile hashes are
excluded. Scan only the manifest (a whole-repository scan would add the
lockfiles the hook excludes), and on Windows replace the backslashes in
the baseline's `filename` entries with forward slashes so the hook
matches on Ubuntu CI. Update `tests/fixtures/golden/README.md` if the
counts it lists changed, and record the bump in `docs/ROADMAP.md`.

## Known limitations

- One defendant per case; all charges are filed with the case; no
  charge is added or amended later.
- `age_at_filing` is withheld with `date_of_birth` (`GENERATOR_VERSION`
  3); a source that carries an age without a birth date is Phase 5's
  concern.
- A revocation is recorded after its case closed (the case does not
  reopen); a bench warrant may be absent when the corpus ends within
  ten days of the failure to appear.
- Time at risk is deferred by every incarceration term the source
  records (`TRUTH_VERSION` 3, methodology 0.2); a term served elsewhere is
  not modelled — the same documented limitation as the metrics engine's,
  so the two agree. The generator itself lets a person be released, and
  file again, while a term of another case runs; the deferral is what
  keeps such time out of the risk window.
- The oracle's `p` counts other cases' outcomes as realized (above), so
  it is exact for the draws a judge's effect enters and unbiased in total,
  not a closed form for every path of the simulation.
- `new_case` is the case's `filed_at`, a business-hour instant the
  source publishes only through its charges (`cases.csv` carries the
  date); the engine derives it as the earliest charge filing of the case,
  which equals `filed_at` because every charge is filed with the case.
- The `missing_description` share is a package constant rather than a
  `ScaleSpec` field.
- Synthetic judges never link to FJC judges, and the synthetic world is
  one state-level jurisdiction; there is no federal court and no scale
  beyond `demo`.
- A person's next filing is placed within the remaining corpus span, so
  the new-case rate rises toward the corpus end (0.18 to 0.31 at 365 days,
  "Temporal transport"): a model fitted on early years under-predicts later
  ones. The calendar-year feature absorbs it in the published fit; the
  temporal split's diagnostics show it. No real source is expected to share
  the artifact.
