"""Encryption layer (AES-256-GCM) for patient data at rest.

This module provides two cooperating pieces:

- :class:`EncryptionService` — authenticated encryption/decryption using
  AES-256-GCM (Requirement 13.1, 13.2). Every write uses a fresh random 12-byte
  nonce. The stored blob is laid out as::

      version (1 byte) || nonce (12 bytes) || ciphertext || tag (16 bytes)

  AES-256-GCM (via :class:`cryptography.hazmat.primitives.ciphers.aead.AESGCM`)
  appends the 16-byte authentication tag to the ciphertext, so the trailing
  ``ciphertext || tag`` is produced and consumed as a single unit. Decryption
  fails loudly (raises :class:`DecryptionError`) when the authentication tag
  does not verify, i.e. on tampering or a wrong key (Requirement 13.2 / design
  "fail loudly on auth-tag mismatch").

- :class:`EncryptedType` — a SQLAlchemy ``TypeDecorator`` that transparently
  encrypts Python ``str`` values on write and decrypts them on read, so service
  code works with plaintext while storage holds only ciphertext
  (Requirements 13.1-13.3).

The AES key is sourced *only* from the ``EMR_ENCRYPTION_KEY`` environment
variable (via :func:`app.core.config.get_settings`) and is never read from the
database or hard-coded in source (Requirements 13.6, 21.3). The leading
version byte allows future key rotation without changing the storage format
(design "Encryption Design Detail").
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from functools import lru_cache
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import LargeBinary, TypeDecorator

KEY_SIZE = 32
NONCE_SIZE = 12

CURRENT_KEY_VERSION = 1

class EncryptionError(Exception):
    """Base class for encryption-layer failures."""

class DecryptionError(EncryptionError):
    """Raised when ciphertext cannot be authenticated/decrypted.

    This surfaces an AES-GCM authentication-tag mismatch (tampering or wrong
    key), an unknown key version, or a malformed blob. It deliberately fails
    loudly rather than returning corrupt or partial plaintext.
    """

def _derive_key(key_material: str) -> bytes:
    """Derive a 32-byte AES-256 key from the configured key material.

    The ``EMR_ENCRYPTION_KEY`` value may be supplied as base64- or hex-encoded
    32-byte key material (the production convention). To remain robust across
    environments, any value that does not decode cleanly to exactly 32 bytes is
    reduced to a stable 32-byte key via SHA-256. The mapping is deterministic,
    so the same env value always yields the same key.
    """
    raw = key_material.encode("utf-8")

    try:
        decoded = base64.b64decode(key_material, validate=True)
        if len(decoded) == KEY_SIZE:
            return decoded
    except (binascii.Error, ValueError):
        pass

    try:
        decoded = bytes.fromhex(key_material.strip())
        if len(decoded) == KEY_SIZE:
            return decoded
    except ValueError:
        pass

    if len(raw) == KEY_SIZE:
        return raw

    return hashlib.sha256(raw).digest()

class EncryptionService:
    """AES-256-GCM authenticated encryption for patient data.

    Holds one or more version-tagged keys. Writes always use the current key
    version; reads select the key by the blob's leading version byte, enabling
    transparent key rotation in the future.
    """

    def __init__(
        self,
        keys: dict[int, bytes],
        *,
        current_version: int = CURRENT_KEY_VERSION,
    ) -> None:
        if current_version not in keys:
            raise EncryptionError(
                f"No key configured for current version {current_version}"
            )
        for version, key in keys.items():
            if not 0 <= version <= 255:
                raise EncryptionError(f"Key version {version} out of byte range")
            if len(key) != KEY_SIZE:
                raise EncryptionError(
                    f"Key for version {version} must be {KEY_SIZE} bytes, "
                    f"got {len(key)}"
                )
        self._keys = dict(keys)
        self._current_version = current_version

    @classmethod
    def from_key_material(
        cls, key_material: str, *, version: int = CURRENT_KEY_VERSION
    ) -> "EncryptionService":
        """Build a service from a single env-supplied key string."""
        if not key_material:
            raise EncryptionError(
                "EMR_ENCRYPTION_KEY is not set; refusing to operate without a key"
            )
        return cls({version: _derive_key(key_material)}, current_version=version)

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt a plaintext string into a versioned, nonce-prefixed blob.

        Layout: ``version || nonce(12) || ciphertext || tag(16)``. A fresh
        random nonce is generated for every call (Requirement 13.1).
        """
        if plaintext is None:
            raise EncryptionError("Cannot encrypt None")
        key = self._keys[self._current_version]
        nonce = os.urandom(NONCE_SIZE)
        ct_and_tag = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
        return bytes([self._current_version]) + nonce + ct_and_tag

    def decrypt(self, blob: bytes) -> str:
        """Decrypt a versioned blob back to its plaintext string.

        Raises :class:`DecryptionError` on a malformed blob, unknown key
        version, or authentication-tag mismatch (fail loudly).
        """
        if blob is None:
            raise DecryptionError("Cannot decrypt None")
        if len(blob) < 1 + NONCE_SIZE + 16:
            raise DecryptionError("Ciphertext blob is too short to be valid")

        version = blob[0]
        nonce = blob[1 : 1 + NONCE_SIZE]
        ct_and_tag = blob[1 + NONCE_SIZE :]

        key = self._keys.get(version)
        if key is None:
            raise DecryptionError(f"No key available for key version {version}")

        try:
            plaintext = AESGCM(key).decrypt(nonce, ct_and_tag, None)
        except InvalidTag as exc:
            raise DecryptionError(
                "Authentication tag mismatch: ciphertext is corrupt, tampered "
                "with, or encrypted under a different key"
            ) from exc
        return plaintext.decode("utf-8")

@lru_cache
def get_encryption_service() -> EncryptionService:
    """Return a process-wide cached :class:`EncryptionService`.

    The key is read exclusively from the ``EMR_ENCRYPTION_KEY`` environment
    variable via the application settings (Requirements 13.6, 21.3).
    """
    from app.core.config import get_settings

    settings = get_settings()
    key_material = settings.emr_encryption_key
    if not key_material:
        raise EncryptionError(
            "EMR_ENCRYPTION_KEY environment variable is not configured"
        )
    return EncryptionService.from_key_material(key_material)

class EncryptedType(TypeDecorator):
    """SQLAlchemy column type that encrypts on write and decrypts on read.

    Stores AES-256-GCM ciphertext as a binary blob (``LargeBinary``). Service
    and ORM code assign/read plain Python ``str`` values; the database only ever
    holds ciphertext (Requirements 13.1-13.3). ``None`` passes through unchanged
    so nullable columns behave normally.

    The encryption service is resolved lazily (per operation) so the column type
    can be defined at import time before the environment/key is loaded, and so
    tests can configure the key via the environment.
    """

    impl = LargeBinary
    cache_ok = True

    def __init__(self, *args, service: Optional[EncryptionService] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._service = service

    def _resolve_service(self) -> EncryptionService:
        return self._service if self._service is not None else get_encryption_service()

    def process_bind_param(self, value, dialect):
        """Encrypt the plaintext value before it is written to the database."""
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        return self._resolve_service().encrypt(value)

    def process_result_value(self, value, dialect):
        """Decrypt the stored blob back to plaintext when reading from the DB."""
        if value is None:
            return None

        if isinstance(value, (memoryview, bytearray)):
            value = bytes(value)
        return self._resolve_service().decrypt(value)
