# tests/golden/test_golden_fixture.py
"""The committed golden fixture is exactly what the generator produces for seed 7.

Regenerating seed 7 at the ``golden`` scale into a temporary directory
yields every file byte for byte, ``verify_dataset`` finds no drift, and
the manifest records the current ``GENERATOR_VERSION`` and
``TRUTH_VERSION``. A generator change without a version bump fails the
byte comparison; a version bump without regenerating the fixture fails
the manifest check and the byte comparison — the guard
``tests/fixtures/golden/README.md`` describes. No database is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from judgemetrics.synthetic.config import GENERATOR_VERSION, scale_spec
from judgemetrics.synthetic.generate import Manifest, generate_dataset, verify_dataset
from judgemetrics.synthetic.truth import TRUTH_FILES, TRUTH_VERSION
from judgemetrics.synthetic.writer import SOURCE_FILES
from tests.golden.conftest import GOLDEN

pytestmark = pytest.mark.golden

GOLDEN_SEED = 7
GOLDEN_SCALE = scale_spec("golden")
EVERY_FILE = (
    "manifest.json",
    *(f"source/{name}" for name in SOURCE_FILES),
    *(f"truth/{name}" for name in TRUTH_FILES),
)


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("golden-regenerated")
    manifest = generate_dataset(GOLDEN_SEED, GOLDEN_SCALE.name, out)
    assert manifest.seed == GOLDEN_SEED and manifest.scale == GOLDEN_SCALE.name
    return out


@pytest.mark.parametrize("relative", EVERY_FILE)
def test_regeneration_is_byte_identical(regenerated: Path, relative: str) -> None:
    expected = (GOLDEN / Path(*relative.split("/"))).read_bytes()
    actual = (regenerated / Path(*relative.split("/"))).read_bytes()
    assert actual == expected, f"{relative} differs from the committed golden fixture"


def test_the_committed_fixture_verifies_clean() -> None:
    assert verify_dataset(GOLDEN) == []


def test_the_manifest_lists_every_file_and_nothing_else() -> None:
    manifest = Manifest.load(GOLDEN / "manifest.json")
    assert set(manifest.files) == set(EVERY_FILE) - {"manifest.json"}


def test_the_manifest_carries_the_current_generator_and_truth_versions() -> None:
    manifest = Manifest.load(GOLDEN / "manifest.json")
    assert manifest.generator_version == GENERATOR_VERSION, (
        "GENERATOR_VERSION was bumped without regenerating tests/fixtures/golden "
        "(see tests/fixtures/golden/README.md)"
    )
    assert manifest.truth_version == TRUTH_VERSION, (
        "TRUTH_VERSION was bumped without regenerating tests/fixtures/golden "
        "(see tests/fixtures/golden/README.md)"
    )
