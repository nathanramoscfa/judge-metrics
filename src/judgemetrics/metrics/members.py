# src/judgemetrics/metrics/members.py
"""Member families: the canonical rows behind a metric's observations, kept once.

Every observation of a metric for one subject and source — each window, each
calendar year, each dimension value — is a different cut of the same canonical
rows. Phase 3 stored one member row per row per observation; at Cook County's
scale that is a billion rows. A ``MemberFamily`` holds each row once, with what is
needed to cut it again, and every observation's member multiset is a *filter* of it:

========================  ==========================================================
``member_id``             the entity id of the public row (a decision, charge, case,
                          sentence, court event, or justice event — ``kind``); never
                          a person id
``anchor_year``           the calendar year (UTC) of the row's anchor
                          (``registry.POPULATION_ANCHORS``): the year observation that
                          holds it; null when the anchor is unknown
``dimension_value``       the dimension value the row belongs to (``BELONGS_TO``: a
                          median by offense category) or counts in (``COUNTED_IN``: the
                          final disposition of a distribution); null otherwise
``counted_mask``          bit ``i`` is the row's ``counted`` flag in the family's
``followed_mask``         ``i``-th window (``windows``; slot 0 when the metric has none)
``multiplicity``          how many identical rows the family holds: a disposed case
                          is one index event per defendant, with no person id kept
========================  ==========================================================

``project(year, window, dimension)`` is the one rule that turns a family back into
an observation's member multiset ``(member_id, counted, followed) x copies``; the
SQL form in ``member_store`` is its twin, and ``tests/integration/test_member_storage``
holds them equal on the golden data. A family is *canonical*: rows that are identical
in every column are merged into one with a multiplicity, and rows that share
``(member_id, anchor_year, dimension_value)`` but differ in their flags are paired
by sorted order per window — the pairing is not recoverable from the observations'
multisets, so it is fixed — which makes the family a function of those multisets
alone and lets ``digest`` (the sha256 of the sorted rows) stand for "the same members"
whoever computed it, the migration included.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import polars as pl

ID: Final = "member_id"
YEAR: Final = "anchor_year"
DIMENSION: Final = "dimension_value"
COUNTED: Final = "counted_mask"
FOLLOWED: Final = "followed_mask"
COPIES: Final = "multiplicity"
KEY: Final[tuple[str, ...]] = (ID, YEAR, DIMENSION)
FLAGS: Final[tuple[str, ...]] = (COUNTED, FOLLOWED)
COLUMNS: Final[tuple[str, ...]] = (ID, YEAR, DIMENSION, COUNTED, FOLLOWED, COPIES)
SCHEMA: Final = pl.Schema(
    {
        ID: pl.String(),
        YEAR: pl.Int16(),
        DIMENSION: pl.String(),
        COUNTED: pl.Int16(),
        FOLLOWED: pl.Int16(),
        COPIES: pl.Int32(),
    }
)
ATOM_SCHEMA: Final = pl.Schema({name: SCHEMA[name] for name in (*KEY, *FLAGS)})
# A smallint mask holds fifteen non-negative bits: windows per metric.
MAX_SLOTS: Final = 15

# How a member relates to the dimension value of an observation.
PLAIN: Final = "plain"
BELONGS_TO: Final = "belongs_to"
COUNTED_IN: Final = "counted_in"
MODES: Final[tuple[str, ...]] = (PLAIN, BELONGS_TO, COUNTED_IN)


# The registry kinds whose observations carry follow-up windows (one flag slot per window).
WINDOWED_KINDS: Final[tuple[str, ...]] = ("windowed_rate", "survival", "observed_expected")


class MemberError(ValueError):
    """A family cannot be built or read as asked (an engine defect, never a data defect)."""


def mode_for(kind: str, dimension: str | None) -> str:
    """How a definition's members relate to an observation's dimension value.

    A distribution's rows all belong to every value's observation and count in the one of
    their own value; a median by dimension keeps each row in its dimension's observation
    only; everything else has no dimension to cut by.
    """
    if kind == "distribution":
        return COUNTED_IN
    if kind == "median" and dimension is not None:
        return BELONGS_TO
    return PLAIN


def windows_for(kind: str, windows_days: Sequence[int] | None) -> tuple[int | None, ...]:
    """The flag slots of a definition: its windows, or the single slot ``None``."""
    if kind in WINDOWED_KINDS and windows_days:
        return tuple(windows_days)
    return (None,)


@dataclass(frozen=True, slots=True)
class Member:
    """One canonical row behind an observation: ``(kind, id, counted, followed)``."""

    kind: str
    id: str
    counted: bool
    followed: bool

    def as_tuple(self) -> tuple[str, str, bool, bool]:
        return (self.kind, self.id, self.counted, self.followed)


# --- building atoms ---------------------------------------------------------------------


def mask(flags: Sequence[pl.Expr]) -> pl.Expr:
    """The bit mask whose bit ``i`` is ``flags[i]`` (a null flag is a clear bit)."""
    if not 0 < len(flags) <= MAX_SLOTS:
        msg = f"a family has between 1 and {MAX_SLOTS} window slots; got {len(flags)}"
        raise MemberError(msg)
    terms = [flag.fill_null(False).cast(pl.Int16) * (1 << slot) for slot, flag in enumerate(flags)]
    return pl.sum_horizontal(terms).cast(pl.Int16)


def anchor_year(anchor: str | pl.Expr | None) -> pl.Expr:
    """The calendar year (UTC) of an anchor column, as the family stores it (null: no anchor)."""
    if anchor is None:
        return pl.lit(None, dtype=pl.Int16).alias(YEAR)
    column = pl.col(anchor) if isinstance(anchor, str) else anchor
    return column.dt.year().cast(pl.Int16).alias(YEAR)


def atoms(
    rows: pl.DataFrame,
    *,
    member_id: str | pl.Expr,
    anchor: str | pl.Expr | None,
    counted: Sequence[pl.Expr],
    followed: Sequence[pl.Expr],
    dimension: pl.Expr | None = None,
) -> pl.DataFrame:
    """One atom per row of ``rows``: the id, anchor year, dimension, and flag masks."""
    ident = pl.col(member_id) if isinstance(member_id, str) else member_id
    value = pl.lit(None, dtype=pl.String) if dimension is None else dimension.cast(pl.String)
    return rows.select(
        ident.cast(pl.String).alias(ID),
        anchor_year(anchor),
        value.alias(DIMENSION),
        mask(counted).alias(COUNTED),
        mask(followed).alias(FOLLOWED),
    )


# --- canonical form ---------------------------------------------------------------------


def _normalized(frame: pl.DataFrame, slots: int) -> pl.DataFrame:
    """Pair the flags of rows sharing ``KEY`` by sorted order, per window slot.

    Within such a group of ``m`` rows, window ``s`` holds a multiset of ``(counted,
    followed)`` pairs, encoded ``2 * counted + followed``; the ``k``-th smallest goes
    to the ``k``-th row in every slot. Only the multisets per window survive, which
    is all an observation records.
    """
    columns: list[pl.Expr] = []
    for slot in range(slots):
        bit = 1 << slot
        code = ((pl.col(COUNTED) & bit) != 0).cast(pl.Int16) * 2 + (
            (pl.col(FOLLOWED) & bit) != 0
        ).cast(pl.Int16)
        columns.append(code.sort().over(list(KEY)).alias(f"_code{slot}"))
    coded = frame.with_columns(columns)
    counted = pl.sum_horizontal(
        [((pl.col(f"_code{slot}") // 2).cast(pl.Int16) * (1 << slot)) for slot in range(slots)]
    )
    followed = pl.sum_horizontal(
        [((pl.col(f"_code{slot}") % 2).cast(pl.Int16) * (1 << slot)) for slot in range(slots)]
    )
    return coded.select(
        ID,
        YEAR,
        DIMENSION,
        counted.cast(pl.Int16).alias(COUNTED),
        followed.cast(pl.Int16).alias(FOLLOWED),
    )


def canonical(frame: pl.DataFrame, slots: int) -> pl.DataFrame:
    """The canonical rows of ``frame``'s atoms: paired, merged, sorted (module docstring)."""
    atoms_only = frame.select(*KEY, *FLAGS).cast(ATOM_SCHEMA)
    if atoms_only.height and atoms_only.n_unique(subset=list(KEY)) < atoms_only.height:
        atoms_only = _normalized(atoms_only, slots)
    return (
        atoms_only.group_by([*KEY, *FLAGS])
        .agg(pl.len().cast(pl.Int32).alias(COPIES))
        .select(COLUMNS)
        .sort([*KEY, *FLAGS])
    )


