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


class TestPluginFileMetadata:
    """Tests for filename metadata in forecast transactions."""

    def test_single_file_mode_sets_filename(self, tmp_path, monkeypatch):
        """Should set filename metadata to schedules.yaml for single file mode."""
        import os

        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(
            """
version: "1.0"
schedules:
  - id: test-schedule
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
        schedule_id: test-schedule
      postings:
        - account: Expenses:Test
          amount: 100.00
        - account: Assets:Checking
"""
        )

        # Change to tmp_path so relative path works
        monkeypatch.chdir(tmp_path)

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config_file=str(schedule_yaml))

        # Check filename metadata
        forecast_txn = result_entries[0]
        assert "filename" in forecast_txn.meta
        # Should show relative path from cwd
        assert forecast_txn.meta["filename"] == "schedules.yaml"
        assert forecast_txn.meta["lineno"] == 0

    def test_directory_mode_sets_individual_filenames(self, tmp_path, monkeypatch):
        """Should set filename to individual schedule files in directory mode."""
        import os
        from beanschedule import loader

        # Create schedules directory
        schedules_dir = tmp_path / "schedules"
        schedules_dir.mkdir()

        # Create _config.yaml
        config_yaml = schedules_dir / "_config.yaml"
        config_yaml.write_text(
            """
default_currency: USD
"""
        )

        # Create individual schedule files
        rent_yaml = schedules_dir / "rent-monthly.yaml"
        rent_yaml.write_text(
            """
id: rent-monthly
enabled: true
match:
  account: Assets:Checking
  payee_pattern: ".*LANDLORD.*"
recurrence:
  frequency: MONTHLY
  start_date: 2024-01-01
  day_of_month: 1
transaction:
  payee: "Rent"
  narration: "Monthly rent"
  metadata:
    schedule_id: rent-monthly
  postings:
    - account: Expenses:Housing:Rent
      amount: 1500.00
    - account: Assets:Checking
"""
        )

        paycheck_yaml = schedules_dir / "paycheck.yaml"
        paycheck_yaml.write_text(
            """
id: paycheck
enabled: true
match:
  account: Assets:Checking
  payee_pattern: ".*EMPLOYER.*"
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
"""
        )

        # Change to tmp_path so relative paths work
        monkeypatch.chdir(tmp_path)

        # Mock auto-discovery to find our directory
        monkeypatch.setattr(loader, "find_schedules_location", lambda: ("dir", schedules_dir))

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map)

        # Should have forecasts from both schedules
        assert len(result_entries) > 0
        assert len(errors) == 0

        # Check that different schedules have different source files
        rent_forecasts = [e for e in result_entries if e.meta.get("schedule_id") == "rent-monthly"]
        paycheck_forecasts = [e for e in result_entries if e.meta.get("schedule_id") == "paycheck"]

        assert len(rent_forecasts) > 0
        assert len(paycheck_forecasts) > 0

        # Verify filenames point to individual schedule files
        rent_filename = rent_forecasts[0].meta["filename"]
        paycheck_filename = paycheck_forecasts[0].meta["filename"]

        assert "rent-monthly.yaml" in rent_filename
        assert "paycheck.yaml" in paycheck_filename
        assert rent_filename != paycheck_filename

    def test_filename_respects_display_base_env_var(self, tmp_path, monkeypatch):
        """Should respect BEANSCHEDULE_DISPLAY_BASE for relative paths."""
        import os

        # Create nested structure
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

        # Set base directory env var
        monkeypatch.setenv("BEANSCHEDULE_DISPLAY_BASE", str(tmp_path))

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config_file=str(schedule_yaml))

        # Check filename metadata uses relative path from BEANSCHEDULE_DISPLAY_BASE
        forecast_txn = result_entries[0]
        assert forecast_txn.meta["filename"] == "config/schedules.yaml"


