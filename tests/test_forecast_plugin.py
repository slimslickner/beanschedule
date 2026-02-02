"""Tests for extended forecast plugin."""

from datetime import date
from decimal import Decimal

import pytest
from beancount.core import amount, data
from dateutil import rrule

from beanschedule.plugins.forecast import (
    forecast,
    generate_forecast_dates,
    parse_pattern_from_metadata,
    parse_pattern_from_narration,
)


class TestParsePatternFromNarration:
    """Test narration pattern parsing."""

    def test_parse_monthly_pattern(self):
        """Should parse basic MONTHLY pattern."""
        pattern = parse_pattern_from_narration("Rent Payment [MONTHLY]")

        assert pattern is not None
        assert pattern['pattern_type'] == 'MONTHLY'
        assert pattern['base_narration'] == 'Rent Payment'

    def test_parse_monthly_with_until(self):
        """Should parse MONTHLY with UNTIL condition."""
        pattern = parse_pattern_from_narration("Rent [MONTHLY UNTIL 2024-12-31]")

        assert pattern is not None
        assert pattern['periodicity']['until'] == date(2024, 12, 31)

    def test_parse_monthly_on_days(self):
        """Should parse MONTHLY ON days pattern."""
        pattern = parse_pattern_from_narration("Paycheck [MONTHLY ON 5,20]")

        assert pattern is not None
        assert pattern['pattern_type'] == 'MONTHLY_ON_DAYS'
        assert pattern['days_of_month'] == [5, 20]

    def test_parse_nth_weekday_second_tuesday(self):
        """Should parse 2ND TUE pattern."""
        pattern = parse_pattern_from_narration("Meeting [2ND TUE]")

        assert pattern is not None
        assert pattern['pattern_type'] == 'NTH_WEEKDAY'
        assert pattern['nth_occurrence'] == 2
        assert pattern['day_of_week'] == 1  # TUE

    def test_parse_nth_weekday_last_friday(self):
        """Should parse LAST FRI pattern."""
        pattern = parse_pattern_from_narration("Happy Hour [LAST FRI]")

        assert pattern is not None
        assert pattern['pattern_type'] == 'NTH_WEEKDAY'
        assert pattern['nth_occurrence'] == -1
        assert pattern['day_of_week'] == 4  # FRI

    def test_parse_last_day_of_month(self):
        """Should parse LAST DAY OF MONTH pattern."""
        pattern = parse_pattern_from_narration("CC Payment [LAST DAY OF MONTH]")

        assert pattern is not None
        assert pattern['pattern_type'] == 'LAST_DAY_OF_MONTH'

    def test_parse_interval_pattern(self):
        """Should parse EVERY N MONTHS pattern."""
        pattern = parse_pattern_from_narration("Quarterly [EVERY 3 MONTHS]")

        assert pattern is not None
        assert pattern['pattern_type'] == 'INTERVAL'
        assert pattern['periodicity']['interval'] == 3

    def test_parse_no_pattern(self):
        """Should return None for narration without pattern."""
        pattern = parse_pattern_from_narration("Regular transaction")

        assert pattern is None


