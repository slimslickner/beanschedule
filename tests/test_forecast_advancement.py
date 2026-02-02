"""Tests for forecast_advancement module."""

from datetime import date
from decimal import Decimal

import pytest
from beancount.core import amount, data

from beanschedule.forecast_advancement import (
    advance_forecast_transaction,
    calculate_next_occurrence,
)
from beanschedule.schema import (
    MatchCriteria,
    MissingTransactionConfig,
    Posting,
    RecurrenceRule,
    Schedule,
    TransactionTemplate,
)
from beanschedule.types import FrequencyType


@pytest.fixture
def monthly_schedule():
    """Create a simple monthly schedule."""
    return Schedule(
        id="test-monthly",
        enabled=True,
        match=MatchCriteria(
            account="Assets:Checking",
            payee_pattern=".*TEST.*",
        ),
        recurrence=RecurrenceRule(
            frequency=FrequencyType.MONTHLY,
            start_date=date(2024, 1, 1),
            day_of_month=1,
        ),
        transaction=TransactionTemplate(
            payee="Test Payee",
            narration="Test",
            metadata={"schedule_id": "test-monthly"},
            postings=[
                Posting(account="Expenses:Test", amount=Decimal("100.00")),
                Posting(account="Assets:Checking"),
            ],
        ),
        missing_transaction=MissingTransactionConfig(),
    )


@pytest.fixture
def forecast_transaction():
    """Create a forecast transaction."""
    return data.Transaction(
        meta={
            "schedule-id": "test-monthly",
            "schedule-frequency": "MONTHLY",
            "schedule-day-of-month": "1",
            "filename": "Forecast.bean",
            "lineno": 10,
        },
        date=date(2024, 1, 1),
        flag="#",
        payee="Test Payee",
        narration="Test",
        tags=frozenset(),
        links=frozenset(),
        postings=[
            data.Posting(
                account="Expenses:Test",
                units=amount.Amount(Decimal("100.00"), "USD"),
                cost=None,
                price=None,
                flag=None,
                meta={},
            ),
            data.Posting(
                account="Assets:Checking",
                units=amount.Amount(Decimal("-100.00"), "USD"),
                cost=None,
                price=None,
                flag=None,
                meta={},
            ),
        ],
    )


class TestCalculateNextOccurrence:
    """Tests for calculating next occurrence."""

    def test_monthly_next_occurrence(self, monthly_schedule):
        """Should calculate next monthly occurrence."""
        next_date = calculate_next_occurrence(monthly_schedule, date(2024, 1, 15))
        assert next_date == date(2024, 2, 1)

    def test_next_occurrence_at_boundary(self, monthly_schedule):
        """Should calculate next occurrence when at exact date."""
        next_date = calculate_next_occurrence(monthly_schedule, date(2024, 1, 1))
        assert next_date == date(2024, 2, 1)

    def test_next_occurrence_with_end_date(self, monthly_schedule):
        """Should respect schedule end_date."""
        monthly_schedule.recurrence.end_date = date(2024, 3, 1)

        # Should find Feb
        next_date = calculate_next_occurrence(monthly_schedule, date(2024, 1, 15))
        assert next_date == date(2024, 2, 1)

        # Should find Mar (last one)
        next_date = calculate_next_occurrence(monthly_schedule, date(2024, 2, 15))
        assert next_date == date(2024, 3, 1)

        # Should return None (no more occurrences)
        next_date = calculate_next_occurrence(monthly_schedule, date(2024, 3, 15))
        assert next_date is None

    def test_weekly_next_occurrence(self):
        """Should calculate next weekly occurrence."""
        from beanschedule.types import DayOfWeek

        schedule = Schedule(
            id="test-weekly",
            enabled=True,
            match=MatchCriteria(account="Assets:Checking", payee_pattern=".*"),
            recurrence=RecurrenceRule(
                frequency=FrequencyType.WEEKLY,
                start_date=date(2024, 1, 1),  # Monday
                day_of_week=DayOfWeek.MON,
            ),
            transaction=TransactionTemplate(
                payee="Test",
                narration="",
                metadata={"schedule_id": "test-weekly"},
            ),
            missing_transaction=MissingTransactionConfig(),
        )

        # 2024-01-01 is Monday, next Monday is 2024-01-08
        next_date = calculate_next_occurrence(schedule, date(2024, 1, 3))
        assert next_date == date(2024, 1, 8)


