"""Tests for date recurrence generation engine."""

from datetime import date

from beanschedule.recurrence import RecurrenceEngine


class TestMonthlyRecurrence:
    """Tests for MONTHLY frequency recurrence."""

    def test_monthly_basic(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=15", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert len(dates) == 3
        assert date(2024, 1, 15) in dates
        assert date(2024, 2, 15) in dates
        assert date(2024, 3, 15) in dates

    def test_monthly_day_1(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=1", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 4, 30))
        assert len(dates) == 4
        assert date(2024, 1, 1) in dates
        assert date(2024, 2, 1) in dates

    def test_monthly_day_31(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=31", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 4, 30))
        # dateutil skips months without a 31st
        assert date(2024, 1, 31) in dates
        assert date(2024, 3, 31) in dates
        assert len(dates) == 2

    def test_monthly_leap_year_feb_29(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=29", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2025, 3, 31))
        assert date(2024, 2, 29) in dates


class TestBimonthlyRecurrence:
    """Tests for multiple days per month (BYMONTHDAY list)."""

    def test_bimonthly_5th_and_20th(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=5,20", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 2, 28))
        assert len(dates) == 4
        assert date(2024, 1, 5) in dates
        assert date(2024, 1, 20) in dates
        assert date(2024, 2, 5) in dates
        assert date(2024, 2, 20) in dates

    def test_bimonthly_single_day(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=15", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert len(dates) == 3
        assert date(2024, 1, 15) in dates
        assert date(2024, 2, 15) in dates

    def test_bimonthly_edge_days_1_and_31(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=1,31", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert date(2024, 1, 1) in dates
        assert date(2024, 1, 31) in dates
        assert date(2024, 2, 1) in dates
        assert date(2024, 3, 1) in dates
        assert date(2024, 3, 31) in dates


class TestWeeklyRecurrence:
    """Tests for WEEKLY frequency."""

    def test_weekly_monday(self, sample_schedule):
        engine = RecurrenceEngine()
        # Jan 1 2024 is Monday; BYDAY=MO
        schedule = sample_schedule(
            rrule="FREQ=WEEKLY;BYDAY=MO", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 1, 31))
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
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=WEEKLY;INTERVAL=2;BYDAY=MO", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 2, 28))
        assert date(2024, 1, 1) in dates
        assert date(2024, 1, 15) in dates
        assert date(2024, 1, 29) in dates
        assert len(dates) >= 4

    def test_weekly_all_weekdays(self, sample_schedule):
        engine = RecurrenceEngine()
        for byday in ["MO", "WE", "FR"]:
            schedule = sample_schedule(
                rrule=f"FREQ=WEEKLY;BYDAY={byday}", start_date=date(2024, 1, 1)
            )
            dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 1, 31))
            assert len(dates) > 0


class TestYearlyRecurrence:
    """Tests for YEARLY frequency."""

    def test_yearly_basic(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=15", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2026, 12, 31))
        assert len(dates) == 3
        assert date(2024, 1, 15) in dates
        assert date(2025, 1, 15) in dates
        assert date(2026, 1, 15) in dates

    def test_yearly_leap_day_feb_29(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2028, 12, 31))
        assert date(2024, 2, 29) in dates
        assert date(2028, 2, 29) in dates

    def test_yearly_different_months(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=YEARLY;BYMONTH=12;BYMONTHDAY=25", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2026, 12, 31))
        assert date(2024, 12, 25) in dates
        assert date(2025, 12, 25) in dates


class TestIntervalRecurrence:
    """Tests for every-N-months recurrence."""

    def test_interval_quarterly_every_3_months(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=15", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 12, 31))
        assert len(dates) == 4
        assert date(2024, 1, 15) in dates
        assert date(2024, 4, 15) in dates
        assert date(2024, 7, 15) in dates
        assert date(2024, 10, 15) in dates

    def test_interval_semi_annual_every_6_months(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;INTERVAL=6;BYMONTHDAY=1", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 12, 31))
        assert len(dates) == 2
        assert date(2024, 1, 1) in dates
        assert date(2024, 7, 1) in dates

    def test_interval_custom_2_months(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;INTERVAL=2;BYMONTHDAY=10", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 12, 31))
        assert len(dates) == 6
        assert date(2024, 1, 10) in dates
        assert date(2024, 3, 10) in dates
        assert date(2024, 5, 10) in dates


class TestNthWeekdayRecurrence:
    """Tests for Nth weekday of month."""

    def test_second_tuesday(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYDAY=+2TU", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert date(2024, 1, 9) in dates  # 2nd Tuesday Jan 2024
        assert date(2024, 2, 13) in dates  # 2nd Tuesday Feb 2024

    def test_last_friday(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYDAY=-1FR", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert date(2024, 1, 26) in dates  # Last Friday Jan 2024
        assert date(2024, 2, 23) in dates  # Last Friday Feb 2024


class TestLastDayOfMonth:
    """Tests for last day of month."""

    def test_last_day(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=-1", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert date(2024, 1, 31) in dates
        assert date(2024, 2, 29) in dates  # 2024 is leap year
        assert date(2024, 3, 31) in dates


class TestDateRangeHandling:
    """Tests for date range clipping and boundaries."""

    def test_schedule_start_date_after_range_start(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=15", start_date=date(2024, 2, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert date(2024, 1, 15) not in dates
        assert date(2024, 2, 15) in dates
        assert date(2024, 3, 15) in dates

    def test_schedule_end_date_before_range_end(self, sample_schedule):
        engine = RecurrenceEngine()
        from beanschedule.schema import RecurrenceRule

        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=15", start_date=date(2024, 1, 1)
        )
        schedule.recurrence = RecurrenceRule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=15",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 28),
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert date(2024, 1, 15) in dates
        assert date(2024, 2, 15) in dates
        assert date(2024, 3, 15) not in dates

    def test_invalid_range_start_after_end(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(rrule="FREQ=MONTHLY;BYMONTHDAY=15")
        dates = engine.generate(schedule, date(2024, 3, 1), date(2024, 1, 1))
        assert len(dates) == 0

    def test_range_with_no_occurrences(self, sample_schedule):
        engine = RecurrenceEngine()
        from beanschedule.schema import RecurrenceRule

        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=15", start_date=date(2024, 1, 1)
        )
        schedule.recurrence = RecurrenceRule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=15",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        dates = engine.generate(schedule, date(2024, 2, 1), date(2024, 3, 31))
        assert len(dates) == 0


class TestRecurrenceDateOrdering:
    """Tests for date ordering and deduplication."""

    def test_dates_sorted(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=20,5,15", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert dates == sorted(dates)

    def test_no_duplicate_dates(self, sample_schedule):
        engine = RecurrenceEngine()
        schedule = sample_schedule(
            rrule="FREQ=MONTHLY;BYMONTHDAY=15", start_date=date(2024, 1, 1)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert len(dates) == len(set(dates))
