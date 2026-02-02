"""Tests for forecast_loader module."""

from datetime import date
from decimal import Decimal

import pytest
from beancount.core import amount, data

from beanschedule.forecast_loader import (
    is_forecast_transaction,
    load_forecast_schedules,
    parse_forecast_transaction,
)
from beanschedule.types import FrequencyType


@pytest.fixture
def simple_forecast_transaction():
    """Create a simple monthly forecast transaction."""
    return data.Transaction(
        meta={
            "schedule-id": "rent-monthly",
            "schedule-frequency": "MONTHLY",
            "schedule-payee-pattern": ".*LANDLORD.*",
            "schedule-match-account": "Assets:Checking",
            "filename": "Forecast.bean",
            "lineno": 10,
        },
        date=date(2024, 1, 1),
        flag="#",
        payee="Rent Payment",
        narration="Monthly rent",
        tags=frozenset(["rent"]),
        links=frozenset(),
        postings=[
            data.Posting(
                account="Expenses:Housing:Rent",
                units=amount.Amount(Decimal("1500.00"), "USD"),
                cost=None,
                price=None,
                flag=None,
                meta={},
            ),
            data.Posting(
                account="Assets:Checking",
                units=amount.Amount(Decimal("-1500.00"), "USD"),
                cost=None,
                price=None,
                flag=None,
                meta={},
            ),
        ],
    )


@pytest.fixture
def complex_forecast_transaction():
    """Create a forecast transaction with all optional fields."""
    return data.Transaction(
        meta={
            "schedule-id": "electric-monthly",
            "schedule-frequency": "MONTHLY",
            "schedule-payee-pattern": ".*Electric.*",
            "schedule-match-account": "Assets:Checking",
            "schedule-amount": "45.00",
            "schedule-amount-tolerance": "5.00",
            "schedule-date-window-days": "5",
            "schedule-until": "2024-12-31",
            "schedule-enabled": "true",
            "schedule-placeholder-flag": "!",
            "schedule-placeholder-narration-prefix": "[MISSING]",
            "filename": "Forecast.bean",
            "lineno": 20,
        },
        date=date(2024, 3, 5),
        flag="#",
        payee="Electricity Company",
        narration="Monthly bill",
        tags=frozenset(["utilities"]),
        links=frozenset(),
        postings=[
            data.Posting(
                account="Expenses:Utilities:Electric",
                units=amount.Amount(Decimal("45.00"), "USD"),
                cost=None,
                price=None,
                flag=None,
                meta={},
            ),
            data.Posting(
                account="Assets:Checking",
                units=amount.Amount(Decimal("-45.00"), "USD"),
                cost=None,
                price=None,
                flag=None,
                meta={},
            ),
        ],
    )


@pytest.fixture
def regular_transaction():
    """Create a regular (non-forecast) transaction."""
    return data.Transaction(
        meta={"filename": "main.beancount", "lineno": 100},
        date=date(2024, 1, 15),
        flag="*",
        payee="Store",
        narration="Purchase",
        tags=frozenset(),
        links=frozenset(),
        postings=[
            data.Posting(
                account="Expenses:Shopping",
                units=amount.Amount(Decimal("50.00"), "USD"),
                cost=None,
                price=None,
                flag=None,
                meta={},
            ),
            data.Posting(
                account="Assets:Checking",
                units=amount.Amount(Decimal("-50.00"), "USD"),
                cost=None,
                price=None,
                flag=None,
                meta={},
            ),
        ],
    )


class TestIsForecastTransaction:
    """Tests for is_forecast_transaction function."""

    def test_identifies_forecast_transaction(self, simple_forecast_transaction):
        """Should identify transaction with # flag and schedule-id."""
        assert is_forecast_transaction(simple_forecast_transaction) is True

    def test_rejects_regular_transaction(self, regular_transaction):
        """Should reject transaction without # flag."""
        assert is_forecast_transaction(regular_transaction) is False

    def test_rejects_transaction_without_schedule_id(self):
        """Should reject # transaction without schedule-id metadata."""
        txn = data.Transaction(
            meta={},
            date=date(2024, 1, 1),
            flag="#",
            payee="Test",
            narration="",
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )
        assert is_forecast_transaction(txn) is False

    def test_rejects_non_transaction_directive(self):
        """Should reject non-Transaction directives."""
        directive = data.Balance(
            meta={},
            date=date(2024, 1, 1),
            account="Assets:Checking",
            amount=amount.Amount(Decimal("1000.00"), "USD"),
            tolerance=None,
            diff_amount=None,
        )
        assert is_forecast_transaction(directive) is False


