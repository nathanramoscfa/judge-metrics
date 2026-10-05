# src/judgemetrics/ingest/cook_sao/excerpt.py
"""The committed real-row fixture (``tests/fixtures/cook_sao/``) by a stratified rule.

``select_cases`` walks the strata in a fixed order and, for each, chooses
the smallest ``CASE_ID`` (string order) not chosen yet that satisfies it;
a stratum no case satisfies is reported, never faked. The strata and their
thresholds come from the committed profile (``profile.yaml``): every
``CHARGE_DISPOSITION`` with at least 100 rows; the five commonest reasons
and the suppression-motion reason; each initial bond type and a null one;
each ``SENTENCE_PHASE`` but "Summary Charge Info"; each ``SENTENCE_TYPE``
with at least 1,000 rows; a diversion; an open case (initiated, no
disposition); a case with exactly two participants; a disposition without
a judge; a case received before 2011; a case received (initiated) on or
after 2023-09-18, the Pretrial Fairness Act regime; a charge with two
versions in Initiation, Dispositions, or Sentencing; then twelve sentenced and twelve disposed cases of the judge
with the most sentences, so a later end-to-end test meets an unsuppressed
judge figure (threshold 10).

Every predicate reads only the case's own rows, and every row of a chosen
case is kept, so excerpting the fixture itself chooses the same cases in
the same order: the smallest qualifying case of the full export is still
the smallest of the subset. ``write_excerpt`` then writes, per dataset in
artifact order, every row of the chosen cases with ``BLANKED_COLUMNS``
emptied (headers verbatim, the csv module both ways, LF), and a README
naming the rule, each case's strata, the blanked columns, the source
digests, and the counts — so a rerun over the same artifacts, or over the
fixture, writes identical bytes. Output paths are built from constants.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from judgemetrics.ingest.cook_sao.profile import (
    CHARGE_DATASETS,
    CORPUS_END,
    EARLIEST_EXPECTED_RECEIPT,
    PROFILE_PATH,
    ProfileError,
    parsed_date,
    scan,
)
from judgemetrics.ingest.cook_sao.schema import (
    BLANKED_COLUMNS,
    BOND_TYPE_INITIAL,
    CASE_ID,
    CHARGE_DISPOSITION,
    CHARGE_DISPOSITION_REASON,
    CHARGE_ID,
    CHARGE_VERSION_ID,
    JUDGE,
    PARTICIPANT_ID,
    RECEIVED_DATE,
    SENTENCE_JUDGE,
    SENTENCE_PHASE,
    SENTENCE_TYPE,
    VERIFIED_HEADERS,
)
from judgemetrics.ingest.cook_sao.sources import DATASETS
from judgemetrics.ingest.cook_sao.stored import LocalArtifact

FIXTURE_PATH = Path("tests") / "fixtures" / "cook_sao"
README = "README.md"
DISPOSITION_MINIMUM_ROWS = 100
COMMONEST_REASONS = 5
SUPPRESSION_REASON = "Motion to Quash Arrest & Suppress Evidence/Sustained"
EXCLUDED_PHASE = "Summary Charge Info"
SENTENCE_TYPE_MINIMUM_ROWS = 1000
PRETRIAL_FAIRNESS_ACT = date(2023, 9, 18)
JUDGE_CASES = 12

_COLUMNS: dict[str, tuple[str, ...]] = {
    "intake.csv": (CASE_ID, PARTICIPANT_ID, RECEIVED_DATE),
    "initiation.csv": (CASE_ID, RECEIVED_DATE, BOND_TYPE_INITIAL, CHARGE_ID, CHARGE_VERSION_ID),
    "dispositions.csv": (
        CASE_ID,
        RECEIVED_DATE,
        CHARGE_DISPOSITION,
        CHARGE_DISPOSITION_REASON,
        JUDGE,
        CHARGE_ID,
        CHARGE_VERSION_ID,
    ),
    "sentencing.csv": (
        CASE_ID,
        RECEIVED_DATE,
        SENTENCE_PHASE,
        SENTENCE_TYPE,
        SENTENCE_JUDGE,
        CHARGE_ID,
        CHARGE_VERSION_ID,
    ),
    "diversion.csv": (CASE_ID, RECEIVED_DATE),
}


class ExcerptError(Exception):
    """The excerpt cannot be built (no profile, a profile of other artifacts)."""


@dataclass(frozen=True, slots=True)
class Stratum:
    """One requirement of the rule: ``kind`` with an optional ``value``."""

    kind: str
    value: str | None = None

    @property
    def label(self) -> str:
        if self.value is None:
            return self.kind
        return f"{self.kind}: {self.value}"


@dataclass(frozen=True, slots=True)
class Excerpt:
    """The chosen cases in order, each with the stratum that chose it, and the misses."""

    chosen: tuple[tuple[str, Stratum], ...]
    unsatisfied: tuple[Stratum, ...]

    @property
    def case_ids(self) -> list[str]:
        return [case_id for case_id, _ in self.chosen]


# --- the strata from the profile -------------------------------------------------------


def _values(profile: Mapping[str, Any], dataset: str, column: str) -> list[tuple[str, int]]:
    try:
        entries = profile["datasets"][dataset]["columns"][column]["values"]
    except (KeyError, TypeError) as exc:
        msg = f"the profile has no value set for {dataset} {column}"
        raise ExcerptError(msg) from exc
    return [(str(value), int(count)) for value, count in entries]


def strata_from_profile(profile: Mapping[str, Any]) -> list[Stratum]:
    """The rule's strata in order, thresholds applied to the profile's counts."""
    strata = [
        Stratum("charge_disposition", value)
        for value, count in _values(profile, "dispositions.csv", CHARGE_DISPOSITION)
        if count >= DISPOSITION_MINIMUM_ROWS
    ]
    reasons = [v for v, _ in _values(profile, "dispositions.csv", CHARGE_DISPOSITION_REASON)]
    commonest = reasons[:COMMONEST_REASONS]
    if SUPPRESSION_REASON in reasons and SUPPRESSION_REASON not in commonest:
        commonest.append(SUPPRESSION_REASON)
    strata += [Stratum("charge_disposition_reason", value) for value in commonest]
    strata += [
        Stratum("bond_type_initial", value)
        for value, _ in _values(profile, "initiation.csv", BOND_TYPE_INITIAL)
    ]
    strata.append(Stratum("no_bond_type"))
    strata += [
        Stratum("sentence_phase", value)
        for value, _ in _values(profile, "sentencing.csv", SENTENCE_PHASE)
        if value != EXCLUDED_PHASE
    ]
    strata += [
        Stratum("sentence_type", value)
        for value, count in _values(profile, "sentencing.csv", SENTENCE_TYPE)
        if count >= SENTENCE_TYPE_MINIMUM_ROWS
    ]
    strata += [
        Stratum("diversion"),
        Stratum("open_case"),
        Stratum("two_participants"),
        Stratum("disposition_without_judge"),
        Stratum("received_before_2011"),
        Stratum("received_from_2023_09_18"),
        Stratum("charge_with_two_versions"),
    ]
    judges = _values(profile, "sentencing.csv", SENTENCE_JUDGE)
    if judges:
        judge = judges[0][0]
        strata += [Stratum("sentenced_by", judge)] * JUDGE_CASES
        strata += [Stratum("disposed_by", judge)] * JUDGE_CASES
    return strata


# --- candidates ------------------------------------------------------------------------


def load_frames(artifacts: Sequence[LocalArtifact]) -> dict[str, pl.DataFrame]:
    """The columns the predicates read, per dataset (strings; an empty field is null)."""
    return {
        artifact.external_id: scan(artifact)
        .select(_COLUMNS[artifact.external_id])
        .with_columns(parsed_date(RECEIVED_DATE).dt.date().alias(RECEIVED_DATE))
        .collect(engine="streaming")
        for artifact in artifacts
    }


def _cases(frame: pl.DataFrame, condition: pl.Expr | None = None) -> pl.Series:
    selected = frame if condition is None else frame.filter(condition)
    return selected.get_column(CASE_ID).drop_nulls().unique().sort()


def candidates(stratum: Stratum, frames: Mapping[str, pl.DataFrame]) -> pl.Series:
    """Every case satisfying ``stratum`` (sorted, unique); each test reads the case's own rows."""
    dispositions = frames["dispositions.csv"]
    sentencing = frames["sentencing.csv"]
    initiation = frames["initiation.csv"]
    kind, value = stratum.kind, stratum.value
    if kind == "charge_disposition":
        return _cases(dispositions, pl.col(CHARGE_DISPOSITION) == value)
    if kind == "charge_disposition_reason":
        return _cases(dispositions, pl.col(CHARGE_DISPOSITION_REASON) == value)
    if kind == "bond_type_initial":
        return _cases(initiation, pl.col(BOND_TYPE_INITIAL) == value)
    if kind == "no_bond_type":
        return _cases(initiation, pl.col(BOND_TYPE_INITIAL).is_null())
    if kind == "sentence_phase":
        return _cases(sentencing, pl.col(SENTENCE_PHASE) == value)
    if kind == "sentence_type":
        return _cases(sentencing, pl.col(SENTENCE_TYPE) == value)
    if kind == "sentenced_by":
        return _cases(sentencing, pl.col(SENTENCE_JUDGE) == value)
    if kind == "disposed_by":
        return _cases(dispositions, pl.col(JUDGE) == value)
    if kind == "diversion":
        return _cases(frames["diversion.csv"])
    if kind == "open_case":
        disposed = _cases(dispositions)
        initiated = _cases(initiation)
        return initiated.filter(~initiated.is_in(disposed.implode()))
    if kind == "two_participants":
        intake = frames["intake.csv"]
        counts = intake.group_by(CASE_ID).agg(pl.col(PARTICIPANT_ID).drop_nulls().n_unique())
        return counts.filter(pl.col(PARTICIPANT_ID) == 2).get_column(CASE_ID).sort()
    if kind == "disposition_without_judge":
        return _cases(dispositions, pl.col(JUDGE).is_null())
    if kind == "received_before_2011":
        series = [
            _cases(frame, pl.col(RECEIVED_DATE) < EARLIEST_EXPECTED_RECEIPT)
            for frame in frames.values()
        ]
        return pl.concat(series).unique().sort()
    if kind == "received_from_2023_09_18":
        return _cases(initiation, pl.col(RECEIVED_DATE) >= PRETRIAL_FAIRNESS_ACT)
    if kind == "charge_with_two_versions":
        charges = pl.concat(
            frames[name].select(CASE_ID, CHARGE_ID, CHARGE_VERSION_ID) for name in CHARGE_DATASETS
        )
        versions = charges.group_by(CASE_ID, CHARGE_ID).agg(
            pl.col(CHARGE_VERSION_ID).drop_nulls().n_unique().alias("n")
        )
        return _cases(versions, pl.col("n") >= 2)
    msg = f"unknown stratum kind {kind!r}"
    raise ExcerptError(msg)