class TestParsePatternFromMetadata:
    """Test metadata pattern parsing."""

    def test_parse_monthly_from_metadata(self):
        """Should parse MONTHLY from metadata."""
        txn = data.Transaction(
            meta={
                'schedule-id': 'rent',
                'schedule-frequency': 'MONTHLY',
            },
            date=date(2024, 1, 1),
            flag='#',
            payee='Rent',
            narration='Monthly rent',
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )

        pattern = parse_pattern_from_metadata(txn)

        assert pattern is not None
        assert pattern['pattern_type'] == 'MONTHLY'

    def test_parse_monthly_on_days_from_metadata(self):
        """Should parse MONTHLY_ON_DAYS from metadata."""
        txn = data.Transaction(
            meta={
                'schedule-id': 'paycheck',
                'schedule-frequency': 'MONTHLY_ON_DAYS',
                'schedule-days-of-month': '5,20',
            },
            date=date(2024, 1, 5),
            flag='#',
            payee='Paycheck',
            narration='',
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )

        pattern = parse_pattern_from_metadata(txn)

        assert pattern is not None
        assert pattern['pattern_type'] == 'MONTHLY_ON_DAYS'
        assert pattern['days_of_month'] == [5, 20]

    def test_parse_nth_weekday_from_metadata(self):
        """Should parse NTH_WEEKDAY from metadata."""
        txn = data.Transaction(
            meta={
                'schedule-id': 'meeting',
                'schedule-frequency': 'NTH_WEEKDAY',
                'schedule-nth-occurrence': '2',
                'schedule-day-of-week': 'TUE',
            },
            date=date(2024, 1, 9),
            flag='#',
            payee='Meeting',
            narration='',
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )

        pattern = parse_pattern_from_metadata(txn)

        assert pattern is not None
        assert pattern['pattern_type'] == 'NTH_WEEKDAY'
        assert pattern['nth_occurrence'] == 2
        assert pattern['day_of_week'] == 1  # TUE

    def test_parse_with_until_from_metadata(self):
        """Should parse end date from metadata."""
        txn = data.Transaction(
            meta={
                'schedule-id': 'limited',
                'schedule-frequency': 'MONTHLY',
                'schedule-until': '2024-06-30',
            },
            date=date(2024, 1, 1),
            flag='#',
            payee='Limited',
            narration='',
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )

        pattern = parse_pattern_from_metadata(txn)

        assert pattern is not None
        assert pattern['periodicity']['until'] == date(2024, 6, 30)

    def test_parse_no_metadata(self):
        """Should return None when no schedule metadata present."""
        txn = data.Transaction(
            meta={},
            date=date(2024, 1, 1),
            flag='*',
            payee='Regular',
            narration='',
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )

        pattern = parse_pattern_from_metadata(txn)

        assert pattern is None


class TestGenerateForecastDates:
    """Test forecast date generation."""

    def test_generate_monthly_dates(self):
        """Should generate monthly dates."""
        txn = data.Transaction(
            meta={},
            date=date(2024, 1, 1),
            flag='#',
            payee='',
            narration='',
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )

        pattern = {
            'pattern_type': 'MONTHLY',
            'base_narration': 'Test',
            'interval': rrule.MONTHLY,
            'periodicity': {'until': date(2024, 4, 30)},
        }

        dates = generate_forecast_dates(txn, pattern)

        assert len(dates) == 4
        assert dates[0] == date(2024, 1, 1)
        assert dates[1] == date(2024, 2, 1)
        assert dates[2] == date(2024, 3, 1)
        assert dates[3] == date(2024, 4, 1)

    def test_generate_monthly_on_days(self):
        """Should generate dates on multiple days per month."""
        txn = data.Transaction(
            meta={},
            date=date(2024, 1, 5),
            flag='#',
            payee='',
            narration='',
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )

        pattern = {
            'pattern_type': 'MONTHLY_ON_DAYS',
            'base_narration': 'Paycheck',
            'interval': rrule.MONTHLY,
            'periodicity': {'until': date(2024, 3, 31)},
            'days_of_month': [5, 20],
        }

        dates = generate_forecast_dates(txn, pattern)

        # Should have 5th and 20th of Jan, Feb, Mar
        assert len(dates) == 6
        assert date(2024, 1, 5) in dates
        assert date(2024, 1, 20) in dates
        assert date(2024, 2, 5) in dates
        assert date(2024, 2, 20) in dates
        assert date(2024, 3, 5) in dates
        assert date(2024, 3, 20) in dates

    def test_generate_nth_weekday(self):
        """Should generate nth weekday of each month."""
        txn = data.Transaction(
            meta={},
            date=date(2024, 1, 9),
            flag='#',
            payee='',
            narration='',
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )

        pattern = {
            'pattern_type': 'NTH_WEEKDAY',
            'base_narration': 'Meeting',
            'interval': rrule.MONTHLY,
            'periodicity': {'until': date(2024, 4, 30)},
            'nth_occurrence': 2,
            'day_of_week': 1,  # TUE
        }

        dates = generate_forecast_dates(txn, pattern)

        # Should have 2nd Tuesday of Jan, Feb, Mar, Apr
        assert len(dates) == 4
        assert dates[0] == date(2024, 1, 9)
        assert dates[1] == date(2024, 2, 13)
        assert dates[2] == date(2024, 3, 12)
        assert dates[3] == date(2024, 4, 9)

    def test_generate_last_day_of_month(self):
        """Should generate last day of each month."""
        txn = data.Transaction(
            meta={},
            date=date(2024, 1, 31),
            flag='#',
            payee='',
            narration='',
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )

        pattern = {
            'pattern_type': 'LAST_DAY_OF_MONTH',
            'base_narration': 'Payment',
            'interval': rrule.MONTHLY,
            'periodicity': {'until': date(2024, 4, 30)},
        }

        dates = generate_forecast_dates(txn, pattern)

        # Should have last day of Jan (31), Feb (29 - leap year), Mar (31), Apr (30)
        assert len(dates) == 4
        assert dates[0] == date(2024, 1, 31)
        assert dates[1] == date(2024, 2, 29)  # Leap year
        assert dates[2] == date(2024, 3, 31)
        assert dates[3] == date(2024, 4, 30)


