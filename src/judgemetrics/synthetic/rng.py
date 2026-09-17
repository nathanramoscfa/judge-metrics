# src/judgemetrics/synthetic/rng.py
"""Named seeded random streams and the only random primitives the package uses.

``Streams(seed)`` derives one ``random.Random`` per named stream from
``sha256(f"{seed}:{name}")``, so a new draw added to one stream cannot
change what another stream produces. The helpers below use only
``Random.random()`` — the one method whose sequence Python guarantees
stable across versions for a given seed — so the same seed yields the
same dataset on every supported interpreter. Nothing in this package calls
module-level ``random`` functions, ``datetime.now``, ``uuid.uuid4``, or
``os.urandom``, and every iteration over a mapping or set is sorted.

The generator simulates a justice system; none of this randomness protects
anything, which is why the constructor is exempted from the
cryptographic-randomness lint rules.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence

STREAM_NAMES: tuple[str, ...] = ("world", "persons", "cases", "events", "edge_cases")


def derive_stream(seed: int, name: str) -> random.Random:
    """A ``random.Random`` seeded from ``sha256(f"{seed}:{name}")``."""
    digest = hashlib.sha256(f"{seed}:{name}".encode("ascii")).digest()
    # Simulation only: the streams reproduce a synthetic dataset from a seed;
    # they never generate keys, tokens, or anything security-sensitive.
    return random.Random(int.from_bytes(digest, "big"))  # noqa: S311 # nosec B311


class Streams:
    """One independent stream per stage of the simulation."""

    __slots__ = ("cases", "edge_cases", "events", "persons", "seed", "world")

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.world = derive_stream(seed, "world")
        self.persons = derive_stream(seed, "persons")
        self.cases = derive_stream(seed, "cases")
        self.events = derive_stream(seed, "events")
        self.edge_cases = derive_stream(seed, "edge_cases")


def uniform(rng: random.Random, low: float, high: float) -> float:
    """A float in ``[low, high)``."""
    return low + (high - low) * rng.random()


def randint(rng: random.Random, low: int, high: int) -> int:
    """An integer in ``[low, high]`` (both inclusive)."""
    if high < low:
        msg = f"randint: high {high} < low {low}"
        raise ValueError(msg)
    return low + int(rng.random() * (high - low + 1))


def chance(rng: random.Random, probability: float) -> bool:
    """True with the given probability."""
    return rng.random() < probability


def choice[T](rng: random.Random, items: Sequence[T]) -> T:
    """One element of a non-empty sequence."""
    if not items:
        msg = "choice: empty sequence"
        raise ValueError(msg)
    return items[int(rng.random() * len(items))]


def weighted_choice[T](rng: random.Random, options: Sequence[tuple[T, float]]) -> T:
    """One element, with probability proportional to its weight (weights >= 0)."""
    total = sum(weight for _, weight in options)
    if total <= 0:
        msg = "weighted_choice: weights sum to zero"
        raise ValueError(msg)
    target = rng.random() * total
    running = 0.0
    for item, weight in options:
        running += weight
        if target < running:
            return item
    return options[-1][0]


def shuffled[T](rng: random.Random, items: Sequence[T]) -> list[T]:
    """A Fisher-Yates shuffle of ``items`` as a new list."""
    result = list(items)
    for index in range(len(result) - 1, 0, -1):
        other = int(rng.random() * (index + 1))
        result[index], result[other] = result[other], result[index]
    return result


def sample[T](rng: random.Random, items: Sequence[T], count: int) -> list[T]:
    """``count`` distinct elements in random order."""
    if count > len(items):
        msg = f"sample: {count} requested from {len(items)} items"
        raise ValueError(msg)
    return shuffled(rng, items)[:count]


def skewed_fraction(rng: random.Random, exponent: float) -> float:
    """A fraction in ``[0, 1)`` biased toward zero as ``exponent`` grows."""
    return float(rng.random() ** exponent)