class TestAmortizationRoleValidation:
    """Tests for explicit role validation on amortization schedules."""

    def test_missing_role_raises_helpful_error(self, tmp_path, monkeypatch):
        """Should raise helpful error when role is missing on amortization posting."""
        from beanschedule.plugins.schedules import schedules

        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(
            """
version: "1.0"
schedules:
  - id: mortgage-no-role
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: "MORTGAGE"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    amortization:
      principal: 100000.00
      annual_rate: 0.06
      term_months: 360
      start_date: 2024-01-01
    transaction:
      payee: "Mortgage Company"
      metadata:
        schedule_id: mortgage-no-role
      postings:
        # Missing role fields - should raise error
        - account: Assets:Checking
          amount: null
        - account: Expenses:Mortgage-Interest
          amount: null
        - account: Liabilities:Mortgage
          amount: null
"""
        )

        monkeypatch.chdir(tmp_path)
        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config_file=str(schedule_yaml))

        # Should have error
        assert len(errors) == 1
        error_msg = errors[0]

        # Error message should be helpful
        assert "mortgage-no-role" in error_msg
        assert "role" in error_msg.lower()
        assert "payment" in error_msg
        assert "interest" in error_msg
        assert "principal" in error_msg
        assert "POSTING_ROLES.md" in error_msg


class TestAmortizationWithEscrow:
    """Tests for amortization with fixed escrow amounts."""

    def test_amortization_with_escrow(self, tmp_path, monkeypatch):
        """Should handle amortization with fixed escrow postings."""
        from beanschedule.plugins.schedules import schedules

        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(
            """
version: "1.0"
schedules:
  - id: mortgage-with-escrow
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: "MORTGAGE"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    amortization:
      principal: 100000.00
      annual_rate: 0.06
      term_months: 360
      start_date: 2024-01-01
    transaction:
      payee: "Mortgage Company"
      narration: "Mortgage payment with escrow"
      metadata:
        schedule_id: mortgage-with-escrow
      postings:
        # Payment account - should balance all below
        - account: Assets:Checking
          amount: null
          role: payment
        # Amortized amounts
        - account: Expenses:Mortgage-Interest
          amount: null
          role: interest
        - account: Liabilities:Mortgage
          amount: null
          role: principal
        # Fixed escrow amounts
        - account: Expenses:Property-Tax-Escrow
          amount: 350.00
          role: escrow
        - account: Expenses:Insurance-Escrow
          amount: 125.00
          role: escrow
"""
        )

        monkeypatch.chdir(tmp_path)
        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config_file=str(schedule_yaml))

        assert len(errors) == 0
        assert len(result_entries) > 0

        # Check first forecast transaction
        forecast_txn = result_entries[0]

        # Should have 5 postings
        assert len(forecast_txn.postings) == 5

        # Find postings by account
        postings_by_account = {p.account: p.units.number for p in forecast_txn.postings}

        # Payment account should be negative sum of all others
        checking = postings_by_account["Assets:Checking"]
        interest = postings_by_account["Expenses:Mortgage-Interest"]
        principal = postings_by_account["Liabilities:Mortgage"]
        tax_escrow = postings_by_account["Expenses:Property-Tax-Escrow"]
        insurance_escrow = postings_by_account["Expenses:Insurance-Escrow"]

        # Verify escrow amounts are as specified
        assert tax_escrow == Decimal("350.00")
        assert insurance_escrow == Decimal("125.00")

        # Verify interest and principal are calculated (non-zero, positive)
        assert interest > 0
        assert principal > 0

        # Verify checking account balances everything
        total = interest + principal + tax_escrow + insurance_escrow
        assert checking == -total

        # For a $100k loan at 6%, first payment interest should be around:
        # Interest ≈ $500 (100000 * 0.06 / 12), give or take
        # But the actual first payment will be less since some goes to principal
        assert Decimal("400") < interest < Decimal("510")
        # Total payment should include P+I+Escrow (around $1075)
        assert abs(checking) > Decimal("1000")  # Principal + Interest + Escrow

    def test_amortization_metadata_with_escrow(self, tmp_path, monkeypatch):
        """Should include correct amortization metadata with escrow."""
        from beanschedule.plugins.schedules import schedules

        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(
            """
version: "1.0"
schedules:
  - id: test-mortgage
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: "TEST"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    amortization:
      principal: 50000.00
      annual_rate: 0.05
      term_months: 120
      start_date: 2024-01-01
    transaction:
      payee: "Test"
      metadata:
        schedule_id: test-mortgage
      postings:
        - account: Assets:Checking
          amount: null
          role: payment
        - account: Expenses:Interest
          amount: null
          role: interest
        - account: Liabilities:Loan
          amount: null
          role: principal
        - account: Expenses:Escrow
          amount: 200.00
          role: escrow
"""
        )

        monkeypatch.chdir(tmp_path)
        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config_file=str(schedule_yaml))

        forecast_txn = result_entries[0]

        # Should have amortization metadata
        assert "amortization_payment_number" in forecast_txn.meta
        assert "amortization_balance_after" in forecast_txn.meta
        assert "amortization_principal" in forecast_txn.meta
        assert "amortization_interest" in forecast_txn.meta

        # Payment number will be based on forecast date (today + 1 year)
        # Just verify it's a positive integer
        assert forecast_txn.meta["amortization_payment_number"] > 0