class TestForecastPlugin:
    """Test complete forecast plugin."""

    def test_forecast_basic_monthly(self):
        """Should generate monthly forecast transactions."""
        entries = [
            data.Transaction(
                meta={'lineno': 1, 'filename': 'test.bean'},
                date=date(2024, 1, 1),
                flag='#',
                payee='Rent',
                narration='Monthly rent [MONTHLY UNTIL 2024-03-31]',
                tags=frozenset(),
                links=frozenset(),
                postings=[
                    data.Posting(
                        account='Expenses:Rent',
                        units=amount.Amount(Decimal('1500.00'), 'USD'),
                        cost=None,
                        price=None,
                        flag=None,
                        meta={},
                    ),
                ],
            ),
        ]

        new_entries, errors = forecast(entries, {})

        # Original forecast transaction is filtered out, 3 new ones created
        assert len(errors) == 0
        forecast_txns = [e for e in new_entries if isinstance(e, data.Transaction)]
        assert len(forecast_txns) == 3
        assert forecast_txns[0].date == date(2024, 1, 1)
        assert forecast_txns[1].date == date(2024, 2, 1)
        assert forecast_txns[2].date == date(2024, 3, 1)

    def test_forecast_monthly_on_days_from_metadata(self):
        """Should generate forecast for MONTHLY_ON_DAYS from metadata."""
        entries = [
            data.Transaction(
                meta={
                    'lineno': 1,
                    'filename': 'test.bean',
                    'schedule-id': 'paycheck',
                    'schedule-frequency': 'MONTHLY_ON_DAYS',
                    'schedule-days-of-month': '5,20',
                    'schedule-until': '2024-02-29',
                },
                date=date(2024, 1, 5),
                flag='#',
                payee='Paycheck',
                narration='Semi-monthly pay',
                tags=frozenset(),
                links=frozenset(),
                postings=[],
            ),
        ]

        new_entries, errors = forecast(entries, {})

        assert len(errors) == 0
        forecast_txns = [e for e in new_entries if isinstance(e, data.Transaction)]
        # Jan 5, Jan 20, Feb 5, Feb 20
        assert len(forecast_txns) == 4

    def test_forecast_keeps_non_forecast_entries(self):
        """Should keep non-forecast entries unchanged."""
        entries = [
            data.Transaction(
                meta={'lineno': 1, 'filename': 'test.bean'},
                date=date(2024, 1, 1),
                flag='*',
                payee='Regular',
                narration='Normal transaction',
                tags=frozenset(),
                links=frozenset(),
                postings=[],
            ),
            data.Transaction(
                meta={'lineno': 2, 'filename': 'test.bean'},
                date=date(2024, 1, 5),
                flag='#',
                payee='Forecast',
                narration='Forecast [MONTHLY UNTIL 2024-01-31]',
                tags=frozenset(),
                links=frozenset(),
                postings=[],
            ),
        ]

        new_entries, errors = forecast(entries, {})

        assert len(errors) == 0
        # 1 regular transaction + 1 forecast instance
        assert len(new_entries) == 2

        regular_txns = [e for e in new_entries if e.flag == '*']
        assert len(regular_txns) == 1

    def test_forecast_invalid_pattern_kept(self):
        """Should keep forecast transactions with invalid patterns."""
        entries = [
            data.Transaction(
                meta={'lineno': 1, 'filename': 'test.bean'},
                date=date(2024, 1, 1),
                flag='#',
                payee='Invalid',
                narration='No pattern here',
                tags=frozenset(),
                links=frozenset(),
                postings=[],
            ),
        ]

        new_entries, errors = forecast(entries, {})

        assert len(errors) == 0
        # Original kept as-is
        assert len(new_entries) == 1
        assert new_entries[0].narration == 'No pattern here'
