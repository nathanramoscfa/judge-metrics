# tests/unit/test_members.py
"""Member families: atoms, the canonical form, the digest, and the filter that cuts observations.

A ``MemberFamily`` holds the canonical rows behind every observation of one definition and
subject once. These tests pin what makes it safe to share: the canonical form is a
function of the observations' member multisets alone (atom order and the pairing of rows
that share an id do not matter), the digest names the content (it moves with a flag, a
year, a dimension, a kind, and with nothing else), and ``project`` returns each
observation's multiset for the three ways a row relates to a dimension.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl
import pytest

from judgemetrics.metrics import members as m
from judgemetrics.metrics.members import (
    BELONGS_TO,
    COUNTED_IN,
    PLAIN,
    Member,
    MemberError,
    MemberFamily,
    atoms,
    mode_for,
    windows_for,
)

pytestmark = pytest.mark.unit


def _at(year: int) -> datetime:
    return datetime(year, 6, 15, tzinfo=UTC)


def _frame(rows: Sequence[tuple[str, int, tuple[bool, ...], tuple[bool, ...]]]) -> pl.DataFrame:
    """``(id, year, counted per slot, followed per slot)`` as a frame of boolean columns."""
    slots = len(rows[0][2])
    data: dict[str, list[object]] = {"id": [], "at": []}
    for slot in range(slots):
        data[f"c{slot}"] = []
        data[f"f{slot}"] = []
    for ident, year, counted, followed in rows:
        data["id"].append(ident)
        data["at"].append(_at(year))
        for slot in range(slots):
            data[f"c{slot}"].append(counted[slot])
            data[f"f{slot}"].append(followed[slot])
    return pl.DataFrame(data, schema_overrides={"at": pl.Datetime("us", "UTC")})


def _family(
    rows: Sequence[tuple[str, int, tuple[bool, ...], tuple[bool, ...]]],
    windows: tuple[int | None, ...],
    kind: str = "court_case",
    mode: str = PLAIN,
) -> MemberFamily:
    frame = _frame(rows)
    slots = len(windows)
    return MemberFamily(
        kind,
        mode,
        windows,
        atoms(
            frame,
            member_id="id",
            anchor="at",
            counted=[pl.col(f"c{slot}") for slot in range(slots)],
            followed=[pl.col(f"f{slot}") for slot in range(slots)],
        ),
    )


def _multiset(family: MemberFamily, **cut: object) -> Counter[tuple[str, bool, bool]]:
    return Counter((member.id, member.counted, member.followed) for member in family.members(**cut))  # type: ignore[arg-type]


def test_masks_set_bit_i_for_flag_i_and_refuse_bad_slot_counts() -> None:
    frame = pl.DataFrame({"a": [True, False], "b": [False, False], "c": [True, True]})
    assert frame.select(m.mask([pl.col("a"), pl.col("b"), pl.col("c")]))["a"].to_list() == [5, 4]
    with pytest.raises(MemberError):
        m.mask([])
    with pytest.raises(MemberError):
        m.mask([pl.lit(True)] * (m.MAX_SLOTS + 1))


def test_a_flag_of_null_is_a_clear_bit() -> None:
    frame = pl.DataFrame({"a": [True, None]}, schema={"a": pl.Boolean})
    assert frame.select(m.mask([pl.col("a")]))["a"].to_list() == [1, 0]


def test_the_family_holds_each_row_once_with_its_year_and_flags() -> None:
    family = _family(
        [
            ("a", 2020, (True, False), (True, True)),
            ("b", 2021, (False, False), (True, False)),
        ],
        windows=(30, 90),
    )
    assert family.row_count == family.member_count == 2
    rows = family.rows.sort("member_id").to_dicts()
    assert rows[0] == {
        "member_id": "a",
        "anchor_year": 2020,
        "dimension_value": None,
        "counted_mask": 0b01,
        "followed_mask": 0b11,
        "multiplicity": 1,
    }
    assert rows[1]["anchor_year"] == 2021 and rows[1]["followed_mask"] == 0b01
    # Every observation of the family is a filter of those rows.
    assert _multiset(family, year=None, window=30) == Counter(
        {("a", True, True): 1, ("b", False, True): 1}
    )
    assert _multiset(family, year=None, window=90) == Counter(
        {("a", False, True): 1, ("b", False, False): 1}
    )
    assert _multiset(family, year=2020, window=30) == Counter({("a", True, True): 1})
    assert _multiset(family, year=2022, window=30) == Counter()
    with pytest.raises(MemberError, match="not one of the family's windows"):
        family.project(window=365)


def test_identical_rows_merge_into_one_with_a_multiplicity() -> None:
    family = _family(
        [
            ("a", 2020, (False,), (True,)),
            ("a", 2020, (False,), (True,)),
            ("b", 2020, (True,), (True,)),
        ],
        windows=(None,),
    )
    assert family.row_count == 2 and family.member_count == 3
    assert _multiset(family, window=None) == Counter({("a", False, True): 2, ("b", True, True): 1})


def test_rows_sharing_an_id_are_paired_by_sorted_order_per_window() -> None:
    """Two defendants of one case: who reoffended first is not recoverable, so it is fixed."""
    first = _family(
        [
            ("case", 2020, (True, True), (True, True)),  # reoffends within 30 days
            ("case", 2020, (False, True), (True, True)),  # only within 90
        ],
        windows=(30, 90),
    )
    swapped = _family(
        [
            ("case", 2020, (False, True), (True, True)),
            ("case", 2020, (True, True), (True, True)),
        ],
        windows=(30, 90),
    )
    # Pairing the first atom's window-30 flag with the second's window-90 flag, or the
    # other way round, is the same family: only the per-window multisets are kept.
    assert first.digest == swapped.digest
    assert first.rows.equals(swapped.rows)
    assert _multiset(first, window=30) == Counter(
        {("case", True, True): 1, ("case", False, True): 1}
    )
    assert _multiset(first, window=90) == Counter({("case", True, True): 2})
    crossed = _family(
        [("case", 2020, (True, False), (True, True)), ("case", 2020, (False, True), (True, True))],
        windows=(30, 90),
    )
    # The same per-window multisets as above for window 30, but window 90 differs: a different family.
    assert crossed.digest != first.digest
    assert _multiset(crossed, window=90) == Counter(
        {("case", True, True): 1, ("case", False, True): 1}
    )


def test_the_digest_is_order_independent_and_moves_with_every_stored_fact() -> None:
    rng = random.Random(3)  # noqa: S311 - a fixed shuffle, not a secret
    rows = [
        (f"id-{i}", 2019 + i % 3, (bool(i & 1), bool(i & 2)), (True, bool(i & 4)))
        for i in range(40)
    ]
    base = _family(rows, windows=(30, 90))
    shuffled = rows[:]
    rng.shuffle(shuffled)
    assert _family(shuffled, windows=(30, 90)).digest == base.digest
    assert len(base.digest) == 64 and base.digest == _family(rows, windows=(30, 90)).digest
    # A flag, a year, an id, or the kind changes the content.
    flipped = [(*rows[0][:2], (not rows[0][2][0], rows[0][2][1]), rows[0][3]), *rows[1:]]
    assert _family(flipped, windows=(30, 90)).digest != base.digest
    moved = [(rows[0][0], 2030, *rows[0][2:]), *rows[1:]]
    assert _family(moved, windows=(30, 90)).digest != base.digest
    renamed = [("other", *rows[0][1:]), *rows[1:]]
    assert _family(renamed, windows=(30, 90)).digest != base.digest
    assert _family(rows, windows=(30, 90), kind="charge").digest != base.digest


def test_an_empty_family_has_a_digest_and_no_members() -> None:
    empty = MemberFamily("decision", PLAIN, (None,), m.empty_rows())
    assert empty.row_count == empty.member_count == 0
    assert empty.members() == ()
    assert empty.digest == MemberFamily("decision", PLAIN, (None,), m.empty_rows()).digest
    assert empty.digest != MemberFamily("charge", PLAIN, (None,), m.empty_rows()).digest
    assert empty.ids().len() == 0


def test_a_distribution_row_counts_in_the_value_it_belongs_to() -> None:
    frame = pl.DataFrame(
        {"id": ["a", "b", "c"], "at": [_at(2020), _at(2020), _at(2021)], "d": ["x", "y", "x"]},
        schema_overrides={"at": pl.Datetime("us", "UTC")},
    )
    family = MemberFamily(
        "charge",
        COUNTED_IN,
        (None,),
        atoms(
            frame,
            member_id="id",
            anchor="at",
            counted=[pl.lit(False)],
            followed=[pl.lit(True)],
            dimension=pl.col("d"),
        ),
    )
    # Every row is a member of every value's observation; it counts in its own.
    assert _multiset(family, dimension="x") == Counter(
        {("a", True, True): 1, ("b", False, True): 1, ("c", True, True): 1}
    )
    assert _multiset(family, dimension="y") == Counter(
        {("a", False, True): 1, ("b", True, True): 1, ("c", False, True): 1}
    )
    assert _multiset(family, year=2021, dimension="x") == Counter({("c", True, True): 1})
    assert _multiset(family, dimension="never") == Counter(
        {("a", False, True): 1, ("b", False, True): 1, ("c", False, True): 1}
    )


def test_a_median_by_dimension_keeps_each_row_in_its_dimensions_observation_only() -> None:
    frame = pl.DataFrame(
        {
            "id": ["a", "b", "c"],
            "at": [_at(2020), _at(2020), _at(2020)],
            "category": ["theft", "theft", "drug"],
            "has": [True, False, True],
        },
        schema_overrides={"at": pl.Datetime("us", "UTC")},
    )
    family = MemberFamily(
        "sentence",
        BELONGS_TO,
        (None,),
        atoms(
            frame,
            member_id="id",
            anchor="at",
            counted=[pl.col("has")],
            followed=[pl.col("has")],
            dimension=pl.col("category"),
        ),
    )
    assert _multiset(family, dimension="theft") == Counter(
        {("a", True, True): 1, ("b", False, False): 1}
    )
    assert _multiset(family, dimension="drug") == Counter({("c", True, True): 1})
    assert _multiset(family, year=2020, dimension="drug") == Counter({("c", True, True): 1})


def test_a_family_without_an_anchor_has_no_year_and_is_only_in_the_whole_window() -> None:
    frame = pl.DataFrame({"id": ["a"], "yes": [True]})
    family = MemberFamily(
        "decision",
        PLAIN,
        (None,),
        atoms(
            frame, member_id="id", anchor=None, counted=[pl.col("yes")], followed=[pl.col("yes")]
        ),
    )
    assert family.rows["anchor_year"].to_list() == [None]
    assert _multiset(family) == Counter({("a", True, True): 1})
    assert _multiset(family, year=2020) == Counter()


def test_members_expand_to_member_objects_and_ids_are_distinct() -> None:
    family = _family(
        [
            ("a", 2020, (True,), (True,)),
            ("a", 2020, (True,), (True,)),
            ("b", 2020, (False,), (True,)),
        ],
        windows=(None,),
        kind="court_case",
    )
    members = family.members()
    assert Counter(members) == Counter(
        {Member("court_case", "a", True, True): 2, Member("court_case", "b", False, True): 1}
    )
    assert sorted(family.ids().to_list()) == ["a", "b"]


def test_a_stored_family_reads_back_to_the_same_content() -> None:
    family = _family(
        [("a", 2020, (True, False), (True, True)), ("b", 2021, (False, True), (True, False))],
        windows=(30, 90),
    )
    reversed_rows = family.rows.reverse()
    again = MemberFamily.from_stored("court_case", PLAIN, (30, 90), reversed_rows)
    assert again.digest == family.digest and again.rows.equals(family.rows)


def test_modes_and_windows_follow_the_definition_kind() -> None:
    assert mode_for("distribution", None) == COUNTED_IN
    assert mode_for("median", "offense_category") == BELONGS_TO
    assert mode_for("median", None) == PLAIN
    for kind in ("count", "share", "windowed_rate", "survival", "observed_expected"):
        assert mode_for(kind, None) == PLAIN
    assert windows_for("windowed_rate", [30, 90]) == (30, 90)
    assert windows_for("observed_expected", [365]) == (365,)
    assert windows_for("observed_expected", None) == (None,)
    assert windows_for("share", None) == (None,)
    assert windows_for("count", [30]) == (None,)
    with pytest.raises(MemberError):
        MemberFamily("decision", "sideways", (None,), m.empty_rows())
