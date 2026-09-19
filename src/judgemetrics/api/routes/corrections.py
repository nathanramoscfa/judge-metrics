# src/judgemetrics/api/routes/corrections.py
"""``POST /api/v1/corrections``: the public data-correction intake, the API's one write path.

Order of checks: the corrections rate limiter (before the body is parsed,
so an over-limit client never reaches validation or the database), the
strict query allow-list (a POST takes no query parameter), body
validation (``CorrectionIn``), the target lookup, encryption, the insert.
A missing or unusable contact key is a 503 with a fixed message; the 202
acknowledgement carries the id, the status, and the time received. The
response is never cached.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from judgemetrics.api.deps import SessionDep, SettingsDep, StrictQuery
from judgemetrics.api.errors import ApiError, error_responses
from judgemetrics.api.ratelimit import corrections_rate_limit
from judgemetrics.schemas.metrics import CorrectionAccepted, CorrectionIn
from judgemetrics.security.crypto import ContactKeyMissingError
from judgemetrics.services.corrections import submit_correction

router = APIRouter(prefix="/corrections", tags=["corrections"])

UNAVAILABLE_MESSAGE = (
    "corrections are not being accepted: the contact encryption key is not configured"
)


@router.post(
    "",
    response_model=CorrectionAccepted,
    status_code=202,
    responses=error_responses(422, 429, 503),
    summary="Submit a data-correction request (the contact is encrypted at rest)",
    dependencies=[Depends(corrections_rate_limit), Depends(StrictQuery())],
)
def post_correction(
    body: CorrectionIn, session: SessionDep, settings: SettingsDep, response: Response
) -> CorrectionAccepted:
    response.headers["Cache-Control"] = "no-store"
    try:
        return submit_correction(session, settings, body)
    except ContactKeyMissingError as exc:
        raise ApiError(
            status_code=503, code="corrections_unavailable", message=UNAVAILABLE_MESSAGE
        ) from exc