def empty_rows() -> pl.DataFrame:
    """A family with no row (an observation whose population is empty)."""
    return pl.DataFrame(schema=SCHEMA)


# --- the family -------------------------------------------------------------------------


class MemberFamily:
    """The canonical members behind the observations of one definition, subject, and source.

    ``kind`` is the member kind (one per family), ``mode`` how a member relates to an
    observation's dimension value, ``windows`` the definition's windows (slot ``i`` is
    ``windows[i]``; ``(None,)`` for a metric without windows).
    """

    __slots__ = ("_digest", "kind", "mode", "rows", "windows")

    def __init__(
        self,
        kind: str,
        mode: str,
        windows: Sequence[int | None],
        rows: pl.DataFrame,
        *,
        is_canonical: bool = False,
    ) -> None:
        if mode not in MODES:
            msg = f"unknown member mode {mode!r}"
            raise MemberError(msg)
        self.kind = kind
        self.mode = mode
        self.windows = tuple(windows)
        if not 0 < len(self.windows) <= MAX_SLOTS:
            msg = f"a family has between 1 and {MAX_SLOTS} window slots"
            raise MemberError(msg)
        self.rows = rows if is_canonical else canonical(rows, len(self.windows))
        self._digest: str | None = None

    @classmethod
    def from_stored(
        cls, kind: str, mode: str, windows: Sequence[int | None], rows: pl.DataFrame
    ) -> MemberFamily:
        """A family read back from the database: already canonical, only sorted again."""
        ordered = rows.select(COLUMNS).cast(SCHEMA).sort([*KEY, *FLAGS])
        return cls(kind, mode, windows, ordered, is_canonical=True)

    # --- identity ---------------------------------------------------------------------

    @property
    def digest(self) -> str:
        """sha256 over the kind and the canonical rows as text: "the same members"."""
        if self._digest is None:
            text = ""
            if self.rows.height:
                text = self.rows.select(
                    pl.concat_str(
                        [
                            pl.col(ID),
                            pl.col(YEAR).cast(pl.String).fill_null(""),
                            pl.col(DIMENSION).fill_null(""),
                            pl.col(COUNTED).cast(pl.String),
                            pl.col(FOLLOWED).cast(pl.String),
                            pl.col(COPIES).cast(pl.String),
                        ],
                        separator="|",
                    ).str.join("\n")
                ).item()
            self._digest = hashlib.sha256(f"{self.kind}\n{text}".encode()).hexdigest()
        return self._digest

    @property
    def row_count(self) -> int:
        """Rows stored (distinct profiles)."""
        return self.rows.height

    @property
    def member_count(self) -> int:
        """Members represented: the sum of the multiplicities."""
        return int(self.rows[COPIES].sum()) if self.rows.height else 0

    def ids(self) -> pl.Series:
        """The distinct member ids (what the provenance chain rule checks)."""
        return self.rows[ID].unique()

    # --- the observations of the family ------------------------------------------------

    def slot_of(self, window: int | None) -> int:
        try:
            return self.windows.index(window)
        except ValueError:
            msg = f"window {window!r} is not one of the family's windows {self.windows}"
            raise MemberError(msg) from None

    def project(
        self, *, year: int | None = None, window: int | None = None, dimension: str | None = None
    ) -> pl.DataFrame:
        """``(member_id, counted, followed, multiplicity)`` of one observation of the family.

        ``year`` keeps the rows whose anchor falls in that calendar year (``None``: the
        whole coverage window); ``window`` selects the flag slot; ``dimension`` is the
        observation's dimension value (see ``mode``).
        """
        bit = 1 << self.slot_of(window)
        rows = self.rows
        if year is not None:
            rows = rows.filter(pl.col(YEAR) == year)
        if self.mode == BELONGS_TO and dimension is not None:
            rows = rows.filter(pl.col(DIMENSION) == dimension)
        if self.mode == COUNTED_IN:
            counted = (pl.col(DIMENSION) == dimension).fill_null(False)
        else:
            counted = (pl.col(COUNTED) & bit) != 0
        return rows.select(
            pl.col(ID).alias("member_id"),
            counted.alias("counted"),
            ((pl.col(FOLLOWED) & bit) != 0).alias("followed"),
            pl.col(COPIES).alias("multiplicity"),
        )

    def members(
        self, *, year: int | None = None, window: int | None = None, dimension: str | None = None
    ) -> tuple[Member, ...]:
        """The observation's member multiset, one ``Member`` per copy (tests and small data)."""
        found: list[Member] = []
        for ident, counted, followed, copies in self.project(
            year=year, window=window, dimension=dimension
        ).iter_rows():
            found.extend([Member(self.kind, str(ident), bool(counted), bool(followed))] * copies)
        return tuple(found)

    def __repr__(self) -> str:
        return (
            f"MemberFamily(kind={self.kind!r}, mode={self.mode!r}, windows={self.windows}, "
            f"rows={self.row_count}, members={self.member_count})"
        )
