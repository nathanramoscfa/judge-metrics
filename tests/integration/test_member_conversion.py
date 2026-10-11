# tests/integration/test_member_conversion.py
"""Revision 0013 converts the old per-observation members into member families, and back.

Hand-built observations in the old layout (revision 0012) cover every shape the conversion
must fold: a windowed rate whose cohort has two defendants in one case who reoffended at
different times (rows that share an id and differ in their flags), two identical defendants
(a multiplicity), a row only the whole window holds (a null anchor year), a share, a
distribution (a row counts in the value it belongs to), a median by dimension, and a count
from before calendar years. For each, the member multiset of every observation after
``upgrade`` equals the one before, the family equals the one the engine builds from the true
atoms (same digest), and ``downgrade`` expands the very same multisets again. An
inconsistent group (a calendar-year observation holding a member the whole window lacks) stops
the upgrade with a message instead of guessing. The golden data's round trip is in
``test_member_storage``.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import polars as pl
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from judgemetrics.db.migrations import current_revision, downgrade, upgrade
from judgemetrics.metrics.member_store import observation_members, read_family
from judgemetrics.metrics.members import (
    BELONGS_TO,
    COUNTED_IN,
    PLAIN,
    MemberFamily,
    atoms,
)

pytestmark = pytest.mark.integration

SOURCE = uuid.UUID(int=0xA1)
SNAPSHOT = uuid.UUID(int=0xA2)
JUDGE = uuid.UUID(int=0xA3)
SNAPSHOT_HASH = "c" * 64
SOURCE_NAME = "conversion-test"


def _id(number: int) -> str:
    return str(uuid.UUID(int=0xBEEF0000 + number))


def _url(engine: Engine) -> str:
    return engine.url.render_as_string(hide_password=False)


class World:
    """The hand-built old-layout observations of one test, and their expected member multisets."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.expected: dict[uuid.UUID, Counter[tuple[str, bool, bool]]] = {}
        self.definitions: dict[str, uuid.UUID] = {}
        self.digests: dict[uuid.UUID, str] = {}

    def definition(
        self, slug: str, kind: str, windows: list[int] | None = None, dimension: str | None = None
    ) -> uuid.UUID:
        definition_id = uuid.uuid4()
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO metric_definition (id, slug, name, description, "
                    "numerator_definition, denominator_definition, eligibility_definition, "
                    "version, kind, subject_types, attribution, windows_days, dimension, "
                    "suppression_threshold, unit, registry_version, methodology_version) "
                    "VALUES (:id, :slug, 'n', 'd', 'n', 'd', 'e', '1', :kind, '[\"judge\"]', "
                    "'{}', CAST(:windows AS jsonb), :dimension, 0, 'count', 3, '1.1')"
                ),
                {
                    "id": definition_id,
                    "slug": f"{slug}-{uuid.uuid4().hex[:6]}",
                    "kind": kind,
                    "windows": None if windows is None else str(windows),
                    "dimension": dimension,
                },
            )
        self.definitions[slug] = definition_id
        return definition_id

    def observation(
        self,
        definition: uuid.UUID,
        *,
        kind: str,
        members: list[tuple[str, bool, bool]],
        year: int | None = None,
        window: int | None = None,
        dimension: str | None = None,
    ) -> uuid.UUID:
        observation_id = uuid.uuid4()
        start, end = (
            (date(2019, 1, 1), date(2021, 12, 31))
            if year is None
            else (date(year, 1, 1), date(year, 12, 31))
        )
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO metric_observation (id, metric_definition_id, subject_type, "
                    "subject_id, period_start, period_end, cohort_size, observed_count, "
                    "methodology_version, computed_at, snapshot_id, source_id, window_days, "
                    "dimension_value, eligible_count, code_version, registry_version, "
                    "suppressed_flag, calendar_year) VALUES (:id, :definition, 'judge', :judge, "
                    ":start, :end, 0, 0, '1.1', :now, :snapshot, :source, :window, :dimension, "
                    ":eligible, 'test', 3, false, :year)"
                ),
                {
                    "id": observation_id,
                    "definition": definition,
                    "judge": JUDGE,
                    "start": start,
                    "end": end,
                    "now": datetime.now(tz=UTC),
                    "snapshot": SNAPSHOT,
                    "source": SOURCE,
                    "window": window,
                    "dimension": dimension,
                    "eligible": len(members),
                    "year": year,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO metric_observation_member (observation_id, member_kind, member_id, "
                    "counted, followed) VALUES (:o, :kind, CAST(:m AS uuid), :c, :f)"
                ),
                [
                    {"o": observation_id, "kind": kind, "m": ident, "c": counted, "f": followed}
                    for ident, counted, followed in members
                ],
            )
        self.expected[observation_id] = Counter(
            (ident, counted, followed) for ident, counted, followed in members
        )
        return observation_id