class TestAmortizationOverrides:
    """Tests for amortization overrides functionality.

    NOTE: This feature is partially implemented. The schema and basic structure
    exist, but payment number calculation needs refinement for production use.
    """

    @pytest.mark.skip(reason="Payment number calculation needs refinement")
    def test_override_extra_principal(self, tmp_path, monkeypatch):
        """Should apply extra principal override after effective date."""
        from beanschedule.plugins.schedules import schedules

        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(
            """
version: "1.0"
schedules:
  - id: loan-with-override
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: "LOAN"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    amortization:
      principal: 10000.00
      annual_rate: 0.06
      term_months: 12
      start_date: 2024-01-01
      overrides:
        - effective_date: 2024-07-01
          extra_principal: 200.00
    transaction:
      payee: "Loan Payment"
      metadata:
        schedule_id: loan-with-override
      postings:
        - account: Assets:Checking
          amount: null
          role: payment
        - account: Expenses:Interest
          amount: null
          role: interest
        - account: Liabilities:Loan
          amount: null
          role: principal
"""
        )

        monkeypatch.chdir(tmp_path)
        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config_file=str(schedule_yaml))

        assert len(errors) == 0
        assert len(result_entries) > 0

        # Find January and July forecasts
        jan_forecast = [e for e in result_entries if e.date.month == 1][0]
        jul_forecast = [e for e in result_entries if e.date.month == 7][0]

        # Get principal postings
        jan_principal = [p for p in jan_forecast.postings if "Loan" in p.account][0]
        jul_principal = [p for p in jul_forecast.postings if "Loan" in p.account][0]

        # July payment should be higher due to extra principal
        assert jul_principal.units.number > jan_principal.units.number

    @pytest.mark.skip(reason="Payment number calculation needs refinement")
    def test_override_principal_balance(self, tmp_path, monkeypatch):
        """Should use new principal balance from override."""
        from beanschedule.plugins.schedules import schedules

        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(
            """
version: "1.0"
schedules:
  - id: loan-rebalanced
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: "LOAN"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    amortization:
      principal: 10000.00
      annual_rate: 0.06
      term_months: 12
      start_date: 2024-01-01
      overrides:
        - effective_date: 2024-06-01
          principal: 5000.00
          term_months: 6
    transaction:
      payee: "Loan Payment"
      metadata:
        schedule_id: loan-rebalanced
      postings:
        - account: Assets:Checking
          amount: null
          role: payment
        - account: Expenses:Interest
          amount: null
          role: interest
        - account: Liabilities:Loan
          amount: null
          role: principal
"""
        )

        monkeypatch.chdir(tmp_path)
        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config_file=str(schedule_yaml))

        assert len(errors) == 0
        assert len(result_entries) > 0

        # Find June forecast (after override)
        jun_forecast = [e for e in result_entries if e.date.month == 6][0]

        # Check that principal amount reflects new balance
        principal_posting = [p for p in jun_forecast.postings if "Loan" in p.account][0]
        # With 5000 balance and 6 months remaining, principal should be higher per payment
        assert principal_posting.units.number > Decimal("700")

    @pytest.mark.skip(reason="Payment number calculation needs refinement")
    def test_multiple_overrides(self, tmp_path, monkeypatch):
        """Should apply the most recent override."""
        from beanschedule.plugins.schedules import schedules

        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(
            """
version: "1.0"
schedules:
  - id: loan-multi-override
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: "LOAN"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    amortization:
      principal: 10000.00
      annual_rate: 0.06
      term_months: 12
      start_date: 2024-01-01
      overrides:
        - effective_date: 2024-04-01
          extra_principal: 100.00
        - effective_date: 2024-08-01
          extra_principal: 300.00
    transaction:
      payee: "Loan Payment"
      metadata:
        schedule_id: loan-multi-override
      postings:
        - account: Assets:Checking
          amount: null
          role: payment
        - account: Expenses:Interest
          amount: null
          role: interest
        - account: Liabilities:Loan
          amount: null
          role: principal
"""
        )

        monkeypatch.chdir(tmp_path)
        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules([], options_map, config_file=str(schedule_yaml))

        assert len(errors) == 0

        # Get forecasts for different months
        jan_forecast = [e for e in result_entries if e.date.month == 1][0]
        may_forecast = [e for e in result_entries if e.date.month == 5][0]
        sep_forecast = [e for e in result_entries if e.date.month == 9][0]

        jan_principal = [p for p in jan_forecast.postings if "Loan" in p.account][0]
        may_principal = [p for p in may_forecast.postings if "Loan" in p.account][0]
        sep_principal = [p for p in sep_forecast.postings if "Loan" in p.account][0]

        # May should have more principal than Jan (100 extra)
        # Sep should have more principal than May (300 extra)
        assert may_principal.units.number > jan_principal.units.number
        assert sep_principal.units.number > may_principal.units.number