def select_cases(strata: Sequence[Stratum], frames: Mapping[str, pl.DataFrame]) -> Excerpt:
    chosen: dict[str, Stratum] = {}
    unsatisfied: list[Stratum] = []
    for stratum in strata:
        pool = candidates(stratum, frames)
        pick = next(
            (case for case in pool.head(len(chosen) + 1).to_list() if case not in chosen), None
        )
        if pick is None:
            unsatisfied.append(stratum)
        else:
            chosen[pick] = stratum
    return Excerpt(chosen=tuple(chosen.items()), unsatisfied=tuple(unsatisfied))


def strata_satisfied(
    excerpt: Excerpt, strata: Sequence[Stratum], frames: Mapping[str, pl.DataFrame]
) -> dict[str, list[str]]:
    """Every stratum label each chosen case satisfies, read from the chosen cases' rows only."""
    ids = pl.Series(excerpt.case_ids, dtype=pl.String).implode()
    subset = {name: frame.filter(pl.col(CASE_ID).is_in(ids)) for name, frame in frames.items()}
    satisfied: dict[str, list[str]] = {case_id: [] for case_id in excerpt.case_ids}
    for stratum in dict.fromkeys(strata):
        for case_id in candidates(stratum, subset).to_list():
            satisfied[case_id].append(stratum.label)
    return satisfied


