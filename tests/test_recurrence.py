"""Tests for date recurrence generation engine."""

import pytest
from datetime import date

from beanschedule.recurrence import RecurrenceEngine
from beanschedule.types import FrequencyType, DayOfWeek


class TestMonthlyRecurrence:
    """Tests for MONTHLY frequency recurrence."""

    def test_monthly_basic(self, sample_schedule):
        """Test basic monthly recurrence on day 15."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.MONTHLY,
            day_of_month=15,
            start_date=date(2024, 1, 1),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        # Should have Jan 15, Feb 15, Mar 15
        assert len(dates) == 3
        assert date(2024, 1, 15) in dates
        assert date(2024, 2, 15) in dates
        assert date(2024, 3, 15) in dates

    def test_monthly_day_1(self, sample_schedule):
        """Test monthly recurrence on first day of month."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.MONTHLY,
            day_of_month=1,
            start_date=date(2024, 1, 1),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 4, 30))

        # Should have 1st of each month
        assert len(dates) == 4
        assert date(2024, 1, 1) in dates
        assert date(2024, 2, 1) in dates

    def test_monthly_day_31(self, sample_schedule):
        """Test monthly recurrence on day 31 (handles short months)."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.MONTHLY,
            day_of_month=31,
            start_date=date(2024, 1, 1),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 4, 30))

        # Should skip February (no 31st), April (no 31st) and have Jan 31, Mar 31
        # dateutil.rrule skips invalid dates
        assert date(2024, 1, 31) in dates
        assert date(2024, 3, 31) in dates
        # February and April should be skipped
        assert len(dates) == 2

    def test_monthly_leap_year_feb_29(self, sample_schedule):
        """Test monthly recurrence on Feb 29 in leap year."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.MONTHLY,
            day_of_month=29,
            start_date=date(2024, 1, 1),
        )

        # 2024 is leap year, 2025 is not
        dates = engine.generate(schedule, date(2024, 1, 1), date(2025, 3, 31))

        # Should have Feb 29, 2024 but not Feb 29, 2025
        assert date(2024, 2, 29) in dates
        # In non-leap years, Feb 29 is skipped


