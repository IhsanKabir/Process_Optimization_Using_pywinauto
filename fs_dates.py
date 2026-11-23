"""fs_dates.py - Which travel dates the FS (tax details) search tries.

By default each airline is tried on 7 consecutive days ~1 month out, then 7
more ~3 months out. The user can replace that with their own dates, e.g. when
an airline only has inventory in December:

    15DEC..22DEC, 10JAN          Smartpoint dates (next time that day comes)
    2026-12-15..2026-12-22       ISO dates
    +45..+50                     days from today
    15DEC-22DEC, +45-+50         "-" also works between those two forms

Dates are tried in the order given; duplicates are dropped.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from constants import (
    FS_DATE_FALLBACK_OFFSET,
    FS_DATE_OFFSET_START,
    FS_DATE_STEP,
    FS_DATE_WINDOW_DAYS,
)
from exceptions import ValidationError

# Smartpoint does not sell further ahead than this.
FS_DATE_MAX_AHEAD_DAYS = 331
# Keeps a typo like 01JAN..31DEC from trying hundreds of dates per airline.
FS_DATE_MAX_COUNT = 60

_RANGE_SEPARATORS = re.compile(r"\s*(?:\.\.|\bto\b)\s*", re.IGNORECASE)
_DASH_RANGE = re.compile(
    r"^(\d{1,2}[A-Z]{3}(?:\d{2}|\d{4})?|\+\d+)\s*-\s*(\d{1,2}[A-Z]{3}(?:\d{2}|\d{4})?|\+\d+)$"
)
_SMARTPOINT = re.compile(r"^(\d{1,2})([A-Z]{3})(\d{2}|\d{4})?$")
_OFFSET = re.compile(r"^\+(\d+)$")


def _invalid(value: str, message: str) -> ValidationError:
    return ValidationError("FS dates", value, message)


def default_fs_dates(today: date) -> list[date]:
    """The built-in schedule: two 7-day windows, ~1 and ~3 months out."""
    dates = []
    for window_start in (FS_DATE_OFFSET_START, FS_DATE_FALLBACK_OFFSET):
        for offset in range(
            window_start, window_start + FS_DATE_WINDOW_DAYS, FS_DATE_STEP
        ):
            dates.append(today + timedelta(days=offset))
    return dates


def _parse_one(token: str, today: date) -> date:
    text = token.strip().upper()
    match = _OFFSET.match(text)
    if match:
        return today + timedelta(days=int(match.group(1)))
    match = _SMARTPOINT.match(text)
    if match:
        day, month, year = match.groups()
        try:
            if year:
                full_year = int(year) + (2000 if len(year) == 2 else 0)
                return datetime.strptime(f"{day}{month}{full_year}", "%d%b%Y").date()
            # No year: the next time that day comes, as Smartpoint reads it.
            for candidate_year in (today.year, today.year + 1):
                try:
                    found = datetime.strptime(
                        f"{day}{month}{candidate_year}", "%d%b%Y"
                    ).date()
                except ValueError:
                    continue  # 29FEB in a non-leap year
                if found >= today:
                    return found
        except ValueError:
            pass
        raise _invalid(token.strip(), "not a date")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _invalid(
            token.strip(), "not a date (use 15DEC, 2026-12-15 or +45)"
        ) from None


def _split_range(item: str) -> tuple[str, str] | None:
    parts = _RANGE_SEPARATORS.split(item)
    if len(parts) == 2:
        return parts[0], parts[1]
    if len(parts) > 2:
        raise _invalid(item, "more than one range separator")
    match = _DASH_RANGE.match(item.upper())
    return (match.group(1), match.group(2)) if match else None


def parse_fs_dates(text: str, today: date) -> list[date]:
    """The dates a user typed, in order. Raises ValidationError when unusable."""
    dates: list[date] = []
    for raw_item in re.split(r"[,;\n]", text or ""):
        item = raw_item.strip()
        if not item:
            continue
        bounds = _split_range(item)
        if bounds:
            start, end = (_parse_one(b, today) for b in bounds)
            if end < start:
                raise _invalid(item, "the range ends before it starts")
            days = (end - start).days
            dates.extend(start + timedelta(days=d) for d in range(days + 1))
        else:
            dates.append(_parse_one(item, today))
        if len(dates) > FS_DATE_MAX_COUNT:
            raise _invalid(
                text, f"more than {FS_DATE_MAX_COUNT} days; use shorter ranges"
            )

    unique = list(dict.fromkeys(dates))
    if not unique:
        raise _invalid(text, "no dates given")
    last_day = today + timedelta(days=FS_DATE_MAX_AHEAD_DAYS)
    for d in unique:
        if d < today:
            raise _invalid(f"{d:%d%b%Y}".upper(), "the date is in the past")
        if d > last_day:
            raise _invalid(
                f"{d:%d%b%Y}".upper(),
                f"more than {FS_DATE_MAX_AHEAD_DAYS} days ahead; "
                "Smartpoint cannot search it",
            )
    return unique


def resolve_fs_dates(text: str | None, today: date | None = None) -> list[date]:
    """The user's dates when given, otherwise the built-in schedule."""
    today = today or date.today()
    if not (text or "").strip():
        return default_fs_dates(today)
    return parse_fs_dates(text, today)


def smartpoint_date(d: date) -> str:
    """15DEC: the date form the FS command takes."""
    return d.strftime("%d%b").upper()
