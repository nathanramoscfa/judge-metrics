# tests/unit/test_adjustment_features.py
"""The feature builder over hand-built frames: boundaries, tie-breaks, the missing rule.

Every history feature reads rows strictly before the index case's filing
(00:00 UTC of its filing date): an earlier case, a conviction, or a failure
to appear exactly at that instant is not counted, and a case disposed at or
after it was pending then. The lead charge breaks severity ties by the
source's charge id and the charge count ignores a charge filed after the
decision; ``history_truncated`` marks a filing within the lookback of the
coverage start; a case without a filing date takes the history features'
missing level and a decision without a charge is excluded; the reference
levels (the specification's, the busiest court) have no column. On the
golden world the design's features equal the generator's own risk features.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import polars as pl
import pytest

from judgemetrics.metrics.adjustment.features import (
    DesignFrame,
    design_rows,
    feature_levels,
)
from judgemetrics.metrics.adjustment.spec import load_spec
from judgemetrics.metrics.frame import SCHEMAS, Frame, resolve_dtype
from judgemetrics.synthetic.config import GOLDEN
from tests.property.support import build_world, frame_from_world

pytestmark = pytest.mark.unit

SPEC = load_spec()
RELEASE = SPEC.target("pretrial_release")
COVERAGE = (date(2016, 1, 1), date(2020, 12, 31))
INDEX_FILED = date(2018, 3, 5)
INSTANT = datetime(2018, 3, 5, tzinfo=UTC)
DECIDED = datetime(2018, 3, 8, 10, 0, tzinfo=UTC)


def at(day: date, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def table(name: str, rows: list[dict[str, Any]]) -> pl.DataFrame:
    schema = {column: resolve_dtype(spec, pl.String()) for column, spec in SCHEMAS[name].items()}
    filled = [{column: row.get(column) for column in schema} for row in rows]
    return pl.DataFrame(filled, schema=schema, orient="row")


class World:
    """A hand-built frame: cases, charges, one judge's pretrial decisions, events."""

    def __init__(self) -> None:
        self.cases: list[dict[str, Any]] = []
        self.charges: list[dict[str, Any]] = []
        self.decisions: list[dict[str, Any]] = []
        self.justice: list[dict[str, Any]] = []
        self.courts = [
            {"id": "court-a", "jurisdiction_id": "state"},
            {"id": "court-b", "jurisdiction_id": "state"},
        ]

    def case(self, case_id: str, filed: date | None, court: str = "court-a") -> None:
        self.cases.append(
            {
                "id": case_id,
                "court_id": court,
                "filed_at": None if filed is None else at(filed),
                "status": "closed",
                "case_type": "felony",
            }
        )

    def charge(
        self,
        charge_id: str,
        case_id: str,
        person: str,
        filed: datetime,
        *,
        severity: str = "felony_3",
        category: str = "property",
        disposition: str | None = "pending",
        disposed: datetime | None = None,
    ) -> None:
        self.charges.append(
            {
                "id": f"uuid-{charge_id}",
                "case_id": case_id,
                "person_id": person,
                "filed_at": filed,
                "disposed_at": disposed,
                "disposition": disposition,
                "disposition_actor": None if disposed is None else "judge",
                "offense_category": category,
                "severity": severity,
                "source_row_id": charge_id,
            }
        )

    def decision(
        self, decision_id: str, case_id: str, person: str, when: datetime = DECIDED
    ) -> None:
        self.decisions.append(
            {
                "id": decision_id,
                "case_id": case_id,
                "person_id": person,
                "judge_id": "judge-1",
                "decision_type": "pretrial_release",
                "decision_at": when,
                "actor_type": "judge",
                "discretion": "discretionary",
                "release_at": when + timedelta(hours=4),
                "detained_flag": False,
                "release_type": "recognizance",
            }
        )

    def failure_to_appear(self, person: str, when: datetime, case_id: str) -> None:
        self.justice.append(
            {
                "id": f"je-{len(self.justice)}",
                "person_id": person,
                "event_type": "failure_to_appear",
                "event_at": when,
                "related_case_id": case_id,
            }
        )

    def frame(self) -> Frame:
        persons = sorted({row["person_id"] for row in self.charges + self.decisions})
        base = Frame.empty(*COVERAGE, frozenset({"failure_to_appear", "new_case"}))
        return base.replace(
            cases=table("cases", self.cases),
            charges=table("charges", self.charges),
            decisions=table("decisions", self.decisions),
            justice_events=table("justice_events", self.justice),
            persons=table("persons", [{"id": person} for person in persons]),
            courts=table("courts", self.courts),
        )


