"""Shared Hypothesis strategies for Care-Connect-EMR property-based tests.

This module is a central home for reusable generators so property tests across
the suite constrain inputs to valid (or deliberately invalid) domains in a
consistent way. It is intentionally a lightweight stub at scaffolding time;
later tasks extend it with entity-specific strategies (slots, appointments,
prescriptions, vitals, etc.).

Do NOT reimplement Hypothesis here — only compose ``hypothesis.strategies``.
"""

from __future__ import annotations

import string

from hypothesis import strategies as st

full_names = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=0x9FF),
    min_size=1,
    max_size=80,
).filter(lambda s: s.strip() != "")

_local = st.text(alphabet=string.ascii_lowercase + string.digits, min_size=1, max_size=20)
_domain = st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=15)
_tld = st.sampled_from(["com", "net", "org", "bd", "co", "io"])
emails = st.builds(lambda l, d, t: f"{l}@{d}.{t}", _local, _domain, _tld)

valid_passwords = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=0x9FF),
    min_size=8,
    max_size=64,
)

invalid_passwords = st.text(max_size=7)

invalid_emails = st.one_of(
    st.text(alphabet=string.ascii_lowercase, min_size=0, max_size=12).filter(
        lambda s: "@" not in s
    ),
    st.builds(lambda l: f"{l}@nodot", _local),
    st.builds(lambda d, t: f"@{d}.{t}", _domain, _tld),
    st.builds(lambda l, t: f"{l}@.{t}", _local, _tld),
    st.builds(lambda l, d, t: f"{l} x@{d}.{t}", _local, _domain, _tld),
)

unicode_text = st.text(
    alphabet=st.characters(min_codepoint=0, max_codepoint=0x9FF),
    min_size=0,
    max_size=200,
)

patient_data_text = st.one_of(
    st.just(""),
    st.text(
        alphabet=st.characters(min_codepoint=0, max_codepoint=0x9FF),
        min_size=0,
        max_size=300,
    ),
    st.text(
        alphabet=st.characters(min_codepoint=0, max_codepoint=0x9FF),
        min_size=2000,
        max_size=6000,
    ),
)

valid_vitals_values = st.floats(
    min_value=0, max_value=1000, allow_nan=False, allow_infinity=False
)

out_of_range_vitals_values = st.one_of(
    st.floats(max_value=-0.0001, allow_nan=False, allow_infinity=False),
    st.floats(min_value=1000.0001, allow_nan=False, allow_infinity=False),
)

consultation_fees_bdt = st.decimals(
    min_value=0, max_value=99999999, places=2, allow_nan=False, allow_infinity=False
)

import datetime as _dt

specialties = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=0x9FF),
    min_size=1,
    max_size=60,
).filter(lambda s: s.strip() != "")

qualifications = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(min_codepoint=32, max_codepoint=0x9FF),
        min_size=1,
        max_size=120,
    ).filter(lambda s: s.strip() != ""),
)

_specialty_words = st.text(
    alphabet=string.ascii_letters, min_size=1, max_size=12
)
searchable_specialties = st.lists(
    _specialty_words, min_size=1, max_size=3
).map(lambda words: " ".join(words))

slot_dates = st.dates(
    min_value=_dt.date(2024, 1, 1), max_value=_dt.date(2030, 12, 31)
)

slot_times = st.builds(
    lambda h, m: _dt.time(hour=h, minute=m),
    st.integers(min_value=0, max_value=23),
    st.integers(min_value=0, max_value=59),
)

@st.composite
def valid_slot_intervals(draw):
    """Draw a (date, start, end) tuple with ``start < end`` (Property 19)."""
    date = draw(slot_dates)
    start = draw(slot_times)
    end = draw(slot_times)
    if start >= end:
        start, end = (end, start)

    if start == end:
        end = _dt.time(
            hour=end.hour, minute=end.minute
        )

        total = end.hour * 60 + end.minute + 1
        end = _dt.time(hour=(total // 60) % 24, minute=total % 60)
        if start >= end:
            start, end = _dt.time(0, 0), _dt.time(23, 59)
    return date, start, end

@st.composite
def invalid_slot_intervals(draw):
    """Draw a (date, start, end) tuple with ``start >= end`` (Property 20)."""
    date = draw(slot_dates)
    start = draw(slot_times)
    end = draw(slot_times)
    if start < end:
        start, end = end, start
    return date, start, end

_med_field = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=0x9FF),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip() != "")

@st.composite
def valid_medications(draw):
    """Draw a list (>=1) of fully specified medication dicts (Property 36)."""
    count = draw(st.integers(min_value=1, max_value=5))
    return [
        {
            "name": draw(_med_field),
            "dosage": draw(_med_field),
            "frequency": draw(_med_field),
            "duration": draw(_med_field),
        }
        for _ in range(count)
    ]

_blank_field = st.sampled_from(["", "   ", "\t", "\n"])
