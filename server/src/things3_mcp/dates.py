"""Date encoding used by the Things 3 database.

Two different encodings live in TMTask:

* ``startDate`` / ``deadline`` are bit-packed integers holding a calendar date
  with no timezone: ``year = v >> 16``, ``month = (v >> 12) & 0xF``,
  ``day = (v >> 7) & 0x1F``. The low 7 bits carry internal flags and are
  preserved on re-encode so we never clobber them.
* ``creationDate`` / ``userModificationDate`` / ``stopDate`` are plain Unix
  timestamps as floats.

Verified against live data: 132810624 -> 2026-08-15, 132810496 -> 2026-08-14.
"""

from __future__ import annotations

from datetime import date, datetime, timezone


def decode_date(value: int | None) -> str | None:
    """Packed Things integer -> ``YYYY-MM-DD``. Returns None for empty values."""
    if not value:
        return None
    year = value >> 16
    month = (value >> 12) & 0xF
    day = (value >> 7) & 0x1F
    if not (1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2200):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def encode_date(value: str | date, flags: int = 0) -> int:
    """``YYYY-MM-DD`` (or a date) -> packed Things integer."""
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return (value.year << 16) | (value.month << 12) | (value.day << 7) | (flags & 0x7F)


def today_packed(today: date | None = None) -> int:
    """Packed value for today at flag 0 — the lower bound for Today queries."""
    return encode_date(today or date.today())


def today_upper_bound(today: date | None = None) -> int:
    """Largest packed value still meaning "today", flags included.

    Packed values sort chronologically, so ``startDate <= today_upper_bound()``
    selects everything scheduled today or earlier.
    """
    return today_packed(today) | 0x7F


def decode_timestamp(value: float | None) -> str | None:
    """Unix timestamp -> local ISO-8601 string."""
    if not value:
        return None
    return (
        datetime.fromtimestamp(value, tz=timezone.utc)
        .astimezone()
        .replace(microsecond=0)
        .isoformat()
    )


def now_iso() -> str:
    """Current local time as an ISO-8601 string, used for worklog entries."""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()