def levels_of(frame: Frame, decision_id: str) -> dict[str, str | None]:
    """The feature levels of one decision's index event (before the missing rule)."""
    decision = frame.decisions.filter(pl.col("id") == decision_id)
    events = decision.select(
        pl.lit(0, dtype=pl.UInt32).alias("_row"),
        "case_id",
        "person_id",
        "decision_at",
        pl.col("decision_at").alias("index_at"),
    )
    row = feature_levels(frame, SPEC, events).row(0, named=True)
    return {key: value for key, value in row.items() if key != "_row"}


def index_case(world: World, person: str = "p1") -> None:
    world.case("index", INDEX_FILED)
    world.charge(
        "CH-031", "index", person, at(INDEX_FILED, 9), severity="felony_2", category="drug"
    )
    world.charge(
        "CH-030", "index", person, at(INDEX_FILED, 9, 30), severity="felony_2", category="weapon"
    )
    # Filed after the decision: neither the lead nor the count reads it.
    world.charge(
        "CH-001",
        "index",
        person,
        DECIDED + timedelta(days=12),
        severity="felony_1",
        category="person",
    )
    world.decision("dc-1", "index", person)


def test_prior_counts_and_the_pending_case_read_strictly_before_the_filing() -> None:
    world = World()
    index_case(world)
    world.case("a", date(2017, 1, 10))
    world.charge(
        "CH-010",
        "a",
        "p1",
        at(date(2017, 1, 10), 10),
        disposition="convicted_plea",
        disposed=at(date(2017, 6, 1), 12),
    )
    world.case("b", date(2017, 8, 1))
    world.charge("CH-020", "b", "p1", at(date(2017, 8, 1), 9))  # still pending
    world.case("same-day", INDEX_FILED, court="court-b")
    world.charge("CH-040", "same-day", "p1", at(INDEX_FILED, 11))
    world.failure_to_appear("p1", at(date(2017, 3, 1), 9), "a")
    levels = levels_of(world.frame(), "dc-1")
    assert levels["prior_cases"] == "2"  # a and b; the same-day case is not before the filing
    assert levels["prior_convictions"] == "1"
    assert levels["prior_failures_to_appear"] == "1+"
    assert levels["pending_case"] == "true"
    assert levels["court"] == "court-a" and levels["jurisdiction"] == "state"
    assert levels["calendar_year"] == "2018"


def test_an_event_exactly_at_the_filing_instant_is_excluded() -> None:
    world = World()
    index_case(world)
    world.case("a", date(2017, 1, 10))
    world.charge(
        "CH-010",
        "a",
        "p1",
        at(date(2017, 1, 10), 10),
        disposition="convicted_plea",
        disposed=INSTANT,
    )
    world.failure_to_appear("p1", INSTANT, "a")
    world.failure_to_appear("p1", INSTANT - timedelta(microseconds=1), "a")
    levels = levels_of(world.frame(), "dc-1")
    # The conviction at the instant is not before it, so the case was still open then.
    assert levels["prior_cases"] == "1"
    assert levels["prior_convictions"] == "0"
    assert levels["pending_case"] == "true"
    # One failure to appear a microsecond before the filing counts; the one at it does not.
    assert levels["prior_failures_to_appear"] == "1+"
    only_at = World()
    index_case(only_at)
    only_at.case("a", date(2017, 1, 10))
    only_at.charge("CH-010", "a", "p1", at(date(2017, 1, 10), 10))
    only_at.failure_to_appear("p1", INSTANT, "a")
    assert levels_of(only_at.frame(), "dc-1")["prior_failures_to_appear"] == "0"