@pytest.fixture
def world(migrated_database: Engine) -> Iterator[World]:
    """An empty database at revision 0012 with a source and a snapshot, restored to head after."""
    url = _url(migrated_database)
    downgrade(url, "0012")
    assert current_revision(migrated_database) == "0012"
    try:
        with migrated_database.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO source (id, name, owner, source_type, access_method) "
                    "VALUES (:id, :name, 'test', 'court_records', 'fixture')"
                ),
                {"id": SOURCE, "name": SOURCE_NAME},
            )
            connection.execute(
                text(
                    "INSERT INTO metric_snapshot (id, content_hash, exported_at, code_version, "
                    "registry_version, methodology_version, storage_uri) "
                    "VALUES (:id, :hash, :now, 'test', 3, '1.1', 'file:///nowhere')"
                ),
                {"id": SNAPSHOT, "hash": SNAPSHOT_HASH, "now": datetime.now(tz=UTC)},
            )
        yield World(migrated_database)
    finally:
        with migrated_database.begin() as connection:
            for statement in (
                "DELETE FROM metric_observation_member",
                "DELETE FROM metric_observation WHERE source_id = :source",
                "DELETE FROM metric_snapshot WHERE id = :snapshot",
                "DELETE FROM metric_definition WHERE slug LIKE '%-%' AND description = 'd'",
                "DELETE FROM source WHERE id = :source",
            ):
                connection.execute(text(statement), {"source": SOURCE, "snapshot": SNAPSHOT})
        upgrade(url, "head")
        assert current_revision(migrated_database) == "0013"


def _multisets(engine: Engine, ids: list[uuid.UUID]) -> dict[uuid.UUID, Counter[Any]]:
    with Session(engine) as session:
        return {
            observation_id: Counter(
                (member.id, member.counted, member.followed)
                for member in observation_members(session, observation_id)
            )
            for observation_id in ids
        }


def _family_of(engine: Engine, observation_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT f.id, f.members_hash FROM metric_member_family f "
                "JOIN metric_observation o ON o.member_family_id = f.id WHERE o.id = :id"
            ),
            {"id": observation_id},
        ).one()
    return row[0], row[1]


def _true_family(
    kind: str,
    mode: str,
    windows: tuple[int | None, ...],
    rows: list[tuple[str, int | None, str | None, tuple[bool, ...], tuple[bool, ...]]],
) -> MemberFamily:
    """The family the engine builds from the true atoms ``(id, year, dimension, counted, followed)``."""
    frame = pl.DataFrame(
        {
            "id": [row[0] for row in rows],
            "at": [None if row[1] is None else datetime(row[1], 6, 1, tzinfo=UTC) for row in rows],
            "d": [row[2] for row in rows],
            **{f"c{i}": [row[3][i] for row in rows] for i in range(len(windows))},
            **{f"f{i}": [row[4][i] for row in rows] for i in range(len(windows))},
        },
        schema_overrides={"at": pl.Datetime("us", "UTC"), "d": pl.String},
    )
    return MemberFamily(
        kind,
        mode,
        windows,
        atoms(
            frame,
            member_id="id",
            anchor="at",
            counted=[pl.col(f"c{i}") for i in range(len(windows))],
            followed=[pl.col(f"f{i}") for i in range(len(windows))],
            dimension=pl.col("d") if mode != PLAIN else None,
        ),
    )


