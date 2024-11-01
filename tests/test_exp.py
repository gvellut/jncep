from datetime import date, datetime, timezone

from jncep.core import _compute_expiration_date


def test_date1():
    date1 = date(2024, 12, 16)
    exp_date = _compute_expiration_date(date1)

    assert exp_date.year == 2025
    assert exp_date.month == 1
    assert exp_date.day == 15


def test_date2():
    date1 = date(2025, 1, 24)
    exp_date = _compute_expiration_date(date1)

    assert exp_date.year == 2025
    assert exp_date.month == 2
    assert exp_date.day == 17


def test_date3():
    date1 = date(2024, 8, 9)
    exp_date = _compute_expiration_date(date1)

    assert exp_date.year == 2024
    assert exp_date.month == 9
    assert exp_date.day == 16


def test_date4():
    date1 = date(2024, 9, 10)
    exp_date = _compute_expiration_date(date1)

    assert exp_date.year == 2024
    assert exp_date.month == 10
    assert exp_date.day == 15


def test_date5():
    date1 = date(2023, 5, 8)
    exp_date = _compute_expiration_date(date1)

    assert exp_date.year == 2023
    assert exp_date.month == 5
    assert exp_date.day == 15


def test_date6():
    date1 = date(2024, 10, 14)
    exp_date = _compute_expiration_date(date1)

    assert exp_date.year == 2024
    assert exp_date.month == 11
    assert exp_date.day == 15


def test_date7():
    date1 = date(2025, 1, 10)
    exp_date = _compute_expiration_date(date1)

    assert exp_date.year == 2025
    assert exp_date.month == 2
    assert exp_date.day == 17


def test_compare():
    # session.now is returned in UTC; do the same
    date_local = datetime(2025, 2, 17, 1, tzinfo=timezone.utc)
    date1 = date(2025, 1, 24)
    # should be 2025-02-17
    exp_date = _compute_expiration_date(date1)

    assert date_local > exp_date
