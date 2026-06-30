"""Unit + property tests for the error-envelope helpers.

These exercise the harness itself (Hypothesis profile, shared strategies) so
the scaffolding is verified end-to-end. They are not one of the 53 numbered
correctness properties — those are added alongside their features in later
tasks.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from app.core.errors import AppError, error_payload

def test_error_payload_without_field() -> None:
    payload = error_payload("not-found", "Missing")
    assert payload == {"error": {"code": "not-found", "message": "Missing"}}
    assert "field" not in payload["error"]

def test_error_payload_with_field() -> None:
    payload = error_payload("validation-error", "Too short", field="password")
    assert payload["error"]["field"] == "password"

@given(
    code=st.text(min_size=1, max_size=40),
    message=st.text(min_size=0, max_size=200),
    field=st.one_of(st.none(), st.text(min_size=1, max_size=40)),
)
def test_error_payload_envelope_shape_is_consistent(code, message, field) -> None:
    """The envelope always nests under 'error' with code+message, field optional."""
    payload = error_payload(code, message, field)
    assert set(payload.keys()) == {"error"}
    err = payload["error"]
    assert err["code"] == code
    assert err["message"] == message
    if field is None:
        assert "field" not in err
    else:
        assert err["field"] == field

def test_app_error_carries_envelope_attributes() -> None:
    exc = AppError("conflict", "Email exists", status_code=409, field="email")
    assert exc.code == "conflict"
    assert exc.status_code == 409
    assert exc.field == "email"
    assert str(exc) == "Email exists"