class TestStatefulAmortization:
    """Integration tests for balance_from_ledger stateful amortization mode.

    Test loan: $10 000 at 6 % annual, $200/month payment.
    Three cleared payments have been made; the liability account balance
    after those payments is $9 547.75.  All forecasts are verified against
    that known starting point.
    """

    # ── constants ─────────────────────────────────────────────────────────
    ORIGINATION = Decimal("10000.00")
    RATE = Decimal("0.06")
    PAYMENT = Decimal("200.00")
    LIABILITY_ACCOUNT = "Liabilities:Loan"

    # Payments already in the ledger: (date, principal_portion)
    # Pmt 1: interest = 10000 * 0.005 = 50.00   → principal 150.00
    # Pmt 2: interest =  9850 * 0.005 = 49.25   → principal 150.75
    # Pmt 3: interest = 9699.25 * 0.005 = 48.50 → principal 151.50
    PAYMENTS = [
        (date(2025, 11, 4), Decimal("150.00")),
        (date(2025, 12, 4), Decimal("150.75")),
        (date(2026, 1, 4), Decimal("151.50")),
    ]
    # 10000 - 150 - 150.75 - 151.50
    BALANCE_AFTER_3 = Decimal("9547.75")

    # ── helpers ───────────────────────────────────────────────────────────

    def _make_ledger_entries(self, extra_entries=None):
        """Return origination + 3 cleared payment entries."""
        entries = []

        # Origination
        entries.append(
            data.Transaction(
                meta={"filename": "test", "lineno": 1},
                date=date(2025, 10, 1),
                flag="*",
                payee="Bank",
                narration="Loan origination",
                tags=frozenset(),
                links=frozenset(),
                postings=[
                    data.Posting(
                        "Assets:Checking",
                        amount.Amount(self.ORIGINATION, "USD"),
                        None,
                        None,
                        None,
                        None,
                    ),
                    data.Posting(
                        self.LIABILITY_ACCOUNT,
                        amount.Amount(-self.ORIGINATION, "USD"),
                        None,
                        None,
                        None,
                        None,
                    ),
                ],
            )
        )

        # Monthly payments
        for pmt_date, principal in self.PAYMENTS:
            interest_amt = self.PAYMENT - principal
            entries.append(
                data.Transaction(
                    meta={"filename": "test", "lineno": 2},
                    date=pmt_date,
                    flag="*",
                    payee="Loan Company",
                    narration="Payment",
                    tags=frozenset(),
                    links=frozenset(),
                    postings=[
                        data.Posting(
                            "Assets:Checking",
                            amount.Amount(-self.PAYMENT, "USD"),
                            None,
                            None,
                            None,
                            None,
                        ),
                        data.Posting(
                            "Expenses:Interest",
                            amount.Amount(interest_amt, "USD"),
                            None,
                            None,
                            None,
                            None,
                        ),
                        data.Posting(
                            self.LIABILITY_ACCOUNT,
                            amount.Amount(principal, "USD"),
                            None,
                            None,
                            None,
                            None,
                        ),
                    ],
                )
            )

        if extra_entries:
            entries.extend(extra_entries)
        return entries

    def _schedule_yaml(self, compounding="MONTHLY", extra_principal=None):
        """Build schedule YAML string for the test loan."""
        lines = [
            'version: "1.0"',
            "schedules:",
            "  - id: test-loan",
            "    enabled: true",
            "    match:",
            "      account: Assets:Checking",
            '      payee_pattern: "LOAN"',
            "    recurrence:",
            "      frequency: MONTHLY",
            "      start_date: 2020-01-01",
            "      day_of_month: 4",
            "    amortization:",
            "      annual_rate: 0.06",
            "      balance_from_ledger: true",
            "      monthly_payment: 200.00",
            f"      compounding: {compounding}",
        ]
        if extra_principal is not None:
            lines.append(f"      extra_principal: {extra_principal}")
        lines.extend(
            [
                "    transaction:",
                '      payee: "Loan Payment"',
                '      narration: "Monthly loan payment"',
                "      metadata:",
                "        schedule_id: test-loan",
                "      postings:",
                "        - account: Assets:Checking",
                "          amount: null",
                "          role: payment",
                "        - account: Expenses:Interest",
                "          amount: null",
                "          role: interest",
                f"        - account: {self.LIABILITY_ACCOUNT}",
                "          amount: null",
                "          role: principal",
            ]
        )
        return "\n".join(lines)

    # ── tests ─────────────────────────────────────────────────────────────

    def test_stateful_monthly_compounding(self, tmp_path, monkeypatch):
        """Should derive P/I from actual ledger balance, not original terms."""
        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(self._schedule_yaml("MONTHLY"))
        monkeypatch.chdir(tmp_path)

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules(
            self._make_ledger_entries(), options_map, config_file=str(schedule_yaml)
        )

        assert len(errors) == 0
        forecasts = [e for e in result_entries if isinstance(e, data.Transaction) and e.flag == "#"]
        assert len(forecasts) > 0

        # ── first forecast: 2026-02-04 ────────────────────────────────────
        first = forecasts[0]
        assert first.date == date(2026, 2, 4)

        postings = {p.account: p.units.number for p in first.postings}
        # interest = 9547.75 × 0.005 = 47.73875 → 47.74
        assert postings["Expenses:Interest"] == Decimal("47.74")
        # principal = 200 − 47.74 = 152.26
        assert postings[self.LIABILITY_ACCOUNT] == Decimal("152.26")
        # payment balances everything
        assert postings["Assets:Checking"] == Decimal("-200.00")

        # metadata
        assert first.meta["amortization_balance_after"] == "9395.49"
        assert first.meta["amortization_interest"] == "47.74"
        assert first.meta["amortization_principal"] == "152.26"
        # payment_number is not emitted in stateful mode
        assert "amortization_payment_number" not in first.meta

        # ── second forecast: 2026-03-04 (balance carries forward) ─────────
        second = forecasts[1]
        assert second.date == date(2026, 3, 4)
        postings2 = {p.account: p.units.number for p in second.postings}
        # interest = 9395.49 × 0.005 = 46.97745 → 46.98
        assert postings2["Expenses:Interest"] == Decimal("46.98")
        # principal = 200 − 46.98 = 153.02
        assert postings2[self.LIABILITY_ACCOUNT] == Decimal("153.02")

    def test_stateful_daily_compounding(self, tmp_path, monkeypatch):
        """Daily compounding should use actual days between payment dates."""
        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(self._schedule_yaml("DAILY"))
        monkeypatch.chdir(tmp_path)

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules(
            self._make_ledger_entries(), options_map, config_file=str(schedule_yaml)
        )
        assert len(errors) == 0

        forecasts = [e for e in result_entries if isinstance(e, data.Transaction) and e.flag == "#"]
        first = forecasts[0]
        assert first.date == date(2026, 2, 4)

        postings = {p.account: p.units.number for p in first.postings}

        # 2026-01-04 → 2026-02-04 = 31 days
        expected_interest = (
            self.BALANCE_AFTER_3 * Decimal("0.06") / Decimal("365") * Decimal("31")
        ).quantize(Decimal("0.01"))
        expected_principal = self.PAYMENT - expected_interest

        assert postings["Expenses:Interest"] == expected_interest
        assert postings[self.LIABILITY_ACCOUNT] == expected_principal
        assert postings["Assets:Checking"] == -self.PAYMENT

        # 31-day month produces more interest than monthly (47.74)
        assert expected_interest > Decimal("47.74")

    def test_stateful_with_extra_principal(self, tmp_path, monkeypatch):
        """Extra principal should increase principal posting and total payment."""
        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(self._schedule_yaml("MONTHLY", extra_principal="50.00"))
        monkeypatch.chdir(tmp_path)

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules(
            self._make_ledger_entries(), options_map, config_file=str(schedule_yaml)
        )
        assert len(errors) == 0

        forecasts = [e for e in result_entries if isinstance(e, data.Transaction) and e.flag == "#"]
        first = forecasts[0]
        postings = {p.account: p.units.number for p in first.postings}

        # Interest is unchanged: 47.74
        assert postings["Expenses:Interest"] == Decimal("47.74")
        # Principal = (200 − 47.74) + 50 = 202.26
        assert postings[self.LIABILITY_ACCOUNT] == Decimal("202.26")
        # Total out of pocket = 200 + 50 = 250
        assert postings["Assets:Checking"] == Decimal("-250.00")
        # Balance = 9547.75 − 202.26 = 9345.49
        assert first.meta["amortization_balance_after"] == "9345.49"

    def test_stateful_excludes_non_cleared_transactions(self, tmp_path, monkeypatch):
        """Forecast (#) and placeholder (!) postings must not affect the balance."""
        # A forecast transaction that posts to the liability — should be invisible
        phantom = data.Transaction(
            meta={"filename": "test", "lineno": 99},
            date=date(2026, 1, 15),
            flag="#",
            payee="Phantom",
            narration="Old forecast",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(
                    "Assets:Checking",
                    amount.Amount(Decimal("-200.00"), "USD"),
                    None,
                    None,
                    None,
                    None,
                ),
                data.Posting(
                    self.LIABILITY_ACCOUNT,
                    amount.Amount(Decimal("500.00"), "USD"),  # would lower balance if counted
                    None,
                    None,
                    None,
                    None,
                ),
            ],
        )

        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(self._schedule_yaml("MONTHLY"))
        monkeypatch.chdir(tmp_path)

        options_map = {"filename": str(tmp_path / "main.bean")}
        result_entries, errors = schedules(
            self._make_ledger_entries(extra_entries=[phantom]),
            options_map,
            config_file=str(schedule_yaml),
        )
        assert len(errors) == 0

        # First real forecast should still use 9547.75, not 9047.75
        forecasts = [
            e
            for e in result_entries
            if isinstance(e, data.Transaction)
            and e.flag == "#"
            and e.meta.get("schedule_id") == "test-loan"
        ]
        assert forecasts[0].meta["amortization_interest"] == "47.74"

    def test_stateful_no_cleared_transactions_skips_schedule(self, tmp_path, monkeypatch):
        """Schedule should be silently skipped when liability has no cleared postings."""
        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(self._schedule_yaml("MONTHLY"))
        monkeypatch.chdir(tmp_path)

        options_map = {"filename": str(tmp_path / "main.bean")}
        # Only a forecast entry — no cleared (*) transactions at all
        phantom = data.Transaction(
            meta={"filename": "test", "lineno": 1},
            date=date(2026, 1, 4),
            flag="#",
            payee="Forecast",
            narration="Old forecast",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(
                    self.LIABILITY_ACCOUNT,
                    amount.Amount(Decimal("100.00"), "USD"),
                    None,
                    None,
                    None,
                    None,
                ),
            ],
        )

        result_entries, errors = schedules([phantom], options_map, config_file=str(schedule_yaml))
        # No hard errors — just a warning log and skip
        assert len(errors) == 0
        # No new forecasts generated for this schedule
        new_forecasts = [
            e
            for e in result_entries
            if isinstance(e, data.Transaction) and e.meta.get("schedule_id") == "test-loan"
        ]
        assert len(new_forecasts) == 0