class TestParseForecastTransaction:
    """Tests for parse_forecast_transaction function."""

    def test_parse_simple_forecast(self, simple_forecast_transaction):
        """Should parse basic forecast transaction."""
        schedule = parse_forecast_transaction(simple_forecast_transaction)

        assert schedule is not None
        assert schedule.id == "rent-monthly"
        assert schedule.enabled is True

        # Check match criteria
        assert schedule.match.account == "Assets:Checking"
        assert schedule.match.payee_pattern == ".*LANDLORD.*"
        assert schedule.match.date_window_days == 3  # default

        # Check recurrence
        assert schedule.recurrence.frequency == FrequencyType.MONTHLY
        assert schedule.recurrence.start_date == date(2024, 1, 1)
        assert schedule.recurrence.end_date is None
        assert schedule.recurrence.interval == 1  # default

        # Check transaction template
        assert schedule.transaction.payee == "Rent Payment"
        assert schedule.transaction.narration == "Monthly rent"
        assert "rent" in schedule.transaction.tags
        assert len(schedule.transaction.postings) == 2
        assert schedule.transaction.postings[0].account == "Expenses:Housing:Rent"
        assert schedule.transaction.postings[0].amount == Decimal("1500.00")

    def test_parse_complex_forecast(self, complex_forecast_transaction):
        """Should parse forecast with all optional fields."""
        schedule = parse_forecast_transaction(complex_forecast_transaction)

        assert schedule is not None
        assert schedule.id == "electric-monthly"

        # Check optional match fields
        assert schedule.match.amount == Decimal("45.00")
        assert schedule.match.amount_tolerance == Decimal("5.00")
        assert schedule.match.date_window_days == 5

        # Check optional recurrence fields
        assert schedule.recurrence.end_date == date(2024, 12, 31)

        # Check missing transaction config
        assert schedule.missing_transaction.flag == "!"
        assert schedule.missing_transaction.narration_prefix == "[MISSING]"

    def test_parse_missing_schedule_id(self, simple_forecast_transaction):
        """Should return None if schedule-id missing."""
        del simple_forecast_transaction.meta["schedule-id"]
        schedule = parse_forecast_transaction(simple_forecast_transaction)
        assert schedule is None

    def test_parse_missing_frequency(self, simple_forecast_transaction):
        """Should return None if schedule-frequency missing."""
        del simple_forecast_transaction.meta["schedule-frequency"]
        schedule = parse_forecast_transaction(simple_forecast_transaction)
        assert schedule is None

    def test_parse_invalid_frequency(self, simple_forecast_transaction):
        """Should return None if frequency is invalid."""
        simple_forecast_transaction.meta["schedule-frequency"] = "INVALID"
        schedule = parse_forecast_transaction(simple_forecast_transaction)
        assert schedule is None

    def test_parse_missing_match_account(self, simple_forecast_transaction):
        """Should return None if schedule-match-account missing."""
        del simple_forecast_transaction.meta["schedule-match-account"]
        schedule = parse_forecast_transaction(simple_forecast_transaction)
        assert schedule is None

    def test_parse_decimal_metadata(self):
        """Should parse decimal metadata correctly."""
        txn = data.Transaction(
            meta={
                "schedule-id": "test",
                "schedule-frequency": "MONTHLY",
                "schedule-match-account": "Assets:Checking",
                "schedule-amount": Decimal("100.50"),  # Already Decimal
                "schedule-amount-tolerance": "5.25",  # String
            },
            date=date(2024, 1, 1),
            flag="#",
            payee="Test",
            narration="",
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )
        schedule = parse_forecast_transaction(txn)

        assert schedule is not None
        assert schedule.match.amount == Decimal("100.50")
        assert schedule.match.amount_tolerance == Decimal("5.25")

    def test_parse_int_list_metadata(self):
        """Should parse comma-separated days list."""
        txn = data.Transaction(
            meta={
                "schedule-id": "bimonthly",
                "schedule-frequency": "BIMONTHLY",
                "schedule-match-account": "Assets:Checking",
                "schedule-days-of-month": "5,20",  # String
            },
            date=date(2024, 1, 1),
            flag="#",
            payee="Test",
            narration="",
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )
        schedule = parse_forecast_transaction(txn)

        assert schedule is not None
        assert schedule.recurrence.days_of_month == [5, 20]

    def test_parse_bool_metadata(self):
        """Should parse boolean metadata."""
        txn = data.Transaction(
            meta={
                "schedule-id": "disabled",
                "schedule-frequency": "MONTHLY",
                "schedule-match-account": "Assets:Checking",
                "schedule-enabled": "false",
            },
            date=date(2024, 1, 1),
            flag="#",
            payee="Test",
            narration="",
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )
        schedule = parse_forecast_transaction(txn)

        assert schedule is not None
        assert schedule.enabled is False


