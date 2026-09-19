# src/judgemetrics/services/corrections.py
"""The corrections intake: validate the target, encrypt the contact, store, acknowledge.

The one write path of the public API. The body is a validated
``CorrectionIn``; the target must exist in the table its type names (a
422 naming ``target_id`` otherwise); the contact is encrypted with
``security.crypto.encrypt_contact`` (Fernet under
``JUDGEMETRICS_CORRECTION_CONTACT_KEY``) and nothing else — a missing or
unusable key is ``ContactKeyMissingError``, which the route answers 503
with a fixed message; the row is inserted with a client-generated id and
no ``RETURNING`` and committed; the acknowledgement carries the id, the
status, and the time received — never a submitted field. The log line
carries the id and the target type only (the scrubber redacts ``reason``,
``contact``, and ``supporting_material`` anyway).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from judgemetrics.api.errors import ApiError
from judgemetrics.config import Settings
from judgemetrics.logging import get_logger
from judgemetrics.repositories.corrections import insert_correction, target_exists
from judgemetrics.schemas.metrics import CorrectionAccepted, CorrectionIn
from judgemetrics.security.crypto import encrypt_contact

log = get_logger(__name__)


def submit_correction(
    session: Session, settings: Settings, body: CorrectionIn
) -> CorrectionAccepted:
    """Store the request (two statements: the target lookup, the insert) and acknowledge it."""
    if not target_exists(session, body.target_type, body.target_id):
        raise ApiError(
            status_code=422,
            code="validation_error",
            message=f"target_id: no {body.target_type} with id {body.target_id}",
        )
    # Encrypt before touching the table: a contact is never stored in clear.
    ciphertext = encrypt_contact(settings, body.contact)
    correction_id = uuid.uuid4()
    received_at = datetime.now(UTC)
    insert_correction(
        session,
        correction_id=correction_id,
        target_type=body.target_type,
        target_id=body.target_id,
        requester_contact=ciphertext,
        reason=body.reason,
        supporting_material_path=(
            None if body.supporting_material is None else str(body.supporting_material)
        ),
    )
    session.commit()
    log.info(
        "corrections.received",
        correction_id=str(correction_id),
        target_type=body.target_type,
        target_id=str(body.target_id),
    )
    return CorrectionAccepted(id=correction_id, status="received", received_at=received_at)