class TestAdvanceForecastTransaction:
    """Tests for advancing forecast transactions."""

    def test_advance_transaction_date(self, forecast_transaction):
        """Should create new transaction with advanced date."""
        new_date = date(2024, 2, 1)
        updated_txn = advance_forecast_transaction(forecast_transaction, new_date)

        assert updated_txn.date == new_date
        assert updated_txn.flag == "#"
        assert updated_txn.payee == forecast_transaction.payee
        assert updated_txn.narration == forecast_transaction.narration
        assert len(updated_txn.postings) == len(forecast_transaction.postings)
        assert updated_txn.meta["schedule-id"] == "test-monthly"

    def test_advance_preserves_metadata(self, forecast_transaction):
        """Should preserve all metadata when advancing."""
        updated_txn = advance_forecast_transaction(forecast_transaction, date(2024, 2, 1))

        assert updated_txn.meta["schedule-id"] == forecast_transaction.meta["schedule-id"]
        assert updated_txn.meta["schedule-frequency"] == forecast_transaction.meta[
            "schedule-frequency"
        ]

    def test_advance_preserves_postings(self, forecast_transaction):
        """Should preserve postings when advancing."""
        updated_txn = advance_forecast_transaction(forecast_transaction, date(2024, 2, 1))

        assert len(updated_txn.postings) == 2
        assert updated_txn.postings[0].account == "Expenses:Test"
        assert updated_txn.postings[0].units == amount.Amount(Decimal("100.00"), "USD")
        assert updated_txn.postings[1].account == "Assets:Checking"


