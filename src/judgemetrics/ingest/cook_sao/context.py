# src/judgemetrics/ingest/cook_sao/context.py
"""The five exports of a run, indexed for the connector: sorted frames and the judge tables.

``CookContext.build`` reads every export once (``frames.read_export``: only the columns the
connector uses, dates parsed, rows in a canonical order) and derives, with Polars
aggregates over the Dispositions and Sentencing frames, what no single case knows:

- the **judges** the run references — every judge string of ``JUDGE`` and
  ``SENTENCE_JUDGE`` that ``judge_aliases.csv`` resolves — and one **service** per
  judge and court, from the first to the last disposition or sentence date attributed
  to that judge there;
- a finding per judge string the table holds ``ambiguous`` or ``unresolved`` (with its
  row count): its rows are published without a judge, and the alias table is this
  phase's judge review queue.

``cases`` then walks the exports together in ``CASE_ID`` order, yielding the rows of
each case across the five (a k-way merge of the sorted frames, one case in memory at a
time), and releases the frames when it is exhausted.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from itertools import groupby
from operator import itemgetter
from pathlib import Path

import polars as pl

from judgemetrics.ingest.cook_sao import findings as codes
from judgemetrics.ingest.cook_sao.case import Row
from judgemetrics.ingest.cook_sao.findings import Findings
from judgemetrics.ingest.cook_sao.frames import read_export
from judgemetrics.ingest.cook_sao.rules import RESOLVED, CookSaoRules
from judgemetrics.ingest.cook_sao.schema import (
    CASE_ID,
    DATASET_ORDER,
    DISPOSITIONS_FILE,
    SENTENCING_FILE,
)

# (judge column, court name column, courthouse column, date column) of the two exports that name judges.
JUDGE_SOURCES: dict[str, tuple[str, str, str, str]] = {
    DISPOSITIONS_FILE: (
        "JUDGE",
        "DISPOSITION_COURT_NAME",
        "DISPOSITION_COURT_FACILITY",
        "DISPOSITION_DATE",
    ),
    SENTENCING_FILE: (
        "SENTENCE_JUDGE",
        "SENTENCE_COURT_NAME",
        "SENTENCE_COURT_FACILITY",
        "SENTENCE_DATE",
    ),
}


@dataclass(slots=True)
class Service:
    """The span of dates a judge is attributed rows at one court."""

    start: date | None = None
    end: date | None = None

    def extend(self, first: date | None, last: date | None) -> None:
        if first is not None and (self.start is None or first < self.start):
            self.start = first
        if last is not None and (self.end is None or last > self.end):
            self.end = last


@dataclass(slots=True)
class CookContext:
    frames: dict[str, pl.DataFrame]
    # judge key -> the services derived for it (court key -> span); every referenced judge is a key.
    services: dict[str, dict[str, Service]] = field(default_factory=dict)

    @classmethod
    def build(
        cls, sources: dict[str, Path | bytes], rules: CookSaoRules, findings: Findings
    ) -> CookContext:
        frames = {name: read_export(sources[name], name, findings) for name in DATASET_ORDER}
        context = cls(frames=frames)
        for name, columns in JUDGE_SOURCES.items():
            context._attribute_judges(name, columns, rules, findings)
        return context

    def _attribute_judges(
        self,
        name: str,
        columns: tuple[str, str, str, str],
        rules: CookSaoRules,
        findings: Findings,
    ) -> None:
        judge, court, facility, when = columns
        grouped = (
            self.frames[name]
            .group_by(judge, court, facility, maintain_order=False)
            .agg(
                pl.col(when).min().alias("first"),
                pl.col(when).max().alias("last"),
                pl.len().alias("rows"),
            )
            .sort(judge, court, facility, nulls_last=False)
        )
        unresolved: dict[str, int] = {}
        for string, court_name, courthouse, first, last, rows in grouped.iter_rows():
            if string is None or not str(string).strip():
                continue
            match = rules.judge(str(string))
            if match is None:  # a non-blank string always has a match
                continue
            if match.status != RESOLVED or match.judge_key is None:
                unresolved[str(string)] = unresolved.get(str(string), 0) + int(rows)
                continue
            spans = self.services.setdefault(match.judge_key, {})
            place = rules.court_of_row(court_name, courthouse)
            if place is None:
                continue
            spans.setdefault(place.court_key, Service()).extend(
                None if first is None else first.date(), None if last is None else last.date()
            )
        for string, rows in sorted(unresolved.items()):
            match = rules.judge(string)
            if match is None:  # pragma: no cover - the string was matched above
                continue
            findings.add(
                codes.JUDGE_UNRESOLVED,
                name,
                f"{string!r} ({match.status}: {match.reason})",
                rows,
            )

    def cases(self) -> Iterator[tuple[str, dict[str, list[Row]]]]:
        """``(case id, rows by export)`` in case-id order; the frames are released at the end."""
        streams = {
            name: groupby(frame.iter_rows(named=True), key=itemgetter(CASE_ID))
            for name, frame in self.frames.items()
        }
        heads: dict[str, tuple[str, list[Row]] | None] = {
            name: _advance(stream) for name, stream in streams.items()
        }
        try:
            while True:
                live = [head[0] for head in heads.values() if head is not None]
                if not live:
                    return
                case_id = min(live)
                rows: dict[str, list[Row]] = {}
                for name in DATASET_ORDER:
                    head = heads[name]
                    if head is not None and head[0] == case_id:
                        rows[name] = head[1]
                        heads[name] = _advance(streams[name])
                yield case_id, rows
        finally:
            self.frames = {}


def _advance(stream: Iterator[tuple[str, Iterator[Row]]]) -> tuple[str, list[Row]] | None:
    for case_id, group in stream:
        return str(case_id), list(group)
    return None
