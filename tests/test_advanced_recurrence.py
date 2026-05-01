"""Tests for advanced recurrence rules."""

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
from beanschedule.types import FrequencyType


@pytest.fixture
def engine():
    """Create recurrence engine."""
    return RecurrenceEngine()


def _make_schedule(
    rrule: str, start_date: date = date(2024, 1, 1), end_date: date | None = None
) -> Schedule:
    return Schedule(
        id="test",
        enabled=True,
        match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
        recurrence=RecurrenceRule(
            rrule=rrule, start_date=start_date, end_date=end_date
        ),
        transaction=TransactionTemplate(
            payee="Test", narration="", metadata={"schedule_id": "test"}
        ),
        missing_transaction=MissingTransactionConfig(),
    )


class TestMonthlyOnDays:
    """Tests for multiple days per month."""

    def test_paycheck_5th_and_20th(self, engine):
        schedule = _make_schedule("FREQ=MONTHLY;BYMONTHDAY=5,20")
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
        schedule = _make_schedule("FREQ=MONTHLY;BYMONTHDAY=15")
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert dates == [date(2024, 1, 15), date(2024, 2, 15), date(2024, 3, 15)]

    def test_multiple_days_sorted(self, engine):
        schedule = _make_schedule("FREQ=MONTHLY;BYMONTHDAY=20,5,10")
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
        schedule = _make_schedule("FREQ=MONTHLY;BYMONTHDAY=31")
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 4, 30))
        assert dates == [date(2024, 1, 31), date(2024, 3, 31)]


class TestNthWeekday:
    """Tests for Nth weekday of month."""

    def test_second_tuesday(self, engine):
        schedule = _make_schedule("FREQ=MONTHLY;BYDAY=+2TU")
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert dates == [date(2024, 1, 9), date(2024, 2, 13), date(2024, 3, 12)]

    def test_first_monday(self, engine):
        schedule = _make_schedule("FREQ=MONTHLY;BYDAY=+1MO")
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert dates == [date(2024, 1, 1), date(2024, 2, 5), date(2024, 3, 4)]

    def test_last_friday(self, engine):
        schedule = _make_schedule("FREQ=MONTHLY;BYDAY=-1FR")
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert dates == [date(2024, 1, 26), date(2024, 2, 23), date(2024, 3, 29)]

    def test_third_wednesday(self, engine):
        schedule = _make_schedule("FREQ=MONTHLY;BYDAY=+3WE")
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert dates == [date(2024, 1, 17), date(2024, 2, 21), date(2024, 3, 20)]


class TestLastDayOfMonth:
    """Tests for last day of month."""

    def test_last_day_each_month(self, engine):
        schedule = _make_schedule("FREQ=MONTHLY;BYMONTHDAY=-1")
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 3, 31))
        assert dates == [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)]

    def test_handles_february_non_leap(self, engine):
        schedule = _make_schedule(
            "FREQ=MONTHLY;BYMONTHDAY=-1", start_date=date(2023, 1, 1)
        )
        dates = engine.generate(schedule, date(2023, 1, 1), date(2023, 3, 31))
        assert dates == [date(2023, 1, 31), date(2023, 2, 28), date(2023, 3, 31)]

    def test_handles_30_day_months(self, engine):
        schedule = _make_schedule(
            "FREQ=MONTHLY;BYMONTHDAY=-1", start_date=date(2024, 4, 1)
        )
        dates = engine.generate(schedule, date(2024, 4, 1), date(2024, 6, 30))
        assert dates == [date(2024, 4, 30), date(2024, 5, 31), date(2024, 6, 30)]

    def test_year_boundary(self, engine):
        schedule = _make_schedule(
            "FREQ=MONTHLY;BYMONTHDAY=-1", start_date=date(2023, 11, 1)
        )
        dates = engine.generate(schedule, date(2023, 11, 1), date(2024, 2, 29))
        assert dates == [
            date(2023, 11, 30),
            date(2023, 12, 31),
            date(2024, 1, 31),
            date(2024, 2, 29),
        ]


class TestAdvancedRecurrenceEdgeCases:
    """Edge cases for advanced recurrence types."""

    def test_monthly_on_days_empty_list_raises(self, engine):
        """Empty days_of_month produces invalid RRULE — fail at construction."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="Invalid RRULE"):
            RecurrenceRule.model_validate(
                {
                    "frequency": FrequencyType.MONTHLY_ON_DAYS,
                    "start_date": date(2024, 1, 1),
                    "days_of_month": [],
                }
            )

    def test_nth_weekday_missing_day_of_week_raises(self, engine):
        """Missing day_of_week for NTH_WEEKDAY produces invalid RRULE — fail at construction."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="Invalid RRULE"):
            RecurrenceRule.model_validate(
                {
                    "frequency": FrequencyType.NTH_WEEKDAY,
                    "start_date": date(2024, 1, 1),
                    "nth_occurrence": 2,
                }
            )

    def test_with_end_date(self, engine):
        schedule = _make_schedule(
            "FREQ=MONTHLY;BYMONTHDAY=-1", end_date=date(2024, 2, 29)
        )
        dates = engine.generate(schedule, date(2024, 1, 1), date(2024, 12, 31))
        assert dates == [date(2024, 1, 31), date(2024, 2, 29)]
