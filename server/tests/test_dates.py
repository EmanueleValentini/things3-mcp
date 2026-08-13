from datetime import date

import pytest

from things3_mcp.dates import (
    decode_date,
    decode_timestamp,
    encode_date,
    today_packed,
    today_upper_bound,
)


@pytest.mark.parametrize(
    "packed,expected",
    [
        # Captured from a live Things database.
        (132810624, "2026-08-15"),
        (132810496, "2026-08-14"),
    ],
)
def test_decode_known_values(packed, expected):
    assert decode_date(packed) == expected


def test_decode_empty():
    assert decode_date(None) is None
    assert decode_date(0) is None


def test_round_trip():
    for iso in ("2020-01-01", "2026-08-15", "2031-12-31"):
        assert decode_date(encode_date(iso)) == iso


def test_flags_are_preserved_and_ignored():
    packed = encode_date("2026-08-15", flags=0x7F)
    assert decode_date(packed) == "2026-08-15"
    assert packed & 0x7F == 0x7F


def test_packed_values_sort_chronologically():
    days = ["2026-01-31", "2026-02-01", "2026-12-31", "2027-01-01"]
    packed = [encode_date(d) for d in days]
    assert packed == sorted(packed)


def test_today_bounds_bracket_today():
    today = date(2026, 8, 13)
    assert today_packed(today) <= today_upper_bound(today)
    assert encode_date("2026-08-12") < today_packed(today)
    assert encode_date("2026-08-14") > today_upper_bound(today)


def test_decode_timestamp_is_iso():
    assert decode_timestamp(None) is None
    assert decode_timestamp(1786603213.86925).startswith("2026-08-1")
