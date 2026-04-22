"""Tests for the FS date-offset schedule.

The FS extractor now tries two 7-day windows before giving up on an airline:
one starting ~1 month out and one starting ~3 months out. These tests pin
that contract so a future refactor can't silently regress it.
"""
import pytest

import constants


@pytest.mark.unit
def test_first_window_starts_one_month_out() -> None:
    assert constants.FS_DATE_OFFSET_START == 30


@pytest.mark.unit
def test_fallback_window_starts_three_months_out() -> None:
    assert constants.FS_DATE_FALLBACK_OFFSET == 90


@pytest.mark.unit
def test_each_window_covers_seven_days() -> None:
    assert constants.FS_DATE_WINDOW_DAYS == 7


@pytest.mark.unit
def test_windows_try_consecutive_days() -> None:
    assert constants.FS_DATE_STEP == 1


@pytest.mark.unit
def test_schedule_matches_documented_behavior() -> None:
    """The FS loop in main.py expands constants into this offset list."""
    expected = list(range(30, 37)) + list(range(90, 97))

    schedule: list[int] = []
    for window_start in (
        constants.FS_DATE_OFFSET_START,
        constants.FS_DATE_FALLBACK_OFFSET,
    ):
        schedule.extend(
            range(
                window_start,
                window_start + constants.FS_DATE_WINDOW_DAYS,
                constants.FS_DATE_STEP,
            )
        )

    assert schedule == expected
