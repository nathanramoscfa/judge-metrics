# src/judgemetrics/metrics/periods.py
"""Periods: the whole coverage window, the calendar years, and the anchors that place a row.

Registry version 3 (``periods`` in ``data/reference/metric_registry.yaml``,
methodology 1.1): every metric publishes one observation over the source's
whole coverage window, and every descriptive metric publishes one more per
calendar year (UTC) in which its population has an *anchor* —
``registry.POPULATION_ANCHORS``: the filing for the case counts, the decision,
the disposition, the case disposition, the sentence, and the index time for a
windowed metric.

A row enters a period only when its anchor lies inside the source's coverage
window, ``[coverage_start 00:00 UTC, coverage_end + 1 day 00:00 UTC)``
(``within_coverage``): every counted row then falls within the dates an
observation states, and a row the source dates outside its own window (a typo
year, a disposition before the corpus begins) enters no observation. A row
whose anchor is null enters none either. Because every row of the whole window
falls in exactly one of its years, the years' counts, numerators, and
denominators add up to the whole window's (``tests/property/test_period_consistency.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from judgemetrics.metrics.frame import Frame

YEAR = "_anchor_year"


@dataclass(frozen=True, slots=True)
class Period:
    """An observation's period: its first and last days, and its calendar year (or none)."""

    start: date
    end: date
    calendar_year: int | None = None

    @property
    def is_whole_window(self) -> bool:
        return self.calendar_year is None


def whole_window(frame: Frame) -> Period:
    """The source's coverage window as a period."""
    return Period(frame.coverage_start, frame.coverage_end, None)


def year_period(year: int) -> Period:
    """Calendar year ``year`` (UTC): January 1 to December 31."""
    return Period(date(year, 1, 1), date(year, 12, 31), year)


def within_coverage(frame: Frame, rows: pl.DataFrame, anchor: str) -> pl.DataFrame:
    """``rows`` whose ``anchor`` lies inside the coverage window (a null anchor never does)."""
    return rows.filter(
        pl.col(anchor).is_not_null()
        & (pl.col(anchor) >= pl.lit(frame.coverage_start_at))
        & (pl.col(anchor) < pl.lit(frame.coverage_end_exclusive_at))
    )


def calendar_years(rows: pl.DataFrame, anchor: str) -> list[int]:
    """The calendar years (UTC) the rows' anchors fall in, ascending."""
    if rows.height == 0:
        return []
    years = rows.select(pl.col(anchor).dt.year().alias(YEAR)).drop_nulls().unique()
    return sorted(int(year) for year in years[YEAR].to_list())


def split(
    frame: Frame, rows: pl.DataFrame, anchor: str, *, by_year: bool
) -> list[tuple[Period, pl.DataFrame]]:
    """The whole window's rows, then (``by_year``) each calendar year's.

    ``rows`` must already be ``within_coverage``: a year holds exactly the
    whole window's rows whose anchor falls in it.
    """
    periods: list[tuple[Period, pl.DataFrame]] = [(whole_window(frame), rows)]
    if not by_year:
        return periods
    for year in calendar_years(rows, anchor):
        periods.append((year_period(year), rows.filter(pl.col(anchor).dt.year() == year)))
    return periods
