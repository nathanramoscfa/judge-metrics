# tests/unit/test_ratelimit.py
"""The token bucket: burst, refill, `Retry-After`, per-key isolation, pruning."""

from __future__ import annotations

import pytest

from judgemetrics.api import ratelimit
from judgemetrics.api.ratelimit import TokenBucketLimiter

pytestmark = pytest.mark.unit


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_burst_then_429_with_retry_after() -> None:
    clock = Clock()
    limiter = TokenBucketLimiter(per_minute=60, burst=3, clock=clock)
    assert [limiter.acquire("a").allowed for _ in range(3)] == [True, True, True]
    refused = limiter.acquire("a")
    assert not refused.allowed
    assert refused.retry_after_seconds == 1  # one token a second at 60/minute


def test_refill_is_proportional_to_elapsed_time() -> None:
    clock = Clock()
    limiter = TokenBucketLimiter(per_minute=30, burst=2, clock=clock)  # a token every 2 s
    assert limiter.acquire("a").allowed and limiter.acquire("a").allowed
    refused = limiter.acquire("a")
    assert not refused.allowed and refused.retry_after_seconds == 2
    clock.now = 1.0
    assert not limiter.acquire("a").allowed
    clock.now = 2.0
    assert limiter.acquire("a").allowed
    assert not limiter.acquire("a").allowed
    # A long idle period refills to the burst, never beyond it.
    clock.now = 1_000.0
    assert [limiter.acquire("a").allowed for _ in range(3)] == [True, True, False]


def test_keys_are_independent() -> None:
    limiter = TokenBucketLimiter(per_minute=60, burst=1, clock=Clock())
    assert limiter.acquire("a").allowed
    assert not limiter.acquire("a").allowed
    assert limiter.acquire("b").allowed


def test_full_buckets_are_pruned_past_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ratelimit, "MAX_TRACKED_KEYS", 4)
    clock = Clock()
    limiter = TokenBucketLimiter(per_minute=60, burst=2, clock=clock)
    for key in "abcd":
        limiter.acquire(key)  # each holds 1 of 2 tokens
    clock.now = 60.0  # every bucket has refilled
    limiter.acquire("e")  # the fifth key crosses the cap and triggers pruning
    assert set(limiter._buckets) == {"e"}  # noqa: SLF001
    # A bucket that is still draining survives the prune.
    limiter.acquire("f")
    limiter.acquire("f")
    for key in "ghij":
        limiter.acquire(key)
    clock.now = 60.5
    limiter.acquire("k")
    assert "f" in limiter._buckets  # noqa: SLF001


def test_configuration_is_validated() -> None:
    with pytest.raises(ValueError, match="positive"):
        TokenBucketLimiter(per_minute=0, burst=1)
    with pytest.raises(ValueError, match="positive"):
        TokenBucketLimiter(per_minute=60, burst=0)