class TestAdvanceForecastsCLI:
    """Integration tests for advance-forecasts CLI command."""

    def test_advance_forecasts_from_ledger(self, tmp_path):
        """Should advance forecasts by querying ledger for matched transactions."""
        from click.testing import CliRunner

        from beanschedule.cli import main

        # Create forecast file with a forecast transaction
        forecast_file = tmp_path / "Forecast.bean"
        forecast_file.write_text(
            """
2024-01-01 # "Rent" "Monthly rent [MONTHLY]"
  schedule-id: "rent-monthly"
  schedule-frequency: "MONTHLY"
  schedule-day-of-month: "1"
  schedule-match-account: "Assets:Checking"
  schedule-payee-pattern: ".*LANDLORD.*"
  Expenses:Housing:Rent       1500.00 USD
  Assets:Checking            -1500.00 USD
"""
        )

        # Create main ledger that includes forecast and has a matched transaction
        ledger_file = tmp_path / "main.beancount"
        ledger_file.write_text(
            f"""
plugin "beancount.plugins.auto_accounts"

include "{forecast_file}"

2024-01-03 * "LANDLORD PROPERTY MGR" "Rent payment"
  schedule_id: "rent-monthly"
  schedule_matched_date: 2024-01-01
  schedule_confidence: 0.95
  Assets:Checking            -1500.00 USD
  Expenses:Housing:Rent       1500.00 USD
"""
        )

        # Run advance-forecasts command
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["advance-forecasts", str(ledger_file), "--forecast-file", str(forecast_file)],
        )

        assert result.exit_code == 0
        assert "Found 1 schedule(s) with matched transactions" in result.output
        assert "rent-monthly: 2024-01-01 -> 2024-02-01" in result.output
        assert "Updated 1 forecast(s)" in result.output

        # Verify forecast file was updated
        updated_content = forecast_file.read_text()
        assert "2024-02-01 #" in updated_content  # Date should be advanced to Feb 1
        assert "schedule-id: \"rent-monthly\"" in updated_content

    def test_advance_forecasts_dry_run(self, tmp_path):
        """Should preview changes without writing when --dry-run is used."""
        from click.testing import CliRunner

        from beanschedule.cli import main

        forecast_file = tmp_path / "Forecast.bean"
        forecast_file.write_text(
            """
2024-01-01 # "Rent" "Monthly rent"
  schedule-id: "rent-monthly"
  schedule-frequency: "MONTHLY"
  schedule-day-of-month: "1"
  schedule-match-account: "Assets:Checking"
  Expenses:Housing:Rent       1500.00 USD
  Assets:Checking            -1500.00 USD
"""
        )

        ledger_file = tmp_path / "main.beancount"
        ledger_file.write_text(
            f"""
include "{forecast_file}"

2024-01-03 * "LANDLORD" ""
  schedule_id: "rent-monthly"
  Assets:Checking            -1500.00 USD
  Expenses:Housing:Rent       1500.00 USD
"""
        )

        original_content = forecast_file.read_text()

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "advance-forecasts",
                str(ledger_file),
                "--forecast-file",
                str(forecast_file),
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        assert "Dry-run mode: would update 1 forecast(s)" in result.output

        # Verify file was NOT modified
        assert forecast_file.read_text() == original_content

    def test_advance_forecasts_no_matches(self, tmp_path):
        """Should report when no matched transactions are found."""
        from click.testing import CliRunner

        from beanschedule.cli import main

        forecast_file = tmp_path / "Forecast.bean"
        forecast_file.write_text(
            """
2024-01-01 # "Rent" "Monthly rent"
  schedule-id: "rent-monthly"
  schedule-frequency: "MONTHLY"
  schedule-day-of-month: "1"
  schedule-match-account: "Assets:Checking"
  Expenses:Housing:Rent       1500.00 USD
  Assets:Checking            -1500.00 USD
"""
        )

        ledger_file = tmp_path / "main.beancount"
        ledger_file.write_text(
            f"""
include "{forecast_file}"

; No matched transactions
2024-01-03 * "Some other transaction" ""
  Assets:Checking            -100.00 USD
  Expenses:Other              100.00 USD
"""
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["advance-forecasts", str(ledger_file), "--forecast-file", str(forecast_file)],
        )

        assert result.exit_code == 0
        assert "No matched forecasts found in ledger" in result.output

    def test_advance_forecasts_multiple_schedules(self, tmp_path):
        """Should advance multiple schedules independently."""
        from click.testing import CliRunner

        from beanschedule.cli import main

        forecast_file = tmp_path / "Forecast.bean"
        forecast_file.write_text(
            """
2024-01-01 # "Rent" "Monthly rent"
  schedule-id: "rent-monthly"
  schedule-frequency: "MONTHLY"
  schedule-day-of-month: "1"
  schedule-match-account: "Assets:Checking"
  Expenses:Housing:Rent       1500.00 USD
  Assets:Checking            -1500.00 USD

2024-01-05 # "Electric" "Utility bill"
  schedule-id: "electric-monthly"
  schedule-frequency: "MONTHLY"
  schedule-day-of-month: "5"
  schedule-match-account: "Assets:Checking"
  Expenses:Utilities:Electric  150.00 USD
  Assets:Checking             -150.00 USD
"""
        )

        ledger_file = tmp_path / "main.beancount"
        ledger_file.write_text(
            f"""
include "{forecast_file}"

2024-01-03 * "LANDLORD" ""
  schedule_id: "rent-monthly"
  Assets:Checking            -1500.00 USD
  Expenses:Housing:Rent       1500.00 USD

2024-01-07 * "ELECTRIC CO" ""
  schedule_id: "electric-monthly"
  Assets:Checking            -150.00 USD
  Expenses:Utilities:Electric  150.00 USD
"""
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["advance-forecasts", str(ledger_file), "--forecast-file", str(forecast_file)],
        )

        assert result.exit_code == 0
        assert "Found 2 schedule(s) with matched transactions" in result.output
        assert "rent-monthly: 2024-01-01 -> 2024-02-01" in result.output
        assert "electric-monthly: 2024-01-05 -> 2024-02-05" in result.output
        assert "Updated 2 forecast(s)" in result.output

        # Verify both were advanced
        updated_content = forecast_file.read_text()
        assert "2024-02-01 #" in updated_content
        assert "2024-02-05 #" in updated_content

    def test_advance_forecasts_ignores_forecast_generated_transactions(self, tmp_path):
        """Should ignore forecast-generated transactions (# flag) when finding matches."""
        from click.testing import CliRunner

        from beanschedule.cli import main

        forecast_file = tmp_path / "Forecast.bean"
        forecast_file.write_text(
            """
2026-01-01 # "Rent" "Monthly rent"
  schedule-id: "rent-monthly"
  schedule-frequency: "MONTHLY"
  schedule-match-account: "Assets:Checking"
  schedule-day-of-month: "1"
  Expenses:Housing:Rent       1500.00 USD
  Assets:Checking            -1500.00 USD
"""
        )

        ledger_file = tmp_path / "main.beancount"
        ledger_file.write_text(
            f"""
plugin "beancount.plugins.auto_accounts"

include "{forecast_file}"

; Real matched transaction (should be used for advancement)
2026-01-03 * "LANDLORD" "Rent payment"
  schedule_id: "rent-monthly"
  Assets:Checking            -1500.00 USD
  Expenses:Housing:Rent       1500.00 USD

; Forecast-generated transactions (should be IGNORED - have # flag)
; These would be generated by the forecast plugin
2026-02-01 # "Rent" "Monthly rent"
  schedule_id: "rent-monthly"
  Assets:Checking            -1500.00 USD
  Expenses:Housing:Rent       1500.00 USD

2026-03-01 # "Rent" "Monthly rent"
  schedule_id: "rent-monthly"
  Assets:Checking            -1500.00 USD
  Expenses:Housing:Rent       1500.00 USD
"""
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["advance-forecasts", str(ledger_file), "--forecast-file", str(forecast_file)],
        )

        assert result.exit_code == 0
        assert "Found 1 schedule(s) with matched transactions" in result.output
        # Should advance based on the real match (Jan 3), not the forecast-generated ones
        # Next occurrence after Jan 3 is Feb 1
        assert "rent-monthly: 2026-01-01 -> 2026-02-01" in result.output

        # Verify forecast was advanced to Feb 1 (not Mar 1 or later)
        updated_content = forecast_file.read_text()
        assert "2026-02-01 #" in updated_content
