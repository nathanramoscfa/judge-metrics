# tests/unit/test_model_artifacts.py
"""Fitted-model artifacts: canonical bytes, content hash, write-once, no person-level row.

``render`` sorts keys, rounds every float to twelve significant digits, and
refuses a NaN; the content hash is the sha256 of the bytes; a path is built
only from two validated hashes and stays under the root; an equal artifact
is a no-op and a different one at an existing path raises. The inspection
test (``inspect_artifact``, also run by the integration suite over what
``models fit`` writes) walks every artifact a fit writes — the golden and
the demo worlds in memory, fitted under a reduced bootstrap so the unit run
stays fast — and finds no array longer than the design's structure (its
columns, the features, the ten bins, the solver's iteration limit; the
replicate list is exactly the requested count), so none is as long as the
index-event or person count; no UUID-shaped string; no 64-hex string other
than the snapshot hash; and no key naming a person, case, decision, or
participant.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from judgemetrics.metrics.adjustment.artifacts import (
    ArtifactError,
    artifact_path,
    content_hash,
    render,
    round_significant,
    write_artifact,
)
from judgemetrics.metrics.adjustment.diagnostics import BINS
from judgemetrics.metrics.adjustment.fit import FITTED, INSUFFICIENT_EVENTS, FittedModel, fit_frame
from judgemetrics.metrics.adjustment.spec import OutcomeModelSpec, load_spec
from judgemetrics.synthetic.config import DEMO, GOLDEN, ScaleSpec
from tests.property.support import build_world, frame_from_world

pytestmark = pytest.mark.unit

SPEC = load_spec()
SNAPSHOT = "ab" * 32
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
HEX64 = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
PERSON_KEYS = re.compile(r"person|case|decision|participant")


def inspect_artifact(
    payload: dict[str, Any], *, snapshot: str, rows: int, persons: int, spec: OutcomeModelSpec
) -> None:
    """Assert that an artifact holds no person-level row (see the module docstring)."""
    columns = payload["design"]["columns"]
    bound = max(len(columns), len(spec.features), BINS, spec.model.max_iterations)
    replicates = payload.get("replicates")
    replicate_list: list[Any] | None = None if replicates is None else replicates["coefficients"]
    if replicates is not None and replicate_list is not None:
        assert len(replicate_list) == replicates["requested"]

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                assert not PERSON_KEYS.search(key), f"{path}.{key} names a person-level entity"
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            if value is not replicate_list:
                assert len(value) <= bound, f"{path} has {len(value)} entries (bound {bound})"
                if rows > bound:
                    assert len(value) != rows, f"{path} is as long as the index events"
                if persons > bound:
                    assert len(value) != persons, f"{path} is as long as the persons"
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str):
            assert not UUID.search(value), f"{path} carries a UUID-shaped string"
            for found in HEX64.findall(value):
                assert found == snapshot, f"{path} carries a 64-hex string other than the snapshot"

    walk(payload, "")
    assert payload["snapshot"] == snapshot


def _reduced(spec: OutcomeModelSpec, replicates: int, minimum: int) -> OutcomeModelSpec:
    return replace(
        spec,
        bootstrap=replace(spec.bootstrap, replicates=replicates),
        thresholds=replace(spec.thresholds, minimum_events_per_column=minimum),
    )


def _fitted(scale: ScaleSpec, seed: int, spec: OutcomeModelSpec) -> list[FittedModel]:
    frame = frame_from_world(build_world(seed, scale), scale)
    return fit_frame(frame, spec, seed=spec.seed, source="synthetic")


def test_canonical_serialization_sorts_rounds_and_is_stable() -> None:
    payload = {
        "b": 1.0 / 3.0,
        "a": [np.float64(2.0), -0.0, np.int64(7), True, None],
        "t": datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC),
        "nested": {"z": 123456789.123456789, "y": 1e-17},
    }
    data = render(payload)
    assert data == (
        b'{"a":[2.0,0.0,7,true,null],"b":0.333333333333,'
        b'"nested":{"y":1e-17,"z":123456789.123},"t":"2020-01-02T03:04:05+00:00"}\n'
    )
    assert render(payload) == data
    assert json.loads(data)["b"] == round_significant(1.0 / 3.0)
    with pytest.raises(ArtifactError, match="NaN"):
        render({"x": float("nan")})
    with pytest.raises(ArtifactError, match="timezone-aware"):
        render({"t": datetime(2020, 1, 1)})  # noqa: DTZ001 - the refusal under test


def test_the_content_hash_and_the_path() -> None:
    data = render({"a": 1})
    digest = content_hash(data)
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    root = Path("snapshots-root")
    path = artifact_path(root, SNAPSHOT, digest)
    assert path == (root.resolve() / SNAPSHOT / "models" / f"{digest}.json")
    for bad in ("../" + "a" * 61, "A" * 64, "a" * 63, ""):
        with pytest.raises(ArtifactError, match="64-character"):
            artifact_path(root, bad, digest)
        with pytest.raises(ArtifactError, match="64-character"):
            artifact_path(root, SNAPSHOT, bad)


def test_an_artifact_is_written_once(tmp_path: Path) -> None:
    data = render({"model": 1})
    path, digest, written = write_artifact(tmp_path, SNAPSHOT, data)
    assert written and path.read_bytes() == data and digest == content_hash(data)
    assert path.parent == tmp_path.resolve() / SNAPSHOT / "models"
    again = write_artifact(tmp_path, SNAPSHOT, data)
    assert again == (path, digest, False)
    # Different bytes at an existing artifact's path (a corrupted file) raise, never overwrite.
    path.write_bytes(b"tampered\n")
    with pytest.raises(ArtifactError, match="different bytes"):
        write_artifact(tmp_path, SNAPSHOT, data)
    assert path.read_bytes() == b"tampered\n"


def test_a_model_renders_the_same_bytes_twice() -> None:
    spec = _reduced(SPEC, replicates=5, minimum=1)
    first = _fitted(GOLDEN, 7, spec)
    second = _fitted(GOLDEN, 7, spec)
    assert [m.key for m in first] == [m.key for m in second]
    for left, right in zip(first, second, strict=True):
        assert left.render(snapshot=SNAPSHOT, code_version="v") == right.render(
            snapshot=SNAPSHOT, code_version="v"
        )


def test_every_artifact_a_fit_writes_passes_the_inspection(tmp_path: Path) -> None:
    golden = _fitted(GOLDEN, 7, _reduced(SPEC, replicates=12, minimum=1))
    demo = _fitted(
        DEMO,
        20260916,
        _reduced(SPEC, replicates=8, minimum=SPEC.thresholds.minimum_events_per_column),
    )
    insufficient = _fitted(GOLDEN, 7, SPEC)
    statuses = {model.status for model in [*golden, *demo, *insufficient]}
    assert {FITTED, INSUFFICIENT_EVENTS} <= statuses
    assert len(demo) == 13 and all(model.status == FITTED for model in demo)
    for model in [*golden, *demo, *insufficient]:
        data = model.render(snapshot=SNAPSHOT, code_version="0.1.0+abc1234")
        path, _, _ = write_artifact(tmp_path, SNAPSHOT, data)
        payload = json.loads(path.read_bytes())
        inspect_artifact(
            payload,
            snapshot=SNAPSHOT,
            rows=model.design.rows,
            persons=model.design.persons,
            spec=SPEC,
        )
        assert payload["training"]["rows"] == model.design.rows
        assert payload["source"] == "synthetic"
        if model.status == FITTED:
            assert len(payload["coefficients"]) == len(payload["design"]["columns"])
            assert len(payload["stability"]) == len(payload["design"]["columns"])
        else:
            assert payload["coefficients"] is None and payload["replicates"] is None
    # The demo world's index events far outnumber any structural array.
    assert min(model.design.rows for model in demo) > 1000
