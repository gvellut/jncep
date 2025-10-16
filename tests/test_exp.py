from datetime import date, datetime, timezone

import dateutil.parser

from jncep.core import _compute_expiration_date, expiration_date
from jncep.model import Part, Volume, Series
from addict import Dict as Addict


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


def test_api_expiration_matches_computed():
    """
    Test that the expiration field from API matches the computed expiration date.
    This test creates a mock Part with raw_data containing an expiration field
    and verifies it matches what the computation would produce.
    """
    # Test case 1: Publishing date 2024-02-16, expiration should be 2024-03-15
    # (day >= 9, so next month)
    publishing_date = "2024-02-16T00:00:00Z"
    expected_expiration = "2024-03-15T00:00:00Z"
    
    # Create mock objects
    series_raw_data = Addict({"catchup": False})
    series = Series(series_raw_data, "test_series_id")
    
    volume_raw_data = Addict({"publishing": publishing_date, "owned": False})
    volume = Volume(volume_raw_data, "test_volume_id", 1, series=series)
    
    part_raw_data = Addict({
        "expiration": expected_expiration,
        "preview": False,
        "launch": "2024-02-16T00:00:00Z"
    })
    part = Part(part_raw_data, "test_part_id", 1, volume=volume, series=series)
    
    # Compute expiration using the old function
    computed_exp_date = expiration_date(part)
    
    # Parse the API expiration field
    api_exp_date = dateutil.parser.parse(part.raw_data["expiration"])
    
    # They should match (ignoring hour differences - API uses 05:00:00, computation uses 00:00:00)
    # So we compare only year, month, day
    assert computed_exp_date.year == api_exp_date.year
    assert computed_exp_date.month == api_exp_date.month
    assert computed_exp_date.day == api_exp_date.day


def test_api_expiration_matches_computed_weekend():
    """
    Test expiration date computation when it falls on a weekend.
    The computation should adjust to Monday.
    """
    # Test case: Publishing date that results in expiration on a weekend
    # 2024-08-09 -> expiration 2024-09-15 (Sunday) -> should be 2024-09-16 (Monday)
    publishing_date = "2024-08-09T00:00:00Z"
    expected_expiration = "2024-09-16T05:00:00Z"
    
    series_raw_data = Addict({"catchup": False})
    series = Series(series_raw_data, "test_series_id")
    
    volume_raw_data = Addict({"publishing": publishing_date, "owned": False})
    volume = Volume(volume_raw_data, "test_volume_id", 1, series=series)
    
    part_raw_data = Addict({
        "expiration": expected_expiration,
        "preview": False,
        "launch": "2024-08-09T00:00:00Z"
    })
    part = Part(part_raw_data, "test_part_id", 1, volume=volume, series=series)
    
    # Compute expiration using the old function
    computed_exp_date = expiration_date(part)
    
    # Parse the API expiration field
    api_exp_date = dateutil.parser.parse(part.raw_data["expiration"])
    
    # They should match
    assert computed_exp_date.year == api_exp_date.year
    assert computed_exp_date.month == api_exp_date.month
    assert computed_exp_date.day == api_exp_date.day


def test_api_expiration_matches_computed_before_9th():
    """
    Test expiration date when publishing is before the 9th of the month.
    Expiration should be on the 15th of the same month.
    """
    # Publishing date 2023-05-08 -> expiration 2023-05-15
    publishing_date = "2023-05-08T00:00:00Z"
    expected_expiration = "2023-05-15T05:00:00Z"
    
    series_raw_data = Addict({"catchup": False})
    series = Series(series_raw_data, "test_series_id")
    
    volume_raw_data = Addict({"publishing": publishing_date, "owned": False})
    volume = Volume(volume_raw_data, "test_volume_id", 1, series=series)
    
    part_raw_data = Addict({
        "expiration": expected_expiration,
        "preview": False,
        "launch": "2023-05-08T00:00:00Z"
    })
    part = Part(part_raw_data, "test_part_id", 1, volume=volume, series=series)
    
    # Compute expiration using the old function
    computed_exp_date = expiration_date(part)
    
    # Parse the API expiration field
    api_exp_date = dateutil.parser.parse(part.raw_data["expiration"])
    
    # They should match
    assert computed_exp_date.year == api_exp_date.year
    assert computed_exp_date.month == api_exp_date.month
    assert computed_exp_date.day == api_exp_date.day
