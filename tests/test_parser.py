"""Unit-тесты для parser."""

from parser import doy_to_date


class TestDoyToDate:
    def test_jan_1(self):
        assert doy_to_date(2025, 1) == "2025-01-01"

    def test_dec_31_non_leap(self):
        assert doy_to_date(2025, 365) == "2025-12-31"

    def test_dec_31_leap(self):
        assert doy_to_date(2024, 366) == "2024-12-31"

    def test_feb_29_leap(self):
        assert doy_to_date(2024, 60) == "2024-02-29"

    def test_feb_28_non_leap(self):
        assert doy_to_date(2025, 59) == "2025-02-28"

    def test_overflow_doy_wraps_to_next_year(self):
        # DOY 400 для 2025 = 2025-01-01 + 399 дней = 2026-02-04
        assert doy_to_date(2025, 400) == "2026-02-04"
