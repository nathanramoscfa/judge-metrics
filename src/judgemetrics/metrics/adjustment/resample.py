# src/judgemetrics/metrics/adjustment/resample.py
"""Person-cluster bootstrap weights from seeded streams.

``replicates(clusters, *, seed, stream, count)`` yields ``count`` weight
vectors, one value per design row: the number of times the row's person
cluster was drawn when ``K`` clusters are drawn uniformly with replacement
from the ``K`` distinct cluster keys. The keys are sorted first and every
draw comes from one ``random.Random`` per stream, derived exactly as
``synthetic/rng.py`` derives its streams — from ``sha256(f"{seed}:{stream}")``
— and drawn only through ``Random.random()``, the one method whose sequence
Python guarantees across versions. The replicates therefore depend on the
seed, the stream name, and the source-assigned cluster keys alone: never on
a canonical id or on the order of the rows. Step 3's interval recomputes
the same weights from the same streams (``replicate_stream``).
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterator, Sequence

import numpy as np
import numpy.typing as npt

STREAM_PREFIX = "bootstrap"


def derive_stream(seed: int, name: str) -> random.Random:
    """A ``random.Random`` seeded from ``sha256(f"{seed}:{name}")`` (as ``synthetic/rng.py``)."""
    digest = hashlib.sha256(f"{seed}:{name}".encode("ascii")).digest()
    # Statistical resampling only: the stream reproduces bootstrap replicates from
    # a published seed; it never generates keys, tokens, or anything secret.
    return random.Random(int.from_bytes(digest, "big"))  # noqa: S311 # nosec B311


def replicate_stream(target: str, window_days: int | None) -> str:
    """The stream name of one model's replicates (``bootstrap:<target>:<window or none>``)."""
    window = "none" if window_days is None else str(window_days)
    return f"{STREAM_PREFIX}:{target}:{window}"


def cluster_index(clusters: Sequence[str]) -> tuple[tuple[str, ...], npt.NDArray[np.int64]]:
    """The sorted distinct keys and, per row, the position of its key among them."""
    keys = tuple(sorted(set(clusters)))
    position = {key: index for index, key in enumerate(keys)}
    return keys, np.fromiter(
        (position[key] for key in clusters), dtype=np.int64, count=len(clusters)
    )


def replicates(
    clusters: Sequence[str], *, seed: int, stream: str, count: int
) -> Iterator[npt.NDArray[np.float64]]:
    """``count`` person-cluster bootstrap weight vectors over the rows of ``clusters``."""
    keys, rows = cluster_index(clusters)
    size = len(keys)
    rng = derive_stream(seed, stream)
    for _ in range(count):
        picks = np.fromiter((int(rng.random() * size) for _ in range(size)), np.int64, size)
        draws = np.bincount(picks, minlength=size).astype(np.float64)
        yield draws[rows]