@pytest.mark.parametrize(
    ("charges", "expected"),
    [
        # Disposed before the filing: not pending.
        ([("convicted_plea", at(date(2017, 5, 1)))], "false"),
        # One charge disposed before, one after: pending as of the filing.
        ([("dismissed", at(date(2017, 5, 1))), ("dismissed", at(date(2018, 6, 1)))], "true"),
        # An unrecorded disposition is ignored beside a disposed charge ...
        ([("acquitted", at(date(2017, 5, 1))), (None, None)], "false"),
        # ... and alone leaves nothing disposed: pending.
        ([(None, None)], "true"),
        # A charge still pending at export.
        ([("acquitted", at(date(2017, 5, 1))), ("pending", None)], "true"),
    ],
)
def test_the_pending_case_is_evaluated_as_of_the_filing(
    charges: list[tuple[str | None, datetime | None]], expected: str
) -> None:
    world = World()
    index_case(world)
    world.case("a", date(2017, 1, 10))
    for number, (disposition, disposed) in enumerate(charges):
        world.charge(
            f"CH-1{number}",
            "a",
            "p1",
            at(date(2017, 1, 10), 10),
            disposition=disposition,
            disposed=disposed,
        )
    assert levels_of(world.frame(), "dc-1")["pending_case"] == expected


def test_the_lead_severity_breaks_ties_by_the_source_charge_id() -> None:
    world = World()
    index_case(world)
    levels = levels_of(world.frame(), "dc-1")
    assert levels["lead_severity"] == "felony_2"  # the later felony_1 is not read
    assert levels["lead_category"] == "weapon"  # CH-030 sorts before CH-031
    assert levels["charge_count"] == "2"
    # Relabelling the canonical charge ids does not move the tie-break.
    frame = world.frame()
    relabelled = frame.replace(
        charges=frame.charges.with_columns(
            pl.when(pl.col("source_row_id") == "CH-030")
            .then(pl.lit("zzz"))
            .otherwise(pl.lit("aaa"))
            .alias("id")
        )
    )
    assert levels_of(relabelled, "dc-1")["lead_category"] == "weapon"


@pytest.mark.parametrize(
    ("filed", "expected"),
    [
        (date(2016, 1, 1), "true"),
        (date(2018, 12, 30), "true"),  # 1,094 days after the coverage start
        (date(2018, 12, 31), "false"),  # 1,095 days: no longer within
        (date(2019, 6, 1), "false"),
    ],
)
def test_history_truncated_marks_a_filing_within_the_lookback(filed: date, expected: str) -> None:
    assert (filed - COVERAGE[0]).days in (0, 1094, 1095, 1247)
    world = World()
    world.case("index", filed)
    world.charge("CH-1", "index", "p1", at(filed, 9))
    world.decision("dc-1", "index", "p1", at(filed + timedelta(days=2), 10))
    assert levels_of(world.frame(), "dc-1")["history_truncated"] == expected


def _design(world: World) -> DesignFrame:
    design = design_rows(world.frame(), SPEC, RELEASE, None)
    assert isinstance(design, DesignFrame)
    return design