def test_a_windowed_cohort_with_shared_ids_duplicates_and_a_whole_window_only_row(
    world: World, migrated_database: Engine
) -> None:
    case_x, case_y, case_z, case_w = _id(1), _id(2), _id(3), _id(4)
    definition = world.definition("rate", "windowed_rate", windows=[30, 90])
    made: list[uuid.UUID] = []

    def add(year: int | None, window: int, members: list[tuple[str, bool, bool]]) -> None:
        made.append(
            world.observation(
                definition, kind="court_case", members=members, year=year, window=window
            )
        )

    # 2020: case X has two defendants (one reoffends within 30 days, one within 90), case Z two
    # identical defendants who never reoffend; 2021: case Y. Case W is in the whole window only.
    add(
        2020,
        30,
        [(case_x, True, True), (case_x, False, True), (case_z, False, True), (case_z, False, True)],
    )
    add(
        2020,
        90,
        [(case_x, True, True), (case_x, True, True), (case_z, False, True), (case_z, False, True)],
    )
    add(2021, 30, [(case_y, False, True)])
    add(2021, 90, [(case_y, False, False)])
    add(
        None,
        30,
        [(case_x, True, True), (case_x, False, True), (case_z, False, True), (case_z, False, True)]
        + [(case_y, False, True), (case_w, False, True)],
    )
    add(
        None,
        90,
        [(case_x, True, True), (case_x, True, True), (case_z, False, True), (case_z, False, True)]
        + [(case_y, False, False), (case_w, False, False)],
    )
    upgrade(_url(migrated_database), "head")

    after = _multisets(migrated_database, made)
    assert after == {oid: world.expected[oid] for oid in made}
    truth = _true_family(
        "court_case",
        PLAIN,
        (30, 90),
        [
            (case_x, 2020, None, (True, True), (True, True)),
            (case_x, 2020, None, (False, True), (True, True)),
            (case_z, 2020, None, (False, False), (True, True)),
            (case_z, 2020, None, (False, False), (True, True)),
            (case_y, 2021, None, (False, False), (True, False)),
            (case_w, None, None, (False, False), (True, False)),
        ],
    )
    assert {_family_of(migrated_database, oid)[1] for oid in made} == {truth.digest}
    # One family, with the identical defendants merged into one row of multiplicity two.
    family_id = _family_of(migrated_database, made[0])[0]
    with Session(migrated_database) as session:
        stored = read_family(session, family_id, kind="court_case", mode=PLAIN, windows=(30, 90))
    assert stored.rows.equals(truth.rows)
    assert stored.row_count == 5 and stored.member_count == 6
    assert stored.rows.filter(pl.col("member_id") == case_z)["multiplicity"].to_list() == [2]

    # And back: the old rows are the very multisets they were.
    downgrade(_url(migrated_database), "0012")
    with migrated_database.connect() as connection:
        for observation_id in made:
            rows = connection.execute(
                text(
                    "SELECT member_id::text, counted, followed FROM metric_observation_member "
                    "WHERE observation_id = :id"
                ),
                {"id": observation_id},
            ).all()
            assert Counter(tuple(row) for row in rows) == world.expected[observation_id]


