# src/judgemetrics/security/crypto.py
"""Application-level encryption for restricted columns.

``correction_request.requester_contact`` is stored as Fernet ciphertext
(AES-128-CBC with an HMAC-SHA256 tag and a timestamp) under
``Settings.correction_contact_key``. The key never reaches the database or
the logs (the logging scrubber redacts ``correction_contact_key``): the
API encrypts every accepted correction with it and cannot read the table
back, and only the admin tooling that answers corrections decrypts.
Generate one with
``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``.
``require_contact_key`` is the startup check ``create_app`` runs outside
the test environment, so an API without a usable key fails fast with a
message naming the variable rather than answering 503 to every request.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from judgemetrics.config import Settings

CONTACT_KEY_VARIABLE = "JUDGEMETRICS_CORRECTION_CONTACT_KEY"


class ContactKeyMissingError(RuntimeError):
    """Raised when a contact must be encrypted or decrypted without a usable key configured."""


def _fernet(settings: Settings) -> Fernet:
    key = settings.correction_contact_key
    if key is None or not key.get_secret_value():
        msg = f"{CONTACT_KEY_VARIABLE} is not configured"
        raise ContactKeyMissingError(msg)
    try:
        return Fernet(key.get_secret_value().encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        # The message names the variable and never the value.
        msg = f"{CONTACT_KEY_VARIABLE} is not a valid Fernet key (see .env.example)"
        raise ContactKeyMissingError(msg) from exc


def require_contact_key(settings: Settings) -> None:
    """``ContactKeyMissingError`` unless a usable Fernet key is configured."""
    _fernet(settings)


def encrypt_contact(settings: Settings, contact: str) -> bytes:
    """Encrypt a requester contact string for storage."""
    return _fernet(settings).encrypt(contact.encode("utf-8"))


def decrypt_contact(settings: Settings, ciphertext: bytes) -> str:
    """Decrypt a stored requester contact; raises ``InvalidToken`` on tampering."""
    return _fernet(settings).decrypt(ciphertext).decode("utf-8")


__all__ = [
    "CONTACT_KEY_VARIABLE",
    "ContactKeyMissingError",
    "InvalidToken",
    "decrypt_contact",
    "encrypt_contact",
    "require_contact_key",
]