# --- writing ---------------------------------------------------------------------------


def _write_rows(artifact: LocalArtifact, case_ids: set[str], out: Path) -> int:
    headers = VERIFIED_HEADERS[artifact.external_id]
    blank = [index for index, header in enumerate(headers) if header in BLANKED_COLUMNS]
    case_index = headers.index(CASE_ID)
    written = 0
    with (
        artifact.path.open(encoding="utf-8", newline="") as source,
        out.open("w", encoding="utf-8", newline="") as target,
    ):
        reader = csv.reader(source)
        writer = csv.writer(target, lineterminator="\n")
        header = next(reader)
        if tuple(header) != headers:
            msg = f"{artifact.external_id}: the header differs from the verified set"
            raise ProfileError(msg)
        writer.writerow(header)
        for row in reader:
            if row[case_index] not in case_ids:
                continue
            for index in blank:
                row[index] = ""
            writer.writerow(row)
            written += 1
    return written


def write_excerpt(
    artifacts: Sequence[LocalArtifact],
    profile: Mapping[str, Any],
    out: Path,
) -> Excerpt:
    """Select the cases and write the five CSVs and the README into ``out``."""
    strata = strata_from_profile(profile)
    frames = load_frames(artifacts)
    excerpt = select_cases(strata, frames)
    satisfied = strata_satisfied(excerpt, strata, frames)
    out.mkdir(parents=True, exist_ok=True)
    case_ids = set(excerpt.case_ids)
    rows = {
        artifact.external_id: _write_rows(artifact, case_ids, out / artifact.external_id)
        for artifact in artifacts
    }
    readme = render_readme(excerpt, satisfied, profile, rows)
    (out / README).write_bytes(readme.encode("utf-8"))
    return excerpt


