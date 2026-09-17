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
  stream — `world`, `persons`, `cases`, `events`, `edge_cases` — from
  `sha256(f"{seed}:{name}")`, so adding a draw to one stage cannot move
  another stage's output. The helpers in `rng.py` (`randint`, `choice`,
  `weighted_choice`, `shuffled`, `sample`, `skewed_fraction`) call only
  `Random.random()`, the one method whose sequence Python guarantees
  stable across versions for a given seed.
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
fixture. `tiny` exists for property tests and smoke runs. A `ScaleSpec`
validates itself: at least one judge per court, at least as many cases
as persons, at most four cases per person, room for every plant.

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
records). Each judge carries three latent tendencies that later phases
can test against (Phase 4's planted effects): a release bias added to
the recognizance share, a dismissal bias added to the
judicial-dismissal share, and a severity multiplier on incarceration
lengths.

**Persons.** Each person has a true identity (`P-`), a unique composed
name, a date of birth drawn inside an age band (18–24, 25–34, 35–44,
45–54, 55+ at the corpus start), a latent propensity (`random() ** 2`,
mean one third) that drives subsequent behaviour, and a home court.
Names are unique across judges and persons; only the edge-case planter
creates a collision, and it records it. Every person appears in one to
four cases: one each, then the extra cases distributed by propensity,
so subsequent cases exist and the demo's 3,200 persons carry 5,200
cases.

**Cases.** A person's cases are chronological: the first is filed on a
random day of the corpus (leaving room for later ones), each later one
at least fourteen days after the previous case's pretrial decision,
sooner for higher propensities. The first case sits in the home court;
later cases stay there 65% of the time (the persons the split-person
plant will use always get a second court for their second case). Then,
in a fixed draw order per case:

1. **Type and charges.** `felony` (45%) or `misdemeanor`; one (55%),
   two (30%), or three charges from the curated
   `data/reference/synthetic_offenses.csv` — the lead charge from the
   case type's severity class, add-ons from any class for felonies. All
   charges are filed with the case.
2. **Assignment.** An initial assignment to a judge serving at the
   court, within two days of filing; an arraignment one to five days
   later; a pretrial decision within three days of that (business hours
   throughout).
3. **Pretrial decision.** A statutory release in 10% of cases
   (`actor = legislature_or_mandatory_rule`, `discretion = mandatory`,
   `release_type = statutory`, no judge); otherwise the assigned judge
   decides (`actor = judge`, `discretion = discretionary`):
   `recognizance`, `monetary_bond` with an amount from the schedule
   (posted 75% of the time, else the defendant stays `detained`), or
   `detained`. Felonies are detained more; the judge's release bias
   moves the shares. Released defendants get zero to two conditions.
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
   hearings at least seven days after the pretrial decision; in a share
   of released cases growing with propensity, one hearing becomes a
   `failure_to_appear` (`actor = defense`, the defendant) followed by a
   `bench_warrant` one to ten days later; a `trial` for the trial
   track; a `plea_hearing` or dismissal `hearing` at the disposition; a
   `sentencing_hearing`; and, for a share of probation sentences
   growing with propensity, a `revocation` thirty days or more after
   sentencing (after the case closed).
8. **Closing and the corpus end.** A case closes at its sentence or, if
   none, its disposition. Everything at or after the corpus end
   (`ScaleSpec.corpus_end_at`, midnight after 31 December of the last
   year) is removed the way an export taken on that date would show it:
   the case is `open` with no `closed_date`, its charges `pending`, its
   last assignment open-ended, later events absent, a release not yet
   posted shown as `detained`.

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
| `participants.csv`  | `participant_id`, `case_number`, `court_code`, `party_type` (`defendant`), `full_name`, `date_of_birth`, `age_at_filing` (whole years; present even when the date of birth is missing, as sources often carry an age without a birth date) |
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
1`); Phase 2 Step 2 writes the same values to
`data/reference/case_vocabulary.yaml`, which must equal these
constants, and Phase 5's real connectors map onto them.

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
| `ambiguous_person_same_dob`    | Two distinct persons given the same name and date of birth, with cases in disjoint courts and no shared case. | Two `person` rows; the candidate pair is decided `review`, never merged automatically. |
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
never enters the database. `TRUTH_VERSION` is `1`.

| File                          | Columns / contents |
|-------------------------------|--------------------|
| `persons.csv`                 | `true_person_id`, `participant_id`, `court_code` — the true identity behind every participant id in every court (a split person has two rows with different participant ids). |
| `subsequent_events.csv`       | `true_person_id`, `index_case_number`, `index_event_type` (`pretrial_release` with `index_at` = the release time of a released pretrial decision, `disposition`, `sentence`), `index_at`, `outcome_type` (`new_case`, `new_charge`, `reconviction` — in another case of the person; `failure_to_appear`, `revocation` — any case), `outcome_at`, `days_after`. One row per distinct (index event, outcome type, outcome time), strictly after the index; `days_after` is the smallest whole number of days *d* with `outcome_at <= index_at + d days`, so an outcome is inside window *w* exactly when `days_after <= w`, and it is always at least 1. |
| `resolution_expectations.csv` | `left_participant_id`, `right_participant_id` (ordered), `expected_decision` (`matched` / `rejected` / `review`), `reason`. |
| `planted.csv`                 | `kind`, `ids`, `expected_behaviour` (above). |
| `metrics.json`                | `truth_version`, `generator_version`, `seed`, `scale`, `corpus` (`start`, `end`, `end_exclusive_at`), `windows_days`, `definitions` (every metric's definition string), and the metric set under `judges.<judge_code>` and `courts.<court_code>`. |
| `README.md`                   | How to read the files; the count of planted items per kind; for scales with at most 100 planted items (golden, tiny) the full hand-checkable list; the metric definitions. |

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
  `windows.<30|90|180|365|730|1095>`: `cohort` (attributed released
  decisions, `index_at = release_at`), `followed` (cohort members with
  `release_at + w days` strictly before `corpus.end_exclusive_at`), and
  `failure_to_appear_rate`, `new_case_rate`, `reconviction_rate` — each
  the followed members with at least one outcome of that type in
  `(index_at, index_at + w days]` over the followed cohort.
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
denominator and recounts the simplest metrics from the source files.
Phase 3's registry must reproduce these values exactly on the golden
fixture; disposition- and sentence-indexed windowed rates are derivable
from `subsequent_events.csv` and will join `metrics.json` under a new
`TRUTH_VERSION` when the registry defines them.

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
- `age_at_filing` is present even when `date_of_birth` is missing.
- A revocation is recorded after its case closed (the case does not
  reopen); a bench warrant may be absent when the corpus ends within
  ten days of the failure to appear.
- Windowed outcome rates in `metrics.json` are computed on the
  pretrial-release index only; the `subsequent_events.csv` rows for
  `disposition` and `sentence` index events carry what Phase 3 needs to
  extend them. Time at risk after a sentence (incarceration deferral) is
  not modelled in `truth/`.
- The `missing_description` share is a package constant rather than a
  `ScaleSpec` field.
- Synthetic judges never link to FJC judges, and the synthetic world is
  one state-level jurisdiction; there is no federal court and no scale
  beyond `demo`.
