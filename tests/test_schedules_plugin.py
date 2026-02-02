"""Tests for schedules plugin (YAML-based forecast generation)."""

from datetime import date
from decimal import Decimal

import pytest
from beancount.core import amount, data

from beanschedule.plugins.schedules import schedules


@pytest.fixture
def sample_schedule_yaml(tmp_path):
    """Create a sample YAML schedule file."""
    schedule_yaml = tmp_path / "schedules.yaml"
    schedule_yaml.write_text(
        """
version: "1.0"

config:
  default_currency: USD

schedules:
  - id: rent-monthly
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: ".*LANDLORD.*"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    transaction:
      payee: "Rent Payment"
      narration: "Monthly rent"
      metadata:
        schedule_id: rent-monthly
        category: housing
      tags: [rent, recurring]
      postings:
        - account: Expenses:Housing:Rent
          amount: 1500.00
        - account: Assets:Checking
"""
    )
    return schedule_yaml


@pytest.fixture
def disabled_schedule_yaml(tmp_path):
    """Create YAML with disabled schedule."""
    schedule_yaml = tmp_path / "schedules.yaml"
    schedule_yaml.write_text(
        """
version: "1.0"
schedules:
  - id: disabled-schedule
    enabled: false
    match:
      account: Assets:Checking
      payee_pattern: ".*TEST.*"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    transaction:
      payee: "Test"
      narration: ""
      metadata:
        schedule_id: disabled-schedule
      postings:
        - account: Expenses:Test
          amount: 100.00
        - account: Assets:Checking
"""
    )
    return schedule_yaml


class TestSchedulesPlugin:
    """Tests for schedules plugin."""

    def test_plugin_generates_forecasts_from_yaml(self, sample_schedule_yaml):
        """Should generate forecast transactions from YAML schedules."""
        options_map = {"filename": str(sample_schedule_yaml.parent / "main.bean")}

        # Run plugin with explicit config file
        result_entries, errors = schedules([], options_map, config_file=str(sample_schedule_yaml))

        # Should have generated forecast transactions
        assert len(result_entries) > 0, "Should generate forecast transactions"
        assert len(errors) == 0, "Should not have errors"

        # Check first forecast transaction
        forecast_txn = result_entries[0]
        assert isinstance(forecast_txn, data.Transaction)
        assert forecast_txn.flag == "#", "Should have forecast flag"
        assert forecast_txn.payee == "Rent Payment"
        assert forecast_txn.narration == "Monthly rent"
        assert forecast_txn.meta["schedule_id"] == "rent-monthly"

        # Check metadata
        assert forecast_txn.meta.get("category") == "housing"

        # Check tags
        assert "rent" in forecast_txn.tags
        assert "recurring" in forecast_txn.tags

        # Check postings
        assert len(forecast_txn.postings) == 2
        assert forecast_txn.postings[0].account == "Expenses:Housing:Rent"
        assert forecast_txn.postings[0].units == amount.Amount(Decimal("1500.00"), "USD")
        assert forecast_txn.postings[1].account == "Assets:Checking"
        # Balancing posting should be calculated (negative of the first posting)
        assert forecast_txn.postings[1].units == amount.Amount(Decimal("-1500.00"), "USD")

    def test_plugin_skips_disabled_schedules(self, disabled_schedule_yaml):
        """Should not generate forecasts for disabled schedules."""
        options_map = {"filename": str(disabled_schedule_yaml.parent / "main.bean")}

        result_entries, errors = schedules([], options_map, config_file=str(disabled_schedule_yaml))

        # Should not generate any forecasts
        assert len(result_entries) == 0, "Should not generate forecasts for disabled schedules"
        assert len(errors) == 0

    def test_plugin_handles_missing_yaml(self, tmp_path):
        """Should handle missing YAML file gracefully."""
        options_map = {"filename": str(tmp_path / "main.bean")}

        result_entries, errors = schedules(
            [], options_map, config_file=str(tmp_path / "nonexistent.yaml")
        )

        # Should return original entries unchanged
        assert len(result_entries) == 0
        # Should have error
        assert len(errors) > 0
        assert "not found" in errors[0].lower()

    def test_plugin_auto_discovers_schedules(self, sample_schedule_yaml, monkeypatch):
        """Should auto-discover schedules.yaml when no config_file provided."""
        from beanschedule import loader

        # Mock find_schedules_location to return our test file
        monkeypatch.setattr(
            loader, "find_schedules_location", lambda: ("file", sample_schedule_yaml)
        )

        options_map = {"filename": str(sample_schedule_yaml.parent / "main.bean")}

        # Run plugin without config_file (should auto-discover)
        result_entries, errors = schedules([], options_map)

        # Should have generated forecasts
        assert len(result_entries) > 0
        assert len(errors) == 0

    def test_plugin_preserves_existing_entries(self, sample_schedule_yaml):
        """Should preserve existing ledger entries."""
        # Create some existing entries
        existing_txn = data.Transaction(
            meta={"filename": "main.bean", "lineno": 1},
            date=date(2024, 1, 5),
            flag="*",
            payee="Grocery Store",
            narration="Weekly shopping",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(
                    account="Expenses:Food",
                    units=amount.Amount(Decimal("100.00"), "USD"),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
                data.Posting(
                    account="Assets:Checking",
                    units=amount.Amount(Decimal("-100.00"), "USD"),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
            ],
        )

        options_map = {"filename": str(sample_schedule_yaml.parent / "main.bean")}

        result_entries, errors = schedules(
            [existing_txn], options_map, config_file=str(sample_schedule_yaml)
        )

        # Should include existing entry + forecast entries
        assert len(result_entries) > 1
        assert existing_txn in result_entries
        assert len(errors) == 0

    def test_plugin_generates_multiple_months(self, sample_schedule_yaml):
        """Should generate forecasts for multiple months."""
        options_map = {"filename": str(sample_schedule_yaml.parent / "main.bean")}

        result_entries, errors = schedules([], options_map, config_file=str(sample_schedule_yaml))

        # Should generate 12 months of forecasts (1 year)
        forecast_txns = [e for e in result_entries if isinstance(e, data.Transaction)]
        assert len(forecast_txns) >= 12, "Should generate at least 12 monthly forecasts"

        # All should be on day 1 of month
        for txn in forecast_txns:
            assert txn.date.day == 1, "All forecasts should be on day 1"

    def test_plugin_with_bimonthly_schedule(self, tmp_path):
        """Should generate forecasts for bimonthly schedule (multiple days per month)."""
        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(
            """
version: "1.0"
schedules:
  - id: paycheck
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: ".*PAYROLL.*"
    recurrence:
      frequency: MONTHLY_ON_DAYS
      start_date: 2024-01-05
      days_of_month: [5, 20]
    transaction:
      payee: "Employer"
      narration: "Paycheck"
      metadata:
        schedule_id: paycheck
      postings:
        - account: Assets:Checking
          amount: 2500.00
        - account: Income:Salary
          amount: -2500.00
"""
        )

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config_file=str(schedule_yaml))

        # Should generate 2 forecasts per month (5th and 20th)
        forecast_txns = [e for e in result_entries if isinstance(e, data.Transaction)]
        assert len(forecast_txns) >= 24, "Should generate at least 24 forecasts (2 per month)"

        # Check days
        days = {txn.date.day for txn in forecast_txns}
        assert 5 in days
        assert 20 in days

    def test_plugin_with_posting_narrations(self, tmp_path):
        """Should include posting-level narrations in metadata."""
        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(
            """
version: "1.0"
schedules:
  - id: test
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: ".*TEST.*"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    transaction:
      payee: "Test"
      narration: "Test transaction"
      metadata:
        schedule_id: test
      postings:
        - account: Expenses:Test
          amount: 100.00
          narration: "Test expense note"
        - account: Assets:Checking
          narration: "Payment from checking"
"""
        )

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config_file=str(schedule_yaml))

        # Check posting narrations
        forecast_txn = result_entries[0]
        assert forecast_txn.postings[0].meta is not None
        assert forecast_txn.postings[0].meta.get("narration") == "Test expense note"
        assert forecast_txn.postings[1].meta.get("narration") == "Payment from checking"


