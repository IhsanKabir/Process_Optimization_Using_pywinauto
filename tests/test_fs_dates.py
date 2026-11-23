"""Tests for fs_dates: the user's own FS search dates."""

from datetime import date, timedelta

import pytest

from exceptions import ValidationError
from fs_dates import (
    FS_DATE_MAX_AHEAD_DAYS,
    default_fs_dates,
    parse_fs_dates,
    resolve_fs_dates,
    smartpoint_date,
)

TODAY = date(2026, 11, 23)


def _days(*pairs):
    return [date(y, m, d) for y, m, d in pairs]


def test_empty_text_gives_the_built_in_schedule():
    dates = resolve_fs_dates("  ", TODAY)

    assert dates == default_fs_dates(TODAY)
    assert dates[0] == TODAY + timedelta(days=30)
    assert dates[7] == TODAY + timedelta(days=90)
    assert len(dates) == 14


def test_smartpoint_range_and_single_date():
    dates = parse_fs_dates("15DEC..17DEC, 10JAN", TODAY)

    assert dates == _days((2026, 12, 15), (2026, 12, 16), (2026, 12, 17), (2027, 1, 10))


def test_dash_range_between_smartpoint_dates():
    assert parse_fs_dates("15dec-16dec", TODAY) == _days((2026, 12, 15), (2026, 12, 16))


def test_smartpoint_date_without_year_rolls_into_next_year():
    assert parse_fs_dates("10JAN", TODAY) == _days((2027, 1, 10))
    assert parse_fs_dates("23NOV", TODAY) == [TODAY]
    # Already gone this year, and next year's is beyond what Smartpoint sells.
    with pytest.raises(ValidationError, match="days ahead"):
        parse_fs_dates("01NOV", TODAY)


def test_smartpoint_date_with_year():
    assert parse_fs_dates("05JAN27", TODAY) == _days((2027, 1, 5))
    assert parse_fs_dates("05JAN2027", TODAY) == _days((2027, 1, 5))


def test_iso_range_and_offsets():
    assert parse_fs_dates("2026-12-30 to 2027-01-01", TODAY) == _days(
        (2026, 12, 30), (2026, 12, 31), (2027, 1, 1)
    )
    assert parse_fs_dates("+45..+46", TODAY) == [
        TODAY + timedelta(days=45),
        TODAY + timedelta(days=46),
    ]
    assert parse_fs_dates("+45-+46", TODAY) == parse_fs_dates("+45..+46", TODAY)


def test_order_is_kept_and_duplicates_dropped():
    assert parse_fs_dates("10JAN, 15DEC..16DEC, 10JAN", TODAY) == _days(
        (2027, 1, 10), (2026, 12, 15), (2026, 12, 16)
    )


@pytest.mark.parametrize(
    "text, message",
    [
        ("hello", "not a date"),
        ("31FEB", "not a date"),
        ("20DEC..15DEC", "ends before it starts"),
        ("2026-11-01", "in the past"),
        (f"+{FS_DATE_MAX_AHEAD_DAYS + 1}", "days ahead"),
        ("+30..+200", "more than"),
        (",,", "no dates given"),
    ],
)
def test_unusable_dates_are_rejected(text, message):
    with pytest.raises(ValidationError, match=message):
        parse_fs_dates(text, TODAY)


def test_smartpoint_date_format():
    assert smartpoint_date(date(2026, 12, 5)) == "05DEC"
