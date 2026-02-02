"""Integration tests for hook with forecast transactions."""

from datetime import date
from decimal import Decimal

import pytest
from beancount.core import amount, data

from beanschedule.hook import schedule_hook


@pytest.fixture
def forecast_transaction_rent():
    """Forecast transaction for monthly rent."""
    return data.Transaction(
        meta={
            "schedule-id": "rent-monthly",
            "schedule-frequency": "MONTHLY",
            "schedule-day-of-month": "1",
            "schedule-payee-pattern": ".*LANDLORD.*|.*PROPERTY.*",
            "schedule-match-account": "Assets:Checking",
            "schedule-amount-tolerance": "0.00",
            "schedule-date-window-days": "3",
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
def imported_rent_transaction():
    """Imported transaction that matches rent forecast."""
    return data.Transaction(
        meta={"filename": "import.csv", "lineno": 1},
        date=date(2024, 1, 1),
        flag="*",
        payee="PROPERTY MANAGEMENT",
        narration="",
        tags=frozenset(),
        links=frozenset(),
        postings=[
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


class TestForecastTransactionLoading:
    """Tests for loading schedules from forecast transactions."""

    def test_hook_loads_forecast_transactions(
        self, forecast_transaction_rent, imported_rent_transaction
    ):
        """Should load schedules from forecast transactions in existing_entries."""
        # Setup
        existing_entries = [forecast_transaction_rent]
        extracted_entries_list = [
            ("import.csv", [imported_rent_transaction], "Assets:Checking", None)
        ]

        # Execute
        result = schedule_hook(extracted_entries_list, existing_entries)

        # Verify
        assert result is not None
        assert len(result) == 1

        # Check that transaction was enriched
        _, entries, _, _ = result[0]
        assert len(entries) == 1
        enriched_txn = entries[0]

        # Should have schedule metadata
        assert "schedule_id" in enriched_txn.meta
        assert enriched_txn.meta["schedule_id"] == "rent-monthly"
        assert float(enriched_txn.meta["schedule_confidence"]) > 0.8

        # Should have correct payee and narration from forecast
        assert enriched_txn.payee == "Rent Payment"
        assert enriched_txn.narration == "Monthly rent"

        # Should have tags from forecast
        assert "rent" in enriched_txn.tags

        # Should have full postings from forecast template
        assert len(enriched_txn.postings) == 2
        assert enriched_txn.postings[0].account == "Expenses:Housing:Rent"
        assert enriched_txn.postings[0].units.number == Decimal("1500.00")

    def test_hook_prioritizes_forecast_over_yaml(
        self, forecast_transaction_rent, imported_rent_transaction, tmp_path, monkeypatch
    ):
        """Should prioritize forecast transactions over YAML schedules."""
        # Create a YAML file with different schedule
        yaml_file = tmp_path / "schedules.yaml"
        yaml_file.write_text(
            """
version: "1.0"
schedules:
  - id: other-schedule
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: ".*OTHER.*"
      amount: -100.00
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    transaction:
      payee: "Other Payment"
      narration: "Other"
      metadata:
        schedule_id: other-schedule
      postings:
        - account: Expenses:Other
          amount: 100.00
        - account: Assets:Checking
"""
        )

        # Set environment to use YAML file
        monkeypatch.setenv("BEANSCHEDULE_FILE", str(yaml_file))

        # Setup with forecast transaction (should take priority)
        existing_entries = [forecast_transaction_rent]
        extracted_entries_list = [
            ("import.csv", [imported_rent_transaction], "Assets:Checking", None)
        ]

        # Execute
        result = schedule_hook(extracted_entries_list, existing_entries)

        # Verify - should match forecast, not YAML
        _, entries, _, _ = result[0]
        enriched_txn = entries[0]
        assert enriched_txn.meta["schedule_id"] == "rent-monthly"  # From forecast
        assert enriched_txn.payee == "Rent Payment"  # From forecast

    def test_hook_falls_back_to_yaml_if_no_forecast(
        self, imported_rent_transaction, tmp_path, monkeypatch
    ):
        """Should fall back to YAML if no forecast transactions found."""
        # Create a YAML file
        yaml_file = tmp_path / "schedules.yaml"
        yaml_file.write_text(
            """
version: "1.0"
schedules:
  - id: rent-yaml
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: ".*PROPERTY.*"
      amount: -1500.00
      amount_tolerance: 0.00
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    transaction:
      payee: "Rent from YAML"
      narration: "Monthly rent"
      metadata:
        schedule_id: rent-yaml
      postings:
        - account: Expenses:Housing:Rent
          amount: 1500.00
        - account: Assets:Checking
"""
        )

        # Set environment to use YAML file
        monkeypatch.setenv("BEANSCHEDULE_FILE", str(yaml_file))

        # Setup with NO forecast transactions
        existing_entries = []
        extracted_entries_list = [
            ("import.csv", [imported_rent_transaction], "Assets:Checking", None)
        ]

        # Execute
        result = schedule_hook(extracted_entries_list, existing_entries)

        # Verify - should match YAML
        _, entries, _, _ = result[0]
        enriched_txn = entries[0]
        assert enriched_txn.meta["schedule_id"] == "rent-yaml"  # From YAML
        assert enriched_txn.payee == "Rent from YAML"  # From YAML

    def test_hook_with_multiple_forecast_transactions(self, imported_rent_transaction):
        """Should handle multiple forecast transactions."""
        # Create two forecast transactions
        forecast_rent = data.Transaction(
            meta={
                "schedule-id": "rent",
                "schedule-frequency": "MONTHLY",
                "schedule-day-of-month": "1",
                "schedule-payee-pattern": ".*PROPERTY.*",
                "schedule-match-account": "Assets:Checking",
                "filename": "Forecast.bean",
                "lineno": 10,
            },
            date=date(2024, 1, 1),
            flag="#",
            payee="Rent",
            narration="",
            tags=frozenset(),
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

        forecast_electric = data.Transaction(
            meta={
                "schedule-id": "electric",
                "schedule-frequency": "MONTHLY",
                "schedule-day-of-month": "5",
                "schedule-payee-pattern": ".*ELECTRIC.*",
                "schedule-match-account": "Assets:Checking",
                "filename": "Forecast.bean",
                "lineno": 20,
            },
            date=date(2024, 1, 5),
            flag="#",
            payee="Electric Company",
            narration="",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(
                    account="Expenses:Utilities:Electric",
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

        existing_entries = [forecast_rent, forecast_electric]
        extracted_entries_list = [
            ("import.csv", [imported_rent_transaction], "Assets:Checking", None)
        ]

        # Execute
        result = schedule_hook(extracted_entries_list, existing_entries)

        # Verify - should match rent (not electric)
        _, entries, _, _ = result[0]
        enriched_txn = entries[0]
        assert enriched_txn.meta["schedule_id"] == "rent"

    def test_hook_ignores_regular_transactions_in_existing_entries(
        self, forecast_transaction_rent, imported_rent_transaction
    ):
        """Should ignore regular transactions when loading forecast schedules."""
        # Mix forecast and regular transactions
        regular_txn = data.Transaction(
            meta={"filename": "main.beancount", "lineno": 100},
            date=date(2024, 1, 15),
            flag="*",  # Not a forecast
            payee="Store",
            narration="Purchase",
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )

        existing_entries = [forecast_transaction_rent, regular_txn]
        extracted_entries_list = [
            ("import.csv", [imported_rent_transaction], "Assets:Checking", None)
        ]

        # Execute
        result = schedule_hook(extracted_entries_list, existing_entries)

        # Verify - should still match forecast
        _, entries, _, _ = result[0]
        enriched_txn = entries[0]
        assert enriched_txn.meta["schedule_id"] == "rent-monthly"
