# src/judgemetrics/synthetic/__init__.py
"""The deterministic synthetic justice dataset generator (Phase 2 Step 1).

``generate_dataset(seed, scale, out)`` writes source-format CSV files a
connector can ingest, a ``truth/`` directory the database never sees, and a
manifest with the sha256 of every file; two runs from one seed are
byte-identical. See docs/SYNTHETIC_DATA.md.
"""

from judgemetrics.synthetic.config import DEMO, GENERATOR_VERSION, GOLDEN, TINY, ScaleSpec
from judgemetrics.synthetic.generate import (
    DatasetExistsError,
    Manifest,
    generate_dataset,
    verify_dataset,
)

__all__ = [
    "DEMO",
    "GENERATOR_VERSION",
    "GOLDEN",
    "TINY",
    "DatasetExistsError",
    "Manifest",
    "ScaleSpec",
    "generate_dataset",
    "verify_dataset",
]