class TestLoadForecastSchedules:
    """Tests for load_forecast_schedules function."""

    def test_load_single_forecast(self, simple_forecast_transaction):
        """Should load single forecast transaction."""
        entries = [simple_forecast_transaction]
        schedule_file = load_forecast_schedules(entries)

        assert schedule_file is not None
        assert schedule_file.version == "2.0"
        assert len(schedule_file.schedules) == 1
        assert schedule_file.schedules[0].id == "rent-monthly"

    def test_load_multiple_forecasts(
        self, simple_forecast_transaction, complex_forecast_transaction
    ):
        """Should load multiple forecast transactions."""
        entries = [simple_forecast_transaction, complex_forecast_transaction]
        schedule_file = load_forecast_schedules(entries)

        assert schedule_file is not None
        assert len(schedule_file.schedules) == 2
        assert schedule_file.schedules[0].id == "rent-monthly"
        assert schedule_file.schedules[1].id == "electric-monthly"

    def test_load_filters_regular_transactions(
        self, simple_forecast_transaction, regular_transaction
    ):
        """Should filter out non-forecast transactions."""
        entries = [simple_forecast_transaction, regular_transaction]
        schedule_file = load_forecast_schedules(entries)

        assert schedule_file is not None
        assert len(schedule_file.schedules) == 1
        assert schedule_file.schedules[0].id == "rent-monthly"

    def test_load_empty_entries(self):
        """Should return None for empty entries list."""
        schedule_file = load_forecast_schedules([])
        assert schedule_file is None

    def test_load_none_entries(self):
        """Should return None for None entries."""
        schedule_file = load_forecast_schedules(None)
        assert schedule_file is None

    def test_load_no_forecast_transactions(self, regular_transaction):
        """Should return None if no forecast transactions found."""
        entries = [regular_transaction]
        schedule_file = load_forecast_schedules(entries)
        assert schedule_file is None

    def test_load_with_invalid_forecast(self, simple_forecast_transaction):
        """Should skip invalid forecast transactions."""
        # Create invalid forecast (missing required field)
        invalid_txn = data.Transaction(
            meta={
                "schedule-id": "invalid",
                # Missing schedule-frequency
                "schedule-match-account": "Assets:Checking",
            },
            date=date(2024, 1, 1),
            flag="#",
            payee="Invalid",
            narration="",
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )

        entries = [simple_forecast_transaction, invalid_txn]
        schedule_file = load_forecast_schedules(entries)

        assert schedule_file is not None
        assert len(schedule_file.schedules) == 1  # Only valid one loaded
        assert schedule_file.schedules[0].id == "rent-monthly"

    def test_load_sets_global_config(self, simple_forecast_transaction):
        """Should set default global config."""
        entries = [simple_forecast_transaction]
        schedule_file = load_forecast_schedules(entries)

        assert schedule_file is not None
        assert schedule_file.config is not None
        assert schedule_file.config.fuzzy_match_threshold == 0.80
        assert schedule_file.config.default_date_window_days == 3
