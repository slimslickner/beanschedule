"""Tests for advanced recurrence rules (Phase 3)."""

from datetime import date

import pytest

from beanschedule.recurrence import RecurrenceEngine
from beanschedule.schema import (
    MatchCriteria,
    MissingTransactionConfig,
    RecurrenceRule,
    Schedule,
    TransactionTemplate,
)
from beanschedule.types import DayOfWeek, FrequencyType


@pytest.fixture
def engine():
    """Create recurrence engine."""
    return RecurrenceEngine()


class TestMonthlyOnDays:
    """Tests for MONTHLY_ON_DAYS frequency (multiple days per month)."""

    def test_paycheck_5th_and_20th(self, engine):
        """Should generate occurrences on 5th and 20th of each month."""
        schedule = Schedule(
            id="paycheck",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*EMPLOYER.*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.MONTHLY_ON_DAYS,
                start_date=date(2024, 1, 1),
                days_of_month=[5, 20],
            ),
            transaction=TransactionTemplate(
                payee="Paycheck",
                narration="",
                metadata={"schedule_id": "paycheck"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        expected = [
            date(2024, 1, 5),
            date(2024, 1, 20),
            date(2024, 2, 5),
            date(2024, 2, 20),
            date(2024, 3, 5),
            date(2024, 3, 20),
        ]
        assert dates == expected

    def test_single_day_per_month(self, engine):
        """Should work with single day (similar to MONTHLY)."""
        schedule = Schedule(
            id="test",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.MONTHLY_ON_DAYS,
                start_date=date(2024, 1, 1),
                days_of_month=[15],
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        expected = [
            date(2024, 1, 15),
            date(2024, 2, 15),
            date(2024, 3, 15),
        ]
        assert dates == expected

    def test_multiple_days_sorted(self, engine):
        """Should return days in sorted order even if input is unsorted."""
        schedule = Schedule(
            id="test",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.MONTHLY_ON_DAYS,
                start_date=date(2024, 1, 1),
                days_of_month=[20, 5, 10],  # Unsorted
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 2, 28))

        expected = [
            date(2024, 1, 5),
            date(2024, 1, 10),
            date(2024, 1, 20),
            date(2024, 2, 5),
            date(2024, 2, 10),
            date(2024, 2, 20),
        ]
        assert dates == expected

    def test_day_31_skips_short_months(self, engine):
        """Should skip months that don't have day 31."""
        schedule = Schedule(
            id="test",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.MONTHLY_ON_DAYS,
                start_date=date(2024, 1, 1),
                days_of_month=[31],
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 4, 30))

        # Jan 31, Mar 31 (Feb has no 31st), no Apr 31
        expected = [
            date(2024, 1, 31),
            date(2024, 3, 31),
        ]
        assert dates == expected


class TestNthWeekday:
    """Tests for NTH_WEEKDAY frequency (Nth occurrence of weekday in month)."""

    def test_second_tuesday(self, engine):
        """Should generate 2nd Tuesday of each month."""
        schedule = Schedule(
            id="meeting",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.NTH_WEEKDAY,
                start_date=date(2024, 1, 1),
                day_of_week=DayOfWeek.TUE,
                nth_occurrence=2,
            ),
            transaction=TransactionTemplate(
                payee="Meeting",
                narration="",
                metadata={"schedule_id": "meeting"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        expected = [
            date(2024, 1, 9),  # 2nd Tuesday of Jan
            date(2024, 2, 13),  # 2nd Tuesday of Feb
            date(2024, 3, 12),  # 2nd Tuesday of Mar
        ]
        assert dates == expected

    def test_first_monday(self, engine):
        """Should generate 1st Monday of each month."""
        schedule = Schedule(
            id="test",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.NTH_WEEKDAY,
                start_date=date(2024, 1, 1),
                day_of_week=DayOfWeek.MON,
                nth_occurrence=1,
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        expected = [
            date(2024, 1, 1),  # 1st Monday of Jan (Jan 1 is Monday)
            date(2024, 2, 5),  # 1st Monday of Feb
            date(2024, 3, 4),  # 1st Monday of Mar
        ]
        assert dates == expected

    def test_last_friday(self, engine):
        """Should generate last Friday of each month."""
        schedule = Schedule(
            id="test",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.NTH_WEEKDAY,
                start_date=date(2024, 1, 1),
                day_of_week=DayOfWeek.FRI,
                nth_occurrence=-1,  # -1 means last
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        expected = [
            date(2024, 1, 26),  # Last Friday of Jan
            date(2024, 2, 23),  # Last Friday of Feb
            date(2024, 3, 29),  # Last Friday of Mar
        ]
        assert dates == expected

    def test_third_wednesday(self, engine):
        """Should generate 3rd Wednesday of each month."""
        schedule = Schedule(
            id="test",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.NTH_WEEKDAY,
                start_date=date(2024, 1, 1),
                day_of_week=DayOfWeek.WED,
                nth_occurrence=3,
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        expected = [
            date(2024, 1, 17),  # 3rd Wednesday of Jan
            date(2024, 2, 21),  # 3rd Wednesday of Feb
            date(2024, 3, 20),  # 3rd Wednesday of Mar
        ]
        assert dates == expected


class TestLastDayOfMonth:
    """Tests for LAST_DAY_OF_MONTH frequency."""

    def test_last_day_each_month(self, engine):
        """Should generate last day of each month."""
        schedule = Schedule(
            id="test",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.LAST_DAY_OF_MONTH,
                start_date=date(2024, 1, 1),
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))

        expected = [
            date(2024, 1, 31),  # Last day of Jan
            date(2024, 2, 29),  # Last day of Feb (2024 is leap year)
            date(2024, 3, 31),  # Last day of Mar
        ]
        assert dates == expected

    def test_handles_february_non_leap(self, engine):
        """Should handle February in non-leap years."""
        schedule = Schedule(
            id="test",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.LAST_DAY_OF_MONTH,
                start_date=date(2023, 1, 1),  # 2023 is not a leap year
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2023, 1, 1), date(2023, 3, 31))

        expected = [
            date(2023, 1, 31),  # Last day of Jan
            date(2023, 2, 28),  # Last day of Feb (28 in non-leap year)
            date(2023, 3, 31),  # Last day of Mar
        ]
        assert dates == expected

    def test_handles_30_day_months(self, engine):
        """Should handle months with 30 days."""
        schedule = Schedule(
            id="test",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.LAST_DAY_OF_MONTH,
                start_date=date(2024, 4, 1),
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2024, 4, 1), date(2024, 6, 30))

        expected = [
            date(2024, 4, 30),  # Last day of Apr (30 days)
            date(2024, 5, 31),  # Last day of May (31 days)
            date(2024, 6, 30),  # Last day of Jun (30 days)
        ]
        assert dates == expected

    def test_year_boundary(self, engine):
        """Should handle year boundaries correctly."""
        schedule = Schedule(
            id="test",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.LAST_DAY_OF_MONTH,
                start_date=date(2023, 11, 1),
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2023, 11, 1), date(2024, 2, 29))

        expected = [
            date(2023, 11, 30),  # Last day of Nov 2023
            date(2023, 12, 31),  # Last day of Dec 2023
            date(2024, 1, 31),  # Last day of Jan 2024
            date(2024, 2, 29),  # Last day of Feb 2024 (leap year)
        ]
        assert dates == expected


class TestAdvancedRecurrenceEdgeCases:
    """Edge cases for advanced recurrence types."""

    def test_monthly_on_days_empty_list_returns_empty(self, engine):
        """Should return empty list if days_of_month is empty."""
        schedule = Schedule(
            id="test",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.MONTHLY_ON_DAYS,
                start_date=date(2024, 1, 1),
                days_of_month=[],  # Empty
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert dates == []

    def test_nth_weekday_missing_day_of_week_returns_empty(self, engine):
        """Should return empty list if day_of_week is missing."""
        schedule = Schedule(
            id="test",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.NTH_WEEKDAY,
                start_date=date(2024, 1, 1),
                nth_occurrence=2,
                # day_of_week is missing
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert dates == []

    def test_with_end_date(self, engine):
        """Should respect end_date for advanced recurrence types."""
        schedule = Schedule(
            id="test",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.LAST_DAY_OF_MONTH,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 2, 29),  # Stop after Feb
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 12, 31))

        # Should only include Jan and Feb
        expected = [
            date(2024, 1, 31),
            date(2024, 2, 29),
        ]
        assert dates == expected
