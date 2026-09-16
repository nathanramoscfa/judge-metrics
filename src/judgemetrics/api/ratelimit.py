# src/judgemetrics/api/ratelimit.py
"""In-process token-bucket rate limiter for ``/api/v1/search``.

This is the local layer beneath the Phase 8 edge limits (the reverse proxy
or CDN in front of the API): it protects one process from one client, it
is not shared across workers, and it forgets everything on restart. Each
bucket (``RequestIdentity.rate_limit_key``: anonymous + client address)
holds ``burst`` tokens and refills at ``per_minute`` tokens a minute; a
request takes one token or is answered 429 with ``Retry-After`` and an
``ErrorBody``. ``create_app`` builds the limiter from
``settings.search_rate_limit_*`` and leaves it off under the test
environment unless ``search_rate_limit_enabled`` says otherwise.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

from judgemetrics.api.deps import get_settings
from judgemetrics.api.errors import ApiError
from judgemetrics.api.identity import resolve_identity

RETRY_AFTER_HEADER = "Retry-After"
# Buckets are pruned once the table grows past this many keys; a full
# bucket carries no state worth keeping, so dropping it is exact.
MAX_TRACKED_KEYS = 10_000


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    retry_after_seconds: int


class TokenBucketLimiter:
    """``burst`` tokens per key, refilled at ``per_minute`` / 60 tokens a second.

    ``clock`` is injectable so tests can hold time still.
    """

    def __init__(
        self, *, per_minute: int, burst: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if per_minute < 1 or burst < 1:
            msg = "per_minute and burst must be positive"
            raise ValueError(msg)
        self.per_minute = per_minute
        self.burst = burst
        self._refill_per_second = per_minute / 60.0
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str) -> Decision:
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(self.burst), updated_at=now)
                self._buckets[key] = bucket
            else:
                elapsed = max(0.0, now - bucket.updated_at)
                bucket.tokens = min(
                    float(self.burst), bucket.tokens + elapsed * self._refill_per_second
                )
                bucket.updated_at = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                decision = Decision(allowed=True, retry_after_seconds=0)
            else:
                wait = (1.0 - bucket.tokens) / self._refill_per_second
                decision = Decision(allowed=False, retry_after_seconds=max(1, math.ceil(wait)))
            if len(self._buckets) > MAX_TRACKED_KEYS:
                self._prune(now)
        return decision

    def _prune(self, now: float) -> None:
        """Drop buckets that have refilled completely (the lock is held)."""
        for key, bucket in list(self._buckets.items()):
            refilled = bucket.tokens + (now - bucket.updated_at) * self._refill_per_second
            if refilled >= self.burst:
                del self._buckets[key]


def search_rate_limit(request: Request) -> None:
    """Route dependency: take a token for this request's identity or answer 429."""
    limiter: TokenBucketLimiter | None = request.app.state.search_limiter
    if limiter is None:
        return
    identity = resolve_identity(request, get_settings(request))
    decision = limiter.acquire(identity.rate_limit_key)
    if not decision.allowed:
        raise ApiError(
            status_code=429,
            code="rate_limited",
            message="search rate limit exceeded; retry after the indicated seconds",
            headers={RETRY_AFTER_HEADER: str(decision.retry_after_seconds)},
        )