class TestBimonthlyRecurrence:
    """Tests for BIMONTHLY frequency (multiple days per month)."""

    def test_bimonthly_5th_and_20th(self, sample_schedule):
        """Test bimonthly recurrence on 5th and 20th."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.BIMONTHLY,
            day_of_month=None,  # Not used for BIMONTHLY
        )
        schedule.recurrence.days_of_month = [5, 20]
        schedule.recurrence.start_date = date(2024, 1, 1)

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 2, 28))

        # Should have 4 dates: Jan 5, Jan 20, Feb 5, Feb 20
        assert len(dates) == 4
        assert date(2024, 1, 5) in dates
        assert date(2024, 1, 20) in dates
        assert date(2024, 2, 5) in dates
        assert date(2024, 2, 20) in dates

    def test_bimonthly_single_day(self, sample_schedule):
        """Test bimonthly with single day (equivalent to monthly)."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.BIMONTHLY,
        )
        schedule.recurrence.days_of_month = [15]
        schedule.recurrence.start_date = date(2024, 1, 1)

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        # Should have Jan 15, Feb 15, Mar 15 (like monthly)
        assert len(dates) == 3
        assert date(2024, 1, 15) in dates
        assert date(2024, 2, 15) in dates

    def test_bimonthly_edge_days_1_and_31(self, sample_schedule):
        """Test bimonthly with first and last days."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.BIMONTHLY,
        )
        schedule.recurrence.days_of_month = [1, 31]
        schedule.recurrence.start_date = date(2024, 1, 1)

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        # Should have: Jan 1, Jan 31, Feb 1, Mar 1, Mar 31
        # Feb 31 doesn't exist, so skipped
        assert date(2024, 1, 1) in dates
        assert date(2024, 1, 31) in dates
        assert date(2024, 2, 1) in dates
        assert date(2024, 3, 1) in dates
        assert date(2024, 3, 31) in dates


class TestWeeklyRecurrence:
    """Tests for WEEKLY frequency."""

    def test_weekly_monday(self, sample_schedule):
        """Test weekly recurrence on Monday."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.WEEKLY,
            day_of_month=None,
        )
        schedule.recurrence.day_of_week = DayOfWeek.MON
        schedule.recurrence.interval = 1
        schedule.recurrence.start_date = date(2024, 1, 1)

        # Jan 1, 2024 is Monday
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 1, 31))

        # Should have all Mondays in January
        mondays = [
            date(2024, 1, 1),
            date(2024, 1, 8),
            date(2024, 1, 15),
            date(2024, 1, 22),
            date(2024, 1, 29),
        ]
        assert len(dates) == 5
        for monday in mondays:
            assert monday in dates

    def test_weekly_biweekly_interval_2(self, sample_schedule):
        """Test bi-weekly recurrence (every 2 weeks)."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.WEEKLY,
        )
        schedule.recurrence.day_of_week = DayOfWeek.MON
        schedule.recurrence.interval = 2  # Bi-weekly
        schedule.recurrence.start_date = date(2024, 1, 1)

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 2, 28))

        # Should have every other Monday
        # Jan 1, Jan 15, Jan 29, Feb 12, Feb 26
        assert date(2024, 1, 1) in dates
        assert date(2024, 1, 15) in dates
        assert date(2024, 1, 29) in dates
        assert len(dates) >= 4

    def test_weekly_all_weekdays(self, sample_schedule):
        """Test weekly recurrence for each day of week."""
        engine = RecurrenceEngine()

        for day in [DayOfWeek.MON, DayOfWeek.WED, DayOfWeek.FRI]:
            schedule = sample_schedule(
                frequency=FrequencyType.WEEKLY,
            )
            schedule.recurrence.day_of_week = day
            schedule.recurrence.interval = 1
            schedule.recurrence.start_date = date(2024, 1, 1)

            dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 1, 31))

            # Should have dates
            assert len(dates) > 0


class TestYearlyRecurrence:
    """Tests for YEARLY frequency."""

    def test_yearly_basic(self, sample_schedule):
        """Test basic yearly recurrence."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.YEARLY,
            day_of_month=None,
        )
        schedule.recurrence.month = 1
        schedule.recurrence.day_of_month = 15
        schedule.recurrence.start_date = date(2024, 1, 1)

        dates = engine.generate(schedule, date(2024, 1, 1), date(2026, 12, 31))

        # Should have Jan 15 for 2024, 2025, 2026
        assert len(dates) == 3
        assert date(2024, 1, 15) in dates
        assert date(2025, 1, 15) in dates
        assert date(2026, 1, 15) in dates

    def test_yearly_leap_day_feb_29(self, sample_schedule):
        """Test yearly recurrence on Feb 29 (leap day)."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.YEARLY,
        )
        schedule.recurrence.month = 2
        schedule.recurrence.day_of_month = 29
        schedule.recurrence.start_date = date(2024, 1, 1)

        dates = engine.generate(schedule, date(2024, 1, 1), date(2028, 12, 31))

        # Feb 29 only exists in leap years (2024, 2028)
        assert date(2024, 2, 29) in dates
        assert date(2028, 2, 29) in dates
        # 2025, 2026, 2027 are not leap years

    def test_yearly_different_months(self, sample_schedule):
        """Test yearly recurrence in different months."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.YEARLY,
        )
        schedule.recurrence.month = 12  # December
        schedule.recurrence.day_of_month = 25
        schedule.recurrence.start_date = date(2024, 1, 1)

        dates = engine.generate(schedule, date(2024, 1, 1), date(2026, 12, 31))

        # Should have Dec 25 for each year
        assert date(2024, 12, 25) in dates
        assert date(2025, 12, 25) in dates


