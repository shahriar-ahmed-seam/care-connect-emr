"""Property test for password hashing (task 4.2).

Verifies the salted one-way hashing guarantee behind Requirement 1.6.
"""

from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.core.security import hash_password, verify_password

_passwords = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=0x9FF),
    min_size=8,
    max_size=64,
)

@given(password=_passwords)
def test_passwords_stored_as_salted_one_way_hashes(password: str) -> None:
    stored = hash_password(password)

    assert stored != password

    assert verify_password(password, stored) is True

    stored_again = hash_password(password)
    assert stored_again != stored
    assert verify_password(password, stored_again) is True

@settings(max_examples=25)
@given(
    password=st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=8, max_size=64),
    other=st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=8, max_size=64),
)
def test_wrong_password_does_not_verify(password: str, other: str) -> None:
    """A different password must not verify against the stored hash.

    Uses single-byte ASCII passwords so the comparison stays within bcrypt's
    72-byte input window, and skips the degenerate equal-password case.
    """
    assume(password != other)
    stored = hash_password(password)
    assert verify_password(other, stored) is False