def render_readme(
    excerpt: Excerpt,
    satisfied: Mapping[str, Sequence[str]],
    profile: Mapping[str, Any],
    rows: Mapping[str, int],
) -> str:
    source_rows = {name: int(entry["rows"]) for name, entry in profile["datasets"].items()}
    digests = {a["external_id"]: a for a in profile["artifacts"]}
    lines = [
        "<!-- tests/fixtures/cook_sao/README.md -->",
        "# Cook County SAO fixture excerpt",
        "",
        "Real rows of the five Cook County State's Attorney exports (`docs/DATA_SOURCES.md`,",
        "entry `cook_sao`), chosen by a documented stratified rule. Generated by",
        "`judgemetrics sources excerpt cook_sao --out tests/fixtures/cook_sao` from the stored",
        "artifacts that `data/reference/cook_sao/profile.yaml` describes; regenerate it, never",
        "edit it by hand. Excerpting this directory itself",
        "(`--from-fixture tests/fixtures/cook_sao`) writes it again byte for byte.",
        "",
        "## Source",
        "",
        "| File | Portal id | Rows in the export | Rows here | Export sha256 |",
        "|------|-----------|--------------------|-----------|---------------|",
    ]
    for dataset in DATASETS:
        name = dataset.external_id
        lines.append(
            f"| `{name}` | `{dataset.portal_id}` | {source_rows.get(name, 0):,} | "
            f"{rows.get(name, 0):,} | `{digests.get(name, {}).get('sha256', '')}` |"
        )
    lines += [
        "",
        "The exports are public-domain data of the Cook County State's Attorney's Office,",
        f"published on the Cook County open-data portal; the corpus ends on {CORPUS_END}.",
        "",
        "## The rule",
        "",
        "For each stratum in this order, the smallest `CASE_ID` (string order) not chosen",
        "yet that satisfies it is chosen, and every row of every chosen case in all five",
        "datasets is kept, in artifact order. The strata and thresholds come from the",
        "profile's counts:",
        "",
        f"1. every `CHARGE_DISPOSITION` with at least {DISPOSITION_MINIMUM_ROWS} rows;",
        f"2. the {COMMONEST_REASONS} commonest `CHARGE_DISPOSITION_REASON` values and",
        f'   "{SUPPRESSION_REASON}";',
        "3. each `BOND_TYPE_INITIAL` value, and a case with an Initiation row without one;",
        f'4. each `SENTENCE_PHASE` but "{EXCLUDED_PHASE}";',
        f"5. each `SENTENCE_TYPE` with at least {SENTENCE_TYPE_MINIMUM_ROWS:,} rows;",
        "6. a diversion; an open case (an Initiation row and no Dispositions row); a case",
        "   with exactly two participants in Intake; a disposition without a judge; a case",
        "   with a row received before 2011-01-01; a case initiated with a receipt on or",
        f"   after {PRETRIAL_FAIRNESS_ACT} (the Pretrial Fairness Act); a charge with two",
        "   versions in Initiation, Dispositions, or Sentencing;",
        f"7. {JUDGE_CASES} cases sentenced and {JUDGE_CASES} cases disposed by the judge with the",
        "   most Sentencing rows, so an end-to-end test meets an unsuppressed judge figure.",
        "",
        "Each stratum tests the case's own rows only, so excerpting this directory chooses",
        "the same cases in the same order.",
        "",
        "## Blanked columns",
        "",
        "Every value of these columns is empty in every row; the headers are verbatim:",
        "",
        *(f"- `{column}`" for column in BLANKED_COLUMNS),
        "",
        "They are the restricted attributes (race, gender, age at the incident) and the",
        "quasi-identifiers the canonical model never reads (the incident's city and dates,",
        "the arresting agency and unit). `CASE_ID` and `CASE_PARTICIPANT_ID` are kept: they",
        "are the SAO's pseudonymous identifiers, hashed independently for every release, and",
        "they join the datasets.",
        "",
        "## Cases",
        "",
        "| # | `CASE_ID` | Chosen for | Every stratum it satisfies |",
        "|---|-----------|------------|----------------------------|",
    ]
    for number, (case_id, stratum) in enumerate(excerpt.chosen, start=1):
        others = "; ".join(satisfied.get(case_id, []))
        lines.append(f"| {number} | `{case_id}` | {stratum.label} | {others} |")
    lines += ["", "## Strata no case satisfies", ""]
    if excerpt.unsatisfied:
        lines += [f"- {stratum.label}" for stratum in excerpt.unsatisfied]
    else:
        lines.append("None.")
    lines += [
        "",
        "## Counts",
        "",
        f"{len(excerpt.chosen)} cases; "
        + ", ".join(f"`{name}` {count:,} rows" for name, count in rows.items())
        + ".",
        "",
    ]
    return "\n".join(lines)


def check_profile_matches(profile: Mapping[str, Any], artifacts: Sequence[LocalArtifact]) -> None:
    """The profile must describe these exports (a stale profile picks stale strata)."""
    recorded = {entry["external_id"]: entry["sha256"] for entry in profile["artifacts"]}
    for artifact in artifacts:
        if recorded.get(artifact.external_id) != artifact.sha256:
            msg = (
                f"{PROFILE_PATH} describes another {artifact.external_id}; "
                "regenerate it with `judgemetrics sources profile cook_sao` first"
            )
            raise ExcerptError(msg)