class TestPluginErrorHandling:
    """Tests for plugin error handling."""

    def test_invalid_yaml_syntax(self, tmp_path):
        """Should handle invalid YAML gracefully."""
        invalid_yaml = tmp_path / "schedules.yaml"
        invalid_yaml.write_text("invalid: yaml: syntax: here:")

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config_file=str(invalid_yaml))

        # Should have errors
        assert len(errors) > 0

    def test_missing_required_fields(self, tmp_path):
        """Should handle missing required fields in schedule."""
        invalid_schedule = tmp_path / "schedules.yaml"
        invalid_schedule.write_text(
            """
version: "1.0"
schedules:
  - id: incomplete
    # Missing enabled, match, recurrence, transaction
"""
        )

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config_file=str(invalid_schedule))

        # Should handle gracefully (pydantic validation will catch it)
        assert len(errors) > 0


class TestPluginWithLedgerFile:
    """Integration tests with actual ledger files."""

    def test_relative_path_resolution(self, tmp_path):
        """Should resolve relative config paths relative to ledger file."""
        # Create subdirectory structure
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        schedule_yaml = config_dir / "schedules.yaml"
        schedule_yaml.write_text(
            """
version: "1.0"
schedules:
  - id: test
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: ".*TEST.*"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    transaction:
      payee: "Test"
      narration: ""
      metadata:
        schedule_id: test
      postings:
        - account: Expenses:Test
          amount: 100.00
        - account: Assets:Checking
"""
        )

        # Simulate ledger file in tmp_path
        options_map = {"filename": str(tmp_path / "main.bean")}

        # Use relative path from ledger location
        result_entries, errors = schedules([], options_map, config_file="config/schedules.yaml")

        # Should resolve correctly and generate forecasts
        assert len(result_entries) > 0
        assert len(errors) == 0