def test_the_missing_rule_excludes_or_takes_the_missing_level() -> None:
    world = World()
    index_case(world)
    # A case without a filing date: its history cannot be placed in time.
    world.case("undated", None, court="court-b")
    world.charge("CH-500", "undated", "p2", at(date(2018, 4, 1), 9))
    world.decision("dc-2", "undated", "p2", at(date(2018, 4, 3), 10))
    # A decision whose case has no charge before it: not describable, excluded.
    world.case("uncharged", date(2018, 5, 1))
    world.charge("CH-600", "uncharged", "p3", at(date(2018, 5, 20), 9))
    world.decision("dc-3", "uncharged", "p3", at(date(2018, 5, 3), 10))
    levels = levels_of(world.frame(), "dc-2")
    assert levels["prior_cases"] is None and levels["history_truncated"] is None
    design = _design(world)
    assert design.eligible == 3 and design.excluded_missing == 1 and design.rows == 2
    assert "dc-3" not in design.member_ids
    undated = design.member_ids.index("dc-2")
    assert bool(design.missing[undated]) and not bool(
        design.missing[design.member_ids.index("dc-1")]
    )
    row = design.levels.row(undated, named=True)
    for name in ("prior_cases", "prior_convictions", "pending_case", "history_truncated"):
        assert row[name] == "unrecorded", name


def test_the_reference_levels_are_dropped_and_the_busiest_court_is_the_reference() -> None:
    world = World()
    index_case(world)
    for number, (court, severity) in enumerate(
        [("court-b", "misdemeanor_b"), ("court-b", "felony_1"), ("court-a", "misdemeanor_a")]
    ):
        filed = date(2019, 2, 1) + timedelta(days=number)
        world.case(f"c{number}", filed, court=court)
        world.charge(f"CH-7{number}", f"c{number}", f"q{number}", at(filed, 9), severity=severity)
        world.decision(f"dc-q{number}", f"c{number}", f"q{number}", at(filed, 15))
    design = _design(world)
    names = [column.name for column in design.columns]
    assert names[0] == "intercept"
    assert design.matrix[:, 0].tolist() == [1.0] * design.rows
    # The specification's references and the busiest data levels have no column.
    for reference in (
        "lead_severity=misdemeanor_b",
        "charge_count=1",
        "prior_cases=0",
        "pending_case=false",
    ):
        assert reference not in names
    encoding = design.encoding("court")
    # Two decisions in each court: the tie goes to the court whose earliest charge
    # (filing time, then source id) is earlier - court-a's index charges, 2018.
    assert encoding.levels[:2] == ("1", "2") and encoding.reference == "1"
    assert encoding.keys["1"] == "court-a" and encoding.keys["2"] == "court-b"
    assert "court=2" in names and "court=1" not in names
    # A jurisdiction with one level adds no column and is reported as dropped.
    assert not any(column.feature == "jurisdiction" for column in design.columns)
    assert "jurisdiction" in {item.name for item in design.dropped}
    # Every observed non-reference level has a column; an unobserved one is listed.
    assert "lead_severity=felony_1" in names and "lead_severity=felony_3" in design.unobserved
    assert design.matrix.dtype.name == "float64" and design.matrix.flags["C_CONTIGUOUS"]


def test_the_golden_world_design_equals_the_generators_risk_features() -> None:
    world = build_world(7, GOLDEN)
    frame = frame_from_world(world, GOLDEN)
    design = design_rows(frame, SPEC, RELEASE, None)
    assert isinstance(design, DesignFrame) and design.rows > 0
    cases = {decision.decision_id: case for case in world.cases for decision in case.decisions}

    def band(value: int, top: int) -> str:
        return str(value) if value < top else f"{top}+"

    for member, row in zip(design.member_ids, design.levels.iter_rows(named=True), strict=True):
        draws = cases[member].draws
        assert draws is not None
        features = draws.features
        assert row["lead_severity"] == features.lead_severity, member
        assert row["charge_count"] == band(features.charge_count, 3), member
        assert row["prior_cases"] == band(features.prior_cases, 3), member
        assert row["prior_convictions"] == band(features.prior_convictions, 2), member
        assert row["prior_failures_to_appear"] == band(features.prior_failures_to_appear, 1), member
        assert row["pending_case"] == ("true" if features.pending_case else "false"), member
