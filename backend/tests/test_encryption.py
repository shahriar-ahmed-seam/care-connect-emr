"""Tests for the AES-256-GCM encryption layer (Encryption_Service + EncryptedType).

Covers the two highest-value safety guarantees from the design:

- Property 42: Patient data is encrypted at rest (ciphertext != plaintext).
- Property 43: Encryption round-trip preserves data.

Both properties are exercised with Hypothesis at >= 100 generated cases (see the
``default`` profile in ``conftest.py``) and through *both* the raw
``EncryptionService`` and the SQLAlchemy ``EncryptedType`` bind/result path,
since the column type is the real persistence boundary.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.encryption import (
    CURRENT_KEY_VERSION,
    KEY_SIZE,
    NONCE_SIZE,
    DecryptionError,
    EncryptedType,
    EncryptionService,
    get_encryption_service,
)
from tests.strategies import patient_data_text

def _service() -> EncryptionService:
    """A deterministic, env-independent service for unit-level assertions."""
    return EncryptionService({CURRENT_KEY_VERSION: b"\x01" * KEY_SIZE})

@given(value=patient_data_text)
def test_property_43_encryption_round_trip_preserves_data(value: str) -> None:
    service = _service()
    restored = service.decrypt(service.encrypt(value))
    assert restored == value

@given(value=patient_data_text)
def test_property_43_encrypted_type_round_trip(value: str) -> None:
    col = EncryptedType(service=_service())
    stored = col.process_bind_param(value, dialect=None)
    restored = col.process_result_value(stored, dialect=None)
    assert restored == value

@given(value=patient_data_text)
def test_property_42_patient_data_is_encrypted_at_rest(value: str) -> None:
    service = _service()
    blob = service.encrypt(value)
    plaintext_bytes = value.encode("utf-8")

    assert blob != plaintext_bytes

    if len(plaintext_bytes) >= 16:
        assert plaintext_bytes not in blob

    assert blob[0] == CURRENT_KEY_VERSION
    assert len(blob) >= 1 + NONCE_SIZE + 16
    assert service.decrypt(blob) == value

@given(value=patient_data_text)
def test_property_42_encrypted_type_stores_ciphertext(value: str) -> None:
    col = EncryptedType(service=_service())
    stored = col.process_bind_param(value, dialect=None)
    plaintext_bytes = value.encode("utf-8")

    assert isinstance(stored, bytes)
    assert stored != plaintext_bytes
    if len(plaintext_bytes) >= 16:
        assert plaintext_bytes not in stored

def test_empty_string_round_trips() -> None:
    service = _service()
    assert service.decrypt(service.encrypt("")) == ""

def test_bangla_text_round_trips() -> None:
    service = _service()
    value = "রোগীর রক্তচাপ ১২০/৮০ — স্বাভাবিক"
    assert service.decrypt(service.encrypt(value)) == value

def test_large_value_round_trips() -> None:
    service = _service()
    value = "চিকিৎসা" * 5000
    assert service.decrypt(service.encrypt(value)) == value

def test_fresh_nonce_per_write_produces_distinct_blobs() -> None:
    service = _service()
    a = service.encrypt("same plaintext")
    b = service.encrypt("same plaintext")

    assert a != b
    assert a[1 : 1 + NONCE_SIZE] != b[1 : 1 + NONCE_SIZE]
    assert service.decrypt(a) == service.decrypt(b) == "same plaintext"

def test_tampered_ciphertext_fails_loudly() -> None:
    service = _service()
    blob = bytearray(service.encrypt("sensitive diagnosis"))
    blob[-1] ^= 0x01
    with pytest.raises(DecryptionError):
        service.decrypt(bytes(blob))

def test_wrong_key_fails_loudly() -> None:
    writer = EncryptionService({CURRENT_KEY_VERSION: b"\x01" * KEY_SIZE})
    reader = EncryptionService({CURRENT_KEY_VERSION: b"\x02" * KEY_SIZE})
    blob = writer.encrypt("sensitive diagnosis")
    with pytest.raises(DecryptionError):
        reader.decrypt(blob)

def test_unknown_key_version_fails_loudly() -> None:
    service = _service()
    blob = bytearray(service.encrypt("x"))
    blob[0] = 0xFE
    with pytest.raises(DecryptionError):
        service.decrypt(bytes(blob))

def test_truncated_blob_fails_loudly() -> None:
    service = _service()
    with pytest.raises(DecryptionError):
        service.decrypt(b"\x01short")

def test_none_passes_through_encrypted_type() -> None:
    col = EncryptedType(service=_service())
    assert col.process_bind_param(None, dialect=None) is None
    assert col.process_result_value(None, dialect=None) is None

def test_memoryview_result_is_decrypted() -> None:
    service = _service()
    col = EncryptedType(service=service)
    blob = col.process_bind_param("vitals: 98.6", dialect=None)
    assert col.process_result_value(memoryview(blob), dialect=None) == "vitals: 98.6"

def test_key_loaded_from_env_only() -> None:

    service = get_encryption_service()
    assert service.decrypt(service.encrypt("env-keyed")) == "env-keyed"
