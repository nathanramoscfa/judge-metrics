# tests/property/test_feature_leakage.py
"""The expected-outcome model's features never read the future and ignore canonical ids.

For a Hypothesis-drawn seed the ``TINY`` world is built in memory
(``support.frame_from_world``). Leakage: for each index event (the release
target's decisions and a windowed target's releases), every row at or after
its known-at instants is removed — other cases, charges, failures to
appear, and decisions at or after the index case's filing; dispositions at
or after it turned back into ``pending``; the index case's own charges
filed at or after the decision, and every disposition of the index case —
and the event's feature row is unchanged. Order invariance: relabelling
every canonical id of the frame (and so reordering every table) leaves the
design matrix, the outcomes, the cluster keys, the fitted coefficients, and
the bootstrap replicate draws byte-identical.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import numpy as np
import polars as pl
import pytest
from hypothesis import given

from judgemetrics.metrics.adjustment.features import (
    DesignFrame,
    design_rows,
    feature_levels,
    target_events,
)
from judgemetrics.metrics.adjustment.logistic import fit_logistic
from judgemetrics.metrics.adjustment.resample import replicate_stream, replicates
from judgemetrics.metrics.adjustment.spec import load_spec
from judgemetrics.metrics.frame import ID, SCHEMAS, Frame
from judgemetrics.synthetic.config import TINY
from tests.property.support import build_world, frame_from_world, seeds

pytestmark = pytest.mark.property

SPEC = load_spec()
# The release target and one window of each windowed target.
TARGETS: tuple[tuple[str, int | None], ...] = (
    ("pretrial_release", None),
    ("new_case", 365),
    ("failure_to_appear", 30),
)
EVENTS_PER_TARGET = 6
REPLICATES = 5


def _events(frame: Frame, target: str, window: int | None) -> pl.DataFrame:
    events = target_events(frame, SPEC.target(target), window)
    assert isinstance(events, pl.DataFrame)
    return events.head(EVENTS_PER_TARGET)


def _truncated(frame: Frame, event: dict[str, Any]) -> Frame:
    """``frame`` without every row the event's features must not read."""
    case_id, person = event["case_id"], event["person_id"]
    filed = frame.cases.filter(pl.col("id") == case_id)["filed_at"][0]
    decided: datetime = event["decision_at"]
    cases = frame.cases.filter((pl.col("id") == case_id) | (pl.col("filed_at") < filed))
    index_charges = frame.charges.filter(
        (pl.col("case_id") == case_id)
        & (pl.col("person_id") == person)
        & (pl.col("filed_at") < decided)
    ).with_columns(
        pl.lit(None, dtype=pl.String).alias("disposition"),
        pl.lit(None, dtype=pl.Datetime("us", "UTC")).alias("disposed_at"),
        pl.lit(None, dtype=pl.String).alias("disposition_actor"),
    )
    later = pl.col("disposed_at") >= filed
    other_charges = frame.charges.filter(
        (pl.col("case_id") != case_id) & (pl.col("filed_at") < filed)
    ).with_columns(
        pl.when(later)
        .then(pl.lit("pending"))
        .otherwise(pl.col("disposition"))
        .alias("disposition"),
        pl.when(later).then(None).otherwise(pl.col("disposed_at")).alias("disposed_at"),
        pl.when(later).then(None).otherwise(pl.col("disposition_actor")).alias("disposition_actor"),
    )
    return frame.replace(
        cases=cases,
        charges=pl.concat([index_charges, other_charges]),
        decisions=frame.decisions.filter(pl.col("id") == event["member_id"]),
        assignments=frame.assignments.clear(),
        sentences=frame.sentences.clear(),
        events=frame.events.clear(),
        justice_events=frame.justice_events.filter(pl.col("event_at") < filed),
    )


@given(seed=seeds)
def test_no_feature_reads_a_row_at_or_after_its_known_at_instant(seed: int) -> None:
    frame = frame_from_world(build_world(seed, TINY), TINY)
    for target, window in TARGETS:
        events = _events(frame, target, window).with_row_index("_row")
        if events.height == 0:
            continue
        full = feature_levels(frame, SPEC, events)
        for event in events.iter_rows(named=True):
            single = events.filter(pl.col("_row") == event["_row"])
            truncated = feature_levels(_truncated(frame, event), SPEC, single)
            expected = full.filter(pl.col("_row") == event["_row"])
            assert truncated.to_dicts() == expected.to_dicts(), (seed, target, event["member_id"])


def _relabel(frame: Frame) -> Frame:
    """Every canonical id replaced by a hash of itself; every table reordered by its new ids."""

    def new(value: str) -> str:
        return "R" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]

    ids: set[str] = set()
    for name, schema in SCHEMAS.items():
        table = frame.table(name)
        for column, spec in schema.items():
            if spec == ID:
                ids.update(str(value) for value in table[column].drop_nulls().to_list())
    mapping = {value: new(value) for value in ids}
    tables: dict[str, pl.DataFrame] = {}
    for name, schema in SCHEMAS.items():
        columns = [column for column, spec in schema.items() if spec == ID]
        relabelled = frame.table(name).with_columns(
            pl.col(column).replace_strict(mapping, default=None, return_dtype=pl.String)
            for column in columns
        )
        tables[name] = relabelled.sort(columns[0], nulls_last=True)
    return frame.replace(**tables)


def _design(frame: Frame, target: str, window: int | None) -> DesignFrame:
    design = design_rows(frame, SPEC, SPEC.target(target), window)
    assert isinstance(design, DesignFrame)
    return design


@given(seed=seeds)
def test_relabelling_every_id_leaves_the_design_the_fit_and_the_replicates_identical(
    seed: int,
) -> None:
    frame = frame_from_world(build_world(seed, TINY), TINY)
    relabelled = _relabel(frame)
    assert set(frame.cases["id"].to_list()).isdisjoint(relabelled.cases["id"].to_list())
    settings = SPEC.model
    for target, window in TARGETS:
        original = _design(frame, target, window)
        again = _design(relabelled, target, window)
        assert [c.name for c in original.columns] == [c.name for c in again.columns], seed
        assert original.matrix.tobytes() == again.matrix.tobytes(), (seed, target)
        assert original.outcome.tobytes() == again.outcome.tobytes(), (seed, target)
        assert original.index_at.tobytes() == again.index_at.tobytes(), (seed, target)
        assert original.clusters == again.clusters, (seed, target)
        if original.rows == 0:
            continue
        fits = [
            fit_logistic(
                design.matrix,
                design.outcome,
                lam=settings.lam,
                max_iterations=settings.max_iterations,
                tolerance=settings.tolerance,
                step_halvings=settings.step_halvings,
            )
            for design in (original, again)
        ]
        assert fits[0].coefficients.tobytes() == fits[1].coefficients.tobytes(), (seed, target)
        stream = replicate_stream(target, window)
        draws = [
            np.vstack(
                list(replicates(design.clusters, seed=SPEC.seed, stream=stream, count=REPLICATES))
            )
            for design in (original, again)
        ]
        assert draws[0].tobytes() == draws[1].tobytes(), (seed, target)
