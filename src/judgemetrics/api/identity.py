# src/judgemetrics/api/identity.py
"""Request identity: which rate-limit bucket a request belongs to.

ROADMAP.md §1.4: an optional ``X-API-Key`` header resolves to a bucket.
Anonymous is the only bucket until Phase 9 and no key is issued before
then, so a presented key changes nothing today — the hook exists so keyed
tiers add a lookup here, not a re-plumbing. The client key is the peer
address, or the address a trusted reverse proxy appended to
``X-Forwarded-For`` when ``settings.trust_proxy`` is on (never otherwise:
the header is client-controlled). Key values are never logged; the
logging scrubber redacts ``api_key`` anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from judgemetrics.config import Settings

API_KEY_HEADER = "X-API-Key"  # pragma: allowlist secret - a header name, not a key
FORWARDED_FOR_HEADER = "X-Forwarded-For"
ANONYMOUS = "anonymous"


@dataclass(frozen=True, slots=True)
class RequestIdentity:
    bucket: str
    client: str

    @property
    def rate_limit_key(self) -> str:
        return f"{self.bucket}:{self.client}"


def client_address(request: Request, settings: Settings) -> str:
    if settings.trust_proxy:
        forwarded = request.headers.get(FORWARDED_FOR_HEADER, "")
        if forwarded:
            # The rightmost entry is the one the trusted proxy appended; the
            # entries before it are whatever the client sent.
            return forwarded.rsplit(",", 1)[-1].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def resolve_identity(request: Request, settings: Settings) -> RequestIdentity:
    """The bucket for this request.

    Until keys are issued (Phase 9) the ``X-API-Key`` header is not even
    read: every request is anonymous and keyed by client address.
    """
    return RequestIdentity(bucket=ANONYMOUS, client=client_address(request, settings))