def test_a_share_a_distribution_a_median_by_dimension_and_a_count_from_before_years(
    world: World, migrated_database: Engine
) -> None:
    decisions = [_id(10), _id(11), _id(12)]
    share = world.definition("share", "share")
    made = [
        world.observation(
            share,
            kind="decision",
            members=[(decisions[0], True, True), (decisions[1], False, True)],
            year=2020,
        ),
        world.observation(share, kind="decision", members=[(decisions[2], True, True)], year=2021),
        world.observation(
            share,
            kind="decision",
            members=[
                (decisions[0], True, True),
                (decisions[1], False, True),
                (decisions[2], True, True),
            ],
        ),
    ]
    charges = [_id(20), _id(21), _id(22)]
    values = ["dismissed", "convicted_plea", "acquitted", "convicted_verdict"]
    dispositions = {charges[0]: "dismissed", charges[1]: "convicted_plea", charges[2]: "dismissed"}
    years = {charges[0]: 2020, charges[1]: 2020, charges[2]: 2021}
    distribution = world.definition("dist", "distribution", dimension="disposition")
    for year in (2020, 2021, None):
        for value in values:
            members = [
                (charge, dispositions[charge] == value, True)
                for charge in charges
                if year is None or years[charge] == year
            ]
            made.append(
                world.observation(
                    distribution, kind="charge", members=members, year=year, dimension=value
                )
            )
    sentences = [_id(30), _id(31), _id(32)]
    categories = {sentences[0]: "theft", sentences[1]: "theft", sentences[2]: "drug"}
    has_value = {sentences[0]: True, sentences[1]: False, sentences[2]: True}
    median = world.definition("median", "median", dimension="offense_category")
    for category in ("theft", "drug"):
        made.append(
            world.observation(
                median,
                kind="sentence",
                members=[
                    (sentence, has_value[sentence], has_value[sentence])
                    for sentence in sentences
                    if categories[sentence] == category
                ],
                dimension=category,
            )
        )
    count = world.definition("count", "count")
    made.append(
        world.observation(
            count, kind="court_case", members=[(_id(40), True, True), (_id(41), False, True)]
        )
    )
    upgrade(_url(migrated_database), "head")

    after = _multisets(migrated_database, made)
    assert after == {oid: world.expected[oid] for oid in made}
    share_truth = _true_family(
        "decision",
        PLAIN,
        (None,),
        [
            (decisions[0], 2020, None, (True,), (True,)),
            (decisions[1], 2020, None, (False,), (True,)),
            (decisions[2], 2021, None, (True,), (True,)),
        ],
    )
    assert _family_of(migrated_database, made[0])[1] == share_truth.digest
    assert _family_of(migrated_database, made[1])[1] == share_truth.digest
    distribution_truth = _true_family(
        "charge",
        COUNTED_IN,
        (None,),
        [(charge, years[charge], dispositions[charge], (False,), (True,)) for charge in charges],
    )
    assert _family_of(migrated_database, made[3])[1] == distribution_truth.digest
    median_truth = _true_family(
        "sentence",
        BELONGS_TO,
        (None,),
        [
            (sentence, None, categories[sentence], (has_value[sentence],), (has_value[sentence],))
            for sentence in sentences
        ],
    )
    assert _family_of(migrated_database, made[15])[1] == median_truth.digest
    count_truth = _true_family(
        "court_case",
        PLAIN,
        (None,),
        [(_id(40), None, None, (True,), (True,)), (_id(41), None, None, (False,), (True,))],
    )
    assert _family_of(migrated_database, made[-1])[1] == count_truth.digest

    downgrade(_url(migrated_database), "0012")
    with migrated_database.connect() as connection:
        for observation_id in made:
            rows = connection.execute(
                text(
                    "SELECT member_id::text, counted, followed FROM metric_observation_member "
                    "WHERE observation_id = :id"
                ),
                {"id": observation_id},
            ).all()
            assert Counter(tuple(row) for row in rows) == world.expected[observation_id]


def test_an_inconsistent_group_stops_the_upgrade_and_leaves_the_database_at_0012(
    world: World, migrated_database: Engine
) -> None:
    definition = world.definition("bad", "share")
    world.observation(definition, kind="decision", members=[(_id(50), True, True)], year=2020)
    # The whole window lacks the member the year holds.
    world.observation(definition, kind="decision", members=[(_id(51), True, True)])
    with pytest.raises(Exception, match="holds members the whole window lacks"):
        upgrade(_url(migrated_database), "head")
    assert current_revision(migrated_database) == "0012"
    # Make the group consistent so the fixture's upgrade back to head can run.
    with migrated_database.begin() as connection:
        connection.execute(text("DELETE FROM metric_observation_member"))
        connection.execute(
            text("DELETE FROM metric_observation WHERE source_id = :s"), {"s": SOURCE}
        )