class TestIntervalRecurrence:
    """Tests for INTERVAL frequency (every N months)."""

    def test_interval_quarterly_every_3_months(self, sample_schedule):
        """Test quarterly recurrence (every 3 months)."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.INTERVAL,
            day_of_month=None,
        )
        schedule.recurrence.interval_months = 3
        schedule.recurrence.day_of_month = 15
        schedule.recurrence.start_date = date(2024, 1, 1)

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 12, 31))

        # Should have Jan 15, Apr 15, Jul 15, Oct 15
        assert len(dates) == 4
        assert date(2024, 1, 15) in dates
        assert date(2024, 4, 15) in dates
        assert date(2024, 7, 15) in dates
        assert date(2024, 10, 15) in dates

    def test_interval_semi_annual_every_6_months(self, sample_schedule):
        """Test semi-annual recurrence (every 6 months)."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.INTERVAL,
        )
        schedule.recurrence.interval_months = 6
        schedule.recurrence.day_of_month = 1
        schedule.recurrence.start_date = date(2024, 1, 1)

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 12, 31))

        # Should have Jan 1, Jul 1
        assert len(dates) == 2
        assert date(2024, 1, 1) in dates
        assert date(2024, 7, 1) in dates

    def test_interval_custom_2_months(self, sample_schedule):
        """Test custom interval (every 2 months)."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.INTERVAL,
        )
        schedule.recurrence.interval_months = 2
        schedule.recurrence.day_of_month = 10
        schedule.recurrence.start_date = date(2024, 1, 1)

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 12, 31))

        # Should have Jan 10, Mar 10, May 10, Jul 10, Sep 10, Nov 10
        assert len(dates) == 6
        assert date(2024, 1, 10) in dates
        assert date(2024, 3, 10) in dates
        assert date(2024, 5, 10) in dates


class TestDateRangeHandling:
    """Tests for date range clipping and boundaries."""

    def test_schedule_start_date_after_range_start(self, sample_schedule):
        """Test when schedule start_date is after range start."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.MONTHLY,
            day_of_month=15,
            start_date=date(2024, 2, 1),  # Schedule starts in Feb
        )

        # Query range starts in Jan
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        # Should not have Jan 15 (before schedule start)
        assert date(2024, 1, 15) not in dates
        # But should have Feb 15 and Mar 15
        assert date(2024, 2, 15) in dates
        assert date(2024, 3, 15) in dates

    def test_schedule_end_date_before_range_end(self, sample_schedule):
        """Test when schedule end_date is before range end."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.MONTHLY,
            day_of_month=15,
            start_date=date(2024, 1, 1),
        )
        schedule.recurrence.end_date = date(2024, 2, 28)

        # Query range extends to March
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        # Should have Jan 15, Feb 15 but not Mar 15
        assert date(2024, 1, 15) in dates
        assert date(2024, 2, 15) in dates
        assert date(2024, 3, 15) not in dates

    def test_invalid_range_start_after_end(self, sample_schedule):
        """Test with invalid date range (start > end)."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.MONTHLY,
            day_of_month=15,
        )

        # Invalid range
        dates = engine.generate(schedule, date(2024, 3, 1), date(2024, 1, 1))

        # Should return empty list
        assert len(dates) == 0

    def test_range_with_no_occurrences(self, sample_schedule):
        """Test range with no occurrences in requested range."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.MONTHLY,
            day_of_month=15,
            start_date=date(2024, 1, 1),
        )
        schedule.recurrence.end_date = date(2024, 1, 31)

        # Query range after schedule end
        dates = engine.generate(schedule, date(2024, 2, 1), date(2024, 3, 31))

        # Should return empty (schedule ends before query range)
        assert len(dates) == 0


class TestRecurrenceEdgeCases:
    """Tests for edge cases and error handling."""

    def test_monthly_missing_day_of_month(self, sample_schedule):
        """Test monthly without required day_of_month."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.MONTHLY,
        )
        schedule.recurrence.day_of_month = None

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        # Should return empty list (error handling)
        assert len(dates) == 0

    def test_weekly_missing_day_of_week(self, sample_schedule):
        """Test weekly without required day_of_week."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.WEEKLY,
        )
        schedule.recurrence.day_of_week = None

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 1, 31))

        # Should return empty list (error handling)
        assert len(dates) == 0

    def test_yearly_missing_month(self, sample_schedule):
        """Test yearly without required month."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.YEARLY,
        )
        schedule.recurrence.month = None

        dates = engine.generate(schedule, date(2024, 1, 1), date(2026, 12, 31))

        # Should return empty list (error handling)
        assert len(dates) == 0

    def test_interval_missing_interval_months(self, sample_schedule):
        """Test interval without required interval_months."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.INTERVAL,
        )
        schedule.recurrence.interval_months = None

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 12, 31))

        # Should return empty list (error handling)
        assert len(dates) == 0

    def test_bimonthly_empty_days_of_month(self, sample_schedule):
        """Test bimonthly with empty days_of_month list."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.BIMONTHLY,
        )
        schedule.recurrence.days_of_month = []

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 2, 28))

        # Should return empty list (error handling)
        assert len(dates) == 0


class TestRecurrenceDateOrdering:
    """Tests for date ordering and sorting."""

    def test_dates_sorted(self, sample_schedule):
        """Test that generated dates are sorted."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.BIMONTHLY,
        )
        schedule.recurrence.days_of_month = [20, 5, 15]  # Out of order
        schedule.recurrence.start_date = date(2024, 1, 1)

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        # Dates should be sorted
        assert dates == sorted(dates)

    def test_no_duplicate_dates(self, sample_schedule):
        """Test that no duplicate dates are generated."""
        engine = RecurrenceEngine()

        schedule = sample_schedule(
            frequency=FrequencyType.BIMONTHLY,
        )
        schedule.recurrence.days_of_month = [15, 15, 15]  # Duplicates in input

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        # Should have unique dates
        assert len(dates) == len(set(dates))
