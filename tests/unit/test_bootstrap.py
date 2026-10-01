# tests/unit/test_bootstrap.py
"""The pooled ratio's bootstrap interval: deterministic, label-free, reproducible from the artifact.

Over the golden world built in memory (seed 7), the release target's design
is fitted with the events-per-column gate lifted and a short bootstrap (the
golden cohorts are too small for the published gate; the arithmetic is the
same): the replicate pooled ratios are identical across two runs and after
every canonical id of the frame is relabelled (each judge's figures equal
its relabelled twin's, bit for bit); the interval of the best-populated
judge contains its pooled estimate; and a replicate set read back from the
model's artifact — rendered, written, and read through
``catalog.read_parameters`` — reproduces the in-memory interval exactly,
because ``ModelParameters.from_fitted`` rounds as the artifact does. A
replicate whose refit did not converge is skipped with its weights still
drawn.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from judgemetrics.config import Settings
from judgemetrics.metrics.adjustment.artifacts import write_artifact
from judgemetrics.metrics.adjustment.bootstrap import interval, replicate_ratios
from judgemetrics.metrics.adjustment.catalog import read_parameters
from judgemetrics.metrics.adjustment.expected import ModelParameters, expectations
from judgemetrics.metrics.adjustment.features import DesignFrame, design_rows
from judgemetrics.metrics.adjustment.fit import FITTED, FittedModel, fit_design
from judgemetrics.metrics.adjustment.ratios import Estimates, estimate
from judgemetrics.metrics.adjustment.spec import OutcomeModelSpec, load_spec
from judgemetrics.metrics.frame import Frame
from judgemetrics.synthetic.config import GOLDEN
from tests.property.support import build_world, frame_from_world, relabel_frame

pytestmark = pytest.mark.unit

GOLDEN_SEED = 7
REPLICATES = 40
SNAPSHOT = "ab" * 32
TARGET = "pretrial_release"


def _spec() -> OutcomeModelSpec:
    spec = load_spec()
    return replace(
        spec,
        thresholds=replace(spec.thresholds, minimum_events_per_column=0),
        bootstrap=replace(spec.bootstrap, replicates=REPLICATES),
    )


SPEC = _spec()


def _fit(frame: Frame) -> tuple[DesignFrame, FittedModel]:
    design = design_rows(frame, SPEC, SPEC.target(TARGET), None)
    assert isinstance(design, DesignFrame)
    model = fit_design(design, SPEC, seed=SPEC.seed, source="synthetic")
    assert model.status == FITTED
    return design, model


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    frame = frame_from_world(build_world(GOLDEN_SEED, GOLDEN), GOLDEN)
    design, model = _fit(frame)
    return {"frame": frame, "design": design, "model": model}


def _estimate(design: DesignFrame, model: FittedModel) -> Estimates:
    return estimate(design, ModelParameters.from_fitted(model), SPEC)


def test_replicates_are_identical_across_two_runs(golden: dict[str, Any]) -> None:
    design, model = golden["design"], golden["model"]
    first = _estimate(design, model)
    second = _estimate(design, model)
    for name in ("ratio", "weight", "lower", "upper"):
        assert getattr(first, name).tobytes() == getattr(second, name).tobytes(), name
    parameters = ModelParameters.from_fitted(model)
    scored = expectations(design, parameters)
    ratios = [
        replicate_ratios(
            scored,
            design,
            parameters.replicates,
            seed=parameters.seed,
            bounds=SPEC.pooling.shape_bounds,
            grid=SPEC.pooling.shape_grid,
        )
        for _ in range(2)
    ]
    assert ratios[0].shape == (REPLICATES, len(scored.judges))
    assert ratios[0].tobytes() == ratios[1].tobytes()


def test_replicates_are_identical_after_every_id_is_relabelled(golden: dict[str, Any]) -> None:
    original = _estimate(golden["design"], golden["model"])
    relabelled_frame, mapping = relabel_frame(golden["frame"])
    design, model = _fit(relabelled_frame)
    again = _estimate(design, model)
    assert again.shape == original.shape
    position = {judge: index for index, judge in enumerate(again.scored.judges)}
    assert len(position) == len(original.scored.judges)
    for index, judge in enumerate(original.scored.judges):
        twin = position[mapping[judge]]
        assert again.scored.size[twin] == original.scored.size[index]
        assert again.scored.observed[twin] == original.scored.observed[index]
        assert again.scored.expected is not None and original.scored.expected is not None
        assert again.scored.expected[twin] == original.scored.expected[index]
        for name in ("ratio", "weight", "lower", "upper"):
            assert getattr(again, name)[twin] == getattr(original, name)[index], (judge, name)


def test_the_interval_contains_the_pooled_estimate_of_a_well_populated_judge(
    golden: dict[str, Any],
) -> None:
    estimates = _estimate(golden["design"], golden["model"])
    busiest = int(np.argmax(estimates.scored.size))
    assert estimates.scored.size[busiest] >= 10
    assert estimates.lower[busiest] <= estimates.ratio[busiest] <= estimates.upper[busiest]
    assert estimates.lower[busiest] < estimates.upper[busiest]
    assert estimates.shape is not None


def test_a_replicate_set_read_from_the_artifact_reproduces_the_interval(
    golden: dict[str, Any], tmp_path: Path
) -> None:
    design, model = golden["design"], golden["model"]
    data = model.render(snapshot=SNAPSHOT, code_version="test")
    _, content_hash, written = write_artifact(tmp_path, SNAPSHOT, data)
    assert written
    stored = read_parameters(Settings(env="test", snapshot_dir=tmp_path), SNAPSHOT, content_hash)
    assert stored.content_hash == content_hash and stored.status == FITTED
    in_memory = ModelParameters.from_fitted(model)
    assert stored.columns == in_memory.columns
    assert stored.coefficients is not None and in_memory.coefficients is not None
    assert stored.coefficients.tobytes() == in_memory.coefficients.tobytes()
    assert len(stored.replicates) == REPLICATES
    from_artifact = estimate(design, stored, SPEC)
    from_fit = estimate(design, in_memory, SPEC)
    for name in ("ratio", "weight", "lower", "upper"):
        assert getattr(from_artifact, name).tobytes() == getattr(from_fit, name).tobytes(), name


def test_a_replicate_that_did_not_converge_is_skipped_with_its_weights_drawn(
    golden: dict[str, Any],
) -> None:
    design, model = golden["design"], golden["model"]
    parameters = ModelParameters.from_fitted(model)
    scored = expectations(design, parameters)
    full = interval(
        scored,
        design,
        parameters.replicates,
        seed=parameters.seed,
        bounds=SPEC.pooling.shape_bounds,
        grid=SPEC.pooling.shape_grid,
        level=SPEC.bootstrap.level,
    )
    dropped = (None, *parameters.replicates[1:])
    partial = interval(
        scored,
        design,
        dropped,
        seed=parameters.seed,
        bounds=SPEC.pooling.shape_bounds,
        grid=SPEC.pooling.shape_grid,
        level=SPEC.bootstrap.level,
    )
    assert (full.replicates, partial.replicates) == (REPLICATES, REPLICATES - 1)
    assert partial.requested == full.requested == REPLICATES
    # Replicate r keeps replicate r's weights: the rest of the draws are unchanged.
    assert partial.ratios.tobytes() == full.ratios[1:].tobytes()
