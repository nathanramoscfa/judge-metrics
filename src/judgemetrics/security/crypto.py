# src/judgemetrics/security/crypto.py
"""Application-level encryption for restricted columns.

``correction_request.requester_contact`` is stored as Fernet ciphertext
(AES-128-CBC with an HMAC-SHA256 tag and a timestamp) under
``Settings.correction_contact_key``. The key never reaches the database or
the logs: the API role cannot read the table, and only the admin tooling
that answers corrections is configured with the key. Generate one with
``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from judgemetrics.config import Settings


class ContactKeyMissingError(RuntimeError):
    """Raised when a contact must be encrypted or decrypted without a key configured."""


def _fernet(settings: Settings) -> Fernet:
    key = settings.correction_contact_key
    if key is None or not key.get_secret_value():
        msg = "JUDGEMETRICS_CORRECTION_CONTACT_KEY is not configured"
        raise ContactKeyMissingError(msg)
    return Fernet(key.get_secret_value().encode("ascii"))


def encrypt_contact(settings: Settings, contact: str) -> bytes:
    """Encrypt a requester contact string for storage."""
    return _fernet(settings).encrypt(contact.encode("utf-8"))


def decrypt_contact(settings: Settings, ciphertext: bytes) -> str:
    """Decrypt a stored requester contact; raises ``InvalidToken`` on tampering."""
    return _fernet(settings).decrypt(ciphertext).decode("utf-8")


__all__ = ["ContactKeyMissingError", "InvalidToken", "decrypt_contact", "encrypt_contact"]
