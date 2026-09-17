# src/judgemetrics/synthetic/config.py
"""Scale specifications and the generator version.

``GENERATOR_VERSION`` is written to every manifest and must be bumped
whenever the output for a fixed seed changes (a new draw, a new column, a
changed constant); the golden fixture under ``tests/fixtures/golden/`` is
then regenerated, never hand-edited (docs/SYNTHETIC_DATA.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

GENERATOR_VERSION = "1"

# The brief's synthetic demo dataset minimums (<synthetic_demo_dataset>).
BRIEF_MINIMUM_COURTS = 5
BRIEF_MINIMUM_JUDGES = 20
BRIEF_MINIMUM_CASES = 5_000
BRIEF_MINIMUM_PERSONS = 3_000

# Every person appears in one to four cases, so subsequent cases exist.
MAX_CASES_PER_PERSON = 4


@dataclass(frozen=True, slots=True)
class ScaleSpec:
    """The size of a generated world and the quantities of planted edge cases."""

    name: str
    courts: int
    judges: int
    persons: int
    cases: int
    start_year: int
    end_year: int
    duplicate_source_records: int
    ambiguous_person_pairs: int
    split_person_pairs: int
    missing_dob_share: float
    missing_judge_share: float
    missing_disposition_share: float

    def __post_init__(self) -> None:
        problems: list[str] = []
        if self.courts < 1:
            problems.append("at least one court")
        if self.judges < self.courts:
            problems.append("at least one judge per court (an anchor judge serves the whole span)")
        if self.persons < 1 or self.cases < self.persons:
            problems.append("at least as many cases as persons (every person has a case)")
        if self.cases > self.persons * MAX_CASES_PER_PERSON:
            problems.append(f"at most {MAX_CASES_PER_PERSON} cases per person")
        if self.end_year < self.start_year:
            problems.append("end_year on or after start_year")
        if self.split_person_pairs > self.cases - self.persons:
            problems.append("one extra case per split person")
        if 2 * self.ambiguous_person_pairs + self.split_person_pairs > self.persons:
            problems.append("enough persons for the ambiguous and split plants")
        if self.duplicate_source_records > self.cases:
            problems.append("no more duplicates than cases")
        for label, share in (
            ("missing_dob_share", self.missing_dob_share),
            ("missing_judge_share", self.missing_judge_share),
            ("missing_disposition_share", self.missing_disposition_share),
        ):
            if not 0.0 <= share <= 1.0:
                problems.append(f"{label} within [0, 1]")
        if problems:
            msg = f"ScaleSpec {self.name!r} needs: " + "; ".join(problems)
            raise ValueError(msg)

    @property
    def corpus_start(self) -> date:
        """First day a case can be filed."""
        return date(self.start_year, 1, 1)

    @property
    def corpus_end(self) -> date:
        """Last day of the corpus (inclusive); the corpus end date for follow-up."""
        return date(self.end_year, 12, 31)

    @property
    def corpus_end_at(self) -> datetime:
        """Exclusive upper bound: every emitted timestamp is strictly before it."""
        return datetime(self.end_year + 1, 1, 1, tzinfo=UTC)

    @property
    def span_days(self) -> int:
        return (self.corpus_end - self.corpus_start).days + 1


GOLDEN = ScaleSpec(
    name="golden",
    courts=3,
    judges=6,
    persons=40,
    cases=60,
    start_year=2019,
    end_year=2021,
    duplicate_source_records=3,
    ambiguous_person_pairs=2,
    split_person_pairs=2,
    missing_dob_share=0.05,
    missing_judge_share=0.05,
    missing_disposition_share=0.03,
)

DEMO = ScaleSpec(
    name="demo",
    courts=5,
    judges=24,
    persons=3_200,
    cases=5_200,
    start_year=2016,
    end_year=2023,
    duplicate_source_records=40,
    ambiguous_person_pairs=25,
    split_person_pairs=25,
    missing_dob_share=0.04,
    missing_judge_share=0.02,
    missing_disposition_share=0.01,
)

# A reduced world for property tests (Phase 2 Step 5) and quick smoke runs.
TINY = ScaleSpec(
    name="tiny",
    courts=2,
    judges=3,
    persons=12,
    cases=16,
    start_year=2020,
    end_year=2021,
    duplicate_source_records=1,
    ambiguous_person_pairs=1,
    split_person_pairs=1,
    missing_dob_share=0.1,
    missing_judge_share=0.1,
    missing_disposition_share=0.1,
)

SCALES: dict[str, ScaleSpec] = {GOLDEN.name: GOLDEN, DEMO.name: DEMO, TINY.name: TINY}


def scale_spec(name: str) -> ScaleSpec:
    """The spec registered under ``name``; ``ValueError`` names the known scales."""
    try:
        return SCALES[name]
    except KeyError:
        known = ", ".join(sorted(SCALES))
        msg = f"unknown scale {name!r}; known scales: {known}"
        raise ValueError(msg) from None
